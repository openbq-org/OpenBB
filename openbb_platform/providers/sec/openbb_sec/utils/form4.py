"""Module for handling Form 4 data, by company, from the SEC."""

import logging
from datetime import date as dateType

from openbb_core.app.model.abstract.error import OpenBBError

SEC_HEADERS: dict[str, str] = {
    "User-Agent": "Jesus Window Washing jesus@stainedglass.com",
    "Accept-Encoding": "gzip, deflate",
    "Host": "www.sec.gov",
}

field_map = {
    "filing_date": "filing_date",
    "symbol": "symbol",
    "form": "form",
    "owner": "owner_name",
    "owner_cik": "owner_cik",
    "issuer": "company_name",
    "issuer_cik": "company_cik",
    "isDirector": "director",
    "isOfficer": "officer",
    "isTenPercentOwner": "ten_percent_owner",
    "isOther": "other",
    "otherText": "other_text",
    "officerTitle": "owner_title",
    "securityTitle": "security_type",
    "transactionDate": "transaction_date",
    "footnote": "footnote",
    "transactionShares": "securities_transacted",
    "transactionPricePerShare": "transaction_price",
    "transactionTotalValue": "transaction_value",
    "transactionCode": "transaction_type",
    "transactionAcquiredDisposedCode": "acquisition_or_disposition",
    "sharesOwnedFollowingTransaction": "securities_owned",
    "valueOwnedFollowingTransaction": "value_owned",
    "transactionTimeliness": "transaction_timeliness",
    "directOrIndirectOwnership": "ownership_type",
    "natureOfOwnership": "nature_of_ownership",
    "conversionOrExercisePrice": "conversion_exercise_price",
    "exerciseDate": "exercise_date",
    "expirationDate": "expiration_date",
    "deemedExecutionDate": "deemed_execution_date",
    "underlyingSecurityTitle": "underlying_security_title",
    "underlyingSecurityShares": "underlying_security_shares",
    "underlyingSecurityValue": "underlying_security_value",
}

timeliness_map = {
    "E": "Early",
    "L": "Late",
    "Empty": "On-time",
}

transaction_code_map = {
    "A": "Grant, award or other acquisition pursuant to Rule 16b-3(d)",
    "C": "Conversion of derivative security",
    "D": "Disposition to the issuer of issuer equity securities pursuant to Rule 16b-3(e)",
    "E": "Expiration of short derivative position",
    "F": (
        "Payment of exercise price or tax liability by delivering or withholding securities incident to the receipt, "
        "exercise or vesting of a security issued in accordance with Rule 16b-3"
    ),
    "G": "Bona fide gift",
    "H": "Expiration (or cancellation) of long derivative position with value received",
    "I": (
        "Discretionary transaction in accordance with Rule 16b-3(f) "
        "resulting in acquisition or disposition of issuer securities"
    ),
    "J": "Other acquisition or disposition (describe transaction)",
    "L": "Small acquisition under Rule 16a-6",
    "M": "Exercise or conversion of derivative security exempted pursuant to Rule 16b-3",
    "O": "Exercise of out-of-the-money derivative security",
    "P": "Open market or private purchase of non-derivative or derivative security",
    "S": "Open market or private sale of non-derivative or derivative security",
    "U": "Disposition pursuant to a tender of shares in a change of control transaction",
    "W": "Acquisition or disposition by will or the laws of descent and distribution",
    "X": "Exercise of in-the-money or at-the-money derivative security",
    "Z": "Deposit into or withdrawal from voting trust",
}


def get_logger():
    """Get the logger."""
    logger_instance = logging.getLogger("openbb.sec")
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter("\n%(message)s\n")
    handler.setFormatter(formatter)
    logger_instance.addHandler(handler)
    logger_instance.setLevel(logging.INFO)

    return logger_instance


logger = get_logger()


