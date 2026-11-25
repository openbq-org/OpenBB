"""OpenBB Federal Reserve Router Module."""

from typing import Annotated, Any

from fastapi import Body
from openbb_core.app.model.abstract.error import OpenBBError
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

from openbb_federal_reserve import ECONOMY_INSTALLED, FIXEDINCOME_INSTALLED

router = Router(prefix="", description="Federal Reserve provider router.")

_FR_META = {"category": "Federal Reserve", "subCategory": "FRB"}


_ECONOMY_WIDGET_ID_FALLBACK_MAP = {
    "economy_money_measures_federal_reserve_obb": "federal_reserve_money_measures_federal_reserve_obb",
    "economy_central_bank_holdings_federal_reserve_obb": "ny_central_bank_holdings_federal_reserve_obb",
    "economy_primary_dealer_positioning_federal_reserve_obb": "ny_primary_dealer_positioning_federal_reserve_obb",
    "economy_primary_dealer_fails_federal_reserve_obb": "ny_primary_dealer_fails_federal_reserve_obb",
    "economy_fomc_documents_federal_reserve_obb": "federal_reserve_fomc_documents_federal_reserve_obb",
    "economy_survey_inflation_expectations_federal_reserve_obb": "federal_reserve_inflation_expectations_federal_reserve_obb",
}

_FIXEDINCOME_WIDGET_ID_FALLBACK_MAP = {
    "fixedincome_rate_sofr_federal_reserve_obb": "ny_sofr_federal_reserve_obb",
    "fixedincome_rate_effr_federal_reserve_obb": "ny_effr_federal_reserve_obb",
    "fixedincome_rate_overnight_bank_funding_federal_reserve_obb": "ny_overnight_bank_funding_federal_reserve_obb",
    "fixedincome_government_treasury_rates_federal_reserve_obb": "federal_reserve_treasury_rates_federal_reserve_obb",
    "fixedincome_government_yield_curve_federal_reserve_obb": "federal_reserve_yield_curve_federal_reserve_obb",
}


