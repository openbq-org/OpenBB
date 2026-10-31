"""SEC Income Statement Model."""

from math import isnan
from typing import Any, Literal
from warnings import warn

from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.income_statement import (
    IncomeStatementData,
    IncomeStatementQueryParams,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import ConfigDict, Field, model_serializer, model_validator


class SecIncomeStatementQueryParams(IncomeStatementQueryParams):
    """SEC IncomeStatement Query.

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


class SecIncomeStatementData(IncomeStatementData):
    """SEC IncomeStatement Data."""

    model_config = ConfigDict(
        allow_inf_nan=True,
        ser_json_inf_nan="null",
        json_schema_extra={
            "x-widget_config": {"$.data": {"table": {"enableFormulas": True}}}
        },
    )

    reported_currency: str | None = Field(
        default=None,
        description="The currency in which the income statement is reported.",
    )
    operating_revenue: float | None = Field(
        default=None,
        description="Amount of revenue recognized from goods sold, services rendered, insurance premiums, or other "
        "activities that constitute an earning process. Includes, but is not limited to, investment and interest income "
        "before deduction of interest expense when recognized as a component of revenue, and sales and trading gain "
        "(loss).",
    )
    other_revenue: float | None = Field(
        default=None,
        description="Revenues from the sale of other goods or rendering of other services, not elsewhere specified in "
        "the taxonomy; net of (reduced by) sales adjustments, returns, allowances, and discounts.",
    )
    total_revenue: float | None = Field(
        default=None,
        description="Amount of revenue recognized from goods sold, services rendered, insurance premiums, or other "
        "activities that constitute an earning process. Includes, but is not limited to, investment and interest income "
        "before deduction of interest expense when recognized as a component of revenue, and sales and trading gain "
        "(loss).",
    )
    operating_cost_of_revenue: float | None = Field(
        default=None,
        description="The aggregate costs related to goods produced and sold and services rendered by an entity during "
        "the reporting period. This excludes costs incurred during the reporting period related to financial services "
        "rendered and other revenue generating activities.",
    )
    other_cost_of_revenue: float | None = Field(
        default=None,
        description="Other costs incurred during the reporting period related to other revenue generating activities.",
    )
    total_cost_of_revenue: float | None = Field(
        default=None,
        description="The aggregate costs related to goods produced and sold and services rendered by an entity during "
        "the reporting period. This excludes costs incurred during the reporting period related to financial services "
        "rendered and other revenue generating activities.",
    )
    excise_and_sales_taxes: float | None = Field(
        default=None,
        description="Amount of excise and sales taxes included in revenue.",
    )
    total_gross_profit: float | None = Field(
        default=None,
        description="Aggregate revenue less cost of goods and services sold or operating expenses directly attributable "
        "to the revenue generation activity.",
    )
    sga_expense: float | None = Field(
        default=None,
        description="The aggregate total costs related to selling a firm's product and services, as well as all other "
        "general and administrative expenses. Direct selling expenses (for example, credit, warranty, and advertising) "
        "are expenses that can be directly linked to the sale of specific products. Indirect selling expenses are "
        "expenses that cannot be directly linked to the sale of specific products, for example telephone expenses, "
        "Internet, and postal charges. General and administrative expenses include salaries of non-sales personnel, "
        "rent, utilities, communication, etc.",
    )
    rd_expense: float | None = Field(
        default=None,
        description="Amount of expense for research and development. Includes, but is not limited to, cost for computer "
        "software product to be sold, leased, or otherwise marketed and writeoff of research and development assets "
        "acquired in transaction other than business combination or joint venture formation or both. Excludes write-down "
        "of intangible asset acquired in business combination or from joint venture formation or both, used in research "
        "and development activity.",
    )
    exploration_expense: float | None = Field(
        default=None,
        description="Exploration expenses (including prospecting) related to oil and gas producing entities and would be "
        "included in operating expenses of that entity. Costs incurred in identifying areas that may warrant examination "
        "and in examining specific areas that are considered to have prospects of containing oil and gas reserves, "
        "including costs of drilling exploratory wells and exploratory-type stratigraphic test wells. Exploration costs "
        "may be incurred both before acquiring the related property (sometimes referred to in part as prospecting costs) "
        "and after acquiring the property. Principal types of exploration costs, which include depreciation and "
        "applicable operating costs of support equipment and facilities and other costs of exploration activities, are: "
        "(i) Costs of topographical, geographical and geophysical studies, rights of access to properties to conduct "
        "those studies, and salaries and other expenses of geologists, geophysical crews, and others conducting those "
        'studies. Collectively, these are sometimes referred to as geological and geophysical or "G&G" costs. (ii) '
        "Costs of carrying and retaining undeveloped properties, such as delay rentals, ad valorem taxes on properties, "
        "legal costs for title defense, and the maintenance of land and lease records. (iii) Dry hole contributions and "
        "bottom hole contributions. (iv) Costs of drilling and equipping exploratory wells. (v) Costs of drilling "
        "exploratory-type stratigraphic test wells.",
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
    depletion_expense: float | None = Field(
        default=None,
        description="The noncash expense charged against earnings to recognize the consumption of natural resources.",
    )
    other_operating_expenses: float | None = Field(
        default=None,
        description="The net amount of other operating income and expenses, the components of which are not separately "
        "disclosed on the income statement, from items that are associated with the entity's normal revenue producing "
        "operations.",
    )
    impairment_expense: float | None = Field(
        default=None,
        description="Amount of impairment loss for asset. Includes, but is not limited to, tangible and intangible "
        "assets and goodwill.",
    )
    restructuring_charge: float | None = Field(
        default=None,
        description="Amount of expenses associated with exit or disposal activities pursuant to an authorized plan. "
        "Excludes expenses related to a discontinued operation or an asset retirement obligation.",
    )
    other_special_charges: float | None = Field(
        default=None,
        description="Amount of restructuring charges, remediation cost, and asset impairment loss.",
    )
    total_operating_expenses: float | None = Field(
        default=None,
        description="Generally recurring costs associated with normal operations except for the portion of these "
        "expenses which can be clearly related to production and included in cost of sales or services. Includes "
        "selling, general and administrative expense.",
    )
    costs_and_expenses: float | None = Field(
        default=None,
        description="Total costs of sales and operating expenses for the period.",
    )
    total_operating_income: float | None = Field(
        default=None,
        description="The net result for the period of deducting operating expenses from operating revenues.",
    )
    loans_and_lease_interest_income: float | None = Field(
        default=None,
        description="The aggregate interest and fee income generated by: (1) loans the Entity has positive intent and "
        "ability to hold for the foreseeable future, or until maturity or payoff, including commercial and consumer "
        "loans, whether domestic or foreign, which may consist of: (a) industrial and agricultural; (b) real estate; and "
        "(c) real estate construction loans; (d) trade financing; (e) lease financing; (f) home equity lines-of-credit; "
        "(g) automobile and other vehicle loans; and (h) credit card and other revolving-type loans and (2) loans and "
        "leases held-for-sale which may include mortgage loans, direct financing, and sales-type leases.",
    )
    investment_securities_interest_income: float | None = Field(
        default=None,
        description="Amount of operating interest income, including amortization and accretion of premiums and "
        "discounts, on securities subject to state, federal and other income tax.",
    )
    deposits_interest_income: float | None = Field(
        default=None,
        description="Interest income derived from funds deposited with both domestic and foreign financial institutions "
        "including funds in money market and other accounts.",
    )
    fed_funds_and_repo_interest_income: float | None = Field(
        default=None,
        description="The aggregate interest income earned from (1) the lending of excess federal funds to another "
        "commercial bank requiring such for its legal reserve requirements and (2) securities purchased under agreements "
        "to resell.",
    )
    trading_account_interest_income: float | None = Field(
        default=None,
        description="Interest and dividend income on securities that are bought and held principally for the purpose of "
        'selling them in the near term ("trading securities") and on securities measured at fair value through '
        "earnings.",
    )
    other_interest_income: float | None = Field(
        default=None,
        description="Amount of interest income earned from interest bearing assets classified as other.",
    )
    total_interest_income: float | None = Field(
        default=None,
        description="Amount of operating interest income, including, but not limited to, amortization and accretion of "
        "premiums and discounts on securities.",
    )
    deposits_interest_expense: float | None = Field(
        default=None,
        description="Aggregate amount of interest expense on all deposits.",
    )
    short_term_borrowing_interest_expense: float | None = Field(
        default=None,
        description="The aggregate interest expense incurred on short-term borrowings including commercial paper and "
        "Federal funds purchased and securities sold under agreements to repurchase.",
    )
    long_term_debt_interest_expense: float | None = Field(
        default=None,
        description="Aggregate amount of interest paid or due on all long-term debt.",
    )
    fed_funds_and_repo_interest_expense: float | None = Field(
        default=None,
        description="The aggregate expense incurred on federal funds purchased and securities sold under agreements to "
        "repurchase. If amounts recognized as payables under repurchase agreements have been offset against amounts "
        "recognized as receivables under reverse repurchase agreements and reported as a net amount on the balance "
        "sheet, the income and expense from these agreements may be reported on a net basis.",
    )
    capitalized_lease_obligation_interest_expense: float | None = Field(
        default=None,
        description="Amount of interest expense on finance lease liability.",
    )
    other_interest_expense: float | None = Field(
        default=None,
        description="Amount of interest expense classified as other.",
    )
    total_interest_expense: float | None = Field(
        default=None,
        description="Amount of interest expense classified as operating.",
    )
    net_interest_income: float | None = Field(
        default=None,
        description="Amount of interest income (expense) classified as operating.",
    )
    revenues_excl_interest_dividends: float | None = Field(
        default=None,
        description="Revenue excluding interest and dividend income (securities firms).",
    )
    trust_fee_income: float | None = Field(
        default=None,
        description="Revenue recognized in the period for (1) performance (incentive) fees based on the investment "
        "results achieved for management of certain institutional accounts and hedge funds, (2) schedule-based fees "
        "earned for management of mutual funds and closed-end funds, based either on average daily net assets or on a "
        "combination of the average daily net assets and gross income, and (3) other investment management and advisory "
        "fees.",
    )
    service_charges_on_deposits_income: float | None = Field(
        default=None,
        description="Includes amounts charged depositors for: (1) maintenance of their accounts (maintenance charges); "
        "(2) failure to maintain specified minimum balances on account; (3) exceeding the number of checks or "
        "transactions allowed to be processed in a given period; (4) checks drawn on no minimum balance deposit "
        "accounts; (5) withdrawals from nontransaction deposit accounts; (6) closing savings accounts before a "
        "specified minimum period of time has elapsed; (7) accounts which have remained inactive for extended periods "
        "of time or which have become dormant; (8) use of automated teller machines or remote service units; (9) checks "
        "drawn against insufficient funds that the bank assesses regardless of whether it decides to pay, return or hold "
        "the check; (10) issuing stop payment orders; (11) certifying checks; and (12) accumulating or disbursing funds "
        "deposited in IRAs or Keogh Plan accounts when not handled by the bank's trust department. This item does not "
        "include penalties assessed on the early withdrawal of time deposits.",
    )
    other_service_charge_income: float | None = Field(
        default=None,
        description="Fee and commission revenue earned from sources not otherwise specified in the existing taxonomy.",
    )
    net_realized_capital_gains: float | None = Field(
        default=None,
        description="Amount of realized and unrealized gain (loss) on investment.",
    )
    premiums_earned: float | None = Field(
        default=None,
        description="Amount, after premiums ceded to other entities and premiums assumed by the entity, of premiums "
        "earned.",
    )
    investment_banking_income: float | None = Field(
        default=None,
        description="Amount of fees and commissions from banking, advisory, brokerage, and securities underwriting "
        "activities. Activities include, but are not limited to, underwriting securities, private placements of "
        "securities, investment advisory and management services, merger and acquisition services, sale and servicing of "
        "mutual funds, and other related consulting fees.",
    )
    other_noninterest_income: float | None = Field(
        default=None,
        description="Represents the total of noninterest income derived from certain activities and assets including "
        "(for example): (1) venture capital investments; (2) bank owned life insurance; (3) foreign currency "
        "transactions; and (4) mortgage servicing rights.",
    )
    total_noninterest_income: float | None = Field(
        default=None,
        description="The total amount of noninterest income which may be derived from: (1) fees and commissions; (2) "
        "premiums earned; (3) insurance policy charges; (4) the sale or disposal of assets; and (5) other sources not "
        "otherwise specified.",
    )
    provision_for_credit_losses: float | None = Field(
        default=None,
        description="Amount of expense related to estimated loss from loan and lease transactions.",
    )
    net_interest_income_after_provision: float | None = Field(
        default=None,
        description="Amount of net interest income after provision for credit losses.",
    )
    benefits_costs_expenses: float | None = Field(
        default=None,
        description="The total amount of expense recognized during the period for future policy benefits, claims and "
        "claims adjustment costs, and for selling, general and administrative costs.",
    )
    current_and_future_benefits: float | None = Field(
        default=None,
        description="Amount, after effect of policies assumed or ceded, of expense related to provision for policy "
        "benefits and costs incurred for health insurance contracts.",
    )
    salaries_and_employee_benefits_expense: float | None = Field(
        default=None,
        description="Amount of expense for salary, wage, profit sharing; incentive and equity-based compensation; and "
        "other employee benefit.",
    )
    net_occupancy_equipment_expense: float | None = Field(
        default=None,
        description="Amount of net occupancy expense that may include items, such as depreciation of facilities and "
        "equipment, lease expenses, property taxes and property and casualty insurance expense.",
    )
    marketing_expense: float | None = Field(
        default=None,
        description="The aggregate total amount of expenses directly related to the marketing or selling of products or "
        "services.",
    )
    property_liability_insurance_claims: float | None = Field(
        default=None,
        description="Amount, after effects of policies assumed or ceded, of expense related to the provision for policy "
        "benefits and costs incurred.",
    )
    policy_acquisition_costs: float | None = Field(
        default=None,
        description="Amount of deferred policy acquisition cost capitalized on contract remaining in force.",
    )
    amortization_of_deferred_policy_acquisition_costs: float | None = Field(
        default=None,
        description="Amount of amortization expense (reversal of expense) for deferred policy acquisition costs.",
    )
    total_noninterest_expense: float | None = Field(
        default=None,
        description="Total aggregate amount of all noninterest expense.",
    )
    non_operating_income: float | None = Field(
        default=None,
        description="The aggregate amount of income or expense from ancillary business-related activities (that is to "
        "say, excluding major activities considered part of the normal operations of the business).",
    )
    other_income: float | None = Field(
        default=None,
        description="Amount of income (expense) related to nonoperating activities, classified as other.",
    )
    other_gains: float | None = Field(
        default=None,
        description="Amount of realized and unrealized gain (loss) on investment.",
    )
    total_other_income: float | None = Field(
        default=None,
        description="The aggregate amount of income or expense from ancillary business-related activities (that is to "
        "say, excluding major activities considered part of the normal operations of the business).",
    )
    total_pretax_income: float | None = Field(
        default=None,
        description="Amount of income (loss) from continuing operations, including income (loss) from equity method "
        "investments, before deduction of income tax expense (benefit), and income (loss) attributable to noncontrolling "
        "interest.",
    )
    income_tax_expense: float | None = Field(
        default=None,
        description="Amount of current income tax expense (benefit) and deferred income tax expense (benefit) pertaining "
        "to continuing operations.",
    )
    income_tax_current: float | None = Field(
        default=None,
        description="Amount of current income tax expense (benefit) pertaining to taxable income (loss) from continuing "
        "operations.",
    )
    income_tax_deferred: float | None = Field(
        default=None,
        description="Amount of deferred income tax expense (benefit) pertaining to income (loss) from continuing "
        "operations.",
    )
    income_before_equity_method: float | None = Field(
        default=None,
        description="Amount of income/loss from continuing operations before income from equity method investments.",
    )
    equity_method_investments: float | None = Field(
        default=None,
        description="Amount of income (loss) for proportionate share of equity method investee's income (loss).",
    )
    net_income_continuing: float | None = Field(
        default=None,
        description="Amount after tax of income (loss) from continuing operations including portion attributable to the "
        "noncontrolling interest.",
    )
    net_income_discontinued: float | None = Field(
        default=None,
        description="Amount after tax of income (loss) from a discontinued operation including the portion attributable "
        "to the noncontrolling interest. Includes, but is not limited to, the income (loss) from operations during the "
        "phase-out period, gain (loss) on disposal, gain (loss) for reversal of write-down (write-down) to fair value, "
        "less cost to sell, and adjustments to a prior period gain (loss) on disposal.",
    )
    extraordinary_income: float | None = Field(
        default=None,
        description="Description of the gains (losses), after tax, arising from an event or transaction that is both "
        "unusual in nature and infrequent in occurrence when considered in relation to the environment in which the "
        "entity operates and which represents the portion assigned to noncontrolling interest, if any. This amount is "
        "the income statement amount which is allocable to that ownership interest in subsidiary equity which is not "
        "attributable to the parent (noncontrolling interest, minority interest).",
    )
    other_adjustments_to_consolidated_net_income: float | None = Field(
        default=None,
        description="Amount after tax and reclassification adjustments of other comprehensive income (loss).",
    )
    gain_on_sale_properties: float | None = Field(
        default=None,
        description="Amount of gain (loss) on sale or disposal of property, net of applicable income taxes.",
    )
    gain_loss_disposition_subsidiary: float | None = Field(
        default=None,
        description="Gain/loss on sale of stock in subsidiary or equity method investee.",
    )
    net_income: float | None = Field(
        default=None,
        description="The consolidated profit or loss for the period, net of income taxes, including the portion "
        "attributable to the noncontrolling interest.",
    )
    preferred_dividends: float | None = Field(
        default=None,
        description="Amount of paid and unpaid preferred stock dividends declared with the form of settlement in cash, "
        "stock and payment-in-kind (PIK).",
    )
    net_income_nci_redeemable: float | None = Field(
        default=None,
        description="Amount after tax of income attributable to redeemable noncontrolling interest.",
    )
    net_income_nci_nonredeemable: float | None = Field(
        default=None,
        description="Amount after tax of income attributable to nonredeemable noncontrolling interest.",
    )
    net_income_to_noncontrolling_interest: float | None = Field(
        default=None,
        description="Amount of Net Income (Loss) attributable to noncontrolling interest.",
    )
    other_adjustments_to_net_income_to_common: float | None = Field(
        default=None,
        description="The aggregate value of preferred stock dividends and other adjustments necessary to derive net "
        "income apportioned to common stockholders.",
    )
    net_income_to_common: float | None = Field(
        default=None,
        description="Amount, after deduction of tax, noncontrolling interests, dividends on preferred stock and "
        "participating securities; of income (loss) available to common shareholders.",
    )
    weighted_ave_basic_shares_os: int | None = Field(
        default=None,
        description="Number of [basic] shares or units, after adjustment for contingently issuable shares or units and "
        "other shares or units not deemed outstanding, determined by relating the portion of time within a reporting "
        "period that common shares or units have been outstanding to the total time in that period.",
    )
    basic_eps: float | None = Field(
        default=None,
        description="The amount of net income (loss) for the period per each share of common stock or unit outstanding "
        "during the reporting period.",
    )
    weighted_ave_diluted_shares_os: int | None = Field(
        default=None,
        description="The average number of shares or units issued and outstanding that are used in calculating diluted "
        "EPS or earnings per unit (EPU), determined based on the timing of issuance of shares or units in the period.",
    )
    diluted_eps: float | None = Field(
        default=None,
        description="The amount of net income (loss) for the period available to each share of common stock or common "
        "unit outstanding during the reporting period and to each share or unit that would have been outstanding "
        "assuming the issuance of common shares or units for all dilutive potential common shares or units outstanding "
        "during the reporting period.",
    )
    weighted_ave_basic_diluted_shares_os: int | None = Field(
        default=None,
        description="Average number of shares or units issued and outstanding that are used in calculating basic and "
        "diluted earnings per share (EPS).",
    )
    basic_diluted_eps: float | None = Field(
        default=None,
        description="The amount of net income or loss for the period per each share in instances when basic and diluted "
        "earnings per share are the same amount and reported as a single line item on the face of the financial "
        "statements. Basic earnings per share is the amount of net income or loss for the period per each share of "
        "common stock or unit outstanding during the reporting period. Diluted earnings per share includes the amount of "
        "net income or loss for the period available to each share of common stock or common unit outstanding during the "
        "reporting period and to each share or unit that would have been outstanding assuming the issuance of common "
        "shares or units for all dilutive potential common shares or units outstanding during the reporting period.",
    )
    cash_dividends_per_share: float | None = Field(
        default=None,
        description="Aggregate dividends declared during the period for each share of common stock outstanding.",
    )
    other_comprehensive_income_parent: float | None = Field(
        default=None,
        description="Amount after tax and reclassification adjustments of OCI attributable to parent.",
    )
    comprehensive_income_parent: float | None = Field(
        default=None,
        description="Amount after tax of increase (decrease) in equity from transactions and other events, attributable "
        "to parent.",
    )
    other_comprehensive_income_nci: float | None = Field(
        default=None,
        description="Amount after tax and reclassification adjustments of OCI attributable to noncontrolling interests.",
    )
    comprehensive_income_nci: float | None = Field(
        default=None,
        description="Amount after tax of increase (decrease) in equity from transactions and other events, attributable "
        "to noncontrolling interests.",
    )
    comprehensive_income: float | None = Field(
        default=None,
        description="Amount after tax of increase (decrease) in equity from transactions and other events/circumstances "
        "from net income and OCI. Includes portion attributable to NCI.",
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


class SecIncomeStatementFetcher(
    Fetcher[SecIncomeStatementQueryParams, list[SecIncomeStatementData]]
):
    """SEC IncomeStatement Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> SecIncomeStatementQueryParams:
        """Transform the query."""
        return SecIncomeStatementQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: SecIncomeStatementQueryParams,
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
            "statement": "income_statement",
        }

    @staticmethod
    def transform_data(
        query: SecIncomeStatementQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> AnnotatedResult[list[SecIncomeStatementData]]:
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

        normalize_period_fields(periods, SecIncomeStatementData)

        # Sort by period_ending descending (most recent first).
        sorted_periods = sorted(
            periods.values(),
            key=lambda x: x["period_ending"],
            reverse=True,
        )

        if query.limit is not None:
            sorted_periods = sorted_periods[: query.limit]

        results = [SecIncomeStatementData.model_validate(d) for d in sorted_periods]

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
            "fields": order_field_meta(field_meta, SecIncomeStatementData),
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
