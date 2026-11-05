"""Interactive Brokers through a local IB Gateway / TWS (ib_async).

The day-trader skills write orders in Alpaca's place_stock_order shape;
`plan_orders` turns one into IBKR order specs, `Gateway` sends them.

Safety rails, on top of the trader-risk / yes / Allow once gates:
- paper by default (IB Gateway paper port 4002);
- live needs IBKR_MODE=live AND IBKR_ALLOW_LIVE=yes, and a live port;
- in paper mode, orders are refused unless the account id is a paper one (D...);
- US stocks only, whole shares, no shorting past the position held.
"""

import asyncio
import contextlib
import math
import os
from dataclasses import dataclass, field
from typing import Any

PAPER_PORTS = {4002, 7497}
LIVE_PORTS = {4001, 7496}
TIF = {"day": "DAY", "gtc": "GTC", "ioc": "IOC", "fok": "FOK", "opg": "OPG"}


class BrokerError(RuntimeError):
    """An order or a connection was refused."""


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 4002
    client_id: int = 17
    account: str = ""
    mode: str = "paper"
    allow_live: bool = False
    allow_short: bool = False
    max_order_usd: float | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        mode = env.get("IBKR_MODE", "paper").strip().lower()
        default_port = 4001 if mode == "live" else 4002
        cap = env.get("IBKR_MAX_ORDER_USD")
        return cls(
            host=env.get("IBKR_HOST", "127.0.0.1"),
            port=int(env.get("IBKR_PORT") or default_port),
            client_id=int(env.get("IBKR_CLIENT_ID", "17")),
            account=env.get("IBKR_ACCOUNT", "").strip(),
            mode=mode,
            allow_live=env.get("IBKR_ALLOW_LIVE", "").strip().lower()
            in ("1", "yes", "true"),
            allow_short=env.get("IBKR_ALLOW_SHORT", "").strip().lower()
            in ("1", "yes", "true"),
            max_order_usd=float(cap) if cap else None,
        )

    def check(self) -> None:
        if self.mode not in ("paper", "live"):
            raise BrokerError(f"IBKR_MODE must be paper or live, not {self.mode!r}")
        if self.mode == "paper" and self.port in LIVE_PORTS:
            raise BrokerError(
                f"paper mode on live port {self.port}: use 4002 (Gateway) or 7497 (TWS)"
            )
        if self.mode == "live":
            if not self.allow_live:
                raise BrokerError("live mode needs IBKR_ALLOW_LIVE=yes as well")
            if self.port in PAPER_PORTS:
                raise BrokerError(
                    f"live mode on paper port {self.port}: use 4001 (Gateway) or 7496 (TWS)"
                )


@dataclass
class OrderSpec:
    """One IBKR order, before ib_async objects exist (pure, testable)."""

    role: str  # parent | take_profit | stop_loss | single
    action: str  # BUY | SELL
    qty: int
    order_type: str  # MKT | LMT | STP | STP LMT
    tif: str
    lmt_price: float | None = None
    aux_price: float | None = None
    transmit: bool = True
    extra: dict = field(default_factory=dict)


