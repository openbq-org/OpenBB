"""Tests for the Cboe router and its sub-routers."""

import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from openbb_cboe import cboe_router
from openbb_cboe.routers import equity, futures, index, options

MODEL_COMMANDS = [
    equity.search,
    equity.quote,
    equity.historical,
    index.available,
    index.search,
    index.snapshots,
    index.constituents,
    index.documents,
    index.historical,
    options.chains,
    futures.curve,
    futures.instruments,
    futures.settlement_prices,
]


class TestRouterAssembly:
    """Route registration."""

    @classmethod
    def _paths(cls, routes) -> set:
        """Flatten route paths across FastAPI's copied and deferred inclusion."""
        found: set = set()

        for route in routes:
            included = getattr(route, "original_router", None)

            if included is None:
                found.add(route.path)
            else:
                found |= cls._paths(included.routes)

        return found

    def test_every_route_is_registered(self):
        """The assembled router exposes one path per Cboe endpoint."""
        paths = self._paths(cboe_router.router.api_router.routes)

        assert paths == {
            "/equity/symbol_choices",
            "/equity/search",
            "/equity/quote",
            "/equity/historical",
            "/index/symbol_choices",
            "/index/constituent_choices",
            "/index/documents",
            "/index/document_choices",
            "/index/documents_viewer",
            "/index/available",
            "/index/search",
            "/index/snapshots",
            "/index/constituents",
            "/index/historical",
            "/options/get_tickers",
            "/options/straddle",
            "/options/strangle",
            "/options/spreads",
            "/options/chains",
            "/options/smile",
            "/options/surface",
            "/options/stats",
            "/options/term_structure",
            "/options/trade_optimizer",
            "/options/payoff",
            "/futures/instruments",
            "/futures/settlement_prices",
            "/futures/curve",
            "/apps.json",
        }


class TestModelCommands:
    """Model-backed commands delegate to the query pipeline."""

    @pytest.mark.parametrize("command", MODEL_COMMANDS)
    def test_delegates_to_from_query(self, command):
        """Each command hands off to ``OBBject.from_query``."""
        module = __import__(command.__module__, fromlist=["OBBject"])
        sentinel = object()

        with (
            patch.object(module, "OBBject") as mock_obbject,
            patch.object(module, "OBBQuery") as mock_query,
        ):
            mock_obbject.from_query = AsyncMock(return_value=sentinel)
            result = asyncio.run(
                command(
                    cc=None,
                    provider_choices=None,
                    standard_params=None,
                    extra_params=None,
                )
            )

        assert result is sentinel
        assert mock_query.called
        mock_obbject.from_query.assert_awaited_once()


class TestChoiceEndpoints:
    """Widget dropdown endpoints delegate to the helpers."""

    def test_equity_symbol_choices(self):
        """The equity picker reads the company directory."""
        choices = [{"label": "AAPL - APPLE INC", "value": "AAPL"}]

        with patch(
            "openbb_cboe.utils.helpers.get_equity_choices",
            new=AsyncMock(return_value=choices),
        ) as helper:
            assert asyncio.run(equity.symbol_choices(use_cache=False)) == choices

        helper.assert_awaited_once_with(use_cache=False)

    def test_index_symbol_choices(self):
        """The index picker reads the index directory."""
        choices = [{"label": "BUK100P - Cboe UK 100", "value": "BUK100P"}]

        with patch(
            "openbb_cboe.utils.helpers.get_index_choices",
            new=AsyncMock(return_value=choices),
        ) as helper:
            assert asyncio.run(index.symbol_choices()) == choices

        helper.assert_awaited_once_with(use_cache=True)

    def test_constituent_choices(self):
        """The constituents picker reads the supported European indices."""
        choices = [{"label": "BUK100P - Cboe UK 100", "value": "BUK100P"}]

        with patch(
            "openbb_cboe.utils.helpers.get_eu_index_choices",
            new=AsyncMock(return_value=choices),
        ) as helper:
            assert asyncio.run(index.constituent_choices()) == choices

        helper.assert_awaited_once_with(use_cache=True)


class TestFuturesEndpoints:
    """Futures utility endpoints."""

    def test_the_curve_charts_price_against_expiration(self):
        """The term structure reads across expirations, not dates."""
        charted = {
            column["field"]: column["chartDataType"] for column in futures.CURVE_COLUMNS
        }

        assert charted == {
            "expiration": "category",
            "price": "series",
            "symbol": "excluded",
            "date": "excluded",
        }

    def test_the_curve_declares_every_field_it_returns(self):
        """A field with no definition is appended by the grid in its own order."""
        from openbb_cboe.models.futures_curve import CboeFuturesCurveData

        declared = {column["field"] for column in futures.CURVE_COLUMNS}

        assert declared == set(CboeFuturesCurveData.model_fields)


