"""IBKR translation, safety rails and MCP server (no IB Gateway needed)."""

import asyncio
from types import SimpleNamespace

import pytest

from openbb_daytrader import ibkr
from openbb_daytrader.ibkr import BrokerError, Gateway, Settings, plan_orders

TSLA = {
    "symbol": "TSLA",
    "side": "buy",
    "qty": "8",
    "type": "market",
    "time_in_force": "day",
    "order_class": "bracket",
    "take_profit_limit_price": "370.04",
    "stop_loss_stop_price": "358.32",
}


def test_bracket_market_entry():
    symbol, specs = plan_orders(TSLA)
    assert symbol == "TSLA"
    parent, take, stop = specs
    assert (parent.order_type, parent.action, parent.qty, parent.transmit) == (
        "MKT",
        "BUY",
        8,
        False,
    )
    assert (take.order_type, take.action, take.lmt_price, take.transmit) == (
        "LMT",
        "SELL",
        370.04,
        False,
    )
    assert (stop.order_type, stop.action, stop.aux_price, stop.transmit) == (
        "STP",
        "SELL",
        358.32,
        True,
    )
    assert {s.tif for s in specs} == {"DAY"}


def test_simple_limit_and_sell():
    _, (o,) = plan_orders(
        {
            "symbol": "aapl",
            "side": "sell",
            "qty": 3,
            "type": "limit",
            "limit_price": "200",
            "time_in_force": "gtc",
        }
    )
    assert (o.role, o.action, o.order_type, o.lmt_price, o.tif, o.transmit) == (
        "single",
        "SELL",
        "LMT",
        200.0,
        "GTC",
        True,
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"qty": "1.5"},
        {"qty": "0"},
        {"notional": "100"},
        {"side": "short"},
        {"type": "trailing_stop"},
        {"order_class": "oco"},
        {"stop_loss_stop_price": "371"},
        {"symbol": "TSLA; rm"},
        {"time_in_force": "cls"},
    ],
)
def test_refusals(bad):
    with pytest.raises(BrokerError):
        plan_orders({**TSLA, **bad})


def test_limit_bracket_must_straddle_entry():
    with pytest.raises(BrokerError):
        plan_orders({**TSLA, "type": "limit", "limit_price": "357"})


