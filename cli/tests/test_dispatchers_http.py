"""Tests for openbb_cli.dispatchers.http — HttpDispatcher against openbb-platform-api."""

import json
import re

import httpx
import pytest

from openbb_cli.dispatchers.http import HttpDispatcher
from openbb_cli.dispatchers.protocol import Request


def _make_dispatcher(handler) -> HttpDispatcher:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return HttpDispatcher("http://test", client=client)


@pytest.mark.asyncio
async def test_dispatch_success_translates_dotted_path():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content) if request.content else {}
        return httpx.Response(200, json={"echo": captured["body"]})

    d = _make_dispatcher(handler)
    try:
        resp = await d.dispatch(
            Request(
                id="x", command="equity.price.historical", params={"symbol": "AAPL"}
            )
        )
    finally:
        await d.aclose()

    assert resp.ok is True
    assert resp.id == "x"
    # The single-key ``echo`` wrapper gets stripped by the response
    # unwrap, matching how an installed extension surfaces the same row.
    assert resp.result == {"symbol": "AAPL"}
    assert "/api/v1/equity/price/historical" in captured["url"]


@pytest.mark.asyncio
async def test_dispatch_4xx_yields_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "not found"})

    d = _make_dispatcher(handler)
    try:
        resp = await d.dispatch(Request(command="nope"))
    finally:
        await d.aclose()

    assert resp.ok is False
    assert resp.error is not None
    assert resp.error.type == "HTTP404"


@pytest.mark.asyncio
async def test_dispatch_5xx_with_text_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal explosion")

    d = _make_dispatcher(handler)
    try:
        resp = await d.dispatch(Request(command="equity.q"))
    finally:
        await d.aclose()

    assert resp.ok is False
    assert resp.error is not None
    assert resp.error.type == "HTTP500"


@pytest.mark.asyncio
async def test_dispatch_request_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failed")

    d = _make_dispatcher(handler)
    try:
        resp = await d.dispatch(Request(command="x"))
    finally:
        await d.aclose()

    assert resp.ok is False
    assert resp.error is not None
    assert resp.error.type == "ConnectError"


@pytest.mark.asyncio
async def test_dispatch_unexpected_exception_isolated():
    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("boom")

    d = _make_dispatcher(handler)
    try:
        resp = await d.dispatch(Request(command="x"))
    finally:
        await d.aclose()

    assert resp.ok is False
    assert resp.error is not None
    assert resp.error.type in {"RuntimeError", "TransportError"}


@pytest.mark.asyncio
async def test_aclose_owns_client_when_constructed_internally():
    d = HttpDispatcher("http://x")
    assert d._owns_client is True
    await d.aclose()


@pytest.mark.asyncio
async def test_aclose_does_not_close_external_client():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    client = httpx.AsyncClient(transport=transport)
    d = HttpDispatcher("http://x", client=client)
    await d.aclose()
    response = await client.get("http://x/")
    assert response.status_code == 200
    await client.aclose()


def test_url_for_strips_separators():
    d = HttpDispatcher("http://srv/")
    assert d._url_for("equity.price") == "http://srv/api/v1/equity/price"


def test_custom_api_prefix():
    d = HttpDispatcher("http://srv", api_prefix="custom/v2")
    assert d._url_for("ping") == "http://srv/custom/v2/ping"


@pytest.mark.asyncio
async def test_dispatch_unwraps_single_array_envelope():
    """``{"refRates": [...]}`` -> the rows list, matching codegen behavior."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "refRates": [
                    {"effectiveDate": "2026-04-30", "type": "TGCR"},
                    {"effectiveDate": "2026-04-29", "type": "TGCR"},
                ]
            },
        )

    d = _make_dispatcher(handler)
    try:
        resp = await d.dispatch(Request(command="rates.last"))
    finally:
        await d.aclose()
    assert resp.ok is True
    assert resp.result == [
        {"effectiveDate": "2026-04-30", "type": "TGCR"},
        {"effectiveDate": "2026-04-29", "type": "TGCR"},
    ]


@pytest.mark.asyncio
async def test_dispatch_splits_metadata_from_rows():
    """Sibling API metadata (NY-Fed-style ``asOfDate`` next to a row array)
    lands at its own key under ``extra`` of an OBBject — NOT folded into
    ``results_metadata`` (which is per-column data) and NOT folded into
    ``metadata`` (which is execution telemetry). Three distinct concepts,
    three distinct keys.
    """
    from openbb_core.app.model.obbject import OBBject

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"asOfDate": "2026-04-30", "operations": [{"id": 1}, {"id": 2}]},
        )

    d = _make_dispatcher(handler)
    try:
        resp = await d.dispatch(Request(command="x"))
    finally:
        await d.aclose()
    assert resp.ok is True
    assert isinstance(resp.result, OBBject)
    assert resp.result.results == [{"id": 1}, {"id": 2}]
    # ``asOfDate`` lands directly under ``extra`` — its own key, not
    # buried inside ``results_metadata`` (which is per-column) and not
    # inside ``metadata`` (which is execution info).
    assert resp.result.extra["asOfDate"] == "2026-04-30"
    assert "results_metadata" not in resp.result.extra
    # ``metadata`` is NOT a top-level OBBject property — it lives under
    # ``extra``. The dump confirms the shape.
    dumped = resp.result.model_dump()
    assert "metadata" not in dumped  # never at top level
    assert "results_metadata" not in dumped  # ditto


@pytest.mark.asyncio
async def test_dispatch_unwraps_array_of_scalars_into_value_field_then_flattens():
    """Single-key envelope around a string array -> a flat list of strings."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"asOfDates": ["2026-04-30", "2026-04-23"]})

    d = _make_dispatcher(handler)
    try:
        resp = await d.dispatch(Request(command="x"))
    finally:
        await d.aclose()
    # Each scalar gets wrapped as ``{value: x}`` by ``unpack_response``;
    # ``_shape_result`` then unwraps the synthetic ``value`` key for clean
    # rendering.
    assert resp.result == ["2026-04-30", "2026-04-23"]


@pytest.mark.asyncio
async def test_dispatch_passes_text_response_through_unchanged():
    """Non-JSON responses (XML, CSV, plain text) bypass the unwrap entirely."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text="<xml>raw</xml>", headers={"content-type": "application/xml"}
        )

    d = _make_dispatcher(handler)
    try:
        resp = await d.dispatch(Request(command="x"))
    finally:
        await d.aclose()
    assert resp.result == "<xml>raw</xml>"


@pytest.mark.asyncio
async def test_dispatch_returns_payload_unchanged_when_unwrap_yields_nothing():
    """Empty list response: ``unpack_response`` produces ``([], {})``;
    the dispatcher leaves the original payload untouched rather than
    collapsing to ``None``."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    d = _make_dispatcher(handler)
    try:
        resp = await d.dispatch(Request(command="x"))
    finally:
        await d.aclose()
    assert resp.result == []


@pytest.mark.asyncio
async def test_dispatch_uses_get_when_command_methods_says_so():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher(
        "http://t",
        client=client,
        command_methods={"equity.quote": "get"},
    )
    try:
        await d.dispatch(Request(command="equity.quote", params={"symbol": "AAPL"}))
    finally:
        await d.aclose()
    assert captured["method"] == "GET"
    assert "symbol=AAPL" in captured["url"]


@pytest.mark.asyncio
async def test_dispatch_falls_back_to_post_without_method_map():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher("http://t", client=client)
    try:
        await d.dispatch(Request(command="equity.quote", params={"symbol": "X"}))
    finally:
        await d.aclose()
    assert captured["method"] == "POST"


@pytest.mark.asyncio
async def test_dispatch_explicit_method_overrides_map():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher(
        "http://t",
        client=client,
        command_methods={"x": "post"},
    )
    try:
        await d.dispatch(Request(command="x"), method="get")
    finally:
        await d.aclose()
    assert captured["method"] == "GET"


def test_http_dispatcher_from_spec_extracts_methods():
    from openbb_cli.dispatchers.http import http_dispatcher_from_spec

    spec_doc = {
        "base_url": "http://h",
        "api_prefix": "/api/v1",
        "commands": {
            "equity.quote": {"method": "get"},
            "scratch.rebuild": {"method": "post"},
        },
    }
    d = http_dispatcher_from_spec(spec_doc)
    assert d._command_methods == {"equity.quote": "get", "scratch.rebuild": "post"}
    assert d._base_url == "http://h"


def test_http_dispatcher_from_server_fetches_and_maps(monkeypatch):
    """``http_dispatcher_from_server`` synthesizes a methods map from openapi.json."""
    from openbb_cli.dispatchers import http as http_mod

    fake_openapi = {
        "paths": {
            "/api/v1/x/y": {"get": {}},
            "/api/v1/foo/bar": {"post": {}},
            "/api/v1/skip": {"delete": {}},
        }
    }

    def fake_fetch(
        base_url, *, timeout=10.0, path=None, headers=None, query_params=None
    ):
        return fake_openapi

    monkeypatch.setattr(
        "openbb_cli.dispatchers.openapi_schema.fetch_openapi", fake_fetch
    )
    d = http_mod.http_dispatcher_from_server("http://h")
    assert d._command_methods == {"x.y": "get", "foo.bar": "post"}


@pytest.mark.asyncio
async def test_dispatch_sends_constructor_headers():
    """Headers passed at construction time go on every request."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    dispatcher = HttpDispatcher(
        "http://t",
        headers={"Authorization": "Bearer xyz", "X-Tenant": "acme"},
        client=httpx.AsyncClient(
            transport=transport,
            base_url="http://t",
            headers={"Authorization": "Bearer xyz", "X-Tenant": "acme"},
        ),
        command_methods={"x": "get"},
    )
    try:
        await dispatcher.dispatch(Request(command="x"))
    finally:
        await dispatcher.aclose()
    assert captured["headers"]["authorization"] == "Bearer xyz"
    assert captured["headers"]["x-tenant"] == "acme"


def test_http_dispatcher_owns_client_when_headers_passed():
    """No explicit client → dispatcher remembers headers + builds a fresh
    client per ``dispatch()`` call. We assert the bookkeeping; the actual
    header round-trip is covered by the ``handler``-based dispatch tests
    above which observe headers on the wire.
    """
    d = HttpDispatcher(
        "http://h",
        headers={"X-Foo": "bar"},
    )
    assert d._headers == {"X-Foo": "bar"}
    assert d._owns_client is True
    assert d._client is None


def test_http_dispatcher_from_spec_passes_headers():
    """``http_dispatcher_from_spec`` forwards headers to the dispatcher."""
    from openbb_cli.dispatchers.http import http_dispatcher_from_spec

    spec_doc = {
        "base_url": "http://h",
        "api_prefix": "/api/v1",
        "commands": {"foo": {"method": "get", "url_path": "/api/v1/foo"}},
    }
    d = http_dispatcher_from_spec(spec_doc, headers={"X-API-Key": "k"})
    assert d._headers == {"X-API-Key": "k"}


@pytest.mark.asyncio
async def test_dispatch_substitutes_path_params_into_url_template():
    """``{format}``-style placeholders are substituted from the request params."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher(
        "http://t",
        client=client,
        command_methods={"fxs.list.counterparties": "get"},
        command_url_paths={
            "fxs.list.counterparties": "/api/fxs/list/counterparties.{format}"
        },
    )
    try:
        await d.dispatch(
            Request(
                command="fxs.list.counterparties",
                params={"format": "json", "extra": "value"},
            )
        )
    finally:
        await d.aclose()
    assert "/api/fxs/list/counterparties.json" in captured["url"]
    assert "format=" not in captured["url"]
    assert "extra=value" in captured["url"]


