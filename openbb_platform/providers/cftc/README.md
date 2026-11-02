# CFTC Provider Extension

This package provides full access to the CFTC Commitment of Traders database.
Reports are fetched by CFTC Code (e.g. `13874+`) and returns the full history of the contract.

It also exposes the swap transaction and pricing data published by DTCC's Public Price
Dissemination service — the swap data repository for CFTC-jurisdiction trades — including
the CDS index tape, central bank overnight index swap curves, and FX forward points
constructed from executed transactions.

## Installation

Install into a Python environment (3.11 - 3.14) from PyPI with:

```sh
pip install openbb-cftc
```

Then build the Python static assets:

```sh
openbb-build
```

## Credentials

Credentials are not required, but your IP address may be subject to throttling limits on the
Commitment of Traders endpoints. The DTCC Public Price Dissemination endpoints are public and
require no credentials.

API requests made using an application token are not throttled.

Create a free account here: <https://evergreen.data.socrata.com/signup>

Then, generate the app_token by signing in with the credentials here: <https://publicreporting.cftc.gov/profile/edit/developer_settings>.

### Credentials Key

If adding a token, use `cftc_app_token` as the key in the `user_settings.json` file. The value expected value is the app_token and not the `secret` or `api_key`.

The token can be set as an environment variable:

```env
CFTC_APP_TOKEN
```

## Coverage

This extension provides a dedicated router module with eight endpoints, and one OpenBB Workspace application.

| Endpoint | Source | Description |
|:---------|:-------|:------------|
| `obb.cftc.cot` | CFTC Public Reporting | Commitment of Traders reports. |
| `obb.cftc.cot_search` | CFTC Public Reporting | Search COT report series. |
| `obb.cftc.swap_trades` | DTCC PPD slice | Swap transaction and pricing data. |
| `obb.cftc.cds_index_trades` | DTCC PPD slice | CDS index transactions, curated per print. |
| `obb.cftc.ois_curve` | DTCC PPD search | Central bank overnight index swap curve. |
| `obb.cftc.ois_curve_history` | DTCC PPD slice | OIS curve over time, by tenor. |
| `obb.cftc.ois_forward_curve` | DTCC PPD search | Forward par swap rate curve, by start date. |
| `obb.cftc.fx_forward_points` | DTCC PPD search | FX forward points for the major crosses. |

The DTCC endpoints draw on two different sources, deliberately:

- The **cumulative slice** is one zip per calendar day holding every transaction disseminated
  that day, in a 110-column CSV. It has no record cap.
- The **search** endpoint queries a date range server-side and returns JSON. It filters by UPI,
  currency and notional, but truncates at 10,000 records without saying so.

`swap_trades` stays on the slice. It is a raw feed of the published columns, its model is
CSV-shaped, and the search's schema is a different shape (116 camelCase fields that split some
of the CSV's merged columns) that would need a mapping layer for no gain — the slice already
returns a full day uncapped, which is what a raw feed should do. With no `date`, it walks back
from the newest published file to the most recent one holding transactions that match the
query, because a Saturday's file is published but nearly empty.

`ois_curve_history` also stays on the slice: it is explicitly a per-report-date series, so
per-node as-of dating would defeat its purpose.

`cds_index_trades` stays on the slice for the same reason `swap_trades` does, plus one of its
own: it is a **tape**, so it must not silently drop prints, and the search's 10,000-record cap
would do exactly that on a busy day. The slice returns a full day, uncapped.

## Methodology

A compact reference for the formulas and assumptions behind the calculated endpoints. The
discount factors `DF(t)` bootstrapped in the first block feed every block below.

### Rate curve bootstrap — `ois_curve`, `ois_curve_history`

- **Par rate** at a tenor: the median of the day's executed fixed rates (`aggregation` selects
  median / mean / vwap).
- **Discount factors**, bootstrapped from par rate `c`, with annual fixed payments and accrual
  `τ_i = days_i / b` on the currency's money-market basis `b` (360 or 365):
  - tenor ≤ 1Y (one payment): `DF = 1 / (1 + c·τ)`;
  - longer: `DF_n = (1 − c·Σ_{i<n} τ_i·DF_i) / (1 + c·τ_n)`, the `DF_i` read off the curve built
    so far.
- **Zero rate** `z`, annually compounded ACT/365F over `t` years: `DF = (1 + z)^(−t)`.
- Intermediate DFs interpolate on `log DF` (`log_linear`, or monotone Hermite `log_cubic`).
- *Assumptions:* fixed leg pays annually; negative rates admitted, so `DF > 1` is allowed and the
  curve is not required to be monotone; a node is dropped only if its bootstrapped `|z|` exceeds a
  sanity bound.

### Forward par swap rate — `ois_forward_curve`

A Nelson-Siegel-Svensson curve is fit to the bootstrapped `log DF` (trade-count weighted). The
rate of a `T`-year swap starting `t0` forward is the par rate of that forward schedule:

`f(t0, T) = (DF(t0) − DF(t0 + T)) / Σ_i τ_i·DF(t0 + t_i)`

over the swap's annual points `t_i`. A tail past the last pillar uses the extended fit and is
flagged `extrapolated`.

### Policy path — `ois_policy_path`

The forward par curve *implies* forwards off the spot curve; this reads them **directly** from
the forward-starting OIS the spot curve excludes. A forward-starting OIS over `[E, E+τ]` fixes at
the expected average compounded overnight rate over that window, so its fixed rate is a market
observation of the forward policy rate. Trades are anchored to the curve date (a start that has
rolled to spot drops out), bucketed to whole-month `(forward start, tenor)`, medianed on the most
recent day each bucket traded in depth, and sorted by start — the priced central-bank path. Its
short, meeting-dated tenors are the policy segments; `max_tenor` bounds how far up the term a
forward-starting swap is still treated as a policy point rather than a forward par rate.

