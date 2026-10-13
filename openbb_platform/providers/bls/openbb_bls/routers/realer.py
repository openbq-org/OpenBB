"""BLS Real Earnings sub-router."""

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

from openbb_bls.utils.constants import BLS_USER_AGENT

router = Router(prefix="/real_earnings", description="BLS Real Earnings router.")


@router.command(
    model="BlsRealerDocuments",
    examples=[
        APIEx(
            description="All Real Earnings release PDFs (current + archive).",
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
    """List BLS Real Earnings release PDFs for the file viewer."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.api_router.get("/document_choices", include_in_schema=False)
async def document_choices(
    category: str = "all",
    start_date: str | None = None,
    end_date: str | None = None,
) -> list:
    """Return [{label, value}] for the Real Earnings document file-selector dropdown."""
    from openbb_bls.models.realer_documents import BlsRealerDocumentsFetcher

    fetcher = BlsRealerDocumentsFetcher
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
    """Download BLS Real Earnings PDFs and return them base64-encoded."""
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
