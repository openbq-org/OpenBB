"""TMX app references must match optional chart route availability."""

import pytest

from openbb_tmx import tmx_router

CHART_IDS = {
    f"tmx_derivatives_options_{name}_custom_obb"
    for name in ("term_structure", "stats", "smile", "surface")
}


@pytest.mark.parametrize("installed", [False, True])
@pytest.mark.asyncio
async def test_optional_chart_references(monkeypatch, installed):
    monkeypatch.setattr(tmx_router, "CHARTING_INSTALLED", installed, raising=False)
    apps = await tmx_router.tmx_apps()
    layout_ids = {
        w["i"]
        for app in apps
        for tab in app["tabs"].values()
        for w in tab.get("layout", [])
    }
    group_ids = {
        wid
        for app in apps
        for group in app.get("groups", [])
        for wid in group.get("widgetIds", [])
    }
    if installed:
        assert layout_ids >= CHART_IDS
        assert group_ids >= CHART_IDS
    else:
        assert not CHART_IDS & layout_ids
        assert not CHART_IDS & group_ids
        assert "tmx_derivatives_options_chains_tmx_obb" in layout_ids