### FX forward points — `fx_forward_points`

- **Rate** of a trade is quote-per-base from the leg-notional ratio (not the reported basis
  field, which flips orientation).
- **Spot** `S` is the median of the shortest-dated trades: deliverable pairs use trades settling
  ≤ 2 days; a non-deliverable pair has no spot leg, so its two shortest tenor buckets are linearly
  extrapolated back to T+2.
- **Executed points** `= (F − S)·pip`, with `F` the tenor's median forward rate and `pip` the
  quote's smallest increment (`10^4`, or `10^2` for a JPY / two-decimal EM quote).
- **Covered-interest-parity (theoretical) points:** `F_cip = S·(1 + r_q·T/b_q)/(1 + r_b·T/b_b)`.
  Each leg's simple rate is `r = (1/DF − 1)·b/days`, so `(1 + r·T/b) = 1/DF` and `F_cip` collapses
  to the factor ratio `S·DF_base/DF_quote` — basis-independent. `basis_points = executed − theoretical`
  is the cross-currency / NDF basis to onshore rates.
- An EM leg with no OIS builds `DF_quote` from its fixed-float IRS, then its non-deliverable cross
  swap — deepest source first.

### FX implied volatility — `fx_implied_vol`

- Each option is inverted with **Garman-Kohlhagen** (two-rate Black-Scholes), forward
  `F = S·DF_for/DF_dom`, implied vol solved by **bisection** on the price (out-of-the-money options
  only, since an ITM one is redundant by put-call parity).
- A **non-deliverable pair** has no domestic (EM) OIS, so its domestic DF is implied from the
  observed NDF forward: `DF_dom(t) = DF_for(t)·S / F_ndf(t)`, which makes `F` equal the traded NDF
  forward rather than a covered-parity one.
- **Empirical** surface: median vol per (grid strike, expiry). **Theoretical:** a lognormal-SABR
  smile per expiry (`β = 1`, `α` pinned to the ATM vol, `ρ`/`ν` by grid-and-refine least squares),
  evaluated on the grid.
- Strike grid: pip offsets from spot for the majors; **basis-point moneyness**,
  `K = S·(1 + offset/10^4)`, for the wider-trading NDF pairs.

### Swap valuation — `swap_valuation`

Off the bootstrapped `DF` and an annual fixed schedule to maturity `T` with annuity
`A = Σ_i τ_i·DF(t_i)`:

- **Par rate** `c* = (1 − DF(T)) / A`.
- **Fixed leg** PV `= N·c·A`; **floating leg** PV `= N·(1 − DF(T))` — the sum of the period
  forwards `f_i = (DF_{i−1}/DF_i − 1)/τ_i`, discounted, telescopes to it.
- **NPV** (pay-fixed) `= PV_float − PV_fixed`; receive-fixed is its negative. A contract at
  `c = c*` prices to zero.
- **DV01** `= N·A·10^−4`, the present value of one basis point on the fixed leg.

### Swap payoff — `swap_payoff`

The valuation is one point; the payoff is the whole curve. Holding the contract rate `c`, the
discount curve is shifted in parallel by `δ` (basis points), `DF_δ(t) = DF(t)·e^{−δ·t}`, and the
swap re-valued at each shift. The result is the mark-to-market P&L profile against rates: zero at
the entry par rate, rising for the side long rates (pay-fixed gains as rates rise), and **concave
for pay-fixed** — it is short duration, so a symmetric shift loses more than it gains. Re-pricing
off the shifted curve, rather than a straight `DV01·δ` line, is what shows that curvature.

## Usage

The package can be used as a Python module, or a REST API.

### REST API

Start the server over localhost with:

```sh
openbb-api
```

### Python

```python
from openbb import obb

search_results = obb.cftc.cot_search(query="gold")

print(search_results.to_df())
```

| code        | name               | category          | subcategory     | commodity_name   | contract_units                 |
|:------------|:-------------------|:------------------|:----------------|:-----------------|:-------------------------------|
| CFTC_088691 | GOLD               | NATURAL RESOURCES | PRECIOUS METALS | GOLD             | (CONTRACTS OF 100 TROY OUNCES) |
| CFTC_088LM1 | GOLD -1 TROY OUNCE | NATURAL RESOURCES | PRECIOUS METALS | GOLD             | (1 troy ounce x $2,300)        |
| CFTC_088695 | MICRO GOLD         | NATURAL RESOURCES | PRECIOUS METALS | GOLD             | (CONTRACTS OF 10 TROY OUNCES)  |

```python
report = obb.cftc.cot(code="CFTC_088695", measure="percent_of_oi", limit=4)
print(report.to_df().T)
```

|                                             |   2026-03-03 |   2026-03-10 |   2026-03-17 |   2026-03-24 |
|:--------------------------------------------|-------------:|-------------:|-------------:|-------------:|
| open_interest_all                           |    60933     |    58119     |    64124     |    71998     |
| open_interest_pct_all                       |        1     |        1     |        1     |        1     |
| open_interest_pct_non_commercial_long_all   |        0.186 |        0.18  |        0.168 |        0.285 |
| open_interest_pct_non_commercial_short_all  |        0.527 |        0.546 |        0.555 |        0.515 |
| open_interest_pct_non_commercial_spread     |        0.058 |        0.06  |        0.078 |        0.124 |
| open_interest_pct_commercial_long_all       |        0.088 |        0.095 |        0.091 |        0.083 |
| open_interest_pct_commercial_short_all      |        0     |        0     |        0     |        0     |
| open_interest_pct_total_reportable_long_all |        0.333 |        0.335 |        0.336 |        0.492 |
| open_interest_pct_total_reportable_short    |        0.585 |        0.606 |        0.632 |        0.64  |
| open_interest_pct_non_reportable_long_all   |        0.667 |        0.665 |        0.664 |        0.508 |
| open_interest_pct_non_reportable_short_all  |        0.415 |        0.394 |        0.368 |        0.36  |

