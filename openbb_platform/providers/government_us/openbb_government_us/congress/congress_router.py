"""US Congress Router."""

import logging
from typing import Any

from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse
from openbb_core.app.model.command_context import CommandContext
from openbb_core.app.model.example import APIEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.provider_interface import (
    ExtraParams,
    ProviderChoices,
    StandardParams,
)
from openbb_core.app.query import Query as OpenBBQuery
from openbb_core.app.router import Router
from openbb_core.app.service.system_service import SystemService

from openbb_government_us.congress.utils.constants import (
    COMMITTEES,
    SUBCOMMITTEES,
    chamber_options,
)

NO_SUBCOMMITTEES = [{"label": "None (Parent Committee)", "value": None}]
router = Router(prefix="", description="Data connector to Congress.gov API.")
api_prefix = SystemService().system_settings.api_settings.prefix
logger = logging.getLogger("uvicorn.error")


@router.command(
    model="CongressBills",
    examples=[
        APIEx(parameters={"provider": "congress_gov"}),
        APIEx(
            parameters={
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
                "provider": "congress_gov",
            }
        ),
        APIEx(
            description="Get all bills of type 's' (Senate) for the 118th Congress.",
            parameters={
                "bill_type": "s",
                "congress": 118,
                "limit": 0,
                "provider": "congress_gov",
            },
        ),
    ],
)
async def bills(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get and filter lists of Congressional Bills."""
    return await OBBject.from_query(OpenBBQuery(**locals()))


@router.command(
    model="CongressLaws",
    examples=[
        APIEx(parameters={"provider": "congress_gov"}),
        APIEx(
            description="Get the 5 most recent public laws of the 118th Congress.",
            parameters={
                "congress": 118,
                "law_type": "public",
                "limit": 5,
                "provider": "congress_gov",
            },
        ),
    ],
)
async def laws(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get and filter lists of enacted Congressional Laws (public or private)."""
    return await OBBject.from_query(OpenBBQuery(**locals()))


@router.command(
    model="CongressCalendars",
    examples=[
        APIEx(parameters={"chamber": "house", "provider": "congress_gov"}),
        APIEx(
            description="Get the most recent Senate calendar.",
            parameters={
                "chamber": "senate",
                "publishdate": "mostrecent",
                "provider": "congress_gov",
            },
        ),
    ],
)
async def calendars(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get House or Senate Congressional Calendar editions."""
    return await OBBject.from_query(OpenBBQuery(**locals()))


@router.command(
    model="CongressMandatedReports",
    examples=[
        APIEx(parameters={"provider": "congress_gov"}),
        APIEx(
            description="Get the 10 most recent mandated reports for the 119th Congress.",
            parameters={"congress": 119, "limit": 10, "provider": "congress_gov"},
        ),
    ],
)
async def mandated_reports(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get Congressionally Mandated Reports submitted by federal agencies."""
    return await OBBject.from_query(OpenBBQuery(**locals()))


@router.command(
    model="CongressSearch",
    examples=[
        APIEx(
            parameters={"query": "artificial intelligence", "provider": "congress_gov"}
        ),
        APIEx(
            description="Search hearings in the 119th Congress for 'immigration'.",
            parameters={
                "query": "immigration",
                "collection": "CHRG",
                "congress": 119,
                "provider": "congress_gov",
            },
        ),
    ],
)
async def search(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Full-text search across congressional GovInfo collections."""
    return await OBBject.from_query(OpenBBQuery(**locals()))


def _document_viewer_config(
    name: str, description: str, widget_id: str, options_endpoint: str
) -> dict:
    """Build a multi_file_viewer widget_config that groups by ``package_id``."""
    return {
        "widget_config": {
            "name": name,
            "description": description,
            "category": "Government",
            "subCategory": "Congress",
            "type": "multi_file_viewer",
            "widgetId": widget_id,
            "endpoint": f"{api_prefix}/uscongress/bill_text",
            "params": [
                {
                    "paramName": "urls",
                    "type": "endpoint",
                    "optionsEndpoint": f"{api_prefix}/uscongress/{options_endpoint}",
                    "optionsParams": {
                        "package_id": "$package_id",
                        "is_workspace": True,
                    },
                    "show": False,
                    "multiSelect": True,
                    "roles": ["fileSelector"],
                },
                {"paramName": "is_workspace", "value": True, "show": False},
                {
                    "label": "Package ID",
                    "description": "The GovInfo package id. Group by 'package_id' on"
                    + " the source table and click a cell to load the document.",
                    "show": True,
                    "paramName": "package_id",
                    "value": None,
                },
            ],
            "refetchInterval": False,
        }
    }


@router.command(
    methods=["GET"],
    examples=[
        APIEx(
            parameters={
                "provider": "congress_gov",
                "law_id": "119-1",
                "law_type": "public",
            }
        ),
    ],
    openapi_extra={
        "widget_config": {
            "name": "Congressional Law Viewer",
            "description": "View the text of an enacted public or private law.",
            "category": "Government",
            "subCategory": "Congress",
            "type": "multi_file_viewer",
            "widgetId": "uscongress_law_viewer_congress_gov_obb",
            "endpoint": f"{api_prefix}/uscongress/bill_text",
            "params": [
                {
                    "paramName": "urls",
                    "type": "endpoint",
                    "optionsEndpoint": f"{api_prefix}/uscongress/law_text_urls",
                    "optionsParams": {
                        "law_id": "$law_id",
                        "law_type": "$law_type",
                        "is_workspace": True,
                    },
                    "show": False,
                    "multiSelect": True,
                    "roles": ["fileSelector"],
                },
                {"paramName": "is_workspace", "value": True, "show": False},
                {
                    "label": "Law Type",
                    "show": True,
                    "paramName": "law_type",
                    "value": "public",
                    "options": [
                        {"label": "Public Law", "value": "public"},
                        {"label": "Private Law", "value": "private"},
                    ],
                },
                {
                    "label": "Law ID",
                    "description": "Group the Laws table by 'Law ID' and click a cell"
                    + " to load the law text.",
                    "show": True,
                    "paramName": "law_id",
                    "value": None,
                },
            ],
            "refetchInterval": False,
        }
    },
)
async def law_text_urls(
    law_id: str | None = None,
    law_type: str = "public",
    congress: int | None = None,
    provider: str = "congress_gov",
    is_workspace: bool = False,
) -> list:
    """Resolve a law's links by law id, falling back to recent enacted laws."""
    from openbb_government_us.congress.utils.helpers import (
        document_choices_from_records,
        get_document_choices,
    )

    if law_id and "-" in law_id:
        cong, number = law_id.split("-", 1)
        suffix = "pvtl" if law_type.lower() == "private" else "publ"
        return get_document_choices(f"PLAW-{cong}{suffix}{number}", is_workspace)

    import asyncio
    from datetime import datetime

    from openbb_government_us.congress.utils.bulk import load_plaw
    from openbb_government_us.congress.utils.helpers import year_to_congress

    cong = int(congress) if congress else year_to_congress(datetime.now().year)
    loaded = await asyncio.gather(load_plaw(cong, "public"), load_plaw(cong, "private"))
    records = [record for type_records in loaded for record in type_records]
    records.sort(key=lambda record: record.get("package_id", ""), reverse=True)

    return document_choices_from_records(records[:25], is_workspace)


@router.command(
    methods=["GET"],
    examples=[
        APIEx(
            parameters={
                "provider": "congress_gov",
                "package_id": "CCAL-119hcal-2025-01-03",
            }
        ),
    ],
    openapi_extra=_document_viewer_config(
        "Congressional Calendar Viewer",
        "View a House or Senate Congressional Calendar edition.",
        "uscongress_calendar_viewer_congress_gov_obb",
        "calendar_document_urls",
    ),
)
async def calendar_document_urls(
    package_id: str | None = None,
    congress: int | None = None,
    provider: str = "congress_gov",
    is_workspace: bool = False,
) -> list:
    """Resolve a calendar edition's links, falling back to recent editions."""
    from openbb_government_us.congress.utils.helpers import (
        document_choices_from_records,
        get_document_choices,
    )

    if package_id:
        return get_document_choices(package_id, is_workspace)

    import asyncio
    from datetime import datetime

    from openbb_government_us.congress.utils.bulk import load_calendars
    from openbb_government_us.congress.utils.helpers import year_to_congress

    cong = int(congress) if congress else year_to_congress(datetime.now().year)
    loaded = await asyncio.gather(
        load_calendars(cong, "house"), load_calendars(cong, "senate")
    )
    records = [record for chamber_records in loaded for record in chamber_records]
    records.sort(key=lambda record: record["calendar_date"], reverse=True)

    return document_choices_from_records(records[:25], is_workspace)


@router.command(
    methods=["GET"],
    examples=[
        APIEx(
            parameters={
                "provider": "congress_gov",
                "package_id": "CMR-A98-00199920",
            }
        ),
    ],
    openapi_extra=_document_viewer_config(
        "Mandated Report Viewer",
        "View a Congressionally Mandated Report submitted by a federal agency.",
        "uscongress_mandated_report_viewer_congress_gov_obb",
        "mandated_report_urls",
    ),
)
async def mandated_report_urls(
    package_id: str | None = None,
    congress: int | None = None,
    provider: str = "congress_gov",
    is_workspace: bool = False,
) -> list:
    """Resolve a mandated report's links, falling back to recent reports."""
    from openbb_government_us.congress.utils.helpers import (
        document_choices_from_records,
        get_document_choices,
    )

    if package_id:
        return get_document_choices(package_id, is_workspace)

    from datetime import datetime

    from openbb_government_us.congress.utils.bulk import fetch_cmr
    from openbb_government_us.congress.utils.helpers import year_to_congress

    cong = int(congress) if congress else year_to_congress(datetime.now().year)
    records = await fetch_cmr(cong, pagesize=25, offset=0)

    return document_choices_from_records(records, is_workspace)


@router.command(
    methods=["GET"],
    examples=[
        APIEx(
            parameters={"provider": "congress_gov", "package_id": "CHRG-119hhrg63299"}
        ),
    ],
    openapi_extra=_document_viewer_config(
        "Congressional Search Viewer",
        "View a document returned by the congressional full-text search.",
        "uscongress_search_viewer_congress_gov_obb",
        "search_document_urls",
    ),
)
async def search_document_urls(
    package_id: str | None = None,
    provider: str = "congress_gov",
    is_workspace: bool = False,
) -> list:
    """Get the document link for a search result, by GovInfo package id."""
    from openbb_government_us.congress.utils.helpers import get_document_choices

    return get_document_choices(package_id, is_workspace)


@router.command(
    methods=["GET"],
    examples=[
        APIEx(parameters={"provider": "congress_gov", "bill_id": "119-hr-29"}),
    ],
    openapi_extra={
        "widget_config": {
            "name": "Congressional Bill Viewer",
            "description": "View current and historical U.S. Congressional Bills.",
            "category": "Government",
            "subCategory": "Congress",
            "type": "multi_file_viewer",
            "widgetId": "uscongress_bill_text_congress_gov_obb",
            "endpoint": f"{api_prefix}/uscongress/bill_text",
            "params": [
                {
                    "paramName": "urls",
                    "type": "endpoint",
                    "optionsEndpoint": f"{api_prefix}/uscongress/bill_text_urls",
                    "optionsParams": {
                        "bill_id": "$bill_id",
                        "is_workspace": True,
                    },
                    "show": False,
                    "multiSelect": True,
                    "roles": ["fileSelector"],
                },
                {
                    "paramName": "is_workspace",
                    "value": True,
                    "show": False,
                },
                {
                    "label": "Bill ID",
                    "description": "Enter a bill id (e.g. '119-hr-29'), or group the"
                    + " 'Congressional Bills' widget by 'Bill ID' and click a cell.",
                    "show": True,
                    "paramName": "bill_id",
                    "value": "119-hr-1",
                },
            ],
            "refetchInterval": False,
        }
    },
)
async def bill_text_urls(
    bill_id: str | None = None,
    provider: str = "congress_gov",
    is_workspace: bool = False,
) -> list:
    """Get the available text-version document links for a bill, by bill id."""
    from openbb_government_us.congress.utils.helpers import get_bill_text_choices

    if not bill_id:
        if is_workspace is True:
            return [
                {"label": "Select a bill to view available documents.", "value": None}
            ]
        raise HTTPException(
            status_code=500,
            detail="A bill_id (e.g. '119-hr-29') is required.",
        )

    return await get_bill_text_choices(bill_id=bill_id, is_workspace=is_workspace)


@router.command(
    model="CongressBillInfo",
    examples=[
        APIEx(
            parameters={
                "provider": "congress_gov",
                "bill_url": "https://api.congress.gov/v3/bill/119/s/1947?",
            }
        ),
        APIEx(
            description="The bill URL can be shortened to just the bill number (e.g., '119/s/1947').",
            parameters={
                "bill_url": "119/s/1947",
                "provider": "congress_gov",
            },
        ),
    ],
)
async def bill_info(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get summary, status, and other metadata for a specific bill."""
    return await OBBject.from_query(OpenBBQuery(**locals()))


@router.command(
    model="CongressBillText",
    response_model=list,
    no_validate=True,
    methods=["POST"],
    examples=[
        APIEx(
            parameters={
                "provider": "congress_gov",
                "urls": ["https://www.congress.gov/119/bills/hr1/BILLS-119hr1eh.pdf"],
            }
        ),
    ],
    openapi_extra={
        "widget_config": {
            "exclude": True,
        }
    },
)
async def bill_text(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> Any:
    """Download the content of bill(s) from a Congress.gov file."""
    return (await OBBject.from_query(OpenBBQuery(**locals()))).results


@router.command(
    model="CongressAmendments",
    examples=[
        APIEx(parameters={"provider": "congress_gov"}),
        APIEx(
            parameters={
                "congress": 119,
                "amendment_type": "hamdt",
                "provider": "congress_gov",
            }
        ),
    ],
)
async def amendments(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get and filter lists of Congressional Amendments."""
    return await OBBject.from_query(OpenBBQuery(**locals()))


@router.command(
    methods=["GET"],
    examples=[
        APIEx(parameters={"provider": "congress_gov", "amendment_id": "119-hamdt-2"}),
    ],
    openapi_extra={
        "widget_config": {
            "name": "Congressional Amendment Viewer",
            "description": "View Congressional Record documents for a U.S. Amendment.",
            "category": "Government",
            "subCategory": "Congress",
            "type": "multi_file_viewer",
            "widgetId": "uscongress_amendment_text_congress_gov_obb",
            "endpoint": f"{api_prefix}/uscongress/amendment_text",
            "params": [
                {
                    "paramName": "urls",
                    "type": "endpoint",
                    "optionsEndpoint": f"{api_prefix}/uscongress/amendment_text_urls",
                    "optionsParams": {
                        "amendment_id": "$amendment_id",
                        "is_workspace": True,
                    },
                    "show": False,
                    "multiSelect": True,
                    "roles": ["fileSelector"],
                },
                {
                    "paramName": "is_workspace",
                    "value": True,
                    "show": False,
                },
                {
                    "label": "Amendment ID",
                    "description": "Enter an amendment id (e.g. '119-samdt-2'), or group"
                    + " the 'Congressional Amendments' widget by 'Amendment ID' and"
                    + " click a cell.",
                    "show": True,
                    "paramName": "amendment_id",
                    "value": "119-samdt-2",
                },
            ],
            "refetchInterval": False,
        }
    },
)
async def amendment_text_urls(
    amendment_id: str | None = None,
    provider: str = "congress_gov",
    is_workspace: bool = False,
) -> list:
    """Get the Congressional Record document links for an amendment, by amendment id."""
    from openbb_government_us.congress.utils.helpers import get_amendment_text_choices

    if not amendment_id:
        if is_workspace is True:
            return [
                {
                    "label": "Select an amendment to view available documents.",
                    "value": None,
                }
            ]
        raise HTTPException(
            status_code=500,
            detail="An amendment_id (e.g. '119-hamdt-2') is required.",
        )

    return await get_amendment_text_choices(
        amendment_id=amendment_id, is_workspace=is_workspace
    )


@router.command(
    model="CongressAmendmentInfo",
    examples=[
        APIEx(parameters={"provider": "congress_gov", "amendment_id": "119-hamdt-2"}),
    ],
)
async def amendment_info(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get details for a specific amendment."""
    return await OBBject.from_query(OpenBBQuery(**locals()))


@router.command(
    model="CongressAmendmentText",
    response_model=list,
    no_validate=True,
    methods=["POST"],
    examples=[
        APIEx(
            parameters={
                "provider": "congress_gov",
                "urls": [
                    "https://www.govinfo.gov/content/pkg/CREC-2022-03-24/pdf/CREC-2022-03-24-pt1-PgS1778-4.pdf"
                ],
            }
        ),
    ],
    openapi_extra={
        "widget_config": {
            "exclude": True,
        }
    },
)
async def amendment_text(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> Any:
    """Download amendment document(s) from Congress.gov."""
    return (await OBBject.from_query(OpenBBQuery(**locals()))).results


@router.command(
    model="CongressCommitteeInfo",
    examples=[
        APIEx(
            parameters={
                "chamber": "senate",
                "committee": "ssaf00",
                "provider": "congress_gov",
            }
        ),
        APIEx(
            parameters={
                "chamber": "house",
                "committee": "hsju00",
                "provider": "congress_gov",
            }
        ),
        APIEx(
            description="Get info for a subcommittee.",
            parameters={
                "chamber": "senate",
                "committee": "ssga00",
                "subcommittee": "ssga22",
                "provider": "congress_gov",
            },
        ),
    ],
)
async def committee_info(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get metadata and membership for a single U.S. Congressional Committee."""
    return await OBBject.from_query(OpenBBQuery(**locals()))


@router.command(
    model="CongressCommitteeDocuments",
    openapi_extra={"widget_config": {"exclude": True}},
    examples=[
        APIEx(
            description="Get reports from the Senate Agriculture Committee.",
            parameters={
                "chamber": "senate",
                "committee": "ssaf00",
                "doc_type": "report",
                "provider": "congress_gov",
            },
        ),
        APIEx(
            description="Get hearings from the House Judiciary Committee for the 119th Congress.",
            parameters={
                "chamber": "house",
                "committee": "hsju00",
                "doc_type": "meeting",
                "congress": 119,
                "provider": "congress_gov",
            },
        ),
    ],
)
async def committee_documents(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get documents (reports, hearings, prints, meetings) produced by a single Congressional Committee."""
    return await OBBject.from_query(OpenBBQuery(**locals()))


@router.command(
    methods=["GET"],
    openapi_extra={"widget_config": {"exclude": True}},
)
async def committee_choices(
    chamber: str | None = None,
    congress: int | None = None,
    committee: str | None = None,
    subcommittees: bool = False,
    provider: str = "congress_gov",
    is_workspace: bool = False,
) -> list:
    """Get committee or subcommittee choices for cascading dropdowns."""
    if not chamber:
        return chamber_options

    chamber = chamber.lower()

    if subcommittees and not committee:
        return [{"label": "Select a committee first.", "value": None}]

    if subcommittees and committee:
        return SUBCOMMITTEES.get(f"{chamber}/{committee}", NO_SUBCOMMITTEES)

    if chamber not in ("senate", "house", "joint"):
        return [{"label": "Invalid chamber.", "value": None}]

    return COMMITTEES.get(chamber, [{"label": "No committees found.", "value": None}])


@router.command(
    methods=["GET"],
    examples=[
        APIEx(
            parameters={
                "provider": "congress_gov",
                "chamber": "senate",
                "committee": "ssaf00",
            },
        ),
    ],
    openapi_extra={
        "widget_config": {
            "name": "Committee Document Viewer",
            "description": "Browse and view documents for a U.S. Congressional Committee.",
            "category": "Government",
            "subCategory": "Congress",
            "type": "multi_file_viewer",
            "widgetId": "uscongress_committee_document_viewer_congress_gov_obb",
            "endpoint": f"{api_prefix}/uscongress/bill_text",
            "params": [
                {
                    "paramName": "urls",
                    "type": "endpoint",
                    "optionsEndpoint": f"{api_prefix}/uscongress/committee_document_urls",
                    "optionsParams": {
                        "chamber": "$chamber",
                        "committee": "$committee",
                        "subcommittee": "$subcommittee",
                        "doc_type": "$doc_type",
                        "congress": "$congress",
                        "is_workspace": True,
                    },
                    "show": False,
                    "multiSelect": True,
                    "roles": ["fileSelector"],
                },
                {
                    "paramName": "is_workspace",
                    "value": True,
                    "show": False,
                },
                {
                    "label": "Congress",
                    "description": "Congress number (e.g. 119).",
                    "show": True,
                    "paramName": "congress",
                    "value": 119,
                    "type": "number",
                },
                {
                    "label": "Chamber",
                    "show": True,
                    "paramName": "chamber",
                    "type": "endpoint",
                    "optionsEndpoint": f"{api_prefix}/uscongress/committee_choices",
                    "optionsParams": {"congress": "$congress", "is_workspace": True},
                },
                {
                    "label": "Committee",
                    "show": True,
                    "paramName": "committee",
                    "type": "endpoint",
                    "optionsEndpoint": f"{api_prefix}/uscongress/committee_choices",
                    "optionsParams": {
                        "chamber": "$chamber",
                        "congress": "$congress",
                        "is_workspace": True,
                    },
                    "style": {"popupWidth": 750},
                },
                {
                    "label": "Subcommittee",
                    "show": True,
                    "paramName": "subcommittee",
                    "type": "endpoint",
                    "optionsEndpoint": f"{api_prefix}/uscongress/committee_choices",
                    "optionsParams": {
                        "chamber": "$chamber",
                        "committee": "$committee",
                        "subcommittees": True,
                        "is_workspace": True,
                    },
                    "style": {"popupWidth": 750},
                },
                {
                    "label": "Document Type",
                    "description": "Type of committee document to browse.",
                    "show": True,
                    "paramName": "doc_type",
                    "value": "meeting",
                    "options": [
                        {"label": "Reports", "value": "report"},
                        {"label": "Meetings & Hearings", "value": "meeting"},
                        {"label": "Publications & Prints", "value": "publication"},
                        {"label": "Legislation", "value": "legislation"},
                    ],
                },
            ],
            "refetchInterval": False,
        }
    },
)
async def committee_document_urls(
    chamber: str,
    committee: str,
    subcommittee: str | None = None,
    doc_type: str = "all",
    congress: int | None = None,
    provider: str = "congress_gov",
    is_workspace: bool = False,
) -> list:
    """Get document choices for a Congressional Committee."""
    from datetime import datetime

    from openbb_government_us.congress.utils.committees import get_committee_doc_choices
    from openbb_government_us.congress.utils.helpers import year_to_congress

    if not committee:
        if is_workspace is True:
            return [
                {
                    "label": "Select a committee to view available documents.",
                    "value": None,
                }
            ]
        raise HTTPException(
            status_code=500,
            detail="Committee system code is required.",
        )

    system_code = (subcommittee or committee).lower()
    if congress is None:
        congress = year_to_congress(datetime.now().year)

    return await get_committee_doc_choices(
        system_code=system_code,
        congress=congress,
        doc_type=doc_type,
        is_workspace=is_workspace,
    )


async def get_congress_gov_apps_json() -> list[dict[str, Any]]:
    """Get the Congress.gov apps.json file."""
    import json
    from pathlib import Path

    apps_file = Path(__file__).parent / "assets" / "apps.json"

    try:
        with apps_file.open("r", encoding="utf-8") as f:
            apps_json = json.load(f)
            return apps_json
    except Exception:
        return []


router._api_router.add_api_route(
    path="/apps.json",
    endpoint=get_congress_gov_apps_json,
    methods=["GET"],
    include_in_schema=False,
)


def _widget_page(template: str, payload: dict) -> HTMLResponse:
    """Serve a packaged widget page with its bootstrap payload injected.

    Parameters
    ----------
    template : str
        File name of the page in the assets directory.
    payload : dict
        JSON-serializable data the page renders itself from.
    """
    import json
    from pathlib import Path

    blob = (
        json.dumps(payload)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    page = (Path(__file__).parent / "assets" / template).read_text(encoding="utf-8")

    return HTMLResponse(
        content=page.replace("__WIDGET_DATA__", blob),
        headers={"Cache-Control": "no-cache"},
    )


async def committee_members_data(
    chamber: str = "senate",
    committee: str = "ssaf00",
    subcommittee: str | None = None,
) -> dict:
    """Get a committee's current membership with each member's profile.

    Parameters
    ----------
    chamber : str
        Chamber the committee belongs to.
    committee : str
        Committee system code.
    subcommittee : str | None
        Subcommittee system code. Takes precedence over the committee.
    """
    import asyncio

    from openbb_government_us.congress.utils.bulk import (
        load_legislators,
        member_photo_url,
    )
    from openbb_government_us.congress.utils.committees import get_committee_overview
    from openbb_government_us.congress.utils.member_cards import (
        committee_members_payload,
    )

    system_code = (subcommittee or committee).lower()
    overview = await get_committee_overview(system_code, chamber)
    members = overview.get("members", [])
    legislators = await load_legislators()

    bioguides = [m.get("bioguide", "") for m in members]
    photos = await asyncio.gather(*[member_photo_url(b) for b in bioguides])
    profiles = {
        b: {**legislators.get(b, {}), "photo_url": photo}
        for b, photo in zip(bioguides, photos)
    }
    detail = {**overview.get("detail", {}), "chamber": chamber}

    return committee_members_payload(members, profiles, detail)


router._api_router.add_api_route(
    path="/committee_members_data",
    endpoint=committee_members_data,
    methods=["GET"],
    openapi_extra={"widget_config": {"exclude": True}},
)


async def committee_members(
    chamber: str = "senate",
    committee: str = "ssaf00",
    subcommittee: str | None = None,
    theme: str | None = "dark",
):
    """Render a committee's members as cards (OpenBB Workspace iframe widget)."""
    payload = await committee_members_data(chamber, committee, subcommittee)

    return _widget_page(
        "committee_members.html",
        {
            "theme": "light" if (theme or "").lower() == "light" else "dark",
            "chamber": chamber,
            "committee": committee,
            "subcommittee": subcommittee,
            "committee_detail": payload["committee"],
            "members": payload["members"],
        },
    )


router._api_router.add_api_route(
    path="/committee_members",
    endpoint=committee_members,
    methods=["GET"],
    response_class=HTMLResponse,
    openapi_extra={
        "widget_config": {
            "name": "Congressional Committee Members",
            "description": "Member cards for a U.S. Congressional Committee.",
            "category": "Government",
            "subCategory": "Congress",
            "type": "iframe",
            "widgetId": "uscongress_committee_members_congress_gov_obb",
            "params": [
                {
                    "label": "Chamber",
                    "show": True,
                    "paramName": "chamber",
                    "value": "house",
                    "options": [
                        {"label": "Senate", "value": "senate"},
                        {"label": "House", "value": "house"},
                        {"label": "Joint", "value": "joint"},
                    ],
                },
                {
                    "label": "Committee",
                    "show": True,
                    "paramName": "committee",
                    "type": "endpoint",
                    "optionsEndpoint": f"{api_prefix}/uscongress/committee_choices",
                    "optionsParams": {
                        "chamber": "$chamber",
                        "is_workspace": True,
                    },
                    "value": "hsju00",
                    "style": {"popupWidth": 700},
                },
                {
                    "label": "Subcommittee",
                    "show": True,
                    "paramName": "subcommittee",
                    "type": "endpoint",
                    "optionsEndpoint": f"{api_prefix}/uscongress/committee_choices",
                    "optionsParams": {
                        "chamber": "$chamber",
                        "committee": "$committee",
                        "subcommittees": True,
                        "is_workspace": True,
                    },
                    "style": {"popupWidth": 750},
                },
                {"paramName": "theme", "show": False},
            ],
            "refetchInterval": False,
        }
    },
)


@router.command(
    model="CongressMembers",
    examples=[
        APIEx(parameters={"provider": "congress_gov"}),
        APIEx(
            parameters={
                "chamber": "house",
                "state": "OH",
                "provider": "congress_gov",
            }
        ),
    ],
)
async def members(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get and filter the current members of the U.S. Congress."""
    return await OBBject.from_query(OpenBBQuery(**locals()))


async def member_info_data(bioguide_id: str = "A000055") -> dict:
    """Get a member's bio, contact, links, committees, terms, and voting record.

    Parameters
    ----------
    bioguide_id : str
        Bioguide id of a current member of Congress.
    """
    from openbb_government_us.congress.utils.bulk import (
        load_member_record,
        load_social_media,
        member_committees,
        member_passage_record,
        member_photo_url,
    )
    from openbb_government_us.congress.utils.member_cards import member_bio_payload

    record = await load_member_record(bioguide_id)
    committees = await member_committees(bioguide_id)
    social = (await load_social_media()).get(bioguide_id, {})
    voting = await member_passage_record(bioguide_id)
    photo_url = await member_photo_url(bioguide_id)

    return member_bio_payload(record, committees, social, voting, photo_url)


router._api_router.add_api_route(
    path="/member_info_data",
    endpoint=member_info_data,
    methods=["GET"],
    openapi_extra={"widget_config": {"exclude": True}},
)


async def member_info(
    bioguide_id: str = "A000055",
    theme: str | None = "dark",
):
    """Render a member's bio, history, and committees (OpenBB Workspace iframe widget)."""
    payload = await member_info_data(bioguide_id)
    payload["theme"] = "light" if (theme or "").lower() == "light" else "dark"

    return _widget_page("member_bio.html", payload)


router._api_router.add_api_route(
    path="/member_info",
    endpoint=member_info,
    methods=["GET"],
    response_class=HTMLResponse,
    openapi_extra={
        "widget_config": {
            "name": "Congressional Member Info",
            "description": "Bio, history, and committee assignments for a member.",
            "category": "Government",
            "subCategory": "Congress",
            "type": "iframe",
            "widgetId": "uscongress_member_info_congress_gov_obb",
            "params": [
                {
                    "label": "Member",
                    "show": True,
                    "paramName": "bioguide_id",
                    "type": "endpoint",
                    "optionsEndpoint": f"{api_prefix}/uscongress/member_choices",
                    "optionsParams": {"is_workspace": True},
                    "value": "A000055",
                    "style": {"popupWidth": 400},
                },
                {"paramName": "theme", "show": False},
            ],
            "refetchInterval": False,
        }
    },
)


@router.command(
    model="CongressMemberVotes",
    examples=[
        APIEx(parameters={"provider": "congress_gov", "bioguide_id": "A000055"}),
    ],
)
async def member_votes(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get a member's roll-call votes on legislation, House and Senate."""
    return await OBBject.from_query(OpenBBQuery(**locals()))


@router.command(
    model="CongressMemberLegislation",
    examples=[
        APIEx(parameters={"provider": "congress_gov", "bioguide_id": "A000055"}),
    ],
)
async def member_legislation(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get the bills a member sponsored or cosponsored in a Congress."""
    return await OBBject.from_query(OpenBBQuery(**locals()))


@router.command(
    methods=["GET"],
    openapi_extra={"widget_config": {"exclude": True}},
)
async def member_choices(
    chamber: str | None = None,
    provider: str = "congress_gov",
    is_workspace: bool = False,
) -> list:
    """Get bioguide picker choices for the member widgets."""
    from openbb_government_us.congress.utils.bulk import (
        filter_members,
        load_members,
        to_member_list_item,
    )

    members_data = await load_members()
    items = filter_members(
        [to_member_list_item(m) for m in members_data], chamber=chamber
    )

    choices: list = []
    for item in items:
        district = f"-{item['district']}" if item.get("district") else ""
        party = (item.get("party") or "")[:1]
        choices.append(
            {
                "label": f"{item['name']} ({party}-{item['state']}{district})",
                "value": item["bioguide_id"],
            }
        )

    return choices or [{"label": "No members found.", "value": None}]


async def how_to_use(note: str = "bills") -> str:
    """Return a tab's 'How To Use' note as Markdown (OpenBB Workspace markdown widget)."""
    from openbb_government_us.congress.utils.notes import HOW_TO_USE

    return HOW_TO_USE.get(note, "")


router._api_router.add_api_route(
    path="/how_to_use",
    endpoint=how_to_use,
    methods=["GET"],
    openapi_extra={
        "widget_config": {
            "name": "How To Use",
            "description": "Usage notes for the U.S. Congress app tabs.",
            "category": "Government",
            "subCategory": "Congress",
            "type": "markdown",
            "widgetId": "uscongress_how_to_use_congress_gov_obb",
            "data": {"dataKey": ""},
            "params": [
                {
                    "paramName": "note",
                    "value": "bills",
                    "show": False,
                },
            ],
            "refetchInterval": False,
        }
    },
)


_BACKGROUND_TASKS: set = set()
_WARM_GUARD: set = set()
_REFRESH_INTERVAL_SECONDS: int = 3600
_PASSAGE_REFRESH_INTERVAL_SECONDS: int = 43200


async def _preload_bills() -> None:
    """Download and cache the current Congress bills bulk data for every bill type."""
    import asyncio
    from datetime import datetime

    from openbb_government_us.congress.utils.bulk import ensure_billstatus
    from openbb_government_us.congress.utils.constants import BillTypes
    from openbb_government_us.congress.utils.helpers import year_to_congress

    congress = year_to_congress(datetime.now().year)
    logger.info("congress_gov: warming current Congress %d bills...", congress)
    results = await asyncio.gather(
        *[ensure_billstatus(congress, bt) for bt in BillTypes],
        return_exceptions=True,
    )
    failed = [
        bt
        for bt, result in zip(BillTypes, results)
        if isinstance(result, BaseException)
    ]
    for bill_type, result in zip(BillTypes, results):
        if isinstance(result, BaseException):
            logger.error(
                "congress_gov: warming %s-%s failed: %s",
                congress,
                bill_type,
                result,
                exc_info=result,
            )
    if failed:
        logger.warning(
            "congress_gov: current Congress %d bills ready, except %s"
            " (these re-download on first request)",
            congress,
            ", ".join(failed),
        )
    else:
        logger.info("congress_gov: current Congress %d bills ready", congress)


def _served_range(members: list, current: int) -> list[int]:
    """Return Congresses from the current one back to the earliest any member served."""
    from openbb_government_us.congress.utils.helpers import year_to_congress

    earliest = current
    for member in members:
        for term in member.get("terms") or []:
            start = (term.get("start") or "")[:4]
            if not start.isdigit():
                continue
            try:
                earliest = min(earliest, year_to_congress(int(start)))
            except ValueError:
                continue
    return list(range(current, earliest - 1, -1))


async def _preload_members() -> None:
    """Warm reference data, then precompute the member vote and legislation indexes."""
    import asyncio
    from datetime import datetime

    from openbb_government_us.congress.utils.bulk import (
        _BILLSTATUS_MIN_CONGRESS,
        build_passage_index,
        ingest_billstatus_range,
        load_committee_membership,
        load_committee_structure,
        load_legislators,
        load_members,
        load_social_media,
    )
    from openbb_government_us.congress.utils.helpers import year_to_congress

    logger.info("congress_gov: warming member reference data...")
    results = await asyncio.gather(
        load_members(),
        load_social_media(),
        load_committee_membership(),
        load_committee_structure(),
        load_legislators(),
        return_exceptions=True,
    )

    members = results[0] if isinstance(results[0], list) else []
    current = year_to_congress(datetime.now().year)
    congresses = _served_range(members, current)
    legislatable = [c for c in congresses if c >= _BILLSTATUS_MIN_CONGRESS]

    try:
        await build_passage_index(congresses, keep_votes=congresses[:2])
    except Exception as exc:  # noqa: BLE001
        logger.error("congress_gov: passage warmup failed: %s", exc, exc_info=exc)

    try:
        await ingest_billstatus_range(legislatable)
    except Exception as exc:  # noqa: BLE001
        logger.error("congress_gov: legislation warmup failed: %s", exc, exc_info=exc)


def _schedule_background(coro_factory) -> None:
    """Schedule a warmup coroutine as a fire-and-forget background task."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    task = loop.create_task(coro_factory())
    _BACKGROUND_TASKS.add(task)

    def _done(finished) -> None:
        _BACKGROUND_TASKS.discard(finished)
        exc = None if finished.cancelled() else finished.exception()
        if exc is not None:
            logger.error(
                "congress_gov: background warmup failed: %s", exc, exc_info=exc
            )

    task.add_done_callback(_done)


async def _refresh_loop() -> None:
    """Periodically re-ingest current-Congress archives that GovInfo has updated."""
    import asyncio

    from openbb_government_us.congress.utils.bulk import refresh_billstatus

    logger.info(
        "congress_gov: refresh loop active (every %ds, all ingested Congresses)",
        _REFRESH_INTERVAL_SECONDS,
    )
    while True:
        try:
            await asyncio.sleep(_REFRESH_INTERVAL_SECONDS)
            await refresh_billstatus()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("congress_gov: refresh tick failed: %s", exc, exc_info=exc)


async def _passage_refresh_loop() -> None:
    """Periodically re-ingest the current Congress's Voteview passage votes."""
    import asyncio

    from openbb_government_us.congress.utils.bulk import refresh_passage

    logger.info(
        "congress_gov: passage refresh loop active (every %ds, current Congress)",
        _PASSAGE_REFRESH_INTERVAL_SECONDS,
    )
    while True:
        try:
            await asyncio.sleep(_PASSAGE_REFRESH_INTERVAL_SECONDS)
            await refresh_passage()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "congress_gov: passage refresh tick failed: %s", exc, exc_info=exc
            )


async def _warmup() -> None:
    """Warm the current Congress first (Bills widgets), then the member data."""
    from openbb_government_us.congress.utils.bulk import seed_billstatus_markers

    logger.info("congress_gov: startup cache warmup begun")
    await _preload_bills()
    await _preload_members()
    await seed_billstatus_markers()
    logger.info("congress_gov: startup cache warmup complete")
    _schedule_background(_refresh_loop)
    _schedule_background(_passage_refresh_loop)


def _warm_cache() -> None:
    """Kick off the ordered cache warmup in the background at API startup, once."""
    if _WARM_GUARD:
        return
    _WARM_GUARD.add(True)
    _schedule_background(_warmup)


def _stop_background() -> None:
    """Cancel any in-flight warmup/refresh tasks at API shutdown."""
    for task in list(_BACKGROUND_TASKS):
        task.cancel()


router._api_router.add_event_handler("startup", _warm_cache)
router._api_router.add_event_handler("shutdown", _stop_background)
