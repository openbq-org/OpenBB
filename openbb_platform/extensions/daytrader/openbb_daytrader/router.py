"""Day Trader router: the day-trader-skill pipeline as OpenBB commands.

Every command runs one vendored skill script in the shared workdir, so
Claude Code (`.claude/skills/trader-*`), the Python `obb.daytrader.*`
interface, the REST API, OpenBB Workspace widgets and the MCP server all
read and write the same `trader/` state.

No command here can place an order. Execution stays with the
`trader-broker` skill in Claude, behind its three gates (risk PASS, the
user's typed yes, the Allow once card).
"""

import os
from typing import Annotated, Any, Literal

from fastapi import Query
from openbb_core.app.model.example import APIEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_daytrader import runner
from openbb_daytrader.runner import flags

router = Router(prefix="", description="Day trading desk: scan, plan, size, check.")

CATEGORY = "Day Trader"

Now = Annotated[
    str | None,
    Query(description='Pretend it is this New York time, e.g. "2026-10-19 10:15".'),
]


def _widget(name: str, sub: str, data_key: str | None = None, **extra: Any) -> dict:
    cfg: dict[str, Any] = {
        "name": name,
        "category": CATEGORY,
        "subCategory": sub,
        "source": ["day-trader-skill"],
    }
    if data_key:
        cfg["dataKey"] = data_key
    cfg.update(extra)
    return cfg


@router.command(
    methods=["GET"],
    widget_config=_widget(
        "Chart Scanner", "1. Scan", "hits", gridData={"w": 40, "h": 14}
    ),
    examples=[
        APIEx(parameters={"mode": "orb", "symbols": "TSLA,AAPL,NVDA"}),
        APIEx(parameters={"mode": "daily", "limit": 500}),
    ],
)
def scanner(
    mode: Annotated[
        Literal["orb", "daily"],
        Query(
            description="orb: opening-range breakouts so far today. daily: pre-market setups."
        ),
    ] = "orb",
    symbols: Annotated[
        str | None,
        Query(description="Comma-separated tickers instead of the whole universe."),
    ] = None,
    limit: Annotated[
        int | None, Query(description="Scan only the first N symbols.")
    ] = None,
    min_price: Annotated[float | None, Query(description="Minimum price.")] = None,
    at: Annotated[
        str | None, Query(description="orb only: cut the clock at HH:MM New York.")
    ] = None,
    write: Annotated[bool, Query(description="Write trader/watchlist.json.")] = True,
    now: Now = None,
) -> OBBject[Any]:
    """Scan charts for setups (trader-scanner)."""
    args = [mode, "--json", "--quiet"]
    args += flags(
        symbols=symbols, limit=limit, min_price=min_price, now=now, no_write=not write
    )
    if mode == "orb":
        args += flags(at=at)
    return OBBject(results=runner.run("scanner", args))


@router.command(
    methods=["GET"],
    widget_config=_widget(
        "Trade News Monitor", "1. Scan", "items", gridData={"w": 40, "h": 14}
    ),
    examples=[APIEx(parameters={"tickers": "TSLA", "hours": 12})],
)
def news(
    tickers: Annotated[
        str | None,
        Query(
            description="Comma-separated tickers. Default: watchlist + plan + portfolio."
        ),
    ] = None,
    hours: Annotated[float, Query(description="Ignore items older than this.")] = 48,
    sec: Annotated[bool, Query(description="Include SEC 8-K filings.")] = True,
    mark_seen: Annotated[
        bool, Query(description="Update trader/state/news.json so items show once.")
    ] = False,
    now: Annotated[
        str | None, Query(description="ISO time, for reproducible runs.")
    ] = None,
) -> OBBject[Any]:
    """Headlines, 8-Ks and the day's move per ticker (trader-news)."""
    args = ["--json"] + flags(
        tickers=tickers.replace(",", " ").split() if tickers else None,
        hours=hours,
        no_sec=not sec,
        dry_run=not mark_seen,
        now=now,
    )
    return OBBject(results=runner.run("news", args))


@router.command(
    methods=["GET"],
    widget_config=_widget("Entry Timer", "2. Plan"),
    examples=[APIEx(parameters={"symbol": "TSLA", "setup": "orb"})],
)
def entry(
    symbol: Annotated[str, Query(description="Ticker to check.")],
    setup: Annotated[
        Literal["orb", "level"], Query(description="Setup to time.")
    ] = "orb",
    level: Annotated[
        float | None, Query(description="Price to close above (setup=level).")
    ] = None,
    interval: Annotated[Literal["5m", "1m"], Query(description="Bar size.")] = "5m",
    or_minutes: Annotated[int, Query(description="Opening range length.")] = 15,
    write: Annotated[bool, Query(description="Write trader/entry.json.")] = True,
    now: Now = None,
) -> OBBject[Any]:
    """Is the setup waiting, triggered or expired (trader-entry)."""
    args = ["check", symbol.upper(), "--json"]
    args += flags(
        setup=setup,
        level=level,
        interval=interval,
        or_minutes=or_minutes,
        now=now,
        write=write,
    )
    return OBBject(results=runner.run("entry", args))


