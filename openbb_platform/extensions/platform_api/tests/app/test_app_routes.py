"""Targeted tests for ``openbb_platform_api.app.app`` route handlers
and ``launch_api`` / ``main``.

The legacy ``tests/app/test_app.py`` exercises ``get_apps_json`` and
``parse_args`` already; this file fills the remaining gaps:

* ``root`` (landing-page handler)
* ``get_widgets`` in all three flow modes
* ``get_agents`` and ``get_agents_json`` variants
* ``launch_api`` env / port / host normalization + ``uvicorn.run``
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_root_serves_landing_page_html(tmp_path):
    """The root handler reads ``assets/landing_page.html`` and returns
    its contents as ``HTMLResponse``.
    """
    import asyncio

    from openbb_platform_api.app import app as app_module

    html_path = tmp_path / "landing_page.html"
    html_path.write_text("<html>hello</html>")

    fake_module_file = tmp_path / "child" / "app.py"
    fake_module_file.parent.mkdir()
    fake_module_file.write_text("")
    # Patch the file the route reads from. The handler builds the path
    # via ``Path(__file__).parents[1] / "assets" / ...``; mock the file
    # contents instead of relocating the lookup.
    real_file = (
        os.path.dirname(os.path.abspath(app_module.__file__))
        + "/../assets/landing_page.html"
    )
    if not os.path.exists(real_file):
        # Real assets dir not present in this checkout — skip.
        import pytest

        pytest.skip("landing_page.html not present in this checkout")
    response = asyncio.run(app_module.root())
    assert response.status_code == 200
    assert b"<html" in response.body or b"<!DOCTYPE" in response.body


def test_get_widgets_non_editable_first_run_serves_cached_build():
    """Non-editable + first request → cached build, ``FIRST_RUN`` flips
    to ``False`` afterwards. Editable mode bypasses this branch entirely
    (separate test below).
    """
    import asyncio

    from openbb_platform_api.app import app as app_module
    from openbb_platform_api.service import widgets_service

    original_first_run = widgets_service.FIRST_RUN
    original_widgets_json = app_module.widgets_json
    original_editable = app_module.EDITABLE
    widgets_service.FIRST_RUN = True
    app_module.EDITABLE = False
    app_module.widgets_json = {"cached": {"name": "Cached"}}
    try:
        response = asyncio.run(app_module.get_widgets())
        assert json.loads(response.body) == {"cached": {"name": "Cached"}}
        assert widgets_service.FIRST_RUN is False
    finally:
        widgets_service.FIRST_RUN = original_first_run
        app_module.widgets_json = original_widgets_json
        app_module.EDITABLE = original_editable


def test_get_widgets_editable_mode_loads_from_disk_on_every_request():
    """Editable mode loads ``widgets.json`` from disk on EVERY request
    — including the first one — so manual edits to the file are
    reflected without a server restart. The cached startup build is
    bypassed so the first request never returns a stale snapshot.
    """
    import asyncio

    from openbb_platform_api.app import app as app_module
    from openbb_platform_api.service import widgets_service

    original_first_run = widgets_service.FIRST_RUN
    original_editable = app_module.EDITABLE
    app_module.EDITABLE = True
    try:
        # Even with FIRST_RUN True, editable must still load from disk.
        widgets_service.FIRST_RUN = True
        with patch.object(
            app_module,
            "get_widgets_json",
            return_value={"from_disk_first": {"name": "First"}},
        ) as mock_load:
            first = asyncio.run(app_module.get_widgets())
        assert json.loads(first.body) == {"from_disk_first": {"name": "First"}}
        mock_load.assert_called_once()
        # FIRST_RUN intentionally NOT toggled by the editable branch —
        # editable doesn't depend on it; the flag is only meaningful for
        # the non-editable cache path.

        # Subsequent request also loads from disk (no caching).
        with patch.object(
            app_module,
            "get_widgets_json",
            return_value={"from_disk_second": {"name": "Second"}},
        ) as mock_load_2:
            second = asyncio.run(app_module.get_widgets())
        assert json.loads(second.body) == {"from_disk_second": {"name": "Second"}}
        mock_load_2.assert_called_once()
    finally:
        widgets_service.FIRST_RUN = original_first_run
        app_module.EDITABLE = original_editable


def test_get_widgets_non_editable_serves_cached_after_first_run():
    """Non-editable mode after first run → still hand back the cached
    widgets_json dict, no rebuild.
    """
    import asyncio

    from openbb_platform_api.app import app as app_module
    from openbb_platform_api.service import widgets_service

    original_first_run = widgets_service.FIRST_RUN
    original_editable = app_module.EDITABLE
    original_widgets = app_module.widgets_json
    widgets_service.FIRST_RUN = False
    app_module.EDITABLE = False
    app_module.widgets_json = {"cached": {"name": "Cached"}}
    try:
        with patch.object(
            app_module,
            "get_widgets_json",
            return_value={"NOT_THIS": "Should not be called"},
        ) as mock_build:
            response = asyncio.run(app_module.get_widgets())
        # Cached path returns the snapshot, not the rebuild.
        mock_build.assert_not_called()
        assert json.loads(response.body) == {"cached": {"name": "Cached"}}
    finally:
        widgets_service.FIRST_RUN = original_first_run
        app_module.EDITABLE = original_editable
        app_module.widgets_json = original_widgets


def test_get_agents_json_returns_empty_when_no_additional_or_explicit_path():
    """The default ``get_agents_json`` returns an empty dict when
    nothing's been wired up.
    """
    import asyncio

    from openbb_platform_api.app import app as app_module

    out = asyncio.run(app_module.get_agents_json())
    assert out == {}


def test_launch_api_invokes_uvicorn_run_with_normalized_host_and_port():
    """Happy path: explicit host / port → uvicorn.run invoked once with
    those values + ``use_colors`` derived from platform.
    """
    from openbb_platform_api.app import app as app_module

    with (
        patch.object(app_module.uvicorn, "run") as mock_run,
        patch.object(app_module, "check_port", return_value=8000),
    ):
        app_module.launch_api(host="127.0.0.1", port=8000)
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0] == "openbb_platform_api.main:app"
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8000
    assert "use_colors" in kwargs


def test_launch_api_normalizes_hyphenated_uvicorn_flags():
    """Flags with internal hyphens (e.g. ``--ssl-keyfile``) survive
    ``parse_args`` as literally-hyphenated dict keys; uvicorn's own
    signature only accepts the underscored form.
    """
    from openbb_platform_api.app import app as app_module

    with (
        patch.object(app_module.uvicorn, "run") as mock_run,
        patch.object(app_module, "check_port", return_value=8000),
    ):
        app_module.launch_api(
            host="127.0.0.1",
            port=8000,
            **{"ssl-keyfile": "/tmp/x.pem", "proxy-headers": True},
        )
    mock_run.assert_called_once()
    _, kwargs = mock_run.call_args
    assert kwargs["ssl_keyfile"] == "/tmp/x.pem"
    assert kwargs["proxy_headers"] is True
    assert "ssl-keyfile" not in kwargs
    assert "proxy-headers" not in kwargs


def test_launch_api_uses_env_vars_when_kwargs_omit_host_and_port(monkeypatch):
    """``OPENBB_API_HOST`` / ``OPENBB_API_PORT`` are the env-var defaults."""
    from openbb_platform_api.app import app as app_module

    monkeypatch.setenv("OPENBB_API_HOST", "0.0.0.0")  # noqa: S104 — container deploy fixture
    monkeypatch.setenv("OPENBB_API_PORT", "8123")
    with (
        patch.object(app_module.uvicorn, "run") as mock_run,
        patch.object(app_module, "check_port", return_value=8123),
    ):
        app_module.launch_api()
    args, kwargs = mock_run.call_args
    assert kwargs["host"] == "0.0.0.0"  # noqa: S104 — container deploy fixture
    assert kwargs["port"] == 8123


def test_launch_api_prompts_for_host_when_env_var_empty(monkeypatch, capsys):
    """Empty ``OPENBB_API_HOST`` → input prompt, fallback to default."""
    from openbb_platform_api.app import app as app_module

    monkeypatch.setenv("OPENBB_API_HOST", "")
    monkeypatch.setenv("OPENBB_API_PORT", "8000")
    # First input() returns empty too → falls back to 127.0.0.1.
    with (
        patch("builtins.input", side_effect=[""]),
        patch.object(app_module.uvicorn, "run") as mock_run,
        patch.object(app_module, "check_port", return_value=8000),
    ):
        app_module.launch_api()
    _, kwargs = mock_run.call_args
    assert kwargs["host"] == "127.0.0.1"


def test_launch_api_prompts_when_env_host_set_to_invalid_value(monkeypatch):
    """Empty host string → prompt, then use what the user typed."""
    from openbb_platform_api.app import app as app_module

    monkeypatch.setenv("OPENBB_API_HOST", "")
    with (
        patch("builtins.input", side_effect=["192.168.1.1"]),
        patch.object(app_module.uvicorn, "run") as mock_run,
        patch.object(app_module, "check_port", return_value=8000),
    ):
        app_module.launch_api(port=8000)
    _, kwargs = mock_run.call_args
    assert kwargs["host"] == "192.168.1.1"


def test_launch_api_clamps_low_port_to_default():
    """Port below 1024 → forced to 6900 with a log message."""
    from openbb_platform_api.app import app as app_module

    with (
        patch.object(app_module.uvicorn, "run") as mock_run,
        patch.object(app_module, "check_port", return_value=6900),
    ):
        app_module.launch_api(host="127.0.0.1", port=80)
    _, kwargs = mock_run.call_args
    assert kwargs["port"] == 6900


def test_launch_api_recovers_from_non_numeric_port_via_input(monkeypatch):
    """Non-numeric port → input prompt; user supplies a valid port."""
    from openbb_platform_api.app import app as app_module

    with (
        patch("builtins.input", side_effect=["8080"]),
        patch.object(app_module.uvicorn, "run") as mock_run,
        patch.object(app_module, "check_port", return_value=8080),
    ):
        app_module.launch_api(host="127.0.0.1", port="not-a-port")
    _, kwargs = mock_run.call_args
    assert kwargs["port"] == 8080


def test_launch_api_falls_back_to_6900_when_input_also_invalid():
    """Invalid env port AND invalid input → defaults to 6900."""
    from openbb_platform_api.app import app as app_module

    with (
        patch("builtins.input", side_effect=["still-not-a-number"]),
        patch.object(app_module.uvicorn, "run") as mock_run,
        patch.object(app_module, "check_port", return_value=6900),
    ):
        app_module.launch_api(host="127.0.0.1", port="bogus")
    _, kwargs = mock_run.call_args
    assert kwargs["port"] == 6900


def test_launch_api_advances_to_next_free_port_when_taken():
    """When ``check_port`` reports a different port back, ``launch_api``
    uses the alternative without prompting the user.
    """
    from openbb_platform_api.app import app as app_module

    with (
        patch.object(app_module.uvicorn, "run") as mock_run,
        patch.object(app_module, "check_port", return_value=6901),
    ):
        app_module.launch_api(host="127.0.0.1", port=6900)
    _, kwargs = mock_run.call_args
    assert kwargs["port"] == 6901


def test_launch_api_respects_explicit_use_colors_in_kwargs():
    """A user-supplied ``use_colors`` survives — the platform-derived
    default doesn't overwrite it.
    """
    from openbb_platform_api.app import app as app_module

    with (
        patch.object(app_module.uvicorn, "run") as mock_run,
        patch.object(app_module, "check_port", return_value=8000),
    ):
        app_module.launch_api(host="127.0.0.1", port=8000, use_colors=False)
    _, kwargs = mock_run.call_args
    assert kwargs["use_colors"] is False


def test_main_delegates_to_launch_api():
    """``main()`` is a thin alias that forwards the cached argv kwargs."""
    from openbb_platform_api.app import app as app_module

    with patch.object(app_module, "launch_api") as mock_launch:
        app_module.main()
    mock_launch.assert_called_once()


def _reload_app_module_with_argv(argv: list, *, with_agents_route=False):
    """Pop and reimport ``openbb_platform_api.app.app`` with the given
    argv so module-level branches (AGENTS_PATH route, additional-agents
    handler) are taken. ``with_agents_route`` adds a stub
    ``/x/agents.json`` route to the underlying FastAPI app so the
    additional-agents merge handler gets registered.
    """
    import importlib
    import sys
    import types
    from unittest.mock import patch

    from fastapi import FastAPI

    stub_app = FastAPI()
    if with_agents_route:

        @stub_app.get("/x/agents.json")
        async def agents_x():
            return {"x": {"endpoints": {}}}

    rest_api_module = types.ModuleType("openbb_core.api.rest_api")
    rest_api_module.app = stub_app  # ty: ignore[unresolved-attribute]

    cached_to_pop = [
        "openbb_platform_api.main",
        "openbb_platform_api.app.app",
    ]
    saved = {name: sys.modules.pop(name, None) for name in cached_to_pop}

    with (
        patch("sys.argv", argv),
        patch.dict(
            sys.modules, {"openbb_core.api.rest_api": rest_api_module}, clear=False
        ),
        patch("openbb_platform_api.app.app.SystemService") as mock_system,
        patch("openbb_platform_api.app.app.parse_args", return_value={})
        if False
        else patch.dict({}, clear=False),
    ):
        mock_system.return_value.system_settings.python_settings.model_dump = lambda: {
            "uvicorn": {}
        }
        mock_system.return_value.system_settings.api_settings.prefix = "/api/v1"
        # Patch get_widgets_json so the cached build doesn't blow up the import.
        with (
            patch(
                "openbb_platform_api.service.widgets_service.get_widgets_json",
                return_value={},
            ),
            patch(
                "openbb_platform_api.app.app.check_for_platform_extensions",
                return_value=[],
            ),
        ):
            module = importlib.import_module("openbb_platform_api.app.app")

    # Restore caches.
    for name in cached_to_pop:
        if saved[name] is not None:
            sys.modules[name] = saved[name]
        else:
            sys.modules.pop(name, None)
    return module


def test_app_registers_agents_route_when_agents_path_set(tmp_path):
    """Importing the module with ``--agents-json /path`` registers a
    ``/agents.json`` route that reads from that file.
    """
    import asyncio
    import json as _json

    agents_file = tmp_path / "agents.json"
    agents_file.write_text(_json.dumps({"some_agent": {"endpoints": {}}}))

    module = _reload_app_module_with_argv(
        ["openbb-api", "--agents-json", str(agents_file)]
    )
    response = asyncio.run(module.get_agents())
    body = _json.loads(response.body)
    assert body == {"some_agent": {"endpoints": {}}}


def test_app_agents_route_returns_empty_when_file_missing(tmp_path):
    """``--agents-json /missing`` → ``/agents.json`` returns ``{}``."""
    import asyncio
    import json as _json

    missing_path = tmp_path / "nope.json"
    module = _reload_app_module_with_argv(
        ["openbb-api", "--agents-json", str(missing_path)]
    )
    response = asyncio.run(module.get_agents())
    assert _json.loads(response.body) == {}


def test_app_get_agents_json_merges_additional_agents():
    """When the FastAPI app already has additional ``/x/agents.json``
    routes (no AGENTS_PATH set), the launcher registers a merge handler
    that gathers agents from those routes — exercises lines 273-282.
    """
    import asyncio
    import json as _json

    module = _reload_app_module_with_argv(["openbb-api"], with_agents_route=True)
    response = asyncio.run(module.get_agents_json())
    body = _json.loads(response.body)
    # The stub agents route returns ``{"x": {"endpoints": {}}}``.
    assert body == {"x": {"endpoints": {}}}


@pytest.mark.parametrize(
    "catalogue, defaults",
    [
        ('[{"id": "example-app"}]', [{"id": "example-app"}]),
        ('[{"layout": [{"i": "example-app"}]}]', [{"layout": [{"i": "example-app"}]}]),
        (
            '[{"tabs": {"main": {"layout": [{"i": "example-app"}]}}}]',
            [{"tabs": {"main": {"layout": [{"i": "example-app"}]}}}],
        ),
        ("[]", []),
        ("missing", []),
        ("directory", []),
        ("", []),
        (b"\xff", []),
        ("not JSON", []),
        ("null", []),
        ('{"id": "example-app"}', []),
        ('["not an app"]', []),
        ('[{"id": ["invalid"]}]', []),
        ('[{"layout": "invalid"}]', []),
        ('[{"layout": [42]}]', []),
        ('[{"layout": [{"i": 42}]}]', []),
        ('[{"tabs": ["invalid"]}]', []),
        ('[{"tabs": {"main": "invalid"}}]', []),
        ('[{"id": "example-app"}, {"layout": [42]}]', []),
    ],
)
def test_default_apps_override_preserves_user_and_extension_apps(
    tmp_path, monkeypatch, catalogue, defaults
):
    """Invalid default catalogues must not interfere with other app sources."""
    import asyncio

    default_path = tmp_path / "default_apps.json"
    if catalogue == "directory":
        default_path.mkdir()
    elif isinstance(catalogue, bytes):
        default_path.write_bytes(catalogue)
    elif catalogue != "missing":
        default_path.write_text(catalogue)
    monkeypatch.setenv("OPENBB_DEFAULT_APPS_PATH", str(default_path))
    module = _reload_app_module_with_argv(["openbb-api"])
    assert str(default_path) == module.DEFAULT_APPS_PATH

    user_app = {"id": "user-app"}
    extension_app = {"id": "extension-app"}
    apps_path = tmp_path / "apps.json"
    apps_path.write_text(json.dumps([user_app]))
    widgets = {"user-app": {}, "example-app": {}, "extension-app": {}}

    with (
        patch.object(module, "APPS_PATH", str(apps_path)),
        patch.object(module, "get_widgets", AsyncMock(return_value=widgets)),
        patch.object(module, "widgets_json", widgets),
        patch.object(module, "has_additional_apps", return_value=True),
        patch.object(
            module,
            "get_additional_apps",
            AsyncMock(return_value={"/provider/": [extension_app]}),
        ),
    ):
        response = asyncio.run(module.get_apps_json())

    assert json.loads(response.body) == [user_app, *defaults, extension_app]


def test_default_apps_path_uses_bundled_catalogue_without_override(monkeypatch):
    """No environment override must preserve the installed examples path."""
    from pathlib import Path

    monkeypatch.delenv("OPENBB_DEFAULT_APPS_PATH", raising=False)
    module = _reload_app_module_with_argv(["openbb-api"])
    assert (
        Path(module.__file__).absolute().parents[1] / "assets" / "default_apps.json"
    ) == module.DEFAULT_APPS_PATH


def test_app_get_apps_json_extends_with_non_empty_additional_apps_list(tmp_path):
    """Non-empty list values in ``additional_apps`` get extended into
    ``default_templates`` — exercises line 207.
    """
    import asyncio

    from openbb_platform_api.app import app as app_module

    apps_path = tmp_path / "apps.json"
    apps_path.write_text("[]")

    # The matching widget id makes the template survive the filter.
    additional = {"id": "matching-app"}

    with (
        patch.object(app_module, "APPS_PATH", str(apps_path)),
        patch.object(app_module, "DEFAULT_APPS_PATH", str(tmp_path / "missing.json")),
        patch.object(app_module, "widgets_json", {"matching-app": {}}),
        patch.object(
            app_module,
            "get_widgets",
            AsyncMock(return_value={"matching-app": {}}),
        ),
        patch.object(app_module, "has_additional_apps", return_value=True),
        patch.object(
            app_module,
            "get_additional_apps",
            AsyncMock(return_value={"/x/": [additional]}),
        ),
    ):
        response = asyncio.run(app_module.get_apps_json())
    assert json.loads(response.body) == [additional]


def test_app_get_apps_json_skips_empty_apps_in_additional_dict(tmp_path):
    """An ``additional_apps`` value that's empty (``[]``) gets skipped
    via the ``if not apps: continue`` arm.
    """
    import asyncio

    from openbb_platform_api.app import app as app_module

    apps_path = tmp_path / "apps.json"
    apps_path.write_text("[]")

    with (
        patch.object(app_module, "APPS_PATH", str(apps_path)),
        patch.object(app_module, "DEFAULT_APPS_PATH", str(tmp_path / "missing.json")),
        patch.object(app_module, "widgets_json", {}),
        patch.object(app_module, "get_widgets", AsyncMock(return_value={})),
        patch.object(app_module, "has_additional_apps", return_value=True),
        patch.object(
            app_module,
            "get_additional_apps",
            AsyncMock(return_value={"/empty/": [], "/null/": None}),
        ),
    ):
        response = asyncio.run(app_module.get_apps_json())
    assert json.loads(response.body) == []


def test_app_get_apps_json_handles_dict_template_payload(tmp_path):
    """An ``apps.json`` file containing a single dict (instead of a
    list) is wrapped to a single-element list before merge — exercises
    the ``isinstance(templates, dict): templates = [templates]`` branch.
    """
    import asyncio

    from openbb_platform_api.app import app as app_module

    apps_path = tmp_path / "apps.json"
    # Single-dict payload with id matching a widget — survives the
    # template filter.
    apps_path.write_text(json.dumps({"id": "matched-widget"}))
    default_path = tmp_path / "default.json"

    with (
        patch.object(app_module, "APPS_PATH", str(apps_path)),
        patch.object(app_module, "DEFAULT_APPS_PATH", str(default_path)),
        patch.object(
            app_module,
            "get_widgets",
            AsyncMock(return_value={"matched-widget": {"name": "Match"}}),
        ),
        patch.object(app_module, "has_additional_apps", return_value=False),
    ):
        response = asyncio.run(app_module.get_apps_json())
    rendered = json.loads(response.body)
    assert rendered == [{"id": "matched-widget"}]


def test_get_apps_json_layout_template_with_matching_widgets(tmp_path):
    """An ``apps.json`` template with a ``layout`` whose items reference
    known widget ids (or ``rich_note`` placeholders) survives the
    filter; templates referencing unknown widgets are dropped.
    """
    import asyncio

    from openbb_platform_api.app import app as app_module

    apps_path = tmp_path / "apps.json"
    templates = [
        # Layout-only: all items match → kept.
        {"layout": [{"i": "wid-a"}, {"i": "rich_note_1"}]},
        # Layout-only: contains an unknown widget → dropped.
        {"layout": [{"i": "unknown"}]},
        # Tabs: matching layout in tab1 → kept.
        {"tabs": {"tab1": {"layout": [{"i": "wid-a"}]}}},
    ]
    apps_path.write_text(json.dumps(templates))
    default_path = tmp_path / "default.json"

    widgets_dict = {"wid-a": {"name": "A"}}

    with (
        patch.object(app_module, "APPS_PATH", str(apps_path)),
        patch.object(app_module, "DEFAULT_APPS_PATH", str(default_path)),
        patch.object(app_module, "widgets_json", widgets_dict),
        patch.object(
            app_module,
            "get_widgets",
            AsyncMock(return_value=widgets_dict),
        ),
        patch.object(app_module, "has_additional_apps", return_value=False),
    ):
        response = asyncio.run(app_module.get_apps_json())
    rendered = json.loads(response.body)
    # Layout-only kept, layout-with-unknown dropped, tabs kept.
    assert {"layout": [{"i": "wid-a"}, {"i": "rich_note_1"}]} in rendered
    assert {"tabs": {"tab1": {"layout": [{"i": "wid-a"}]}}} in rendered
    assert {"layout": [{"i": "unknown"}]} not in rendered


def test_get_apps_json_returns_empty_list_when_no_templates_match(tmp_path):
    """No matching templates → empty-list response (not None / 404)."""
    import asyncio

    from openbb_platform_api.app import app as app_module

    apps_path = tmp_path / "apps.json"
    apps_path.write_text(json.dumps([{"layout": [{"i": "unknown"}]}]))

    with (
        patch.object(app_module, "APPS_PATH", str(apps_path)),
        patch.object(app_module, "DEFAULT_APPS_PATH", str(tmp_path / "missing.json")),
        patch.object(app_module, "widgets_json", {}),
        patch.object(app_module, "get_widgets", AsyncMock(return_value={})),
        patch.object(app_module, "has_additional_apps", return_value=False),
    ):
        response = asyncio.run(app_module.get_apps_json())
    assert json.loads(response.body) == []


def test_get_apps_json_logs_error_for_non_list_additional_apps(tmp_path, caplog):
    """When ``get_additional_apps`` yields a non-list value for some
    path, the launcher logs an error rather than crashing.
    """
    import asyncio

    from openbb_platform_api.app import app as app_module

    apps_path = tmp_path / "apps.json"
    apps_path.write_text(json.dumps([]))

    with (
        patch.object(app_module, "APPS_PATH", str(apps_path)),
        patch.object(app_module, "DEFAULT_APPS_PATH", str(tmp_path / "missing.json")),
        patch.object(app_module, "widgets_json", {}),
        patch.object(app_module, "get_widgets", AsyncMock(return_value={})),
        patch.object(app_module, "has_additional_apps", return_value=True),
        patch.object(
            app_module,
            "get_additional_apps",
            AsyncMock(return_value={"/x/": {"not_a_list": True}}),
        ),
        patch.object(app_module.logger, "error") as mock_log_error,
    ):
        asyncio.run(app_module.get_apps_json())
    mock_log_error.assert_called()


def test_get_apps_json_skips_empty_additional_apps(tmp_path):
    """Empty list values in ``additional_apps`` get skipped (the
    ``if not apps: continue`` arm) without affecting downstream
    processing.
    """
    import asyncio

    from openbb_platform_api.app import app as app_module

    apps_path = tmp_path / "apps.json"
    apps_path.write_text(json.dumps([]))

    with (
        patch.object(app_module, "APPS_PATH", str(apps_path)),
        patch.object(app_module, "DEFAULT_APPS_PATH", str(tmp_path / "missing.json")),
        patch.object(app_module, "widgets_json", {}),
        patch.object(app_module, "get_widgets", AsyncMock(return_value={})),
        patch.object(app_module, "has_additional_apps", return_value=True),
        patch.object(
            app_module,
            "get_additional_apps",
            AsyncMock(return_value={"/empty/": []}),
        ),
    ):
        response = asyncio.run(app_module.get_apps_json())
    assert json.loads(response.body) == []


def test_get_widgets_handler_when_root_widgets_exists_returns_endpoint():
    """When the underlying app already has ``/widgets.json`` defined
    BEFORE the launcher's import, ``get_widgets`` is bound to the
    pre-existing route's endpoint. Synthesize a route to exercise the
    re-import path.
    """
    # The launcher captures ``has_root_widgets`` at import time, so we
    # exercise this by tearing down + reimporting the module with a
    # FastAPI app that already has /widgets.json.
    import sys as _sys
    import types

    from fastapi import FastAPI

    # Build the stub app with /widgets.json pre-registered.
    stub_app = FastAPI()

    @stub_app.get("/widgets.json")
    async def existing_widgets():  # noqa: D401
        return {"existing": "yes"}

    # Stub openbb_core dependencies similar to the legacy test helper.
    stub_modules = {
        "openbb_core.api.rest_api": types.SimpleNamespace(app=stub_app),
        "openbb_core.api.app_loader": MagicMock(),
        "openbb_core.app.service.user_service": MagicMock(),
        "openbb_core.app.service.system_service": MagicMock(),
        "openbb_core.env": types.SimpleNamespace(Env=lambda: None),
    }

    cached_to_pop = [
        "openbb_platform_api.main",
        "openbb_platform_api.app.app",
    ]
    saved = {name: _sys.modules.pop(name, None) for name in cached_to_pop}

    with (
        patch.dict(_sys.modules, stub_modules, clear=False),
        patch("openbb_platform_api.app.app.SystemService") as mock_system,
        patch("openbb_platform_api.app.app.parse_args", return_value={}),
        patch(
            "openbb_platform_api.app.app.check_for_platform_extensions",
            return_value=[],
        ),
        patch(
            "openbb_platform_api.app.app.get_widgets_json",
            return_value={},
        ),
    ):
        mock_system.return_value.system_settings.python_settings.model_dump = lambda: {
            "uvicorn": {}
        }
        mock_system.return_value.system_settings.api_settings.prefix = "/api/v1"
        from importlib import import_module

        module = import_module("openbb_platform_api.app.app")

    # The pre-existing route's endpoint is bound to ``module.get_widgets``.
    assert module.get_widgets is existing_widgets

    # Restore environment.
    for name in cached_to_pop:
        if saved[name] is not None:
            _sys.modules[name] = saved[name]
        else:
            _sys.modules.pop(name, None)


def test_main_help_short_circuit_skips_app_module_import():
    """``openbb-api --help`` (and ``-h``) must exit BEFORE importing
    ``openbb_platform_api.app.app`` — that module's top-level imports
    pull in ``openbb_core.*``, FastAPI, uvicorn, and the service layer,
    which is wasted work when the user just wants to see the flags.
    The short-circuit lives in ``main.py`` so the help path stays
    stdlib-only at module scope.
    """
    import sys as _sys

    import pytest

    cached_to_pop = [
        "openbb_platform_api.main",
        "openbb_platform_api.app.app",
    ]
    for flag in ("--help", "-h"):
        saved = {name: _sys.modules.pop(name, None) for name in cached_to_pop}
        try:
            with (
                patch("sys.argv", ["openbb-api", flag]),
                pytest.raises(SystemExit) as exc_info,
            ):
                from importlib import import_module

                import_module("openbb_platform_api.main")

            # Exit code 0 — clean success exit.
            assert exc_info.value.code == 0
            # ``app.app`` was NEVER imported as part of the help path.
            # If it had been, the heavy openbb_core stack would have
            # loaded; the whole point of the short-circuit is that it
            # doesn't.
            assert "openbb_platform_api.app.app" not in _sys.modules, (
                f"Importing main with {flag} loaded openbb_platform_api.app.app — "
                "the help short-circuit regressed."
            )
        finally:
            for name in cached_to_pop:
                if saved[name] is not None:
                    _sys.modules[name] = saved[name]
                else:
                    _sys.modules.pop(name, None)


def test_app_skips_default_rest_api_import_when_user_app_supplied():
    """When ``--app`` is supplied (i.e. ``parse_args`` returns an
    ``app`` key), the launcher must NOT import
    ``openbb_core.api.rest_api`` — that module pulls in
    ``RouterLoader`` / ``ExtensionLoader`` and walks every installed
    extension to mount routers, which is exactly the work the user is
    trying to skip by bringing their own app. Regression guard for the
    "unnecessarily using resources in a large environment" fix.

    Patches at the source modules (``args``, ``bootstrap``) BEFORE the
    launcher's module body executes, so when ``app.app`` does
    ``from openbb_platform_api.app.args import parse_args`` it picks up
    the mock and the deferred ``rest_api`` import is never reached.
    """
    import sys as _sys

    from fastapi import FastAPI

    user_app = FastAPI()

    cached_to_pop = [
        "openbb_platform_api.main",
        "openbb_platform_api.app.app",
        # Crucially: clear ``openbb_core.api.rest_api`` so we can detect
        # whether the launcher's import path repopulates it.
        "openbb_core.api.rest_api",
    ]
    saved = {name: _sys.modules.pop(name, None) for name in cached_to_pop}

    # ``parse_args`` must be patched at the *source* module so the
    # ``from ... import parse_args`` in app.py grabs the mock during
    # module body execution.
    fake_parse_args = MagicMock(return_value={"app": user_app})

    with (
        patch("openbb_platform_api.app.args.parse_args", fake_parse_args),
        patch("openbb_platform_api.app.app.SystemService") as mock_system,
        patch(
            "openbb_platform_api.app.app.check_for_platform_extensions",
            return_value=[],
        ),
        patch(
            "openbb_platform_api.app.app.get_widgets_json",
            return_value={},
        ),
    ):
        mock_system.return_value.system_settings.python_settings.model_dump = lambda: {
            "uvicorn": {}
        }
        mock_system.return_value.system_settings.api_settings.prefix = "/api/v1"
        from importlib import import_module

        module = import_module("openbb_platform_api.app.app")

    try:
        # The user-supplied app is what got bound — not a default.
        assert module.app is user_app
        # And the heavy ``rest_api`` module was NEVER imported as a
        # side-effect. If it had been, ``sys.modules`` would carry it.
        assert "openbb_core.api.rest_api" not in _sys.modules, (
            "openbb_core.api.rest_api was imported during app startup "
            "even though --app was supplied; the deferred-import fix "
            "regressed."
        )
    finally:
        # Restore environment so subsequent tests see the original
        # module table.
        for name in cached_to_pop:
            if saved[name] is not None:
                _sys.modules[name] = saved[name]
            else:
                _sys.modules.pop(name, None)


# ---------------------------------------------------------------------------
# Coverage for the remaining module-level branches in app.app
# ---------------------------------------------------------------------------


def _reload_app_with_overrides(
    argv: list,
    *,
    uvicorn_settings: dict | None = None,
    stub_app=None,
    check_for_platform_extensions=None,
):
    """Variant of ``_reload_app_module_with_argv`` that lets the test
    inject a ``uvicorn_settings`` payload (read by app.app's
    SystemService merge loop), a custom ``stub_app`` (to register
    pre-existing routes / mounts before the launcher rewires it),
    and a ``check_for_platform_extensions`` shim so tests of the
    file-load branch can capture the filter at the call site —
    later mutations from ``build_json`` strip starred entries.
    """
    import importlib
    import sys as _sys
    import types

    from fastapi import FastAPI

    if stub_app is None:
        stub_app = FastAPI()
    rest_api_module = types.ModuleType("openbb_core.api.rest_api")
    rest_api_module.app = stub_app  # ty: ignore[unresolved-attribute]

    cached_to_pop = [
        "openbb_platform_api.main",
        "openbb_platform_api.app.app",
    ]
    saved = {name: _sys.modules.pop(name, None) for name in cached_to_pop}

    # Passthrough on ``check_for_platform_extensions`` by default.
    # Patched at the SOURCE module (``app.bootstrap``) rather than the
    # consumer (``app.app``) because ``app.py`` does
    # ``from openbb_platform_api.app.bootstrap import check_for_platform_extensions``
    # at import time — by the time the consumer-side patch resolves
    # the target, the module body has already bound the original
    # function in the consumer namespace. Patching the source closes
    # that race because the import statement re-reads the (now-mocked)
    # attribute fresh.
    cfpe_side_effect = check_for_platform_extensions or (lambda _app, filt: filt)

    # Pre-replace attributes on the SOURCE modules — patching the
    # consumer (``openbb_platform_api.app.app.X``) is too late because
    # mock.patch's __enter__ imports the consumer first, which runs
    # the module body and binds the original X in the consumer
    # namespace BEFORE the mock replaces it. Source-module
    # replacement closes that race because the consumer's
    # ``from foo import X`` reads the (already-replaced) attribute.
    import openbb_core.app.service.system_service as _sys_svc

    import openbb_platform_api.app.bootstrap as _bs

    class _StubSystemService:
        def __init__(self, *_a, **_kw):
            self.system_settings = MagicMock()
            self.system_settings.python_settings.model_dump = lambda: {
                "uvicorn": uvicorn_settings or {}
            }
            self.system_settings.api_settings.prefix = "/api/v1"

    _orig_cfpe = _bs.check_for_platform_extensions
    _orig_sys = _sys_svc.SystemService
    _bs.check_for_platform_extensions = cfpe_side_effect
    _sys_svc.SystemService = _StubSystemService

    try:
        with (
            patch("sys.argv", argv),
            patch.dict(
                _sys.modules,
                {"openbb_core.api.rest_api": rest_api_module},
                clear=False,
            ),
            patch(
                "openbb_platform_api.service.widgets_service.get_widgets_json",
                return_value={},
            ),
        ):
            module = importlib.import_module("openbb_platform_api.app.app")
    finally:
        _bs.check_for_platform_extensions = _orig_cfpe
        _sys_svc.SystemService = _orig_sys

    for name in cached_to_pop:
        if saved[name] is not None:
            _sys.modules[name] = saved[name]
        else:
            _sys.modules.pop(name, None)
    return module


def test_uvicorn_settings_from_system_service_merge_into_kwargs(monkeypatch, tmp_path):
    """``SystemService().system_settings.python_settings`` may carry a
    ``uvicorn`` table whose entries are folded into the launcher's
    final kwargs (so a deployment can configure ``workers`` /
    ``log_level`` etc. from the OpenBB system settings file rather
    than the CLI). Existing CLI kwargs and ``app`` are preserved.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    module = _reload_app_with_overrides(
        ["openbb-api"],
        uvicorn_settings={
            "workers": 4,
            "log_level": "info",
            "app": "should-be-skipped",  # ``app`` key is filtered out
            "ignored_none": None,  # ``None`` values are skipped
        },
    )
    assert module.kwargs.get("workers") == 4
    assert module.kwargs.get("log_level") == "info"
    # The ``app`` key from uvicorn settings is filtered — the launcher
    # owns that slot.
    assert module.kwargs.get("app") != "should-be-skipped"
    # ``None`` values don't pollute kwargs.
    assert "ignored_none" not in module.kwargs


