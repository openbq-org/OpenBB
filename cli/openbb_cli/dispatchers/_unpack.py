"""Shared response unwrapping used by both the HTTP dispatcher and codegen."""

from __future__ import annotations

import json as _json
import re as _re
from typing import Any

_BARE_ASTERISK = _re.compile(r":\s*\*\s*(?=[,}\]])")


def safe_json_loads(text: str) -> Any:
    """Parse JSON text, sanitizing common upstream quirks first."""
    try:
        return _json.loads(text)
    except ValueError:
        sanitized = _BARE_ASTERISK.sub(": null", text)
        return _json.loads(sanitized)


def _drop_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove JSON-LD ``@context`` (syntax, never data) from a mapping."""
    if "@context" in payload and len(payload) > 1:
        return {k: v for k, v in payload.items() if k != "@context"}
    return payload


def _unpack_by_hint(
    payload: Any, rows_key: str | None, kind: str
) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    """Unpack as the response schema says; ``None`` if the payload doesn't fit."""
    if not isinstance(payload, dict):
        return None
    if kind == "single":
        return [payload], {}
    value = payload.get(rows_key) if rows_key else None
    metadata = {k: v for k, v in payload.items() if k != rows_key}
    if kind == "list" and isinstance(value, list):
        if all(isinstance(v, dict) for v in value):
            return value, metadata
        return [{"value": v} for v in value], metadata
    if kind == "map" and isinstance(value, dict):
        rows = [
            {"key": k, **v} if isinstance(v, dict) else {"key": k, "value": v}
            for k, v in value.items()
        ]
        return rows, metadata
    return None


def unpack_response(
    payload: Any,
    rows_key: str | None = None,
    kind: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Split a raw API payload into (rows, metadata).

    ``kind`` (``"list"``, ``"map"`` or ``"single"``) and ``rows_key`` come from
    the response schema when the caller knows it; otherwise the payload shape
    is guessed.
    """
    if kind:
        hinted = _unpack_by_hint(payload, rows_key, kind)
        if hinted is not None:
            return hinted
    if isinstance(payload, list):
        if len(payload) == 1:
            return unpack_response(payload[0])
        rows = [r for r in payload if isinstance(r, dict)]
        if rows:
            return rows, {}
        return [{"value": r} for r in payload], {}
    if not isinstance(payload, dict):
        return [{"value": payload}], {}
    payload = _drop_context(payload)
    list_keys = [k for k, v in payload.items() if isinstance(v, list)]
    if len(list_keys) == 1:
        key = list_keys[0]
        items = payload[key]
        metadata = {k: v for k, v in payload.items() if k != key}
        # Only return this as an envelope if all items are dicts or the list is
        # the only thing in the payload.
        if all(isinstance(v, dict) for v in items):
            return items, metadata
        if len(payload) == 1:
            return [{"value": r} for r in items], metadata
    if len(payload) == 1:
        only_value = next(iter(payload.values()))
        if isinstance(only_value, (list, dict)):
            return unpack_response(only_value)
    return [payload], {}
