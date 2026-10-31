"""HTTP dispatcher — thin client that talks to a long-running openbb-platform-api server."""

from __future__ import annotations

import contextlib
import inspect
import json
import re
import warnings
from datetime import datetime, timezone
from time import perf_counter_ns
from typing import Any

import httpx
from openbb_core.app.model.abstract.warning import OpenBBWarning

from openbb_cli.auth import AuthContext, AuthDecision, AuthHook
from openbb_cli.dispatchers._unpack import unpack_response
from openbb_cli.dispatchers.openapi_schema import (
    PROVIDER_SECTION_SPLIT_RE,
    PROVIDER_TAG_RE,
)
from openbb_cli.dispatchers.protocol import Request, Response, ResponseError
from openbb_cli.dispatchers.spec import command_parameters

_PATH_TEMPLATE_RE = re.compile(r"\{([^}]+)\}")


def _help_for_provider(text: str | None, provider: str) -> str | None:
    """Pick the sections of an OpenBB-merged help string that apply to ``provider``."""
    if not text:
        return text
    sections = PROVIDER_SECTION_SPLIT_RE.split(text)
    target = provider.lower()
    kept: list[str] = []
    for raw_section in sections:
        section = raw_section.strip()
        if not section:
            continue
        match = PROVIDER_TAG_RE.search(section)
        if match is None:
            kept.append(section)
            continue
        tag_providers = {
            p.strip().lower() for p in match.group(1).split(",") if p.strip()
        }
        if target in tag_providers:
            kept.append(PROVIDER_TAG_RE.sub("", section).rstrip())
    return "\n".join(kept) if kept else None


# Wire delimiter per spec ``list_style``; ``multi`` (repeated key) needs none.
_LIST_DELIMITERS = {"csv": ",", "space": " ", "pipe": "|"}


def _slim_param(p: dict[str, Any]) -> dict[str, Any]:
    """Strip empty / falsy fields from a normalized parameter entry."""
    out: dict[str, Any] = {
        "name": p["name"],
        "in": p.get("in", "query"),
        "type": p.get("type", "string"),
    }
    if p.get("is_list"):
        out["is_list"] = True
        if p.get("list_style"):
            out["list_style"] = p["list_style"]
    if p.get("json_arg"):
        out["json_arg"] = True
    if p.get("required"):
        out["required"] = True
    if p.get("default") is not None:
        out["default"] = p["default"]
    if p.get("choices"):
        out["choices"] = p["choices"]
    if p.get("help"):
        out["help"] = p["help"]
    return out


