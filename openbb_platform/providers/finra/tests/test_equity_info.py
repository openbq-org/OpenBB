"""Tests for the equity info model."""

import asyncio
import json
from datetime import date
from urllib.parse import urlparse

import pytest
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_finra.models.equity_info import (
    FinraEquityInfoData,
    FinraEquityInfoFetcher,
    _profile,
)


def _fetch(params):
    """Run the fetcher."""
    return asyncio.run(FinraEquityInfoFetcher.fetch_data(params, {}))


class TestProfiles:
    """Profiles join the lookup record to the static data."""

    def test_profiles(self, fake_session, response):
        """Stocks, ETFs, and funds resolve with their reference data."""
        fake_session("equity_info")
        result = {row.symbol: row for row in _fetch({"symbol": "AAPL,SPY,VFIAX,BRK-B"})}

        assert all(isinstance(row, FinraEquityInfoData) for row in result.values())
        assert set(result) == {"AAPL", "SPY", "VFIAX", "BRK.B"}

        apple = result["AAPL"]

        assert apple.cusip == "037833100"
        assert apple.stock_exchange == "XNAS"
        assert apple.sector == "Technology"
        assert apple.gics_sector == "Information Technology"
        assert apple.ipo_date == date(1980, 12, 12)
        assert apple.dividend_payment_date != apple.ex_dividend_date
        assert apple.morningstar_rating in {1, 2, 3, 4, 5}
        assert apple.security_type == "Stock"
        assert apple.fiscal_year_end_month == "September"
        assert result["SPY"].security_type == "ETF"

    def test_share_class_request(self, fake_session, response):
        """A hyphenated share class is looked up in the dotted form."""
        session = fake_session("equity_info")
        _fetch({"symbol": "AAPL,SPY,VFIAX,BRK-B"})

        assert session.calls[1]["params"] == {"symbol": "AAPL,SPY,VFIAX,BRK.B"}
        assert session.closed

    def test_unresolved(self, fake_session, response):
        """Symbols that resolve to nothing are empty."""
        fake_session(
            responder=lambda call: response(
                200,
                "\n"
                if urlparse(call["url"]).path == "/finralogin.jsp"
                else json.dumps({"Records": []}),
            )
        )

        with pytest.raises(EmptyDataError, match="No security resolved for ZZZZ"):
            _fetch({"symbol": "ZZZZ"})


class TestProfileMapping:
    """One profile maps a lookup record and its static data."""

    def test_fund_uses_fund_ranges(self):
        """Funds read their 52-week range and dividends from the fund fields."""
        profile = _profile(
            {"Ticker": "VFIAX", "Type": "FO"},
            {
                "secType": "FO",
                "os70c": "700.1",
                "os70e": "500.2",
                "os70d": "20260801",
                "os70f": "20260101",
                "ub170": "2026-06-30",
                "ub172": "2026-07-02",
                "st168": "1",
            },
        )

        assert profile["year_high"] == 700.1
        assert profile["year_low"] == 500.2
        assert profile["year_high_date"] == "2026-08-01"
        assert profile["ex_dividend_date"] == "2026-06-30"
        assert profile["dividend_payment_date"] == "2026-07-02"
        assert profile["url"] is None

    def test_missing_static_data(self):
        """A record without static data keeps its lookup fields."""
        profile = _profile({"Symbol": "X", "Name": "X Corp", "AA0A6": "1"}, {})

        assert profile["symbol"] == "X"
        assert profile["name"] == "X Corp"
        assert profile["is_adr"] is True
        assert profile["morningstar_rating"] is None
        assert profile["fiscal_year_end_month"] is None
