"""BLS Productivity sub-router."""

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

from openbb_bls.models.mining_manufacturing_charts import (
    mining_manufacturing_model_name as _mm_model_name,
)
from openbb_bls.models.productivity_charts import (
    productivity_model_name as _productivity_model_name,
)
from openbb_bls.models.tfp_charts import tfp_model_name as _tfp_model_name
from openbb_bls.models.wholesale_retail_charts import (
    wholesale_retail_model_name as _wr_model_name,
)
from openbb_bls.utils.constants import BLS_USER_AGENT
from openbb_bls.utils.mining_manufacturing_charts import (
    CHART_SPECS as _MM_CHART_SPECS,
)
from openbb_bls.utils.productivity_charts import (
    CHART_SPECS as _PRODUCTIVITY_CHART_SPECS,
)
from openbb_bls.utils.tfp_charts import CHART_SPECS as _TFP_CHART_SPECS
from openbb_bls.utils.wholesale_retail_charts import CHART_SPECS as _WR_CHART_SPECS

router = Router(prefix="/productivity", description="BLS Productivity router.")


@router.command(
    model="BlsProductivityTables",
    examples=[
        APIEx(
            description="Quarterly Nonfarm business sector labor productivity"
            " (the default headline series).",
            parameters={"provider": "bls"},
        ),
        APIEx(
            description="Manufacturing sector unit labor costs, quarterly.",
            parameters={
                "provider": "bls",
                "sector": "Manufacturing sector",
                "measure": "Unit labor costs",
            },
        ),
        APIEx(
            description="Total economy hours worked, in billions of hours.",
            parameters={
                "provider": "bls",
                "dataset": "total-economy-hours-employment",
                "sector": "Total economy",
                "measure": "Hours worked",
                "units": "Billions of hours",
            },
        ),
        APIEx(
            description="Nonfarm business labor productivity growth by business cycle.",
            parameters={
                "provider": "bls",
                "dataset": "major-sectors-business-cycles",
                "units": "Compound annual growth rate",
            },
        ),
    ],
)
async def tables(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Fetch a BLS Productivity prod2 supplemental table in long form (every column preserved)."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="BlsProductivityDocuments",
    examples=[
        APIEx(
            description="All current Productivity release PDFs.",
            parameters={"provider": "bls"},
        ),
    ],
)
async def documents(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """List BLS Productivity release PDFs and supplemental XLSX files for the file viewer."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.api_router.get("/document_choices", include_in_schema=False)
async def document_choices(
    category: str = "all",
    release_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list:
    """Return ``[{label, value}]`` for the Productivity document file-selector dropdown."""
    from openbb_bls.models.productivity_documents import BlsProductivityDocumentsFetcher

    fetcher = BlsProductivityDocumentsFetcher
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
    """Download BLS Productivity PDFs and return them base64-encoded."""
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


def _register_productivity_chart_route(
    model_name: str, func_name: str, label: str
) -> None:
    """Register one Productivity and Costs chart-package command route."""

    async def _route(
        cc: CommandContext,
        provider_choices: ProviderChoices,
        standard_params: StandardParams,
        extra_params: ExtraParams,
    ) -> OBBject:
        return await OBBject.from_query(OBBQuery(**locals()))

    _route.__name__ = func_name
    _route.__qualname__ = func_name
    _route.__doc__ = f"BLS Productivity and Costs chart — {label}."
    router.command(
        model=model_name,
        examples=[APIEx(parameters={"provider": "bls"})],
    )(_route)


for _prod_key, _prod_spec in _PRODUCTIVITY_CHART_SPECS.items():
    _register_productivity_chart_route(
        _productivity_model_name(_prod_key),
        _prod_key.replace("-", "_"),
        _prod_spec["label"],
    )

for _specs, _name_fn in (
    (_TFP_CHART_SPECS, _tfp_model_name),
    (_WR_CHART_SPECS, _wr_model_name),
    (_MM_CHART_SPECS, _mm_model_name),
):
    for _key, _spec in _specs.items():
        _register_productivity_chart_route(
            _name_fn(_key),
            _key.replace("-", "_"),
            _spec["label"],
        )