def test_widget_settings_json_filter_loaded_from_disk(monkeypatch, tmp_path):
    """When ``~/.openbb_platform/widget_settings.json`` exists, its
    ``exclude`` list is appended to the launcher's exclude filter at
    module load. Lets users persist per-machine widget filtering
    without redeploying.

    Uses a hooked ``check_for_platform_extensions`` to capture the
    filter contents AT the moment of the call — entries land in
    ``widget_exclude_filter`` between the file-load branch (line 139)
    and the call site (line 151), but ``get_widgets_json`` later
    mutates the list in place (``build_json`` strips starred entries
    into a local), so reading ``module.widget_exclude_filter`` after
    module load can't reliably show what the file contributed.
    """
    import json as _json

    captured: dict[str, list] = {}

    def capturing_check(app, filt):
        captured["filt"] = list(filt)
        return filt

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    settings_dir = tmp_path / ".openbb_platform"
    settings_dir.mkdir()
    settings_file = settings_dir / "widget_settings.json"
    settings_file.write_text(
        _json.dumps({"exclude": ["/api/v1/admin/*", "/api/v1/internal/exact_path"]})
    )

    module = _reload_app_with_overrides(
        ["openbb-api"], check_for_platform_extensions=capturing_check
    )
    # Confirm the module read OUR HOME and saw OUR file.
    assert str(tmp_path) == module.HOME
    assert str(settings_file) == module.WIDGET_SETTINGS
    # The file's exclude entries reached ``check_for_platform_extensions``,
    # which is the call between the file load and ``get_widgets_json``'s
    # in-place mutation.
    assert "/api/v1/admin/*" in captured["filt"]
    assert "/api/v1/internal/exact_path" in captured["filt"]


