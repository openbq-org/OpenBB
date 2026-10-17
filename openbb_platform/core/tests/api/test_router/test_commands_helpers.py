"""Targeted tests for ``openbb_core.api.router.commands`` helpers."""

import runpy
from inspect import signature
from typing import Annotated
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Depends
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from openbb_core.api.router.commands import (
    add_command_map,
    build_api_wrapper,
    build_new_annotation_map,
    build_new_signature,
    validate_output,
)
from openbb_core.app.command_runner import CommandRunner
from openbb_core.app.model.command_context import CommandContext
from openbb_core.app.model.obbject import OBBject


def test_build_new_annotation_map_includes_return():
    def f(a: int, b: str = "x") -> bool:
        return True

    out = build_new_annotation_map(signature(f))
    assert out["a"] is int
    assert out["b"] is str
    assert out["return"] is bool


def test_commands_module_resolves_charting_engine(monkeypatch):
    from openbb_core.app.charting import manager as charting_manager

    class _Charting:
        @staticmethod
        def functions():
            return []

    with pytest.MonkeyPatch.context() as m:
        m.setattr(
            charting_manager.ChartingManager,
            "get_charting_class",
            classmethod(lambda cls: _Charting),
        )
        module_ns = runpy.run_module(
            "openbb_core.api.router.commands", run_name="__test_commands_charting__"
        )
        assert module_ns["CHARTING_INSTALLED"] is True
        assert module_ns["Charting"] is _Charting


def test_build_new_signature_skips_command_context_and_kwargs():
    def f(cc: CommandContext, x: int, **kwargs) -> None: ...

    new_sig = build_new_signature("/some/path", f)
    names = [p.name for p in new_sig.parameters.values()]
    assert "cc" not in names
    assert "kwargs" not in names
    assert "x" in names


def test_build_new_signature_handles_depends_metadata():
    """Annotated[..., Depends(...)] params get re-injected at var_kw_pos."""

    def dep():
        return 1

    def f(x: int, y: Annotated[int, Depends(dep)] = 0) -> None: ...

    new_sig = build_new_signature("/path", f)
    names = [p.name for p in new_sig.parameters.values()]
    assert "x" in names and "y" in names


def test_build_new_signature_inserts_custom_headers(monkeypatch):
    from openbb_core.api.router import commands as cmds

    fake_settings = MagicMock()
    fake_settings.system_settings.api_settings.custom_headers = {"X-Test": "default"}
    monkeypatch.setattr(cmds, "SystemService", lambda: fake_settings)

    def f(x: int) -> None: ...

    new_sig = build_new_signature("/p", f)
    names = [p.name for p in new_sig.parameters.values()]
    assert "X_Test" in names


def test_build_new_signature_inserts_auth_param_when_api_auth(monkeypatch):
    from openbb_core.api.router import commands as cmds

    monkeypatch.setattr(cmds, "Env", type("E", (), {"API_AUTH": True}))

    def f(x: int) -> None: ...

    new_sig = build_new_signature("/p", f)
    names = [p.name for p in new_sig.parameters.values()]
    assert "__authenticated_user_settings" in names


def test_build_new_signature_inserts_chart_param_when_charting_enabled(monkeypatch):
    from openbb_core.api.router import commands as cmds

    monkeypatch.setattr(cmds, "CHARTING_INSTALLED", True)
    monkeypatch.setattr(
        cmds,
        "Charting",
        type("Charting", (), {"functions": staticmethod(lambda: ["api_v1_chart"])})(),
        raising=False,
    )

    def f(x: int, **extras) -> None: ...

    new_sig = build_new_signature("/api/v1/chart", f)
    names = [p.name for p in new_sig.parameters.values()]
    assert "chart" in names


class _NestedExcl(BaseModel):
    nested_secret: int = Field(default=0, json_schema_extra={"exclude_from_api": True})
    visible: int = 0


class _OuterModel(BaseModel):
    outer_secret: int = Field(default=0, json_schema_extra={"exclude_from_api": True})
    inner: _NestedExcl = _NestedExcl()
    public: int = 1


def test_validate_output_passthrough_non_obbject():
    """A non-OBBject value is returned unchanged."""
    obj = {"x": 1}
    out = validate_output(obj)  # type: ignore[arg-type]
    assert out is obj


def test_validate_output_excludes_top_level_field_marked_exclude_from_api():
    class _OBBWithSecret(OBBject):
        secret_thing: int = Field(
            default=0, json_schema_extra={"exclude_from_api": True}
        )

    out = _OBBWithSecret(results=[{"a": 1}], secret_thing=42)
    validate_output(out)
    assert not hasattr(out, "secret_thing")


