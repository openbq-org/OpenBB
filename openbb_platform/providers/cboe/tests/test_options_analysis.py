"""Tests for the Cboe options analysis utilities."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from openbb_core.app.model.abstract.error import OpenBBError

from openbb_cboe.utils.options import data_handler, trade_optimizer
from openbb_cboe.utils.options.create_payoff import (
    _breakeven_labels,
    _label,
    _legs,
    _position_legs,
    create_payoff,
    payoff_curve,
)
from openbb_cboe.utils.options.create_smile import (
    _first_priced_expiration,
    create_smile,
)
from openbb_cboe.utils.options.create_stats import create_stats
from openbb_cboe.utils.options.create_surface import create_surface
from openbb_cboe.utils.options.create_term_structure import create_term_structure
from openbb_cboe.utils.options.legs import (
    build_calendar,
    build_naked,
    build_straddle,
    build_strangle,
    leg_value,
    naked_quotes,
    option_value,
)
from openbb_cboe.utils.options.strategies import to_spreads, to_strategies


class TestDataHandler:
    """Per-symbol chain cache and dropdown choices."""

    def test_load_symbol_caches(self, options_chain):
        """A symbol is fetched once and served from the cache thereafter."""
        fetch = AsyncMock(return_value=options_chain)

        with patch(
            "openbb_cboe.models.options_chains.CboeOptionsChainsFetcher.fetch_data",
            new=fetch,
        ):
            first = asyncio.run(data_handler.load_symbol("clx"))
            second = asyncio.run(data_handler.load_symbol("CLX"))

        assert first is second
        fetch.assert_awaited_once()

    def test_load_symbol_update_refetches(self, options_chain):
        """``update`` bypasses the cache."""
        fetch = AsyncMock(return_value=options_chain)

        with patch(
            "openbb_cboe.models.options_chains.CboeOptionsChainsFetcher.fetch_data",
            new=fetch,
        ):
            asyncio.run(data_handler.load_symbol("CLX"))
            asyncio.run(data_handler.load_symbol("CLX", update=True))

        assert fetch.await_count == 2

    def test_load_symbol_wraps_fetch_errors(self):
        """A fetcher error surfaces as a symbol-specific OpenBBError."""
        with (
            patch(
                "openbb_cboe.models.options_chains.CboeOptionsChainsFetcher.fetch_data",
                new=AsyncMock(side_effect=OpenBBError("boom")),
            ),
            pytest.raises(OpenBBError, match="No options available for NOPE"),
        ):
            asyncio.run(data_handler.load_symbol("NOPE"))

    def test_load_symbol_rejects_empty_chain(self):
        """A chain with no expirations is treated as unavailable."""
        empty = type("Empty", (), {"expirations": []})()

        with (
            patch(
                "openbb_cboe.models.options_chains.CboeOptionsChainsFetcher.fetch_data",
                new=AsyncMock(return_value=empty),
            ),
            pytest.raises(OpenBBError, match="No options available"),
        ):
            asyncio.run(data_handler.load_symbol("NOPE"))

    def test_choices_empty_when_not_loaded(self):
        """Choices are empty until the symbol has been loaded."""
        assert data_handler.get_expirations("CLX") == []
        assert data_handler.get_strikes("CLX") == []

    def test_choices_after_load(self, options_chain):
        """Expiration and strike choices come from the cached chain."""
        data_handler.LOADED_SYMBOLS["CLX"] = options_chain
        expirations = data_handler.get_expirations("CLX")
        strikes = data_handler.get_strikes("CLX")

        assert (
            expirations[0]["value"] == data_handler.chain_expirations(options_chain)[0]
        )
        assert strikes[0] == {"label": "Nearest OTM", "value": None}
        assert strikes[1]["value"] == options_chain.strikes[0]
        assert "Underlying" in strikes[1]["extraInfo"]["rightOfDescription"]


class TestSmile:
    """Implied-volatility smile builder."""

    def test_default_expiration_skips_zero_iv(self, options_chain):
        """The default expiration is the front one that still carries IV."""
        expiration = _first_priced_expiration(options_chain)

        assert expiration in options_chain.expirations

    def test_no_priced_expiration_falls_back(self, options_chain):
        """With no priced contracts the front expiration is used."""
        stub = type(
            "Stub",
            (),
            {
                "dataframe": options_chain.dataframe.assign(implied_volatility=0.0),
                "expirations": options_chain.expirations,
            },
        )()

        assert (
            _first_priced_expiration(stub)
            == data_handler.chain_expirations(options_chain)[0]
        )

    def test_builds_chart(self, options_chain):
        """The default smile renders two traces and returns the plotted rows."""
        output = create_smile(options_chain)

        assert output.chart.format == "plotly"
        assert len(output.chart.content["data"]) == 2
        assert output.results

    def test_otm_and_skew(self, options_chain):
        """The OTM and skew variants both render."""
        output = create_smile(options_chain, otm=True, skew=True, theme="light")

        assert len(output.chart.content["data"]) == 2

    def test_list_of_expirations(self, options_chain):
        """A list of expirations plots one pair of traces per date."""
        expirations = options_chain.expirations[1:3]
        output = create_smile(options_chain, expirations=expirations)

        assert len(output.chart.content["data"]) == 2 * len(expirations)

    def test_too_many_expirations(self, options_chain):
        """More than five expirations is rejected."""
        with pytest.raises(OpenBBError, match="Too many dates"):
            create_smile(options_chain, expirations=options_chain.expirations[:6])

    def test_requires_iv(self, options_chain):
        """A chain without implied volatility is rejected."""
        stub = type("Stub", (), {"has_iv": False})()

        with pytest.raises(OpenBBError, match="Implied Volatility"):
            create_smile(stub)


class TestStats:
    """Open interest and volume statistics builder."""

    @pytest.mark.parametrize("unit", ["value", "percent", "pcr"])
    def test_units(self, options_chain, unit):
        """Every unit mode renders a bar chart."""
        output = create_stats(options_chain, unit=unit)

        assert output.chart.content["data"]

    def test_by_strike_for_one_expiration(self, options_chain):
        """Passing a date switches the axis to strikes."""
        output = create_stats(
            options_chain,
            by="strike",
            metric="volume",
            date=options_chain.expirations[1],
            theme="light",
        )

        assert output.chart.content["data"]


# pandas warns that way when a frame that is a view of another is written to. The
# class it uses is not in every version, so it is matched by what it says, and the
# message starts on a new line, hence the flag that lets ``.`` match one.
@pytest.mark.filterwarnings("error:(?s).*trying to be set on a copy of a slice")
class TestSurface:
    """3-D surface builder."""

    @pytest.mark.parametrize("option_type", ["otm", "itm", "calls", "puts"])
    def test_option_types(self, options_chain, option_type):
        """Every side of the chain renders a surface."""
        output = create_surface(options_chain, option_type=option_type)

        assert output.chart.content["data"]

    @pytest.mark.parametrize("metric", ["delta", "gamma", "theta", "vega", "rho"])
    def test_greeks(self, options_chain, metric):
        """Cboe greeks are plottable as the Z axis."""
        output = create_surface(options_chain, metric=metric)

        assert output.chart.content["data"]

    def test_case_insensitive_exposure_columns(self, options_chain):
        """The upper-cased DEX/GEX columns resolve from lowercase metric names."""
        output = create_surface(options_chain, metric="gex", theme="light")

        assert output.chart.content["data"]

    def test_filters(self, options_chain):
        """DTE, moneyness, open-interest, and volume filters all apply."""
        output = create_surface(
            options_chain,
            dte_range=[0, 400],
            moneyness=25,
            oi=True,
            volume=True,
        )

        assert output.chart.content["data"]

    def test_unknown_metric(self, options_chain):
        """An absent metric is rejected."""
        with pytest.raises(OpenBBError, match="No nope data"):
            create_surface(options_chain, metric="nope")


class TestTermStructure:
    """Term-structure builder."""

    def test_default(self, options_chain):
        """The default plots calls and puts at the nearest OTM strikes."""
        output = create_term_structure(options_chain)

        assert len(output.chart.content["data"]) == 2

    def test_by_strike(self, options_chain):
        """A fixed strike is honored."""
        strike = options_chain.strikes[len(options_chain.strikes) // 2]
        output = create_term_structure(
            options_chain, strike=strike, metric="price", option_type="calls"
        )

        assert len(output.chart.content["data"]) == 1

    def test_by_moneyness(self, options_chain):
        """A moneyness target is honored."""
        output = create_term_structure(
            options_chain, moneyness=10, option_type="puts", theme="light"
        )

        assert len(output.chart.content["data"]) == 1

    def test_requires_iv(self, options_chain):
        """Requesting IV on a chain without it is rejected."""
        stub = type("Stub", (), {"has_iv": False})()

        with pytest.raises(OpenBBError, match="No implied volatility"):
            create_term_structure(stub, metric="iv")


class TestStrategies:
    """Strategy and spread row conversion."""

    def test_strategies(self, options_chain):
        """Straddle rows validate against StrategyData."""
        df = options_chain.strategies(days=-1)
        rows = to_strategies(df)

        assert rows
        assert rows[0].strike_1
        assert rows[0].dte >= 0

    def test_spreads(self, options_chain):
        """Vertical spread rows validate against SpreadData."""
        last = options_chain.underlying_price[0]
        df = options_chain.strategies(
            days=-1, vertical_calls=[(last * 1.075, last * 1.025)]
        )
        rows = to_spreads(df)

        assert rows
        assert rows[0].strategy


class TestCalendarPayoff:
    """A calendar spread is valued on the near expiration."""

    NEAR = {
        "quotes": {
            ("short", "p", 736.0): {
                "price": 2.91,
                "dte": 1,
                "expiration": "2026-07-31",
                "iv": 0.2144,
                "theoretical_price": 9.2691,
            }
        },
        "forward": 736.44,
        "discount": 1.0001,
        "dte": 1,
    }
    FAR = {
        "quotes": {
            ("long", "p", 736.0): {
                "price": 17.96,
                "dte": 32,
                "expiration": "2026-08-31",
                "iv": 0.162,
                "theoretical_price": 16.8603,
            }
        },
        "forward": 737.93,
        "discount": 1.0028,
        "dte": 32,
    }
    SPOT = 736.42

    @staticmethod
    def _position():
        from openbb_cboe.utils.options.legs import build_calendar

        return build_calendar(
            TestCalendarPayoff.NEAR,
            TestCalendarPayoff.FAR,
            TestCalendarPayoff.SPOT,
            option_type="p",
        )

    def test_each_leg_is_valued_at_the_volatility_it_was_quoted_at(self):
        """A chain publishes a volatility its own price does not imply."""
        from openbb_cboe.utils.options.legs import leg_value

        position = self._position()
        near, far = position["legs"]

        assert far["iv"] != self.FAR["quotes"][("long", "p", 736.0)]["iv"]

        for leg in (near, far):
            assert leg_value(leg, self.SPOT, 0) == pytest.approx(leg["price"], abs=0.01)

    def test_the_position_opens_at_what_it_cost(self):
        """A position that has not moved has neither made nor lost anything."""
        from openbb_cboe.utils.options.legs import payoff_from_legs

        position = self._position()

        assert payoff_from_legs(position["legs"], [self.SPOT], 0)[0] == pytest.approx(
            0, abs=1
        )

    def test_the_payoff_peaks_at_the_strike(self):
        """The short leg expires worthless there and the long one does not."""
        from openbb_cboe.utils.options.legs import payoff_from_legs

        position = self._position()
        prices = [700 + index / 2 for index in range(150)]
        payoff = payoff_from_legs(position["legs"], prices, position["elapsed"])
        peak = prices[payoff.index(max(payoff))]

        assert max(payoff) > 0
        assert peak == pytest.approx(736.0, abs=1)

    def test_the_payoff_loses_on_both_wings(self):
        from openbb_cboe.utils.options.legs import payoff_from_legs

        position = self._position()
        payoff = payoff_from_legs(
            position["legs"], [600.0, 736.0, 900.0], position["elapsed"]
        )

        assert payoff[0] < 0
        assert payoff[1] > 0
        assert payoff[2] < 0

    def test_the_payoff_breaks_even_on_both_sides(self):
        from openbb_cboe.utils.options.create_payoff import _breakevens
        from openbb_cboe.utils.options.legs import payoff_from_legs

        position = self._position()
        prices = [600 + index for index in range(301)]
        crossings = _breakevens(
            prices, payoff_from_legs(position["legs"], prices, position["elapsed"])
        )

        assert len(crossings) == 2
        assert crossings[0] < 736.0 < crossings[1]

    def test_a_price_no_volatility_implies_falls_back_to_the_chain(self):
        from openbb_cboe.utils.options.legs import implied_vol

        assert implied_vol(0.0, 736.0, 736.0, 0.1, 1.0, "p") is None
        assert implied_vol(5.0, 736.0, 736.0, 0.0, 1.0, "p") is None
        assert implied_vol(500.0, 736.0, 736.0, 0.1, 1.0, "p") is None
        assert implied_vol(50.0, 736.0, 900.0, 0.1, 1.0, "p") is None

    def test_the_range_is_wide_enough_to_read(self):
        """A single strike must not collapse the diagram onto the spot."""
        from openbb_cboe.utils.options.create_payoff import _bounds

        low, high = _bounds(736.42, 736.37, [736.0], [])

        assert high - low > 736.42 * 0.1


class TestLegPricing:
    """A leg is priced at what the chain quotes its contract at."""

    MARKS = {
        "contracts": {
            ("c", 736.0): {
                "iv": 0.1623,
                "theoretical_price": 11.24,
                "bid": 11.15,
                "ask": 11.26,
            },
            ("c", 740.0): {
                "iv": 0.16,
                "theoretical_price": 9.1,
                "bid": None,
                "ask": None,
            },
        },
        "dte": 29,
    }
    ROWS = [
        {
            "strategy": "Naked Short",
            "type": "c",
            "strike1": 736.0,
            "current_price": 15.6,
            "expiry": "2026-08-28",
        },
        {
            "strategy": "Naked Long",
            "type": "c",
            "strike1": 736.0,
            "current_price": 15.6,
            "expiry": "2026-08-28",
        },
        {
            "strategy": "Naked Long",
            "type": "c",
            "strike1": 740.0,
            "current_price": 9.5,
            "expiry": "2026-08-28",
        },
    ]

    def test_selling_takes_the_bid_and_buying_takes_the_ask(self):
        """The optimizer's 'current_price' belongs to the strategy, not the leg."""
        from openbb_cboe.utils.options.legs import naked_quotes

        quotes = naked_quotes(self.ROWS, self.MARKS)

        assert quotes[("short", "c", 736.0)]["price"] == 11.15
        assert quotes[("long", "c", 736.0)]["price"] == 11.26

    def test_an_unquoted_contract_keeps_what_the_optimizer_named(self):
        from openbb_cboe.utils.options.legs import naked_quotes

        quotes = naked_quotes(self.ROWS, self.MARKS)

        assert quotes[("long", "c", 740.0)]["price"] == 9.5

    def test_multi_leg_rows_are_not_quotes(self):
        """Only the naked strategies quote a single contract."""
        rows = [
            {
                "strategy": "Long Spread",
                "type": "c",
                "strike1": 100.0,
                "current_price": 5.0,
            }
        ]

        assert naked_quotes(rows, self.MARKS) == {}

    def test_the_chain_carries_the_quote_of_every_contract(self, options_chain):
        """The marks must publish the two sides a leg is priced from.

        Reads the expiration from ``chain_expirations`` rather than the model's
        own list: the bundled payload ages, and its earliest expiration has
        since passed, so ``expirations[0]`` names a date the frame has dropped.
        """
        expiration = data_handler.chain_expirations(options_chain)[0]

        with patch(
            "openbb_cboe.utils.options.data_handler.load_symbol",
            new=AsyncMock(return_value=options_chain),
        ):
            marks = asyncio.run(data_handler.get_chain_marks("CLX", expiration))

        published = next(iter(marks["contracts"].values()))

        assert {"bid", "ask", "iv", "theoretical_price"} <= set(published)