class TestOptionsEndpoints:
    """Options analysis endpoints."""

    def test_get_tickers_without_symbol(self):
        """No symbol yields no choices."""
        assert asyncio.run(options.get_tickers()) == []

    def test_get_tickers_unknown_symbol(self):
        """A symbol that fails to load yields no choices."""
        with patch(
            "openbb_cboe.utils.options.data_handler.load_symbol",
            new=AsyncMock(
                side_effect=__import__(
                    "openbb_core.app.model.abstract.error", fromlist=["OpenBBError"]
                ).OpenBBError("no")
            ),
        ):
            assert asyncio.run(options.get_tickers(symbol="NOPE")) == []

    def test_get_tickers_expiries_and_strikes(self, options_chain):
        """Expiry and strike lists come from the cached chain."""
        with patch(
            "openbb_cboe.utils.options.data_handler.load_symbol",
            new=AsyncMock(return_value=options_chain),
        ):
            asyncio.run(options.get_tickers(symbol="CLX"))
            from openbb_cboe.utils.options import data_handler

            data_handler.LOADED_SYMBOLS["CLX"] = options_chain
            expiries = asyncio.run(options.get_tickers(symbol="CLX", expiry_list=True))
            strikes = asyncio.run(options.get_tickers(symbol="CLX", strike_list=True))
            neither = asyncio.run(options.get_tickers(symbol="CLX"))

        assert expiries[0]["value"] == data_handler.chain_expirations(options_chain)[0]
        assert strikes[0]["label"] == "Nearest OTM"
        assert neither == []

    def test_straddle(self, options_chain):
        """Straddle pricing returns one row per expiration."""
        with patch(
            "openbb_cboe.utils.options.data_handler.load_symbol",
            new=AsyncMock(return_value=options_chain),
        ):
            result = asyncio.run(options.straddle(symbol="CLX"))

        assert result.provider == "cboe"
        assert result.results

    def test_strangle(self, options_chain):
        """Strangle pricing returns one row per expiration."""
        with patch(
            "openbb_cboe.utils.options.data_handler.load_symbol",
            new=AsyncMock(return_value=options_chain),
        ):
            result = asyncio.run(options.strangle(symbol="CLX", moneyness=10))

        assert result.results

    def test_strangle_zero_moneyness_coerced(self, options_chain):
        """A zero moneyness is coerced to one percent before pricing."""
        captured: dict = {}

        def _strategies(**kwargs):
            captured.update(kwargs)
            return options_chain.strategies(days=-1, strangle_moneyness=10)

        stub = type("Stub", (), {"strategies": staticmethod(_strategies)})()

        with patch(
            "openbb_cboe.utils.options.data_handler.load_symbol",
            new=AsyncMock(return_value=stub),
        ):
            asyncio.run(options.strangle(symbol="CLX", moneyness=0))

        assert captured["strangle_moneyness"] == 1

    @pytest.mark.parametrize("spread_type", ["call", "put", "both"])
    def test_spreads(self, options_chain, spread_type):
        """Every spread type prices its legs."""
        with patch(
            "openbb_cboe.utils.options.data_handler.load_symbol",
            new=AsyncMock(return_value=options_chain),
        ):
            result = asyncio.run(options.spreads(symbol="CLX", spread_type=spread_type))

        assert result.results

    def test_chart_route_returns_figure_json(self, options_chain):
        """A chart route returns Plotly figure JSON with the widget config."""
        with patch(
            "openbb_cboe.utils.options.data_handler.load_symbol",
            new=AsyncMock(return_value=options_chain),
        ):
            figure = asyncio.run(options.stats_chart(symbol="CLX"))

        assert figure["data"]
        assert figure["config"]["scrollZoom"] is True

    def test_chart_route_raw_returns_rows(self, options_chain):
        """The raw toggle returns the underlying rows instead of a figure."""
        with patch(
            "openbb_cboe.utils.options.data_handler.load_symbol",
            new=AsyncMock(return_value=options_chain),
        ):
            rows = asyncio.run(options.smile_chart(symbol="CLX", raw=True))

        assert isinstance(rows, list)
        assert rows

    def test_chart_route_unknown_symbol_404s(self):
        """A symbol with no chain surfaces as a 404."""
        from fastapi import HTTPException
        from openbb_core.app.model.abstract.error import OpenBBError

        with (
            patch(
                "openbb_cboe.utils.options.data_handler.load_symbol",
                new=AsyncMock(side_effect=OpenBBError("no")),
            ),
            pytest.raises(HTTPException) as exc,
        ):
            asyncio.run(options.surface_chart(symbol="NOPE"))

        assert exc.value.status_code == 404

    def test_surface_chart_builds_dte_range(self, options_chain):
        """Supplying either DTE bound builds a range for the builder."""
        with patch(
            "openbb_cboe.utils.options.data_handler.load_symbol",
            new=AsyncMock(return_value=options_chain),
        ):
            figure = asyncio.run(options.surface_chart(symbol="CLX", dte_max=400))

        assert figure["data"]

    def test_term_structure_chart(self, options_chain):
        """The term-structure route renders a figure."""
        with patch(
            "openbb_cboe.utils.options.data_handler.load_symbol",
            new=AsyncMock(return_value=options_chain),
        ):
            figure = asyncio.run(options.term_structure_chart(symbol="CLX"))

        assert figure["data"]


