---
name: trader-alerts
description: >-
  Price Alerts. Rings when a price, a stop or the opening bell hits. Turns
  the trade plan into three alerts in one go (the stop, the target and "flat
  by close" at your flat-by time), plus above / below / stop / target levels,
  percent moves from the previous close, any time of day, and the NYSE
  opening bell, each ringing once so you are not spammed. Knows NYSE hours
  with the 2026 and 2027 holidays and 1:00 p.m. early closes, works out New
  York time itself, fetches free delayed quotes (Yahoo chart JSON, Stooq
  CSV) one ticker at a time, and writes trader/prices.json for sizing and the
  risk check. Use when the user says "alert me when", "tell me if TSLA hits",
  "watch my stop", "watch my trade", "remind me to close by 3:55", "is the
  market open", "when does the market open", "get me a price", or right
  after /trader-exit writes a plan.
argument-hint: "[ticker] [price]"
---

# trader-alerts

Price Alerts watches the numbers so the user does not have to stare at a
chart. An alert is information, never an order: when a stop alert rings,
nothing is sold by this skill. With a bracket order the stop-loss and the
take-profit already sit at the broker and do the work; the alerts tell the
user what happened and when it is time to be flat.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" clock                          # NYSE open or closed, next open
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --from-plan                # stop, target, flat by close from trader/plan.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --opening-bell
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol TSLA --stop 358.32
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol TSLA --target 370.04
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --at 15:55 --label "flat by close" --before-close
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol KO --pct 3
python3 "${CLAUDE_SKILL_DIR}/alerts.py" check                          # exit 0 = something rang
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote TSLA --write             # -> trader/prices.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote --holdings --write       # portfolio + plan tickers
python3 "${CLAUDE_SKILL_DIR}/alerts.py" list
python3 "${CLAUDE_SKILL_DIR}/alerts.py" reset tsla-plan-stop
```

`--now "2026-10-19 15:55"` pins the clock (New York time); `--offline DIR`
reads saved quote files instead of the network.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/plan.json` | the trade from trader-exit, for `add --from-plan` |
| `trader/alerts.json` | the rules (`alerts.example.json` in this folder) |
| `trader/state/alerts.json` | which rules rang and when, so each rings once |
| `trader/prices.json` | the latest quotes, merged in, for trader-budget and trader-risk |
| `trader/portfolio.json` | the tickers held, for `quote --holdings` |

## Rule types

| type | rings when | rings again |
| --- | --- | --- |
| `above` / `target` | price at or above `price` | after `reset`, or on its own if `"rearm": true` and the price fell back |
| `below` / `stop` | price at or below `price` | same |
| `pct_move` | moved `pct` percent from the previous close (or `ref`), optional `direction` up or down | once per day at most |
| `time` | the New York clock passed `at` ("15:55") on a trading day | once per trading day |
| `opening_bell` | the NYSE is open | once per trading day |

A rule with `"date"` is watched on that New York date only; `--from-plan`
rules carry the plan's date, so yesterday's stop never rings today. A `time`
rule with `"before_close": true` moves 3 hours earlier on a 1:00 p.m. early
close, so "flat by close" at 15:55 rings at 12:55 on those days.

## Quotes

- `yahoo` (default): `query2.finance.yahoo.com/v8/finance/chart/<TICKER>`, an
  unofficial free JSON endpoint, one request per ticker, half a second apart.
  On a 429 it waits and tries once more; on a 429 or a 5xx after that it
  tries `query1`. It identifies itself as `day-trader-skill/2.0`.
- `stooq`: `stooq.com/q/l/?s=tsla.us&f=sd2t2ohlcv&h&e=csv`, Stooq's free CSV.
  It answered 404 on 2026-10-13; the parser stays for when it is back.
- Free quotes are unofficial, delayed and can lag. They are fine for alerts
  and for checking a size, not for timing an order. The broker's price is the
  one that fills. Each price in `trader/prices.json` keeps its quote time, and
  trader-risk only uses one under 15 minutes old.
- If both are down, read the price from the broker connector (Alpaca
  `get_stock_snapshot`, IBKR `get_price_snapshot`) and write it into
  `trader/prices.json` as `{"as_of": "...Z", "prices": {"TSLA": 366.48}}`.

## The NYSE clock

Regular session 9:30 a.m. to 4:00 p.m. New York time, closed on weekends and
on these holidays, from nyse.com/markets/hours-calendars (read 2026-10-13):

- 2026: Jan 1, Jan 19, Feb 16, Apr 3 (Good Friday), May 25, Jun 19, Jul 3
  (Independence Day observed), Sep 7, Nov 26, Dec 25. Early close 1:00 p.m. on
  Nov 27 and Dec 24.
- 2027: Jan 1, Jan 18, Feb 15, Mar 26 (Good Friday), May 31, Jun 18
  (Juneteenth observed), Jul 5 (Independence Day observed), Sep 6, Nov 25,
  Dec 24 (Christmas observed). Early close 1:00 p.m. on Nov 26.

Daylight saving time is worked out in the tool, so it needs no time zone
files and ignores the computer's own zone. For any other year it says the
holiday list is unknown.

## Steps

1. Right after trader-exit writes the plan, run `add --from-plan`. Confirm
   the three alerts back to the user: the stop, the target and the flat-by time.
2. Run `check` while the trade is open: every few minutes from a Claude
   scheduled task or `/loop`. Each run fetches only the tickers in today's
   rules and rings each alert once. A check reads the latest delayed quote;
   it is not a live feed, and a price can pass a level between two checks.
3. Tell the user what rang in one line each. A stop or target alert means the
   bracket order has probably filled: check `get_open_position` and record the
   fill with trader-broker. "Flat by close" means close anything still open:
   trader-broker `flatten`, then trader-risk, then the user's yes. Never act
   for them.

## Example: the reel

TSLA on Monday 2026-10-19: entry 364.18 at 10:15 AM, stop 358.32, target
370.04, flat by 15:55. `add --from-plan` writes `tsla-plan-stop`,
`tsla-plan-target` and `tsla-flat-by` for that day. A `check` at 10:53 reads
the real 10:52 quote, 366.48, between the stop and the target:

```
NYSE OPEN (2026-10-19 10:53 New York, regular session).
Nothing hit. 3 rule(s) watched today, TSLA $366.48.
```

At 3:55 PM:

```
ALERT Flat by close: it is 15:55 New York (set for 15:55), the market closes at 16:00. If TSLA is still
open, close it: trader-broker flatten --symbol TSLA builds the sell ticket, then trader-risk and your yes.
```

It rings once. The next morning the plan's three alerts are no longer
watched; with `add --opening-bell`, the bell rings at 9:30.

## Rules

- An alert is a fact about a price or the clock. Say it as a fact.
- Never present a quote as live. Free quotes are delayed and unofficial.
- Confirm every new rule back to the user: ticker, type, level, day.

## What it never does

It never places, cancels or changes an order, never claims a quote is
live, and never predicts where a price is going.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`). Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except trader-broker, and only when all three hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and the
  user clicked Allow once on Claude's own card because the order tool is set to "Needs approval"
  (Customize > Connectors > tool permissions). Never set an order tool to "Always allow".
- No options, margin, short selling or leverage unless the config allows it and the user confirms.
- Broker keys live in environment variables or the Claude Desktop config, never in the chat.