class TestImpliedForward:
    """The forward and discount a chain of put-call pairs implies."""

    @staticmethod
    def _records(slope: float) -> list[dict]:
        records: list[dict] = []

        for strike in (90.0, 95.0, 100.0, 105.0, 110.0):
            records.append(
                {
                    "strike": strike,
                    "option_type": "call",
                    "theoretical_price": slope * (strike - 100.0) + 20.0,
                }
            )
            records.append(
                {"strike": strike, "option_type": "put", "theoretical_price": 20.0}
            )

        return records

    def test_regresses_the_forward_from_put_call_gaps(self):
        """The gap declines by the discount factor per unit of strike."""
        records = self._records(-1.0)
        records.append(
            {"strike": 90.0, "option_type": "call", "theoretical_price": None}
        )
        forward, discount = data_handler._implied_forward(records)

        assert forward == pytest.approx(100.0)
        assert discount == pytest.approx(1.0)

    def test_too_few_pairs_imply_nothing(self):
        """Fewer than five paired strikes regress nothing."""
        records = self._records(-1.0)[:8]

        assert data_handler._implied_forward(records) == (0.0, 1.0)

    def test_an_inverted_slope_is_rejected(self):
        """A gap that grows with the strike implies a negative discount."""
        assert data_handler._implied_forward(self._records(1.0)) == (0.0, 1.0)