class TestTradeOptimizer:
    """The optimizer ranking command and the payoff diagram routes."""

    NEAR = (date.today() + timedelta(days=30)).isoformat()
    FAR = (date.today() + timedelta(days=60)).isoformat()

    @staticmethod
    def _info(expirations):
        return {
            "success": True,
            "details": {"current_price": 100.0, "iv30": 25.0},
            "expirations": expirations,
        }

    @classmethod
    def _ranked(cls):
        return [
            {
                "strategy": "Long Spread",
                "type": "c",
                "strike1": 100.0,
                "strike2": 110.0,
                "current_price": 4.0,
                "expiry": cls.NEAR,
                "return": 1.5,
            },
            {
                "strategy": "Long Spread",
                "type": "c",
                "strike1": 105.0,
                "strike2": 115.0,
                "current_price": 3.0,
                "expiry": cls.NEAR,
                "return": 2.5,
            },
            {
                "strategy": "Short Spread",
                "type": "p",
                "strike1": 95.0,
                "strike2": 90.0,
                "current_price": 1.5,
                "expiry": cls.NEAR,
                "return": 0.5,
            },
        ]

    @classmethod
    def _naked(cls):
        return [
            {
                "strategy": strategy,
                "type": option_type,
                "strike1": 100.0,
                "current_price": 5.0,
                "expiry": cls.NEAR,
            }
            for strategy in ("Naked Long", "Naked Short")
            for option_type in ("c", "p")
        ]

    @classmethod
    def _marks(cls, symbol, expiration):
        contracts = {
            ("c", 100.0): {
                "iv": 0.22,
                "theoretical_price": 5.0,
                "bid": 4.9,
                "ask": 5.1,
            },
            ("p", 100.0): {
                "iv": 0.21,
                "theoretical_price": 4.8,
                "bid": 4.7,
                "ask": 4.9,
            },
        }

        if expiration == cls.NEAR:
            return {
                "contracts": contracts,
                "forward": 100.5,
                "discount": 0.999,
                "dte": 30,
            }

        return {"contracts": contracts, "forward": 101.0, "discount": 0.998, "dte": 60}

    def _patched(self, expirations=None, strategies=None):
        marks = self._marks

        async def chain_marks(symbol, expiration):
            return marks(symbol, expiration)

        return (
            patch(
                "openbb_cboe.utils.options.trade_optimizer.get_symbol_info",
                new=AsyncMock(
                    return_value=self._info(expirations or [self.NEAR, self.FAR])
                ),
            ),
            patch(
                "openbb_cboe.utils.options.trade_optimizer.get_strategies",
                new=strategies or AsyncMock(return_value=self._ranked()),
            ),
            patch(
                "openbb_cboe.utils.options.data_handler.get_chain_marks",
                new=chain_marks,
            ),
        )

    def test_ranks_labels_and_projects_the_grid_fields(self):
        """Rows are labelled, sorted by return, and projected onto the grid."""
        info, strategies, marks = self._patched()

        with info, strategies, marks:
            rows = asyncio.run(options.trade_optimizer(symbol="SPY"))

        assert [row["strategy_label"] for row in rows] == [
            "Buy Call Spread",
            "Buy Call Spread",
            "Sell Put Spread",
        ]
        assert rows[0]["return"] == 2.5
        assert set(rows[0]) == {c["field"] for c in options.OPTIMIZER_COLUMNS}

    def test_expiration_fallbacks(self):
        """No expirations yield an empty expiry and a zero DTE."""
        assert options._default_expiration([]) == ""
        assert options._dte("") == 0

    def test_expiry_math_is_anchored_to_new_york(self):
        """DTE and the default expiration count from the New York session date."""
        with patch("openbb_cboe.utils.helpers.ny_today", return_value=date(2026, 7, 1)):
            assert options._dte("2026-07-31") == 30
            assert options._dte("2026-06-30") == 0
            assert (
                options._default_expiration(["2026-07-03", "2026-07-31", "2026-09-18"])
                == "2026-07-31"
            )

    def test_describe_honors_a_listed_expiration(self):
        """A requested expiration is used only when the optimizer offers it."""
        info = self._info([self.NEAR, self.FAR])

        assert options._describe(info, self.FAR)["expiry"] == self.FAR
        assert options._describe(info, "1999-01-01")["expiry"] == self.NEAR

    def test_far_expiration_picks_a_month_out(self):
        """The calendar's far leg lands a month past the near one."""
        assert options._far_expiration([self.NEAR], self.NEAR) == self.NEAR
        assert options._far_expiration([self.NEAR, self.FAR], self.NEAR) == self.FAR

    def test_payoff_ranked_spread(self):
        """A ranked spread draws its payoff, clamping the rank to the matches."""
        info, strategies, marks = self._patched()

        with info, strategies, marks:
            figure = asyncio.run(
                options.payoff_chart(symbol="SPY", strategy="buy_call_spread", rank=99)
            )

        assert figure["data"]
        assert figure["config"]["scrollZoom"] is True

    def test_payoff_raw_returns_rows(self):
        """The raw toggle returns the evaluated curve instead of a figure."""
        info, strategies, marks = self._patched()

        with info, strategies, marks:
            rows = asyncio.run(
                options.payoff_chart(symbol="SPY", strategy="buy_call_spread", raw=True)
            )

        assert isinstance(rows, list)
        assert rows

    def test_payoff_unranked_spread_404s(self):
        """A spread the optimizer did not rank surfaces as a 404."""
        from fastapi import HTTPException

        info, strategies, marks = self._patched()

        with info, strategies, marks, pytest.raises(HTTPException) as exc:
            asyncio.run(options.payoff_chart(symbol="SPY", strategy="sell_call_spread"))

        assert exc.value.status_code == 404

    def test_payoff_naked_falls_back_to_the_quote_book(self):
        """A naked strategy the ranking left out is quoted directly."""
        responses = {"count": 0}
        ranked, naked = self._ranked(), self._naked()

        async def strategies(symbol, expiry, price, **kwargs):
            responses["count"] += 1
            return ranked if responses["count"] == 1 else naked

        info, strategies_patch, marks = self._patched(strategies=strategies)

        with info, strategies_patch, marks:
            figure = asyncio.run(
                options.payoff_chart(symbol="SPY", strategy="buy_call")
            )

        assert figure["data"]
        assert responses["count"] == 4

    def test_payoff_straddle_is_assembled(self):
        """A straddle is assembled from the quoted legs."""
        info, strategies, marks = self._patched(
            strategies=AsyncMock(return_value=self._naked())
        )

        with info, strategies, marks:
            figure = asyncio.run(
                options.payoff_chart(symbol="SPY", strategy="buy_straddle")
            )

        assert figure["data"]

    def test_payoff_strangle_is_assembled(self):
        """A short strangle quotes five targets for its wings."""
        strategies = AsyncMock(return_value=self._naked())
        info, strategies_patch, marks = self._patched(strategies=strategies)

        with info, strategies_patch, marks:
            figure = asyncio.run(
                options.payoff_chart(
                    symbol="SPY", strategy="sell_strangle", moneyness=5
                )
            )

        assert figure["data"]
        assert strategies.await_count == 5

    def test_payoff_calendar_is_assembled(self):
        """A calendar spread quotes both expirations."""
        info, strategies, marks = self._patched(
            strategies=AsyncMock(return_value=self._naked())
        )

        with info, strategies, marks:
            figure = asyncio.run(
                options.payoff_chart(symbol="SPY", strategy="call_calendar")
            )

        assert figure["data"]

    def test_payoff_calendar_without_a_second_expiration_404s(self):
        """A calendar with nothing to sell against surfaces as a 404."""
        from fastapi import HTTPException

        info, strategies, marks = self._patched(
            expirations=[self.NEAR],
            strategies=AsyncMock(return_value=self._naked()),
        )

        with info, strategies, marks, pytest.raises(HTTPException) as exc:
            asyncio.run(options.payoff_chart(symbol="SPY", strategy="put_calendar"))

        assert exc.value.status_code == 404