def _rewrite_widget_ids(apps_json: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Swap host-prefixed widget IDs for their federal_reserve fallbacks per absent host."""
    mapping: dict[str, str] = {}
    if not ECONOMY_INSTALLED:
        mapping.update(_ECONOMY_WIDGET_ID_FALLBACK_MAP)
    if not FIXEDINCOME_INSTALLED:
        mapping.update(_FIXEDINCOME_WIDGET_ID_FALLBACK_MAP)
    if not mapping:
        return apps_json
    for app in apps_json:
        tabs = app.get("tabs", {}) or {}
        for tab in tabs.values():
            for widget in tab.get("layout", []) or []:
                widget_id = widget.get("i")
                if widget_id in mapping:
                    widget["i"] = mapping[widget_id]
    return apps_json


async def get_apps_json() -> list[dict[str, Any]]:
    """Get the apps.json for the Federal Reserve provider."""
    import json
    from pathlib import Path

    apps_json_path = Path(__file__).parent / "assets" / "apps.json"
    try:
        with apps_json_path.open(encoding="utf-8") as file:
            apps_data = json.load(file)
    except Exception:
        return []
    return _rewrite_widget_ids(apps_data)


async def fomc_documents_download(params: Annotated[dict, Body()]) -> list:
    """Download FOMC documents from the Federal Reserve's website.

    Parameters
    ----------
    params : dict
        A dictionary with a key "url" containing a list of URLs to download.

    Returns
    -------
    list
        A list of dictionaries, each containing keys `filename`, `content`, and `data_format`.
    """
    import base64
    from io import BytesIO
    from urllib.parse import urlparse

    from openbb_core.provider.utils.helpers import make_request

    urls = params.get("url") or []
    results: list = []

    for url in urls:
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname or ""

        if parsed_url.scheme != "https" or hostname not in {
            "www.federalreserve.gov",
            "federalreserve.gov",
        }:
            raise OpenBBError(
                "Invalid URL provided for download. Must be from federalreserve.gov -> "
                + url
            )

        is_pdf = url.lower().endswith(".pdf")

        if (
            not is_pdf
            and not url.lower().endswith(".htm")
            and not url.lower().endswith(".html")
        ):
            raise OpenBBError(
                "Unsupported document format. File must be PDF or HTM type -> " + url
            )

        try:
            response = make_request(url)
            response.raise_for_status()
            pdf = (
                base64.b64encode(BytesIO(response.content).getvalue()).decode("utf-8")
                if isinstance(response.content, bytes)
                else response.content
            )
            results.append(
                {
                    "content": pdf,
                    "data_format": {
                        "data_type": "pdf" if is_pdf else "markdown",
                        "filename": url.split("/")[-1],
                    },
                }
            )
        except Exception as exc:
            results.append(
                {
                    "error_type": "download_error",
                    "content": f"{exc.__class__.__name__}: {exc.args[0]}",
                    "filename": url.split("/")[-1],
                }
            )
            continue

    return results


async def fomc_documents_choices(
    year: int | None = None, document_type: str | None = None
) -> list:
    """Get the available choices for FOMC document types.

    Returns
    -------
    list
        A list of available document choices with URLs for download.
    """
    from openbb_federal_reserve.utils.fomc_documents import get_fomc_documents_by_year

    docs = get_fomc_documents_by_year(year, document_type, True)
    choices_list: list = []

    for doc in docs:
        title = (
            doc.get("doc_type", "").replace("_", " ").title()
            + " - "
            + doc.get("date", "")
        )
        value = doc.get("url", "")
        if title and value:
            choices_list.append(
                {
                    "label": title,
                    "value": value,
                }
            )

    return choices_list


_PUB_FETCHERS: dict[str, tuple[str, str]] = {
    "atlanta": ("atlanta_publications", "FederalReserveAtlantaPublicationsFetcher"),
    "boston": ("boston_publications", "FederalReserveBostonPublicationsFetcher"),
    "chicago": ("chicago_publications", "FederalReserveChicagoPublicationsFetcher"),
    "cleveland": (
        "cleveland_publications",
        "FederalReserveClevelandPublicationsFetcher",
    ),
    "dallas": ("dallas_publications", "FederalReserveDallasPublicationsFetcher"),
    "kc": (
        "kansas_city_publications",
        "FederalReserveKansasCityPublicationsFetcher",
    ),
    "minneapolis": (
        "minneapolis_publications",
        "FederalReserveMinneapolisPublicationsFetcher",
    ),
    "philadelphia": (
        "philadelphia_publications",
        "FederalReservePhiladelphiaPublicationsFetcher",
    ),
    "richmond": ("richmond_publications", "FederalReserveRichmondPublicationsFetcher"),
    "sf": (
        "san_francisco_publications",
        "FederalReserveSanFranciscoPublicationsFetcher",
    ),
    "ny": ("new_york_publications", "FederalReserveNewYorkPublicationsFetcher"),
    "stl": ("st_louis_publications", "FederalReserveStLouisPublicationsFetcher"),
}

_REPORT_FETCHERS: dict[str, tuple[str, str]] = {
    "empire_state": (
        "new_york_empire_reports",
        "FederalReserveNewYorkEmpireReportsFetcher",
    ),
    "market_expectations": (
        "new_york_market_expectations_reports",
        "FederalReserveNewYorkMarketExpectationsReportsFetcher",
    ),
}


def _download_pdf(url: str) -> bytes:
    """Fetch a PDF by URL as bytes.

    A browser-impersonating ``curl_cffi`` session is tried first because some
    Reserve Bank hosts (e.g. Kansas City behind Akamai) reject or time out plain
    HTTP clients; the standard client is the fallback.
    """
    import threading

    from openbb_federal_reserve.utils.curl_session import get_session

    try:
        session = get_session(f"publications_download:{threading.get_ident()}")
        response = session.get(url, timeout=60)
        response.raise_for_status()
        return response.content
    except Exception:  # noqa: BLE001
        from openbb_core.provider.utils.helpers import make_request

        response = make_request(url, timeout=30)
        response.raise_for_status()
        return response.content


async def regional_publications_download(params: Annotated[dict, Body()]) -> list:
    """Download regional publication PDFs as base64-encoded content.

    Parameters
    ----------
    params : dict
        A dictionary with a ``url`` key holding the list of PDF URLs to fetch.

    Returns
    -------
    list
        One dict per URL, each with ``content`` (base64 PDF) and ``data_format``.
    """
    import base64

    from openbb_federal_reserve.utils import fedinprint

    results: list = []
    for url in params.get("url") or []:
        try:
            target = url
            if "fedinprint.org/item/" in url:
                target = fedinprint.resolve_file(url, fedinprint.fetch_text)
                if not target:
                    raise ValueError("No document is published for this item.")
            content = _download_pdf(target)
            results.append(
                {
                    "content": base64.b64encode(content).decode("utf-8"),
                    "data_format": {
                        "data_type": "pdf",
                        "filename": target.split("/")[-1],
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


async def regional_publications_choices(
    district: str,
    series: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list:
    """List a Reserve Bank's publication PDFs as file-selector choices.

    The catalog filters — series, date range, and paging — are applied so the
    file list tracks the widget's parameters.

    Returns
    -------
    list
        A list of ``{label, value}`` choices, the PDF URL as each value.
    """
    from importlib import import_module

    module_name, fetcher_name = _PUB_FETCHERS[district]
    fetcher = getattr(
        import_module(f"openbb_federal_reserve.models.regional.{module_name}"),
        fetcher_name,
    )
    params = {
        "series": series,
        "start_date": start_date,
        "end_date": end_date,
        "limit": limit,
        "offset": offset,
    }
    query = fetcher.transform_query(
        {k: v for k, v in params.items() if v not in (None, "")}
    )
    catalog = fetcher.transform_data(query, fetcher.extract_data(query, None))
    choices: list = []
    for record in catalog:
        item = record.model_dump()
        label = item.get("title") or ""
        if item.get("date"):
            label = f"{label} ({str(item['date'])[:7]})".strip()
        choices.append(
            {"label": label or item["url"].split("/")[-1], "value": item["url"]}
        )
    return choices


async def regional_reports_choices(
    report: str,
    start_date: str | None = None,
    end_date: str | None = None,
    kind: str | None = None,
) -> list:
    """List a report catalog's PDFs as file-selector choices.

    Parameters
    ----------
    report : str
        The report catalog key, e.g. ``"empire_state"``.
    start_date, end_date : str | None
        Optional inclusive date bounds applied to the catalog.
    kind : str | None
        An optional catalog-specific document-kind filter.

    Returns
    -------
    list
        A list of ``{label, value}`` choices, the PDF URL as each value.
    """
    from importlib import import_module

    module_name, fetcher_name = _REPORT_FETCHERS[report]
    fetcher = getattr(
        import_module(f"openbb_federal_reserve.models.regional.{module_name}"),
        fetcher_name,
    )
    params = {"start_date": start_date, "end_date": end_date, "kind": kind}
    query = fetcher.transform_query(
        {k: v for k, v in params.items() if v not in (None, "")}
    )
    catalog = fetcher.transform_data(query, fetcher.extract_data(query, None))
    choices: list = []
    for record in catalog:
        item = record.model_dump()
        label = item.get("title")
        if not label and item.get("date"):
            label = item["date"].strftime("%B %Y")
        choices.append(
            {"label": label or item["url"].split("/")[-1], "value": item["url"]}
        )
    return choices


async def market_probability_meetings() -> list:
    """List the latest date's reference FOMC meetings as dropdown choices.

    Returns
    -------
    list
        A list of ``{label, value}`` choices, each meeting's ISO date as value.
    """
    from openbb_federal_reserve.models.regional.atlanta_market_probability import (
        FederalReserveAtlantaMarketProbabilityFetcher,
        _load_meetings,
    )

    query = FederalReserveAtlantaMarketProbabilityFetcher.transform_query({})
    rows = FederalReserveAtlantaMarketProbabilityFetcher.extract_data(query, None)
    _, meetings = _load_meetings(rows[0]["_raw"])
    return [
        {"label": meeting.isoformat(), "value": meeting.isoformat()}
        for meeting in meetings
    ]


router._api_router.add_api_route(
    path="/regional_publications_download",
    endpoint=regional_publications_download,
    methods=["POST"],
    include_in_schema=False,
)
router._api_router.add_api_route(
    path="/regional_publications_choices",
    endpoint=regional_publications_choices,
    methods=["GET"],
    include_in_schema=False,
)
router._api_router.add_api_route(
    path="/regional_reports_choices",
    endpoint=regional_reports_choices,
    methods=["GET"],
    include_in_schema=False,
)
router._api_router.add_api_route(
    path="/market_probability_meetings",
    endpoint=market_probability_meetings,
    methods=["GET"],
    include_in_schema=False,
)
router._api_router.add_api_route(
    path="/apps.json",
    endpoint=get_apps_json,
    methods=["GET"],
    include_in_schema=False,
)
router._api_router.add_api_route(
    path="/fomc_documents_download",
    endpoint=fomc_documents_download,
    methods=["POST"],
    include_in_schema=False,
)
router._api_router.add_api_route(
    path="/fomc_documents_choices",
    endpoint=fomc_documents_choices,
    methods=["GET"],
    include_in_schema=False,
)


@router.command(
    methods=["GET"],
    examples=[
        APIEx(
            description="List the Federal Reserve statistical releases available"
            " via the Data Download Program.",
            parameters={},
        )
    ],
    widget_config={
        **_FR_META,
        "name": "Federal Reserve Statistical Releases",
        "description": "The statistical releases published through the Federal"
        " Reserve Data Download Program. Click a release to load its data tables"
        " and series.",
        "gridData": {"w": 20, "h": 18},
        "data": {
            "table": {
                "showAll": False,
                "columnsDefs": [
                    {
                        "field": "dataset",
                        "headerName": "Release",
                        "cellDataType": "text",
                        "formatterFn": "none",
                        "pinned": "left",
                        "renderFn": "cellOnClick",
                        "renderFnParams": {
                            "actionType": "groupBy",
                            "groupBy": {"paramName": "dataset"},
                        },
                    },
                    {"field": "name", "headerName": "Name", "cellDataType": "text"},
                ],
            }
        },
    },
)
async def list_releases() -> list[dict]:
    """List Federal Reserve Data Download Program (DDP) statistical releases."""
    from openbb_federal_reserve.utils.ddp import list_releases as _list_releases

    return _list_releases()


@router.command(
    methods=["GET"],
    examples=[
        APIEx(
            description="List the data tables within a release.",
            parameters={"dataset": "H.15"},
        ),
    ],
    widget_config={
        **_FR_META,
        "name": "Release Data Tables",
        "description": "The data tables available within a Federal Reserve"
        " statistical release. Click a table to load its time series.",
        "gridData": {"w": 20, "h": 18},
        "data": {
            "table": {
                "showAll": False,
                "columnsDefs": [
                    {
                        "field": "table",
                        "headerName": "Table",
                        "cellDataType": "text",
                        "pinned": "left",
                        "renderFn": "cellOnClick",
                        "renderFnParams": {
                            "actionType": "groupBy",
                            "groupBy": {"paramName": "table"},
                        },
                    },
                    {
                        "field": "dataset",
                        "headerName": "Release",
                        "cellDataType": "text",
                        "formatterFn": "none",
                    },
                    {
                        "field": "release_name",
                        "headerName": "Release Name",
                        "cellDataType": "text",
                    },
                ],
            }
        },
    },
)
async def list_datasets(dataset: str = "H.15") -> list[dict]:
    """List the data tables available within a Federal Reserve DDP release."""
    from openbb_federal_reserve.utils.ddp import list_datasets as _list_datasets

    return _list_datasets(dataset)


@router.command(
    methods=["GET"],
    examples=[
        APIEx(
            description="The upcoming and recent Federal Reserve release schedule.",
            parameters={},
        ),
        APIEx(
            description="The release schedule from a start date.",
            parameters={"start_date": "2026-01-01"},
        ),
    ],
    widget_config={
        **_FR_META,
        "name": "Federal Reserve Release Calendar",
        "description": "The publication schedule of Federal Reserve statistical"
        " releases (federalreserve.gov/data/releaseschedule.htm). Click a release"
        " to load its data tables and series.",
        "gridData": {"w": 40, "h": 16},
        "data": {
            "table": {
                "showAll": False,
                "columnsDefs": [
                    {
                        "field": "date",
                        "headerName": "Date",
                        "cellDataType": "date",
                        "pinned": "left",
                        "sort": "asc",
                    },
                    {"field": "time", "headerName": "Time", "cellDataType": "text"},
                    {
                        "field": "release",
                        "headerName": "Release",
                        "cellDataType": "text",
                        "formatterFn": "none",
                        "renderFn": "cellOnClick",
                        "renderFnParams": {
                            "actionType": "groupBy",
                            "groupBy": {"paramName": "dataset"},
                        },
                    },
                    {"field": "title", "headerName": "Title", "cellDataType": "text"},
                    {
                        "field": "event_type",
                        "headerName": "Type",
                        "cellDataType": "text",
                    },
                ],
            }
        },
    },
)
async def release_calendar(
    start_date: str | None = None, end_date: str | None = None
) -> list[dict]:
    """Get the Federal Reserve statistical release publication schedule."""
    from datetime import datetime

    from openbb_federal_reserve.utils.ddp import fetch_release_schedule

    cutoff = start_date or datetime.now().strftime("%Y-%m-%d")
    rows = [row for row in fetch_release_schedule() if row["date"] >= cutoff]
    if end_date:
        rows = [row for row in rows if row["date"] <= end_date]
    return rows


@router.command(
    model="FederalReserveDataDownload",
    examples=[
        APIEx(
            description="Fetch a release's first table.",
            parameters={"dataset": "H.15", "provider": "federal_reserve"},
        ),
        APIEx(
            description="Fetch a specific table within a release.",
            parameters={
                "dataset": "H.15",
                "table": "Monthly Averages",
                "provider": "federal_reserve",
            },
        ),
    ],
    widget_config={
        **_FR_META,
        "name": "Federal Reserve Data Download (DDP)",
        "description": "Any published Federal Reserve dataset retrieved from the"
        " Data Download Program by release and table.",
        "gridData": {"w": 40, "h": 20},
        "data": {
            "table": {
                "showAll": True,
                "columnsDefs": [
                    {
                        "field": "series_id",
                        "headerName": "Series ID",
                        "cellDataType": "text",
                        "formatterFn": "none",
                        "pinned": "left",
                        "renderFn": "cellOnClick",
                        "renderFnParams": {
                            "actionType": "groupBy",
                            "groupBy": {"paramName": "series"},
                        },
                    },
                ],
            }
        },
    },
)
async def fed_data(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Fetch any published Federal Reserve dataset from the Data Download Program."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="FederalReserveMoneyMarketFunds",
    examples=[
        APIEx(
            description="Get total money market fund investment holdings by category.",
            parameters={"table": "total", "provider": "federal_reserve"},
        ),
        APIEx(
            description="Get prime fund holdings detail for a single country.",
            parameters={
                "table": "detail",
                "country": "Japan",
                "provider": "federal_reserve",
            },
        ),
    ],
    widget_config={
        **_FR_META,
        "name": "Money Market Fund Holdings (EFA)",
        "description": "Money market fund investment holdings, in millions of"
        " dollars, from the Enhanced Financial Accounts.",
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
                ],
            }
        },
    },
)
async def money_market_funds(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get Money Market Funds Investment Holdings (Enhanced Financial Accounts)."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="FederalReserveInternationalPortfolioInvestment",
    examples=[
        APIEx(
            description="Get foreign residents' holdings of total U.S. long-term"
            " securities by country.",
            parameters={"table": "table1", "provider": "federal_reserve"},
        ),
        APIEx(
            description="Get U.S. residents' holdings of foreign corporate stocks"
            " for a single country.",
            parameters={
                "table": "table2b",
                "country": "Japan",
                "provider": "federal_reserve",
            },
        ),
    ],
    widget_config={
        **_FR_META,
        "name": "International Portfolio Investment (EFA)",
        "description": "Cross-border holdings of long-term securities, from the"
        " Enhanced Financial Accounts project.",
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
async def international_portfolio_investment(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get International Portfolio Investment holdings (Enhanced Financial Accounts)."""
    return await OBBject.from_query(Query(**locals()))


if not ECONOMY_INSTALLED:

    @router.command(
        model="FederalReserveFomcDocuments",
        examples=[
            APIEx(parameters={"provider": "federal_reserve"}),
            APIEx(
                description="Filter all documents by year.",
                parameters={"provider": "federal_reserve", "year": 2022},
            ),
            APIEx(
                description="Filter all documents by year and document type.",
                parameters={
                    "provider": "federal_reserve",
                    "year": 2022,
                    "document_type": "minutes",
                },
            ),
        ],
    )
    async def fomc_documents(
        cc: CommandContext,
        provider_choices: ProviderChoices,
        standard_params: StandardParams,
        extra_params: ExtraParams,
    ) -> OBBject:
        """Get lists of FOMC documents by year and document type."""
        return await OBBject.from_query(Query(**locals()))

    @router.command(
        model="FederalReserveInflationExpectations",
        examples=[APIEx(parameters={"provider": "federal_reserve"})],
        widget_config={
            **_FR_META,
            "name": "Survey of Professional Forecasters Inflation Expectations",
            "description": "One-year-ahead and ten-year-ahead inflation forecasts"
            " from the Philadelphia Fed's Survey of Professional Forecasters.",
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
                            "field": "infpgdp1yr",
                            "headerName": "GDP Deflator Inflation (1-Year)",
                            "cellDataType": "number",
                            "formatterFn": "percent",
                        },
                        {
                            "field": "infcpi1yr",
                            "headerName": "CPI Inflation (1-Year)",
                            "cellDataType": "number",
                            "formatterFn": "percent",
                        },
                        {
                            "field": "infcpi10yr",
                            "headerName": "CPI Inflation (10-Year)",
                            "cellDataType": "number",
                            "formatterFn": "percent",
                        },
                    ],
                }
            },
        },
    )
    async def inflation_expectations(
        cc: CommandContext,
        provider_choices: ProviderChoices,
        standard_params: StandardParams,
        extra_params: ExtraParams,
    ) -> OBBject:
        """Survey of forward inflation expectations from the Survey of Professional Forecasters."""
        return await OBBject.from_query(Query(**locals()))

    @router.command(
        model="FederalReserveMoneyMeasures",
        examples=[
            APIEx(parameters={"provider": "federal_reserve"}),
            APIEx(parameters={"adjusted": False, "provider": "federal_reserve"}),
        ],
        widget_config={
            **_FR_META,
            "name": "Federal Reserve Money Measures (H.6)",
            "description": "M1 and M2 money supply and their components, in dollars,"
            " from the Federal Reserve's H.6 release.",
            "gridData": {"w": 40, "h": 20},
            "data": {
                "table": {
                    "showAll": True,
                    "columnsDefs": [
                        {
                            "field": "month",
                            "headerName": "Month",
                            "cellDataType": "date",
                            "pinned": "left",
                        },
                        {
                            "field": "m1",
                            "headerName": "M1",
                            "cellDataType": "number",
                            "formatterFn": "int",
                        },
                        {
                            "field": "m2",
                            "headerName": "M2",
                            "cellDataType": "number",
                            "formatterFn": "int",
                        },
                        {
                            "field": "currency",
                            "headerName": "Currency",
                            "cellDataType": "number",
                            "formatterFn": "int",
                        },
                        {
                            "field": "demand_deposits",
                            "headerName": "Demand Deposits",
                            "cellDataType": "number",
                            "formatterFn": "int",
                        },
                        {
                            "field": "retail_money_market_funds",
                            "headerName": "Retail Money Market Funds",
                            "cellDataType": "number",
                            "formatterFn": "int",
                        },
                        {
                            "field": "other_liquid_deposits",
                            "headerName": "Other Liquid Deposits",
                            "cellDataType": "number",
                            "formatterFn": "int",
                        },
                        {
                            "field": "small_denomination_time_deposits",
                            "headerName": "Small Denomination Time Deposits",
                            "cellDataType": "number",
                            "formatterFn": "int",
                        },
                    ],
                }
            },
        },
    )
    async def money_measures(
        cc: CommandContext,
        provider_choices: ProviderChoices,
        standard_params: StandardParams,
        extra_params: ExtraParams,
    ) -> OBBject:
        """Get Money Measures (M1/M2 and components) from the H.6 Release."""
        return await OBBject.from_query(Query(**locals()))