@router.command(
    methods=["GET"],
    widget_config=_widget("Exit Planner", "2. Plan"),
    examples=[APIEx(parameters={"stop": "or-mid", "target": "1R"})],
)
def exit_plan(
    stop: Annotated[
        str | None,
        Query(description="or-mid (default), or-low, price:X, pct:X, atr:K."),
    ] = None,
    target: Annotated[
        str | None, Query(description="2R (default), 1R, 1.5R, price:X.")
    ] = None,
    symbol: Annotated[
        str | None, Query(description="Plan without trader/entry.json.")
    ] = None,
    entry: Annotated[float | None, Query(description="Entry price.")] = None,
    or_high: Annotated[float | None, Query(description="Opening range high.")] = None,
    or_low: Annotated[float | None, Query(description="Opening range low.")] = None,
    flat_by: Annotated[
        str | None, Query(description="HH:MM New York, default 15:55.")
    ] = None,
    write: Annotated[bool, Query(description="Write trader/plan.json.")] = True,
    now: Now = None,
) -> OBBject[Any]:
    """Set the stop, the target and the flat-by time (trader-exit)."""
    args = ["plan", "--json"] + flags(
        stop=stop,
        target=target,
        symbol=symbol.upper() if symbol else None,
        entry=entry,
        or_high=or_high,
        or_low=or_low,
        flat_by=flat_by,
        now=now,
        write=write,
    )
    return OBBject(results=runner.run("exit", args))


@router.command(
    methods=["GET"],
    widget_config=_widget("Time Machine", "3. Test"),
    examples=[APIEx(parameters={"replays": 10000, "seed": 19})],
)
def timemachine(
    replays: Annotated[
        int, Query(description="Simulated sessions.", ge=100, le=100000)
    ] = 10000,
    seed: Annotated[
        int, Query(description="Random seed, so a run can be repeated.")
    ] = 19,
    write: Annotated[bool, Query(description="Write trader/timemachine.json.")] = True,
    now: Now = None,
) -> OBBject[Any]:
    """Replay trader/plan.json 10,000 times plus every past session (trader-timemachine)."""
    args = ["run", "--json"] + flags(replays=replays, seed=seed, now=now, write=write)
    return OBBject(results=runner.run("timemachine", args))


@router.command(
    methods=["GET"],
    widget_config=_widget("Position Sizer", "3. Test", "orders"),
    examples=[APIEx(parameters={"budget": 5000})],
)
def size(
    budget: Annotated[
        float | None, Query(description="Override the config budget.")
    ] = None,
    write: Annotated[bool, Query(description="Write trader/orders.json.")] = True,
    now: Now = None,
) -> OBBject[Any]:
    """Size trader/plan.json to the budget and max loss (trader-budget)."""
    args = ["--json"] + flags(budget=budget, now=now, write=write)
    return OBBject(results=runner.run("budget", args))


@router.command(
    methods=["GET"],
    widget_config=_widget("Risk Check", "4. Check", "results"),
    examples=[APIEx(parameters={})],
)
def risk(
    record: Annotated[
        bool,
        Query(
            description="Record verdicts in trader/state/risk.json (needed for READY)."
        ),
    ] = True,
    now: Now = None,
) -> OBBject[Any]:
    """PASS or BLOCK every order in trader/orders.json (trader-risk)."""
    args = ["--json"] + flags(now=now, no_write=not record)
    return OBBject(results=runner.run("risk", args))


@router.command(
    methods=["GET"],
    widget_config=_widget("Order Tickets", "4. Check", gridData={"w": 40, "h": 10}),
    examples=[APIEx(parameters={})],
)
def tickets(now: Now = None) -> OBBject[Any]:
    """Read-only order tickets, READY or not (trader-broker show).

    Placing an order is not available here: ask Claude, the trader-broker
    skill needs your typed yes for that exact order.
    """
    data = runner.run("broker", ["show", "--json"] + flags(now=now))
    return OBBject(results=data if isinstance(data, list) else [data])


@router.command(
    methods=["GET"],
    widget_config=_widget("Price Alerts", "5. Manage", "rings", refetchInterval=60000),
    examples=[APIEx(parameters={})],
)
def alerts(
    record: Annotated[
        bool,
        Query(
            description="Record rings in trader/state/alerts.json so each rings once."
        ),
    ] = False,
    now: Now = None,
) -> OBBject[Any]:
    """Check every alert rule in trader/alerts.json (trader-alerts)."""
    args = ["check", "--json"] + flags(now=now, no_write=not record)
    return OBBject(results=runner.run("alerts", args))


