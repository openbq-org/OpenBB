"""SEC Cash Flow Statement Model."""

from math import isnan
from typing import Any, Literal
from warnings import warn

from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.cash_flow import (
    CashFlowStatementData,
    CashFlowStatementQueryParams,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import ConfigDict, Field, model_serializer, model_validator


class SecCashFlowStatementQueryParams(CashFlowStatementQueryParams):
    """SEC CashFlowStatement Query.

    Source: https://www.sec.gov/edgar/sec-api-documentation
    """

    period: Literal["annual", "quarterly", "ttm"] = Field(
        default="annual",
        description=QUERY_DESCRIPTIONS.get("period", ""),
    )
    use_cache: bool = Field(
        default=True,
        description="Whether to use cache (4-hour memory) for the SEC request."
        " Defaults to True.",
    )
    include_preliminary: bool = Field(
        default=False,
        description="Whether to include preliminary data from 8-K filings"
        " for periods not yet reported on 10-Q/K.",
    )
    pit_mode: bool = Field(
        default=False,
        description="Point-in-time mode. When True, returns data as originally"
        " reported at the time of filing, without subsequent restatements or"
        " amendments. For annual data, uses the original 10-K values. For"
        " quarterly data, preserves 10-Q filing vintage instead of using"
        " restated comparatives from the 10-K.",
    )


class SecCashFlowStatementData(CashFlowStatementData):
    """SEC CashFlowStatement Data."""

    model_config = ConfigDict(
        allow_inf_nan=True,
        ser_json_inf_nan="null",
        json_schema_extra={
            "x-widget_config": {"$.data": {"table": {"enableFormulas": True}}}
        },
    )

    reported_currency: str | None = Field(
        default=None,
        description="The currency in which the cash flow statement is reported.",
    )
    net_income: float | None = Field(
        default=None,
        description="The consolidated profit or loss for the period, net of income taxes, including the portion "
        "attributable to the noncontrolling interest.",
    )
    net_income_discontinued: float | None = Field(
        default=None,
        description="Amount after tax of income (loss) from a discontinued operation including the portion attributable "
        "to the noncontrolling interest. Includes, but is not limited to, the income (loss) from operations during the "
        "phase-out period, gain (loss) on disposal, gain (loss) for reversal of write-down (write-down) to fair value, "
        "less cost to sell, and adjustments to a prior period gain (loss) on disposal.",
    )
    net_income_continuing: float | None = Field(
        default=None,
        description="Amount after tax of income (loss) from continuing operations including portion attributable to the "
        "noncontrolling interest.",
    )
    provision_for_loan_losses: float | None = Field(
        default=None,
        description="Amount of expense related to estimated loss from loan and lease transactions.",
    )
    depreciation_expense: float | None = Field(
        default=None,
        description="The current period expense charged against earnings on long-lived, physical assets not used in "
        "production, and which are not intended for resale, to allocate or recognize the cost of such assets over their "
        "useful lives; or to record the reduction in book value of an intangible asset over the benefit period of such "
        "asset; or to reflect consumption during the period of an asset that is not used in production.",
    )
    amortization_expense: float | None = Field(
        default=None,
        description="Amount of amortization expense for finite-lived intangible asset. Excludes goodwill and capitalized "
        "cost for software to be sold, leased, or marketed.",
    )
    depreciation_and_amortization: float | None = Field(
        default=None,
        description="The aggregate expense recognized in the current period that allocates the cost of tangible and "
        "intangible assets over their useful lives.",
    )
    stock_based_compensation: float | None = Field(
        default=None,
        description="Amount of noncash expense for share-based payment arrangement.",
    )
    deferred_income_tax: float | None = Field(
        default=None,
        description="Amount of deferred income tax expense (benefit) pertaining to income (loss) from continuing "
        "operations.",
    )
    gain_loss_on_investments: float | None = Field(
        default=None,
        description="Amount of realized and unrealized gain (loss) on investment.",
    )
    gain_loss_on_sale_of_assets: float | None = Field(
        default=None,
        description="Amount of gain (loss) on sale or disposal of property, plant and equipment assets, including oil "
        "and gas property and timber property.",
    )
    income_loss_from_equity_method_investments: float | None = Field(
        default=None,
        description="Amount of income (loss) for proportionate share of equity method investee's income (loss).",
    )
    asset_impairment_charges: float | None = Field(
        default=None,
        description="Amount of impairment loss for asset. Includes, but is not limited to, tangible and intangible "
        "assets and goodwill.",
    )
    noncash_adjustments_to_net_income: float | None = Field(
        default=None,
        description="Amount of income (expense) included in net income that results in no cash inflow (outflow), "
        "classified as other.",
    )
    other_operating_activities: float | None = Field(
        default=None,
        description="Amount of cash inflow (outflow) from operating activity, classified as other, in reconciling net "
        "income to reflect cash provided by (used in) operating activity when indirect cash flow method is applied.",
    )
    change_in_insurance_reserves: float | None = Field(
        default=None,
        description="The increase (decrease) in health care insurance liability balances during the period.",
    )
    change_in_accounts_receivable: float | None = Field(
        default=None,
        description="The increase (decrease) during the reporting period in amount due within one year (or one business "
        "cycle) from customers for the credit sale of goods and services.",
    )
    change_in_nontrade_receivables: float | None = Field(
        default=None,
        description="Amount of increase (decrease) in receivables classified as other.",
    )
    change_in_inventories: float | None = Field(
        default=None,
        description="The increase (decrease) during the reporting period in the aggregate value of all inventory held by "
        "the reporting entity, associated with underlying transactions that are classified as operating activities.",
    )
    change_in_accounts_payable: float | None = Field(
        default=None,
        description="The increase (decrease) during the reporting period in the aggregate amount of liabilities incurred "
        "(and for which invoices have typically been received) and payable to vendors for goods and services received "
        "that are used in an entity's business.",
    )
    change_in_other_operating_assets_and_liabilities: float | None = Field(
        default=None,
        description="Amount of increase (decrease) in operating assets classified as other.",
    )
    increase_decrease_in_operating_capital: float | None = Field(
        default=None,
        description="Amount of increase (decrease) in asset and (increase) decrease in liability, used in operating "
        "activity in reconciling net income to reflect cash provided by (used in) operating activity when indirect cash "
        "flow method is applied.",
    )
    net_cash_from_continuing_operating_activities: float | None = Field(
        default=None,
        description="Amount of cash inflow (outflow) from operating activity, including, but not limited to, "
        "discontinued operation. Operating activity includes, but is not limited to, transaction, adjustment, and change "
        "in value not defined as investing or financing activity.",
    )
    net_cash_from_discontinued_operating_activities: float | None = Field(
        default=None,
        description="Amount of cash inflow (outflow) from operating activity attributable to discontinued operation. "
        "Operating activity includes, but is not limited to, transaction, adjustment, and change in value not defined as "
        "investing or financing activity.",
    )
    net_cash_from_operating_activities: float | None = Field(
        default=None,
        description="Amount of cash inflow (outflow) from operating activity, including, but not limited to, "
        "discontinued operation. Operating activity includes, but is not limited to, transaction, adjustment, and change "
        "in value not defined as investing or financing activity.",
    )
    purchase_of_plant_property_and_equipment: float | None = Field(
        default=None,
        description="The cash outflow associated with the acquisition of long-lived, physical assets that are used in "
        "the normal conduct of business to produce goods and services and not intended for resale; includes cash "
        "outflows to pay for construction of self-constructed assets.",
    )
    acquisitions: float | None = Field(
        default=None,
        description="The cash outflow associated with the acquisition of a business, net of the cash acquired from the "
        "purchase.",
    )
    purchase_of_investments: float | None = Field(
        default=None,
        description="Amount of cash outflow to acquire investment in debt security measured at fair value with change in "
        "fair value recognized in other comprehensive income (available-for-sale).",
    )
    purchase_of_held_to_maturity_investments: float | None = Field(
        default=None,
        description="Amount of cash outflow through purchase of long-term held-to-maturity securities.",
    )
    sale_of_plant_property_and_equipment: float | None = Field(
        default=None,
        description="The cash inflow from the sale of long-lived, physical assets that are used in the normal conduct of "
        "business to produce goods and services and not intended for resale.",
    )
    sale_of_productive_assets: float | None = Field(
        default=None,
        description="The cash inflow from the sale of property, plant and equipment (capital expenditures), software, "
        "and other intangible assets.",
    )
    divestitures: float | None = Field(
        default=None,
        description="The cash inflow associated with the amount received from the sale of a portion of the company's "
        "business, for example a segment, division, branch or other business, during the period.",
    )
    sale_of_investments: float | None = Field(
        default=None,
        description="Amount of cash inflow from sale of investment in debt security measured at fair value with change "
        "in fair value recognized in other comprehensive income (available-for-sale).",
    )
    maturity_of_investments: float | None = Field(
        default=None,
        description="Amount of cash inflow from maturity, prepayment and call of investment in debt security measured at "
        "fair value with change in fair value recognized in other comprehensive income (available-for-sale).",
    )
    net_increase_in_fed_funds_sold: float | None = Field(
        default=None,
        description="The net cash inflow or outflow from the fund lent to other financial institution arising from the "
        "excess in reserve deposited at Federal Reserve Bank to meet legal requirement. This borrowing is usually "
        "contracted on an overnight basis at an agreed rate of interest.",
    )
    loans_held_for_sale_net: float | None = Field(
        default=None,
        description="The net cash outflow or inflow for the increase (decrease) in the beginning and end of period of "
        "loan and lease balances which are not originated or purchased specifically for resale. Includes cash payments "
        "and proceeds associated with (a) loans held-for-investment, (b) leases held-for-investment, and (c) both.",
    )
    other_investing_activities_net: float | None = Field(
        default=None,
        description="Amount of cash (inflow) outflow from investing activity, classified as other.",
    )
    net_cash_from_continuing_investing_activities: float | None = Field(
        default=None,
        description="Amount of cash inflow (outflow) from investing activity, including, but not limited to, "
        "discontinued operation. Investing activity includes, but is not limited to, making and collecting loan, "
        "acquiring and disposing of debt and equity instruments, property, plant, and equipment, and other productive "
        "assets.",
    )
    net_cash_from_discontinued_investing_activities: float | None = Field(
        default=None,
        description="Amount of cash inflow (outflow) from investing activity attributable to discontinued operation. "
        "Investing activity includes, but is not limited to, making and collecting loan, acquiring and disposing of debt "
        "and equity instruments, property, plant, and equipment, and other productive assets.",
    )
    net_cash_from_investing_activities: float | None = Field(
        default=None,
        description="Amount of cash inflow (outflow) from investing activity, including, but not limited to, "
        "discontinued operation. Investing activity includes, but is not limited to, making and collecting loan, "
        "acquiring and disposing of debt and equity instruments, property, plant, and equipment, and other productive "
        "assets.",
    )
    repayment_of_debt: float | None = Field(
        default=None,
        description="The cash outflow for debt initially having maturity due after one year or beyond the normal "
        "operating cycle, if longer.",
    )
    repurchase_of_preferred_equity: float | None = Field(
        default=None,
        description="The cash outflow to reacquire preferred stock during the period.",
    )
    repurchase_of_common_equity: float | None = Field(
        default=None,
        description="The cash outflow to reacquire common stock during the period.",
    )
    payment_of_dividends: float | None = Field(
        default=None,
        description="Cash outflow in the form of capital distributions and dividends to common shareholders, preferred "
        "shareholders and noncontrolling interests.",
    )
    issuance_of_debt: float | None = Field(
        default=None,
        description="The cash inflow from a debt initially having maturity due after one year or beyond the operating "
        "cycle, if longer.",
    )
    issuance_of_preferred_equity: float | None = Field(
        default=None,
        description="Proceeds from issuance of capital stock which provides for a specific dividend that is paid to the "
        "shareholders before any dividends to common stockholders and which takes precedence over common stockholders in "
        "the event of liquidation.",
    )
    issuance_of_common_equity: float | None = Field(
        default=None,
        description="The cash inflow from the additional capital contribution to the entity.",
    )
    net_change_in_deposits: float | None = Field(
        default=None,
        description="The net cash inflow or outflow for the increase (decrease) in the beginning and end of period "
        "deposits balances.",
    )
    short_term_debt_net: float | None = Field(
        default=None,
        description="The net cash inflow or outflow for borrowing having initial term of repayment within one year or "
        "the normal operating cycle, if longer.",
    )
    tax_withholding_share_based_compensation: float | None = Field(
        default=None,
        description="Amount of cash outflow to satisfy grantee's tax withholding obligation for award under share-based "
        "payment arrangement.",
    )
    other_financing_activities_net: float | None = Field(
        default=None,
        description="Amount of cash inflow (outflow) from financing activity, classified as other.",
    )
    net_cash_from_continuing_financing_activities: float | None = Field(
        default=None,
        description="Amount of cash inflow (outflow) from financing activity, including, but not limited to, "
        "discontinued operation. Financing activity includes, but is not limited to, obtaining resource from owner and "
        "providing return on, and return of, their investment; borrowing money and repaying amount borrowed, or settling "
        "obligation; and obtaining and paying for other resource obtained from creditor on long-term credit.",
    )
    net_cash_from_discontinued_financing_activities: float | None = Field(
        default=None,
        description="Amount of cash inflow (outflow) from financing activity attributable to discontinued operation. "
        "Financing activity includes, but is not limited to, obtaining resource from owner and providing return on, and "
        "return of, their investment; borrowing money and repaying amount borrowed, or settling obligation; and "
        "obtaining and paying for other resource obtained from creditor on long-term credit.",
    )
    net_cash_from_financing_activities: float | None = Field(
        default=None,
        description="Amount of cash inflow (outflow) from financing activity, including, but not limited to, "
        "discontinued operation. Financing activity includes, but is not limited to, obtaining resource from owner and "
        "providing return on, and return of, their investment; borrowing money and repaying amount borrowed, or settling "
        "obligation; and obtaining and paying for other resource obtained from creditor on long-term credit.",
    )
    effect_of_exchange_rate_changes: float | None = Field(
        default=None,
        description="The effect of exchange rate changes on cash balances held in foreign currencies.",
    )
    net_cash_from_discontinued_operations: float | None = Field(
        default=None,
        description="The net change in cash and cash equivalents resulting from the cash inflows and outflows of "
        "discontinued operations.",
    )
    other_net_changes_in_cash: float | None = Field(
        default=None,
        description="Amount of other net changes in cash and cash equivalents not separately disclosed in the statement "
        "of cash flows.",
    )
    net_change_in_cash: float | None = Field(
        default=None,
        description="The increase (decrease) during the reporting period in cash and cash equivalents. While for "
        "technical reasons this element has no balance attribute, the default assumption is a debit balance consistent "
        "with its label.",
    )
    cash_at_beginning_of_period: float | None = Field(
        default=None,
        description="Cash, cash equivalents, restricted cash, and restricted cash equivalents at the beginning of the "
        "reporting period. Derived from the previous period's ending balance.",
    )
    cash_at_end_of_period: float | None = Field(
        default=None,
        description="Cash, cash equivalents, restricted cash, and restricted cash equivalents at the end of the "
        "reporting period.",
    )
    cash_interest_paid: float | None = Field(
        default=None,
        description="Amount of cash paid for interest, excluding capitalized interest, classified as operating activity. "
        "Includes, but is not limited to, payment to settle zero-coupon bond for accreted interest of debt discount and "
        "debt instrument with insignificant coupon interest rate in relation to effective interest rate of borrowing "
        "attributable to accreted interest of debt discount.",
    )
    cash_interest_received: float | None = Field(
        default=None,
        description="The cash inflow from interest received, classified as operating activities.",
    )
    cash_income_taxes_paid: float | None = Field(
        default=None,
        description="Amount, after refund, of cash paid to foreign, federal, state, and local jurisdictions as income "
        "tax.",
    )

    @model_validator(mode="before")
    @classmethod
    def _validate_model(cls, values):
        """Validate the model."""
        return {k: v for k, v in values.items() if v is not None}

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        d = handler(self)
        return {
            k: (None if isinstance(v, float) and isnan(v) else v) for k, v in d.items()
        }


class SecCashFlowStatementFetcher(
    Fetcher[SecCashFlowStatementQueryParams, list[SecCashFlowStatementData]]
):
    """SEC CashFlowStatement Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> SecCashFlowStatementQueryParams:
        """Transform the query."""
        return SecCashFlowStatementQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: SecCashFlowStatementQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Return the raw data from the SEC endpoint."""
        from openbb_sec.utils.company_facts import (
            get_standardized_financials,
        )

        kwargs_call: dict[str, Any] = {
            "symbol": query.symbol,
            "period": query.period,
            "use_cache": query.use_cache,
            "include_preliminary": query.include_preliminary,
            "pit_mode": query.pit_mode,
        }
        if query.as_of_date is not None:
            kwargs_call["as_of_date"] = query.as_of_date
        result = await get_standardized_financials(**kwargs_call)
        return {
            "result": result,
            "statement": "cash_flow",
        }

    @staticmethod
    def transform_data(
        query: SecCashFlowStatementQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> AnnotatedResult[list[SecCashFlowStatementData]]:
        """Transform the data and validate the model."""
        from openbb_sec.utils.company_facts import (
            StandardizedStatements,
            normalize_period_fields,
            order_field_meta,
        )

        result: StandardizedStatements = data["result"]
        statement_name: str = data["statement"]
        records: list[dict] = getattr(result, statement_name)

        if not records:
            raise EmptyDataError("The request was returned empty.")

        # Group records by period_ending to pivot from long to wide format.
        periods: dict[str, dict] = {}
        sources: dict[str, dict[str, str]] = {}
        field_meta: dict[str, dict] = {}  # tag -> schema metadata
        period_meta: dict[str, dict] = {}

        for rec in records:
            date_key = rec["period_ending"]

            if date_key not in periods:
                periods[date_key] = {
                    "period_ending": date_key,
                    "fiscal_period": rec.get("fiscal_period"),
                    "fiscal_year": rec.get("fiscal_year"),
                    "reported_currency": rec.get("currency"),
                }
                if rec.get("filing_date") is not None:
                    periods[date_key]["filing_date"] = rec["filing_date"]
                if rec.get("is_restated") is not None:
                    periods[date_key]["is_restated"] = rec["is_restated"]
                if (
                    rec.get("filing_date") is not None
                    or rec.get("is_restated") is not None
                ):
                    period_meta[date_key] = {
                        "period_end": date_key,
                        "filing_date": rec.get("filing_date"),
                        "original_filing_date": rec.get("original_filing_date"),
                        "latest_filing_date": rec.get("latest_filing_date"),
                        "is_restated": rec.get("is_restated"),
                        "source": "SEC EDGAR XBRL",
                    }
                sources[date_key] = {}
            tag = rec["tag"]
            periods[date_key][tag] = rec["value"]
            source = rec.get("source", "")

            if source:
                sources[date_key][tag] = source

            if tag not in field_meta:
                field_meta[tag] = {
                    "label": rec.get("label", ""),
                    "description": rec.get("description", ""),
                    "parent": rec.get("parent"),
                    "sequence": rec.get("sequence"),
                    "factor": rec.get("factor", "+"),
                    "balance": rec.get("balance", ""),
                    "unit": rec.get("unit", "monetary"),
                }

        normalize_period_fields(periods, SecCashFlowStatementData)

        # Sort by period_ending descending (most recent first).
        sorted_periods = sorted(
            periods.values(),
            key=lambda x: x["period_ending"],
            reverse=True,
        )

        if query.limit is not None:
            sorted_periods = sorted_periods[: query.limit]

        results = [SecCashFlowStatementData.model_validate(d) for d in sorted_periods]
        # Build metadata: field provenance (sources) and diagnostics.
        field_sources: dict[str, dict[str, str]] = {}

        for date_key, date_sources in sources.items():
            for tag, source in date_sources.items():
                if source:
                    if tag not in field_sources:
                        field_sources[tag] = {}
                    field_sources[tag][date_key] = source

        # Merge sources into field metadata.
        for tag, period_sources in field_sources.items():
            if tag in field_meta:
                field_meta[tag]["sources"] = period_sources

        metadata: dict = {
            "entity_name": result.entity_name,
            "cik": result.cik,
            "company_type": result.company_type,
            "fields": order_field_meta(field_meta, SecCashFlowStatementData),
        }
        if getattr(result, "schema_version", None):
            metadata["schema_version"] = result.schema_version
        if period_meta:
            metadata["periods"] = period_meta
        if getattr(query, "as_of_date", None) is not None:
            metadata["as_of_date"] = str(query.as_of_date)
        if getattr(query, "pit_mode", False):
            metadata["pit_mode"] = True

        # Surface ValidationWarning diagnostics.
        if result.diagnostics:
            diag_details = [
                {
                    "date": d.date,
                    "tag": d.tag,
                    "expected": d.expected,
                    "actual": d.actual,
                    "formula": d.formula,
                    "identity": d.identity,
                }
                for d in result.diagnostics
            ]
            metadata["validation_warnings"] = diag_details
            tags_affected = sorted({d.tag for d in result.diagnostics})
            dates_affected = sorted({d.date for d in result.diagnostics})
            warn(
                f"SEC XBRL validation: {len(result.diagnostics)} "
                f"warning(s) across {len(dates_affected)} period(s)"
                f" affecting tag(s): {', '.join(tags_affected)}. "
                "See metadata['validation_warnings'] for details."
            )

        return AnnotatedResult(result=results, metadata=metadata)
