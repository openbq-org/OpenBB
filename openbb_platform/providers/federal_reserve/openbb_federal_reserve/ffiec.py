"""Federal Reserve FFIEC bank-supervision subrouter."""

from typing import Annotated

from fastapi import Body
from openbb_core.app.model.command_context import CommandContext
from openbb_core.app.model.example import APIEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.provider_interface import (
    ExtraParams,
    ProviderChoices,
    StandardParams,
)
from openbb_core.app.query import Query
from openbb_core.app.router import Router

router = Router(prefix="", description="FFIEC bank-supervision reports.")

_FR_META = {"category": "Federal Reserve", "subCategory": "FFIEC Reports"}


async def bhcpr_report_download(params: Annotated[dict, Body()]) -> list:
    """Download BHCPR peer-group report PDFs from the FFIEC.

    Parameters
    ----------
    params : dict
        A dictionary with a key "url" containing a list of PDF URLs to download.

    Returns
    -------
    list
        A list of dictionaries, each with `content` and `data_format` keys.
    """
    import base64

    from openbb_federal_reserve.utils.ffiec import download_bhcpr_pdf

    urls = params.get("url") or []
    results: list = []

    for url in urls:
        try:
            content = download_bhcpr_pdf(url)
            results.append(
                {
                    "content": base64.b64encode(content).decode("utf-8"),
                    "data_format": {
                        "data_type": "pdf",
                        "filename": url.split("/")[-1],
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            message = exc.args[0] if exc.args else str(exc)
            results.append(
                {
                    "error_type": "download_error",
                    "content": f"{exc.__class__.__name__}: {message}",
                    "filename": url.split("/")[-1],
                }
            )

    return results


async def bhcpr_report_choices(
    peer_group: str | None = None, year: int | None = None
) -> list:
    """Get the available BHCPR report PDFs for a peer group and year.

    Returns
    -------
    list
        File choices labelled by quarter and year with the PDF URL as the value.
    """
    from openbb_federal_reserve.utils.ffiec import list_bhcpr_reports

    matches = [
        report
        for report in list_bhcpr_reports()
        if (not peer_group or str(report["peer_group"]) == str(peer_group))
        and (not year or report["year"] == int(year))
    ]
    matches.sort(key=lambda report: (report["year"], report["quarter"]), reverse=True)

    return [
        {"label": f"Q{report['quarter']} {report['year']}", "value": report["url"]}
        for report in matches
    ]


async def financial_report_pdf_choices(
    rssd_id: str | None = None, report_type: str | None = None
) -> list:
    """Get the filed-report PDF choices for an institution and report type.

    Parameters
    ----------
    rssd_id : str | None
        The institution's RSSD identifier.
    report_type : str | None
        The FFIEC report code whose filed PDFs are listed.

    Returns
    -------
    list
        One ``{label, value}`` file choice per filed period, newest first.
    """
    from openbb_federal_reserve.models.ffiec.financial_report_pdf import _pdf_choices

    if not rssd_id:
        return []
    try:
        return _pdf_choices(rssd_id, report_type)
    except Exception:  # noqa: BLE001
        return []


async def financial_report_pdf_download(params: Annotated[dict, Body()]) -> list:
    """Download filed FFIEC financial-report PDFs from the FFIEC.

    Parameters
    ----------
    params : dict
        A dictionary with a key "url" containing a list of PDF URLs to download.

    Returns
    -------
    list
        A list of dictionaries, each with `content` and `data_format` keys.
    """
    import base64

    from openbb_federal_reserve.utils.ffiec import download_financial_report_pdf

    urls = params.get("url") or []
    results: list = []

    for url in urls:
        try:
            content = download_financial_report_pdf(url)
            results.append(
                {
                    "content": base64.b64encode(content).decode("utf-8"),
                    "data_format": {
                        "data_type": "pdf",
                        "filename": _pdf_filename(url),
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            message = exc.args[0] if exc.args else str(exc)
            results.append(
                {
                    "error_type": "download_error",
                    "content": f"{exc.__class__.__name__}: {message}",
                    "filename": _pdf_filename(url),
                }
            )

    return results


def _pdf_filename(url: str) -> str:
    """Build a descriptive filename from a ReturnFinancialReportPDF URL."""
    from urllib.parse import parse_qs, urlparse

    query = parse_qs(urlparse(url).query)
    rpt = (query.get("rpt") or [""])[0]
    rssd = (query.get("id") or [""])[0]
    dt = (query.get("dt") or [""])[0]
    if rpt and rssd and dt:
        return f"{rpt}_{rssd}_{dt}.pdf"
    return url.rsplit("/", maxsplit=1)[-1]


async def report_types(rssd_id: str | None = None) -> list:
    """Get the regulatory reports a selected institution actually files.

    Parameters
    ----------
    rssd_id : str | None
        The selected institution's RSSD identifier; cascades the choices.

    Returns
    -------
    list
        One ``{label, value}`` choice per available report.
    """
    from openbb_federal_reserve.utils.ffiec import (
        READY_REPORTS,
        fetch_institution_financial_reports,
    )

    rssd = str(rssd_id).strip() if rssd_id else ""
    filed: dict[str, dict] | None = None
    if rssd:
        try:
            filed = fetch_institution_financial_reports(rssd)
        except Exception:  # noqa: BLE001
            filed = None
    if not isinstance(filed, dict):
        filed = None

    return [
        {
            "label": (
                (filed.get(code, {}).get("name") if filed else None) or report["name"]
            ),
            "value": code,
        }
        for code, report in READY_REPORTS.items()
        if filed is None or code in filed
    ]


async def report_periods(
    rssd_id: str | None = None, report_type: str = "FRY9C"
) -> list:
    """Get the periods an institution has on file for a selected report.

    Parameters
    ----------
    rssd_id : str | None
        The selected institution's RSSD identifier.
    report_type : str
        The FFIEC report code whose filed periods are listed.

    Returns
    -------
    list
        One ``{label, value}`` choice per filed period, newest first.
    """
    from openbb_federal_reserve.utils.ffiec import fetch_institution_financial_reports

    rssd = str(rssd_id).strip() if rssd_id else ""
    if not rssd:
        return []
    code = str(report_type).strip().upper()
    try:
        reports = fetch_institution_financial_reports(rssd)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(reports, dict):
        return []

    month_day_to_end = {"3/31": "0331", "6/30": "0630", "9/30": "0930", "12/31": "1231"}
    return [
        {
            "label": f"{period['year']} Q{period['quarter']}",
            "value": f"{period['year']}{month_day_to_end[period['month_day']]}",
        }
        for period in reports.get(code, {}).get("periods", [])
    ]


async def report_sections(report_type: str = "FRY9C") -> list:
    """Get a report's schedule sections for the section dropdown.

    Parameters
    ----------
    report_type : str
        The FFIEC report code whose schedules are listed.

    Returns
    -------
    list
        An "All Sections" choice followed by one ``{label, value}`` choice per schedule.
    """
    import json
    from pathlib import Path

    from openbb_federal_reserve.utils.ffiec import READY_REPORTS

    report = READY_REPORTS.get(str(report_type).strip().upper())
    if report is None:
        return []
    asset = (
        Path(__file__).resolve().parent
        / "assets"
        / report["structure"]
        / "structure.json"
    )
    structure = json.loads(asset.read_text(encoding="utf-8"))
    choices: list = [{"label": "All Sections", "value": None}]
    for schedule in structure["schedules"]:
        if schedule["schedule"] == "COVER" or schedule["name"] == "Cover Page":
            continue
        choices.append({"label": schedule["name"], "value": schedule["schedule"]})
    return choices


async def bhcpr_periods(rssd_id: str | None = None) -> list:
    """Get the BHCPR periods a holding company has on file.

    Parameters
    ----------
    rssd_id : str | None
        The holding company's RSSD identifier.

    Returns
    -------
    list
        One ``{label, value}`` choice per filed period, newest first.
    """
    from openbb_federal_reserve.utils.ffiec import resolve_bhcpr_holder

    rssd = str(rssd_id).strip() if rssd_id else ""
    if not rssd:
        return []
    return await report_periods(resolve_bhcpr_holder(rssd), "BHCPR")


async def bhcpr_sections() -> list:
    """Get the BHCPR sections for the data widget's section dropdown.

    Returns
    -------
    list
        An "All Sections" choice followed by one ``{label, value}`` choice per BHCPR section.
    """
    from openbb_federal_reserve.utils.bhcpr_schema import section_titles

    choices: list = [{"label": "All Sections", "value": "All Sections"}]
    for title in section_titles():
        choices.append({"label": title, "value": title})
    return choices


router._api_router.add_api_route(
    path="/bhcpr_sections",
    endpoint=bhcpr_sections,
    methods=["GET"],
    include_in_schema=False,
)
router._api_router.add_api_route(
    path="/bhcpr_periods",
    endpoint=bhcpr_periods,
    methods=["GET"],
    include_in_schema=False,
)
router._api_router.add_api_route(
    path="/bhcpr_report_download",
    endpoint=bhcpr_report_download,
    methods=["POST"],
    include_in_schema=False,
)
router._api_router.add_api_route(
    path="/bhcpr_report_choices",
    endpoint=bhcpr_report_choices,
    methods=["GET"],
    include_in_schema=False,
)
router._api_router.add_api_route(
    path="/report_types",
    endpoint=report_types,
    methods=["GET"],
    include_in_schema=False,
)
router._api_router.add_api_route(
    path="/report_periods",
    endpoint=report_periods,
    methods=["GET"],
    include_in_schema=False,
)
router._api_router.add_api_route(
    path="/report_sections",
    endpoint=report_sections,
    methods=["GET"],
    include_in_schema=False,
)
router._api_router.add_api_route(
    path="/financial_report_pdf_choices",
    endpoint=financial_report_pdf_choices,
    methods=["GET"],
    include_in_schema=False,
)
router._api_router.add_api_route(
    path="/financial_report_pdf_download",
    endpoint=financial_report_pdf_download,
    methods=["POST"],
    include_in_schema=False,
)


@router.command(
    model="FederalReserveInstitutions",
    examples=[
        APIEx(
            description="Search the FFIEC NIC institution directory by name.",
            parameters={"name": "JPMorgan", "provider": "federal_reserve"},
        ),
        APIEx(
            description="Look up a single institution by RSSD id.",
            parameters={"rssd_id": "1039502", "provider": "federal_reserve"},
        ),
    ],
    widget_config={
        **_FR_META,
        "name": "FFIEC NIC Institution Search",
        "description": "Search the FFIEC National Information Center directory of"
        " financial institutions by name, ticker, or RSSD identifier. Click an"
        " RSSD to drive the Call Report, UBPR, financial-statement, and structure"
        " widgets.",
        "gridData": {"w": 40, "h": 20},
        "runButton": True,
        "params": [{"paramName": "rssd_id", "show": False}],
        "data": {
            "table": {
                "showAll": False,
                "columnsDefs": [
                    {
                        "field": "rssd_id",
                        "headerName": "RSSD ID",
                        "cellDataType": "text",
                        "formatterFn": "none",
                        "pinned": "left",
                        "renderFn": "cellOnClick",
                        "renderFnParams": {
                            "actionType": "groupBy",
                            "groupBy": {"paramName": "rssd_id"},
                        },
                    },
                    {
                        "field": "legal_name",
                        "headerName": "Legal Name",
                        "cellDataType": "text",
                    },
                    {
                        "field": "short_name",
                        "headerName": "Short Name",
                        "cellDataType": "text",
                    },
                    {
                        "field": "entity_type_description",
                        "headerName": "Entity Type",
                        "cellDataType": "text",
                    },
                    {
                        "field": "charter_type",
                        "headerName": "Charter Type",
                        "cellDataType": "text",
                    },
                    {
                        "field": "organization_type",
                        "headerName": "Organization Type",
                        "cellDataType": "text",
                    },
                    {
                        "field": "primary_federal_regulator",
                        "headerName": "Primary Federal Regulator",
                        "cellDataType": "text",
                    },
                    {
                        "field": "is_bank_holding_company",
                        "headerName": "Bank Holding Company",
                        "cellDataType": "text",
                    },
                    {
                        "field": "is_financial_holding_company",
                        "headerName": "Financial Holding Company",
                        "cellDataType": "text",
                    },
                    {"field": "city", "headerName": "City", "cellDataType": "text"},
                    {"field": "state", "headerName": "State", "cellDataType": "text"},
                    {
                        "field": "country",
                        "headerName": "Country",
                        "cellDataType": "text",
                    },
                    {
                        "field": "established_date",
                        "headerName": "Established Date",
                        "cellDataType": "date",
                    },
                    {
                        "field": "fdic_cert",
                        "headerName": "FDIC Cert",
                        "cellDataType": "text",
                    },
                    {
                        "field": "occ_id",
                        "headerName": "OCC ID",
                        "cellDataType": "text",
                    },
                    {"field": "lei", "headerName": "LEI", "cellDataType": "text"},
                    {"field": "url", "headerName": "URL", "cellDataType": "text"},
                ],
            }
        },
    },
)
async def institutions(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Search the FFIEC National Information Center institution directory."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="FederalReserveCallReport",
    examples=[
        APIEx(
            description="Get a bank's latest Call Report by ticker; the symbol"
            " resolves to the subsidiary bank, not the parent holding company.",
            parameters={"symbol": "JPM", "provider": "federal_reserve"},
        ),
        APIEx(
            description="Get a bank's latest Call Report by RSSD identifier.",
            parameters={"rssd_id": "852218", "provider": "federal_reserve"},
        ),
        APIEx(
            description="Get just the balance-sheet (instant) items by FDIC certificate.",
            parameters={
                "fdic_cert": "628",
                "period_type": "instant",
                "provider": "federal_reserve",
            },
        ),
    ],
    widget_config={
        **_FR_META,
        "name": "FFIEC Call Report (Condition & Income)",
        "description": "A commercial bank's FFIEC Call Report (Consolidated Reports"
        " of Condition and Income) by ticker, RSSD, or FDIC certificate.",
        "gridData": {"w": 40, "h": 20},
        "data": {
            "table": {
                "showAll": True,
                "columnsDefs": [
                    {
                        "field": "date",
                        "headerName": "Date",
                        "cellDataType": "date",
                        "pinned": "left",
                        "sort": "desc",
                    },
                    {
                        "field": "label",
                        "headerName": "Line Item",
                        "cellDataType": "text",
                        "pinned": "left",
                    },
                    {
                        "field": "rssd_id",
                        "headerName": "RSSD ID",
                        "cellDataType": "text",
                        "formatterFn": "none",
                    },
                ],
            }
        },
    },
)
async def call_report(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get a commercial bank's FFIEC Call Report (Consolidated Reports of Condition and Income)."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="FederalReserveUBPR",
    examples=[
        APIEx(
            description="Get a bank's UBPR performance measures by ticker; the"
            " symbol resolves to the subsidiary bank, not the holding company.",
            parameters={"symbol": "JPM", "provider": "federal_reserve"},
        ),
        APIEx(
            description="Get a bank's UBPR performance measures by RSSD identifier.",
            parameters={"rssd_id": "852218", "provider": "federal_reserve"},
        ),
    ],
    widget_config={
        **_FR_META,
        "name": "FFIEC Uniform Bank Performance Report (UBPR)",
        "description": "The Uniform Bank Performance Report (UBPR) is an analytical"
        " tool created for bank supervisory, examination, and management purposes. In"
        " a concise format, it shows the impact of management decisions and economic"
        " conditions on a bank's performance and balance-sheet composition. The"
        " performance and composition data contained in the report can be used as an"
        " aid in evaluating the adequacy of earnings, liquidity, capital, asset and"
        " liability management, and growth management. Bankers and examiners alike can"
        " use this report to further their understanding of a bank's financial"
        " condition, and through such understanding, perform their duties more"
        " effectively.",
        "gridData": {"w": 50, "h": 25},
        "data": {
            "table": {
                "showAll": True,
                "columnsDefs": [
                    {
                        "field": "label",
                        "headerName": "Line Item",
                        "cellDataType": "text",
                        "pinned": "left",
                        "width": 360,
                        "renderFn": "hoverCard",
                        "renderFnParams": {
                            "hoverCard": {
                                "cellField": "label",
                                "markdown": "{narrative}",
                            }
                        },
                    },
                    {"field": "is_header", "hide": True},
                    {"field": "narrative", "hide": True},
                ],
            }
        },
    },
)
async def ubpr(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get a bank's FFIEC Uniform Bank Performance Report (UBPR) measures."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="FederalReserveExecutiveSummary",
    examples=[
        APIEx(
            description="Get a bank's Executive Summary Report by ticker; the"
            " symbol resolves to the subsidiary bank, not the holding company.",
            parameters={"symbol": "JPM", "provider": "federal_reserve"},
        ),
        APIEx(
            description="Get a bank's Executive Summary Report by RSSD identifier.",
            parameters={"rssd_id": "451965", "provider": "federal_reserve"},
        ),
    ],
    widget_config={
        **_FR_META,
        "subCategory": "FFIEC Reports",
        "name": "FFIEC Executive Summary Report (ESR)",
        "description": "This report is intended for Bank Executives and Board Members"
        " to easily see the trend of an institution's key ratios.",
        "gridData": {"w": 50, "h": 25},
        "data": {
            "table": {
                "showAll": True,
                "columnsDefs": [
                    {
                        "field": "label",
                        "headerName": "Line Item",
                        "cellDataType": "text",
                        "pinned": "left",
                        "width": 360,
                        "renderFn": "hoverCard",
                        "renderFnParams": {
                            "hoverCard": {
                                "cellField": "label",
                                "markdown": "{narrative}",
                            }
                        },
                    },
                    {"field": "is_header", "hide": True},
                    {"field": "narrative", "hide": True},
                ],
            }
        },
    },
)
async def executive_summary(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get a bank's FFIEC Executive Summary Report (ESR) measures."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="FederalReserveCustomPeerGroup",
    examples=[
        APIEx(
            description="Get a bank's UBPR measures against a custom peer group of"
            " RSSDs, by ticker.",
            parameters={
                "symbol": "WFC",
                "peers": "451965,480228,852218",
                "provider": "federal_reserve",
            },
        ),
        APIEx(
            description="Get a bank's UBPR measures against a custom peer group of"
            " RSSDs, by RSSD identifier and report section.",
            parameters={
                "rssd_id": "451965",
                "peers": "451965,480228,852218",
                "section": "Capital Analysis-a",
                "provider": "federal_reserve",
            },
        ),
    ],
    widget_config={
        **_FR_META,
        "subCategory": "FFIEC Reports",
        "name": "FFIEC UBPR Custom Peer Group (CPG)",
        "description": "Similar to the UBPR this report is an analytical tool created"
        " for bank supervisory, examination, and management purposes. In a concise"
        " format, it shows the impact of management decisions and economic conditions"
        " on a bank's performance and balance-sheet composition, evaluated against a"
        " user-defined custom peer group.",
        "gridData": {"w": 50, "h": 25},
        "data": {
            "table": {
                "showAll": True,
                "columnsDefs": [
                    {
                        "field": "label",
                        "headerName": "Line Item",
                        "cellDataType": "text",
                        "pinned": "left",
                        "width": 360,
                        "renderFn": "hoverCard",
                        "renderFnParams": {
                            "hoverCard": {
                                "cellField": "label",
                                "markdown": "{narrative}",
                            }
                        },
                    },
                    {"field": "is_header", "hide": True},
                    {"field": "narrative", "hide": True},
                ],
            }
        },
    },
)
async def custom_peer_group(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get a bank's FFIEC UBPR measures against a custom peer group of RSSDs."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="FederalReservePeerGroupAverage",
    examples=[
        APIEx(
            description="Get the peer group average UBPR ratios for the largest"
            " insured commercial banks (assets greater than $100 billion).",
            parameters={"peer_group": "1", "provider": "federal_reserve"},
        ),
        APIEx(
            description="Get a peer group's average balance-sheet composition.",
            parameters={
                "peer_group": "4",
                "section": "Balance Sheet %",
                "provider": "federal_reserve",
            },
        ),
    ],
    widget_config={
        **_FR_META,
        "subCategory": "FFIEC Reports",
        "name": "FFIEC UBPR Peer Group Average Report",
        "description": "This report displays all UBPR ratios averaged by peer group in"
        " UBPR format. All peer groups are available.",
        "gridData": {"w": 50, "h": 25},
        "data": {
            "table": {
                "showAll": True,
                "columnsDefs": [
                    {
                        "field": "label",
                        "headerName": "Line Item",
                        "cellDataType": "text",
                        "pinned": "left",
                        "width": 360,
                        "renderFn": "hoverCard",
                        "renderFnParams": {
                            "hoverCard": {
                                "cellField": "label",
                                "markdown": "{narrative}",
                            }
                        },
                    },
                    {"field": "is_header", "hide": True},
                    {"field": "narrative", "hide": True},
                ],
            }
        },
    },
)
async def peer_group_average(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get a UBPR peer group's average performance ratios."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="FederalReservePeerGroupBank",
    examples=[
        APIEx(
            description="Get the UBPR Peer Group Bank Report for a bank by ticker;"
            " the symbol resolves to the subsidiary bank, whose UBPR peer group"
            " defines the set of banks compared.",
            parameters={"symbol": "WFC", "provider": "federal_reserve"},
        ),
        APIEx(
            description="Get the UBPR Peer Group Bank Report by RSSD identifier.",
            parameters={"rssd_id": "451965", "provider": "federal_reserve"},
        ),
    ],
    widget_config={
        **_FR_META,
        "subCategory": "FFIEC Reports",
        "name": "FFIEC UBPR Peer Group Bank Report",
        "description": "Displays the Uniform Bank Performance Report (UBPR) for every"
        " bank in a peer group side by side, so a bank's section line items can be"
        " compared directly against its peers for the latest reporting period.",
        "gridData": {"w": 50, "h": 25},
        "data": {
            "table": {
                "showAll": True,
                "columnsDefs": [
                    {
                        "field": "label",
                        "headerName": "Line Item",
                        "cellDataType": "text",
                        "pinned": "left",
                        "width": 360,
                        "renderFn": "hoverCard",
                        "renderFnParams": {
                            "hoverCard": {
                                "cellField": "label",
                                "markdown": "{narrative}",
                            }
                        },
                    },
                    {"field": "is_header", "hide": True},
                    {"field": "narrative", "hide": True},
                ],
            }
        },
    },
)
async def peer_group_bank(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get the FFIEC UBPR Peer Group Bank Report for a bank's peer group."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="FederalReservePeerGroupDistribution",
    examples=[
        APIEx(
            description="Get the percentile distribution of Summary Ratios across"
            " UBPR commercial-bank peer group 1.",
            parameters={"peer_group": "1", "provider": "federal_reserve"},
        ),
        APIEx(
            description="Get the Capital Analysis distribution for all insured"
            " commercial banks at a specific quarter.",
            parameters={
                "peer_group": "NATIONAL",
                "section": "Capital Analysis-a",
                "period": "2025-12-31",
                "provider": "federal_reserve",
            },
        ),
    ],
    widget_config={
        **_FR_META,
        "subCategory": "FFIEC Reports",
        "name": "FFIEC UBPR Peer Group Average Distribution",
        "description": "This report provides a distribution or range of values for all"
        " ratios that appear in the UBPR by peer group. The report can provide"
        " valuable insight into the population of banks that are used to calculate the"
        " peer average data that appears in the UBPR.",
        "gridData": {"w": 50, "h": 25},
        "data": {
            "table": {
                "showAll": True,
                "columnsDefs": [
                    {
                        "field": "label",
                        "headerName": "Line Item",
                        "cellDataType": "text",
                        "pinned": "left",
                        "width": 360,
                        "renderFn": "hoverCard",
                        "renderFnParams": {
                            "hoverCard": {
                                "cellField": "label",
                                "markdown": "{narrative}",
                            }
                        },
                    },
                    {"field": "narrative", "hide": True},
                    {"field": "is_header", "hide": True},
                ],
            }
        },
    },
)
async def peer_group_distribution(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get the FFIEC UBPR Peer Group Average Distribution for a peer group."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="FederalReserveStateAverage",
    examples=[
        APIEx(
            description="Get the UBPR State Average for South Dakota commercial banks.",
            parameters={"state": "SD", "provider": "federal_reserve"},
        ),
        APIEx(
            description="Get a State Average section for New York savings institutions.",
            parameters={
                "state": "NY",
                "group_type": "savings",
                "section": "Balance Sheet %",
                "provider": "federal_reserve",
            },
        ),
    ],
    widget_config={
        **_FR_META,
        "subCategory": "FFIEC Reports",
        "name": "FFIEC UBPR State Average Report",
        "description": "This report provides summary UBPR ratio data and selected"
        " aggregate information averaged by state. A further breakdown of average"
        " statistical data is provided by asset size. The information is provided for"
        " all states and territories in UBPR format.",
        "gridData": {"w": 40, "h": 25},
        "data": {
            "table": {
                "showAll": True,
                "columnsDefs": [
                    {
                        "field": "label",
                        "headerName": "Line Item",
                        "cellDataType": "text",
                        "pinned": "left",
                        "width": 360,
                        "renderFn": "hoverCard",
                        "renderFnParams": {
                            "hoverCard": {
                                "cellField": "label",
                                "markdown": "{narrative}",
                            }
                        },
                    },
                    {"field": "narrative", "hide": True},
                    {"field": "is_header", "hide": True},
                ],
            }
        },
    },
)
async def state_average(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get the FFIEC UBPR State Average report (state-level peer-group averages)."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="FederalReserveListOfBanksPeerGroup",
    examples=[
        APIEx(
            description="Get the roster of banks in UBPR peer group 1 (the"
            " largest commercial banks) for the latest reporting period.",
            parameters={"peer_group": "1", "provider": "federal_reserve"},
        ),
        APIEx(
            description="Get the banks in a peer group for a specific period.",
            parameters={
                "peer_group": "4",
                "date": "12/31/2025",
                "provider": "federal_reserve",
            },
        ),
    ],
    widget_config={
        **_FR_META,
        "subCategory": "FFIEC Reports",
        "name": "FFIEC List of Banks in Peer Group",
        "description": "This report provides a list of banks by peer group. The list"
        " includes core information such as location, assets and net income.",
        "gridData": {"w": 40, "h": 20},
        "data": {
            "table": {
                "showAll": True,
                "columnsDefs": [
                    {
                        "field": "rssd_id",
                        "headerName": "ID RSSD",
                        "cellDataType": "text",
                        "pinned": "left",
                        "width": 110,
                    },
                    {
                        "field": "name",
                        "headerName": "Name",
                        "cellDataType": "text",
                        "width": 260,
                    },
                    {
                        "field": "fdic_cert",
                        "headerName": "FDIC Cert.",
                        "cellDataType": "text",
                    },
                    {
                        "field": "charter_class",
                        "headerName": "Class",
                        "cellDataType": "text",
                    },
                    {"field": "city", "headerName": "City", "cellDataType": "text"},
                    {"field": "state", "headerName": "State", "cellDataType": "text"},
                    {
                        "field": "offices",
                        "headerName": "No. Offices",
                        "cellDataType": "number",
                    },
                    {
                        "field": "average_assets",
                        "headerName": "Average Assets ($)",
                        "cellDataType": "number",
                        "sort": "desc",
                    },
                    {
                        "field": "net_income",
                        "headerName": "Net Income ($)",
                        "cellDataType": "number",
                    },
                    {"field": "state_name", "hide": True},
                    {"field": "latitude", "hide": True},
                    {"field": "longitude", "hide": True},
                ],
            }
        },
    },
)
async def list_of_banks_peer_group(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get the FFIEC List of Banks in a UBPR peer group for a reporting period."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="FederalReserveCallReportSectioned",
    examples=[
        APIEx(
            description="Get a bank's Call Report balance sheet by ticker; the"
            " symbol resolves to the subsidiary bank, not the holding company.",
            parameters={"symbol": "WFC", "provider": "federal_reserve"},
        ),
        APIEx(
            description="Get a Call Report schedule by RSSD identifier.",
            parameters={
                "rssd_id": "451965",
                "section": "Schedule RI - Income Statement",
                "provider": "federal_reserve",
            },
        ),
    ],
    widget_config={
        **_FR_META,
        "subCategory": "FFIEC Reports",
        "name": "FFIEC Call Report (Sectioned)",
        "description": "A commercial bank's FFIEC Call Report rendered by"
        " schedule — line items across the five most recent quarters, in the"
        " Call Report's own section layout.",
        "gridData": {"w": 50, "h": 25},
        "data": {
            "table": {
                "showAll": True,
                "columnsDefs": [
                    {
                        "field": "label",
                        "headerName": "Line Item",
                        "cellDataType": "text",
                        "pinned": "left",
                        "width": 360,
                        "renderFn": "hoverCard",
                        "renderFnParams": {
                            "hoverCard": {
                                "cellField": "label",
                                "markdown": "{narrative}",
                            }
                        },
                    },
                    {"field": "is_header", "hide": True},
                    {"field": "narrative", "hide": True},
                ],
            }
        },
    },
)
async def call_report_sectioned(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get a commercial bank's FFIEC Call Report by schedule, periods as columns."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="FederalReserveCountryExposure",
    examples=[
        APIEx(
            description="Get the latest E16 country-exposure survey, all banks.",
            parameters={"provider": "federal_reserve"},
        ),
        APIEx(
            description="Get large financial institutions' claims by sector of"
            " obligor (Table 4.1) for a single country.",
            parameters={
                "group": "lfi",
                "table": "4.1",
                "country": "JAPAN",
                "provider": "federal_reserve",
            },
        ),
    ],
    widget_config={
        **_FR_META,
        "name": "FFIEC E.16 Country Exposure (FFIEC 009)",
        "description": "The FFIEC E.16 Country Exposure Lending Survey (FFIEC 009)"
        " of U.S. banks' foreign claims.",
        "gridData": {"w": 40, "h": 20},
        "data": {
            "table": {
                "showAll": True,
                "columnsDefs": [
                    {
                        "field": "date",
                        "headerName": "Date",
                        "cellDataType": "date",
                        "pinned": "left",
                    },
                    {
                        "field": "country_group",
                        "headerName": "Region",
                        "cellDataType": "text",
                        "pinned": "left",
                    },
                    {
                        "field": "country",
                        "headerName": "Country",
                        "cellDataType": "text",
                        "pinned": "left",
                    },
                ],
            }
        },
    },
)
async def country_exposure(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get the FFIEC E.16 Country Exposure Lending Survey (FFIEC 009)."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="FederalReserveLargeHoldingCompanies",
    examples=[
        APIEx(
            description="Get the 25 largest bank holding companies.",
            parameters={"limit": 25, "provider": "federal_reserve"},
        )
    ],
    widget_config={
        **_FR_META,
        "name": "Largest U.S. Bank Holding Companies",
        "description": "The largest U.S. bank holding companies ranked by total"
        " consolidated assets. Click an RSSD to drive the bank-condition widgets.",
        "gridData": {"w": 40, "h": 20},
        "data": {
            "table": {
                "showAll": False,
                "columnsDefs": [
                    {
                        "field": "date",
                        "headerName": "Date",
                        "cellDataType": "date",
                        "pinned": "left",
                    },
                    {
                        "field": "rank",
                        "headerName": "Rank",
                        "cellDataType": "number",
                        "formatterFn": "int",
                    },
                    {
                        "field": "rssd_id",
                        "headerName": "RSSD ID",
                        "cellDataType": "text",
                        "formatterFn": "none",
                        "renderFn": "cellOnClick",
                        "renderFnParams": {
                            "actionType": "groupBy",
                            "groupBy": {"paramName": "rssd_id"},
                        },
                    },
                    {"field": "name", "headerName": "Name", "cellDataType": "text"},
                    {
                        "field": "location",
                        "headerName": "Location",
                        "cellDataType": "text",
                    },
                    {
                        "field": "total_assets",
                        "headerName": "Total Assets ($)",
                        "cellDataType": "number",
                        "formatterFn": "int",
                    },
                ],
            }
        },
    },
)
async def large_holding_companies(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get the largest US bank holding companies ranked by total assets."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="FederalReserveInstitutionStructure",
    examples=[
        APIEx(
            description="Get holding-company ownership relationships for an institution.",
            parameters={"rssd_id": "1039502", "provider": "federal_reserve"},
        ),
        APIEx(
            description="Get merger/acquisition transformations.",
            parameters={
                "kind": "transformations",
                "rssd_id": "1039502",
                "provider": "federal_reserve",
            },
        ),
    ],
    widget_config={
        **_FR_META,
        "name": "FFIEC NIC Institution Structure",
        "description": "NIC ownership relationships and merger/acquisition"
        " transformation history for the selected institution (RSSD).",
        "gridData": {"w": 40, "h": 20},
        "data": {
            "table": {
                "showAll": False,
                "columnsDefs": [
                    {
                        "field": "offspring_name",
                        "headerName": "Subsidiary",
                        "cellDataType": "text",
                        "pinned": "left",
                    },
                    {
                        "field": "parent_name",
                        "headerName": "Parent",
                        "cellDataType": "text",
                        "pinned": "left",
                    },
                    {
                        "field": "successor_name",
                        "headerName": "Successor",
                        "cellDataType": "text",
                    },
                    {
                        "field": "predecessor_name",
                        "headerName": "Predecessor",
                        "cellDataType": "text",
                    },
                    {
                        "field": "relationship_level",
                        "headerName": "Relationship",
                        "cellDataType": "text",
                    },
                    {
                        "field": "control_indicator",
                        "headerName": "Control",
                        "cellDataType": "text",
                    },
                    {
                        "field": "percent_equity",
                        "headerName": "Equity %",
                        "cellDataType": "number",
                    },
                    {
                        "field": "equity_indicator",
                        "headerName": "Basis of Control",
                        "cellDataType": "text",
                    },
                    {
                        "field": "percent_equity_bracket",
                        "headerName": "Equity Range",
                        "cellDataType": "text",
                    },
                    {
                        "field": "percent_other",
                        "headerName": "Other Voting %",
                        "cellDataType": "number",
                    },
                    {
                        "field": "regulated_indicator",
                        "headerName": "Regulated",
                        "cellDataType": "text",
                    },
                    {
                        "field": "reason_relationship_terminated",
                        "headerName": "Termination Reason",
                        "cellDataType": "text",
                    },
                    {
                        "field": "transformation_type",
                        "headerName": "Transformation",
                        "cellDataType": "text",
                    },
                    {
                        "field": "accounting_method",
                        "headerName": "Accounting Method",
                        "cellDataType": "text",
                    },
                    {
                        "field": "relationship_established_date",
                        "headerName": "Established",
                        "cellDataType": "date",
                    },
                    {
                        "field": "start_date",
                        "headerName": "Start",
                        "cellDataType": "date",
                    },
                    {
                        "field": "end_date",
                        "headerName": "End",
                        "cellDataType": "date",
                    },
                    {
                        "field": "transformation_date",
                        "headerName": "Transformation Date",
                        "cellDataType": "date",
                    },
                    {
                        "field": "offspring_rssd_id",
                        "headerName": "Subsidiary RSSD",
                        "cellDataType": "text",
                        "formatterFn": "none",
                    },
                    {
                        "field": "parent_rssd_id",
                        "headerName": "Parent RSSD",
                        "cellDataType": "text",
                        "formatterFn": "none",
                    },
                    {
                        "field": "successor_rssd_id",
                        "headerName": "Successor RSSD",
                        "cellDataType": "text",
                        "formatterFn": "none",
                    },
                    {
                        "field": "predecessor_rssd_id",
                        "headerName": "Predecessor RSSD",
                        "cellDataType": "text",
                        "formatterFn": "none",
                    },
                ],
            }
        },
    },
)
async def institution_structure(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get NIC institution ownership relationships or merger transformations."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="FederalReserveBhcprReport",
    examples=[
        APIEx(
            description="Get the Peer 1 ($10B and over) BHCPR reports.",
            parameters={"peer_group": "1", "provider": "federal_reserve"},
        ),
        APIEx(
            description="Get a peer group's reports for a single year.",
            parameters={
                "peer_group": "1",
                "year": 2024,
                "provider": "federal_reserve",
            },
        ),
    ],
)
async def bhcpr_report(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Browse Bank Holding Company Performance Report (BHCPR) peer-group average PDFs."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="FederalReserveFinancialReport",
    examples=[
        APIEx(
            description="Get JPMorgan Chase & Co.'s latest FR Y-9C report by RSSD.",
            parameters={"rssd_id": "1039502", "provider": "federal_reserve"},
        ),
        APIEx(
            description="Get a single schedule of a holding company's FR Y-15"
            " systemic-risk report.",
            parameters={
                "rssd_id": "1039502",
                "report_type": "FRY15",
                "section": "A",
                "provider": "federal_reserve",
            },
        ),
    ],
    widget_config={
        **_FR_META,
        "name": "FFIEC Regulatory Financial Report",
        "description": "An institution's regulatory financial report (FR Y-9C, FFIEC"
        " 101, FFIEC 102, or FR Y-15) rendered in the report's own schedule layout,"
        " for the selected reporting period.",
        "gridData": {"w": 50, "h": 25},
        "data": {
            "table": {
                "showAll": True,
                "columnsDefs": [
                    {
                        "field": "label",
                        "headerName": "Line Item",
                        "cellDataType": "text",
                        "pinned": "left",
                        "width": 360,
                        "renderFn": "hoverCard",
                        "renderFnParams": {
                            "hoverCard": {
                                "cellField": "label",
                                "markdown": "{narrative}",
                            }
                        },
                    },
                    {
                        "field": "value",
                        "headerName": "Value",
                        "cellDataType": "number",
                        "formatterFn": "int",
                    },
                    {"field": "is_header", "hide": True},
                    {"field": "narrative", "hide": True},
                ],
            }
        },
    },
)
async def financial_report(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get an institution's FFIEC regulatory financial report by schedule."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="FederalReserveFinancialReportPdf",
    examples=[
        APIEx(
            description="Get JPMorgan Chase & Co.'s filed FR Y-9C report PDFs.",
            parameters={"rssd_id": "1039502", "provider": "federal_reserve"},
        ),
        APIEx(
            description="Get a holding company's filed FR Y-15 report PDFs.",
            parameters={
                "rssd_id": "1039502",
                "report_type": "FRY15",
                "provider": "federal_reserve",
            },
        ),
    ],
)
async def financial_report_pdf(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Browse an institution's filed FFIEC regulatory financial reports as PDFs."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="FederalReserveBhcpr",
    examples=[
        APIEx(
            description="Get JPMorgan Chase & Co.'s latest BHCPR performance"
            " measures by RSSD.",
            parameters={"rssd_id": "1039502", "provider": "federal_reserve"},
        ),
        APIEx(
            description="Get a single BHCPR report section for a holding company.",
            parameters={
                "rssd_id": "1039502",
                "section": "Regulatory Capital Components and Ratios",
                "provider": "federal_reserve",
            },
        ),
    ],
    widget_config={
        **_FR_META,
        "name": "FFIEC Bank Holding Company Performance Report (BHCPR)",
        "description": "A bank holding company's BHCPR performance data rendered in"
        " the report's own section layout, with the holding-company value, the"
        " peer-group average, and the percentile rank for the current period plus"
        " the value for each of the four prior-year periods.",
        "gridData": {"w": 50, "h": 25},
        "data": {
            "table": {
                "showAll": True,
                "columnsDefs": [
                    {
                        "field": "label",
                        "headerName": "Line Item",
                        "cellDataType": "text",
                        "pinned": "left",
                        "width": 360,
                    },
                    {
                        "field": "bank",
                        "headerName": "BHC",
                        "headerTooltip": "The holding company's value for the"
                        " current period.",
                        "cellDataType": "number",
                    },
                    {
                        "field": "peer",
                        "headerName": "Peer Group",
                        "headerTooltip": "The peer-group average for the current"
                        " period.",
                        "cellDataType": "number",
                    },
                    {
                        "field": "percentile",
                        "headerName": "Percentile",
                        "headerTooltip": "The holding company's percentile rank"
                        " within its peer group.",
                        "cellDataType": "number",
                    },
                    {"field": "is_header", "hide": True},
                ],
            }
        },
    },
)
async def bhcpr(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get a bank holding company's BHCPR performance data by section."""
    return await OBBject.from_query(Query(**locals()))
