# openbb-core

`openbb-core` is the runtime that turns a collection of installed Python
packages into the OpenBB Platform. By itself it ships **no data, no providers,
and no commands**. Its job is to:

1. Discover provider, command, and result-type extensions installed in the
   current Python environment via setuptools entry points.
2. Stitch them together into a single typed Python client (`from openbb import
   obb`) and an equivalent FastAPI REST API.
3. Execute calls against those extensions, normalise the output through shared
   Pydantic models, and return a uniform `OBBject` result wrapper.

If you are an end user, you install `openbb` (which depends on this package)
and one or more provider extensions. If you are an extension author, you
depend on `openbb-core` and register one of the entry points below.

## Entry points

Extensions plug into the runtime through three setuptools entry-point groups
defined in [`openbb_core/app/extension_loader.py`](openbb_core/app/extension_loader.py).
At import time, `ExtensionLoader` enumerates each group and the rest of the
platform consumes the results.

### `openbb_core_extension`

A `Router` to mount under the platform. Each entry point is loaded as an
`openbb_core.app.router.Router` instance and merged into the root router. This
is how command surfaces such as `obb.equity`, `obb.economy`, `obb.derivatives`
get added.

```toml
# pyproject.toml of an extension
[project.entry-points."openbb_core_extension"]
equity = "openbb_equity.equity_router:router"
```

### `openbb_provider_extension`

A `Provider` describing a data source — its credentials, the standard models
it implements, and the `Fetcher` classes that satisfy them. Routers do not
hard-code providers; they declare a standard model, and at call time the
runtime picks a `Fetcher` from any installed provider that implements it.

```toml
[project.entry-points."openbb_provider_extension"]
yfinance = "openbb_yfinance:yfinance_provider"
```

### `openbb_obbject_extension`

An `Extension` (see [`openbb_core/app/model/extension.py`](openbb_core/app/model/extension.py))
attached to the `OBBject` result wrapper. There are two flavours, configured
on the same `Extension` instance:

**1. Accessor extensions** (default — `on_command_output=False`)

Add a namespace attribute on every `OBBject`, pandas-style. The entry-point
name becomes the attribute name. Used for opt-in transformations the caller
explicitly invokes:

```python
result = obb.equity.price.historical("AAPL")
result.charting.to_chart()  # accessor registered by openbb_charting
```

```toml
[project.entry-points."openbb_obbject_extension"]
charting = "openbb_charting:ext"   # ext = Extension(name="charting")
```

**2. `on_command_output` callbacks** (post-execution hooks)

Set `on_command_output=True` to make the extension run automatically on the
`OBBject` returned by every command, or only by specific routes via
`command_output_paths`. `ExtensionLoader._register_command_output_callbacks`
indexes them by path (with `"*"` meaning "all commands") and the API layer
([`openbb_core/api/router/commands.py`](openbb_core/api/router/commands.py))
applies them after the command runs.

Three flags govern their behaviour:

- `on_command_output: bool` — enable the post-execution hook.
- `command_output_paths: list[str] | None` — restrict to specific endpoint
  paths; `None` means every command.
- `immutable: bool = True` — if `False`, the hook may modify `OBBject.results`
  in place. Mutable hooks additionally require
  `system_settings.allow_mutable_extensions=True`.
- `results_only: bool = False` — return just `OBBject.results` over the REST
  API instead of the full envelope.

```toml
[project.entry-points."openbb_obbject_extension"]
my_hook = "openbb_my_hook:ext"
# ext = Extension(
#     name="my_hook",
#     on_command_output=True,
#     command_output_paths=["/equity/price/historical"],
#     immutable=False,
# )
```

Because these hooks run on every matching response, they are gated by an
explicit opt-in: `system_settings.allow_on_command_output` (env:
`OPENBB_ALLOW_ON_COMMAND_OUTPUT`) must be `True`, or instantiating the
`Extension` will raise. Mutating hooks need
`allow_mutable_extensions` (env: `OPENBB_ALLOW_MUTABLE_EXTENSIONS`) on top of
that. Treat `on_command_output` extensions as code that runs against every
result — only install them from sources you trust.

## Console script: `openbb-build`

`openbb-core` installs one console script:

```sh
openbb-build
```

It is defined in [`openbb_core/build.py`](openbb_core/build.py) (`openbb-build
= openbb_core.build:main`). It imports the `openbb` package in a subprocess,
which triggers static-client generation when the generated package is missing
or stale, and falls back to calling `openbb.build()` explicitly if the import
did not rebuild. Run it after installing or upgrading any extension to
regenerate `openbb/package/` and `reference.json`.

## What lives inside the package

- **`openbb_core.provider`** — base classes (`Data`, `QueryParams`, `Provider`,
  `Fetcher`) and the registry that turns `openbb_provider_extension` entries
  into a queryable map of `(standard_model, provider) -> Fetcher`.
- **`openbb_core.provider.standard_models`** — the shared Pydantic schemas
  (equity prices, options chains, CPI, treasury rates, etc.) that every
  provider maps onto. This is what makes "swap providers without changing
  caller code" possible.
- **`openbb_core.app.router.Router`** — a thin wrapper around FastAPI's
  `APIRouter` used by `openbb_core_extension` packages to declare commands.
- **`openbb_core.app.command_runner`** — the execution path used by the
  generated Python client: resolves provider choice, runs the matching
  `Fetcher`, applies post-processing hooks, and returns an `OBBject`.
- **`openbb_core.app.static.package_builder`** — walks the merged router and
  emits the typed `openbb/package/` modules plus `reference.json`. This is
  what `openbb-build` ultimately drives.
- **`openbb_core.api.rest_api`** — the FastAPI app (`app`) built from the same
  routers, with auth hooks and OpenAPI generation. Serve it with any ASGI
  server.
- **`openbb_core.app.extension_loader`** — the entry-point discovery layer
  described above.
- **`openbb_core.app.service`** — system settings, user settings, credentials,
  and auth services shared by the runtime and the REST API.
- **`openbb_core.app.logs`** — structured logging with rotating file handlers.

## Prerequisites

- Python `>=3.11,<4`
- For extension authors: working knowledge of FastAPI and Pydantic v2.

## Installation

```sh
pip install openbb-core
```

You normally do not install `openbb-core` directly — `openbb` and provider
extensions pull it in. Install it explicitly only when authoring an extension.

## Running the REST API

```sh
uvicorn openbb_core.api.rest_api:app --reload
```

The same router graph that backs `from openbb import obb` is exposed over
HTTP, with OpenAPI available at `/docs`.

## Bugs

Report bugs on
[GitHub](https://github.com/OpenBB-finance/OpenBB/issues/new/choose).

## License

Apache-2.0. See
[LICENSE](https://github.com/OpenBB-finance/OpenBB/blob/main/LICENSE).
