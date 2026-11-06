"""Utility functions for parsing SEC Form 13F-HR."""

from typing import Any

from openbb_core.app.model.abstract.error import OpenBBError


def date_to_quarter_end(date: str) -> str:
    """Convert a date to the end of the calendar quarter."""
    from pandas import to_datetime
    from pandas.tseries.offsets import QuarterEnd

    return (
        (to_datetime(date).to_period("Q").to_timestamp("D") + QuarterEnd())
        .date()
        .strftime("%Y-%m-%d")
    )


async def get_13f_candidates(symbol: str | None = None, cik: str | None = None):
    """Get the 13F-HR filings for a given symbol or CIK."""
    from pandas import DataFrame, to_datetime

    from openbb_sec.models.company_filings import SecCompanyFilingsFetcher

    fetcher = SecCompanyFilingsFetcher()
    params: dict[str, Any] = {}
    if cik is not None:
        params["cik"] = str(cik)
    if symbol is not None:
        params["symbol"] = symbol
    if cik is None and symbol is None:
        raise OpenBBError("Either symbol or cik must be provided.")

    params["use_cache"] = False
    params["form_type"] = "13F-HR"
    filings = await fetcher.fetch_data(params, {})
    filings = [d.model_dump() for d in filings]  # ty: ignore[unresolved-attribute]
    if len(filings) == 0:
        raise OpenBBError(f"No 13F-HR filings found for {symbol if symbol else cik}.")

    # Filings before June 30, 2013 are non-structured and are not supported by downstream parsers.
    up_to = to_datetime("2013-06-30").date()  # noqa: F841
    return (
        DataFrame(data=filings)
        .query("`report_date` >= @up_to")
        .set_index("report_date")["complete_submission_url"]
        .fillna("N/A")
        .replace("N/A", None)
    )


async def complete_submission_callback(response, _):
    """Use callback function for processing the response object."""
    if response.status == 200:
        return await response.text()
    raise OpenBBError(f"Request failed with status code {response.status}")


async def get_complete_submission(url: str):
    """Get the Complete Submission TXT file string from the SEC API."""
    from openbb_sec.utils.definitions import HEADERS
    from openbb_sec.utils.ratelimit import sec_amake_request as amake_request

    return await amake_request(
        url, headers=HEADERS, response_callback=complete_submission_callback
    )


def parse_header(filing_str: str) -> dict:
    """Parse the header of a Complete Submission TXT file string."""
    import xmltodict
    from bs4 import BeautifulSoup

    header_dict: dict = {}
    soup = (
        filing_str
        if filing_str.__class__.__name__ == "BeautifulSoup"
        else BeautifulSoup(filing_str, "xml")
    )
    try:
        header_xml = soup.find("headerData")
        header_dict = xmltodict.parse(str(header_xml))["headerData"]
    except KeyError:
        header_xml = soup.find("type")
        header_dict = xmltodict.parse(str(header_xml)).get("type")
    if header_dict:
        return header_dict
    raise OpenBBError(
        "Failed to parse the form header."
        + " Check the `filing_str` to for the tag, 'headerData'."
    )


def get_submission_type(filing_str: str):
    """Get the submission type of a Complete Submission TXT file string."""
    header = parse_header(filing_str)
    if header:
        try:
            form_type = header["submissionType"]
            return form_type
        except KeyError:
            form_type = header["#text"]
            return form_type
    raise OpenBBError(  # pragma: no cover - parse_header raises before returning a falsy header
        "Failed to get the submission type from the form header."
        + " Check the response from `parse_header`."
    )


def get_period_ending(filing_str: str):
    """Get the report date from a Complete Submission TXT file string."""
    header = parse_header(filing_str)
    if header.get("filerInfo"):
        return header["filerInfo"].get("periodOfReport")
    raise OpenBBError(
        "Failed to get the period of report from the form header."
        + " Check the response from `parse_header`."
    )


