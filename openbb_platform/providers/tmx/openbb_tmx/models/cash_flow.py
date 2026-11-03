"""TMX Cash Flow Statement Model."""

from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.cash_flow import (
    CashFlowStatementData,
    CashFlowStatementQueryParams,
)
from pydantic import Field

from openbb_tmx.utils.choices import literal_choices


class TmxCashFlowStatementQueryParams(CashFlowStatementQueryParams):
    """TMX Cash Flow Statement Query."""

    __json_schema_extra__ = {
        "period": {
            "x-widget_config": {"options": literal_choices(("annual", "quarter"))}
        },
    }

    period: Literal["annual", "quarter"] = Field(
        default="annual",
        description="Time period of the data to return.",
    )
    limit: int | None = Field(
        default=None,
        description="The number of periods to return. Every published period"
        + " when not supplied.",
    )
    use_cache: bool = Field(
        default=True,
        description="Whether to use the on-disk response cache. Set to False to bypass.",
    )


class TmxCashFlowStatementData(CashFlowStatementData):
    """TMX Cash Flow Statement Data."""

    reported_currency: str | None = Field(
        default=None, description="The currency the statement is reported in."
    )
    net_income_from_continuing_operations: float | None = Field(
        default=None, description="Net income from continuing operations."
    )
    depreciation: float | None = Field(default=None, description="Depreciation.")
    amortization: float | None = Field(default=None, description="Amortization.")
    amortization_of_intangibles: float | None = Field(
        default=None, description="Amortization of intangibles."
    )
    depletion: float | None = Field(default=None, description="Depletion.")
    depreciation_and_amortization: float | None = Field(
        default=None, description="Depreciation and amortization."
    )
    depreciation_amortization_depletion: float | None = Field(
        default=None, description="Depreciation amortization depletion."
    )
    stock_based_compensation: float | None = Field(
        default=None, description="Stock based compensation."
    )
    deferred_tax: float | None = Field(default=None, description="Deferred tax.")
    deferred_income_tax: float | None = Field(
        default=None, description="Deferred income tax."
    )
    asset_impairment_charge: float | None = Field(
        default=None, description="Asset impairment charge."
    )
    provision_for_loan_lease_and_other_losses: float | None = Field(
        default=None, description="Provision for loan lease and other losses."
    )
    pension_and_employee_benefit_expense: float | None = Field(
        default=None, description="Pension and employee benefit expense."
    )
    operating_gains_losses: float | None = Field(
        default=None, description="Operating gains losses."
    )
    earnings_losses_from_equity_investments: float | None = Field(
        default=None, description="Earnings losses from equity investments."
    )
    gain_loss_on_investment_securities: float | None = Field(
        default=None, description="Gain loss on investment securities."
    )
    gain_loss_on_sale_of_business: float | None = Field(
        default=None, description="Gain loss on sale of business."
    )
    gain_loss_on_sale_of_ppe: float | None = Field(
        default=None, description="Gain loss on sale of property, plant and equipment."
    )
    unrealized_gain_loss_on_investment_securities: float | None = Field(
        default=None, description="Unrealized gain loss on investment securities."
    )
    unrealized_gains_losses_on_derivatives: float | None = Field(
        default=None, description="Unrealized gains losses on derivatives."
    )
    net_foreign_currency_exchange_gain_loss: float | None = Field(
        default=None, description="Net foreign currency exchange gain loss."
    )
    other_non_cash_items: float | None = Field(
        default=None, description="Other non cash items."
    )
    change_in_receivables: float | None = Field(
        default=None, description="Change in receivables."
    )
    changes_in_account_receivables: float | None = Field(
        default=None, description="Changes in account receivables."
    )
    change_in_inventory: float | None = Field(
        default=None, description="Change in inventory."
    )
    change_in_prepaid_assets: float | None = Field(
        default=None, description="Change in prepaid assets."
    )
    change_in_payable: float | None = Field(
        default=None, description="Change in payable."
    )
    change_in_account_payable: float | None = Field(
        default=None, description="Change in account payable."
    )
    change_in_accrued_expense: float | None = Field(
        default=None, description="Change in accrued expense."
    )
    change_in_payables_and_accrued_expense: float | None = Field(
        default=None, description="Change in payables and accrued expense."
    )
    change_in_tax_payable: float | None = Field(
        default=None, description="Change in tax payable."
    )
    change_in_income_tax_payable: float | None = Field(
        default=None, description="Change in income tax payable."
    )
    change_in_interest_payable: float | None = Field(
        default=None, description="Change in interest payable."
    )
    change_in_other_current_assets: float | None = Field(
        default=None, description="Change in other current assets."
    )
    change_in_other_current_liabilities: float | None = Field(
        default=None, description="Change in other current liabilities."
    )
    change_in_other_working_capital: float | None = Field(
        default=None, description="Change in other working capital."
    )
    change_in_working_capital: float | None = Field(
        default=None, description="Change in working capital."
    )
    change_in_loans: float | None = Field(default=None, description="Change in loans.")
    change_in_trading_account_securities: float | None = Field(
        default=None, description="Change in trading account securities."
    )
    change_in_deferred_acquisition_costs: float | None = Field(
        default=None, description="Change in deferred acquisition costs."
    )
    change_in_premiums_receivable: float | None = Field(
        default=None, description="Change in premiums receivable."
    )
    change_in_unearned_premiums: float | None = Field(
        default=None, description="Change in unearned premiums."
    )
    change_in_loss_and_loss_adjustment_expense_reserves: float | None = Field(
        default=None, description="Change in loss and loss adjustment expense reserves."
    )
    change_in_reinsurance_recoverable_on_paid_and_unpaid_losses: float | None = Field(
        default=None,
        description="Change in reinsurance recoverable on paid and unpaid losses.",
    )
    change_in_reinsurance_recoverable_on_unpaid_losses: float | None = Field(
        default=None, description="Change in reinsurance recoverable on unpaid losses."
    )
    increase_decrease_in_deposit: float | None = Field(
        default=None, description="Increase decrease in deposit."
    )
    cash_flow_from_continuing_operating_activities: float | None = Field(
        default=None, description="Cash flow from continuing operating activities."
    )
    cash_from_discontinued_operating_activities: float | None = Field(
        default=None, description="Cash from discontinued operating activities."
    )
    operating_cash_flow: float | None = Field(
        default=None, description="Operating cash flow."
    )
    capital_expenditure: float | None = Field(
        default=None, description="Capital expenditure."
    )
    capital_expenditure_reported: float | None = Field(
        default=None, description="Capital expenditure reported."
    )
    purchase_of_ppe: float | None = Field(
        default=None, description="Purchase of property, plant and equipment."
    )
    sale_of_ppe: float | None = Field(
        default=None, description="Sale of property, plant and equipment."
    )
    net_ppe_purchase_and_sale: float | None = Field(
        default=None, description="Net property, plant and equipment purchase and sale."
    )
    net_capital_expenditure_disposals: float | None = Field(
        default=None, description="Net capital expenditure disposals."
    )
    purchase_of_business: float | None = Field(
        default=None, description="Purchase of business."
    )
    sale_of_business: float | None = Field(
        default=None, description="Sale of business."
    )
    net_business_purchase_and_sale: float | None = Field(
        default=None, description="Net business purchase and sale."
    )
    purchase_of_intangibles: float | None = Field(
        default=None, description="Purchase of intangibles."
    )
    net_intangibles_purchase_and_sale: float | None = Field(
        default=None, description="Net intangibles purchase and sale."
    )
    purchase_of_investment: float | None = Field(
        default=None, description="Purchase of investment."
    )
    sale_of_investment: float | None = Field(
        default=None, description="Sale of investment."
    )
    purchase_of_short_term_investments: float | None = Field(
        default=None, description="Purchase of short term investments."
    )
    sale_of_short_term_investments: float | None = Field(
        default=None, description="Sale of short term investments."
    )
    purchase_of_long_term_investments: float | None = Field(
        default=None, description="Purchase of long term investments."
    )
    sale_of_long_term_investments: float | None = Field(
        default=None, description="Sale of long term investments."
    )
    purchase_of_fixed_maturity_securities: float | None = Field(
        default=None, description="Purchase of fixed maturity securities."
    )
    sales_of_fixed_maturity_securities: float | None = Field(
        default=None, description="Sales of fixed maturity securities."
    )
    calls_maturities_of_maturity_securities: float | None = Field(
        default=None, description="Calls maturities of maturity securities."
    )
    net_investment_purchase_and_sale: float | None = Field(
        default=None, description="Net investment purchase and sale."
    )
    net_investment_properties_purchase_and_sale: float | None = Field(
        default=None, description="Net investment properties purchase and sale."
    )
    payment_for_loans: float | None = Field(
        default=None, description="Payment for loans."
    )
    net_proceeds_payment_for_loan: float | None = Field(
        default=None, description="Net proceeds payment for loan."
    )
    proceeds_payment_in_interest_bearing_deposits_in_bank: float | None = Field(
        default=None,
        description="Proceeds payment in interest bearing deposits in bank.",
    )
    net_other_investing_changes: float | None = Field(
        default=None, description="Net other investing changes."
    )
    cash_flow_from_continuing_investing_activities: float | None = Field(
        default=None, description="Cash flow from continuing investing activities."
    )
    cash_from_discontinued_investing_activities: float | None = Field(
        default=None, description="Cash from discontinued investing activities."
    )
    investing_cash_flow: float | None = Field(
        default=None, description="Investing cash flow."
    )
    issuance_of_debt: float | None = Field(
        default=None, description="Issuance of debt."
    )
    repayment_of_debt: float | None = Field(
        default=None, description="Repayment of debt."
    )
    short_term_debt_issuance: float | None = Field(
        default=None, description="Short term debt issuance."
    )
    short_term_debt_payments: float | None = Field(
        default=None, description="Short term debt payments."
    )
    net_short_term_debt_issuance: float | None = Field(
        default=None, description="Net short term debt issuance."
    )
    long_term_debt_issuance: float | None = Field(
        default=None, description="Long term debt issuance."
    )
    long_term_debt_payments: float | None = Field(
        default=None, description="Long term debt payments."
    )
    net_long_term_debt_issuance: float | None = Field(
        default=None, description="Net long term debt issuance."
    )
    net_issuance_payments_of_debt: float | None = Field(
        default=None, description="Net issuance payments of debt."
    )
    common_stock_issuance: float | None = Field(
        default=None, description="Common stock issuance."
    )
    issuance_of_capital_stock: float | None = Field(
        default=None, description="Issuance of capital stock."
    )
    common_stock_payments: float | None = Field(
        default=None, description="Common stock payments."
    )
    repurchase_of_capital_stock: float | None = Field(
        default=None, description="Repurchase of capital stock."
    )
    net_common_stock_issuance: float | None = Field(
        default=None, description="Net common stock issuance."
    )
    proceeds_from_stock_option_exercised: float | None = Field(
        default=None, description="Proceeds from stock option exercised."
    )
    preferred_stock_issuance: float | None = Field(
        default=None, description="Preferred stock issuance."
    )
    preferred_stock_payments: float | None = Field(
        default=None, description="Preferred stock payments."
    )
    net_preferred_stock_issuance: float | None = Field(
        default=None, description="Net preferred stock issuance."
    )
    cash_dividends_paid: float | None = Field(
        default=None, description="Cash dividends paid."
    )
    common_stock_dividend_paid: float | None = Field(
        default=None, description="Common stock dividend paid."
    )
    preferred_stock_dividend_paid: float | None = Field(
        default=None, description="Preferred stock dividend paid."
    )
    net_other_financing_charges: float | None = Field(
        default=None, description="Net other financing charges."
    )
    cash_flow_from_continuing_financing_activities: float | None = Field(
        default=None, description="Cash flow from continuing financing activities."
    )
    financing_cash_flow: float | None = Field(
        default=None, description="Financing cash flow."
    )
    effect_of_exchange_rate_changes: float | None = Field(
        default=None, description="Effect of exchange rate changes."
    )
    changes_in_cash: float | None = Field(default=None, description="Changes in cash.")
    beginning_cash_position: float | None = Field(
        default=None, description="Beginning cash position."
    )
    end_cash_position: float | None = Field(
        default=None, description="End cash position."
    )
    free_cash_flow: float | None = Field(default=None, description="Free cash flow.")
    income_tax_paid_supplemental_data: float | None = Field(
        default=None, description="Income tax paid supplemental data."
    )
    interest_paid_supplemental_data: float | None = Field(
        default=None, description="Interest paid supplemental data."
    )


