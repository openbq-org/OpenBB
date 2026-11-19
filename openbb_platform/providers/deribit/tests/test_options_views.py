"""Tests for the Deribit options charts and the commands that serve them."""

from datetime import UTC

import pytest

from openbb_deribit.routers import options as router
from openbb_deribit.utils.options import chain


class TestLoading:
    """A chain is read over REST, once, and shared while it is current."""

    @pytest.fixture(autouse=True)
    def _clean(self):
        """Start each test with nothing held."""
        chain._LOADED.clear()
        chain._LOCKS.clear()

        yield

        chain._LOADED.clear()
        chain._LOCKS.clear()

    @pytest.fixture
    def exchange(self, responder):
        """Publish one synthetic underlying over the three REST calls."""
        from datetime import datetime, timedelta

        from openbb_deribit.utils.helpers import to_timestamp

        def install(root="BTC", inverse=True, size=1.0, strikes=(0.31, 100.0)):
            now = datetime.now(UTC)
            expiry = to_timestamp(now + timedelta(days=30))
            names = [
                f"{root}-30OCT26-{strike:g}-{side}"
                for strike in strikes
                for side in ("C", "P")
            ]
            specs = [
                {
                    "instrument_name": name,
                    "strike": strike,
                    "option_type": "call" if name.endswith("C") else "put",
                    "contract_size": size,
                    "expiration_timestamp": expiry,
                    "instrument_type": "reversed" if inverse else "linear",
                    "price_index": f"{root.lower()}_usd",
                }
                for name, strike in zip(
                    names, [s for s in strikes for _ in range(2)], strict=True
                )
            ]
            quotes = [
                {
                    "instrument_name": spec["instrument_name"],
                    "mark_price": 0.01,
                    "bid_price": 0.009,
                    "ask_price": 0.011,
                    "last": 0.01,
                    "mark_iv": 50.0,
                    "open_interest": 10.0,
                    "volume": 5.0,
                    "volume_usd": 100.0,
                    "underlying_price": 100.0,
                }
                for spec in specs
            ]
            calls: list = []

            def summary(params):
                calls.append(("summary", params["currency"]))

                return quotes

            def instruments(params):
                calls.append(("instruments", params.get("currency")))

                return specs

            def index(params):
                calls.append(("index", params["index_name"]))

                return {"index_price": 100.0}

            responder(
                {
                    "get_book_summary_by_currency": summary,
                    "get_instruments": instruments,
                    "get_index_price": index,
                }
            )

            return calls

        return install

    @pytest.mark.asyncio
    async def test_reads_the_exchange_once(self, exchange):
        """One read makes one call to each of the three feeds."""
        calls = exchange()
        frame = await chain.load_chain("btc")

        assert len(frame) == 4
        assert [name for name, _ in calls] == ["summary", "instruments", "index"]

    @pytest.mark.asyncio
    async def test_a_second_read_reuses_the_first(self, exchange):
        """Reading the same chain twice queries the exchange once."""
        calls = exchange()
        first = await chain.load_chain("BTC")
        second = await chain.load_chain("BTC")

        assert len(calls) == 3
        assert first.equals(second)

    @pytest.mark.asyncio
    async def test_the_caller_cannot_alter_what_is_held(self, exchange):
        """A frame handed out is a copy, so editing it changes nothing."""
        exchange()
        first = await chain.load_chain("BTC")
        first["strike"] = 0.0

        assert (await chain.load_chain("BTC"))["strike"].max() > 0

    @pytest.mark.asyncio
    async def test_a_fresh_read_queries_again(self, exchange):
        """Asking for current data goes back to the exchange."""
        calls = exchange()
        await chain.load_chain("BTC")
        await chain.load_chain("BTC", use_cache=False)

        assert len(calls) == 6

    @pytest.mark.asyncio
    async def test_a_stale_read_is_not_reused(self, exchange, monkeypatch):
        """A read older than its lifetime is taken again."""
        calls = exchange()
        monkeypatch.setattr(chain, "CHAIN_TTL", 0.0)
        await chain.load_chain("BTC")
        await chain.load_chain("BTC")

        assert len(calls) == 6

    @pytest.mark.asyncio
    async def test_a_fractional_strike_survives(self, exchange):
        """A strike the instrument name spells with a letter is read intact."""
        exchange(root="TRX_USDC", inverse=False, size=10000.0, strikes=(0.31,))
        frame = await chain.load_chain("TRX_USDC")

        assert sorted(frame["strike"].unique()) == [0.31]
        assert sorted(frame["contract_size"].unique()) == [10000.0]

    @pytest.mark.asyncio
    async def test_an_inverse_premium_is_carried_to_the_quote(self, exchange):
        """A coin-quoted premium is carried at the index level."""
        exchange(inverse=True)
        frame = await chain.load_chain("BTC")

        assert frame["mark"].iloc[0] == pytest.approx(0.01 * 100.0)
        assert chain.is_inverse(frame) is True

    @pytest.mark.asyncio
    async def test_a_linear_premium_is_left_alone(self, exchange):
        """A premium already in the quote currency is not carried."""
        exchange(root="SOL_USDC", inverse=False, size=10.0)
        frame = await chain.load_chain("SOL_USDC")

        assert frame["mark"].iloc[0] == pytest.approx(0.01)
        assert chain.is_inverse(frame) is False

    @pytest.mark.asyncio
    async def test_greeks_are_modelled_from_the_quoted_volatility(self, exchange):
        """The exchange publishes no greeks here, so they are computed."""
        exchange()
        frame = await chain.load_chain("BTC")

        for greek in ("delta", "gamma", "theta", "vega", "rho"):
            assert frame[greek].notna().all()

        calls = frame[frame["option_type"] == "call"]
        puts = frame[frame["option_type"] == "put"]

        assert (calls["delta"] >= 0).all()
        assert (puts["delta"] <= 0).all()
        assert (frame["gamma"] >= 0).all()

        money = frame[frame["strike"] == 100.0]

        assert float(money[money["option_type"] == "call"]["delta"].iloc[0]) > 0.4
        assert float(money[money["option_type"] == "put"]["delta"].iloc[0]) < -0.4

    @pytest.mark.asyncio
    async def test_only_the_asked_for_root_is_kept(self, exchange, responder):
        """One settlement currency serves several roots, so the root is matched."""
        from datetime import datetime, timedelta

        from openbb_deribit.utils.helpers import to_timestamp

        expiry = to_timestamp(datetime.now(UTC) + timedelta(days=30))
        specs = [
            {
                "instrument_name": f"{root}-30OCT26-100-C",
                "strike": 100.0,
                "option_type": "call",
                "contract_size": 1.0,
                "expiration_timestamp": expiry,
                "instrument_type": "linear",
                "price_index": f"{root.lower()}",
            }
            for root in ("BTC_USDC", "XRP_USDC")
        ]
        responder(
            {
                "get_instruments": specs,
                "get_book_summary_by_currency": [
                    {
                        "instrument_name": spec["instrument_name"],
                        "mark_price": 1.0,
                        "bid_price": 1.0,
                        "ask_price": 1.0,
                        "last": 1.0,
                        "mark_iv": 50.0,
                        "open_interest": 1.0,
                        "volume": 1.0,
                        "volume_usd": 1.0,
                        "underlying_price": 100.0,
                    }
                    for spec in specs
                ],
                "get_index_price": {"index_price": 100.0},
            }
        )
        frame = await chain.load_chain("BTC_USDC")

        assert list(frame["contract_symbol"]) == ["BTC_USDC-30OCT26-100-C"]

    @pytest.mark.asyncio
    async def test_an_unlisted_underlying_says_so(self, responder):
        """An underlying nobody quotes raises rather than returning nothing."""
        from openbb_core.provider.utils.errors import EmptyDataError

        responder(
            {
                "get_instruments": [],
                "get_book_summary_by_currency": [],
                "get_index_price": {"index_price": 0.0},
            }
        )

        with pytest.raises(EmptyDataError, match="no option quotes for NOPE"):
            await chain.load_chain("NOPE")


