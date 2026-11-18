"""Binance Fetcher Tests."""

from datetime import datetime

import pytest
from openbb_binance.models.crypto_trades import BinanceCryptoTradesFetcher
from openbb_binance.utils.helpers import get_trade_side, normalize_symbol


MOCK_TRADES = [
    {
        "id": 28457,
        "price": "4.00000100",
        "qty": "12.00000000",
        "quoteQty": "48.000012",
        "time": 1499865549590,
        "isBuyerMaker": True,
        "isBestMatch": True,
    },
    {
        "id": 28458,
        "price": "4.10000100",
        "qty": "2.00000000",
        "quoteQty": "8.200002",
        "time": 1499865559590,
        "isBuyerMaker": False,
        "isBestMatch": True,
    },
]


def test_normalize_symbol():
    """Test symbol normalization."""
    assert normalize_symbol("BTCUSDT") == "BTCUSDT"
    assert normalize_symbol("BTC/USDT") == "BTCUSDT"
    assert normalize_symbol("BTC-USDT") == "BTCUSDT"


def test_get_trade_side():
    """Test Binance side conversion."""
    assert get_trade_side(True) == "sell"
    assert get_trade_side(False) == "buy"
    assert get_trade_side(None) is None


def test_transform_query():
    """Test query transformation."""
    params = {"symbol": "BTC/USDT", "limit": 100}
    query = BinanceCryptoTradesFetcher.transform_query(params)

    assert query.symbol == "BTCUSDT"
    assert query.limit == 100


def test_transform_data():
    """Test data transformation."""
    query = BinanceCryptoTradesFetcher.transform_query(
        {"symbol": "BTCUSDT", "limit": 2}
    )

    result = BinanceCryptoTradesFetcher.transform_data(query, MOCK_TRADES)

    assert len(result) == 2
    assert result[0].symbol == "BTCUSDT"
    assert result[0].exchange == "binance"
    assert result[0].trade_id == 28457
    assert result[0].price == 4.000001
    assert result[0].quantity == 12.0
    assert result[0].quote_quantity == 48.000012
    assert result[0].side == "sell"
    assert isinstance(result[0].timestamp, datetime)

    assert result[1].side == "buy"


def test_limit_validation():
    """Test max limit validation."""
    with pytest.raises(ValueError):
        BinanceCryptoTradesFetcher.transform_query(
            {"symbol": "BTCUSDT", "limit": 1001}
        )
