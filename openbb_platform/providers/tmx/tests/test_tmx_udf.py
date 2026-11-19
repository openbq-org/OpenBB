"""Tests for the TradingView UDF feed."""

from datetime import UTC

import pytest

from openbb_tmx.routers import udf


class TestConfig:
    """The feed's advertised capabilities."""

    async def test_resolutions(self):
        config = await udf.config()
        assert config["supported_resolutions"] == [
            "1",
            "5",
            "15",
            "30",
            "60",
            "D",
            "W",
            "M",
        ]

    async def test_search_is_supported(self):
        assert (await udf.config())["supports_search"] is True

    async def test_exchanges_cover_every_asset_class(self):
        venues = {e["value"] for e in (await udf.config())["exchanges"]}

        assert {"TSX", "TSXV", "NYSE", "NASD"} <= venues
        assert {"NMX", "CMX", "MOE"} <= venues
        assert {"FOREX", "Crypto", "CMF"} <= venues

    async def test_only_chartable_exchanges_are_offered(self):
        """The picker offers no venue whose instruments cannot be charted."""
        from openbb_tmx.utils.exchanges import CHARTABLE_VENUES

        venues = {e["value"] for e in (await udf.config())["exchanges"]}

        assert venues == set(CHARTABLE_VENUES) | {""}
        assert not venues & {"PA", "AS", "LN", "HK", "MI", "STOX", "NKK"}
        assert not venues & {"NYGIF", "NMF", "CMEG", "CBOT", "DJI", "SPIC"}

    async def test_every_offered_venue_is_described(self):
        from openbb_tmx.utils.exchanges import DIRECTORY_VENUES

        for entry in (await udf.config())["exchanges"][1:]:
            assert DIRECTORY_VENUES[entry["value"]] == entry["desc"]

    async def test_the_all_exchanges_entry_comes_first(self):
        exchanges = (await udf.config())["exchanges"]

        assert exchanges[0] == {"value": "", "name": "All Exchanges", "desc": ""}

    async def test_server_time(self):
        assert await udf.time() > 1_700_000_000


class TestSearch:
    """The chart's symbol picker."""

    async def test_maps_directory_rows(self, monkeypatch):
        async def fake(
            query, limit=100, country=None, symbol_only=False, use_cache=True
        ):
            return [
                {
                    "symbol": "AC",
                    "name": "Air Canada",
                    "exchangeShortName": "TSX",
                    "symbolType": "Equity",
                },
                {
                    "symbol": "XIU",
                    "name": "iShares",
                    "exchangeShortName": "TSX",
                    "symbolType": "ETF",
                },
            ]

        monkeypatch.setattr("openbb_tmx.utils.directory.lookup_symbols", fake)
        rows = await udf.search(query="a", limit=10)
        assert [r["type"] for r in rows] == ["stock", "fund"]

    async def test_an_opened_picker_lists_the_universe(self, monkeypatch):
        """The picker opens with no query and must still offer something."""
        searched: list = []

        async def browse(limit=200, country="CA", symbol_types=None, use_cache=True):
            return [
                {
                    "symbol": "RY",
                    "name": "Royal Bank",
                    "exchangeShortName": "TSX",
                    "symbolType": "Equity",
                }
            ]

        async def lookup(*args, **kwargs):
            searched.append(args)

            return []

        monkeypatch.setattr("openbb_tmx.utils.directory.browse_symbols", browse)
        monkeypatch.setattr("openbb_tmx.utils.directory.lookup_symbols", lookup)
        rows = await udf.search(limit=10)

        assert [r["ticker"] for r in rows] == ["RY"]
        assert searched == []

    async def test_filters_by_exchange_and_type(self, monkeypatch):
        async def fake(
            query, limit=100, country=None, symbol_only=False, use_cache=True
        ):
            return [
                {
                    "symbol": "AC",
                    "name": "Air Canada",
                    "exchangeShortName": "TSX",
                    "symbolType": "Equity",
                },
                {
                    "symbol": "IBM:US",
                    "name": "IBM",
                    "exchangeShortName": "NYSE",
                    "symbolType": "Equity",
                },
            ]

        monkeypatch.setattr("openbb_tmx.utils.directory.lookup_symbols", fake)
        assert len(await udf.search(query="a", exchange="NYSE")) == 1
        assert len(await udf.search(query="a", type="fund")) == 0

    async def test_respects_the_limit(self, monkeypatch):
        async def fake(
            query, limit=100, country=None, symbol_only=False, use_cache=True
        ):
            return [
                {
                    "symbol": f"S{i}",
                    "name": "n",
                    "exchangeShortName": "TSX",
                    "symbolType": "Equity",
                }
                for i in range(50)
            ]

        monkeypatch.setattr("openbb_tmx.utils.directory.lookup_symbols", fake)
        assert len(await udf.search(query="s", limit=5)) == 5


