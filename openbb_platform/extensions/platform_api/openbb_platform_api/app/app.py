"""OpenBB Platform API launcher entry point.

Runs at import time:

1. ``parse_args`` reads the CLI flags and may swap in a custom FastAPI
   ``app`` via ``--app``.
2. The active ``app`` gets walked for platform-extension routes that
   should be excluded from auto widget generation.
3. The Workspace endpoints (``/``, ``/widgets.json``, ``/apps.json``,
   ``/agents.json``) are registered on whatever app instance is now
   active — only when the user hasn't already mounted their own at
   the same path.

``main`` is the script entry point declared in pyproject.toml; it
delegates to ``launch_api`` which calls ``uvicorn.run`` with the
parsed kwargs.
"""

import json
import logging
import os
import sys
from pathlib import Path

import uvicorn
from fastapi.responses import HTMLResponse, JSONResponse
from openbb_core.app.service.system_service import SystemService
from openbb_core.env import Env

from openbb_platform_api.app.args import parse_args
from openbb_platform_api.app.bootstrap import (
    apply_cors_from_system_service,
    check_for_platform_extensions,
)
from openbb_platform_api.service import widgets_service
from openbb_platform_api.service.agents_service import (
    get_additional_agents,
    has_additional_agents,
)
from openbb_platform_api.service.apps_service import (
    get_additional_apps,
    has_additional_apps,
    load_default_apps,
)
from openbb_platform_api.service.widgets_service import get_widgets_json
from openbb_platform_api.utils.network import check_port, get_user_settings

logger = logging.getLogger("openbb_platform_api")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
formatter = logging.Formatter("\n%(message)s\n")
handler.setFormatter(formatter)
logger.addHandler(handler)


# Adds the OpenBB Environment variables to the script process.
Env()
HOME = os.environ.get("HOME") or os.environ.get("USERPROFILE")

if not HOME:  # pragma: no cover — defensive against pristine env
    # Both ``HOME`` (POSIX) and ``USERPROFILE`` (Windows) are unset
    # only on a wholly stripped environment — no shell, no
    # ``passwd``, no Windows user profile. Real launches always have
    # one or the other; testing the absence requires module reload
    # in a process with a wiped environment, which is intrusive
    # for the rest of the test session.
    raise ValueError("HOME or USERPROFILE environment variable not set.")

CURRENT_USER_SETTINGS = os.path.join(HOME, ".openbb_platform", "user_settings.json")
# Widget filtering is optional and can be used to exclude widgets from the widgets.json file
# Alternatively, you can supply a JSON-encoded list of API paths to ignore.
WIDGET_SETTINGS = os.path.join(HOME, ".openbb_platform", "widget_settings.json")


# ---------------------------------------------------------------------------
# Module-level boot. Importing this module parses argv, may swap out
# ``app``, and registers the launcher routes. Tests that need the
# parsing path in isolation should import ``app/args`` directly rather
# than triggering the full import chain.
# ---------------------------------------------------------------------------
kwargs = parse_args()
_app = kwargs.pop("app", None)
if _app:
    app = _app
else:
    # Defer this import: ``openbb_core.api.rest_api`` triggers
    # ``AppLoader.from_extensions`` and walks every installed extension
    # to mount routers — heavy in a large environment. When the user
    # supplied their own app via ``--app``, none of that work is needed
    # and importing it just to drop ``default_app`` would waste seconds
    # of startup time and a lot of memory.
    from openbb_core.api.rest_api import app as default_app

    app = default_app


# Ensure CORS is wired from SystemService for every code path —
# ``--app`` (already handled inside ``import_app`` but the helper
# is idempotent so the second call is a no-op), ``--spec`` (the
# proxy app has no CORS otherwise — OPTIONS preflight returns 405),
# and the default ``rest_api`` app (which already has CORS, also
# skipped via dedup). Placing the call here guarantees a single
# source of truth at module import time.
apply_cors_from_system_service(app)