@router.command(
    methods=["GET"],
    widget_config=_widget(
        "Market Clock", "5. Manage", refetchInterval=60000, gridData={"w": 12, "h": 6}
    ),
    examples=[APIEx(parameters={})],
)
def clock(now: Now = None) -> OBBject[Any]:
    """Is the NYSE open, and when it opens or closes next (trader-alerts)."""
    return OBBject(results=runner.run("alerts", ["clock", "--json"] + flags(now=now)))


@router.command(
    methods=["GET"],
    widget_config=_widget("Earnings Analyst", "6. Research"),
    examples=[APIEx(parameters={"symbol": "AAPL", "quarters": 6})],
)
def analyst(
    symbol: Annotated[str, Query(description="Comma-separated tickers.")],
    quarters: Annotated[int, Query(description="Quarters to show.", ge=1, le=20)] = 6,
) -> OBBject[Any]:
    """Quarterly revenue, margins, EPS and growth from SEC EDGAR (trader-analyst)."""
    tickers = [t.upper() for t in symbol.replace(",", " ").split()]
    data = runner.run("analyst", [*tickers, "--json", "--quarters", str(quarters)])
    rows: list[dict] = []
    for item in data if isinstance(data, list) else []:
        result = item.get("result") or {}
        if item.get("error") or not result:
            rows.append({"ticker": item.get("ticker"), "error": item.get("error")})
        for row in result.get("rows", []):
            rows.append(
                {"ticker": item.get("ticker"), "entity": result.get("entity"), **row}
            )
    return OBBject(results=rows)


@router.command(
    methods=["GET"],
    widget_config=_widget("Congress Trades", "6. Research"),
    examples=[APIEx(parameters={"member": "pelosi"})],
)
def congress(
    member: Annotated[
        str | None, Query(description="Last name filter, e.g. pelosi.")
    ] = None,
    year: Annotated[
        int | None, Query(description="Filing year (default this year).")
    ] = None,
    limit: Annotated[int, Query(description="Filings to list.", ge=1)] = 50,
) -> OBBject[Any]:
    """House periodic transaction reports from the yearly index (trader-pelosi)."""
    args = ["index", "--json"] + flags(member=member, year=year, limit=limit)
    return OBBject(results=runner.run("pelosi", args))


@router.command(
    methods=["GET"],
    widget_config=_widget("Desk State", "0. Desk", gridData={"w": 20, "h": 12}),
    examples=[APIEx(parameters={"name": "plan"})],
)
def state(
    name: Annotated[
        Literal[
            "watchlist",
            "entry",
            "plan",
            "timemachine",
            "orders",
            "portfolio",
            "config",
            "alerts",
            "risk",
            "broker",
        ],
        Query(description="Which trader/ file to read."),
    ] = "plan",
) -> OBBject[Any]:
    """Read one file of the shared trader/ state, as the skills left it."""
    return OBBject(results=runner.read_state(name))


_GATEWAY: list = []


async def _broker(method: str) -> OBBject[Any]:
    from openbb_daytrader.ibkr import BrokerError, Gateway, Settings

    if not _GATEWAY:
        settings = Settings.from_env()
        # one id per process: openbb-api and openbb-mcp both load this router,
        # and the ibkr MCP server holds IBKR_CLIENT_ID itself
        settings.client_id = 100 + os.getpid() % 800
        _GATEWAY.append(Gateway(settings))
    try:
        return OBBject(results=await getattr(_GATEWAY[0], method)())
    except BrokerError as exc:
        from openbb_core.app.model.abstract.error import OpenBBError

        raise OpenBBError(str(exc)) from exc


@router.command(
    methods=["GET"],
    widget_config=_widget("IBKR Account", "7. Broker", gridData={"w": 20, "h": 8}),
    examples=[APIEx(parameters={})],
)
async def broker_account() -> OBBject[Any]:
    """Interactive Brokers account summary via the local IB Gateway (read-only)."""
    return await _broker("account")


@router.command(
    methods=["GET"],
    widget_config=_widget("IBKR Positions", "7. Broker", refetchInterval=30000),
    examples=[APIEx(parameters={})],
)
async def broker_positions() -> OBBject[Any]:
    """Open positions at Interactive Brokers (read-only)."""
    return await _broker("positions")


@router.command(
    methods=["GET"],
    widget_config=_widget("IBKR Orders", "7. Broker", refetchInterval=30000),
    examples=[APIEx(parameters={})],
)
async def broker_orders() -> OBBject[Any]:
    """Open orders at Interactive Brokers, bracket legs included (read-only)."""
    return await _broker("open_orders")
