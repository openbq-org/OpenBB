"""Nasdaq Income Statement Model."""

from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.income_statement import (
    IncomeStatementData,
    IncomeStatementQueryParams,
)
from openbb_core.provider.utils.descriptions import DATA_DESCRIPTIONS
from pydantic import Field

from openbb_nasdaq.utils.constants import SYMBOL_CHOICES_ENDPOINT


class NasdaqIncomeStatementQueryParams(IncomeStatementQueryParams):
    """Nasdaq Income Statement Query.

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


class NasdaqIncomeStatementData(IncomeStatementData):
    """Nasdaq Income Statement Data."""

    symbol: str | None = Field(
        default=None, description=DATA_DESCRIPTIONS.get("symbol", "")
    )
    revenue: float | None = Field(
        default=None,
        description="Total Revenue.",
    )
    cost_of_revenue: float | None = Field(
        default=None,
        description="Cost of Revenue.",
    )
    gross_profit: float | None = Field(
        default=None,
        description="Gross Profit.",
    )
    total_operating_expenses: float | None = Field(
        default=None,
        description="Operating Expenses.",
    )
    research_and_development_expense: float | None = Field(
        default=None,
        description="Research and Development.",
    )
    selling_general_and_administrative_expense: float | None = Field(
        default=None,
        description="Sales, General and Admin.",
    )
    non_recurring_items: float | None = Field(
        default=None,
        description="Non-Recurring Items.",
    )
    other_operating_expenses: float | None = Field(
        default=None,
        description="Other Operating Items.",
    )
    operating_income: float | None = Field(
        default=None,
        description="Operating Income.",
    )
    additional_income_expense_items: float | None = Field(
        default=None,
        description="Add'l income/expense items.",
    )
    ebit: float | None = Field(
        default=None,
        description="Earnings Before Interest and Tax.",
    )
    interest_expense: float | None = Field(
        default=None,
        description="Interest Expense.",
    )
    income_before_tax: float | None = Field(
        default=None,
        description="Earnings Before Tax.",
    )
    income_tax_expense: float | None = Field(
        default=None,
        description="Income Tax.",
    )
    minority_interest: float | None = Field(
        default=None,
        description="Minority Interest.",
    )
    equity_earnings: float | None = Field(
        default=None,
        description="Equity Earnings/Loss Unconsolidated Subsidiary.",
    )
    net_income_from_continuing_operations: float | None = Field(
        default=None,
        description="Net Income-Cont. Operations.",
    )
    consolidated_net_income: float | None = Field(
        default=None,
        description="Net Income.",
    )
    net_income: float | None = Field(
        default=None,
        description="Net Income Applicable to Common Shareholders.",
    )


class NasdaqIncomeStatementFetcher(
    Fetcher[
        NasdaqIncomeStatementQueryParams,
        list[NasdaqIncomeStatementData],
    ]
):
    """Transform the query, extract and transform the data from the Nasdaq endpoints."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> NasdaqIncomeStatementQueryParams:
        """Transform the query."""
        return NasdaqIncomeStatementQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: NasdaqIncomeStatementQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Return the raw data from the Nasdaq endpoint."""
        from openbb_nasdaq.utils.financials import get_financials

        return await get_financials(query.symbol, query.period)

    @staticmethod
    def transform_data(
        query: NasdaqIncomeStatementQueryParams, data: dict, **kwargs: Any
    ) -> list[NasdaqIncomeStatementData]:
        """Transform the data to the standard format.

        Raises
        ------
        EmptyDataError
            If Nasdaq publishes no income statement for the symbol.
        """
        from openbb_core.provider.utils.errors import EmptyDataError

        from openbb_nasdaq.utils.financials import INCOME_STATEMENT_MAP, parse_statement

        records = parse_statement(
            data, "income", INCOME_STATEMENT_MAP, query.symbol, query.period
        )

        if getattr(query, "as_of_date", None) is not None:
            records = [r for r in records if r["period_ending"] <= query.as_of_date]

        if not records:
            raise EmptyDataError(f"No income statement was found for {query.symbol}.")

        return [
            NasdaqIncomeStatementData.model_validate(r) for r in records[: query.limit]
        ]