# Apply user-defined HTTP middleware hooks from the layered TOML
# config — runs once at module import, before any request hits the
# app. Reading the config a second time here is cheap (TOML parse is
# microseconds; ``main.py`` already validated it) and avoids
# threading a config object through ``parse_args``.
def _apply_configured_middleware() -> None:
    """Pull ``[middleware] hooks`` from the bootstrapped config and
    register each entrypoint as an HTTP middleware on ``app``. The
    list runs outermost-to-innermost in TOML order; failures raise
    loudly at startup so misconfigurations don't silently passthrough.

    Reads from ``get_bootstrapped_config()`` rather than re-running
    the cascade — ``main.py``'s bootstrap is the only step that sniffs
    ``--config-file`` from argv, so reusing its result is the only way
    to see the same merged config here.
    """
    from openbb_platform_api.app.config import get_bootstrapped_config
    from openbb_platform_api.app.middleware import apply_http_middleware_hooks

    layered = get_bootstrapped_config()
    hooks = (layered.get("middleware") or {}).get("hooks")
    apply_http_middleware_hooks(app, hooks)


_apply_configured_middleware()

WIDGETS_PATH = kwargs.pop("widgets-json", None)
APPS_PATH = kwargs.pop("apps-json", None)
EDITABLE = kwargs.pop("editable", None) is True or WIDGETS_PATH is not None
DEFAULT_APPS_PATH = os.environ.get(
    "OPENBB_DEFAULT_APPS_PATH",
    Path(__file__).absolute().parents[1] / "assets" / "default_apps.json",
)
AGENTS_PATH = kwargs.pop("agents-json", None)
build = kwargs.pop("build", True)
build = False if kwargs.pop("no-build", None) else build
dont_filter = kwargs.pop("no-filter", False)
widget_exclude_filter: list = kwargs.pop("exclude", [])
uvicorn_settings = (
    SystemService().system_settings.python_settings.model_dump().get("uvicorn", {})
)
obb_headers = {"X-Backend-Type": "OpenBB Platform"}

for key, value in uvicorn_settings.items():
    if key not in kwargs and key != "app" and value is not None:
        kwargs[key] = value

if not dont_filter and os.path.exists(WIDGET_SETTINGS):
    with open(WIDGET_SETTINGS, encoding="utf-8") as widget_settings_file:
        try:
            widget_exclude_filter_json = json.load(widget_settings_file).get(
                "exclude", []
            )
            if isinstance(widget_exclude_filter_json, list):
                widget_exclude_filter.extend(widget_exclude_filter_json)
        except json.JSONDecodeError as e:
            logger.info("Error loading widget filter settings -> %s", e)


widget_exclude_filter = check_for_platform_extensions(app, widget_exclude_filter)
openapi = app.openapi()
current_settings = get_user_settings(CURRENT_USER_SETTINGS)
widgets_json = get_widgets_json(
    build, openapi, widget_exclude_filter, EDITABLE, WIDGETS_PATH, app
)
APPS_PATH = (
    APPS_PATH
    if APPS_PATH
    else (
        current_settings.get("preferences", {}).get(
            "data_directory", HOME + "/OpenBBUserData"
        )
        + "/workspace_apps.json"
    )
)


