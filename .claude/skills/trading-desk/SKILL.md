---
name: trading-desk
description: >-
  Trading Desk. Runs the whole day-trade loop as one agent on top of OpenBB:
  scan, news, entry, exit plan, Time Machine, sizing, risk, ticket, alerts,
  with OpenBB Platform data (quotes, options, short interest, SEC, macro) as
  a second opinion on every setup. Ranks candidates, explains the edge and
  the odds, and hands the best ticket to trader-broker. It never places an
  order on its own: every order still needs a risk PASS, the user's typed
  yes and the Allow once card. Use when the user says "run the desk",
  "find me a trade", "morning routine", "boost my trades", "what's setting
  up", "trading session", or "desk status".
argument-hint: "[premarket | open | manage | close | status]"
---

# trading-desk

The desk is the orchestrator. The eleven `trader-*` skills do the work and
write into `trader/`; OpenBB adds context. The same `trader/` folder is read
by `obb.daytrader.*`, the REST API, the OpenBB Workspace **Day Trader**
widgets and the `openbb` MCP server (`daytrader_*` tools), so whatever the
desk does shows up on the user's screens.

Hard rules, every phase:

- Broker: Interactive Brokers through the user's IB Gateway (`ibkr` MCP
  server, trader-broker Setup C). Paper unless `get_account_info` says
  `"paper": false`, which only happens when the user chose REEL in the
  launcher. Say which account it is on every ticket.
- No order without trader-risk PASS + the user's typed yes for that exact
  ticket + the Allow once card. Follow `/trader-broker` word for word.
- Never call `close_all_positions`, `cancel_all_orders`, options or crypto
  order tools.
- Say the odds honestly. Most day traders lose money; a Time Machine coin
  flip is a coin flip. "Boost" means better selection, sizing and
  discipline, never more risk than `trader/config.json` allows.
- Times are New York. Everything you decide goes in `trader/desk.md`
  (append a dated line per decision) so the user can audit it.

## Phases

`$ARGUMENTS` picks the phase; with none, pick from the clock
(`/trader-alerts` clock): before 9:30 premarket, 9:30-15:30 open, after
15:30 close, market closed status.

### premarket
1. `/trader-scanner` daily on the universe (build it first if
   `trader/universe.txt` is missing).
2. `/trader-news` on the hits, `/trader-analyst` on any hit that reports
   this week, `/trader-pelosi` new filings touching the hits.
3. OpenBB second opinion per top hit (MCP `openbb`, use `available_tools`
   to find them): options IV / put-call (cboe), short interest and dark-pool
   volume (finra), recent filings (sec), the macro calendar for the day.
4. Write a ranked watchlist to `trader/desk.md`: ticker, setup, catalyst,
   red flags (earnings today, halts, thin volume), one-line thesis.

### open
1. From 9:45 (after a 15-minute range), `/trader-scanner` orb on the
   watchlist, then `/trader-entry` on each hit.
2. For each trigger: `/trader-exit` plan, then `/trader-timemachine`.
   Drop anything whose target-first odds do not beat stop-first, or whose
   history fired fewer than 10 times, and say why.
3. Keep at most the best two by (target-first minus stop-first) and reward
   to risk. `/trader-budget`, then `/trader-risk`.
4. Show each READY ticket with `/trader-broker` and the evidence: setup,
   news, OpenBB context, Time Machine odds, max loss. Wait for the yes.
5. After a fill: `/trader-alerts` add --from-plan.

### manage
`/trader-alerts` check, `/trader-news` on open positions, `/trader-broker`
log. If a stop or target rang, record the fill. Never move a stop further
away; tightening is allowed if the user agrees.

### close
By the plan's flat-by time, `/trader-broker` flatten every open day trade
(still needs the yes). Then a recap in `trader/desk.md`: trades, P&L, rule
breaks, what the Time Machine said vs what happened.

### status
Read-only: clock, open positions, today's risk used vs the daily limit,
alerts armed, last lines of `trader/desk.md`.

## Running the screens

```bash
pip install -e openbb_platform/extensions/daytrader
openbb-api                      # REST + Workspace backend on 127.0.0.1:6900
```

In OpenBB Workspace add `http://127.0.0.1:6900` as a custom backend and
open the **Day Trader** widgets. Start the API from the folder that holds
`trader/` (or set `OPENBB_DAYTRADER_WORKDIR`) so it sees the desk's state.
