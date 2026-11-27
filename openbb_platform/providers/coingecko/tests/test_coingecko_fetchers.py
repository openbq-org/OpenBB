"""Tests for CoinGecko fetchers."""

import pytest
from datetime import date, datetime
from unittest.mock import Mock, patch

# Skip tests if imports fail (e.g., in CI without provider installed)
try:
    from openbb_coingecko.models.crypto_historical import (
        CoinGeckoCryptoHistoricalFetcher,
        CoinGeckoCryptoHistoricalQueryParams,
    )
    from openbb_coingecko.models.crypto_price import (
        CoinGeckoCryptoPriceFetcher,
        CoinGeckoCryptoPriceQueryParams,
    )
    from openbb_coingecko.models.crypto_search import (
        CoinGeckoCryptoSearchFetcher,
        CoinGeckoCryptoSearchQueryParams,
    )
    IMPORTS_AVAILABLE = True
except ImportError:
    IMPORTS_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not IMPORTS_AVAILABLE, reason="CoinGecko provider not available"
)


class TestCoinGeckoCryptoHistoricalFetcher:
    """Test CoinGecko Crypto Historical Fetcher."""

    @pytest.fixture
    def query_params(self):
        """Return query parameters for testing."""
        return {
            "symbol": "bitcoin",
            "vs_currency": "usd",
            "interval": "30d",
            "start_date": None,
            "end_date": None,
        }

    @pytest.fixture
    def mock_historical_data(self):
        """Return mock historical data."""
        return {
            "prices": [
                [1640995200000, 47000.0],  # 2022-01-01
                [1641081600000, 47500.0],  # 2022-01-02
            ],
            "market_caps": [
                [1640995200000, 890000000000.0],
                [1641081600000, 900000000000.0],
            ],
            "total_volumes": [
                [1640995200000, 25000000000.0],
                [1641081600000, 26000000000.0],
            ],
        }

    def test_transform_query(self, query_params):
        """Test query transformation."""
        result = CoinGeckoCryptoHistoricalFetcher.transform_query(query_params)
        assert isinstance(result, CoinGeckoCryptoHistoricalQueryParams)
        assert result.symbol == "bitcoin"
        assert result.vs_currency == "usd"
        assert result.interval == "30d"

    @patch("openbb_coingecko.models.crypto_historical.make_request")
    async def test_aextract_data(self, mock_request, query_params, mock_historical_data):
        """Test data extraction."""
        mock_request.return_value = mock_historical_data
        
        query = CoinGeckoCryptoHistoricalFetcher.transform_query(query_params)
        result = await CoinGeckoCryptoHistoricalFetcher.aextract_data(query, None)
        
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["symbol"] == "BITCOIN"
        assert result[0]["close"] == 47000.0
        assert result[0]["market_cap"] == 890000000000.0

    def test_transform_data(self, query_params, mock_historical_data):
        """Test data transformation."""
        query = CoinGeckoCryptoHistoricalFetcher.transform_query(query_params)
        
        # Simulate processed data
        processed_data = [
            {
                "symbol": "BITCOIN",
                "date": datetime(2022, 1, 1),
                "open": 47000.0,
                "high": 47000.0,
                "low": 47000.0,
                "close": 47000.0,
                "volume": 25000000000.0,
                "market_cap": 890000000000.0,
            }
        ]
        
        result = CoinGeckoCryptoHistoricalFetcher.transform_data(query, processed_data)
        
        assert len(result) == 1
        assert result[0].symbol == "BITCOIN"
        assert result[0].close == 47000.0
        assert result[0].market_cap == 890000000000.0