## Overnight Index Swap Curves

`obb.cftc.ois_curve` builds a curve from the overnight index swaps reported to the CFTC.
Par rates are the median of the executed fixed rates at each tenor; discount factors are
bootstrapped from the par rates, and the zero rate is derived from the bootstrapped discount
curve. The forward rate curve is a separate endpoint, `ois_forward_curve` (see below).

Each currency references its own central bank's overnight benchmark. Currencies whose OIS is
too thinly reported to bootstrap a curve (AUD, NZD, KRW, PHP, TRY) are not offered — their
liquidity sits in fixed-float swaps against a term benchmark instead.

### Depth against staleness, and how this endpoint resolves it

Not every tenor trades every day, and a file is published every calendar day including the
ones where nothing trades. A curve built from a single day is therefore full of holes: CHF
OIS yields three nodes from one day, and a Saturday yields none at all.

Searching a **window** of dissemination days fixes the holes but introduces a worse problem
if it is done naively. A 30-day median is not today's curve — it is a 30-day-average curve,
and rates move inside the window. Buying depth with silent staleness is its own kind of lie.

So each tenor is priced from **the most recent day it actually traded in depth**, and reports
that day as `as_of_date` along with `staleness_days`. Deep tenors stay fresh; thin ones show
their age instead of hiding it in an average.

Because the search filters on the product's FISN (`NA/Swap OIS {ccy}`), not just its currency,
it returns only that currency's OIS — so even a full year of prints stays well under the
source's 10,000-record response cap. A thinly traded currency can therefore raise `lookback_days`
to reach the whole **one-year search horizon** and still price each tenor from its freshest print;
the search chains 180-day sub-windows to cover a span longer than one query allows. Widen the
window for a currency that never fills its curve from a short one — a THB, ILS or BRL — and leave
it short for USD or EUR, whose curve is dense from a week. A wide window resurrects tenors that
last traded months ago, so pair it with `max_staleness_days` to keep the curve current — covered
next.

```python
curve = obb.cftc.ois_curve(currency="CHF", lookback_days=30)
```

| tenor | as_of_date | staleness_days | num_trades | par_rate | discount_factor |
|:------|:-----------|---------------:|-----------:|---------:|----------------:|
| 1M    | 2026-07-13 |              3 |          1 | −0.000490 |        1.000041 |
| 9M    | 2026-07-02 |             14 |          1 | −0.000182 |        1.000138 |
| 1Y    | 2026-07-16 |              0 |          2 |  0.000709 |        0.999282 |
| 10Y   | 2026-07-16 |              0 |          5 |  0.006800 |        0.932928 |
| 30Y   | 2026-07-16 |              0 |          1 |  0.009400 |        0.748409 |

The 10Y is today's; the 9M is a fortnight old and says so.

### Capping staleness on a wide window

Reaching back a year fills a thin currency's curve, but not for free: a tenor that last traded
eight months ago is priced against a market that has since moved, and splicing it beside a
fresh node is a curve of two different dates pretending to be one. NZD is the clearest case — a
full-year search finds a 1M node 250 days stale sitting under a 3M node priced yesterday, and the
short end zig-zags because the two are from different regimes.

`max_staleness_days` drops any node whose freshest print is older than the cutoff, **before** the
bootstrap, so a stale off-market rate never becomes a pillar the rest of the curve discounts
through. It defaults to `None` — every node is kept and its age reported in `staleness_days`, the
same judge-for-yourself default as `min_trades` — but on a wide window it is how you keep the
result a curve rather than a mosaic:

```python
curve = obb.cftc.ois_curve(currency="NZD", lookback_days=365, max_staleness_days=30)
```

Widen `lookback_days` for reach, then tighten `max_staleness_days` for freshness; the two knobs
trade the curve's completeness against its currency, and the balance differs by how often the
currency trades.

### `min_trades` counts one day, not the window

This is the subtlety worth understanding before raising it.

`min_trades` is the number of trades a tenor must have **on a single dissemination day** to
be dated to that day. It is not a count across the window. Widening `lookback_days` gives a
tenor *more chances* to clear the bar; it does not pool trades to help it clear.

It defaults to 1: one executed trade is still a price, and dropping it would discard real
transactional data in favour of no data at all. `num_trades`, `min_rate` and `max_rate` report
how thin a node is, so the caller can judge rather than have the choice made for them.

Raising it costs whole tenors on a thin currency, because the bar is per-day:

| currency | nodes at `min_trades=1` | nodes at `min_trades=3` |
|:--|--:|--:|
| USD | 26 | 25 |
| EUR | 26 | 24 |
| GBP | 26 | 24 |
| JPY | 24 | 21 |
| CAD | 24 | 14 |
| CHF | 19 | **9** |
| CLP | 14 | 5 |

CHF short-dated OIS trades **at most once on any given day**. No day will ever carry three
1M prints, so at `min_trades=3` the CHF short end does not exist at any `lookback_days` — the
curve simply starts at 1Y. There is no setting that gives you both a dated short end and
three prints behind it, because those trades were never reported.