async def parse_13f_hr(filing: str, use_cache: bool = True):
    """Parse a 13F-HR filing from the Complete Submission TXT file string."""
    import re

    import xmltodict
    from numpy import nan
    from pandas import DataFrame, to_datetime

    from openbb_sec.utils.cache import aget_cached, aset_cached

    cache_key = None
    if filing.startswith("https://"):
        if use_cache:
            cache_key = f"GET {filing} ::13f-parsed"
            cached = await aget_cached(cache_key)
            if cached is not None:
                return cached
        filing = await get_complete_submission(filing)

    text = filing.replace("ns1:", "").replace("n1:", "")
    match = re.search(r"<informationTable[\s>][\s\S]*</informationTable>", text)
    if match:
        parsed_xml = xmltodict.parse(match.group(0))["informationTable"]["infoTable"]
    else:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(filing, "xml")
        info_table = soup.find_all("informationTable") or soup.find_all("table")[-1:]
        parsed_xml = xmltodict.parse(
            str(info_table[0]).replace("ns1:", "").replace("n1:", "")
        )["informationTable"]["infoTable"]

    if parsed_xml is None:
        raise OpenBBError(
            "Failed to parse the 13F-HR information table."
            + " Check the `filing_str` to make sure it is valid and contains the tag 'informationTable'."
            + " Documents filed before Q2 2013 are not supported."
        )

    periods = re.findall(r"<periodOfReport>([^<]+)</periodOfReport>", text)
    period_ending = periods[0] if periods else get_period_ending(text)
    data = (
        DataFrame(parsed_xml)
        if isinstance(parsed_xml, list)
        else DataFrame([parsed_xml])
    )
    data.columns = data.columns.str.replace("ns1:", "")
    data["value"] = data["value"].astype(int)
    security_type: list = []
    principal_amount: list = []

    # Unpack the nested objects
    try:
        security_type = [d.get("sshPrnamtType") for d in data["shrsOrPrnAmt"]]
        data["security_type"] = security_type
        principal_amount = [int(d.get("sshPrnamt", 0)) for d in data["shrsOrPrnAmt"]]
        data["principal_amount"] = principal_amount
        _ = data.pop("shrsOrPrnAmt")
    except ValueError:
        pass
    try:
        sole = [d.get("Sole") for d in data["votingAuthority"]]
        shared = [d.get("Shared") for d in data["votingAuthority"]]
        none = [d.get("None") for d in data["votingAuthority"]]
        data["voting_authority_sole"] = [int(s) if s else 0 for s in sole]
        data["voting_authority_shared"] = [int(s) if s else 0 for s in shared]
        data["voting_authority_none"] = [int(s) if s else 0 for s in none]
        _ = data.pop("votingAuthority")
    except ValueError:
        pass

    if "putCall" in data.columns:
        data["putCall"] = data["putCall"].fillna("--")

    # Add the period ending so that the filing is identified when multiple are requested.
    data["period_ending"] = to_datetime(period_ending, yearfirst=False).date()
    df = DataFrame(data)
    # Aggregate the data because there are multiple entries for each security and we need the totals.
    # We break it down by CUSIP, security type, and option type.
    agg_index = [
        "period_ending",
        "nameOfIssuer",
        "cusip",
        "titleOfClass",
        "security_type",
        "putCall",
        "investmentDiscretion",
    ]
    agg_columns = {
        "value": "sum",
        "principal_amount": "sum",
        "voting_authority_sole": "sum",
        "voting_authority_shared": "sum",
        "voting_authority_none": "sum",
    }
    # Only aggregate columns that exist in the DataFrame
    agg_columns = {k: v for k, v in agg_columns.items() if k in df.columns}
    agg_index = [k for k in agg_index if k in df.columns]
    df = df.groupby([*agg_index]).agg(agg_columns)

    for col in [
        "voting_authority_sole",
        "voting_authority_shared",
        "voting_authority_none",
    ]:
        if col in df.columns and all(df[col] == 0):
            df = df.drop(columns=col)

    total_value = df.value.sum()
    df["weight"] = (
        round(df.value.astype(float) / total_value, 6) if total_value else 0.0
    )

    records = (
        df.reset_index()
        .replace({nan: None, "--": None})
        .sort_values(by="weight", ascending=False)
        .to_dict("records")
    )
    if cache_key is not None:
        await aset_cached(cache_key, records)
    return records