def test_widget_settings_json_malformed_logs_and_does_not_crash(
    monkeypatch, tmp_path, caplog
):
    """A malformed ``widget_settings.json`` is logged but doesn't
    crash module load — keeps the launcher resilient against
    user-edit corruption.
    """
    import logging

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    settings_dir = tmp_path / ".openbb_platform"
    settings_dir.mkdir()
    (settings_dir / "widget_settings.json").write_text("{not json")

    with caplog.at_level(logging.INFO, logger="openbb_platform_api"):
        module = _reload_app_with_overrides(["openbb-api"])

    # Module loaded successfully — no crash from the malformed file.
    assert isinstance(module.widget_exclude_filter, list)
    # The error was logged with a clear "Error loading" prefix.
    assert any("Error loading" in r.message for r in caplog.records)


def test_get_widgets_fallback_used_when_existing_route_has_no_endpoint(
    monkeypatch, tmp_path
):
    """When the underlying app has a ``/widgets.json`` registration
    that doesn't expose an ``endpoint`` attribute (e.g. a ``Mount``
    or static-files route), the launcher falls back to its own
    ``get_widgets`` async wrapper that returns the cached
    ``widgets_json`` dict — exercises lines 218-220.
    """
    import asyncio
    import json as _json

    from fastapi import FastAPI
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    monkeypatch.setenv("HOME", str(tmp_path))

    # Build a stub app with a ``/widgets.json`` route whose endpoint
    # is None (simulating a registration that doesn't surface a
    # callable). Use ``Route`` directly so ``has_root_widgets``
    # detects the path but ``getattr(root_route, "endpoint", None)``
    # returns falsy.
    stub_app = FastAPI()

    async def _placeholder(request):
        return PlainTextResponse("placeholder")

    custom_route = Route("/widgets.json", endpoint=_placeholder, methods=["GET"])
    # Surgically null the endpoint after registration so the launcher's
    # ``getattr(..., "endpoint", None)`` check picks the fallback path.
    stub_app.routes.append(custom_route)
    custom_route.endpoint = None  # type: ignore[assignment]

    module = _reload_app_with_overrides(["openbb-api"], stub_app=stub_app)

    # ``get_widgets`` is the fallback wrapper, NOT the existing route's
    # endpoint. Calling it returns a JSONResponse with the cached
    # widgets_json (an empty dict, since we patched
    # ``get_widgets_json`` to return {}).
    response = asyncio.run(module.get_widgets())
    assert _json.loads(response.body) == {}
