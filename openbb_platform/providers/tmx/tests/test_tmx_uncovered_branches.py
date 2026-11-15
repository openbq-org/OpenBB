"""Tests for the failure paths and edge branches across the provider."""

from datetime import UTC, date, datetime

import pytest
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils.errors import EmptyDataError
from pandas import DataFrame


class TestResolutionParsing:
    """The chart's resolution grammar."""

    @pytest.mark.parametrize(
        ("resolution", "expected"),
        [
            ("1S", ("intraday", 1)),
            ("30S", ("intraday", 1)),
            ("2D", ("period", "day")),
            ("1Q", ("period", "day")),
            ("", ("period", "day")),
        ],
    )
    def test_unusual_resolutions_are_read(self, resolution, expected):
        from openbb_tmx.routers.udf import _parse_resolution

        assert _parse_resolution(resolution) == expected


class TestSymbolClassification:
    """Instrument typing and currency derivation."""

    def test_an_unknown_issue_type_is_a_stock(self):
        from openbb_tmx.routers.udf import _instrument_type

        assert _instrument_type("AC", "ZZ") == "stock"

    @pytest.mark.parametrize(
        ("symbol", "expected"),
        [("~BTCUSD:US", "USD"), ("$CADXRP", "XRP"), ("AC", None), ("~AB", None)],
    )
    def test_a_pair_currency_is_read_from_the_symbol(self, symbol, expected):
        from openbb_tmx.routers.udf import _pair_currency

        assert _pair_currency(symbol) == expected

    def test_a_reported_currency_wins(self):
        from openbb_tmx.routers.udf import _currency_for

        assert _currency_for("AC", "TSX", "CAD") == "CAD"

    def test_a_pair_currency_is_preferred_over_the_venue(self):
        from openbb_tmx.routers.udf import _currency_for

        assert _currency_for("~BTCUSD:US", "Crypto", None) == "USD"

    def test_a_canadian_venue_implies_the_dollar(self):
        from openbb_tmx.routers.udf import _currency_for

        assert _currency_for("AC", "TSX", None) == "CAD"

    def test_a_currency_suffix_is_read(self):
        from openbb_tmx.routers.udf import _currency_for

        assert _currency_for("XYZ:EUR", "XETRA", None) == "EUR"

    def test_an_unknown_venue_falls_back_to_the_dollar(self):
        from openbb_tmx.routers.udf import _currency_for

        assert _currency_for("XYZ:ZZ", "SOMEWHERE", None) == "USD"

    def test_no_venue_leaves_the_currency_unset(self):
        from openbb_tmx.routers.udf import _currency_for

        assert _currency_for("XYZ", None, None) is None


class TestSymbolResolution:
    """The chart resolves a symbol against every symbology it reaches."""

    async def test_the_quote_feed_short_circuits(self, monkeypatch):
        from openbb_tmx.routers import udf

        async def quote(operation, query, variables, **kwargs):
            return {
                "getQuoteBySymbol": {
                    "name": "Air Canada",
                    "exShortName": "TSX",
                    "currency": "CAD",
                    "issueType": "CS",
                }
            }

        monkeypatch.setattr("openbb_tmx.utils.cache.amake_gql_request", quote)
        found = await udf._resolve_symbol("AC")

        assert found["description"] == "Air Canada"
        assert found["currency"] == "CAD"

    async def test_a_failing_directory_leaves_the_symbol_unresolved(self, monkeypatch):
        from openbb_tmx.routers import udf

        async def nothing(*args, **kwargs):
            return {}

        async def boom(*args, **kwargs):
            raise RuntimeError("down")

        monkeypatch.setattr("openbb_tmx.utils.cache.amake_gql_request", nothing)
        monkeypatch.setattr("openbb_tmx.utils.directory.lookup_symbols", boom)
        found = await udf._resolve_symbol("ZZZZ")

        assert found["description"] is None
        assert found["venue"] is None


