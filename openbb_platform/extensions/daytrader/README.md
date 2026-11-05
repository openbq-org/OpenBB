# OpenBB Day Trader extension

The [day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) pack
(MIT, vendored in `openbb_daytrader/skills/`, commit in `UPSTREAM_COMMIT`) running
inside the OpenBB Platform.

One shared `trader/` folder, four ways in:

| surface | how |
| --- | --- |
| Claude Code | `/trader-scanner`, `/trader-entry` ... (repo `.claude/skills/`) |
| Python | `obb.daytrader.scanner(mode="orb")`, `obb.daytrader.exit_plan(...)` |
| REST + OpenBB Workspace | `openbb-api` → widgets under the **Day Trader** category |
| MCP (Claude Desktop / Code) | `openbb-mcp` → `daytrader_*` tools |

All of them run in `OPENBB_DAYTRADER_WORKDIR` (default: current directory), so
point them at the same folder to share the watchlist, plan, orders and risk log.

## Commands

| command | skill | writes |
| --- | --- | --- |
| `scanner` | trader-scanner | `trader/watchlist.json` |
| `news` | trader-news | `trader/state/news.json` (only with `mark_seen`) |
| `entry` | trader-entry | `trader/entry.json` |
| `exit_plan` | trader-exit | `trader/plan.json` |
| `timemachine` | trader-timemachine | `trader/timemachine.json` |
| `size` | trader-budget | `trader/orders.json` |
| `risk` | trader-risk | `trader/state/risk.json` |
| `tickets` | trader-broker `show` | nothing (read-only) |
| `alerts`, `clock` | trader-alerts | `trader/state/alerts.json` (only with `record`) |
| `analyst` | trader-analyst | nothing |
| `congress` | trader-pelosi | nothing |
| `state` | – | nothing, reads any `trader/` file |

**No command places an order.** Execution stays with the `trader-broker` skill in
Claude: risk PASS for that exact order, your typed yes, then the Allow once card.
Paper trading is the default.

SEC endpoints (news 8-Ks, analyst) need `SEC_USER_AGENT="Your Name you@example.com"`.

## Install

```bash
pip install -e openbb_platform/extensions/daytrader
openbb-build   # regenerate the static obb.* package
```

## Tests

```bash
pytest openbb_platform/extensions/daytrader/tests
cd openbb_platform/extensions/daytrader/openbb_daytrader/skills && python3 -m unittest discover -s tests
```
