"""Resolve BLS calendar references for standalone provider installs."""

import pytest

from openbb_bls import bls_router


@pytest.mark.parametrize("installed", [False, True])
@pytest.mark.asyncio
async def test_standalone_calendar_reference(monkeypatch, installed):
    monkeypatch.setattr(bls_router, "ECONOMY_INSTALLED", installed)
    apps = await bls_router.bls_apps()
    ids = [
        w["i"]
        for app in apps
        for tab in app["tabs"].values()
        for w in tab.get("layout", [])
    ]
    expected = "economy_calendar_bls_obb" if installed else "bls_calendar_bls_obb"
    absent = "bls_calendar_bls_obb" if installed else "economy_calendar_bls_obb"
    assert expected in ids
    assert absent not in ids
