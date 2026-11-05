"""MCP server for Interactive Brokers via a local IB Gateway / TWS.

Tool names and place_stock_order's input match what the trader-broker skill
already prints (Alpaca's shape), so the desk flow is unchanged. Keep every
order tool on "ask" in .claude/settings.json.

    openbb-ibkr-mcp            # stdio (Claude Code / Claude Desktop)
"""

import json
from typing import Annotated

from pydantic import Field

from openbb_daytrader.ibkr import BrokerError, Gateway

INSTRUCTIONS = (
    "Interactive Brokers account through the user's local IB Gateway. Paper by default. "
    "Only call place_stock_order, cancel_order_by_id or close_position for an order that "
    "trader-risk passed and the user approved with an explicit yes in the chat for that exact order."
)


def build_server():
    from fastmcp import FastMCP  # noqa: PLC0415

    mcp = FastMCP("ibkr", instructions=INSTRUCTIONS)
    gw = Gateway()

    async def call(coro):
        try:
            return await coro
        except BrokerError as exc:
            return {"error": str(exc)}

    @mcp.tool(annotations={"readOnlyHint": True})
    async def get_account_info() -> dict:
        """Account id, paper or live, net liquidation, cash, buying power, P&L."""
        return await call(gw.account())

    @mcp.tool(annotations={"readOnlyHint": True})
    async def get_all_positions() -> list | dict:
        """Every open position: symbol, quantity, average cost."""
        return await call(gw.positions())

    @mcp.tool(annotations={"readOnlyHint": True})
    async def get_orders(
        status: Annotated[
            str | None, Field(description="ignored: always open orders")
        ] = None,
        nested: Annotated[
            bool | None, Field(description="ignored: legs carry parent_id")
        ] = None,
    ) -> list | dict:
        """Open orders, with bracket children (parent_id) and status."""
        return await call(gw.open_orders())

    @mcp.tool(annotations={"readOnlyHint": True})
    async def get_open_position(symbol: str) -> dict:
        """Shares held of one US stock (0 if none)."""
        return await call(gw.position(symbol))

    @mcp.tool(annotations={"readOnlyHint": True})
    async def get_stock_snapshot(
        symbols: Annotated[list[str], Field(description="US tickers, e.g. ['TSLA']")],
    ) -> list | dict:
        """Delayed quote (last, bid, ask, close) unless the account has live data."""
        return await call(gw.quote(symbols))

    @mcp.tool(annotations={"destructiveHint": True})
    async def place_stock_order(
        symbol: str,
        side: Annotated[str, Field(description="buy or sell")],
        qty: Annotated[str, Field(description="whole shares, as a string")],
        type: Annotated[
            str, Field(description="market, limit, stop, stop_limit")
        ] = "market",  # noqa: A002
        time_in_force: Annotated[
            str, Field(description="day, gtc, ioc, fok, opg")
        ] = "day",
        limit_price: str | None = None,
        stop_price: str | None = None,
        order_class: Annotated[
            str | None, Field(description="simple or bracket")
        ] = None,
        take_profit_limit_price: str | None = None,
        stop_loss_stop_price: str | None = None,
        stop_loss_limit_price: str | None = None,
        extended_hours: bool | None = None,
        client_order_id: str | None = None,
    ) -> dict:
        """Place ONE US stock order (bracket: entry + take-profit + stop-loss, one cancels the other).

        Only with trader-risk PASS and the user's explicit yes for this exact order.
        """
        order = {
            k: v
            for k, v in locals().items()
            if v is not None and k not in ("gw", "call")
        }
        return await call(gw.place(order))

    @mcp.tool(annotations={"destructiveHint": True})
    async def cancel_order_by_id(order_id: int) -> dict:
        """Cancel one open order (cancelling a bracket parent cancels its children)."""
        return await call(gw.cancel(order_id))

    @mcp.tool(annotations={"destructiveHint": True})
    async def close_position(
        symbol: str,
        qty: Annotated[
            str | None, Field(description="shares to close, default all")
        ] = None,
    ) -> dict:
        """Market order that closes (part of) one stock position. Cancel its bracket legs first."""
        return await call(gw.close_position(symbol, float(qty) if qty else None))

    return mcp


def main() -> None:
    """Run the server on stdio."""
    import sys  # noqa: PLC0415

    if "--check" in sys.argv:
        import asyncio  # noqa: PLC0415

        try:
            import os  # noqa: PLC0415

            from openbb_daytrader.ibkr import Settings  # noqa: PLC0415

            settings = Settings.from_env()
            settings.client_id = (
                900 + os.getpid() % 99
            )  # never collide with the servers
            out = asyncio.run(Gateway(settings).account())
        except BrokerError as exc:
            print(f"[ERR] {exc}")  # noqa: T201
            sys.exit(1)
        print(json.dumps(out, indent=2, default=str))  # noqa: T201
        return
    build_server().run()


if __name__ == "__main__":
    main()