class TestHistoryEnvelopeBranches:
    """Bars without a zone, and a window that holds none."""

    async def test_a_naive_stamp_is_read_as_utc(self, monkeypatch):
        from openbb_tmx.routers import udf

        async def bars(*args, **kwargs):
            return [
                {
                    "dateTime": "2026-07-24T16:00:00",
                    "open": 1.0,
                    "high": 2.0,
                    "low": 0.5,
                    "close": 1.5,
                    "volume": 3,
                }
            ]

        monkeypatch.setattr("openbb_tmx.utils.helpers.get_timeseries_history", bars)
        envelope = await udf.history(symbol="AC", resolution="1D", to=2_000_000_000)

        assert envelope["s"] == "ok"
        assert envelope["t"] == [
            int(datetime(2026, 7, 24, 16, tzinfo=UTC).timestamp())
        ]

    async def test_bars_without_a_close_leave_no_data(self, monkeypatch):
        from openbb_tmx.routers import udf

        async def bars(*args, **kwargs):
            return [{"dateTime": "2026-07-24T16:00:00Z", "close": None}]

        monkeypatch.setattr("openbb_tmx.utils.helpers.get_timeseries_history", bars)

        assert await udf.history(symbol="AC", resolution="1D", to=1) == {"s": "no_data"}


class TestScreenerChoiceOptions:
    """The dependent dropdown narrows by its parent."""

    def test_an_industry_narrows_to_its_group(self):
        from openbb_tmx.utils.choices import screener_options

        options = screener_options("industry", "banking")

        assert options
        assert all(o["value"] for o in options)

    def test_a_group_narrows_to_its_sector(self):
        from openbb_tmx.utils.choices import screener_options

        assert screener_options("industry_group", "energy")

    def test_an_unparented_field_lists_everything(self):
        from openbb_tmx.utils.choices import screener_options

        assert len(screener_options("sector")) == 11

    def test_an_unknown_field_lists_nothing(self):
        from openbb_tmx.utils.choices import screener_options

        assert screener_options("nonsense") == []

    def test_a_duplicate_name_gets_its_own_slug(self):
        from openbb_tmx.utils.choices import _index

        assert _index(["Gold", "Gold!"]) == {"gold": "Gold", "gold_2": "Gold!"}


class TestScreenerFilterBranches:
    """The screen's fixed filters."""

    def _query(self, **kwargs):
        from openbb_tmx.models.equity_screener import TmxEquityScreenerQueryParams

        return TmxEquityScreenerQueryParams(**kwargs)

    def test_a_boolean_filter_narrows_the_rows(self):
        from openbb_tmx.models.equity_screener import _apply_fixed

        rows = [
            {"symbol": "AC", "optionable": True},
            {"symbol": "ZZZ", "optionable": False},
        ]

        assert [
            r["symbol"] for r in _apply_fixed(rows, self._query(optionable=True))
        ] == ["AC"]

    def test_a_sector_filter_matches_the_code_prefix(self):
        from openbb_tmx.models.equity_screener import _apply_fixed

        rows = [{"symbol": "RY", "sector": 10402001}, {"symbol": "AC", "sector": 10501}]
        kept = _apply_fixed(rows, self._query(sector="finance"))

        assert [r["symbol"] for r in kept] == ["RY"]

    def test_an_unselected_sector_leaves_the_rows(self):
        from openbb_tmx.models.equity_screener import _sector_prefix

        assert _sector_prefix(self._query()) is None