### Negative rates

Negative rates are real — SARON, TONA and ESTR have all printed below zero — so the bootstrap
admits them. A negative par rate discounts to *more* than 1.0, because the lender pays; CHF's
short end carries `discount_factor` above 1 and a negative `zero_rate`.

Discount factors are therefore **not** guaranteed to decrease across the curve. A monotonically
decreasing discount curve is not a no-arbitrage condition: it is equivalent to assuming every
forward rate is positive, which is untrue of CHF and JPY. The condition the bootstrap enforces
is a positive discount factor, plus a bound on the implied zero rate that rejects a node whose
par rate is so far off-market that the bootstrap degenerates.

### Sources

`source="search"` (default) queries a window of dissemination days, as above.
`source="slice"` uses a single day's cumulative file: no per-node dating, sparse tenors
missing. A file is published every calendar day, but a weekend or holiday file carries no
swaps, so `slice` walks `date` back to the most recent day that actually priced the
currency rather than returning an empty curve. It is kept as a fallback and for reproducing
a specific published file exactly.

| Currency | Index | Administrator |
|:--|:--|:--|
| USD | SOFR | Federal Reserve |
| EUR | ESTR | European Central Bank |
| GBP | SONIA | Bank of England |
| JPY | TONA | Bank of Japan |
| CAD | CORRA | Bank of Canada |
| CHF | SARON | Swiss National Bank |
| MXN | TIIE | Banco de Mexico |
| SGD | SORA | Monetary Authority of Singapore |
| INR | MIBOR | Reserve Bank of India |
| COP | IBR | Banco de la Republica |
| ZAR | ZARONIA | South African Reserve Bank |
| CLP | ICP | Banco Central de Chile |
| THB | THOR | Bank of Thailand |
| ILS | SHIR | Bank of Israel |
| BRL | CDI | Banco Central do Brasil |
| AUD | AONIA | Reserve Bank of Australia |
| NZD | NZIONA | Reserve Bank of New Zealand |

AONIA and NZIONA trade only a handful of times a day, so their curves need a long
`lookback_days` and, to stay current, a `max_staleness_days` cap (see below).

BRL's DI maturities fall on fixed calendar dates rather than rolling tenors, so they do not
snap to benchmark nodes; use `granularity="observed"` for a full BRL curve. CDI accrues on
BUS/252, recovered to the same year fraction on calendar days.

```python
from openbb import obb

curve = obb.cftc.ois_curve(currency="USD", date="2026-07-15")
print(curve.to_df())
```

The `rate` column carries the selected `curve_type` (par or zero) **in percent** — 4.32 is
4.32%, not a decimal — so the chart axis reads as a rate (the grid's percent formatter is not
applied to the chart). The par and zero values below are shown together for illustration; the
endpoint returns whichever one `curve_type` selects.

| tenor | num_trades | par (%) | zero (%) | discount_factor |
|:------|-----------:|--------:|---------:|----------------:|
| 1M    |         16 |  3.6668 |   3.7120 |        0.996954 |
| 1Y    |         90 |  4.0135 |   3.9886 |        0.960899 |
| 2Y    |        193 |  4.0203 |   3.9954 |        0.923201 |
| 10Y   |        368 |  4.1378 |   4.1281 |        0.661635 |
| 30Y   |        195 |  4.3379 |   4.3111 |        0.274126 |

### Granularity

`granularity="benchmark"` (default) snaps trades to standard nodes. `granularity="observed"`
emits a node for every distinct tenor traded, including broken dates — roughly 180 nodes on a
typical day, against 24 benchmark nodes.

### Interpolation

`interpolation` sets how discount factors are read between pillars, on the log of the discount
factor. It applies to `ois_curve`, `ois_forward_curve` and `ois_curve_history`.

- `interpolation` governs how the **bootstrap** interpolates intermediate discount factors,
  which shapes the par and zero curves (the forward curve is fitted separately, see below).
  `log_linear` (default) is piecewise linear on the log discount factors — the standard, most
  transparent choice, and the one a par-swap bootstrap is self-consistent with. `log_cubic`
  fits a monotone Hermite cubic (Fritsch–Butland slopes) to the log discount factors, smoother
  through the pillars without overshooting into a spurious negative forward.

The par rates are the curve's input and never move with `interpolation`; only the derived zero
rates and discount factors do. Tenors of one year or less are a single payment with no
interpolation, so they are identical under both schemes; longer nodes differ marginally.

### Conventions and caveats

- Par rates are aggregated with the **median** by default. Notionals above the reporting cap are
  disseminated at the cap (and flagged by `is_capped`), which biases notional-weighted averages.
- The fixed leg accrues on the day count the trades report - ACT/360 for USD/EUR/CHF/MXN/COP/CLP,
  ACT/365F for GBP/JPY/CAD/SGD/INR/ZAR/THB/ILS, and BRL's BUS/252 recovered to the same year
  fraction on calendar days - with annual payments and a single payment for tenors of one year or
  less. Zero rates are annually compounded ACT/365F, so on an upward-sloping curve the zero rate
  sits above the par rate.
- `min_trades` (default 1) keeps every node, because one executed trade is still a price. It
  counts one dissemination day's trades, not the window's — see above before raising it.
- Each node's `maturity_date` rolls off its own `as_of_date`, not the curve's date.
- `spot_only` (default True) restricts the curve to spot-starting trades, judged against the
  day each trade was disseminated rather than the end of the window.
- Discount factors are positive but not necessarily decreasing: a negative par rate discounts
  above 1.0. Derived values are withheld only where the bootstrap degenerates; the observed par
  rate is still reported.
