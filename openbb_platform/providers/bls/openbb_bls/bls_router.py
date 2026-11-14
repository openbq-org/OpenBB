"""BLS Router.

Thin assembly point that mounts one sub-router per survey topic. Each topic
lives in its own module under ``openbb_bls.routers`` so that the routes,
file-viewer choices/download endpoints, and chart packages for a survey are
co-located. Sub-routers are merged with no path prefix, so the public
``/bls/<command>`` routes are unchanged.
"""

import json
from pathlib import Path

from openbb_core.app.router import Router

from openbb_bls import ECONOMY_INSTALLED
from openbb_bls.routers.ces import router as ces_router
from openbb_bls.routers.core import router as core_router
from openbb_bls.routers.cpi import router as cpi_router
from openbb_bls.routers.jolts import router as jolts_router
from openbb_bls.routers.ppi import router as ppi_router
from openbb_bls.routers.productivity import router as productivity_router
from openbb_bls.routers.realer import router as realer_router
from openbb_bls.routers.ximpim import router as ximpim_router

router = Router(prefix="", description="BLS provider router.")

for _subrouter in (
    cpi_router,
    ppi_router,
    jolts_router,
    ces_router,
    productivity_router,
    realer_router,
    ximpim_router,
    core_router,
):
    router.include_router(_subrouter)

_APPS_JSON = Path(__file__).parent / "assets" / "apps.json"

# Calendar is exposed under Economy, while Search & Series use its ``survey``
# namespace when ``openbb_economy`` is installed. All three use standalone
# ``/bls`` commands otherwise.
# The template stores the Economy-namespaced widget IDs; rewrite them to the
# standalone IDs when Economy is absent so the dashboard resolves either way.
_STANDALONE_WIDGET_IDS: dict[str, str] = {
    "economy_calendar_bls_obb": "bls_calendar_bls_obb",
    "economy_survey_bls_search_bls_obb": "bls_search_bls_obb",
    "economy_survey_bls_series_bls_obb": "bls_series_bls_obb",
}


@router.api_router.get("/apps.json", include_in_schema=False)
async def bls_apps() -> list:
    """Serve the bundled BLS dashboard template (``assets/apps.json``).

    Calendar, Search & Series widget IDs match the active install:
    Economy-namespaced when ``openbb_economy`` is present, standalone
    ``/bls`` IDs when it is not.
    """
    apps = json.loads(_APPS_JSON.read_text(encoding="utf-8"))
    if not ECONOMY_INSTALLED:
        for app in apps:
            for tab in app.get("tabs", {}).values():
                for widget in tab.get("layout", []):
                    widget["i"] = _STANDALONE_WIDGET_IDS.get(
                        widget.get("i"), widget.get("i")
                    )
            for group in app.get("groups", []):
                # Only groups that link widgets explicitly by id need rewriting;
                # paramName-linked groups carry no ``widgetIds`` and must be left
                # untouched (injecting an empty list would unlink them).
                if "widgetIds" in group:
                    group["widgetIds"] = [
                        _STANDALONE_WIDGET_IDS.get(wid, wid)
                        for wid in group["widgetIds"]
                    ]
    return apps
