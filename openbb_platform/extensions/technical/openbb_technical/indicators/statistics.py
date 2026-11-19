"""Statistics-family technical indicators."""

from datetime import (
    date as dateType,
    datetime,
)
from typing import Literal, cast

from openbb_core.app.model.example import APIEx, PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from openbb_core.app.utils import basemodel_to_df, get_target_column
from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field, PositiveInt

from openbb_technical.helpers import clenow_momentum, validate_data

date = dateType


router = Router(prefix="", description="Statistics indicators.")


_FREQ_FACTORS: dict[str, int] = {
    "daily": 252,
    "weekly": 52,
    "monthly": 12,
    "quarterly": 4,
    "annual": 1,
}

Frequency = Literal["daily", "weekly", "monthly", "quarterly", "annual"]


class ClenowQueryParams(QueryParams):
    """Query parameters for the Clenow Volatility-Adjusted Momentum endpoint.

    Parameters
    ----------
    data : list[Data]
        Input price series.
    index : str, optional
        Index column name in ``data``, by default ``"date"``.
    target : str, optional
        Column to regress on the log-linear time index, by default ``"close"``.
    period : PositiveInt, optional
        Lookback window in bars for the log-price regression, by default 90.
    """

    __category__ = "stats"
    __output_columns__ = (
        "date",
        "predicted",
        "r2",
        "coefficient",
        "annualized_coefficient",
    )

    data: list[Data] = Field(description="Input price series.")
    index: str = Field(default="date", description="Index column name in ``data``.")
    target: str = Field(default="close", description="Column to regress.")
    period: PositiveInt = Field(
        default=90,
        description="Lookback window for the log-price regression.",
    )


class ClenowData(Data):
    """One row of the Clenow best-fit regression with the summary echoed per row.

    Parameters
    ----------
    date : date | str
        Observation date.
    predicted : float, optional
        Best-fit log-linear value at this date.
    r2 : float
        R-squared of the regression fit on log prices.
    coefficient : float
        Annualised slope of the log-price regression.
    annualized_coefficient : float
        ``coefficient * r2`` - Clenow's volatility-adjusted momentum factor.
    """

    date: datetime | dateType | str = Field(description="Observation date.")
    predicted: float | None = Field(
        description="Best-fit log-linear value at this date."
    )
    r2: float = Field(description="R-squared of the regression fit on log prices.")
    coefficient: float = Field(
        description="Annualised slope of the log-price regression."
    )
    annualized_coefficient: float = Field(
        description="``coefficient * r2`` - Clenow's momentum factor.",
    )


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Clenow momentum on TSLA over the trailing 90 days.",
            code=[
                "data = obb.equity.price.historical(symbol='TSLA', start_date='2023-01-01', provider='yfinance').results",
                "out = obb.technical.clenow(data=data, period=90)",
            ],
        ),
        APIEx(parameters={"data": APIEx.mock_data("timeseries"), "period": 2}),
    ],
)
def clenow(params: ClenowQueryParams) -> OBBject[list[ClenowData]]:
    """Calculate Clenow Volatility-Adjusted Momentum on log prices."""
    validate_data(params.data, params.period)
    df = basemodel_to_df(params.data, index=params.index)
    series = get_target_column(df, params.target)
    r2, coef, predictions = clenow_momentum(series, params.period)
    factor = coef * r2
    tail = df.tail(params.period).reset_index().rename(columns={params.index: "date"})
    out = []
    for i, row in enumerate(tail.to_dict(orient="records")):
        out.append(
            ClenowData(
                date=row["date"],
                predicted=float(predictions.iloc[i]),
                r2=float(r2),
                coefficient=float(coef),
                annualized_coefficient=float(factor),
            )
        )
    return OBBject(results=out)


class DrawdownQueryParams(QueryParams):
    """Query parameters for the drawdown endpoint.

    Parameters
    ----------
    data : list[Data]
        Input price series.
    index : str, optional
        Index column name in ``data``, by default ``"date"``.
    target : str, optional
        Column to evaluate drawdowns on, by default ``"close"``.
    """

    __category__ = "stats"
    __output_columns__ = (
        "date",
        "cumulative_return",
        "running_peak",
        "drawdown",
        "drawdown_duration_days",
    )

    data: list[Data] = Field(description="Input price series.")
    index: str = Field(default="date", description="Index column name in ``data``.")
    target: str = Field(default="close", description="Column to evaluate drawdowns on.")


