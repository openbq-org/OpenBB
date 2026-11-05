"""Day Trader extension tests (offline, on the vendored fixtures)."""

import pytest
from openbb_core.app.route_iter import iter_api_routes

from openbb_daytrader import (
    router as rt,
    runner,
)

FIX = runner.SKILLS_DIR / "tests" / "fixtures"
NOW = "2026-10-19 10:15"


@pytest.fixture(autouse=True)
def _workdir(tmp_path, monkeypatch):
    monkeypatch.setenv(runner.WORKDIR_ENV, str(tmp_path))
    return tmp_path


def test_every_script_is_vendored():
    for rel in runner.SCRIPTS.values():
        assert (runner.SKILLS_DIR / rel).is_file(), rel


def test_routes():
    paths = {getattr(r, "path", "") for r in iter_api_routes(rt.router.api_router)}
    for name in (
        "/scanner",
        "/news",
        "/entry",
        "/exit_plan",
        "/timemachine",
        "/size",
        "/risk",
        "/tickets",
        "/alerts",
        "/clock",
        "/analyst",
        "/congress",
        "/state",
    ):
        assert name in paths
    assert not any("approve" in p or "place" in p for p in paths)


def test_flags():
    assert runner.flags(
        a=None, no_write=False, write=True, or_high=1.5, tickers=["A", "B"]
    ) == [
        "--write",
        "--or-high",
        "1.5",
        "--tickers",
        "A",
        "B",
    ]


def test_pipeline_entry_exit_size_tickets(_workdir):
    entry = runner.run(
        "entry",
        [
            "check",
            "TSLA",
            "--offline",
            str(FIX / "trader-entry" / "TSLA-2026-10-19-5m.json"),
            "--now",
            NOW,
            "--json",
            "--write",
        ],
    )
    assert entry["status"] == "triggered"
    plan = rt.exit_plan(stop="or-mid", target="1R", now=NOW).results
    assert (plan["stop"], plan["target"]) == (358.32, 370.04)
    assert runner.read_state("plan")["symbol"] == "TSLA"
    sized = rt.size(budget=5000, now=NOW).results
    assert sized["orders"][0]["qty"] in (8, "8")
    tickets = rt.tickets(now=NOW).results
    assert tickets[0]["tool"] == "place_stock_order"
    assert tickets[0]["ready"] is False


def test_clock():
    out = rt.clock(now=NOW).results
    assert out["open"] is True


def test_state_missing_file_is_none():
    assert rt.state(name="orders").results is None


def test_error_is_raised():
    with pytest.raises(runner.DayTraderError):
        runner.run("pelosi", ["index", "--offline", "/nonexistent.zip"])


def test_router_builds_args(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        runner, "run", lambda skill, args: seen.update(skill=skill, args=args) or {}
    )
    rt.scanner(mode="orb", symbols="TSLA,AAPL", write=False, at="10:15")
    assert seen["skill"] == "scanner"
    assert seen["args"][:3] == ["orb", "--json", "--quiet"]
    assert "--no-write" in seen["args"] and "--at" in seen["args"]
    rt.news(tickers="TSLA,KO", hours=12)
    assert seen["args"][seen["args"].index("--tickers") + 1 :][:2] == ["TSLA", "KO"]
    assert "--dry-run" in seen["args"]
