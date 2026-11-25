"""Quantitative variance-share decomposition commands."""

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

router = Router(prefix="", description="Variance-share decomposition commands.")

_RESIDUAL_LABEL = "Residual"


class RiskDecompositionQueryParams(QueryParams):
    """Query parameters for the risk_decomposition endpoint."""

    __category__ = "quantitative"
    __output_columns__ = ("period", "factor", "contribution", "share")

    data: list[Data] = Field(
        description="Target periodic return series (index column plus the target column)."
    )
    factors_data: list[Data] = Field(
        description="Factor return matrix (index column plus one column per factor),"
        " in the same units as the target."
    )
    target: str = Field(
        default="close",
        description="Name of the return column in `data` to decompose against the factors.",
    )
    index: str = Field(
        default="date",
        description="Name of the index column shared by `data` and `factors_data`.",
    )
    risk_free_column: str | None = Field(
        default=None,
        description="Optional name of the risk-free rate column in `factors_data`."
        " When provided, the target is converted to excess returns before"
        " decomposition and the column is dropped from the factor set.",
    )
    periods: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_PERIODS),
        description="Named look-back periods to decompose over, anchored to the"
        " latest factor observation.",
    )


class RiskDecompositionData(Data):
    """One variance-share observation for a given look-back period."""

    period: str = Field(description="Look-back period the decomposition was run over.")
    factor: str = Field(
        description="Factor name, or 'Residual' for the idiosyncratic component."
    )
    contribution: float = Field(
        description="Covariance-based contribution to Var(target): for a factor,"
        " beta_i * Cov(factor_i, target); for 'Residual', Var(target) * (1 - R^2)."
    )
    share: float = Field(
        description="Fraction of Var(target) attributed to this factor (or to the"
        " residual). Factor shares sum to R^2; the residual share equals 1 - R^2."
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
def risk_decomposition(
    params: RiskDecompositionQueryParams,
) -> OBBject[list[RiskDecompositionData]]:
    """Decompose Var(target) into per-factor contributions plus residual variance.

    For each look-back period, runs OLS of the target on the factor matrix and
    splits the target's variance via the additive identity
    `Var(target) = sum_i beta_i * Cov(factor_i, target) + Var(residual)`.
    Returned shares sum to 1 per period: factor shares sum to R^2 and the residual
    row holds `1 - R^2`. Handles correlated factors cleanly because each share is
    measured by the covariance with the target rather than by the factor's
    standalone variance.
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
    out: list[RiskDecompositionData] = []

    for period in params.periods:
        start = period_start(max_date, period)
        window = aligned if start is None else aligned[aligned.index >= start]
        if len(window) <= len(factor_cols) + 1:
            continue

        y = window[params.target]
        var_y = float(y.var())
        if var_y == 0.0:
            continue

        x = sm.add_constant(window[factor_cols])
        model = sm.OLS(y, x).fit()
        residual_var = float(model.resid.var())

        for name in factor_cols:
            beta = float(model.params[name])
            cov = float(window[name].cov(y))
            contribution = beta * cov
            out.append(
                RiskDecompositionData(
                    period=period,
                    factor=name,
                    contribution=contribution,
                    share=contribution / var_y,
                )
            )

        out.append(
            RiskDecompositionData(
                period=period,
                factor=_RESIDUAL_LABEL,
                contribution=residual_var,
                share=residual_var / var_y,
            )
        )

    return OBBject(results=out)
