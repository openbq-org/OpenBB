"""BLS CPI sub-router."""

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

from openbb_bls.models.cpi_charts import cpi_model_name as _cpi_model_name
from openbb_bls.utils.constants import BLS_USER_AGENT
from openbb_bls.utils.cpi_charts import CHART_SPECS as _CPI_CHART_SPECS

router = Router(prefix="/cpi", description="BLS CPI router.")


@router.command(
    model="BlsCpiNrTable1",
    examples=[
        APIEx(
            description="Latest CPI-U expenditure category table.",
            parameters={"provider": "bls"},
        ),
    ],
)
async def t1_expenditure_category(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """CPI News Release Table 1 — CPI-U U.S. city average, by expenditure category."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsCpiNrTable2",
    examples=[
        APIEx(
            description="Latest CPI-U detailed expenditure category table.",
            parameters={"provider": "bls"},
        ),
    ],
)
async def t2_detailed_expenditure(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """CPI News Release Table 2 — CPI-U U.S. city average, by detailed expenditure category."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsCpiNrTable3",
    examples=[
        APIEx(
            description="Latest CPI-U special aggregate indexes.",
            parameters={"provider": "bls"},
        ),
    ],
)
async def t3_special_aggregates(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """CPI News Release Table 3 — CPI-U U.S. city average, special aggregate indexes."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsCpiNrTable4",
    examples=[
        APIEx(
            description="Latest CPI-U selected areas all-items index.",
            parameters={"provider": "bls"},
        ),
    ],
)
async def t4_selected_areas(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """CPI News Release Table 4 — CPI-U selected areas, all items index."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsCpiNrTable5",
    examples=[
        APIEx(
            description="Latest Chained CPI vs CPI-U time series.",
            parameters={"provider": "bls"},
        ),
    ],
)
async def t5_chained_vs_cpiu(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """CPI News Release Table 5 — Chained CPI (C-CPI-U) and CPI-U 1m/12m percent changes."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsCpiNrTable6",
    examples=[
        APIEx(
            description="Latest CPI-U 1-month analysis table.",
            parameters={"provider": "bls"},
        ),
    ],
)
async def t6_1m_analysis(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """CPI News Release Table 6 — CPI-U U.S. city average, by expenditure category, 1-month analysis."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsCpiNrTable7",
    examples=[
        APIEx(
            description="Latest CPI-U 12-month analysis table.",
            parameters={"provider": "bls"},
        ),
    ],
)
async def t7_12m_analysis(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """CPI News Release Table 7 — CPI-U U.S. city average, by expenditure category, 12-month analysis."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsCpiRelativeImportance",
    examples=[
        APIEx(
            description="Latest CPI relative-importance weights for CPI-U & CPI-W.",
            parameters={"provider": "bls"},
        ),
        APIEx(
            description="2024 weights for selected local areas (Table 2).",
            parameters={"provider": "bls", "year": 2024, "table": 2},
        ),
    ],
)
async def relative_importance(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Fetch BLS CPI relative-importance and weights for one yearly file + sheet."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsCpiSeasonalFactors",
    examples=[
        APIEx(
            description="Latest BLS CPI revised seasonal factors + adjusted indexes.",
            parameters={"provider": "bls"},
        ),
        APIEx(
            description="2024-vintage seasonal factors (covers 2020-2024).",
            parameters={"provider": "bls", "year": 2024},
        ),
    ],
)
async def seasonal_factors(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Fetch BLS CPI revised seasonally-adjusted indexes and seasonal factors."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsCpiSupplementalTables",
    examples=[
        APIEx(
            description="Latest CPI-U U.S. city average expenditure-category table.",
            parameters={"provider": "bls"},
        ),
        APIEx(
            description="Latest C-CPI-U snapshot.",
            parameters={"provider": "bls", "table": "c-cpi-u"},
        ),
        APIEx(
            description="Historical CPI-U index values (back to 1913).",
            parameters={"provider": "bls", "table": "historical-cpi-u-index"},
        ),
        APIEx(
            description="One specific monthly snapshot.",
            parameters={
                "provider": "bls",
                "table": "cpi-u-us",
                "date": "2024-06-01",
            },
        ),
    ],
)
async def supplemental_tables(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Fetch one of the BLS CPI supplemental XLSX tables (C-CPI-U, CPI-W, historical, etc.)."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsCpiDocuments",
    examples=[
        APIEx(
            description="All CPI release PDFs (current + archive back to May 2002).",
            parameters={"provider": "bls"},
        ),
        APIEx(
            description="Only the archive, narrowed to 2024 releases.",
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
    """List BLS CPI release PDFs for the file viewer (current edition + archive back to May 2002)."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.api_router.get("/document_choices", include_in_schema=False)
async def document_choices(
    category: str = "all",
    start_date: str | None = None,
    end_date: str | None = None,
) -> list:
    """Return [{label, value}] for the CPI document file-selector dropdown."""
    from openbb_bls.models.cpi_documents import BlsCpiDocumentsFetcher

    fetcher = BlsCpiDocumentsFetcher
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
    """Download BLS CPI PDFs and return them base64-encoded."""
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


def _register_cpi_chart_route(model_name: str, func_name: str, label: str) -> None:
    """Register one Consumer Price Index chart-package command route."""

    async def _route(
        cc: CommandContext,
        provider_choices: ProviderChoices,
        standard_params: StandardParams,
        extra_params: ExtraParams,
    ) -> OBBject:
        return await OBBject.from_query(OBBQuery(**locals()))

    _route.__name__ = func_name
    _route.__qualname__ = func_name
    _route.__doc__ = f"BLS Consumer Price Index chart — {label}."
    router.command(
        model=model_name,
        examples=[APIEx(parameters={"provider": "bls"})],
    )(_route)


for _cpi_key, _cpi_spec in _CPI_CHART_SPECS.items():
    _register_cpi_chart_route(
        _cpi_model_name(_cpi_key),
        _cpi_key.replace("-", "_"),
        _cpi_spec["label"],
    )
