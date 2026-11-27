"""CoinGecko Crypto Historical Price Model."""

"""CoinGecko Crypto Historical Price Model."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from warnings import warn

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.crypto_historical import (
    CryptoHistoricalData,
    CryptoHistoricalQueryParams,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from openbb_coingecko.utils.helpers import make_request, validate_symbol
from pydantic import Field, field_validator


class CoinGeckoCryptoHistoricalQueryParams(CryptoHistoricalQueryParams):
    """CoinGecko Crypto Historical Price Query.
    
    Source: https://docs.coingecko.com/reference/coins-id-market-chart
    """

    __json_schema_extra__ = {
        "symbol": {"multiple_items_allowed": True},
        "interval": {
            "choices": ["1d", "7d", "14d", "30d", "90d", "180d", "365d", "max"]
        },
    }

    vs_currency: str = Field(
        default="usd",
        description="The target currency of market data (usd, eur, jpy, etc.)",
    )
    interval: Literal["1d", "7d", "14d", "30d", "90d", "180d", "365d", "max"] = Field(
        default="30d",
        description=QUERY_DESCRIPTIONS.get("interval", "") + 
        " Defaults to '30d'. Use 'max' for maximum available history.",
    )
    precision: Optional[Literal["full"]] = Field(
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


class CoinGeckoCryptoHistoricalData(CryptoHistoricalData):
    """CoinGecko Crypto Historical Price Data."""

    market_cap: Optional[float] = Field(
        default=None,
        description="Market capitalization at the time.",
        json_schema_extra={"x-unit_measurement": "currency"},
    )


class CoinGeckoCryptoHistoricalFetcher(
    Fetcher[
        CoinGeckoCryptoHistoricalQueryParams,
        List[CoinGeckoCryptoHistoricalData],
    ]
):
    """Transform the query, extract and transform the data from the CoinGecko endpoints."""

    @staticmethod
    def transform_query(params: Dict[str, Any]) -> CoinGeckoCryptoHistoricalQueryParams:
        """Transform the query parameters."""
        return CoinGeckoCryptoHistoricalQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: CoinGeckoCryptoHistoricalQueryParams,
        credentials: Optional[Dict[str, str]],
        **kwargs: Any,
    ) -> List[Dict]:
        """Return the raw data from the CoinGecko endpoint."""
        api_key = credentials.get("coingecko_api_key") if credentials else None
        
        symbols = query.symbol.split(",")
        results = []
        
        for symbol in symbols:
            try:
                # Convert interval to days for CoinGecko API
                days = _parse_interval_to_days(query.interval)
                
                # Build parameters for the API call
                params = {
                    "vs_currency": query.vs_currency,
                    "days": days,
                }
                
                if query.precision:
                    params["precision"] = query.precision
                
                # Handle date range if provided
                if query.start_date and query.end_date:
                    # Convert dates to timestamps for range endpoint
                    start_timestamp = int(query.start_date.timestamp())
                    end_timestamp = int(query.end_date.timestamp())
                    
                    endpoint = f"coins/{symbol}/market_chart/range"
                    params = {
                        "vs_currency": query.vs_currency,
                        "from": start_timestamp,
                        "to": end_timestamp,
                    }
                    if query.precision:
                        params["precision"] = query.precision
                else:
                    endpoint = f"coins/{symbol}/market_chart"
                
                data = make_request(endpoint, params, api_key)
                
                if not data or not isinstance(data, dict):
                    warn(f"No data found for symbol: {symbol}")
                    continue
                
                # Transform the data structure
                prices = data.get("prices", [])
                market_caps = data.get("market_caps", [])
                volumes = data.get("total_volumes", [])
                
                if not prices:
                    warn(f"No price data found for symbol: {symbol}")
                    continue
                
                # Combine the data
                for i, price_data in enumerate(prices):
                    timestamp, price = price_data
                    
                    # Get corresponding market cap and volume data
                    market_cap = market_caps[i][1] if i < len(market_caps) else None
                    volume = volumes[i][1] if i < len(volumes) else None
                    
                    # Convert timestamp to datetime
                    date = datetime.fromtimestamp(timestamp / 1000)
                    
                    result = {
                        "symbol": symbol.upper(),
                        "date": date,
                        "open": price,  # CoinGecko doesn't provide OHLC, only price points
                        "high": price,
                        "low": price,
                        "close": price,
                        "volume": volume,
                        "market_cap": market_cap,
                    }
                    
                    results.append(result)
                    
            except Exception as e:
                warn(f"Error fetching data for {symbol}: {str(e)}")
                continue
        
        if not results:
            raise EmptyDataError("No data found for any of the provided symbols.")
        
        return results

    @staticmethod
    def transform_data(
        query: CoinGeckoCryptoHistoricalQueryParams,
        data: List[Dict],
        **kwargs: Any,
    ) -> List[CoinGeckoCryptoHistoricalData]:
        """Return the transformed data."""
        return [CoinGeckoCryptoHistoricalData.model_validate(d) for d in data]


def _parse_interval_to_days(interval: str) -> Union[int, str]:
    """Parse interval string to number of days for CoinGecko API."""
    interval_map = {
        "1d": 1,
        "7d": 7,
        "14d": 14,
        "30d": 30,
        "90d": 90,
        "180d": 180,
        "365d": 365,
        "max": "max",
    }
    
    return interval_map.get(interval.lower(), 30)