class TestChainMarks:
    """The published marks for one expiration."""

    EMPTY = {"contracts": {}, "forward": 0.0, "discount": 1.0, "dte": 0}

    def test_a_symbol_that_fails_to_load_marks_nothing(self):
        """A load failure yields the empty marks."""
        with patch(
            "openbb_cboe.utils.options.data_handler.load_symbol",
            new=AsyncMock(side_effect=OpenBBError("no")),
        ):
            marks = asyncio.run(data_handler.get_chain_marks("NOPE", "2026-01-01"))

        assert marks == self.EMPTY

    def test_an_unpublished_expiration_marks_nothing(self, options_chain):
        """An expiration absent from the chain yields the empty marks."""
        with patch(
            "openbb_cboe.utils.options.data_handler.load_symbol",
            new=AsyncMock(return_value=options_chain),
        ):
            marks = asyncio.run(data_handler.get_chain_marks("CLX", "2099-12-31"))

        assert marks == self.EMPTY


class TestTradeOptimizerTransport:
    """Optimizer endpoints and the sentiment math."""

    def test_symbol_info(self):
        """A successful response is handed back whole."""
        payload = {
            "success": True,
            "details": {"current_price": 100.0},
            "expirations": ["2026-08-28"],
        }

        with patch(
            "openbb_cboe.utils.helpers.get_cboe_data",
            new=AsyncMock(return_value=payload),
        ) as transport:
            info = asyncio.run(trade_optimizer.get_symbol_info("spy"))

        assert info is payload
        assert "symbol=SPY" in transport.await_args.args[0]

    def test_uncovered_symbol_raises(self):
        """A symbol the optimizer does not cover raises."""
        with (
            patch(
                "openbb_cboe.utils.helpers.get_cboe_data",
                new=AsyncMock(return_value={}),
            ),
            pytest.raises(OpenBBError, match="does not cover NOPE"),
        ):
            asyncio.run(trade_optimizer.get_symbol_info("NOPE"))

    def test_strategies(self):
        """The ranked strategies come from the results block."""
        payload = {"results": [{"strategy": "Long Spread"}]}

        with patch(
            "openbb_cboe.utils.helpers.get_cboe_data",
            new=AsyncMock(return_value=payload),
        ) as transport:
            rows = asyncio.run(
                trade_optimizer.get_strategies("spy", "2026-08-28", 105.0)
            )

        assert rows == [{"strategy": "Long Spread"}]
        assert "targetDate=2026-08-28" in transport.await_args.args[0]

    def test_no_strategies_raises(self):
        """An empty results block raises."""
        with (
            patch(
                "openbb_cboe.utils.helpers.get_cboe_data",
                new=AsyncMock(return_value={"results": []}),
            ),
            pytest.raises(OpenBBError, match="No strategies"),
        ):
            asyncio.run(trade_optimizer.get_strategies("SPY", "2026-08-28", 105.0))

    def test_target_price_orders_by_sentiment(self):
        """A more bullish view targets a higher quantile of the distribution."""
        prices = [
            trade_optimizer.target_price(100.0, 25.0, 30, sentiment)
            for sentiment in ("very_bearish", "neutral", "very_bullish")
        ]

        assert prices == sorted(prices)
        assert prices[1] == pytest.approx(100.0, rel=0.01)

    def test_probability_below(self):
        """Zero volatility is a coin flip; otherwise the price orders it."""
        assert trade_optimizer.probability_below(100.0, 0.0, 30, 100.0) == 0.5

        below = trade_optimizer.probability_below(100.0, 25.0, 30, 90.0)
        above = trade_optimizer.probability_below(100.0, 25.0, 30, 110.0)

        assert below < 0.5 < above