def test_validate_output_excludes_nested_basemodel_fields():
    class _OBBNested(OBBject):
        outer: _OuterModel = _OuterModel()

    out = _OBBNested(results=[{"a": 1}], outer=_OuterModel())
    validate_output(out)
    # nested exclusion happens; the remaining structure stays intact
    assert hasattr(out, "outer")


def _make_route(endpoint, path="/api/v1/x"):
    return APIRoute(path=path, endpoint=endpoint, methods=["GET"])


@pytest.mark.asyncio
async def test_wrapper_returns_jsonresponse_when_results_only():
    runner = MagicMock(spec=CommandRunner)

    async def _run(path, user_settings, *args, **kwargs):
        out = OBBject(results=[{"a": 1}])
        out._results_only = True  # type: ignore[attr-defined]
        return out

    runner.run = _run

    async def endpoint(symbol: str = "AAPL", **kwargs):
        return OBBject(results=[{"symbol": symbol}])

    route = _make_route(endpoint)
    wrapper = build_api_wrapper(runner, route)
    out = await wrapper(symbol="AAPL")
    assert isinstance(out, JSONResponse)
    assert out.status_code == 200


@pytest.mark.asyncio
async def test_wrapper_returns_jsonresponse_when_extension_modified():
    runner = MagicMock(spec=CommandRunner)

    async def _run(path, user_settings, *args, **kwargs):
        out = OBBject(results=[{"a": 1}])
        out._extension_modified = True  # type: ignore[attr-defined]
        return out

    runner.run = _run

    async def endpoint(symbol: str = "AAPL", **kwargs):
        return OBBject(results=[{"symbol": symbol}])

    route = _make_route(endpoint)
    wrapper = build_api_wrapper(runner, route)
    out = await wrapper(symbol="AAPL")
    assert isinstance(out, JSONResponse)


@pytest.mark.asyncio
async def test_wrapper_passes_through_non_obbject():
    runner = MagicMock(spec=CommandRunner)

    async def _run(path, user_settings, *args, **kwargs):
        return {"plain": "dict"}

    runner.run = _run

    async def endpoint(symbol: str = "AAPL", **kwargs):
        return OBBject(results=[{"symbol": symbol}])

    route = _make_route(endpoint)
    wrapper = build_api_wrapper(runner, route)
    out = await wrapper(symbol="AAPL")
    assert out == {"plain": "dict"}


@pytest.mark.asyncio
async def test_wrapper_returns_streaming_response_for_obbstream():
    from starlette.responses import StreamingResponse

    from openbb_core.app.model.stream import OBBStream

    runner = MagicMock(spec=CommandRunner)

    class _Source:
        media_type = "text/event-stream"

        def __init__(self):
            self.body_iterator = self._gen()

        async def _gen(self):
            yield "data: 0\n\n"

    async def _run(path, user_settings, *args, **kwargs):
        return OBBStream(_Source())

    runner.run = _run

    async def endpoint(symbol: str = "AAPL", **kwargs):
        return OBBject(results=[])

    route = _make_route(endpoint)
    wrapper = build_api_wrapper(runner, route)
    out = await wrapper(symbol="AAPL")
    assert isinstance(out, StreamingResponse)
    assert out.media_type == "text/event-stream"
    assert out.headers["X-OpenBB-Stream-Id"]


@pytest.mark.asyncio
async def test_wrapper_streaming_broadcasts_warnings_and_provider_headers():
    import json as _json

    from starlette.responses import StreamingResponse

    from openbb_core.app.model.abstract.warning import Warning_
    from openbb_core.app.model.stream import OBBStream

    runner = MagicMock(spec=CommandRunner)

    class _Source:
        media_type = "text/event-stream"

        def __init__(self):
            self.body_iterator = self._gen()

        async def _gen(self):
            yield "data: 0\n\n"

    stream = OBBStream(_Source())
    stream.provider = "fmp"
    stream.warnings = [Warning_(category="OpenBBWarning", message="heads up")]

    async def _run(path, user_settings, *args, **kwargs):
        return stream

    runner.run = _run

    async def endpoint(symbol: str = "AAPL", **kwargs):
        return OBBject(results=[])

    route = _make_route(endpoint)
    wrapper = build_api_wrapper(runner, route)
    out = await wrapper(symbol="AAPL")
    assert isinstance(out, StreamingResponse)
    assert out.headers["X-OpenBB-Provider"] == "fmp"
    assert out.headers["X-OpenBB-Stream-Id"] == stream.id
    broadcast = _json.loads(out.headers["X-OpenBB-Warning"])
    assert broadcast[0]["category"] == "OpenBBWarning"
    assert broadcast[0]["message"] == "heads up"