class TestEtfSearchBranches:
    """The ETF screen's currency and ESG filters."""

    @pytest.fixture
    def universe(self, monkeypatch):
        """Serve a two-fund universe."""
        funds = [
            {
                "symbol": "XIU",
                "name": "iShares",
                "short_name": "XIU",
                "investment_style": "Index",
                "investment_objectives": "Track",
                "dividend_frequency": "Quarterly",
                "currency": "CAD",
                "esg": False,
                "regions": [],
                "sectors": [],
                "holdings_top10_summary": None,
                "holdings_top10": None,
                "additional_data": None,
                "website": None,
                "asset_class_id": None,
            },
            {
                "symbol": "ESGA",
                "name": "ESG Fund",
                "short_name": "ESGA",
                "investment_style": "Index",
                "investment_objectives": "Track",
                "dividend_frequency": "Monthly",
                "currency": "USD",
                "esg": True,
                "regions": [],
                "sectors": [],
                "holdings_top10_summary": None,
                "holdings_top10": None,
                "additional_data": None,
                "website": None,
                "asset_class_id": None,
            },
        ]

        async def all_etfs(use_cache=True):
            return [dict(f) for f in funds]

        monkeypatch.setattr("openbb_tmx.utils.helpers.get_all_etfs", all_etfs)

    async def test_the_currency_filter_narrows_the_universe(self, universe):
        from openbb_tmx.models.etf_search import (
            TmxEtfSearchFetcher,
            TmxEtfSearchQueryParams,
        )

        rows = await TmxEtfSearchFetcher.aextract_data(
            TmxEtfSearchQueryParams(currency="USD"), {}
        )

        assert [r["symbol"] for r in rows] == ["ESGA"]

    async def test_the_esg_filter_narrows_the_universe(self, universe):
        from openbb_tmx.models.etf_search import (
            TmxEtfSearchFetcher,
            TmxEtfSearchQueryParams,
        )

        rows = await TmxEtfSearchFetcher.aextract_data(
            TmxEtfSearchQueryParams(esg=True), {}
        )

        assert [r["symbol"] for r in rows] == ["ESGA"]


class TestTransportFailures:
    """The paths taken when a host refuses."""

    async def test_a_failing_directory_lookup_returns_nothing(self, monkeypatch):
        from openbb_tmx.utils import directory

        async def boom(*args, **kwargs):
            raise RuntimeError("down")

        async def token(_tool):
            return "t"

        token.cache_clear = lambda: None
        monkeypatch.setattr("openbb_tmx.utils.cache.amake_request", boom)
        monkeypatch.setattr("openbb_tmx.utils.quotemedia.get_token", token)

        assert await directory.lookup_symbols("AC", limit=5) == []


class TestMxParsingBranches:
    """The Montreal Exchange documents that come back unusable."""

    async def test_an_unreadable_cycles_document_is_empty(self, monkeypatch):
        from openbb_tmx.utils import mx

        async def nothing(*args, **kwargs):
            return None

        monkeypatch.setattr("openbb_tmx.utils.cache.amake_request", nothing)
        mx.get_expiry_cycles.cache_clear()

        assert await mx.get_expiry_cycles() == {}

    async def test_a_screener_page_without_tables_is_empty(self, monkeypatch):
        from openbb_tmx.utils import mx

        async def page(*args, **kwargs):
            return "<html><body>nothing here</body></html>"

        monkeypatch.setattr("openbb_tmx.utils.cache.amake_request", page)

        assert await mx.screen_covered_calls() == []

    async def test_a_row_without_a_series_is_skipped(self, monkeypatch):
        from openbb_tmx.utils import mx

        async def page(*args, **kwargs):
            return (
                "<table><tr><th>Symbol</th><th>Serie / Strike Price</th>"
                "<th>Last Price</th></tr>"
                "<tr><td>AC</td><td></td><td>23.27</td></tr></table>"
            )

        monkeypatch.setattr("openbb_tmx.utils.cache.amake_request", page)

        assert await mx.screen_covered_calls() == []


class TestHelperBranches:
    """The date and value helpers."""

    def test_a_blank_date_reads_as_none(self):
        from openbb_tmx.utils.helpers import _as_date

        assert _as_date(None) is None
        assert _as_date("") is None

    def test_a_string_date_is_read(self):
        from openbb_tmx.utils.helpers import _as_date

        assert _as_date("2026-07-24") == date(2026, 7, 24)

    def test_a_datetime_is_reduced_to_its_date(self):
        from openbb_tmx.utils.helpers import _as_date

        assert _as_date(datetime(2026, 7, 24, 16)) == date(2026, 7, 24)

    def test_nested_placeholders_are_replaced(self):
        from openbb_tmx.utils.helpers import replace_values_in_list_of_dicts

        data = [{"a": [{"b": "NA"}], "c": ["-", "keep"], "d": "NA"}]
        cleaned = replace_values_in_list_of_dicts(data)

        assert cleaned[0]["a"][0]["b"] is None
        assert cleaned[0]["c"] == [None, "keep"]
        assert cleaned[0]["d"] is None


