"""BLS Employment Situation (CES) sub-router."""

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

from openbb_bls.models.empsit_charts import empsit_model_name as _empsit_model_name
from openbb_bls.utils.constants import BLS_USER_AGENT
from openbb_bls.utils.empsit_charts import CHART_SPECS as _EMPSIT_CHART_SPECS

router = Router(
    prefix="/employment_situation", description="BLS Employment Situation (CES) router."
)


@router.command(
    model="BlsEmpsitDocuments",
    examples=[
        APIEx(
            description="All Employment Situation release PDFs (current + archive).",
            parameters={"provider": "bls"},
        ),
        APIEx(
            description="Only 2024 archived releases.",
            parameters={
                "provider": "bls",
                "category": "archived",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
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
    """List BLS Employment Situation release PDFs for the file viewer."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.api_router.get("/document_choices", include_in_schema=False)
async def document_choices(
    category: str = "all",
    start_date: str | None = None,
    end_date: str | None = None,
) -> list:
    """Return [{label, value}] for the Employment Situation document file-selector dropdown."""
    from openbb_bls.models.empsit_documents import BlsEmpsitDocumentsFetcher

    fetcher = BlsEmpsitDocumentsFetcher
    params: dict = {"category": category}
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
    """Download BLS Employment Situation PDFs and return them base64-encoded."""
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


@router.command(
    model="BlsEmpsitSummaryA",
    examples=[APIEx(parameters={"provider": "bls"})],
)
async def summary_household(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Employment Situation Summary Table A — household data, seasonally adjusted."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsEmpsitSummaryB",
    examples=[APIEx(parameters={"provider": "bls"})],
)
async def summary_establishment(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Employment Situation Summary Table B — establishment data, seasonally adjusted."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsCesTable1",
    examples=[APIEx(parameters={"provider": "bls"})],
)
async def t1_employment_changes(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """CES Analytical Table 1 — employment normal seasonal movements, OTM changes, significance."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsCesTable2",
    examples=[APIEx(parameters={"provider": "bls"})],
)
async def t2_ranked_industries(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """CES Analytical Table 2 — detailed industries ranked by over-the-month change."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsCesTable3A",
    examples=[APIEx(parameters={"provider": "bls"})],
)
async def t3a_employment_changes_sa(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """CES Analytical Table 3A — SA employment changes and tests of significance."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsCesTable3B",
    examples=[APIEx(parameters={"provider": "bls"})],
)
async def t3b_changes_vs_averages(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """CES Analytical Table 3B — over-the-month changes compared with recent averages."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsCesTable4",
    examples=[APIEx(parameters={"provider": "bls"})],
)
async def t4_over_the_year_changes(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """CES Analytical Table 4 — over-the-year employment changes and significance."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsCesTable5",
    examples=[APIEx(parameters={"provider": "bls"})],
)
async def t5_hours_earnings(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """CES Analytical Table 5 — average weekly hours and average hourly earnings changes."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsCesTable6",
    examples=[APIEx(parameters={"provider": "bls"})],
)
async def t6_aggregate_hours_payrolls(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """CES Analytical Table 6 — aggregate weekly hours and payroll changes."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsCesTable7",
    examples=[APIEx(parameters={"provider": "bls"})],
)
async def t7_peak_trough(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """CES Analytical Table 7 — most recent employment peak/trough and changes."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsCesConfidenceIntervals",
    examples=[
        APIEx(parameters={"provider": "bls"}),
        APIEx(parameters={"provider": "bls", "ci_table": "A"}),
    ],
)
async def confidence_intervals(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """CES Analytical Tables A-C2 — 90% confidence intervals for employment, hours, and earnings."""
    return await OBBject.from_query(OBBQuery(**locals()))


def _register_empsit_chart_route(model_name: str, func_name: str, label: str) -> None:
    """Register one Employment Situation chart-package command route."""

    async def _route(
        cc: CommandContext,
        provider_choices: ProviderChoices,
        standard_params: StandardParams,
        extra_params: ExtraParams,
    ) -> OBBject:
        return await OBBject.from_query(OBBQuery(**locals()))

    _route.__name__ = func_name
    _route.__qualname__ = func_name
    _route.__doc__ = f"BLS Employment Situation chart — {label}."
    router.command(
        model=model_name,
        examples=[APIEx(parameters={"provider": "bls"})],
    )(_route)


for _empsit_key, _empsit_spec in _EMPSIT_CHART_SPECS.items():
    _register_empsit_chart_route(
        _empsit_model_name(_empsit_key),
        _empsit_key.replace("-", "_"),
        _empsit_spec["label"],
    )
