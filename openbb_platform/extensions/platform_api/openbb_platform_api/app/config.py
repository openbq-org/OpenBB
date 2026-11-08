"""Launcher TOML config bootstrap.

Hooks ``openbb-api`` into the same layered TOML cascade
``openbb-core`` ships with (pyproject → user-global → project →
explicit → .env → real-shell env vars), and surfaces two extra tables
the core loader doesn't itself consume:

* ``[launcher]`` — defaults for the ``openbb-api`` CLI flags (``host``,
  ``port``, ``app``, ``agents-json``, ``editable``, etc.). CLI flags
  always win; the TOML provides fallbacks.
* ``[env]`` — extra environment variables pushed into ``os.environ``
  before any heavy import runs. Lets containers inject API keys and
  other ``OPENBB_*`` knobs without shell exports. Real shell env vars
  always win (we never clobber a value the operator already set).

The ``--config-file <path>`` CLI flag and the ``OPENBB_API_CONFIG`` /
``OPENBB_CONFIG`` env vars all map to the same explicit-path slot in
the cascade — the highest-priority TOML layer below real env vars.

Container compatibility:

* Every cascade layer is optional. The user-global layer
  (``$HOME/.openbb_platform/openbb.toml``) is gracefully skipped when
  ``HOME`` is unset or unreadable.
* Project-local discovery walks up from CWD, so a single
  ``openbb.toml`` at the container root configures everything.
* The bootstrap runs BEFORE ``openbb_platform_api.app.app`` imports,
  so ``[env]`` keys are visible to the very first ``openbb_core.*``
  module load — no race between env injection and module-time
  ``Env()`` reads.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

logger = logging.getLogger("openbb_platform_api.config")

#: Match ``$VAR`` and ``${VAR}`` references in ``[env]`` values. The
#: identifier rule mirrors POSIX shell variable names: a leading
#: letter / underscore followed by letters / digits / underscores. A
#: ``$`` not followed by a valid identifier (e.g. ``$5``, ``$ ``,
#: ``$@``) is left untouched, so literal-dollar use cases still work.
_ENV_REF_PATTERN = re.compile(
    r"\$\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}"
    r"|\$(?P<bare>[A-Za-z_][A-Za-z0-9_]*)"
)

#: Env vars that, when set, point ``load_launcher_config`` at an
#: explicit TOML to use as the highest-priority layer in the cascade
#: (real shell env vars still win). ``OPENBB_API_CONFIG`` is the
#: launcher-specific name; ``OPENBB_CONFIG`` is core's existing slot —
#: we honor it too so a single env var can configure the whole stack.
EXPLICIT_CONFIG_ENVS: tuple[str, ...] = ("OPENBB_API_CONFIG", "OPENBB_CONFIG")

#: CLI flag that supplies an explicit config path. Detected by
#: ``extract_config_file_from_argv`` before the launcher's full
#: ``parse_args`` runs, so the bootstrap can find the TOML before
#: any heavy import.
CONFIG_FILE_FLAG = "--config-file"


def extract_config_file_from_argv(argv: list[str] | None = None) -> str | None:
    """Sniff ``--config-file <path>`` out of argv WITHOUT importing args.

    Used in two places:

    1. ``main.py`` — to find the config before the launcher's heavy
       module body runs.
    2. ``args.parse_args`` — same flag, full parser; this helper just
       gives ``main.py`` a peek.

    Accepts both ``--config-file PATH`` and ``--config-file=PATH``.
    Returns ``None`` if the flag isn't present or has no value.
    """
    args = (argv if argv is not None else sys.argv[1:]).copy()
    for i, arg in enumerate(args):
        if arg == CONFIG_FILE_FLAG and i + 1 < len(args):
            value = args[i + 1]
            if value and not value.startswith("--"):
                return value
        elif arg.startswith(f"{CONFIG_FILE_FLAG}="):
            return arg.split("=", 1)[1] or None
    return None


def resolve_explicit_config_path(
    cli_path: str | None = None,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Pick the explicit-path slot for the cascade.

    Priority (highest first): ``--config-file`` CLI value → env vars in
    ``EXPLICIT_CONFIG_ENVS`` order. Returns the first non-empty value
    or ``None`` when nothing is set.

    ``env`` is typed as ``Mapping`` (read-only) so callers can pass
    either ``os.environ`` (an ``_Environ`` instance) or a plain dict
    without ty complaining about variance.
    """
    if cli_path:
        return cli_path
    env_map: Mapping[str, str] = env if env is not None else os.environ
    for key in EXPLICIT_CONFIG_ENVS:
        value = env_map.get(key)
        if value:
            return value
    return None


