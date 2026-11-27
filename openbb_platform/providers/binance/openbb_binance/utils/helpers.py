"""Binance Helpers."""

from datetime import datetime, timezone
from typing import Any

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils.errors import EmptyDataError
from openbb_core.provider.utils.helpers import amake_request


BASE_URL = "https://api.binance.com"


def normalize_symbol(symbol: str) -> str:
    """Normalize BTC/USD, BTC-USD, or BTCUSDT to Binance format."""
    return symbol.upper().replace("/", "").replace("-", "")


def ms_to_datetime(value: int) -> datetime:
    """Convert milliseconds timestamp to UTC datetime."""
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def get_trade_side(is_buyer_maker: bool | None) -> str | None:
    """
    Convert Binance isBuyerMaker flag to aggressor side.

    If buyer is maker, seller was taker/aggressor -> sell.
    If buyer is not maker, buyer was taker/aggressor -> buy.
    """
    if is_buyer_maker is None:
        return None
    return "sell" if is_buyer_maker else "buy"


async def get_recent_trades(symbol: str, limit: int = 500, **kwargs: Any) -> list[dict]:
    """Get recent trades from Binance."""
    url = f"{BASE_URL}/api/v3/trades"
    params = {
        "symbol": normalize_symbol(symbol),
        "limit": limit,
    }

    data = await amake_request(url, params=params, **kwargs)

    if not data:
        raise EmptyDataError(f"No trade data found for {symbol}.")

    if isinstance(data, dict) and data.get("code"):
        message = data.get("msg", "Unknown Binance API error.")
        raise OpenBBError(f"Binance API error: {message}")

    return data