class TestOptionValuation:
    """Contract valuation off the forward."""

    def test_an_expired_contract_is_worth_its_intrinsic(self):
        assert option_value(110.0, 100.0, 0.0, 0.2, 1.0, "c") == 10.0

    def test_puts_and_calls_agree_at_the_forward(self):
        """Put-call parity holds when the strike sits on the forward."""
        call = option_value(100.0, 100.0, 0.5, 0.2, 1.0, "c")
        put = option_value(100.0, 100.0, 0.5, 0.2, 1.0, "p")

        assert call > 0
        assert call == pytest.approx(put, abs=1e-9)

    def test_a_live_leg_without_volatility_raises(self):
        leg = {
            "type": "c",
            "strike": 100.0,
            "quantity": 1,
            "price": 5.0,
            "dte": 30,
            "iv": None,
            "expiration": "2026-08-28",
        }

        with pytest.raises(OpenBBError, match="no implied volatility"):
            leg_value(leg, 100.0, 0)


def _quote(price: float, dte: int = 30, iv: float | None = 0.22) -> dict:
    """Build one quoted contract for a position book."""
    return {
        "price": price,
        "dte": dte,
        "expiration": "2026-08-28",
        "iv": iv,
        "theoretical_price": price,
    }


class TestPositionBuilders:
    """Single- and multi-leg positions assembled from a quote book."""

    BOOK = {
        "quotes": {
            ("long", "c", 100.0): _quote(5.1),
            ("long", "p", 100.0): _quote(4.9),
            ("short", "c", 105.0): _quote(2.5),
            ("short", "p", 95.0): _quote(2.2),
        },
        "forward": 100.5,
        "discount": 1.0,
        "dte": 30,
    }

    def test_naked_long_takes_the_nearest_strike(self):
        position = build_naked(self.BOOK, 101.0, "c")

        assert position["legs"][0]["strike"] == 100.0
        assert position["legs"][0]["quantity"] == 1
        assert position["elapsed"] == 30

    def test_naked_short_uses_the_short_side(self):
        position = build_naked(self.BOOK, 101.0, "c", sell=True)

        assert position["legs"][0]["strike"] == 105.0
        assert position["legs"][0]["quantity"] == -1

    def test_naked_without_quotes_raises(self):
        with pytest.raises(OpenBBError, match="no contract"):
            build_naked({"quotes": {}}, 100.0, "c")

    def test_straddle_shares_one_strike(self):
        position = build_straddle(self.BOOK, 100.4)

        assert [leg["strike"] for leg in position["legs"]] == [100.0, 100.0]
        assert [leg["type"] for leg in position["legs"]] == ["c", "p"]

    def test_straddle_without_a_shared_strike_raises(self):
        with pytest.raises(OpenBBError, match="no strike on both sides"):
            build_straddle(self.BOOK, 100.0, sell=True)

    def test_strangle_places_each_wing(self):
        position = build_strangle(self.BOOK, 100.0, 0.05)

        assert [leg["type"] for leg in position["legs"]] == ["c", "p"]
        assert all(leg["quantity"] == 1 for leg in position["legs"])

    def test_strangle_without_a_wing_raises(self):
        book = {"quotes": {("short", "c", 105.0): _quote(2.5)}}

        with pytest.raises(OpenBBError, match="no wing"):
            build_strangle(book, 100.0, sell=True)

    def test_calendar_without_a_shared_strike_raises(self):
        near = {
            "quotes": {("short", "c", 100.0): _quote(5.0)},
            "forward": 100.5,
            "discount": 1.0,
        }
        far = {
            "quotes": {("long", "c", 110.0): _quote(7.0, dte=60)},
            "forward": 101.0,
            "discount": 0.99,
        }

        with pytest.raises(OpenBBError, match="both expirations"):
            build_calendar(near, far, 100.0)

    def test_calendar_without_a_forward_raises(self):
        near = {
            "quotes": {("short", "c", 100.0): _quote(5.0)},
            "forward": 0.0,
            "discount": 1.0,
        }
        far = {
            "quotes": {("long", "c", 100.0): _quote(7.0, dte=60)},
            "forward": 101.0,
            "discount": 0.99,
        }

        with pytest.raises(OpenBBError, match="no forward"):
            build_calendar(near, far, 100.0)


