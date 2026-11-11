"""Tests for the Cboe model transform layers."""

import asyncio
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils.errors import EmptyDataError
from pandas import DataFrame

from openbb_cboe.models.available_indices import CboeAvailableIndicesFetcher
from openbb_cboe.models.equity_historical import CboeEquityHistoricalFetcher
from openbb_cboe.models.equity_quote import CboeEquityQuoteFetcher
from openbb_cboe.models.equity_search import CboeEquitySearchFetcher
from openbb_cboe.models.futures_curve import (
    CboeFuturesCurveFetcher,
    CboeFuturesCurveQueryParams,
)
from openbb_cboe.models.futures_instruments import CboeFuturesInstrumentsFetcher
from openbb_cboe.models.futures_settlements import (
    CboeFuturesSettlementsData,
    CboeFuturesSettlementsFetcher,
)
from openbb_cboe.models.index_constituents import CboeIndexConstituentsFetcher
from openbb_cboe.models.index_documents import (
    CboeIndexDocumentsFetcher,
    DocumentCategory,
    DocumentSymbol,
)
from openbb_cboe.models.index_historical import CboeIndexHistoricalFetcher
from openbb_cboe.models.index_search import CboeIndexSearchFetcher
from openbb_cboe.models.index_snapshots import (
    CboeIndexSnapshotsFetcher,
    CboeIndexSnapshotsQueryParams,
)
from openbb_cboe.models.options_chains import CboeOptionsChainsFetcher

DAILY_BARS = [
    {"date": "2024-01-02", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5},
    {"date": "2024-01-03", "open": 11.0, "high": 12.0, "low": 10.0, "close": 11.5},
]

