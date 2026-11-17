"""Tests for the Deribit shared accessors."""

from datetime import date, datetime, timezone

import pytest
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_deribit.utils import helpers


class TestTimestamps:
    """Dates cross the exchange boundary as milliseconds."""

    def test_to_timestamp_from_string(self):
        """An ISO date reads as midnight UTC."""
        assert helpers.to_timestamp("2026-01-01") == 1767225600000

    def test_to_timestamp_from_date(self):
        """A date object reads the same as its ISO spelling."""
        assert helpers.to_timestamp(date(2026, 1, 1)) == helpers.to_timestamp(
            "2026-01-01"
        )

    def test_to_timestamp_keeps_zone(self):
        """A datetime that carries a zone is not shifted twice."""
        aware = datetime(2026, 1, 1, tzinfo=timezone.utc)

        assert helpers.to_timestamp(aware) == 1767225600000

    def test_from_timestamp(self):
        """Milliseconds read back as a UTC datetime."""
        stamp = helpers.from_timestamp(1767225600000)

        assert stamp.year == 2026
        assert stamp.tzinfo is not None

    def test_to_timestamp_from_a_pandas_stamp(self):
        """A pandas timestamp is used as it stands."""
        from pandas import Timestamp

        assert helpers.to_timestamp(Timestamp("2026-01-01")) == 1767225600000
        assert helpers.to_timestamp(Timestamp("2026-01-01", tz="UTC")) == (
            1767225600000
        )

    def test_from_timestamp_none(self):
        """No timestamp reads as no datetime."""
        assert helpers.from_timestamp(None) is None

    def test_from_day_number(self):
        """A count of whole days reads as a date."""
        assert helpers.from_day_number(20714) == date(2026, 9, 18)

    def test_from_day_number_none(self):
        """No day number reads as no date."""
        assert helpers.from_day_number(None) is None


class TestDaysToExpiration:
    """Days are counted to the instant a contract expires."""

    EXPIRES = 1789977600000  # 2026-09-21 08:00 UTC

    @pytest.mark.parametrize(
        ("hours_left", "days"),
        [(5, 0), (23.99, 0), (24, 1), (47, 1), (24 * 30, 30), (-1, 0)],
    )
    def test_whole_days_left(self, hours_left, days):
        """Part of a day is dropped, and an expired contract has none left."""
        now = self.EXPIRES - hours_left * 3_600_000

        assert helpers.days_to_expiration(self.EXPIRES, now) == days


class TestNormalizeCurrency:
    """The wildcard is spelled the way the exchange spells it."""

    @pytest.mark.parametrize("given", ["any", "ANY", "all", "All"])
    def test_wildcards(self, given):
        """Either wildcard resolves to the one the exchange accepts."""
        assert helpers.normalize_currency(given) == "any"

    def test_real_currency(self):
        """A real currency is upper-cased."""
        assert helpers.normalize_currency("btc") == "BTC"


class TestFlattenTicker:
    """A ticker's nested members are lifted to the top level."""

    def test_lifts_stats_and_greeks(self, load):
        """Statistics and greeks end up beside the quote."""
        flat = helpers.flatten_ticker(load("ticker_future"))

        assert "stats" not in flat
        assert "greeks" not in flat
        assert flat["instrument_name"] == "BTC-PERPETUAL"
        assert "volume" in flat

    def test_tolerates_missing_members(self):
        """A ticker with neither member is returned unchanged."""
        assert helpers.flatten_ticker({"a": 1}) == {"a": 1}

    def test_tolerates_null_members(self):
        """A null member is dropped rather than unpacked."""
        assert helpers.flatten_ticker({"a": 1, "stats": None}) == {"a": 1}


