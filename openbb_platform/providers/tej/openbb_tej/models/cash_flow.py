from __future__ import annotations
import datetime as dt
from typing import Any, List, Optional
import tejapi
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.cash_flow import (
    CashFlowStatementData,
    CashFlowStatementQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

class TEJCashFlowStatementQueryParams(CashFlowStatementQueryParams):
    """TEJ Cash Flow Statement Query."""
    start_date: Optional[dt.date] = Field(
        default=None,
        description="Start date of the data, in YYYY-MM-DD format.",
    )
    end_date: Optional[dt.date] = Field(
        default=None,
        description="End date of the data, in YYYY-MM-DD format.",
    )

class TEJCashFlowStatementData(CashFlowStatementData):
    """TEJ Cash Flow Statement Data."""

    # Standard OpenBB Fields
    operating_cash_flow: float | None = Field(default=None, description="Net cash flows from (used in) operating activities")
    investing_cash_flow: float | None = Field(default=None, description="Net cash flows from (used in) investing activities")
    financing_cash_flow: float | None = Field(default=None, description="Net cash flows from (used in) financing activities")
    free_cash_flow: float | None = Field(default=None, description="Free Cash Flow")
    announcement_date: Optional[dt.date] | str | None = Field(default=None, description="Announcement Date (key3)")

    # CFO - Adjustments
    pre_tax_income_cfo: float | None = Field(default=None, description="Pre-Tax income - CFO")
    depreciation_expense_cfo: float | None = Field(default=None, description="Depreciation expense - CFO")
    amortization_expense_cfo: float | None = Field(default=None, description="Amortization expense - CFO")
    lg_expected_credit_impairment_cfo: float | None = Field(default=None, description="L(G) on expected credit impairment - CFO")
    net_lg_fin_assets_liabilities_fvpl_cfo: float | None = Field(default=None, description="Net L(G) on fin. assets or liabilities at FVPL - CFO")
    lg_derecognition_fin_assets_ac_cfo: float | None = Field(default=None, description="L(G) on derecognition of fin. assets measured at AC - CFO")
    lg_fin_assets_reclassification_cfo: float | None = Field(default=None, description="L(G) on fin. assets reclassification - CFO")
    increase_decrease_inventory_valuation_cfo: float | None = Field(default=None, description="Increase (Decrease) in loss on inventory valuation - CFO")
    interest_expense_cfo: float | None = Field(default=None, description="Interest expense - CFO")
    inventory_shortages_loss_disposal_cfo: float | None = Field(default=None, description="Inventory shortages (overages) and loss on disposal of inventory - CFO")
    interest_income_cfo: float | None = Field(default=None, description="Interest income - CFO")
    dividend_income_cfo: float | None = Field(default=None, description="Dividend income - CFO")
    share_based_payments_cfo: float | None = Field(default=None, description="Share-based payments - CFO")
    share_of_profit_associates_jvs_cfo: float | None = Field(default=None, description="Share of profit of associates & JVs (equity method) - CFO")
    share_of_loss_associates_jvs_cfo: float | None = Field(default=None, description="Share of loss of associates & JVs (equity method) - CFO")
    gain_on_disposal_fixed_assets_cfo: float | None = Field(default=None, description="Gain on disposal of fixed assets - CFO")
    loss_on_disposal_fixed_assets_cfo: float | None = Field(default=None, description="Loss on disposal of fixed assets - CFO")
    lg_disposal_investment_properties_cfo: float | None = Field(default=None, description="L(G) on disposal of investment properties - CFO")
    lg_disposal_intangible_assets_cfo: float | None = Field(default=None, description="L(G) on disposal of intangible assets - CFO")
    lg_disposal_investments_equity_method_cfo: float | None = Field(default=None, description="L(G) on disposal of investments (equity method) - CFO")
    lg_disposal_investments_cfo: float | None = Field(default=None, description="L(G) on disposal of investments - CFO")
    impairment_loss_fin_assets_cfo: float | None = Field(default=None, description="Impairment loss on fin. assets - CFO")
    reversal_impairment_loss_fin_assets_cfo: float | None = Field(default=None, description="Reversal of impairment loss on fin. assets - CFO")
    impairment_loss_non_fin_assets_cfo: float | None = Field(default=None, description="Impairment loss on non-fin. assets - CFO")
    reversal_impairment_loss_non_fin_assets_cfo: float | None = Field(default=None, description="Reversal of impairment loss on non-fin. assets - CFO")
    lg_corporate_bonds_repurchases_cfo: float | None = Field(default=None, description="L(G) on corporate bonds repurchases - CFO")
    provision_of_reserve_cfo: float | None = Field(default=None, description="Provision of reserve - CFO")
    reversal_of_reserve_cfo: float | None = Field(default=None, description="Reversal of reserve - CFO")

    # CFO - Working Capital Changes
    decrease_increase_fin_assets_fvpl_cfo: float | None = Field(default=None, description="Decrease (Increase) in fin. assets at FVPL - CFO")
    decrease_increase_fin_assets_hedging_cfo: float | None = Field(default=None, description="Decrease (Increase) in fin. assets for hedging - CFO")
    decrease_increase_contract_assets_cfo: float | None = Field(default=None, description="Decrease (Increase) in contract assets - CFO")
    decrease_increase_accounts_receivable_cfo: float | None = Field(default=None, description="Decrease (Increase) in accounts receivable - CFO")
    decrease_increase_other_accounts_receivable_cfo: float | None = Field(default=None, description="Decrease (Increase) in other accounts receivable - CFO")
    decrease_increase_inventories_cfo: float | None = Field(default=None, description="Decrease (Increase) in inventories - CFO")
    decrease_increase_prepayments_cfo: float | None = Field(default=None, description="Decrease (Increase) in prepayments - CFO")
    decrease_increase_biological_assets_cfo: float | None = Field(default=None, description="Decrease (Increase) in biological assets - CFO")
    decrease_increase_other_fin_assets_cfo: float | None = Field(default=None, description="Decrease (Increase) in other fin. assets - CFO")
    increase_decrease_fin_liabilities_fvpl_cfo: float | None = Field(default=None, description="Increase (Decrease) in fin. liabilities at FVPL - CFO")
    increase_decrease_fin_liabilities_hedging_cfo: float | None = Field(default=None, description="Increase (Decrease) in fin. liabilities for hedging - CFO")
    increase_decrease_contract_liabilities_cfo: float | None = Field(default=None, description="Increase (Decrease) in contract liabilities - CFO")
    increase_decrease_accounts_payable_cfo: float | None = Field(default=None, description="Increase (Decrease) in accounts payable - CFO")
    increase_decrease_other_accounts_payable_cfo: float | None = Field(default=None, description="Increase (Decrease) in other accounts payable - CFO")
    increase_decrease_other_fin_liabilities_cfo: float | None = Field(default=None, description="Increase (Decrease) in other fin. liabilities - CFO")
    increase_decrease_provisions_cfo: float | None = Field(default=None, description="Increase (Decrease) in provisions - CFO")
    employee_pension_provision_cfo: float | None = Field(default=None, description="Employee pension provision - CFO")
    employee_pension_payment_cfo: float | None = Field(default=None, description="Employee pension payment - CFO")

    # CFO - Interest, Dividends, Tax
    interest_received_cfo: float | None = Field(default=None, description="Interest received - CFO")
    dividends_received_cfo: float | None = Field(default=None, description="Dividends received - CFO")
    interest_paid_cfo: float | None = Field(default=None, description="Interest paid - CFO")
    dividends_paid_cfo: float | None = Field(default=None, description="Dividends paid - CFO")
    income_taxes_refund_paid_cfo: float | None = Field(default=None, description="Income taxes refund (paid) - CFO")
    other_adjustment_cfo: float | None = Field(default=None, description="Other adjustment - CFO")

    # CFI - Investing Activities
    decrease_increase_fin_assets_fvpl_cfi: float | None = Field(default=None, description="Decrease (Increase) in fin. assets at FVPL - CFI")
    decrease_increase_fin_assets_fvoci_cfi: float | None = Field(default=None, description="Decrease (Increase) in fin. assets at FVOCI - CFI")
    decrease_increase_fin_assets_ac_cfi: float | None = Field(default=None, description="Decrease (Increase) in fin. assets measured at AC - CFI")
    decrease_increase_hedging_fin_cfi: float | None = Field(default=None, description="Decrease (Increase) in hedging fin. assets & liabilities - CFI")
    increase_decrease_receivables_cfi: float | None = Field(default=None, description="Increase (Decrease) in receivables - CFI")
    purchase_long_term_investments_cfi: float | None = Field(default=None, description="Purchase of long-term investments - CFI")
    sale_long_term_investments_cfi: float | None = Field(default=None, description="Sale of long-term investments - CFI")
    purchase_fixed_assets_cfi: float | None = Field(default=None, description="Purchase of fixed assets - CFI")
    sale_fixed_assets_cfi: float | None = Field(default=None, description="Sale of fixed assets - CFI")
    decrease_increase_investment_properties_cfi: float | None = Field(default=None, description="Decrease (Increase) in investment properties - CFI")
    decrease_increase_intangible_assets_cfi: float | None = Field(default=None, description="Decrease (Increase) in intangible assets - CFI")
    decrease_increase_other_fin_assets_cfi: float | None = Field(default=None, description="Decrease (Increase) in other fin. assets - CFI")
    net_cash_flow_acquisition_subsidiaries_cfi: float | None = Field(default=None, description="Net cash flow from acquisition of subsidiaries - CFI")
    cash_acquired_from_merger_cfi: float | None = Field(default=None, description="Cash acquired from merger - CFI")
    cash_outflow_disposal_subsidiaries_cfi: float | None = Field(default=None, description="Cash outflow from disposal of subsidiaries - CFI")
    interest_received_cfi: float | None = Field(default=None, description="Interest received - CFI")
    dividends_received_cfi: float | None = Field(default=None, description="Dividends received - CFI")
    income_taxes_refund_paid_cfi: float | None = Field(default=None, description="Income taxes refund (paid) - CFI")
    other_adjustment_cfi: float | None = Field(default=None, description="Other adjustment - CFI")

    # CFF - Financing Activities
    increase_decrease_short_term_debt_cff: float | None = Field(default=None, description="Increase (Decrease) in short-term debt - CFF")
    increase_decrease_short_term_notes_bills_cff: float | None = Field(default=None, description="Increase (Decrease) in short-term notes and bills payable - CFF")
    proceeds_issuing_bonds_cff: float | None = Field(default=None, description="Proceeds from issuing bonds - CFF")
    repayments_bonds_cff: float | None = Field(default=None, description="Repayments of bonds - CFF")
    increase_long_term_debt_cff: float | None = Field(default=None, description="Increase in long-term debt - CFF")
    repayments_long_term_debts_cff: float | None = Field(default=None, description="Repayments of long-term debts - CFF")
    proceeds_issuing_preference_share_liabilities_cff: float | None = Field(default=None, description="Proceeds from issuing preference share liabilities - CFF")
    repayments_preference_share_liabilities_cff: float | None = Field(default=None, description="Repayments of preference share liabilities - CFF")
    decrease_increase_treasury_shares_cff: float | None = Field(default=None, description="Decrease (Increase) in treasury shares - CFF")
    proceeds_capital_increase_decrease_cff: float | None = Field(default=None, description="Proceeds from capital increase (decrease) - CFF")
    exercise_employee_share_options_cff: float | None = Field(default=None, description="Exercise of employee share options - CFF")
    cash_dividends_paid_cff: float | None = Field(default=None, description="Cash dividends paid - CFF")
    increase_decrease_fin_liabilities_fvpl_cff: float | None = Field(default=None, description="Increase (Decrease) in fin. liabilities at FVPL - CFF")
    increase_decrease_fin_liabilities_ac_cff: float | None = Field(default=None, description="Increase (decrease) in fin. liabilities measured at AC - CFF")
    increase_decrease_hedging_fin_instruments_cff: float | None = Field(default=None, description="Increase (Decrease) in hedging fin. instruments - CFF")
    increase_decrease_other_fin_liabilities_cff: float | None = Field(default=None, description="Increase (Decrease) in other fin. liabilities - CFF")
    changes_in_nci_cff: float | None = Field(default=None, description="Changes in NCI - CFF")
    acquisition_ownership_subsidiaries_cff: float | None = Field(default=None, description="Acquisition of ownership interests in subsidiaries - CFF")
    disposal_ownership_subsidiaries_cff: float | None = Field(default=None, description="Disposal of ownership interests in subsidiaries (without losing control) - CFF")
    interest_paid_cff: float | None = Field(default=None, description="Interest paid - CFF")
    income_taxes_refund_paid_cff: float | None = Field(default=None, description="Income taxes refund (paid) - CFF")
    other_adjustment_cff: float | None = Field(default=None, description="Other adjustment - CFF")

    # Summary
    effect_of_exchange_rate_changes: float | None = Field(default=None, description="Effect of exchange rate changes on cash and cash equivalents")
    cash_flows_during_current_period: float | None = Field(default=None, description="Cash flows during current period")
    cash_equivalents_beginning_of_period: float | None = Field(default=None, description="Cash and cash equivalents at beginning of period")
    cash_equivalents_end_of_period: float | None = Field(default=None, description="Cash and cash equivalents at end of period")


class TEJCashFlowStatementFetcher(
    Fetcher[
        TEJCashFlowStatementQueryParams,
        List[TEJCashFlowStatementData],
    ]
):
    """TEJ Cash Flow Statement Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> TEJCashFlowStatementQueryParams:
        return TEJCashFlowStatementQueryParams(**params)

    @staticmethod
    def extract_data(
        query: TEJCashFlowStatementQueryParams,
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
            # CFO - Adjustments
            "a7002", "a7211", "a7212", "a7513", "a721p", "a721r", "a721s", "a7532",
            "a721k", "a7533", "a721j", "a7333", "a7227", "a7213", "a7214", "a7221",
            "a7222", "a722f", "a722g", "a7233", "a7234", "a723h", "a723m", "a7225",
            "a7224", "a722h", "a7243", "a7244",
            # CFO - Working Capital
            "a7231", "a723e", "a727l", "a7511", "a7521", "a7531", "a7278", "a727n",
            "a723f", "a7232", "a723j", "a7515", "a7512", "a7280", "a723l", "a7546",
            "a7253", "a7510",
            # CFO - Interest, Dividends, Tax
            "a720c", "a724l", "a7714", "a7713", "a7721", "a729c", "a7210",
            # CFI - Investing
            "a736c", "a7362", "a736d", "a736e", "a7331", "a7336", "a7335", "a7324",
            "a7323", "a7340", "a7560", "a7368", "a7350", "a7352", "a7353", "a739c",
            "a739b", "a739d", "a739e", "a7300",
            # CFF - Financing
            "a7411", "a7412", "a7443", "a7444", "a7441", "a7442", "a7448", "a7449",
            "a7446", "a7445", "a7447", "a7611", "a7431", "a7433", "a7430", "a7432",
            "a7470", "a744a", "a74ab", "a7712", "a7460", "a749b", "a7400",
            # Summary
            "a7700", "a7800", "a7910", "a7920",
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
        query: TEJCashFlowStatementQueryParams, data: Any, **kwargs: Any
    ) -> List[TEJCashFlowStatementData]:
        if data is None or data.empty:
             raise EmptyDataError("No data returned.")

        rename_map = {
            "mdate": "period_ending",
            "key3": "announcement_date",

            # CFO - Adjustments
            "a7002": "pre_tax_income_cfo",
            "a7211": "depreciation_expense_cfo",
            "a7212": "amortization_expense_cfo",
            "a7513": "lg_expected_credit_impairment_cfo",
            "a721p": "net_lg_fin_assets_liabilities_fvpl_cfo",
            "a721r": "lg_derecognition_fin_assets_ac_cfo",
            "a721s": "lg_fin_assets_reclassification_cfo",
            "a7532": "increase_decrease_inventory_valuation_cfo",
            "a721k": "interest_expense_cfo",
            "a7533": "inventory_shortages_loss_disposal_cfo",
            "a721j": "interest_income_cfo",
            "a7333": "dividend_income_cfo",
            "a7227": "share_based_payments_cfo",
            "a7213": "share_of_profit_associates_jvs_cfo",
            "a7214": "share_of_loss_associates_jvs_cfo",
            "a7221": "gain_on_disposal_fixed_assets_cfo",
            "a7222": "loss_on_disposal_fixed_assets_cfo",
            "a722f": "lg_disposal_investment_properties_cfo",
            "a722g": "lg_disposal_intangible_assets_cfo",
            "a7233": "lg_disposal_investments_equity_method_cfo",
            "a7234": "lg_disposal_investments_cfo",
            "a723h": "impairment_loss_fin_assets_cfo",
            "a723m": "reversal_impairment_loss_fin_assets_cfo",
            "a7225": "impairment_loss_non_fin_assets_cfo",
            "a7224": "reversal_impairment_loss_non_fin_assets_cfo",
            "a722h": "lg_corporate_bonds_repurchases_cfo",
            "a7243": "provision_of_reserve_cfo",
            "a7244": "reversal_of_reserve_cfo",

            # CFO - Working Capital
            "a7231": "decrease_increase_fin_assets_fvpl_cfo",
            "a723e": "decrease_increase_fin_assets_hedging_cfo",
            "a727l": "decrease_increase_contract_assets_cfo",
            "a7511": "decrease_increase_accounts_receivable_cfo",
            "a7521": "decrease_increase_other_accounts_receivable_cfo",
            "a7531": "decrease_increase_inventories_cfo",
            "a7278": "decrease_increase_prepayments_cfo",
            "a727n": "decrease_increase_biological_assets_cfo",
            "a723f": "decrease_increase_other_fin_assets_cfo",
            "a7232": "increase_decrease_fin_liabilities_fvpl_cfo",
            "a723j": "increase_decrease_fin_liabilities_hedging_cfo",
            "a7515": "increase_decrease_contract_liabilities_cfo",
            "a7512": "increase_decrease_accounts_payable_cfo",
            "a7280": "increase_decrease_other_accounts_payable_cfo",
            "a723l": "increase_decrease_other_fin_liabilities_cfo",
            "a7546": "increase_decrease_provisions_cfo",
            "a7253": "employee_pension_provision_cfo",
            "a7510": "employee_pension_payment_cfo",

            # CFO - Interest, Dividends, Tax
            "a720c": "interest_received_cfo",
            "a724l": "dividends_received_cfo",
            "a7714": "interest_paid_cfo",
            "a7713": "dividends_paid_cfo",
            "a7721": "income_taxes_refund_paid_cfo",
            "a729c": "other_adjustment_cfo",
            "a7210": "operating_cash_flow",

            # CFI - Investing
            "a736c": "decrease_increase_fin_assets_fvpl_cfi",
            "a7362": "decrease_increase_fin_assets_fvoci_cfi",
            "a736d": "decrease_increase_fin_assets_ac_cfi",
            "a736e": "decrease_increase_hedging_fin_cfi",
            "a7331": "increase_decrease_receivables_cfi",
            "a7336": "purchase_long_term_investments_cfi",
            "a7335": "sale_long_term_investments_cfi",
            "a7324": "purchase_fixed_assets_cfi",
            "a7323": "sale_fixed_assets_cfi",
            "a7340": "decrease_increase_investment_properties_cfi",
            "a7560": "decrease_increase_intangible_assets_cfi",
            "a7368": "decrease_increase_other_fin_assets_cfi",
            "a7350": "net_cash_flow_acquisition_subsidiaries_cfi",
            "a7352": "cash_acquired_from_merger_cfi",
            "a7353": "cash_outflow_disposal_subsidiaries_cfi",
            "a739c": "interest_received_cfi",
            "a739b": "dividends_received_cfi",
            "a739d": "income_taxes_refund_paid_cfi",
            "a739e": "other_adjustment_cfi",
            "a7300": "investing_cash_flow",

            # CFF - Financing
            "a7411": "increase_decrease_short_term_debt_cff",
            "a7412": "increase_decrease_short_term_notes_bills_cff",
            "a7443": "proceeds_issuing_bonds_cff",
            "a7444": "repayments_bonds_cff",
            "a7441": "increase_long_term_debt_cff",
            "a7442": "repayments_long_term_debts_cff",
            "a7448": "proceeds_issuing_preference_share_liabilities_cff",
            "a7449": "repayments_preference_share_liabilities_cff",
            "a7446": "decrease_increase_treasury_shares_cff",
            "a7445": "proceeds_capital_increase_decrease_cff",
            "a7447": "exercise_employee_share_options_cff",
            "a7611": "cash_dividends_paid_cff",
            "a7431": "increase_decrease_fin_liabilities_fvpl_cff",
            "a7433": "increase_decrease_fin_liabilities_ac_cff",
            "a7430": "increase_decrease_hedging_fin_instruments_cff",
            "a7432": "increase_decrease_other_fin_liabilities_cff",
            "a7470": "changes_in_nci_cff",
            "a744a": "acquisition_ownership_subsidiaries_cff",
            "a74ab": "disposal_ownership_subsidiaries_cff",
            "a7712": "interest_paid_cff",
            "a7460": "income_taxes_refund_paid_cff",
            "a749b": "other_adjustment_cff",
            "a7400": "financing_cash_flow",

            # Summary
            "a7700": "effect_of_exchange_rate_changes",
            "a7800": "cash_flows_during_current_period",
            "a7910": "cash_equivalents_beginning_of_period",
            "a7920": "cash_equivalents_end_of_period",
        }

        df = data.rename(columns=rename_map)
        df["fiscal_period"] = df["no"] if "no" in df.columns else "Q"
        df["fiscal_year"] = df["period_ending"].apply(lambda x: x.year)

        records = df.to_dict("records")
        return [TEJCashFlowStatementData.model_validate(d) for d in records]