class TestSymbols:
    """Symbol resolution."""

    @pytest.mark.parametrize(
        ("symbol", "expected"),
        [("AC", "stock"), ("^TSX", "index"), ("/CGB", "futures"), ("$USDCAD", "forex")],
    )
    async def test_type_follows_the_prefix(self, gql, symbol, expected):
        assert (await udf.symbols(symbol=symbol))["type"] == expected

    async def test_unresolvable_symbol(self, monkeypatch):
        from openbb_core.app.model.abstract.error import OpenBBError

        async def empty(*args, **kwargs):
            return {}

        monkeypatch.setattr("openbb_tmx.utils.cache.amake_gql_request", empty)

        with pytest.raises(OpenBBError, match="did not resolve"):
            await udf.symbols(symbol="ZZZZ")

    async def test_declares_intraday_and_daily(self, gql):
        info = await udf.symbols(symbol="AC")
        assert info["has_intraday"] and info["has_daily"]
        assert info["timezone"] == "America/Toronto"


class TestHistory:
    """The OHLCV envelope."""

    async def test_daily_bars(self, gql):
        bars = await udf.history(symbol="AC", resolution="D", from_=0, to=2_000_000_000)
        assert bars["s"] == "ok"
        assert len(bars["t"]) == len(bars["c"]) == 2
        assert bars["c"][-1] == 23.27

    async def test_every_series_is_aligned(self, gql):
        bars = await udf.history(symbol="AC", resolution="W", from_=0, to=2_000_000_000)
        lengths = {len(bars[k]) for k in ("t", "o", "h", "l", "c", "v")}
        assert len(lengths) == 1

    async def test_no_data(self, monkeypatch):
        async def empty(*args, **kwargs):
            return {"getTimeSeriesData": []}

        monkeypatch.setattr("openbb_tmx.utils.cache.amake_gql_request", empty)
        bars = await udf.history(symbol="AC", resolution="D", from_=0, to=1)
        assert bars == {"s": "no_data"}

    async def test_intraday_uses_the_minute_feed(self, monkeypatch):
        called: dict = {}

        async def fake(symbol, start, end, interval):
            called["interval"] = interval
            return [
                {
                    "dateTime": "2026-07-24T10:00:00-04:00",
                    "open": 1.0,
                    "high": 2.0,
                    "low": 0.5,
                    "close": 1.5,
                    "volume": 10,
                }
            ]

        monkeypatch.setattr("openbb_tmx.utils.helpers.get_intraday_price_history", fake)
        bars = await udf.history(
            symbol="AC", resolution="15", from_=0, to=2_000_000_000
        )
        assert called["interval"] == 15
        assert bars["s"] == "ok"

    async def test_bars_without_a_close_are_dropped(self, monkeypatch):
        async def partial(*args, **kwargs):
            return {
                "getTimeSeriesData": [
                    {"dateTime": "2026-07-24T16:00:00-04:00", "close": None},
                    {
                        "dateTime": "2026-07-23T16:00:00-04:00",
                        "open": 1.0,
                        "high": 2.0,
                        "low": 0.5,
                        "close": 1.5,
                        "volume": 3,
                    },
                ]
            }

        monkeypatch.setattr("openbb_tmx.utils.cache.amake_gql_request", partial)
        bars = await udf.history(symbol="AC", resolution="D", from_=0, to=2_000_000_000)
        assert len(bars["t"]) == 1