class TestComboLoading:
    """The combo books listed on an underlying are read with their quotes."""

    @pytest.fixture(autouse=True)
    def _clean(self):
        """Start each test with nothing held."""
        chain._LOADED.clear()
        chain._LOCKS.clear()

        yield

        chain._LOADED.clear()
        chain._LOCKS.clear()

    @pytest.fixture
    def exchange(self, responder):
        """List option, other-root, and future combos on BTC."""
        calls: list = []

        def combos(params):
            calls.append(("combos", params["currency"]))

            return [
                {
                    "id": "BTC-CS-30OCT26-100000_110000",
                    "legs": [
                        {"instrument_name": "BTC-30OCT26-100000-C", "amount": 1},
                        {"instrument_name": "BTC-30OCT26-110000-C", "amount": -1},
                    ],
                },
                {
                    "id": "BTC-STRD-30OCT26-100000",
                    "legs": [
                        {"instrument_name": "BTC-30OCT26-100000-C", "amount": 1},
                        {"instrument_name": "BTC-30OCT26-100000-P", "amount": 1},
                    ],
                },
                {
                    "id": "BTC-FS-30OCT26_PERP",
                    "legs": [
                        {"instrument_name": "BTC-PERPETUAL", "amount": -1},
                        {"instrument_name": "BTC-30OCT26", "amount": 1},
                    ],
                },
                {
                    "id": "ETH-CS-30OCT26-3000_3100",
                    "legs": [
                        {"instrument_name": "ETH-30OCT26-3000-C", "amount": 1},
                        {"instrument_name": "ETH-30OCT26-3100-C", "amount": -1},
                    ],
                },
            ]

        def quotes(params):
            calls.append(("quotes", params["kind"]))

            return [
                {
                    "instrument_name": "BTC-CS-30OCT26-100000_110000",
                    "bid_price": 0.01,
                    "ask_price": 0.02,
                }
            ]

        responder({"get_combos": combos, "get_book_summary_by_currency": quotes})

        return calls

    @pytest.mark.asyncio
    async def test_only_the_underlyings_option_combos_are_kept(self, exchange):
        """Future spreads and other roots are left out."""
        books = await chain.load_combos("btc")

        assert [book["name"] for book in books] == [
            "BTC-CS-30OCT26-100000_110000",
            "BTC-STRD-30OCT26-100000",
        ]
        assert books[0]["legs"] == [
            ("BTC-30OCT26-100000-C", 1),
            ("BTC-30OCT26-110000-C", -1),
        ]

    @pytest.mark.asyncio
    async def test_each_combo_carries_its_quote(self, exchange):
        """A quoted combo has its bid and offer; an unquoted one has neither."""
        quoted, unquoted = await chain.load_combos("BTC")

        assert (quoted["bid"], quoted["ask"]) == (0.01, 0.02)
        assert (unquoted["bid"], unquoted["ask"]) == (None, None)

    @pytest.mark.asyncio
    async def test_the_settlement_currency_is_read(self, exchange):
        """The combos of a coin-settled root are read in the coin."""
        await chain.load_combos("BTC")

        assert exchange == [("combos", "BTC"), ("quotes", "option_combo")]

    @pytest.mark.asyncio
    async def test_a_second_read_reuses_the_first(self, exchange):
        """Reading the combos twice queries the exchange once."""
        first = await chain.load_combos("BTC")
        first.clear()
        second = await chain.load_combos("BTC")

        assert len(exchange) == 2
        assert len(second) == 2

    @pytest.mark.asyncio
    async def test_a_fresh_read_queries_again(self, exchange):
        """Asking for current combos goes back to the exchange."""
        await chain.load_combos("BTC")
        await chain.load_combos("BTC", use_cache=False)

        assert len(exchange) == 4