async def get_form_4_urls(
    symbol,
    start_date: dateType | None = None,
    end_date: dateType | None = None,
    use_cache: bool = True,
):
    """Get the form 4 URLs for a symbol."""
    from openbb_sec.models.company_filings import SecCompanyFilingsFetcher

    fetcher = SecCompanyFilingsFetcher()
    form_4 = await fetcher.fetch_data(
        dict(
            symbol=symbol,
            form_type="4",
            provider="sec",
            limit=0,
            use_cache=use_cache,
        ),
        {},
    )
    start_date = (
        start_date
        if isinstance(start_date, dateType)
        else (dateType.fromisoformat(start_date) if start_date else None)  # ty: ignore[redundant-condition]
    )
    end_date = (
        end_date
        if isinstance(end_date, dateType)
        else (dateType.fromisoformat(end_date) if end_date else None)  # ty: ignore[redundant-condition]
    )
    urls: list = []
    for item in form_4:
        if (
            (not start_date or not item.filing_date)  # ty: ignore[missing-union-attribute]
            or start_date
            and item.filing_date < start_date  # ty: ignore[missing-union-attribute]
        ):
            continue
        if (
            (not end_date or not item.report_date)  # ty: ignore[missing-union-attribute]
            or end_date
            and item.report_date > end_date  # ty: ignore[missing-union-attribute]
        ):
            continue
        to_replace = f"{item.primary_doc.split('/')[0]}/"  # ty: ignore[missing-union-attribute]
        form_url = item.report_url.replace(to_replace, "")  # ty: ignore[missing-union-attribute]
        if form_url.endswith(".xml"):
            urls.append(form_url)

    return urls


def clean_xml(xml_content):
    """Clean the XML content."""
    import re

    xml_content = re.sub(r"\\", "", xml_content)
    xml_content = xml_content.replace("/s/ ", "")
    xml_content = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;)", "&amp;", xml_content)
    return xml_content


async def get_form_4_data(url) -> dict:
    """Get the form 4 data."""
    from warnings import warn  # noqa
    from xmltodict import parse
    from openbb_sec.utils.ratelimit import sec_amake_request as amake_request

    async def response_callback(response, _):
        """Response callback function."""
        return await response.read()

    response = await amake_request(
        url,
        headers=SEC_HEADERS,
        response_callback=response_callback,
        timeout=30,
    )
    response_text = response.decode("utf-8")

    if "Traffic Limit" in response_text:
        raise OpenBBError(
            "You've exceeded the SEC's traffic limit. Access will be limited for 10 minutes."
            " Reduce the number of requests by using a more specific date range."
        )

    cleaned_response = clean_xml(response_text)

    try:
        xml_data = parse(cleaned_response)
    except Exception as e:
        warn(f"Error parsing XML from {url}: {e}")
        return {}

    return (
        xml_data.get("ownershipDocument") if xml_data.get("ownershipDocument") else {}
    )