@pytest.mark.asyncio
async def test_dispatch_keeps_placeholder_when_param_missing():
    """A missing path param leaves the placeholder so the server returns a clean error."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher(
        "http://t",
        client=client,
        command_methods={"x": "get"},
        command_url_paths={"x": "/api/x/{missing}"},
    )
    try:
        await d.dispatch(Request(command="x", params={}))
    finally:
        await d.aclose()
    assert "%7Bmissing%7D" in captured["url"] or "{missing}" in captured["url"]


@pytest.mark.asyncio
async def test_dispatch_picks_longest_satisfied_url_template():
    """When a command has multiple URL templates, pick the longest one whose placeholders are filled."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher(
        "http://t",
        client=client,
        command_methods={"x": "get"},
        command_url_paths={
            "x": [
                "/api/ratings/historical/{country}",
                "/api/ratings/historical/{country}/{d1}/{d2}",
            ]
        },
    )
    try:
        await d.dispatch(
            Request(
                command="x",
                params={"country": "USA", "d1": "2024-01-01", "d2": "2024-12-31"},
            )
        )
    finally:
        await d.aclose()
    assert "/api/ratings/historical/USA/2024-01-01/2024-12-31" in captured["url"]


@pytest.mark.asyncio
async def test_dispatch_falls_back_to_shorter_template_when_extras_missing():
    """When the longer template is missing extra path params, fall back to the shorter."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher(
        "http://t",
        client=client,
        command_methods={"x": "get"},
        command_url_paths={
            "x": [
                "/api/ratings/historical/{country}",
                "/api/ratings/historical/{country}/{d1}/{d2}",
            ]
        },
    )
    try:
        await d.dispatch(Request(command="x", params={"country": "USA"}))
    finally:
        await d.aclose()
    assert "/api/ratings/historical/USA" in captured["url"]
    assert "{d1}" not in captured["url"]
    assert "%7Bd1%7D" not in captured["url"]


@pytest.mark.asyncio
async def test_dispatch_falls_back_to_no_placeholder_template_when_path_params_missing():
    """When no path params are supplied, a placeholder-free template still wins."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher(
        "http://t",
        client=client,
        command_methods={"x": "get"},
        command_url_paths={"x": ["/api/ratings", "/api/ratings/{country}"]},
    )
    try:
        await d.dispatch(Request(command="x", params={}))
    finally:
        await d.aclose()
    assert captured["url"].endswith("/api/ratings")


def test_http_dispatcher_from_spec_uses_url_templates_when_present():
    """The spec-doc factory routes ``url_templates`` through to the dispatcher."""
    from openbb_cli.dispatchers.http import http_dispatcher_from_spec

    spec_doc = {
        "base_url": "http://h",
        "api_prefix": "/api/v1",
        "commands": {
            "x": {
                "method": "get",
                "url_path": "/api/x",
                "url_templates": ["/api/x", "/api/x/{id}"],
            }
        },
    }
    d = http_dispatcher_from_spec(spec_doc)
    assert d._command_url_paths["x"] == ["/api/x", "/api/x/{id}"]


@pytest.mark.asyncio
async def test_dispatch_invokes_sync_auth_hook_and_merges_headers():
    """Sync hook returning headers/query gets merged into the request."""
    from openbb_cli.auth import AuthContext, AuthDecision

    captured: dict[str, object] = {}
    seen: list[AuthContext] = []

    def hook(ctx):
        seen.append(ctx)
        return AuthDecision(headers={"X-User": "alice"}, query_params={"trace": "1"})

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["url"] = str(request.url)
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    d = HttpDispatcher(
        "http://test",
        client=client,
        command_methods={"foo": "get"},
        auth_hook=hook,
        namespace="ns1",
    )
    try:
        resp = await d.dispatch(Request(command="foo", params={"a": 1}))
    finally:
        await d.aclose()
    assert resp.ok
    assert captured["headers"]["x-user"] == "alice"
    assert "trace=1" in captured["url"]
    assert seen[0].namespace == "ns1"
    assert seen[0].command == "foo"
    assert seen[0].params == {"a": 1}


