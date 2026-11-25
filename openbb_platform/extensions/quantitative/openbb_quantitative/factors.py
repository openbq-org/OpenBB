"""Quantitative factor-regression commands."""

from typing import TYPE_CHECKING, cast

from openbb_core.app.model.example import APIEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field

from openbb_quantitative._factor_helpers import (
    _DEFAULT_PERIODS,
    align_inputs,
    period_start,
)

if TYPE_CHECKING:
    from pandas import Timestamp

router = Router(prefix="", description="Quantitative factor-regression commands.")


class FactorRegressionQueryParams(QueryParams):
    """Query parameters for the factors endpoint."""

    __category__ = "quantitative"
    __output_columns__ = (
        "period",
        "factor",
        "coefficient",
        "p_value",
        "lower_ci",
        "upper_ci",
        "r_squared",
    )

    data: list[Data] = Field(
        description="Target periodic return series (index column plus the target column)."
    )
    factors_data: list[Data] = Field(
        description="Factor return matrix (index column plus one column per factor),"
        " in the same units as the target."
    )
    target: str = Field(
        default="close",
        description="Name of the return column in `data` to regress on the factor matrix.",
    )
    index: str = Field(
        default="date",
        description="Name of the index column shared by `data` and `factors_data`.",
    )
    risk_free_column: str | None = Field(
        default=None,
        description="Optional name of the risk-free rate column in `factors_data`."
        " When provided, the target is regressed in excess form (target minus the"
        " risk-free column) and the column itself is dropped from the regressors.",
    )
    periods: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_PERIODS),
        description="Named look-back periods to regress over, anchored to the latest"
        " factor observation. Supported values: '1 Month', '3 Month', 'YTD',"
        " '1 Year', '3 Year', 'Max'.",
    )


class FactorRegressionData(Data):
    """One factor coefficient observation for a given look-back period."""

    period: str = Field(description="Look-back period the regression was run over.")
    factor: str = Field(
        description="Factor name (or 'const' for the regression intercept)."
    )
    coefficient: float = Field(description="OLS coefficient estimate for the factor.")
    p_value: float = Field(description="Two-sided p-value of the coefficient estimate.")
    lower_ci: float = Field(description="Lower bound of the 95% confidence interval.")
    upper_ci: float = Field(description="Upper bound of the 95% confidence interval.")
    r_squared: float = Field(
        description="R-squared of the regression for this period (repeated per row)."
    )


@router.command(
    methods=["POST"],
    examples=[
        APIEx(
            parameters={
                "target": "close",
                "data": APIEx.mock_data("timeseries", 800),
                "factors_data": APIEx.mock_data("timeseries", 800),
            }
        )
    ],
)
def factors(
    params: FactorRegressionQueryParams,
) -> OBBject[list[FactorRegressionData]]:
    """Regress a target return series on a factor matrix across named periods.

    Aligns `data` and `factors_data` on their shared index, optionally subtracts a
    risk-free column from the target, then runs an OLS regression of the target on
    the factor columns (plus an intercept) for each named look-back period. Returns
    one row per (`period`, `factor`) with the OLS coefficient, p-value, 95%
    confidence interval, and the period's R-squared.

    Designed to be paired with any factor provider; for Fama-French data, pipe the
    `openbb-famafrench` provider's output into `factors_data`.
    """
    import statsmodels.api as sm

    factor_matrix, target_series, factor_cols = align_inputs(
        params.data,
        params.factors_data,
        target=params.target,
        index=params.index,
        risk_free_column=params.risk_free_column,
    )
    aligned = factor_matrix.assign(**{params.target: target_series})
    max_date = cast("Timestamp", aligned.index.max())
    out: list[FactorRegressionData] = []

    for period in params.periods:
        start = period_start(max_date, period)
        window = aligned if start is None else aligned[aligned.index >= start]
        if len(window) <= len(factor_cols) + 1:
            continue

        x = sm.add_constant(window[factor_cols])
        model = sm.OLS(window[params.target], x).fit()
        conf = model.conf_int()
        r_squared = float(model.rsquared)

        for name in model.params.index:
            out.append(
                FactorRegressionData(
                    period=period,
                    factor=str(name),
                    coefficient=float(model.params[name]),
                    p_value=float(model.pvalues[name]),
                    lower_ci=float(conf.loc[name, 0]),
                    upper_ci=float(conf.loc[name, 1]),
                    r_squared=r_squared,
                )
            )

    return OBBject(results=out)