def _group_by_provider(
    raw_params: list[dict[str, Any]],
    providers: list[str],
    output_schema: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Group parameters and output schemas per provider."""
    out: dict[str, dict[str, Any]] = {}
    for provider in providers:
        provider_params: list[dict[str, Any]] = []
        for p in raw_params:
            if p.get("name") == "provider":
                continue
            tags = p.get("providers") or []
            if tags and provider not in tags:
                continue
            slim = _slim_param(p)
            slim["help"] = _help_for_provider(slim.get("help"), provider)
            if not slim.get("help"):
                slim.pop("help", None)
            provider_params.append(slim)
        out[provider] = {
            "parameters": provider_params,
            "output_schema": _provider_output_schema(output_schema, provider),
        }
    return out


def _provider_output_schema(
    output_schema: dict[str, Any] | None, provider: str
) -> dict[str, Any] | None:
    """Pick the per-provider variant out of a OneOf-of-data-classes results list."""
    if not isinstance(output_schema, dict):
        return None
    results = (output_schema.get("properties") or {}).get("results")
    if not isinstance(results, dict):
        return None
    candidates: list[Any] = []
    for variant in results.get("anyOf") or [results]:
        if not isinstance(variant, dict) or variant.get("type") == "null":
            continue
        if variant.get("type") == "array" and isinstance(variant.get("items"), dict):
            inner = variant["items"]
            candidates.extend(inner.get("oneOf") or [inner])
        else:
            candidates.extend(variant.get("oneOf") or [variant])
    target = provider.lower()
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        title = (cand.get("title") or "").lower()
        if title.startswith(target):
            return cand
    if len(candidates) == 1 and isinstance(candidates[0], dict):
        return candidates[0]
    return None


def _decode_response(response: httpx.Response) -> Any:
    """Return the response body as JSON when the server says so, otherwise text."""
    content_type = (response.headers.get("content-type") or "").lower().split(";", 1)[0]
    if content_type.endswith("json") or content_type == "":
        try:
            return response.json()
        except ValueError:
            return response.text
    return response.text


class _HttpSSESource:
    """Adapt an HTTP streaming endpoint to the ``OBBStream`` body_iterator protocol.

    Holds the request details and opens the connection lazily on first iteration
    (inside ``OBBStream``'s worker loop), so the stream's lifetime is bound to the
    handle — not to the dispatcher's event loop.
    """

    media_type = "text/event-stream"

    def __init__(self, url, params, headers, method="get", body=None) -> None:
        self.provider: str | None = None
        self.warnings: list[dict[str, Any]] | None = None
        self.body_iterator = self._iterate(url, params, headers, method, body)

    def _consume_headers(self, response_headers) -> None:
        """Surface the server's out-of-band stream headers (provider, warnings).

        Parameters
        ----------
        response_headers : Mapping
            The streaming response's headers.
        """
        self.provider = response_headers.get("X-OpenBB-Provider")
        raw = response_headers.get("X-OpenBB-Warning")
        if not raw:
            return
        try:
            items = json.loads(raw)
        except (ValueError, TypeError):
            return
        self.warnings = items
        for item in items:
            message = item.get("message") if isinstance(item, dict) else str(item)
            warnings.warn(message, OpenBBWarning, stacklevel=2)

    async def _iterate(self, url, params, headers, method, body):
        async with httpx.AsyncClient(timeout=None) as client:  # noqa: S113
            request_kwargs: dict[str, Any] = {"params": params, "headers": headers}
            if method == "post":
                request_kwargs["json"] = body or {}
            async with client.stream(method.upper(), url, **request_kwargs) as resp:
                resp.raise_for_status()
                self._consume_headers(resp.headers)
                async for line in resp.aiter_lines():
                    if line:
                        yield line + "\n"


_NUMERIC_RESPONSE_TYPES: frozenset[str] = frozenset(
    {"number", "money", "percent", "double"}
)

_SOCRATA_PAGE_SIZE = 5000

_SOCRATA_MAX_PAGES = 1000


def _user_requested_all_rows(request: Request) -> bool:
    """Return True when the caller asked for the full dataset (``limit=0``)."""
    raw = (request.params or {}).get("limit")
    if raw is None:
        return False
    try:
        return int(raw) == 0
    except (TypeError, ValueError):
        return False


def _user_limit_for_per_item(request: Request) -> int | None:
    """Return the user's ``limit`` as an int, or ``None`` if unusable."""
    raw = (request.params or {}).get("limit")
    if raw is None:
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    if n < 0:
        return None
    return n if n > 0 else None


async def _fetch_until_n_distinct_dates(
    client: httpx.AsyncClient,
    url: str,
    base_query: dict[str, Any],
    extra_headers: dict[str, str] | None,
    time_axis: str,
    n: int,
) -> list[dict[str, Any]]:
    """Page until the response covers >= ``n + 1`` distinct ``time_axis`` values."""
    rows: list[dict[str, Any]] = []
    distinct_dates: set[Any] = set()
    base = dict(base_query)
    base["$limit"] = _SOCRATA_PAGE_SIZE
    for page in range(_SOCRATA_MAX_PAGES):
        page_params = dict(base)
        page_params["$offset"] = page * _SOCRATA_PAGE_SIZE
        response = await client.get(url, params=page_params, headers=extra_headers)
        response.raise_for_status()
        payload = _decode_response(response)
        if not isinstance(payload, list) or not payload:
            break
        rows.extend(payload)
        for row in payload:
            if isinstance(row, dict):
                value = row.get(time_axis)
                if value is not None:
                    distinct_dates.add(value)
        if len(distinct_dates) > n:
            break
        if len(payload) < _SOCRATA_PAGE_SIZE:
            break
    return rows


async def _fetch_all_pages(
    client: httpx.AsyncClient,
    url: str,
    base_query: dict[str, Any],
    extra_headers: dict[str, str] | None,
) -> list[dict[str, Any]]:
    """Page through ``$offset`` until the upstream returns an empty page."""
    rows: list[dict[str, Any]] = []
    base = dict(base_query)
    base["$limit"] = _SOCRATA_PAGE_SIZE
    for page in range(_SOCRATA_MAX_PAGES):
        page_params = dict(base)
        page_params["$offset"] = page * _SOCRATA_PAGE_SIZE
        response = await client.get(url, params=page_params, headers=extra_headers)
        response.raise_for_status()
        payload = _decode_response(response)
        if not isinstance(payload, list) or not payload:
            break
        rows.extend(payload)
        if len(payload) < _SOCRATA_PAGE_SIZE:
            break
    return rows


def _request_with_page_size_limit(request: Request) -> Request:
    """Return a copy of ``request`` with ``limit`` capped to one page."""
    bumped = dict(request.params or {})
    bumped["limit"] = _SOCRATA_PAGE_SIZE
    return Request(id=request.id, command=request.command, params=bumped)


def _truncate_to_top_n_dates(
    shaped: Any, time_axis: str, user_limit: int | None
) -> Any:
    """Keep every row whose ``time_axis`` is among the ``user_limit`` most recent."""
    rows = _extract_rows(shaped)
    if rows is None or user_limit is None:
        return shaped
    seen_dates: list[Any] = []
    seen_set: set[Any] = set()
    kept: list[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            kept.append(row)
            continue
        date = row.get(time_axis)
        if date is None:
            kept.append(row)
            continue
        if date not in seen_set:
            if len(seen_dates) >= user_limit:
                break
            seen_dates.append(date)
            seen_set.add(date)
        kept.append(row)
    return _replace_rows(shaped, kept)


def _extract_rows(shaped: Any) -> list[Any] | None:
    """Pull the row list out of a shaped result, or return ``None``."""
    if isinstance(shaped, list):
        return shaped
    if isinstance(shaped, dict):
        results = shaped.get("results")
        if isinstance(results, list):
            return results
        return None
    results = getattr(shaped, "results", None)
    if isinstance(results, list) and hasattr(shaped, "extra"):
        return results
    return None


def _replace_rows(shaped: Any, rows: list[Any]) -> Any:
    """Inverse of ``_extract_rows`` — substitute the collapsed row list back in."""
    if isinstance(shaped, list):
        return rows
    if isinstance(shaped, dict) and isinstance(shaped.get("results"), list):
        return {**shaped, "results": rows}
    if isinstance(getattr(shaped, "results", None), list) and hasattr(shaped, "extra"):
        shaped.results = rows
        return shaped
    return shaped


def _coerce_response_value(value: Any, type_name: str, fmt: str) -> Any:
    """Cast a single field value to the type declared by the response schema."""
    if not isinstance(value, str):
        return value
    if type_name in _NUMERIC_RESPONSE_TYPES:
        try:
            num = float(value)
        except ValueError:
            return value
        return int(num) if num.is_integer() else num
    if type_name == "integer":
        try:
            return int(value)
        except ValueError:
            return value
    if type_name == "boolean":
        if value.lower() in {"true", "false"}:
            return value.lower() == "true"
        return value
    if type_name == "string" and fmt == "date" and "T" in value and len(value) >= 10:
        return value.split("T", 1)[0]
    return value


def _row_column_types(cmd_spec: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """Extract ``{field_name: (type, format)}`` from a command's response schema."""
    response = cmd_spec.get("response_schema") or {}
    results = (response.get("properties") or {}).get("results") or {}
    items = results.get("items") or {}
    item_props = items.get("properties") or {}
    out: dict[str, tuple[str, str]] = {}
    for name, schema in item_props.items():
        if not isinstance(schema, dict):
            continue
        out[name] = (
            schema.get("type") or "",
            schema.get("format") or "",
        )
    return out


def _command_to_route(command: str) -> str:
    """Translate a dotted CLI command into a slash-separated route."""
    return "/" + command.replace(".", "/").strip("/")


def _row_column_metadata(cmd_spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract per-column description / format hints from the response schema."""
    response = cmd_spec.get("response_schema") or {}
    results = (response.get("properties") or {}).get("results") or {}
    items = results.get("items") or {}
    item_props = items.get("properties") or {}
    out: dict[str, dict[str, Any]] = {}
    for name, schema in item_props.items():
        if not isinstance(schema, dict):
            continue
        meta: dict[str, Any] = {}
        if schema.get("description"):
            meta["description"] = schema["description"]
        if schema.get("format"):
            meta["format"] = schema["format"]
        if schema.get("socrata_format"):
            meta["socrata_format"] = schema["socrata_format"]
        if meta:
            out[name] = meta
    return out


def _coerce_row_types(
    rows: list[dict[str, Any]], column_types: dict[str, tuple[str, str]]
) -> list[dict[str, Any]]:
    """Apply schema-driven coercion to every row in a response."""
    if not column_types:
        return rows
    coerced: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            coerced.append(row)
            continue
        new_row = {}
        for k, v in row.items():
            type_info = column_types.get(k)
            if type_info is None:
                new_row[k] = v
            else:
                new_row[k] = _coerce_response_value(v, type_info[0], type_info[1])
        coerced.append(new_row)
    return coerced


def _is_plotly_figure(payload: Any) -> bool:
    """Detect a Plotly figure-shaped payload."""
    if not isinstance(payload, dict):
        return False
    data = payload.get("data")
    layout = payload.get("layout")
    if not isinstance(data, list) or not isinstance(layout, dict):
        return False
    if not data:
        return False
    return any(
        isinstance(trace, dict) and isinstance(trace.get("type"), str) for trace in data
    )


def _wrap_plotly_figure(
    payload: dict[str, Any],
    *,
    command: str,
    params: dict[str, Any] | None,
    timestamp: datetime | None,
    duration_ns: int | None,
) -> Any:
    """Wrap a Plotly figure dict in an ``OBBject`` with ``results=figure``."""
    try:
        from openbb_core.app.model.charts.chart import Chart
        from openbb_core.app.model.metadata import Metadata
        from openbb_core.app.model.obbject import OBBject
    except ImportError:
        return payload

    extra: dict[str, Any] = {}
    if timestamp is not None and duration_ns is not None:
        with contextlib.suppress(Exception):
            extra["metadata"] = Metadata(
                arguments={
                    "provider_choices": {},
                    "standard_params": dict(params or {}),
                    "extra_params": {},
                },
                duration=duration_ns,
                route=_command_to_route(command),
                timestamp=timestamp,
            )

    return OBBject(
        results=payload,
        chart=Chart(content=payload, format="plotly"),
        extra=extra,
    )


def _shape_result(payload: Any) -> Any:
    """Apply the same envelope unwrap codegen does, then return a tidy result."""
    if not isinstance(payload, (dict, list)):
        return payload
    rows, metadata = unpack_response(payload)
    if not rows and not metadata:
        return payload
    body: Any
    if len(rows) == 1:
        sole = rows[0]
        body = sole.get("value", sole) if set(sole.keys()) == {"value"} else sole
    else:
        body = [r.get("value", r) if set(r.keys()) == {"value"} else r for r in rows]
    if metadata:
        return {"results": body, "metadata": metadata}
    return body


class HttpDispatcher:
    """Multi-tenant dispatcher backed by openbb-platform-api over HTTP."""

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
        api_prefix: str = "/api/v1",
        command_methods: dict[str, str] | None = None,
        command_url_paths: dict[str, str | list[str]] | None = None,
        headers: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
        spec_doc: dict[str, Any] | None = None,
        auth_hook: AuthHook | None = None,
        namespace: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_prefix = "/" + api_prefix.strip("/")
        self._timeout = timeout
        if client is not None:
            self._client: httpx.AsyncClient | None = client
            self._owns_client = False
        else:
            self._client = None
            self._owns_client = True
        self._command_methods = command_methods or {}
        self._command_url_paths: dict[str, list[str]] = {
            cmd: [paths] if isinstance(paths, str) else list(paths)
            for cmd, paths in (command_url_paths or {}).items()
        }
        self._headers = dict(headers) if headers else {}
        self._query_params = dict(query_params) if query_params else {}
        self._spec_doc = spec_doc or {}
        self._auth_hook = auth_hook
        self._namespace = namespace

    def _url_for(self, command: str) -> str:
        """Build the fully-qualified URL for a command, no path-param substitution."""
        path = command.replace(".", "/").strip("/")
        return f"{self._base_url}{self._api_prefix}/{path}"

    def _resolve_url(
        self, command: str, params: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Build the URL for ``command`` and split path-substituted params off.

        When multiple URL templates exist for the command (overloads merged at
        spec-build time), pick the one with the most path placeholders that are
        all satisfied by ``params``; fall back to the shortest template otherwise.
        """
        templates = self._command_url_paths.get(command)
        if not templates:
            return self._url_for(command), self._apply_param_transforms(
                command, dict(params)
            )

        ordered = sorted(templates, key=lambda t: -t.count("{"))
        chosen: str | None = None
        for template in ordered:
            placeholders = _PATH_TEMPLATE_RE.findall(template)
            if not placeholders:
                chosen = template
                break
            if all(params.get(key) not in (None, "") for key in placeholders):
                chosen = template
                break
        if chosen is None:
            chosen = ordered[-1]

        consumed: set[str] = set()

        def _substitute(match: re.Match[str]) -> str:
            key = match.group(1)
            consumed.add(key)
            value = params.get(key)
            if value is None:
                return match.group(0)
            return str(value)

        path = _PATH_TEMPLATE_RE.sub(_substitute, chosen)
        remaining = {k: v for k, v in params.items() if k not in consumed}
        return f"{self._base_url}{path}", self._apply_param_transforms(
            command, remaining
        )

    def _date_snapshot_context(self, request: Request) -> tuple[str | None, int | None]:
        """Detect the rows-from-N-most-recent-dates branch for ``limit``."""
        cmd_spec = (self._spec_doc.get("commands") or {}).get(request.command) or {}
        time_axis = cmd_spec.get("_socrata_time_axis")
        if not time_axis:
            return None, None
        raw_limit = (request.params or {}).get("limit")
        if raw_limit is None:
            return None, None
        try:
            user_limit = int(raw_limit)
        except (TypeError, ValueError):
            return None, None
        if user_limit <= 0:
            return None, None
        return time_axis, user_limit

    def _shape_and_coerce(
        self,
        command: str,
        payload: Any,
        *,
        params: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
        duration_ns: int | None = None,
    ) -> Any:
        """Unpack envelopes, coerce row types, then return a real ``OBBject``."""
        if _is_plotly_figure(payload):
            return _wrap_plotly_figure(
                payload,
                command=command,
                params=params,
                timestamp=timestamp,
                duration_ns=duration_ns,
            )
        shaped = _shape_result(payload)
        cmd_spec = (self._spec_doc.get("commands") or {}).get(command) or {}
        column_types = _row_column_types(cmd_spec)
        column_metadata = _row_column_metadata(cmd_spec)

        api_metadata: dict[str, Any] = {}
        rows: Any
        if isinstance(shaped, list):
            rows = shaped
        elif isinstance(shaped, dict):
            inner = shaped.get("results")
            if isinstance(inner, list) or inner is not None:
                rows = inner
                api_metadata = dict(shaped.get("metadata") or {})
            else:
                rows = shaped
        else:
            return shaped

        if column_types:
            if isinstance(rows, list):
                rows = _coerce_row_types(rows, column_types)
            elif isinstance(rows, dict):
                rows = _coerce_row_types([rows], column_types)[0]

        if not column_metadata and not api_metadata:
            return rows

        try:
            from openbb_core.app.model.metadata import Metadata
            from openbb_core.app.model.obbject import OBBject
        except ImportError:
            extra_fallback: dict[str, Any] = dict(api_metadata)
            if column_metadata:
                extra_fallback["results_metadata"] = {"columns": column_metadata}
            return {"results": rows, "extra": extra_fallback}

        extra: dict[str, Any] = dict(api_metadata)
        if column_metadata:
            extra["results_metadata"] = {"columns": column_metadata}

        if timestamp is not None and duration_ns is not None:
            with contextlib.suppress(Exception):
                extra["metadata"] = Metadata(
                    arguments={
                        "provider_choices": {},
                        "standard_params": dict(params or {}),
                        "extra_params": {},
                    },
                    duration=duration_ns,
                    route=_command_to_route(command),
                    timestamp=timestamp,
                )

        return OBBject(results=rows, extra=extra)

    def _apply_param_transforms(
        self, command: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Translate user-facing param names into the upstream wire form."""
        cmd_spec = (self._spec_doc.get("commands") or {}).get(command) or {}
        param_specs = cmd_spec.get("parameters") or []
        if not param_specs:
            return params
        out = dict(params)
        where_parts: list[str] = []
        for p in param_specs:
            if not isinstance(p, dict):
                continue
            op = p.get("_socrata_op")
            if op not in {"date_min", "date_max"}:
                continue
            value = out.pop(p["name"], None)
            if value is None:
                continue
            column = p.get("_socrata_column")
            if not column:
                continue
            cmp = ">=" if op == "date_min" else "<="
            where_parts.append(f"{column} {cmp} '{value}'")
        if where_parts:
            existing = out.pop("$where", None)
            joined = " AND ".join(where_parts)
            out["$where"] = f"({existing}) AND ({joined})" if existing else joined
        time_axis = cmd_spec.get("_socrata_time_axis")
        if time_axis and "$order" not in out:
            out["$order"] = f"{time_axis} DESC"
        for p in param_specs:
            if not isinstance(p, dict):
                continue
            wire = p.get("wire_name")
            name = p.get("name")
            if wire and name and wire != name and name in out:
                out[wire] = out.pop(name)
        return out

    def _method_for(self, command: str, override: str | None) -> str:
        """Resolve the HTTP method for ``command``: explicit override > map > default."""
        if override is not None:
            return override.lower()
        return self._command_methods.get(command, "post").lower()

    def _is_streaming_command(self, command: str) -> bool:
        """Return whether the command's success response is a stream."""
        cmd_spec = (self._spec_doc.get("commands") or {}).get(command) or {}
        for status, content in (cmd_spec.get("response_schemas") or {}).items():
            if (
                str(status).startswith("2")
                and isinstance(content, dict)
                and any("event-stream" in str(ct) for ct in content)
            ):
                return True
        return False

    def _partition_params(
        self, command: str, params: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Split dispatch params into ``(query, body, headers)`` by spec ``in`` tag."""
        cmd_spec = (self._spec_doc.get("commands") or {}).get(command) or {}
        locations: dict[str, tuple[str, str]] = {}
        delimiters: dict[str, str] = {}
        for p in command_parameters(cmd_spec):
            if isinstance(p, dict) and p.get("name"):
                spec_name = p["name"]
                loc = p.get("in", "query")
                delimiter = _LIST_DELIMITERS.get(p.get("list_style", "multi"))
                for key in {
                    spec_name,
                    spec_name.replace("-", "_"),
                    spec_name.replace("_", "-"),
                }:
                    locations[key] = (loc, spec_name)
                    if p.get("is_list") and delimiter:
                        delimiters[key] = delimiter
        query: dict[str, Any] = {}
        body: dict[str, Any] = {}
        headers: dict[str, Any] = {}
        for name, value in params.items():
            loc, spec_name = locations.get(name, ("body", name))
            if loc == "header":
                if value is not None:
                    headers[spec_name] = str(value)
            elif loc == "body":
                body[name] = value
            else:
                out_value = value
                if name in delimiters and isinstance(value, (list, tuple)):
                    out_value = delimiters[name].join(str(v) for v in value)
                query[name] = out_value
        return query, body, headers

    async def _invoke_auth_hook(
        self, request: Request, method_lower: str
    ) -> AuthDecision:
        """Run the configured auth hook (if any) and return its decision."""
        if self._auth_hook is None:
            return AuthDecision()
        ctx = AuthContext(
            namespace=self._namespace,
            command=request.command,
            params=dict(request.params or {}),
            method=method_lower,
        )
        try:
            result = self._auth_hook(ctx)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:  # noqa: BLE001
            return AuthDecision(allow=False, deny_reason=f"auth hook raised: {exc}")
        if not isinstance(result, AuthDecision):
            return AuthDecision(
                allow=False,
                deny_reason=(
                    f"auth hook returned {type(result).__name__}; expected AuthDecision"
                ),
            )
        return result

    async def dispatch(self, request: Request, method: str | None = None) -> Response:
        """Send ``request`` to the platform-api endpoint that maps to its command."""
        if request.command == "__commands__":
            return await self._list_commands(request)
        if request.command == "__schema__":
            return await self._describe_command(request)
        time_axis, user_limit = self._date_snapshot_context(request)
        fetch_all = _user_requested_all_rows(request)
        wire_request = request
        if time_axis is not None or fetch_all:
            wire_request = _request_with_page_size_limit(request)
        timestamp = datetime.now(timezone.utc)
        start_ns = perf_counter_ns()
        try:
            url, body_or_query = self._resolve_url(
                wire_request.command, wire_request.params or {}
            )
            method_lower = self._method_for(wire_request.command, method)
            decision = await self._invoke_auth_hook(wire_request, method_lower)
            if not decision.allow:
                return Response(
                    id=request.id,
                    ok=False,
                    error=ResponseError(
                        type="AccessDenied",
                        message=decision.deny_reason or "auth hook denied request",
                    ),
                )
            extra_query = decision.query_params or None
            query_part, body_part, header_part = self._partition_params(
                wire_request.command, body_or_query
            )
            extra_headers = {**(decision.headers or {}), **header_part} or None
            # GET carries every non-header param in the query string; only POST
            # splits the body out as JSON.
            get_query = {**query_part, **body_part}

            if self._is_streaming_command(wire_request.command):
                from openbb_core.app.model.stream import OBBStream

                if method_lower == "get":
                    merged_query = {
                        **self._query_params,
                        **(extra_query or {}),
                        **get_query,
                    }
                    stream_body: dict[str, Any] = {}
                else:
                    merged_query = {
                        **self._query_params,
                        **(extra_query or {}),
                        **query_part,
                    }
                    stream_body = body_part
                source = _HttpSSESource(
                    url, merged_query or None, extra_headers, method_lower, stream_body
                )
                return Response(
                    id=request.id, ok=True, result=OBBStream(source), error=None
                )

            async with self._client_context() as client:
                if method_lower == "get":
                    merged_query = {
                        **self._query_params,
                        **(extra_query or {}),
                        **get_query,
                    }
                    if fetch_all:
                        payload = await _fetch_all_pages(
                            client, url, merged_query, extra_headers
                        )
                    elif time_axis is not None:
                        payload = await _fetch_until_n_distinct_dates(
                            client,
                            url,
                            merged_query,
                            extra_headers,
                            time_axis,
                            user_limit or 0,
                        )
                    else:
                        response = await client.get(
                            url, params=merged_query, headers=extra_headers
                        )
                        response.raise_for_status()
                        payload = _decode_response(response)
                else:
                    merged_query = {
                        **self._query_params,
                        **(extra_query or {}),
                        **query_part,
                    }
                    response = await client.post(
                        url,
                        params=merged_query or None,
                        json=body_part,
                        headers=extra_headers,
                    )
                    response.raise_for_status()
                    payload = _decode_response(response)
            duration_ns = perf_counter_ns() - start_ns
            shaped = self._shape_and_coerce(
                wire_request.command,
                payload,
                params=request.params or {},
                timestamp=timestamp,
                duration_ns=duration_ns,
            )
            if time_axis is not None and not fetch_all:
                shaped = _truncate_to_top_n_dates(shaped, time_axis, user_limit)
            return Response(
                id=request.id,
                ok=True,
                result=shaped,
                error=None,
            )
        except httpx.HTTPStatusError as exc:
            try:
                detail = exc.response.json()
            except ValueError:
                detail = exc.response.text
            return Response(
                id=request.id,
                ok=False,
                error=ResponseError(
                    type=f"HTTP{exc.response.status_code}",
                    message=str(detail),
                ),
            )
        except httpx.RequestError as exc:
            return Response(
                id=request.id,
                ok=False,
                error=ResponseError(type=type(exc).__name__, message=str(exc)),
            )
        except Exception as exc:  # noqa: BLE001
            return Response(
                id=request.id,
                ok=False,
                error=ResponseError(type=type(exc).__name__, message=str(exc)),
            )

    async def _list_commands(self, request: Request) -> Response:
        """Return ``[{name, description}, ...]`` for every command the auth hook permits."""
        commands = self._spec_doc.get("commands", {})
        rows: list[dict[str, Any]] = []
        for name, meta in commands.items():
            if self._auth_hook is not None:
                decision = await self._invoke_auth_hook(
                    Request(command=name), method_lower="list"
                )
                if not decision.allow:
                    continue
            rows.append(
                {
                    "name": name,
                    "description": (meta.get("description") or "").split(".")[0] or "",
                }
            )
        rows.sort(key=lambda r: r["name"])
        return Response(id=request.id, ok=True, result=rows, error=None)

    async def _describe_command(self, request: Request) -> Response:
        """Return ``{name, parameters, output_schema}`` for one command."""
        name = (request.params or {}).get("name")
        if not name:
            return Response(
                id=request.id,
                ok=False,
                error=ResponseError(
                    type="MissingParameter",
                    message="__schema__ requires --name=<command>",
                ),
            )
        cmd_spec = self._spec_doc.get("commands", {}).get(name)
        if cmd_spec is None:
            return Response(
                id=request.id,
                ok=False,
                error=ResponseError(
                    type="UnknownCommand",
                    message=(
                        f"command not in spec: {name!r}. "
                        "Use __commands__ to list available commands."
                    ),
                ),
            )
        if self._auth_hook is not None:
            decision = await self._invoke_auth_hook(
                Request(command=name), method_lower="schema"
            )
            if not decision.allow:
                return Response(
                    id=request.id,
                    ok=False,
                    error=ResponseError(
                        type="AccessDenied",
                        message=decision.deny_reason or "auth hook denied describe",
                    ),
                )
        providers = cmd_spec.get("providers") or []
        if providers:
            requested_provider = (request.params or {}).get("provider")
            grouped = _group_by_provider(
                command_parameters(cmd_spec),
                providers,
                cmd_spec.get("response_schema"),
            )
            if requested_provider:
                slice_ = grouped.get(requested_provider)
                if slice_ is None:
                    return Response(
                        id=request.id,
                        ok=False,
                        error=ResponseError(
                            type="UnknownProvider",
                            message=(
                                f"provider {requested_provider!r} not declared "
                                f"by {name!r}. Available: "
                                f"{', '.join(sorted(grouped))}."
                            ),
                        ),
                    )
                return Response(
                    id=request.id,
                    ok=True,
                    result={
                        "name": name,
                        "provider": requested_provider,
                        **slice_,
                    },
                    error=None,
                )
            return Response(
                id=request.id,
                ok=True,
                result={"name": name, "providers": grouped},
                error=None,
            )
        params: list[dict[str, Any]] = [
            _slim_param(p) for p in command_parameters(cmd_spec)
        ]
        return Response(
            id=request.id,
            ok=True,
            result={
                "name": name,
                "parameters": params,
                "output_schema": cmd_spec.get("response_schema"),
            },
            error=None,
        )

    def _client_context(self):
        """Yield an ``httpx.AsyncClient`` for one dispatch."""
        from contextlib import asynccontextmanager

        owns = self._owns_client
        client_ref = self._client
        timeout = self._timeout
        headers = self._headers or None

        @asynccontextmanager
        async def _ctx():
            if owns:
                async with httpx.AsyncClient(timeout=timeout, headers=headers) as c:
                    yield c
            else:
                yield client_ref

        return _ctx()

    async def aclose(self) -> None:
        """No-op."""
        return None


def http_dispatcher_from_spec(
    spec_doc: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    query_params: dict[str, str] | None = None,
    auth_hook: AuthHook | None = None,
    namespace: str | None = None,
) -> HttpDispatcher:
    """Build an ``HttpDispatcher`` from a loaded ``.spec`` document."""
    commands = spec_doc.get("commands", {})
    methods = {cmd: meta.get("method", "post") for cmd, meta in commands.items()}
    url_paths: dict[str, str | list[str]] = {}
    for cmd, meta in commands.items():
        templates = meta.get("url_templates")
        if templates:
            url_paths[cmd] = list(templates)
        elif meta.get("url_path"):
            url_paths[cmd] = meta["url_path"]
    return HttpDispatcher(
        spec_doc["base_url"],
        api_prefix=spec_doc.get("api_prefix", "/api/v1"),
        command_methods=methods,
        command_url_paths=url_paths,
        headers={**(spec_doc.get("headers") or {}), **(headers or {})} or None,
        query_params=query_params,
        spec_doc=spec_doc,
        auth_hook=auth_hook,
        namespace=namespace,
    )


def http_dispatcher_from_server(
    base_url: str,
    *,
    headers: dict[str, str] | None = None,
    query_params: dict[str, str] | None = None,
    auth_hook: AuthHook | None = None,
    namespace: str | None = None,
) -> HttpDispatcher:
    """Build an ``HttpDispatcher`` by fetching the server's OpenAPI document."""
    from openbb_cli.dispatchers.openapi_schema import fetch_openapi
    from openbb_cli.dispatchers.spec import build_spec_document

    openapi = fetch_openapi(base_url, headers=headers, query_params=query_params)
    spec_doc = build_spec_document(openapi, base_url=base_url)
    return http_dispatcher_from_spec(
        spec_doc,
        headers=headers,
        query_params=query_params,
        auth_hook=auth_hook,
        namespace=namespace,
    )