- The search endpoint truncates at 10,000 records **without signalling it**. A window that comes
  back at exactly that count is treated as truncated and bisected until every sub-window clears
  it; a single day that still hits the cap raises rather than building a curve from an arbitrary
  subset.
- Closed dissemination days are immutable, so each is cached on disk as its own partition and
  only the current day is re-queried. Daily slice files are revalidated against the source
  `ETag`. Slice files are retained for 366 days; the search endpoint serves a rolling one year,
  which a `lookback_days` beyond 180 reaches by chaining 180-day sub-windows.

## Forward Rate Curve

`obb.cftc.ois_forward_curve` prices the forward par swap rate curve off the OIS curve - the
object Bloomberg's Forward Curve (FWCV) shows. Each point is the rate of a `forward_tenor` swap
starting that far forward, read off a **Nelson-Siegel-Svensson** (Svensson) fit to the
bootstrapped discount factors and weighted by trade count, so a thin long-end node cannot kink
it and a specific point like 5Y1Y or 1Y5Y is smooth and stable.

The swap length and the spacing between start dates are **independent**: `forward_tenor` is how
long each forward swap runs, `forward_step` is how far apart the start dates sit. So
`forward_tenor="5Y", forward_step="1Y"` plots the 5Y forward at yearly starts, matching how
Bluegamma spaces its forward curve at the tenor. `forward_count` caps how many start dates are
drawn (the next N steps); left unset the curve runs out to its last pillar. A swap whose tail
runs past the last pillar is priced off the extended fit and flagged `extrapolated` rather than
withheld, so the final start is still a real point.

```python
from openbb import obb

# the 5Y forward at yearly start dates
fwd = obb.cftc.ois_forward_curve(currency="USD", forward_tenor="5Y", forward_step="1Y")
print(fwd.to_df())
```

| index      | tenor      | start_years | forward_rate |
|:-----------|:-----------|------------:|-------------:|
| 2026-07-15 | 5Y @ 0.00Y |        0.00 |      4.0473% |
| 2027-07-15 | 5Y @ 1.00Y |        1.00 |      4.0221% |
| 2028-07-15 | 5Y @ 2.00Y |        2.00 |      4.0864% |
| 2031-07-15 | 5Y @ 5.00Y |        5.00 |      4.2861% |

The row `index` is the forward start date, so the chart reads across the dates each forward
begins; `tenor` labels the swap and its start (`5Y @ 5.00Y` is the 5Y swap five years out).

## FX Forward Points

`obb.cftc.fx_forward_points` builds forward points from the deliverable FX forwards and FX
swaps reported to the CFTC. Deliverable FX forwards and swaps are excluded from the swap
definition but remain reportable to swap data repositories, so they appear in the same data.

Spot FX is *not* reportable, so there is no spot fix in the data. Spot is proxied by the
median of trades settling within two days — overnight FX swap legs, in practice.

Tenors are dated per-tenor exactly as the OIS curve's nodes are, with one addition: **each
tenor is priced against the spot of its own as-of day**, not the curve's freshest spot. A
tenor that last traded six days ago is differenced against that day's spot, so its points
stay internally consistent instead of absorbing an unrelated spot move. `spot_rate` therefore
varies row to row whenever `staleness_days` does.

```python
from openbb import obb

points = obb.cftc.fx_forward_points(pair="USDJPY", date="2026-07-15")
print(points.to_df())
```

| tenor | num_trades | forward_rate | forward_points |
|:------|-----------:|-------------:|---------------:|
| SPOT  |          4 |   162.141038 |           0.00 |
| 1W    |         12 |   162.133000 |          −0.80 |
| 2W    |          2 |   162.053933 |          −8.71 |
| 1M    |         12 |   161.990078 |         −15.10 |
| 2M    |          7 |   161.354029 |         −78.70 |
| 3M    |          4 |   160.805970 |        −133.51 |
| 6M    |          2 |   159.128884 |        −301.22 |

### FX forward conventions and caveats

- Rates are derived from each trade's **leg notionals**, not the reported
  `Exchange rate basis`, which flips between `USD/EUR` and `EUR/USD` on the same instrument.
- **`min_notional` (default 1,000,000 base units) is load-bearing.** Sub-institutional prints
  — trades of order 10² base units — execute percent away from the interbank market. Left in,
  they dominate a tenor's median: the EURUSD 3M point moves from ~46 pips to ~292 pips, a
  level that is economically impossible for a 3M forward.
- Points are quoted in pips: 1/10,000 of the quote currency, or 1/100 against JPY.
- **Depth varies sharply by pair.** USDJPY is the best supported and is reliably monotonic;
  USDCAD and EURUSD are deep but not always monotonic — an individual bucket can print away
  from its neighbours on a given day, which is a property of the reported trades rather than
  of the construction. In the extreme, a single day's bucket dominated by off-market prints (or
  a funding squeeze, e.g. offshore CNH) can cross to the **wrong side of spot** and flip that
  tenor's sign; the median faithfully reports what traded. `num_trades` and the `min_rate` /
  `max_rate` spread — surfaced on the widget — flag such a bucket. GBPUSD and NZDUSD are thin and
  noisy. Check them before relying on a tenor.
- A tenor's `spot_rate` is its own as-of day's spot, so rows with different `staleness_days`
  are differenced against different spots. Points across such rows are each internally
  consistent but are not a single instant's curve.

### Theoretical (covered interest parity) fair value