def _validate_explicit_toml(explicit_path: str) -> None:
    """Pre-parse the user-supplied config so malformed TOML fails loudly.

    The core cascade swallows TOML decode errors (every layer is
    best-effort by design — a typo in someone else's pyproject.toml
    shouldn't crash an unrelated launcher). But when the operator
    passes ``--config-file`` or sets ``$OPENBB_API_CONFIG``, a parse
    failure means the deployment is silently misconfigured and the
    launcher would boot with defaults the operator never asked for.
    Raise instead so the error surfaces at startup.

    Missing files are tolerated (cascade behavior) — only
    parse failures escalate.
    """
    import tomllib
    from pathlib import Path

    p = Path(explicit_path)
    if not p.is_file():
        return
    try:
        with p.open("rb") as fh:
            tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(
            f"Malformed TOML at explicit config path '{explicit_path}': {exc}"
        ) from exc


def load_launcher_config(
    explicit_path: str | None = None,
    *,
    apply_to_services: bool = True,
    apply_to_env: bool = True,
) -> dict[str, Any]:
    """Run the layered TOML cascade and return the merged config.

    Thin wrapper around ``openbb_core.app.config.loader.load_layered_config``.
    Defaults preserve the core loader's behavior — push system/user
    sections onto the singleton services and emit ``OPENBB_*`` env vars
    for the promoted top-level flags. Pass ``apply_to_services=False``
    if you only want the dict for inspection (e.g., in tests).

    The returned dict includes the ``[launcher]`` and ``[env]`` tables
    raw — callers must run ``apply_launcher_env`` / merge launcher
    kwargs themselves; the core loader doesn't know about those.

    If ``explicit_path`` is provided, the file is pre-parsed so any
    TOML syntax errors raise immediately (instead of being silently
    swallowed by the cascade's best-effort layer handling).
    """
    from openbb_core.app.config.loader import load_layered_config

    if explicit_path:
        _validate_explicit_toml(explicit_path)

    return load_layered_config(
        explicit_path=explicit_path,
        apply_to_services=apply_to_services,
        apply_to_env=apply_to_env,
    )


def expand_env_refs(
    value: str, env: Mapping[str, str] | None = None
) -> tuple[str, list[str]]:
    """Public entry point for ``$VAR`` / ``${VAR}`` substitution.

    Used by ``apply_launcher_env`` for the ``[env]`` table and by
    ``[spec.headers]`` parsing for credential injection on the spec
    proxy. Defaults ``env`` to ``os.environ`` so callers don't have to
    plumb it through. ``env`` is typed as ``Mapping`` so ``os.environ``
    (an ``_Environ`` instance, not a plain dict) is accepted.
    Returns ``(expanded_value, missing_refs)`` — missing refs are
    reported left-to-right with deduplication.
    """
    return _expand_env_refs(value, env if env is not None else os.environ)


def _expand_env_refs(value: str, env: Mapping[str, str]) -> tuple[str, list[str]]:
    """Substitute ``$VAR`` / ``${VAR}`` references against ``env``.

    Returns ``(expanded_value, missing_refs)``. Missing references stay
    as their literal ``$VAR`` form in the expanded value so a caller
    that wants to skip the entry has the original spelling for the
    error message. Each missing name is reported only once even if it
    appears multiple times in the same value.

    Order of substitution matches the regex match order (left to
    right), and ``apply_launcher_env`` iterates in TOML insertion
    order — so an earlier ``[env]`` entry that lands in ``os.environ``
    becomes resolvable for a later entry that references it.
    """
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group("braced") or match.group("bare")
        if name and name in env:
            return env[name]
        if name and name not in missing:
            missing.append(name)
        return match.group(0)

    return _ENV_REF_PATTERN.sub(replace, value), missing


