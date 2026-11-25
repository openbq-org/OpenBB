<br />
<img src="https://github.com/OpenBB-finance/OpenBB/blob/develop/images/odp-light.svg?raw=true#gh-light-mode-only" alt="Open Data Platform by OpenBB logo" width="600">
<img src="https://github.com/OpenBB-finance/OpenBB/blob/develop/images/odp-dark.svg?raw=true#gh-dark-mode-only" alt="Open Data Platform by OpenBB logo" width="600">
<br />
<br />

# ODP Command-Line Interface

## Overview

`openbb-cli` is a command-line interface for the [OpenBB Platform](https://docs.openbb.co/platform) and any other OpenAPI 3.x server. It runs in three modes:

* **Non-TTY one-shot** (default) — `openbb <command.path> [--key value]` dispatches one command, prints a JSON line, exits. The form CI tools and agents reach for.
* **Batch** — `openbb --batch` reads NDJSON requests from stdin, fans them out concurrently, writes NDJSON responses to stdout.
* **Interactive REPL** — `openbb -i` drops into a rich-output prompt with auto-completion, menu navigation, and routine playback.

Backends are pluggable: dispatch through an in-process `obb` namespace, an `openbb-platform-api` HTTP server, or any OpenAPI 3.x server (e.g. `https://api.congress.gov`) without touching code.

The full user docs live at **[docs.openbb.co/odp/cli](https://docs.openbb.co/odp/cli)**.

## Backends

Four sources for the command surface. Three are OpenBB-aware; the fourth is the generic OpenAPI 3.x fallback.

| Source | Flag | Cold start | When to use |
|--------|------|------------|-------------|
| **In-process `obb`** | _(default)_ | slow (`import openbb` ~2s) | Local script with `openbb` already installed; no separate process to manage. |
| **OpenBB Platform server** | `--server URL` | fast after first fetch | Long-running shared server (`openbb-platform-api`) — many CLI invocations or many users amortize the import cost. |
| **OpenBB `.spec` file** | `--spec PATH` | fastest (~50ms) | Ship the spec next to scripts/agents; skips OpenAPI fetch + parse on every call. Generate with `openbb --generate-spec --server URL -o file.spec`. |
| **Arbitrary OpenAPI 3.x server** | `--server URL` (non-OpenBB host) | depends on host | Any external API with an OpenAPI document — Congress.gov, NY Fed, USDA, NWS, your own FastAPI service. |

The first three speak the same OpenBB Platform surface (the `OBBject` envelope, providers, the `obb.reference` menu tree). The fourth treats whatever the upstream publishes as the truth — same dispatcher, same parser, same auth, just no OpenBB-specific affordances.

### What's different about OpenBB upstreams

Multi-provider Pydantic models and the `OBBject` envelope are OpenBB Platform conventions, not OpenAPI ones. The CLI detects an OpenBB endpoint by the presence of a `provider` discriminator parameter on the operation and turns on extra behavior:

| Feature | OpenBB upstream | Generic OpenAPI upstream |
|---------|-----------------|--------------------------|
| Response envelope | `OBBject` — `id`, `results`, `provider`, `warnings`, `chart`, `extra` | Whatever the server returns |
| `--describe COMMAND` | Groups parameters + result schema **per provider** | Flat `{parameters, output_schema}` |
| `--describe COMMAND:PROVIDER` | Returns just that provider's slice | Suffix ignored |
| Per-provider argparse narrowing | `--provider X` filters accepted flags; passing a flag from another provider errors at parse time | Every declared flag accepted |
| Help text per provider | `(provider: …)` annotations stripped; only sections relevant to the chosen provider | Description shown verbatim |
| REPL menu tree | Mirrors `obb.reference` (router descriptions, command groupings) | Built from URL path prefixes |
| Boolean flags | `--flag` / `--no-flag` toggle (OpenBB exposes `default: true` booleans) | Same — applies to any spec |

Everything else — `--list-commands`, `--describe COMMAND`, `--batch`, headers/query auth, spec generation, REPL playback — works identically against both kinds of upstream.

## Installation

```bash
pip install openbb-cli
```

Optional extras:

```bash
pip install "openbb-cli[charting]"      # Plotly + openbb-charting
pip install "openbb-cli[interactive]"   # PyWry browser-based tables
pip install "openbb-cli[all]"           # everything
```

## Quick start

### One-shot dispatch

```bash
# Against the local in-process obb namespace (the historical default)
openbb economy.gdp --provider oecd --limit 5

# Against any OpenAPI server — auto-detects spec layout, $ref-resolves params,
# auto-extracts HTML-embedded specs (e.g. Congress.gov)
openbb --server http://127.0.0.1:6900 equity.price.historical --symbol AAPL --provider fmp
openbb --server https://api.congress.gov bill --limit 5
```

### Spec files for instant cold-start

```bash
# Generate once; ship alongside the script that invokes the CLI
openbb --generate-spec --server https://api.congress.gov --output congress.spec

# Subsequent calls skip the OpenAPI fetch + parse on every invocation
openbb --spec congress.spec law --congress 119 --limit 5
```

Two flags shape the spec as it is generated:

| Flag | What it does |
|------|--------------|
| `--api-prefix PREFIX` | Strips `PREFIX` from each path when naming commands, e.g. `--api-prefix /api/v3` names `/api/v3/klines` `klines` instead of `api.v3.klines`. Paths outside the prefix keep their full name; request URLs are unchanged. A path the prefix strips to nothing (the prefix itself, or the prefix plus only placeholders) is skipped; with an explicit `--api-prefix` a warning lists those paths. Default: the longest prefix the paths share, leaving out each path's last segment. |
| `--overlay PATH` | Applies an [OpenAPI Overlay 1.0](https://spec.openapis.org/overlay/v1.0.0) document (YAML or JSON) to the fetched OpenAPI description before the spec is built, to correct upstream schema errors without editing generated code. Repeatable; overlays apply in order. Targets use the JSONPath subset `$`, `.name`, `['name']`, `[index]` and `*`; a target that matches nothing is reported as a warning. |

```bash
openbb --generate-spec \
       --server https://api.binance.com \
       --openapi-path https://raw.githubusercontent.com/binance/binance-api-swagger/master/spot_api.yaml \
       --api-prefix /api/v3 \
       --overlay binance.overlay.yaml \
       --output binance.spec
```

### Generate an installable OpenBB extension from a spec

A `.spec` file is enough to dispatch commands directly. Going one step further, `--generate-extension` turns that spec into a full installable OpenBB Platform extension package — `Provider(...)` + `Fetcher` classes + a router that mirrors the upstream's namespace tree — that registers with `openbb-build` like any first-party extension. After install, every command shows up on the typed `obb.*` surface (auto-completion, `obb.reference`, `OBBject` envelopes, the works).

End-to-end with the NY Fed Markets API:

```bash
# 1. Snapshot the OpenAPI surface as a spec file. NY Fed publishes its
#    spec at a non-default path, so point --openapi-path at the YAML.
openbb --generate-spec \
       --server https://markets.newyorkfed.org \
       --openapi-path /static/docs/markets-api.yml \
       --output nyfed.spec
# wrote 55 commands to nyfed.spec

# 2. Generate a complete extension project from that spec
openbb --generate-extension \
       --spec nyfed.spec \
       --provider-name nyfed \
       --output ./openbb-nyfed
# wrote project to ./openbb-nyfed/openbb-nyfed
#   providers (1): nyfed
#   routers (10): ambs, fxs, guidesheets, marketshare, pd, rates, rp, seclending, soma, tsy
#   fetchers: 55 GET (across all providers)
#   POST:     0 local-compute commands
#   install:  pip install -e ./openbb-nyfed/openbb-nyfed
#   build:    openbb-build

# 3. Install + register with the OpenBB Platform
pip install -e ./openbb-nyfed/openbb-nyfed
openbb-build

# 4. The new namespaces are live on the typed obb surface
python -c "from openbb import obb; print(obb.nyfed.rates.all.latest().to_df())"
```

(`--openapi-path` is only needed when the upstream doesn't expose `/openapi.json` directly. For servers that do — most FastAPI deployments, Congress.gov via the embedded-spec scraper — drop the flag.)

What `--generate-extension` produces:

```
openbb-nyfed/
├── pyproject.toml                          # PEP 621 / Hatchling — every provider + router declared as entry points
├── README.md
└── openbb_nyfed/
    ├── providers/
    │   └── nyfed/
    │       ├── __init__.py                 # nyfed_provider = Provider(name="nyfed", fetcher_dict={...}, credentials=[...])
    │       └── models/<command>.py         # one Fetcher class per command (QueryParams + Data + Fetcher)
    └── routers/
        ├── rates.py                        # @router.command(model="RatesAllLatest") — typed signature
        ├── ambs.py
        └── ...                             # one router per top-level namespace; sub-routers nest via include_router(prefix="/sub")
```

Every flag is optional except `--spec`:

| Flag | Default | What it controls |
|------|---------|------------------|
| `--output PATH` | _required_ | Project root directory written to disk. |
| `--provider-name NAME` | derived from `--output` basename | Snake-case provider identifier — drives credential lookup keys (`credentials.get(f"{provider}_api_key")`). |
| `--project-name NAME` | `openbb-<provider-name>` | PyPI distribution name in `pyproject.toml`. Use dashes. |
| `--package-name NAME` | `openbb_<provider-name>` | Snake-case Python package name. |
| `--router-name NAME` | `<provider-name>` | Top-level router identifier. |

Bring-your-own-key APIs: parameter names that look like credentials (`api_key`, `apikey`, `app_token`, `X-API-Key`, `Authorization`, `client_secret`, `bearer_token`, …) are auto-promoted to the provider's `credentials=[...]` list. After install, `openbb` reads them through the standard user-settings flow (`OBB_USER_SETTINGS` / `~/.openbb_platform/user_settings.json`) — no per-call flag needed.

### Multi-spec — combine APIs under one CLI

Repeat `--spec NAME=PATH` to mount more than one spec at once. Each spec's commands get prefixed with its namespace, and each backend keeps its own `base_url`, headers, and query params:

```bash
openbb \
  --spec congress=congress.spec \
  --spec nyfed=nyfed.spec \
  congress.bill --limit 5

openbb \
  --spec congress=congress.spec \
  --spec nyfed=nyfed.spec \
  nyfed.markets.ambs --operation rates
```

Scope auth per namespace by prefixing the flag value with `<NAME>:`:

```bash
openbb \
  --spec congress=congress.spec \
  --spec usda=usda.spec \
  -Q congress:api_key="$CONGRESS_KEY" \
  -Q usda:api_key="$USDA_KEY" \
  -H usda:Authorization="Bearer $USDA_BEARER" \
  congress.bill --limit 5
```

Tokens without a namespace prefix (`-H Authorization=...`, `-Q api_key=...`) apply to every backend; namespace-scoped tokens override on conflict for that one backend only.

The same shape works in TOML, which is the better fit when scripts reach for the same set repeatedly:

```toml
[specs.congress]
path = "/path/congress.spec"
[specs.congress.query]
api_key = "..."

[specs.usda]
path = "/path/usda.spec"
[specs.usda.headers]
Authorization = "Bearer ..."
[specs.usda.query]
api_key = "..."
```

`--list-commands` aggregates across every namespace; `--describe NAMESPACE.command[:provider]` resolves to the right backend automatically.

A single unnamed `--spec PATH` keeps the flat (unprefixed) command surface — backward-compatible with the historical single-spec form.

### Auth

Pick whichever the upstream API uses:

```bash
# Headers (Authorization, X-API-Key, ...)
openbb --server URL -H "Authorization: Bearer xxx" -H "X-Tenant: acme" cmd

# Query-string params (e.g. ?api_key=... like Congress.gov, USDA, NWS)
openbb --server URL -Q api_key=xxx cmd
# or via env — OPENBB_HTTP_QUERY_<NAME> auto-injected
OPENBB_HTTP_QUERY_API_KEY=xxx openbb --server URL cmd
```

#### Auth hooks (RBAC, token refresh, dynamic credentials)

Static headers and query params cover the common case. For RBAC, expiring tokens, or per-user credentials sourced from a vault, register an importable callable as an auth hook. Configured in TOML by `module:attribute` path — global, or per `[specs.<ns>]`:

```toml
auth-hook = "myapp.auth:default_hook"        # applies to every backend

[specs.congress]
path = "/path/congress.spec"
auth-hook = "myapp.auth:congress_hook"      # overrides the global for this one

[specs.internal]
path = "/path/internal.spec"
auth-hook = "myapp.auth:rbac_hook"
```

The hook receives an `AuthContext` (namespace, command, params, method) and returns an `AuthDecision`:

```python
# myapp/auth.py
from openbb_cli.auth import AuthContext, AuthDecision
from myapp.identity import current_user, get_token


def rbac_hook(ctx: AuthContext) -> AuthDecision:
    user = current_user()
    if not user.can_access(ctx.namespace, ctx.command):
        return AuthDecision(
            allow=False, deny_reason=f"{user.role} cannot call {ctx.command}"
        )
    return AuthDecision(headers={"Authorization": f"Bearer {get_token(user)}"})
```

Hooks may be sync or async; coroutines are awaited. Returned headers and query params merge on top of the dispatcher's static auth (hook wins on conflict). `allow=False` short-circuits the dispatch with an `AccessDenied` error response — no network call is made.

Introspection is gated by the same hook: `--list-commands` invokes it for every command and silently drops denied entries from the listing, and `--describe COMMAND` returns `AccessDenied` when the hook denies. RBAC implementations that hide endpoints therefore hide them everywhere — discovery, schema, and dispatch all see the same surface.

### Batch

NDJSON request/response over stdin/stdout, concurrent dispatch:

```bash
cat <<'EOF' | openbb --spec congress.spec --batch
{"id":"a","command":"bill","params":{"limit":5,"format":"json"}}
{"id":"b","command":"law","params":{"congress":119,"format":"json"}}
{"id":"c","command":"__commands__"}
EOF
```

### Introspection

```bash
openbb --spec congress.spec --list-commands     # every command + short description
openbb --spec congress.spec --describe bill     # full schema (params + response)
```

The same calls work as reserved commands in batch mode (`__commands__`, `__schema__`).

### Interactive REPL

```bash
openbb -i                          # in-process obb backend
openbb -i --spec congress.spec     # spec-driven; no obb install required
openbb -i --server URL             # live OpenAPI fetch
```

The REPL adds menu navigation (`bill`, `..`, `home`, `exit`), tab/auto-completion against parser flags, `--help` per command, the OBBject registry, and routine playback (`exe --file ...`).

## Configuration

Layered, all optional. Resolution order (lowest → highest priority):

1. Built-in defaults
2. `[tool.openbb-cli]` in nearest ancestor `pyproject.toml`
3. `~/.openbb_platform/openbb.toml` (user-global; same dir as `user_settings.json`)
4. `./openbb.toml` (project-local, walks up from CWD)
5. `--config PATH` (or `OPENBB_CLI_CONFIG`)
6. `~/.openbb_platform/.env` and `--env-file PATH`
7. `OPENBB_*` shell exports
8. CLI flags

Bootstrap a documented template:

```bash
openbb --print-config-template > ~/.openbb_platform/openbb.toml
```

Inspect what's currently active across all layers:

```bash
openbb --show-config
```

Schema:

```toml
# Backend / dispatch — pick one of these forms
server = "https://api.congress.gov"   # live OpenAPI fetch
spec = "/path/to/api.spec"            # single spec (flat surface)
batch-concurrency = 16

# Multi-spec: each table mounts under its own namespace
[specs.congress]
path = "/path/congress.spec"
[specs.congress.query]
api_key = "..."

[specs.usda]
path = "/path/usda.spec"
[specs.usda.headers]
Authorization = "Bearer ..."
[specs.usda.query]
api_key = "..."

# REPL display preferences (top-level shortcuts)
output-mode = "rich"        # rich | json | tsv | html
flair = ":fox_face"
timezone = "America/New_York"
rich-style = "dark"

[headers]                             # global — applied to every backend
Authorization = "Bearer ..."

[query]                               # global — applied to every backend
api_key = "..."

[settings]
# Every other Settings field — same surface as the /settings/ REPL menu
allowed-number-of-rows = 50
use-prompt-toolkit = true
toolbar-hint = false
```

## Documentation

Full user documentation: **[docs.openbb.co/odp/cli](https://docs.openbb.co/odp/cli)**

API reference: [docs.openbb.co/platform](https://docs.openbb.co/platform)