@pytest.mark.asyncio
async def test_wrapper_passes_through_response():
    from starlette.responses import PlainTextResponse

    runner = MagicMock(spec=CommandRunner)
    response = PlainTextResponse("hi")

    async def _run(path, user_settings, *args, **kwargs):
        return response

    runner.run = _run

    async def endpoint(symbol: str = "AAPL", **kwargs):
        return OBBject(results=[])

    route = _make_route(endpoint)
    wrapper = build_api_wrapper(runner, route)
    out = await wrapper(symbol="AAPL")
    assert out is response


@pytest.mark.asyncio
async def test_wrapper_no_validate_route_returns_jsonresponse():
    runner = MagicMock(spec=CommandRunner)

    async def _run(path, user_settings, *args, **kwargs):
        return OBBject(results=[{"a": 1}])

    runner.run = _run

    async def endpoint(symbol: str = "AAPL", **kwargs):
        return OBBject(results=[{"symbol": symbol}])

    route = _make_route(endpoint)
    route.openapi_extra = {"no_validate": True}
    wrapper = build_api_wrapper(runner, route)
    out = await wrapper(symbol="AAPL")
    assert isinstance(out, JSONResponse)


@pytest.mark.asyncio
async def test_wrapper_applies_user_defaults_to_standard_params():
    """User defaults populate empty standard_params keys."""
    from dataclasses import dataclass

    from openbb_core.app.model.user_settings import UserSettings

    @dataclass
    class _SP:
        symbol: str | None = None
        limit: int | None = None

    runner = MagicMock(spec=CommandRunner)
    captured = {}

    async def _run(path, user_settings, *args, **kwargs):
        captured["kwargs"] = kwargs
        return OBBject(results=[{"a": 1}])

    runner.run = _run

    async def endpoint(standard_params=None, extra_params=None, **kwargs):
        return OBBject(results=[{"a": 1}])

    route = _make_route(endpoint)
    wrapper = build_api_wrapper(runner, route)

    fake_user_settings = UserSettings()
    fake_user_settings.defaults.commands = {  # type: ignore[attr-defined]
        "api.v1.x": {"symbol": "AAPL", "limit": 10}
    }
    out = await wrapper(
        standard_params=_SP(),
        extra_params=_SP(),
        __authenticated_user_settings=fake_user_settings,
    )
    assert isinstance(out, OBBject)
    assert captured["kwargs"]["standard_params"]["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_wrapper_injects_dependencies_into_kwargs():
    """Route dependencies are injected into ``kwargs``-accepting endpoints."""

    def get_thing():
        return "the-thing"

    runner = MagicMock(spec=CommandRunner)
    captured = {}

    async def _run(path, user_settings, *args, **kwargs):
        captured["kwargs"] = kwargs
        return OBBject(results=[{"a": 1}])

    runner.run = _run

    async def endpoint(**kwargs):
        return OBBject(results=[{"a": 1}])

    route = APIRoute(
        path="/api/v1/x",
        endpoint=endpoint,
        methods=["GET"],
        dependencies=[Depends(get_thing)],
    )
    wrapper = build_api_wrapper(runner, route)
    await wrapper()
    assert captured["kwargs"]["kwargs"]["thing"] == "the-thing"


@pytest.mark.asyncio
async def test_wrapper_skips_none_dependency_callable():
    runner = MagicMock(spec=CommandRunner)
    captured = {}

    async def _run(path, user_settings, *args, **kwargs):
        captured["kwargs"] = kwargs
        return OBBject(results=[{"a": 1}])

    runner.run = _run

    async def endpoint(**kwargs):
        return OBBject(results=[{"a": 1}])

    route = APIRoute(path="/api/v1/x", endpoint=endpoint, methods=["GET"])
    route.dependencies = [Depends(None)]
    wrapper = build_api_wrapper(runner, route)
    await wrapper()
    assert captured["kwargs"]["kwargs"] == {}


@pytest.mark.asyncio
async def test_wrapper_defaults_do_not_override_existing_values():
    from dataclasses import dataclass

    from openbb_core.app.model.user_settings import UserSettings

    @dataclass
    class _SP:
        symbol: str | None = "MSFT"

    @dataclass
    class _EP:
        limit: int | None = 5

    runner = MagicMock(spec=CommandRunner)
    captured = {}

    async def _run(path, user_settings, *args, **kwargs):
        captured["kwargs"] = kwargs
        return OBBject(results=[{"a": 1}])

    runner.run = _run

    async def endpoint(standard_params=None, extra_params=None, **kwargs):
        return OBBject(results=[{"a": 1}])

    route = _make_route(endpoint)
    wrapper = build_api_wrapper(runner, route)

    fake_user_settings = UserSettings()
    fake_user_settings.defaults.commands = {  # type: ignore[attr-defined]
        "api.v1.x": {"symbol": "AAPL", "limit": 10}
    }
    await wrapper(
        standard_params=_SP(),
        extra_params=_EP(),
        __authenticated_user_settings=fake_user_settings,
    )

    assert captured["kwargs"]["standard_params"]["symbol"] == "MSFT"
    assert captured["kwargs"]["extra_params"]["limit"] == 5


@pytest.mark.asyncio
async def test_wrapper_serialization_error_raises_openbb_error():
    """If JSONResponse serialization fails for an extension-modified output, OpenBBError is raised."""
    from openbb_core.app.model.abstract.error import OpenBBError

    runner = MagicMock(spec=CommandRunner)

    async def _run(path, user_settings, *args, **kwargs):
        out = OBBject(results=[{"a": 1}])
        out._extension_modified = True  # type: ignore[attr-defined]
        return out

    runner.run = _run

    async def endpoint(**kwargs):
        return OBBject(results=[{"a": 1}])

    route = _make_route(endpoint)
    wrapper = build_api_wrapper(runner, route)
    with (
        patch(
            "openbb_core.api.router.commands.jsonable_encoder",
            side_effect=RuntimeError("boom"),
        ),
        pytest.raises(OpenBBError, match="Error serializing"),
    ):
        await wrapper()


def test_add_command_map_wraps_and_includes_plugin_routes(monkeypatch):
    from fastapi import APIRouter

    async def endpoint():
        return OBBject(results=[{"a": 1}])

    plugins_api_router = APIRouter()
    plugins_api_router.add_api_route("/plugin", endpoint, methods=["GET"])
    plugins_router = type("PR", (), {"api_router": plugins_api_router})()

    async def wrapped():
        return OBBject(results=[{"a": 1}])

    monkeypatch.setattr(
        "openbb_core.api.router.commands.RouterLoader.from_extensions",
        lambda: plugins_router,
    )
    monkeypatch.setattr(
        "openbb_core.api.router.commands.build_api_wrapper",
        lambda command_runner, route: wrapped,
    )

    api_router = APIRouter()
    add_command_map(MagicMock(spec=CommandRunner), api_router)

    from openbb_core.app.route_iter import iter_api_routes

    assert plugins_api_router.routes[0].endpoint is wrapped
    assert any(
        getattr(route, "path", None) == "/plugin"
        for route in iter_api_routes(api_router)
    )


def test_add_command_map_skips_non_apiroute_leaf(monkeypatch):
    """A resolved route whose leaf is not an ``APIRoute`` is skipped, not wrapped."""
    from fastapi import APIRouter

    plugins_api_router = APIRouter()
    plugins_router = type("PR", (), {"api_router": plugins_api_router})()

    # Not an APIRoute -> `build_api_wrapper` must never be reached.
    mount = MagicMock(spec=[])

    monkeypatch.setattr(
        "openbb_core.api.router.commands.RouterLoader.from_extensions",
        lambda: plugins_router,
    )
    monkeypatch.setattr(
        "openbb_core.api.router.commands.iter_api_routes",
        lambda _router: iter([mount]),
    )

    def _boom(command_runner, route):
        raise AssertionError("build_api_wrapper should not be called")

    monkeypatch.setattr("openbb_core.api.router.commands.build_api_wrapper", _boom)

    api_router = APIRouter()
    add_command_map(MagicMock(spec=CommandRunner), api_router)

    assert plugins_api_router.routes == []


def test_build_new_signature_auth_param_once_for_endpoint_on_two_routes(monkeypatch):
    """One function can back several routes (openbb-federal-reserve mounts its
    regional_* commands once per Reserve Bank). build_api_wrapper stores each
    rewritten signature on the function, so the second route must not add the
    auth parameter again."""
    from openbb_core.api.router import commands as cmds

    monkeypatch.setattr(cmds, "Env", type("E", (), {"API_AUTH": True}))

    def f(x: int) -> None: ...

    f.__signature__ = build_new_signature("/a", f)  # as build_api_wrapper does
    second = build_new_signature("/b", f)
    names = [p.name for p in second.parameters.values()]
    assert names.count("__authenticated_user_settings") == 1
    assert names[0] == "x"


def test_build_new_signature_auth_param_after_keyword_only_params(monkeypatch):
    """openbb-sec's /sec/standardized_statement takes keyword-only parameters;
    the auth parameter must be addable after them."""
    from inspect import Parameter

    from openbb_core.api.router import commands as cmds

    monkeypatch.setattr(cmds, "Env", type("E", (), {"API_AUTH": True}))

    def f(*, symbol: str, limit: int = 1) -> None: ...

    new_sig = build_new_signature("/p", f)
    assert (
        new_sig.parameters["__authenticated_user_settings"].kind
        is Parameter.KEYWORD_ONLY
    )
    assert list(new_sig.parameters)[:2] == ["symbol", "limit"]
