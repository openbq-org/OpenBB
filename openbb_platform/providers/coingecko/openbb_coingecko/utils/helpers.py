"""CoinGecko API Helper Functions."""

import asyncio
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlencode

import requests
from openbb_core.provider.utils.errors import EmptyDataError


class CoinGeckoAPIError(Exception):
    """CoinGecko API Error."""


def get_coingecko_base_url(use_pro_api: bool = False) -> str:
    """Get the appropriate CoinGecko API base URL."""
    if use_pro_api:
        return "https://pro-api.coingecko.com/api/v3"
    return "https://api.coingecko.com/api/v3"


def build_headers(api_key: Optional[str] = None) -> Dict[str, str]:
    """Build headers for CoinGecko API requests."""
    headers = {
        "accept": "application/json",
        "User-Agent": "OpenBB/1.0.0",
    }
    
    if api_key:
        headers["x-cg-pro-api-key"] = api_key
    
    return headers


def build_url(
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
) -> str:
    """Build complete URL for CoinGecko API requests."""
    base_url = get_coingecko_base_url(use_pro_api=bool(api_key))
    url = f"{base_url}/{endpoint.lstrip('/')}"
    
    if params:
        # Filter out None values
        filtered_params = {k: v for k, v in params.items() if v is not None}
        if filtered_params:
            url += f"?{urlencode(filtered_params)}"
    
    return url


def make_request(
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
    timeout: int = 30,
) -> Union[Dict, List]:
    """Make synchronous request to CoinGecko API."""
    url = build_url(endpoint, params, api_key)
    headers = build_headers(api_key)
    
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        
        data = response.json()
        
        if not data:
            raise EmptyDataError("No data returned from CoinGecko API")
        
        return data
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            raise CoinGeckoAPIError(
                "Rate limit exceeded. Please try again later or upgrade your API plan."
            ) from e
        elif e.response.status_code == 401:
            raise CoinGeckoAPIError(
                "Invalid API key. Please check your CoinGecko API key."
            ) from e
        elif e.response.status_code == 404:
            raise CoinGeckoAPIError(
                "Endpoint not found or invalid parameters."
            ) from e
        else:
            raise CoinGeckoAPIError(
                f"HTTP error {e.response.status_code}: {e.response.text}"
            ) from e
    
    except requests.exceptions.RequestException as e:
        raise CoinGeckoAPIError(f"Request failed: {str(e)}") from e
    
    except ValueError as e:
        raise CoinGeckoAPIError(f"Invalid JSON response: {str(e)}") from e


async def amake_request(
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
    timeout: int = 30,
) -> Union[Dict, List]:
    """Make asynchronous request to CoinGecko API."""
    # For now, we'll use the synchronous version in a thread pool
    # In a production environment, you might want to use aiohttp
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, make_request, endpoint, params, api_key, timeout
    )


def validate_symbol(symbol: str) -> str:
    """Validate and normalize cryptocurrency symbol."""
    if not symbol:
        raise ValueError("Symbol cannot be empty")
    
    # CoinGecko uses lowercase coin IDs
    return symbol.lower().strip()


def parse_interval_to_days(interval: str) -> int:
    """Parse interval string to number of days for CoinGecko API."""
    interval_map = {
        "1d": 1,
        "7d": 7,
        "14d": 14,
        "30d": 30,
        "90d": 90,
        "180d": 180,
        "365d": 365,
        "max": 365 * 10,  # 10 years as max
    }
    
    return interval_map.get(interval.lower(), 30)  # Default to 30 days


def get_supported_vs_currencies() -> List[str]:
    """Get list of supported vs currencies for CoinGecko API."""
    return [
        "usd", "eur", "jpy", "btc", "eth", "ltc", "bch", "bnb", "eos", "xrp",
        "xlm", "link", "dot", "yfi", "gbp", "aud", "cad", "chf", "cny", "hkd",
        "inr", "krw", "mxn", "nok", "nzd", "php", "pln", "rub", "sek", "sgd",
        "thb", "try", "twd", "zar"
    ]
