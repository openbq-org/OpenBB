from __future__ import annotations
import datetime as dt
from typing import Any, List, Optional
import tejapi
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.balance_sheet import (
    BalanceSheetData,
    BalanceSheetQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

class TEJBalanceSheetQueryParams(BalanceSheetQueryParams):
    """TEJ Balance Sheet Query."""
    start_date: Optional[dt.date] = Field(
        default=None,
        description="Start date of the data, in YYYY-MM-DD format.",
    )
    end_date: Optional[dt.date] = Field(
        default=None,
        description="End date of the data, in YYYY-MM-DD format.",
    )

class TEJBalanceSheetData(BalanceSheetData):
    """TEJ Balance Sheet Data."""
    # Standard OpenBB Fields (Explicitly re-declaring for clarity, though inherited)
    cash_and_cash_equivalents: float | None = Field(default=None, description="Total cash and cash equivalents")
    total_assets: float | None = Field(default=None, description="Total assets")
    total_liabilities: float | None = Field(default=None, description="Total liabilities")
    total_equity: float | None = Field(default=None, description="Total equity")
    total_current_assets: float | None = Field(default=None, description="Total current assets")
    total_current_liabilities: float | None = Field(default=None, description="Total current liabilities")
    announcement_date: Optional[dt.date] | str | None = Field(default=None, description="Announcement Date (key3)")
    
    # TEJ Specific Fields
    current_fin_assets_at_fvpl: float | None = Field(default=None, description="Total current fin. assets at FVPL")
    current_fin_assets_at_fvoci: float | None = Field(default=None, description="Current fin. assets at FVOCI")
    current_fin_assets_measured_at_ac: float | None = Field(default=None, description="Current fin. assets measured at AC")
    current_fin_assets_for_hedging: float | None = Field(default=None, description="Current fin. assets for hedging")
    current_contract_assets: float | None = Field(default=None, description="Current contract assets")
    accounts_and_notes_receivable: float | None = Field(default=None, description="Accounts & notes receivable")
    other_receivable: float | None = Field(default=None, description="Other receivable")
    total_inventories: float | None = Field(default=None, description="Total inventories")
    current_biological_assets_net: float | None = Field(default=None, description="Current biological assets, net")
    total_prepayments: float | None = Field(default=None, description="Total prepayments")
    agency_current_debit: float | None = Field(default=None, description="Agency current - Debit")
    non_current_assets_held_for_sale_net: float | None = Field(default=None, description="Non-current assets held for sale, net")
    total_current_tax_assets: float | None = Field(default=None, description="Total current tax assets")
    other_current_fin_assets: float | None = Field(default=None, description="Other current fin. assets")
    other_current_assets: float | None = Field(default=None, description="Other current assets")
    
    total_non_current_fin_assets_at_fvpl: float | None = Field(default=None, description="Total non-current fin. assets at FVPL")
    non_current_fin_assets_at_fvoci: float | None = Field(default=None, description="Non-current fin. assets at FVOCI")
    non_current_fin_assets_measured_at_ac: float | None = Field(default=None, description="Non-current fin. assets measured at AC")
    non_current_fin_assets_for_hedging: float | None = Field(default=None, description="Non-current fin. assets for hedging")
    non_current_contract_assets: float | None = Field(default=None, description="Non-current contract assets")
    investments_equity_method_net: float | None = Field(default=None, description="Investments (equity method), net")
    non_current_prepayments_for_investments: float | None = Field(default=None, description="Non-current prepayments for investments")
    total_property_plant_and_equipment: float | None = Field(default=None, description="Total property, plant and equipment")
    goodwill_and_intangible_assets: float | None = Field(default=None, description="Goodwill and intangible assets")
    deferred_assets: float | None = Field(default=None, description="Deferred assets")
    right_of_use_assets: float | None = Field(default=None, description="Right of use assets")
    investment_property_net: float | None = Field(default=None, description="Investment property, net")
    prepayments_for_business_facilities: float | None = Field(default=None, description="Prepayments for business facilities")
    long_term_prepaid_rents: float | None = Field(default=None, description="Long-term prepaid rents")
    total_non_current_biological_assets: float | None = Field(default=None, description="Total non-current biological assets")
    other_non_current_assets_others: float | None = Field(default=None, description="Other non-current assets - Others")
    total_other_non_current_assets: float | None = Field(default=None, description="Total other non-current assets")
    total_non_current_assets: float | None = Field(default=None, description="Total non-current assets")
    
    total_short_term_borrowings: float | None = Field(default=None, description="Total short-term borrowings")
    total_short_term_notes_and_bills_payable: float | None = Field(default=None, description="Total short-term notes and bills payable")
    total_current_fin_liabilities_at_fvpl: float | None = Field(default=None, description="Total current fin. liabilities at FVPL")
    current_fin_liabilities_for_hedging: float | None = Field(default=None, description="Current fin. liabilities for hedging")
    current_fin_liabilities_measured_at_ac: float | None = Field(default=None, description="Current fin. liabilities measured at AC")
    current_contract_liabilities: float | None = Field(default=None, description="Current contract liabilities")
    accounts_and_notes_payable: float | None = Field(default=None, description="Accounts and notes payable")
    other_payable: float | None = Field(default=None, description="Other payable")
    current_tax_liabilities: float | None = Field(default=None, description="Current tax liabilities")
    total_current_provisions: float | None = Field(default=None, description="Total current provisions")
    liabilities_included_in_disposal_groups_held_for_sale: float | None = Field(default=None, description="Liabilities included in disposal groups held for sale")
    other_current_fin_liabilities: float | None = Field(default=None, description="Other current fin. liabilities")
    current_lease_liabilities: float | None = Field(default=None, description="Current lease liabilities")
    current_portion_of_long_term_debt: float | None = Field(default=None, description="Current portion of long-term debt")
    current_preference_share_liabilities: float | None = Field(default=None, description="Current preference share liabilities")
    agency_current_credit: float | None = Field(default=None, description="Agency current - Credit")
    other_current_liability: float | None = Field(default=None, description="Other current liability")
    
    total_non_current_fin_liabilities_at_fvpl: float | None = Field(default=None, description="Total non-current fin. liabilities at FVPL")
    non_current_fin_liabilities_for_hedging: float | None = Field(default=None, description="Non-current fin. liabilities for hedging")
    non_current_fin_liabilities_measured_at_ac: float | None = Field(default=None, description="Non-Current fin. liabilities measured at AC")
    non_current_contract_liabilities: float | None = Field(default=None, description="Non-current contract liabilities")
    non_current_preference_share_liabilities: float | None = Field(default=None, description="Non-current preference share liabilities")
    total_bonds_payable: float | None = Field(default=None, description="Total bonds payable")
    long_term_bank_loans: float | None = Field(default=None, description="Long-term bank loans")
    other_long_term_payable: float | None = Field(default=None, description="Other long-term payable")
    non_current_lease_liabilities: float | None = Field(default=None, description="Non-current lease liabilities")
    total_non_current_provisions: float | None = Field(default=None, description="Total non-current provisions")
    deferred_credits_gains_on_inter_affiliate_accounts: float | None = Field(default=None, description="Deferred credits, gains on inter-affiliate accounts")
    accrued_pension_liabilities: float | None = Field(default=None, description="Accrued pension liabilities")
    total_deferred_tax_liabilities: float | None = Field(default=None, description="Total deferred tax liabilities")
    other_non_current_liability: float | None = Field(default=None, description="Other non-current liability")
    total_non_current_liabilities: float | None = Field(default=None, description="Total non-current liabilities")

    ordinary_share: float | None = Field(default=None, description="Ordinary share")
    preference_share: float | None = Field(default=None, description="Preference share")
    advance_receipts_for_share_capital: float | None = Field(default=None, description="Advance receipts for share capital")
    stock_dividend_to_be_distributed: float | None = Field(default=None, description="Stock dividend to be distributed")
    share_capital: float | None = Field(default=None, description="Share Capital")
    total_capital_surplus: float | None = Field(default=None, description="Total capital surplus")
    total_retained_earnings: float | None = Field(default=None, description="Total retained earnings")
    total_other_equity_interest: float | None = Field(default=None, description="Total other equity interest")
    treasury_shares: float | None = Field(default=None, description="Treasury shares")
    total_equity_attributable_to_owners_of_parent: float | None = Field(default=None, description="Total equity attributable to owners of parent")
    interests_in_former_associate: float | None = Field(default=None, description="Interests in the former associate or jointly controlled entity")
    nci_in_pre_acquisition_share_capital: float | None = Field(default=None, description="NCI in pre-acquisition share capital")
    nci: float | None = Field(default=None, description="NCI")


class TEJBalanceSheetFetcher(
    Fetcher[
        TEJBalanceSheetQueryParams,
        List[TEJBalanceSheetData],
    ]
):
    """TEJ Balance Sheet Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> TEJBalanceSheetQueryParams:
        return TEJBalanceSheetQueryParams(**params)

    @staticmethod
    def extract_data(
        query: TEJBalanceSheetQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> Any:
        if credentials:
            api_key = credentials.get("tej_api_key")
            if api_key:
                tejapi.ApiConfig.api_key = api_key

        tickers = query.symbol.split(",") if query.symbol else []
        
        # User provided column list
        cols = [
            "mdate", "no", "key3",
            "a0112", "a01BA", "a0170", "a017L", "a0180", "a0140", "a0197", "a0182", "a016A", "a0190", 
            "a0100", "a034A", "a0350", "a0361", "a0370", "a0391", "a0314", "a0315", 
            "a0400", "a0820", "a0810", "a0966", "a032A", "a0847", "a0846", "a017N", 
            "a0395", "a0890", "a0960", "a0010", "a1120", "a1110", "a112M", "a1128", 
            "a112N", "a118E", "a1130", "a1190", "a1181", "a123A", "a1199", "a1197", 
            "a1226", "a1220", "a112A", "a1140", "a1230", "a1100", "a1587", "a1583", 
            "a1588", "a156P", "a1485", "a1421", "a1411", "a1441", "a1446", "a1560", 
            "a1490", "a1510", "a1515", "a1590", "a1800", "a1000", "a2110", "a2120", 
            "a2200", "a2300", "a211E", "a2310", "a2341", "a2480", "a2400", "a200E", 
            "a2801", "a2802", "a2900", "a2000", "a0020"
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
        query: TEJBalanceSheetQueryParams, data: Any, **kwargs: Any
    ) -> List[TEJBalanceSheetData]:
        if data is None or data.empty:
             raise EmptyDataError("No data returned.")
        
        # User provided 1:1 mapping
        rename_map = {
            "mdate": "period_ending",
            "key3": "announcement_date",

            'a0112':'Total cash and cash equivalents',
            'a01ba':'Total current fin. assets at FVPL',
            'a012h':'Current fin. assets at FVOCI',
            'a01bb':'Current fin. assets measured at AC',
            'a012m':'Current fin. assets for hedging',
            'a017z':'Current contract assets',
            'a0130':'Accounts & notes receivable',
            'a0160':'Other receivable',
            'a0170':'Total inventories',
            'a017l':'Current biological assets, net',
            'a0180':'Total prepayments',
            'a0140':'Agency current - Debit (for sea/land shipping business)',
            'a0197':'Non-current assets held for sale, net',
            'a0182':'Total current tax assets',
            'a016a':'Other current fin. assets',
            'a0190':'Other current assets',
            'a0100':'Total current assets',
            'a034a':'Total non-current fin. assets at FVPL',
            'a0350':'Non-current fin. assets at FVOCI',
            'a0361':'Non-current fin. assets measured at AC',
            'a0370':'Non-current fin. assets for hedging',
            'a0391':'Non-current contract assets',
            'a0314':'Investments (equity method), net',
            'a0315':'Non-current prepayments for investments',
            'a0400':'Total property, plant and equipment',
            'a0820':'Goodwill and intangible assets',
            'a0810':'Deferred assets',
            'a0966':'Right of use assets',
            'a032a':'Investment property, net',
            'a0847':'Prepayments for business facilities',
            'a0846':'Long-term prepaid rents',
            'a017n':'Total non-current biological assets',
            'a0395':'Other non-current assets - Others',
            'a0890':'Total other non-current assets',
            'a0960':'Total non-current assets',
            'a0010':'Total assets',
            'a1120':'Total short-term borrowings',
            'a1110':'Total short-term notes and bills payable',
            'a112m':'Total current fin. liabilities at FVPL',
            'a1128':'Current fin. liabilities for hedging',
            'a112n':'Current fin. liabilities measured at AC',
            'a118e':'Current contract liabilities',
            'a1130':'Accounts and notes payable',
            'a1190':'Other payable',
            'a1181':'Current tax liabilities',
            'a123a':'Total current provisions',
            'a1199':'Liabilities included in disposal groups held for sale',
            'a1197':'Other current fin. liabilities',
            'a1226':'Current lease liabilities',
            'a1220':'Current portion of long-term debt',
            'a112a':'Current preference share liabilities',
            'a1140':'Agency current - Credit (for sea/land and shipping business)',
            'a1230':'Other current liability',
            'a1100':'Total current liabilities',
            'a1587':'Total non-current fin. liabilities at FVPL',
            'a1583':'Non-current fin. liabilities for hedging',
            'a1588':'Non-Current fin. liabilities measured at AC',
            'a156p':'Non-current contract liabilities',
            'a1485':'Non-current preference share liabilities',
            'a1421':'Total bonds payable',
            'a1411':'Long-term bank loans',
            'a1441':'Other long-term payable',
            'a1446':'Non-current lease liabilities',
            'a1560':'Total non-current provisions',
            'a1490':'Deferred credits, gains on inter-affiliate accounts',
            'a1510':'Accrued pension liabilities',
            'a1515':'Total deferred tax liabilities',
            'a1590':'Other non-current liability',
            'a1800':'Total non-current liabilities',
            'a1000':'Total liabilities',
            'a2110':'Ordinary share',
            'a2120':'Preference share',
            'a2200':'Advance receipts for share capital',
            'a2300':'Stock dividend to be distributed',
            'a211e':'Share Capital',
            'a2310':'Total capital surplus',
            'a2341':'Total retained earnings',
            'a2480':'Total other equity interest',
            'a2400':'Treasury shares',
            'a200e':'Total equity attributable to owners of parent',
            'a2801':'Interests in the former associate or jointly controlled entity',
            'a2802':'NCI in pre-acquisition share capital',
            'a2900':'NCI',
            'a2000':'Total equity',
            'a0020':'Total liabilities & equity',
        }

        df = data.rename(columns=rename_map)

        df["fiscal_period"] = df["no"] if "no" in df.columns else "Q"
        df["fiscal_year"] = df["period_ending"].apply(lambda x: x.year)

        records = df.to_dict("records")

        return [TEJBalanceSheetData.model_validate(d) for d in records]
