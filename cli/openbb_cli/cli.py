"""OpenBB Platform CLI entry point."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from openbb_cli.utils.utils import change_logging_sub_app, reset_logging_sub_app


def _materialize_socrata_spec(story_source: str) -> str:
    """Build a Socrata spec from a story and write it to a temp file."""
    import tempfile

    from openbb_cli.dispatchers.socrata import build_socrata_spec
    from openbb_cli.dispatchers.spec import write_spec

    spec_doc = build_socrata_spec(story_source)
    fd, path = tempfile.mkstemp(prefix="openbb-socrata-", suffix=".spec")
    os.close(fd)
    write_spec(path, spec_doc)
    return path


def _parse_spec_arg(token: str) -> tuple[str | None, str]:
    """``[NAME=]PATH`` to ``(name, path)``; returns ``(None, path)`` if no name."""
    if "=" in token:
        name, _, path = token.partition("=")
        name = name.strip()
        path = path.strip()
        if not name or not path:
            raise ValueError(f"--spec entry {token!r} is malformed; expected NAME=PATH")
        return (name, path)
    return (None, token.strip())


def _resolve_spec_entries(
    cli_spec: list[str],
    config_specs: Any,
    config_single_spec: str | None = None,
) -> list[tuple[str | None, str]]:
    """Build the final ``[(namespace_or_None, path), ...]`` list."""
    entries: list[tuple[str | None, str]] = []
    if cli_spec:
        for token in cli_spec:
            entries.append(_parse_spec_arg(token))
    elif isinstance(config_specs, dict) and config_specs:
        for ns, info in config_specs.items():
            path = info.get("path") if isinstance(info, dict) else info
            if not path:
                raise ValueError(f"[specs.{ns}] missing required 'path' key")
            entries.append((str(ns), str(path)))
    elif config_single_spec:
        entries.append((None, str(config_single_spec)))
    else:
        env_path = os.environ.get("OPENBB_SPEC_PATH")
        if env_path:
            entries.append((None, env_path))
    unnamed = [e for e in entries if e[0] is None]
    if unnamed and len(entries) > 1:
        raise ValueError(
            "When passing multiple --spec entries, every one must be NAME=PATH; "
            "an unnamed --spec PATH may only appear alone."
        )
    return entries


def _split_scoped_token(token: str, namespaces: set[str]) -> tuple[str | None, str]:
    """Detect a ``<NS>:rest`` namespace prefix on a header / query-param token."""
    if ":" not in token:
        return (None, token)
    leading, _, rest = token.partition(":")
    if leading.strip() in namespaces:
        return (leading.strip(), rest)
    return (None, token)


def _split_per_namespace(
    cli_tokens: list[str], namespaces: set[str]
) -> tuple[list[str], dict[str, list[str]]]:
    """Partition CLI ``-H`` / ``-Q`` tokens into ``(global, per_ns)`` buckets."""
    global_tokens: list[str] = []
    per_ns: dict[str, list[str]] = {ns: [] for ns in namespaces}
    for token in cli_tokens or []:
        ns, rest = _split_scoped_token(token, namespaces)
        if ns is None:
            global_tokens.append(token)
        else:
            per_ns[ns].append(rest)
    return global_tokens, per_ns


def _merge_dicts(*dicts: dict[str, str] | None) -> dict[str, str] | None:
    """Right-biased merge of optional dicts; returns ``None`` if the result is empty."""
    out: dict[str, str] = {}
    for d in dicts:
        if d:
            out.update(d)
    return out or None


def _parse_header_kv(token: str) -> tuple[str, str]:
    """Split a ``KEY=VALUE`` or ``KEY: VALUE`` header token."""
    eq = token.find("=")
    colon = token.find(":")
    if eq == -1 and colon == -1:
        raise ValueError(f"--header must be 'KEY=VALUE' or 'KEY: VALUE'; got {token!r}")
    if eq != -1 and (colon == -1 or eq < colon):
        key, value = token[:eq], token[eq + 1 :]
    else:
        key, value = token[:colon], token[colon + 1 :]
    return key.strip(), value.strip()


def _resolve_headers(
    cli_headers: list[str] | None,
    header_file: str | None,
    config_headers: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    """Merge headers in priority order (lowest to highest)."""
    headers: dict[str, str] = {}
    if config_headers:
        for k, v in config_headers.items():
            headers[str(k)] = str(v)
    if header_file:
        try:
            file_data = json.loads(Path(header_file).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"--header-file: {exc}\n")
            return None
        if not isinstance(file_data, dict):
            sys.stderr.write("--header-file must contain a JSON object.\n")
            return None
        for k, v in file_data.items():
            headers[str(k)] = str(v)
    for token in cli_headers or []:
        k, v = _parse_header_kv(token)
        headers[k] = v
    return headers or None


_QUERY_ENV_PREFIX = "OPENBB_HTTP_QUERY_"


def _resolve_query_params(
    cli_params: list[str] | None,
    param_file: str | None,
    config_query: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    """Merge query params in priority order (lowest to highest)."""
    import os

    params: dict[str, str] = {}
    if config_query:
        for k, v in config_query.items():
            params[str(k)] = str(v)
    if param_file:
        try:
            file_data = json.loads(Path(param_file).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"--query-param-file: {exc}\n")
            return None
        if not isinstance(file_data, dict):
            sys.stderr.write("--query-param-file must contain a JSON object.\n")
            return None
        for k, v in file_data.items():
            params[str(k)] = str(v)
    for env_key, env_val in os.environ.items():
        if env_key.startswith(_QUERY_ENV_PREFIX):
            name = env_key[len(_QUERY_ENV_PREFIX) :].lower()
            params[name] = env_val
    for token in cli_params or []:
        k, _, v = token.partition("=")
        if not k or not v:
            sys.stderr.write(f"--query-param must be 'KEY=VALUE'; got {token!r}\n")
            return None
        params[k.strip()] = v.strip()
    return params or None


def _resolve_auth_hooks(
    config: dict[str, Any],
    namespaces: set[str],
) -> tuple[Any, dict[str, Any]]:
    """Import the configured auth hooks (global and per-namespace)."""
    from openbb_cli.auth import resolve_auth_hook

    def _hook_value(table: dict[str, Any]) -> str | None:
        spec = table.get("auth-hook") or table.get("auth_hook")
        return spec if isinstance(spec, str) and spec else None

    global_spec = _hook_value(config)
    global_hook = resolve_auth_hook(global_spec) if global_spec else None
    per_ns_hooks: dict[str, Any] = {}
    config_specs = config.get("specs")
    if isinstance(config_specs, dict):
        for ns in namespaces:
            entry = config_specs.get(ns)
            if not isinstance(entry, dict):
                continue
            ns_spec = _hook_value(entry)
            if ns_spec:
                per_ns_hooks[ns] = resolve_auth_hook(ns_spec)
    return global_hook, per_ns_hooks


def _resolve_per_ns_auth(
    per_ns_h_tokens: dict[str, list[str]],
    per_ns_q_tokens: dict[str, list[str]],
    namespaces: set[str],
    config_specs: dict[str, Any] | None,
) -> tuple[dict[str, dict[str, str]] | None, dict[str, dict[str, str]] | None]:
    """Build per-namespace header / query maps from CLI flags and TOML."""
    per_ns_headers: dict[str, dict[str, str]] = {}
    per_ns_query: dict[str, dict[str, str]] = {}
    for ns in namespaces:
        h: dict[str, str] = {}
        q: dict[str, str] = {}
        if config_specs and isinstance(config_specs.get(ns), dict):
            spec_cfg = config_specs[ns]
            for k, v in (spec_cfg.get("headers") or {}).items():
                h[str(k)] = str(v)
            for k, v in (spec_cfg.get("query") or {}).items():
                q[str(k)] = str(v)
        for token in per_ns_h_tokens.get(ns, []):
            try:
                key, value = _parse_header_kv(token)
            except ValueError as exc:
                sys.stderr.write(f"--header (scoped to {ns}): {exc}\n")
                return None, None
            h[key] = value
        for token in per_ns_q_tokens.get(ns, []):
            key, _, value = token.partition("=")
            if not key or not value:
                sys.stderr.write(
                    f"--query-param (scoped to {ns}) must be 'KEY=VALUE'; "
                    f"got {token!r}\n"
                )
                return None, None
            q[key.strip()] = value.strip()
        if h:
            per_ns_headers[ns] = h
        if q:
            per_ns_query[ns] = q
    return per_ns_headers, per_ns_query


def _build_spec_dispatcher(
    spec_entries: list[tuple[str | None, str]],
    headers: dict[str, str] | None,
    query_params: dict[str, str] | None,
    per_ns_headers: dict[str, dict[str, str]] | None = None,
    per_ns_query: dict[str, dict[str, str]] | None = None,
    global_auth_hook: Any = None,
    per_ns_auth_hooks: dict[str, Any] | None = None,
):
    """Build the HTTP dispatcher backed by one or more ``.spec`` files."""
    from openbb_cli.dispatchers.http import http_dispatcher_from_spec
    from openbb_cli.dispatchers.spec import load_spec

    if len(spec_entries) == 1 and spec_entries[0][0] is None:
        _, path = spec_entries[0]
        return http_dispatcher_from_spec(
            load_spec(path),
            headers=headers,
            query_params=query_params,
            auth_hook=global_auth_hook,
        )
    from openbb_cli.dispatchers.multi import MultiSpecDispatcher

    per_ns_headers = per_ns_headers or {}
    per_ns_query = per_ns_query or {}
    per_ns_auth_hooks = per_ns_auth_hooks or {}
    backends: dict[str, Any] = {}
    for name, path in spec_entries:
        if name is None:
            raise ValueError(
                "multi-spec entry missing namespace; pass --spec NAME=PATH"
            )
        ns_headers = _merge_dicts(headers, per_ns_headers.get(name))
        ns_query = _merge_dicts(query_params, per_ns_query.get(name))
        ns_hook = per_ns_auth_hooks.get(name, global_auth_hook)
        backends[name] = http_dispatcher_from_spec(
            load_spec(path),
            headers=ns_headers,
            query_params=ns_query,
            auth_hook=ns_hook,
            namespace=name,
        )
    return MultiSpecDispatcher(backends)


def _build_dispatcher(
    server_url: str | None,
    headers: dict[str, str] | None = None,
    query_params: dict[str, str] | None = None,
    spec_entries: list[tuple[str | None, str]] | None = None,
    per_ns_headers: dict[str, dict[str, str]] | None = None,
    per_ns_query: dict[str, dict[str, str]] | None = None,
    global_auth_hook: Any = None,
    per_ns_auth_hooks: dict[str, Any] | None = None,
):
    """Resolve a dispatcher from CLI args."""
    if spec_entries:
        return _build_spec_dispatcher(
            spec_entries,
            headers,
            query_params,
            per_ns_headers,
            per_ns_query,
            global_auth_hook=global_auth_hook,
            per_ns_auth_hooks=per_ns_auth_hooks,
        )
    if server_url:
        from openbb_cli.dispatchers.http import http_dispatcher_from_server

        return http_dispatcher_from_server(
            server_url,
            headers=headers,
            query_params=query_params,
            auth_hook=global_auth_hook,
        )
    from openbb_cli.dispatchers import LocalDispatcher

    return LocalDispatcher()


def _launch_repl(
    dev: bool,
    debug: bool,
    spec_entries: list[tuple[str | None, str]] | None = None,
    server_url: str | None = None,
    headers: dict[str, str] | None = None,
    query_params: dict[str, str] | None = None,
    per_ns_headers: dict[str, dict[str, str]] | None = None,
    per_ns_query: dict[str, dict[str, str]] | None = None,
    global_auth_hook: Any = None,
    per_ns_auth_hooks: dict[str, Any] | None = None,
    initial_command: list[str] | None = None,
) -> int:
    """Launch the interactive REPL."""
    sys.stdout.write("Loading...\n")
    sys.stdout.flush()
    from openbb_cli.config.setup import bootstrap

    backend: object | None = None
    if spec_entries:
        from openbb_cli.backend import SpecBackend

        dispatcher = _build_spec_dispatcher(
            spec_entries,
            headers,
            query_params,
            per_ns_headers,
            per_ns_query,
            global_auth_hook=global_auth_hook,
            per_ns_auth_hooks=per_ns_auth_hooks,
        )
        backend = SpecBackend(dispatcher._spec_doc, dispatcher)
    elif server_url:
        from openbb_cli.backend import SpecBackend
        from openbb_cli.dispatchers.http import http_dispatcher_from_server
        from openbb_cli.dispatchers.openapi_schema import fetch_openapi
        from openbb_cli.dispatchers.spec import build_spec_document

        openapi = fetch_openapi(server_url, headers=headers, query_params=query_params)
        spec_doc = build_spec_document(openapi, base_url=server_url)
        backend = SpecBackend(
            spec_doc,
            http_dispatcher_from_server(
                server_url,
                headers=headers,
                query_params=query_params,
                auth_hook=global_auth_hook,
            ),
        )

    bootstrap()
    from openbb_cli.controllers.cli_controller import run_cli, session

    _apply_interactive_defaults(session.settings)
    if debug:
        session.settings.DEBUG_MODE = True
    if dev:
        session.settings.DEV_BACKEND = True

    queue: list[str] | None = None
    if initial_command:
        joined = " ".join(initial_command).replace(" /", "/home/")
        if joined:
            queue = [joined]
    run_cli(queue, backend=backend)
    return 0


def _apply_interactive_defaults(settings: Any) -> None:
    """Apply REPL-friendly defaults without clobbering explicit user choices."""
    if getattr(settings, "OUTPUT_MODE", "tsv") == "tsv":
        settings.OUTPUT_MODE = "rich"
    if getattr(settings, "USE_INTERACTIVE_DF", False) is False:
        settings.USE_INTERACTIVE_DF = True
    settings.TEST_MODE = False


def _generate_spec(
    server_url: str | None,
    output_path: str,
    openapi_path: str | None,
    headers: dict[str, str] | None = None,
    query_params: dict[str, str] | None = None,
    socrata_story: str | None = None,
) -> int:
    """Build a precomputed .spec file from one of the supported sources."""
    from openbb_cli.dispatchers.spec import write_spec

    if socrata_story:
        from openbb_cli.dispatchers.socrata import build_socrata_spec

        spec_doc = build_socrata_spec(socrata_story)
        write_spec(output_path, spec_doc)
        skipped = (spec_doc.get("_socrata") or {}).get("skipped") or []
        sys.stdout.write(
            f"wrote {len(spec_doc['commands'])} dataset commands to {output_path}"
        )
        if skipped:
            sys.stdout.write(f" (skipped {len(skipped)} non-dataset views)")
        sys.stdout.write("\n")
        return 0

    if not server_url:
        sys.stderr.write(
            "--generate-spec requires --server URL (or OPENBB_SERVER_URL env var) "
            "or --socrata-story URL_OR_PATH.\n"
        )
        return 2

    from openbb_cli.dispatchers.openapi_schema import fetch_openapi
    from openbb_cli.dispatchers.spec import build_spec_document

    openapi = fetch_openapi(
        server_url, path=openapi_path, headers=headers, query_params=query_params
    )
    if openapi_path and (
        openapi_path.startswith("http://") or openapi_path.startswith("https://")
    ):
        source_url = openapi_path
    elif openapi_path:
        source_url = server_url.rstrip("/") + openapi_path
    else:
        source_url = server_url.rstrip("/") + "/openapi.json"
    spec_doc = build_spec_document(
        openapi, base_url=server_url, source_url=source_url, headers=headers
    )
    if not spec_doc["commands"]:
        sys.stderr.write(
            f"generated 0 commands from {source_url} — the document exposes no "
            "GET/POST operations OpenBB can map. Multi-file specs that split "
            "paths across documents with external $refs must be bundled into "
            "a single file first.\n"
        )
        return 2
    write_spec(output_path, spec_doc)
    sys.stdout.write(f"wrote {len(spec_doc['commands'])} commands to {output_path}\n")
    return 0


def _filter_spec_commands(
    spec_doc: dict[str, Any],
    *,
    include: list[str] | None,
    exclude: list[str] | None,
) -> dict[str, Any]:
    """Apply ``--include`` / ``--exclude`` glob filters to a spec's commands."""
    if not include and not exclude:
        return spec_doc
    from fnmatch import fnmatchcase

    commands: dict[str, Any] = spec_doc.get("commands") or {}
    include_patterns = include or []
    exclude_patterns = exclude or []

    def _matches(name: str, patterns: list[str]) -> bool:
        return any(fnmatchcase(name, pat) for pat in patterns)

    filtered: dict[str, Any] = {}
    for name, cmd in commands.items():
        if include_patterns:
            if _matches(name, include_patterns):
                filtered[name] = cmd
            continue
        if exclude_patterns and _matches(name, exclude_patterns):
            continue
        filtered[name] = cmd
    return {**spec_doc, "commands": filtered}


