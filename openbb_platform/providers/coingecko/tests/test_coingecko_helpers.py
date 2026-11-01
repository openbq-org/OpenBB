"""Tests for CoinGecko helper functions."""

import pytest
from unittest.mock import Mock, patch
import requests

# Skip tests if imports fail (e.g., in CI without provider installed)
try:
    from openbb_coingecko.utils.helpers import (
        build_headers,
        build_url,
        get_coingecko_base_url,
        get_supported_vs_currencies,
        make_request,
        parse_interval_to_days,
        validate_symbol,
        CoinGeckoAPIError,
    )
    IMPORTS_AVAILABLE = True
except ImportError:
    IMPORTS_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not IMPORTS_AVAILABLE, reason="CoinGecko provider not available"
)


class TestCoinGeckoHelpers:
    """Test CoinGecko helper functions."""

    def test_get_coingecko_base_url_free(self):
        """Test getting free API base URL."""
        url = get_coingecko_base_url(use_pro_api=False)
        assert url == "https://api.coingecko.com/api/v3"

    def test_get_coingecko_base_url_pro(self):
        """Test getting Pro API base URL."""
        url = get_coingecko_base_url(use_pro_api=True)
        assert url == "https://pro-api.coingecko.com/api/v3"

    def test_build_headers_without_api_key(self):
        """Test building headers without API key."""
        headers = build_headers()
        expected = {
            "accept": "application/json",
            "User-Agent": "OpenBB/1.0.0",
        }
        assert headers == expected

    def test_build_headers_with_api_key(self):
        """Test building headers with API key."""
        api_key = "test_api_key"
        headers = build_headers(api_key)
        expected = {
            "accept": "application/json",
            "User-Agent": "OpenBB/1.0.0",
            "x-cg-pro-api-key": api_key,
        }
        assert headers == expected

    def test_build_url_without_params(self):
        """Test building URL without parameters."""
        url = build_url("simple/price")
        assert url == "https://api.coingecko.com/api/v3/simple/price"

    def test_build_url_with_params(self):
        """Test building URL with parameters."""
        params = {"ids": "bitcoin", "vs_currencies": "usd"}
        url = build_url("simple/price", params)
        assert "https://api.coingecko.com/api/v3/simple/price?" in url
        assert "ids=bitcoin" in url
        assert "vs_currencies=usd" in url

    def test_build_url_with_api_key(self):
        """Test building URL with API key (uses Pro API)."""
        url = build_url("simple/price", api_key="test_key")
        assert url == "https://pro-api.coingecko.com/api/v3/simple/price"

    def test_build_url_filters_none_params(self):
        """Test that None parameters are filtered out."""
        params = {"ids": "bitcoin", "vs_currencies": None, "include_market_cap": "true"}
        url = build_url("simple/price", params)
        assert "vs_currencies" not in url
        assert "ids=bitcoin" in url
        assert "include_market_cap=true" in url

    def test_validate_symbol_single(self):
        """Test validating single symbol."""
        result = validate_symbol("Bitcoin")
        assert result == "bitcoin"

    def test_validate_symbol_with_spaces(self):
        """Test validating symbol with spaces."""
        result = validate_symbol("  Bitcoin  ")
        assert result == "bitcoin"

    def test_validate_symbol_empty_raises_error(self):
        """Test that empty symbol raises error."""
        with pytest.raises(ValueError, match="Symbol cannot be empty"):
            validate_symbol("")

    def test_parse_interval_to_days(self):
        """Test parsing interval to days."""
        assert parse_interval_to_days("1d") == 1
        assert parse_interval_to_days("7d") == 7
        assert parse_interval_to_days("30d") == 30
        assert parse_interval_to_days("365d") == 365
        assert parse_interval_to_days("max") == 365 * 10
        assert parse_interval_to_days("invalid") == 30  # default

    def test_get_supported_vs_currencies(self):
        """Test getting supported vs currencies."""
        currencies = get_supported_vs_currencies()
        assert isinstance(currencies, list)
        assert "usd" in currencies
        assert "eur" in currencies
        assert "btc" in currencies
        assert "eth" in currencies

    @patch("openbb_coingecko.utils.helpers.requests.get")
    def test_make_request_success(self, mock_get):
        """Test successful API request."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"bitcoin": {"usd": 50000}}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = make_request("simple/price", {"ids": "bitcoin", "vs_currencies": "usd"})
        
        assert result == {"bitcoin": {"usd": 50000}}
        mock_get.assert_called_once()

    @patch("openbb_coingecko.utils.helpers.requests.get")
    def test_make_request_http_error_429(self, mock_get):
        """Test handling of rate limit error."""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        
        http_error = requests.exceptions.HTTPError()
        http_error.response = mock_response
        mock_get.return_value.raise_for_status.side_effect = http_error

        with pytest.raises(CoinGeckoAPIError, match="Rate limit exceeded"):
            make_request("simple/price")

    @patch("openbb_coingecko.utils.helpers.requests.get")
    def test_make_request_http_error_401(self, mock_get):
        """Test handling of authentication error."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Invalid API key"
        
        http_error = requests.exceptions.HTTPError()
        http_error.response = mock_response
        mock_get.return_value.raise_for_status.side_effect = http_error

        with pytest.raises(CoinGeckoAPIError, match="Invalid API key"):
            make_request("simple/price")

    @patch("openbb_coingecko.utils.helpers.requests.get")
    def test_make_request_http_error_404(self, mock_get):
        """Test handling of not found error."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = "Not found"
        
        http_error = requests.exceptions.HTTPError()
        http_error.response = mock_response
        mock_get.return_value.raise_for_status.side_effect = http_error

        with pytest.raises(CoinGeckoAPIError, match="Endpoint not found"):
            make_request("simple/price")

    @patch("openbb_coingecko.utils.helpers.requests.get")
    def test_make_request_connection_error(self, mock_get):
        """Test handling of connection error."""
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection failed")

        with pytest.raises(CoinGeckoAPIError, match="Request failed"):
            make_request("simple/price")

    @patch("openbb_coingecko.utils.helpers.requests.get")
    def test_make_request_json_error(self, mock_get):
        """Test handling of JSON parsing error."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        with pytest.raises(CoinGeckoAPIError, match="Invalid JSON response"):
            make_request("simple/price")

    @patch("openbb_coingecko.utils.helpers.requests.get")
    def test_make_request_empty_data(self, mock_get):
        """Test handling of empty data response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = None
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        with pytest.raises(Exception):  # Should raise EmptyDataError
            make_request("simple/price")

    @patch("openbb_coingecko.utils.helpers.requests.get")
    def test_make_request_with_timeout(self, mock_get):
        """Test request with custom timeout."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"test": "data"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        make_request("simple/price", timeout=60)
        
        # Check that timeout was passed to requests.get
        args, kwargs = mock_get.call_args
        assert kwargs["timeout"] == 60
