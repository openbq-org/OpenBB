"""CoinGecko Crypto Search Model."""

from typing import Any, Dict, List, Optional

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.crypto_search import (
    CryptoSearchData,
    CryptoSearchQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from openbb_coingecko.utils.helpers import make_request
from pydantic import Field


class CoinGeckoCryptoSearchQueryParams(CryptoSearchQueryParams):
    """CoinGecko Crypto Search Query.
    
    Source: https://docs.coingecko.com/reference/search-data
    """


class CoinGeckoCryptoSearchData(CryptoSearchData):
    """CoinGecko Crypto Search Data."""

    id: Optional[str] = Field(
        default=None,
        description="CoinGecko coin ID (used for API calls).",
    )
    api_symbol: Optional[str] = Field(
        default=None,
        description="API symbol used by CoinGecko.",
    )
    market_cap_rank: Optional[int] = Field(
        default=None,
        description="Market cap rank of the cryptocurrency.",
    )
    thumb: Optional[str] = Field(
        default=None,
        description="URL to the thumbnail image of the cryptocurrency.",
    )
    large: Optional[str] = Field(
        default=None,
        description="URL to the large image of the cryptocurrency.",
    )


class CoinGeckoCryptoSearchFetcher(
    Fetcher[
        CoinGeckoCryptoSearchQueryParams,
        List[CoinGeckoCryptoSearchData],
    ]
):
    """Transform the query, extract and transform the data from the CoinGecko endpoints."""

    @staticmethod
    def transform_query(params: Dict[str, Any]) -> CoinGeckoCryptoSearchQueryParams:
        """Transform the query parameters."""
        return CoinGeckoCryptoSearchQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: CoinGeckoCryptoSearchQueryParams,
        credentials: Optional[Dict[str, str]],
        **kwargs: Any,
    ) -> List[Dict]:
        """Return the raw data from the CoinGecko endpoint."""
        api_key = credentials.get("coingecko_api_key") if credentials else None
        
        if query.query:
            # Use search endpoint for specific query
            endpoint = "search"
            params = {"query": query.query}
            
            data = make_request(endpoint, params, api_key)
            
            if not data or not isinstance(data, dict):
                raise EmptyDataError("No search results found.")
            
            # Extract coins from search results
            coins = data.get("coins", [])
            
            if not coins:
                raise EmptyDataError(f"No cryptocurrencies found for query: {query.query}")
            
            results = []
            for coin in coins:
                result = {
                    "symbol": coin.get("symbol", "").upper(),
                    "name": coin.get("name"),
                    "id": coin.get("id"),
                    "api_symbol": coin.get("api_symbol"),
                    "market_cap_rank": coin.get("market_cap_rank"),
                    "thumb": coin.get("thumb"),
                    "large": coin.get("large"),
                }
                results.append(result)
            
            return results
        
        else:
            # Use coins list endpoint for all available coins
            endpoint = "coins/list"
            params = {"include_platform": "false"}
            
            data = make_request(endpoint, params, api_key)
            
            if not data or not isinstance(data, list):
                raise EmptyDataError("No cryptocurrency list data found.")
            
            results = []
            for coin in data:
                result = {
                    "symbol": coin.get("symbol", "").upper(),
                    "name": coin.get("name"),
                    "id": coin.get("id"),
                    "api_symbol": coin.get("symbol"),
                    "market_cap_rank": None,  # Not available in list endpoint
                    "thumb": None,  # Not available in list endpoint
                    "large": None,  # Not available in list endpoint
                }
                results.append(result)
            
            return results

    @staticmethod
    def transform_data(
        query: CoinGeckoCryptoSearchQueryParams,
        data: List[Dict],
        **kwargs: Any,
    ) -> List[CoinGeckoCryptoSearchData]:
        """Return the transformed data."""
        return [CoinGeckoCryptoSearchData.model_validate(d) for d in data]
