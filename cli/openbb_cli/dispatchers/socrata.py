"""Generate a ``.spec`` file from a Socrata story JSON."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

_DISCOVERY_MAX_WORKERS = 20

from openbb_cli.dispatchers.spec import SPEC_VERSION, _generator_identifier

_CACHED_TOP_CAP = 20

_MAX_RESOLVED_CHOICES = 1000

_NUMERIC_CHOICE_CAP = 50

_NUMERIC_TYPES: frozenset[str] = frozenset({"number", "money", "percent", "double"})


def _coerce_choices_to_type(values: list[Any], data_type: str) -> list[Any]:
    """Cast distinct-value strings to match the column's declared type."""
    if data_type in _NUMERIC_TYPES:
        coerced: list[Any] = []
        for v in values:
            try:
                num = float(v)
            except (TypeError, ValueError):
                continue
            if num.is_integer():
                coerced.append(int(num))
            else:
                coerced.append(num)
        return coerced
    if data_type == "checkbox":
        coerced_bool: list[Any] = []
        for v in values:
            if v is None:
                continue
            if isinstance(v, bool):
                coerced_bool.append(v)
            elif isinstance(v, str) and v.lower() in {"true", "false"}:
                coerced_bool.append(v.lower() == "true")
        return coerced_bool
    return values


def _cached_top_values(column: dict[str, Any]) -> list[Any]:
    """Pull the items out of a column's ``cachedContents.top`` list."""
    cached = column.get("cachedContents") or {}
    top = cached.get("top") or []
    values: list[Any] = []
    for entry in top:
        if isinstance(entry, dict):
            item = entry.get("item")
            if item is not None:
                values.append(item)
        elif entry is not None:
            values.append(entry)
    return values


def _is_categorical_column(column: dict[str, Any]) -> bool:
    """Return True when querying for distinct values is worthwhile."""
    return (column.get("dataTypeName") or "text") in ("text", "html")


async def afetch_column_distinct_values(
    client: httpx.AsyncClient,
    host: str,
    uid: str,
    field_name: str,
    *,
    limit: int = _MAX_RESOLVED_CHOICES,
) -> list[Any] | None:
    """Resolve a column's full distinct-value set via SoQL (async)."""
    query = urllib.parse.urlencode(
        {
            "$select": field_name,
            "$group": field_name,
            "$order": field_name,
            "$limit": str(limit + 1),
        }
    )
    url = f"{host.rstrip('/')}/resource/{uid}.json?{query}"
    try:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, OSError):
        return None
    if not isinstance(payload, list) or len(payload) > limit:
        return None
    out: list[Any] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        value = row.get(field_name)
        if value is not None:
            out.append(value)
    return out


def _column_choices(
    column: dict[str, Any],
    *,
    host: str | None = None,
    uid: str | None = None,
    resolver: Any = None,
    choices_cache: dict[tuple[str, str], list[Any] | None] | None = None,
) -> list[Any]:
    """Return the closed ``choices`` set for a column, or ``[]`` if unbounded."""
    field_name = column.get("fieldName") or column.get("name")
    if (
        choices_cache is not None
        and host
        and uid
        and field_name
        and (uid, field_name) in choices_cache
    ):
        cached = choices_cache[(uid, field_name)]
        if cached is None:
            return []
        type_name = column.get("dataTypeName") or ""
        return _coerce_choices_to_type(cached, type_name)
    if not host or not uid:
        return _cached_top_values(column)
    if not field_name:
        return []
    if resolver is None:
        return _cached_top_values(column)
    fetch = resolver
    type_name = column.get("dataTypeName") or ""
    cap = _NUMERIC_CHOICE_CAP if type_name in _NUMERIC_TYPES else _MAX_RESOLVED_CHOICES
    resolved = fetch(host, uid, field_name, limit=cap)
    if resolved is not None:
        return _coerce_choices_to_type(resolved, type_name)
    cached = column.get("cachedContents") or {}
    if 0 < len(cached.get("top") or []) < _CACHED_TOP_CAP:
        return _cached_top_values(column)
    return []