class TestPayoffCurve:
    """Ranked-strategy payoff arithmetic."""

    def test_naked_short_call(self):
        row = {
            "strategy": "Naked Short",
            "type": "c",
            "strike1": 100.0,
            "current_price": 5.0,
        }

        assert payoff_curve(row, [90.0, 110.0]) == [500.0, -500.0]

    def test_naked_long_put(self):
        row = {
            "strategy": "Naked Long",
            "type": "p",
            "strike1": 100.0,
            "current_price": 5.0,
        }

        assert payoff_curve(row, [90.0, 110.0]) == [500.0, -500.0]

    def test_long_spread(self):
        row = {
            "strategy": "Long Spread",
            "type": "c",
            "strike1": 100.0,
            "strike2": 110.0,
            "current_price": 4.0,
        }

        assert payoff_curve(row, [90.0, 120.0]) == [-400.0, 600.0]

    def test_short_spread(self):
        row = {
            "strategy": "Short Spread",
            "type": "c",
            "strike1": 100.0,
            "strike2": 110.0,
            "current_price": 4.0,
        }

        assert payoff_curve(row, [90.0, 120.0]) == [400.0, -600.0]


class TestPayoffDescriptions:
    """Titles and leg descriptions on the payoff diagram."""

    def test_label_known_and_unknown(self):
        assert _label({"strategy": "Long Spread", "type": "c"}) == "Buy Call Spread"
        assert _label({"strategy": "Iron Condor", "type": "c"}) == "Iron Condor"

    def test_legs_naked(self):
        row = {
            "strategy": "Naked Short",
            "type": "c",
            "symbol": "SPY",
            "expiry": "2026-08-28",
            "strike1": 100.0,
        }

        assert _legs(row) == "Sell SPY 2026-08-28 100 Call"

    def test_legs_spread_verbs(self):
        row = {
            "strategy": "Short Spread",
            "type": "p",
            "symbol": "SPY",
            "expiry": "2026-08-28",
            "strike1": 100.0,
            "strike2": 95.0,
        }

        assert _legs(row) == ("Sell SPY 2026-08-28 100 Put, Buy SPY 2026-08-28 95 Put")

    def test_position_legs(self):
        position = {
            "legs": [
                {
                    "quantity": 1,
                    "type": "c",
                    "expiration": "2026-08-28",
                    "strike": 100.0,
                },
                {
                    "quantity": -1,
                    "type": "p",
                    "expiration": "2026-08-28",
                    "strike": 95.0,
                },
            ]
        }

        assert _position_legs(position, "SPY") == (
            "Buy SPY 2026-08-28 100 Call, Sell SPY 2026-08-28 95 Put"
        )

    def test_breakeven_labels(self):
        assert _breakeven_labels(2) == ["Lower B/E", "Upper B/E"]
        assert _breakeven_labels(1) == ["B/E"]