@pytest.mark.asyncio
async def test_dispatch_supports_async_auth_hook():
    """Awaited coroutine hooks work the same as sync ones."""
    from openbb_cli.auth import AuthDecision

    async def hook(ctx):
        return AuthDecision(headers={"X-Async": "yes"})

    captured: dict[str, dict[str, str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["h"] = dict(request.headers)
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    d = HttpDispatcher(
        "http://test",
        client=client,
        command_methods={"foo": "get"},
        auth_hook=hook,
    )
    try:
        await d.dispatch(Request(command="foo"))
    finally:
        await d.aclose()
    assert captured["h"]["x-async"] == "yes"


@pytest.mark.asyncio
async def test_dispatch_auth_hook_deny_short_circuits():
    """``allow=False`` produces an AccessDenied error and skips the network call."""
    from openbb_cli.auth import AuthDecision

    network_calls: list[str] = []

    def hook(ctx):
        return AuthDecision(allow=False, deny_reason="role too low")

    def handler(request: httpx.Request) -> httpx.Response:
        network_calls.append(str(request.url))
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    d = HttpDispatcher("http://test", client=client, auth_hook=hook)
    try:
        resp = await d.dispatch(Request(command="x"))
    finally:
        await d.aclose()
    assert not resp.ok
    assert resp.error.type == "AccessDenied"
    assert "role too low" in resp.error.message
    assert network_calls == []


@pytest.mark.asyncio
async def test_dispatch_auth_hook_raises_becomes_deny():
    """A raising hook becomes an ``AccessDenied`` response, not a crash."""

    def hook(ctx):
        raise RuntimeError("vault unreachable")

    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    d = HttpDispatcher("http://test", client=client, auth_hook=hook)
    try:
        resp = await d.dispatch(Request(command="x"))
    finally:
        await d.aclose()
    assert not resp.ok
    assert resp.error.type == "AccessDenied"
    assert "vault unreachable" in resp.error.message


@pytest.mark.asyncio
async def test_dispatch_auth_hook_wrong_return_type_denies():
    """A hook returning the wrong shape is treated as a deny, not silent ok."""

    def hook(ctx):
        return {"headers": {"x": "1"}}  # not an AuthDecision

    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    d = HttpDispatcher("http://test", client=client, auth_hook=hook)
    try:
        resp = await d.dispatch(Request(command="x"))
    finally:
        await d.aclose()
    assert not resp.ok
    assert resp.error.type == "AccessDenied"
    assert "expected AuthDecision" in resp.error.message


@pytest.mark.asyncio
async def test_list_commands_filters_out_denied_entries():
    """``__commands__`` runs the auth hook for each command; deny → drop."""
    from openbb_cli.auth import AuthDecision

    def hook(ctx):
        # Only allow ``allowed.cmd``
        if ctx.command == "allowed.cmd":
            return AuthDecision()
        return AuthDecision(allow=False, deny_reason="rbac")

    d = HttpDispatcher(
        "http://test",
        spec_doc={
            "commands": {
                "allowed.cmd": {"description": "Visible."},
                "denied.cmd": {"description": "Hidden."},
            }
        },
        auth_hook=hook,
    )
    resp = await d.dispatch(Request(command="__commands__"))
    assert resp.ok
    names = [r["name"] for r in resp.result]
    assert names == ["allowed.cmd"]


@pytest.mark.asyncio
async def test_describe_denied_returns_access_denied():
    """``__schema__`` for a denied command returns ``AccessDenied``."""
    from openbb_cli.auth import AuthDecision

    d = HttpDispatcher(
        "http://test",
        spec_doc={
            "commands": {
                "secret.thing": {
                    "description": "Hidden.",
                    "parameters": [],
                    "providers": [],
                    "request_body_schema": None,
                    "response_schema": None,
                }
            }
        },
        auth_hook=lambda ctx: AuthDecision(allow=False, deny_reason="rbac"),
    )
    resp = await d.dispatch(
        Request(command="__schema__", params={"name": "secret.thing"})
    )
    assert not resp.ok
    assert resp.error.type == "AccessDenied"
    assert "rbac" in resp.error.message


@pytest.mark.asyncio
async def test_describe_returns_slim_shape_for_non_multi_provider():
    """Single-provider commands get the flat ``{name, parameters, output_schema}``."""
    d = HttpDispatcher(
        "http://test",
        spec_doc={
            "commands": {
                "foo": {
                    "description": "F",
                    "parameters": [
                        {
                            "name": "x",
                            "in": "query",
                            "type": "string",
                            "is_list": False,
                            "required": True,
                            "default": None,
                            "choices": [],
                            "help": None,
                            "providers": [],
                        }
                    ],
                    "providers": [],
                    "request_body_schema": None,
                    "response_schema": {"type": "object"},
                }
            }
        },
    )
    resp = await d._describe_command(
        Request(command="__schema__", params={"name": "foo"})
    )
    assert resp.ok
    assert set(resp.result) == {"name", "parameters", "output_schema"}
    p = resp.result["parameters"][0]
    # Empty/falsy fields stripped
    assert "is_list" not in p
    assert "default" not in p
    assert "choices" not in p
    assert "help" not in p
    assert p["required"] is True


@pytest.mark.asyncio
async def test_describe_groups_by_provider_when_present():
    """Multi-provider commands return ``{name, providers: {ns: {...}, ...}}``."""
    d = HttpDispatcher(
        "http://test",
        spec_doc={
            "commands": {
                "q": {
                    "description": "Q",
                    "parameters": [
                        {
                            "name": "symbol",
                            "in": "query",
                            "type": "string",
                            "required": True,
                            "providers": [],
                        },
                        {
                            "name": "use_cache",
                            "in": "query",
                            "type": "boolean",
                            "providers": ["cboe"],
                        },
                        {
                            "name": "source",
                            "in": "query",
                            "type": "string",
                            "providers": ["intrinio"],
                        },
                    ],
                    "providers": ["cboe", "intrinio"],
                    "request_body_schema": None,
                    "response_schema": None,
                }
            }
        },
    )
    resp = await d._describe_command(
        Request(command="__schema__", params={"name": "q"})
    )
    assert resp.ok
    by = resp.result["providers"]
    assert set(by) == {"cboe", "intrinio"}
    cboe_params = [p["name"] for p in by["cboe"]["parameters"]]
    intrinio_params = [p["name"] for p in by["intrinio"]["parameters"]]
    assert cboe_params == ["symbol", "use_cache"]
    assert intrinio_params == ["symbol", "source"]


@pytest.mark.asyncio
async def test_describe_with_provider_suffix_returns_single_slice():
    """Passing ``provider`` narrows the output to that provider's slice."""
    d = HttpDispatcher(
        "http://test",
        spec_doc={
            "commands": {
                "q": {
                    "description": "Q",
                    "parameters": [
                        {
                            "name": "symbol",
                            "in": "query",
                            "type": "string",
                            "required": True,
                            "providers": [],
                        },
                        {
                            "name": "source",
                            "in": "query",
                            "type": "string",
                            "providers": ["intrinio"],
                        },
                    ],
                    "providers": ["cboe", "intrinio"],
                    "request_body_schema": None,
                    "response_schema": None,
                }
            }
        },
    )
    resp = await d._describe_command(
        Request(command="__schema__", params={"name": "q", "provider": "intrinio"})
    )
    assert resp.ok
    assert resp.result["provider"] == "intrinio"
    assert set(resp.result) == {"name", "provider", "parameters", "output_schema"}
    names = [p["name"] for p in resp.result["parameters"]]
    assert names == ["symbol", "source"]


@pytest.mark.asyncio
async def test_describe_unknown_provider_returns_error():
    d = HttpDispatcher(
        "http://test",
        spec_doc={
            "commands": {
                "q": {
                    "description": "Q",
                    "parameters": [],
                    "providers": ["cboe"],
                    "request_body_schema": None,
                    "response_schema": None,
                }
            }
        },
    )
    resp = await d._describe_command(
        Request(command="__schema__", params={"name": "q", "provider": "bogus"})
    )
    assert not resp.ok
    assert resp.error.type == "UnknownProvider"
    assert "Available: cboe" in resp.error.message


def test_help_for_provider_keeps_only_relevant_sections():
    """Per-provider help filtering: drops ``(provider: X)`` blocks for other providers."""
    from openbb_cli.dispatchers.http import _help_for_provider

    text = (
        "Shared header for everyone.;\n    "
        "FMP says hi. (provider: fmp);\n    "
        "Intrinio says hi. (provider: intrinio)"
    )
    assert _help_for_provider(text, "fmp") == (
        "Shared header for everyone.\nFMP says hi."
    )
    assert _help_for_provider(text, "intrinio") == (
        "Shared header for everyone.\nIntrinio says hi."
    )


def test_help_for_provider_returns_none_when_nothing_applies():
    from openbb_cli.dispatchers.http import _help_for_provider

    text = "Only for cboe. (provider: cboe)"
    assert _help_for_provider(text, "fmp") is None


def test_help_for_provider_passthrough_for_empty():
    from openbb_cli.dispatchers.http import _help_for_provider

    assert _help_for_provider(None, "fmp") is None
    assert _help_for_provider("", "fmp") == ""


def test_provider_output_schema_picks_matching_variant():
    """``IntrinioEquityQuoteData`` matches provider ``intrinio`` by case-insensitive prefix."""
    from openbb_cli.dispatchers.http import _provider_output_schema

    schema = {
        "properties": {
            "results": {
                "anyOf": [
                    {
                        "items": {
                            "oneOf": [
                                {"title": "IntrinioEquityQuoteData", "type": "object"},
                                {"title": "FMPEquityQuoteData", "type": "object"},
                            ]
                        },
                        "type": "array",
                    },
                    {"type": "null"},
                ]
            }
        }
    }
    intrinio = _provider_output_schema(schema, "intrinio")
    assert intrinio is not None
    assert intrinio["title"] == "IntrinioEquityQuoteData"


def test_provider_output_schema_handles_non_array_results():
    """Single-record results with a top-level ``oneOf`` work the same way."""
    from openbb_cli.dispatchers.http import _provider_output_schema

    schema = {
        "properties": {
            "results": {
                "oneOf": [
                    {"title": "IntrinioFoo", "type": "object"},
                    {"title": "FMPFoo", "type": "object"},
                ]
            }
        }
    }
    out = _provider_output_schema(schema, "fmp")
    assert out is not None
    assert out["title"] == "FMPFoo"


def test_provider_output_schema_returns_none_for_invalid_input():
    from openbb_cli.dispatchers.http import _provider_output_schema

    assert _provider_output_schema(None, "fmp") is None
    assert _provider_output_schema({}, "fmp") is None


def test_http_dispatcher_from_server_passes_headers(monkeypatch):
    """``http_dispatcher_from_server`` forwards headers to both fetch and dispatcher."""
    from openbb_cli.dispatchers import http as http_mod

    captured: dict[str, dict[str, str] | None] = {}

    def fake_fetch(
        base_url, *, timeout=10.0, path=None, headers=None, query_params=None
    ):
        captured["headers"] = headers
        return {"paths": {"/api/v1/x": {"get": {}}}}

    monkeypatch.setattr(
        "openbb_cli.dispatchers.openapi_schema.fetch_openapi", fake_fetch
    )
    d = http_mod.http_dispatcher_from_server(
        "http://h", headers={"Authorization": "Bearer abc"}
    )
    assert captured["headers"] == {"Authorization": "Bearer abc"}
    assert d._headers == {"Authorization": "Bearer abc"}


@pytest.mark.asyncio
async def test_describe_missing_name_returns_error():
    """``__schema__`` without ``--name`` returns a structured error."""
    d = HttpDispatcher("http://test", spec_doc={"commands": {}})
    resp = await d._describe_command(Request(command="__schema__", params={}))
    assert not resp.ok
    assert resp.error.type == "MissingParameter"
    assert "--name" in resp.error.message


@pytest.mark.asyncio
async def test_describe_unknown_command_returns_error():
    """Asking for a command that isn't in the spec returns ``UnknownCommand``."""
    d = HttpDispatcher("http://test", spec_doc={"commands": {"a": {}}})
    resp = await d._describe_command(
        Request(command="__schema__", params={"name": "missing.cmd"})
    )
    assert not resp.ok
    assert resp.error.type == "UnknownCommand"
    assert "missing.cmd" in resp.error.message


# --- _slim_param branch coverage ---


def test_slim_param_drops_empty_choices_and_default_zero():
    """Falsy fields (empty choices, missing default) are stripped."""
    from openbb_cli.dispatchers.http import _slim_param

    out = _slim_param(
        {
            "name": "x",
            "in": "query",
            "type": "integer",
            "is_list": False,
            "required": False,
            "default": None,
            "choices": [],
            "help": None,
        }
    )
    assert out == {"name": "x", "in": "query", "type": "integer"}


def test_slim_param_keeps_default_zero():
    """``default=0`` is meaningful — must NOT be stripped (only None is)."""
    from openbb_cli.dispatchers.http import _slim_param

    out = _slim_param({"name": "x", "in": "query", "type": "integer", "default": 0})
    assert out["default"] == 0


def test_slim_param_keeps_choices_and_help_when_set():
    from openbb_cli.dispatchers.http import _slim_param

    out = _slim_param(
        {
            "name": "x",
            "in": "query",
            "type": "string",
            "choices": ["a", "b"],
            "help": "pick",
        }
    )
    assert out["choices"] == ["a", "b"]
    assert out["help"] == "pick"


def test_slim_param_keeps_json_arg_flag():
    """A non-scalar body field carries its ``json_arg`` flag through ``--describe``."""
    from openbb_cli.dispatchers.http import _slim_param

    out = _slim_param(
        {"name": "data", "in": "body", "type": "string", "json_arg": True}
    )
    assert out["json_arg"] is True


def test_partition_params_splits_query_and_body_by_in_tag():
    """POST params split by ``in`` tag: query-tagged to the query string, rest to body."""
    spec_doc = {
        "commands": {
            "x.y": {
                "parameters": [{"name": "fmt", "in": "query", "type": "string"}],
                "request_body_schema": {
                    "type": "object",
                    "properties": {
                        "data": {"type": "array", "items": {"type": "object"}}
                    },
                },
            }
        }
    }
    d = HttpDispatcher("http://t", spec_doc=spec_doc)
    query, body, headers = d._partition_params(
        "x.y", {"fmt": "json", "data": [1], "extra": 9}
    )
    assert query == {"fmt": "json"}
    assert body == {"data": [1], "extra": 9}
    assert headers == {}


def test_partition_params_surfaces_header_tagged_params():
    """Params tagged ``in: header`` are routed to the headers map, not query/body."""
    spec_doc = {
        "commands": {
            "x.y": {
                "parameters": [
                    {"name": "x-api-key", "in": "header", "type": "string"},
                    {"name": "fmt", "in": "query", "type": "string"},
                ],
            }
        }
    }
    d = HttpDispatcher("http://t", spec_doc=spec_doc)
    query, body, headers = d._partition_params(
        "x.y", {"x_api_key": "secret", "fmt": "json", "payload": 1}
    )
    assert query == {"fmt": "json"}
    assert body == {"payload": 1}
    assert headers == {"x-api-key": "secret"}


def test_partition_params_drops_none_header_value():
    """A header-tagged param with a ``None`` value is omitted from headers."""
    spec_doc = {
        "commands": {
            "x.y": {
                "parameters": [{"name": "x-api-key", "in": "header", "type": "string"}],
            }
        }
    }
    d = HttpDispatcher("http://t", spec_doc=spec_doc)
    _query, _body, headers = d._partition_params("x.y", {"x_api_key": None})
    assert headers == {}


# --- streaming (SSE) ---


def test_is_streaming_command_detects_event_stream():
    spec_doc = {
        "commands": {
            "x.feed": {"response_schemas": {"200": {"text/event-stream": {}}}},
            "x.plain": {"response_schemas": {"200": {"application/json": {}}}},
        }
    }
    d = HttpDispatcher("http://t", spec_doc=spec_doc)
    assert d._is_streaming_command("x.feed") is True
    assert d._is_streaming_command("x.plain") is False
    assert d._is_streaming_command("missing") is False


@pytest.mark.asyncio
async def test_dispatch_streaming_get_returns_obbstream():
    from openbb_core.app.model.stream import OBBStream

    spec_doc = {
        "commands": {
            "x.feed": {
                "method": "get",
                "response_schemas": {"200": {"text/event-stream": {}}},
            }
        }
    }
    d = HttpDispatcher("http://t", spec_doc=spec_doc, command_methods={"x.feed": "get"})
    resp = await d.dispatch(Request(command="x.feed", params={"limit": 2}))
    await d.aclose()
    assert resp.ok
    assert isinstance(resp.result, OBBStream)


@pytest.mark.asyncio
async def test_dispatch_streaming_post_returns_obbstream():
    from openbb_core.app.model.stream import OBBStream

    spec_doc = {
        "commands": {
            "x.feed": {
                "method": "post",
                "response_schemas": {"200": {"text/event-stream": {}}},
                "request_body_schema": {
                    "type": "object",
                    "properties": {"data": {"type": "array"}},
                },
            }
        }
    }
    d = HttpDispatcher(
        "http://t", spec_doc=spec_doc, command_methods={"x.feed": "post"}
    )
    resp = await d.dispatch(Request(command="x.feed", params={"data": [1]}))
    await d.aclose()
    assert resp.ok
    assert isinstance(resp.result, OBBStream)


@pytest.mark.asyncio
async def test_http_sse_source_iterates_get(monkeypatch):
    import openbb_cli.dispatchers.http as http_mod
    from openbb_cli.dispatchers.http import _HttpSSESource

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        return httpx.Response(200, text="data: 0\n\ndata: 1\n")

    real_client = httpx.AsyncClient

    def make_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(http_mod.httpx, "AsyncClient", make_client)
    source = _HttpSSESource("http://t/feed", {"limit": 2}, None, "get", None)
    lines = [line async for line in source.body_iterator]
    assert captured["method"] == "GET"
    assert "limit=2" in captured["url"]
    assert any("data: 0" in line for line in lines)


@pytest.mark.asyncio
async def test_http_sse_source_iterates_post_with_body(monkeypatch):
    import openbb_cli.dispatchers.http as http_mod
    from openbb_cli.dispatchers.http import _HttpSSESource

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["body"] = request.content.decode()
        return httpx.Response(200, text="data: 0\n")

    real_client = httpx.AsyncClient

    def make_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(http_mod.httpx, "AsyncClient", make_client)
    source = _HttpSSESource("http://t/feed", None, None, "post", {"data": [1]})
    lines = [line async for line in source.body_iterator]
    assert captured["method"] == "POST"
    assert "data" in captured["body"]
    assert any("data: 0" in line for line in lines)


@pytest.mark.asyncio
async def test_http_sse_source_consumes_warning_header(monkeypatch):
    import json as _json

    from openbb_core.app.model.abstract.warning import OpenBBWarning

    import openbb_cli.dispatchers.http as http_mod
    from openbb_cli.dispatchers.http import _HttpSSESource

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="data: 0\n",
            headers={
                "X-OpenBB-Provider": "fmp",
                "X-OpenBB-Warning": _json.dumps(
                    [{"category": "OpenBBWarning", "message": "heads up"}]
                ),
            },
        )

    real_client = httpx.AsyncClient

    def make_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(http_mod.httpx, "AsyncClient", make_client)
    source = _HttpSSESource("http://t/feed", None, None, "get", None)
    with pytest.warns(OpenBBWarning, match="heads up"):
        _lines = [line async for line in source.body_iterator]
    assert source.provider == "fmp"
    assert source.warnings is not None
    assert source.warnings[0]["message"] == "heads up"


@pytest.mark.asyncio
async def test_http_sse_source_ignores_malformed_warning_header(monkeypatch):
    import openbb_cli.dispatchers.http as http_mod
    from openbb_cli.dispatchers.http import _HttpSSESource

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text="data: 0\n", headers={"X-OpenBB-Warning": "not-json"}
        )

    real_client = httpx.AsyncClient

    def make_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(http_mod.httpx, "AsyncClient", make_client)
    source = _HttpSSESource("http://t/feed", None, None, "get", None)
    _lines = [line async for line in source.body_iterator]
    assert source.warnings is None


