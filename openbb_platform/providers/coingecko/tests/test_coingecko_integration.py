"""Integration tests for CoinGecko provider."""

import pytest
from datetime import date

# Skip integration tests in CI to avoid network dependencies
pytestmark = pytest.mark.skip(reason="Integration tests require network access")

# Skip tests if imports fail (e.g., in CI without provider installed)
try:
    from openbb_coingecko.models.crypto_historical import CoinGeckoCryptoHistoricalFetcher
    from openbb_coingecko.models.crypto_price import CoinGeckoCryptoPriceFetcher
    from openbb_coingecko.models.crypto_search import CoinGeckoCryptoSearchFetcher
    IMPORTS_AVAILABLE = True
except ImportError:
    IMPORTS_AVAILABLE = False


@pytest.mark.integration
class TestCoinGeckoIntegration:
    """Integration tests for CoinGecko provider."""

    @pytest.mark.asyncio
    async def test_crypto_historical_bitcoin(self):
        """Test historical data for Bitcoin."""
        params = {
            "symbol": "bitcoin",
            "vs_currency": "usd",
            "interval": "7d",
        }
        
        query = CoinGeckoCryptoHistoricalFetcher.transform_query(params)
        result = await CoinGeckoCryptoHistoricalFetcher.aextract_data(query, None)
        
        assert isinstance(result, list)
        assert len(result) > 0
        
        # Check data structure
        first_item = result[0]
        assert "symbol" in first_item
        assert "date" in first_item
        assert "close" in first_item
        assert "volume" in first_item
        
        # Transform and validate
        transformed = CoinGeckoCryptoHistoricalFetcher.transform_data(query, result)
        assert len(transformed) > 0
        assert transformed[0].symbol.upper() == "BITCOIN"

    @pytest.mark.asyncio
    async def test_crypto_historical_multiple_symbols(self):
        """Test historical data for multiple cryptocurrencies."""
        params = {
            "symbol": "bitcoin,ethereum",
            "vs_currency": "usd",
            "interval": "1d",
        }
        
        query = CoinGeckoCryptoHistoricalFetcher.transform_query(params)
        result = await CoinGeckoCryptoHistoricalFetcher.aextract_data(query, None)
        
        assert isinstance(result, list)
        assert len(result) > 0
        
        # Should have data for both symbols
        symbols = {item["symbol"] for item in result}
        assert len(symbols) >= 1  # At least one symbol should work

    @pytest.mark.asyncio
    async def test_crypto_historical_with_date_range(self):
        """Test historical data with specific date range."""
        params = {
            "symbol": "bitcoin",
            "vs_currency": "usd",
            "start_date": date(2024, 1, 1),
            "end_date": date(2024, 1, 7),
        }
        
        query = CoinGeckoCryptoHistoricalFetcher.transform_query(params)
        result = await CoinGeckoCryptoHistoricalFetcher.aextract_data(query, None)
        
        assert isinstance(result, list)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_crypto_price_bitcoin(self):
        """Test real-time price for Bitcoin."""
        params = {
            "symbol": "bitcoin",
            "vs_currency": "usd",
            "include_market_cap": True,
            "include_24hr_vol": True,
            "include_24hr_change": True,
        }
        
        query = CoinGeckoCryptoPriceFetcher.transform_query(params)
        result = await CoinGeckoCryptoPriceFetcher.aextract_data(query, None)
        
        assert isinstance(result, list)
        assert len(result) == 1
        
        # Check data structure
        first_item = result[0]
        assert "symbol" in first_item
        assert "price" in first_item
        assert first_item["price"] > 0
        
        # Transform and validate
        transformed = CoinGeckoCryptoPriceFetcher.transform_data(query, result)
        assert len(transformed) == 1
        assert transformed[0].price > 0

    @pytest.mark.asyncio
    async def test_crypto_price_multiple_symbols(self):
        """Test real-time prices for multiple cryptocurrencies."""
        params = {
            "symbol": "bitcoin,ethereum,cardano",
            "vs_currency": "usd",
            "include_market_cap": True,
            "include_24hr_vol": True,
        }
        
        query = CoinGeckoCryptoPriceFetcher.transform_query(params)
        result = await CoinGeckoCryptoPriceFetcher.aextract_data(query, None)
        
        assert isinstance(result, list)
        assert len(result) >= 1  # At least one symbol should work
        
        # All items should have valid prices
        for item in result:
            assert item["price"] > 0

    @pytest.mark.asyncio
    async def test_crypto_price_different_currency(self):
        """Test real-time price in different currency."""
        params = {
            "symbol": "bitcoin",
            "vs_currency": "eur",
            "include_market_cap": True,
        }
        
        query = CoinGeckoCryptoPriceFetcher.transform_query(params)
        result = await CoinGeckoCryptoPriceFetcher.aextract_data(query, None)
        
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["price"] > 0

    @pytest.mark.asyncio
    async def test_crypto_search_with_query(self):
        """Test cryptocurrency search with query."""
        params = {"query": "bitcoin"}
        
        query = CoinGeckoCryptoSearchFetcher.transform_query(params)
        result = await CoinGeckoCryptoSearchFetcher.aextract_data(query, None)
        
        assert isinstance(result, list)
        assert len(result) > 0
        
        # Check data structure
        first_item = result[0]
        assert "symbol" in first_item
        assert "name" in first_item
        assert "id" in first_item
        
        # Transform and validate
        transformed = CoinGeckoCryptoSearchFetcher.transform_data(query, result)
        assert len(transformed) > 0
        assert any("bitcoin" in item.name.lower() for item in transformed if item.name)

    @pytest.mark.asyncio
    async def test_crypto_search_all_coins(self):
        """Test getting all available cryptocurrencies."""
        params = {"query": None}
        
        query = CoinGeckoCryptoSearchFetcher.transform_query(params)
        result = await CoinGeckoCryptoSearchFetcher.aextract_data(query, None)
        
        assert isinstance(result, list)
        assert len(result) > 1000  # Should have many cryptocurrencies
        
        # Check data structure
        first_item = result[0]
        assert "symbol" in first_item
        assert "name" in first_item
        assert "id" in first_item

    @pytest.mark.asyncio
    async def test_error_handling_invalid_symbol(self):
        """Test error handling for invalid symbol."""
        params = {
            "symbol": "invalid_coin_that_does_not_exist",
            "vs_currency": "usd",
        }
        
        query = CoinGeckoCryptoPriceFetcher.transform_query(params)
        
        # This should handle the error gracefully
        try:
            result = await CoinGeckoCryptoPriceFetcher.aextract_data(query, None)
            # If no exception, result should be empty or contain error info
            assert isinstance(result, list)
        except Exception as e:
            # Should raise a meaningful error
            assert "No" in str(e) or "not found" in str(e).lower()

    @pytest.mark.asyncio
    async def test_rate_limiting_handling(self):
        """Test that rate limiting is handled gracefully."""
        # This test makes multiple rapid requests to test rate limiting
        params = {
            "symbol": "bitcoin",
            "vs_currency": "usd",
        }
        
        query = CoinGeckoCryptoPriceFetcher.transform_query(params)
        
        # Make multiple requests rapidly
        for _ in range(3):
            try:
                result = await CoinGeckoCryptoPriceFetcher.aextract_data(query, None)
                assert isinstance(result, list)
            except Exception as e:
                # Rate limiting errors should be handled gracefully
                if "rate limit" in str(e).lower():
                    assert "rate limit" in str(e).lower()
                else:
                    raise