class TestCreatePayoff:
    """The payoff diagram for ranked rows and assembled positions."""

    ROW = {
        "strategy": "Long Spread",
        "type": "c",
        "strike1": 100.0,
        "strike2": 110.0,
        "current_price": 4.0,
        "symbol": "SPY",
        "expiry": "2026-08-28",
        "target_stock_price": 112.0,
    }

    def test_a_ranked_row_draws_debit_pricing(self):
        output = create_payoff(
            {"symbol": "SPY", "strategy": dict(self.ROW), "spot": 100.0}
        )
        title = output.chart.content["layout"]["title"]["text"]

        assert "Buy Call Spread for $4.00" in title
        assert output.chart.content["data"]
        assert output.results

    def test_a_credit_is_priced_as_a_credit(self):
        row = dict(self.ROW) | {"strategy": "Short Spread"}
        output = create_payoff({"symbol": "SPY", "strategy": row, "spot": 100.0})
        title = output.chart.content["layout"]["title"]["text"]

        assert "Sell Call Spread for a $4.00 credit" in title

    def test_an_assembled_position_is_valued_from_its_legs(self):
        leg = {
            "type": "c",
            "strike": 100.0,
            "quantity": 1,
            "price": 5.0,
            "dte": 30,
            "iv": 0.22,
            "theoretical_price": 5.0,
            "expiration": "2026-08-28",
        }
        position = {"legs": [leg], "elapsed": 30, "label": "Buy Call"}
        output = create_payoff(
            {"symbol": "SPY", "position": position, "spot": 100.0, "target": 108.0}
        )
        title = output.chart.content["layout"]["title"]["text"]

        assert "Buy Call for $5.00" in title
        assert output.chart.content["data"]


