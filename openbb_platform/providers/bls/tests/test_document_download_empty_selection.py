"""An unselected Workspace file picker must not crash document routes."""

import importlib

import pytest


@pytest.mark.parametrize(
    "route", ["cpi", "ppi", "jolts", "ces", "productivity", "ximpim", "realer"]
)
@pytest.mark.parametrize("params", [{}, {"url": None}, {"url": []}])
@pytest.mark.asyncio
async def test_empty_document_selection(route, params):
    module = importlib.import_module(f"openbb_bls.routers.{route}")
    assert await module.document_download(params) == []


@pytest.mark.parametrize(
    "route", ["cpi", "ppi", "jolts", "ces", "productivity", "ximpim", "realer"]
)
@pytest.mark.asyncio
async def test_selected_url_still_validated(route):
    from openbb_core.app.model.abstract.error import OpenBBError

    module = importlib.import_module(f"openbb_bls.routers.{route}")
    with pytest.raises(OpenBBError, match="Invalid URL"):
        await module.document_download({"url": "https://example.com/file.pdf"})
