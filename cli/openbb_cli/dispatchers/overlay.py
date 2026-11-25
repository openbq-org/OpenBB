"""Apply OpenAPI Overlay documents to an OpenAPI description before spec build.

Implements the action model of the OpenAPI Overlay Specification 1.0
(https://spec.openapis.org/overlay/v1.0.0): each action selects nodes with a
JSONPath ``target`` and either merges an ``update`` into them or removes them.

Only the JSONPath subset that names nodes directly is supported: ``$``,
``.name``, ``['name']`` / ``["name"]``, ``[index]``, and the ``*`` / ``[*]``
wildcards. Filters, slices, unions, and recursive descent (``..``) are rejected.
"""

from __future__ import annotations

import copy
import datetime
import json
import re
from pathlib import Path
from typing import Any

_INDEX_RE = re.compile(r"\[(-?[0-9]+)\]")
_INTEGER_RE = re.compile(r"-?[0-9]+")

Step = str | int | None


def parse_target(target: str) -> list[Step]:
    """Split a JSONPath expression into lookup steps.

    Parameters
    ----------
    target : str
        JSONPath expression starting with ``$``.

    Returns
    -------
    list[str | int | None]
        One step per segment: a key, a list index, or ``None`` for a wildcard.

    Raises
    ------
    ValueError
        When the expression is malformed or uses unsupported syntax.
    """
    if not target.startswith("$"):
        raise ValueError(f"JSONPath target must start with '$': {target!r}")
    steps: list[Step] = []
    i, n = 1, len(target)
    while i < n:
        if target.startswith("..", i):
            raise ValueError(f"recursive descent '..' is not supported: {target!r}")
        if target[i] == ".":
            j = i + 1
            while j < n and target[j] not in ".[":
                j += 1
            name = target[i + 1 : j]
            if not name:
                raise ValueError(f"empty segment in JSONPath target: {target!r}")
            steps.append(None if name == "*" else name)
            i = j
        elif target.startswith("[*]", i):
            steps.append(None)
            i += 3
        elif target[i : i + 2] in ("['", '["'):
            quote = target[i + 1]
            j = i + 2
            chars: list[str] = []
            while j < n and target[j] != quote:
                if target[j] == "\\" and j + 1 < n:
                    j += 1
                chars.append(target[j])
                j += 1
            if not target.startswith(quote + "]", j):
                raise ValueError(f"unterminated quoted segment: {target!r}")
            steps.append("".join(chars))
            i = j + 2
        elif match := _INDEX_RE.match(target, i):
            steps.append(int(match.group(1)))
            i = match.end()
        else:
            raise ValueError(
                f"unsupported JSONPath syntax at position {i}: {target!r} "
                "(only $, .name, ['name'], [index], and * are supported)"
            )
    return steps


def _dict_key(node: dict[Any, Any], step: str | int) -> Any:
    """Find the key ``step`` names in ``node``, matching ``"200"`` and ``200`` alike."""
    candidates: list[Any] = [step, str(step)]
    if isinstance(step, str) and _INTEGER_RE.fullmatch(step):
        candidates.append(int(step))
    for key in candidates:
        if key in node:
            return key
    return None


def select(doc: Any, steps: list[Step]) -> list[tuple[Any, Any, Any]]:
    """Return ``(parent, key, node)`` for every node the steps select.

    Parameters
    ----------
    doc : Any
        The document to search.
    steps : list[str | int | None]
        Output of ``parse_target``.

    Returns
    -------
    list[tuple[Any, Any, Any]]
        Matches in document order; ``parent`` and ``key`` are ``None`` for the root.
    """
    current: list[tuple[Any, Any, Any]] = [(None, None, doc)]
    for step in steps:
        selected: list[tuple[Any, Any, Any]] = []
        for _, _, node in current:
            if step is None:
                if isinstance(node, dict):
                    selected.extend((node, k, v) for k, v in node.items())
                elif isinstance(node, list):
                    selected.extend((node, k, v) for k, v in enumerate(node))
            elif isinstance(node, dict):
                key = _dict_key(node, step)
                if key is not None:
                    selected.append((node, key, node[key]))
            elif (
                isinstance(node, list)
                and isinstance(step, int)
                and -len(node) <= step < len(node)
            ):
                selected.append((node, step % len(node), node[step]))
        current = selected
    return current


