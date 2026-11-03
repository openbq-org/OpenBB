"""TMX Balance Sheet Model."""

from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.balance_sheet import (
    BalanceSheetData,
    BalanceSheetQueryParams,
)
from pydantic import Field

from openbb_tmx.utils.choices import literal_choices


class TmxBalanceSheetQueryParams(BalanceSheetQueryParams):
    """TMX Balance Sheet Query."""

    __json_schema_extra__ = {
        "period": {
            "x-widget_config": {"options": literal_choices(("annual", "quarter"))}
        },
    }

    period: Literal["annual", "quarter"] = Field(
        default="annual",
        description="Time period of the data to return.",
    )
    use_cache: bool = Field(
        default=True,
        description="Whether to use the on-disk response cache. Set to False to bypass.",
    )


class TmxBalanceSheetData(BalanceSheetData):
    """TMX Balance Sheet Data."""

    __alias_dict__ = {
        "receivables_adjustments_allowances": "recievables_adjustments_allowances",
        "mortgage_and_consumer_loans": "mortgage_and_consumerloans",
        "securities_agreed_to_be_resold": "security_agree_to_be_resell",
        "total_non_current_liabilities_net_minority_interest": "total_non_current_liabilities_net_minority_interes",
    }

    reported_currency: str | None = Field(
        default=None, description="The currency the statement is reported in."
    )
    cash: float | None = Field(default=None, description="Cash.")
    cash_equivalents: float | None = Field(
        default=None, description="Cash equivalents."
    )
    cash_and_cash_equivalents: float | None = Field(
        default=None, description="Cash and cash equivalents."
    )
    cash_and_due_from_banks: float | None = Field(
        default=None, description="Cash and due from banks."
    )
    restricted_cash: float | None = Field(default=None, description="Restricted cash.")
    restricted_cash_and_cash_equivalents: float | None = Field(
        default=None, description="Restricted cash and cash equivalents."
    )
    restricted_cash_and_investments: float | None = Field(
        default=None, description="Restricted cash and investments."
    )
    restricted_investments: float | None = Field(
        default=None, description="Restricted investments."
    )
    short_term_investments: float | None = Field(
        default=None, description="Short term investments."
    )
    short_term_investments_available_for_sale: float | None = Field(
        default=None, description="Short term investments available for sale."
    )
    cash_cash_equivalents_and_short_term_investments: float | None = Field(
        default=None, description="Cash cash equivalents and short term investments."
    )
    money_market_investments: float | None = Field(
        default=None, description="Money market investments."
    )
    interest_bearing_deposits_assets: float | None = Field(
        default=None, description="Interest bearing deposits assets."
    )
    accounts_receivable: float | None = Field(
        default=None, description="Accounts receivable."
    )
    gross_accounts_receivable: float | None = Field(
        default=None, description="Gross accounts receivable."
    )
    receivables: float | None = Field(default=None, description="Receivables.")
    other_receivables: float | None = Field(
        default=None, description="Other receivables."
    )
    notes_receivable: float | None = Field(
        default=None, description="Notes receivable."
    )
    non_current_note_receivables: float | None = Field(
        default=None, description="Non current note receivables."
    )
    non_current_accounts_receivable: float | None = Field(
        default=None, description="Non current accounts receivable."
    )
    taxes_receivable: float | None = Field(
        default=None, description="Taxes receivable."
    )
    receivables_adjustments_allowances: float | None = Field(
        default=None, description="Receivables adjustments allowances."
    )
    premiums_receivable: float | None = Field(
        default=None, description="Premiums receivable."
    )
    reinsurance_receivables: float | None = Field(
        default=None, description="Reinsurance receivables."
    )
    accrued_investment_income: float | None = Field(
        default=None, description="Accrued investment income."
    )
    inventory: float | None = Field(default=None, description="Inventory.")
    raw_materials: float | None = Field(default=None, description="Raw materials.")
    work_in_process: float | None = Field(default=None, description="Work in process.")
    finished_goods: float | None = Field(default=None, description="Finished goods.")
    purchased_components: float | None = Field(
        default=None, description="Purchased components."
    )
    other_inventories: float | None = Field(
        default=None, description="Other inventories."
    )
    materials_and_supplies: float | None = Field(
        default=None, description="Materials and supplies."
    )
    natural_gas_fuel_and_other: float | None = Field(
        default=None, description="Natural gas fuel and other."
    )
    inventories_adjustments_allowances: float | None = Field(
        default=None, description="Inventories adjustments allowances."
    )
    prepaid_assets: float | None = Field(default=None, description="Prepaid assets.")
    non_current_prepaid_assets: float | None = Field(
        default=None, description="Non current prepaid assets."
    )
    other_current_assets: float | None = Field(
        default=None, description="Other current assets."
    )
    current_deferred_assets: float | None = Field(
        default=None, description="Current deferred assets."
    )
    current_deferred_taxes_assets: float | None = Field(
        default=None, description="Current deferred taxes assets."
    )
    current_assets: float | None = Field(default=None, description="Current assets.")
    gross_loan: float | None = Field(default=None, description="Gross loan.")
    net_loan: float | None = Field(default=None, description="Net loan.")
    commercial_loan: float | None = Field(default=None, description="Commercial loan.")
    consumer_loan: float | None = Field(default=None, description="Consumer loan.")
    mortgage_loan: float | None = Field(default=None, description="Mortgage loan.")
    mortgage_and_consumer_loans: float | None = Field(
        default=None, description="Mortgage and consumer loans."
    )
    loans_receivable: float | None = Field(
        default=None, description="Loans receivable."
    )
    loans_held_for_sale: float | None = Field(
        default=None, description="Loans held for sale."
    )
    other_loan_assets: float | None = Field(
        default=None, description="Other loan assets."
    )
    allowance_for_loans_and_lease_losses: float | None = Field(
        default=None, description="Allowance for loans and lease losses."
    )
    policy_loans: float | None = Field(default=None, description="Policy loans.")
    trading_securities: float | None = Field(
        default=None, description="Trading securities."
    )
    available_for_sale_securities: float | None = Field(
        default=None, description="Available for sale securities."
    )
    held_to_maturity_securities: float | None = Field(
        default=None, description="Held to maturity securities."
    )
    common_stocks_available_for_sale: float | None = Field(
        default=None, description="Common stocks available for sale."
    )
    preferred_stocks_available_for_sale: float | None = Field(
        default=None, description="Preferred stocks available for sale."
    )
    fixed_maturity_investments: float | None = Field(
        default=None, description="Fixed maturity investments."
    )
    fixed_maturities_available_for_sale: float | None = Field(
        default=None, description="Fixed maturities available for sale."
    )
    fixed_maturities_held_to_maturity: float | None = Field(
        default=None, description="Fixed maturities held to maturity."
    )
    securities_and_investments: float | None = Field(
        default=None, description="Securities and investments."
    )
    total_investments: float | None = Field(
        default=None, description="Total investments."
    )
    other_invested_assets: float | None = Field(
        default=None, description="Other invested assets."
    )
    equity_investments: float | None = Field(
        default=None, description="Equity investments."
    )
    investments_and_advances: float | None = Field(
        default=None, description="Investments and advances."
    )
    investments_in_affiliates_subsidiaries_associates_and_joint_ventures: (
        float | None
    ) = Field(
        default=None,
        description="Investments in affiliates subsidiaries associates and joint ventures.",
    )
    investments_in_other_ventures_under_equity_method: float | None = Field(
        default=None, description="Investments in other ventures under equity method."
    )
    real_estate_and_real_estate_joint_ventures_held_for_investment: float | None = (
        Field(
            default=None,
            description="Real estate and real estate joint ventures held for investment.",
        )
    )
    derivative_assets: float | None = Field(
        default=None, description="Derivative assets."
    )
    financial_assets: float | None = Field(
        default=None, description="Financial assets."
    )
    security_borrowed: float | None = Field(
        default=None, description="Security borrowed."
    )
    securities_agreed_to_be_resold: float | None = Field(
        default=None, description="Securities agreed to be resold."
    )
    federal_funds_sold_and_securities_purchase_under_agreements_to_resell: (
        float | None
    ) = Field(
        default=None,
        description="Federal funds sold and securities purchase under agreements to resell.",
    )
    separate_account_assets: float | None = Field(
        default=None, description="Separate account assets."
    )
    bank_owned_life_insurance: float | None = Field(
        default=None, description="Bank owned life insurance."
    )
    gross_ppe: float | None = Field(
        default=None, description="Gross property, plant and equipment."
    )
    accumulated_depreciation: float | None = Field(
        default=None, description="Accumulated depreciation."
    )
    net_ppe: float | None = Field(
        default=None, description="Net property, plant and equipment."
    )
    properties: float | None = Field(default=None, description="Properties.")
    other_properties: float | None = Field(
        default=None, description="Other properties."
    )
    land_and_improvements: float | None = Field(
        default=None, description="Land and improvements."
    )
    buildings_and_improvements: float | None = Field(
        default=None, description="Buildings and improvements."
    )
    machinery_furniture_equipment: float | None = Field(
        default=None, description="Machinery furniture equipment."
    )
    construction_in_progress: float | None = Field(
        default=None, description="Construction in progress."
    )
    flight_fleet_vehicle_and_related_equipments: float | None = Field(
        default=None, description="Flight fleet vehicle and related equipments."
    )
    mineral_properties: float | None = Field(
        default=None, description="Mineral properties."
    )
    leases: float | None = Field(default=None, description="Leases.")
    electric_utility_plant: float | None = Field(
        default=None, description="Electric utility plant."
    )
    common_utility_plant: float | None = Field(
        default=None, description="Common utility plant."
    )
    net_utility_plant: float | None = Field(
        default=None, description="Net utility plant."
    )
    goodwill: float | None = Field(default=None, description="Goodwill.")
    other_intangible_assets: float | None = Field(
        default=None, description="Other intangible assets."
    )
    goodwill_and_other_intangible_assets: float | None = Field(
        default=None, description="Goodwill and other intangible assets."
    )
    deferred_assets: float | None = Field(default=None, description="Deferred assets.")
    deferred_tax_assets: float | None = Field(
        default=None, description="Deferred tax assets."
    )
    deferred_costs: float | None = Field(default=None, description="Deferred costs.")
    other_deferred_costs: float | None = Field(
        default=None, description="Other deferred costs."
    )
    deferred_financing_costs: float | None = Field(
        default=None, description="Deferred financing costs."
    )
    deferred_policy_acquisition_costs: float | None = Field(
        default=None, description="Deferred policy acquisition costs."
    )
    regulatory_assets: float | None = Field(
        default=None, description="Regulatory assets."
    )
    reinsurance_recoverable: float | None = Field(
        default=None, description="Reinsurance recoverable."
    )
    reinsurance_recoverable_for_paid_losses: float | None = Field(
        default=None, description="Reinsurance recoverable for paid losses."
    )
    reinsurance_recoverable_for_unpaid_losses: float | None = Field(
        default=None, description="Reinsurance recoverable for unpaid losses."
    )
    non_current_deferred_assets: float | None = Field(
        default=None, description="Non current deferred assets."
    )
    non_current_deferred_taxes_assets: float | None = Field(
        default=None, description="Non current deferred taxes assets."
    )
    other_assets: float | None = Field(default=None, description="Other assets.")
    other_non_current_assets: float | None = Field(
        default=None, description="Other non current assets."
    )
    total_non_current_assets: float | None = Field(
        default=None, description="Total non current assets."
    )
    total_assets: float | None = Field(default=None, description="Total assets.")
    accounts_payable: float | None = Field(
        default=None, description="Accounts payable."
    )
    other_payable: float | None = Field(default=None, description="Other payable.")
    payables: float | None = Field(default=None, description="Payables.")
    current_accrued_expenses: float | None = Field(
        default=None, description="Current accrued expenses."
    )
    payables_and_accrued_expenses: float | None = Field(
        default=None, description="Payables and accrued expenses."
    )
    income_tax_payable: float | None = Field(
        default=None, description="Income tax payable."
    )
    total_tax_payable: float | None = Field(
        default=None, description="Total tax payable."
    )
    interest_payable: float | None = Field(
        default=None, description="Interest payable."
    )
    dividends_payable: float | None = Field(
        default=None, description="Dividends payable."
    )
    current_notes_payable: float | None = Field(
        default=None, description="Current notes payable."
    )
    line_of_credit: float | None = Field(default=None, description="Line of credit.")
    other_current_borrowings: float | None = Field(
        default=None, description="Other current borrowings."
    )
    current_debt: float | None = Field(default=None, description="Current debt.")
    current_capital_lease_obligation: float | None = Field(
        default=None, description="Current capital lease obligation."
    )
    current_debt_and_capital_lease_obligation: float | None = Field(
        default=None, description="Current debt and capital lease obligation."
    )
    current_deferred_revenue: float | None = Field(
        default=None, description="Current deferred revenue."
    )
    current_deferred_liabilities: float | None = Field(
        default=None, description="Current deferred liabilities."
    )
    current_deferred_taxes_liabilities: float | None = Field(
        default=None, description="Current deferred taxes liabilities."
    )
    current_provisions: float | None = Field(
        default=None, description="Current provisions."
    )
    other_current_liabilities: float | None = Field(
        default=None, description="Other current liabilities."
    )
    current_liabilities: float | None = Field(
        default=None, description="Current liabilities."
    )
    non_interest_bearing_deposits: float | None = Field(
        default=None, description="Non interest bearing deposits."
    )
    interest_bearing_deposits_liabilities: float | None = Field(
        default=None, description="Interest bearing deposits liabilities."
    )
    other_deposits: float | None = Field(default=None, description="Other deposits.")
    total_deposits: float | None = Field(default=None, description="Total deposits.")
    federal_funds_purchased_and_securities_sold_under_agreement_to_repurchase: (
        float | None
    ) = Field(
        default=None,
        description="Federal funds purchased and securities sold under agreement to repurchase.",
    )
    financial_instruments_sold_under_agreements_to_repurchase: float | None = Field(
        default=None,
        description="Financial instruments sold under agreements to repurchase.",
    )
    security_sold_not_yet_repurchased: float | None = Field(
        default=None, description="Security sold not yet repurchased."
    )
    trading_liabilities: float | None = Field(
        default=None, description="Trading liabilities."
    )
    derivative_product_liabilities: float | None = Field(
        default=None, description="Derivative product liabilities."
    )
    bank_acceptance_executed_and_outstanding: float | None = Field(
        default=None, description="Bank acceptance executed and outstanding."
    )
    customer_acceptances: float | None = Field(
        default=None, description="Customer acceptances."
    )
    unearned_premiums: float | None = Field(
        default=None, description="Unearned premiums."
    )
    future_policy_benefits: float | None = Field(
        default=None, description="Future policy benefits."
    )
    policyholder_funds: float | None = Field(
        default=None, description="Policyholder funds."
    )
    reinsurance_balances_payable: float | None = Field(
        default=None, description="Reinsurance balances payable."
    )
    long_term_debt: float | None = Field(default=None, description="Long term debt.")
    long_term_capital_lease_obligation: float | None = Field(
        default=None, description="Long term capital lease obligation."
    )
    long_term_debt_and_capital_lease_obligation: float | None = Field(
        default=None, description="Long term debt and capital lease obligation."
    )
    long_term_provisions: float | None = Field(
        default=None, description="Long term provisions."
    )
    non_current_accrued_expenses: float | None = Field(
        default=None, description="Non current accrued expenses."
    )
    non_current_deferred_revenue: float | None = Field(
        default=None, description="Non current deferred revenue."
    )
    non_current_deferred_liabilities: float | None = Field(
        default=None, description="Non current deferred liabilities."
    )
    non_current_deferred_taxes_liabilities: float | None = Field(
        default=None, description="Non current deferred taxes liabilities."
    )
    employee_benefits: float | None = Field(
        default=None, description="Employee benefits."
    )
    defined_pension_benefit: float | None = Field(
        default=None, description="Defined pension benefit."
    )
    minimum_pension_liabilities: float | None = Field(
        default=None, description="Minimum pension liabilities."
    )
    non_current_pension_and_other_postretirement_benefit_plans: float | None = Field(
        default=None,
        description="Non current pension and other postretirement benefit plans.",
    )
    regulatory_liabilities: float | None = Field(
        default=None, description="Regulatory liabilities."
    )
    total_deferred_credits_and_other_non_current_liabilities: float | None = Field(
        default=None,
        description="Total deferred credits and other non current liabilities.",
    )
    trust_preferred_securities: float | None = Field(
        default=None, description="Trust preferred securities."
    )
    other_liabilities: float | None = Field(
        default=None, description="Other liabilities."
    )
    other_non_current_liabilities: float | None = Field(
        default=None, description="Other non current liabilities."
    )
    total_non_current_liabilities: float | None = Field(
        default=None, description="Total non current liabilities."
    )
    total_non_current_liabilities_net_minority_interest: float | None = Field(
        default=None, description="Total non current liabilities net minority interest."
    )
    total_liabilities: float | None = Field(
        default=None, description="Total liabilities."
    )
    preferred_stock: float | None = Field(default=None, description="Preferred stock.")
    common_stock: float | None = Field(default=None, description="Common stock.")
    capital_stock: float | None = Field(default=None, description="Capital stock.")
    other_capital_stock: float | None = Field(
        default=None, description="Other capital stock."
    )
    additional_paid_in_capital: float | None = Field(
        default=None, description="Additional paid in capital."
    )
    treasury_stock: float | None = Field(default=None, description="Treasury stock.")
    retained_earnings: float | None = Field(
        default=None, description="Retained earnings."
    )
    gains_losses_not_affecting_retained_earnings: float | None = Field(
        default=None, description="Gains losses not affecting retained earnings."
    )
    net_unrealized_gain_loss_investments: float | None = Field(
        default=None, description="Net unrealized gain loss investments."
    )
    net_unrealized_gain_loss_foreign_currency: float | None = Field(
        default=None, description="Net unrealized gain loss foreign currency."
    )
    net_other_unrealized_gain_loss: float | None = Field(
        default=None, description="Net other unrealized gain loss."
    )
    unrealized_gain_loss: float | None = Field(
        default=None, description="Unrealized gain loss."
    )
    other_equity_adjustments: float | None = Field(
        default=None, description="Other equity adjustments."
    )
    other_equity_interest: float | None = Field(
        default=None, description="Other equity interest."
    )
    common_stock_equity: float | None = Field(
        default=None, description="Common stock equity."
    )
    minority_interest: float | None = Field(
        default=None, description="Minority interest."
    )
    stockholders_equity: float | None = Field(
        default=None, description="Stockholders equity."
    )
    total_equity_gross_minority: float | None = Field(
        default=None, description="Total equity gross minority."
    )
    total_equity_gross_minority_interest: float | None = Field(
        default=None, description="Total equity gross minority interest."
    )
    total_liabilities_and_total_equity_gross_minority_interest: float | None = Field(
        default=None,
        description="Total liabilities and total equity gross minority interest.",
    )
    total_capitalization: float | None = Field(
        default=None, description="Total capitalization."
    )
    working_capital: float | None = Field(default=None, description="Working capital.")
    total_employees: int | None = Field(default=None, description="Total employees.")


class TmxBalanceSheetFetcher(
    Fetcher[TmxBalanceSheetQueryParams, list[TmxBalanceSheetData]]
):
    """TMX Balance Sheet Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> TmxBalanceSheetQueryParams:
        """Transform the query."""
        return TmxBalanceSheetQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: TmxBalanceSheetQueryParams,
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
        results = transform_reports(reports, "balance")

        if getattr(query, "as_of_date", None) is not None:
            cutoff = str(query.as_of_date)
            results = [r for r in results if str(r["period_ending"]) <= cutoff]

        if not results:
            raise EmptyDataError(
                f"No balance sheet data was returned for {query.symbol}."
            )

        return results

    @staticmethod
    def transform_data(
        query: TmxBalanceSheetQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[TmxBalanceSheetData]:
        """Transform the data and validate the model."""
        return [TmxBalanceSheetData.model_validate(d) for d in data]