def _column_help(column: dict[str, Any]) -> str:
    """Compose the per-column help text shown under ``--<col>=<value>``."""
    parts: list[str] = []
    description = column.get("description")
    if description:
        parts.append(description.strip().rstrip(".") + ".")
    cached = column.get("cachedContents") or {}
    top = cached.get("top") or []
    if top and len(top) >= _CACHED_TOP_CAP:
        sample = []
        for entry in top[:5]:
            item = entry.get("item") if isinstance(entry, dict) else entry
            if item is not None:
                sample.append(str(item))
        if sample:
            parts.append(f"Examples: {', '.join(sample)}.")
    smallest = cached.get("smallest")
    largest = cached.get("largest")
    if smallest is not None and largest is not None and len(top) >= _CACHED_TOP_CAP:
        parts.append(f"Range: {smallest} – {largest}.")
    return " ".join(parts)


def _column_param_type(column: dict[str, Any]) -> str:
    """Map a Socrata ``dataTypeName`` to a spec ``type`` value."""
    type_name = column.get("dataTypeName") or "text"
    if type_name in ("number", "money", "double", "percent"):
        return "number"
    if type_name == "checkbox":
        return "boolean"
    return "string"


_DATE_COLUMN_TYPES: frozenset[str] = frozenset({"calendar_date", "date"})

_TIME_AXIS_NAME_PATTERNS: tuple[str, ...] = (
    "month_year",
    "year_month",
    "yearmonth",
    "monthyear",
    "as_of_date",
    "as_of",
    "asof",
    "observation_date",
    "report_date",
    "release_date",
    "effective_date",
    "date",
    "datetime",
    "timestamp",
    "time",
    "year",
    "quarter",
    "month",
    "week",
    "period",
)


def _is_date_column(column: dict[str, Any]) -> bool:
    """Return True when the column's data type calls for range-style filtering."""
    return (column.get("dataTypeName") or "") in _DATE_COLUMN_TYPES


def _is_time_axis_named(field_name: str) -> bool:
    """Return True when the column's name suggests it carries a time value."""
    name = (field_name or "").lower()
    return name in _TIME_AXIS_NAME_PATTERNS


def _detect_time_axis_column(meta: dict[str, Any]) -> str | None:
    """Pick the column to sort by descending for most-recent semantics."""
    for col in meta.get("columns") or []:
        if not isinstance(col, dict):
            continue
        if _is_date_column(col):
            field_name = col.get("fieldName") or col.get("name")
            if field_name:
                return field_name
    candidates: list[str] = []
    for col in meta.get("columns") or []:
        if not isinstance(col, dict):
            continue
        field_name = col.get("fieldName") or col.get("name")
        if field_name and _is_time_axis_named(field_name):
            candidates.append(field_name)
    if not candidates:
        return None
    candidates.sort(key=len, reverse=True)
    return candidates[0]


def _to_plain_date(value: Any) -> Any:
    """Trim the time component off a Socrata datetime string."""
    if not isinstance(value, str):
        return value
    if "T" in value and len(value) >= 10 and value[4] == "-" and value[7] == "-":
        return value.split("T", 1)[0]
    return value


