"""Tests for openbb_technical.indicators.statistics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from openbb_core.app.utils import df_to_basemodel

from openbb_technical.indicators.statistics import (
    AutocorrelationData,
    AutocorrelationQueryParams,
    ClenowData,
    ClenowQueryParams,
    DrawdownData,
    DrawdownQueryParams,
    HurstData,
    HurstQueryParams,
    ReturnsStatsData,
    ReturnsStatsQueryParams,
    StationarityData,
    StationarityQueryParams,
    _hurst_dfa,
    _hurst_rs,
    _interpret_hurst,
    _overall_verdict,
    _stats_block,
    autocorrelation,
    clenow,
    drawdown,
    hurst,
    returns_stats,
    stationarity,
)


@pytest.fixture(scope="module")
def long_records(ohlcv_df):
    """Convert the standard 99-row OHLCV fixture into ``list[Data]``."""
    return df_to_basemodel(ohlcv_df.reset_index())


@pytest.fixture(scope="module")
def stationary_records():
    """500 rows of i.i.d. Gaussian noise — stationary by construction."""
    rng = np.random.default_rng(0)
    n = 500
    y = rng.normal(loc=100.0, scale=1.0, size=n)
    df = pd.DataFrame(
        {"open": y, "high": y, "low": y, "close": y, "volume": np.arange(n)},
        index=pd.date_range("2021-01-01", periods=n, freq="D", name="date"),
    )
    return df_to_basemodel(df.reset_index())


@pytest.fixture(scope="module")
def random_walk_records():
    """500 rows of a Gaussian random walk — non-stationary by construction."""
    rng = np.random.default_rng(1)
    n = 500
    y = rng.normal(size=n).cumsum() + 100.0
    df = pd.DataFrame(
        {"open": y, "high": y, "low": y, "close": y, "volume": np.arange(n)},
        index=pd.date_range("2021-01-01", periods=n, freq="D", name="date"),
    )
    return df_to_basemodel(df.reset_index())


@pytest.fixture(scope="module")
def trend_stationary_records():
    """Linear trend plus noise — trend-stationary under ``ct`` regression."""
    rng = np.random.default_rng(42)
    n = 300
    t = np.arange(n, dtype=float)
    y = 0.1 * t + rng.normal(size=n)
    df = pd.DataFrame(
        {"open": y, "high": y, "low": y, "close": y, "volume": np.arange(n)},
        index=pd.date_range("2021-01-01", periods=n, freq="D", name="date"),
    )
    return df_to_basemodel(df.reset_index())


@pytest.fixture(scope="module")
def realistic_returns_records():
    """A year of log-normal returns suitable for Sharpe/Sortino/Calmar."""
    rng = np.random.default_rng(7)
    n = 252
    y = np.cumprod(1.0 + rng.normal(0.001, 0.02, n)) * 100.0
    df = pd.DataFrame(
        {"open": y, "high": y, "low": y, "close": y, "volume": np.arange(n)},
        index=pd.date_range("2021-01-01", periods=n, freq="D", name="date"),
    )
    return df_to_basemodel(df.reset_index())


@pytest.fixture(scope="module")
def monotone_up_records():
    """Strictly monotone rising series — no downside returns, no drawdown."""
    y = np.array([100.0, 101.0, 102.5, 105.0, 108.0, 110.0, 115.0, 120.0, 130.0, 145.0])
    df = pd.DataFrame(
        {"open": y, "high": y, "low": y, "close": y, "volume": np.arange(len(y))},
        index=pd.date_range("2021-01-01", periods=len(y), freq="D", name="date"),
    )
    return df_to_basemodel(df.reset_index())


@pytest.fixture(scope="module")
def constant_records():
    """Constant series — zero returns, zero variance."""
    y = np.full(50, 100.0)
    df = pd.DataFrame(
        {"open": y, "high": y, "low": y, "close": y, "volume": np.arange(50)},
        index=pd.date_range("2021-01-01", periods=50, freq="D", name="date"),
    )
    return df_to_basemodel(df.reset_index())


class TestClenow:
    def test_default(self, long_records):
        result = clenow(ClenowQueryParams(data=long_records, period=20))
        assert len(result.results) == 20
        assert all(isinstance(r, ClenowData) for r in result.results)
        first = result.results[0]
        assert first.predicted is not None
        assert first.r2 == result.results[-1].r2
        assert first.coefficient == result.results[-1].coefficient
        assert first.annualized_coefficient == pytest.approx(
            first.coefficient * first.r2
        )

    def test_alternate_target(self, long_records):
        result = clenow(ClenowQueryParams(data=long_records, target="open", period=20))
        assert result.results

    def test_defaults_via_params(self, long_records):
        params = ClenowQueryParams(data=long_records)
        assert params.period == 90
        assert params.target == "close"


class TestDrawdown:
    def test_default(self, long_records):
        result = drawdown(DrawdownQueryParams(data=long_records))
        assert result.results
        assert all(isinstance(r, DrawdownData) for r in result.results)
        first = result.results[0]
        assert first.cumulative_return == pytest.approx(0.0)
        assert first.drawdown_duration_days == 0

    def test_monotone_up_has_zero_drawdown(self, monotone_up_records):
        result = drawdown(DrawdownQueryParams(data=monotone_up_records))
        assert all(r.drawdown == pytest.approx(0.0) for r in result.results)
        assert all(r.drawdown_duration_days == 0 for r in result.results)

    def test_drawdown_duration_increments(self):
        """Drop-then-recover should grow duration while below peak, reset at recovery."""
        prices = [100.0, 110.0, 105.0, 100.0, 95.0, 120.0]
        df = pd.DataFrame(
            {
                "open": prices,
                "high": prices,
                "low": prices,
                "close": prices,
                "volume": list(range(len(prices))),
            },
            index=pd.date_range(
                "2021-01-01", periods=len(prices), freq="D", name="date"
            ),
        )
        records = df_to_basemodel(df.reset_index())
        result = drawdown(DrawdownQueryParams(data=records))
        durations = [r.drawdown_duration_days for r in result.results]
        assert durations == [0, 0, 1, 2, 3, 0]

    def test_defaults_via_params(self, long_records):
        params = DrawdownQueryParams(data=long_records)
        assert params.target == "close"


class TestReturnsStats:
    def test_summary_default(self, realistic_returns_records):
        result = returns_stats(ReturnsStatsQueryParams(data=realistic_returns_records))
        assert len(result.results) == 1
        row = result.results[0]
        assert isinstance(row, ReturnsStatsData)
        assert row.sharpe is not None
        assert row.sortino is not None
        assert row.calmar is not None
        assert row.max_drawdown < 0
        assert row.var_95 is not None
        assert row.cvar_95 is not None

    def test_rolling_window(self, realistic_returns_records):
        result = returns_stats(
            ReturnsStatsQueryParams(data=realistic_returns_records, window=20)
        )
        assert len(result.results) > 1
        assert all(isinstance(r, ReturnsStatsData) for r in result.results)
        assert result.results[0].date is not None

    @pytest.mark.parametrize(
        "frequency", ["daily", "weekly", "monthly", "quarterly", "annual"]
    )
    def test_each_frequency(self, realistic_returns_records, frequency):
        result = returns_stats(
            ReturnsStatsQueryParams(data=realistic_returns_records, frequency=frequency)
        )
        assert result.results

    def test_risk_free_rate_flips_excess(self, realistic_returns_records):
        baseline = returns_stats(
            ReturnsStatsQueryParams(data=realistic_returns_records, risk_free_rate=0.0)
        )
        shifted = returns_stats(
            ReturnsStatsQueryParams(data=realistic_returns_records, risk_free_rate=0.50)
        )
        assert baseline.results[0].sharpe != shifted.results[0].sharpe

    def test_monotone_up_no_sortino_no_calmar(self, monotone_up_records):
        result = returns_stats(ReturnsStatsQueryParams(data=monotone_up_records))
        row = result.results[0]
        assert row.sortino is None
        assert row.calmar is None

    def test_sortino_uses_downside_deviation_below_target(self):
        # Simple returns: [-0.10, -0.10, 0.20, 0.20].
        # Mean excess = 0.05; downside deviation = sqrt((0.01 + 0.01 + 0 + 0) / 4) = sqrt(0.005).
        # Using sample std of negative returns only would yield std([-0.10, -0.10]) == 0 -> None.
        returns = pd.Series([-0.10, -0.10, 0.20, 0.20])
        block = _stats_block(returns, periods_per_year=252, rf_per_period=0.0)
        expected = 0.05 / np.sqrt(0.005) * np.sqrt(252)
        assert block["sortino"] == pytest.approx(expected)

        # Single negative observation: [-0.08, 0.04, 0.04, 0.04].
        # Mean excess = 0.01; downside deviation = sqrt(0.08^2 / 4) = 0.04.
        single_neg = pd.Series([-0.08, 0.04, 0.04, 0.04])
        block_single = _stats_block(single_neg, periods_per_year=252, rf_per_period=0.0)
        assert block_single["sortino"] == pytest.approx(0.25 * np.sqrt(252))

    def test_constant_series(self, constant_records):
        result = returns_stats(ReturnsStatsQueryParams(data=constant_records))
        row = result.results[0]
        assert row.mean_return == pytest.approx(0.0)
        assert row.std_return == pytest.approx(0.0)
        assert row.sharpe is None
        assert row.skew is None
        assert row.kurtosis is None

    def test_single_row_short_block(self):
        df = pd.DataFrame(
            {
                "open": [100.0],
                "high": [100.0],
                "low": [100.0],
                "close": [100.0],
                "volume": [1],
            },
            index=pd.date_range("2021-01-01", periods=1, freq="D", name="date"),
        )
        records = df_to_basemodel(df.reset_index())
        result = returns_stats(ReturnsStatsQueryParams(data=records))
        row = result.results[0]
        assert row.mean_return is None
        assert row.date is None

    def test_defaults_via_params(self, long_records):
        params = ReturnsStatsQueryParams(data=long_records)
        assert params.frequency == "daily"
        assert params.window is None
        assert params.risk_free_rate == 0.0


class TestStationarity:
    def test_random_walk_is_non_stationary(self, random_walk_records):
        result = stationarity(StationarityQueryParams(data=random_walk_records))
        row = result.results[0]
        assert isinstance(row, StationarityData)
        assert row.overall_verdict == "non_stationary"
        assert row.adf_verdict == "non_stationary"

    def test_stationary_series(self, stationary_records):
        result = stationarity(
            StationarityQueryParams(data=stationary_records, regression="c")
        )
        row = result.results[0]
        assert row.overall_verdict == "stationary"
        assert row.adf_verdict == "stationary"
        assert row.kpss_verdict == "stationary"

    def test_trend_stationary_with_ct(self, trend_stationary_records):
        result = stationarity(
            StationarityQueryParams(data=trend_stationary_records, regression="ct")
        )
        row = result.results[0]
        assert row.overall_verdict == "trend_stationary"

    def test_adf_only(self, random_walk_records):
        result = stationarity(
            StationarityQueryParams(data=random_walk_records, test="adf")
        )
        row = result.results[0]
        assert row.kpss_verdict == "skipped"
        assert row.adf_verdict in {"stationary", "non_stationary"}

    def test_kpss_only(self, random_walk_records):
        result = stationarity(
            StationarityQueryParams(data=random_walk_records, test="kpss")
        )
        row = result.results[0]
        assert row.adf_verdict == "skipped"
        assert row.kpss_verdict in {"stationary", "non_stationary"}

    def test_regression_n_routes_kpss_to_c(self, stationary_records):
        result = stationarity(
            StationarityQueryParams(data=stationary_records, regression="n")
        )
        assert result.results

    def test_inconclusive_branch(self, trend_stationary_records):
        result = stationarity(
            StationarityQueryParams(data=trend_stationary_records, regression="ctt")
        )
        assert result.results[0].overall_verdict == "inconclusive"

    def test_overall_verdict_adf_only_helper(self):
        assert _overall_verdict("stationary", None, "c") == "stationary"
        assert _overall_verdict("non_stationary", None, "c") == "non_stationary"

    def test_overall_verdict_kpss_only_helper(self):
        assert _overall_verdict(None, "stationary", "c") == "stationary"
        assert _overall_verdict(None, "non_stationary", "c") == "non_stationary"

    def test_defaults_via_params(self, long_records):
        params = StationarityQueryParams(data=long_records)
        assert params.test == "both"
        assert params.regression == "c"


class TestHurst:
    def test_rs_random_walk_is_trending(self, random_walk_records):
        result = hurst(
            HurstQueryParams(data=random_walk_records, method="rs", max_lag=80)
        )
        row = result.results[0]
        assert isinstance(row, HurstData)
        assert row.hurst_exponent is not None
        assert row.interpretation == "trending"
        assert row.confidence is not None

    def test_dfa_random_walk(self, random_walk_records):
        result = hurst(
            HurstQueryParams(data=random_walk_records, method="dfa", max_lag=80)
        )
        row = result.results[0]
        assert row.hurst_exponent is not None
        assert row.interpretation == "trending"

    def test_invalid_lag_range(self, random_walk_records):
        with pytest.raises(ValueError, match="max_lag must be greater"):
            hurst(HurstQueryParams(data=random_walk_records, min_lag=10, max_lag=5))

    def test_interpret_helper(self):
        assert _interpret_hurst(0.7) == "trending"
        assert _interpret_hurst(0.3) == "mean_reverting"
        assert _interpret_hurst(0.5) == "random_walk"
        assert _interpret_hurst(None) == "random_walk"
        assert _interpret_hurst(float("nan")) == "random_walk"

    def test_rs_too_short_returns_nan(self):
        h, r2 = _hurst_rs(np.arange(10, dtype=float), 100, 200)
        assert np.isnan(h) and np.isnan(r2)

    def test_dfa_too_short_returns_nan(self):
        h, r2 = _hurst_dfa(np.arange(10, dtype=float), 100, 200)
        assert np.isnan(h) and np.isnan(r2)

    def test_rs_constant_series_returns_nan(self):
        h, r2 = _hurst_rs(np.ones(500, dtype=float), 2, 10)
        assert np.isnan(h) and np.isnan(r2)

    def test_dfa_constant_series_returns_nan(self):
        with np.errstate(divide="ignore", invalid="ignore"):
            h, r2 = _hurst_dfa(np.ones(500, dtype=float), 2, 10)
        assert np.isnan(h) and np.isnan(r2)

    def test_endpoint_propagates_nan(self):
        """Trigger the ``h_out`` / ``r2_out`` ``None`` branches on a short series."""
        y = np.arange(50, dtype=float)
        df = pd.DataFrame(
            {"open": y, "high": y, "low": y, "close": y, "volume": np.arange(50)},
            index=pd.date_range("2021-01-01", periods=50, freq="D", name="date"),
        )
        records = df_to_basemodel(df.reset_index())
        result = hurst(
            HurstQueryParams(data=records, method="rs", min_lag=100, max_lag=200)
        )
        row = result.results[0]
        assert row.hurst_exponent is None
        assert row.confidence is None
        assert row.interpretation == "random_walk"

    def test_defaults_via_params(self, random_walk_records):
        params = HurstQueryParams(data=random_walk_records)
        assert params.method == "rs"
        assert params.min_lag == 2
        assert params.max_lag == 100


class TestAutocorrelation:
    def test_default_both(self, random_walk_records):
        result = autocorrelation(
            AutocorrelationQueryParams(data=random_walk_records, max_lag=10)
        )
        assert len(result.results) == 11
        assert all(isinstance(r, AutocorrelationData) for r in result.results)
        row = result.results[0]
        assert row.lag == 0
        assert row.acf == pytest.approx(1.0)
        assert row.pacf == pytest.approx(1.0)
        assert row.significant is False

    def test_acf_only(self, random_walk_records):
        result = autocorrelation(
            AutocorrelationQueryParams(
                data=random_walk_records, max_lag=10, method="acf"
            )
        )
        row = result.results[1]
        assert row.acf is not None
        assert row.pacf is None

    def test_pacf_only(self, random_walk_records):
        result = autocorrelation(
            AutocorrelationQueryParams(
                data=random_walk_records, max_lag=10, method="pacf"
            )
        )
        row = result.results[1]
        assert row.pacf is not None
        assert row.acf is None
        assert row.significant is False

    def test_use_returns_false(self, random_walk_records):
        result = autocorrelation(
            AutocorrelationQueryParams(
                data=random_walk_records, max_lag=10, use_returns=False
            )
        )
        assert result.results

    def test_significant_lag_flag(self):
        """A deterministic monotone series produces highly autocorrelated levels."""
        n = 200
        y = np.linspace(100.0, 200.0, n)
        df = pd.DataFrame(
            {"open": y, "high": y, "low": y, "close": y, "volume": np.arange(n)},
            index=pd.date_range("2021-01-01", periods=n, freq="D", name="date"),
        )
        records = df_to_basemodel(df.reset_index())
        result = autocorrelation(
            AutocorrelationQueryParams(data=records, max_lag=20, use_returns=False)
        )
        flags = [r.significant for r in result.results]
        assert flags[0] is False
        assert any(flags[1:])

    def test_short_series_raises(self, long_records):
        with pytest.raises(ValueError, match="too short"):
            autocorrelation(AutocorrelationQueryParams(data=long_records, max_lag=200))

    def test_defaults_via_params(self, long_records):
        params = AutocorrelationQueryParams(data=long_records)
        assert params.max_lag == 40
        assert params.method == "both"
        assert params.use_returns is True


class TestStatsBlockHelper:
    """Direct coverage of ``_stats_block`` edge cases."""

    def test_empty_returns(self):
        block = _stats_block(pd.Series(dtype="float64"), 252, 0.0)
        assert block["mean_return"] is None
        assert block["sharpe"] is None