if not FIXEDINCOME_INSTALLED:

    @router.command(
        model="FederalReserveTreasuryRates",
        examples=[APIEx(parameters={"provider": "federal_reserve"})],
        widget_config={
            **_FR_META,
            "name": "Treasury Constant Maturity Rates (H.15)",
            "description": "Daily Treasury constant-maturity rates across the curve,"
            " in percent, from the Federal Reserve's H.15 release.",
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
                            "field": "month_1",
                            "headerName": "1 Month",
                            "cellDataType": "number",
                            "formatterFn": "normalizedPercent",
                        },
                        {
                            "field": "month_3",
                            "headerName": "3 Month",
                            "cellDataType": "number",
                            "formatterFn": "normalizedPercent",
                        },
                        {
                            "field": "month_6",
                            "headerName": "6 Month",
                            "cellDataType": "number",
                            "formatterFn": "normalizedPercent",
                        },
                        {
                            "field": "year_1",
                            "headerName": "1 Year",
                            "cellDataType": "number",
                            "formatterFn": "normalizedPercent",
                        },
                        {
                            "field": "year_2",
                            "headerName": "2 Year",
                            "cellDataType": "number",
                            "formatterFn": "normalizedPercent",
                        },
                        {
                            "field": "year_3",
                            "headerName": "3 Year",
                            "cellDataType": "number",
                            "formatterFn": "normalizedPercent",
                        },
                        {
                            "field": "year_5",
                            "headerName": "5 Year",
                            "cellDataType": "number",
                            "formatterFn": "normalizedPercent",
                        },
                        {
                            "field": "year_7",
                            "headerName": "7 Year",
                            "cellDataType": "number",
                            "formatterFn": "normalizedPercent",
                        },
                        {
                            "field": "year_10",
                            "headerName": "10 Year",
                            "cellDataType": "number",
                            "formatterFn": "normalizedPercent",
                        },
                        {
                            "field": "year_20",
                            "headerName": "20 Year",
                            "cellDataType": "number",
                            "formatterFn": "normalizedPercent",
                        },
                        {
                            "field": "year_30",
                            "headerName": "30 Year",
                            "cellDataType": "number",
                            "formatterFn": "normalizedPercent",
                        },
                    ],
                }
            },
        },
    )
    async def treasury_rates(
        cc: CommandContext,
        provider_choices: ProviderChoices,
        standard_params: StandardParams,
        extra_params: ExtraParams,
    ) -> OBBject:
        """Get Government Treasury Rates."""
        return await OBBject.from_query(Query(**locals()))

    @router.command(
        model="FederalReserveYieldCurve",
        examples=[
            APIEx(parameters={"provider": "federal_reserve"}),
            APIEx(
                parameters={
                    "date": "2024-05-13,2020-05-09",
                    "provider": "federal_reserve",
                }
            ),
        ],
        widget_config={
            **_FR_META,
            "name": "Treasury Yield Curve",
            "description": "The Treasury constant-maturity yield curve by date,"
            " rates in percent across the maturity spectrum.",
            "gridData": {"w": 40, "h": 20},
            "data": {
                "table": {
                    "showAll": True,
                    "chartView": {"enabled": True, "chartType": "line"},
                    "columnsDefs": [
                        {
                            "field": "maturity",
                            "headerName": "Maturity",
                            "pinned": "left",
                            "chartDataType": "category",
                        },
                        {
                            "field": "rate",
                            "headerName": "Rate",
                            "cellDataType": "number",
                            "formatterFn": "normalizedPercent",
                            "chartDataType": "series",
                        },
                        {
                            "field": "date",
                            "headerName": "Date",
                            "cellDataType": "date",
                            "chartDataType": "excluded",
                        },
                    ],
                }
            },
        },
    )
    async def yield_curve(
        cc: CommandContext,
        provider_choices: ProviderChoices,
        standard_params: StandardParams,
        extra_params: ExtraParams,
    ) -> OBBject:
        """Get yield curve data by date."""
        return await OBBject.from_query(Query(**locals()))