class TestAccessors:
    """The thin accessors pass their arguments through to the transport."""

    @pytest.mark.asyncio
    async def test_get_currencies(self, responder, load):
        """Currencies come back as the exchange sends them."""
        responder({"get_currencies": load("currencies")})

        assert len(await helpers.get_currencies()) == 7

    @pytest.mark.asyncio
    async def test_get_instruments_normalizes(self, responder, load):
        """The wildcard currency reaches the exchange in lower case."""
        seen: dict = {}

        def capture(params):
            seen.update(params)

            return load("instruments_future")

        responder({"get_instruments": capture})
        await helpers.get_instruments("all", "future", True)

        assert seen == {"currency": "any", "kind": "future", "expired": True}

    @pytest.mark.asyncio
    async def test_get_instrument(self, responder, load):
        """One instrument is read by name."""
        responder({"get_instrument": load("instrument")})
        instrument = await helpers.get_instrument("BTC-PERPETUAL")

        assert instrument["instrument_name"] == "BTC-PERPETUAL"

    @pytest.mark.asyncio
    async def test_get_ticker(self, responder, load):
        """A ticker is flattened on the way out."""
        responder({"ticker": load("ticker_future")})
        ticker = await helpers.get_ticker("BTC-PERPETUAL")

        assert "stats" not in ticker

    @pytest.mark.asyncio
    async def test_get_tickers_skips_failures(self, monkeypatch, load):
        """A symbol whose quote failed is left out rather than raising."""

        async def _gather(calls, use_cache=True):
            return [load("ticker_future"), OpenBBError("no"), {}]

        monkeypatch.setattr("openbb_deribit.utils.client.gather", _gather)
        tickers = await helpers.get_tickers(["A", "B", "C"])

        assert len(tickers) == 1

    @pytest.mark.asyncio
    async def test_get_index_names(self, responder, load):
        """Index names come back as the exchange sends them."""
        responder({"get_index_price_names": load("index_price_names")})

        assert "btc_usd" in await helpers.get_index_names()

    @pytest.mark.asyncio
    async def test_get_expirations(self, responder, load):
        """Expirations come back keyed the way the query asked for."""
        responder({"get_expirations": load("expirations_grouped")})
        expirations = await helpers.get_expirations("grouped", "any")

        assert "btc" in expirations


class TestRoots:
    """Underlyings are derived from what the exchange lists right now."""

    @pytest.mark.asyncio
    async def test_options_roots(self, responder, load):
        """Every root with a listed option is returned, sorted."""
        responder({"get_instruments": load("instruments_option")})

        assert await helpers.get_options_roots() == ["BTC", "XRP_USDC"]

    @pytest.mark.asyncio
    async def test_futures_roots_need_a_curve(self, responder, load):
        """A root with one dated contract is not a curve."""
        rows = load("instruments_future")
        responder({"get_instruments": rows})

        assert await helpers.get_futures_roots() == ["BTC"]

    @pytest.mark.asyncio
    async def test_futures_roots_skip_lone_contracts(self, responder):
        """A root with a perpetual and one dated contract is left out."""
        responder(
            {
                "get_instruments": [
                    {
                        "instrument_name": "SOL_USDC-PERPETUAL",
                        "settlement_period": "perpetual",
                    },
                    {
                        "instrument_name": "SOL_USDC-25DEC26",
                        "settlement_period": "month",
                    },
                ]
            }
        )

        assert await helpers.get_futures_roots() == []

    @pytest.mark.asyncio
    async def test_roots_ignore_unnamed_rows(self, responder):
        """A row with no instrument name is skipped."""
        responder({"get_instruments": [{"instrument_name": ""}, {}]})

        assert await helpers.get_options_roots() == []


class TestOptionsSymbols:
    """Option symbols are grouped by the expiration they carry."""

    @pytest.mark.asyncio
    async def test_grouped_by_expiration(self, responder, load):
        """Every contract lands under its own expiration date."""
        responder({"get_instruments": load("instruments_option")})
        grouped = await helpers.get_options_symbols("XRP_USDC")

        contracts = [symbol for symbols in grouped.values() for symbol in symbols]

        assert len(grouped) == 2
        assert len(contracts) == 80
        assert all(symbol.startswith("XRP_USDC-") for symbol in contracts)
        assert list(grouped) == sorted(grouped)
        assert all(symbol.endswith(("-C", "-P")) for symbol in contracts)

    @pytest.mark.asyncio
    async def test_unknown_underlying(self, responder, load):
        """An underlying with no options names the ones that have them."""
        responder({"get_instruments": load("instruments_option")})

        with pytest.raises(OpenBBError, match="XRP_USDC"):
            await helpers.get_options_symbols("DOGE")