class TestOptionalCharting:
    """Without the charting extension a view returns the rows it would draw."""

    @pytest.fixture
    def unplotted(self, monkeypatch):
        """Run as though openbb-charting were not installed."""
        import openbb_cboe

        monkeypatch.setattr(openbb_cboe, "CHARTING_INSTALLED", False)

    def test_a_figure_that_cannot_be_drawn_draws_nothing(self, unplotted):
        from openbb_cboe.utils.options.theme import Unplotted, new_figure

        fig, text_color, background = new_figure("dark")

        assert isinstance(fig, Unplotted)
        assert text_color == "white"
        assert background == "rgba(0,0,0,0)"
        assert fig.add_scatter(x=[1], y=[2]).update_layout(title="x") is fig

    def test_nothing_is_attached_to_the_result(self, unplotted):
        from openbb_core.app.model.obbject import OBBject

        from openbb_cboe.utils.options.theme import Unplotted, finalize

        output = OBBject(results=[])

        assert finalize(output, Unplotted(), "dark") is output
        assert output.chart is None

    def test_every_view_returns_its_rows(self, unplotted, options_chain):
        from openbb_cboe.utils.options.create_smile import create_smile
        from openbb_cboe.utils.options.create_stats import create_stats
        from openbb_cboe.utils.options.create_surface import create_surface
        from openbb_cboe.utils.options.create_term_structure import (
            create_term_structure,
        )

        for builder in (
            create_smile,
            create_stats,
            create_surface,
            create_term_structure,
        ):
            output = builder(options_chain, theme="dark")

            assert output.chart is None, builder.__name__
            assert output.results, builder.__name__

    def test_the_route_hands_back_rows(self, unplotted, options_chain):
        from unittest.mock import AsyncMock, patch

        from openbb_cboe.routers import options

        with patch(
            "openbb_cboe.utils.options.data_handler.load_symbol",
            new=AsyncMock(return_value=options_chain),
        ):
            drawn = asyncio.run(options.smile_chart(symbol="CLX"))

        assert isinstance(drawn, list)
        assert drawn and isinstance(drawn[0], dict)


