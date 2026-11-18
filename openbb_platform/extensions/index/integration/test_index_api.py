"""Test the index API endpoints."""

import base64

import pytest
import requests
from openbb_core.env import Env
from openbb_core.provider.utils.helpers import get_querystring


@pytest.fixture(scope="session")
def headers():
    """Get the headers for the API request."""
    userpass = f"{Env().API_USERNAME}:{Env().API_PASSWORD}"
    userpass_bytes = userpass.encode("ascii")
    base64_bytes = base64.b64encode(userpass_bytes)

    return {"Authorization": f"Basic {base64_bytes.decode('ascii')}"}


@pytest.mark.parametrize(
    "params",
    [
        ({"symbol": "dowjones", "provider": "fmp"}),
        ({"symbol": "^TX60", "provider": "tmx", "use_cache": False}),
        ({"symbol": "BUK100P", "provider": "cboe"}),
    ],
)
@pytest.mark.integration
def test_index_constituents(params, headers):
    """Test the index constituents endpoint."""
    params = {p: v for p, v in params.items() if v}

    query_str = get_querystring(params, [])
    url = f"http://0.0.0.0:8000/api/v1/index/constituents?{query_str}"
    result = requests.get(url, headers=headers, timeout=10)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "interval": "1d",
                "provider": "cboe",
                "symbol": "AAVE100",
                "start_date": "2023-01-01",
                "end_date": "2023-06-06",
                "use_cache": False,
            }
        ),
        (
            {
                "interval": "1d",
                "provider": "fmp",
                "symbol": "^DJI",
                "start_date": "2024-01-01",
                "end_date": "2024-02-05",
            }
        ),
        (
            {
                "interval": "1h",
                "provider": "fmp",
                "symbol": "^DJI,^NDX",
                "start_date": None,
                "end_date": None,
            }
        ),
        (
            {
                "interval": "1d",
                "provider": "yfinance",
                "symbol": "DJI",
                "start_date": "2023-01-01",
                "end_date": "2023-06-06",
            }
        ),
        (
            {
                "provider": "intrinio",
                "start_date": "2023-01-01",
                "end_date": "2023-06-06",
                "symbol": "DJI",
                "limit": 100,
            }
        ),
    ],
)
@pytest.mark.integration
def test_index_price_historical(params, headers):
    """Test the index historical price endpoint."""
    params = {p: v for p, v in params.items() if v}

    query_str = get_querystring(params, [])
    url = f"http://0.0.0.0:8000/api/v1/index/price/historical?{query_str}"
    result = requests.get(url, headers=headers, timeout=20)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        ({"provider": "cboe", "use_cache": False}),
        ({"provider": "fmp"}),
        ({"provider": "yfinance"}),
        ({"provider": "tmx", "use_cache": False}),
    ],
)
@pytest.mark.integration
def test_index_available(params, headers):
    """Test the index available endpoint."""
    params = {p: v for p, v in params.items() if v}

    query_str = get_querystring(params, [])
    url = f"http://0.0.0.0:8000/api/v1/index/available?{query_str}"
    result = requests.get(url, headers=headers, timeout=10)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        ({"query": "D", "is_symbol": True, "provider": "cboe", "use_cache": False}),
    ],
)
@pytest.mark.integration
def test_index_search(params, headers):
    """Test the index search endpoint."""
    params = {p: v for p, v in params.items() if v}

    query_str = get_querystring(params, [])
    url = f"http://0.0.0.0:8000/api/v1/index/search?{query_str}"
    result = requests.get(url, headers=headers, timeout=10)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        ({"provider": "cboe", "region": "us"}),
        ({"provider": "tmx", "region": "ca", "use_cache": False}),
    ],
)
@pytest.mark.integration
def test_index_snapshots(params, headers):
    """Test the index snapshots endpoint."""
    params = {p: v for p, v in params.items() if v}

    query_str = get_querystring(params, [])
    url = f"http://0.0.0.0:8000/api/v1/index/snapshots?{query_str}"
    result = requests.get(url, headers=headers, timeout=10)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "series_name": "pe_month",
                "start_date": None,
                "end_date": None,
                "provider": "multpl",
            }
        ),
    ],
)
@pytest.mark.integration
def test_index_sp500_multiples(params, headers):
    """Test the index sp500 multiples endpoint."""
    params = {p: v for p, v in params.items() if v}

    query_str = get_querystring(params, [])
    url = f"http://0.0.0.0:8000/api/v1/index/sp500_multiples?{query_str}"
    result = requests.get(url, headers=headers, timeout=20)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        ({"provider": "tmx", "symbol": "^TX60", "use_cache": False}),
    ],
)
@pytest.mark.integration
def test_index_sectors(params, headers):
    """Test the index sectors endpoint."""
    params = {p: v for p, v in params.items() if v}

    query_str = get_querystring(params, [])
    url = f"http://0.0.0.0:8000/api/v1/index/sectors?{query_str}"
    result = requests.get(url, headers=headers, timeout=10)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200
