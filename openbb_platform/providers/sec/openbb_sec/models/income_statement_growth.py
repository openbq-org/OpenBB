"""SEC Income Statement Growth Model."""

from math import isnan
from typing import Any, Literal
from warnings import warn

from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.income_statement_growth import (
    IncomeStatementGrowthData,
    IncomeStatementGrowthQueryParams,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import ConfigDict, Field, model_serializer, model_validator

_PCT: dict[str, Any] = {"x-unit_measurement": "percent", "x-frontend_multiply": 100}


class SecIncomeStatementGrowthQueryParams(IncomeStatementGrowthQueryParams):
    """SEC Income Statement Growth Query.

    Source: https://www.sec.gov/edgar/sec-api-documentation
    """

    period: Literal["annual", "quarterly", "quarterly_yoy", "ttm"] = Field(
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


class SecIncomeStatementGrowthData(IncomeStatementGrowthData):
    """SEC Income Statement Growth Data."""

    model_config = ConfigDict(
        allow_inf_nan=True,
        ser_json_inf_nan="null",
        json_schema_extra={
            "x-widget_config": {"$.data": {"table": {"enableFormulas": True}}}
        },
    )

    growth_operating_revenue: float | None = Field(
        default=None,
        description="Growth rate of operating revenue.",
        json_schema_extra=_PCT,
    )
    growth_other_revenue: float | None = Field(
        default=None,
        description="Growth rate of other revenue.",
        json_schema_extra=_PCT,
    )
    growth_total_revenue: float | None = Field(
        default=None,
        description="Growth rate of total revenue.",
        json_schema_extra=_PCT,
    )
    growth_operating_cost_of_revenue: float | None = Field(
        default=None,
        description="Growth rate of operating cost of revenue.",
        json_schema_extra=_PCT,
    )
    growth_other_cost_of_revenue: float | None = Field(
        default=None,
        description="Growth rate of other cost of revenue.",
        json_schema_extra=_PCT,
    )
    growth_total_cost_of_revenue: float | None = Field(
        default=None,
        description="Growth rate of total cost of revenue.",
        json_schema_extra=_PCT,
    )
    growth_excise_and_sales_taxes: float | None = Field(
        default=None,
        description="Growth rate of excise and sales taxes.",
        json_schema_extra=_PCT,
    )
    growth_total_gross_profit: float | None = Field(
        default=None,
        description="Growth rate of total gross profit.",
        json_schema_extra=_PCT,
    )
    growth_sga_expense: float | None = Field(
        default=None,
        description="Growth rate of selling, general, and administrative expense.",
        json_schema_extra=_PCT,
    )
    growth_rd_expense: float | None = Field(
        default=None,
        description="Growth rate of research and development expense.",
        json_schema_extra=_PCT,
    )
    growth_exploration_expense: float | None = Field(
        default=None,
        description="Growth rate of exploration expense.",
        json_schema_extra=_PCT,
    )
    growth_depreciation_expense: float | None = Field(
        default=None,
        description="Growth rate of depreciation expense.",
        json_schema_extra=_PCT,
    )
    growth_amortization_expense: float | None = Field(
        default=None,
        description="Growth rate of amortization expense.",
        json_schema_extra=_PCT,
    )
    growth_depreciation_and_amortization: float | None = Field(
        default=None,
        description="Growth rate of depreciation and amortization.",
        json_schema_extra=_PCT,
    )
    growth_depletion_expense: float | None = Field(
        default=None,
        description="Growth rate of depletion expense.",
        json_schema_extra=_PCT,
    )
    growth_other_operating_expenses: float | None = Field(
        default=None,
        description="Growth rate of other operating expenses.",
        json_schema_extra=_PCT,
    )
    growth_impairment_expense: float | None = Field(
        default=None,
        description="Growth rate of impairment expense.",
        json_schema_extra=_PCT,
    )
    growth_restructuring_charge: float | None = Field(
        default=None,
        description="Growth rate of restructuring charge.",
        json_schema_extra=_PCT,
    )
    growth_other_special_charges: float | None = Field(
        default=None,
        description="Growth rate of other special charges.",
        json_schema_extra=_PCT,
    )
    growth_total_operating_expenses: float | None = Field(
        default=None,
        description="Growth rate of total operating expenses.",
        json_schema_extra=_PCT,
    )
    growth_costs_and_expenses: float | None = Field(
        default=None,
        description="Growth rate of costs and expenses.",
        json_schema_extra=_PCT,
    )
    growth_total_operating_income: float | None = Field(
        default=None,
        description="Growth rate of total operating income.",
        json_schema_extra=_PCT,
    )
    growth_loans_and_lease_interest_income: float | None = Field(
        default=None,
        description="Growth rate of loans and lease interest income.",
        json_schema_extra=_PCT,
    )
    growth_investment_securities_interest_income: float | None = Field(
        default=None,
        description="Growth rate of investment securities interest income.",
        json_schema_extra=_PCT,
    )
    growth_deposits_interest_income: float | None = Field(
        default=None,
        description="Growth rate of deposits interest income.",
        json_schema_extra=_PCT,
    )
    growth_fed_funds_and_repo_interest_income: float | None = Field(
        default=None,
        description="Growth rate of federal funds and repo interest income.",
        json_schema_extra=_PCT,
    )
    growth_trading_account_interest_income: float | None = Field(
        default=None,
        description="Growth rate of trading account interest income.",
        json_schema_extra=_PCT,
    )
    growth_other_interest_income: float | None = Field(
        default=None,
        description="Growth rate of other interest income.",
        json_schema_extra=_PCT,
    )
    growth_total_interest_income: float | None = Field(
        default=None,
        description="Growth rate of total interest income.",
        json_schema_extra=_PCT,
    )
    growth_deposits_interest_expense: float | None = Field(
        default=None,
        description="Growth rate of deposits interest expense.",
        json_schema_extra=_PCT,
    )
    growth_short_term_borrowing_interest_expense: float | None = Field(
        default=None,
        description="Growth rate of short-term borrowing interest expense.",
        json_schema_extra=_PCT,
    )
    growth_long_term_debt_interest_expense: float | None = Field(
        default=None,
        description="Growth rate of long-term debt interest expense.",
        json_schema_extra=_PCT,
    )
    growth_fed_funds_and_repo_interest_expense: float | None = Field(
        default=None,
        description="Growth rate of federal funds and repo interest expense.",
        json_schema_extra=_PCT,
    )
    growth_capitalized_lease_obligation_interest_expense: float | None = Field(
        default=None,
        description="Growth rate of capitalized lease obligation interest expense.",
        json_schema_extra=_PCT,
    )
    growth_other_interest_expense: float | None = Field(
        default=None,
        description="Growth rate of other interest expense.",
        json_schema_extra=_PCT,
    )
    growth_total_interest_expense: float | None = Field(
        default=None,
        description="Growth rate of total interest expense.",
        json_schema_extra=_PCT,
    )
    growth_net_interest_income: float | None = Field(
        default=None,
        description="Growth rate of net interest income.",
        json_schema_extra=_PCT,
    )
    growth_revenues_excl_interest_dividends: float | None = Field(
        default=None,
        description="Growth rate of revenues excluding interest and dividends.",
        json_schema_extra=_PCT,
    )
    growth_trust_fee_income: float | None = Field(
        default=None,
        description="Growth rate of trust fee income.",
        json_schema_extra=_PCT,
    )
    growth_service_charges_on_deposits_income: float | None = Field(
        default=None,
        description="Growth rate of service charges on deposit accounts.",
        json_schema_extra=_PCT,
    )
    growth_other_service_charge_income: float | None = Field(
        default=None,
        description="Growth rate of other service charge income.",
        json_schema_extra=_PCT,
    )
    growth_net_realized_capital_gains: float | None = Field(
        default=None,
        description="Growth rate of net realized and unrealized capital gains on investments.",
        json_schema_extra=_PCT,
    )
    growth_premiums_earned: float | None = Field(
        default=None,
        description="Growth rate of premiums earned.",
        json_schema_extra=_PCT,
    )
    growth_investment_banking_income: float | None = Field(
        default=None,
        description="Growth rate of investment banking income.",
        json_schema_extra=_PCT,
    )
    growth_other_noninterest_income: float | None = Field(
        default=None,
        description="Growth rate of other noninterest income.",
        json_schema_extra=_PCT,
    )
    growth_total_noninterest_income: float | None = Field(
        default=None,
        description="Growth rate of total noninterest income.",
        json_schema_extra=_PCT,
    )
    growth_provision_for_credit_losses: float | None = Field(
        default=None,
        description="Growth rate of provision for credit losses.",
        json_schema_extra=_PCT,
    )
    growth_net_interest_income_after_provision: float | None = Field(
        default=None,
        description="Growth rate of net interest income after provision.",
        json_schema_extra=_PCT,
    )
    growth_benefits_costs_expenses: float | None = Field(
        default=None,
        description="Growth rate of benefits, costs, and expenses.",
        json_schema_extra=_PCT,
    )
    growth_current_and_future_benefits: float | None = Field(
        default=None,
        description="Growth rate of current and future benefits.",
        json_schema_extra=_PCT,
    )
    growth_salaries_and_employee_benefits_expense: float | None = Field(
        default=None,
        description="Growth rate of salaries and employee benefits expense.",
        json_schema_extra=_PCT,
    )
    growth_net_occupancy_equipment_expense: float | None = Field(
        default=None,
        description="Growth rate of net occupancy equipment expense.",
        json_schema_extra=_PCT,
    )
    growth_marketing_expense: float | None = Field(
        default=None,
        description="Growth rate of marketing expense.",
        json_schema_extra=_PCT,
    )
    growth_property_liability_insurance_claims: float | None = Field(
        default=None,
        description="Growth rate of property liability insurance claims.",
        json_schema_extra=_PCT,
    )
    growth_policy_acquisition_costs: float | None = Field(
        default=None,
        description="Growth rate of policy acquisition costs.",
        json_schema_extra=_PCT,
    )
    growth_amortization_of_deferred_policy_acquisition_costs: float | None = Field(
        default=None,
        description="Growth rate of amortization of deferred policy acquisition costs.",
        json_schema_extra=_PCT,
    )
    growth_total_noninterest_expense: float | None = Field(
        default=None,
        description="Growth rate of total noninterest expense.",
        json_schema_extra=_PCT,
    )
    growth_non_operating_income: float | None = Field(
        default=None,
        description="Growth rate of non-operating income.",
        json_schema_extra=_PCT,
    )
    growth_other_income: float | None = Field(
        default=None,
        description="Growth rate of other income.",
        json_schema_extra=_PCT,
    )
    growth_other_gains: float | None = Field(
        default=None,
        description="Growth rate of other gains.",
        json_schema_extra=_PCT,
    )
    growth_total_other_income: float | None = Field(
        default=None,
        description="Growth rate of total other income.",
        json_schema_extra=_PCT,
    )
    growth_total_pretax_income: float | None = Field(
        default=None,
        description="Growth rate of total pretax income.",
        json_schema_extra=_PCT,
    )
    growth_income_tax_expense: float | None = Field(
        default=None,
        description="Growth rate of income tax expense.",
        json_schema_extra=_PCT,
    )
    growth_income_tax_current: float | None = Field(
        default=None,
        description="Growth rate of current income tax.",
        json_schema_extra=_PCT,
    )
    growth_income_tax_deferred: float | None = Field(
        default=None,
        description="Growth rate of deferred income tax.",
        json_schema_extra=_PCT,
    )
    growth_income_before_equity_method: float | None = Field(
        default=None,
        description="Growth rate of income before equity method.",
        json_schema_extra=_PCT,
    )
    growth_equity_method_investments: float | None = Field(
        default=None,
        description="Growth rate of equity method investments.",
        json_schema_extra=_PCT,
    )
    growth_net_income_continuing: float | None = Field(
        default=None,
        description="Growth rate of net income from continuing operations.",
        json_schema_extra=_PCT,
    )
    growth_net_income_discontinued: float | None = Field(
        default=None,
        description="Growth rate of net income from discontinued operations.",
        json_schema_extra=_PCT,
    )
    growth_extraordinary_income: float | None = Field(
        default=None,
        description="Growth rate of extraordinary income.",
        json_schema_extra=_PCT,
    )
    growth_other_adjustments_to_consolidated_net_income: float | None = Field(
        default=None,
        description="Growth rate of other adjustments to consolidated net income.",
        json_schema_extra=_PCT,
    )
    growth_gain_on_sale_properties: float | None = Field(
        default=None,
        description="Growth rate of gain on sale of properties.",
        json_schema_extra=_PCT,
    )
    growth_gain_loss_disposition_subsidiary: float | None = Field(
        default=None,
        description="Growth rate of gain/loss on disposition of subsidiary.",
        json_schema_extra=_PCT,
    )
    growth_net_income: float | None = Field(
        default=None,
        description="Growth rate of net income.",
        json_schema_extra=_PCT,
    )
    growth_preferred_dividends: float | None = Field(
        default=None,
        description="Growth rate of preferred dividends.",
        json_schema_extra=_PCT,
    )
    growth_net_income_nci_redeemable: float | None = Field(
        default=None,
        description="Growth rate of net income NCI redeemable.",
        json_schema_extra=_PCT,
    )
    growth_net_income_nci_nonredeemable: float | None = Field(
        default=None,
        description="Growth rate of net income NCI nonredeemable.",
        json_schema_extra=_PCT,
    )
    growth_net_income_to_noncontrolling_interest: float | None = Field(
        default=None,
        description="Growth rate of net income to noncontrolling interest.",
        json_schema_extra=_PCT,
    )
    growth_other_adjustments_to_net_income_to_common: float | None = Field(
        default=None,
        description="Growth rate of other adjustments to net income to common.",
        json_schema_extra=_PCT,
    )
    growth_net_income_to_common: float | None = Field(
        default=None,
        description="Growth rate of net income to common.",
        json_schema_extra=_PCT,
    )
    growth_weighted_ave_basic_shares_os: float | None = Field(
        default=None,
        description="Growth rate of weighted average basic shares outstanding.",
        json_schema_extra=_PCT,
    )
    growth_basic_eps: float | None = Field(
        default=None,
        description="Growth rate of basic earnings per share.",
        json_schema_extra=_PCT,
    )
    growth_weighted_ave_diluted_shares_os: float | None = Field(
        default=None,
        description="Growth rate of weighted average diluted shares outstanding.",
        json_schema_extra=_PCT,
    )
    growth_diluted_eps: float | None = Field(
        default=None,
        description="Growth rate of diluted earnings per share.",
        json_schema_extra=_PCT,
    )
    growth_weighted_ave_basic_diluted_shares_os: float | None = Field(
        default=None,
        description="Growth rate of weighted average basic/diluted shares outstanding.",
        json_schema_extra=_PCT,
    )
    growth_basic_diluted_eps: float | None = Field(
        default=None,
        description="Growth rate of basic/diluted earnings per share.",
        json_schema_extra=_PCT,
    )
    growth_cash_dividends_per_share: float | None = Field(
        default=None,
        description="Growth rate of cash dividends per share.",
        json_schema_extra=_PCT,
    )
    growth_other_comprehensive_income_parent: float | None = Field(
        default=None,
        description="Growth rate of other comprehensive income attributable to parent.",
        json_schema_extra=_PCT,
    )
    growth_comprehensive_income_parent: float | None = Field(
        default=None,
        description="Growth rate of comprehensive income attributable to parent.",
        json_schema_extra=_PCT,
    )
    growth_other_comprehensive_income_nci: float | None = Field(
        default=None,
        description="Growth rate of other comprehensive income attributable to NCI.",
        json_schema_extra=_PCT,
    )
    growth_comprehensive_income_nci: float | None = Field(
        default=None,
        description="Growth rate of comprehensive income attributable to NCI.",
        json_schema_extra=_PCT,
    )
    growth_comprehensive_income: float | None = Field(
        default=None,
        description="Growth rate of comprehensive income.",
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


class SecIncomeStatementGrowthFetcher(
    Fetcher[SecIncomeStatementGrowthQueryParams, list[SecIncomeStatementGrowthData]]
):
    """SEC Income Statement Growth Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> SecIncomeStatementGrowthQueryParams:
        """Transform the query."""
        return SecIncomeStatementGrowthQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: SecIncomeStatementGrowthQueryParams,
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
        return {"result": result, "statement": "income_statement"}

    @staticmethod
    def transform_data(
        query: SecIncomeStatementGrowthQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> AnnotatedResult[list[SecIncomeStatementGrowthData]]:
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

        normalize_period_fields(periods, SecIncomeStatementGrowthData)

        sorted_periods = sorted(
            periods.values(),
            key=lambda x: x["period_ending"],
            reverse=True,
        )

        if query.limit is not None:
            sorted_periods = sorted_periods[: query.limit]

        results = [
            SecIncomeStatementGrowthData.model_validate(d) for d in sorted_periods
        ]

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
            "fields": order_field_meta(field_meta, SecIncomeStatementGrowthData),
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
