"""Tests for ``AppLoader``'s OpenAPI tag rewriting."""

import json

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from openbb_core.api.app_loader import AppLoader


def _app_with_base_schema(schema: dict) -> FastAPI:
    """Return an app whose base ``openapi()`` yields ``schema``."""
    app = FastAPI()
    app.openapi = lambda: schema  # type: ignore[method-assign]
    AppLoader.add_openapi_tags(app)
    return app


def test_openapi_collapses_nested_tags_into_one_composite():
    """A route tagged per nesting level collapses to a single composite tag.

    Swagger renders an operation under every tag it carries, so leaving
    ``["eia", "coal"]`` in place lists the endpoint twice, in two sections.
    """
    schema = {
        "paths": {
            "/a": {
                "get": {"tags": ["eia", "coal"]},
                # A path-level ``parameters`` list is not an operation.
                "parameters": [],
            },
            "/b": {"get": {"tags": ["eia"]}},
            "/c": {"get": {}},
        }
    }
    app = _app_with_base_schema(schema)
    out = app.openapi()

    assert out["paths"]["/a"]["get"]["tags"] == ["eia/coal"]
    assert out["paths"]["/b"]["get"]["tags"] == ["eia"]
    # Untagged operations are left alone.
    assert "tags" not in out["paths"]["/c"]["get"]
    # No operation carries more than one tag, so nothing is listed twice.
    assert all(
        len(op.get("tags", [])) <= 1
        for item in out["paths"].values()
        for op in item.values()
        if isinstance(op, dict)
    )


def test_openapi_emits_redoc_tag_groups():
    """The first level becomes a ReDoc ``x-tagGroups`` group."""
    schema = {
        "paths": {
            "/a": {"get": {"tags": ["eia", "petroleum", "prices"]}},
            "/b": {"get": {"tags": ["eia", "coal"]}},
            "/c": {"get": {"tags": ["sec"]}},
        }
    }
    out = _app_with_base_schema(schema).openapi()

    assert out["x-tagGroups"] == [
        {"name": "eia", "tags": ["eia/coal", "eia/petroleum/prices"]},
        {"name": "sec", "tags": ["sec"]},
    ]
    assert [t["name"] for t in out["tags"]] == [
        "eia/coal",
        "eia/petroleum/prices",
        "sec",
    ]


def test_openapi_unknown_tag_path_gets_empty_description():
    """A tag with no matching router resolves to an empty description."""
    out = _app_with_base_schema(
        {"paths": {"/a": {"get": {"tags": ["not_a_router_xyz"]}}}}
    ).openapi()
    assert out["tags"] == [{"name": "not_a_router_xyz", "description": ""}]


def test_openapi_without_tagged_operations_adds_nothing():
    """With no tagged operation there is no tag list or group list to add."""
    out = _app_with_base_schema({"paths": {"/a": {"get": {}}}}).openapi()
    assert "x-tagGroups" not in out
    assert "tags" not in out


def test_openapi_returns_cached_schema():
    """A built schema is returned as-is on later calls."""
    app = _app_with_base_schema({"paths": {}})
    app.openapi_schema = {"already": "built"}
    assert app.openapi() == {"already": "built"}


def test_core_groups_sort_after_data_extensions(monkeypatch):
    """``Coverage`` and friends sort last, below the data extensions.

    They come from routers the core mounts itself, so they are absent from
    ``main_router.routers``. Plain alphabetical order floats them to the top
    (``"C" < "e"`` in ASCII), burying what the API is actually for.
    """

    class _FakeRouter:
        routers = {"eia": object(), "sec": object()}

        @staticmethod
        def get_attr(_path, _attr):
            return ""

    monkeypatch.setattr(
        "openbb_core.api.app_loader.RouterLoader.from_extensions",
        _FakeRouter,
    )

    schema = {
        "paths": {
            "/a": {"get": {"tags": ["Coverage"]}},
            "/b": {"get": {"tags": ["System"]}},
            "/c": {"get": {"tags": ["sec"]}},
            "/d": {"get": {"tags": ["eia", "coal"]}},
            "/e": {"get": {"tags": ["eia"]}},
        }
    }
    out = _app_with_base_schema(schema).openapi()

    assert [t["name"] for t in out["tags"]] == [
        "eia",
        "eia/coal",
        "sec",
        "Coverage",
        "System",
    ]
    assert [g["name"] for g in out["x-tagGroups"]] == [
        "eia",
        "sec",
        "Coverage",
        "System",
    ]


def test_swagger_ui_opens_with_every_tag_collapsed():
    """``docExpansion="none"`` keeps the tag cards closed on load.

    Swagger UI's own default is "list", which expands every section and dumps
    hundreds of endpoint rows on the reader before they pick anything.
    """
    from openbb_core.api.rest_api import app

    assert (app.swagger_ui_parameters or {}).get("docExpansion") == "none"


@pytest.mark.parametrize(
    "error, status",
    [
        (TimeoutError("slow"), 504),
        (json.JSONDecodeError("Expecting value", "<html>", 0), 502),
    ],
)
def test_timeout_and_invalid_json_responses_keep_cors_headers(
    monkeypatch, error, status
):
    """Handlers registered by type run inside the CORS middleware.

    The ``Exception`` catch-all runs outside it, so a browser client would see
    a CORS failure instead of the status.
    """
    monkeypatch.setattr(
        "openbb_core.api.exception_handlers.Env", type("E", (), {"DEBUG_MODE": False})
    )
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=["*"])
    AppLoader.add_exception_handlers(app)

    @app.get("/fail")
    async def fail():
        raise error

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/fail", headers={"Origin": "https://example.com"})
    assert response.status_code == status
    assert response.headers.get("access-control-allow-origin") == "*"
