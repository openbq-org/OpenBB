"""Crypto Real-time Price Standard Model."""

from datetime import datetime
from typing import List, Optional, Set, Union

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import (
    DATA_DESCRIPTIONS,
    QUERY_DESCRIPTIONS,
)
from pydantic import Field, field_validator


class CryptoPriceQueryParams(QueryParams):
    """Crypto Real-time Price Query."""

    symbol: str = Field(
        description=QUERY_DESCRIPTIONS.get("symbol", "")
        + " Can use coin IDs (bitcoin, ethereum) or symbols (btc, eth). Multiple symbols supported."
    )

    @field_validator("symbol", mode="before", check_fields=False)
    @classmethod
    def validate_symbol(cls, v: Union[str, List[str], Set[str]]):
        """Convert field to lowercase for coin IDs."""
        if isinstance(v, str):
            return v.lower().strip()
        return ",".join([symbol.lower().strip() for symbol in list(v)])


class CryptoPriceData(Data):
    """Crypto Real-time Price Data."""

    symbol: str = Field(description=DATA_DESCRIPTIONS.get("symbol", "") + " (Crypto)")
    name: Optional[str] = Field(
        default=None, description="Name of the cryptocurrency."
    )
    price: float = Field(
        description="Current price of the cryptocurrency.",
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    market_cap: Optional[float] = Field(
        default=None,
        description="Market capitalization.",
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    market_cap_rank: Optional[int] = Field(
        default=None,
        description="Market cap rank.",
    )
    volume_24h: Optional[float] = Field(
        default=None,
        description="24-hour trading volume.",
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    change_24h: Optional[float] = Field(
        default=None,
        description="24-hour price change in percentage.",
        json_schema_extra={"x-unit_measurement": "percent", "x-frontend_multiply": 100},
    )
    last_updated: Optional[datetime] = Field(
        default=None,
        description="Last updated timestamp.",
    )