@app.get("/")
async def root():
    """Serve the landing page HTML content."""
    html_path = Path(__file__).parents[1] / "assets" / "landing_page.html"
    with open(html_path, encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


# Check if the app has already defined widgets.json at the root.
has_root_widgets = any(getattr(d, "path", "") == "/widgets.json" for d in app.routes)

if not has_root_widgets:
    # We assume that if an app already has /widgets.json at the app root,
    # we can leave it alone. Otherwise, use our endpoint to serve and/or generate.
    @app.get("/widgets.json")
    async def get_widgets():
        """Widgets configuration file for the OpenBB Workspace.

        Two modes:

        * **Editable** — re-load the on-disk ``widgets.json`` on every
          request so manual edits to the file are picked up live with no
          server restart. The file is created at startup if it doesn't
          already exist; subsequent requests just stream the file's
          current contents.
        * **Ephemeral** — serve the in-memory build that ran at startup.
          ``FIRST_RUN`` flips on the first request so any router-attached
          widget discovery happens once, then the cached dict is reused.
        """
        if EDITABLE:
            # Editable always loads from disk — including the first
            # request — so the user's hand edits are reflected without
            # a restart. Bypassing the FIRST_RUN cache here is the whole
            # point of the flag.
            return JSONResponse(
                content=get_widgets_json(
                    False, openapi, widget_exclude_filter, EDITABLE, WIDGETS_PATH, app
                ),
                headers=obb_headers,
            )
        if widgets_service.FIRST_RUN is True:
            widgets_service.FIRST_RUN = False
        return JSONResponse(content=widgets_json, headers=obb_headers)

else:
    # Populate the local name `get_widgets` with the endpoint function
    # of the existing root /widgets.json route so callers (e.g.
    # get_apps_json) can await it. ``app.routes`` returns
    # ``BaseRoute`` instances that don't expose ``endpoint`` —
    # ``getattr`` keeps the attribute access uniform whether the
    # matched object is an ``APIRoute`` (has ``endpoint``) or
    # something else (Mount, static-files route — falls back to the
    # local async wrapper below).
    root_route = next(
        (r for r in app.routes if getattr(r, "path", "") == "/widgets.json"), None
    )
    _root_endpoint = getattr(root_route, "endpoint", None) if root_route else None
    if _root_endpoint is not None:
        get_widgets = _root_endpoint
    else:
        # Fallback mechanism
        async def get_widgets():
            """Return the generated widgets.json"""
            return JSONResponse(content=widgets_json, headers=obb_headers)


# Check if the app has already defined apps.json at the root.
has_root_apps = any(getattr(d, "path", "") == "/apps.json" for d in app.routes)

if not has_root_apps:

    @app.get("/apps.json")
    async def get_apps_json():
        """Get the apps.json file."""
        new_templates: list = []
        default_templates: list = []
        widgets = await get_widgets()

        if not os.path.exists(APPS_PATH):
            apps_dir = os.path.dirname(APPS_PATH)
            if not os.path.exists(apps_dir):
                os.makedirs(apps_dir, exist_ok=True)
            # Write an empty file for the user to add exported apps from Workspace to.
            with open(APPS_PATH, "w", encoding="utf-8") as templates_file:
                templates_file.write(json.dumps([]))

        if os.path.exists(DEFAULT_APPS_PATH):
            default_templates = load_default_apps(DEFAULT_APPS_PATH)

        if has_additional_apps(app):
            additional_apps = await get_additional_apps(app)

            if additional_apps:
                for apps in additional_apps.values():
                    if not apps:
                        continue
                    if apps and isinstance(apps, list):
                        default_templates.extend(apps)
                    elif apps and not isinstance(apps, list):
                        logger.error(
                            "TypeError: Invalid apps.json format. Expected a list[dict] got %s instead -> %s",
                            type(apps),
                            str(apps),
                        )

        if os.path.exists(APPS_PATH):
            with open(APPS_PATH, encoding="utf-8") as templates_file:
                templates = json.load(templates_file)

            if isinstance(templates, dict):
                templates = [templates]

            templates.extend(default_templates)

            for template in templates:
                if _id := template.get("id"):
                    if _id in widgets and template not in new_templates:
                        new_templates.append(template)
                        continue
                elif template.get("layout") or template.get("tabs"):
                    if _tabs := template.get("tabs"):
                        for v in _tabs.values():
                            if v.get("layout", []) and all(
                                item.get("i", "").startswith("rich_note")
                                or item.get("i") in widgets_json
                                for item in v.get("layout")
                            ):
                                new_templates.append(template)
                                break
                    elif (
                        template.get("layout")
                        and all(
                            item.get("i", "").startswith("rich_note")
                            or item.get("i") in widgets_json
                            for item in template["layout"]
                        )
                        and template not in new_templates
                    ):
                        new_templates.append(template)

            if new_templates:
                return JSONResponse(content=new_templates, headers=obb_headers)

        return JSONResponse(content=[], headers=obb_headers)


if AGENTS_PATH:

    @app.get("/agents.json")
    async def get_agents():
        """Get the agents.json file."""
        if os.path.exists(AGENTS_PATH):
            with open(AGENTS_PATH, encoding="utf-8") as f:
                agents = json.load(f)
            return JSONResponse(content=agents, headers=obb_headers)
        return JSONResponse(content={}, headers=obb_headers)


# Check if the app has already defined agents.json at the root.
has_root_agents = any(getattr(d, "path", "") == "/agents.json" for d in app.routes)

if not has_root_agents and has_additional_agents(app):

    @app.get("/agents.json")
    async def get_agents_json():
        """Get the agents.json file."""
        new_agents: dict = {}
        additional_agents = await get_additional_agents(app)
        if additional_agents:
            for path_agents in additional_agents.values():
                for k, v in path_agents.items():
                    new_agents[k] = v
        return JSONResponse(content=new_agents, headers=obb_headers)

else:

    @app.get("/agents.json")
    async def get_agents_json():
        """Get an empty agents.json file."""
        return {}


def launch_api(**_kwargs):  # noqa: PLR0912
    """Start the API server.

    Validates / clamps the host/port from kwargs (or env vars), probes
    for a free port via ``check_port`` if the requested one is taken,
    and hands off to ``uvicorn.run`` with the launcher's module path so
    the FastAPI app instance imported here is the one served.
    """
    host = _kwargs.pop("host", os.getenv("OPENBB_API_HOST", "127.0.0.1"))
    if not host:
        logger.info(
            "OPENBB_API_HOST is set incorrectly. It should be an IP address or hostname."
        )
        host = input("Enter the host IP address or hostname: ")
        if not host:
            host = "127.0.0.1"

    port = _kwargs.pop("port", os.getenv("OPENBB_API_PORT", "6900"))

    try:
        port = int(port)
    except ValueError:
        logger.info("OPENBB_API_PORT is set incorrectly. It should be an port number.")
        port = input("Enter the port number: ")
        try:
            port = int(port)
        except ValueError:
            logger.info("Invalid port number. Defaulting to 6900.")
            port = 6900
    if port < 1025:
        port = 6900
        logger.info("Invalid port number, must be above 1024. Defaulting to 6900.")

    free_port = check_port(host, port)

    if free_port != port:
        logger.info("Port %d is already in use. Using port %d.", port, free_port)
        port = free_port

    if "use_colors" not in _kwargs:
        _kwargs["use_colors"] = "win" not in sys.platform or os.name != "nt"

    _msg = (
        "\nTo access this data from OpenBB Workspace, use the link displayed after the application startup completes."
        "\nChrome is the recommended browser. Other browsers may conflict or require additional configuration."
        f"\n{f'Documentation is available at {app.docs_url}.' if app.docs_url else ''}"
    )
    logger.info(_msg)
    # Everything left in _kwargs at this point is an unrecognized flag meant
    # for uvicorn.run itself; its parameters are underscored (ssl_keyfile,
    # proxy_headers, ...), but parse_args only ever strips the leading "--".
    _kwargs = {k.replace("-", "_"): v for k, v in _kwargs.items()}
    uvicorn.run("openbb_platform_api.main:app", host=host, port=port, **_kwargs)


def main():
    """Launch the API."""
    launch_api(**kwargs)


if __name__ == "__main__":  # pragma: no cover — script entry
    # Direct ``python -m openbb_platform_api.app.app`` invocation.
    # The console script declared in ``pyproject.toml`` calls
    # ``main()`` via ``main:main`` instead, so this branch only fires
    # for manual debugging.
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
