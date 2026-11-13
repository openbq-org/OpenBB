"""Binance Crypto Trades Model."""

from typing import Any

from openbb_binance.utils.helpers import (
    get_recent_trades,
    get_trade_side,
    ms_to_datetime,
    normalize_symbol,
)
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.crypto_trades import (
    CryptoTradesData,
    CryptoTradesQueryParams,
)
from pydantic import Field


class BinanceCryptoTradesQueryParams(CryptoTradesQueryParams):
    """Binance Crypto Trades Query."""

    symbol: str = Field(description="Trading pair symbol, e.g. BTCUSDT.")
    limit: int = Field(
        default=500,
        ge=1,
        le=1000,
        description="Number of recent trades to return. Maximum is 1000.",
    )


class BinanceCryptoTradesData(CryptoTradesData):
    """Binance Crypto Trades Data."""


class BinanceCryptoTradesFetcher(
    Fetcher[
        BinanceCryptoTradesQueryParams,
        list[BinanceCryptoTradesData],
    ]
):
    """Binance Crypto Trades Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> BinanceCryptoTradesQueryParams:
        """Transform query params."""
        transformed = params.copy()
        transformed["symbol"] = normalize_symbol(transformed["symbol"])
        return BinanceCryptoTradesQueryParams(**transformed)

    @staticmethod
    async def aextract_data(
        query: BinanceCryptoTradesQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Extract raw data from Binance."""
        return await get_recent_trades(
            symbol=query.symbol,
            limit=query.limit,
            **kwargs,
        )

    @staticmethod
    def transform_data(
        query: BinanceCryptoTradesQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[BinanceCryptoTradesData]:
        """Transform Binance trade data."""
        return [
            BinanceCryptoTradesData.model_validate(
                {
                    "symbol": query.symbol,
                    "exchange": "binance",
                    "trade_id": item["id"],
                    "price": float(item["price"]),
                    "quantity": float(item["qty"]),
                    "quote_quantity": (
                        float(item["quoteQty"])
                        if item.get("quoteQty") is not None
                        else None
                    ),
                    "timestamp": ms_to_datetime(item["time"]),
                    "side": get_trade_side(item.get("isBuyerMaker")),
                }
            )
            for item in data
        ]
