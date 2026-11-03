"""Nasdaq Balance Sheet Model."""

from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.balance_sheet import (
    BalanceSheetData,
    BalanceSheetQueryParams,
)
from openbb_core.provider.utils.descriptions import DATA_DESCRIPTIONS
from pydantic import Field

from openbb_nasdaq.utils.constants import SYMBOL_CHOICES_ENDPOINT


class NasdaqBalanceSheetQueryParams(BalanceSheetQueryParams):
    """Nasdaq Balance Sheet Query.

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


class NasdaqBalanceSheetData(BalanceSheetData):
    """Nasdaq Balance Sheet Data."""

    symbol: str | None = Field(
        default=None, description=DATA_DESCRIPTIONS.get("symbol", "")
    )
    cash_and_cash_equivalents: float | None = Field(
        default=None,
        description="Cash and Cash Equivalents.",
    )
    short_term_investments: float | None = Field(
        default=None,
        description="Short-Term Investments.",
    )
    net_receivables: float | None = Field(
        default=None,
        description="Net Receivables.",
    )
    inventory: float | None = Field(
        default=None,
        description="Inventory.",
    )
    other_current_assets: float | None = Field(
        default=None,
        description="Other Current Assets.",
    )
    total_current_assets: float | None = Field(
        default=None,
        description="Total Current Assets.",
    )
    long_term_investments: float | None = Field(
        default=None,
        description="Long-Term Investments.",
    )
    property_plant_equipment_net: float | None = Field(
        default=None,
        description="Fixed Assets.",
    )
    goodwill: float | None = Field(
        default=None,
        description="Goodwill.",
    )
    intangible_assets: float | None = Field(
        default=None,
        description="Intangible Assets.",
    )
    other_non_current_assets: float | None = Field(
        default=None,
        description="Other Assets.",
    )
    deferred_asset_charges: float | None = Field(
        default=None,
        description="Deferred Asset Charges.",
    )
    total_assets: float | None = Field(
        default=None,
        description="Total Assets.",
    )
    accounts_payable: float | None = Field(
        default=None,
        description="Accounts Payable.",
    )
    short_term_debt: float | None = Field(
        default=None,
        description="Short-Term Debt / Current Portion of Long-Term Debt.",
    )
    other_current_liabilities: float | None = Field(
        default=None,
        description="Other Current Liabilities.",
    )
    total_current_liabilities: float | None = Field(
        default=None,
        description="Total Current Liabilities.",
    )
    long_term_debt: float | None = Field(
        default=None,
        description="Long-Term Debt.",
    )
    other_non_current_liabilities: float | None = Field(
        default=None,
        description="Other Liabilities.",
    )
    deferred_liability_charges: float | None = Field(
        default=None,
        description="Deferred Liability Charges.",
    )
    misc_stocks: float | None = Field(
        default=None,
        description="Misc. Stocks.",
    )
    minority_interest: float | None = Field(
        default=None,
        description="Minority Interest.",
    )
    total_liabilities: float | None = Field(
        default=None,
        description="Total Liabilities.",
    )
    common_stock: float | None = Field(
        default=None,
        description="Common Stocks.",
    )
    additional_paid_in_capital: float | None = Field(
        default=None,
        description="Capital Surplus.",
    )
    retained_earnings: float | None = Field(
        default=None,
        description="Retained Earnings.",
    )
    treasury_stock: float | None = Field(
        default=None,
        description="Treasury Stock.",
    )
    other_shareholders_equity: float | None = Field(
        default=None,
        description="Other Equity.",
    )
    total_shareholders_equity: float | None = Field(
        default=None,
        description="Total Equity.",
    )
    total_liabilities_and_shareholders_equity: float | None = Field(
        default=None,
        description="Total Liabilities & Equity.",
    )


class NasdaqBalanceSheetFetcher(
    Fetcher[
        NasdaqBalanceSheetQueryParams,
        list[NasdaqBalanceSheetData],
    ]
):
    """Transform the query, extract and transform the data from the Nasdaq endpoints."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> NasdaqBalanceSheetQueryParams:
        """Transform the query."""
        return NasdaqBalanceSheetQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: NasdaqBalanceSheetQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Return the raw data from the Nasdaq endpoint."""
        from openbb_nasdaq.utils.financials import get_financials

        return await get_financials(query.symbol, query.period)

    @staticmethod
    def transform_data(
        query: NasdaqBalanceSheetQueryParams, data: dict, **kwargs: Any
    ) -> list[NasdaqBalanceSheetData]:
        """Transform the data to the standard format.

        Raises
        ------
        EmptyDataError
            If Nasdaq publishes no balance sheet for the symbol.
        """
        from openbb_core.provider.utils.errors import EmptyDataError

        from openbb_nasdaq.utils.financials import BALANCE_SHEET_MAP, parse_statement

        records = parse_statement(
            data, "balance", BALANCE_SHEET_MAP, query.symbol, query.period
        )

        if getattr(query, "as_of_date", None) is not None:
            records = [r for r in records if r["period_ending"] <= query.as_of_date]

        if not records:
            raise EmptyDataError(f"No balance sheet was found for {query.symbol}.")

        return [
            NasdaqBalanceSheetData.model_validate(r) for r in records[: query.limit]
        ]