class TestAppsJson:
    """Dashboard template resolution."""

    def test_serves_template(self):
        """Every widget in the template exists in the current install."""
        apps = asyncio.run(cboe_router.cboe_apps())

        assert apps
        assert set(apps[0]["tabs"]) == {"indices", "options", "optimizer", "futures"}

    def test_constituents_open_on_an_index_with_a_file(self):
        """The template's index is one Cboe publishes constituents for."""
        import json

        apps = json.dumps(asyncio.run(cboe_router.cboe_apps()))

        assert "BUKENGY" not in apps
        assert '"BUK100P"' in apps

    def test_standalone_ids_when_extensions_absent(self):
        """Standard-namespace IDs are swapped for the ``/cboe`` ones."""
        apps = asyncio.run(cboe_router.cboe_apps())
        ids = {w["i"] for tab in apps[0]["tabs"].values() for w in tab["layout"]}

        assert "cboe_index_snapshots_cboe_obb" in ids
        assert "index_snapshots_cboe_obb" not in ids

    def test_resolve_widget_id_keeps_standard_when_installed(self):
        """An installed namespace keeps its standard widget ID."""
        with patch.dict(
            cboe_router._STANDALONE_WIDGET_IDS,
            {"index_snapshots_cboe_obb": ("cboe_index_snapshots_cboe_obb", True)},
        ):
            assert (
                cboe_router._resolve_widget_id("index_snapshots_cboe_obb")
                == "index_snapshots_cboe_obb"
            )

    def test_unknown_widget_id_passes_through(self):
        """An ID outside the map is returned unchanged."""
        assert cboe_router._resolve_widget_id("something_else") == "something_else"

    def test_chart_widgets_are_served_without_charting(self, monkeypatch):
        """A chart route without the extension returns the rows it would draw."""
        import openbb_cboe

        monkeypatch.setattr(openbb_cboe, "CHARTING_INSTALLED", False)
        apps = asyncio.run(cboe_router.cboe_apps())
        ids = {w["i"] for w in apps[0]["tabs"]["options"]["layout"]}

        assert "cboe_options_smile_custom_obb" in ids
        assert "cboe_options_surface_custom_obb" in ids
        assert "cboe_options_straddle_custom_obb" in ids