def _date_range_parameters(column: dict[str, Any]) -> list[dict[str, Any]]:
    """Emit a uniform ``start_date`` / ``end_date`` pair for a date column."""
    field_name = column.get("fieldName") or column.get("name")
    cached = column.get("cachedContents") or {}
    smallest = _to_plain_date(cached.get("smallest"))
    largest = _to_plain_date(cached.get("largest"))
    description = column.get("description") or ""
    base_help = description.strip().rstrip(".")
    range_text = (
        f" Dataset spans {smallest} to {largest}." if smallest and largest else ""
    )
    return [
        {
            "name": "start_date",
            "in": "query",
            "type": "string",
            "is_list": False,
            "required": False,
            "default": None,
            "choices": [],
            "example": smallest,
            "help": (
                f"Earliest date (YYYY-MM-DD) to include — filters on ``{field_name}``."
                f" Omit to fetch from the dataset's earliest record."
                f"{(' ' + base_help + '.') if base_help else ''}"
                f"{range_text}"
            ).strip(),
            "providers": [],
            "_socrata_op": "date_min",
            "_socrata_column": field_name,
        },
        {
            "name": "end_date",
            "in": "query",
            "type": "string",
            "is_list": False,
            "required": False,
            "default": None,
            "choices": [],
            "example": largest,
            "help": (
                f"Latest date (YYYY-MM-DD) to include — filters on ``{field_name}``."
                f" Omit to fetch through the dataset's latest record."
                f"{(' ' + base_help + '.') if base_help else ''}"
                f"{range_text}"
            ).strip(),
            "providers": [],
            "_socrata_op": "date_max",
            "_socrata_column": field_name,
        },
    ]


def _build_query_parameters(
    meta: dict[str, Any],
    *,
    host: str | None = None,
    uid: str | None = None,
    resolver: Any = None,
    choices_cache: dict[tuple[str, str], list[Any] | None] | None = None,
) -> list[dict[str, Any]]:
    """Build the per-dataset query parameter list."""
    parameters: list[dict[str, Any]] = []
    date_range_emitted = False
    for column in meta.get("columns") or []:
        if not isinstance(column, dict):
            continue
        field_name = column.get("fieldName") or column.get("name")
        if not field_name:
            continue
        if _is_date_column(column):
            if not date_range_emitted:
                parameters.extend(_date_range_parameters(column))
                date_range_emitted = True
            continue
        parameters.append(
            {
                "name": field_name,
                "in": "query",
                "type": _column_param_type(column),
                "is_list": False,
                "required": False,
                "default": None,
                "choices": _column_choices(
                    column,
                    host=host,
                    uid=uid,
                    resolver=resolver,
                    choices_cache=choices_cache,
                ),
                "example": None,
                "help": _column_help(column),
                "providers": [],
            }
        )
    parameters.extend(
        [
            {
                "name": "limit",
                "in": "query",
                "type": "integer",
                "is_list": False,
                "required": False,
                "default": 1000,
                "choices": [],
                "example": None,
                "help": (
                    "Max rows returned. Socrata's API default is 1000; up to "
                    "50000 per request without pagination."
                ),
                "providers": [],
                "wire_name": "$limit",
            },
            {
                "name": "offset",
                "in": "query",
                "type": "integer",
                "is_list": False,
                "required": False,
                "default": None,
                "choices": [],
                "example": None,
                "help": "Row offset for pagination — pair with limit.",
                "providers": [],
                "wire_name": "$offset",
            },
        ]
    )
    return parameters


_SOCRATA_TYPE_MAP: dict[str, dict[str, Any]] = {
    "text": {"type": "string"},
    "html": {"type": "string"},
    "number": {"type": "number"},
    "money": {"type": "number"},
    "percent": {"type": "number"},
    "double": {"type": "number"},
    "checkbox": {"type": "boolean"},
    "calendar_date": {"type": "string", "format": "date"},
    "date": {"type": "string", "format": "date"},
    "url": {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "description": {"type": "string"},
        },
    },
    "email": {"type": "string"},
    "phone": {"type": "object"},
    "point": {"type": "object"},
    "location": {"type": "object"},
    "multipoint": {"type": "object"},
    "line": {"type": "object"},
    "multiline": {"type": "object"},
    "polygon": {"type": "object"},
    "multipolygon": {"type": "object"},
    "photo": {"type": "object"},
    "document": {"type": "object"},
}


def _slugify(name: str) -> str:
    """Translate a free-form dataset name to a snake_case identifier."""
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()
    if not cleaned:
        cleaned = "dataset"
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


