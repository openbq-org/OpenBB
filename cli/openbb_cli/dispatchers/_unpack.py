"""Runtime helpers shared by the HTTP dispatcher and generated code.

Response unwrapping, plus the query-string encoding generated fetchers use.
"""

from __future__ import annotations

import json as _json
import re as _re
from typing import Any

_BARE_ASTERISK = _re.compile(r":\s*\*\s*(?=[,}\]])")
_QUERY_SAFE = ",:/@!$'()*;?"


def encode_query(items: dict[str, Any]) -> str:
    """Build a URL query string from ``items``.

    ``None`` values are dropped, list values repeat the key, and booleans are
    sent as ``true`` / ``false``. Characters that
    change how a query string parses (``&``, ``=``, ``+``, ``#``, ``%``,
    spaces, quotes, brackets) are percent-encoded; commas, colons and slashes
    stay literal, so delimited lists and times are sent as written.
    """
    from urllib.parse import quote, urlencode

    return urlencode(
        {
            key: (
                [wire_value(item) for item in value]
                if isinstance(value, (list, tuple))
                else wire_value(value)
            )
            for key, value in items.items()
            if value is not None
        },
        doseq=True,
        safe=_QUERY_SAFE,
        quote_via=quote,
    )


def wire_value(value: Any) -> Any:
    """Return ``value`` as it goes on the wire: booleans as ``true`` / ``false``."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


_PLACEHOLDER = _re.compile(r"\{([^}]+)\}")


def choose_url_template(
    templates: Any,
    values: dict[str, Any],
    labels: dict[str, str] | None = None,
    defaults: dict[str, Any] | None = None,
) -> tuple[str, list[str], list[str]]:
    """Pick the URL template that fits the path values passed, and fill it in.

    ``templates`` lists ``(template, path_names, query_names)`` from most to
    fewest placeholders: ``path_names`` are the template's placeholders and
    ``query_names`` the query parameters that URL declares. A value counts as
    passed when it is not ``None`` or ``""`` and differs from its entry in
    ``defaults``. A template fits when every placeholder has a value (passed or
    default), every other passed path value is one of its query parameters,
    and at least one of its placeholders that not every template shares was
    passed (or it has none of those): a default can complete a URL the caller
    picked, but never picks or blocks one by itself. ``labels`` renames values
    in the error message.

    Returns the filled-in path, the names its placeholders used, and its query
    parameters. Raises ``ValueError`` listing the accepted combinations when
    no template fits.
    """
    defaults = defaults or {}
    available = {name for name, value in values.items() if value not in (None, "")}
    passed = {
        name
        for name in available
        if not (name in defaults and values[name] == defaults[name])
    }
    shared = (
        set.intersection(*(set(names) for _, names, _ in templates))
        if templates
        else set()
    )
    for template, path_names, query_names in templates:
        path = set(path_names)
        distinct = path - shared
        if (
            path <= available
            and passed - path <= set(query_names)
            and (not distinct or distinct & passed)
        ):
            filled = _PLACEHOLDER.sub(
                lambda m: str(wire_value(values[m.group(1)])), template
            )
            return filled, list(path_names), list(query_names)
    label = (labels or {}).get
    options = " | ".join(
        dict.fromkeys(
            " + ".join(label(name, name) for name in path_names) or "none"
            for _, path_names, _ in templates
        )
    )
    given = ", ".join(sorted(label(name, name) for name in passed)) or "none"
    raise ValueError(
        f"Path parameters ({given}) do not form a URL. Pass one of: {options}"
    )


def json_array(value: str, item_type: str = "string") -> str | None:
    """Encode a comma-separated value, or a JSON array string, as a compact JSON array.

    Comma-separated items are converted to ``item_type`` (``"integer"``,
    ``"number"`` or ``"boolean"``; anything else stays a string). A JSON array
    string is sent as written. Empty input returns ``None`` so it is not sent.
    """
    text = value.strip()
    if not text:
        return None
    if text.startswith("["):
        try:
            items = _json.loads(text)
        except ValueError:
            items = None
        if isinstance(items, list):
            return _json.dumps(items, separators=(",", ":"))
    convert = {
        "integer": int,
        "number": float,
        "boolean": lambda item: item.lower() == "true",
    }.get(item_type, str)
    return _json.dumps(
        [convert(item.strip()) for item in text.split(",") if item.strip()],
        separators=(",", ":"),
    )


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
    if kind in ("tuples", "records"):
        row_type = list if kind == "tuples" else dict
        if not isinstance(payload, list) or not all(
            isinstance(v, row_type) for v in payload
        ):
            return None
        return ([{"value": v} for v in payload] if kind == "tuples" else payload), {}
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

    ``kind`` (``"list"``, ``"map"``, ``"single"``, ``"tuples"`` or ``"records"``) and ``rows_key`` come from
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