class DrawdownData(Data):
    """One row of the drawdown time series.

    Parameters
    ----------
    date : date | str
        Observation date.
    cumulative_return : float, optional
        Cumulative return from the first observation in ``data``.
    running_peak : float, optional
        Running maximum of ``cumulative_return``.
    drawdown : float, optional
        Percentage drop from the running peak (negative or zero).
    drawdown_duration_days : int
        Consecutive observations since the most recent peak.
    """

    date: datetime | dateType | str = Field(description="Observation date.")
    cumulative_return: float | None = Field(
        description="Cumulative return from the first observation.",
    )
    running_peak: float | None = Field(
        description="Running maximum of ``cumulative_return``."
    )
    drawdown: float | None = Field(
        description="Percentage drop from the running peak (negative or zero).",
    )
    drawdown_duration_days: int = Field(
        description="Consecutive observations since the most recent peak.",
    )


@router.command(
    methods=["POST"],
    examples=[APIEx(parameters={"data": APIEx.mock_data("timeseries")})],
)
def drawdown(params: DrawdownQueryParams) -> OBBject[list[DrawdownData]]:
    """Compute cumulative return, running peak, drawdown, and underwater duration."""
    df = basemodel_to_df(params.data, index=params.index)
    series = get_target_column(df, params.target).astype(float)
    cum = series / series.iloc[0] - 1.0
    peak = cum.cummax()
    dd = (1.0 + cum) / (1.0 + peak) - 1.0
    duration = []
    counter = 0
    for c, p in zip(cum.tolist(), peak.tolist()):
        if c >= p:
            counter = 0
        else:
            counter += 1
        duration.append(counter)
    out = []
    for i, idx in enumerate(cum.index):
        out.append(
            DrawdownData(
                date=idx,
                cumulative_return=float(cum.iloc[i]),
                running_peak=float(peak.iloc[i]),
                drawdown=float(dd.iloc[i]),
                drawdown_duration_days=int(duration[i]),
            )
        )
    return OBBject(results=out)


class ReturnsStatsQueryParams(QueryParams):
    """Query parameters for the ``returns_stats`` endpoint.

    Parameters
    ----------
    data : list[Data]
        Input price series.
    index : str, optional
        Index column name in ``data``, by default ``"date"``.
    target : str, optional
        Column to evaluate returns on, by default ``"close"``.
    frequency : Frequency, optional
        Annualisation frequency for Sharpe, Sortino, Calmar, and the
        per-period risk-free rate, by default ``"daily"``.
    risk_free_rate : float, optional
        Annualised risk-free rate used for Sharpe and Sortino numerators,
        by default 0.0.
    window : PositiveInt, optional
        Rolling window length in bars. ``None`` returns a single summary row
        over the full sample, by default ``None``.
    """

    __category__ = "stats"
    __output_columns__ = (
        "date",
        "mean_return",
        "std_return",
        "skew",
        "kurtosis",
        "sharpe",
        "sortino",
        "calmar",
        "max_drawdown",
        "var_95",
        "cvar_95",
    )

    data: list[Data] = Field(description="Input price series.")
    index: str = Field(default="date", description="Index column name in ``data``.")
    target: str = Field(default="close", description="Column to evaluate returns on.")
    frequency: Frequency = Field(
        default="daily",
        description="Annualisation frequency for Sharpe/Sortino/Calmar/risk-free.",
    )
    risk_free_rate: float = Field(
        default=0.0,
        description="Annualised risk-free rate used for Sharpe and Sortino.",
    )
    window: PositiveInt | None = Field(
        default=None,
        description="Rolling window. ``None`` returns a single summary row.",
    )