class TestCoinGeckoCryptoPriceFetcher:
    """Test CoinGecko Crypto Price Fetcher."""

    @pytest.fixture
    def query_params(self):
        """Return query parameters for testing."""
        return {
            "symbol": "bitcoin",
            "vs_currency": "usd",
            "include_market_cap": True,
            "include_24hr_vol": True,
            "include_24hr_change": True,
            "include_last_updated_at": True,
        }

    @pytest.fixture
    def mock_price_data(self):
        """Return mock price data."""
        return {
            "bitcoin": {
                "usd": 47000.0,
                "usd_market_cap": 890000000000.0,
                "usd_24h_vol": 25000000000.0,
                "usd_24h_change": 2.5,
                "last_updated_at": 1640995200,
            }
        }

    def test_transform_query(self, query_params):
        """Test query transformation."""
        result = CoinGeckoCryptoPriceFetcher.transform_query(query_params)
        assert isinstance(result, CoinGeckoCryptoPriceQueryParams)
        assert result.symbol == "bitcoin"
        assert result.vs_currency == "usd"
        assert result.include_market_cap is True

    @patch("openbb_coingecko.models.crypto_price.make_request")
    async def test_aextract_data(self, mock_request, query_params, mock_price_data):
        """Test data extraction."""
        mock_request.return_value = mock_price_data
        
        query = CoinGeckoCryptoPriceFetcher.transform_query(query_params)
        result = await CoinGeckoCryptoPriceFetcher.aextract_data(query, None)
        
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["symbol"] == "BITCOIN"
        assert result[0]["price"] == 47000.0
        assert result[0]["market_cap"] == 890000000000.0
        assert result[0]["change_24h"] == 2.5

    def test_transform_data(self, query_params):
        """Test data transformation."""
        query = CoinGeckoCryptoPriceFetcher.transform_query(query_params)
        
        # Simulate processed data
        processed_data = [
            {
                "symbol": "BITCOIN",
                "name": None,
                "price": 47000.0,
                "market_cap": 890000000000.0,
                "market_cap_rank": None,
                "volume_24h": 25000000000.0,
                "change_24h": 2.5,
                "last_updated": datetime(2022, 1, 1),
            }
        ]
        
        result = CoinGeckoCryptoPriceFetcher.transform_data(query, processed_data)
        
        assert len(result) == 1
        assert result[0].symbol == "BITCOIN"
        assert result[0].price == 47000.0
        assert result[0].change_24h == 2.5


class TestCoinGeckoCryptoSearchFetcher:
    """Test CoinGecko Crypto Search Fetcher."""

    @pytest.fixture
    def query_params(self):
        """Return query parameters for testing."""
        return {"query": "bitcoin"}

    @pytest.fixture
    def mock_search_data(self):
        """Return mock search data."""
        return {
            "coins": [
                {
                    "id": "bitcoin",
                    "name": "Bitcoin",
                    "symbol": "btc",
                    "market_cap_rank": 1,
                    "thumb": "https://assets.coingecko.com/coins/images/1/thumb/bitcoin.png",
                    "large": "https://assets.coingecko.com/coins/images/1/large/bitcoin.png",
                }
            ]
        }

    def test_transform_query(self, query_params):
        """Test query transformation."""
        result = CoinGeckoCryptoSearchFetcher.transform_query(query_params)
        assert isinstance(result, CoinGeckoCryptoSearchQueryParams)
        assert result.query == "bitcoin"

    @patch("openbb_coingecko.models.crypto_search.make_request")
    async def test_aextract_data(self, mock_request, query_params, mock_search_data):
        """Test data extraction."""
        mock_request.return_value = mock_search_data
        
        query = CoinGeckoCryptoSearchFetcher.transform_query(query_params)
        result = await CoinGeckoCryptoSearchFetcher.aextract_data(query, None)
        
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["symbol"] == "BTC"
        assert result[0]["name"] == "Bitcoin"
        assert result[0]["id"] == "bitcoin"

    def test_transform_data(self, query_params):
        """Test data transformation."""
        query = CoinGeckoCryptoSearchFetcher.transform_query(query_params)
        
        # Simulate processed data
        processed_data = [
            {
                "symbol": "BTC",
                "name": "Bitcoin",
                "id": "bitcoin",
                "api_symbol": "btc",
                "market_cap_rank": 1,
                "thumb": "https://assets.coingecko.com/coins/images/1/thumb/bitcoin.png",
                "large": "https://assets.coingecko.com/coins/images/1/large/bitcoin.png",
            }
        ]
        
        result = CoinGeckoCryptoSearchFetcher.transform_data(query, processed_data)
        
        assert len(result) == 1
        assert result[0].symbol == "BTC"
        assert result[0].name == "Bitcoin"
        assert result[0].id == "bitcoin"
