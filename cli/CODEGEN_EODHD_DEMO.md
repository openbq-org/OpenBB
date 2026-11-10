# `openbb-cli` codegen + EODHD data exploration

## Part 1 — Codegen: OpenAPI spec → installable OpenBB extension

`openbb --generate-spec` snapshots any OpenAPI 3.x document into a `.spec` file; `--generate-extension`
turns that `.spec` into a full `Provider` + `Fetcher` + `Router` package that registers with
`openbb-build` like any first-party extension. Worked example against the NY Fed Markets API,
which publishes its OpenAPI document at a non-default path:

```bash
openbb --generate-spec \
       --server https://markets.newyorkfed.org \
       --openapi-path /static/docs/markets-api.yml \
       --output nyfed.spec
# wrote 53 commands to nyfed.spec
```

### What's inside a `.spec` file

It's a self-contained JSON snapshot: `base_url`, every command's parameters, and full
`response_schema` per content type (including the upstream's XML shape, when it has one). Real
excerpt for `ambs.latest`:

```json
{
  "base_url": "https://markets.newyorkfed.org",
  "api_prefix": "/api",
  "commands": {
    "ambs.latest": {
      "url_path": "/api/ambs/{operation}/{status}/{include}/latest.{format}",
      "method": "get",
      "description": "Returns the latest AMBS operation Announcements or Results for the current day.",
      "parameters": [
        {
          "name": "operation",
          "in": "path",
          "type": "string",
          "required": true,
          "choices": ["all", "purchases", "sales", "roll", "swap"],
          "help": "The operation type"
        },
        {
          "name": "status",
          "in": "path",
          "type": "string",
          "required": true,
          "choices": ["announcements", "results"],
          "help": "The operation status"
        }
      ]
    }
  }
}
```

Because it's precomputed, dispatching against `--spec nyfed.spec` skips the OpenAPI fetch + parse
on every call (~50ms cold start vs. a live `--server` fetch).

### Generate the extension project

```bash
openbb --generate-extension \
       --spec nyfed.spec \
       --provider-name nyfed \
       --output ./openbb-nyfed
# wrote project to openbb-nyfed/openbb-nyfed
#   providers (1): nyfed
#   routers (1): nyfed
#   fetchers: 53 GET (across all providers)
#   POST:     0 local-compute commands
#   install:  pip install -e openbb-nyfed/openbb-nyfed
#   build:    openbb-build
```

```
openbb-nyfed/openbb-nyfed/
├── pyproject.toml                       # entry points: openbb_provider_extension, openbb_core_extension
├── README.md
└── openbb_nyfed/
    ├── providers/nyfed/
    │   ├── __init__.py                  # nyfed_provider = Provider(name="nyfed", fetcher_dict={...})
    │   └── models/ambs_latest.py        # QueryParams + Data + Fetcher, one file per command
    └── routers/
        ├── nyfed.py                     # root router, include_router() per sub-namespace
        ├── ambs.py
        ├── rates.py
        ├── soma.py
        └── ...                          # one file per top-level path segment
```

```bash
pip install -e ./openbb-nyfed/openbb-nyfed
openbb-build
python -c "from openbb import obb; print(obb.nyfed.rates.all.latest().to_df())"
```

### Codegen against EODHD — a second real API, warts included

EODHD publishes its own OpenAPI 3.1 document (not at the default `/openapi.json`), which is a good
stress test for `--openapi-path` accepting a fully-qualified URL independent of `--server`:

```bash
openbb --generate-spec \
       --server https://eodhd.com/api \
       --openapi-path https://eodhistoricaldata.github.io/EODHD-openapi/openapi.yaml \
       --output eodhd.spec
# wrote 87 commands to eodhd.spec
```

```bash
openbb --generate-extension --spec eodhd.spec --provider-name eodhd --output ./openbb-eodhd
```

```
E741 Ambiguous variable name: `l`
  --> openbb-eodhd/openbb-eodhd/openbb_eodhd/providers/eodhd/models/history.py:77:5
   |
77 |     l: float | None = Field(default=None, description='Low price.')

wrote project to openbb-eodhd/openbb-eodhd
  providers (1): eodhd
  routers (1): eodhd
  fetchers: 87 GET (across all providers)
  POST:     0 local-compute commands
  install:  pip install -e openbb-eodhd/openbb-eodhd
  build:    openbb-build
```

That ruff warning is genuine: the generator maps a `low` field literally named `l` in the OHLC
schema and doesn't rename single-letter identifiers. Codegen output is a starting point, not
guaranteed lint-clean — worth a pass before shipping the package.

Two things worth inspecting in the generated code:

**Credential auto-detection** — EODHD's `api_token` query param was recognized as a credential and
promoted onto the provider, so once installed, `openbb` reads it from user settings instead of
requiring a flag on every call:

```python
# openbb_eodhd/providers/eodhd/__init__.py
eodhd_provider = Provider(
    name="eodhd",
    description="eodhd provider proxied through https://eodhd.com/api.",
    credentials=["api_token"],
    website="https://eodhd.com/api",
    fetcher_dict={
        "History": HistoryFetcher,
        "BulkFundamentals": BulkFundamentalsFetcher,
        "Eod": EodFetcher,
        # ... 84 more
    },
)
```

**Typed router command** — every command becomes a real `@router.command`, so `obb.eodhd.eod(...)`
gets full auto-completion and an `OBBject` envelope, same as any first-party command:

```python
# openbb_eodhd/routers/eodhd.py
@router.command(model="Eod")
async def eod(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Retrieve end-of-day historical data for a specific company by its ticker symbol, with optional filters for specific data points."""
    return await OBBject.from_query(Query(**locals()))
```

**Credential naming gotcha** — if you already have OpenBB's legacy EODHD credential saved
(`eodhd_api_key`, from the old first-party provider), it will **not** be picked up here. The
generated Fetcher reads `credentials.get("eodhd_api_token", "")` — matching the provider name
(`eodhd`) plus the exact query param the live spec declares (`api_token`, not `api_key`).
Add the matching key to `~/.openbb_platform/user_settings.json`:

```json
{
  "credentials": {
    "eodhd_api_key": "<existing legacy key>",
    "eodhd_api_token": "<same value — this is the key the generated Fetcher actually reads>"
  }
}
```

With that in place, install + build and it passes through with no key on the call site:

```bash
pip install -e ./openbb-eodhd/openbb-eodhd
openbb-build
```

```
Extensions to add: eodhd@0.1.0
Building...
```

```python
from openbb import obb

obb.eodhd.eod(ticker="MSFT.US", from_="2024-01-01", to="2024-01-10").to_df()
```

```
              open    high     low   close  adjusted_close    volume
date
2024-01-02  373.86  375.90  366.77  370.87        363.1179  25258600
2024-01-03  369.01  373.26  368.51  370.60        362.8536  23083500
2024-01-04  370.67  373.10  367.17  367.94        360.2492  20901500
2024-01-05  368.97  372.06  366.50  367.75        360.0632  21004600
2024-01-08  369.30  375.20  369.01  374.69        366.8581  23134000
2024-01-09  372.01  375.99  371.19  375.79        367.9351  20830000
2024-01-10  376.37  384.17  376.32  382.77        374.7692  25514200
```

This is `MSFT.US` — not `AAPL.US`/`VTI.US` from the demo key's allowlist — confirming the real key is
what's actually being used, resolved automatically from user settings. `search`, which returned
`HTTP403` under the restricted demo key in Part 2 below, also succeeds now:

```python
obb.eodhd.search(query="Microsoft").to_df().head(3)
```

```
        Code Exchange  ...  previousCloseDate  isPrimary
0       MSFT       US  ...          2026-09-24       True
1       MSFT       BA  ...          2026-09-24      False
2  MSFTX-USD       CC  ...          2026-09-25      False
```

## Part 2 — Data exploration against EODHD (spec-driven, no install required)

Everything in this section runs straight off `eodhd.spec` — no extension install, no `openbb-build`.
This is the fast path for exploring an API before deciding it's worth turning into a permanent
extension.

### Discover the surface

```bash
openbb --spec eodhd.spec --list-commands
```

87 commands span EOD prices, fundamentals, calendar events, options, sanctions lists, credit-risk
indices, and more:

```json
{"name": "eod", "description": "Retrieve end-of-day historical data for a specific company by its ticker symbol, with optional filters for specific data points"}
{"name": "real-time", "description": "Retrieve live (delayed) stock prices for specified ticker(s)"}
{"name": "calendar.earnings", "description": "Fetches upcoming earnings data, with optional parameters for date ranges and specific symbols"}
{"name": "fundamentals", "description": "Fetches various sections of fundamental data for a given stock symbol"}
{"name": "screener", "description": "Retrieves stock data filtered by criteria such as market capitalization, exchange, sector, and more"}
{"name": "sanctions.entities", "description": "Returns sanctioned entities (individuals and organizations) aggregated from OFAC and other sanctions sources"}
```

```bash
openbb --spec eodhd.spec --describe eod
```

```json
{
  "parameters": [
    {"name": "ticker", "in": "path", "type": "string", "required": true, "help": "Ticker symbol of the company"},
    {"name": "fmt", "in": "query", "type": "string", "default": "json", "choices": ["json", "csv"]},
    {"name": "from", "in": "query", "type": "string", "help": "Start date (YYYY-MM-DD)"},
    {"name": "to", "in": "query", "type": "string", "help": "End date (YYYY-MM-DD)"},
    {"name": "period", "in": "query", "type": "string", "choices": ["d", "w", "m"]},
    {"name": "api_token", "in": "query", "type": "string", "help": "EODHD API key"}
  ]
}
```

### Auth

EODHD takes the key as a query param, not a header — use `-Q`:

```bash
openbb --spec eodhd.spec eod --ticker AAPL.US
# {"ok": false, "error": {"type": "HTTP401", "message": "Unauthenticated"}}

openbb --spec eodhd.spec -Q api_token=demo eod --ticker AAPL.US --from 2024-01-01 --to 2024-01-10
```

`demo` is EODHD's public demo key — real, rate-limited, and scoped to `AAPL.US`/`VTI.US`/a handful
of other symbols, which is why every example below uses it. Swap in
`OPENBB_HTTP_QUERY_API_TOKEN=<your key>` (or `-Q api_token=...`) for unrestricted symbols.

**Gotcha found while testing:** the spec declares `fmt` defaults to `json`, but EODHD's live API
actually defaults to CSV when `fmt` is omitted — pass `--fmt json` explicitly if you want structured
output. Published API docs and live behavior drift; this is exactly the kind of thing worth
smoke-testing before building automation on a generated spec.

### Pull real data

```bash
openbb --spec eodhd.spec -Q api_token=demo eod \
       --ticker AAPL.US --fmt json --from 2024-01-01 --to 2024-01-10
```

```json
{"ok": true, "result": [
  {"date": "2024-01-02", "open": 187.15, "high": 188.44, "low": 183.89, "close": 185.64, "adjusted_close": 183.404, "volume": 82488700},
  {"date": "2024-01-03", "open": 184.22, "high": 185.88, "low": 183.43, "close": 184.25, "adjusted_close": 182.0308, "volume": 58414500},
  {"date": "2024-01-10", "open": 184.35, "high": 186.4, "low": 183.92, "close": 186.19, "adjusted_close": 183.9474, "volume": 46792900}
]}
```

```bash
openbb --spec eodhd.spec -Q api_token=demo real-time --ticker AAPL.US
# {"ok": true, "result": {"code": "AAPL.US", "close": 335.92, "previousClose": 337.02, "change": -1.1, "change_p": -0.3264, ...}}

openbb --spec eodhd.spec -Q api_token=demo fundamentals --ticker AAPL.US
# {"ok": true, "result": {"General": {"Code": "AAPL", "Name": "Apple Inc.", "Sector": "Technology", "Industry": "Consumer Electronics", ...}}}
```

### Batch mode — several EODHD calls in one shot

```bash
cat <<'EOF' | openbb --spec eodhd.spec -Q api_token=demo --batch
{"id":"eod","command":"eod","params":{"ticker":"AAPL.US","fmt":"json","from":"2024-06-01","to":"2024-06-05"}}
{"id":"rt","command":"real-time","params":{"ticker":"AAPL.US"}}
EOF
```

```json
{"id": "eod", "ok": true, "result": [
  {"date": "2024-06-03", "open": 192.9, "high": 194.99, "low": 192.52, "close": 194.03, "volume": 50080500},
  {"date": "2024-06-04", "open": 194.64, "high": 195.32, "low": 193.03, "close": 194.35, "volume": 47471400},
  {"date": "2024-06-05", "open": 195.4, "high": 196.9, "low": 194.87, "close": 195.87, "volume": 54156800}
]}
{"id": "rt", "ok": true, "result": {"code": "AAPL.US", "close": 335.92, "change_p": -0.3264}}
```

### From JSON to a DataFrame

The CLI's job stops at a JSON envelope; pandas takes it from there:

```python
import json
import subprocess
import pandas as pd

out = subprocess.run(
    [
        "openbb",
        "--spec",
        "eodhd.spec",
        "-Q",
        "api_token=demo",
        "eod",
        "--ticker",
        "AAPL.US",
        "--fmt",
        "json",
        "--from",
        "2024-01-01",
        "--to",
        "2024-03-29",
    ],
    capture_output=True,
    text=True,
    check=True,
).stdout

rows = json.loads(out)["result"]
df = pd.DataFrame(rows)
df["date"] = pd.to_datetime(df["date"])
df = df.set_index("date")

print(df[["close", "volume"]].describe())
print(df["close"].rolling(20).mean().tail())
```

```
            close        volume
count   61.000000  6.100000e+01
mean   181.830328  6.200321e+07
std      7.413215  1.924904e+07
min    169.000000  4.047780e+07
25%    173.720000  4.912840e+07
50%    182.680000  5.652950e+07
75%    186.860000  6.966880e+07
max    195.180000  1.366826e+08

date
2024-03-22    174.7270
2024-03-25    174.2115
2024-03-26    173.5655
2024-03-27    173.1600
2024-03-28    172.6965
Name: close, dtype: float64
```

Once `openbb-eodhd` is installed and built (Part 1), the same exploration reads more naturally off
the typed surface: `obb.eodhd.eod(ticker="AAPL.US", from_="2024-01-01", to="2024-03-29", api_token="demo").to_df()`.

## Reference

- `cli/README.md` — full flag reference for `--generate-spec`, `--generate-extension`, multi-spec
  mounting, auth hooks, batch mode, and the REPL.
- NY Fed Markets API: <https://markets.newyorkfed.org/static/docs/markets-api.yml>
- EODHD OpenAPI document: <https://eodhistoricaldata.github.io/EODHD-openapi/openapi.yaml>