INTRADAY_BARS = [
    {
        "datetime": "2024-01-02T09:30:00",
        "price": {"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5},
        "volume": {
            "stock_volume": 100,
            "calls_volume": 5,
            "puts_volume": 3,
            "total_options_volume": 8,
        },
    }
]


class TestAvailableIndices:
    """Available indices transforms."""

    def test_aliases_directory_columns(self, index_directory):
        """Directory columns are mapped onto the standard model aliases."""
        query = CboeAvailableIndicesFetcher.transform_query({"use_cache": False})

        with patch(
            "openbb_cboe.utils.helpers.get_index_directory",
            new=AsyncMock(return_value=index_directory),
        ):
            raw = asyncio.run(CboeAvailableIndicesFetcher.aextract_data(query, None))

        results = CboeAvailableIndicesFetcher.transform_data(query, raw)

        assert [r.symbol for r in results] == ["BUK100P", "AAVE10RP", "X2C"]
        assert results[0].name == "Cboe UK 100"
        assert results[-1].name == "CXA 200 Price Return Index"


class TestIndexSearch:
    """Index search filtering."""

    def test_search_by_name(self, index_directory):
        """A non-symbol query matches name, symbol, or description."""
        query = CboeIndexSearchFetcher.transform_query(
            {"query": "uk", "use_cache": False}
        )

        with patch(
            "openbb_cboe.utils.helpers.get_index_directory",
            new=AsyncMock(return_value=index_directory),
        ):
            raw = asyncio.run(CboeIndexSearchFetcher.aextract_data(query, None))

        results = CboeIndexSearchFetcher.transform_data(query, raw)

        assert [r.symbol for r in results] == ["BUK100P"]

    def test_search_by_symbol(self, index_directory):
        """is_symbol restricts matching to the ticker column."""
        query = CboeIndexSearchFetcher.transform_query(
            {"query": "AAVE", "is_symbol": True, "use_cache": False}
        )

        with patch(
            "openbb_cboe.utils.helpers.get_index_directory",
            new=AsyncMock(return_value=index_directory),
        ):
            raw = asyncio.run(CboeIndexSearchFetcher.aextract_data(query, None))

        results = CboeIndexSearchFetcher.transform_data(query, raw)

        assert [r.symbol for r in results] == ["AAVE10RP"]


class TestEquitySearch:
    """Equity search filtering."""

    def test_search_by_name(self, company_directory):
        """A non-symbol query matches the company name."""
        query = CboeEquitySearchFetcher.transform_query(
            {"query": "APPLE", "use_cache": False}
        )

        with patch(
            "openbb_cboe.utils.helpers.get_company_directory",
            new=AsyncMock(return_value=company_directory),
        ):
            raw = asyncio.run(CboeEquitySearchFetcher.aextract_data(query, None))

        results = CboeEquitySearchFetcher.transform_data(query, raw)

        assert [r.symbol for r in results] == ["AAPL"]

    def test_search_by_symbol_cleans_nan(self, company_directory):
        """NaN cells are coerced to None before validation."""
        directory = company_directory.copy()
        directory["dpm_name"] = float("nan")
        query = CboeEquitySearchFetcher.transform_query(
            {"query": "SPY", "is_symbol": True, "use_cache": False}
        )

        with patch(
            "openbb_cboe.utils.helpers.get_company_directory",
            new=AsyncMock(return_value=directory),
        ):
            raw = asyncio.run(CboeEquitySearchFetcher.aextract_data(query, None))

        results = CboeEquitySearchFetcher.transform_data(query, raw)

        assert results[0].symbol == "SPY"
        assert results[0].dpm_name is None


class TestEquityHistorical:
    """Equity historical query defaults and transforms."""

    def test_default_date_range(self):
        """A single symbol with no dates spans history through the NY session."""
        from openbb_cboe.utils.helpers import ny_today

        query = CboeEquityHistoricalFetcher.transform_query({"symbol": "AAPL"})

        assert query.start_date == date(1950, 1, 1)
        assert query.end_date == ny_today()

    def test_multi_symbol_default_window(self):
        """Multiple symbols default to a trailing 720-day window."""
        query = CboeEquityHistoricalFetcher.transform_query({"symbol": "AAPL,MSFT"})

        assert query.start_date > date(1950, 1, 1)

    def test_daily_transform(self):
        """Daily bars are filtered to the requested range."""
        query = CboeEquityHistoricalFetcher.transform_query(
            {"symbol": "AAPL", "start_date": "2024-01-03", "end_date": "2024-01-03"}
        )
        data = [{"symbol": "AAPL", "data": DAILY_BARS}]
        results = CboeEquityHistoricalFetcher.transform_data(query, data)

        assert len(results) == 1
        assert results[0].close == 11.5

    def test_intraday_transform_keeps_options_volume(self):
        """Intraday bars carry the calls/puts volume columns."""
        query = CboeEquityHistoricalFetcher.transform_query(
            {"symbol": "AAPL", "interval": "1m", "start_date": "2024-01-01"}
        )
        data = [{"symbol": "AAPL", "data": INTRADAY_BARS}]
        results = CboeEquityHistoricalFetcher.transform_data(query, data)

        assert results[0].calls_volume == 5
        assert results[0].volume == 100

    def test_multi_symbol_keeps_symbol_column(self):
        """The symbol column survives when more than one ticker is requested."""
        query = CboeEquityHistoricalFetcher.transform_query(
            {"symbol": "AAPL,MSFT", "start_date": "2024-01-01"}
        )
        data = [
            {"symbol": "AAPL", "data": DAILY_BARS},
            {"symbol": "MSFT", "data": DAILY_BARS},
        ]
        results = CboeEquityHistoricalFetcher.transform_data(query, data)

        assert {r.symbol for r in results} == {"AAPL", "MSFT"}

    def test_empty_raises(self):
        """An empty response raises EmptyDataError."""
        query = CboeEquityHistoricalFetcher.transform_query({"symbol": "AAPL"})

        with pytest.raises(EmptyDataError):
            CboeEquityHistoricalFetcher.transform_data(query, [])

    def test_url_uses_underscore_for_indices(self, index_directory):
        """Index and exception symbols get the underscore-prefixed endpoint."""
        query = CboeEquityHistoricalFetcher.transform_query({"symbol": "AAVE10RP"})
        captured: dict = {}

        async def _capture(urls, **kwargs):
            captured["urls"] = urls
            return []

        with (
            patch(
                "openbb_cboe.utils.helpers.get_index_directory",
                new=AsyncMock(return_value=index_directory),
            ),
            patch("openbb_core.provider.utils.helpers.amake_requests", new=_capture),
        ):
            asyncio.run(CboeEquityHistoricalFetcher.aextract_data(query, None))

        assert captured["urls"] == [
            "https://cdn.cboe.com/api/global/delayed_quotes/charts/historical/_AAVE10RP.json"
        ]

    def test_ticker_exception_warns(self, index_directory):
        """A ticker exception warns that only the current session is available."""
        query = CboeEquityHistoricalFetcher.transform_query({"symbol": "NDX"})

        async def _capture(urls, **kwargs):
            return []

        with (
            patch(
                "openbb_cboe.utils.helpers.get_index_directory",
                new=AsyncMock(return_value=index_directory),
            ),
            patch("openbb_core.provider.utils.helpers.amake_requests", new=_capture),
            pytest.warns(UserWarning, match="most recent trading day"),
        ):
            asyncio.run(CboeEquityHistoricalFetcher.aextract_data(query, None))


class TestIndexHistorical:
    """Index historical routing and transforms."""

    def test_daily_reads_the_published_history_files(self):
        """Daily levels come from the per-symbol full-history files."""
        query = CboeIndexHistoricalFetcher.transform_query({"symbol": "VIX,SPX"})
        history = [{"date": "01/02/1990", "close": "17.24"}]

        with patch(
            "openbb_cboe.utils.helpers.get_index_history",
            new=AsyncMock(return_value=history),
        ) as helper:
            raw = asyncio.run(CboeIndexHistoricalFetcher.aextract_data(query, None))

        assert [item["symbol"] for item in raw] == ["VIX", "SPX"]
        assert helper.await_count == 2

    def test_daily_transform_parses_us_date_format(self):
        """The published files use MM/DD/YYYY dates."""
        query = CboeIndexHistoricalFetcher.transform_query(
            {"symbol": "VIX", "start_date": "1990-01-01", "end_date": "1990-01-03"}
        )
        data = [
            {
                "symbol": "VIX",
                "data": [
                    {
                        "date": "01/02/1990",
                        "open": "17.24",
                        "high": "17.24",
                        "low": "17.24",
                        "close": "17.24",
                    }
                ],
            }
        ]
        results = CboeIndexHistoricalFetcher.transform_data(query, data)

        assert len(results) == 1
        assert results[0].date == date(1990, 1, 2)
        assert results[0].close == 17.24

    def test_daily_transform_close_only_series(self):
        """Close-only files validate with the OHLC fields left empty."""
        query = CboeIndexHistoricalFetcher.transform_query(
            {"symbol": "SPX", "start_date": "1975-01-01", "end_date": "1975-01-03"}
        )
        data = [{"symbol": "SPX", "data": [{"date": "01/02/1975", "close": "70.23"}]}]
        results = CboeIndexHistoricalFetcher.transform_data(query, data)

        assert results[0].close == 70.23
        assert results[0].open is None

    def test_multi_symbol_keeps_symbol_column(self):
        """The symbol column survives when more than one index is requested."""
        query = CboeIndexHistoricalFetcher.transform_query(
            {"symbol": "VIX,SPX", "start_date": "1990-01-01"}
        )
        bars = [{"date": "01/02/1990", "close": "17.24"}]
        data = [{"symbol": "VIX", "data": bars}, {"symbol": "SPX", "data": bars}]
        results = CboeIndexHistoricalFetcher.transform_data(query, data)

        assert {r.symbol for r in results} == {"VIX", "SPX"}

    def test_intraday_eu_index_url(self, index_directory):
        """European indices use the european_indices intraday endpoint."""
        query = CboeIndexHistoricalFetcher.transform_query(
            {"symbol": "BUK100P", "interval": "1m"}
        )
        captured: dict = {}

        async def _capture(urls, **kwargs):
            captured["urls"] = urls
            return []

        with (
            patch(
                "openbb_cboe.utils.helpers.get_index_directory",
                new=AsyncMock(return_value=index_directory),
            ),
            patch("openbb_core.provider.utils.helpers.amake_requests", new=_capture),
        ):
            asyncio.run(CboeIndexHistoricalFetcher.aextract_data(query, None))

        assert captured["urls"] == [
            "https://cdn.cboe.com/api/global/european_indices/"
            "intraday_chart_data/BUK100P.json"
        ]

    def test_intraday_us_index_url(self, index_directory):
        """US indices use the underscore-prefixed delayed-quotes chart endpoint."""
        query = CboeIndexHistoricalFetcher.transform_query(
            {"symbol": "AAVE10RP", "interval": "1m"}
        )
        captured: dict = {}

        async def _capture(urls, **kwargs):
            captured["urls"] = urls
            return []

        with (
            patch(
                "openbb_cboe.utils.helpers.get_index_directory",
                new=AsyncMock(return_value=index_directory),
            ),
            patch("openbb_core.provider.utils.helpers.amake_requests", new=_capture),
        ):
            asyncio.run(CboeIndexHistoricalFetcher.aextract_data(query, None))

        assert captured["urls"][0].endswith("/intraday/_AAVE10RP.json")

    def test_intraday_unlisted_symbol_url(self, index_directory):
        """A symbol outside the directory uses the plain chart endpoint."""
        query = CboeIndexHistoricalFetcher.transform_query(
            {"symbol": "NOTLISTED", "interval": "1m"}
        )
        captured: dict = {}

        async def _capture(urls, **kwargs):
            captured["urls"] = urls
            return []

        with (
            patch(
                "openbb_cboe.utils.helpers.get_index_directory",
                new=AsyncMock(return_value=index_directory),
            ),
            patch("openbb_core.provider.utils.helpers.amake_requests", new=_capture),
        ):
            asyncio.run(CboeIndexHistoricalFetcher.aextract_data(query, None))

        assert captured["urls"][0].endswith("/intraday/NOTLISTED.json")

    def test_intraday_ticker_exception_warns(self, index_directory):
        """A ticker exception warns that only the current session is available."""
        query = CboeIndexHistoricalFetcher.transform_query(
            {"symbol": "RUT", "interval": "1m"}
        )

        async def _capture(urls, **kwargs):
            return []

        with (
            patch(
                "openbb_cboe.utils.helpers.get_index_directory",
                new=AsyncMock(return_value=index_directory),
            ),
            patch("openbb_core.provider.utils.helpers.amake_requests", new=_capture),
            pytest.warns(UserWarning, match="most recent trading day"),
        ):
            asyncio.run(CboeIndexHistoricalFetcher.aextract_data(query, None))

    def test_intraday_transform(self):
        """Intraday index bars are flattened from the nested price dict."""
        query = CboeIndexHistoricalFetcher.transform_query(
            {"symbol": "AAVE10RP", "interval": "1m", "start_date": "2024-01-01"}
        )
        results = CboeIndexHistoricalFetcher.transform_data(
            query, [{"symbol": "AAVE10RP", "data": INTRADAY_BARS}]
        )

        assert results[0].close == 10.5

    def test_drops_string_volume_column(self):
        """Index files publish volume as a string zero, so the column is dropped."""
        query = CboeIndexHistoricalFetcher.transform_query(
            {"symbol": "AAVE10RP", "start_date": "2024-01-01"}
        )
        data = [
            {
                "symbol": "AAVE10RP",
                "data": [{"date": "01/02/2024", "close": "10.5", "volume": "0"}],
            }
        ]
        results = CboeIndexHistoricalFetcher.transform_data(query, data)

        assert results[0].volume is None
        assert results[0].close == 10.5

    def test_default_date_range(self):
        """A single index with no dates spans the full published history."""
        query = CboeIndexHistoricalFetcher.transform_query({"symbol": "AAVE10RP"})

        assert query.start_date == date(1950, 1, 1)

    def test_multi_symbol_default_window(self):
        """Multiple indices default to a trailing 720-day window."""
        query = CboeIndexHistoricalFetcher.transform_query(
            {"symbol": "AAVE10RP,BUK100P"}
        )

        assert query.start_date > date(1950, 1, 1)

    def test_empty_raises(self):
        """An empty response raises EmptyDataError."""
        query = CboeIndexHistoricalFetcher.transform_query({"symbol": "AAVE10RP"})

        with pytest.raises(EmptyDataError):
            CboeIndexHistoricalFetcher.transform_data(query, [])


class TestIndexSnapshots:
    """Index snapshot region routing and normalization."""

    @pytest.mark.parametrize(
        "region, expected",
        [
            ("us", "delayed_quotes/quotes/all_us_indices.json"),
            ("eu", "european_indices/index_quotes/all-indices.json"),
            ("au", "au_indices/index_quotes/all-indices.json"),
        ],
    )
    def test_region_url(self, region, expected):
        """Each region maps to its own snapshot endpoint."""
        query = CboeIndexSnapshotsFetcher.transform_query({"region": region})
        captured: dict = {}

        async def _capture(url, **kwargs):
            captured["url"] = url
            return {"data": []}

        with patch("openbb_core.provider.utils.helpers.amake_request", new=_capture):
            asyncio.run(CboeIndexSnapshotsFetcher.aextract_data(query, None))

        assert captured["url"].endswith(expected)

    def test_list_response_is_named(self, index_directory):
        """A bare list response is named from the index directory."""
        query = CboeIndexSnapshotsFetcher.transform_query({"region": "us"})

        async def _list(url, **kwargs):
            return [{"symbol": "^BUK100P"}, {"symbol": "NOTANINDEX"}]

        with (
            patch("openbb_core.provider.utils.helpers.amake_request", new=_list),
            patch(
                "openbb_cboe.utils.helpers.get_index_directory",
                new=AsyncMock(return_value=index_directory),
            ),
        ):
            raw = asyncio.run(CboeIndexSnapshotsFetcher.aextract_data(query, None))

        assert raw[0]["symbol"] == "BUK100P"
        assert raw[0]["name"] == "Cboe UK 100"
        assert "name" not in raw[1]

    def test_naming_survives_a_directory_failure(self):
        """A directory failure leaves the rows unnamed rather than failing."""
        query = CboeIndexSnapshotsFetcher.transform_query({"region": "us"})

        async def _list(url, **kwargs):
            return [{"symbol": "SPX"}]

        with (
            patch("openbb_core.provider.utils.helpers.amake_request", new=_list),
            patch(
                "openbb_cboe.utils.helpers.get_index_directory",
                new=AsyncMock(side_effect=Exception("down")),
            ),
        ):
            raw = asyncio.run(CboeIndexSnapshotsFetcher.aextract_data(query, None))

        assert raw == [{"symbol": "SPX"}]

    def test_percent_normalized_and_columns_dropped(self):
        """Percent columns are normalized and context columns removed."""
        query = CboeIndexSnapshotsFetcher.transform_query({"region": "us"})
        data = [
            {
                "symbol": "SPX",
                "current_price": 5000.0,
                "price_change_percent": 1.5,
                "exchange_id": 1,
                "seqno": 2,
                "security_type": "index",
            }
        ]
        results = CboeIndexSnapshotsFetcher.transform_data(query, data)

        assert results[0].change_percent == 0.015
        assert results[0].price == 5000.0

    def test_empty_raises(self):
        """An empty response raises EmptyDataError."""
        query = CboeIndexSnapshotsFetcher.transform_query({"region": "us"})

        with pytest.raises(EmptyDataError):
            CboeIndexSnapshotsFetcher.transform_data(query, [])

    def test_region_validator_falls_back_to_us(self):
        """A falsy region validates back to 'us'."""
        assert CboeIndexSnapshotsQueryParams.validate_region("") == "us"
        assert CboeIndexSnapshotsQueryParams.validate_region("eu") == "eu"


class TestIndexConstituents:
    """Index constituent transforms."""

    def test_au_constituents_carry_weights(self):
        """CXA files are mapped to weighted constituents, heaviest first."""
        query = CboeIndexConstituentsFetcher.transform_query({"symbol": "X2C"})
        data = [
            {
                "Constituent Name": "BHP Group Ltd",
                "Symbol": "BHP",
                "Weight": "0.11176",
                "Closing Price": "42.5",
                "ISIN Code": "AU000000BHP4",
                "SEDOL Code": "5974437",
                "GICS": "15104020",
                "Currency": "AUD",
                "Shares in Issue": "5070000000.5",
                "Float Ratio": "1",
                "Total Market Capitalisation": "215475000000",
                "Adjusted Market Capitalisation": "215475000000",
            },
            {
                "Constituent Name": "Unlisted Line",
                "Symbol": "",
                "Weight": "0.0005",
                "Closing Price": "1.0",
                "ISIN Code": "AU0000000001",
                "SEDOL Code": "BMX3786",
                "GICS": "35103010",
                "Currency": "AUD",
            },
        ]
        results = CboeIndexConstituentsFetcher.transform_data(query, data)

        assert [r.symbol for r in results] == ["BHP", "BMX3786"]
        assert results[0].weight == 0.11176
        assert results[0].isin == "AU000000BHP4"
        assert results[0].shares_outstanding == 5070000000.5

    def test_au_routes_to_the_file_helper(self):
        """A CXA symbol reads the daily constituent file, not the EU endpoint."""
        query = CboeIndexConstituentsFetcher.transform_query(
            {"symbol": "X2CG", "session": "sod"}
        )

        with patch(
            "openbb_cboe.utils.helpers.get_au_index_constituents",
            new=AsyncMock(return_value=[{"Weight": "1"}]),
        ) as helper:
            raw = asyncio.run(CboeIndexConstituentsFetcher.aextract_data(query, None))

        assert raw == [{"Weight": "1"}]
        helper.assert_awaited_once_with("X2CG", session="sod")

    def test_transform(self):
        """Percent change is normalized and context columns dropped."""
        query = CboeIndexConstituentsFetcher.transform_query({"symbol": "BUK100P"})
        data = [
            {
                "symbol": "SHEL",
                "current_price": 25.0,
                "price_change_percent": 2.0,
                "exchange_id": 1,
                "last_trade_time": "2024-06-27T16:00:00",
                "type": "stock",
            }
        ]
        results = CboeIndexConstituentsFetcher.transform_data(query, data)

        assert results[0].change_percent == 0.02
        assert results[0].last_trade_time == datetime(2024, 6, 27, 16, 0)

    def test_dict_response_unwrapped(self):
        """A dict response is unwrapped from its data key."""
        query = CboeIndexConstituentsFetcher.transform_query({"symbol": "BUK100P"})

        async def _dict(url, **kwargs):
            return {"data": [{"symbol": "SHEL"}]}

        async def _names(use_cache=True):
            return {"SHEL": "Shell PLC"}

        with (
            patch("openbb_core.provider.utils.helpers.amake_request", new=_dict),
            patch("openbb_cboe.utils.europe.get_eu_company_names", new=_names),
        ):
            raw = asyncio.run(CboeIndexConstituentsFetcher.aextract_data(query, None))

        assert raw == [{"symbol": "SHEL", "name": "Shell PLC"}]

    def test_empty_rows_skip_naming(self):
        """An empty payload is returned before the symbology is fetched."""
        query = CboeIndexConstituentsFetcher.transform_query({"symbol": "BUK100P"})

        async def _dict(url, **kwargs):
            return {"data": []}

        with patch("openbb_core.provider.utils.helpers.amake_request", new=_dict):
            raw = asyncio.run(CboeIndexConstituentsFetcher.aextract_data(query, None))

        assert raw == []

    def test_naming_survives_a_symbology_failure(self):
        """A symbology failure leaves the constituents unnamed."""
        query = CboeIndexConstituentsFetcher.transform_query({"symbol": "BUK100P"})

        async def _dict(url, **kwargs):
            return {"data": [{"symbol": "SHEL-LN"}]}

        with (
            patch("openbb_core.provider.utils.helpers.amake_request", new=_dict),
            patch(
                "openbb_cboe.utils.europe.get_eu_company_names",
                new=AsyncMock(side_effect=Exception("down")),
            ),
        ):
            raw = asyncio.run(CboeIndexConstituentsFetcher.aextract_data(query, None))

        assert raw == [{"symbol": "SHEL-LN"}]

    def test_empty_raises(self):
        """An empty response raises EmptyDataError."""
        query = CboeIndexConstituentsFetcher.transform_query({"symbol": "BUK100P"})

        with pytest.raises(EmptyDataError):
            CboeIndexConstituentsFetcher.transform_data(query, [])


class TestIndexDocuments:
    """Index documents catalog model."""

    def test_full_catalog(self):
        """With no filters the whole bundled catalog validates."""
        query = CboeIndexDocumentsFetcher.transform_query({})
        raw = asyncio.run(CboeIndexDocumentsFetcher.aextract_data(query, None))
        results = CboeIndexDocumentsFetcher.transform_data(query, raw)

        assert len(results) == len(raw)
        assert all(r.url.startswith("https://cdn.cboe.com/") for r in results)
        assert any(r.symbols for r in results)

    def test_symbol_scope_prepends_a_published_factsheet(self):
        """A symbol keeps its own and the global documents, factsheet first."""
        query = CboeIndexDocumentsFetcher.transform_query({"symbol": "x2c"})

        with patch(
            "openbb_cboe.utils.helpers.amake_request",
            new=AsyncMock(return_value=200),
        ):
            raw = asyncio.run(CboeIndexDocumentsFetcher.aextract_data(query, None))

        results = CboeIndexDocumentsFetcher.transform_data(query, raw)
        titles = [r.title for r in results]

        assert query.symbol == "X2C"
        assert results[0].category == "Factsheet"
        assert results[0].url.endswith("CboeGlobalIndices_X2C-Index.pdf")
        assert "Cboe Australia CXA 200 Index Methodology" in titles
        assert "Cboe Index Policies & Practices" in titles
        assert "SPBFA Constituents" not in titles

    def test_category_filter(self):
        """A category restricts the catalog to that category."""
        query = CboeIndexDocumentsFetcher.transform_query({"category": "Governance"})
        raw = asyncio.run(CboeIndexDocumentsFetcher.aextract_data(query, None))
        results = CboeIndexDocumentsFetcher.transform_data(query, raw)

        assert results
        assert {r.category for r in results} == {"Governance"}

    def test_no_matches_raises(self):
        """A filter that leaves nothing raises EmptyDataError."""
        query = CboeIndexDocumentsFetcher.transform_query({"category": "Factsheet"})

        with pytest.raises(EmptyDataError):
            CboeIndexDocumentsFetcher.transform_data(
                query, [{"category": "Governance", "title": "t", "url": "u"}]
            )

    def test_symbol_outside_the_catalog_is_rejected(self):
        """The symbol Literal admits only the symbols the catalog tags."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CboeIndexDocumentsFetcher.transform_query({"symbol": "NOPE"})

    def test_literals_track_the_catalog(self):
        """The query Literals stay in lockstep with the bundled asset."""
        import json
        from pathlib import Path
        from typing import get_args

        import openbb_cboe

        catalog = json.loads(
            (
                Path(openbb_cboe.__file__).parent / "assets" / "index_documents.json"
            ).read_text(encoding="utf-8")
        )
        symbols: set = set()

        for doc in catalog:
            symbols.update(doc.get("symbols") or [])

        assert set(get_args(DocumentCategory)) == {doc["category"] for doc in catalog}
        assert set(get_args(DocumentSymbol)) == symbols


class TestEquityQuote:
    """Equity quote merging and normalization."""

    def test_transform_normalizes_percent_columns(self):
        """Percent and volatility columns are divided by 100."""
        query = CboeEquityQuoteFetcher.transform_query({"symbol": "AAPL"})
        frame = DataFrame(
            [{"price_change_percent": 2.0, "iv30": 25.0, "current_price": 190.0}],
            index=["AAPL"],
        )
        frame.index.name = "symbol"
        results = CboeEquityQuoteFetcher.transform_data(query, frame)

        assert results[0].change_percent == 0.02
        assert results[0].iv30 == 0.25

    def test_extract_merges_quotes_and_iv(self, index_directory, company_directory):
        """Quote and IV payloads are merged, and names filled from the directories."""
        query = CboeEquityQuoteFetcher.transform_query(
            {"symbol": "AAPL", "use_cache": False}
        )
        responses = [
            [{"data": {"symbol": "AAPL", "current_price": 190.0, "seqno": 1}}],
            [{"data": {"symbol": "AAPL", "iv30": 25.0}}],
        ]

        async def _requests(urls, **kwargs):
            return responses.pop(0)

        with (
            patch(
                "openbb_cboe.utils.helpers.get_company_directory",
                new=AsyncMock(return_value=company_directory),
            ),
            patch(
                "openbb_cboe.utils.helpers.get_index_directory",
                new=AsyncMock(return_value=index_directory),
            ),
            patch("openbb_core.provider.utils.helpers.amake_requests", new=_requests),
        ):
            frame = asyncio.run(CboeEquityQuoteFetcher.aextract_data(query, None))

        assert frame.loc["AAPL", "iv30"] == 25.0
        assert frame.loc["AAPL", "name"] == "APPLE INC"
        assert "seqno" not in frame.columns

    def test_eu_index_uses_european_endpoint(self, index_directory, company_directory):
        """European indices route to the european_indices quote endpoint."""
        query = CboeEquityQuoteFetcher.transform_query(
            {"symbol": "BUK100P", "use_cache": False}
        )
        captured: list = []

        async def _requests(urls, **kwargs):
            captured.append(urls)
            return [{"data": {"symbol": "BUK100P", "current_price": 800.0}}]

        with (
            patch(
                "openbb_cboe.utils.helpers.get_company_directory",
                new=AsyncMock(return_value=company_directory),
            ),
            patch(
                "openbb_cboe.utils.helpers.get_index_directory",
                new=AsyncMock(return_value=index_directory),
            ),
            patch("openbb_core.provider.utils.helpers.amake_requests", new=_requests),
        ):
            asyncio.run(CboeEquityQuoteFetcher.aextract_data(query, None))

        assert "european_indices" in captured[0][0]
        assert captured[1] == []

    def test_drops_redundant_index_column(self, index_directory, company_directory):
        """European payloads carry a duplicate 'index' column that is dropped."""
        query = CboeEquityQuoteFetcher.transform_query(
            {"symbol": "BUK100P", "use_cache": False}
        )

        async def _requests(urls, **kwargs):
            if not urls:
                return []
            return [
                {
                    "data": {
                        "symbol": "BUK100P",
                        "index": "BUK100P",
                        "current_price": 800.0,
                    }
                }
            ]

        with (
            patch(
                "openbb_cboe.utils.helpers.get_company_directory",
                new=AsyncMock(return_value=company_directory),
            ),
            patch(
                "openbb_cboe.utils.helpers.get_index_directory",
                new=AsyncMock(return_value=index_directory),
            ),
            patch("openbb_core.provider.utils.helpers.amake_requests", new=_requests),
        ):
            frame = asyncio.run(CboeEquityQuoteFetcher.aextract_data(query, None))

        assert "index" not in frame.columns

    def test_no_responses_raises(self, index_directory, company_directory):
        """No quote responses raises EmptyDataError."""
        query = CboeEquityQuoteFetcher.transform_query(
            {"symbol": "AAPL", "use_cache": False}
        )

        async def _requests(urls, **kwargs):
            return []

        with (
            patch(
                "openbb_cboe.utils.helpers.get_company_directory",
                new=AsyncMock(return_value=company_directory),
            ),
            patch(
                "openbb_cboe.utils.helpers.get_index_directory",
                new=AsyncMock(return_value=index_directory),
            ),
            patch("openbb_core.provider.utils.helpers.amake_requests", new=_requests),
            pytest.raises(EmptyDataError),
        ):
            asyncio.run(CboeEquityQuoteFetcher.aextract_data(query, None))


class TestFuturesCurve:
    """Futures curve symbol handling."""

    @pytest.mark.parametrize("value", ["vix", "^vix", "vx", "vix_index", ""])
    def test_symbol_aliases(self, value):
        """VIX aliases resolve to the end-of-day curve."""
        assert CboeFuturesCurveQueryParams.validate_symbol(value) == "VX_EOD"

    def test_symbol_upper_cased(self):
        """Any other symbol is upper-cased."""
        assert CboeFuturesCurveQueryParams.validate_symbol("vx_am") == "VX_AM"

    def test_current_curve(self):
        """Omitting the date requests the live curve."""
        query = CboeFuturesCurveFetcher.transform_query({"symbol": "VX_EOD"})
        curve = DataFrame({"expiration": ["2024-07"], "price": [13.0]})

        with patch(
            "openbb_cboe.utils.vix.get_vx_current", new=AsyncMock(return_value=curve)
        ):
            raw = asyncio.run(CboeFuturesCurveFetcher.aextract_data(query, None))

        results = CboeFuturesCurveFetcher.transform_data(query, raw)

        assert results[0].price == 13.0

    def test_dated_curve(self):
        """Supplying a date requests the historical curve."""
        query = CboeFuturesCurveFetcher.transform_query(
            {"symbol": "VX_AM", "date": "2024-06-27"}
        )
        curve = DataFrame(
            {"expiration": ["2024-07"], "price": [13.0], "symbol": ["VX1"]}
        )

        with patch(
            "openbb_cboe.utils.vix.get_vx_by_date", new=AsyncMock(return_value=curve)
        ):
            raw = asyncio.run(CboeFuturesCurveFetcher.aextract_data(query, None))

        results = CboeFuturesCurveFetcher.transform_data(query, raw)

        assert results[0].symbol == "VX1"

    def test_empty_raises(self):
        """An empty curve raises EmptyDataError."""
        query = CboeFuturesCurveFetcher.transform_query({"symbol": "VX_EOD"})

        with (
            patch(
                "openbb_cboe.utils.vix.get_vx_current",
                new=AsyncMock(return_value=DataFrame()),
            ),
            pytest.raises(EmptyDataError),
        ):
            asyncio.run(CboeFuturesCurveFetcher.aextract_data(query, None))

    def test_multi_date_curves_pivot_by_contract(self):
        """Multiple dates pivot to one row per contract, sessions as columns."""
        query = CboeFuturesCurveFetcher.transform_query(
            {"symbol": "VX_EOD", "date": "2024-06-25,2024-06-26"}
        )
        data = [
            {"symbol": "VX2", "date": "2024-06-25", "price": 14.0},
            {"symbol": "VX1", "date": "2024-06-25", "price": 13.0},
            {"symbol": "VX1", "date": "2024-06-26", "price": 13.5},
            {"symbol": "VX", "date": "2024-06-26", "price": 12.9},
            {"symbol": None, "date": "2024-06-26", "price": 1.0},
        ]
        results = CboeFuturesCurveFetcher.transform_data(query, data)

        assert [r.symbol for r in results] == ["VX1", "VX2", "VX"]
        assert results[0].model_extra["2024-06-25"] == 13.0
        assert results[0].model_extra["2024-06-26"] == 13.5
        assert results[1].model_extra["2024-06-26"] is None


class TestFuturesInstruments:
    """Futures instrument listing."""

    def test_extract_reads_the_roots_directory(self):
        """The instruments come straight from the futures roots directory."""
        query = CboeFuturesInstrumentsFetcher.transform_query({})
        roots = [
            {
                "future_root": "VX",
                "name": "Cboe Volatility Index Futures",
                "family": "Volatility",
                "underlying": "VIX",
            }
        ]

        with patch(
            "openbb_cboe.utils.helpers.list_futures",
            new=AsyncMock(return_value=roots),
        ):
            raw = asyncio.run(CboeFuturesInstrumentsFetcher.aextract_data(query, None))

        results = CboeFuturesInstrumentsFetcher.transform_data(query, raw)

        assert results[0].future_root == "VX"
        assert results[0].underlying == "VIX"

    def test_empty_raises(self):
        """An empty roots directory raises EmptyDataError."""
        query = CboeFuturesInstrumentsFetcher.transform_query({})

        with (
            patch(
                "openbb_cboe.utils.helpers.list_futures",
                new=AsyncMock(return_value=[]),
            ),
            pytest.raises(EmptyDataError),
        ):
            asyncio.run(CboeFuturesInstrumentsFetcher.aextract_data(query, None))


class TestFuturesSettlements:
    """Futures settlement price extraction."""

    def test_extract_purges_nan_cells(self):
        """NaN cells are converted to None before validation."""
        query = CboeFuturesSettlementsFetcher.transform_query({"date": "2024-06-27"})
        frame = DataFrame(
            [
                {
                    "product": "VX",
                    "symbol": "VX/N4",
                    "expiration": "2024-06-27",
                    "price": 12.5,
                    "duration_type": float("nan"),
                    "settlement_date": "06/27/2024",
                }
            ]
        )

        with patch(
            "openbb_cboe.utils.helpers.get_settlement_prices",
            new=AsyncMock(return_value=frame),
        ) as helper:
            raw = asyncio.run(CboeFuturesSettlementsFetcher.aextract_data(query, None))

        results = CboeFuturesSettlementsFetcher.transform_data(query, raw)

        assert raw[0]["duration_type"] is None
        assert results[0].settlement_date == date(2024, 6, 27)
        assert results[0].price == 12.5
        helper.assert_awaited_once_with(
            settlement_date=date(2024, 6, 27),
            options=False,
            archives=False,
            final_settlement=False,
        )

    def test_non_numeric_price_is_null(self):
        """The options file prints CAB for cabinet trades; that price is null."""
        csv = (
            "Product,Symbol,Expiration Date,Price\n"
            "IBYO,IBYO/H7 P16800,2027-03-01,0.7389\n"
            "IBYO,IBYO/Z6 P17000,2026-12-01,CAB\n"
        )
        query = CboeFuturesSettlementsFetcher.transform_query({"options": True})

        with patch(
            "openbb_cboe.utils.helpers.get_cboe_data", new=AsyncMock(return_value=csv)
        ):
            raw = asyncio.run(CboeFuturesSettlementsFetcher.aextract_data(query, None))

        results = CboeFuturesSettlementsFetcher.transform_data(query, raw)

        assert [r.price for r in results] == [0.7389, None]

    def test_empty_raises(self):
        """A session with no published prices raises EmptyDataError."""
        query = CboeFuturesSettlementsFetcher.transform_query({})

        with (
            patch(
                "openbb_cboe.utils.helpers.get_settlement_prices",
                new=AsyncMock(return_value=DataFrame()),
            ),
            pytest.raises(EmptyDataError),
        ):
            asyncio.run(CboeFuturesSettlementsFetcher.aextract_data(query, None))

    def test_settlement_date_validator(self):
        """The settlement date parses from US formatting and passes None through."""
        parsed = CboeFuturesSettlementsData.validate_settlement_date("06/27/2024")

        assert parsed == date(2024, 6, 27)
        assert CboeFuturesSettlementsData.validate_settlement_date(None) is None


class TestOptionsChains:
    """Options chain extraction and transformation."""

    def test_transform_parses_contracts(self, raw_options_chain):
        """Contract symbols are parsed into expiration, strike, and type."""
        query = CboeOptionsChainsFetcher.transform_query({"symbol": "CLX"})
        result = CboeOptionsChainsFetcher.transform_data(query, raw_options_chain)

        assert result.metadata["symbol"] == "CLX"
        assert set(result.result.option_type) == {"call", "put"}
        assert result.result.dte

    def test_normalizes_underlying_percentages(self, raw_options_chain):
        """The underlying percent-change fields are normalized in the metadata."""
        raw_options_chain["data"]["percent_change"] = 2.0
        raw_options_chain["data"]["iv30_change_percent"] = 5.0
        query = CboeOptionsChainsFetcher.transform_query({"symbol": "CLX"})
        result = CboeOptionsChainsFetcher.transform_data(query, raw_options_chain)

        assert result.metadata["change_percent"] == 0.02
        assert result.metadata["iv30_change_percent"] == 0.05

    def test_empty_raises(self):
        """An empty response raises EmptyDataError."""
        query = CboeOptionsChainsFetcher.transform_query({"symbol": "CLX"})

        with pytest.raises(EmptyDataError):
            CboeOptionsChainsFetcher.transform_data(query, {})

    def test_unknown_symbol_raises(self, index_directory, company_directory):
        """A symbol outside the options directory raises."""
        query = CboeOptionsChainsFetcher.transform_query({"symbol": "NOPE"})

        with (
            patch(
                "openbb_cboe.utils.helpers.get_index_directory",
                new=AsyncMock(return_value=index_directory),
            ),
            patch(
                "openbb_cboe.utils.helpers.get_company_directory",
                new=AsyncMock(return_value=company_directory),
            ),
            pytest.raises(OpenBBError, match="not found"),
        ):
            asyncio.run(CboeOptionsChainsFetcher.aextract_data(query, None))

    def test_extract_builds_symbol_url(self, index_directory, company_directory):
        """A listed equity symbol uses the plain options endpoint."""
        query = CboeOptionsChainsFetcher.transform_query({"symbol": "AAPL"})
        captured: dict = {}

        async def _request(url, **kwargs):
            captured["url"] = url
            return {"data": {}}

        with (
            patch(
                "openbb_cboe.utils.helpers.get_index_directory",
                new=AsyncMock(return_value=index_directory),
            ),
            patch(
                "openbb_cboe.utils.helpers.get_company_directory",
                new=AsyncMock(return_value=company_directory),
            ),
            patch("openbb_core.provider.utils.helpers.amake_request", new=_request),
        ):
            asyncio.run(CboeOptionsChainsFetcher.aextract_data(query, None))

        assert captured["url"].endswith("/options/AAPL.json")