class TestSettlement:
    """A root names the currency it settles in and the index that prices it."""

    @pytest.mark.parametrize(
        "root,currency",
        [
            ("BTC", "BTC"),
            ("ETH", "ETH"),
            ("BTC_USDC", "USDC"),
            ("XRP_USDC", "USDC"),
            ("TRX_USDC", "USDC"),
        ],
    )
    def test_settlement_currency(self, root, currency):
        """Coin-margined roots settle in the coin, the rest in USDC."""
        assert chain.settlement_of(root) == currency


class TestCharts:
    """Every view draws, and every view still answers without a chart."""

    @staticmethod
    def _payoff(frame):
        """Build the sized position a payoff is drawn from."""
        from openbb_deribit.utils.options.optimizer import rank

        expiration = chain.expirations(frame)[0]

        return rank(frame, expiration, 100.0, 120.0, 1.0, True, 1)[0]

    @pytest.fixture
    def drawings(self, chain_frame):
        """Return every view, already reduced to the rows it draws."""
        from openbb_deribit.utils.options.create_payoff import create_payoff
        from openbb_deribit.utils.options.create_smile import create_smile
        from openbb_deribit.utils.options.create_stats import create_stats
        from openbb_deribit.utils.options.create_surface import create_surface
        from openbb_deribit.utils.options.create_term_structure import (
            create_term_structure,
        )
        from openbb_deribit.utils.options.data_handler import to_chain

        frame = chain_frame()
        options_chain = to_chain(frame, "BTC")

        return {
            "payoff": (
                create_payoff,
                {
                    **self._payoff(frame),
                    "spot": 100.0,
                    "target": 120.0,
                    "settles": "BTC",
                },
            ),
            "smile": (create_smile, options_chain),
            "term_structure": (create_term_structure, options_chain),
            "surface": (create_surface, options_chain),
            "stats": (create_stats, options_chain),
        }

    @pytest.mark.parametrize(
        "view", ["payoff", "smile", "term_structure", "surface", "stats"]
    )
    def test_draws_a_figure_and_its_rows(self, drawings, view):
        """A view returns both the picture and the numbers behind it."""
        build, data = drawings[view]
        output = build(data, theme="light")

        assert output.results
        assert output.chart is not None
        assert output.chart.format == "plotly"

    @pytest.mark.parametrize(
        "view", ["payoff", "smile", "term_structure", "surface", "stats"]
    )
    def test_answers_without_the_charting_extension(self, drawings, view, monkeypatch):
        """With nothing to draw with, a view still returns its rows."""
        import openbb_deribit

        monkeypatch.setattr(openbb_deribit, "CHARTING_INSTALLED", False)
        build, data = drawings[view]
        output = build(data, theme="dark")

        assert output.results
        assert output.chart is None

    def test_a_credit_is_titled_as_one(self, drawings):
        """A position opened for a credit says so rather than a negative cost."""
        from openbb_deribit.utils.options.create_payoff import create_payoff

        _build, data = drawings["payoff"]
        output = create_payoff({**data, "cost": -250.0}, theme="dark")

        assert "for a 250 USD credit" in output.chart.fig.layout.title.text

    def test_a_listed_combo_is_named_in_the_title(self, drawings):
        """A position traded as a listed combo names the combo."""
        from openbb_deribit.utils.options.create_payoff import create_payoff

        _build, data = drawings["payoff"]
        output = create_payoff({**data, "combo": "BTC-CS-X"}, theme="dark")

        assert "BTC-CS-X" in output.chart.fig.layout.title.text

    def test_a_target_at_spot_is_not_marked_twice(self, drawings):
        """A target the underlying is already at needs no second marker."""
        from openbb_deribit.utils.options.create_payoff import create_payoff

        _build, data = drawings["payoff"]
        output = create_payoff({**data, "target": 100.0}, theme="dark")
        marked = [note.text for note in output.chart.fig.layout.annotations]

        assert sum(text.startswith("Target") for text in marked) == 0

    def test_a_marker_outside_the_drawn_range_is_left_off(self, drawings):
        """Nothing is marked where the chart does not reach.

        Drawing one would stretch the axis back out to it, which is the whole
        reason the range was narrowed.
        """
        from openbb_deribit.utils.options.create_payoff import create_payoff

        _build, data = drawings["payoff"]
        output = create_payoff({**data, "spot": 1e9}, theme="dark")
        marked = [note.text for note in output.chart.fig.layout.annotations]

        assert not any(text.startswith("Spot") for text in marked)
        assert output.chart.fig.layout.xaxis.autorange is False