_PREFIX_STOP_TOKENS: frozenset[str] = frozenset(
    {"by", "for", "of", "in", "at", "to", "with", "and", "the"}
)


def _common_token_prefix(token_lists: list[list[str]]) -> list[str]:
    """Return the longest leading token sequence shared by every input."""
    if not token_lists:
        return []
    shortest = min(len(tl) for tl in token_lists)
    common: list[str] = []
    for i in range(shortest):
        token = token_lists[0][i]
        if all(tl[i] == token for tl in token_lists):
            common.append(token)
        else:
            break
    return common


def _longest_common_token_run(token_lists: list[list[str]]) -> list[str]:
    """Return the longest contiguous token run shared by every input list."""
    if not token_lists:
        return []
    first = token_lists[0]
    n = len(first)
    others = token_lists[1:]
    for length in range(n, 0, -1):
        for start in range(n - length + 1):
            candidate = first[start : start + length]
            if all(
                any(
                    tl[i : i + length] == candidate for i in range(len(tl) - length + 1)
                )
                for tl in others
            ):
                return candidate
    return []


def _strip_stop_tokens(tokens: list[str]) -> list[str]:
    """Trim leading and trailing connector words from a token list."""
    out = list(tokens)
    while out and out[-1] in _PREFIX_STOP_TOKENS:
        out.pop()
    while out and out[0] in _PREFIX_STOP_TOKENS:
        out.pop(0)
    return out


_MIN_SHARED_RUN = 2


def _assign_router_namespaces(
    slugs: dict[str, str],
) -> dict[str, tuple[str | None, str]]:
    """Group dataset slugs into ``(router, command)`` pairs.

    Parameters
    ----------
    slugs : dict
        Mapping of dataset UID to slugified dataset name.

    Returns
    -------
    dict
        Mapping of dataset UID to ``(router_or_None, command)`` tuple.
    """
    if not slugs:
        return {}
    token_lists: dict[str, list[str]] = {
        uid: slug.split("_") for uid, slug in slugs.items()
    }
    uids = list(slugs.keys())

    parent: dict[str, str] = {uid: uid for uid in uids}

    def find(u: str) -> str:
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    def union(u: str, v: str) -> None:
        ru, rv = find(u), find(v)
        if ru != rv:
            parent[ru] = rv

    for i in range(len(uids)):
        for j in range(i + 1, len(uids)):
            run = _longest_common_token_run(
                [token_lists[uids[i]], token_lists[uids[j]]]
            )
            if len(run) >= _MIN_SHARED_RUN:
                union(uids[i], uids[j])

    groups: dict[str, list[str]] = {}
    for uid in uids:
        groups.setdefault(find(uid), []).append(uid)

    out: dict[str, tuple[str | None, str]] = {}
    for group_uids in groups.values():
        if len(group_uids) == 1:
            uid = group_uids[0]
            out[uid] = (None, slugs[uid])
            continue
        group_tokens = [token_lists[u] for u in group_uids]
        router_tokens = _strip_stop_tokens(_longest_common_token_run(group_tokens))
        if not router_tokens:
            for uid in group_uids:
                out[uid] = (None, slugs[uid])
            continue
        router = "_".join(router_tokens)
        run_len = len(router_tokens)
        member_commands = {
            uid: _command_tokens_around_run(token_lists[uid], router_tokens, run_len)
            for uid in group_uids
        }
        if all(not c for c in member_commands.values()):
            for uid in group_uids:
                out[uid] = (None, slugs[uid])
            continue
        for uid in group_uids:
            tokens = member_commands[uid]
            command = "_".join(tokens) if tokens else "query"
            out[uid] = (router, command)
    return out


def _command_tokens_around_run(
    tokens: list[str], router_tokens: list[str], run_len: int
) -> list[str]:
    """Return ``tokens`` minus the first occurrence of ``router_tokens``."""
    for i in range(len(tokens) - run_len + 1):
        if tokens[i : i + run_len] == router_tokens:
            return tokens[:i] + tokens[i + run_len :]
    return list(tokens)