def test_settings(monkeypatch):
    for k in ("IBKR_MODE", "IBKR_PORT", "IBKR_ALLOW_LIVE"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env()
    assert (s.mode, s.port) == ("paper", 4002)
    s.check()
    monkeypatch.setenv("IBKR_MODE", "live")
    with pytest.raises(BrokerError, match="IBKR_ALLOW_LIVE"):
        Settings.from_env().check()
    monkeypatch.setenv("IBKR_ALLOW_LIVE", "yes")
    s = Settings.from_env()
    assert s.port == 4001
    s.check()
    monkeypatch.setenv("IBKR_PORT", "4002")
    with pytest.raises(BrokerError, match="paper port"):
        Settings.from_env().check()
    monkeypatch.setenv("IBKR_MODE", "paper")
    monkeypatch.setenv("IBKR_PORT", "7496")
    with pytest.raises(BrokerError, match="live port"):
        Settings.from_env().check()


class FakeIB:
    def __init__(self, account="DU123", held=0.0, open_sells=0, price=364.0):
        self.account, self.held, self.placed, self.cancelled = account, held, [], []
        self.price = price
        self.client = SimpleNamespace(getReqId=iter(range(100, 200)).__next__)
        self.trades = []
        if open_sells:
            self._add_trade("SELL", open_sells, client_id=17)

    def _add_trade(self, action, qty, client_id=17):
        order = SimpleNamespace(
            orderId=50 + len(self.trades),
            action=action,
            totalQuantity=qty,
            clientId=client_id,
        )
        self.trades.append(
            SimpleNamespace(
                order=order,
                contract=SimpleNamespace(conId=1, symbol="TSLA"),
                orderStatus=SimpleNamespace(status="Submitted", filled=0),
            )
        )

    def isConnected(self):
        return True

    def managedAccounts(self):
        return [self.account]

    def positions(self, account=""):
        stock = SimpleNamespace(symbol="TSLA", secType="STK", currency="USD", conId=1)
        option = SimpleNamespace(symbol="TSLA", secType="OPT", currency="USD", conId=9)
        rows = [
            SimpleNamespace(
                account=self.account, contract=option, position=50, avgCost=1
            )
        ]
        if self.held:
            rows.append(
                SimpleNamespace(
                    account=self.account, contract=stock, position=self.held, avgCost=1
                )
            )
        return rows

    async def qualifyContractsAsync(self, c):
        c.conId = 1
        return [c]

    async def reqAllOpenOrdersAsync(self):
        return list(self.trades)

    async def reqTickersAsync(self, *contracts):
        return [
            SimpleNamespace(
                ask=self.price, bid=self.price, last=self.price, close=self.price
            )
        ]

    def cancelOrder(self, order):
        self.cancelled.append(order.orderId)
        for t in self.trades:
            if t.order is order:
                t.orderStatus.status = "Cancelled"

    def placeOrder(self, contract, order):
        self.placed.append(order)
        return SimpleNamespace(
            order=order,
            log=[],
            orderStatus=SimpleNamespace(status="Submitted", filled=0, avgFillPrice=0),
        )


def _gateway(fake, mode="paper", **kw):
    pytest.importorskip("ib_async")
    gw = Gateway(
        Settings(
            mode=mode, allow_live=True, port=4001 if mode == "live" else 4002, **kw
        )
    )
    gw.ib = fake

    async def connect():
        return fake

    gw.connect = connect
    return gw


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(ibkr.asyncio, "sleep", lambda s: real_sleep(0))


def test_place_bracket():
    fake = FakeIB()
    out = asyncio.run(_gateway(fake).place(TSLA))
    parent, take, stop = fake.placed
    assert parent.orderId == 100 and take.parentId == 100 and stop.parentId == 100
    assert [o.transmit for o in fake.placed] == [False, False, True]
    assert stop.auxPrice == 358.32 and take.lmtPrice == 370.04
    assert out["paper"] is True and [o["role"] for o in out["orders"]] == [
        "parent",
        "take_profit",
        "stop_loss",
    ]


def test_paper_mode_refuses_live_account():
    with pytest.raises(BrokerError, match="not a paper account"):
        asyncio.run(_gateway(FakeIB(account="U999")).place(TSLA))


def test_live_mode_refuses_paper_account():
    with pytest.raises(BrokerError, match="is a paper account"):
        asyncio.run(_gateway(FakeIB(account="DU1"), mode="live").place(TSLA))


def test_no_short_sale_and_options_are_not_shares():
    sell = {"symbol": "TSLA", "side": "sell", "qty": "5", "type": "market"}
    with pytest.raises(BrokerError, match="no short"):
        asyncio.run(_gateway(FakeIB(held=2)).place(sell))


def test_sell_while_bracket_legs_hold_the_shares():
    sell = {"symbol": "TSLA", "side": "sell", "qty": "8", "type": "market"}
    with pytest.raises(BrokerError, match="open sell orders"):
        asyncio.run(_gateway(FakeIB(held=8, open_sells=8)).place(sell))


def test_market_order_cap_uses_a_quote():
    with pytest.raises(BrokerError, match="IBKR_MAX_ORDER_USD"):
        asyncio.run(_gateway(FakeIB(price=364.0), max_order_usd=1000).place(TSLA))
    asyncio.run(_gateway(FakeIB(price=364.0), max_order_usd=4000).place(TSLA))


def test_close_position_cancels_legs_first():
    fake = FakeIB(held=8, open_sells=8)
    out = asyncio.run(_gateway(fake, max_order_usd=1).close_position("TSLA"))
    assert fake.cancelled == [50] and out["cancelled_first"] == [50]
    (o,) = fake.placed
    assert (o.action, o.totalQuantity, o.orderType) == ("SELL", 8, "MKT")


def test_close_position_refuses_fractions_and_others_orders():
    with pytest.raises(BrokerError, match="whole number"):
        asyncio.run(_gateway(FakeIB(held=8)).close_position("TSLA", 2.5))
    fake = FakeIB(held=8)
    fake._add_trade("SELL", 8, client_id=42)
    with pytest.raises(BrokerError, match="belongs to API client 42"):
        asyncio.run(_gateway(fake).close_position("TSLA"))


def test_sell_bracket_must_straddle_entry():
    with pytest.raises(BrokerError, match="sell bracket"):
        plan_orders(
            {
                "symbol": "TSLA",
                "side": "sell",
                "qty": "1",
                "type": "limit",
                "limit_price": "380",
                "order_class": "bracket",
                "take_profit_limit_price": "350",
                "stop_loss_stop_price": "370",
            }
        )


def test_mcp_tools():
    pytest.importorskip("fastmcp")
    from openbb_daytrader.ibkr_mcp import build_server

    server = build_server()
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {
        "get_account_info",
        "get_all_positions",
        "get_open_position",
        "get_orders",
        "get_stock_snapshot",
        "place_stock_order",
        "cancel_order_by_id",
        "close_position",
    }