class ReturnsStatsData(Data):
    """One row of return-distribution statistics.

    Parameters
    ----------
    date : date | str, optional
        Window end date, or ``None`` for the summary row when ``window`` is
        unset.
    mean_return : float, optional
        Arithmetic mean of simple returns over the window.
    std_return : float, optional
        Sample standard deviation of returns (ddof=1).
    skew : float, optional
        Skewness of the return distribution.
    kurtosis : float, optional
        Excess kurtosis of the return distribution.
    sharpe : float, optional
        Annualised Sharpe ratio of excess returns.
    sortino : float, optional
        Annualised Sortino ratio using downside deviation.
    calmar : float, optional
        Annualised return divided by the absolute value of max drawdown.
    max_drawdown : float, optional
        Worst peak-to-trough drawdown over the window (negative).
    var_95 : float, optional
        5th-percentile return - historical Value-at-Risk at 95%.
    cvar_95 : float, optional
        Mean of returns at or below ``var_95`` - historical Conditional VaR.
    """

    date: datetime | dateType | str | None = Field(
        default=None, description="Window end date, or ``None`` for the summary row."
    )
    mean_return: float | None = Field(
        description="Arithmetic mean of simple returns over the window."
    )
    std_return: float | None = Field(
        description="Sample standard deviation of returns (ddof=1)."
    )
    skew: float | None = Field(description="Skewness of the return distribution.")
    kurtosis: float | None = Field(
        description="Excess kurtosis of the return distribution."
    )
    sharpe: float | None = Field(
        description="Annualised Sharpe ratio of excess returns."
    )
    sortino: float | None = Field(
        description="Annualised Sortino ratio using downside deviation."
    )
    calmar: float | None = Field(
        description="Annualised return divided by the absolute value of max drawdown."
    )
    max_drawdown: float | None = Field(
        description="Worst peak-to-trough drawdown over the window (negative)."
    )
    var_95: float | None = Field(
        description="5th-percentile return - historical Value-at-Risk at 95%."
    )
    cvar_95: float | None = Field(
        description="Mean of returns at or below ``var_95`` - historical Conditional VaR."
    )


def _stats_block(returns, periods_per_year: int, rf_per_period: float) -> dict:
    """Compute the full statistics block for one return vector."""
    from numpy import isfinite, sqrt
    from scipy.stats import (
        kurtosis as _kurt,
        skew as _skew,
    )

    clean = returns.dropna()
    if len(clean) < 2:
        return {
            "mean_return": None,
            "std_return": None,
            "skew": None,
            "kurtosis": None,
            "sharpe": None,
            "sortino": None,
            "calmar": None,
            "max_drawdown": None,
            "var_95": None,
            "cvar_95": None,
        }
    mean = float(clean.mean())
    std = float(clean.std(ddof=1))
    sk = float(_skew(clean))
    kt = float(_kurt(clean))
    excess = clean - rf_per_period
    sharpe = (
        float(excess.mean() / excess.std(ddof=1) * sqrt(periods_per_year))
        if excess.std(ddof=1) > 0
        else None
    )
    downside_dev = float(sqrt((excess.clip(upper=0.0) ** 2).mean()))
    if downside_dev > 0:
        sortino = float(excess.mean() / downside_dev * sqrt(periods_per_year))
    else:
        sortino = None
    cum = (1.0 + clean).cumprod()
    peak = cum.cummax()
    dd = cum / peak - 1.0
    max_dd = float(dd.min())
    ann_return = (float(cum.iloc[-1]) ** (periods_per_year / len(clean))) - 1.0
    calmar = float(ann_return / abs(max_dd)) if max_dd < 0 else None
    var_95 = float(clean.quantile(0.05))
    tail = clean[clean <= var_95]
    cvar_95 = float(tail.mean()) if len(tail) > 0 else None
    return {
        "mean_return": mean,
        "std_return": std,
        "skew": sk if isfinite(sk) else None,
        "kurtosis": kt if isfinite(kt) else None,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "max_drawdown": max_dd,
        "var_95": var_95,
        "cvar_95": cvar_95,
    }