# --- _help_for_provider edge: empty section ---


def test_help_for_provider_skips_empty_sections_between_separators():
    from openbb_cli.dispatchers.http import _help_for_provider

    text = "shared.;\n    ;\n    Foo. (provider: fmp)"
    out = _help_for_provider(text, "fmp")
    assert out == "shared.\nFoo."


# --- _provider_output_schema edges ---


def test_provider_output_schema_returns_none_when_results_field_absent():
    from openbb_cli.dispatchers.http import _provider_output_schema

    schema = {"properties": {}}
    assert _provider_output_schema(schema, "fmp") is None


def test_provider_output_schema_skips_unmatched_titles():
    """When no oneOf variant matches the provider, return None (not arbitrary first)."""
    from openbb_cli.dispatchers.http import _provider_output_schema

    schema = {
        "properties": {
            "results": {
                "anyOf": [
                    {
                        "items": {
                            "oneOf": [
                                {"title": "AlphaData", "type": "object"},
                                {"title": "BetaData", "type": "object"},
                            ]
                        },
                        "type": "array",
                    },
                    {"type": "null"},
                ]
            }
        }
    }
    assert _provider_output_schema(schema, "gamma") is None


def test_provider_output_schema_skips_non_dict_oneof_entries():
    from openbb_cli.dispatchers.http import _provider_output_schema

    schema = {
        "properties": {
            "results": {"oneOf": ["not-a-dict", {"title": "FMPx", "type": "object"}]}
        }
    }
    out = _provider_output_schema(schema, "fmp")
    assert out is not None
    assert out["title"] == "FMPx"


# --- _decode_response branches ---


def test_decode_response_text_for_xml_content_type():
    """Non-JSON content type returns the raw text body."""
    from openbb_cli.dispatchers.http import _decode_response

    response = httpx.Response(
        200, text="<root>x</root>", headers={"content-type": "application/xml"}
    )
    assert _decode_response(response) == "<root>x</root>"


def test_decode_response_falls_back_to_text_when_json_invalid():
    """JSON content type with a body that won't parse falls back to text."""
    from openbb_cli.dispatchers.http import _decode_response

    response = httpx.Response(
        200, text="not json", headers={"content-type": "application/json"}
    )
    assert _decode_response(response) == "not json"


def test_decode_response_no_content_type_attempts_json():
    """Empty content type defaults to JSON parsing."""
    from openbb_cli.dispatchers.http import _decode_response

    response = httpx.Response(200, text='{"a": 1}', headers={"content-type": ""})
    assert _decode_response(response) == {"a": 1}


# --- _client_context external client branch ---


@pytest.mark.asyncio
async def test_client_context_yields_external_client_when_not_owned():
    """External clients are yielded as-is, not closed by the dispatcher."""
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    external = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher("http://t", client=external)
    async with d._client_context() as c:
        assert c is external
    # Not closed
    response = await external.get("http://t/")
    assert response.status_code == 200
    await external.aclose()


def test_slim_param_keeps_is_list_when_true():
    """``is_list: True`` lands in the slim output."""
    from openbb_cli.dispatchers.http import _slim_param

    out = _slim_param({"name": "x", "in": "query", "type": "string", "is_list": True})
    assert out["is_list"] is True


def test_provider_output_schema_falls_back_to_only_candidate_with_no_title_match():
    """Single candidate that doesn't title-match the provider is returned anyway."""
    from openbb_cli.dispatchers.http import _provider_output_schema

    schema = {
        "properties": {
            "results": {
                "anyOf": [
                    {"oneOf": [{"title": "GenericData", "type": "object"}]},
                    {"type": "null"},
                ]
            }
        }
    }
    out = _provider_output_schema(schema, "fmp")
    assert out is not None
    assert out["title"] == "GenericData"


@pytest.mark.asyncio
async def test_dispatch_routes_list_commands_through_dispatch():
    """``dispatch(Request(command="__commands__"))`` reaches the introspection path."""
    d = HttpDispatcher(
        "http://test",
        spec_doc={"commands": {"foo": {"description": "F"}}},
    )
    resp = await d.dispatch(Request(command="__commands__"))
    assert resp.ok
    assert resp.result == [{"name": "foo", "description": "F"}]


@pytest.mark.asyncio
async def test_dispatch_routes_describe_through_dispatch():
    """``dispatch(Request(command="__schema__"))`` reaches ``_describe_command``."""
    d = HttpDispatcher(
        "http://test",
        spec_doc={
            "commands": {
                "foo": {
                    "description": "F",
                    "parameters": [],
                    "providers": [],
                    "request_body_schema": None,
                    "response_schema": None,
                }
            }
        },
    )
    resp = await d.dispatch(Request(command="__schema__", params={"name": "foo"}))
    assert resp.ok
    assert resp.result["name"] == "foo"


def test_group_by_provider_skips_provider_discriminator():
    """The ``provider`` flag itself is filtered out per-provider — already implicit."""
    from openbb_cli.dispatchers.http import _group_by_provider

    raw_params = [
        {"name": "provider", "type": "string", "providers": []},
        {"name": "symbol", "type": "string", "providers": []},
    ]
    grouped = _group_by_provider(raw_params, ["cboe"], None)
    names = [p["name"] for p in grouped["cboe"]["parameters"]]
    assert names == ["symbol"]  # ``provider`` itself dropped


@pytest.mark.asyncio
async def test_dispatch_with_owned_client_uses_fresh_async_client(monkeypatch):
    """An owned client (no ``client=`` arg) takes the ``owns`` branch in ``_client_context``,
    constructing a fresh ``httpx.AsyncClient`` per dispatch.
    """
    constructed: list[bool] = []
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True}))
    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        constructed.append(True)
        kwargs.pop("transport", None)
        return real_async_client(*args, transport=transport, **kwargs)

    from openbb_cli.dispatchers import http as http_mod

    monkeypatch.setattr(http_mod.httpx, "AsyncClient", factory)
    d = HttpDispatcher("http://t", command_methods={"foo": "get"})
    resp = await d.dispatch(Request(command="foo"))
    assert resp.ok
    assert constructed == [True]


def test_row_column_metadata_extracts_description_format_and_socrata_format():
    """``_row_column_metadata`` mirrors codegen's metadata extraction."""
    from openbb_cli.dispatchers.http import _row_column_metadata

    cmd_spec = {
        "response_schema": {
            "properties": {
                "results": {
                    "items": {
                        "properties": {
                            "price": {
                                "type": "number",
                                "description": "Price, measured in dollars per ton",
                                "socrata_format": {"precisionStyle": "standard"},
                            },
                            "obs_date": {"type": "string", "format": "date"},
                            "raw_id": {"type": "string"},
                        }
                    }
                }
            }
        }
    }
    out = _row_column_metadata(cmd_spec)
    assert out == {
        "price": {
            "description": "Price, measured in dollars per ton",
            "socrata_format": {"precisionStyle": "standard"},
        },
        "obs_date": {"format": "date"},
    }


def test_row_column_metadata_returns_empty_when_schema_absent():
    """No ``response_schema`` → empty dict, no error."""
    from openbb_cli.dispatchers.http import _row_column_metadata

    assert _row_column_metadata({}) == {}
    assert _row_column_metadata({"response_schema": None}) == {}
    assert _row_column_metadata({"response_schema": {"type": "object"}}) == {}


