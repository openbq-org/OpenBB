"""BLS PPI sub-router."""

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

from openbb_bls.models.ppi_charts import ppi_model_name as _ppi_model_name
from openbb_bls.utils.constants import BLS_USER_AGENT
from openbb_bls.utils.ppi_charts import CHART_SPECS as _PPI_CHART_SPECS

router = Router(prefix="/ppi", description="BLS PPI router.")


@router.command(
    model="BlsPpiRelativeImportance",
    examples=[
        APIEx(
            description="Final Demand relative importance (default canonical table).",
            parameters={"provider": "bls", "category": "final_demand"},
        ),
        APIEx(
            description="Fetch a specific relative-importance table by id.",
            parameters={"provider": "bls", "table_id": "ppi-comrlp"},
        ),
    ],
)
async def relative_importance(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Fetch a published BLS Producer Price Index relative-importance table."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsPpiSeasonalFactors",
    examples=[
        APIEx(
            description="FD-ID aggregation seasonal factors for the previous five years.",
            parameters={"provider": "bls", "category": "fd_id"},
        ),
        APIEx(
            description="Current-year commodity forecast seasonal factors.",
            parameters={"provider": "bls", "category": "forecast"},
        ),
    ],
)
async def seasonal_factors(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Fetch a published BLS Producer Price Index seasonal-factor table."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsPpiDetailedReport",
    examples=[
        APIEx(
            description="Latest monthly PPI Detailed Report, Table 1 (FD-ID summary).",
            parameters={"provider": "bls"},
        ),
        APIEx(
            description="Specific month and table — unadjusted commodity indexes.",
            parameters={"provider": "bls", "date": "2026-04-01", "table": 9},
        ),
    ],
)
async def detailed_report(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Fetch one table from a BLS monthly PPI Detailed Report (XLSX, 2022+)."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsPpiDocuments",
    examples=[
        APIEx(
            description="Browse the monthly PPI Detailed Report PDF archive.",
            parameters={"provider": "bls", "category": "detailed_report"},
        ),
        APIEx(
            description="Detailed Report PDFs for a single year.",
            parameters={"provider": "bls", "category": "detailed_report", "year": 2024},
        ),
    ],
)
async def documents(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """List published BLS PPI PDF documents for the multi-file viewer widget."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.api_router.get("/document_choices", include_in_schema=False)
async def document_choices(
    category: str = "detailed_report",
    year: int | None = None,
) -> list:
    """Return ``[{label, value}]`` for the PPI document file-selector dropdown."""
    from openbb_bls.models.ppi_documents import BlsPpiDocumentsFetcher

    fetcher = BlsPpiDocumentsFetcher
    query = fetcher.transform_query({"category": category, "year": year})
    docs = fetcher.extract_data(query, None)
    return [{"label": d["name"], "value": d["url"]} for d in docs]


@router.api_router.post(
    "/document_download",
    include_in_schema=False,
    openapi_extra={},
)
async def document_download(params: Annotated[dict, Body()]) -> list:
    """Download one or more BLS PPI PDFs and return them base64-encoded."""
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


def _register_ppi_chart_route(model_name: str, func_name: str, label: str) -> None:
    """Register one Producer Price Index chart-package command route."""

    async def _route(
        cc: CommandContext,
        provider_choices: ProviderChoices,
        standard_params: StandardParams,
        extra_params: ExtraParams,
    ) -> OBBject:
        return await OBBject.from_query(OBBQuery(**locals()))

    _route.__name__ = func_name
    _route.__qualname__ = func_name
    _route.__doc__ = f"BLS Producer Price Index chart — {label}."
    router.command(
        model=model_name,
        examples=[APIEx(parameters={"provider": "bls"})],
    )(_route)


for _ppi_key, _ppi_spec in _PPI_CHART_SPECS.items():
    _register_ppi_chart_route(
        _ppi_model_name(_ppi_key),
        _ppi_key.replace("-", "_"),
        _ppi_spec["label"],
    )