class TestUnplotted:
    """Without the charting extension the drawing calls go nowhere."""

    def test_every_call_is_accepted(self, monkeypatch):
        """A figure that cannot draw still answers every drawing call."""
        import openbb_deribit
        from openbb_deribit.utils.options.theme import Unplotted, new_figure

        monkeypatch.setattr(openbb_deribit, "CHARTING_INSTALLED", False)
        figure, text_color, background = new_figure("light")

        assert isinstance(figure, Unplotted)
        assert figure.add_scatter(x=[1], y=[2]).update_layout() is figure
        assert (text_color, background) == ("black", "rgba(255,255,255,0)")

    def test_a_dark_figure_is_drawn_on_nothing(self):
        """The dark theme writes in white on a transparent ground."""
        from openbb_deribit.utils.options.theme import new_figure

        _figure, text_color, background = new_figure("dark")

        assert (text_color, background) == ("white", "rgba(0,0,0,0)")


class TestCommands:
    """Each command reads the chain once and returns what it was asked for."""

    @pytest.mark.asyncio
    async def test_underlying_choices(self, responder, load):
        """The underlyings on offer are the ones with listed options."""
        responder({"get_instruments": load("instruments_option")})

        assert await router.underlying_choices() == [
            {"label": "BTC", "value": "BTC"},
            {"label": "XRP_USDC", "value": "XRP_USDC"},
        ]

    @pytest.mark.asyncio
    async def test_a_listed_combo_prices_the_drawn_position(self, loaded_chain):
        """Drawing a position Deribit lists as a combo prices it off that book."""
        frame = loaded_chain()
        quotes = chain.quotes_at(frame, chain.expirations(frame)[0])
        calls = sorted(
            quotes[quotes["option_type"] == "call"]["contract_symbol"],
            key=lambda name: float(name.split("-")[2]),
        )
        books = [
            {
                "name": "BTC-LISTED",
                "legs": [(calls[3], 1), (calls[5], -1)],
                "bid": 0.01,
                "ask": 0.02,
            }
        ]
        loaded_chain(books=books)
        drawn = await router.payoff_chart(
            symbol="BTC", legs=f"Buy {calls[3]} / Sell {calls[5]}"
        )

        assert "BTC-LISTED" in drawn["layout"]["title"]["text"]
        assert "Bull Call Spread" in drawn["layout"]["title"]["text"]

    @pytest.mark.asyncio
    async def test_optimizer(self, loaded_chain):
        """The ranking comes back with what it was measured against."""
        loaded_chain()
        output = await router.optimizer(symbol="BTC", target_price=120.0, limit=5)

        assert 0 < len(output.results) <= 5
        assert output.extra["results_metadata"] == {
            "symbol": "BTC",
            "underlying_price": 100.0,
            "target_price": 120.0,
            "expiration": str(chain.expirations(loaded_chain())[0]),
            "quote_currency": "USD",
            "settlement_currency": "BTC",
        }

    @pytest.mark.asyncio
    async def test_the_optimizer_holds_back_the_drawing(self, loaded_chain):
        """A ranked row carries its numbers, not the curve behind them."""
        loaded_chain()
        output = await router.optimizer(symbol="BTC", target_price=120.0)

        for row in output.results:
            assert not {"position", "prices", "payoff"} & set(row)
            assert row["strategy"] and row["legs"] and row["code"]

    @pytest.mark.asyncio
    async def test_no_target_ranks_against_spot(self, loaded_chain):
        """With no view expressed, the underlying is expected to sit still."""
        loaded_chain()
        output = await router.optimizer(symbol="BTC")

        assert output.extra["results_metadata"]["target_price"] == 100.0

    @pytest.mark.asyncio
    async def test_payoff(self, loaded_chain):
        """The drawn position is the one the ranking put first."""
        loaded_chain()
        ranked = await router.optimizer(symbol="BTC", target_price=120.0)
        drawn = await router.payoff_chart(symbol="BTC", target_price=120.0)

        assert set(drawn) >= {"data", "layout", "config"}
        assert ranked.results[0]["strategy"] in drawn["layout"]["title"]["text"]

    @pytest.mark.asyncio
    async def test_a_named_position_is_the_one_drawn(self, loaded_chain):
        """Picking a strategy out of the ranking draws exactly those contracts."""
        loaded_chain()
        ranked = await router.optimizer(symbol="BTC", target_price=120.0)
        second = ranked.results[1]
        drawn = await router.payoff_chart(
            symbol="BTC", target_price=120.0, legs=second["legs"]
        )

        assert second["strategy"] in drawn["layout"]["title"]["text"]

        assert second["legs"] in drawn["layout"]["title"]["text"]

    @pytest.mark.asyncio
    async def test_a_named_position_is_not_ranked_again(
        self, loaded_chain, monkeypatch
    ):
        """Drawing a chosen position does not re-run the ranking."""
        from openbb_deribit.utils.options import optimizer as engine

        loaded_chain()
        ranked = await router.optimizer(symbol="BTC", target_price=120.0)

        def _refuse(*args, **kwargs):
            raise AssertionError("the ranking was run to draw a chosen position")

        monkeypatch.setattr(engine, "rank", _refuse)

        assert await router.payoff_chart(
            symbol="BTC", target_price=120.0, legs=ranked.results[0]["legs"]
        )

    @pytest.mark.asyncio
    async def test_an_unlisted_position_says_so(self, loaded_chain):
        """A position naming a contract the expiration lacks is refused."""
        from fastapi import HTTPException

        loaded_chain()

        with pytest.raises(HTTPException) as raised:
            await router.payoff_chart(symbol="BTC", legs="Buy NOPE-1-1-C")

        assert raised.value.status_code == 404
        assert "not a listed contract" in raised.value.detail

    @pytest.mark.asyncio
    async def test_every_ranked_strategy_can_be_drawn_back(self, loaded_chain):
        """Every set of legs the optimizer prints prices back as it was."""
        loaded_chain()
        ranked = await router.optimizer(symbol="BTC", target_price=120.0)

        for row in ranked.results:
            drawn = await router.payoff_chart(
                symbol="BTC", target_price=120.0, legs=row["legs"]
            )

            assert row["strategy"] in drawn["layout"]["title"]["text"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("view", ["smile_chart", "straddle"])
    async def test_an_unlisted_underlying_is_a_404(self, monkeypatch, view):
        """A underlying the exchange does not list answers 404, not 500."""
        from fastapi import HTTPException
        from openbb_core.provider.utils.errors import EmptyDataError

        async def _empty(symbol, use_cache=True):
            raise EmptyDataError("nothing listed")

        monkeypatch.setattr("openbb_deribit.utils.options.chain.load_chain", _empty)

        with pytest.raises(HTTPException) as raised:
            await getattr(router, view)(symbol="NOPE")

        assert raised.value.status_code == 404
        assert "NOPE" in raised.value.detail

    @pytest.mark.asyncio
    async def test_straddle(self, loaded_chain):
        """A straddle is priced at every expiration."""
        loaded_chain()
        output = await router.straddle(symbol="BTC")

        assert len(output.results) == 2
        assert all(row["cost"] > 0 for row in output.results)

    @pytest.mark.asyncio
    async def test_strangle(self, loaded_chain):
        """The moneyness is read as a percentage either side of spot."""
        loaded_chain()
        output = await router.strangle(symbol="BTC", moneyness=4.0)

        assert output.results
        assert all(
            row["put_strike"] < 100.0 < row["call_strike"] for row in output.results
        )

    @pytest.mark.asyncio
    async def test_spreads(self, loaded_chain):
        """Both verticals are priced at every expiration."""
        loaded_chain()
        output = await router.spreads(symbol="BTC", moneyness=4.0)

        assert {row["strategy"] for row in output.results} == {
            "Bull Call Spread",
            "Bear Put Spread",
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("otm", [True, False])
    @pytest.mark.parametrize("skew", [True, False])
    async def test_smile(self, loaded_chain, otm, skew):
        """The smile draws calls and puts for the front expiration."""
        loaded_chain()
        drawn = await router.smile_chart(
            symbol="BTC", otm=otm, skew=skew, theme="light"
        )

        assert [trace["name"] for trace in drawn["data"]] == ["Calls", "Puts"]

    @pytest.mark.asyncio
    async def test_the_smile_draws_only_what_was_asked_for(self, loaded_chain):
        """A chain lists more expirations than are drawn unless named."""
        frame = loaded_chain()
        listed = chain.expirations(frame)
        drawn = await router.smile_chart(
            symbol="BTC", expirations=",".join(str(day) for day in listed)
        )

        assert len(drawn["data"]) == 2 * len(listed) > 2

    @pytest.mark.asyncio
    async def test_the_smile_offers_the_expirations_it_lists(self, loaded_chain):
        """The dropdown behind the smile names every expiration with its term."""
        frame = loaded_chain()
        offered = await router.expiration_choices(symbol="BTC")

        assert [item["value"] for item in offered] == [
            str(day) for day in chain.expirations(frame)
        ]
        assert all("d)" in item["label"] for item in offered)

    @pytest.mark.asyncio
    async def test_the_raw_toggle_returns_the_rows(self, loaded_chain):
        """With the raw toggle on, a chart route answers with its numbers."""
        loaded_chain()
        rows = await router.smile_chart(symbol="BTC", raw=True)

        assert isinstance(rows, list)
        assert rows and "IV" in rows[0]

    @pytest.mark.asyncio
    async def test_term_structure(self, loaded_chain):
        """The term structure draws calls and puts, one point per expiration."""
        loaded_chain()
        drawn = await router.term_structure_chart(symbol="BTC")

        assert [trace["name"] for trace in drawn["data"]] == ["Calls", "Puts"]
        assert all(len(trace["x"]) == 2 for trace in drawn["data"])

    @pytest.mark.asyncio
    async def test_term_structure_at_a_strike(self, loaded_chain):
        """A chosen strike and metric reach the chart."""
        loaded_chain()
        drawn = await router.term_structure_chart(
            symbol="BTC", strike=100.0, metric="price", option_type="calls"
        )

        assert [trace["name"] for trace in drawn["data"]] == ["Calls"]
        assert "$100.0" in drawn["layout"]["title"]["text"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("metric", ["implied_volatility", "vega", "gex"])
    async def test_surface(self, loaded_chain, metric):
        """Any published metric can be raised over the chain."""
        loaded_chain()
        drawn = await router.surface_chart(symbol="BTC", metric=metric, dte_max=60)

        assert drawn["data"][0]["type"] == "mesh3d"
        assert drawn["config"]["responsive"] is True

    @pytest.mark.asyncio
    async def test_surface_without_a_window(self, loaded_chain):
        """With no DTE bounds every expiration is raised."""
        loaded_chain()
        drawn = await router.surface_chart(
            symbol="BTC", option_type="calls", oi=True, volume=True
        )

        assert drawn["data"][0]["type"] == "mesh3d"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("by", ["strike", "expiration"])
    async def test_stats(self, loaded_chain, by):
        """Totals are grouped by whichever axis was asked for."""
        loaded_chain()
        drawn = await router.stats_chart(symbol="BTC", by=by, theme="light")

        assert [trace["name"] for trace in drawn["data"]] == ["Calls", "Puts"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "unit,name", [("percent", "% of Total"), ("pcr", "Put/Call Ratio")]
    )
    async def test_stats_units(self, loaded_chain, unit, name):
        """The unit chooses what the bars measure."""
        loaded_chain()
        drawn = await router.stats_chart(symbol="BTC", metric="volume", unit=unit)

        assert [trace["name"] for trace in drawn["data"]] == [name]

    @pytest.mark.asyncio
    async def test_stats_for_one_expiration(self, loaded_chain):
        """Naming an expiration draws its strikes."""
        frame = loaded_chain()
        drawn = await router.stats_chart(
            symbol="BTC", date=str(chain.expirations(frame)[1])
        )

        assert drawn["layout"]["title"]["text"] == "BTC Open Interest By Strike"

    @pytest.mark.asyncio
    async def test_strike_choices(self, loaded_chain):
        """The strike dropdown leads with the nearest out-of-the-money default."""
        frame = loaded_chain()
        offered = await router.strike_choices(symbol="BTC")

        assert offered[0] == {"label": "Nearest OTM", "value": None}
        assert [item["value"] for item in offered[1:]] == sorted(
            frame["strike"].unique()
        )

    @pytest.mark.asyncio
    async def test_strike_choices_for_an_unlisted_underlying(self, monkeypatch):
        """An underlying with no options offers no strikes."""
        from openbb_core.provider.utils.errors import EmptyDataError

        async def _empty(symbol, use_cache=True):
            raise EmptyDataError("nothing listed")

        monkeypatch.setattr("openbb_deribit.utils.options.chain.load_chain", _empty)

        assert await router.strike_choices(symbol="NOPE") == []

    @pytest.mark.asyncio
    async def test_a_linear_underlying_settles_in_its_quote(self, loaded_chain):
        """A USDC-quoted position is measured in USDC."""
        loaded_chain(inverse=False, spot=1.5, size=1000)
        output = await router.optimizer(symbol="XRP_USDC", target_price=2.0, budget=100)

        assert output.extra["results_metadata"]["settlement_currency"] == "USDC"
        assert output.results


class TestPayoffRefusals:
    """A position a budget cannot size is refused rather than drawn wrong."""

    @pytest.mark.asyncio
    async def test_a_credit_position_is_drawn(self, loaded_chain):
        """A position taken in for a credit is sized by what it risks."""
        frame = loaded_chain()
        quotes = chain.quotes_at(frame, chain.expirations(frame)[0])
        sold = quotes[quotes["option_type"] == "call"].iloc[0]["contract_symbol"]
        drawn = await router.payoff_chart(symbol="BTC", legs=f"Sell {sold}")

        assert "Short Call" in drawn["layout"]["title"]["text"]
        assert "credit" in drawn["layout"]["title"]["text"]

    @pytest.mark.asyncio
    async def test_a_position_with_nothing_at_risk_is_refused(
        self, loaded_chain, monkeypatch
    ):
        """A position that cannot lose has no capital to size against."""
        from fastapi import HTTPException

        from openbb_deribit.utils.options import optimizer as engine

        frame = loaded_chain()
        quotes = chain.quotes_at(frame, chain.expirations(frame)[0])
        bought = quotes[quotes["option_type"] == "call"].iloc[0]["contract_symbol"]
        monkeypatch.setattr(engine, "score", lambda *args, **kwargs: None)

        with pytest.raises(HTTPException) as raised:
            await router.payoff_chart(symbol="BTC", legs=f"Buy {bought}")

        assert raised.value.status_code == 404
        assert "nothing at risk" in raised.value.detail

    @pytest.mark.asyncio
    async def test_an_expiration_with_nothing_to_size_is_refused(
        self, loaded_chain, monkeypatch
    ):
        """An expiration forming no affordable strategy says so."""
        from fastapi import HTTPException

        from openbb_deribit.utils.options import optimizer as engine

        loaded_chain()
        monkeypatch.setattr(engine, "rank", lambda *args, **kwargs: [])

        with pytest.raises(HTTPException) as raised:
            await router.payoff_chart(symbol="BTC")

        assert raised.value.status_code == 404
        assert "can be sized" in raised.value.detail


class TestStrategyChoices:
    """The optimizer's ranking is also the payoff's dropdown.

    The value a reader picks is the contracts, so clicking the ranking and
    picking from the list put the same thing in the same parameter.
    """

    @pytest.mark.asyncio
    async def test_the_dropdown_is_the_ranking(self, loaded_chain):
        """Every entry offered is a strategy the optimizer ranked."""
        loaded_chain()
        view = {"symbol": "BTC", "target_price": 120.0}
        offered = await router.strategy_choices(**view)
        ranked = await router.optimizer(**view)

        assert offered
        assert [item["value"] for item in offered] == [
            row["legs"] for row in ranked.results
        ]

        for item, row in zip(offered, ranked.results, strict=True):
            assert item["label"].startswith(row["strategy"])
            assert row["legs"] in item["label"]

    @pytest.mark.asyncio
    async def test_what_is_offered_can_be_drawn(self, loaded_chain):
        """Each offered value draws the contracts it names."""
        loaded_chain()
        offered = await router.strategy_choices(symbol="BTC", target_price=120.0)

        for item in offered:
            drawn = await router.payoff_chart(
                symbol="BTC", target_price=120.0, legs=item["value"]
            )

            assert item["value"] in drawn["layout"]["title"]["text"]

    @pytest.mark.asyncio
    async def test_no_view_ranks_against_spot(self, loaded_chain):
        """With no target the ranking is against where the underlying is."""
        loaded_chain()

        assert await router.strategy_choices(symbol="BTC")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "written", ["garbage", "Buy", "Hold BTC-1-100-C", "Buy A B C"]
    )
    async def test_something_that_is_not_a_leg_says_so(self, loaded_chain, written):
        """Text that names no contract is refused with what the format is."""
        from fastapi import HTTPException

        loaded_chain()

        with pytest.raises(HTTPException) as raised:
            await router.payoff_chart(symbol="BTC", legs=written)

        assert raised.value.status_code == 404
        assert "Buy SYMBOL / Sell SYMBOL" in raised.value.detail