@pytest.mark.asyncio
async def test_dispatch_injects_column_metadata_into_results_envelope():
    """Spec-mode dispatch surfaces column metadata under ``metadata.columns``.

    Mirrors what the installed-extension fetcher embeds in
    ``AnnotatedResult.metadata['columns']`` so spec-mode and codegen
    paths look identical to downstream consumers (e.g. the OBBject
    ``extra['results_metadata']`` surface).
    """
    spec_doc = {
        "commands": {
            "ag.prices": {
                "method": "get",
                "response_schema": {
                    "properties": {
                        "results": {
                            "items": {
                                "properties": {
                                    "price": {
                                        "type": "number",
                                        "description": "Price in $/ton",
                                        "socrata_format": {"noCommas": "true"},
                                    },
                                    "obs_date": {
                                        "type": "string",
                                        "format": "date",
                                    },
                                }
                            }
                        }
                    }
                },
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"price": "12.5", "obs_date": "2026-04-30T00:00:00.000"},
                {"price": "13.0", "obs_date": "2026-04-23T00:00:00.000"},
            ],
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher("http://t", client=client, spec_doc=spec_doc)
    try:
        resp = await d.dispatch(Request(command="ag.prices"))
    finally:
        await d.aclose()
    assert resp.ok
    # Dispatcher returns a live OBBject instance (not a dict) — the
    # registry can register it directly and JSON serialization still
    # works through pydantic's recursive model_dump.
    from openbb_core.app.model.obbject import OBBject

    assert isinstance(resp.result, OBBject)
    # Rows coerced (numeric strings → numbers, date timestamps → date).
    assert resp.result.results == [
        {"price": 12.5, "obs_date": "2026-04-30"},
        {"price": 13.0, "obs_date": "2026-04-23"},
    ]
    # Column metadata under extra.results_metadata.columns — same path
    # the installed-extension AnnotatedResult flow produces.
    assert resp.result.extra["results_metadata"]["columns"] == {
        "price": {
            "description": "Price in $/ton",
            "socrata_format": {"noCommas": "true"},
        },
        "obs_date": {"format": "date"},
    }
    # Standard OBBject fields are all defaulted.
    assert resp.result.provider is None
    assert resp.result.warnings is None
    assert resp.result.chart is None
    assert resp.result.id  # Tagged base class auto-generates this
    # Route lives where it canonically belongs — extra.metadata.route —
    # not duplicated as a synthetic top-level attr.
    assert resp.result.extra["metadata"].route == "/ag/prices"
    # ``metadata`` is never a top-level OBBject property.
    dumped = resp.result.model_dump()
    assert "metadata" not in dumped


@pytest.mark.asyncio
async def test_dispatch_skips_metadata_envelope_when_schema_has_none():
    """No metadata in schema → no metadata envelope added; raw shape preserved."""
    spec_doc = {
        "commands": {
            "x": {
                "method": "get",
                "response_schema": {
                    "properties": {
                        "results": {"items": {"properties": {"id": {"type": "string"}}}}
                    }
                },
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": "a"}, {"id": "b"}])

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher("http://t", client=client, spec_doc=spec_doc)
    try:
        resp = await d.dispatch(Request(command="x"))
    finally:
        await d.aclose()
    assert resp.ok
    # No description / format / socrata_format in the schema → flat list,
    # no synthetic metadata envelope.
    assert resp.result == [{"id": "a"}, {"id": "b"}]


@pytest.mark.asyncio
async def test_dispatch_attaches_execution_metadata_to_obbject():
    """Spec-mode wraps in an OBBject AND attaches command_runner-style execution
    metadata under ``extra['metadata']`` — route, arguments, duration, timestamp.

    Without this, downstream registries / loggers can't tell what was
    called, with what args, or how long it took. Mirrors what
    ``StaticCommandRunner`` writes when ``preferences.metadata`` is on.
    """
    spec_doc = {
        "commands": {
            "ag.fertilizer_prices_by_region": {
                "method": "get",
                "response_schema": {
                    "properties": {
                        "results": {
                            "items": {
                                "properties": {
                                    "price": {
                                        "type": "number",
                                        "description": "Price in $/ton",
                                    }
                                }
                            }
                        }
                    }
                },
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"price": 12.5}])

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher("http://t", client=client, spec_doc=spec_doc)
    try:
        resp = await d.dispatch(
            Request(
                command="ag.fertilizer_prices_by_region",
                params={"region": "Cornbelt", "limit": 1},
            )
        )
    finally:
        await d.aclose()
    assert resp.ok
    meta = resp.result.extra["metadata"]
    # Route uses slash form, mirroring command_runner's convention.
    assert meta.route == "/ag/fertilizer_prices_by_region"
    # Arguments organized into the canonical three-key shape.
    assert meta.arguments == {
        "provider_choices": {},
        "standard_params": {"region": "Cornbelt", "limit": 1},
        "extra_params": {},
    }
    # Duration is a positive integer (nanoseconds).
    assert isinstance(meta.duration, int) and meta.duration > 0
    # Timestamp captured.
    assert meta.timestamp is not None
    # ``metadata`` is not a top-level OBBject property — only at extra.metadata.
    dumped = resp.result.model_dump()
    assert "metadata" not in dumped
    assert dumped["extra"]["metadata"]["arguments"]["standard_params"] == {
        "region": "Cornbelt",
        "limit": 1,
    }


@pytest.mark.asyncio
async def test_dispatch_keeps_api_siblings_separate_from_results_metadata():
    """API-level sibling fields (NY-Fed ``asOfDate``) and per-column
    descriptions are *distinct* concepts and ride at distinct keys —
    sibling fields land directly under ``extra`` (their own key),
    column hints land under ``extra.results_metadata.columns``. Folding
    them together would lie about what each piece of data describes.
    """
    spec_doc = {
        "commands": {
            "ops.list": {
                "method": "get",
                "response_schema": {
                    "properties": {
                        "results": {
                            "items": {
                                "properties": {
                                    "id": {
                                        "type": "string",
                                        "description": "Operation ID",
                                    }
                                }
                            }
                        }
                    }
                },
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"asOfDate": "2026-04-30", "operations": [{"id": "a"}, {"id": "b"}]},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher("http://t", client=client, spec_doc=spec_doc)
    try:
        resp = await d.dispatch(Request(command="ops.list"))
    finally:
        await d.aclose()
    assert resp.ok
    assert resp.result.results == [{"id": "a"}, {"id": "b"}]
    # Per-column metadata stays in ``results_metadata.columns``.
    assert resp.result.extra["results_metadata"]["columns"] == {
        "id": {"description": "Operation ID"}
    }
    # API sibling field at its own top-level extra key — never folded
    # into ``results_metadata`` (different concept).
    assert resp.result.extra["asOfDate"] == "2026-04-30"
    assert "asOfDate" not in resp.result.extra["results_metadata"]


# --- Regression coverage for the OBBject-wrap edge cases ---


def test_is_plotly_figure_recognizes_canonical_shape():
    """A real Plotly figure dict (``data`` list of typed traces +
    ``layout`` dict) trips the detector — without this guard the generic
    unpack would tear the figure apart."""
    from openbb_cli.dispatchers.http import _is_plotly_figure

    fig = {
        "data": [
            {"type": "scattergeo", "lat": [0], "lon": [0]},
            {"type": "scatter", "x": [1, 2], "y": [3, 4]},
        ],
        "layout": {"title": "Map"},
    }
    assert _is_plotly_figure(fig) is True


def test_is_plotly_figure_rejects_lookalikes():
    """Conservative: random ``{data, layout}`` payloads from APIs that
    happen to share the key names but aren't Plotly figures don't
    trigger the chart wrap."""
    from openbb_cli.dispatchers.http import _is_plotly_figure

    # Not a dict.
    assert _is_plotly_figure([{"data": [], "layout": {}}]) is False
    # Missing ``layout``.
    assert _is_plotly_figure({"data": [{"type": "scatter"}]}) is False
    # ``layout`` not a dict.
    assert _is_plotly_figure({"data": [{"type": "scatter"}], "layout": []}) is False
    # ``data`` not a list.
    assert _is_plotly_figure({"data": {"type": "scatter"}, "layout": {}}) is False
    # Empty ``data``.
    assert _is_plotly_figure({"data": [], "layout": {"x": 1}}) is False
    # ``data`` items don't carry a ``type`` (look like generic rows).
    assert _is_plotly_figure({"data": [{"x": 1}], "layout": {"y": 2}}) is False


@pytest.mark.asyncio
async def test_dispatch_routes_plotly_figure_payload_to_obbject_chart():
    """A Plotly-figure-shaped server response lands at
    ``OBBject.chart.content`` with ``format="plotly"`` — preserves the
    full figure structure (data + layout) instead of letting the
    generic unwrap shred it into a list of half-traces.
    """
    from openbb_core.app.model.obbject import OBBject

    figure = {
        "data": [
            {
                "type": "scattergeo",
                "lat": [12.5, 13.0],
                "lon": [-77.0, -76.5],
                "name": "Red",
            }
        ],
        "layout": {
            "title": {"text": "Disruptions"},
            "geo": {"projection": "natural earth"},
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=figure)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher("http://t", client=client, command_methods={"chart_cmd": "get"})
    try:
        resp = await d.dispatch(
            Request(command="chart_cmd", params={"region": "global"})
        )
    finally:
        await d.aclose()
    assert resp.ok
    assert isinstance(resp.result, OBBject)
    # The figure rides at BOTH ``results`` and ``chart.content`` so
    # callers reading ``obbject.results`` see the actual figure (not
    # ``None``), and chart-aware renderers (``obbject.charting.show()``)
    # also keep working off the canonical ``chart`` slot.
    assert resp.result.results == figure
    assert resp.result.chart is not None
    assert resp.result.chart.format == "plotly"
    assert resp.result.chart.content == figure
    # Execution metadata still rides under ``extra.metadata`` like
    # every other dispatch.
    meta = resp.result.extra["metadata"]
    assert meta.route == "/chart_cmd"
    assert meta.arguments["standard_params"] == {"region": "global"}


@pytest.mark.asyncio
async def test_dispatch_plotly_figure_falls_back_to_raw_dict_without_openbb_core(
    monkeypatch,
):
    """Without ``openbb_core``, the Plotly wrap can't construct an
    OBBject. Fall back to returning the raw figure dict so the figure
    structure is still preserved end-to-end."""
    import builtins

    real_import = builtins.__import__

    def _block_chart_imports(name, *args, **kwargs):
        if name.startswith("openbb_core.app.model"):
            raise ImportError(f"simulated missing {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_chart_imports)

    figure = {
        "data": [{"type": "scatter", "x": [1], "y": [2]}],
        "layout": {"title": "x"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=figure)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher("http://t", client=client, command_methods={"x": "get"})
    try:
        resp = await d.dispatch(Request(command="x"))
    finally:
        await d.aclose()
    # Raw figure dict preserved — both data and layout intact.
    assert resp.result == figure


def test_command_to_route_translates_dotted_to_slash_form():
    """Dotted command paths land in ``Metadata.route`` as the slash form
    ``command_runner`` uses, with a leading slash."""
    from openbb_cli.dispatchers.http import _command_to_route

    assert _command_to_route("equity.price.historical") == "/equity/price/historical"
    assert _command_to_route("law") == "/law"
    # Strips redundant slashes so callers don't have to normalize.
    assert _command_to_route("/foo.bar/") == "/foo/bar"


@pytest.mark.asyncio
async def test_shape_and_coerce_returns_payload_unchanged_for_non_collection():
    """A scalar / non-list / non-dict shape from ``_shape_result`` short-
    circuits the wrap — there's no row payload to type-coerce or wrap."""
    spec_doc = {
        "commands": {
            "x": {
                "method": "get",
                "response_schema": {
                    "properties": {
                        "results": {"items": {"properties": {"id": {"type": "string"}}}}
                    }
                },
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        # ``"plain text"`` is not JSON content-type, falls through as-is.
        return httpx.Response(
            200, text="plain text", headers={"content-type": "text/plain"}
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher("http://t", client=client, spec_doc=spec_doc)
    try:
        resp = await d.dispatch(Request(command="x"))
    finally:
        await d.aclose()
    assert resp.ok
    # Non-JSON text bypasses unwrap entirely — stays a plain string.
    assert resp.result == "plain text"


@pytest.mark.asyncio
async def test_dispatch_handles_single_row_envelope_with_sibling_metadata():
    """Sibling-metadata API returning a single-row array — after unpack +
    ``_shape_result``'s single-row collapse, the inner ``results`` field
    arrives at ``_shape_and_coerce`` as a single dict (not a list).
    Exercises the ``elif inner is not None`` branch.
    """
    from openbb_core.app.model.obbject import OBBject

    spec_doc = {
        "commands": {
            "y": {
                "method": "get",
                "response_schema": {
                    "properties": {
                        "results": {"items": {"properties": {"x": {"type": "number"}}}}
                    }
                },
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        # ``operations`` (single row) + sibling ``asOfDate`` →
        # ``unpack_response`` extracts metadata, ``_shape_result``
        # collapses the single-row list, and ``_shape_and_coerce`` sees
        # ``{results: {dict}, metadata: {asOfDate}}``.
        return httpx.Response(
            200, json={"asOfDate": "2026-04-30", "operations": [{"x": "1.5"}]}
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher("http://t", client=client, spec_doc=spec_doc)
    try:
        resp = await d.dispatch(Request(command="y"))
    finally:
        await d.aclose()
    assert resp.ok
    # Wrap produces a real OBBject; the sibling ``asOfDate`` lands at
    # ``extra.asOfDate`` (its own concept), separate from per-row
    # metadata.
    assert isinstance(resp.result, OBBject)
    assert resp.result.extra["asOfDate"] == "2026-04-30"
    # Type coercion ran through the single-row branch — string ``"1.5"``
    # → float.
    assert resp.result.results == {"x": 1.5}


@pytest.mark.asyncio
async def test_dispatch_obbject_wrap_falls_back_to_dict_when_openbb_core_missing(
    monkeypatch,
):
    """Without ``openbb_core`` available, the wrap can't construct a real
    OBBject — fall back to a plain dict that still puts metadata under
    ``extra`` so the schema never sprouts a top-level ``metadata`` field.
    """
    import builtins

    real_import = builtins.__import__

    def _block_openbb_core(name, *args, **kwargs):
        if name.startswith("openbb_core.app.model"):
            raise ImportError(f"simulated missing {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_openbb_core)

    spec_doc = {
        "commands": {
            "z": {
                "method": "get",
                "response_schema": {
                    "properties": {
                        "results": {
                            "items": {
                                "properties": {
                                    "id": {
                                        "type": "string",
                                        "description": "An ID",
                                    }
                                }
                            }
                        }
                    }
                },
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        # Two rows — avoid the single-row collapse so we can assert on
        # the list shape unambiguously.
        return httpx.Response(200, json=[{"id": "a"}, {"id": "b"}])

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher("http://t", client=client, spec_doc=spec_doc)
    try:
        resp = await d.dispatch(Request(command="z"))
    finally:
        await d.aclose()
    assert resp.ok
    # Plain dict fallback — but metadata still under ``extra``, never
    # at top level.
    assert isinstance(resp.result, dict)
    assert "metadata" not in resp.result
    assert resp.result["results"] == [{"id": "a"}, {"id": "b"}]
    assert resp.result["extra"]["results_metadata"]["columns"] == {
        "id": {"description": "An ID"}
    }


@pytest.mark.asyncio
async def test_dispatch_metadata_construction_failure_does_not_kill_response():
    """Telemetry is best-effort — when ``Metadata`` construction raises
    (e.g. malformed timestamp), the OBBject still gets returned with
    the rest of its metadata intact.
    """
    from openbb_core.app.model.obbject import OBBject

    spec_doc = {
        "commands": {
            "w": {
                "method": "get",
                "response_schema": {
                    "properties": {
                        "results": {
                            "items": {
                                "properties": {
                                    "id": {
                                        "type": "string",
                                        "description": "An ID",
                                    }
                                }
                            }
                        }
                    }
                },
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": "a"}])

    # Patch ``Metadata`` to raise so we exercise the suppress branch.
    import openbb_core.app.model.metadata as metadata_mod

    def _raise(*args, **kwargs):
        raise RuntimeError("simulated metadata failure")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher("http://t", client=client, spec_doc=spec_doc)
    original = metadata_mod.Metadata
    metadata_mod.Metadata = _raise  # type: ignore[assignment]
    try:
        resp = await d.dispatch(Request(command="w"))
    finally:
        metadata_mod.Metadata = original  # type: ignore[assignment]
        await d.aclose()
    assert resp.ok
    assert isinstance(resp.result, OBBject)
    # Column metadata still surfaced; ``extra.metadata`` simply absent
    # because telemetry construction failed and got suppressed.
    assert resp.result.extra["results_metadata"]["columns"] == {
        "id": {"description": "An ID"}
    }
    assert "metadata" not in resp.result.extra


# --- Helper-function coverage ---


def test_user_limit_for_per_item_handles_none_invalid_negative_zero():
    """``_user_limit_for_per_item`` returns ``None`` for missing / non-numeric /
    negative / zero limits — the per-item collapse pass treats all of these
    the same way (no cap)."""
    from openbb_cli.dispatchers.http import _user_limit_for_per_item

    # No limit at all → ``None``.
    assert _user_limit_for_per_item(Request(command="x", params={})) is None
    # Non-numeric → ``None`` via the ``ValueError`` branch.
    assert (
        _user_limit_for_per_item(Request(command="x", params={"limit": "abc"})) is None
    )
    # Negative → ``None`` (not a real cap).
    assert _user_limit_for_per_item(Request(command="x", params={"limit": -5})) is None
    # Zero → ``None`` (means "every row" — the collapse runs uncapped).
    assert _user_limit_for_per_item(Request(command="x", params={"limit": 0})) is None
    # Positive → integer.
    assert _user_limit_for_per_item(Request(command="x", params={"limit": 5})) == 5


def test_request_with_page_size_limit_caps_user_limit_to_one_page():
    """``_request_with_page_size_limit`` clobbers ``limit`` with the page-size
    constant so the most-recent-per-item path issues exactly one page-sized
    fetch regardless of what the user asked for."""
    from openbb_cli.dispatchers.http import (
        _SOCRATA_PAGE_SIZE,
        _request_with_page_size_limit,
    )

    out = _request_with_page_size_limit(
        Request(id="abc", command="x", params={"limit": 3, "region": "Tampa"})
    )
    assert out.id == "abc"
    assert out.params["limit"] == _SOCRATA_PAGE_SIZE
    assert out.params["region"] == "Tampa"


def test_truncate_to_top_n_dates_handles_non_dict_rows_and_missing_dates():
    """Non-dict rows and rows missing the time-axis value are passed through
    unchanged — only rows with a real date count toward the distinct-date cap."""
    from openbb_cli.dispatchers.http import _truncate_to_top_n_dates

    rows = [
        "scalar-row",  # non-dict, kept verbatim
        {"date": "2026-04-30", "x": 1},
        {"date": None, "x": 2},  # missing date, kept verbatim
        {"date": "2026-04-30", "x": 3},  # same date, kept (still under cap)
        {"date": "2026-04-29", "x": 4},  # second date — fills the cap
        {"date": "2026-04-28", "x": 5},  # third date — break before this row
    ]
    out = _truncate_to_top_n_dates(rows, "date", 2)
    # Three "real" date rows kept (two in date 2026-04-30, one in 2026-04-29);
    # the non-dict scalar and missing-date row also kept; the third-date row
    # is dropped.
    assert "scalar-row" in out
    assert {"date": None, "x": 2} in out
    assert {"date": "2026-04-30", "x": 1} in out
    assert {"date": "2026-04-30", "x": 3} in out
    assert {"date": "2026-04-29", "x": 4} in out
    assert {"date": "2026-04-28", "x": 5} not in out


def test_truncate_to_top_n_dates_returns_unchanged_when_user_limit_is_none():
    """``user_limit=None`` (the ``limit=0`` case) means no truncation —
    the rows pass through verbatim."""
    from openbb_cli.dispatchers.http import _truncate_to_top_n_dates

    rows = [{"date": "2026-04-30"}, {"date": "2026-04-01"}]
    assert _truncate_to_top_n_dates(rows, "date", None) == rows
    # Non-list shape with no extractable rows also passes through.
    assert _truncate_to_top_n_dates("scalar", "date", 5) == "scalar"


def test_extract_rows_handles_duck_typed_obbject():
    """``_extract_rows`` recognizes a duck-typed OBBject (``results`` list +
    ``extra``) without importing ``openbb_core``. Other shapes return ``None``.
    """
    from openbb_cli.dispatchers.http import _extract_rows

    class _DuckOBBject:
        results = [{"a": 1}, {"a": 2}]
        extra: dict = {}

    assert _extract_rows(_DuckOBBject()) == [{"a": 1}, {"a": 2}]

    # ``{results: [...]}`` envelope dict → returns the inner list.
    assert _extract_rows({"results": [{"x": 1}]}) == [{"x": 1}]

    # No ``extra`` attr → not enough fingerprint, returns ``None``.
    class _Almost:
        results = [{"a": 1}]

    assert _extract_rows(_Almost()) is None
    # Plain string scalar → ``None``.
    assert _extract_rows("scalar") is None
    # Dict without a ``results`` list value → ``None``.
    assert _extract_rows({"x": 1}) is None
    assert _extract_rows({"results": "not-a-list"}) is None


def test_replace_rows_substitutes_into_envelope_dict():
    """A ``{results: [...]}`` envelope dict with extra siblings preserves
    the siblings and only replaces the ``results`` key. Exercises the
    dict branch at line 441."""
    from openbb_cli.dispatchers.http import _replace_rows

    out = _replace_rows({"results": [{"old": 1}], "metadata": {"k": "v"}}, [{"new": 1}])
    assert out == {"results": [{"new": 1}], "metadata": {"k": "v"}}


def test_replace_rows_returns_shaped_for_unrecognized_object():
    """An object with neither ``results`` (as a list) nor ``extra`` falls
    through the OBBject duck-type and gets returned verbatim."""
    from openbb_cli.dispatchers.http import _replace_rows

    class _NotAnOBBject:
        results = "not-a-list"  # disqualifies the duck-type fingerprint

    obj = _NotAnOBBject()
    assert _replace_rows(obj, [{"a": 1}]) is obj


def test_replace_rows_mutates_obbject_in_place_and_returns_it():
    """``_replace_rows`` mutates an OBBject's ``results`` in place, preserving
    the original instance (and its private attrs) — important so registry
    insertion later sees the canonical instance."""
    from openbb_core.app.model.obbject import OBBject

    from openbb_cli.dispatchers.http import _replace_rows

    obb = OBBject(results=[{"old": 1}], extra={"x": 1})
    obb._route = "/r"
    new_rows = [{"new": 1}, {"new": 2}]
    out = _replace_rows(obb, new_rows)
    assert out is obb  # same instance
    assert obb.results == new_rows
    assert obb._route == "/r"  # private attr survived


def test_replace_rows_returns_unchanged_for_unrecognized_shape():
    """A shape that's neither list / dict-with-results / duck-OBBject is
    returned verbatim — there's no row slot to substitute into."""
    from openbb_cli.dispatchers.http import _replace_rows

    assert _replace_rows("scalar", [{"a": 1}]) == "scalar"
    assert _replace_rows({"no_results_key": True}, [{"a": 1}]) == {
        "no_results_key": True
    }


def test_coerce_response_value_numeric_parse_failure_returns_string():
    """Numeric coercion treats ``ValueError`` from ``float()`` as a signal
    to return the raw string — protects against malformed wire payloads
    sneaking through to downstream consumers as ``NaN``."""
    from openbb_cli.dispatchers.http import _coerce_response_value

    # ``"infinity-but-not"`` → float() raises → string passthrough.
    assert _coerce_response_value("not-a-number", "number", "") == "not-a-number"


def test_coerce_response_value_handles_integer_boolean_and_date_branches():
    """``_coerce_response_value`` coerces wire strings into typed values across
    each declared schema type."""
    from openbb_cli.dispatchers.http import _coerce_response_value

    # Integer happy-path.
    assert _coerce_response_value("42", "integer", "") == 42
    # Integer parse fail → string passthrough.
    assert _coerce_response_value("not-an-int", "integer", "") == "not-an-int"
    # Boolean happy-path (case-insensitive).
    assert _coerce_response_value("True", "boolean", "") is True
    assert _coerce_response_value("FALSE", "boolean", "") is False
    # Boolean unrecognized → string passthrough.
    assert _coerce_response_value("maybe", "boolean", "") == "maybe"
    # Date drop time component when the string contains a ``T`` and is long
    # enough to look like an ISO timestamp.
    assert _coerce_response_value("2026-04-30T00:00:00.000", "string", "date") == (
        "2026-04-30"
    )
    # Already a plain date string, no ``T`` → unchanged.
    assert _coerce_response_value("2026-04-30", "string", "date") == "2026-04-30"
    # Non-string input → unchanged.
    assert _coerce_response_value(42, "integer", "") == 42


def test_row_column_types_skips_non_dict_property_entries():
    """Defensive: a non-dict entry in ``items.properties`` (malformed schema)
    gets skipped instead of crashing the whole walk."""
    from openbb_cli.dispatchers.http import _row_column_types

    cmd_spec = {
        "response_schema": {
            "properties": {
                "results": {
                    "items": {
                        "properties": {
                            "ok": {"type": "string"},
                            "garbage": "not-a-dict",
                        }
                    }
                }
            }
        }
    }
    out = _row_column_types(cmd_spec)
    assert "ok" in out
    assert "garbage" not in out


def test_row_column_metadata_skips_non_dict_property_entries():
    """Same defensive skip for ``_row_column_metadata`` so codegen-style
    schemas can't trip the column-metadata extraction."""
    from openbb_cli.dispatchers.http import _row_column_metadata

    cmd_spec = {
        "response_schema": {
            "properties": {
                "results": {
                    "items": {
                        "properties": {
                            "ok": {"type": "string", "description": "Real"},
                            "garbage": "not-a-dict",
                        }
                    }
                }
            }
        }
    }
    out = _row_column_metadata(cmd_spec)
    assert "ok" in out
    assert "garbage" not in out


def test_coerce_row_types_handles_empty_types_non_dict_rows_and_unknown_fields():
    """Three branches of ``_coerce_row_types``:
    * empty ``column_types`` → no-op pass-through
    * non-dict row → kept verbatim
    * row field absent from ``column_types`` → value passed through unchanged
    """
    from openbb_cli.dispatchers.http import _coerce_row_types

    # Empty types — no-op.
    assert _coerce_row_types([{"a": "1"}], {}) == [{"a": "1"}]
    # Non-dict row — kept verbatim.
    out = _coerce_row_types(["scalar", {"a": "1"}], {"a": ("integer", "")})
    assert out == ["scalar", {"a": 1}]
    # Field not in column_types — passed through unchanged.
    out = _coerce_row_types([{"a": "1", "b": "stuff"}], {"a": ("integer", "")})
    assert out == [{"a": 1, "b": "stuff"}]


@pytest.mark.asyncio
async def test_apply_param_transforms_folds_socrata_date_range_into_where():
    """``_apply_param_transforms`` rewrites ``start_date`` / ``end_date`` params
    into a SoQL ``$where`` clause and applies ``wire_name`` renames so the
    spec-mode dispatcher hits the upstream API with the same URL the
    installed-extension fetcher would build.
    """
    # No ``_socrata_time_axis`` — keeps the test off the date-snapshot
    # pagination path so the user's ``limit`` survives intact for the
    # ``$limit`` rename assertion.
    spec_doc = {
        "commands": {
            "ag.prices": {
                "method": "get",
                "parameters": [
                    {
                        "name": "start_date",
                        "_socrata_op": "date_min",
                        "_socrata_column": "obs_date",
                    },
                    {
                        "name": "end_date",
                        "_socrata_op": "date_max",
                        "_socrata_column": "obs_date",
                    },
                    {"name": "limit", "wire_name": "$limit"},
                    "not-a-dict",  # defensive non-dict skip
                ],
            }
        }
    }
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher(
        "http://t",
        client=client,
        spec_doc=spec_doc,
        command_methods={"ag.prices": "get"},
    )
    try:
        await d.dispatch(
            Request(
                command="ag.prices",
                params={
                    "start_date": "2026-01-01",
                    "end_date": "2026-04-30",
                    "limit": 10,
                },
            )
        )
    finally:
        await d.aclose()
    # Where-fold and wire_name rename applied.
    assert (
        captured["params"]["$where"]
        == "obs_date >= '2026-01-01' AND obs_date <= '2026-04-30'"
    )
    assert captured["params"]["$limit"] == "10"
    # User-facing names removed in favour of the wire form.
    assert "start_date" not in captured["params"]
    assert "end_date" not in captured["params"]
    assert "limit" not in captured["params"]
    # No default $order without a ``_socrata_time_axis``.
    assert "$order" not in captured["params"]


@pytest.mark.asyncio
async def test_apply_param_transforms_default_order_with_time_axis_set():
    """A spec command with ``_socrata_time_axis`` gets ``$order=<axis> DESC``
    auto-injected so ``limit=N`` returns the most-recent N rows by default.
    User-supplied ``$order`` overrides it.
    """
    spec_doc = {
        "commands": {
            "x": {
                "method": "get",
                "_socrata_time_axis": "obs_date",
                "parameters": [{"name": "foo"}],
            }
        }
    }
    captured: dict = {"calls": []}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["calls"].append(dict(request.url.params))
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher(
        "http://t",
        client=client,
        spec_doc=spec_doc,
        command_methods={"x": "get"},
    )
    try:
        # No user $order → auto-injected.
        await d.dispatch(Request(command="x", params={"foo": "bar"}))
        # User-supplied $order overrides the default.
        await d.dispatch(
            Request(command="x", params={"foo": "bar", "$order": "obs_date ASC"})
        )
    finally:
        await d.aclose()
    assert captured["calls"][0]["$order"] == "obs_date DESC"
    assert captured["calls"][1]["$order"] == "obs_date ASC"


@pytest.mark.asyncio
async def test_apply_param_transforms_combines_existing_where_with_date_fold():
    """User-supplied ``$where`` + folded date-range get AND-combined into a
    single SoQL clause, parenthesized to preserve precedence."""
    spec_doc = {
        "commands": {
            "x": {
                "method": "get",
                "parameters": [
                    {
                        "name": "start_date",
                        "_socrata_op": "date_min",
                        "_socrata_column": "obs_date",
                    },
                ],
            }
        }
    }
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher(
        "http://t",
        client=client,
        spec_doc=spec_doc,
        command_methods={"x": "get"},
    )
    try:
        await d.dispatch(
            Request(
                command="x",
                params={"start_date": "2026-01-01", "$where": "region = 'Tampa'"},
            )
        )
    finally:
        await d.aclose()
    assert (
        captured["params"]["$where"]
        == "(region = 'Tampa') AND (obs_date >= '2026-01-01')"
    )


@pytest.mark.asyncio
async def test_apply_param_transforms_skips_date_range_when_user_omits_value():
    """A date-range param the user didn't supply gets skipped — no
    ``$where`` clause appended for it. Exercises the ``value is None``
    continue at line 882."""
    spec_doc = {
        "commands": {
            "x": {
                "method": "get",
                "parameters": [
                    {
                        "name": "start_date",
                        "_socrata_op": "date_min",
                        "_socrata_column": "obs_date",
                    },
                ],
            }
        }
    }
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher(
        "http://t",
        client=client,
        spec_doc=spec_doc,
        command_methods={"x": "get"},
    )
    try:
        # No ``start_date`` in params → the date-range fold sees no
        # value and skips, leaving no ``$where`` clause.
        await d.dispatch(Request(command="x", params={"foo": "bar"}))
    finally:
        await d.aclose()
    assert "$where" not in captured["params"]


@pytest.mark.asyncio
async def test_apply_param_transforms_skips_date_range_when_socrata_column_missing():
    """A date-range param flagged with ``_socrata_op`` but missing the
    ``_socrata_column`` (malformed spec) gets skipped — no fabricated
    where clause. Exercises the ``not column`` continue at line 885."""
    spec_doc = {
        "commands": {
            "x": {
                "method": "get",
                "parameters": [
                    {
                        "name": "start_date",
                        "_socrata_op": "date_min",
                        # ``_socrata_column`` deliberately absent.
                    },
                ],
            }
        }
    }
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher(
        "http://t",
        client=client,
        spec_doc=spec_doc,
        command_methods={"x": "get"},
    )
    try:
        await d.dispatch(Request(command="x", params={"start_date": "2026-01-01"}))
    finally:
        await d.aclose()
    # Where-clause never built; the user's start_date param ends up
    # consumed (popped during the fold attempt) so it doesn't leak to
    # the URL either.
    assert "$where" not in captured["params"]


@pytest.mark.asyncio
async def test_apply_param_transforms_no_op_when_spec_has_no_parameters():
    """No parameters declared on the command → no transform; params pass
    through to the URL exactly as supplied."""
    spec_doc = {"commands": {"x": {"method": "get", "parameters": []}}}
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher(
        "http://t",
        client=client,
        spec_doc=spec_doc,
        command_methods={"x": "get"},
    )
    try:
        await d.dispatch(Request(command="x", params={"foo": "bar"}))
    finally:
        await d.aclose()
    assert captured["params"]["foo"] == "bar"


@pytest.mark.asyncio
async def test_fetch_until_n_distinct_dates_paginates_and_breaks_on_short_page():
    """``_fetch_until_n_distinct_dates`` pages until either ``n+1`` distinct
    dates are seen OR the upstream returns a short page, whichever comes
    first."""
    from openbb_cli.dispatchers.http import (
        _SOCRATA_PAGE_SIZE,
        _fetch_until_n_distinct_dates,
    )

    pages = [
        # First page has ``_SOCRATA_PAGE_SIZE`` rows but only one distinct
        # date — must keep paging.
        [{"date": "2026-04-30", "x": i} for i in range(_SOCRATA_PAGE_SIZE)],
        # Short second page introduces a second distinct date AND signals
        # end-of-data via the < page-size length.
        [{"date": "2026-04-29", "x": 1}, {"date": "2026-04-29", "x": 2}],
    ]
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        i = call_count["n"]
        call_count["n"] += 1
        if i < len(pages):
            return httpx.Response(200, json=pages[i])
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        rows = await _fetch_until_n_distinct_dates(
            client, "http://t/x", {}, None, "date", 1
        )
    # Both pages consumed; short page breaks the loop.
    assert call_count["n"] == 2
    assert len(rows) == _SOCRATA_PAGE_SIZE + 2


@pytest.mark.asyncio
async def test_fetch_until_n_distinct_dates_breaks_on_empty_first_page():
    """Empty first page → exit immediately. Exercises the
    ``not isinstance(payload, list) or not payload`` break."""
    from openbb_cli.dispatchers.http import _fetch_until_n_distinct_dates

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        rows = await _fetch_until_n_distinct_dates(
            client, "http://t/x", {}, None, "date", 5
        )
    assert rows == []
    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_fetch_until_n_distinct_dates_breaks_on_short_page_before_n_plus_one():
    """A page shorter than ``_SOCRATA_PAGE_SIZE`` arrives before the
    (n+1)-th distinct date is seen → exit via the short-page break."""
    from openbb_cli.dispatchers.http import _fetch_until_n_distinct_dates

    # Page of 5 rows (way under page-size cap), all sharing the same date —
    # exits via the ``len(payload) < _SOCRATA_PAGE_SIZE`` branch before
    # the n+1 break.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"date": "2026-04-30", "x": i} for i in range(5)],
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        rows = await _fetch_until_n_distinct_dates(
            client, "http://t/x", {}, None, "date", 10
        )
    assert len(rows) == 5


@pytest.mark.asyncio
async def test_fetch_until_n_distinct_dates_breaks_when_n_plus_one_seen():
    """Once we've seen ``n+1`` distinct dates, the loop exits even if the
    upstream still has more rows."""
    from openbb_cli.dispatchers.http import _fetch_until_n_distinct_dates

    page = [
        {"date": "2026-04-30", "x": 1},
        {"date": "2026-04-29", "x": 2},  # distinct #2 — exceeds n=1.
        # Skipped — non-dict row in payload triggers the defensive
        # skip in the date-collection loop too.
        "garbage",
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=page)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        rows = await _fetch_until_n_distinct_dates(
            client, "http://t/x", {}, None, "date", 1
        )
    # Single fetch sufficed because n+1 dates appeared.
    assert {row.get("date") if isinstance(row, dict) else None for row in rows} == {
        "2026-04-30",
        "2026-04-29",
        None,
    }


@pytest.mark.asyncio
async def test_fetch_all_pages_paginates_until_short_page_or_empty():
    """``_fetch_all_pages`` keeps requesting until the upstream returns a
    short page OR an empty list (the ``limit=0`` semantic)."""
    from openbb_cli.dispatchers.http import _SOCRATA_PAGE_SIZE, _fetch_all_pages

    pages = [
        [{"x": i} for i in range(_SOCRATA_PAGE_SIZE)],
        # Short page — terminates the loop.
        [{"x": _SOCRATA_PAGE_SIZE}],
    ]
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        i = call_count["n"]
        call_count["n"] += 1
        if i < len(pages):
            return httpx.Response(200, json=pages[i])
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        rows = await _fetch_all_pages(client, "http://t/x", {}, None)
    assert call_count["n"] == 2
    assert len(rows) == _SOCRATA_PAGE_SIZE + 1


@pytest.mark.asyncio
async def test_fetch_all_pages_terminates_on_empty_first_page():
    """Empty first page → loop exits immediately, no second request."""
    from openbb_cli.dispatchers.http import _fetch_all_pages

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        rows = await _fetch_all_pages(client, "http://t/x", {}, None)
    assert rows == []
    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_dispatch_engages_fetch_all_when_limit_zero():
    """``limit=0`` flips the dispatch into the all-pages path — exercises
    the ``fetch_all`` branch in ``dispatch``.
    """
    from openbb_cli.dispatchers.http import _SOCRATA_PAGE_SIZE

    pages = [
        [{"id": i} for i in range(_SOCRATA_PAGE_SIZE)],
        [{"id": _SOCRATA_PAGE_SIZE}],
    ]
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        i = call_count["n"]
        call_count["n"] += 1
        if i < len(pages):
            return httpx.Response(200, json=pages[i])
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher(
        "http://t",
        client=client,
        command_methods={"x": "get"},
    )
    try:
        resp = await d.dispatch(Request(command="x", params={"limit": 0}))
    finally:
        await d.aclose()
    assert resp.ok
    assert call_count["n"] == 2  # Two pages, then short-page break.


@pytest.mark.asyncio
async def test_dispatch_engages_date_snapshot_truncation_when_time_axis_present():
    """Spec command with a ``_socrata_time_axis`` + a positive ``limit`` engages
    the date-snapshot path: pagination via ``_fetch_until_n_distinct_dates``
    then local truncation via ``_truncate_to_top_n_dates``.
    """
    spec_doc = {
        "commands": {
            "ds": {
                "method": "get",
                "_socrata_time_axis": "obs_date",
                "parameters": [],
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        # Three distinct dates in a single short page so the n+1 break and
        # short-page break both fire.
        return httpx.Response(
            200,
            json=[
                {"obs_date": "2026-04-30", "x": 1},
                {"obs_date": "2026-04-30", "x": 2},
                {"obs_date": "2026-04-29", "x": 3},
                {"obs_date": "2026-04-28", "x": 4},
            ],
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher(
        "http://t",
        client=client,
        spec_doc=spec_doc,
        command_methods={"ds": "get"},
    )
    try:
        # ``limit=2`` → keep top-2 most recent distinct dates.
        resp = await d.dispatch(Request(command="ds", params={"limit": 2}))
    finally:
        await d.aclose()
    assert resp.ok
    # Two-date truncation: kept rows for 2026-04-30 and 2026-04-29; dropped 2026-04-28.
    distinct = {row["obs_date"] for row in resp.result if isinstance(row, dict)}
    assert distinct == {"2026-04-30", "2026-04-29"}


@pytest.mark.asyncio
async def test_dispatch_date_snapshot_skipped_when_limit_zero_or_invalid():
    """``limit=0`` or non-numeric ``limit`` short-circuits the date-
    snapshot context — no truncation, no special pagination."""
    spec_doc = {
        "commands": {
            "ds": {
                "method": "get",
                "_socrata_time_axis": "obs_date",
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"obs_date": "2026-04-30"}])

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher("http://t", client=client, spec_doc=spec_doc)
    try:
        # ``limit=0`` short-circuits — no truncation engaged.
        await d.dispatch(Request(command="ds", params={"limit": 0}))
        # Non-numeric short-circuits via the int() ValueError path.
        await d.dispatch(Request(command="ds", params={"limit": "not-a-number"}))
        # No-limit also short-circuits via the ``raw_limit is None`` path.
        await d.dispatch(Request(command="ds", params={}))
    finally:
        await d.aclose()


def test_partition_params_sends_json_list_style_as_json_array():
    d = HttpDispatcher(
        "http://test",
        spec_doc={
            "commands": {
                "ticker.price": {
                    "parameters": [
                        {
                            "name": "symbols",
                            "in": "query",
                            "is_list": True,
                            "list_style": "json",
                        }
                    ]
                }
            }
        },
    )
    for value in (["BTCUSDT", "ETHUSDT"], "BTCUSDT,ETHUSDT", '["BTCUSDT","ETHUSDT"]'):
        query, _, _ = d._partition_params("ticker.price", {"symbols": value})
        assert query == {"symbols": '["BTCUSDT","ETHUSDT"]'}


def _sigmets_dispatcher(handler):
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    templates = ["/sigmets/{atsu}/{date}", "/sigmets/{atsu}", "/sigmets"]
    return HttpDispatcher(
        "http://t",
        client=client,
        command_methods={"sigmets": "get"},
        command_url_paths={"sigmets": templates},
        spec_doc={
            "commands": {
                "sigmets": {
                    "url_path": "/sigmets",
                    "url_templates": templates,
                    "template_query_params": {
                        "/sigmets/{atsu}/{date}": [],
                        "/sigmets/{atsu}": [],
                        "/sigmets": ["date", "limit"],
                    },
                    "parameters": [
                        {"name": "atsu", "in": "path"},
                        {"name": "date", "in": "path"},
                        {"name": "limit", "in": "query", "default": 500},
                    ],
                }
            }
        },
    )


@pytest.mark.asyncio
async def test_dispatch_sends_only_the_query_params_the_chosen_url_declares():
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(str(request.url))
        return httpx.Response(200, json={})

    d = _sigmets_dispatcher(handler)
    try:
        await d.dispatch(
            Request(command="sigmets", params={"date": "2026-10-18", "limit": 500})
        )
        await d.dispatch(
            Request(
                command="sigmets",
                params={"atsu": "KKCI", "date": "2026-10-18", "limit": 500},
            )
        )
        await d.dispatch(Request(command="sigmets", params={"limit": 500}))
    finally:
        await d.aclose()
    assert captured == [
        "http://t/sigmets?date=2026-10-18&limit=500",
        "http://t/sigmets/KKCI/2026-10-18",
        "http://t/sigmets?limit=500",
    ]


@pytest.mark.asyncio
async def test_dispatch_spec_without_template_query_params_keeps_query_fallback():
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(str(request.url))
        return httpx.Response(200, json={})

    d = _sigmets_dispatcher(handler)
    del d._spec_doc["commands"]["sigmets"]["template_query_params"]
    try:
        await d.dispatch(Request(command="sigmets", params={"date": "2026-10-18"}))
        await d.dispatch(
            Request(command="sigmets", params={"atsu": "KKCI", "date": "2026-10-18"})
        )
    finally:
        await d.aclose()
    assert captured == [
        "http://t/sigmets?date=2026-10-18",
        "http://t/sigmets/KKCI/2026-10-18",
    ]


@pytest.mark.asyncio
async def test_dispatch_argparse_boolean_default_does_not_pick_or_block_a_url():
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(str(request.url))
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    templates = ["/v/{n}/{flag}", "/v"]
    d = HttpDispatcher(
        "http://t",
        client=client,
        command_methods={"v": "get"},
        command_url_paths={"v": templates},
        spec_doc={
            "commands": {
                "v": {
                    "url_templates": templates,
                    "template_query_params": {"/v/{n}/{flag}": [], "/v": ["q"]},
                    "parameters": [
                        {"name": "n", "in": "path"},
                        {"name": "flag", "in": "path", "type": "boolean"},
                        {"name": "q", "in": "query"},
                    ],
                }
            }
        },
    )
    try:
        await d.dispatch(Request(command="v", params={"flag": False, "q": "a"}))
        await d.dispatch(Request(command="v", params={"n": 3, "flag": True}))
    finally:
        await d.aclose()
    assert captured == ["http://t/v?q=a", "http://t/v/3/true"]


@pytest.mark.asyncio
async def test_dispatch_rejects_path_values_that_form_no_url_without_a_request():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request to {request.url}")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher(
        "http://t",
        client=client,
        command_methods={"cwas": "get"},
        command_url_paths={"cwas": ["/cwas/{id}", "/cwas/{id}/{date}/{seq}"]},
    )
    try:
        resp = await d.dispatch(
            Request(command="cwas", params={"id": "ZAB", "date": "2026-10-18"})
        )
    finally:
        await d.aclose()
    assert not resp.ok
    assert "do not form a URL" in resp.error.message


def test_partition_params_json_list_from_argparse_lists_and_typed_items():
    d = HttpDispatcher(
        "http://test",
        spec_doc={
            "commands": {
                "orders": {
                    "parameters": [
                        {
                            "name": "symbols",
                            "in": "query",
                            "is_list": True,
                            "list_style": "json",
                        },
                        {
                            "name": "ids",
                            "in": "query",
                            "is_list": True,
                            "list_style": "json",
                            "type": "integer",
                        },
                    ]
                }
            }
        },
    )
    cases = [
        ({"symbols": ['["BTCUSDT","ETHUSDT"]']}, {"symbols": '["BTCUSDT","ETHUSDT"]'}),
        ({"symbols": ["BTCUSDT,ETHUSDT"]}, {"symbols": '["BTCUSDT","ETHUSDT"]'}),
        ({"symbols": ["BTCUSDT", "ETHUSDT"]}, {"symbols": '["BTCUSDT","ETHUSDT"]'}),
        ({"ids": [1, 2]}, {"ids": "[1,2]"}),
        ({"ids": "1,2"}, {"ids": "[1,2]"}),
        ({"symbols": ""}, {}),
        ({"symbols": [""]}, {}),
        ({"symbols": ["  "]}, {}),
    ]
    for params, expected in cases:
        query, _, _ = d._partition_params("orders", params)
        assert query == expected, params


def test_shape_result_keeps_a_single_positional_row_whole():
    from openbb_cli.dispatchers.http import _shape_result

    cmd_spec = {
        "response_schema": {
            "type": "array",
            "items": {"type": "array", "items": {"type": "string"}},
        }
    }
    assert _shape_result([[1, "a", "b"]], cmd_spec) == [[1, "a", "b"]]
    assert _shape_result([[1, "a"], [2, "b"]], cmd_spec) == [[1, "a"], [2, "b"]]


def test_check_required_groups_ignores_optional_members_at_their_default():
    from openbb_cli.dispatchers.http import _check_required_groups

    cmd_spec = {
        "parameters": [
            {"name": "symbol"},
            {"name": "isin"},
            {"name": "limit", "default": 10},
        ],
        "required_groups": [
            {
                "combinator": "oneOf",
                "alternatives": [["symbol"], ["isin"]],
                "members": ["symbol", "isin", "limit"],
                "required": False,
            }
        ],
    }
    _check_required_groups(cmd_spec, {"limit": 10, "index": "idx1"})
    _check_required_groups(cmd_spec, {"symbol": "A", "limit": 5})
    with pytest.raises(
        ValueError, match=re.escape("Pass exactly one of: symbol | isin")
    ):
        _check_required_groups(cmd_spec, {"limit": 5})


@pytest.mark.asyncio
async def test_dispatch_enforces_required_groups_without_a_request():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request to {request.url}")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    d = HttpDispatcher(
        "http://t",
        client=client,
        command_methods={"ticker": "get"},
        command_url_paths={"ticker": "/ticker"},
        spec_doc={
            "commands": {
                "ticker": {
                    "url_path": "/ticker",
                    "parameters": [
                        {"name": "symbol", "in": "query"},
                        {"name": "symbols", "in": "query"},
                    ],
                    "required_groups": [
                        {
                            "combinator": "oneOf",
                            "alternatives": [["symbol"], ["symbols"]],
                            "members": ["symbol", "symbols"],
                            "required": True,
                        }
                    ],
                }
            }
        },
    )
    try:
        for params in ({}, {"symbol": "A", "symbols": "B"}):
            resp = await d.dispatch(Request(command="ticker", params=params))
            assert not resp.ok
            assert "Pass exactly one of: symbol | symbols" in resp.error.message
    finally:
        await d.aclose()
