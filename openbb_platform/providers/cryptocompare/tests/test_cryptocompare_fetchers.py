"""Unit tests for the CryptoCompare provider."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
from openbb_core.app.service.user_service import UserService

# Ensure the local provider package is importable without needing installation.
sys.path.append(str(Path(__file__).resolve().parents[1]))

from openbb_cryptocompare.models.crypto_historical import (  # noqa: E402  pylint: disable=wrong-import-position
    CryptoCompareCryptoHistoricalFetcher,
)

test_credentials = UserService().default_user_settings.credentials.model_dump(
    mode="json"
)


@pytest.fixture(scope="module")
def vcr_config():
    """VCR configuration."""
    return {
        "filter_query_parameters": [("api_key", "MOCK_API_KEY")],
    }


@pytest.fixture(scope="module")
def sample_crypto_compare_payload():
    """Sample CryptoCompare response used to avoid live HTTP in tests."""
    return {
        "Response": "Success",
        "Message": "",
        "HasWarning": False,
        "Type": 100,
        "RateLimit": {},
        "Data": {
            "Aggregated": False,
            "TimeFrom": 1672444800,
            "TimeTo": 1672876800,
            "Data": [
                {
                    "time": 1672444800,
                    "high": 16650.12,
                    "low": 16400.0,
                    "open": 16510.42,
                    "close": 16580.33,
                    "volumefrom": 1324.5,
                    "volumeto": 21954230.12,
                    "conversionType": "direct",
                    "conversionSymbol": "",
                },
                {
                    "time": 1672531200,
                    "high": 16780.41,
                    "low": 16520.52,
                    "open": 16580.33,
                    "close": 16710.77,
                    "volumefrom": 1120.13,
                    "volumeto": 18723511.45,
                    "conversionType": "direct",
                    "conversionSymbol": "",
                },
                {
                    "time": 1672617600,
                    "high": 16840.85,
                    "low": 16640.13,
                    "open": 16710.77,
                    "close": 16795.14,
                    "volumefrom": 1211.88,
                    "volumeto": 20356444.58,
                    "conversionType": "direct",
                    "conversionSymbol": "",
                },
                {
                    "time": 1672704000,
                    "high": 16920.64,
                    "low": 16760.02,
                    "open": 16795.14,
                    "close": 16888.12,
                    "volumefrom": 1098.77,
                    "volumeto": 18564355.76,
                    "conversionType": "direct",
                    "conversionSymbol": "",
                },
                {
                    "time": 1672790400,
                    "high": 16980.91,
                    "low": 16810.17,
                    "open": 16888.12,
                    "close": 16940.55,
                    "volumefrom": 1455.02,
                    "volumeto": 24622590.61,
                    "conversionType": "direct",
                    "conversionSymbol": "",
                },
            ],
        },
        "SponsoredData": [],
    }


@pytest.mark.record_http
def test_crypto_compare_crypto_historical_fetcher(
    monkeypatch,
    sample_crypto_compare_payload,
):
    """Test CryptoCompare crypto historical fetcher."""
    credentials = test_credentials
    params = {
        "symbol": "BTC-USD",
        "start_date": date(2023, 1, 1),
        "end_date": date(2023, 1, 5),
        "interval": "1d",
    }

    async def _mock_get_data(*_args, **_kwargs):
        return sample_crypto_compare_payload

    monkeypatch.setattr(
        "openbb_cryptocompare.utils.helpers.get_cryptocompare_data",
        _mock_get_data,
    )

    fetcher = CryptoCompareCryptoHistoricalFetcher()
    result = fetcher.test(params, credentials)
    assert result is None
