"""File-viewer downloads return an empty list when nothing is selected."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openbb_federal_reserve.federal_reserve_router import router

# The multi-file viewer widgets post their selection to these paths.
ENDPOINTS = [
    "/fomc_documents_download",
    "/ffiec/bhcpr_report_download",
    "/ffiec/financial_report_pdf_download",
] + [
    f"/{district}/regional_publications_download"
    for district in (
        "atlanta",
        "boston",
        "chicago",
        "cleveland",
        "dallas",
        "kc",
        "minneapolis",
        "ny",
        "philadelphia",
        "richmond",
        "sf",
        "stl",
    )
]


@pytest.fixture(scope="module")
def client():
    """Serve the provider router on its own."""
    app = FastAPI()
    app.include_router(router.api_router)
    return TestClient(app)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("body", [{"url": None}, {"url": []}, {}])
def test_empty_selection_returns_empty_list(client, endpoint, body):
    """A viewer with no selection sends ``{"url": null}``; that is not an error."""
    response = client.post(endpoint, json=body)
    assert (response.status_code, response.json()) == (200, [])