def _walk_for_dataset_uids(node: Any, sink: set[str]) -> None:
    """Recursively collect every ``datasetUid`` value in a JSON tree."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "datasetUid" and isinstance(value, str):
                sink.add(value)
            else:
                _walk_for_dataset_uids(value, sink)
    elif isinstance(node, list):
        for item in node:
            _walk_for_dataset_uids(item, sink)


def extract_dataset_uids(story: dict[str, Any]) -> list[str]:
    """Return the unique dataset UIDs referenced by a story, in stable order."""
    sink: set[str] = set()
    _walk_for_dataset_uids(story, sink)
    return sorted(sink)


_STORY_URL_RE = re.compile(
    r"^(?P<base>https?://[^/]+/stories/s/[a-z0-9]{4}-[a-z0-9]{4})(?P<rest>.*)$"
)

_SINGLE_VIEW_URL_RE = re.compile(
    r"^(?P<host>https?://[^/]+)"
    r"/(?:resource|api/views)/(?P<uid>[a-z0-9]{4}-[a-z0-9]{4})"
    r"(?:\.json)?(?:\?.*)?$"
)


def _direct_dataset_seed(source: str) -> tuple[str, str] | None:
    """Detect ``/resource/`` or ``/api/views/`` URLs and return ``(host, uid)``."""
    match = _SINGLE_VIEW_URL_RE.match(source)
    if match:
        return match.group("host"), match.group("uid")
    return None


def _normalize_story_url(source: str) -> str:
    """Append ``.json`` when the user pastes the browser-facing story URL."""
    match = _STORY_URL_RE.match(source)
    if not match:
        return source
    rest = match.group("rest")
    if rest.startswith(".json") or rest.startswith("?") and ".json" in rest:
        return source
    if not rest:
        return f"{match.group('base')}.json"
    if rest.startswith("?"):
        return f"{match.group('base')}.json{rest}"
    return source


async def _aread_json_url_or_path(source: str, *, timeout: float = 15.0) -> Any:
    """Load JSON from an HTTP URL (async via httpx) or local file path (sync)."""
    if source.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            response = await client.get(source)
            response.raise_for_status()
            return response.json()
    return json.loads(Path(source).read_text())


def _story_host(story_source: str, story: dict[str, Any]) -> str:
    """Pick the portal base URL the story's datasets live on."""
    domain = (story.get("dataSource") or {}).get("domainCName")
    if isinstance(domain, str) and domain:
        return f"https://{domain}".rstrip("/")
    if story_source.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(story_source)
        return f"{parsed.scheme}://{parsed.netloc}"
    raise ValueError(
        "story has no ``dataSource.domainCName`` and the source is a local "
        "file — pass an HTTP URL or add the host to the story document."
    )


async def _afetch_json(client: httpx.AsyncClient, url: str) -> Any:
    """Async GET + JSON-decode, raising on HTTP errors."""
    response = await client.get(url)
    response.raise_for_status()
    return response.json()