from openbb_federal_reserve.ffiec import router as ffiec_router  # noqa: E402
from openbb_federal_reserve.regional.atlanta import (  # noqa: E402
    router as atlanta_router,
)
from openbb_federal_reserve.regional.boston import (  # noqa: E402
    router as boston_router,
)
from openbb_federal_reserve.regional.chicago import (
    router as chicago_router,  # noqa: E402
)
from openbb_federal_reserve.regional.cleveland import (  # noqa: E402
    router as cleveland_router,
)
from openbb_federal_reserve.regional.dallas import (  # noqa: E402
    router as dallas_router,
)
from openbb_federal_reserve.regional.kansas_city import (  # noqa: E402
    router as kansas_city_router,
)
from openbb_federal_reserve.regional.minneapolis import (  # noqa: E402
    router as minneapolis_router,
)
from openbb_federal_reserve.regional.new_york import (  # noqa: E402
    router as new_york_router,
)
from openbb_federal_reserve.regional.philadelphia import (  # noqa: E402
    router as philadelphia_router,
)
from openbb_federal_reserve.regional.richmond import (  # noqa: E402
    router as richmond_router,
)
from openbb_federal_reserve.regional.san_francisco import (  # noqa: E402
    router as san_francisco_router,
)
from openbb_federal_reserve.regional.st_louis import (  # noqa: E402
    router as st_louis_router,
)
from openbb_federal_reserve.utils.widgets import (  # noqa: E402
    register_spec_routes,
)