@router.command(
    methods=["POST"],
    examples=[APIEx(parameters={"data": APIEx.mock_data("timeseries")})],
)
def returns_stats(params: ReturnsStatsQueryParams) -> OBBject[list[ReturnsStatsData]]:
    """Calculate distributional and risk-adjusted statistics on simple returns."""
    df = basemodel_to_df(params.data, index=params.index)
    series = get_target_column(df, params.target).astype(float)
    returns = series.pct_change().dropna()
    periods_per_year = _FREQ_FACTORS[params.frequency]
    rf_per_period = params.risk_free_rate / periods_per_year
    if params.window is None:
        block = _stats_block(returns, periods_per_year, rf_per_period)
        block["date"] = returns.index[-1] if len(returns) else None
        return OBBject(results=[ReturnsStatsData(**block)])
    out: list[ReturnsStatsData] = []
    for end in range(params.window, len(returns) + 1):
        chunk = returns.iloc[end - params.window : end]
        block = _stats_block(chunk, periods_per_year, rf_per_period)
        block["date"] = chunk.index[-1]
        out.append(ReturnsStatsData(**block))
    return OBBject(results=out)


class StationarityQueryParams(QueryParams):
    """Query parameters for the stationarity endpoint.

    Parameters
    ----------
    data : list[Data]
        Input series.
    index : str, optional
        Index column name in ``data``, by default ``"date"``.
    target : str, optional
        Column to test for stationarity, by default ``"close"``.
    test : {"adf", "kpss", "both"}, optional
        Which test(s) to run, by default ``"both"``.
    regression : {"c", "ct", "ctt", "n"}, optional
        Deterministic component included in the regression: ``c`` constant,
        ``ct`` constant plus trend, ``ctt`` constant plus quadratic trend,
        ``n`` none. KPSS supports ``c`` or ``ct`` only and falls back to
        ``c`` for other values, by default ``"c"``.
    """

    __category__ = "stats"
    __output_columns__ = (
        "adf_statistic",
        "adf_pvalue",
        "adf_critical_1pct",
        "adf_critical_5pct",
        "adf_critical_10pct",
        "adf_verdict",
        "kpss_statistic",
        "kpss_pvalue",
        "kpss_critical_1pct",
        "kpss_critical_5pct",
        "kpss_critical_10pct",
        "kpss_verdict",
        "overall_verdict",
    )

    data: list[Data] = Field(description="Input series.")
    index: str = Field(default="date", description="Index column name in ``data``.")
    target: str = Field(default="close", description="Column to test for stationarity.")
    test: Literal["adf", "kpss", "both"] = Field(
        default="both", description="Which test(s) to run."
    )
    regression: Literal["c", "ct", "ctt", "n"] = Field(
        default="c",
        description="Regression component: constant, trend, quadratic-trend, or none.",
    )


class StationarityData(Data):
    """Single-row stationarity-test summary.

    Parameters
    ----------
    adf_statistic : float, optional
        Augmented Dickey-Fuller test statistic.
    adf_pvalue : float, optional
        ADF p-value.
    adf_critical_1pct : float, optional
        ADF critical value at the 1% significance level.
    adf_critical_5pct : float, optional
        ADF critical value at the 5% significance level.
    adf_critical_10pct : float, optional
        ADF critical value at the 10% significance level.
    adf_verdict : {"stationary", "non_stationary", "skipped"}, optional
        ADF verdict at 5%, or ``"skipped"`` when the test was not run.
    kpss_statistic : float, optional
        Kwiatkowski-Phillips-Schmidt-Shin test statistic.
    kpss_pvalue : float, optional
        KPSS p-value.
    kpss_critical_1pct : float, optional
        KPSS critical value at the 1% significance level.
    kpss_critical_5pct : float, optional
        KPSS critical value at the 5% significance level.
    kpss_critical_10pct : float, optional
        KPSS critical value at the 10% significance level.
    kpss_verdict : {"stationary", "non_stationary", "skipped"}, optional
        KPSS verdict at 5%, or ``"skipped"`` when the test was not run.
    overall_verdict : {"stationary", "non_stationary", "trend_stationary", "inconclusive"}
        Combined verdict from the available ADF and KPSS results.
    """

    adf_statistic: float | None = Field(
        description="Augmented Dickey-Fuller test statistic."
    )
    adf_pvalue: float | None = Field(description="ADF p-value.")
    adf_critical_1pct: float | None = Field(
        description="ADF critical value at the 1% significance level."
    )
    adf_critical_5pct: float | None = Field(
        description="ADF critical value at the 5% significance level."
    )
    adf_critical_10pct: float | None = Field(
        description="ADF critical value at the 10% significance level."
    )
    adf_verdict: Literal["stationary", "non_stationary", "skipped"] | None = Field(
        description='ADF verdict at 5%, or ``"skipped"`` when the test was not run.'
    )
    kpss_statistic: float | None = Field(
        description="Kwiatkowski-Phillips-Schmidt-Shin test statistic."
    )
    kpss_pvalue: float | None = Field(description="KPSS p-value.")
    kpss_critical_1pct: float | None = Field(
        description="KPSS critical value at the 1% significance level."
    )
    kpss_critical_5pct: float | None = Field(
        description="KPSS critical value at the 5% significance level."
    )
    kpss_critical_10pct: float | None = Field(
        description="KPSS critical value at the 10% significance level."
    )
    kpss_verdict: Literal["stationary", "non_stationary", "skipped"] | None = Field(
        description='KPSS verdict at 5%, or ``"skipped"`` when the test was not run.'
    )
    overall_verdict: Literal[
        "stationary", "non_stationary", "trend_stationary", "inconclusive"
    ] = Field(description="Combined verdict from the available ADF and KPSS results.")


