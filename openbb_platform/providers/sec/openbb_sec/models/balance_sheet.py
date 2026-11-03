"""SEC Balance Sheet Model."""

from math import isnan
from typing import Any, Literal
from warnings import warn

from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.balance_sheet import (
    BalanceSheetData,
    BalanceSheetQueryParams,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import ConfigDict, Field, model_serializer, model_validator


class SecBalanceSheetQueryParams(BalanceSheetQueryParams):
    """SEC BalanceSheet Query.

    Source: https://www.sec.gov/edgar/sec-api-documentation
    """

    period: Literal["annual", "quarterly", "ttm"] = Field(
        default="annual",
        description=QUERY_DESCRIPTIONS.get("period", "")
        + " For balance sheet, TTM is treated as the average of the last 4 quarters.",
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


class SecBalanceSheetData(BalanceSheetData):
    """SEC BalanceSheet Data."""

    model_config = ConfigDict(
        allow_inf_nan=True,
        ser_json_inf_nan="null",
        json_schema_extra={
            "x-widget_config": {"$.data": {"table": {"enableFormulas": True}}}
        },
    )

    reported_currency: str | None = Field(
        default=None,
        description="The currency in which the balance sheet is reported.",
    )
    cash_and_equivalents: float | None = Field(
        default=None,
        description="Amount of cash and cash equivalent. Cash includes, but is not limited to, currency on hand, demand "
        "deposit with financial institution, and account with general characteristic of demand deposit. Cash equivalent "
        "includes, but is not limited to, short-term, highly liquid investment that is both readily convertible to known "
        "amount of cash and so near maturity that it presents insignificant risk of change in value because of change in "
        "interest rate.",
    )
    restricted_cash: float | None = Field(
        default=None,
        description="Amount of cash restricted as to withdrawal or usage. Cash includes, but is not limited to, currency "
        "on hand, demand deposits with banks or financial institutions, and other accounts with general characteristics "
        "of demand deposits.",
    )
    short_term_investments: float | None = Field(
        default=None,
        description="Amount of investment in marketable security, classified as current.",
    )
    fed_funds_sold: float | None = Field(
        default=None,
        description="Includes: (1) the amount outstanding of funds lent to other depository institutions, securities "
        "brokers, or securities dealers in the form of Federal Funds sold; for example, immediately available funds lent "
        "under agreements or contracts that mature in one business day or roll over under a continuing contract, "
        "regardless of the nature of the transaction or the collateral involved, excluding overnight lending for "
        "commercial and industrial purposes. Also include Federal Funds sold under agreements to resell on a gross "
        "basis, excluding (1) sales of term Federal Funds, (2) due bills representing purchases of securities or other "
        "assets by the reporting bank that have not yet been delivered and similar instruments, (3) resale agreements "
        "that mature in more than one business day involving assets other than securities, and (4) yield maintenance "
        "dollar repurchase agreements (Federal Funds Sold) and (2) the dollar amount outstanding of funds lent in the "
        "form of security resale agreements regardless of maturity, if the agreement requires the bank to resell the "
        "identical security purchased or a security that meets the definition of substantially the same in the case of a "
        "dollar roll. Also include purchases of participations in pools of securities, regardless of maturity "
        "(Securities Purchased Under Agreements to Re-sell).",
    )
    interest_bearing_deposits_at_other_banks: float | None = Field(
        default=None,
        description="For banks and other depository institutions (including Federal Reserve Banks, if applicable): "
        "Interest-bearing deposits in other financial institutions for relatively short periods of time including, for "
        "example, certificates of deposits, which are presented separately from cash on the balance sheet.",
    )
    time_deposits_placed: float | None = Field(
        default=None,
        description="Amount of time deposit liabilities, including certificates of deposit.",
    )
    trading_account_securities: float | None = Field(
        default=None,
        description="Amount of investment in debt security measured at fair value with change in fair value recognized "
        "in net income (trading) and investment in equity security measured at fair value with change in fair value "
        "recognized in net income (FV-NI).",
    )
    loans_and_leases: float | None = Field(
        default=None,
        description="Amortized cost excluding accrued interest, before allowance for credit loss, of financing "
        "receivable. Excludes net investment in lease.",
    )
    allowance_for_loan_and_lease_losses: float | None = Field(
        default=None,
        description="Amount of allowance for credit loss on financing receivable. Excludes allowance for financing "
        "receivable covered under loss sharing agreement.",
    )
    net_loans_and_leases: float | None = Field(
        default=None,
        description="Amortized cost excluding accrued interest, after allowance for credit loss, of financing "
        "receivable. Excludes net investment in lease.",
    )
    loans_held_for_sale: float | None = Field(
        default=None,
        description="Amount before allowance and after deduction of deferred interest and fees, unamortized costs and "
        "premiums and discounts from face amounts, of loans and leases held in portfolio, including but not limited to, "
        "commercial and consumer loans. Excludes loans and leases covered under loss sharing agreements.",
    )
    accrued_investment_income: float | None = Field(
        default=None,
        description="Interest, dividends, rents, ancillary and other revenues earned but not yet received by the entity "
        "on its investments.",
    )
    accounts_receivable: float | None = Field(
        default=None,
        description="Amount, after allowance for credit loss, of right to consideration from customer for product sold "
        "and service rendered in normal course of business, classified as current.",
    )
    customer_and_other_receivables: float | None = Field(
        default=None,
        description="Amount, after allowance for credit loss, of right to consideration from customer for product sold "
        "and service rendered in normal course of business.",
    )
    note_receivable: float | None = Field(
        default=None,
        description="Amortized cost, after allowance for credit loss, of financing receivable classified as current. "
        "Excludes net investment in lease.",
    )
    nontrade_receivables: float | None = Field(
        default=None,
        description="The sum of amounts currently receivable other than from customers. For classified balance sheets, "
        "represents the current amount receivable, that is amounts expected to be collected within one year or the "
        "normal operating cycle, if longer.",
    )
    net_inventory: float | None = Field(
        default=None,
        description="Amount after valuation and LIFO reserves of inventory expected to be sold, or consumed within one "
        "year or operating cycle, if longer.",
    )
    prepaid_expenses: float | None = Field(
        default=None,
        description="Amount of asset related to consideration paid in advance for costs that provide economic benefits "
        "within a future period of one year or the normal operating cycle, if longer.",
    )
    current_deferred_tax_assets: float | None = Field(
        default=None,
        description="The current portion of the aggregate tax effects as of the balance sheet date of all future tax "
        "deductions arising from temporary differences between tax basis and generally accepted accounting principles "
        "basis recognition of assets, liabilities, revenues and expenses, which can only be deducted for tax purposes "
        "when permitted under enacted tax laws; after deducting the allocated valuation allowance, if any, to reduce "
        "such amount to net realizable value. Deferred tax liabilities and assets are classified as current or "
        "noncurrent based on the classification of the related asset or liability for financial reporting. A deferred "
        "tax liability or asset that is not related to an asset or liability for financial reporting, including deferred "
        "tax assets related to carryforwards, are classified according to the expected reversal date of the temporary "
        "difference. An unrecognized tax benefit that is directly related to a position taken in a tax year that results "
        "in a net operating loss carryforward is presented as a reduction of the related deferred tax asset.",
    )
    other_current_assets: float | None = Field(
        default=None,
        description="Amount of current assets classified as other.",
    )
    other_current_nonoperating_assets: float | None = Field(
        default=None,
        description="Amount of asset related to consideration paid in advance for costs that provide economic benefits "
        "in future periods, and amount of other assets that are expected to be realized or consumed within one year or "
        "the normal operating cycle, if longer.",
    )
    total_current_assets: float | None = Field(
        default=None,
        description="Amount of asset recognized for present right to economic benefit, classified as current.",
    )
    gross_ppe: float | None = Field(
        default=None,
        title="Gross PPE",
        description="Amount, before accumulated depreciation, depletion, and amortization, of property, plant, and "
        "equipment. Includes, but is not limited to, land and land improvement; building; machinery and equipment; "
        "furniture and fixture; and work of art, historical treasure, or similar asset classified as collection.",
    )
    accumulated_depreciation: float | None = Field(
        default=None,
        description="Amount of accumulated depreciation, depletion, and amortization of property, plant, and equipment. "
        "Includes, but is not limited to, land and land improvement; building; machinery and equipment; furniture and "
        "fixture; and work of art, historical treasure, or similar asset classified as collection.",
    )
    net_ppe: float | None = Field(
        default=None,
        title="Net PPE",
        description="Amount, after accumulated depreciation, depletion, and amortization, of property, plant, and "
        "equipment. Includes, but is not limited to, land and land improvement; building; machinery and equipment; "
        "furniture and fixture; and work of art, historical treasure, or similar asset classified as collection.",
    )
    net_premises_and_equipment: float | None = Field(
        default=None,
        description="Amount, after accumulated depreciation, depletion, and amortization, of property, plant, and "
        "equipment. Includes, but is not limited to, land and land improvement; building; machinery and equipment; "
        "furniture and fixture; and work of art, historical treasure, or similar asset classified as collection.",
    )
    operating_lease_right_of_use_asset: float | None = Field(
        default=None,
        description="Amount of lessee's right to use underlying asset under operating lease.",
    )
    finance_lease_right_of_use_asset: float | None = Field(
        default=None,
        description="Amount, after accumulated amortization, of right-of-use asset from finance lease.",
    )
    long_term_investments: float | None = Field(
        default=None,
        description="Amount of investment in marketable security, classified as noncurrent.",
    )
    mortgage_servicing_rights: float | None = Field(
        default=None,
        description="Fair value of an asset representing net future revenue from contractually specified servicing fees, "
        "late charges, and other ancillary revenues, in excess of future costs related to servicing arrangements.",
    )
    deferred_acquisition_cost: float | None = Field(
        default=None,
        description="Amount of deferred policy acquisition cost capitalized on contract remaining in force.",
    )
    separate_account_business_assets: float | None = Field(
        default=None,
        description="Amount of asset at fair value held for benefit of separate account policyholder.",
    )
    noncurrent_note_receivables: float | None = Field(
        default=None,
        description="Amount, after allowance for credit loss, of financing receivable, classified as noncurrent.",
    )
    goodwill: float | None = Field(
        default=None,
        description="Amount, after accumulated impairment loss, of asset representing future economic benefit arising "
        "from other asset acquired in business combination or from joint venture formation or both, that is not "
        "individually identified and separately recognized.",
    )
    intangible_assets: float | None = Field(
        default=None,
        description="Amount, after accumulated amortization, of finite- and indefinite-lived intangible assets and "
        "capitalized cost for software to be sold, leased, or marketed. Excludes goodwill.",
    )
    noncurrent_deferred_tax_assets: float | None = Field(
        default=None,
        description="The noncurrent portion as of the balance sheet date of the aggregate carrying amount of all future "
        "tax deductions arising from temporary differences between tax basis and generally accepted accounting "
        "principles basis recognition of assets, liabilities, revenues and expenses, which can only be deducted for tax "
        "purposes when permitted under enacted tax laws; after the valuation allowance, if any, to reduce such amount to "
        "net realizable value. Deferred tax liabilities and assets are classified as current or noncurrent based on the "
        "classification of the related asset or liability for financial reporting. A deferred tax liability or asset "
        "that is not related to an asset or liability for financial reporting, including deferred tax assets related to "
        "carryforwards, is classified according to the expected reversal date of the temporary difference.",
    )
    employee_benefit_assets: float | None = Field(
        default=None,
        description="This represents the entire assets recognized in the balance sheet that are associated with the "
        "defined benefit plans.",
    )
    other_noncurrent_assets: float | None = Field(
        default=None,
        description="Amount of noncurrent assets classified as other.",
    )
    other_noncurrent_nonoperating_assets: float | None = Field(
        default=None,
        description="Amount of investments, and noncurrent assets classified as other.",
    )
    other_noncurrent_assets_excl_ppe: float | None = Field(
        default=None,
        description="Noncurrent assets other than investments and PP&E.",
    )
    total_noncurrent_assets: float | None = Field(
        default=None,
        description="Sum of the carrying amounts as of the balance sheet date of all assets that are expected to be "
        "realized in cash, sold or consumed after one year or beyond the normal operating cycle, if longer.",
    )
    other_assets: float | None = Field(
        default=None,
        description="Amount of assets classified as other.",
    )
    total_assets: float | None = Field(
        default=None,
        description="Amount of asset recognized for present right to economic benefit.",
    )
    noninterest_bearing_deposits: float | None = Field(
        default=None,
        description="The aggregate amount of all domestic and foreign noninterest-bearing deposits liabilities held by "
        "the entity.",
    )
    interest_bearing_deposits: float | None = Field(
        default=None,
        description="The aggregate of all domestic and foreign interest-bearing deposit liabilities.",
    )
    fed_funds_purchased: float | None = Field(
        default=None,
        description="Amount after offset of short term borrowing where a bank borrows, at the federal funds rate, from "
        "another bank and securities that an entity sells and agrees to repurchase at a specified date for a specified "
        "price.",
    )
    short_term_debt: float | None = Field(
        default=None,
        description="Reflects the total carrying amount as of the balance sheet date of debt having initial terms less "
        "than one year or the normal operating cycle, if longer.",
    )
    current_portion_of_long_term_debt: float | None = Field(
        default=None,
        description="Amount of long-term debt due within one year or within the normal operating cycle, "
        "if longer.",
    )
    bankers_acceptances: float | None = Field(
        default=None,
        description="Amount of short-term, negotiable time drafts drawn on and accepted by a financial institution. "
        "Bankers acceptances are a bank's promise to pay to the holder of the draft a stated amount on a specified date.",
    )
    accounts_payable: float | None = Field(
        default=None,
        description="Carrying value as of the balance sheet date of liabilities incurred (and for which invoices have "
        "typically been received) and payable to vendors for goods and services received that are used in an entity's "
        "business. Used to reflect the current portion of the liabilities (due within one year or within the normal "
        "operating cycle if longer).",
    )
    accrued_interest_payable: float | None = Field(
        default=None,
        description="Carrying value as of the balance sheet date of [accrued] interest payable on all forms of debt, "
        "including trade payables, that has been incurred and is unpaid. Used to reflect the current portion of the "
        "liabilities (due within one year or within the normal operating cycle if longer).",
    )
    other_short_term_payables: float | None = Field(
        default=None,
        description="Amount of borrowings classified as other, maturing within one year or the normal operating cycle, "
        "if longer.",
    )
    accrued_expenses: float | None = Field(
        default=None,
        description="Carrying value as of the balance sheet date of obligations incurred and payable, pertaining to "
        "costs that are statutory in nature, are incurred on contractual obligations, or accumulate over time and for "
        "which invoices have not yet been received or will not be rendered. Examples include taxes, interest, rent and "
        "utilities. Used to reflect the current portion of the liabilities (due within one year or within the normal "
        "operating cycle if longer).",
    )
    customer_deposits: float | None = Field(
        default=None,
        description="Carrying amount of liabilities for customer deposits received and held, classified as current. "
        "Includes cash received in advance for undelivered goods or services and refundable security deposits.",
    )
    dividends_payable: float | None = Field(
        default=None,
        description="Carrying value as of the balance sheet date of dividends declared but unpaid on equity securities "
        "issued by the entity and outstanding.",
    )
    current_deferred_revenue: float | None = Field(
        default=None,
        description="Amount of deferred income and obligation to transfer product and service to customer for which "
        "consideration has been received or is receivable, classified as current.",
    )
    current_deferred_tax_liabilities: float | None = Field(
        default=None,
        description="Represents the current portion of deferred tax liabilities, which result from applying the "
        "applicable tax rate to net taxable temporary differences pertaining to each jurisdiction to which the entity is "
        "obligated to pay income tax. A current taxable temporary difference is a difference between the tax basis and "
        "the carrying amount of a current asset or liability in the financial statements prepared in accordance with "
        "generally accepted accounting principles. In a classified statement of financial position, an enterprise "
        "separates deferred tax liabilities and assets into a current amount and a noncurrent amount. Deferred tax "
        "liabilities and assets are classified as current or noncurrent based on the classification of the related asset "
        "or liability for financial reporting. A deferred tax liability or asset that is not related to an asset or "
        "liability for financial reporting, including deferred tax assets related to carryforwards, is classified "
        "according to the expected reversal date of the temporary difference.",
    )
    current_employee_benefit_liabilities: float | None = Field(
        default=None,
        description="Total of the carrying values as of the balance sheet date of obligations incurred through that date "
        "and payable for obligations related to services received from employees, such as accrued salaries and bonuses, "
        "payroll taxes and fringe benefits. Used to reflect the current portion of the liabilities (due within one year "
        "or within the normal operating cycle if longer).",
    )
    other_taxes_payable: float | None = Field(
        default=None,
        description="Carrying value as of the balance sheet date of obligations incurred and payable for statutory "
        "income, sales, use, payroll, excise, real, property and other taxes. Used to reflect the current portion of the "
        "liabilities (due within one year or within the normal operating cycle if longer).",
    )
    other_current_liabilities: float | None = Field(
        default=None,
        description="Amount of liabilities classified as other, due within one year or the normal operating cycle, if "
        "longer.",
    )
    other_current_nonoperating_liabilities: float | None = Field(
        default=None,
        description="Amount of current liabilities from nonoperating activities, classified as other. Includes accrued "
        "liabilities and other liabilities not separately disclosed.",
    )
    operating_lease_liability_current: float | None = Field(
        default=None,
        description="Present value of lessee's discounted obligation for lease payments from operating lease, "
        "classified as current.",
    )
    finance_lease_liability_current: float | None = Field(
        default=None,
        description="Present value of lessee's discounted obligation for lease payments from finance lease, "
        "classified as current.",
    )
    total_current_liabilities: float | None = Field(
        default=None,
        description="Total obligations incurred as part of normal operations that are expected to be paid during the "
        "following twelve months or within one business cycle, if longer.",
    )
    long_term_debt: float | None = Field(
        default=None,
        description="Amount, after deduction of unamortized premium (discount) and debt issuance cost, of long-term debt "
        "classified as noncurrent. Excludes lease obligation.",
    )
    capital_lease_obligations: float | None = Field(
        default=None,
        description="Present value of lessee's discounted obligation for lease payments from finance lease.",
    )
    operating_lease_liability_noncurrent: float | None = Field(
        default=None,
        description="Present value of lessee's discounted obligation for lease payments from operating lease, "
        "classified as noncurrent.",
    )
    claims_and_claim_expenses: float | None = Field(
        default=None,
        description="The amount needed to reflect the estimated ultimate cost of settling claims relating to insured "
        "events that have occurred on or before the balance sheet date, whether or not reported to the insurer at that "
        "date.",
    )
    future_policy_benefits: float | None = Field(
        default=None,
        description="Amount, before effect of reinsurance, of present value of future benefit to be paid to or on behalf "
        "of policyholder and related expense less present value of future net premium receivable under insurance "
        "contract.",
    )
    unearned_premiums_credit: float | None = Field(
        default=None,
        description="Carrying amount of premiums written on insurance contracts that have not been earned as of the "
        "balance sheet date.",
    )
    policyholder_funds: float | None = Field(
        default=None,
        description="Amount due to policyholders for funds held that are returnable under the terms of insurance "
        "contracts, classified as other.",
    )
    participating_policyholder_equity: float | None = Field(
        default=None,
        description="Amount due to policyholders for funds held that are returnable under the terms of insurance "
        "contracts, classified as other.",
    )
    separate_account_business_liabilities: float | None = Field(
        default=None,
        description="Amount of liability for variable contract in which all or portion of contract holder's funds is "
        "allocated to specific separate account and supported by assets held in separate account.",
    )
    other_long_term_liabilities: float | None = Field(
        default=None,
        description="Amount of liabilities classified as other, due after one year or the normal operating cycle, if "
        "longer.",
    )
    asset_retirement_and_litigation_obligation: float | None = Field(
        default=None,
        description="Noncurrent portion of the carrying amount of a liability for an asset retirement obligation. An "
        "asset retirement obligation is a legal obligation associated with the disposal or retirement of a tangible "
        "long-lived asset that results from the acquisition, construction or development, or the normal operations of a "
        "long-lived asset, except for certain obligations of lessees.",
    )
    noncurrent_deferred_revenue: float | None = Field(
        default=None,
        description="Amount of deferred income and obligation to transfer product and service to customer for which "
        "consideration has been received or is receivable, classified as noncurrent.",
    )
    noncurrent_deferred_tax_liabilities: float | None = Field(
        default=None,
        description="Amount, after deferred tax asset, of deferred tax liability attributable to taxable differences "
        "with jurisdictional netting.",
    )
    noncurrent_employee_benefit_liabilities: float | None = Field(
        default=None,
        description="Amount of liability, recognized in statement of financial position, for defined benefit pension and "
        "other postretirement plans, classified as noncurrent.",
    )
    other_noncurrent_liabilities: float | None = Field(
        default=None,
        description="Amount of liabilities classified as other, due after one year or the normal operating cycle, if "
        "longer.",
    )
    other_noncurrent_nonoperating_liabilities: float | None = Field(
        default=None,
        description="Amount of noncurrent liabilities from nonoperating activities, classified as other. Includes "
        "deferred income taxes and other liabilities not separately disclosed.",
    )
    total_noncurrent_liabilities: float | None = Field(
        default=None,
        description="Amount of obligation due after one year or beyond the normal operating cycle, if longer.",
    )
    total_liabilities: float | None = Field(
        default=None,
        description="Amount of liability recognized for present obligation requiring transfer or otherwise providing "
        "economic benefit to others.",
    )
    commitments_and_contingencies: float | None = Field(
        default=None,
        description="Represents the caption on the face of the balance sheet to indicate that the entity has entered "
        "into (1) purchase or supply arrangements that will require expending a portion of its resources to meet the "
        "terms thereof, and (2) is exposed to potential losses or, less frequently, gains, arising from (a) possible "
        "claims against a company's resources due to future performance under contract terms, and (b) possible losses or "
        "likely gains from uncertainties that will ultimately be resolved when one or more future events that are deemed "
        "likely to occur do occur or fail to occur.",
    )
    temporary_equity: float | None = Field(
        default=None,
        description="Carrying amount of the equity component of securities that are redeemable.",
    )
    temporary_equity_parent: float | None = Field(
        default=None,
        description="Carrying amount of temporary equity attributable to parent.",
    )
    redeemable_noncontrolling_interest: float | None = Field(
        default=None,
        description="As of the reporting date, the aggregate carrying amount of all noncontrolling interests which are "
        "redeemable by the (parent) entity (1) at a fixed or determinable price on a fixed or determinable date, (2) at "
        "the option of the holder of the noncontrolling interest, or (3) upon occurrence of an event that is not solely "
        "within the control of the (parent) entity. This item includes noncontrolling interest holder's ownership (or "
        "holders' ownership) regardless of the type of equity interest (common, preferred, other) including all "
        "potential organizational (legal) forms of the investee entity.",
    )
    redeemable_nci_common: float | None = Field(
        default=None,
        title="Redeemable NCI Common",
        description="Equity carrying amount of the common stock component of redeemable NCI.",
    )
    redeemable_nci_preferred: float | None = Field(
        default=None,
        title="Redeemable NCI Preferred",
        description="Equity carrying amount of the preferred stock component of redeemable NCI.",
    )
    redeemable_nci_other: float | None = Field(
        default=None,
        title="Redeemable NCI Other",
        description="Equity carrying amount of the other component of redeemable NCI.",
    )
    total_preferred_equity: float | None = Field(
        default=None,
        description="Aggregate par or stated value of issued nonredeemable preferred stock (or preferred stock "
        "redeemable solely at the option of the issuer). This item includes treasury stock repurchased by the entity. "
        "Note: elements for number of nonredeemable preferred shares, par value and other disclosure concepts are in "
        "another section within stockholders' equity.",
    )
    common_equity: float | None = Field(
        default=None,
        description="Aggregate par or stated value of issued nonredeemable common stock (or common stock redeemable "
        "solely at the option of the issuer). This item includes treasury stock repurchased by the entity. Note: "
        "elements for number of nonredeemable common shares, par value and other disclosure concepts are in another "
        "section within stockholders' equity.",
    )
    additional_paid_in_capital: float | None = Field(
        default=None,
        description="Value received from shareholders in common stock-related transactions that are in excess of par "
        "value or stated value and amounts received from other stock-related transactions. Includes only common stock "
        "transactions (excludes preferred stock transactions). May be called contributed capital, capital in excess of "
        "par, capital surplus, or paid-in capital.",
    )
    retained_earnings: float | None = Field(
        default=None,
        description="Amount of accumulated undistributed earnings (deficit).",
    )
    treasury_stock: float | None = Field(
        default=None,
        description="The amount allocated to treasury stock. Treasury stock is common and preferred shares of an entity "
        "that were issued, repurchased by the entity, and are held in its treasury.",
    )
    accumulated_other_comprehensive_income: float | None = Field(
        default=None,
        description="Amount, after tax, of accumulated increase (decrease) in equity from transaction and other event "
        "and circumstance from nonowner source.",
    )
    other_equity: float | None = Field(
        default=None,
        description="This element represents movements included in the statement of changes in stockholders' equity "
        "which are not separately disclosed or provided for elsewhere in the taxonomy.",
    )
    total_common_equity: float | None = Field(
        default=None,
        description="Amount of equity (deficit) attributable to parent. Excludes temporary equity and equity "
        "attributable to noncontrolling interest.",
    )
    total_equity: float | None = Field(
        default=None,
        description="Amount of equity (deficit) attributable to parent. Excludes temporary equity and equity "
        "attributable to noncontrolling interest.",
    )
    noncontrolling_interests: float | None = Field(
        default=None,
        description="Amount of equity (deficit) attributable to noncontrolling interest. Excludes temporary equity.",
    )
    total_equity_and_noncontrolling_interests: float | None = Field(
        default=None,
        description="Amount of equity (deficit) attributable to parent and noncontrolling interest. Excludes temporary "
        "equity.",
    )
    total_liabilities_and_equity: float | None = Field(
        default=None,
        description="Amount of liabilities and equity items, including the portion of equity attributable to "
        "noncontrolling interests, if any.",
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


class SecBalanceSheetFetcher(
    Fetcher[SecBalanceSheetQueryParams, list[SecBalanceSheetData]]
):
    """SEC BalanceSheet Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> SecBalanceSheetQueryParams:
        """Transform the query."""
        return SecBalanceSheetQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: SecBalanceSheetQueryParams,
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
            "statement": "balance_sheet",
        }

    @staticmethod
    def transform_data(
        query: SecBalanceSheetQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> AnnotatedResult[list[SecBalanceSheetData]]:
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

        normalize_period_fields(periods, SecBalanceSheetData)

        # Sort by period_ending descending (most recent first).
        sorted_periods = sorted(
            periods.values(),
            key=lambda x: x["period_ending"],
            reverse=True,
        )

        if query.limit is not None:
            sorted_periods = sorted_periods[: query.limit]

        results = [SecBalanceSheetData.model_validate(d) for d in sorted_periods]

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
            "fields": order_field_meta(field_meta, SecBalanceSheetData),
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