register_spec_routes(ffiec_router, "ffiec", "FFIEC", curated_apps=True)
router._api_router.include_router(router=ffiec_router.api_router, prefix="/ffiec")
router._routers["ffiec"] = ffiec_router
_REGIONAL_DISTRICTS = [
    (atlanta_router, "atlanta", "Atlanta"),
    (boston_router, "boston", "Boston"),
    (chicago_router, "chicago", "Chicago"),
    (cleveland_router, "cleveland", "Cleveland"),
    (dallas_router, "dallas", "Dallas"),
    (kansas_city_router, "kc", "Kansas City"),
    (minneapolis_router, "minneapolis", "Minneapolis"),
    (new_york_router, "ny", "New York"),
    (philadelphia_router, "philadelphia", "Philadelphia"),
    (richmond_router, "richmond", "Richmond"),
    (san_francisco_router, "sf", "San Francisco"),
    (st_louis_router, "stl", "Saint Louis"),
]

for _district_router, _slug, _district_name in _REGIONAL_DISTRICTS:
    register_spec_routes(_district_router, _slug, _district_name)
    _district_router.api_router.add_api_route(
        path="/regional_publications_download",
        endpoint=regional_publications_download,
        methods=["POST"],
        include_in_schema=False,
    )
    _district_router.api_router.add_api_route(
        path="/regional_publications_choices",
        endpoint=regional_publications_choices,
        methods=["GET"],
        include_in_schema=False,
    )
    _district_router.api_router.add_api_route(
        path="/regional_reports_choices",
        endpoint=regional_reports_choices,
        methods=["GET"],
        include_in_schema=False,
    )
    if _slug == "atlanta":
        _district_router.api_router.add_api_route(
            path="/market_probability_meetings",
            endpoint=market_probability_meetings,
            methods=["GET"],
            include_in_schema=False,
        )
    router._api_router.include_router(
        router=_district_router.api_router, prefix=f"/{_slug}"
    )
    router._routers[_slug] = _district_router