class TestHistoryEnvelope:
    """The UDF error and countback contracts."""

    async def test_upstream_failure_returns_an_error_envelope(self, monkeypatch):
        async def boom(*args, **kwargs):
            raise RuntimeError("upstream down")

        monkeypatch.setattr("openbb_tmx.utils.helpers.get_timeseries_history", boom)
        bars = await udf.history(symbol="AC", resolution="D", from_=0, to=2_000_000_000)

        assert bars == {"s": "error", "errmsg": udf.HISTORY_FAILED}
        assert "upstream down" not in bars["errmsg"]

    async def test_countback_never_truncates_the_series(self, gql):
        """The chart always receives every bar the feed holds."""
        full = await udf.history(symbol="AC", resolution="D", from_=0, to=2_000_000_000)
        capped = await udf.history(
            symbol="AC", resolution="D", from_=0, to=2_000_000_000, countback=1
        )

        assert capped["t"] == full["t"]

    async def test_a_narrow_window_still_returns_everything(self, gql):
        """A windowed request is answered with the full history."""
        full = await udf.history(symbol="AC", resolution="D", from_=0, to=2_000_000_000)
        windowed = await udf.history(
            symbol="AC", resolution="D", from_=1_900_000_000, to=2_000_000_000
        )

        assert windowed["t"] == full["t"]


class TestSessionMetadata:
    """The session, timezone, and intraday support a symbol reports."""

    @pytest.mark.parametrize(
        ("symbol", "zone", "session", "intraday"),
        [
            ("AC", "America/Toronto", "0930-1600", True),
            ("IBM:US", "America/New_York", "0930-1600", True),
            ("AIR:PA", "Europe/Paris", "0900-1730", False),
            ("SAP:DB", "Europe/Berlin", "0900-1730", False),
            ("NOKIA:HI", "Europe/Helsinki", "1000-1830", False),
            ("0700:HK", "Asia/Hong_Kong", "0930-1600", False),
            ("$USDCAD", "Etc/UTC", "24x7", True),
            ("~BTCUSD", "Etc/UTC", "24x7", True),
            ("/CGB", "America/Toronto", "24x7", True),
            ("^TSX", "America/Toronto", "0930-1600", True),
        ],
    )
    def test_session_follows_the_venue(self, symbol, zone, session, intraday):
        assert udf._session_for(symbol) == (zone, session, intraday)

    async def test_venues_without_intraday_advertise_period_resolutions(self, gql):
        info = await udf.symbols(symbol="AIR:PA")
        assert info["supported_resolutions"] == udf.PERIOD_ONLY_RESOLUTIONS
        assert info["has_intraday"] is False

    async def test_north_american_venues_advertise_every_resolution(self, gql):
        info = await udf.symbols(symbol="AC")
        assert info["supported_resolutions"] == udf.SUPPORTED_RESOLUTIONS
        assert info["has_intraday"] is True

    async def test_bar_timestamps_are_utc_epochs(self, gql):
        bars = await udf.history(symbol="AC", resolution="D", from_=0, to=2_000_000_000)
        from datetime import datetime

        stamped = datetime.fromtimestamp(bars["t"][-1], tz=UTC)
        assert stamped.year == 2026
        assert bars["t"] == sorted(bars["t"])


class TestSymbolResolutionFallback:
    """Charting must not depend on a symbol also being quotable."""

    async def test_falls_back_to_the_directory(self, monkeypatch):
        async def no_quote(*args, **kwargs):
            raise RuntimeError("not entitled")

        async def entries(query, limit=100, country=None, symbol_only=False, **kwargs):
            return [
                {
                    "symbol": "AIR:PA",
                    "name": "AIRBUS",
                    "exchangeShortName": "PA",
                    "symbolType": "Equity",
                }
            ]

        monkeypatch.setattr("openbb_tmx.utils.cache.amake_gql_request", no_quote)
        monkeypatch.setattr("openbb_tmx.utils.directory.lookup_symbols", entries)
        info = await udf.symbols(symbol="AIR:PA")

        assert info["exchange"] == "PA"
        assert info["description"] == "AIRBUS"
        assert info["type"] == "stock"

    async def test_unknown_symbol_still_fails(self, monkeypatch):
        from openbb_core.app.model.abstract.error import OpenBBError

        async def no_quote(*args, **kwargs):
            raise RuntimeError("not entitled")

        async def invalid(symbols, use_cache=True):
            return [{"valid": False, "symbol": "ZZZZ9", "exchange": ""}]

        monkeypatch.setattr("openbb_tmx.utils.cache.amake_gql_request", no_quote)
        monkeypatch.setattr("openbb_tmx.utils.quotemedia.validate_symbols", invalid)

        with pytest.raises(OpenBBError, match="did not resolve"):
            await udf.symbols(symbol="ZZZZ9")