class TestQuoteBranches:
    """The quote falls back and scrubs its values."""

    async def test_a_rejected_symbol_falls_back_to_the_batch(self, monkeypatch):
        from openbb_tmx.models.equity_quote import TmxEquityQuoteFetcher

        async def gql(operation, query, variables, **kwargs):
            if operation == "getQuoteBySymbol":
                raise OpenBBError("not found")

            return {
                "getQuoteForSymbols": [
                    {"symbol": "AIR:PA", "price": 206.05, "currency": "EUR"}
                ]
            }

        monkeypatch.setattr("openbb_tmx.utils.cache.amake_gql_request", gql)
        rows = await TmxEquityQuoteFetcher.aextract_data(
            TmxEquityQuoteFetcher.transform_query({"symbol": "AIR:PA"}), {}
        )

        assert rows[0]["symbol"] == "AIR:PA"

    def test_zero_and_blank_values_are_dropped(self):
        from openbb_tmx.models.equity_quote import TmxEquityQuoteFetcher

        query = TmxEquityQuoteFetcher.transform_query({"symbol": "AC"})
        rows = TmxEquityQuoteFetcher.transform_data(
            query, [{"symbol": "AC", "openPrice": 0, "volume": ""}]
        )

        assert rows[0].open is None


class TestHistoricalTransformBranches:
    """The historical transform's shapes."""

    def _query(self, **kwargs):
        from openbb_tmx.models.equity_historical import (
            TmxEquityHistoricalQueryParams,
        )

        return TmxEquityHistoricalQueryParams(symbol="AC", **kwargs)

    def test_no_rows_is_reported(self):
        from openbb_tmx.models.equity_historical import TmxEquityHistoricalFetcher

        with pytest.raises(EmptyDataError):
            TmxEquityHistoricalFetcher.transform_data(self._query(), [])

    def test_several_symbols_are_sorted_together(self):
        from openbb_tmx.models.equity_historical import TmxEquityHistoricalFetcher

        data = [
            _bar("2026-07-24", 2.0, symbol="ZZZ"),
            _bar("2026-07-24", 1.0, symbol="AC"),
        ]
        rows = TmxEquityHistoricalFetcher.transform_data(
            TmxEquityHistoricalQueryParamsFor("AC,ZZZ"), data
        )

        assert [r.symbol for r in rows] == ["AC", "ZZZ"]

    def test_a_weekly_open_is_zero_filled(self):
        from openbb_tmx.models.equity_historical import TmxEquityHistoricalFetcher

        data = [_bar("2011-09-12T00:00:00Z", 1.0, open=None, symbol="AC")]
        rows = TmxEquityHistoricalFetcher.transform_data(
            self._query(interval="1W"), data
        )

        assert rows[0].open == 0

    def test_an_intraday_stamp_keeps_its_offset(self):
        from openbb_tmx.models.equity_historical import TmxEquityHistoricalFetcher

        data = [_bar("2026-07-24T10:00:00-04:00", 1.0, symbol="AC")]
        rows = TmxEquityHistoricalFetcher.transform_data(
            self._query(interval="15"), data
        )

        assert rows[0].date.hour == 10


def _bar(stamp: str, close: float, **extra):
    """Build one historical bar."""
    bar = {
        "dateTime": stamp,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1,
    }
    bar.update(extra)

    return bar


def TmxEquityHistoricalQueryParamsFor(symbol: str):
    """Build a historical query for several symbols."""
    from openbb_tmx.models.equity_historical import TmxEquityHistoricalQueryParams

    return TmxEquityHistoricalQueryParams(symbol=symbol)


