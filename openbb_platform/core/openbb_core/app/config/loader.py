"""Layered configuration loader for openbb-core.

Resolution order (highest priority last; later layers overwrite earlier ones):

1. Built-in defaults (model field defaults on ``SystemSettings`` /
   ``UserSettings``).
2. The on-disk JSONs the existing services have always loaded —
   ``~/.openbb_platform/system_settings.json`` and
   ``user_settings.json``. Treated as defaults so a user who has only
   ever touched the JSONs sees zero behavior change.
3. ``[tool.openbb]`` in the nearest ancestor ``pyproject.toml``,
   walking up from CWD. Lets a library/service ship a known-good
   baseline (default credentials shape, preferred output format) with
   its distribution.
4. ``~/.openbb_platform/openbb.toml`` (or ``.openbb.toml``) — the
   user-global config in the same directory the JSON files live in,
   intended as the friendlier sibling of those raw JSON dumps.
5. ``openbb.toml`` (or ``.openbb.toml``) in the nearest ancestor
   directory of CWD — project-local override that doesn't pollute
   ``pyproject.toml``.
6. ``$OPENBB_CONFIG`` env var (or an explicit ``path=`` to
   ``load_config``) — swappable, scoped configurations
   (``staging.toml``, ``prod.toml``, ...).
7. ``.env`` files (``~/.openbb_platform/.env`` plus
   ``$OPENBB_ENV_FILE``) — applied to ``os.environ`` so the env-var
   layer below picks them up without coupling.
8. ``OPENBB_*`` real-shell env vars — already honored by the
   ``Env`` singleton and various model fields. Real shell exports
   always beat dotfiles + TOML.

This module covers (3)-(7); the existing services + ``Env`` cover (1),
(2), and (8). The merged result of (3)-(6) is the "layered config" —
``apply_config_to_services`` pushes it onto the singleton services so
downstream code reads the layered values via the existing
``SystemService().system_settings`` / ``UserService().default_user_settings``
APIs.

Schema (every key + section optional)::

    # Top-level promotions — convenience shortcuts for the most-tweaked
    # System fields. Setting these here is identical to the matching
    # entry under ``[system]``; both forms are accepted, the top-level
    # form wins on conflicts.
    debug-mode = true
    test-mode = false
    headless = false

    [system]
    debug_mode = true
    headless = false

    [system.api_settings]
    prefix = "/api/v1"

    [system.api_settings.cors]
    allow_origins = ["*"]

    [user]

    [user.credentials]
    fmp_api_key = "..."
    polygon_api_key = "..."

    [user.preferences]
    data_directory = "/data/openbb"
    output_type = "dataframe"

    [user.defaults]

    [user.defaults.commands."/equity/price/historical"]
    provider = "fmp"

The ``[system]``, ``[user]``, and their nested tables are deep-merged
across layers. Top-level promotions cascade onto the corresponding
``[system]`` keys (top-level wins). See the ``render_config_template``
output for a fully documented version.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from openbb_core.app.constants import OPENBB_DIRECTORY

DEFAULT_CONFIG_NAMES: tuple[str, ...] = ("openbb.toml", ".openbb.toml")
PYPROJECT_NAME = "pyproject.toml"
PYPROJECT_TABLE: tuple[str, ...] = ("tool", "openbb")
EXPLICIT_CONFIG_ENV = "OPENBB_CONFIG"
EXPLICIT_ENV_FILE_ENV = "OPENBB_ENV_FILE"

USER_OPENBB_DIR = OPENBB_DIRECTORY
USER_OPENBB_TOML_NAMES: tuple[str, ...] = ("openbb.toml", ".openbb.toml")
USER_OPENBB_ENV_NAME = ".env"

# Top-level convenience keys that promote onto the matching ``[system]``
# field. Same idea as the cli's ``_TOP_LEVEL_SETTINGS_PROMOTIONS`` —
# the most-tweaked subset of the System surface gets first-class
# top-level placement so users don't have to dig into ``[system]``.
_TOP_LEVEL_SYSTEM_PROMOTIONS: tuple[str, ...] = (
    "debug_mode",
    "test_mode",
    "headless",
    "logging_suppress",
    "allow_mutable_extensions",
    "allow_on_command_output",
)


def _walk_up(start: Path | None = None):
    """Yield ``start`` and every parent up to the filesystem root."""
    cur = (start or Path.cwd()).resolve()
    yield cur
    yield from cur.parents


def _read_toml(path: Path) -> dict[str, Any]:
    """Safe-load a TOML file. Missing / unreadable files yield ``{}``."""
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _find_first(start: Path | None, names: tuple[str, ...]) -> Path | None:
    """Walk up from ``start`` looking for any filename in ``names``."""
    for parent in _walk_up(start):
        for name in names:
            candidate = parent / name
            if candidate.is_file():
                return candidate
    return None


def _find_pyproject_section(start: Path | None = None) -> dict[str, Any]:
    """Find the nearest ancestor ``pyproject.toml`` with ``[tool.openbb]``.

    Walks up from ``start`` (or CWD) and returns the section dict, or
    ``{}`` when no matching pyproject is found.
    """
    py = _find_first(start, (PYPROJECT_NAME,))
    if py is None:
        return {}
    data = _read_toml(py)
    node: Any = data
    for key in PYPROJECT_TABLE:
        if not isinstance(node, dict) or key not in node:
            return {}
        node = node[key]
    return node if isinstance(node, dict) else {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    """In-place deep merge: nested dicts merge, scalars / lists overwrite."""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _normalize_keys(d: dict[str, Any]) -> dict[str, Any]:
    """Normalize top-level kebab-case keys to snake_case.

    The ``[system]`` / ``[user]`` nested tables keep their original
    keys — those names go straight into Settings model field lookups
    so they must round-trip exactly. Only the top-level convenience
    keys (``debug-mode``, ``test-mode``, ...) get the snake-case
    treatment so users can write either form.
    """
    return {k.replace("-", "_"): v for k, v in d.items()}


def _user_global_toml() -> Path | None:
    """Locate ``~/.openbb_platform/openbb.toml`` (or the dotted variant)."""
    if not USER_OPENBB_DIR.is_dir():
        return None
    for name in USER_OPENBB_TOML_NAMES:
        candidate = USER_OPENBB_DIR / name
        if candidate.is_file():
            return candidate
    return None


def load_config(
    explicit_path: str | os.PathLike[str] | None = None,
    *,
    start: Path | None = None,
) -> dict[str, Any]:
    """Resolve the layered openbb-core configuration.

    Layers, lowest to highest priority:

    * ``[tool.openbb]`` from the nearest ancestor ``pyproject.toml``
    * ``~/.openbb_platform/openbb.toml`` (or ``.openbb.toml``)
    * ``openbb.toml`` (or ``.openbb.toml``) walking up from ``start``
      (defaults to CWD)
    * ``explicit_path`` if provided, otherwise ``$OPENBB_CONFIG``

    Returns a single merged dict with normalized top-level keys
    (kebab-case → snake_case). Nested ``[system]`` / ``[user]`` tables
    keep their original casing so they map directly to model fields.
    Returns ``{}`` when no layer is found — callers should fall back
    to disk JSONs / model defaults.
    """
    layers: list[dict[str, Any]] = [_find_pyproject_section(start)]
    user_toml = _user_global_toml()
    if user_toml is not None:
        layers.append(_read_toml(user_toml))
    project_toml = _find_first(start, DEFAULT_CONFIG_NAMES)
    if project_toml is not None:
        layers.append(_read_toml(project_toml))
    explicit = explicit_path or os.environ.get(EXPLICIT_CONFIG_ENV)
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file():
            layers.append(_read_toml(path))
    merged: dict[str, Any] = {}
    for layer in layers:
        _deep_merge(merged, _normalize_keys(layer))
    return merged


def _promote_top_level_keys(config: dict[str, Any]) -> dict[str, Any]:
    """Fold top-level convenience keys into ``[system]``.

    Returns a new dict — caller's input untouched. Top-level wins on
    conflict because users who set both clearly meant the explicit
    short form.
    """
    if not config:
        return {}
    out = {k: v for k, v in config.items() if k != "system" or isinstance(v, dict)}
    system_section: dict[str, Any] = dict(out.get("system") or {})
    for key in _TOP_LEVEL_SYSTEM_PROMOTIONS:
        if key in out:
            system_section[key] = out.pop(key)
    if system_section:
        out["system"] = system_section
    return out


def apply_config_to_services(config: dict[str, Any] | None) -> dict[str, list[str]]:
    """Push the layered config onto ``SystemService`` and ``UserService``.

    Both services are singletons that already loaded their on-disk JSON
    (the canonical "user has manually edited this" surface). This
    function takes the layered TOML config — typically the output of
    ``load_config()`` — and merges its ``[system]`` / ``[user]``
    sections into the live service settings, then re-validates so any
    nested-model coercion (CORS lists, Defaults sub-tables, etc.)
    runs against the merged dict rather than the raw TOML.

    Real shell exports through the ``Env`` singleton stay
    authoritative — TOML provides defaults, env vars override them via
    the model-field validator paths.

    Returns ``{"system": [field1, ...], "user": [field1, ...]}``: the
    fields each service updated, for logging / debugging.
    """
    from pydantic import BaseModel

    from openbb_core.app.model.credentials import Credentials
    from openbb_core.app.model.defaults import Defaults
    from openbb_core.app.model.preferences import Preferences
    from openbb_core.app.model.system_settings import SystemSettings
    from openbb_core.app.service.system_service import SystemService
    from openbb_core.app.service.user_service import UserService

    if not config:
        return {"system": [], "user": []}
    promoted = _promote_top_level_keys(config)
    applied: dict[str, list[str]] = {"system": [], "user": []}

    system_overrides = promoted.get("system") or {}
    if isinstance(system_overrides, dict) and system_overrides:
        service = SystemService()
        current = service.system_settings.model_dump()
        merged = _deep_merge_copy(current, system_overrides)
        # ``SystemSettings`` is frozen — replace, don't mutate.
        service.system_settings = SystemSettings.model_validate(merged)
        applied["system"] = sorted(system_overrides.keys())

    user_overrides = promoted.get("user") or {}
    if isinstance(user_overrides, dict) and user_overrides:
        # ``UserSettings.__init__`` re-loads from disk on construction —
        # going through ``model_validate`` would clobber the merged
        # values with whatever's already on disk. Patch the live
        # singleton's sub-models instead so the layered config wins
        # without the __init__ override fighting us.
        u_service = UserService()
        live = u_service.default_user_settings
        sub_model_map: dict[str, type[BaseModel]] = {
            "credentials": Credentials,
            "preferences": Preferences,
            "defaults": Defaults,
        }
        for section, model_cls in sub_model_map.items():
            section_overrides = user_overrides.get(section)
            if not isinstance(section_overrides, dict):
                continue
            current_section = getattr(live, section).model_dump()
            merged_section = _deep_merge_copy(current_section, section_overrides)
            setattr(live, section, model_cls.model_validate(merged_section))
        applied["user"] = sorted(user_overrides.keys())

    return applied


def _deep_merge_copy(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Non-mutating ``_deep_merge`` — returns a fresh dict."""
    out: dict[str, Any] = {}
    _deep_merge(out, base)
    _deep_merge(out, override)
    return out