async def _amaybe_call(callable_: Any, *args: Any, **kwargs: Any) -> Any:
    """Invoke ``callable_`` and ``await`` the result if it's a coroutine."""
    result = callable_(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


async def _aone_metadata(
    client: httpx.AsyncClient,
    host: str,
    uid: str,
    fetcher: Any,
) -> dict[str, Any] | None:
    """Fetch one view's metadata, returning ``None`` on any failure."""
    if fetcher is None or fetcher is afetch_dataset_metadata:
        try:
            return await afetch_dataset_metadata(client, host, uid)
        except (httpx.HTTPError, ValueError, OSError):
            return None
    try:
        return await _amaybe_call(fetcher, host, uid)
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _afetch_metadata_batch(
    client: httpx.AsyncClient,
    host: str,
    uids: list[str],
    fetcher: Any,
) -> dict[str, dict[str, Any] | None]:
    """Concurrently fetch metadata for many UIDs."""
    if not uids:
        return {}
    sem = asyncio.Semaphore(_DISCOVERY_MAX_WORKERS)

    async def _one(uid: str) -> dict[str, Any] | None:
        async with sem:
            return await _aone_metadata(client, host, uid, fetcher)

    results = await asyncio.gather(*(_one(uid) for uid in uids))
    return dict(zip(uids, results))


async def _aone_choice(
    client: httpx.AsyncClient,
    host: str,
    uid: str,
    field: str,
    cap: int,
    resolver: Any,
) -> list[Any] | None:
    """Fetch one column's distinct values, ``None`` on overflow / error."""
    if resolver is None or resolver is afetch_column_distinct_values:
        return await afetch_column_distinct_values(client, host, uid, field, limit=cap)
    try:
        return await _amaybe_call(resolver, host, uid, field, limit=cap)
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _abuild_discovery(
    story_source: str,
    host_override: str | None,
    fetcher: Any,
    choice_resolver: Any,
    direct_seed: tuple[str, str] | None = None,
) -> tuple[
    dict[str, Any],
    str,
    dict[str, dict[str, Any]],
    dict[str, str],
    list[tuple[str, str]],
    dict[tuple[str, str], list[Any] | None],
]:
    """Run the full async discovery pipeline end-to-end."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        limits=httpx.Limits(
            max_connections=_DISCOVERY_MAX_WORKERS * 2,
            max_keepalive_connections=_DISCOVERY_MAX_WORKERS,
        ),
    ) as client:
        if direct_seed is not None:
            seed_host, seed_uid = direct_seed
            story = {"_synthetic_single_view": True, "uid": seed_uid}
            host = host_override or seed_host
            uids = [seed_uid]
        else:
            story = await _aload_story(client, story_source)
            host = host_override or _story_host(story_source, story)
            uids = extract_dataset_uids(story)

        metas: dict[str, dict[str, Any]] = {}
        slugs: dict[str, str] = {}
        skipped: list[tuple[str, str]] = []
        pending: list[str] = list(dict.fromkeys(uids))
        processed: set[str] = set()

        while pending:
            wave = [uid for uid in pending if uid not in processed]
            pending = []
            if not wave:  # pragma: no cover
                break
            processed.update(wave)
            wave_metas = await _afetch_metadata_batch(client, host, wave, fetcher)
            for uid, meta in wave_metas.items():
                if meta is None:
                    skipped.append((uid, "unreachable"))
                    continue
                asset_type = meta.get("assetType")
                if asset_type in {"dataset", "filter"}:
                    metas[uid] = meta
                    slugs[uid] = _slugify(meta.get("name") or uid)
                else:
                    skipped.append((uid, asset_type or "unknown"))
                backing = _backing_dataset_uid(meta)
                if backing and backing not in processed:
                    pending.append(backing)
        choices_cache = await _aprobe_choices_batch(
            client, host, metas, choice_resolver
        )
    return story, host, metas, slugs, skipped, choices_cache


async def _aload_story(client: httpx.AsyncClient, story_source: str) -> dict[str, Any]:
    """Async version of ``_aread_json_url_or_path`` that reuses the client."""
    if story_source.startswith(("http://", "https://")):
        response = await client.get(story_source)
        response.raise_for_status()
        return response.json()
    return json.loads(Path(story_source).read_text())


async def _aprobe_choices_batch(
    client: httpx.AsyncClient,
    host: str,
    metas: dict[str, dict[str, Any]],
    resolver: Any,
) -> dict[tuple[str, str], list[Any] | None]:
    """Concurrently probe distinct-value choices for every column on every dataset."""
    tasks: list[tuple[str, str, int]] = []
    for uid, meta in metas.items():
        for col in meta.get("columns") or []:
            if not isinstance(col, dict):
                continue
            field = col.get("fieldName") or col.get("name")
            if not field:
                continue
            if _is_date_column(col):
                continue
            type_name = col.get("dataTypeName") or "text"
            if type_name not in _NUMERIC_TYPES and type_name not in {
                "text",
                "html",
                "checkbox",
            }:
                continue
            cap = (
                _NUMERIC_CHOICE_CAP
                if type_name in _NUMERIC_TYPES
                else _MAX_RESOLVED_CHOICES
            )
            tasks.append((uid, field, cap))

    if not tasks:
        return {}

    sem = asyncio.Semaphore(_DISCOVERY_MAX_WORKERS)

    async def _one(
        uid: str, field: str, cap: int
    ) -> tuple[tuple[str, str], list[Any] | None]:
        async with sem:
            value = await _aone_choice(client, host, uid, field, cap, resolver)
        return (uid, field), value

    results = await asyncio.gather(
        *(_one(uid, field, cap) for uid, field, cap in tasks)
    )
    return dict(results)


async def afetch_dataset_metadata(
    client: httpx.AsyncClient, host: str, uid: str
) -> dict[str, Any]:
    """Fetch a Socrata view's metadata JSON (async)."""
    url = f"{host.rstrip('/')}/api/views/{uid}.json"
    response = await client.get(url)
    response.raise_for_status()
    return response.json()


def _backing_dataset_uid(meta: dict[str, Any]) -> str | None:
    """Return the UID of a non-dataset view's backing dataset, or ``None``."""
    backing = meta.get("modifyingViewUid")
    if isinstance(backing, str) and backing:
        return backing
    query = meta.get("query")
    if isinstance(query, dict):
        source = query.get("viewSourceId")
        if isinstance(source, str) and source:
            return source
    return None


def _column_to_schema(column: dict[str, Any]) -> dict[str, Any]:
    """Translate one Socrata column descriptor into a JSON-schema fragment."""
    type_name = column.get("dataTypeName") or "text"
    schema = dict(_SOCRATA_TYPE_MAP.get(type_name, {"type": "string"}))
    description = column.get("description")
    if description:
        cleaned = description.strip()
        if cleaned:
            schema["description"] = cleaned
    fmt = column.get("format")
    if isinstance(fmt, dict) and fmt:
        rendering_hints = {
            k: v
            for k, v in fmt.items()
            if k
            in {
                "precisionStyle",
                "currency",
                "decimalSeparator",
                "groupSeparator",
                "noCommas",
                "precision",
                "view",
                "mask",
            }
        }
        if rendering_hints:
            schema["socrata_format"] = rendering_hints
    return schema


def _build_response_schema(meta: dict[str, Any]) -> dict[str, Any]:
    """Build a row-shape schema from a dataset's column metadata."""
    columns = meta.get("columns") or []
    properties: dict[str, dict[str, Any]] = {}
    for column in columns:
        if not isinstance(column, dict):
            continue
        field_name = column.get("fieldName") or column.get("name")
        if not field_name:
            continue
        properties[field_name] = _column_to_schema(column)
    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {"type": "object", "properties": properties},
            }
        },
    }