async def parse_form_4_data(  # noqa: PLR0915, PLR0912
    data,
):
    """Parse the Form 4 data."""

    owner = data.get("reportingOwner", {})
    owners = ""
    ciks = ""
    if isinstance(owner, list):
        owners = ";".join(
            [d.get("reportingOwnerId", {}).get("rptOwnerName") for d in owner]
        )
        ciks = ";".join(
            [d.get("reportingOwnerId", {}).get("rptOwnerCik") for d in owner]
        )

    issuer = data.get("issuer", {})
    owner_relationship = (
        owner.get("reportingOwnerRelationship", {})
        if isinstance(owner, dict)
        else (
            owner[0].get("reportingOwnerRelationship", {})
            if isinstance(owner, list)
            else {}
        )
    )
    signature_data = data.get("ownerSignature")

    if signature_data and isinstance(signature_data, dict):
        signature_date = signature_data.get("signatureDate")
    elif signature_data and isinstance(signature_data, list):
        signature_date = signature_data[0].get("signatureDate")
    else:
        signature_date = None

    footnotes = data.get("footnotes", {})
    if footnotes:
        footnote_items = footnotes.get("footnote")
        if isinstance(footnote_items, dict):
            footnote_items = [footnote_items]
        footnotes = {item["@id"]: item["#text"] for item in footnote_items}

    metadata = {
        "filing_date": signature_date or data.get("periodOfReport"),
        "symbol": issuer.get("issuerTradingSymbol", "").upper(),
        "form": data.get("documentType"),
        "owner": (
            owners if owners else owner.get("reportingOwnerId", {}).get("rptOwnerName")
        ),
        "owner_cik": (
            ciks if ciks else owner.get("reportingOwnerId", {}).get("rptOwnerCik")
        ),
        "issuer": issuer.get("issuerName"),
        "issuer_cik": issuer.get("issuerCik"),
        **owner_relationship,
    }
    results: list = []

    if data.get("nonDerivativeTable") and (
        data["nonDerivativeTable"].get("nonDerivativeTransaction")
        or data["nonDerivativeTable"].get("nonDerivativeHolding")
    ):
        temp_table = data["nonDerivativeTable"]
        tables = (
            temp_table["nonDerivativeTransaction"]
            if temp_table.get("nonDerivativeTransaction")
            else temp_table["nonDerivativeHolding"]
        )
        parsed_table1: list = []
        if isinstance(tables, dict):
            tables = [tables]
        for table in tables:
            if isinstance(table, str):
                continue
            new_row = {**metadata}
            for key, value in table.items():
                if key == "transactionCoding":
                    new_row["transaction_type"] = value.get("transactionCode")
                    new_row["form"] = (
                        value.get("transactionFormType") or metadata["form"]
                    )
                elif isinstance(value, dict):
                    if "footnoteId" in value:
                        if isinstance(value["footnoteId"], list):
                            ids = [item["@id"] for item in value["footnoteId"]]
                            footnotes = (
                                "; ".join(
                                    [
                                        footnotes.get(footnote_id, "")
                                        for footnote_id in ids
                                    ]
                                )
                                if isinstance(footnotes, dict)
                                else footnotes
                            )
                            new_row["footnote"] = footnotes
                        else:
                            footnote_id = value["footnoteId"]["@id"]
                            new_row["footnote"] = (
                                (
                                    footnotes
                                    if isinstance(footnotes, str)
                                    else footnotes.get(footnote_id)
                                )
                                if footnotes
                                else None
                            )
                    for k, v in value.items():
                        if k == "value":
                            new_row[key] = v
                        if isinstance(v, dict):
                            if "footnoteId" in v:
                                if isinstance(v["footnoteId"], list):
                                    ids = [item["@id"] for item in v["footnoteId"]]
                                    footnotes = (
                                        footnotes
                                        if isinstance(footnotes, str)
                                        else (
                                            "; ".join(
                                                [
                                                    footnotes.get(footnote_id, "")
                                                    for footnote_id in ids
                                                ]
                                            )
                                            if footnotes
                                            else None
                                        )
                                    )
                                    new_row["footnote"] = footnotes
                                else:
                                    footnote_id = v["footnoteId"]["@id"]
                                    new_row["footnote"] = (
                                        (
                                            footnotes
                                            if isinstance(footnotes, str)
                                            else footnotes.get(footnote_id)
                                        )
                                        if footnotes
                                        else None
                                    )
                            for k1, v1 in v.items():
                                if k1 == "value":
                                    new_row[k] = v1
            if new_row:
                parsed_table1.append(new_row)

        results.extend(parsed_table1)

    if (
        data.get("derivativeTable")
        and data["derivativeTable"].get("derivativeTransaction")
    ) or data.get("derivativeSecurity"):
        parsed_table2: list = []
        tables = (
            data["derivativeSecurity"]
            if data.get("derivativeSecurity")
            else data["derivativeTable"]["derivativeTransaction"]
        )
        if isinstance(tables, dict):
            tables = [tables]
        for table in tables:
            if isinstance(table, str):
                continue
            new_row = {**metadata}
            for key, value in table.items():
                if key == "transactionCoding":
                    new_row["transaction_type"] = value.get("transactionCode")
                    new_row["form"] = (
                        value.get("transactionFormType") or metadata["form"]
                    )
                elif isinstance(value, dict):
                    for k, v in value.items():
                        if k == "value":
                            new_row[key] = v
                        if isinstance(v, dict):
                            for k1, v1 in v.items():
                                if k1 == "value":
                                    new_row[k] = v1
            t_value = new_row.pop("transactionValue", None)
            if t_value:
                new_row["transactionTotalValue"] = t_value
            parsed_table2.append(new_row)

        results.extend(parsed_table2)

    return results


