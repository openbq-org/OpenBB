"""Quantitative return-attribution commands."""

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

router = Router(prefix="", description="Return-attribution commands.")

_ALPHA_LABEL = "Alpha"
_RESIDUAL_LABEL = "Residual"


class ReturnAttributionQueryParams(QueryParams):
    """Query parameters for the attribution endpoint."""

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
        description="Name of the return column in `data` to attribute across the factors.",
    )
    index: str = Field(
        default="date",
        description="Name of the index column shared by `data` and `factors_data`.",
    )
    risk_free_column: str | None = Field(
        default=None,
        description="Optional name of the risk-free rate column in `factors_data`."
        " When provided, the target is converted to excess returns before"
        " attribution and the column is dropped from the factor set.",
    )
    periods: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_PERIODS),
        description="Named look-back periods to attribute over, anchored to the"
        " latest factor observation.",
    )


class ReturnAttributionData(Data):
    """One return-contribution observation for a given look-back period."""

    period: str = Field(description="Look-back period the attribution was run over.")
    factor: str = Field(
        description="Factor name, 'Alpha' for the intercept contribution, or"
        " 'Residual' for the unexplained residual."
    )
    contribution: float = Field(
        description="Component's contribution to the period's total target return:"
        " for a factor, beta_i * sum_t factor_i; for 'Alpha', alpha * n; for"
        " 'Residual', sum of regression residuals. The three sum to the period's"
        " total target return."
    )
    share: float = Field(
        description="Component's contribution divided by the total target return"
        " over the period. Shares sum to 1.0 unless the total return is zero."
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
def attribution(
    params: ReturnAttributionQueryParams,
) -> OBBject[list[ReturnAttributionData]]:
    """Decompose the target's total return into per-factor contributions plus alpha
    and residual.

    For each look-back period, runs OLS of the target on the factor matrix and
    splits the period's cumulative target return via the identity
    `sum_t y_t = alpha * n + sum_i beta_i * sum_t f_{i,t} + sum_t residual_t`.
    The three components are returned as rows: one per factor, one `Alpha`, and one
    `Residual`. Use with arithmetic (additive) returns; for geometric compounding,
    convert returns to log-returns before passing in.
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
    out: list[ReturnAttributionData] = []

    for period in params.periods:
        start = period_start(max_date, period)
        window = aligned if start is None else aligned[aligned.index >= start]
        if len(window) <= len(factor_cols) + 1:
            continue

        y = window[params.target]
        total_return = float(y.sum())
        x = sm.add_constant(window[factor_cols])
        model = sm.OLS(y, x).fit()
        n = len(window)

        alpha_contribution = float(model.params["const"]) * n
        residual_contribution = float(model.resid.sum())
        components: list[tuple[str, float]] = []
        for name in factor_cols:
            beta = float(model.params[name])
            factor_sum = float(window[name].sum())
            components.append((name, beta * factor_sum))
        components.append((_ALPHA_LABEL, alpha_contribution))
        components.append((_RESIDUAL_LABEL, residual_contribution))

        denom = total_return if total_return != 0.0 else float("nan")
        for name, contribution in components:
            out.append(
                ReturnAttributionData(
                    period=period,
                    factor=name,
                    contribution=contribution,
                    share=contribution / denom,
                )
            )

    return OBBject(results=out)