For a pair whose two legs both have an OIS curve — USD, EUR, GBP, JPY, CHF and CAD, i.e. all
the USD majors — each tenor also carries the **covered-interest-parity** forward points
alongside the executed ones. This is the forward that neutralizes the interest-rate
differential (Lehman Brothers, *FX Training Manual*): `F = S·(1 + r_quote·T/b) / (1 + r_base·T/b)`,
where each leg's money-market rate `r` is the simple rate implied by its OIS **discount
factor** — so the forward is the factor ratio `S·DF_base/DF_quote`, independent of how the
curve compounds its zero — accruing on its own basis (365 days for GBP, JPY and CAD, 360 for
USD, EUR and CHF). The base is at a forward **premium** (points added to spot) when the quote
out-yields it, a **discount** otherwise.

- `theoretical_points` — the CIP fair value, in pips.
- `basis_points` — executed less theoretical: **positive where the market pays over CIP fair
  value, negative under**. This is the cross-currency basis the executed forwards are pricing.
- `quotation` — `premium` or `discount`, from the sign of the executed points.
- `carry` — whether a **long base-currency forward earns or pays** the points to the forward
  date: it **earns** at a discount (the base out-yields the quote, so it is bought forward below
  spot) and **pays** at a premium; the short-base side is the opposite (Lehman Brothers,
  *FX Training Manual*: pay or earn the points). `quotation` and `carry` are set for every pair.

AUDUSD and NZDUSD have no OIS curve for the foreign leg, so they carry the executed points
(and `quotation`/`carry`) but no `theoretical_points`.

## FX Implied Volatility

`obb.cftc.fx_implied_vol` inverts the **vanilla FX options** (`NA/O Van Call|Put`) reported to
the CFTC to an implied volatility, using **Garman-Kohlhagen** — the two-rate FX form of
Black-Scholes (Lehman Brothers, *FX Training Manual*: implied volatility is extracted from the
Black-Scholes formula). Each option contributes its spot, strike, tenor, and premium; the two
legs' OIS **discount factors** supply the forward and the discounting — so the pricing is
consistent with the curve rather than a re-compounded zero — and spot is the same
concurrent-forward proxy the forward points use.

```python
from openbb import obb

vol = obb.cftc.fx_implied_vol(pair="EURUSD")
print(vol.to_df())
```

The output is the **volatility surface**: one row per **strike**, one column per **expiry**. A
strike is an **actual price of the pair** — the strikes lie on a grid of **point (pip) offsets
from spot**, so spot (offset zero) is the at-the-money reference and every column shares the same
strike axis. Reading **down a column** traces that expiry's whole smile; reading **across the
spot strike** is the near-the-money term structure (values in percent, e.g. `6.15` = 6.15%).
Rendered as a table, each cell is colour-coded by its vol (green low → amber → red high), so the
smile and the term structure read at a glance — a proper heatmap rather than overlapping lines.

| Strike (USD/JPY) | pts | 1W | 1M | 3M | 6M | 1Y |
|:-----------------|----:|---:|---:|---:|---:|---:|
| 157.31 | −500 | 8.95 | 7.99 | 7.50 | 8.02 | 8.59 |
| 159.81 | −250 | 6.77 | 6.87 | 6.98 | 7.67 | 8.56 |
| 161.31 | −100 | 5.47 | 6.30 | 6.77 | 7.52 | 8.55 |
| **162.31** | **0** | 4.76 | 6.01 | 6.68 | 7.44 | 8.54 |
| 163.31 | +100 | 4.49 | 5.82 | 6.63 | 7.39 | 8.53 |
| 164.81 | +250 | 4.99 | 5.78 | 6.65 | 7.37 | 8.51 |

*(USD/JPY, theoretical basis — the downside strikes carry the higher vol, the market's standing
bid for USD/JPY downside; a negative SABR correlation captures the skew.)*

- **`basis`** picks how the surface is built:
  - **`empirical`** (default) medians the traded options at each grid strike — what actually
    traded, with **gaps** where nothing did. The vol is solved by **bisection** on the option
    price, which recovers the out-of-the-money wings a Newton step abandons where its vega
    vanishes.
  - **`theoretical`** fits each expiry's out-of-the-money prints to a **lognormal-SABR** smile
    (β = 1, `α` pinned to the observed at-the-money vol, `ρ`/`ν` found by a grid-and-refine
    least-squares) and evaluates it on the **same strike grid** — a **smooth, gap-free** smile,
    the per-expiry `(α, ρ, ν)` returned in the metadata. A fit needs strikes on both sides of the
    forward, else that expiry is skipped.
- Only out-of-the-money options are priced — an in-the-money one is redundant by put-call parity
  and its thin extrinsic value inverts to an unstable vol; the surviving puts and calls span the
  smile below and above the forward.
- Each option is only used if it **executed on the dissemination day** — an option struck days
  earlier priced against a different spot, so inverting it with today's spot would give a wrong
  vol.
- Each cell is trimmed to a plausibility band around that expiry's own median vol, so a lone
  off-market print cannot corrupt a strike.

The **spot** the whole surface hangs off is the median of the pair's shortest-dated
**deliverable** forwards (`NA/Fwd` / `NA/Swaps`). Non-deliverable forwards (`NA/Fwd NDF …`, a
scatter of off-spot strikes reported even for deliverable pairs) and vol/variance swaps are
excluded — left in, they bias spot by tens of pips and manufacture a false skew. A **cross** with
no deliverable forward of its own (e.g. GBP/JPY) is **triangulated through the dollar** from each
leg's USD pair; the result reprices the cross's own options to within a few pips of their
put-call-parity forward. Each option's **strike** is taken in whichever orientation sits closer to
spot, so a record that mislabels its strike currency pair cannot invert a near-the-money strike
into a bogus wing.