def load_env_files(
    explicit_path: str | os.PathLike[str] | None = None,
) -> list[Path]:
    """Apply ``.env`` files into ``os.environ`` for subsequent env lookups.

    Layers, applied in order so later files override earlier ones, and
    pre-existing ``os.environ`` values still win (real shell exports
    always beat dotfiles):

    * ``~/.openbb_platform/.env`` — the canonical openbb-platform
      dotenv that ``Env`` already loads at import time. Re-loading
      here is a no-op when ``Env`` already ran but covers the case
      where this loader runs first.
    * ``explicit_path`` if provided, otherwise
      ``$OPENBB_ENV_FILE``.

    Returns the list of files actually applied, for logging.
    """
    # pylint: disable=import-outside-toplevel
    from dotenv import dotenv_values

    candidates: list[Path] = []
    user_env = USER_OPENBB_DIR / USER_OPENBB_ENV_NAME
    if user_env.is_file():
        candidates.append(user_env)
    explicit = explicit_path or os.environ.get(EXPLICIT_ENV_FILE_ENV)
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file():
            candidates.append(path)

    loaded: list[Path] = []
    for path in candidates:
        for k, v in dotenv_values(path).items():
            if v is None:
                continue
            os.environ.setdefault(k, v)
        loaded.append(path)
    return loaded