def apply_launcher_env(
    env_section: dict[str, Any] | None,
    *,
    env: MutableMapping[str, str] | None = None,
) -> list[str]:
    """Push ``[env]`` table entries into ``os.environ`` (no clobber).

    Real shell env vars always win — if a key is already set, we leave
    it alone. Values support shell-style ``$VAR`` / ``${VAR}``
    substitution against the current environment, so a TOML can map
    secrets injected by the orchestrator (Kubernetes secrets,
    ``docker run -e``, ``GITHUB_TOKEN`` from CI, etc.) into the
    ``OPENBB_*`` names the application expects::

        [env]
        OPENBB_GITHUB_TOKEN = "$GITHUB_TOKEN"
        OPENBB_API_HOST     = "${HOST}"

    Entries whose value references an unresolved variable are SKIPPED
    (a warning is logged) — silently setting a value of literal
    ``"$MISSING"`` would let the application boot with bogus credentials.

    Substitution order is TOML-insertion order, so an earlier ``[env]``
    entry can be referenced by a later one within the same table.

    Returns the list of keys actually applied (resolved + set) so
    callers can log/observe what came from TOML versus the shell.
    ``env`` arg is for tests; callers normally let it default to the
    real ``os.environ``.
    """
    if not env_section:
        return []
    target: MutableMapping[str, str] = env if env is not None else os.environ
    applied: list[str] = []
    for key, value in env_section.items():
        if not isinstance(key, str):
            continue
        if key in target:
            continue
        expanded, missing = _expand_env_refs(str(value), target)
        if missing:
            logger.warning(
                "Skipping [env] entry %s: references unresolved variable(s) %s",
                key,
                ", ".join(missing),
            )
            continue
        target[key] = expanded
        applied.append(key)
    return applied


def merge_launcher_kwargs(
    cli_kwargs: dict[str, Any],
    launcher_section: dict[str, Any] | None,
) -> dict[str, Any]:
    """Overlay ``[launcher]`` section under CLI kwargs (CLI wins).

    The launcher section is treated as a defaults dict — every key it
    provides is filled into ``cli_kwargs`` only when the CLI didn't
    already set it. Lists / dicts / scalars are all replaced wholesale
    (no deep merge); the CLI is the single source of truth for any
    explicit setting.
    """
    if not launcher_section:
        return cli_kwargs
    merged = dict(launcher_section)
    merged.update(cli_kwargs)
    return merged


#: Stashed result of the most recent ``bootstrap_launcher_config`` so
#: downstream consumers (``parse_args``, the middleware hook
#: registrar in ``app.py``) can read the same merged config without
#: re-walking the cascade — and, more importantly, without losing the
#: ``--config-file`` argv sniff that only ``bootstrap_launcher_config``
#: performs. Cleared by ``reset_bootstrapped_config`` for tests.
_BOOTSTRAPPED_CONFIG: dict[str, Any] | None = None


def bootstrap_launcher_config(
    argv: list[str] | None = None,
) -> dict[str, Any]:
    """One-call bootstrap for ``main.py``.

    Resolves the explicit config path from ``--config-file``/env vars,
    runs the layered cascade, and applies the ``[env]`` table. The
    merged result is also stashed in ``_BOOTSTRAPPED_CONFIG`` so
    later boot phases (``parse_args``, middleware registration) can
    reuse it via ``get_bootstrapped_config()`` without re-doing
    cascade discovery — that matters because the launcher's argv
    sniff for ``--config-file`` only happens here, and ``app.py``
    has no other way to find the same explicit path.

    Safe to call before any ``openbb-core`` import — the only modules
    touched are stdlib + the core's lightweight loader module.

    ``[env]`` is applied BEFORE ``apply_config_to_services`` runs.
    That order matters: ``apply_config_to_services`` is what first
    imports ``openbb_core.app.model.credentials``, whose ``Credentials``
    model takes a one-shot snapshot of ``os.environ`` at import time.
    Pushing ``[env]`` after that import would mean a credential
    supplied only via the TOML ``[env]`` table (not a real shell
    export) is invisible to that snapshot.
    """
    global _BOOTSTRAPPED_CONFIG  # noqa: PLW0603

    cli_path = extract_config_file_from_argv(argv)
    explicit_path = resolve_explicit_config_path(cli_path)
    config = load_launcher_config(explicit_path=explicit_path, apply_to_services=False)
    apply_launcher_env(config.get("env"))

    from openbb_core.app.config.loader import apply_config_to_services

    apply_config_to_services(config)

    _BOOTSTRAPPED_CONFIG = config
    return config


def get_bootstrapped_config() -> dict[str, Any]:
    """Return the config loaded by the most recent ``bootstrap_launcher_config``.

    Returns an empty dict when bootstrap hasn't run — keeps the
    consumer code path branch-free (it can ``.get("middleware", {})``
    without first checking for None).
    """
    return _BOOTSTRAPPED_CONFIG or {}


def reset_bootstrapped_config() -> None:
    """Clear the stashed bootstrap config. For tests only — production
    code shouldn't need to reset launcher state.
    """
    global _BOOTSTRAPPED_CONFIG  # noqa: PLW0603

    _BOOTSTRAPPED_CONFIG = None