def _num(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise BrokerError(f"{name} must be a number, got {value!r}") from None
    if out <= 0:
        raise BrokerError(f"{name} must be positive, got {value!r}")
    return out


def plan_orders(order: dict) -> tuple[str, list[OrderSpec]]:
    """Translate an Alpaca-shaped place_stock_order input to IBKR order specs."""
    symbol = str(order.get("symbol", "")).strip().upper()
    if not symbol or not symbol.replace(".", "").replace("-", "").isalnum():
        raise BrokerError(f"bad symbol {order.get('symbol')!r}")
    if order.get("notional") is not None:
        raise BrokerError(
            "notional orders are not supported on IBKR here: give qty in whole shares"
        )
    for unsupported in ("trail_price", "trail_percent", "advanced_instructions"):
        if order.get(unsupported) is not None:
            raise BrokerError(f"{unsupported} is not supported")
    side = str(order.get("side", "")).lower()
    if side not in ("buy", "sell"):
        raise BrokerError(f"side must be buy or sell, got {order.get('side')!r}")
    qty_f = _num(order.get("qty"), "qty")
    if qty_f != int(qty_f):
        raise BrokerError("whole shares only")
    qty = int(qty_f)
    tif = TIF.get(str(order.get("time_in_force", "day")).lower())
    if not tif:
        raise BrokerError(
            f"time_in_force {order.get('time_in_force')!r} is not supported"
        )
    kind = str(order.get("type", "market")).lower()
    action = side.upper()
    exit_action = "SELL" if action == "BUY" else "BUY"
    extra = {"outsideRth": bool(order.get("extended_hours"))}
    if order.get("client_order_id"):
        extra["orderRef"] = str(order["client_order_id"])[:40]

    if kind == "market":
        entry = OrderSpec("parent", action, qty, "MKT", tif, extra=extra)
    elif kind == "limit":
        entry = OrderSpec(
            "parent",
            action,
            qty,
            "LMT",
            tif,
            lmt_price=_num(order.get("limit_price"), "limit_price"),
            extra=extra,
        )
    elif kind == "stop":
        entry = OrderSpec(
            "parent",
            action,
            qty,
            "STP",
            tif,
            aux_price=_num(order.get("stop_price"), "stop_price"),
            extra=extra,
        )
    elif kind == "stop_limit":
        entry = OrderSpec(
            "parent",
            action,
            qty,
            "STP LMT",
            tif,
            lmt_price=_num(order.get("limit_price"), "limit_price"),
            aux_price=_num(order.get("stop_price"), "stop_price"),
            extra=extra,
        )
    else:
        raise BrokerError(f"order type {kind!r} is not supported")

    order_class = str(order.get("order_class") or "simple").lower()
    if order_class in ("simple", ""):
        entry.role = "single"
        return symbol, [entry]
    if order_class != "bracket":
        raise BrokerError(
            f"order_class {order_class!r} is not supported (simple or bracket)"
        )

    tp = _num(order.get("take_profit_limit_price"), "take_profit_limit_price")
    sl = _num(order.get("stop_loss_stop_price"), "stop_loss_stop_price")
    ref = entry.lmt_price or entry.aux_price
    if action == "BUY" and not sl < tp:
        raise BrokerError("a buy bracket needs stop-loss below take-profit")
    if action == "SELL" and not tp < sl:
        raise BrokerError("a sell bracket needs take-profit below stop-loss")
    if ref and action == "BUY" and not sl < ref < tp:
        raise BrokerError("a buy bracket needs stop-loss < entry < take-profit")
    if ref and action == "SELL" and not tp < ref < sl:
        raise BrokerError("a sell bracket needs take-profit < entry < stop-loss")
    entry.transmit = False
    take = OrderSpec(
        "take_profit",
        exit_action,
        qty,
        "LMT",
        tif,
        lmt_price=tp,
        transmit=False,
        extra=dict(extra),
    )
    if order.get("stop_loss_limit_price") is not None:
        stop = OrderSpec(
            "stop_loss",
            exit_action,
            qty,
            "STP LMT",
            tif,
            lmt_price=_num(order.get("stop_loss_limit_price"), "stop_loss_limit_price"),
            aux_price=sl,
            transmit=True,
            extra=dict(extra),
        )
    else:
        stop = OrderSpec(
            "stop_loss",
            exit_action,
            qty,
            "STP",
            tif,
            aux_price=sl,
            transmit=True,
            extra=dict(extra),
        )
    return symbol, [entry, take, stop]


def _require_ib():
    try:
        import ib_async  # noqa: PLC0415
    except ImportError as exc:
        raise BrokerError(
            "ib_async is not installed: pip install -e openbb_platform/extensions/daytrader[ibkr]"
        ) from exc
    return ib_async


DONE = {"Filled", "Cancelled", "ApiCancelled", "Inactive"}


def _price(*values) -> float | None:
    for v in values:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if not math.isnan(f) and f > 0:
            return f
    return None


class Gateway:
    """A lazily connected ib_async session, reconnected if the event loop changes."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        self.ib = None
        self._loop = None
        self._lock = None

    async def connect(self):
        self.settings.check()
        ib_async = _require_ib()
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            # OpenBB's Python interface may run each call on a fresh loop.
            if self.ib is not None:
                with contextlib.suppress(Exception):
                    self.ib.disconnect()
            self.ib, self._loop, self._lock = None, loop, asyncio.Lock()
        async with self._lock:
            if self.ib is not None and self.ib.isConnected():
                return self.ib
            ib = ib_async.IB()
            s = self.settings
            try:
                await ib.connectAsync(
                    s.host, s.port, clientId=s.client_id, timeout=10, account=s.account
                )
            except Exception as exc:  # noqa: BLE001
                raise BrokerError(
                    f"cannot reach IB Gateway/TWS at {s.host}:{s.port} with client id "
                    f"{s.client_id} ({exc!r}). Start IB Gateway, log in to the PAPER "
                    "account, untick Read-Only API; if the client id is in use, close "
                    "the other desk window or set IBKR_CLIENT_ID."
                ) from exc
            ib.reqMarketDataType(3)
            self.ib = ib
            return ib

    def account_id(self, ib) -> str:
        if self.settings.account:
            return self.settings.account
        accounts = ib.managedAccounts()
        if not accounts:
            raise BrokerError("IB Gateway reports no account")
        return accounts[0]

    def guard_account(self, account: str) -> None:
        paper_id = account.upper().startswith("D")
        if self.settings.mode == "paper" and not paper_id:
            raise BrokerError(
                f"paper mode but {account} is not a paper account (D...): refused"
            )
        if self.settings.mode == "live" and paper_id:
            raise BrokerError(
                f"live mode but {account} is a paper account: check IBKR_PORT"
            )

    async def account(self) -> dict:
        ib = await self.connect()
        acct = self.account_id(ib)
        tags = (
            "NetLiquidation",
            "TotalCashValue",
            "AvailableFunds",
            "BuyingPower",
            "GrossPositionValue",
            "UnrealizedPnL",
            "RealizedPnL",
        )
        rows = await ib.accountSummaryAsync(acct)
        out: dict[str, Any] = {
            "account": acct,
            "mode": self.settings.mode,
            "paper": acct.upper().startswith("D"),
        }
        for v in rows:
            # one row per tag, in the account's base currency (skip per-currency rows)
            if v.tag in tags and v.tag not in out and v.currency != "BASE":
                out[v.tag] = v.value
                out.setdefault("currency", v.currency)
        return out

    async def positions(self) -> list[dict]:
        ib = await self.connect()
        acct = self.account_id(ib)
        return [
            {
                "account": p.account,
                "symbol": p.contract.symbol,
                "sec_type": p.contract.secType,
                "currency": p.contract.currency,
                "qty": float(p.position),
                "avg_cost": p.avgCost,
            }
            for p in ib.positions(acct)
        ]

    async def position(self, symbol: str) -> dict:
        ib = await self.connect()
        contract = await self._contract(ib, symbol.upper())
        held = self._held(ib, self.account_id(ib), contract)
        return {"symbol": symbol.upper(), "qty": held, "sec_type": "STK"}

    async def _open_trades(self, ib, contract=None) -> list:
        trades = await ib.reqAllOpenOrdersAsync()
        return [
            t
            for t in trades or []
            if t.orderStatus.status not in DONE
            and (contract is None or t.contract.conId == contract.conId)
        ]

    async def open_orders(self) -> list[dict]:
        ib = await self.connect()
        return [
            {
                "order_id": t.order.orderId,
                "parent_id": t.order.parentId,
                "client_id": t.order.clientId,
                "symbol": t.contract.symbol,
                "action": t.order.action,
                "qty": float(t.order.totalQuantity),
                "type": t.order.orderType,
                "lmt_price": t.order.lmtPrice,
                "aux_price": t.order.auxPrice,
                "tif": t.order.tif,
                "status": t.orderStatus.status,
                "filled": float(t.orderStatus.filled),
            }
            for t in await self._open_trades(ib)
        ]

    async def _contract(self, ib, symbol: str):
        ib_async = _require_ib()
        contract = ib_async.Stock(symbol, "SMART", "USD")
        qualified = await ib.qualifyContractsAsync(contract)
        if not qualified or not getattr(qualified[0], "conId", 0):
            raise BrokerError(f"IBKR does not know the US stock {symbol}")
        return qualified[0]

    @staticmethod
    def _held(ib, acct: str, contract) -> float:
        """Shares held of exactly this stock (options with the same symbol excluded)."""
        return sum(
            float(p.position)
            for p in ib.positions(acct)
            if p.contract.secType == "STK" and p.contract.conId == contract.conId
        )

    async def quote(self, symbols: list[str]) -> list[dict]:
        ib = await self.connect()
        contracts = [await self._contract(ib, s.upper()) for s in symbols]
        tickers = await ib.reqTickersAsync(*contracts)
        return [
            {
                "symbol": t.contract.symbol,
                "last": t.last,
                "bid": t.bid,
                "ask": t.ask,
                "close": t.close,
                "market_price": t.marketPrice(),
                "time": str(t.time),
            }
            for t in tickers
        ]

    async def _reference_price(self, ib, contract, entry, specs) -> float | None:
        ref = _price(entry.lmt_price, entry.aux_price)
        if ref:
            return ref
        try:
            (t,) = await asyncio.wait_for(ib.reqTickersAsync(contract), 15)
            ref = _price(t.ask if entry.action == "BUY" else t.bid, t.last, t.close)
        except Exception:  # noqa: BLE001
            ref = None
        if ref:
            return ref
        # bracket without a quote: the take-profit bounds a buy's fill from above
        return _price(*(s.lmt_price for s in specs[1:] if s.role == "take_profit"))

    async def place(self, order: dict, closing: bool = False) -> dict:
        symbol, specs = plan_orders(order)
        ib = await self.connect()
        acct = self.account_id(ib)
        self.guard_account(acct)
        entry = specs[0]
        contract = await self._contract(ib, symbol)
        held = self._held(ib, acct, contract)
        if entry.action == "SELL" and not self.settings.allow_short:
            pending = sum(
                float(t.order.totalQuantity) - float(t.orderStatus.filled)
                for t in await self._open_trades(ib, contract)
                if t.order.action == "SELL"
            )
            if entry.qty + pending > held:
                raise BrokerError(
                    f"selling {entry.qty} {symbol}: you hold {held:g} and {pending:g} are "
                    "already in open sell orders (bracket legs?). Cancel them first "
                    "(get_orders, cancel_order_by_id): no short sales"
                )
        cap = self.settings.max_order_usd
        if cap and not closing:
            ref = await self._reference_price(ib, contract, entry, specs)
            if not ref:
                raise BrokerError(
                    f"no price for {symbol} to check IBKR_MAX_ORDER_USD: use a limit order"
                )
            if entry.qty * ref > cap:
                raise BrokerError(
                    f"order value about {entry.qty * ref:.2f} is over IBKR_MAX_ORDER_USD {cap}"
                )
        ib_async = _require_ib()
        parent_id = ib.client.getReqId()
        trades = []
        for spec in specs:
            o = ib_async.Order(
                orderId=parent_id
                if spec.role in ("parent", "single")
                else ib.client.getReqId(),
                action=spec.action,
                totalQuantity=spec.qty,
                orderType=spec.order_type,
                tif=spec.tif,
                transmit=spec.transmit,
                account=acct,
                **spec.extra,
            )
            if spec.lmt_price is not None:
                o.lmtPrice = spec.lmt_price
            if spec.aux_price is not None:
                o.auxPrice = spec.aux_price
            if spec.role in ("take_profit", "stop_loss"):
                o.parentId = parent_id
            trades.append((spec.role, ib.placeOrder(contract, o)))
        await asyncio.sleep(2)
        return {
            "account": acct,
            "paper": acct.upper().startswith("D"),
            "symbol": symbol,
            "orders": [
                {
                    "role": role,
                    "order_id": t.order.orderId,
                    "status": t.orderStatus.status,
                    "filled": float(t.orderStatus.filled),
                    "avg_fill_price": t.orderStatus.avgFillPrice,
                    "log": [e.message for e in t.log if e.message][-3:],
                }
                for role, t in trades
            ],
        }

    async def _cancel_trade(self, ib, trade, wait: float = 5.0) -> str:
        own = self.settings.client_id
        if trade.order.clientId not in (own, 0):
            raise BrokerError(
                f"order {trade.order.orderId} belongs to API client {trade.order.clientId}"
                " (or TWS): cancel it there"
            )
        ib.cancelOrder(trade.order)
        end = asyncio.get_running_loop().time() + wait
        while trade.orderStatus.status not in DONE:
            if asyncio.get_running_loop().time() > end:
                break
            await asyncio.sleep(0.25)
        return trade.orderStatus.status

    async def cancel(self, order_id: int) -> dict:
        ib = await self.connect()
        self.guard_account(self.account_id(ib))
        for t in await self._open_trades(ib):
            if t.order.orderId == int(order_id):
                status = await self._cancel_trade(ib, t)
                return {
                    "order_id": int(order_id),
                    "status": status,
                    "cancelled": status in DONE,
                }
        raise BrokerError(f"no open order {order_id}")

    async def close_position(self, symbol: str, qty: float | None = None) -> dict:
        ib = await self.connect()
        acct = self.account_id(ib)
        self.guard_account(acct)
        symbol = symbol.upper()
        contract = await self._contract(ib, symbol)
        held = self._held(ib, acct, contract)
        if not held:
            raise BrokerError(f"no {symbol} position")
        size = abs(held) if qty is None else float(qty)
        if size != int(size) or size <= 0:
            raise BrokerError(f"close a whole number of shares, not {size:g}")
        if size > abs(held):
            raise BrokerError(f"closing {size:g} but the position is {held:g}")
        side = "sell" if held > 0 else "buy"
        # the bracket's legs would sell the same shares again: cancel them first
        cancelled = []
        for t in await self._open_trades(ib, contract):
            if t.order.action == side.upper():
                status = await self._cancel_trade(ib, t)
                if status not in DONE:
                    raise BrokerError(
                        f"order {t.order.orderId} did not cancel ({status}): not closing"
                    )
                cancelled.append(t.order.orderId)
        out = await self.place(
            {
                "symbol": symbol,
                "side": side,
                "qty": str(int(size)),
                "type": "market",
                "time_in_force": "day",
            },
            closing=True,
        )
        out["cancelled_first"] = cancelled
        return out