def _generate_extension(
    spec_entries: list[tuple[str | None, str]],
    output_path: str,
    *,
    provider_name: str | None,
    project_name: str | None,
    package_name: str | None,
    router_name: str | None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> int:
    """Generate a full installable OpenBB extension from a ``.spec`` file.

    Parameters
    ----------
    spec_entries : list of (str or None, str)
        Resolved ``--spec`` entries; exactly one entry is required.
    output_path : str
        Directory to write the extension package to.
    provider_name : str, optional
        Snake-case provider identifier.
    project_name : str, optional
        PyPI distribution name.
    package_name : str, optional
        Python package directory name.
    router_name : str, optional
        Router identifier.
    include : list of str, optional
        Glob patterns; only matching commands are emitted. Takes priority over ``exclude``.
    exclude : list of str, optional
        Glob patterns; matching commands are dropped.

    Returns
    -------
    int
        Process exit code: 0 on success, 2 on bad input.
    """
    if len(spec_entries) != 1:
        sys.stderr.write(
            "--generate-extension requires exactly one --spec PATH (or [NAME=]PATH).\n"
        )
        return 2
    _, spec_path = spec_entries[0]

    from openbb_cli.codegen.package_gen import generate_packages
    from openbb_cli.dispatchers.spec import load_spec

    spec_doc = load_spec(spec_path)
    original_count = len(spec_doc.get("commands") or {})
    if original_count == 0:
        sys.stderr.write(
            f"--generate-extension: spec at {spec_path} contains 0 commands — "
            "nothing to generate. Regenerate the spec against a source that "
            "exposes GET/POST operations.\n"
        )
        return 2
    spec_doc = _filter_spec_commands(spec_doc, include=include, exclude=exclude)
    filtered_count = len(spec_doc.get("commands") or {})
    if (include or exclude) and filtered_count == 0:
        sys.stderr.write(
            "--generate-extension: --include / --exclude filters matched no "
            f"commands (started with {original_count}). Check your patterns.\n"
        )
        return 2
    if include or exclude:
        sys.stdout.write(
            f"filter: {filtered_count}/{original_count} commands kept "
            f"(include={include or '-'}, exclude={exclude or '-'})\n"
        )
    output = Path(output_path)
    derived_provider = provider_name or output.name or "generated_extension"
    package_set = generate_packages(
        spec_doc,
        output_root=output,
        provider_name=derived_provider,
        project_name=project_name,
        package_name=package_name,
        router_name=router_name,
    )
    paths = package_set.write()
    for pkg, path in zip(package_set.packages, paths, strict=True):
        total_get = sum(len(v) for v in pkg.fetchers_by_provider.values())
        total_post = len(pkg.post_commands)
        sys.stdout.write(
            f"wrote project to {path}\n"
            f"  providers ({len(pkg.providers)}): "
            f"{', '.join(p.provider_name for p in pkg.providers)}\n"
            f"  routers ({len(pkg.top_level_routers)}): "
            f"{', '.join(pkg.top_level_routers)}\n"
            f"  fetchers: {total_get} GET (across all providers)\n"
            f"  POST:     {total_post} local-compute commands\n"
            f"  install:  pip install -e {path}\n"
            f"  build:    openbb-build\n"
        )
    return 0


def _run_spec_one_shot(
    spec_entries: list[tuple[str | None, str]],
    command_argv: list[str],
    headers: dict[str, str] | None = None,
    query_params: dict[str, str] | None = None,
    per_ns_headers: dict[str, dict[str, str]] | None = None,
    per_ns_query: dict[str, dict[str, str]] | None = None,
    global_auth_hook: Any = None,
    per_ns_auth_hooks: dict[str, Any] | None = None,
) -> int:
    """Dispatch a single command using one or more precomputed ``.spec`` files."""
    from openbb_cli.dispatchers.protocol import Request, Response
    from openbb_cli.dispatchers.runtime import (
        _follow_stream,
        _looks_like_stream,
        _to_json_line,
    )
    from openbb_cli.dispatchers.spec import SpecCommandError, parse_command_argv

    if not command_argv:
        sys.stderr.write(
            "usage: openbb --spec [NAME=]PATH <command.path> [--key value]\n"
        )
        return 2

    dispatcher = _build_spec_dispatcher(
        spec_entries,
        headers,
        query_params,
        per_ns_headers,
        per_ns_query,
        global_auth_hook=global_auth_hook,
        per_ns_auth_hooks=per_ns_auth_hooks,
    )
    try:
        command, params = parse_command_argv(dispatcher._spec_doc, command_argv)
    except SpecCommandError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2

    async def _dispatch_and_close() -> Response:
        try:
            return await dispatcher.dispatch(Request(command=command, params=params))
        finally:
            await dispatcher.aclose()

    response: Response = asyncio.run(_dispatch_and_close())

    if response.ok and _looks_like_stream(response.result):
        return _follow_stream(response.result)

    sys.stdout.write(_to_json_line(response) + "\n")
    sys.stdout.flush()

    return 0 if response.ok else 1


_CONFIG_SCALAR_KEYS = (
    "server",
    "openapi_path",
    "header_file",
    "query_param_file",
    "output",
    "batch_concurrency",
)

# Env var (if any) that already wins over TOML for each key, per the documented
# precedence "defaults -> ... -> TOML -> .env files -> OPENBB_* env vars -> CLI
# flags". Some of these flags bake a non-empty literal into their argparse
# default (e.g. --output, --batch-concurrency), so `parser.get_default(key)`
# can't be used to detect "unset" — it's checked against the env var directly.
_CONFIG_SCALAR_ENV_VARS = {
    "server": "OPENBB_SERVER_URL",
    "header_file": "OPENBB_HEADER_FILE",
    "query_param_file": "OPENBB_QUERY_PARAM_FILE",
    "batch_concurrency": "OPENBB_CLI_BATCH_CONCURRENCY",
}


def _peek_flag(argv: list[str], flag: str) -> str | None:
    """Pull ``--flag VALUE`` (or ``--flag=VALUE``) out of argv without parsing the rest."""
    for i, tok in enumerate(argv):
        if tok == flag and i + 1 < len(argv):
            return argv[i + 1]
        if tok.startswith(flag + "="):
            return tok.split("=", 1)[1]
    return None


def _apply_config_defaults(
    parser: Any, raw_argv: list[str], config: dict[str, Any]
) -> None:
    """Apply layered TOML config as argparse defaults for unset flags."""
    overrides: dict[str, Any] = {}
    for key in _CONFIG_SCALAR_KEYS:
        value = config.get(key)
        if value is None:
            continue
        env_var = _CONFIG_SCALAR_ENV_VARS.get(key)
        if env_var and os.environ.get(env_var):
            continue
        overrides[key] = value
    if overrides:
        parser.set_defaults(**overrides)


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0911
    """Use the main entry point for the OpenBB Platform CLI."""
    from openbb_cli.config.loader import (
        apply_settings_to_env,
        load_config,
        load_env_files,
    )
    from openbb_cli.dispatchers.runtime import build_parser, run_argv, run_batch

    raw_argv = list(argv if argv is not None else sys.argv[1:])
    load_env_files(_peek_flag(raw_argv, "--env-file"))
    explicit_cfg = _peek_flag(raw_argv, "--config")
    config = load_config(explicit_cfg)
    apply_settings_to_env(config)

    parser = build_parser()
    _apply_config_defaults(parser, raw_argv, config)
    args = parser.parse_args(raw_argv)

    try:
        spec_entries = _resolve_spec_entries(
            getattr(args, "spec", []) or [],
            config.get("specs"),
            config_single_spec=config.get("spec"),
        )
    except ValueError as exc:
        sys.stderr.write(f"--spec: {exc}\n")
        return 2

    socrata_story = getattr(args, "socrata_story", None)
    if socrata_story and not args.generate_spec:
        try:
            socrata_path = _materialize_socrata_spec(socrata_story)
        except (OSError, ValueError) as exc:
            sys.stderr.write(f"--socrata-story: {exc}\n")
            return 2
        if not spec_entries:
            spec_entries = [(None, socrata_path)]
        else:
            spec_entries.append(("socrata", socrata_path))

    namespaces: set[str] = {n for n, _ in spec_entries if n}
    config_specs = (
        config.get("specs") if isinstance(config.get("specs"), dict) else None
    )

    cli_headers = list(getattr(args, "header", []) or [])
    cli_query = list(getattr(args, "query_param", []) or [])
    global_h_tokens, per_ns_h_tokens = _split_per_namespace(cli_headers, namespaces)
    global_q_tokens, per_ns_q_tokens = _split_per_namespace(cli_query, namespaces)

    headers = _resolve_headers(
        global_h_tokens,
        args.header_file,
        config_headers=config.get("headers"),
    )
    if headers is None and (cli_headers or args.header_file):
        return 2

    query_params = _resolve_query_params(
        global_q_tokens,
        args.query_param_file,
        config_query=config.get("query"),
    )
    if query_params is None and (cli_query or args.query_param_file):
        return 2

    per_ns_headers, per_ns_query = _resolve_per_ns_auth(
        per_ns_h_tokens, per_ns_q_tokens, namespaces, config_specs
    )
    if per_ns_headers is None or per_ns_query is None:
        return 2

    try:
        global_auth_hook, per_ns_auth_hooks = _resolve_auth_hooks(config, namespaces)
    except (ValueError, ImportError, TypeError) as exc:
        sys.stderr.write(f"auth-hook: {exc}\n")
        return 2

    if args.print_config_template:
        from openbb_cli.config.loader import render_config_template

        sys.stdout.write(render_config_template(active=config))
        sys.stdout.flush()
        return 0

    if args.show_config:
        sys.stdout.write(json.dumps(config, indent=2, default=str) + "\n")
        sys.stdout.flush()
        return 0

    if args.generate_spec:
        leftover = list(args.command or [])
        output_path = args.output
        if leftover:
            if output_path == "openbb.spec":
                output_path = leftover[0]
                leftover = leftover[1:]
            if leftover:
                sys.stderr.write(
                    "--generate-spec takes no extra positional arguments after "
                    f"the output path; got {leftover!r}. Use "
                    "``--output PATH`` to be explicit.\n"
                )
                return 2
        return _generate_spec(
            args.server,
            output_path,
            args.openapi_path,
            headers,
            query_params,
            socrata_story=getattr(args, "socrata_story", None),
        )

    if getattr(args, "generate_extension", False):
        return _generate_extension(
            spec_entries,
            args.output,
            provider_name=args.provider_name,
            project_name=args.project_name,
            package_name=args.package_name,
            router_name=args.router_name,
            include=getattr(args, "include", None),
            exclude=getattr(args, "exclude", None),
        )

    if args.interactive:
        return _launch_repl(
            args.dev,
            args.debug,
            spec_entries,
            args.server,
            headers,
            query_params,
            per_ns_headers,
            per_ns_query,
            global_auth_hook=global_auth_hook,
            per_ns_auth_hooks=per_ns_auth_hooks,
            initial_command=args.command,
        )

    if args.list_commands or args.describe:
        return _run_introspection(
            spec_entries,
            args.server,
            headers,
            query_params,
            per_ns_headers,
            per_ns_query,
            global_auth_hook=global_auth_hook,
            per_ns_auth_hooks=per_ns_auth_hooks,
            list_commands=args.list_commands,
            describe=args.describe,
        )

    if spec_entries and not args.batch:
        return _run_spec_one_shot(
            spec_entries,
            args.command,
            headers,
            query_params,
            per_ns_headers,
            per_ns_query,
            global_auth_hook=global_auth_hook,
            per_ns_auth_hooks=per_ns_auth_hooks,
        )

    dispatcher = _build_dispatcher(
        args.server,
        headers=headers,
        query_params=query_params,
        spec_entries=spec_entries,
        per_ns_headers=per_ns_headers,
        per_ns_query=per_ns_query,
        global_auth_hook=global_auth_hook,
        per_ns_auth_hooks=per_ns_auth_hooks,
    )

    if args.batch:
        return run_batch(dispatcher, concurrency=args.batch_concurrency)

    if not args.command:
        parser.print_help(sys.stderr)
        return 2

    spec_doc = getattr(dispatcher, "_spec_doc", None)
    if spec_doc:
        return _run_spec_dispatch(dispatcher, spec_doc, args.command)
    return run_argv(dispatcher, args.command)


def _run_spec_dispatch(
    dispatcher: Any, spec_doc: dict[str, Any], command_argv: list[str]
) -> int:
    """Schema-validated one-shot dispatch reusing an existing dispatcher."""
    from openbb_cli.dispatchers.protocol import Request, Response
    from openbb_cli.dispatchers.runtime import (
        _follow_stream,
        _looks_like_stream,
        _to_json_line,
    )
    from openbb_cli.dispatchers.spec import SpecCommandError, parse_command_argv

    try:
        command, params = parse_command_argv(spec_doc, command_argv)
    except SpecCommandError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2

    async def _dispatch() -> Response:
        return await dispatcher.dispatch(Request(command=command, params=params))

    response: Response = asyncio.run(_dispatch())

    if response.ok and _looks_like_stream(response.result):
        return _follow_stream(response.result)

    sys.stdout.write(_to_json_line(response) + "\n")
    sys.stdout.flush()

    return 0 if response.ok else 1


def _run_introspection(
    spec_entries: list[tuple[str | None, str]],
    server_url: str | None,
    headers: dict[str, str] | None,
    query_params: dict[str, str] | None,
    per_ns_headers: dict[str, dict[str, str]] | None,
    per_ns_query: dict[str, dict[str, str]] | None,
    global_auth_hook: Any = None,
    per_ns_auth_hooks: dict[str, Any] | None = None,
    *,
    list_commands: bool,
    describe: str | None,
) -> int:
    """Dispatch ``__commands__`` / ``__schema__`` against a spec/server."""
    from openbb_cli.dispatchers.http import http_dispatcher_from_server
    from openbb_cli.dispatchers.protocol import Request, Response
    from openbb_cli.dispatchers.runtime import _to_json_line

    if spec_entries:
        dispatcher = _build_spec_dispatcher(
            spec_entries,
            headers,
            query_params,
            per_ns_headers,
            per_ns_query,
            global_auth_hook=global_auth_hook,
            per_ns_auth_hooks=per_ns_auth_hooks,
        )
    elif server_url:
        dispatcher = http_dispatcher_from_server(
            server_url,
            headers=headers,
            query_params=query_params,
            auth_hook=global_auth_hook,
        )
    else:
        sys.stderr.write(
            "--list-commands / --describe require --spec [NAME=]PATH or --server URL.\n"
        )
        return 2

    if list_commands:
        request = Request(command="__commands__")
    else:
        name, _, provider = (describe or "").partition(":")
        params: dict[str, Any] = {"name": name}
        if provider:
            params["provider"] = provider
        request = Request(command="__schema__", params=params)

    async def _dispatch_and_close() -> Response:
        try:
            return await dispatcher.dispatch(request)
        finally:
            await dispatcher.aclose()

    response: Response = asyncio.run(_dispatch_and_close())
    sys.stdout.write(_to_json_line(response) + "\n")
    sys.stdout.flush()
    return 0 if response.ok else 1


if __name__ == "__main__":
    initial_logging_sub_app = change_logging_sub_app()
    try:
        sys.exit(main())
    except BrokenPipeError:
        with contextlib.suppress(Exception):
            sys.stdout.close()
        sys.exit(0)
    except Exception:
        logging.exception("An unexpected error occurred")
        sys.exit(1)
    finally:
        reset_logging_sub_app(initial_logging_sub_app)
