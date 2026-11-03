"""SEC Balance Sheet Growth Model."""

from math import isnan
from typing import Any, Literal
from warnings import warn

from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.balance_sheet_growth import (
    BalanceSheetGrowthData,
    BalanceSheetGrowthQueryParams,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import ConfigDict, Field, model_serializer, model_validator

_PCT: dict[str, Any] = {"x-unit_measurement": "percent", "x-frontend_multiply": 100}


class SecBalanceSheetGrowthQueryParams(BalanceSheetGrowthQueryParams):
    """SEC Balance Sheet Growth Query.

    Source: https://www.sec.gov/edgar/sec-api-documentation
    """

    period: Literal["annual", "quarterly", "quarterly_yoy", "ttm"] = Field(
        default="annual",
        description=QUERY_DESCRIPTIONS.get("period", "")
        + " For balance sheet growth, 'quarterly_yoy' compares the most recent quarter to the same"
        + " quarter in the prior year, and TTM compares the most recent quarter to the average of"
        + " the same quarter and the three preceding quarters in the prior year.",
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


class SecBalanceSheetGrowthData(BalanceSheetGrowthData):
    """SEC Balance Sheet Growth Data."""

    model_config = ConfigDict(
        allow_inf_nan=True,
        ser_json_inf_nan="null",
        json_schema_extra={
            "x-widget_config": {"$.data": {"table": {"enableFormulas": True}}}
        },
    )

    growth_cash_and_equivalents: float | None = Field(
        default=None,
        description="Growth rate of cash and cash equivalents.",
        json_schema_extra=_PCT,
    )
    growth_restricted_cash: float | None = Field(
        default=None,
        description="Growth rate of restricted cash.",
        json_schema_extra=_PCT,
    )
    growth_short_term_investments: float | None = Field(
        default=None,
        description="Growth rate of short-term investments.",
        json_schema_extra=_PCT,
    )
    growth_fed_funds_sold: float | None = Field(
        default=None,
        description="Growth rate of federal funds sold.",
        json_schema_extra=_PCT,
    )
    growth_interest_bearing_deposits_at_other_banks: float | None = Field(
        default=None,
        description="Growth rate of interest-bearing deposits at other banks.",
        json_schema_extra=_PCT,
    )
    growth_time_deposits_placed: float | None = Field(
        default=None,
        description="Growth rate of time deposits placed.",
        json_schema_extra=_PCT,
    )
    growth_trading_account_securities: float | None = Field(
        default=None,
        description="Growth rate of trading account securities.",
        json_schema_extra=_PCT,
    )
    growth_loans_and_leases: float | None = Field(
        default=None,
        description="Growth rate of loans and leases.",
        json_schema_extra=_PCT,
    )
    growth_allowance_for_loan_and_lease_losses: float | None = Field(
        default=None,
        description="Growth rate of allowance for loan and lease losses.",
        json_schema_extra=_PCT,
    )
    growth_net_loans_and_leases: float | None = Field(
        default=None,
        description="Growth rate of net loans and leases.",
        json_schema_extra=_PCT,
    )
    growth_loans_held_for_sale: float | None = Field(
        default=None,
        description="Growth rate of loans held for sale.",
        json_schema_extra=_PCT,
    )
    growth_accrued_investment_income: float | None = Field(
        default=None,
        description="Growth rate of accrued investment income.",
        json_schema_extra=_PCT,
    )
    growth_accounts_receivable: float | None = Field(
        default=None,
        description="Growth rate of accounts receivable.",
        json_schema_extra=_PCT,
    )
    growth_customer_and_other_receivables: float | None = Field(
        default=None,
        description="Growth rate of customer and other receivables.",
        json_schema_extra=_PCT,
    )
    growth_note_receivable: float | None = Field(
        default=None,
        description="Growth rate of note receivable.",
        json_schema_extra=_PCT,
    )
    growth_nontrade_receivables: float | None = Field(
        default=None,
        description="Growth rate of nontrade receivables.",
        json_schema_extra=_PCT,
    )
    growth_net_inventory: float | None = Field(
        default=None,
        description="Growth rate of net inventory.",
        json_schema_extra=_PCT,
    )
    growth_prepaid_expenses: float | None = Field(
        default=None,
        description="Growth rate of prepaid expenses.",
        json_schema_extra=_PCT,
    )
    growth_current_deferred_tax_assets: float | None = Field(
        default=None,
        description="Growth rate of current deferred tax assets.",
        json_schema_extra=_PCT,
    )
    growth_other_current_assets: float | None = Field(
        default=None,
        description="Growth rate of other current assets.",
        json_schema_extra=_PCT,
    )
    growth_other_current_nonoperating_assets: float | None = Field(
        default=None,
        description="Growth rate of other current nonoperating assets.",
        json_schema_extra=_PCT,
    )
    growth_total_current_assets: float | None = Field(
        default=None,
        description="Growth rate of total current assets.",
        json_schema_extra=_PCT,
    )
    growth_gross_ppe: float | None = Field(
        default=None,
        description="Growth rate of gross property, plant, and equipment.",
        json_schema_extra=_PCT,
    )
    growth_accumulated_depreciation: float | None = Field(
        default=None,
        description="Growth rate of accumulated depreciation.",
        json_schema_extra=_PCT,
    )
    growth_net_ppe: float | None = Field(
        default=None,
        description="Growth rate of net property, plant, and equipment.",
        json_schema_extra=_PCT,
    )
    growth_net_premises_and_equipment: float | None = Field(
        default=None,
        description="Growth rate of net premises and equipment.",
        json_schema_extra=_PCT,
    )
    growth_operating_lease_right_of_use_asset: float | None = Field(
        default=None,
        description="Growth rate of operating lease right-of-use asset.",
        json_schema_extra=_PCT,
    )
    growth_finance_lease_right_of_use_asset: float | None = Field(
        default=None,
        description="Growth rate of finance lease right-of-use asset.",
        json_schema_extra=_PCT,
    )
    growth_long_term_investments: float | None = Field(
        default=None,
        description="Growth rate of long-term investments.",
        json_schema_extra=_PCT,
    )
    growth_mortgage_servicing_rights: float | None = Field(
        default=None,
        description="Growth rate of mortgage servicing rights.",
        json_schema_extra=_PCT,
    )
    growth_deferred_acquisition_cost: float | None = Field(
        default=None,
        description="Growth rate of deferred acquisition cost.",
        json_schema_extra=_PCT,
    )
    growth_separate_account_business_assets: float | None = Field(
        default=None,
        description="Growth rate of separate account business assets.",
        json_schema_extra=_PCT,
    )
    growth_noncurrent_note_receivables: float | None = Field(
        default=None,
        description="Growth rate of noncurrent note receivables.",
        json_schema_extra=_PCT,
    )
    growth_goodwill: float | None = Field(
        default=None,
        description="Growth rate of goodwill.",
        json_schema_extra=_PCT,
    )
    growth_intangible_assets: float | None = Field(
        default=None,
        description="Growth rate of intangible assets.",
        json_schema_extra=_PCT,
    )
    growth_noncurrent_deferred_tax_assets: float | None = Field(
        default=None,
        description="Growth rate of noncurrent deferred tax assets.",
        json_schema_extra=_PCT,
    )
    growth_employee_benefit_assets: float | None = Field(
        default=None,
        description="Growth rate of employee benefit assets.",
        json_schema_extra=_PCT,
    )
    growth_other_noncurrent_assets: float | None = Field(
        default=None,
        description="Growth rate of other noncurrent assets.",
        json_schema_extra=_PCT,
    )
    growth_other_noncurrent_nonoperating_assets: float | None = Field(
        default=None,
        description="Growth rate of other noncurrent nonoperating assets.",
        json_schema_extra=_PCT,
    )
    growth_other_noncurrent_assets_excl_ppe: float | None = Field(
        default=None,
        description="Growth rate of other noncurrent assets excluding PPE.",
        json_schema_extra=_PCT,
    )
    growth_total_noncurrent_assets: float | None = Field(
        default=None,
        description="Growth rate of total noncurrent assets.",
        json_schema_extra=_PCT,
    )
    growth_other_assets: float | None = Field(
        default=None,
        description="Growth rate of other assets.",
        json_schema_extra=_PCT,
    )
    growth_total_assets: float | None = Field(
        default=None,
        description="Growth rate of total assets.",
        json_schema_extra=_PCT,
    )
    growth_noninterest_bearing_deposits: float | None = Field(
        default=None,
        description="Growth rate of noninterest-bearing deposits.",
        json_schema_extra=_PCT,
    )
    growth_interest_bearing_deposits: float | None = Field(
        default=None,
        description="Growth rate of interest-bearing deposits.",
        json_schema_extra=_PCT,
    )
    growth_fed_funds_purchased: float | None = Field(
        default=None,
        description="Growth rate of federal funds purchased.",
        json_schema_extra=_PCT,
    )
    growth_short_term_debt: float | None = Field(
        default=None,
        description="Growth rate of short-term debt.",
        json_schema_extra=_PCT,
    )
    growth_current_portion_of_long_term_debt: float | None = Field(
        default=None,
        description="Growth rate of current portion of long-term debt.",
        json_schema_extra=_PCT,
    )
    growth_bankers_acceptances: float | None = Field(
        default=None,
        description="Growth rate of bankers acceptances.",
        json_schema_extra=_PCT,
    )
    growth_accounts_payable: float | None = Field(
        default=None,
        description="Growth rate of accounts payable.",
        json_schema_extra=_PCT,
    )
    growth_accrued_interest_payable: float | None = Field(
        default=None,
        description="Growth rate of accrued interest payable.",
        json_schema_extra=_PCT,
    )
    growth_other_short_term_payables: float | None = Field(
        default=None,
        description="Growth rate of other short-term payables.",
        json_schema_extra=_PCT,
    )
    growth_accrued_expenses: float | None = Field(
        default=None,
        description="Growth rate of accrued expenses.",
        json_schema_extra=_PCT,
    )
    growth_customer_deposits: float | None = Field(
        default=None,
        description="Growth rate of customer deposits.",
        json_schema_extra=_PCT,
    )
    growth_dividends_payable: float | None = Field(
        default=None,
        description="Growth rate of dividends payable.",
        json_schema_extra=_PCT,
    )
    growth_current_deferred_revenue: float | None = Field(
        default=None,
        description="Growth rate of current deferred revenue.",
        json_schema_extra=_PCT,
    )
    growth_current_deferred_tax_liabilities: float | None = Field(
        default=None,
        description="Growth rate of current deferred tax liabilities.",
        json_schema_extra=_PCT,
    )
    growth_current_employee_benefit_liabilities: float | None = Field(
        default=None,
        description="Growth rate of current employee benefit liabilities.",
        json_schema_extra=_PCT,
    )
    growth_other_taxes_payable: float | None = Field(
        default=None,
        description="Growth rate of other taxes payable.",
        json_schema_extra=_PCT,
    )
    growth_other_current_liabilities: float | None = Field(
        default=None,
        description="Growth rate of other current liabilities.",
        json_schema_extra=_PCT,
    )
    growth_other_current_nonoperating_liabilities: float | None = Field(
        default=None,
        description="Growth rate of other current nonoperating liabilities.",
        json_schema_extra=_PCT,
    )
    growth_operating_lease_liability_current: float | None = Field(
        default=None,
        description="Growth rate of current operating lease liability.",
        json_schema_extra=_PCT,
    )
    growth_finance_lease_liability_current: float | None = Field(
        default=None,
        description="Growth rate of current finance lease liability.",
        json_schema_extra=_PCT,
    )
    growth_total_current_liabilities: float | None = Field(
        default=None,
        description="Growth rate of total current liabilities.",
        json_schema_extra=_PCT,
    )
    growth_long_term_debt: float | None = Field(
        default=None,
        description="Growth rate of long-term debt.",
        json_schema_extra=_PCT,
    )
    growth_capital_lease_obligations: float | None = Field(
        default=None,
        description="Growth rate of capital lease obligations.",
        json_schema_extra=_PCT,
    )
    growth_operating_lease_liability_noncurrent: float | None = Field(
        default=None,
        description="Growth rate of noncurrent operating lease liability.",
        json_schema_extra=_PCT,
    )
    growth_claims_and_claim_expenses: float | None = Field(
        default=None,
        description="Growth rate of claims and claim expenses.",
        json_schema_extra=_PCT,
    )
    growth_future_policy_benefits: float | None = Field(
        default=None,
        description="Growth rate of future policy benefits.",
        json_schema_extra=_PCT,
    )
    growth_unearned_premiums_credit: float | None = Field(
        default=None,
        description="Growth rate of unearned premiums credit.",
        json_schema_extra=_PCT,
    )
    growth_policyholder_funds: float | None = Field(
        default=None,
        description="Growth rate of policyholder funds.",
        json_schema_extra=_PCT,
    )
    growth_participating_policyholder_equity: float | None = Field(
        default=None,
        description="Growth rate of participating policyholder equity.",
        json_schema_extra=_PCT,
    )
    growth_separate_account_business_liabilities: float | None = Field(
        default=None,
        description="Growth rate of separate account business liabilities.",
        json_schema_extra=_PCT,
    )
    growth_other_long_term_liabilities: float | None = Field(
        default=None,
        description="Growth rate of other long-term liabilities.",
        json_schema_extra=_PCT,
    )
    growth_asset_retirement_and_litigation_obligation: float | None = Field(
        default=None,
        description="Growth rate of asset retirement and litigation obligation.",
        json_schema_extra=_PCT,
    )
    growth_noncurrent_deferred_revenue: float | None = Field(
        default=None,
        description="Growth rate of noncurrent deferred revenue.",
        json_schema_extra=_PCT,
    )
    growth_noncurrent_deferred_tax_liabilities: float | None = Field(
        default=None,
        description="Growth rate of noncurrent deferred tax liabilities.",
        json_schema_extra=_PCT,
    )
    growth_noncurrent_employee_benefit_liabilities: float | None = Field(
        default=None,
        description="Growth rate of noncurrent employee benefit liabilities.",
        json_schema_extra=_PCT,
    )
    growth_other_noncurrent_liabilities: float | None = Field(
        default=None,
        description="Growth rate of other noncurrent liabilities.",
        json_schema_extra=_PCT,
    )
    growth_other_noncurrent_nonoperating_liabilities: float | None = Field(
        default=None,
        description="Growth rate of other noncurrent nonoperating liabilities.",
        json_schema_extra=_PCT,
    )
    growth_total_noncurrent_liabilities: float | None = Field(
        default=None,
        description="Growth rate of total noncurrent liabilities.",
        json_schema_extra=_PCT,
    )
    growth_total_liabilities: float | None = Field(
        default=None,
        description="Growth rate of total liabilities.",
        json_schema_extra=_PCT,
    )
    growth_commitments_and_contingencies: float | None = Field(
        default=None,
        description="Growth rate of commitments and contingencies.",
        json_schema_extra=_PCT,
    )
    growth_temporary_equity: float | None = Field(
        default=None,
        description="Growth rate of temporary equity.",
        json_schema_extra=_PCT,
    )
    growth_temporary_equity_parent: float | None = Field(
        default=None,
        description="Growth rate of temporary equity attributable to parent.",
        json_schema_extra=_PCT,
    )
    growth_redeemable_noncontrolling_interest: float | None = Field(
        default=None,
        description="Growth rate of redeemable noncontrolling interest.",
        json_schema_extra=_PCT,
    )
    growth_redeemable_nci_common: float | None = Field(
        default=None,
        description="Growth rate of redeemable NCI common.",
        json_schema_extra=_PCT,
    )
    growth_redeemable_nci_preferred: float | None = Field(
        default=None,
        description="Growth rate of redeemable NCI preferred.",
        json_schema_extra=_PCT,
    )
    growth_redeemable_nci_other: float | None = Field(
        default=None,
        description="Growth rate of redeemable NCI other.",
        json_schema_extra=_PCT,
    )
    growth_total_preferred_equity: float | None = Field(
        default=None,
        description="Growth rate of total preferred equity.",
        json_schema_extra=_PCT,
    )
    growth_common_equity: float | None = Field(
        default=None,
        description="Growth rate of common equity.",
        json_schema_extra=_PCT,
    )
    growth_additional_paid_in_capital: float | None = Field(
        default=None,
        description="Growth rate of additional paid-in capital.",
        json_schema_extra=_PCT,
    )
    growth_retained_earnings: float | None = Field(
        default=None,
        description="Growth rate of retained earnings.",
        json_schema_extra=_PCT,
    )
    growth_treasury_stock: float | None = Field(
        default=None,
        description="Growth rate of treasury stock.",
        json_schema_extra=_PCT,
    )
    growth_accumulated_other_comprehensive_income: float | None = Field(
        default=None,
        description="Growth rate of accumulated other comprehensive income.",
        json_schema_extra=_PCT,
    )
    growth_other_equity: float | None = Field(
        default=None,
        description="Growth rate of other equity.",
        json_schema_extra=_PCT,
    )
    growth_total_common_equity: float | None = Field(
        default=None,
        description="Growth rate of total common equity.",
        json_schema_extra=_PCT,
    )
    growth_total_equity: float | None = Field(
        default=None,
        description="Growth rate of total equity.",
        json_schema_extra=_PCT,
    )
    growth_noncontrolling_interests: float | None = Field(
        default=None,
        description="Growth rate of noncontrolling interests.",
        json_schema_extra=_PCT,
    )
    growth_total_equity_and_noncontrolling_interests: float | None = Field(
        default=None,
        description="Growth rate of total equity and noncontrolling interests.",
        json_schema_extra=_PCT,
    )
    growth_total_liabilities_and_equity: float | None = Field(
        default=None,
        description="Growth rate of total liabilities and equity.",
        json_schema_extra=_PCT,
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


class SecBalanceSheetGrowthFetcher(
    Fetcher[SecBalanceSheetGrowthQueryParams, list[SecBalanceSheetGrowthData]]
):
    """SEC Balance Sheet Growth Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> SecBalanceSheetGrowthQueryParams:
        """Transform the query."""
        return SecBalanceSheetGrowthQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: SecBalanceSheetGrowthQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Return the raw data from the SEC endpoint."""
        from openbb_sec.utils.company_facts import (
            PeriodType,
            get_standardized_financials,
        )

        period_map: dict[str, PeriodType] = {
            "annual": "yoy",
            "quarterly": "pop",
            "quarterly_yoy": "yoy_quarterly",
            "ttm": "pop",
        }
        kwargs_call: dict[str, Any] = {
            "symbol": query.symbol,
            "period": period_map[query.period],
            "use_cache": query.use_cache,
            "include_preliminary": query.include_preliminary,
            "pit_mode": query.pit_mode,
        }
        if query.as_of_date is not None:
            kwargs_call["as_of_date"] = query.as_of_date
        result = await get_standardized_financials(**kwargs_call)
        return {"result": result, "statement": "balance_sheet"}

    @staticmethod
    def transform_data(
        query: SecBalanceSheetGrowthQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> AnnotatedResult[list[SecBalanceSheetGrowthData]]:
        """Transform the data and validate the model."""
        from openbb_sec.utils.company_facts import (
            StandardizedStatements,
            normalize_period_fields,
            order_field_meta,
        )

        result: StandardizedStatements = data["result"]
        records: list[dict] = getattr(result, data["statement"])

        if not records:
            raise EmptyDataError("The request was returned empty.")

        periods: dict[str, dict] = {}
        sources: dict[str, dict[str, str]] = {}
        field_meta: dict[str, dict] = {}
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
            growth_tag = f"growth_{tag}"
            periods[date_key][growth_tag] = rec["value"]
            source = rec.get("source", "")

            if source:
                sources[date_key][growth_tag] = source

            if growth_tag not in field_meta:
                field_meta[growth_tag] = {
                    "label": rec.get("label", ""),
                    "description": rec.get("description", ""),
                    "parent": rec.get("parent"),
                    "sequence": rec.get("sequence"),
                    "factor": rec.get("factor", "+"),
                    "balance": rec.get("balance", ""),
                    "unit": rec.get("unit", "monetary"),
                }

        normalize_period_fields(periods, SecBalanceSheetGrowthData)

        sorted_periods = sorted(
            periods.values(),
            key=lambda x: x["period_ending"],
            reverse=True,
        )

        if query.limit is not None:
            sorted_periods = sorted_periods[: query.limit]

        results = [SecBalanceSheetGrowthData.model_validate(d) for d in sorted_periods]

        field_sources: dict[str, dict[str, str]] = {}

        for date_key, date_sources in sources.items():
            for tag, source in date_sources.items():
                if source:
                    if tag not in field_sources:
                        field_sources[tag] = {}
                    field_sources[tag][date_key] = source

        for tag, period_sources in field_sources.items():
            if tag in field_meta:
                field_meta[tag]["sources"] = period_sources

        metadata: dict = {
            "entity_name": result.entity_name,
            "cik": result.cik,
            "company_type": result.company_type,
            "fields": order_field_meta(field_meta, SecBalanceSheetGrowthData),
        }
        if getattr(result, "schema_version", None):
            metadata["schema_version"] = result.schema_version
        if period_meta:
            metadata["periods"] = period_meta
        if getattr(query, "as_of_date", None) is not None:
            metadata["as_of_date"] = str(query.as_of_date)
        if getattr(query, "pit_mode", False):
            metadata["pit_mode"] = True

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