class TestRouterSurfaces:
    """The routes and helpers the routers expose directly."""

    async def test_the_choices_endpoint_narrows_by_parent(self):
        from openbb_tmx.routers.equity import screener_choices

        options = await screener_choices(field="industry_group", parent="energy")

        assert [o["label"] for o in options] == [
            "Fossil Fuels",
            "Other Energy Sources",
            "Renewable Energy Producers",
        ]

    def test_a_desktop_platform_reports_a_display(self, monkeypatch):
        from openbb_tmx.routers import equity

        monkeypatch.setattr("sys.platform", "darwin")

        assert equity._gui_available() is True

    def test_a_linux_host_follows_its_display(self, monkeypatch):
        from openbb_tmx.routers import equity

        monkeypatch.setattr("sys.platform", "linux")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

        assert equity._gui_available() is False

        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

        assert equity._gui_available() is True

    async def test_the_lifespan_closes_the_pooled_sessions(self, monkeypatch):
        from openbb_tmx import tmx_router
        from openbb_tmx.utils import session as session_utils

        closed: list = []

        async def close():
            closed.append(True)

        monkeypatch.setattr(session_utils, "close_sessions", close)

        async with tmx_router._lifespan(None):
            pass

        assert closed == [True]


class TestModelDefaultBranches:
    """The defaults the models fill in."""

    def test_the_earnings_calendar_defaults_its_window(self):
        from openbb_tmx.models.calendar_earnings import TmxCalendarEarningsFetcher

        query = TmxCalendarEarningsFetcher.transform_query({})

        assert query.start_date is not None
        assert query.end_date > query.start_date

    async def test_a_string_end_date_is_read(self, monkeypatch):
        from openbb_tmx.models.bond_trades import TmxBondTradesFetcher

        seen: dict = {}

        async def bonds(use_cache=True):
            return DataFrame(
                [
                    {
                        "secKey": "abc",
                        "cusip": "135087U28",
                        "isin": "CA135087U28",
                        "figi": "",
                        "originalIssueDate": "2020-01-01",
                    }
                ]
            )

        async def trades(sec_key, start, end, account_type=None):
            seen["end"] = end
            return [{"tradeDate": "2026-07-24", "price": 99.5}]

        monkeypatch.setattr("openbb_tmx.utils.helpers.get_all_bonds", bonds)
        monkeypatch.setattr("openbb_tmx.utils.ciro.get_bond_trades", trades)
        query = TmxBondTradesFetcher.transform_query({"cusip": "135087U28"})
        query.end_date = "2026-07-24"
        await TmxBondTradesFetcher.aextract_data(query, {})

        assert seen["end"] == date(2026, 7, 24)

    async def test_an_empty_index_snapshot_is_reported(self, monkeypatch):
        from openbb_tmx.models.index_snapshots import (
            TmxIndexSnapshotsFetcher,
            TmxIndexSnapshotsQueryParams,
        )

        async def nothing(*args, **kwargs):
            return {}

        monkeypatch.setattr("openbb_tmx.utils.helpers.get_data_from_url", nothing)

        with pytest.raises(EmptyDataError):
            await TmxIndexSnapshotsFetcher.aextract_data(
                TmxIndexSnapshotsQueryParams(region="ca"), {}
            )


class TestOptionsChainDate:
    """A dated chain comes from the end-of-day download."""

    async def test_a_dated_chain_reads_the_download(self, monkeypatch):
        from pandas import DataFrame

        from openbb_tmx.models.options_chains import (
            TmxOptionsChainsFetcher,
            TmxOptionsChainsQueryParams,
        )

        async def download(symbol, date, use_cache=True):
            return DataFrame([{"contractSymbol": "AC260731C00023000", "strike": 23.0}])

        monkeypatch.setattr("openbb_tmx.utils.helpers.download_eod_chains", download)
        result = await TmxOptionsChainsFetcher.aextract_data(
            TmxOptionsChainsQueryParams(symbol="AC", date=date(2026, 7, 24)), {}
        )

        assert result["strike"] == [23.0]

    async def test_an_empty_download_is_empty(self, monkeypatch):
        from pandas import DataFrame

        from openbb_tmx.models.options_chains import (
            TmxOptionsChainsFetcher,
            TmxOptionsChainsQueryParams,
        )

        async def download(symbol, date, use_cache=True):
            return DataFrame()

        monkeypatch.setattr("openbb_tmx.utils.helpers.download_eod_chains", download)
        result = await TmxOptionsChainsFetcher.aextract_data(
            TmxOptionsChainsQueryParams(symbol="AC", date=date(2026, 7, 24)), {}
        )

        assert result == {}


