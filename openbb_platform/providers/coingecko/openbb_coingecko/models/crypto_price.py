"""CoinGecko Real-time Crypto Price Model."""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from warnings import warn

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.crypto_price import (
    CryptoPriceData,
    CryptoPriceQueryParams,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from openbb_coingecko.utils.helpers import make_request, validate_symbol
from pydantic import Field, field_validator


class CoinGeckoCryptoPriceQueryParams(CryptoPriceQueryParams):
    """CoinGecko Real-time Crypto Price Query.

    Source: https://docs.coingecko.com/reference/simple-price
    """

    vs_currency: str = Field(
        default="usd",
        description="The target currency of market data (usd, eur, jpy, etc.)",
    )
    include_market_cap: bool = Field(
        default=True,
        description="Include market cap in the response.",
    )
    include_24hr_vol: bool = Field(
        default=True,
        description="Include 24hr volume in the response.",
    )
    include_24hr_change: bool = Field(
        default=True,
        description="Include 24hr change in the response.",
    )
    include_last_updated_at: bool = Field(
        default=True,
        description="Include last updated timestamp in the response.",
    )
    precision: Optional[str] = Field(
        default=None,
        description=(
            "The precision of the data. Use 'full' for full precision, "
            "otherwise 2 decimals."
        ),
    )

    @field_validator("vs_currency", mode="before", check_fields=False)
    @classmethod
    def validate_vs_currency(cls, v: str) -> str:
        """Validate and normalize vs_currency."""
        return v.lower().strip()

    @field_validator("symbol", mode="before", check_fields=False)
    @classmethod
    def validate_symbol(cls, v: Union[str, List[str]]) -> str:
        """Validate and normalize symbol(s)."""
        if isinstance(v, str):
            return validate_symbol(v)
        return ",".join([validate_symbol(symbol) for symbol in v])


class CoinGeckoCryptoPriceData(CryptoPriceData):
    """CoinGecko Real-time Crypto Price Data."""


class CoinGeckoCryptoPriceFetcher(
    Fetcher[
        CoinGeckoCryptoPriceQueryParams,
        List[CoinGeckoCryptoPriceData],
    ]
):
    """Transform the query, extract and transform the data from the CoinGecko endpoints."""

    @staticmethod
    def transform_query(params: Dict[str, Any]) -> CoinGeckoCryptoPriceQueryParams:
        """Transform the query parameters."""
        return CoinGeckoCryptoPriceQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: CoinGeckoCryptoPriceQueryParams,
        credentials: Optional[Dict[str, str]],
        **kwargs: Any,
    ) -> List[Dict]:
        """Return the raw data from the CoinGecko endpoint."""
        api_key = credentials.get("coingecko_api_key") if credentials else None
        
        symbols = query.symbol.split(",")
        
        # Build parameters for the API call
        params = {
            "ids": ",".join(symbols),
            "vs_currencies": query.vs_currency,
            "include_market_cap": str(query.include_market_cap).lower(),
            "include_24hr_vol": str(query.include_24hr_vol).lower(),
            "include_24hr_change": str(query.include_24hr_change).lower(),
            "include_last_updated_at": str(query.include_last_updated_at).lower(),
        }
        
        if query.precision:
            params["precision"] = query.precision
        
        endpoint = "simple/price"
        data = make_request(endpoint, params, api_key)
        
        if not data or not isinstance(data, dict):
            raise EmptyDataError("No price data found.")
        
        results = []
        
        for coin_id, price_data in data.items():
            if not isinstance(price_data, dict):
                warn(f"Invalid price data format for {coin_id}")
                continue
            
            # Get the price for the requested vs_currency
            price = price_data.get(query.vs_currency)
            if price is None:
                warn(f"No price found for {coin_id} in {query.vs_currency}")
                continue
            
            # Extract additional data
            market_cap_key = f"{query.vs_currency}_market_cap"
            volume_key = f"{query.vs_currency}_24h_vol"
            change_key = f"{query.vs_currency}_24h_change"
            
            market_cap = price_data.get(market_cap_key)
            volume_24h = price_data.get(volume_key)
            change_24h = price_data.get(change_key)
            
            # Handle last updated timestamp
            last_updated = None
            if "last_updated_at" in price_data:
                try:
                    last_updated = datetime.fromtimestamp(price_data["last_updated_at"])
                except (ValueError, TypeError):
                    pass
            
            result = {
                "symbol": coin_id.upper(),
                "name": None,  # Not available in simple/price endpoint
                "price": price,
                "market_cap": market_cap,
                "market_cap_rank": None,  # Not available in simple/price endpoint
                "volume_24h": volume_24h,
                "change_24h": change_24h,
                "last_updated": last_updated,
            }
            
            results.append(result)
        
        if not results:
            raise EmptyDataError("No valid price data found for any of the provided symbols.")
        
        return results

    @staticmethod
    def transform_data(
        query: CoinGeckoCryptoPriceQueryParams,
        data: List[Dict],
        **kwargs: Any,
    ) -> List[CoinGeckoCryptoPriceData]:
        """Return the transformed data."""
        return [CoinGeckoCryptoPriceData.model_validate(d) for d in data]