async def download_data(urls, use_cache: bool = True):
    """Get the Form 4 data from a list of URLs.

    Parsed filings are stored in the unified SEC disk cache, keyed by filing URL.
    A filing that yields no transactions is cached as an empty list so it is not
    re-downloaded on subsequent calls.
    """
    import asyncio  # noqa
    from numpy import nan
    from openbb_sec.utils.cache import aget_cached, aset_cached
    from pandas import DataFrame

    def _cache_key(url: str) -> str:
        """Build the cache key for a Form 4 filing URL."""
        return f"form4 {url}"

    results: list = []
    non_cached_urls: list = []

    if use_cache is True:
        cached = await asyncio.gather(*[aget_cached(_cache_key(url)) for url in urls])
        for url, entry in zip(urls, cached):
            if entry is None:
                non_cached_urls.append(url)
            elif entry:
                results.extend(entry)
    else:
        non_cached_urls = list(urls)

    async def get_one(url):
        """Fetch, parse, and cache the Form 4 data for one URL."""
        data = await get_form_4_data(url)
        result = await parse_form_4_data(data)
        rows: list = []
        if result:
            df = DataFrame(result)
            df["filing_url"] = url
            df = df.replace({nan: None}).rename(columns=field_map)
            rows = df.to_dict(orient="records")
            results.extend(rows)
        if use_cache is True:
            await aset_cached(_cache_key(url), rows)

    time_estimate = (len(non_cached_urls) / 7) * 1.8
    logger.info(
        "Found %d total filings and %d uncached entries to download, estimated download time: %d seconds.",
        len(urls),
        len(non_cached_urls),
        round(time_estimate),
    )
    min_warn_time = 10
    if time_estimate > min_warn_time:
        logger.info(
            "Warning: This function is not intended for mass data collection."
            " Long download times are due to limitations with concurrent downloads from the SEC."
            "\n\nReduce the number of requests by using a more specific date range."
        )

    if len(non_cached_urls) > 0:
        async with asyncio.Semaphore(8):
            for url_chunk in [
                non_cached_urls[i : i + 8] for i in range(0, len(non_cached_urls), 8)
            ]:
                await asyncio.gather(*[get_one(url) for url in url_chunk])
                await asyncio.sleep(1.125)

    results = [entry for entry in results if entry.get("filing_date")]

    return sorted(results, key=lambda x: x["filing_date"], reverse=True)


async def get_form_4(
    symbol,
    start_date: dateType | None = None,
    end_date: dateType | None = None,
    limit: int | None = None,
    use_cache: bool = True,
) -> list[dict]:
    """Get the Form 4 data by ticker symbol or CIK number."""
    import asyncio

    try:
        urls = await get_form_4_urls(symbol, start_date, end_date, use_cache)
        if limit is not None:
            urls = urls[:limit]
        data = await download_data(urls, use_cache)
    except asyncio.TimeoutError as e:
        raise OpenBBError(
            "A timeout error occurred while downloading the data. Please try again."
        ) from e

    if not data:
        raise OpenBBError(f"No Form 4 data was returned for {symbol}.")

    return data