def apply_settings_to_env(config: dict[str, Any] | None) -> list[str]:
    """Inject promoted top-level system flags into ``os.environ``.

    The few system-level flags ``Env`` reads (``OPENBB_DEBUG_MODE``,
    ``OPENBB_ALLOW_MUTABLE_EXTENSIONS``, etc.) get seeded from the
    layered config so code that consults ``Env`` rather than
    ``SystemService`` (some pre-existing call sites) sees the same
    values as ``SystemSettings``. Uses ``setdefault`` so real shell
    exports stay authoritative.

    Returns the list of env var names set, for logging.
    """
    if not config:
        return []
    promoted = _promote_top_level_keys(config)
    applied: list[str] = []
    system_section = promoted.get("system") or {}
    if not isinstance(system_section, dict):  # pragma: no cover — defensive
        # ``_promote_top_level_keys`` already filters out non-dict
        # ``system`` values, so this guard is unreachable via the
        # normal load path. Kept in case a future refactor opens the
        # door to a non-dict landing here.
        return []
    for key, value in system_section.items():
        if key not in _TOP_LEVEL_SYSTEM_PROMOTIONS:
            continue
        env_key = f"OPENBB_{key.upper()}"
        if env_key in os.environ:
            continue
        if isinstance(value, bool):
            os.environ[env_key] = "True" if value else "False"
        else:
            os.environ[env_key] = str(value)
        applied.append(env_key)
    return applied


