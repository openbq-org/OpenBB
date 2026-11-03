"""Runtime entry points for the dispatcher subsystem."""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import os
import sys
from collections.abc import Iterable
from typing import IO, Any

from openbb_cli.dispatchers.base import Dispatcher
from openbb_cli.dispatchers.protocol import Request, Response, ResponseError

DEFAULT_BATCH_CONCURRENCY = 8


_JSON_LITERALS = {"true": True, "false": False, "null": None}


def _coerce_literal(text: str) -> Any:
    """Best-effort coerce a CLI string to a Python literal."""
    if text in _JSON_LITERALS:
        return _JSON_LITERALS[text]
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def parse_argv(argv: Iterable[str]) -> Request:
    """Convert positional+kv argv into a Request."""
    args = list(argv)
    if not args:
        raise SystemExit("usage: openbb <command.path> [--key value | --key=value]")
    command = args[0]
    params: dict[str, Any] = {}
    i = 1
    while i < len(args):
        token = args[i]
        if not token.startswith("--"):
            raise SystemExit(f"Unexpected positional argument: {token!r}")
        body = token[2:]
        if "=" in body:
            key, _, value = body.partition("=")
            params[key.replace("-", "_")] = _coerce_literal(value)
            i += 1
            continue
        if i + 1 < len(args) and not args[i + 1].startswith("--"):
            params[body.replace("-", "_")] = _coerce_literal(args[i + 1])
            i += 2
        else:
            params[body.replace("-", "_")] = True
            i += 1
    return Request(command=command, params=params)


async def _run_one(dispatcher: Dispatcher, request: Request) -> Response:
    return await dispatcher.dispatch(request)


def _to_json_line(response: Response) -> str:
    """Serialize a Response to a single JSON line, tolerating non-serializable values."""
    return json.dumps(
        response.model_dump(exclude_unset=True, exclude_none=True),
        default=str,
    )


def _looks_like_stream(value: Any) -> bool:
    """Duck-type an ``OBBStream``-like handle (lazy stream with start/stop/wait)."""
    return all(
        callable(getattr(value, attr, None)) for attr in ("start", "stop", "wait")
    )


def _follow_stream(stream: Any) -> int:
    """Follow a streaming result to STDOUT until it ends or Ctrl+C."""
    stream.start()
    try:
        stream.wait()
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop()
    return 0


def run_argv(dispatcher: Dispatcher, argv: Iterable[str]) -> int:
    """Dispatch a single command from argv and print the JSON response."""
    request = parse_argv(argv)
    response = asyncio.run(_run_one(dispatcher, request))
    if response.ok and _looks_like_stream(response.result):
        return _follow_stream(response.result)
    sys.stdout.write(_to_json_line(response) + "\n")
    sys.stdout.flush()
    return 0 if response.ok else 1