class TestChainExpirations:
    """Expirations offered must be expirations that resolve to rows."""

    def test_drops_expirations_the_frame_no_longer_carries(self, options_chain):
        """A passed expiration is not offered, even though the payload still lists it.

        ``dataframe`` drops expired contracts but ``expirations`` does not, so a
        chain fetched after an expiration led its picker with a date whose
        quotes came back empty.
        """
        offered = data_handler.chain_expirations(options_chain)
        in_frame = {str(v) for v in options_chain.dataframe["expiration"]}

        assert offered
        assert set(offered) == in_frame
        assert set(offered) <= set(options_chain.expirations)

    def test_the_dropdown_offers_only_live_expirations(self, options_chain):
        """The picker is built from the same filtered list."""
        data_handler.LOADED_SYMBOLS["CLX"] = options_chain

        try:
            choices = data_handler.get_expirations("clx")
        finally:
            data_handler.LOADED_SYMBOLS.pop("CLX", None)

        assert [c["value"] for c in choices] == data_handler.chain_expirations(
            options_chain
        )

    def test_falls_back_when_there_is_no_frame(self):
        """A chain whose frame cannot be built still reports its own expirations."""

        class _NoFrame:
            expirations = ["2030-01-18"]

            @property
            def dataframe(self):
                raise ValueError("no validated data")

        assert data_handler.chain_expirations(_NoFrame()) == ["2030-01-18"]