Offered for EURUSD, GBPUSD, USDJPY, USDCHF, USDCAD and EURGBP — the pairs whose options are
reported to the CFTC in enough depth to build a surface each day; the thinner crosses are left
off rather than returned empty. The two-rate pricing needs an OIS curve for each leg, priced off
the rates slice contemporaneous with the options (EURGBP triangulates its spot through the
dollar). Direction is read from the **Call and Put currency and amount** - the currency bought
and sold - not the FISN, whose `Call`/`Put` label contradicts the economic legs on a fraction of
trades. Depth is a single day's options, so on the `empirical` basis short expiries fill only
near the money and longer ones reach the wings — the `num_options` column shows the depth behind
each strike row.

## CDS Index Trades

`obb.cftc.cds_index_trades` is the credit default swap index tape: one row per disseminated
print, curated and fully typed from the credits file's 110 raw columns.

It is deliberately **not** a curve. There is no term structure to build — on 2026-07-15,
1,266 of the day's 1,338 index prints were the 5Y, against 7 at the 10Y and 7 at the 3Y. The
5Y *is* the market, and a bootstrap over the rest would be inventing a curve out of a handful
of prints.

```python
from openbb import obb

tape = obb.cftc.cds_index_trades(index="CDX.NA.HY", tenor="5Y", date="2026-07-15")
print(tape.to_df())
```

| index | maturity_date | tenor | coupon | upfront_amount | upfront_currency | notional_amount | index_factor | venue |
|:--|:--|:--|--:|--:|:--|--:|--:|:--|
| CDX.NA.HY | 2031-06-20 | 5Y | 0.05 | 1,241,583.75 | USD | 15,000,000 | 0.99 | BBSF |

A 500bp coupon, 1.24mm paid upfront on 15mm of protection, and an index factor of 0.99 — 1% of
the notional already written off by a default. That is the trade, priced without a spread.

### A CDS index is priced by coupon plus upfront

This is the whole point of the endpoint, and it comes straight from the technical
specification rather than from convention or inference.