def _merge(target: dict[Any, Any], update: dict[Any, Any]) -> None:
    """Recursively merge ``update`` into ``target``; non-object values replace.

    An update key matches the target key it names, so ``200`` merges into an
    existing ``"200"`` (see ``_dict_key``).
    """
    for key, value in update.items():
        found = _dict_key(target, key) if isinstance(key, (str, int)) else None
        slot = key if found is None else found
        if isinstance(value, dict) and isinstance(target.get(slot), dict):
            _merge(target[slot], value)
        else:
            target[slot] = copy.deepcopy(value)


def _json_key(key: Any) -> str:
    """Return a YAML mapping key as the string JSON would use."""
    if isinstance(key, bool) or key is None:
        return json.dumps(key)
    if isinstance(key, datetime.date):
        return key.isoformat()
    return str(key)


def _json_compatible(node: Any) -> Any:
    """Give YAML-only values their JSON form: string keys, ISO date text."""
    if isinstance(node, dict):
        return {_json_key(k): _json_compatible(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_json_compatible(v) for v in node]
    if isinstance(node, datetime.date):
        return node.isoformat()
    return node


def load_overlay(path: str | Path) -> dict[str, Any]:
    """Read and validate an Overlay document from a YAML or JSON file.

    Mapping keys are read as strings and unquoted YAML dates as ISO text, as
    JSON would give them.

    Parameters
    ----------
    path : str or Path
        Location of the overlay file.

    Returns
    -------
    dict[str, Any]
        The parsed overlay document.

    Raises
    ------
    ValueError
        When the file is not valid YAML or JSON, or not an Overlay document.
    """
    import yaml

    text = Path(path).read_text(encoding="utf-8-sig")
    try:
        doc = json.loads(text)
    except ValueError:
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"not valid YAML or JSON: {exc}") from exc
    doc = _json_compatible(doc)
    if not isinstance(doc, dict) or "overlay" not in doc:
        raise ValueError("not an OpenAPI Overlay document (missing 'overlay' field)")
    if not isinstance(doc.get("actions"), list):
        raise ValueError("overlay 'actions' must be a list")
    return doc


def apply_overlay(
    openapi: dict[str, Any], overlay: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Apply every action of ``overlay`` to a copy of ``openapi``, in order.

    An ``update`` is merged into each selected object (nested objects merge,
    other values replace) or appended to each selected array. ``remove: true``
    deletes each selected node from its parent. The document is read as JSON
    would give it (string keys, ISO date text), so YAML response codes and an
    overlay's keys agree.

    Parameters
    ----------
    openapi : dict
        The OpenAPI document; it is not modified.
    overlay : dict
        A validated Overlay document (see ``load_overlay``).

    Returns
    -------
    tuple[dict, list[str]]
        The updated document and the targets that selected nothing.

    Raises
    ------
    ValueError
        When an action is malformed or cannot apply to what it selects.
    """
    doc = _json_compatible(openapi)
    unmatched: list[str] = []
    for index, action in enumerate(overlay.get("actions") or []):
        target = action.get("target") if isinstance(action, dict) else None
        if not isinstance(target, str):
            raise ValueError(f"actions[{index}] needs a string 'target'")
        matches = select(doc, parse_target(target))
        if not matches:
            unmatched.append(target)
            continue
        if action.get("remove") is True:
            for parent, key, _ in reversed(matches):
                if parent is None:
                    raise ValueError(f"actions[{index}] cannot remove the root")
                del parent[key]
            continue
        if "update" not in action:
            continue
        update = _json_compatible(action["update"])
        for _, _, node in matches:
            if isinstance(node, list):
                node.append(copy.deepcopy(update))
            elif isinstance(node, dict) and isinstance(update, dict):
                _merge(node, update)
            else:
                raise ValueError(
                    f"actions[{index}] update must target objects or arrays, "
                    f"and an object target needs an object update: {target!r}"
                )
    return doc, unmatched
