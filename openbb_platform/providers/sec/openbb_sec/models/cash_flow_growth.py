"""SEC Cash Flow Statement Growth Model."""

from math import isnan
from typing import Any, Literal
from warnings import warn

from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.cash_flow_growth import (
    CashFlowStatementGrowthData,
    CashFlowStatementGrowthQueryParams,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import ConfigDict, Field, model_serializer, model_validator

_PCT: dict[str, Any] = {"x-unit_measurement": "percent", "x-frontend_multiply": 100}


class SecCashFlowStatementGrowthQueryParams(CashFlowStatementGrowthQueryParams):
    """SEC Cash Flow Statement Growth Query.

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


class SecCashFlowStatementGrowthData(CashFlowStatementGrowthData):
    """SEC Cash Flow Statement Growth Data."""

    model_config = ConfigDict(
        allow_inf_nan=True,
        ser_json_inf_nan="null",
        json_schema_extra={
            "x-widget_config": {"$.data": {"table": {"enableFormulas": True}}}
        },
    )

    growth_net_income: float | None = Field(
        default=None,
        description="Growth rate of net income.",
        json_schema_extra=_PCT,
    )
    growth_net_income_discontinued: float | None = Field(
        default=None,
        description="Growth rate of net income from discontinued operations.",
        json_schema_extra=_PCT,
    )
    growth_net_income_continuing: float | None = Field(
        default=None,
        description="Growth rate of net income from continuing operations.",
        json_schema_extra=_PCT,
    )
    growth_provision_for_loan_losses: float | None = Field(
        default=None,
        description="Growth rate of provision for loan losses.",
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
    growth_stock_based_compensation: float | None = Field(
        default=None,
        description="Growth rate of stock-based compensation.",
        json_schema_extra=_PCT,
    )
    growth_deferred_income_tax: float | None = Field(
        default=None,
        description="Growth rate of deferred income tax.",
        json_schema_extra=_PCT,
    )
    growth_gain_loss_on_investments: float | None = Field(
        default=None,
        description="Growth rate of gain/loss on investments.",
        json_schema_extra=_PCT,
    )
    growth_gain_loss_on_sale_of_assets: float | None = Field(
        default=None,
        description="Growth rate of gain/loss on sale of assets.",
        json_schema_extra=_PCT,
    )
    growth_income_loss_from_equity_method_investments: float | None = Field(
        default=None,
        description="Growth rate of income/loss from equity method investments.",
        json_schema_extra=_PCT,
    )
    growth_asset_impairment_charges: float | None = Field(
        default=None,
        description="Growth rate of asset impairment charges.",
        json_schema_extra=_PCT,
    )
    growth_noncash_adjustments_to_net_income: float | None = Field(
        default=None,
        description="Growth rate of noncash adjustments to net income.",
        json_schema_extra=_PCT,
    )
    growth_other_operating_activities: float | None = Field(
        default=None,
        description="Growth rate of other operating activities.",
        json_schema_extra=_PCT,
    )
    growth_change_in_insurance_reserves: float | None = Field(
        default=None,
        description="Growth rate of change in insurance reserves.",
        json_schema_extra=_PCT,
    )
    growth_change_in_accounts_receivable: float | None = Field(
        default=None,
        description="Growth rate of change in accounts receivable.",
        json_schema_extra=_PCT,
    )
    growth_change_in_nontrade_receivables: float | None = Field(
        default=None,
        description="Growth rate of change in nontrade receivables.",
        json_schema_extra=_PCT,
    )
    growth_change_in_inventories: float | None = Field(
        default=None,
        description="Growth rate of change in inventories.",
        json_schema_extra=_PCT,
    )
    growth_change_in_accounts_payable: float | None = Field(
        default=None,
        description="Growth rate of change in accounts payable.",
        json_schema_extra=_PCT,
    )
    growth_change_in_other_operating_assets_and_liabilities: float | None = Field(
        default=None,
        description="Growth rate of change in other operating assets and liabilities.",
        json_schema_extra=_PCT,
    )
    growth_increase_decrease_in_operating_capital: float | None = Field(
        default=None,
        description="Growth rate of increase/decrease in operating capital.",
        json_schema_extra=_PCT,
    )
    growth_net_cash_from_continuing_operating_activities: float | None = Field(
        default=None,
        description="Growth rate of net cash from continuing operating activities.",
        json_schema_extra=_PCT,
    )
    growth_net_cash_from_discontinued_operating_activities: float | None = Field(
        default=None,
        description="Growth rate of net cash from discontinued operating activities.",
        json_schema_extra=_PCT,
    )
    growth_net_cash_from_operating_activities: float | None = Field(
        default=None,
        description="Growth rate of net cash from operating activities.",
        json_schema_extra=_PCT,
    )
    growth_purchase_of_plant_property_and_equipment: float | None = Field(
        default=None,
        description="Growth rate of purchase of plant, property, and equipment.",
        json_schema_extra=_PCT,
    )
    growth_acquisitions: float | None = Field(
        default=None,
        description="Growth rate of acquisitions.",
        json_schema_extra=_PCT,
    )
    growth_purchase_of_investments: float | None = Field(
        default=None,
        description="Growth rate of purchase of investments.",
        json_schema_extra=_PCT,
    )
    growth_purchase_of_held_to_maturity_investments: float | None = Field(
        default=None,
        description="Growth rate of purchase of held-to-maturity investments.",
        json_schema_extra=_PCT,
    )
    growth_sale_of_plant_property_and_equipment: float | None = Field(
        default=None,
        description="Growth rate of sale of plant, property, and equipment.",
        json_schema_extra=_PCT,
    )
    growth_sale_of_productive_assets: float | None = Field(
        default=None,
        description="Growth rate of sale of productive assets.",
        json_schema_extra=_PCT,
    )
    growth_divestitures: float | None = Field(
        default=None,
        description="Growth rate of divestitures.",
        json_schema_extra=_PCT,
    )
    growth_sale_of_investments: float | None = Field(
        default=None,
        description="Growth rate of sale of investments.",
        json_schema_extra=_PCT,
    )
    growth_maturity_of_investments: float | None = Field(
        default=None,
        description="Growth rate of maturity of investments.",
        json_schema_extra=_PCT,
    )
    growth_net_increase_in_fed_funds_sold: float | None = Field(
        default=None,
        description="Growth rate of net increase in federal funds sold.",
        json_schema_extra=_PCT,
    )
    growth_loans_held_for_sale_net: float | None = Field(
        default=None,
        description="Growth rate of loans held for sale, net.",
        json_schema_extra=_PCT,
    )
    growth_other_investing_activities_net: float | None = Field(
        default=None,
        description="Growth rate of other investing activities, net.",
        json_schema_extra=_PCT,
    )
    growth_net_cash_from_continuing_investing_activities: float | None = Field(
        default=None,
        description="Growth rate of net cash from continuing investing activities.",
        json_schema_extra=_PCT,
    )
    growth_net_cash_from_discontinued_investing_activities: float | None = Field(
        default=None,
        description="Growth rate of net cash from discontinued investing activities.",
        json_schema_extra=_PCT,
    )
    growth_net_cash_from_investing_activities: float | None = Field(
        default=None,
        description="Growth rate of net cash from investing activities.",
        json_schema_extra=_PCT,
    )
    growth_repayment_of_debt: float | None = Field(
        default=None,
        description="Growth rate of repayment of debt.",
        json_schema_extra=_PCT,
    )
    growth_repurchase_of_preferred_equity: float | None = Field(
        default=None,
        description="Growth rate of repurchase of preferred equity.",
        json_schema_extra=_PCT,
    )
    growth_repurchase_of_common_equity: float | None = Field(
        default=None,
        description="Growth rate of repurchase of common equity.",
        json_schema_extra=_PCT,
    )
    growth_payment_of_dividends: float | None = Field(
        default=None,
        description="Growth rate of payment of dividends.",
        json_schema_extra=_PCT,
    )
    growth_issuance_of_debt: float | None = Field(
        default=None,
        description="Growth rate of issuance of debt.",
        json_schema_extra=_PCT,
    )
    growth_issuance_of_preferred_equity: float | None = Field(
        default=None,
        description="Growth rate of issuance of preferred equity.",
        json_schema_extra=_PCT,
    )
    growth_issuance_of_common_equity: float | None = Field(
        default=None,
        description="Growth rate of issuance of common equity.",
        json_schema_extra=_PCT,
    )
    growth_net_change_in_deposits: float | None = Field(
        default=None,
        description="Growth rate of net change in deposits.",
        json_schema_extra=_PCT,
    )
    growth_net_short_term_borrowings: float | None = Field(
        default=None,
        description="Growth rate of net short-term borrowings.",
        json_schema_extra=_PCT,
    )
    growth_tax_withholding_share_based_compensation: float | None = Field(
        default=None,
        description="Growth rate of tax withholding for share-based compensation.",
        json_schema_extra=_PCT,
    )
    growth_other_financing_activities_net: float | None = Field(
        default=None,
        description="Growth rate of other financing activities, net.",
        json_schema_extra=_PCT,
    )
    growth_net_cash_from_continuing_financing_activities: float | None = Field(
        default=None,
        description="Growth rate of net cash from continuing financing activities.",
        json_schema_extra=_PCT,
    )
    growth_net_cash_from_discontinued_financing_activities: float | None = Field(
        default=None,
        description="Growth rate of net cash from discontinued financing activities.",
        json_schema_extra=_PCT,
    )
    growth_net_cash_from_financing_activities: float | None = Field(
        default=None,
        description="Growth rate of net cash from financing activities.",
        json_schema_extra=_PCT,
    )
    growth_effect_of_exchange_rate_changes: float | None = Field(
        default=None,
        description="Growth rate of effect of exchange rate changes.",
        json_schema_extra=_PCT,
    )
    growth_net_cash_from_discontinued_operations: float | None = Field(
        default=None,
        description="Growth rate of net cash from discontinued operations.",
        json_schema_extra=_PCT,
    )
    growth_other_net_changes_in_cash: float | None = Field(
        default=None,
        description="Growth rate of other net changes in cash.",
        json_schema_extra=_PCT,
    )
    growth_net_change_in_cash: float | None = Field(
        default=None,
        description="Growth rate of net change in cash.",
        json_schema_extra=_PCT,
    )
    growth_cash_at_beginning_of_period: float | None = Field(
        default=None,
        description="Growth rate of cash at beginning of period.",
        json_schema_extra=_PCT,
    )
    growth_cash_at_end_of_period: float | None = Field(
        default=None,
        description="Growth rate of cash at end of period.",
        json_schema_extra=_PCT,
    )
    growth_cash_interest_paid: float | None = Field(
        default=None,
        description="Growth rate of cash interest paid.",
        json_schema_extra=_PCT,
    )
    growth_cash_interest_received: float | None = Field(
        default=None,
        description="Growth rate of cash interest received.",
        json_schema_extra=_PCT,
    )
    growth_cash_income_taxes_paid: float | None = Field(
        default=None,
        description="Growth rate of cash income taxes paid.",
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


class SecCashFlowStatementGrowthFetcher(
    Fetcher[
        SecCashFlowStatementGrowthQueryParams,
        list[SecCashFlowStatementGrowthData],
    ]
):
    """SEC Cash Flow Statement Growth Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> SecCashFlowStatementGrowthQueryParams:
        """Transform the query."""
        return SecCashFlowStatementGrowthQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: SecCashFlowStatementGrowthQueryParams,
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
        return {"result": result, "statement": "cash_flow"}

    @staticmethod
    def transform_data(
        query: SecCashFlowStatementGrowthQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> AnnotatedResult[list[SecCashFlowStatementGrowthData]]:
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

        normalize_period_fields(periods, SecCashFlowStatementGrowthData)

        sorted_periods = sorted(
            periods.values(),
            key=lambda x: x["period_ending"],
            reverse=True,
        )

        if query.limit is not None:
            sorted_periods = sorted_periods[: query.limit]

        results = [
            SecCashFlowStatementGrowthData.model_validate(d) for d in sorted_periods
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
            "fields": order_field_meta(field_meta, SecCashFlowStatementGrowthData),
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
