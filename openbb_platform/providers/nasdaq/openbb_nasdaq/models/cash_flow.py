"""Nasdaq Cash Flow Statement Model."""

from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.cash_flow import (
    CashFlowStatementData,
    CashFlowStatementQueryParams,
)
from openbb_core.provider.utils.descriptions import DATA_DESCRIPTIONS
from pydantic import Field

from openbb_nasdaq.utils.constants import SYMBOL_CHOICES_ENDPOINT


class NasdaqCashFlowStatementQueryParams(CashFlowStatementQueryParams):
    """Nasdaq Cash Flow Statement Query.

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


class NasdaqCashFlowStatementData(CashFlowStatementData):
    """Nasdaq Cash Flow Statement Data."""

    symbol: str | None = Field(
        default=None, description=DATA_DESCRIPTIONS.get("symbol", "")
    )
    net_income: float | None = Field(
        default=None,
        description="Net Income.",
    )
    depreciation_and_amortization: float | None = Field(
        default=None,
        description="Depreciation.",
    )
    other_non_cash_items: float | None = Field(
        default=None,
        description="Net Income Adjustments.",
    )
    change_in_receivables: float | None = Field(
        default=None,
        description="Accounts Receivable.",
    )
    change_in_inventory: float | None = Field(
        default=None,
        description="Changes in Inventories.",
    )
    other_operating_activities: float | None = Field(
        default=None,
        description="Other Operating Activities.",
    )
    change_in_payables: float | None = Field(
        default=None,
        description="Liabilities.",
    )
    net_cash_flow_from_operating_activities: float | None = Field(
        default=None,
        description="Net Cash Flow-Operating.",
    )
    capital_expenditure: float | None = Field(
        default=None,
        description="Capital Expenditures.",
    )
    purchase_of_investments: float | None = Field(
        default=None,
        description="Investments.",
    )
    other_investing_activities: float | None = Field(
        default=None,
        description="Other Investing Activities.",
    )
    net_cash_flow_from_investing_activities: float | None = Field(
        default=None,
        description="Net Cash Flows-Investing.",
    )
    net_stock_issuance: float | None = Field(
        default=None,
        description="Sale and Purchase of Stock.",
    )
    net_debt_issuance: float | None = Field(
        default=None,
        description="Net Borrowings.",
    )
    other_financing_activities: float | None = Field(
        default=None,
        description="Other Financing Activities.",
    )
    net_cash_flow_from_financing_activities: float | None = Field(
        default=None,
        description="Net Cash Flows-Financing.",
    )
    effect_of_exchange_rate_changes_on_cash: float | None = Field(
        default=None,
        description="Effect of Exchange Rate.",
    )
    net_change_in_cash_and_equivalents: float | None = Field(
        default=None,
        description="Net Cash Flow.",
    )


class NasdaqCashFlowStatementFetcher(
    Fetcher[
        NasdaqCashFlowStatementQueryParams,
        list[NasdaqCashFlowStatementData],
    ]
):
    """Transform the query, extract and transform the data from the Nasdaq endpoints."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> NasdaqCashFlowStatementQueryParams:
        """Transform the query."""
        return NasdaqCashFlowStatementQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: NasdaqCashFlowStatementQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Return the raw data from the Nasdaq endpoint."""
        from openbb_nasdaq.utils.financials import get_financials

        return await get_financials(query.symbol, query.period)

    @staticmethod
    def transform_data(
        query: NasdaqCashFlowStatementQueryParams, data: dict, **kwargs: Any
    ) -> list[NasdaqCashFlowStatementData]:
        """Transform the data to the standard format.

        Raises
        ------
        EmptyDataError
            If Nasdaq publishes no cash flow statement for the symbol.
        """
        from openbb_core.provider.utils.errors import EmptyDataError

        from openbb_nasdaq.utils.financials import CASH_FLOW_MAP, parse_statement

        records = parse_statement(
            data, "cash", CASH_FLOW_MAP, query.symbol, query.period
        )

        if getattr(query, "as_of_date", None) is not None:
            records = [r for r in records if r["period_ending"] <= query.as_of_date]

        if not records:
            raise EmptyDataError(
                f"No cash flow statement was found for {query.symbol}."
            )

        return [
            NasdaqCashFlowStatementData.model_validate(r)
            for r in records[: query.limit]
        ]
