"""Tests for ``OptionsChainsProperties`` DataFrame analytics + pandas guard.

These tests are split into two groups:

1. The pandas-guard test (no ``requires_pandas`` marker) verifies that the
   analytics surface raises a clear, actionable ``OpenBBError`` when the
   ``[pandas]`` extra is not installed — we mock ``__import__`` to hide
   pandas/numpy from the consumer.
2. The DataFrame method tests are gated on the ``requires_pandas`` marker
   (registered in ``pytest.ini``) and exercise the most common analytics
   entry points: ``dataframe``, ``filter_data``, ``_get_stat`` aggregates,
   ``straddle``, ``strangle``, ``synthetic_long``/``_short``,
   ``vertical_call_spread``/``vertical_put_spread`` and ``skew``.

A synthetic, deterministic options chain is built in ``_build_chain`` so the
tests have no provider dependency and run in milliseconds.
"""

import builtins
from datetime import date, timedelta

import pytest

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.standard_models.options_chains import OptionsChainsData

requires_pandas = pytest.mark.requires_pandas


def test_dataframe_raises_clear_error_without_pandas(monkeypatch):
    """``dataframe`` must surface an actionable install hint when pandas is gone."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pandas" or name.startswith("pandas."):
            raise ImportError("No module named 'pandas'")
        if name == "numpy" or name.startswith("numpy."):
            raise ImportError("No module named 'numpy'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    data = OptionsChainsData(
        contract_symbol=["FAKE"],
        expiration=[date(2030, 1, 17)],
        strike=[100.0],
        option_type=["call"],
        underlying_symbol=["FAKE"],
        underlying_price=[100.0],
        bid=[1.0],
        ask=[1.1],
    )
    with pytest.raises(OpenBBError, match=r"openbb-core\[pandas\]"):
        _ = data.dataframe


def _build_chain(
    expirations: int = 2,
    strikes: tuple[float, ...] = (90.0, 95.0, 100.0, 105.0, 110.0),
    underlying_price: float = 100.0,
) -> OptionsChainsData:
    """Build a deterministic, balanced call/put chain across N expirations."""
    rows: list[dict] = []
    base = date.today() + timedelta(days=14)
    for e in range(expirations):
        exp = base + timedelta(days=30 * e)
        for k in strikes:
            for opt in ("call", "put"):
                # Simple, monotone bid/ask so spreads/aggregations are predictable.
                intrinsic = (
                    max(0.0, underlying_price - k)
                    if opt == "call"
                    else max(0.0, k - underlying_price)
                )
                bid = round(intrinsic + 1.0, 2)
                ask = round(bid + 0.10, 2)
                rows.append(
                    {
                        "underlying_symbol": "FAKE",
                        "underlying_price": underlying_price,
                        "contract_symbol": (
                            f"FAKE{exp:%y%m%d}{opt[0].upper()}{int(k * 1000):08d}"
                        ),
                        "eod_date": date.today(),
                        "expiration": exp,
                        "strike": k,
                        "option_type": opt,
                        "open_interest": 100 + int(k),
                        "volume": 50 + int(k),
                        "bid": bid,
                        "ask": ask,
                        "delta": 0.5 if opt == "call" else -0.5,
                        "gamma": 0.05,
                        "implied_volatility": 0.25 + (k - underlying_price) / 1000,
                    }
                )

    columns = {key: [r[key] for r in rows] for key in rows[0]}
    return OptionsChainsData(**columns)


@pytest.fixture
def chain_smoke():
    return _build_chain()


@requires_pandas
class TestDataFrame:
    """Cover ``OptionsChainsProperties.dataframe`` cached property."""

    def test_dataframe_returns_pandas_dataframe(self, chain_smoke):
        from pandas import DataFrame

        df = chain_smoke.dataframe
        assert isinstance(df, DataFrame)

    def test_dataframe_row_count_matches_input(self, chain_smoke):
        df = chain_smoke.dataframe
        expected = (
            df["expiration"].nunique()
            * df["strike"].nunique()
            * df["option_type"].nunique()
        )
        assert len(df) == expected

    def test_dataframe_has_expected_columns(self, chain_smoke):
        df = chain_smoke.dataframe
        for col in ("strike", "option_type", "expiration", "bid", "ask"):
            assert col in df.columns

    def test_dataframe_is_cached(self, chain_smoke):
        # ``cached_property`` returns the same object on repeat access.
        assert chain_smoke.dataframe is chain_smoke.dataframe


@requires_pandas
class TestFilterData:
    """Cover ``OptionsChainsProperties.filter_data``."""

    def test_filter_by_expiration_index(self, chain_smoke):
        from pandas import DataFrame

        # ``date`` accepts either a date string, an integer DTE, or an index.
        filtered = chain_smoke.filter_data(date=0)
        assert isinstance(filtered, DataFrame)
        expected = (
            chain_smoke.dataframe["strike"].nunique()
            * chain_smoke.dataframe["option_type"].nunique()
        )
        assert len(filtered) == expected

    def test_filter_by_option_type_calls(self, chain_smoke):
        filtered = chain_smoke.filter_data(option_type="call")
        assert (filtered["option_type"] == "call").all()

    def test_filter_by_option_type_puts(self, chain_smoke):
        filtered = chain_smoke.filter_data(option_type="put")
        assert (filtered["option_type"] == "put").all()


@requires_pandas
class TestStatAggregates:
    """Cover the ``_get_stat`` family — open interest / volume aggregations."""

    def test_total_oi_returns_dict_or_dataframe(self, chain_smoke):
        result = chain_smoke.total_oi
        # The implementation returns a dict keyed by ('Calls', 'Puts', 'Total').
        assert result is not None

    def test_total_volume_returns_dict_or_dataframe(self, chain_smoke):
        result = chain_smoke.total_volume
        assert result is not None


@requires_pandas
class TestStrategies:
    """Cover the headline single-leg & spread strategy builders."""

    def test_straddle_returns_dataframe(self, chain_smoke):
        from pandas import DataFrame

        result = chain_smoke.straddle()
        assert isinstance(result, DataFrame)
        assert not result.empty

    def test_strangle_returns_dataframe(self, chain_smoke):
        from pandas import DataFrame

        result = chain_smoke.strangle()
        assert isinstance(result, DataFrame)
        assert not result.empty

    def test_synthetic_long_returns_dataframe(self, chain_smoke):
        from pandas import DataFrame

        result = chain_smoke.synthetic_long()
        assert isinstance(result, DataFrame)
        assert not result.empty

    def test_synthetic_short_returns_dataframe(self, chain_smoke):
        from pandas import DataFrame

        result = chain_smoke.synthetic_short()
        assert isinstance(result, DataFrame)
        assert not result.empty

    def test_vertical_call_spread_returns_dataframe(self, chain_smoke):
        from pandas import DataFrame

        # Buy 95 call, sell 105 call on the nearest expiration.
        result = chain_smoke.vertical_call_spread(sold=105.0, bought=95.0)
        assert isinstance(result, DataFrame)
        assert not result.empty

    def test_vertical_put_spread_returns_dataframe(self, chain_smoke):
        from pandas import DataFrame

        # Buy 105 put, sell 95 put.
        result = chain_smoke.vertical_put_spread(sold=95.0, bought=105.0)
        assert isinstance(result, DataFrame)
        assert not result.empty


@requires_pandas
class TestSkew:
    """Cover ``OptionsChainsProperties.skew``."""

    def test_skew_returns_dataframe(self, chain_smoke):
        from pandas import DataFrame

        result = chain_smoke.skew()
        assert isinstance(result, DataFrame)
        assert not result.empty


"""Extended tests for ``OptionsChainsProperties`` - target high-line-count gaps."""


import pytest

from openbb_core.provider.standard_models.options_chains import OptionsChainsData

requires_pandas = pytest.mark.requires_pandas


def _build_chain(
    expirations: int = 3,
    strikes=(80.0, 90.0, 95.0, 100.0, 105.0, 110.0, 120.0),
    underlying_price: float = 100.0,
    with_greeks: bool = True,
    with_eod: bool = True,
) -> OptionsChainsData:
    rows = []
    base = date.today() + timedelta(days=14)
    for e in range(expirations):
        exp = base + timedelta(days=30 * e)
        for k in strikes:
            for opt in ("call", "put"):
                intrinsic = (
                    max(0.0, underlying_price - k)
                    if opt == "call"
                    else max(0.0, k - underlying_price)
                )
                bid = round(intrinsic + 1.0, 2)
                ask = round(bid + 0.10, 2)
                row = {
                    "underlying_symbol": "FAKE",
                    "underlying_price": underlying_price,
                    "contract_symbol": (
                        f"FAKE{exp:%y%m%d}{opt[0].upper()}{int(k * 1000):08d}"
                    ),
                    "expiration": exp,
                    "strike": k,
                    "option_type": opt,
                    "open_interest": 100 + int(k),
                    "volume": 50 + int(k),
                    "bid": bid,
                    "ask": ask,
                    "implied_volatility": 0.25 + (k - underlying_price) / 1000,
                }
                if with_eod:
                    row["eod_date"] = date.today()
                if with_greeks:
                    row["delta"] = 0.5 if opt == "call" else -0.5
                    row["gamma"] = 0.05
                    row["theta"] = -0.02
                    row["vega"] = 0.1
                    row["rho"] = 0.01
                rows.append(row)

    columns = {key: [r.get(key) for r in rows] for key in rows[0]}
    return OptionsChainsData(**columns)


@pytest.fixture
def chain():
    return _build_chain()


@pytest.fixture
def chain_no_greeks():
    return _build_chain(with_greeks=False)


@requires_pandas
class TestLastPrice:
    def test_last_price_setter_and_deleter(self, chain):
        assert chain.last_price is None
        chain.last_price = 99.5
        assert chain.last_price == 99.5
        del chain.last_price
        assert chain.last_price is None

    def test_dataframe_uses_last_price_override(self):
        c = _build_chain()
        c.last_price = 200.0
        df = c.dataframe
        assert (df["underlying_price"] == 200.0).all()

    def test_dataframe_missing_underlying_price_raises(self):
        data = OptionsChainsData(
            contract_symbol=["FAKE"],
            expiration=[date.today() + timedelta(days=30)],
            strike=[100.0],
            option_type=["call"],
            underlying_symbol=["FAKE"],
            bid=[1.0],
            ask=[1.1],
        )

        with pytest.raises(OpenBBError, match="underlying_price"):
            _ = data.dataframe

    def test_dataframe_empty_raises(self):
        data = _build_chain()
        data.model_dump = lambda **kwargs: {"underlying_price": []}

        with pytest.raises(OpenBBError, match="No validated data"):
            _ = data.dataframe

    def test_dataframe_without_eod_date_builds_dte(self):
        df = _build_chain(with_eod=False).dataframe

        assert "dte" in df.columns

    def test_dataframe_falls_back_to_raw_frame_on_processing_error(
        self, monkeypatch, chain
    ):
        monkeypatch.setattr(
            type(chain),
            "_identify_price_col",
            lambda *args, **kwargs: (_ for _ in ()).throw(KeyError("missing")),
        )

        df = chain.dataframe

        assert "Breakeven" not in df.columns


@requires_pandas
class TestExpirationsStrikesFlags:
    def test_expirations_sorted(self, chain):
        exps = chain.expirations
        assert exps == sorted(exps)

    def test_strikes_sorted(self, chain):
        s = chain.strikes
        assert s == sorted(s)

    def test_has_iv_true(self, chain):
        assert chain.has_iv is True

    def test_has_greeks_true_false(self, chain, chain_no_greeks):
        assert chain.has_greeks is True
        assert chain_no_greeks.has_greeks is False


@requires_pandas
class TestTotalDexGex:
    def test_total_dex_returns(self, chain):
        result = chain.total_dex
        assert result is not None

    def test_total_gex_returns(self, chain):
        result = chain.total_gex
        assert result is not None

    def test_total_dex_no_greeks_raises(self, chain_no_greeks):
        with pytest.raises(OpenBBError, match="Greeks are not available"):
            _ = chain_no_greeks.total_dex

    def test_total_gex_no_greeks_raises(self, chain_no_greeks):
        with pytest.raises(OpenBBError, match="Greeks are not available"):
            _ = chain_no_greeks.total_gex


@requires_pandas
class TestFilterDataExtended:
    def test_filter_by_stat_open_interest(self, chain):
        from pandas import DataFrame

        result = chain.filter_data(stat="open_interest")
        assert isinstance(result, DataFrame)

    def test_filter_by_stat_volume(self, chain):
        from pandas import DataFrame

        result = chain.filter_data(stat="volume")
        assert isinstance(result, DataFrame)

    def test_filter_by_stat_dex(self, chain):
        from pandas import DataFrame

        result = chain.filter_data(stat="dex")
        assert isinstance(result, DataFrame)

    def test_filter_by_stat_gex(self, chain):
        from pandas import DataFrame

        result = chain.filter_data(stat="gex")
        assert isinstance(result, DataFrame)

    def test_filter_invalid_stat_raises(self, chain):
        with pytest.raises(OpenBBError, match="stat must be one of"):
            chain.filter_data(stat="bogus")

    def test_filter_by_moneyness(self, chain):
        from pandas import DataFrame

        result = chain.filter_data(moneyness="otm")
        assert isinstance(result, DataFrame)

    def test_filter_by_date(self, chain):
        from pandas import DataFrame

        result = chain.filter_data(date=0)
        assert isinstance(result, DataFrame)

    def test_filter_by_column_min_max(self, chain):
        from pandas import DataFrame

        result = chain.filter_data(column="open_interest", value_min=100, value_max=200)
        assert isinstance(result, DataFrame)
        assert result["open_interest"].abs().between(100, 200).all()

    def test_filter_by_column_min_only(self, chain):
        result = chain.filter_data(column="open_interest", value_min=150)
        assert (result["open_interest"].abs() >= 150).all()

    def test_filter_by_column_max_only(self, chain):
        result = chain.filter_data(column="open_interest", value_max=150)
        assert (result["open_interest"].abs() <= 150).all()

    def test_filter_by_column_no_bounds_sorts(self, chain):
        from pandas import DataFrame

        result = chain.filter_data(column="open_interest")
        assert isinstance(result, DataFrame)

    def test_filter_unknown_column_raises(self, chain):
        with pytest.raises(OpenBBError, match="not found in data"):
            chain.filter_data(column="not_a_column")

    def test_filter_stat_missing_underlying_price_raises(self, chain):
        df = chain.dataframe.drop(columns=["underlying_price", "DEX", "GEX"])
        chain.__dict__["dataframe"] = df

        with pytest.raises(OpenBBError, match="underlying price was not returned"):
            chain.filter_data(stat="gex")


@requires_pandas
class TestStrategiesMethod:
    def test_strategies_default(self, chain):
        from pandas import DataFrame

        result = chain.strategies()
        assert isinstance(result, DataFrame)

    def test_strategies_strangle(self, chain):
        from pandas import DataFrame

        result = chain.strategies(strangle_moneyness=[5.0, 10.0])
        assert isinstance(result, DataFrame)

    def test_strategies_synthetic_long(self, chain):
        from pandas import DataFrame

        result = chain.strategies(synthetic_longs=[100.0])
        assert isinstance(result, DataFrame)

    def test_strategies_synthetic_short(self, chain):
        from pandas import DataFrame

        result = chain.strategies(synthetic_shorts=[100.0])
        assert isinstance(result, DataFrame)

    def test_strategies_vertical_calls(self, chain):
        from pandas import DataFrame

        result = chain.strategies(vertical_calls=[(105.0, 95.0)])
        assert isinstance(result, DataFrame)

    def test_strategies_vertical_puts(self, chain):
        from pandas import DataFrame

        result = chain.strategies(vertical_puts=[(95.0, 105.0)])
        assert isinstance(result, DataFrame)

    def test_strategies_multiple_vertical_puts(self, chain):
        result = chain.strategies(
            days=[14, 44], vertical_puts=[(95.0, 105.0), (90.0, 110.0)]
        )
        put_spreads = result[result["Strategy"].str.contains("Put Spread")]

        assert len(put_spreads) == 4
        assert put_spreads["Expiration"].nunique() == 2
        assert set(zip(put_spreads["Strike 1"], put_spreads["Strike 2"])) == {
            (95.0, 105.0),
            (90.0, 110.0),
        }

    def test_strategies_all_at_once(self, chain):
        from pandas import DataFrame

        result = chain.strategies(
            days=[20, 40],
            straddle_strike=100.0,
            strangle_moneyness=[5.0],
            synthetic_longs=[100.0],
            synthetic_shorts=[100.0],
            vertical_calls=[(105.0, 95.0)],
            vertical_puts=[(95.0, 105.0)],
        )
        assert isinstance(result, DataFrame)

    def test_strategies_days_minus_one(self, chain):
        result = chain.strategies(days=-1, straddle_strike=100.0)
        assert result is not None


@requires_pandas
class TestSkewExtended:
    def test_skew_vertical_default(self, chain):
        from pandas import DataFrame

        result = chain.skew()
        assert isinstance(result, DataFrame)

    def test_skew_horizontal(self, chain):
        from pandas import DataFrame

        result = chain.skew(moneyness=10.0)
        assert isinstance(result, DataFrame)

    def test_skew_specific_date(self, chain):
        from pandas import DataFrame

        result = chain.skew(date=30)
        assert isinstance(result, DataFrame)


@requires_pandas
class TestGetStatBranches:
    def test_get_stat_with_moneyness_otm(self, chain):
        result = chain._get_stat("open_interest", moneyness="otm")
        assert "Calls" in result["total"] or "expiration" in result

    def test_get_stat_with_moneyness_itm(self, chain):
        result = chain._get_stat("open_interest", moneyness="itm")
        assert result is not None

    def test_get_stat_with_date(self, chain):
        exp = chain.expirations[0]
        result = chain._get_stat("open_interest", date=exp)
        assert result is not None

    def test_get_stat_dex_no_greeks_raises(self, chain_no_greeks):
        with pytest.raises(OpenBBError, match="Greeks were not found"):
            chain_no_greeks._get_stat("DEX")


@requires_pandas
class TestNearestHelpers:
    def test_get_nearest_expiration_without_dte(self, chain):
        df = chain.dataframe.drop(columns=["dte"])

        with pytest.raises(TypeError):
            chain._get_nearest_expiration(10, df=df)

    def test_get_nearest_expiration_with_none_date(self, chain):
        assert chain._get_nearest_expiration(None) in chain.expirations

    def test_get_nearest_otm_strikes_default_moneyness(self, chain):
        strikes = chain._get_nearest_otm_strikes(moneyness=None)

        assert set(strikes) == {"call", "put"}

    def test_get_nearest_otm_strikes_invalid_moneyness(self, chain):
        with pytest.raises(OpenBBError, match="between 0 and 100"):
            chain._get_nearest_otm_strikes(moneyness=101)

    def test_get_nearest_otm_strikes_missing_underlying_price_raises(self, chain):
        chain.__dict__["dataframe"] = chain.dataframe.drop(columns=["underlying_price"])

        with pytest.raises(OpenBBError, match="underlying_price must be provided"):
            chain._get_nearest_otm_strikes()

    def test_get_nearest_strike_invalid_option_type(self, chain):
        with pytest.raises(OpenBBError, match="option_type must be either"):
            chain._get_nearest_strike("bad")

    def test_get_nearest_strike_with_none_days(self, chain):
        assert (
            chain._get_nearest_strike("call", days=None, strike=100.0, force_otm=False)
            is not None
        )

    def test_get_nearest_strike_returns_none_for_empty_chain(self, monkeypatch, chain):
        monkeypatch.setattr(
            chain, "_get_nearest_expiration", lambda *args, **kwargs: "2099-01-01"
        )

        assert chain._get_nearest_strike("call", days=30, strike=100.0) is None

    def test_get_nearest_strike_returns_none_when_no_otm_match(self, chain):
        assert (
            chain._get_nearest_strike("put", days=30, strike=1.0, force_otm=True)
            is None
        )


@requires_pandas
class TestStrategyEdges:
    def test_straddle_days_zero_and_short(self, chain):
        zero_day = chain.straddle(days=0)
        short = chain.straddle(strike=-100.0)

        assert not zero_day.empty
        assert short.columns[0] == "Short Straddle"

    def test_straddle_missing_underlying_price_raises(self, chain):
        chain.__dict__["dataframe"] = chain.dataframe.drop(columns=["underlying_price"])

        with pytest.raises(OpenBBError, match="underlying_price must be provided"):
            chain.straddle()

    def test_straddle_missing_strike_raises_when_underlying_override_supplied(
        self, chain
    ):
        chain.__dict__["dataframe"] = chain.dataframe.drop(columns=["underlying_price"])

        with pytest.raises(OpenBBError, match="strike must be provided"):
            chain.straddle(underlying_price=100.0)

    def test_straddle_missing_premium_raises(self, monkeypatch, chain):
        monkeypatch.setattr(chain, "_get_nearest_strike", lambda *args, **kwargs: 999.0)

        with pytest.raises(OpenBBError, match="No premium data found"):
            chain.straddle()

    def test_strangle_short_and_missing_premium(self, monkeypatch, chain):
        short = chain.strangle(moneyness=-5.0)
        monkeypatch.setattr(chain, "_get_nearest_strike", lambda *args, **kwargs: 999.0)

        assert short.columns[0] == "Short Strangle"
        with pytest.raises(OpenBBError, match="No premium data found"):
            chain.strangle(moneyness=5.0)

    def test_strangle_missing_underlying_price_raises(self, chain):
        chain.__dict__["dataframe"] = chain.dataframe.drop(columns=["underlying_price"])

        with pytest.raises(OpenBBError, match="underlying_price must be provided"):
            chain.strangle()

    def test_vertical_call_spread_default_bear_and_empty(self, chain):
        default = chain.vertical_call_spread(days=0)
        bear = chain.vertical_call_spread(sold=95.0, bought=105.0)
        empty = chain.vertical_call_spread(sold=100.0, bought=100.0)

        assert not default.empty
        assert bear.columns[0] == "Bear Call Spread"
        assert empty.empty

    def test_vertical_call_spread_missing_underlying_price_raises(self, chain):
        chain.__dict__["dataframe"] = chain.dataframe.drop(columns=["underlying_price"])

        with pytest.raises(OpenBBError, match="underlying_price must be provided"):
            chain.vertical_call_spread()

    def test_vertical_put_spread_default_and_empty(self, chain):
        default = chain.vertical_put_spread(days=0)
        empty = chain.vertical_put_spread(sold=100.0, bought=100.0)

        assert not default.empty
        assert empty.empty

    def test_vertical_put_spread_missing_underlying_price_raises(self, chain):
        chain.__dict__["dataframe"] = chain.dataframe.drop(columns=["underlying_price"])

        with pytest.raises(OpenBBError, match="underlying_price must be provided"):
            chain.vertical_put_spread()

    def test_synthetic_long_edges(self, monkeypatch, chain):
        assert not chain.synthetic_long(days=None).empty
        assert not chain.synthetic_long(days=0).empty

        monkeypatch.setattr(chain, "_get_nearest_strike", lambda *args, **kwargs: 999.0)
        with pytest.raises(OpenBBError, match="No premium data found"):
            chain.synthetic_long()

    def test_synthetic_long_missing_underlying_price_raises(self, chain):
        chain.__dict__["dataframe"] = chain.dataframe.drop(columns=["underlying_price"])

        with pytest.raises(OpenBBError, match="underlying_price must be provided"):
            chain.synthetic_long()

    def test_synthetic_short_edges(self, monkeypatch, chain):
        assert not chain.synthetic_short(days=0).empty

        monkeypatch.setattr(chain, "_get_nearest_strike", lambda *args, **kwargs: 999.0)
        with pytest.raises(OpenBBError, match="No premium data found"):
            chain.synthetic_short()

    def test_synthetic_short_missing_underlying_price_raises(self, chain):
        chain.__dict__["dataframe"] = chain.dataframe.drop(columns=["underlying_price"])

        with pytest.raises(OpenBBError, match="underlying_price must be provided"):
            chain.synthetic_short()

    def test_strategies_tuple_and_flat_list_inputs(self, chain):
        result = chain.strategies(
            vertical_calls=(105.0, 95.0), vertical_puts=[95.0, 105.0]
        )

        assert result is not None

    def test_strategies_raises_when_all_results_empty(self, monkeypatch, chain):
        from pandas import DataFrame

        monkeypatch.setattr(chain, "straddle", lambda *args, **kwargs: DataFrame())
        monkeypatch.setattr(chain, "strangle", lambda *args, **kwargs: DataFrame())
        monkeypatch.setattr(
            chain, "synthetic_long", lambda *args, **kwargs: DataFrame()
        )
        monkeypatch.setattr(
            chain, "synthetic_short", lambda *args, **kwargs: DataFrame()
        )
        monkeypatch.setattr(
            chain, "vertical_call_spread", lambda *args, **kwargs: DataFrame()
        )
        monkeypatch.setattr(
            chain, "vertical_put_spread", lambda *args, **kwargs: DataFrame()
        )

        with pytest.raises(OpenBBError, match="No strategies found"):
            chain.strategies(straddle_strike=100.0, vertical_calls=(105.0, 95.0))


@requires_pandas
class TestSkewEdges:
    def test_skew_requires_implied_volatility(self, monkeypatch, chain):
        monkeypatch.setattr(type(chain), "has_iv", property(lambda self: False))

        with pytest.raises(OpenBBError, match="implied_volatility"):
            chain.skew()

    def test_skew_missing_underlying_price_raises(self, chain):
        chain.__dict__["dataframe"] = chain.dataframe.drop(columns=["underlying_price"])

        with pytest.raises(OpenBBError, match="underlying_price must be provided"):
            chain.skew(moneyness=10.0)

    def test_skew_horizontal_not_enough_information_raises(self, chain):
        df = chain.dataframe.copy()
        df.loc[df.option_type == "put", "implied_volatility"] = 0
        chain.__dict__["dataframe"] = df

        with pytest.raises(OpenBBError, match="Not enough information"):
            chain.skew(moneyness=10.0)

    def test_skew_vertical_not_enough_information_raises(self, chain):
        df = chain.dataframe.copy()
        df.loc[df.option_type == "put", "implied_volatility"] = 0
        chain.__dict__["dataframe"] = df

        with pytest.raises(OpenBBError, match="Not enough information"):
            chain.skew(date=30, moneyness=None)
