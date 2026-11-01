from __future__ import annotations
import datetime as dt
from typing import Any, List, Optional
import tejapi

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.income_statement import (
    IncomeStatementData,
    IncomeStatementQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

class TEJIncomeStatementQueryParams(IncomeStatementQueryParams):
    """TEJ Income Statement Query."""
    start_date: Optional[dt.date] = Field(
        default=None,
        description="Start date of the data, in YYYY-MM-DD format.",
    )
    end_date: Optional[dt.date] = Field(
        default=None,
        description="End date of the data, in YYYY-MM-DD format.",
    )

class TEJIncomeStatementData(IncomeStatementData):
    """TEJ Income Statement Data."""

    # Standard OpenBB Fields
    revenue: float | None = Field(default=None, description="Total operating revenue")
    operating_income: float | None = Field(default=None, description="Net operating income (loss)")
    net_income: float | None = Field(default=None, description="Profit (loss) from continuing operations")
    eps: float | None = Field(default=None, description="Basic earnings per share")
    announcement_date: Optional[dt.date] | str | None = Field(default=None, description="Announcement Date (key3)")

    # TEJ Specific Fields - Revenue & Costs
    total_operating_costs: float | None = Field(default=None, description="Total operating costs")
    gross_profit_from_operations: float | None = Field(default=None, description="Gross profit (loss) from operations")
    realized_unrealized_profit_affiliated: float | None = Field(default=None, description="Realized (unrealized) profit - Affiliated companies")
    realized_gross_operating_profit: float | None = Field(default=None, description="Realized gross operating profit")

    # TEJ Specific Fields - Operating Expenses
    total_operating_expenses: float | None = Field(default=None, description="Total operating expenses")
    total_selling_expenses: float | None = Field(default=None, description="Total selling expenses")
    total_administrative_expenses: float | None = Field(default=None, description="Total administrative expenses")
    total_rd_expenses: float | None = Field(default=None, description="Total R&D expenses")
    other_expense_by_function: float | None = Field(default=None, description="Other expense, by function")
    operating_expense_expected_credit_impairment: float | None = Field(default=None, description="Operating expense - Expected credit impairment (loss) gain")
    net_other_income_expenses: float | None = Field(default=None, description="Net other income (expenses)")

    # TEJ Specific Fields - Non-Operating
    other_income_interest: float | None = Field(default=None, description="Other income - Interest income")
    total_other_income: float | None = Field(default=None, description="Total other income")
    other_gains_and_losses_net: float | None = Field(default=None, description="Other gains and losses, net")
    finance_costs_net: float | None = Field(default=None, description="Finance costs, net")
    share_of_profit_loss_associates_jvs: float | None = Field(default=None, description="Share of profit (loss) of associates & JVs (equity method)")
    non_operating_expected_credit_impairment: float | None = Field(default=None, description="Non-operating income and expenses - G(L) on expected credit impairment")
    gl_on_derecognition_fin_assets_ac: float | None = Field(default=None, description="G(L) on derecognition of fin. assets measured at AC")
    gl_on_fin_assets_reclassification: float | None = Field(default=None, description="G(L) on fin. assets reclassification")
    total_non_operating_income_expenses: float | None = Field(default=None, description="Total non-operating income and expenses")

    # TEJ Specific Fields - Profit & Tax
    profit_loss_before_tax: float | None = Field(default=None, description="Profit (loss) before tax")
    income_tax_expense: float | None = Field(default=None, description="Income tax expense")
    total_profit_loss_discontinued_operations: float | None = Field(default=None, description="Total profit (loss) from discontinued operations")

    # TEJ Specific Fields - OCI (Not Reclassified)
    oci_remeasurement_defined_benefit_plans: float | None = Field(default=None, description="OCI - Remeasurement of defined benefit plans - not reclassified")
    oci_gl_revaluation_property: float | None = Field(default=None, description="OCI - G(L) on revaluation of property - not reclassified")
    oci_credit_risk_fv_fin_liability: float | None = Field(default=None, description="OCI - Credit risk on FV measurement of fin. liability - not reclassified")
    oci_non_current_assets_held_for_sale_nr: float | None = Field(default=None, description="OCI - Non-current assets held for sale or assigned owners - not reclassified")
    oci_unrealized_gl_fvoci_equity: float | None = Field(default=None, description="OCI - Unrealized G(L) on FVOCI investments in equity - not reclassified")
    oci_gl_hedging_instrument_nr: float | None = Field(default=None, description="OCI - G(L) on hedging instrument - not reclassified")
    oci_gl_share_associate_jv_nr: float | None = Field(default=None, description="OCI - G(L) on share of associate & JV account - not reclassified")
    oci_others_nr: float | None = Field(default=None, description="OCI - Others - not reclassified")
    oci_income_tax_nr: float | None = Field(default=None, description="OCI - Income tax relating to components - not reclassified")
    oci_items_not_reclassified: float | None = Field(default=None, description="OCI - Items that are not reclassified")

    # TEJ Specific Fields - OCI (May Be Reclassified)
    oci_exchange_differences_translation: float | None = Field(default=None, description="OCI - Exchange differences on translation - may be reclassified")
    oci_non_current_assets_held_for_sale_mr: float | None = Field(default=None, description="OCI - Non-current assets held for sale or assigned owners - may be reclassified")
    oci_unrealized_gl_fvoci_debt: float | None = Field(default=None, description="OCI - Unrealized G(L) on FVOCI investment (debt) - may be reclassified")
    oci_gl_hedging_instrument_mr: float | None = Field(default=None, description="OCI - G(L) on hedging instrument - may be reclassified")
    oci_gl_share_associate_jv_mr: float | None = Field(default=None, description="OCI - G(L) on share of associate & JV account - may be reclassified")
    oci_others_mr: float | None = Field(default=None, description="OCI - Others - may be reclassified")
    oci_income_tax_mr: float | None = Field(default=None, description="OCI - Income tax relating to components - may be reclassified")
    oci_items_may_be_reclassified: float | None = Field(default=None, description="OCI - Subsequent items that are or may be reclassified")

    # TEJ Specific Fields - OCI & CI Summary
    oci_attributable_to_nci_pre_acquisition: float | None = Field(default=None, description="OCI - Attributable to NCI in pre-acquisition share capital")
    oci_net: float | None = Field(default=None, description="OCI, net")
    comprehensive_income: float | None = Field(default=None, description="Comprehensive income (CI)")
    ci_attributable_to_nci_pre_acquisition: float | None = Field(default=None, description="CI, attributable to NCI in pre-acquisition share capital")
    total_ci: float | None = Field(default=None, description="Total CI")

    # TEJ Specific Fields - Profit Attribution
    profit_loss_attributable_to_owners_of_parent: float | None = Field(default=None, description="Profit (loss), attributable to owners of parent")
    profit_loss_attributable_to_nci: float | None = Field(default=None, description="Profit (loss), attributable to NCI")
    profit_loss_attributable_to_former_jce: float | None = Field(default=None, description="Profit (loss), attributable to interests in the former jointly controlled entity")
    ci_attributable_to_owners_of_parent: float | None = Field(default=None, description="CI, attributable to owners of parent")
    ci_attributable_to_nci: float | None = Field(default=None, description="CI, attributable to NCI")
    ci_attributable_to_former_jce: float | None = Field(default=None, description="CI, attributable to former jointly controlled entity")

    # TEJ Specific Fields - Share & Other
    weighted_avg_ordinary_shares_thousands: float | None = Field(default=None, description="Weighted average number of ordinary shares in thousands")
    basic_eps_mops: float | None = Field(default=None, description="Basic earnings per share_MOPS")
    common_stock_shares: float | None = Field(default=None, description="Common Stock Shares")
    preferred_stock_shares: float | None = Field(default=None, description="Preferred Stock Shares")
    equivalent_shares_stock_dividend: float | None = Field(default=None, description="Equivalent Shares of Stock dividend to be distributed")
    profit_seeking_enterprise_income_tax: float | None = Field(default=None, description="Profit-seeking Enterprise Income Tax")
    preference_share_dividends: float | None = Field(default=None, description="Preference share dividends")
    ebit: float | None = Field(default=None, description="Earnings before interest and tax")
    ebitda: float | None = Field(default=None, description="Earnings before interest, tax, depreciation and amortization")
    total_treasury_shares: float | None = Field(default=None, description="Total treasury shares")


class TEJIncomeStatementFetcher(
    Fetcher[
        TEJIncomeStatementQueryParams,
        List[TEJIncomeStatementData],
    ]
):
    """TEJ Income Statement Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> TEJIncomeStatementQueryParams:
        return TEJIncomeStatementQueryParams(**params)

    @staticmethod
    def extract_data(
        query: TEJIncomeStatementQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> Any:
        if credentials:
            api_key = credentials.get("tej_api_key")
            if api_key:
                tejapi.ApiConfig.api_key = api_key

        tickers = query.symbol.split(",") if query.symbol else []

        cols = [
            "mdate", "no", "key3",
            "a3100", "a3200", "a3295", "a3296", "a3297", "a3300", "a3352", "a3355",
            "a3356", "a339s", "a339t", "a339r", "a3395", "a3410", "a3489", "a359w",
            "a3501", "a343c", "a34bk", "a34bl", "a34bm", "a3700", "a3900", "a3910",
            "a3920", "a3925", "a3966", "a3970", "a3949", "a3948", "a394i", "a394j",
            "a394e", "a394r", "a394k", "a394l", "a394m", "a3942", "a394a", "a394n",
            "a394b", "a394s", "a394o", "a394p", "a394q", "a3943", "a3944", "a3947",
            "a3971", "a3950", "a3960", "a3964", "a3956", "a3961", "a3967", "a3990",
            "a211f", "a399z", "a2111", "a2121", "a2303", "a391z", "a2117", "a2402",
            "a2403", "a240g",
        ]

        tej_params = {
            "datatable_code": "TWN/AINVFINA",
            "coid": tickers,
            "mdate": {"gte": query.start_date, "lte": query.end_date} if query.start_date else None,
            "opts": {"columns": cols},
            "paginate": True,
            "no": "Q"
        }

        try:
            data = tejapi.get(**tej_params)
        except Exception as e:
            raise RuntimeError(f"TEJ API Error: {str(e)}") from e

        return data

    @staticmethod
    def transform_data(
        query: TEJIncomeStatementQueryParams, data: Any, **kwargs: Any
    ) -> List[TEJIncomeStatementData]:
        if data is None or data.empty:
             raise EmptyDataError("No data returned from TEJ.")

        rename_map = {
            "mdate": "period_ending",
            "key3": "announcement_date",

            "a3100": "revenue",
            "a3200": "total_operating_costs",
            "a3295": "gross_profit_from_operations",
            "a3296": "realized_unrealized_profit_affiliated",
            "a3297": "realized_gross_operating_profit",
            "a3300": "total_operating_expenses",
            "a3352": "total_selling_expenses",
            "a3355": "total_administrative_expenses",
            "a3356": "total_rd_expenses",
            "a339s": "other_expense_by_function",
            "a339t": "operating_expense_expected_credit_impairment",
            "a339r": "net_other_income_expenses",
            "a3395": "operating_income",
            "a3410": "other_income_interest",
            "a3489": "total_other_income",
            "a359w": "other_gains_and_losses_net",
            "a3501": "finance_costs_net",
            "a343c": "share_of_profit_loss_associates_jvs",
            "a34bk": "non_operating_expected_credit_impairment",
            "a34bl": "gl_on_derecognition_fin_assets_ac",
            "a34bm": "gl_on_fin_assets_reclassification",
            "a3700": "total_non_operating_income_expenses",
            "a3900": "profit_loss_before_tax",
            "a3910": "income_tax_expense",
            "a3920": "net_income",
            "a3925": "total_profit_loss_discontinued_operations",
            "a3966": "ci_attributable_to_nci_pre_acquisition",
            "a3970": "total_ci",
            "a3949": "oci_remeasurement_defined_benefit_plans",
            "a3948": "oci_gl_revaluation_property",
            "a394i": "oci_credit_risk_fv_fin_liability",
            "a394j": "oci_non_current_assets_held_for_sale_nr",
            "a394e": "oci_unrealized_gl_fvoci_equity",
            "a394r": "oci_gl_hedging_instrument_nr",
            "a394k": "oci_gl_share_associate_jv_nr",
            "a394l": "oci_others_nr",
            "a394m": "oci_income_tax_nr",
            "a3942": "oci_items_not_reclassified",
            "a394a": "oci_exchange_differences_translation",
            "a394n": "oci_non_current_assets_held_for_sale_mr",
            "a394b": "oci_unrealized_gl_fvoci_debt",
            "a394s": "oci_gl_hedging_instrument_mr",
            "a394o": "oci_gl_share_associate_jv_mr",
            "a394p": "oci_others_mr",
            "a394q": "oci_income_tax_mr",
            "a3943": "oci_items_may_be_reclassified",
            "a3944": "oci_attributable_to_nci_pre_acquisition",
            "a3947": "oci_net",
            "a3971": "comprehensive_income",
            "a3950": "profit_loss_attributable_to_owners_of_parent",
            "a3960": "profit_loss_attributable_to_nci",
            "a3964": "profit_loss_attributable_to_former_jce",
            "a3956": "ci_attributable_to_owners_of_parent",
            "a3961": "ci_attributable_to_nci",
            "a3967": "ci_attributable_to_former_jce",
            "a3990": "eps",
            "a211f": "weighted_avg_ordinary_shares_thousands",
            "a399z": "basic_eps_mops",
            "a2111": "common_stock_shares",
            "a2121": "preferred_stock_shares",
            "a2303": "equivalent_shares_stock_dividend",
            "a391z": "profit_seeking_enterprise_income_tax",
            "a2117": "preference_share_dividends",
            "a2402": "ebit",
            "a2403": "ebitda",
            "a240g": "total_treasury_shares",
        }

        df = data.rename(columns=rename_map)

        # Fill required fields
        df["fiscal_period"] = df["no"] if "no" in df.columns else "Q"
        df["fiscal_year"] = df["period_ending"].apply(lambda x: x.year)

        records = df.to_dict("records")
        return [TEJIncomeStatementData.model_validate(d) for d in records]