def _build_command(
    host: str,
    uid: str,
    meta: dict[str, Any],
    *,
    choice_resolver: Any = None,
    choices_cache: dict[tuple[str, str], list[Any] | None] | None = None,
) -> dict[str, Any]:
    """Synthesize one spec command entry for a dataset."""
    name = (meta.get("name") or uid).strip()
    description = (meta.get("description") or "").strip()
    summary = description or name
    parameters = _build_query_parameters(
        meta,
        host=host,
        uid=uid,
        resolver=choice_resolver,
        choices_cache=choices_cache,
    )
    time_axis = _detect_time_axis_column(meta)
    return {
        "url_path": f"/resource/{uid}.json",
        "method": "get",
        "description": summary,
        "parameters": parameters,
        "providers": [],
        "request_body_schema": None,
        "request_body_schemas": {},
        "response_schema": _build_response_schema(meta),
        "response_schemas": {},
        "_socrata_time_axis": time_axis,
        "_socrata_primary_item": _primary_item_column(parameters, time_axis),
    }


def _primary_item_column(
    parameters: list[dict[str, Any]], time_axis: str | None
) -> str | None:
    """Pick the column to use as the per-item key for ``limit`` semantics."""
    excluded: set[str] = {"limit", "offset"}
    if time_axis:
        excluded.add(time_axis)
    candidates: list[tuple[int, str]] = []
    for p in parameters:
        if not isinstance(p, dict):
            continue
        if p.get("_socrata_op") in {"date_min", "date_max"}:
            continue
        name = p.get("name")
        if not name or name in excluded:
            continue
        if _is_time_axis_named(name):
            continue
        if p.get("type") != "string":
            continue
        choices = p.get("choices") or []
        if len(choices) < 3:
            continue
        candidates.append((len(choices), name))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: -pair[0])
    return candidates[0][1]