def _adf_block(values, regression: str) -> dict:
    """Run ADF and package the result."""
    from statsmodels.tsa.stattools import adfuller

    result = adfuller(values, regression=regression, result_object=True)
    pvalue = result.pvalue
    crit = result.critical_values
    verdict = "stationary" if pvalue < 0.05 else "non_stationary"
    return {
        "adf_statistic": float(result.statistic),
        "adf_pvalue": float(pvalue),
        "adf_critical_1pct": float(crit.get("1%")),
        "adf_critical_5pct": float(crit.get("5%")),
        "adf_critical_10pct": float(crit.get("10%")),
        "adf_verdict": verdict,
    }


def _kpss_block(values, regression: str) -> dict:
    """Run KPSS and package the result."""
    import warnings

    from statsmodels.tsa.stattools import KPSSResult, kpss

    kpss_reg: Literal["c", "ct"] = "c" if regression not in {"c", "ct"} else regression
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = cast(
            KPSSResult,
            kpss(values, regression=kpss_reg, nlags="auto", result_object=True),
        )
    pvalue = result.pvalue
    verdict = "non_stationary" if pvalue < 0.05 else "stationary"
    crit_map: dict[str, float] = dict(result.critical_values)
    return {
        "kpss_statistic": float(result.statistic),
        "kpss_pvalue": float(pvalue),
        "kpss_critical_1pct": crit_map.get("1%", float("nan")),
        "kpss_critical_5pct": crit_map.get("5%", float("nan")),
        "kpss_critical_10pct": crit_map.get("10%", float("nan")),
        "kpss_verdict": verdict,
    }


def _overall_verdict(adf, kpss_, regression: str) -> str:
    """Combine ADF + KPSS verdicts into an overall verdict."""
    if adf is None and kpss_ is None:
        return "inconclusive"  # pragma: no cover
    if adf is not None and kpss_ is None:
        return "stationary" if adf == "stationary" else "non_stationary"
    if kpss_ is not None and adf is None:
        return "stationary" if kpss_ == "stationary" else "non_stationary"
    if adf == "stationary" and kpss_ == "stationary":
        return "trend_stationary" if regression in {"ct", "ctt"} else "stationary"
    if adf == "non_stationary" and kpss_ == "non_stationary":
        return "non_stationary"
    return "inconclusive"


@router.command(
    methods=["POST"],
    examples=[APIEx(parameters={"data": APIEx.mock_data("timeseries")})],
)
def stationarity(params: StationarityQueryParams) -> OBBject[list[StationarityData]]:
    """Test a series for stationarity using ADF, KPSS, or both with a combined verdict."""
    df = basemodel_to_df(params.data, index=params.index)
    values = get_target_column(df, params.target).astype(float).dropna().to_numpy()
    blank = {
        "adf_statistic": None,
        "adf_pvalue": None,
        "adf_critical_1pct": None,
        "adf_critical_5pct": None,
        "adf_critical_10pct": None,
        "adf_verdict": None,
        "kpss_statistic": None,
        "kpss_pvalue": None,
        "kpss_critical_1pct": None,
        "kpss_critical_5pct": None,
        "kpss_critical_10pct": None,
        "kpss_verdict": None,
    }
    payload = dict(blank)
    if params.test in {"adf", "both"}:
        payload.update(_adf_block(values, params.regression))
    else:
        payload["adf_verdict"] = "skipped"
    if params.test in {"kpss", "both"}:
        payload.update(_kpss_block(values, params.regression))
    else:
        payload["kpss_verdict"] = "skipped"
    adf_v = (
        payload["adf_verdict"]
        if payload["adf_verdict"] not in {None, "skipped"}
        else None
    )
    kpss_v = (
        payload["kpss_verdict"]
        if payload["kpss_verdict"] not in {None, "skipped"}
        else None
    )
    payload["overall_verdict"] = _overall_verdict(adf_v, kpss_v, params.regression)
    return OBBject(results=[StationarityData(**payload)])


