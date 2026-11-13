"""Crypto Trades Standard Model."""

from datetime import datetime
from typing import Literal

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from pydantic import Field, field_validator


class CryptoTradesQueryParams(QueryParams):
    """Crypto Trades Query."""

    symbol: str = Field(description=QUERY_DESCRIPTIONS.get("symbol", ""))
    limit: int = Field(
        default=500,
        ge=1,
        le=1000,
        description="Number of recent trades to return.",
    )

    @field_validator("symbol", mode="before", check_fields=False)
    @classmethod
    def _to_upper(cls, v):
        """Convert symbol to uppercase."""
        return str(v).upper()


class CryptoTradesData(Data):
    """Crypto Trades Data."""

    symbol: str = Field(description="Trading pair symbol.")
    exchange: str | None = Field(default=None, description="Exchange name.")
    trade_id: int | str = Field(description="Provider trade ID.")
    price: float = Field(description="Trade execution price.")
    quantity: float = Field(description="Base asset quantity traded.")
    quote_quantity: float | None = Field(
        default=None,
        description="Quote asset quantity traded.",
    )
    timestamp: datetime = Field(description="Trade timestamp.")
    side: Literal["buy", "sell"] | None = Field(
        default=None,
        description="Aggressor side, when available.",
    )
