"""Nasdaq Financial Ratios Model."""

from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.financial_ratios import (
    FinancialRatiosData,
    FinancialRatiosQueryParams,
)
from pydantic import Field

from openbb_nasdaq.utils.constants import SYMBOL_CHOICES_ENDPOINT


class NasdaqFinancialRatiosQueryParams(FinancialRatiosQueryParams):
    """Nasdaq Financial Ratios Query.

    Source: https://www.nasdaq.com/market-activity/stocks
    """

    __json_schema_extra__ = {
        "symbol": {
            "x-widget_config": {
                "type": "endpoint",
                "optionsEndpoint": SYMBOL_CHOICES_ENDPOINT,
                "style": {"popupWidth": 850},
            },
        },
        "period": {"choices": ["annual", "quarter"]},
    }

    period: Literal["annual", "quarter"] = Field(
        default="annual",
        description="The reporting period. Nasdaq publishes the last four"
        + " periods of each statement.",
    )


class NasdaqFinancialRatiosData(FinancialRatiosData):
    """Nasdaq Financial Ratios Data."""

    current_ratio: float | None = Field(
        default=None,
        description="Current Ratio.",
    )
    quick_ratio: float | None = Field(
        default=None,
        description="Quick Ratio.",
    )
    cash_ratio: float | None = Field(
        default=None,
        description="Cash Ratio.",
    )
    gross_profit_margin: float | None = Field(
        default=None,
        description="Gross Margin.",
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-frontend_multiply": 100,
        },
    )
    operating_profit_margin: float | None = Field(
        default=None,
        description="Operating Margin.",
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-frontend_multiply": 100,
        },
    )
    pretax_profit_margin: float | None = Field(
        default=None,
        description="Pre-Tax Margin.",
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-frontend_multiply": 100,
        },
    )
    net_profit_margin: float | None = Field(
        default=None,
        description="Profit Margin.",
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-frontend_multiply": 100,
        },
    )
    pretax_return_on_equity: float | None = Field(
        default=None,
        description="Pre-Tax ROE.",
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-frontend_multiply": 100,
        },
    )
    return_on_equity: float | None = Field(
        default=None,
        description="After Tax ROE.",
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-frontend_multiply": 100,
        },
    )


class NasdaqFinancialRatiosFetcher(
    Fetcher[
        NasdaqFinancialRatiosQueryParams,
        list[NasdaqFinancialRatiosData],
    ]
):
    """Transform the query, extract and transform the data from the Nasdaq endpoints."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> NasdaqFinancialRatiosQueryParams:
        """Transform the query."""
        return NasdaqFinancialRatiosQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: NasdaqFinancialRatiosQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Return the raw data from the Nasdaq endpoint."""
        from openbb_nasdaq.utils.financials import get_financials

        return await get_financials(query.symbol, query.period)

    @staticmethod
    def transform_data(
        query: NasdaqFinancialRatiosQueryParams, data: dict, **kwargs: Any
    ) -> list[NasdaqFinancialRatiosData]:
        """Transform the data to the standard format.

        Raises
        ------
        EmptyDataError
            If Nasdaq publishes no financial ratios for the symbol.
        """
        from openbb_core.provider.utils.errors import EmptyDataError

        from openbb_nasdaq.utils.financials import FINANCIAL_RATIOS_MAP, parse_statement

        records = parse_statement(
            data, "ratios", FINANCIAL_RATIOS_MAP, query.symbol, query.period
        )

        if getattr(query, "as_of_date", None) is not None:
            records = [r for r in records if r["period_ending"] <= query.as_of_date]

        if not records:
            raise EmptyDataError(f"No financial ratios was found for {query.symbol}.")

        return [
            NasdaqFinancialRatiosData.model_validate(r) for r in records[: query.limit]
        ]