For the credit asset class, `Other payment type` (#81) carries the validation rule:

> C, at least one is required: ([Fixed rate] or [Spread] or [Other payment type] = 'UFRO').

and `UFRO` is defined as:

> Upfront Payment, i.e., the initial payment made by one of the counterparties either to bring
> a transaction to fair value or for any other reason that may be the cause of an off-market
> transaction

The two price-carrying fields are conditional *on each other*. For credit, `Fixed rate` (#91)
is required only:

> if [Spread] is not populated and [Other payment type] ≠ 'UFRO' … else {blank}

and `Spread` (#100), symmetrically:

> if [Fixed rate] is not populated and [Other payment type] ≠ 'UFRO' … else {blank}

The specification is explicit that the generic `Price` element does not apply here. `Price`
(#93) states it is not applicable to:

> Credit default swaps and credit total return swaps, as it is understood that the information
> included in the data elements Fixed rate, Spread and Upfront payment (Other payment type:
> Upfront payment) may be interpreted as the price of the transaction.

The data agrees: `Price` is populated on **0 of 1,338** index prints. The three fields the spec
names are what price the trade, and they combine as the rule above dictates:

| Fixed rate | Spread | Upfront (UFRO) | Prints |
|:--:|:--:|:--:|--:|
| ✓ | ✓ | ✓ | 887 |
| ✓ | | ✓ | 212 |
| ✓ | | | 91 |
| ✓ | ✓ | | 79 |
| | ✓ | | 61 |
| | | ✓ | 8 |

Every print carries at least one of the three, exactly as the rule requires — and 1,269 of
1,338 carry the standardised coupon. The coupons are the index conventions and nothing else:
CDX.NA.HY and ITRAXX EUROPE CROSSOVER at `0.05`, CDX.NA.IG and ITRAXX EUROPE at `0.01`,
CMBX.NA.BBB- at `0.03`, CMBX.NA.AAA at `0.005`. So `coupon` alone never distinguishes two
trades in the same index; `upfront_amount` is what carries the price.

### Why `spread` is not the traded level

`spread` is disseminated, so it is surfaced — raw, as reported. But reading it as "the CDS
spread" is wrong twice over.

**First, the spec makes it a conditional alternative,** not a price: it is required only when
there is no fixed rate and no upfront. It is populated on 77% of index prints, against 95% for
the coupon.

**Second, the field does not always contain a spread at all.** Per the spec, notation `3` means
"value expressed as decimal (e.g., 0.0257 instead of 2.57%)" and notation `1` means a monetary
amount. On the price-quoted indices the reported number is the **price in points of par**, and
the notation merely rescales it:

| Index | Notation 3 (decimal) | Notation 1 (monetary) | What it actually is |
|:--|:--|:--|:--|
| CDX.NA.HY | 0.010788 – 0.010810 | 107.93 – 108.03 | price, ~108 points of par |
| CDX.EM | 0.009819 – 0.009825 | 98.21 – 98.25 | price, ~98 points of par |
| CDX.NA.IG | 0.001676 – 0.009121 | *(not reported)* | spread, 17 – 91bp |
| ITRAXX EUROPE CROSSOVER | 0.013345 – 0.027500 | *(not reported)* | spread, 133 – 275bp |

The two notations hold the same number, scaled by 10,000. **This is where "CDX.NA.HY trades at
108bp" comes from, and it is a misreading**: 108 is the price. High yield trades on upfront
against a 500bp coupon, and a 108bp spread against a 500bp coupon is not a thing the market
could produce.

So: read `spread` together with `spread_notation`, per index, or use `coupon` and
`upfront_amount`, which mean the same thing on every row.

### The index name has no series — maturity pins it

`index` comes from `UPI Underlier Name`, which names the **family only**: `CDX.NA.IG`, never
`CDX.NA.IG.45`. The elements that might have carried a series are not disseminated here —
`Underlying Asset Name` and `Underlier ID-Leg 1` are populated on **0 of 1,338** index prints.

`maturity_date` (the spec's `Expiration date`, #142) is therefore load-bearing: it is the only
field separating one series from another, and it is surfaced for exactly that reason.

```python
obb.cftc.cds_index_trades(index="CDX.NA.IG", tenor="5Y", date="2026-07-15")
```

returns both the on-the-run 5Y maturing 2031-06-20 and the previous series maturing
2030-12-20. Both are "the 5Y"; only the maturity tells them apart.

`tenor` is **derived, not disseminated**: it is the years from `execution_timestamp` to
`maturity_date`, snapped to the nearest standard CDS index tenor within one year. Two
consequences worth knowing:

- An off-the-run series keeps the tenor it is quoted at. The 2030-12-20 print above is 4.43
  years from execution and is labelled `5Y`, because that is what it is.
- `Execution timestamp` "remains unchanged throughout the life of the UTI", so on a correction
  or termination the tenor describes the **original** trade, not time remaining today.
- CMBX and other long-dated underliers fall outside the standard grid and keep a rounded year
  count instead (`31Y`, `39Y`), rather than being forced onto a CDS tenor they do not trade.

### Scope and caveats

- **Included:** the index FISNs `NA/CDS Corp Idx`, `NA/CDS Corp Idx Tra` (tranches) and
  `NA/CDS Sov Idx`. **Excluded:** single names (`NA/CDS Corp SN`), baskets, and index
  swaptions (`NA/CDS Idx Swt`) — a swaption prices off a strike and premium rather than a
  coupon, and its `UPI Underlier Name` carries the FISN string instead of an index name, so it
  cannot be filtered by index at all. Check `upi_fisn` to separate tranche prints; the
  `CDS index attachment point` and `detachment point` elements are **not** publicly
  disseminated (P43 Reported = N), so a tranche cannot be identified by its attachment level.
- **There is no per-message dissemination timestamp in this data.** The spec defines one
  (`Dissemination timestamp`, #D3, "to the nearest second"), but the cumulative slice does not
  carry the column — the file's report date *is* the dissemination day. The endpoint therefore
  reports `dissemination_date`, alongside the spec's `event_timestamp` and
  `execution_timestamp`, which are per-print and exact.
- **`cleared` is `I` or `N`, never `Y`** (1,184 / 153 on the sample day). Part 43 disseminates
  the original swap, and `I` is
  "Intent to clear, for alpha transactions that are planned to be submitted to clearing". This
  is why `venue` is well populated: `Platform identifier` is "C if [Cleared] = 'N' or 'I'; NR
  if [Cleared] = 'Y'".
- Notionals above the reporting cap are disseminated at the cap and flagged by `is_capped`
  (178 of 1,338 prints on the sample day). When the notional is capped the SDR must
  proportionally scale the other disseminated amounts, so a capped print's `upfront_amount` is
  scaled too — do not read it as dollars against the true notional.
- **`min_notional` therefore has a trap.** It compares against the *disseminated* notional, and
  a capped notional is only a floor on the real one. The caps vary by index, tenor and currency
  — on the sample day USD prints capped at 50mm, 76mm, 250mm and 400mm — so a threshold above a
  cap silently drops capped prints that may be far larger than it. Filter on `is_capped` to see
  them.
- `index` matching is **exact** and case-insensitive, not a substring match: `ITRAXX EUROPE` is
  a prefix of `ITRAXX EUROPE CROSSOVER` and `ITRAXX EUROPE SENIOR FINANCIALS`, and a substring
  filter would silently conflate three different indices.
- The `index` dropdown lists the families observed in a sampled day's file and is a convenience,
  not a whitelist — the parameter is free text, so an index absent from the list still filters.
- The tape includes every action type (`NEWT`, `MODI`, `CORR`, `EROR`, `TERM`), because all of
  them are disseminated prints — a tape that silently dropped corrections would not be the
  tape. There is no `action_type` parameter; `action_type` and `original_dissemination_identifier`
  are columns, so filtering to new trades is `df[df.action_type == "NEWT"]`.
- `index_factor` is below 1 once a constituent has defaulted; multiplied by `notional_amount`
  it yields the notional actually covered by the seller of protection.

## Report Types

Reports can be filtered by measure, or include all reported fields. Report types come as 'Futures Only', or 'Combined' (futures and options combined positions), selectable by setting the `futures_only` boolean parameter.

### Legacy

The Legacy report is broken down by exchange with reported open interest further broken down into three trader classifications: commercial, non-commercial and non-reportable.

### Disaggregated

The Disaggregated reports are broken down by Agriculture and Natural Resource contracts. The Disaggregated reports break down reportable open interest positions into four classifications: Producer/Merchant, Swap Dealers, Managed Money and Other Reportables.

### Financial

The Traders in Financial Futures (TFF) report includes financial contracts. The TFF report breaks down the reported open interest into five classifications: Dealer, Asset Manager, Leveraged Money, Other Reportables and Non-Reportables.

### Supplemental

The Supplemental report includes 13 select agricultural commodity contracts for combined futures and options positions. Supplemental reports break down the reportable open interest positions into three trader classifications: non-commercial, commercial, and index traders.

Visit the CFTC [website](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm) for detailed descriptions of reports and classification methodology.