async def _batch_loop(
    dispatcher: Dispatcher,
    reader: IO[str],
    writer: IO[str],
    *,
    concurrency: int,
) -> int:
    """Core async loop for ``run_batch``."""
    sem = asyncio.Semaphore(concurrency)
    in_flight: set[asyncio.Task[Response]] = set()
    write_lock = asyncio.Lock()
    failures = 0

    async def _drain(task: asyncio.Task[Response]) -> None:
        nonlocal failures
        try:
            response = await task
        finally:
            sem.release()
        async with write_lock:
            writer.write(_to_json_line(response) + "\n")
            writer.flush()
        if not response.ok:
            failures += 1

    loop = asyncio.get_running_loop()

    def _readline() -> str:
        return reader.readline()

    while True:
        line = await loop.run_in_executor(None, _readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        payload: Any = None
        try:
            payload = json.loads(line)
            request = Request.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            err = Response(
                id=payload.get("id") if isinstance(payload, dict) else None,
                ok=False,
                error=ResponseError(type="RequestParseError", message=str(exc)),
            )
            async with write_lock:
                writer.write(err.model_dump_json() + "\n")
                writer.flush()
            failures += 1
            continue

        await sem.acquire()
        task = asyncio.create_task(_run_one(dispatcher, request))
        in_flight.add(task)
        task.add_done_callback(in_flight.discard)
        asyncio.create_task(_drain(task))

    if in_flight:
        await asyncio.gather(*in_flight, return_exceptions=True)
    return 0 if failures == 0 else 1


def run_batch(
    dispatcher: Dispatcher,
    reader: IO[str] | None = None,
    writer: IO[str] | None = None,
    *,
    concurrency: int | None = None,
) -> int:
    """Read NDJSON requests from ``reader``, write responses to ``writer``."""
    reader = reader if reader is not None else sys.stdin
    writer = writer if writer is not None else sys.stdout
    if concurrency is None:
        concurrency = int(
            os.environ.get("OPENBB_CLI_BATCH_CONCURRENCY", DEFAULT_BATCH_CONCURRENCY)
        )

    async def _run() -> int:
        try:
            return await _batch_loop(
                dispatcher, reader, writer, concurrency=concurrency
            )
        finally:
            await dispatcher.aclose()

    return asyncio.run(_run())


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser used by ``openbb_cli.cli:main``."""
    parser = argparse.ArgumentParser(
        prog="openbb",
        description="OpenBB Platform CLI. Default mode is non-TTY.",
        add_help=True,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Enter the interactive REPL with rich output and prompt-toolkit completion.",
    )
    mode.add_argument(
        "--batch",
        action="store_true",
        help="Read NDJSON requests from stdin; emit NDJSON responses to stdout.",
    )
    mode.add_argument(
        "--generate-spec",
        action="store_true",
        help=(
            "Fetch ``openapi.json`` from --server and write a precomputed "
            ".spec file to --output. Use --spec on subsequent invocations "
            "to skip the OpenAPI fetch + parse on every call."
        ),
    )
    mode.add_argument(
        "--generate-extension",
        action="store_true",
        help=(
            "Generate a full installable OpenBB Platform extension package "
            "from a .spec file (--spec PATH). Each spec becomes one provider "
            "with its own router. After generation: ``pip install -e <output>`` "
            "+ ``openbb-build`` registers it. Configure provider/project names "
            "via --provider-name / --project-name / --package-name / --router-name."
        ),
    )
    parser.add_argument(
        "--provider-name",
        metavar="NAME",
        default=None,
        help=(
            "Snake-case provider identifier for --generate-extension "
            "(default: derived from --output)."
        ),
    )
    parser.add_argument(
        "--project-name",
        metavar="NAME",
        default=None,
        help=(
            "PyPI distribution name for --generate-extension "
            "(default: openbb-<provider-name>)."
        ),
    )
    parser.add_argument(
        "--package-name",
        metavar="NAME",
        default=None,
        help=(
            "Python package directory for --generate-extension "
            "(default: openbb_<provider-name>)."
        ),
    )
    parser.add_argument(
        "--router-name",
        metavar="NAME",
        default=None,
        help=("Router identifier for --generate-extension (default: <provider-name>)."),
    )
    parser.add_argument(
        "--include",
        metavar="PATTERN",
        action="append",
        default=None,
        help=(
            "Include only commands whose dotted name matches PATTERN "
            "(repeat for multiple). ``*`` is a wildcard, e.g. "
            "``--include 'equity.*'`` keeps every command under the "
            "``equity`` namespace. When supplied, --include takes "
            "priority over --exclude (any non-matching command is "
            "dropped regardless of --exclude)."
        ),
    )
    parser.add_argument(
        "--exclude",
        metavar="PATTERN",
        action="append",
        default=None,
        help=(
            "Drop commands whose dotted name matches PATTERN (repeat "
            "for multiple). ``*`` is a wildcard, e.g. "
            "``--exclude 'equity.fundamentals.*'`` drops the whole "
            "fundamentals subtree. Ignored when --include is also "
            "supplied — see --include."
        ),
    )
    mode.add_argument(
        "--list-commands",
        action="store_true",
        help=(
            "Print every spec-declared command as a JSON list of "
            "``{name, method, url_path, description}`` rows. Equivalent "
            "to dispatching the reserved command ``__commands__``."
        ),
    )
    mode.add_argument(
        "--describe",
        metavar="COMMAND",
        default=None,
        help=(
            "Print the full schema (parameters with type/required/default/"
            "choices/help, plus method/url_path/description) for one "
            "command as JSON. Equivalent to dispatching ``__schema__`` "
            "with ``--name=COMMAND``."
        ),
    )
    mode.add_argument(
        "--print-config-template",
        action="store_true",
        help=(
            "Print a documented TOML template covering every supported "
            "config setting. Lines without a resolved value are commented "
            "out, so dropping the output at "
            "``~/.openbb_platform/openbb.toml`` is valid out of the box. "
            "Currently-resolved values from the layered config are inlined "
            "as live values."
        ),
    )
    mode.add_argument(
        "--show-config",
        action="store_true",
        help=(
            "Print the merged TOML config — the result of layering "
            "``pyproject.toml`` → user-global ``openbb.toml`` → project "
            "``openbb.toml`` → ``--config`` — as JSON. Useful for debugging "
            "which layer a given setting is coming from."
        ),
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        default=os.environ.get("OPENBB_CLI_CONFIG"),
        help=(
            "Load CLI configuration from a TOML file. Layered atop "
            "``[tool.openbb-cli]`` in the nearest ``pyproject.toml``, "
            "``~/.openbb_platform/openbb.toml`` (user-global), and any "
            "``openbb.toml`` walking up from the working directory; CLI "
            "flags and ``OPENBB_*`` env vars still win on conflict. Useful "
            "for swapping between ``congress.toml`` / ``platform.toml`` / "
            "``staging.toml`` without re-typing flags. (env: OPENBB_CLI_CONFIG)"
        ),
    )
    parser.add_argument(
        "--env-file",
        metavar="PATH",
        default=os.environ.get("OPENBB_CLI_ENV_FILE"),
        help=(
            "Path to a ``.env`` file to load into the process environment "
            "before argparse runs — so ``OPENBB_SERVER_URL``, "
            "``OPENBB_HTTP_QUERY_API_KEY``, etc. defined inside it populate "
            "the corresponding flags. ``~/.openbb_platform/.env`` is always "
            "tried as well (the canonical openbb-platform .env location); "
            "real shell exports always beat both. "
            "(env: OPENBB_CLI_ENV_FILE)"
        ),
    )
    parser.add_argument(
        "--batch-concurrency",
        metavar="N",
        type=int,
        default=int(
            os.environ.get("OPENBB_CLI_BATCH_CONCURRENCY", DEFAULT_BATCH_CONCURRENCY)
        ),
        help=(
            "Maximum number of concurrent in-flight dispatches in --batch "
            "mode. Higher values raise throughput against fast servers; "
            "lower values give back-pressure when an upstream rate-limits. "
            "(env: OPENBB_CLI_BATCH_CONCURRENCY, default: "
            f"{DEFAULT_BATCH_CONCURRENCY})"
        ),
    )
    parser.add_argument(
        "--server",
        metavar="URL",
        default=os.environ.get("OPENBB_SERVER_URL"),
        help=(
            "Dispatch through an openbb-platform-api server at URL "
            "(env: OPENBB_SERVER_URL). Default: in-process LocalDispatcher."
        ),
    )
    parser.add_argument(
        "--spec",
        metavar="[NAME=]PATH",
        action="append",
        default=[],
        help=(
            "Use a precomputed .spec file (built via --generate-spec) instead "
            "of fetching openapi.json. Repeatable: pass ``NAME=PATH`` to mount "
            "each spec under its own namespace (``congress.bill``, "
            "``nyfed.markets.ambs``). A single unnamed ``--spec PATH`` keeps the "
            "flat (unprefixed) command surface. The spec carries the server URL "
            "it was generated against, so --server is not required when using "
            "--spec. (env: OPENBB_SPEC_PATH)"
        ),
    )
    parser.add_argument(
        "--output",
        "-o",
        metavar="PATH",
        default="openbb.spec",
        help="Output path for --generate-spec (default: openbb.spec).",
    )
    parser.add_argument(
        "--openapi-path",
        metavar="PATH",
        default=None,
        help=(
            "Path (or full URL) to the OpenAPI document on the server. "
            "Defaults to /openapi.json. Servers that publish under a "
            "different name (e.g. NY Fed at /static/docs/markets-api.yml) "
            "need this. JSON or YAML accepted."
        ),
    )
    parser.add_argument(
        "--api-prefix",
        metavar="PREFIX",
        default=None,
        help=(
            "URL path prefix stripped from each path when --generate-spec names "
            "commands, e.g. ``--api-prefix /api/v3`` turns ``/api/v3/klines`` "
            "into ``klines``. Paths outside the prefix keep their full name; "
            "request URLs are unaffected. A path the prefix strips to nothing "
            "is skipped, and listed in a warning. Default: the longest prefix "
            "the paths share, leaving out each path's last segment."
        ),
    )
    parser.add_argument(
        "--overlay",
        metavar="PATH",
        action="append",
        default=None,
        help=(
            "OpenAPI Overlay 1.0 document (YAML or JSON) applied to the fetched "
            "OpenAPI description before --generate-spec builds the spec. Use it "
            "to correct upstream schema errors without editing the generated "
            "code. Repeatable; overlays apply in order."
        ),
    )
    parser.add_argument(
        "--socrata-story",
        metavar="URL_OR_PATH",
        default=None,
        help=(
            "Generate a .spec from a Socrata story JSON. Walks the story for "
            "every ``datasetUid``, fetches each dataset's column metadata, and "
            "emits one router namespace per dataset with a ``query`` command "
            "wrapping ``/resource/{uid}.json`` and the standard SoQL parameters "
            "(``$select`` / ``$where`` / ``$limit`` / ``$offset`` / ``$order`` "
            "/ ``$group`` / ``$having`` / ``$q``). Mutually exclusive with "
            "``--server`` for ``--generate-spec``."
        ),
    )
    parser.add_argument(
        "-H",
        "--header",
        metavar="KEY=VALUE",
        action="append",
        default=[],
        help=(
            "Custom HTTP header to send on every dispatch and on the "
            "OpenAPI fetch. Repeatable: ``-H 'Authorization: Bearer xxx' "
            "-H 'X-Tenant: acme'``. Both ``KEY=VALUE`` and ``KEY: VALUE`` "
            "forms are accepted."
        ),
    )
    parser.add_argument(
        "--header-file",
        metavar="PATH",
        default=os.environ.get("OPENBB_HEADER_FILE"),
        help=(
            "Read additional headers from a JSON file (object of string "
            "values). Headers from --header take precedence on conflicts. "
            "(env: OPENBB_HEADER_FILE)"
        ),
    )
    parser.add_argument(
        "-Q",
        "--query-param",
        metavar="KEY=VALUE",
        action="append",
        default=[],
        help=(
            "Query parameter injected on every request (e.g. APIs that "
            "authenticate via ``?api_key=...`` like https://api.congress.gov). "
            "Repeatable. Also auto-loaded from any env var prefixed "
            "``OPENBB_HTTP_QUERY_`` — ``OPENBB_HTTP_QUERY_API_KEY=xxx`` becomes "
            "``?api_key=xxx``. CLI flag takes precedence over env."
        ),
    )
    parser.add_argument(
        "--query-param-file",
        metavar="PATH",
        default=os.environ.get("OPENBB_QUERY_PARAM_FILE"),
        help=(
            "Read additional query params from a JSON file (object of string "
            "values). --query-param flags and ``OPENBB_HTTP_QUERY_*`` env vars "
            "take precedence on conflicts. (env: OPENBB_QUERY_PARAM_FILE)"
        ),
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Developer mode (verbose backend hooks).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Debug logging.",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Dotted command path followed by --key value pairs.",
    )
    return parser
