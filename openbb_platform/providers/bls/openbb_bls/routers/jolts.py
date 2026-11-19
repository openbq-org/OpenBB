"""BLS JOLTS sub-router."""

from typing import Annotated

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
from openbb_core.app.query import Query as OBBQuery
from openbb_core.app.router import Router

from openbb_bls.models.jolts_charts import (
    jolts_chart_model_name as _jolts_chart_model_name,
)
from openbb_bls.utils.constants import BLS_USER_AGENT
from openbb_bls.utils.jolts_charts import CHART_SPECS as _JOLTS_CHART_SPECS

router = Router(prefix="/jolts", description="BLS JOLTS router.")


@router.command(
    model="BlsJoltsChangeAnalysis",
    examples=[
        APIEx(
            description="National JOLTS Table 1 — Job openings SA over-the-month.",
            parameters={"provider": "bls"},
        ),
        APIEx(
            description="National Table 10 — Quits NSA over-the-year.",
            parameters={"provider": "bls", "table_number": 10},
        ),
        APIEx(
            description="State Table 1 — Job openings by state SA over-the-month.",
            parameters={"provider": "bls", "scope": "state", "table_number": 1},
        ),
    ],
)
async def change_analysis(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Fetch a JOLTS change-analysis TXT table (estimated rate/level changes + significance)."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsJoltsRevisions",
    examples=[
        APIEx(
            description="Full seasonally-adjusted JOLTS revision workbook.",
            parameters={"provider": "bls"},
        ),
        APIEx(
            description="NSA revision rows for Construction (industry code 23) only.",
            parameters={
                "provider": "bls",
                "seasonally_adjusted": False,
                "industry_code": "23",
            },
        ),
        APIEx(
            description="SA Quits revisions across every industry / region.",
            parameters={"provider": "bls", "measure": "Quits"},
        ),
    ],
)
async def revisions(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Fetch the JOLTS SA/NSA revision XLSX in long form (1st / 2nd / benchmark levels + revision deltas)."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsJoltsDocuments",
    examples=[
        APIEx(
            description="All current JOLTS PDFs + supplemental files.",
            parameters={"provider": "bls"},
        ),
        APIEx(
            description="Every archived national JOLTS release.",
            parameters={
                "provider": "bls",
                "category": "archived",
                "release_code": "jolts",
            },
        ),
    ],
)
async def documents(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """List BLS JOLTS release PDFs / supplementals / archived releases for the file viewer."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.api_router.get("/document_choices", include_in_schema=False)
async def document_choices(
    category: str = "all",
    release_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list:
    """Return ``[{label, value}]`` for the JOLTS document file-selector dropdown."""
    from openbb_bls.models.jolts_documents import BlsJoltsDocumentsFetcher

    fetcher = BlsJoltsDocumentsFetcher
    params: dict = {"category": category}
    if release_code:
        params["release_code"] = release_code
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    query = fetcher.transform_query(params)
    docs = fetcher.extract_data(query, None)
    return [{"label": d["name"], "value": d["url"]} for d in docs]


@router.api_router.post(
    "/document_download",
    include_in_schema=False,
    openapi_extra={},
)
async def document_download(params: Annotated[dict, Body()]) -> list:
    """Download BLS JOLTS PDFs and return them base64-encoded."""
    import base64
    from io import BytesIO
    from urllib.parse import urlparse

    from openbb_core.provider.utils.helpers import make_request

    urls = params.get("url", [])
    if urls is None:
        urls = []
    if isinstance(urls, str):
        urls = [urls]
    results: list = []
    for url in urls:
        parsed = urlparse(url)
        if parsed.scheme != "https" or (parsed.hostname or "") not in {
            "www.bls.gov",
            "bls.gov",
        }:
            raise OpenBBError(f"Invalid URL — must be served from bls.gov: {url}")
        if not url.lower().endswith(".pdf"):
            raise OpenBBError(f"Unsupported document format (PDF only): {url}")
        try:
            resp = make_request(
                url,
                headers={
                    "User-Agent": BLS_USER_AGENT,
                    "Accept": "application/pdf,*/*",
                },
            )
            resp.raise_for_status()
            encoded = (
                base64.b64encode(BytesIO(resp.content).getvalue()).decode("utf-8")
                if isinstance(resp.content, bytes)
                else resp.content
            )
            results.append(
                {
                    "content": encoded,
                    "data_format": {
                        "data_type": "pdf",
                        "filename": url.rsplit("/", 1)[-1],
                    },
                }
            )
        except Exception as exc:
            results.append(
                {
                    "error_type": "download_error",
                    "content": f"{exc.__class__.__name__}: {exc.args[0] if exc.args else ''}",
                    "filename": url.rsplit("/", 1)[-1],
                }
            )
    return results


def _register_jolts_chart_route(model_name: str, func_name: str, label: str) -> None:
    """Register one JOLTS chart-package command route."""

    async def _route(
        cc: CommandContext,
        provider_choices: ProviderChoices,
        standard_params: StandardParams,
        extra_params: ExtraParams,
    ) -> OBBject:
        return await OBBject.from_query(OBBQuery(**locals()))

    _route.__name__ = func_name
    _route.__qualname__ = func_name
    _route.__doc__ = f"BLS Job Openings and Labor Turnover chart — {label}."
    router.command(
        model=model_name,
        examples=[APIEx(parameters={"provider": "bls"})],
    )(_route)


for _jolts_key, _jolts_spec in _JOLTS_CHART_SPECS.items():
    _register_jolts_chart_route(
        _jolts_chart_model_name(_jolts_key),
        _jolts_key.replace("-", "_"),
        _jolts_spec["label"],
    )