def load_layered_config(
    explicit_path: str | os.PathLike[str] | None = None,
    *,
    explicit_env_file: str | os.PathLike[str] | None = None,
    apply_to_services: bool = True,
    apply_to_env: bool = True,
) -> dict[str, Any]:
    """End-to-end discovery: TOML cascade + ``.env`` + optional service push.

    Convenience wrapper that bundles the steps a typical bootstrap
    sequence runs:

    1. ``load_env_files`` — drop dotfile values into ``os.environ``
       (real exports still win via ``setdefault``).
    2. ``load_config`` — walk the TOML cascade and produce the merged
       dict.
    3. ``apply_settings_to_env`` (when ``apply_to_env=True``) — seed
       ``OPENBB_*`` env vars for the promoted top-level flags so any
       code path reading via ``Env`` sees the same values.
    4. ``apply_config_to_services`` (when ``apply_to_services=True``)
       — push ``[system]`` / ``[user]`` sections onto the singleton
       services so existing call sites surface the layered values.

    Returns the merged config dict so callers can inspect / re-apply
    if needed.
    """
    load_env_files(explicit_env_file)
    config = load_config(explicit_path)
    if apply_to_env:
        apply_settings_to_env(config)
    if apply_to_services:
        apply_config_to_services(config)
    return config


def _toml_quote(value: Any) -> str:
    """Render a Python value as a TOML literal (string / bool / number)."""
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_quote(v) for v in value) + "]"
    return '"' + str(value) + '"'