class HurstQueryParams(QueryParams):
    """Query parameters for the Hurst-exponent endpoint.

    Parameters
    ----------
    data : list[Data]
        Input series.
    index : str, optional
        Index column name in ``data``, by default ``"date"``.
    target : str, optional
        Column to evaluate, by default ``"close"``.
    method : {"rs", "dfa"}, optional
        Estimation method: ``rs`` for classical Rescaled-Range analysis,
        ``dfa`` for Detrended Fluctuation Analysis, by default ``"rs"``.
    min_lag : PositiveInt, optional
        Smallest window length used in the log-log fit, by default 2.
    max_lag : PositiveInt, optional
        Largest window length used in the log-log fit (exclusive),
        by default 100.
    """

    __category__ = "stats"
    __output_columns__ = ("hurst_exponent", "interpretation", "confidence")

    data: list[Data] = Field(description="Input series.")
    index: str = Field(default="date", description="Index column name in ``data``.")
    target: str = Field(default="close", description="Column to evaluate.")
    method: Literal["rs", "dfa"] = Field(
        default="rs",
        description="``rs`` = Rescaled Range; ``dfa`` = Detrended Fluctuation.",
    )
    min_lag: PositiveInt = Field(default=2, description="Smallest window length.")
    max_lag: PositiveInt = Field(
        default=100, description="Largest window length (exclusive)."
    )


class HurstData(Data):
    """Single-row Hurst-exponent summary.

    Parameters
    ----------
    hurst_exponent : float, optional
        Estimated Hurst exponent in ``[0, 1]``. ``None`` when the fit could
        not be computed.
    interpretation : {"trending", "mean_reverting", "random_walk"}
        Qualitative classification: ``trending`` for H > 0.55,
        ``mean_reverting`` for H < 0.45, otherwise ``random_walk``.
    confidence : float, optional
        R-squared of the log-log fit used to estimate the exponent.
    """

    hurst_exponent: float | None = Field(
        description="Estimated Hurst exponent in ``[0, 1]``. ``None`` when the fit could not be computed."
    )
    interpretation: Literal["trending", "mean_reverting", "random_walk"] = Field(
        description="Qualitative classification: ``trending`` for H > 0.55, ``mean_reverting`` for H < 0.45, otherwise ``random_walk``."
    )
    confidence: float | None = Field(
        description="R-squared of the log-log fit used to estimate the exponent.",
    )


