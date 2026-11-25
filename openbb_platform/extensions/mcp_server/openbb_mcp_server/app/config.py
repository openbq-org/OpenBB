"""Launcher TOML config bootstrap for ``openbb-mcp``."""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

logger = logging.getLogger("openbb_mcp_server.config")

_ENV_REF_PATTERN = re.compile(
    r"\$\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}"
    r"|\$(?P<bare>[A-Za-z_][A-Za-z0-9_]*)"
)

EXPLICIT_CONFIG_ENVS: tuple[str, ...] = (
    "OPENBB_MCP_CONFIG",
    "OPENBB_API_CONFIG",
    "OPENBB_CONFIG",
)

CONFIG_FILE_FLAG = "--config-file"


def extract_config_file_from_argv(argv: list[str] | None = None) -> str | None:
    """Sniff ``--config-file <path>`` out of argv WITHOUT importing args."""
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
    """Pick the explicit-path slot for the cascade."""
    if cli_path:
        return cli_path
    env_map: Mapping[str, str] = env if env is not None else os.environ
    for key in EXPLICIT_CONFIG_ENVS:
        value = env_map.get(key)
        if value:
            return value
    return None


def _validate_explicit_toml(explicit_path: str) -> None:
    """Pre-parse the user-supplied config so malformed TOML fails loudly."""
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
    """Run the layered TOML cascade and return the merged config."""
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
    """Public entry point for ``$VAR`` / ``${VAR}`` substitution."""
    return _expand_env_refs(value, env if env is not None else os.environ)


def _expand_env_refs(value: str, env: Mapping[str, str]) -> tuple[str, list[str]]:
    """Substitute ``$VAR`` / ``${VAR}`` references against ``env``."""
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
    """Push ``[env]`` table entries into ``os.environ`` (no clobber)."""
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
    """Overlay ``[mcp]`` section under CLI kwargs (CLI wins)."""
    if not launcher_section:
        return cli_kwargs
    merged = dict(launcher_section)
    merged.update(cli_kwargs)
    return merged


_BOOTSTRAPPED_CONFIG: dict[str, Any] | None = None


def bootstrap_launcher_config(
    argv: list[str] | None = None,
) -> dict[str, Any]:
    """One-call bootstrap for ``main.py``.

    ``[env]`` is applied BEFORE ``apply_config_to_services`` runs. That
    order matters: ``apply_config_to_services`` is what first imports
    ``openbb_core.app.model.credentials``, whose ``Credentials`` model
    takes a one-shot snapshot of ``os.environ`` at import time. Pushing
    ``[env]`` after that import would mean a credential supplied only
    via the TOML ``[env]`` table (not a real shell export) is invisible
    to that snapshot.
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
    """Return the config loaded by the most recent ``bootstrap_launcher_config``."""
    return _BOOTSTRAPPED_CONFIG or {}


def reset_bootstrapped_config() -> None:
    """Clear the stashed bootstrap config."""
    global _BOOTSTRAPPED_CONFIG  # noqa: PLW0603

    _BOOTSTRAPPED_CONFIG = None