def render_config_template(active: dict[str, Any] | None = None) -> str:
    """Render a documented TOML template covering every supported setting.

    Each section walks the live ``SystemSettings`` / ``UserSettings``
    model fields and emits a comment block + commented-out line per
    field. Fields with values resolved from any layer surface
    uncommented so users can tweak in place. The top-level promotions
    block is rendered first as the "most likely tweak" surface.
    """
    # pylint: disable=import-outside-toplevel
    from openbb_core.app.model.system_settings import SystemSettings
    from openbb_core.app.model.user_settings import UserSettings

    a = active or {}
    parts: list[str] = [
        "# openbb-core configuration template.\n"
        "#\n"
        "# Drop this file at any of the following discovery locations:\n"
        "#   * ~/.openbb_platform/openbb.toml          (user-global)\n"
        "#   * ./openbb.toml or ./.openbb.toml         (project-local; walks up from CWD)\n"
        "#   * [tool.openbb] in pyproject.toml         (ships with a dev project)\n"
        "#   * --config PATH or $OPENBB_CONFIG         (explicit, swappable)\n"
        "#\n"
        "# Resolution order (lowest → highest priority):\n"
        "#   defaults -> system_settings.json / user_settings.json -> pyproject\n"
        "#   -> ~/.openbb_platform/openbb.toml -> ./openbb.toml -> $OPENBB_CONFIG\n"
        "#   -> .env files -> OPENBB_* env vars\n"
        "#\n"
        "# Lines starting with # are commented out. Either uncomment to set a value\n"
        "# (and the matching env var override still wins), or leave commented to\n"
        "# fall through to the next layer.\n\n",
        "# ── Top-level promotions ────────────────────────────────────────────────\n"
        "# Convenience shortcuts for the most-tweaked System fields. Setting these\n"
        "# at the top level overrides the matching key under [system].\n\n",
    ]
    for promoted in _TOP_LEVEL_SYSTEM_PROMOTIONS:
        kebab = promoted.replace("_", "-")
        active_value = a.get(promoted) or (a.get("system") or {}).get(promoted)
        commented = "# " if active_value is None else ""
        rendered = _toml_quote(active_value) if active_value is not None else "false"
        parts.append(
            f"# OPENBB_{promoted.upper()} (env equivalent)\n"
            f"{commented}{kebab} = {rendered}\n\n"
        )
    parts.append(
        "# ── [system] ────────────────────────────────────────────────────────────\n"
        "# Maps directly onto the SystemSettings model. Every field surfaces here;\n"
        "# nested tables (api_settings, python_settings) get their own sub-sections.\n"
        "[system]\n\n"
    )
    parts.append(_render_settings_section("system", SystemSettings, a.get("system")))
    parts.append(
        "# ── [user] ──────────────────────────────────────────────────────────────\n"
        "# Maps onto the UserSettings model — credentials, preferences, defaults.\n"
        "[user]\n\n"
    )
    parts.append(_render_settings_section("user", UserSettings, a.get("user")))
    return "".join(parts)


def _render_settings_section(
    name: str,
    model: Any,
    active: dict[str, Any] | None,
) -> str:
    """Render a section's commented-out fields from the model definition."""
    # pylint: disable=import-outside-toplevel
    out: list[str] = []
    active_dict = active if isinstance(active, dict) else {}
    for field_name, field in sorted(model.model_fields.items()):
        if field_name.startswith("_"):  # pragma: no cover — defensive
            # Pydantic doesn't expose ``_``-prefixed names in
            # ``model_fields``; the guard exists in case a future
            # subclass reaches this with private attrs surfaced.
            continue
        active_value = active_dict.get(field_name)
        if isinstance(active_value, dict):
            # Nested table — emit as ``[name.field_name]``. The actual
            # nested fields render as a sub-call.
            out.append(f"[{name}.{field_name}]\n\n")
            continue
        if isinstance(active_value, list):
            commented = ""
            rendered = _toml_quote(active_value)
        elif active_value is None:
            commented = "# "
            default = field.default if field.default is not None else ""
            rendered = _toml_quote(default)
        else:
            commented = ""
            rendered = _toml_quote(active_value)
        description = (field.description or field_name).split("\n")[0]
        out.append(f"# {description}\n{commented}{field_name} = {rendered}\n\n")
    return "".join(out)