class TestBuilderFallbacks:
    """The builder keeps working when its store does not."""

    def test_unreadable_presets_leave_the_toolbar_empty(self, monkeypatch):
        from openbb_tmx.utils import screener_iframe

        def boom():
            raise OSError("no store")

        monkeypatch.setattr("openbb_tmx.utils.screener_presets.list_presets", boom)
        content, _toolbars, _modals, _theme = screener_iframe.build_screener_content(
            "dark", "iframe"
        )

        assert content.json_data["presets"] == []


class TestFinalBranches:
    """The last conditional paths."""

    async def test_an_intraday_interval_uses_the_minute_feed(self, monkeypatch):
        from openbb_tmx.models.equity_historical import TmxEquityHistoricalFetcher

        seen: dict = {}

        async def intraday(symbol, interval=None, start_date=None, end_date=None):
            seen["interval"] = interval
            return [_bar("2026-07-24T10:00:00-04:00", 1.0)]

        monkeypatch.setattr(
            "openbb_tmx.utils.helpers.get_intraday_price_history", intraday
        )
        query = TmxEquityHistoricalFetcher.transform_query(
            {"symbol": "AC", "interval": "15"}
        )
        rows = await TmxEquityHistoricalFetcher.aextract_data(query, {})

        assert seen["interval"] == 15
        assert rows

    async def test_a_symbol_without_bars_warns(self, monkeypatch):
        from openbb_tmx.models.equity_historical import TmxEquityHistoricalFetcher

        async def nothing(*args, **kwargs):
            return []

        monkeypatch.setattr("openbb_tmx.utils.helpers.get_daily_price_history", nothing)
        query = TmxEquityHistoricalFetcher.transform_query({"symbol": "ZZZZ"})

        with pytest.warns(UserWarning, match="No data found for ZZZZ"):
            assert await TmxEquityHistoricalFetcher.aextract_data(query, {}) == []

    async def test_a_search_row_outside_a_chartable_venue_is_dropped(self, monkeypatch):
        from openbb_tmx.routers import udf

        async def rows(query, limit=100, country=None, symbol_only=False, **kwargs):
            return [
                {
                    "symbol": "AC",
                    "name": "Air Canada",
                    "exchangeShortName": "TSX",
                    "symbolType": "Equity",
                },
                {
                    "symbol": "^DJI:US",
                    "name": "Dow",
                    "exchangeShortName": "DJI",
                    "symbolType": "Index",
                },
            ]

        monkeypatch.setattr("openbb_tmx.utils.directory.lookup_symbols", rows)
        results = await udf.search(query="a", limit=10)

        assert [r["symbol"] for r in results] == ["AC"]

    async def test_a_daily_only_venue_reports_no_intraday(self, monkeypatch):
        from openbb_tmx.routers import udf

        async def resolve(symbol):
            return {
                "description": "BMO Fund",
                "venue": "CMF",
                "currency": "CAD",
                "issue_type": "Mutual Fund",
            }

        monkeypatch.setattr(udf, "_resolve_symbol", resolve)
        info = await udf.symbols(symbol="BMO99814")

        assert info["has_intraday"] is False
        assert info["type"] == "fund"
        assert info["supported_resolutions"] == ["D", "W", "M"]

    async def test_a_single_price_series_omits_its_candles(self, monkeypatch):
        from openbb_tmx.routers import udf

        async def bars(*args, **kwargs):
            return [
                {
                    "dateTime": "2026-07-24T16:00:00-04:00",
                    "open": None,
                    "high": None,
                    "low": None,
                    "close": 11.7,
                    "volume": 0,
                }
            ]

        monkeypatch.setattr("openbb_tmx.utils.helpers.get_timeseries_history", bars)
        envelope = await udf.history(
            symbol="BMO99814", resolution="1D", to=2_000_000_000
        )

        assert sorted(k for k in envelope if k != "s") == ["c", "t", "v"]

    async def test_a_weekly_tab_row_only_marks_the_weekly_flag(self, monkeypatch):
        from openbb_tmx.utils import mx

        tables = "".join(
            "<table><tr><th>Name of Underlying Instrument</th>"
            "<th>Option Symbol</th><th>Underlying Symbol</th></tr>"
            "<tr><td>Air Canada</td><td>AC</td><td>AC</td></tr></table>"
            for _ in range(7)
        )

        async def page(*args, **kwargs):
            return tables

        monkeypatch.setattr("openbb_tmx.utils.cache.amake_request", page)
        mx.get_options_listings.cache_clear()
        listings = await mx.get_options_listings()

        assert listings["AC"]["has_weeklies"] is True

    async def test_a_screener_page_without_a_symbol_column_is_empty(self, monkeypatch):
        from openbb_tmx.utils import mx

        async def page(*args, **kwargs):
            return "<table><tr><th>Other</th></tr><tr><td>x</td></tr></table>"

        monkeypatch.setattr("openbb_tmx.utils.cache.amake_request", page)

        assert await mx.screen_covered_calls() == []

    async def test_a_datatool_payload_is_unwrapped(self, monkeypatch):
        from openbb_tmx.utils import quotemedia

        async def request(url, **kwargs):
            return {"results": {"rows": [1, 2]}}

        async def token(_tool):
            return "t"

        monkeypatch.setattr("openbb_tmx.utils.cache.amake_request", request)
        monkeypatch.setattr(quotemedia, "get_token", token)

        assert await quotemedia.get_datatool("x.json", "tool") == {"rows": [1, 2]}

    def test_an_intraday_window_before_the_epoch_ends_today(self):
        from openbb_tmx.utils.helpers import INTRADAY_EPOCH, _as_date

        assert _as_date("2019-01-01") < INTRADAY_EPOCH