def build_socrata_spec(
    story_source: str,
    *,
    host_override: str | None = None,
    fetch: Any = None,
    choice_resolver: Any = None,
) -> dict[str, Any]:
    """Build a complete spec document from a Socrata story URL or local path.

    Parameters
    ----------
    story_source : str
        A story URL or a path to a previously-downloaded story JSON file.
    host_override : str, optional
        Portal base URL to use instead of the one inferred from the story.
    fetch : callable, optional
        Override the metadata fetcher — signature ``(host, uid) -> dict``.
    choice_resolver : callable, optional
        Override the per-column distinct-value resolver.

    Returns
    -------
    dict
        A spec document conforming to ``SpecDocument``.
    """
    story_source = _normalize_story_url(story_source)
    direct_seed = _direct_dataset_seed(story_source)
    story, host, metas, slugs, skipped, choices_cache = asyncio.run(
        _abuild_discovery(
            story_source,
            host_override,
            fetch,
            choice_resolver,
            direct_seed=direct_seed,
        )
    )

    assignments = _assign_router_namespaces(slugs)

    commands: dict[str, dict[str, Any]] = {}
    seen_paths: set[str] = set()
    for uid, (router, command) in assignments.items():
        path = command if router is None else f"{router}.{command}"
        if path in seen_paths:
            path = f"{path}_{uid.replace('-', '')}"
        seen_paths.add(path)
        commands[path] = _build_command(
            host,
            uid,
            metas[uid],
            choice_resolver=choice_resolver,
            choices_cache=choices_cache,
        )

    return {
        "version": SPEC_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "generator": _generator_identifier(),
        "source_url": story_source,
        "api_version": "socrata-soda-2.1",
        "base_url": host,
        "api_prefix": "",
        "commands": commands,
        "routers": _build_routers(commands),
        "reference": _build_reference(commands),
        "_socrata": {
            "story_uid": story.get("uid"),
            "dataset_count": len(commands),
            "skipped": [{"uid": u, "asset_type": t} for u, t in skipped],
        },
    }


def _build_routers(commands: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Mark every namespace prefix as ``menu`` and every leaf as ``command``."""
    out: dict[str, str] = {}
    for cmd_path in commands:
        parts = cmd_path.split(".")
        for i in range(1, len(parts)):
            out[".".join(parts[:i])] = "menu"
        out[cmd_path] = "command"
    return out


def _build_reference(
    commands: dict[str, dict[str, Any]],
) -> dict[str, dict[str, dict[str, str]]]:
    """Build the slash-style reference index the REPL renders menu help from."""
    paths: dict[str, dict[str, str]] = {}
    routers: dict[str, dict[str, str]] = {}
    for cmd_path, cmd_spec in commands.items():
        parts = cmd_path.split(".")
        slash_path = "/" + "/".join(parts)
        paths[slash_path] = {"description": cmd_spec.get("description", "")}
        for i in range(1, len(parts)):
            slash_router = "/" + "/".join(parts[:i]) + "/"
            routers.setdefault(slash_router, {"description": ""})
    return {"paths": paths, "routers": routers}