class TestFuturesCurveSymbols:
    """A curve is the dated contracts of one root, nearest first."""

    @pytest.mark.asyncio
    async def test_sorted_by_expiration(self, responder, load):
        """The perpetual is left off and the rest run nearest first."""
        responder({"get_instruments": load("instruments_future")})
        symbols = await helpers.get_futures_curve_symbols("BTC")

        assert "BTC-PERPETUAL" not in symbols
        assert len(symbols) == 12

    @pytest.mark.asyncio
    async def test_unknown_root(self, responder, load):
        """A root with no curve names the roots that have one."""
        responder({"get_instruments": load("instruments_future")})

        with pytest.raises(OpenBBError, match="BTC"):
            await helpers.get_futures_curve_symbols("DOGE")


class TestPerpetuals:
    """Perpetuals are addressable by their shortened root."""

    @pytest.mark.asyncio
    async def test_keyed_by_short_root(self, responder):
        """The underscore is dropped from the key, not the value."""
        responder(
            {
                "get_instruments": [
                    {
                        "instrument_name": "SOL_USDC-PERPETUAL",
                        "settlement_period": "perpetual",
                    },
                    {
                        "instrument_name": "BTC-25DEC26",
                        "settlement_period": "month",
                    },
                ]
            }
        )
        perpetuals = await helpers.get_perpetual_symbols()

        assert perpetuals == {"SOLUSDC": "SOL_USDC-PERPETUAL"}

    @pytest.mark.asyncio
    async def test_futures_symbols(self, responder, load):
        """Every listed future is returned, sorted."""
        responder({"get_instruments": load("instruments_future")})
        symbols = await helpers.get_futures_symbols()

        assert symbols == sorted(symbols)
        assert "BTC-PERPETUAL" in symbols


class TestResolveSymbol:
    """A symbol resolves to the name the exchange knows it by."""

    @pytest.mark.asyncio
    async def test_perpetual_root(self, responder, load):
        """A shortened root resolves to the full perpetual name."""
        responder({"get_instruments": load("instruments_future")})

        assert await helpers.resolve_symbol("btc") == "BTC-PERPETUAL"

    @pytest.mark.asyncio
    async def test_full_name(self, responder, load):
        """A full instrument name resolves to itself."""
        responder({"get_instruments": load("instruments_future")})

        assert await helpers.resolve_symbol("BTC-25DEC26") == "BTC-25DEC26"

    @pytest.mark.asyncio
    async def test_unknown(self, responder, load):
        """An unlisted symbol is rejected."""
        responder({"get_instruments": load("instruments_future")})

        with pytest.raises(OpenBBError, match="no instrument named"):
            await helpers.resolve_symbol("NOPE")


class TestChartWindows:
    """A long span is split into pages the exchange will serve."""

    def test_single_window(self):
        """A span shorter than one page is one window."""
        start = helpers.to_timestamp("2026-01-01")
        end = helpers.to_timestamp("2026-01-05")

        assert helpers._chart_windows(start, end, "1D") == [(start, end)]

    def test_splits_long_span(self):
        """A span longer than one page is split."""
        start = helpers.to_timestamp("2026-01-01")
        end = helpers.to_timestamp("2026-01-11")
        windows = helpers._chart_windows(start, end, "1440", window=3)

        assert len(windows) == 4
        assert windows[0][0] == start

    def test_degenerate_span(self):
        """A span that yields no stamps falls back to itself."""
        start = helpers.to_timestamp("2026-01-01")

        assert helpers._chart_windows(start, start, "1D") == [(start, start)]