class TestIndexDocumentsViewer:
    """Cover the index document choices endpoint and the file viewer."""

    def test_document_choices_delegates(self):
        """The picker delegates to the document choices helper."""
        choices = AsyncMock(return_value=[{"label": "a", "value": "https://x/a.pdf"}])

        with patch("openbb_cboe.utils.helpers.get_document_choices", choices):
            result = asyncio.run(index.document_choices("BXM"))

        assert result == [{"label": "a", "value": "https://x/a.pdf"}]
        choices.assert_awaited_once_with("BXM")

    def test_viewer_opens_only_cboe_documents(self):
        """Anything not hosted on a Cboe document host is refused."""
        opener = AsyncMock(return_value={"content": "QUJD"})

        with patch("openbb_cboe.utils.helpers.open_index_document", opener):
            documents = asyncio.run(
                index.documents_viewer(
                    {
                        "document_url": [
                            "https://cdn.cboe.com/a.pdf",
                            "https://evil.example/a.pdf",
                            "not-a-url",
                            42,
                        ]
                    }
                )
            )

        assert len(documents) == 1
        opener.assert_awaited_once_with("https://cdn.cboe.com/a.pdf")

    def test_viewer_without_a_selection(self):
        """No selection yields no documents."""
        assert asyncio.run(index.documents_viewer({})) == []

    def test_viewer_skips_empty_documents(self):
        """A document that opens empty is not returned."""
        with patch(
            "openbb_cboe.utils.helpers.open_index_document", AsyncMock(return_value={})
        ):
            documents = asyncio.run(
                index.documents_viewer({"document_url": ["https://cdn.cboe.com/a.pdf"]})
            )

        assert documents == []
