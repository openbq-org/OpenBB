"""SEC NPORT Holings Model."""

from datetime import date as dateType
from typing import Any, cast
from warnings import warn

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.nport_disclosure import (
    NportDisclosureData,
    NportDisclosureQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator, model_validator


class SecNportDisclosureQueryParams(NportDisclosureQueryParams):
    """SEC NPORT Holdings Query.

    Source: https://www.sec.gov/Archives/edgar/data/
    """

    date: dateType | None = Field(
        default=None,
        description="Specific filing period (period end date) to retrieve."
        " Defaults to the most recent filing. Overrides year and quarter.",
    )
    use_cache: bool = Field(
        description="Whether or not to use cache for the request.",
        default=True,
    )


class SecNportDisclosureData(NportDisclosureData):
    """SEC NPORT Holdings Data."""

    __alias_dict__ = {
        "weight": "pctVal",
        "value": "valUSD",
        "payoff_profile": "derivative_payoff",
        "currency": "curCd",
        "asset_category": "assetCat",
        "issuer_category": "issuerCat",
        "country": "invCountry",
        "is_restricted": "isRestrictedSec",
        "fair_value_level": "fairValLevel",
        "loan_value": "loanVal",
    }

    maturity_date: dateType | None = Field(
        description="The maturity date of the debt security.", default=None
    )
    coupon_kind: str | None = Field(
        description="The type of coupon for the debt security.", default=None
    )
    rate_type: str | None = Field(
        description="The type of rate for the debt security, floating or fixed.",
        default=None,
    )
    annualized_return: float | None = Field(
        description="The annualized return on the debt security.",
        default=None,
        json_schema_extra={"x-unit_measurement": "percent", "x-frontend_multiply": 100},
    )
    is_default: str | None = Field(
        description="If the debt security is defaulted.", default=None
    )
    in_arrears: str | None = Field(
        description="If the debt security is in arrears.", default=None
    )
    is_paid_kind: str | None = Field(
        description="If the debt security payments are paid in kind.", default=None
    )
    derivative_category: str | None = Field(
        description="The derivative category of the holding.", default=None
    )
    counterparty: str | None = Field(
        description="The counterparty of the derivative.", default=None
    )
    underlying_name: str | None = Field(
        description="The name of the underlying asset associated with the derivative.",
        default=None,
    )
    option_type: str | None = Field(description="The type of option.", default=None)
    derivative_payoff: str | None = Field(
        description="The payoff profile of the derivative.", default=None
    )
    expiry_date: dateType | None = Field(
        description="The expiry or termination date of the derivative.", default=None
    )
    exercise_price: float | None = Field(
        description="The exercise price of the option.", default=None
    )
    exercise_currency: str | None = Field(
        description="The currency of the option exercise price.", default=None
    )
    shares_per_contract: float | None = Field(
        description="The number of shares per contract.", default=None
    )
    delta: str | float | None = Field(
        description="The delta of the option.", default=None
    )
    rate_type_rec: str | None = Field(
        description="The type of rate for receivable portion of the swap.", default=None
    )
    receive_currency: str | None = Field(
        description="The receive currency of the swap.", default=None
    )
    upfront_receive: float | None = Field(
        description="The upfront amount received of the swap.", default=None
    )
    floating_rate_index_rec: str | None = Field(
        description="The floating rate index for receivable portion of the swap.",
        default=None,
    )
    floating_rate_spread_rec: float | None = Field(
        description="The floating rate spread for reveivable portion of the swap.",
        default=None,
    )
    rate_tenor_rec: str | None = Field(
        description="The rate tenor for receivable portion of the swap.", default=None
    )
    rate_tenor_unit_rec: str | int | None = Field(
        description="The rate tenor unit for receivable portion of the swap.",
        default=None,
    )
    reset_date_rec: str | None = Field(
        description="The reset date for receivable portion of the swap.", default=None
    )
    reset_date_unit_rec: str | int | None = Field(
        description="The reset date unit for receivable portion of the swap.",
        default=None,
    )
    rate_type_pmnt: str | None = Field(
        description="The type of rate for payment portion of the swap.", default=None
    )
    payment_currency: str | None = Field(
        description="The payment currency of the swap.", default=None
    )
    upfront_payment: float | None = Field(
        description="The upfront amount received of the swap.", default=None
    )
    floating_rate_index_pmnt: str | None = Field(
        description="The floating rate index for payment portion of the swap.",
        default=None,
    )
    floating_rate_spread_pmnt: float | None = Field(
        description="The floating rate spread for payment portion of the swap.",
        default=None,
    )
    rate_tenor_pmnt: str | None = Field(
        description="The rate tenor for payment portion of the swap.", default=None
    )
    rate_tenor_unit_pmnt: str | int | None = Field(
        description="The rate tenor unit for payment portion of the swap.", default=None
    )
    reset_date_pmnt: str | None = Field(
        description="The reset date for payment portion of the swap.", default=None
    )
    reset_date_unit_pmnt: str | int | None = Field(
        description="The reset date unit for payment portion of the swap.", default=None
    )
    repo_type: str | None = Field(description="The type of repo.", default=None)
    is_cleared: str | None = Field(description="If the repo is cleared.", default=None)
    is_tri_party: str | None = Field(
        description="If the repo is tri party.", default=None
    )
    principal_amount: float | None = Field(
        description="The principal amount of the repo.", default=None
    )
    principal_currency: str | None = Field(
        description="The currency of the principal amount.", default=None
    )
    collateral_type: str | None = Field(
        description="The collateral type of the repo.", default=None
    )
    collateral_amount: float | None = Field(
        description="The collateral amount of the repo.", default=None
    )
    collateral_currency: str | None = Field(
        description="The currency of the collateral amount.", default=None
    )
    exchange_currency: str | None = Field(
        description="The currency of the exchange rate.", default=None
    )
    exchange_rate: float | None = Field(description="The exchange rate.", default=None)
    currency_sold: str | None = Field(
        description="The currency sold in a Forward Derivative.",
        default=None,
    )
    currency_amount_sold: float | None = Field(
        description="The amount of currency sold in a Forward Derivative.",
        default=None,
    )
    currency_bought: str | None = Field(
        description="The currency bought in a Forward Derivative.",
        default=None,
    )
    currency_amount_bought: float | None = Field(
        description="The amount of currency bought in a Forward Derivative.",
        default=None,
    )
    notional_amount: float | None = Field(
        description="The notional amount of the derivative.", default=None
    )
    notional_currency: str | None = Field(
        description="The currency of the derivative's notional amount.", default=None
    )
    unrealized_gain: float | None = Field(
        description="The unrealized gain or loss on the derivative.", default=None
    )

    @field_validator("weight", "annualized_return", mode="before", check_fields=False)
    @classmethod
    def normalize_percent(cls, v):
        """Normalize the percent values."""
        return float(v) / 100 if v else None

    @model_validator(mode="before")
    @classmethod
    def replace_zero(cls, values):
        """Check for zero values and replace with None."""
        return (
            {k: None if v == 0 else v for k, v in values.items()}
            if isinstance(values, dict)
            else values
        )


class SecNportDisclosureFetcher(
    Fetcher[
        SecNportDisclosureQueryParams,
        list[SecNportDisclosureData],
    ]
):
    """SEC NPORT Disclosure Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> SecNportDisclosureQueryParams:
        """Transform the query."""
        return SecNportDisclosureQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: SecNportDisclosureQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Return the raw data from the SEC endpoint."""
        import asyncio  # noqa
        import xmltodict
        from openbb_sec.utils.cache import cached_request
        from openbb_sec.utils.helpers import HEADERS, get_nport_candidates
        from pandas import DataFrame, Series, Timestamp, offsets, to_datetime

        # Implement a retry mechanism in case of RemoteDisconnected Error.
        retries = 3
        for i in range(retries):
            filings = []
            try:
                filings = await get_nport_candidates(
                    symbol=query.symbol, use_cache=query.use_cache
                )
                if filings:
                    break
            except Exception as e:
                if i < retries - 1:
                    warn(f"Error: {e}. Retrying...")
                    await asyncio.sleep(1)
                    continue
                raise e

        filing_candidates = DataFrame.from_records(filings)

        if filing_candidates.empty:
            raise OpenBBError(f"No N-Port records found for {query.symbol}.")

        dates = filing_candidates.period_ending.to_list()
        new_date: str = ""

        if query.date is not None:
            target = str(query.date)[:10]
            period = filing_candidates["period_ending"].astype(str).str[:10]
            matched = filing_candidates[period == target]
            filing_url = (
                matched["primary_doc"].values[0]
                if not matched.empty
                else filing_candidates["primary_doc"].values[0]
            )
        elif query.year is not None:
            if query.quarter is None:
                query.quarter = 4 if query.year < to_datetime(dates).max().year else 1
            date = (
                Timestamp(f"{query.year}-{3 * int(query.quarter) - 2:02d}-01")
                + offsets.QuarterEnd()
            ).date()
            # Gets the URL for the nearest date to the requested date.
            __dates = Series(to_datetime(dates))
            __date = to_datetime(str(date))
            __nearest = DataFrame(__dates - __date)
            __nearest_date = abs(__nearest[0].astype("int64")).idxmin()
            new_date = __dates[__nearest_date].strftime("%Y-%m-%d")
            date = new_date if new_date else date
            filing_url = filing_candidates[filing_candidates["period_ending"] == date][
                "primary_doc"
            ].values[0]
        else:
            filing_url = filing_candidates["primary_doc"].values[0]

        async def callback(response, session):
            """Response callback for the request."""
            return await response.read()

        response = await cached_request(
            filing_url,
            headers=HEADERS,
            response_callback=callback,
            use_cache=query.use_cache,
        )
        results = xmltodict.parse(response)

        return results

    @staticmethod
    def transform_data(  # noqa: PLR0912
        query: SecNportDisclosureQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> AnnotatedResult[list[SecNportDisclosureData]]:
        """Transform the data."""
        from pandas import DataFrame, to_datetime
        from pandas.tseries.offsets import MonthEnd

        if not data:
            raise EmptyDataError(f"No data was returned for the symbol, {query.symbol}")
        results = []

        response = data

        submission_type = (
            response.get("edgarSubmission", {})
            .get("headerData", {})
            .get("submissionType", "")
        )
        if submission_type.startswith("N-MFP"):
            from openbb_sec.utils.nmfp import parse_nmfp

            holdings, metadata = parse_nmfp(response)
            if not holdings:
                raise EmptyDataError(
                    f"No holdings were found for the symbol, {query.symbol}"
                )
            return AnnotatedResult(
                result=[SecNportDisclosureData.model_validate(h) for h in holdings],
                metadata=metadata,
            )

        # Parse the response if it is a NPORT-P filing.
        if (
            "edgarSubmission" in response
            and "formData" in response["edgarSubmission"]
            and response["edgarSubmission"]["headerData"]["submissionType"] == "NPORT-P"
            and "invstOrSecs" in response["edgarSubmission"]["formData"]
            and "invstOrSec" in response["edgarSubmission"]["formData"]["invstOrSecs"]
        ):
            invst = response["edgarSubmission"]["formData"]["invstOrSecs"]["invstOrSec"]
            if isinstance(invst, dict):
                invst = [invst]
            for rec in invst:
                if "isin" in rec["identifiers"]:
                    rec["isin"] = rec["identifiers"]["isin"].get("@value")

                if (
                    "other" in rec["identifiers"]
                    and "@value" in rec["identifiers"]["other"]
                ):
                    rec["other_id"] = rec["identifiers"]["other"].get("@value")

                if "securityLending" in rec:
                    security_lending = rec["securityLending"]
                    if "loanByFundCondition" in security_lending:
                        loan_by_fund_condition = security_lending["loanByFundCondition"]
                        rec["isLoanByFund"] = loan_by_fund_condition.get(
                            "@isLoanByFund"
                        )
                        rec["loanVal"] = loan_by_fund_condition.get("@loanVal")
                    if "isCashCollateral" in security_lending:
                        rec["isCashCollateral"] = security_lending.get(
                            "isCashCollateral"
                        )
                    if "isNonCashCollateral" in security_lending:
                        rec["isNonCashCollateral"] = security_lending.get(
                            "isNonCashCollateral"
                        )

                if "debtSec" in rec and isinstance(rec["debtSec"], dict):
                    debt_sec = rec["debtSec"]
                    rec["maturity_date"] = debt_sec.get("maturityDt")
                    rec["coupon_kind"] = debt_sec.get("couponKind")
                    rec["annualized_return"] = debt_sec.get("annualizedRt")
                    rec["is_default"] = debt_sec.get("isDefault")
                    rec["in_arrears"] = debt_sec.get("areIntrstPmntsInArrs")
                    rec["is_paid_kind"] = debt_sec.get("isPaidKind")

                if "issuerConditional" in rec and isinstance(
                    rec["issuerConditional"], dict
                ):
                    rec["issuer_conditional"] = rec["issuerConditional"].get("@desc")

                if "assetConditional" in rec and isinstance(
                    rec["assetConditional"], dict
                ):
                    rec["asset_conditional"] = rec["assetConditional"].get("@desc")

                if "derivativeInfo" in rec and isinstance(rec["derivativeInfo"], dict):
                    derivative_info = rec["derivativeInfo"]

                    if "optionSwaptionWarrantDeriv" in derivative_info:
                        option_swaption_warrant_deriv = derivative_info[
                            "optionSwaptionWarrantDeriv"
                        ]
                        rec["derivative_category"] = option_swaption_warrant_deriv.get(
                            "@derivCat"
                        )
                        rec["counterparty"] = option_swaption_warrant_deriv[
                            "counterparties"
                        ].get("counterpartyName")
                        rec["lei"] = option_swaption_warrant_deriv[
                            "counterparties"
                        ].get("counterpartyLei")
                        rec["underlying_name"] = (
                            option_swaption_warrant_deriv["descRefInstrmnt"]
                            .get("otherRefInst", {})
                            .get("issueTitle")
                        )
                        rec["underlying_name"] = option_swaption_warrant_deriv[
                            "descRefInstrmnt"
                        ].get("nestedDerivInfo", {}).get("fwdDeriv", {}).get(
                            "derivAddlInfo", {}
                        ).get("title") or option_swaption_warrant_deriv[
                            "descRefInstrmnt"
                        ].get("otherRefInst", {}).get("issueTitle")
                        rec["option_type"] = option_swaption_warrant_deriv.get(
                            "putOrCall"
                        )
                        rec["derivative_payoff"] = option_swaption_warrant_deriv.get(
                            "writtenOrPur"
                        )
                        rec["expiry_date"] = option_swaption_warrant_deriv.get("expDt")
                        rec["exercise_price"] = option_swaption_warrant_deriv.get(
                            "exercisePrice"
                        )
                        rec["exercise_currency"] = option_swaption_warrant_deriv.get(
                            "exercisePriceCurCd"
                        )
                        rec["shares_per_contract"] = option_swaption_warrant_deriv.get(
                            "shareNo"
                        )
                        if option_swaption_warrant_deriv.get("delta") != "XXXX":
                            rec["delta"] = option_swaption_warrant_deriv.get("delta")
                        rec["unrealized_gain"] = float(
                            option_swaption_warrant_deriv.get("unrealizedAppr")
                        )

                    if "futrDeriv" in derivative_info:
                        futr_deriv = derivative_info["futrDeriv"]
                        rec["derivative_category"] = futr_deriv.get("@derivCat")
                        if isinstance(futr_deriv.get("counterparties"), dict):
                            rec["counterparty"] = futr_deriv["counterparties"].get(
                                "counterpartyName"
                            )
                            rec["lei"] = futr_deriv["counterparties"].get(
                                "counterpartyLei"
                            )
                        rec["underlying_name"] = (
                            futr_deriv["descRefInstrmnt"]
                            .get("indexBasketInfo", {})
                            .get("indexName")
                        )
                        rec["other_id"] = (
                            futr_deriv["descRefInstrmnt"]
                            .get("indexBasketInfo", {})
                            .get("indexIdentifier")
                        )
                        rec["derivative_payoff"] = futr_deriv.get("payOffProf")
                        rec["expiry_date"] = futr_deriv.get("expDt") or futr_deriv.get(
                            "expDate"
                        )
                        rec["notional_amount"] = float(futr_deriv.get("notionalAmt"))
                        rec["notional_currency"] = futr_deriv.get("curCd")
                        rec["unrealized_gain"] = float(futr_deriv.get("unrealizedAppr"))

                    if "fwdDeriv" in derivative_info:
                        fwd_deriv = derivative_info["fwdDeriv"]
                        rec["derivative_category"] = fwd_deriv.get("@derivCat")
                        rec["counterparty"] = fwd_deriv["counterparties"].get(
                            "counterpartyName"
                        )
                        rec["currency_sold"] = fwd_deriv.get("curSold")
                        rec["currency_amount_sold"] = float(fwd_deriv.get("amtCurSold"))
                        rec["currency_bought"] = fwd_deriv.get("curPur")
                        rec["currency_amount_bought"] = float(
                            fwd_deriv.get("amtCurPur")
                        )
                        rec["expiry_date"] = fwd_deriv.get("settlementDt")
                        rec["unrealized_gain"] = float(fwd_deriv.get("unrealizedAppr"))

                    if "swapDeriv" in rec["derivativeInfo"]:
                        swap_deriv = rec["derivativeInfo"]["swapDeriv"]
                        rec["derivative_category"] = swap_deriv.get("@derivCat")
                        rec["counterparty"] = swap_deriv["counterparties"].get(
                            "counterpartyName"
                        )
                        rec["lei"] = swap_deriv["counterparties"].get("counterpartyLei")
                        if "otherRefInst" in swap_deriv["descRefInstrmnt"]:
                            rec["underlying_name"] = swap_deriv["descRefInstrmnt"][
                                "otherRefInst"
                            ].get("issueTitle")
                        if "indexBasketInfo" in swap_deriv["descRefInstrmnt"]:
                            rec["underlying_name"] = swap_deriv["descRefInstrmnt"][
                                "indexBasketInfo"
                            ].get("indexName")
                            rec["other_id"] = swap_deriv["descRefInstrmnt"][
                                "indexBasketInfo"
                            ].get("indexIdentifier")
                        rec["swap_description"] = (
                            swap_deriv["otherRecDesc"].get("#text")
                            if "otherRecDesc" in swap_deriv["descRefInstrmnt"]
                            else None
                        )
                        if "floatingRecDesc" in swap_deriv:
                            rec["rate_type_rec"] = swap_deriv["floatingRecDesc"].get(
                                "@fixedOrFloating"
                            )
                            rec["floating_rate_index_rec"] = swap_deriv[
                                "floatingRecDesc"
                            ].get("@floatingRtIndex")
                            rec["floating_rate_spread_rec"] = float(
                                swap_deriv["floatingRecDesc"].get("@floatingRtSpread")
                            )
                            rec["payment_amount_rec"] = float(
                                swap_deriv["floatingRecDesc"].get("@pmntAmt")
                            )
                            rec["rate_tenor_rec"] = swap_deriv["floatingRecDesc"][
                                "rtResetTenors"
                            ]["rtResetTenor"].get("@rateTenor")
                            rec["rate_tenor_unit_rec"] = swap_deriv["floatingRecDesc"][
                                "rtResetTenors"
                            ]["rtResetTenor"].get("@rateTenorUnit")
                            rec["reset_date_rec"] = swap_deriv["floatingRecDesc"][
                                "rtResetTenors"
                            ]["rtResetTenor"].get("@resetDt")
                            rec["reset_date_unit_rec"] = swap_deriv["floatingRecDesc"][
                                "rtResetTenors"
                            ]["rtResetTenor"].get("@resetDtUnit")
                        if "floatingPmntDesc" in swap_deriv:
                            rec["rate_type_pmnt"] = swap_deriv["floatingPmntDesc"].get(
                                "@fixedOrFloating"
                            )
                            rec["floating_rate_index_pmnt"] = swap_deriv[
                                "floatingPmntDesc"
                            ].get("@floatingRtIndex")
                            rec["floating_rate_spread_pmnt"] = float(
                                swap_deriv["floatingPmntDesc"].get("@floatingRtSpread")
                            )
                            rec["payment_amount_pmnt"] = float(
                                swap_deriv["floatingPmntDesc"].get("@pmntAmt")
                            )
                            rec["rate_tenor_pmnt"] = swap_deriv["floatingPmntDesc"][
                                "rtResetTenors"
                            ]["rtResetTenor"].get("@rateTenor")
                            rec["rate_tenor_unit_pmnt"] = swap_deriv[
                                "floatingPmntDesc"
                            ]["rtResetTenors"]["rtResetTenor"].get("@rateTenorUnit")
                            rec["reset_date_pmnt"] = swap_deriv["floatingPmntDesc"][
                                "rtResetTenors"
                            ]["rtResetTenor"].get("@resetDt")
                            rec["reset_date_unit_rec"] = swap_deriv["floatingPmntDesc"][
                                "rtResetTenors"
                            ]["rtResetTenor"].get("@resetDtUnit")
                        rec["expiry_date"] = swap_deriv.get("terminationDt")
                        rec["upfront_payment"] = float(swap_deriv.get("upfrontPmnt"))
                        rec["payment_currency"] = swap_deriv.get("pmntCurCd")
                        rec["upfront_receive"] = float(swap_deriv.get("upfrontRcpt"))
                        rec["receive_currency"] = swap_deriv.get("rcptCurCd")
                        rec["notional_amount"] = float(swap_deriv.get("notionalAmt"))
                        rec["notional_currency"] = swap_deriv.get("curCd")
                        rec["unrealized_gain"] = float(swap_deriv.get("unrealizedAppr"))

                if "repurchaseAgrmt" in rec and isinstance(
                    rec["repurchaseAgrmt"], dict
                ):
                    repurchase_agrmt = rec["repurchaseAgrmt"]
                    rec["repo_type"] = repurchase_agrmt.get("transCat")

                    if "clearedCentCparty" in repurchase_agrmt and isinstance(
                        repurchase_agrmt["clearedCentCparty"], dict
                    ):
                        cleared_cent_cparty = repurchase_agrmt["clearedCentCparty"]
                        rec["is_cleared"] = cleared_cent_cparty.get("@isCleared")
                        rec["counterparty"] = cleared_cent_cparty.get(
                            "@centralCounterparty"
                        )
                    rec["is_tri_party"] = repurchase_agrmt.get("isTriParty")
                    rec["annualized_return"] = repurchase_agrmt.get("repurchaseRt")
                    rec["maturity_date"] = repurchase_agrmt.get("maturityDt")

                    if (
                        "repurchaseCollaterals" in repurchase_agrmt
                        and "repurchaseCollateral"
                        in repurchase_agrmt["repurchaseCollaterals"]
                    ):
                        repurchase_collateral = repurchase_agrmt[
                            "repurchaseCollaterals"
                        ]["repurchaseCollateral"]
                        rec["principal_amount"] = float(
                            repurchase_collateral.get("principalAmt")
                        )
                        rec["principal_currency"] = repurchase_collateral.get(
                            "@principalCd"
                        )
                        rec["collateral_amount"] = float(
                            repurchase_collateral.get("collateralVal")
                        )
                        rec["collateral_currency"] = repurchase_collateral.get(
                            "@collateralCd"
                        )
                        rec["collateral_type"] = repurchase_collateral.get("@invstCat")

                if "currencyConditional" in rec and isinstance(
                    rec["currencyConditional"], dict
                ):
                    currency_conditional = rec["currencyConditional"]
                    rec["exchange_currency"] = currency_conditional.get("@curCd")
                    rec["exchange_rate"] = currency_conditional.get("@exchangeRt")

            df = DataFrame.from_records(invst)
            to_drop = [
                "identifiers",
                "securityLending",
                "issuerConditional",
                "assetConditional",
                "debtSec",
                "currencyConditional",
                "derivativeInfo",
                "repurchaseAgrmt",
            ]
            for col in to_drop:
                if col in df.columns:
                    df = df.drop(col, axis=1)

            df["pctVal"] = df["pctVal"].astype(float)
            df = df.sort_values(by="pctVal", ascending=False)
            records = (
                df.astype(object).where(df.notna(), None).to_dict(orient="records")
            )
            results = [
                {
                    key: (
                        None if isinstance(value, str) and not value.strip() else value
                    )
                    for key, value in record.items()
                }
                for record in records
            ]
        # Extract additional information from the form that doesn't belong in the holdings table.
        metadata = {}
        month_1: str = ""
        month_2: str = ""
        month_3: str = ""
        try:
            gen_info = response["edgarSubmission"]["formData"].get("genInfo", {})
            if gen_info:
                period_ending = gen_info.get("repPdDate")
                metadata["fund_name"] = gen_info.get("seriesName")
                metadata["series_id"] = gen_info.get("seriesId")
                metadata["lei"] = gen_info.get("seriesLei")
                metadata["period_ending"] = period_ending
                metadata["fiscal_year_end"] = gen_info.get("repPdEnd")
                current_month = to_datetime(cast(Any, period_ending))
                month_1 = (current_month - MonthEnd(2)).date().strftime("%Y-%m-%d")
                month_2 = (current_month - MonthEnd(1)).date().strftime("%Y-%m-%d")
                month_3 = current_month.strftime("%Y-%m-%d")
            fund_info = response["edgarSubmission"]["formData"].get("fundInfo", {})
            if fund_info:
                metadata["total_assets"] = float(fund_info.pop("totAssets", None))
                metadata["total_liabilities"] = float(fund_info.pop("totLiabs", None))
                metadata["net_assets"] = float(fund_info.pop("netAssets", None))
                metadata["cash_and_equivalents"] = fund_info.pop(
                    "cshNotRptdInCorD", None
                )
                monthly = (
                    fund_info["returnInfo"]["monthlyTotReturns"].get("monthlyTotReturn")
                    or {}
                )
                return_info: Any = (
                    monthly[0] if isinstance(monthly, list) and monthly else monthly
                )
                returns = {
                    month_1: float(return_info.get("@rtn1")) / 100,
                    month_2: float(return_info.get("@rtn2")) / 100,
                    month_3: float(return_info.get("@rtn3")) / 100,
                }
                metadata["returns"] = returns
                flow = {
                    month_1: {
                        "creation": float(fund_info["mon1Flow"].get("@sales", None)),
                        "redemption": float(
                            fund_info["mon1Flow"].get("@redemption", None)
                        ),
                    },
                    month_2: {
                        "creation": float(fund_info["mon2Flow"].get("@sales", None)),
                        "redemption": float(
                            fund_info["mon2Flow"].get("@redemption", None)
                        ),
                    },
                    month_3: {
                        "creation": float(fund_info["mon3Flow"].get("@sales")),
                        "redemption": float(
                            fund_info["mon3Flow"].get("@redemption", None)
                        ),
                    },
                }
                metadata["flow"] = flow
                gains = {
                    month_1: {
                        "realized": float(
                            fund_info["returnInfo"]["othMon1"].get(
                                "@netRealizedGain", None
                            )
                        ),
                        "unrealized": float(
                            fund_info["returnInfo"]["othMon1"].get(
                                "@netUnrealizedAppr", None
                            )
                        ),
                    },
                    month_2: {
                        "realized": float(
                            fund_info["returnInfo"]["othMon2"].get(
                                "@netRealizedGain", None
                            )
                        ),
                        "unrealized": float(
                            fund_info["returnInfo"]["othMon2"].get(
                                "@netUnrealizedAppr", None
                            )
                        ),
                    },
                    month_3: {
                        "realized": float(
                            fund_info["returnInfo"]["othMon3"].get(
                                "@netRealizedGain", None
                            )
                        ),
                        "unrealized": float(
                            fund_info["returnInfo"]["othMon3"].get(
                                "@netUnrealizedAppr", None
                            )
                        ),
                    },
                }
                metadata["gains"] = gains
                _borrowers = (fund_info.get("borrowers") or {}).get("borrower", [])
                if _borrowers:
                    borrowers = [
                        {
                            "name": d["@name"],
                            "lei": d["@lei"],
                            "value": float(d["@aggrVal"]),
                        }
                        for d in _borrowers
                    ]
                    metadata["borrowers"] = borrowers
        except Exception as e:
            warn(f"Error extracting metadata: {e}")
        return AnnotatedResult(
            result=[SecNportDisclosureData.model_validate(d) for d in results],
            metadata=metadata,
        )