class TestOhlc:
    """Candles come back as records, oldest first."""

    @pytest.mark.asyncio
    async def test_columnar_to_records(self, monkeypatch, load):
        """The columnar response is turned into one record per candle."""
        chart = load("tradingview_chart")

        async def _request(method, params=None, use_cache=True):
            return load("instruments_future")

        async def _gather(calls, use_cache=True):
            return [chart for _ in calls]

        monkeypatch.setattr("openbb_deribit.utils.client.request", _request)
        monkeypatch.setattr("openbb_deribit.utils.client.gather", _gather)
        rows = await helpers.get_ohlc_data(
            "BTC-PERPETUAL", "2026-09-13", "2026-09-20", "1d"
        )

        assert len(rows) == len(chart["ticks"])
        assert rows == sorted(rows, key=lambda row: row["date"])
        assert isinstance(rows[0]["date"], date)
        assert set(rows[0]) == {
            "date",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "volume_notional",
        }

    @pytest.mark.asyncio
    async def test_intraday_keeps_time(self, monkeypatch, load):
        """An intraday interval keeps the time of day on the candle."""
        chart = load("tradingview_chart")

        async def _request(method, params=None, use_cache=True):
            return load("instruments_future")

        async def _gather(calls, use_cache=True):
            return [chart]

        monkeypatch.setattr("openbb_deribit.utils.client.request", _request)
        monkeypatch.setattr("openbb_deribit.utils.client.gather", _gather)
        rows = await helpers.get_ohlc_data(
            "BTC-PERPETUAL", "2026-09-20", "2026-09-20", "1h"
        )

        assert isinstance(rows[0]["date"], datetime)

    @pytest.mark.asyncio
    async def test_unknown_symbol(self, responder, load):
        """An unlisted symbol is rejected before any candle is asked for."""
        responder({"get_instruments": load("instruments_future")})

        with pytest.raises(OpenBBError, match="no instrument named"):
            await helpers.get_ohlc_data("NOPE", "2026-01-01", "2026-01-02", "1d")

    @pytest.mark.asyncio
    async def test_span_too_wide(self, responder, load):
        """A span needing more pages than the exchange serves is rejected."""
        responder({"get_instruments": load("instruments_future")})

        with pytest.raises(OpenBBError, match="at most"):
            await helpers.get_ohlc_data(
                "BTC-PERPETUAL", "2019-01-01", "2026-01-01", "1m"
            )

    @pytest.mark.asyncio
    async def test_no_candles(self, monkeypatch, load):
        """A symbol that published nothing raises rather than returning empty."""

        async def _request(method, params=None, use_cache=True):
            return load("instruments_future")

        async def _gather(calls, use_cache=True):
            return [{"status": "no_data"}]

        monkeypatch.setattr("openbb_deribit.utils.client.request", _request)
        monkeypatch.setattr("openbb_deribit.utils.client.gather", _gather)

        with pytest.raises(EmptyDataError):
            await helpers.get_ohlc_data(
                "BTC-PERPETUAL", "2026-09-19", "2026-09-20", "1d"
            )


class TestCurveByHoursAgo:
    """A past curve is read off traded closes."""

    @pytest.mark.asyncio
    async def test_picks_the_nearest_candle(self, monkeypatch, load):
        """The close nearest the target hour is the one reported."""
        target = helpers.to_timestamp(
            datetime.now(timezone.utc).replace(microsecond=0, second=0, minute=0)
        )
        hour = 3600000

        async def _request(method, params=None, use_cache=True):
            return load("instruments_future")

        async def _gather(calls, use_cache=True):
            return [
                {
                    "ticks": [target - 25 * hour, target - 24 * hour, target - hour],
                    "close": [1.0, 2.0, 3.0],
                }
                for _ in calls
            ]

        monkeypatch.setattr("openbb_deribit.utils.client.request", _request)
        monkeypatch.setattr("openbb_deribit.utils.client.gather", _gather)
        curve = await helpers.get_futures_curve_by_hours_ago("BTC", 24)

        assert curve
        assert all(row["last_price"] == 2.0 for row in curve)
        assert all(row["hours_ago"] == 24 for row in curve)

    @pytest.mark.asyncio
    async def test_skips_contracts_with_no_candles(self, monkeypatch, load):
        """A contract the exchange published no candle for is left out."""

        async def _request(method, params=None, use_cache=True):
            return load("instruments_future")

        async def _gather(calls, use_cache=True):
            return [{"status": "no_data"} for _ in calls]

        monkeypatch.setattr("openbb_deribit.utils.client.request", _request)
        monkeypatch.setattr("openbb_deribit.utils.client.gather", _gather)

        assert await helpers.get_futures_curve_by_hours_ago("BTC", 24) == []