def _hurst_rs(values, min_lag: int, max_lag: int) -> tuple[float, float]:
    """Hurst via classical R/S analysis."""
    from numpy import array, log, mean, polyfit

    lags: list[int] = []
    rs_values: list[float] = []
    for lag in range(min_lag, max_lag):
        chunks = len(values) // lag
        if chunks < 1:
            continue
        rs_chunk: list[float] = []
        for i in range(chunks):
            block = values[i * lag : (i + 1) * lag]
            block_mean = block.mean()
            dev = block - block_mean
            cum = dev.cumsum()
            r = float(cum.max() - cum.min())
            s = float(block.std(ddof=0))
            if s > 0:
                rs_chunk.append(r / s)
        if rs_chunk:
            lags.append(lag)
            rs_values.append(float(mean(rs_chunk)))
    if len(lags) < 2:
        return float("nan"), float("nan")
    log_lags = log(array(lags, dtype="float64"))
    log_rs = log(array(rs_values, dtype="float64"))
    slope, intercept = polyfit(log_lags, log_rs, 1)
    fitted = slope * log_lags + intercept
    ss_res = float(((log_rs - fitted) ** 2).sum())
    ss_tot = float(((log_rs - log_rs.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return float(slope), float(r2)


def _hurst_dfa(values, min_lag: int, max_lag: int) -> tuple[float, float]:
    """Hurst via Detrended Fluctuation Analysis."""
    from numpy import arange, array, log, mean, polyfit, polyval, sqrt

    y = (values - values.mean()).cumsum()
    lags: list[int] = []
    fluct: list[float] = []
    for n_box in range(max(min_lag, 4), max_lag):
        n_segs = len(y) // n_box
        if n_segs < 2:
            continue
        rms: list[float] = []
        t = arange(n_box)
        for i in range(n_segs):
            seg = y[i * n_box : (i + 1) * n_box]
            coeffs = polyfit(t, seg, 1)
            trend = polyval(coeffs, t)
            rms.append(float(sqrt(mean((seg - trend) ** 2))))
        if rms:
            lags.append(n_box)
            fluct.append(float(mean(rms)))
    if len(lags) < 2:
        return float("nan"), float("nan")
    log_lags = log(array(lags, dtype="float64"))
    log_f = log(array(fluct, dtype="float64"))
    slope, intercept = polyfit(log_lags, log_f, 1)
    fitted = slope * log_lags + intercept
    ss_res = float(((log_f - fitted) ** 2).sum())
    ss_tot = float(((log_f - log_f.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return float(slope), float(r2)


def _interpret_hurst(h: float) -> str:
    """Classify a Hurst exponent value."""
    import math

    if h is None or math.isnan(h):
        return "random_walk"
    if h > 0.55:
        return "trending"
    if h < 0.45:
        return "mean_reverting"
    return "random_walk"


@router.command(
    methods=["POST"],
    examples=[APIEx(parameters={"data": APIEx.mock_data("timeseries")})],
)
def hurst(params: HurstQueryParams) -> OBBject[list[HurstData]]:
    """Estimate the Hurst exponent via Rescaled-Range analysis or DFA."""
    if params.max_lag <= params.min_lag:
        raise ValueError("max_lag must be greater than min_lag.")
    df = basemodel_to_df(params.data, index=params.index)
    values = get_target_column(df, params.target).astype(float).dropna().to_numpy()
    if params.method == "rs":
        h, r2 = _hurst_rs(values, params.min_lag, params.max_lag)
    else:
        h, r2 = _hurst_dfa(values, params.min_lag, params.max_lag)
    import math

    h_out = None if math.isnan(h) else float(h)
    r2_out = None if math.isnan(r2) else float(r2)
    return OBBject(
        results=[
            HurstData(
                hurst_exponent=h_out,
                interpretation=_interpret_hurst(h),  # ty: ignore[invalid-argument-type]
                confidence=r2_out,
            )
        ]
    )


class AutocorrelationQueryParams(QueryParams):
    """Query parameters for the autocorrelation endpoint.

    Parameters
    ----------
    data : list[Data]
        Input series.
    index : str, optional
        Index column name in ``data``, by default ``"date"``.
    target : str, optional
        Column to evaluate, by default ``"close"``.
    use_returns : bool, optional
        When ``True``, percent-change the series before computing ACF/PACF -
        the standard choice for prices since raw prices are typically
        non-stationary, by default ``True``.
    max_lag : PositiveInt, optional
        Largest lag to compute, by default 40.
    method : {"acf", "pacf", "both"}, optional
        Which functions to compute, by default ``"both"``.
    """

    __category__ = "stats"
    __output_columns__ = (
        "lag",
        "acf",
        "pacf",
        "acf_confidence_lower",
        "acf_confidence_upper",
        "significant",
    )

    data: list[Data] = Field(description="Input series.")
    index: str = Field(default="date", description="Index column name in ``data``.")
    target: str = Field(default="close", description="Column to evaluate.")
    use_returns: bool = Field(
        default=True, description="Difference and percent-change before computing."
    )
    max_lag: PositiveInt = Field(default=40, description="Largest lag to compute.")
    method: Literal["acf", "pacf", "both"] = Field(
        default="both", description="Which functions to compute."
    )


class AutocorrelationData(Data):
    """One row per lag of the autocorrelation analysis.

    Parameters
    ----------
    lag : int
        Lag in bars (0 is the series with itself, by definition 1.0 for ACF).
    acf : float, optional
        Sample autocorrelation at this lag, or ``None`` when ACF was skipped.
    pacf : float, optional
        Sample partial autocorrelation at this lag, or ``None`` when PACF
        was skipped.
    acf_confidence_lower : float, optional
        Lower bound of the 95% confidence band for the ACF estimate.
    acf_confidence_upper : float, optional
        Upper bound of the 95% confidence band for the ACF estimate.
    significant : bool
        ``True`` when the ACF estimate at this lag (other than lag 0) lies
        outside the 95% confidence band.
    """

    lag: int = Field(
        description="Lag in bars (0 is the series with itself, by definition 1.0 for ACF)."
    )
    acf: float | None = Field(
        description="Sample autocorrelation at this lag, or ``None`` when ACF was skipped."
    )
    pacf: float | None = Field(
        description="Sample partial autocorrelation at this lag, or ``None`` when PACF was skipped."
    )
    acf_confidence_lower: float | None = Field(
        description="Lower bound of the 95% confidence band for the ACF estimate."
    )
    acf_confidence_upper: float | None = Field(
        description="Upper bound of the 95% confidence band for the ACF estimate."
    )
    significant: bool = Field(
        description="``True`` when the ACF estimate at this lag (other than lag 0) lies outside the 95% confidence band."
    )


@router.command(
    methods=["POST"],
    examples=[APIEx(parameters={"data": APIEx.mock_data("timeseries")})],
)
def autocorrelation(
    params: AutocorrelationQueryParams,
) -> OBBject[list[AutocorrelationData]]:
    """Compute autocorrelation (ACF) and partial autocorrelation (PACF) with bands."""
    from statsmodels.tsa.stattools import (
        PacfResult,
        acf as _acf,
        pacf as _pacf,
    )

    df = basemodel_to_df(params.data, index=params.index)
    series = get_target_column(df, params.target).astype(float)
    series = series.pct_change().dropna() if params.use_returns else series.dropna()
    if len(series) <= params.max_lag + 1:
        raise ValueError("Series too short for the requested max_lag.")
    acf_vals = None
    acf_lower = None
    acf_upper = None
    if params.method in {"acf", "both"}:
        acf_result = _acf(
            series.to_numpy(), nlags=params.max_lag, alpha=0.05, result_object=True
        )
        acf_vals, conf = acf_result.acf, acf_result.confint
        acf_lower = conf[:, 0] - acf_vals
        acf_upper = conf[:, 1] - acf_vals
    pacf_vals = None
    if params.method in {"pacf", "both"}:
        pacf_vals = cast(
            PacfResult,
            _pacf(series.to_numpy(), nlags=params.max_lag, result_object=True),
        ).pacf
    out: list[AutocorrelationData] = []
    for lag in range(params.max_lag + 1):
        acf_v = float(acf_vals[lag]) if acf_vals is not None else None
        pacf_v = float(pacf_vals[lag]) if pacf_vals is not None else None
        lower = float(acf_lower[lag]) if acf_lower is not None else None
        upper = float(acf_upper[lag]) if acf_upper is not None else None
        if acf_v is not None and lower is not None and upper is not None:
            significant = bool(acf_v < lower or acf_v > upper) and lag != 0
        else:
            significant = False
        out.append(
            AutocorrelationData(
                lag=lag,
                acf=acf_v,
                pacf=pacf_v,
                acf_confidence_lower=lower,
                acf_confidence_upper=upper,
                significant=significant,
            )
        )
    return OBBject(results=out)


__all__ = [
    "AutocorrelationData",
    "AutocorrelationQueryParams",
    "ClenowData",
    "ClenowQueryParams",
    "DrawdownData",
    "DrawdownQueryParams",
    "Frequency",
    "HurstData",
    "HurstQueryParams",
    "ReturnsStatsData",
    "ReturnsStatsQueryParams",
    "StationarityData",
    "StationarityQueryParams",
    "autocorrelation",
    "clenow",
    "drawdown",
    "hurst",
    "returns_stats",
    "router",
    "stationarity",
]
