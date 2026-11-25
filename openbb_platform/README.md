# OpenBB Platform

The OpenBB Platform is a set of Python packages that turn financial and economic data sources into one typed Python client (`from openbb import obb`), a FastAPI REST API, and an MCP server.

`openbb-core` is the runtime. It ships no data and no commands; it discovers the extensions installed in the environment through entry points and assembles them. Everything else in this folder is an extension:

- **Routers** add command namespaces such as `obb.equity` or `obb.economy`.
- **Providers** implement those commands against a data source, and may add their own namespace such as `obb.fred`.
- **OBBject extensions** add accessors to every result, such as `result.charting`.

Documentation lives at [docs.openbb.co](https://docs.openbb.co).

## Repository layout

| Path | Contents |
|------|----------|
| `core/` | `openbb-core`: the runtime, the generated `openbb` package, and the REST API app. |
| `extensions/` | Routers, plus the API launcher, the MCP server, and developer tooling. |
| `providers/` | Data provider extensions. |
| `obbject_extensions/` | Result accessors (`openbb-charting`). |
| `dev_install.py` | Editable install of every package for local development. |
| `../cli/` | `openbb-cli`, the command-line interface. |

## Packages

### Core and tooling

| Package | Path | Description |
|---------|------|-------------|
| `openbb-core` | `core` | Runtime, extension loader, static package builder (`openbb-build`), and REST API app. |
| `openbb-platform-api` | `extensions/platform_api` | `openbb-api` launcher for the REST API and the OpenBB Workspace custom-backend connector. |
| `openbb-mcp-server` | `extensions/mcp_server` | `openbb-mcp`: serves the installed commands as Model Context Protocol tools. |
| `openbb-devtools` | `extensions/devtools` | Linters, type checker, and test dependencies for development. |
| `openbb-cli` | `../cli` | `openbb`: interactive command-line interface. |

### Routers

| Package | Namespace |
|---------|-----------|
| `openbb-commodity` | `obb.commodity` |
| `openbb-crypto` | `obb.crypto` |
| `openbb-currency` | `obb.currency` |
| `openbb-derivatives` | `obb.derivatives` |
| `openbb-econometrics` | `obb.econometrics` |
| `openbb-economy` | `obb.economy` |
| `openbb-equity` | `obb.equity` |
| `openbb-etf` | `obb.etf` |
| `openbb-fixedincome` | `obb.fixedincome` |
| `openbb-index` | `obb.index` |
| `openbb-news` | `obb.news` |
| `openbb-quantitative` | `obb.quantitative` |
| `openbb-technical` | `obb.technical` |

### Providers

| Package | Path | Source | Credential |
|---------|------|--------|------------|
| `openbb-bls` | `providers/bls` | U.S. Bureau of Labor Statistics | `bls_api_key` |
| `openbb-cboe` | `providers/cboe` | Cboe | None |
| `openbb-cftc` | `providers/cftc` | CFTC and DTCC Public Price Dissemination | `cftc_app_token` |
| `openbb-deribit` | `providers/deribit` | Deribit | None |
| `openbb-ecb` | `providers/ecb` | European Central Bank | None |
| `openbb-famafrench` | `providers/famafrench` | Ken French Data Library | None |
| `openbb-federal-reserve` | `providers/federal_reserve` | Federal Reserve System, FOMC, and the twelve regional districts | None |
| `openbb-finra` | `providers/finra` | FINRA | None |
| `openbb-fred` | `providers/fred` | FRED | `fred_api_key` |
| `openbb-government-us` | `providers/government_us` | U.S. Congress, U.S. Treasury, and USDA | `congress_gov_api_key` |
| `openbb-imf` | `providers/imf` | International Monetary Fund | None |
| `openbb-jodi` | `providers/jodi` | Joint Organisations Data Initiative | None |
| `openbb-nasdaq` | `providers/nasdaq` | Nasdaq | None |
| `openbb-oecd` | `providers/oecd` | OECD | None |
| `openbb-sec` | `providers/sec` | SEC EDGAR | None |
| `openbb-tmx` | `providers/tmx` | TMX (Canadian markets) | None |
| `openbb-us-eia` | `providers/eia` | U.S. Energy Information Administration | `eia_api_key` |

### OBBject extensions

| Package | Accessor |
|---------|----------|
| `openbb-charting` | `result.charting`: Plotly charts, with native window rendering through the `pywry` extra. |

## Installation

Install `openbb-core` together with the routers and providers you need; `openbb-core` is pulled in by each of them.

```bash
pip install openbb-equity openbb-cboe
```

The `openbb` Python package is generated from whatever is installed. It rebuilds on import when the installed extensions change, and `openbb-build` rebuilds it explicitly after installing or removing an extension.

```bash
openbb-build
```

## Python

```python
from openbb import obb

output = obb.equity.price.historical("AAPL", provider="cboe")
df = output.to_dataframe()
```

## Credentials

Providers that need a key read it as `<provider>_<credential>`, as listed in the provider table.

Set keys in `~/.openbb_platform/user_settings.json`:

```json
{
  "credentials": {
    "fred_api_key": "REPLACE_ME",
    "bls_api_key": "REPLACE_ME"
  }
}
```

Or as environment variables, which take precedence over the file. `~/.openbb_platform/.env` is loaded automatically.

```bash
export FRED_API_KEY=REPLACE_ME
```

Or for the current session only:

```python
from openbb import obb

obb.user.credentials.fred_api_key = "REPLACE_ME"
```

## REST API

`openbb-platform-api` serves every installed command over FastAPI, with OpenAPI docs at `/docs` and a `widgets.json` for OpenBB Workspace.

```bash
pip install openbb-platform-api
openbb-api
```

The bare FastAPI app is `openbb_core.api.rest_api:app` and runs under any ASGI server.

```bash
uvicorn openbb_core.api.rest_api:app --host 127.0.0.1 --port 8000
```

## MCP server

```bash
pip install openbb-mcp-server
openbb-mcp
```

See [extensions/mcp_server/README.md](extensions/mcp_server/README.md) for transports, tool discovery, and configuration.

## Local development

Requirements:

- Git
- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)

From an activated virtual environment at the repository root:

```bash
python openbb_platform/dev_install.py --routers
```

This installs every tracked package under `core`, `extensions`, `obbject_extensions`, `providers`, and `../cli` in editable mode, with all optional extras and each package's `dev` dependency group, then runs `openbb-build`. A new extension is picked up once its `pyproject.toml` is committed in one of those folders.

Router extensions (`openbb-equity`, `openbb-economy`, `openbb-fixedincome`, and the rest of the router table except `openbb-news`) are installed only with `--routers`. Without it, you get core, the tooling, `openbb-news`, the providers, `openbb-charting`, and the CLI.

Install the git hooks, which run the same ruff, ty, codespell, and markdownlint checks as CI:

```bash
pre-commit install
```

Each package is linted and tested from its own directory, matching its CI workflow:

```bash
cd openbb_platform/providers/fred
ruff format --check .
ruff check .
ty check openbb_fred
pytest tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for extension guidelines.

## License

Apache-2.0. See [LICENSE](https://github.com/OpenBB-finance/OpenBB/blob/main/LICENSE).