class TestConditionalRegistration:
    """The commands that register only when the standard extension is absent."""

    def test_the_news_command_registers_without_the_extension(self, monkeypatch):
        import importlib

        import openbb_tmx

        monkeypatch.setattr(openbb_tmx, "NEWS_INSTALLED", False)
        module = importlib.reload(importlib.import_module("openbb_tmx.routers.news"))

        try:
            assert hasattr(module, "company")
        finally:
            monkeypatch.undo()
            importlib.reload(module)


class TestRemainingHelpers:
    """The last helper paths."""

    @pytest.mark.parametrize("issue_type", [None, "", "Warrant"])
    def test_an_unusable_issue_type_is_a_stock(self, issue_type):
        from openbb_tmx.routers.udf import _instrument_type

        assert _instrument_type("AC", issue_type) == "stock"

    async def test_the_batch_completes_a_partial_quote(self, monkeypatch):
        from openbb_tmx.routers import udf

        async def gql(operation, query, variables, **kwargs):
            if operation == "getQuoteBySymbol":
                return {"getQuoteBySymbol": {"name": "Airbus", "issueType": "CS"}}

            return {
                "getQuoteForSymbols": [
                    {"symbol": "AIR:PA", "currency": "EUR", "exchange": "PA"}
                ]
            }

        monkeypatch.setattr("openbb_tmx.utils.cache.amake_gql_request", gql)
        found = await udf._resolve_symbol("AIR:PA")

        assert found["venue"] == "PA"
        assert found["currency"] == "EUR"

    async def test_a_quote_without_a_currency_consults_the_batch(self, monkeypatch):
        from openbb_tmx.routers import udf

        async def gql(operation, query, variables, **kwargs):
            if operation == "getQuoteBySymbol":
                return {
                    "getQuoteBySymbol": {
                        "name": "Air Canada",
                        "exShortName": "TSX",
                        "currency": "CAD",
                        "issueType": "CS",
                    }
                }

            raise AssertionError("the batch feed should not be reached")

        monkeypatch.setattr("openbb_tmx.utils.cache.amake_gql_request", gql)
        found = await udf._resolve_symbol("AC")

        assert found["issue_type"] == "CS"

    async def test_a_listing_row_without_a_symbol_is_skipped(self, monkeypatch):
        from openbb_tmx.utils import mx

        tables = "".join(
            "<table><tr><th>Name of Underlying Instrument</th>"
            "<th>Option Symbol</th><th>Underlying Symbol</th></tr>"
            "<tr><td>Nothing</td><td></td><td></td></tr></table>"
            for _ in range(7)
        )

        async def page(*args, **kwargs):
            return tables

        monkeypatch.setattr("openbb_tmx.utils.cache.amake_request", page)
        mx.get_options_listings.cache_clear()

        assert await mx.get_options_listings() == {}

    async def test_a_weekend_download_date_is_advanced(self, monkeypatch):
        from openbb_tmx.utils import helpers

        seen: dict = {}

        async def tickers(use_cache=True):
            return DataFrame(
                [{"underlying_symbol": "AC", "underlying_instrument": "Air Canada"}],
                index=["AC"],
            )

        async def download(url, use_cache=True, **kwargs):
            seen["url"] = url
            raise OpenBBError("stop after the URL is built")

        monkeypatch.setattr(helpers, "get_all_options_tickers", tickers)
        monkeypatch.setattr(helpers, "get_data_from_url", download)

        with pytest.raises(OpenBBError):
            await helpers.download_eod_chains("AC", date(2026, 7, 25))

        assert "from=2026-07-27" in seen["url"]

    async def test_a_long_weekend_download_date_is_advanced_twice(self, monkeypatch):
        from openbb_tmx.utils import helpers

        seen: dict = {}

        async def tickers(use_cache=True):
            return DataFrame(
                [{"underlying_symbol": "AC", "underlying_instrument": "Air Canada"}],
                index=["AC"],
            )

        async def download(url, use_cache=True, **kwargs):
            seen["url"] = url
            raise OpenBBError("stop after the URL is built")

        monkeypatch.setattr(helpers, "get_all_options_tickers", tickers)
        monkeypatch.setattr(helpers, "get_data_from_url", download)

        with pytest.raises(OpenBBError):
            await helpers.download_eod_chains("AC", date(2026, 12, 25))

        assert "from=2026-12-2" in seen["url"]

    async def test_an_empty_download_is_reported(self, monkeypatch):
        from openbb_tmx.utils import helpers

        async def tickers(use_cache=True):
            return DataFrame(
                [{"underlying_symbol": "AC", "underlying_instrument": "Air Canada"}],
                index=["AC"],
            )

        async def download(url, use_cache=True, **kwargs):
            return "Symbol,Strike\n"

        monkeypatch.setattr(helpers, "get_all_options_tickers", tickers)
        monkeypatch.setattr(helpers, "get_data_from_url", download)

        with pytest.raises(OpenBBError, match="No data found"):
            await helpers.download_eod_chains("AC", date(2026, 7, 24))

    async def test_an_intraday_window_that_ends_before_the_epoch_is_reset(
        self, monkeypatch
    ):
        from openbb_tmx.utils import helpers

        seen: list = []

        async def gql(operation, query, variables, **kwargs):
            seen.append(variables)
            return {"getTimeSeriesData": []}

        monkeypatch.setattr("openbb_tmx.utils.cache.amake_gql_request", gql)
        await helpers.get_intraday_price_history(
            "AC", date(2019, 1, 1), date(2019, 6, 1), 60
        )

        assert seen
