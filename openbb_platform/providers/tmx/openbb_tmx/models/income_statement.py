"""TMX Income Statement Model."""

from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.income_statement import (
    IncomeStatementData,
    IncomeStatementQueryParams,
)
from pydantic import Field

from openbb_tmx.utils.choices import literal_choices


class TmxIncomeStatementQueryParams(IncomeStatementQueryParams):
    """TMX Income Statement Query."""

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


class TmxIncomeStatementData(IncomeStatementData):
    """TMX Income Statement Data."""

    __alias_dict__ = {
        "trust_fees_by_commissions": "trust_feesby_commissions",
        "other_cost_of_revenue": "other_costof_revenue",
        "other_general_and_administrative": "other_gand_a",
        "restructuring_and_merger_acquisition_income": "restructring_and_mn_a_income",
        "restructuring_and_merger_and_acquisition": "restructuring_and_mergern_acquisition",
    }

    reported_currency: str | None = Field(
        default=None, description="The currency the statement is reported in."
    )
    total_revenue: float | None = Field(default=None, description="Total revenue.")
    operating_revenue: float | None = Field(
        default=None, description="Operating revenue."
    )
    commission_revenue: float | None = Field(
        default=None, description="Commission revenue."
    )
    fee_revenue_and_other_income: float | None = Field(
        default=None, description="Fee revenue and other income."
    )
    fees: float | None = Field(default=None, description="Fees.")
    fees_and_commissions: float | None = Field(
        default=None, description="Fees and commissions."
    )
    agency_fees_and_commissions: float | None = Field(
        default=None, description="Agency fees and commissions."
    )
    dividend_income: float | None = Field(default=None, description="Dividend income.")
    other_customer_services: float | None = Field(
        default=None, description="Other customer services."
    )
    service_charge_on_depositor_accounts: float | None = Field(
        default=None, description="Service charge on depositor accounts."
    )
    credit_card: float | None = Field(default=None, description="Credit card.")
    securities_activities: float | None = Field(
        default=None, description="Securities activities."
    )
    investment_banking_profit: float | None = Field(
        default=None, description="Investment banking profit."
    )
    trading_gain_loss: float | None = Field(
        default=None, description="Trading gain loss."
    )
    trust_fees_by_commissions: float | None = Field(
        default=None, description="Trust fees by commissions."
    )
    interest_income: float | None = Field(default=None, description="Interest income.")
    interest_income_operating: float | None = Field(
        default=None, description="Interest income operating."
    )
    interest_income_from_loans: float | None = Field(
        default=None, description="Interest income from loans."
    )
    interest_income_from_loans_and_lease: float | None = Field(
        default=None, description="Interest income from loans and lease."
    )
    interest_income_from_securities: float | None = Field(
        default=None, description="Interest income from securities."
    )
    interest_income_from_investment_securities: float | None = Field(
        default=None, description="Interest income from investment securities."
    )
    interest_income_from_deposits: float | None = Field(
        default=None, description="Interest income from deposits."
    )
    interest_income_from_federal_funds_sold_and_securities_purchase_under_agreements_to_resell: (
        float | None
    ) = Field(
        default=None,
        description="Interest income from federal funds sold and securities purchase under agreements to resell.",
    )
    interest_income_from_other_money_market_investments: float | None = Field(
        default=None, description="Interest income from other money market investments."
    )
    other_interest_income: float | None = Field(
        default=None, description="Other interest income."
    )
    interest_expense: float | None = Field(
        default=None, description="Interest expense."
    )
    interest_expense_operating: float | None = Field(
        default=None, description="Interest expense operating."
    )
    interest_expense_for_deposit: float | None = Field(
        default=None, description="Interest expense for deposit."
    )
    interest_expense_for_long_term_debt: float | None = Field(
        default=None, description="Interest expense for long term debt."
    )
    interest_expense_for_long_term_debt_and_capital_securities: float | None = Field(
        default=None,
        description="Interest expense for long term debt and capital securities.",
    )
    interest_expense_for_capitalized_lease_obligations: float | None = Field(
        default=None, description="Interest expense for capitalized lease obligations."
    )
    interest_expense_for_federal_funds_sold_and_securities_purchase_under_agreements_to_resell: (
        float | None
    ) = Field(
        default=None,
        description="Interest expense for federal funds sold and securities purchase under agreements to resell.",
    )
    other_interest_expense: float | None = Field(
        default=None, description="Other interest expense."
    )
    net_interest_income: float | None = Field(
        default=None, description="Net interest income."
    )
    net_operating_interest_income_expense: float | None = Field(
        default=None, description="Net operating interest income expense."
    )
    credit_losses_provision: float | None = Field(
        default=None, description="Credit losses provision."
    )
    interest_income_after_provision_for_loan_loss: float | None = Field(
        default=None, description="Interest income after provision for loan loss."
    )
    non_interest_income: float | None = Field(
        default=None, description="Non interest income."
    )
    other_non_interest_income: float | None = Field(
        default=None, description="Other non interest income."
    )
    non_interest_expense: float | None = Field(
        default=None, description="Non interest expense."
    )
    other_non_interest_expense: float | None = Field(
        default=None, description="Other non interest expense."
    )
    net_occupancy_expense: float | None = Field(
        default=None, description="Net occupancy expense."
    )
    occupancy_and_equipment: float | None = Field(
        default=None, description="Occupancy and equipment."
    )
    gross_premiums_written: float | None = Field(
        default=None, description="Gross premiums written."
    )
    ceded_premiums: float | None = Field(default=None, description="Ceded premiums.")
    net_premiums_written: float | None = Field(
        default=None, description="Net premiums written."
    )
    increase_decrease_in_net_unearned_premium_reserves: float | None = Field(
        default=None, description="Increase decrease in net unearned premium reserves."
    )
    total_premiums_earned: float | None = Field(
        default=None, description="Total premiums earned."
    )
    insurance_and_premiums: float | None = Field(
        default=None, description="Insurance and premiums."
    )
    net_investment_income: float | None = Field(
        default=None, description="Net investment income."
    )
    net_realized_gain_loss_on_investments: float | None = Field(
        default=None, description="Net realized gain loss on investments."
    )
    policy_acquisition_expense: float | None = Field(
        default=None, description="Policy acquisition expense."
    )
    policyholder_benefits_ceded: float | None = Field(
        default=None, description="Policyholder benefits ceded."
    )
    acquisition_expense: float | None = Field(
        default=None, description="Acquisition expense."
    )
    underwriting_expenses: float | None = Field(
        default=None, description="Underwriting expenses."
    )
    insurance_and_claims: float | None = Field(
        default=None, description="Insurance and claims."
    )
    commission_expenses: float | None = Field(
        default=None, description="Commission expenses."
    )
    cost_of_revenue: float | None = Field(default=None, description="Cost of revenue.")
    other_cost_of_revenue: float | None = Field(
        default=None, description="Other cost of revenue."
    )
    gross_profit: float | None = Field(default=None, description="Gross profit.")
    salaries_and_wages: float | None = Field(
        default=None, description="Salaries and wages."
    )
    selling_and_marketing_expense: float | None = Field(
        default=None, description="Selling and marketing expense."
    )
    marketing_expense: float | None = Field(
        default=None, description="Marketing expense."
    )
    promotion_and_advertising: float | None = Field(
        default=None, description="Promotion and advertising."
    )
    general_and_administrative_expense: float | None = Field(
        default=None, description="General and administrative expense."
    )
    other_general_and_administrative: float | None = Field(
        default=None, description="Other general and administrative."
    )
    selling_general_and_administration: float | None = Field(
        default=None, description="Selling general and administration."
    )
    research_and_development: float | None = Field(
        default=None, description="Research and development."
    )
    research_expense: float | None = Field(
        default=None, description="Research expense."
    )
    professional_expense_and_contract_services_expense: float | None = Field(
        default=None, description="Professional expense and contract services expense."
    )
    maintenance_and_repairs: float | None = Field(
        default=None, description="Maintenance and repairs."
    )
    operation_and_maintenance: float | None = Field(
        default=None, description="Operation and maintenance."
    )
    rent_and_landing_fees: float | None = Field(
        default=None, description="Rent and landing fees."
    )
    fuel: float | None = Field(default=None, description="Fuel.")
    equipment: float | None = Field(default=None, description="Equipment.")
    exploration_development_and_mineral_property_lease_expenses: float | None = Field(
        default=None,
        description="Exploration development and mineral property lease expenses.",
    )
    other_taxes: float | None = Field(default=None, description="Other taxes.")
    other_operating_expenses: float | None = Field(
        default=None, description="Other operating expenses."
    )
    operating_expense: float | None = Field(
        default=None, description="Operating expense."
    )
    total_expenses: float | None = Field(default=None, description="Total expenses.")
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
    operating_income: float | None = Field(
        default=None, description="Operating income."
    )
    ebitda: float | None = Field(default=None, description="EBITDA.")
    ebit: float | None = Field(default=None, description="EBIT.")
    interest_income_non_operating: float | None = Field(
        default=None, description="Interest income non operating."
    )
    interest_expense_non_operating: float | None = Field(
        default=None, description="Interest expense non operating."
    )
    net_non_operating_interest_income_expense: float | None = Field(
        default=None, description="Net non operating interest income expense."
    )
    earnings_from_equity_interest: float | None = Field(
        default=None, description="Earnings from equity interest."
    )
    earnings_from_equity_interest_net_of_tax: float | None = Field(
        default=None, description="Earnings from equity interest net of tax."
    )
    earning_loss_of_equity_investments: float | None = Field(
        default=None, description="Earning loss of equity investments."
    )
    gain_on_sale_of_business: float | None = Field(
        default=None, description="Gain on sale of business."
    )
    gain_on_sale_of_ppe: float | None = Field(
        default=None, description="Gain on sale of property, plant and equipment."
    )
    gain_on_sale_of_security: float | None = Field(
        default=None, description="Gain on sale of security."
    )
    impairment_of_capital_assets: float | None = Field(
        default=None, description="Impairment of capital assets."
    )
    other_impairment_of_capital_assets: float | None = Field(
        default=None, description="Other impairment of capital assets."
    )
    write_off: float | None = Field(default=None, description="Write off.")
    restructuring_and_merger_acquisition_income: float | None = Field(
        default=None, description="Restructuring and merger acquisition income."
    )
    restructuring_and_merger_and_acquisition: float | None = Field(
        default=None, description="Restructuring and merger and acquisition."
    )
    special_income_charges: float | None = Field(
        default=None, description="Special income charges."
    )
    other_special_charges: float | None = Field(
        default=None, description="Other special charges."
    )
    misc_other_special_charges: float | None = Field(
        default=None, description="Misc other special charges."
    )
    other_income_expense: float | None = Field(
        default=None, description="Other income expense."
    )
    pretax_income: float | None = Field(default=None, description="Pretax income.")
    tax_provision: float | None = Field(default=None, description="Tax provision.")
    minority_interests: float | None = Field(
        default=None, description="Minority interests."
    )
    net_income_continuous_operations: float | None = Field(
        default=None, description="Net income continuous operations."
    )
    net_income_discontinuous_operations: float | None = Field(
        default=None, description="Net income discontinuous operations."
    )
    other_gain_loss_from_disposition_of_discontinued_operations: float | None = Field(
        default=None,
        description="Other gain loss from disposition of discontinued operations.",
    )
    net_income_extraordinary: float | None = Field(
        default=None, description="Net income extraordinary."
    )
    net_income_from_continuing_and_discontinued_operation: float | None = Field(
        default=None,
        description="Net income from continuing and discontinued operation.",
    )
    net_income: float | None = Field(default=None, description="Net income.")
    preferred_stock_dividends: float | None = Field(
        default=None, description="Preferred stock dividends."
    )
    accrued_preferred_stock_dividends: float | None = Field(
        default=None, description="Accrued preferred stock dividends."
    )
    accretion_on_preferred_stock: float | None = Field(
        default=None, description="Accretion on preferred stock."
    )
    net_income_common_stockholders: float | None = Field(
        default=None, description="Net income common stockholders."
    )
    normalized_income: float | None = Field(
        default=None, description="Normalized income."
    )
    basic_eps: float | None = Field(
        default=None, description="Basic earnings per share."
    )
    diluted_eps: float | None = Field(
        default=None, description="Diluted earnings per share."
    )
    basic_continuous_operations: float | None = Field(
        default=None, description="Basic continuous operations."
    )
    diluted_continuous_operations: float | None = Field(
        default=None, description="Diluted continuous operations."
    )
    basic_discontinuous_operations: float | None = Field(
        default=None, description="Basic discontinuous operations."
    )
    diluted_discontinuous_operations: float | None = Field(
        default=None, description="Diluted discontinuous operations."
    )
    dividend_per_share: float | None = Field(
        default=None, description="Dividend per share."
    )
    basic_average_shares: float | None = Field(
        default=None, description="Basic average shares."
    )
    diluted_average_shares: float | None = Field(
        default=None, description="Diluted average shares."
    )
    shares_outstanding: float | None = Field(
        default=None, description="Shares outstanding."
    )
    share_class_level_shares_outstanding: float | None = Field(
        default=None, description="Share class level shares outstanding."
    )


class TmxIncomeStatementFetcher(
    Fetcher[TmxIncomeStatementQueryParams, list[TmxIncomeStatementData]]
):
    """TMX Income Statement Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> TmxIncomeStatementQueryParams:
        """Transform the query."""
        return TmxIncomeStatementQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: TmxIncomeStatementQueryParams,
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
        results = transform_reports(reports, "income")

        if getattr(query, "as_of_date", None) is not None:
            cutoff = str(query.as_of_date)
            results = [r for r in results if str(r["period_ending"]) <= cutoff]

        if not results:
            raise EmptyDataError(
                f"No income statement data was returned for {query.symbol}."
            )

        return results

    @staticmethod
    def transform_data(
        query: TmxIncomeStatementQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[TmxIncomeStatementData]:
        """Transform the data and validate the model."""
        return [TmxIncomeStatementData.model_validate(d) for d in data]
