"""Tests for openbb_technical.helpers."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from openbb_technical.helpers import (
    calculate_cones,
    calculate_fib_levels,
    clenow_momentum,
    garman_klass,
    hodges_tompkins,
    parkinson,
    rogers_satchell,
    standard_deviation,
    validate_data,
    yang_zhang,
)


class TestValidateData:
    def test_accepts_int_length(self, ohlcv_df):
        validate_data(ohlcv_df["close"].tolist(), 20)

    def test_accepts_list_of_lengths(self, ohlcv_df):
        validate_data(ohlcv_df["close"].tolist(), [10, 20, 30])

    def test_raises_when_too_short(self):
        with pytest.raises(ValueError, match="less than required"):
            validate_data([1.0, 2.0], 5)

    def test_raises_when_any_length_exceeds(self):
        with pytest.raises(ValueError, match="less than required"):
            validate_data([1.0, 2.0, 3.0], [2, 5])


class _VolatilityShared:
    """Reusable branch sweep for the six volatility helpers."""

    func: staticmethod = None  # set in subclasses

    def test_default_returns_non_empty(self, ohlcv_df):
        assert not self.__class__.func(ohlcv_df).empty

    def test_is_crypto_picks_365_periods(self, ohlcv_df):
        assert not self.__class__.func(ohlcv_df, is_crypto=True).empty

    def test_trading_periods_override_warns_when_crypto(self, ohlcv_df):
        with pytest.warns(UserWarning, match="is_crypto is overridden"):
            self.__class__.func(ohlcv_df, trading_periods=252, is_crypto=True)

    def test_clean_false_keeps_leading_nans(self, ohlcv_df):
        result = self.__class__.func(ohlcv_df, clean=False)
        assert result.isna().any()

    def test_window_too_small_warns_and_defaults(self, ohlcv_df):
        with pytest.warns(UserWarning, match="Window must be at least"):
            self.__class__.func(ohlcv_df, window=0)


class TestParkinson(_VolatilityShared):
    func = staticmethod(parkinson)


class TestStandardDeviation(_VolatilityShared):
    func = staticmethod(standard_deviation)


class TestGarmanKlass(_VolatilityShared):
    func = staticmethod(garman_klass)


class TestHodgesTompkins(_VolatilityShared):
    func = staticmethod(hodges_tompkins)

    def test_window_too_small_warns_and_defaults(self, ohlcv_df):
        with pytest.warns(UserWarning, match="Window must be at least 2"):
            self.__class__.func(ohlcv_df, window=1)


class TestRogersSatchell(_VolatilityShared):
    func = staticmethod(rogers_satchell)


class TestYangZhang(_VolatilityShared):
    func = staticmethod(yang_zhang)

    def test_window_too_small_warns_and_defaults(self, ohlcv_df):
        with pytest.warns(UserWarning, match="Window must be at least 2"):
            self.__class__.func(ohlcv_df, window=1)


class TestClenowMomentum:
    def test_returns_r2_coef_predictions(self, ohlcv_df):
        r2, coef, preds = clenow_momentum(ohlcv_df["close"])
        assert isinstance(r2, float)
        assert isinstance(coef, float)
        assert len(preds) == 90

    def test_flat_window_has_zero_r2(self):
        r2, coef, preds = clenow_momentum(pd.Series([100.0] * 120))
        assert r2 == 0.0
        assert coef == pytest.approx(0.0, abs=1e-10)
        assert preds.to_numpy() == pytest.approx(np.log(100.0))

    def test_raises_when_window_exceeds_data(self):
        with pytest.raises(ValueError, match="at least last"):
            clenow_momentum(pd.Series([1.0, 2.0]), window=90)


class TestCalculateCones:
    def test_default_model_std(self, ohlcv_df):
        result = calculate_cones(
            ohlcv_df, lower_q=0.1, upper_q=0.9, is_crypto=False, model="std"
        )
        assert not result.empty

    @pytest.mark.parametrize(
        "model",
        [
            "std",
            "parkinson",
            "garman_klass",
            "hodges_tompkins",
            "rogers_satchell",
            "yang_zhang",
        ],
    )
    def test_every_model(self, ohlcv_df, model):
        result = calculate_cones(
            ohlcv_df, lower_q=0.2, upper_q=0.8, is_crypto=False, model=model
        )
        assert not result.empty

    def test_is_crypto_branch(self, ohlcv_df):
        result = calculate_cones(
            ohlcv_df, lower_q=0.1, upper_q=0.9, is_crypto=True, model="std"
        )
        assert not result.empty

    def test_swaps_quantiles_when_lower_above_upper(self, ohlcv_df):
        """When lower_q > upper_q the function swaps them silently."""
        normal = calculate_cones(
            ohlcv_df, lower_q=0.1, upper_q=0.9, is_crypto=False, model="std"
        )
        swapped = calculate_cones(
            ohlcv_df, lower_q=0.9, upper_q=0.1, is_crypto=False, model="std"
        )
        assert list(normal.columns) == list(swapped.columns)

    def test_raises_on_quantile_out_of_range(self, ohlcv_df):
        with pytest.raises(ValueError, match="between 0 and 1"):
            calculate_cones(
                ohlcv_df, lower_q=1.5, upper_q=2.0, is_crypto=False, model="std"
            )


class TestCalculateFibLevels:
    def test_snaps_missing_start_date_to_nearest(self):
        """Resolve a missing start date against itself when choosing the endpoint."""
        index = pd.bdate_range("2024-01-01", periods=60)
        data = pd.DataFrame({"close": np.linspace(100, 160, 60)}, index=index)
        start_date = pd.Timestamp("2024-01-06")  # Saturday, not in the index.
        end_date = index[-1]

        with pytest.warns(UserWarning, match="Start date not in data"):
            _, min_date, max_date, min_pr, max_pr, _ = calculate_fib_levels(
                data, "close", start_date=start_date, end_date=end_date
            )

        assert min_date == pd.Timestamp("2024-01-05")
        assert max_date == end_date
        assert max_pr > min_pr

    def test_default_branch(self, ohlcv_df):
        result = calculate_fib_levels(ohlcv_df, "close")
        assert result is not None
        assert len(result) >= 6

    def test_raises_on_missing_close_col(self, ohlcv_df):
        with pytest.raises(ValueError, match="not in data"):
            calculate_fib_levels(ohlcv_df, "missing_col")

    def test_with_explicit_start_end_in_index(self, ohlcv_df):
        start = ohlcv_df.index[10]
        end = ohlcv_df.index[60]
        result = calculate_fib_levels(ohlcv_df, "close", start_date=start, end_date=end)
        assert result is not None

    def test_with_explicit_start_end_not_in_index_warns(self, ohlcv_df):
        """When user supplies dates outside the index, nearest neighbours are used and a warning is emitted."""
        start = ohlcv_df.index[10] + pd.Timedelta(hours=12)
        end = ohlcv_df.index[60] + pd.Timedelta(hours=12)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            calculate_fib_levels(ohlcv_df, "close", start_date=start, end_date=end)
        assert any("not in data" in str(w.message) for w in caught)

    def test_swaps_when_min_date_after_max(self, ohlcv_df):
        """When start_date is after end_date the function swaps the pair."""
        df = ohlcv_df.copy()
        df["close"] = np.concatenate(
            [np.arange(50, 0, -1, dtype=float), np.arange(1, 50, dtype=float)]
        )
        start = df.index[5]
        end = df.index[80]
        result = calculate_fib_levels(df, "close", start_date=start, end_date=end)
        assert result is not None