class TmxCashFlowStatementFetcher(
    Fetcher[TmxCashFlowStatementQueryParams, list[TmxCashFlowStatementData]]
):
    """TMX Cash Flow Statement Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> TmxCashFlowStatementQueryParams:
        """Transform the query."""
        return TmxCashFlowStatementQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: TmxCashFlowStatementQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Return the raw data from the TMX endpoint."""
        from openbb_core.provider.utils.errors import EmptyDataError

        from openbb_tmx.utils.financials import transform_reports
        from openbb_tmx.utils.helpers import normalize_symbol
        from openbb_tmx.utils.quotemedia import ALL_REPORTS, get_financials

        reports = await get_financials(
            normalize_symbol(query.symbol),
            period=query.period,
            limit=query.limit or ALL_REPORTS,
            use_cache=query.use_cache,
        )
        results = transform_reports(reports, "cash")

        if getattr(query, "as_of_date", None) is not None:
            cutoff = str(query.as_of_date)
            results = [r for r in results if str(r["period_ending"]) <= cutoff]

        if not results:
            raise EmptyDataError(f"No cash flow data was returned for {query.symbol}.")

        return results

    @staticmethod
    def transform_data(
        query: TmxCashFlowStatementQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[TmxCashFlowStatementData]:
        """Transform the data and validate the model."""
        return [TmxCashFlowStatementData.model_validate(d) for d in data]
