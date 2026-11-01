"""Pre-computed spec format for instant one-shot CLI startup."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from importlib.metadata import (
    PackageNotFoundError,
    version as _pkg_version,
)
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from openbb_cli.dispatchers.openapi_schema import (
    _escape_help,
    _provider_choices,
    _resolve_schema,
    build_reference,
    build_router_map,
    detect_api_prefix,
    extract_request_body_schema,
    extract_response_schema,
    extract_response_schemas,
    merge_allof,
    operation_parameters,
    param_provider_membership,
    parse_json_arg,
    path_item_credential_parameters,
    request_body_parameters,
    url_to_command,
)

SPEC_VERSION = 5


_TYPE_TO_NAME: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}
_NAME_TO_TYPE: dict[str, type] = {v: k for k, v in _TYPE_TO_NAME.items()}


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z?$")


def _coerce_iso_datetime(value: str) -> str:
    """Expand short date forms to RFC-3339 timestamps the upstream API expects."""
    if _DATE_RE.match(value):
        return f"{value}T00:00:00Z"
    if _DATETIME_RE.match(value) and not value.endswith("Z"):
        return value + "Z"
    return value


def _looks_like_datetime_param(name: str, help_text: str | None) -> bool:
    """Heuristic: parameter is a datetime if name or help points at one."""
    n = name.lower()
    if n.endswith("datetime") or "_datetime" in n:
        return True
    return bool(
        help_text
        and ("timestamp" in help_text.lower() or "yyyy-mm-dd" in help_text.lower())
    )


def _operation_providers(op: dict[str, Any]) -> list[str]:
    """Return the OpenBB provider list for an operation, ordered as declared."""
    for raw in op.get("parameters", []) or []:
        if not isinstance(raw, dict):
            continue
        if raw.get("name") != "provider":
            continue
        schema = raw.get("schema") or {}
        enum = schema.get("enum")
        if isinstance(enum, list):
            return [str(e) for e in enum]
        const = schema.get("const")
        if const is not None:
            return [str(const)]
    return []


_COLLECTION_FORMATS = {"csv": "csv", "multi": "multi", "ssv": "space", "pipes": "pipe"}


_DELIMITED_RE = re.compile(
    r"(?<!not )(?<!n't )\b(comma|pipe|space)[- ](?:delimited|separated)\b",
    re.IGNORECASE,
)
_DELIMITED_STYLE = {"comma": "csv", "pipe": "pipe", "space": "space"}


def _described_delimiter(description: str | None) -> str | None:
    """List style a parameter's *description* states, e.g. "(comma-delimited)".

    Many specs type such a parameter as a plain string and say in prose that it
    takes several values; the wire format is still a delimited list.
    """
    match = _DELIMITED_RE.search(description or "")
    return _DELIMITED_STYLE[match.group(1).lower()] if match else None


def _list_style(param: dict[str, Any], location: str) -> str:
    """Return how an array parameter is serialized on the wire.

    One of ``"multi"`` (``a=1&a=2``), ``"csv"`` (``a=1,2``), ``"space"``
    (``a=1 2``) or ``"pipe"`` (``a=1|2``). Follows the OpenAPI 3 ``style`` /
    ``explode`` rules (query default: ``form`` + ``explode=true``) and the
    Swagger 2 ``collectionFormat`` field.
    """
    fmt = param.get("collectionFormat")
    if fmt in _COLLECTION_FORMATS:
        return _COLLECTION_FORMATS[fmt]
    style = param.get("style")
    if style == "spaceDelimited":
        return "space"
    if style == "pipeDelimited":
        return "pipe"
    explode = param.get("explode")
    if explode is None:
        explode = (
            style or ("form" if location in ("query", "cookie") else "simple")
        ) == "form"
    return "multi" if explode and style in (None, "form") else "csv"


def _json_encoded_array(
    param: dict[str, Any], schema: dict[str, Any]
) -> dict[str, Any] | None:
    """Return the array schema of a parameter whose value is a JSON-encoded array.

    OpenAPI declares one with ``content: {application/json: {schema: ...}}`` on
    the Parameter Object, or, in JSON Schema 2019-09+ (OpenAPI 3.1), with
    ``contentMediaType: application/json`` plus ``contentSchema`` on a string.
    """
    candidates: list[Any] = []
    content = param.get("content")
    if isinstance(content, dict):
        candidates.extend(
            media.get("schema")
            for media_type, media in content.items()
            if "json" in str(media_type).lower() and isinstance(media, dict)
        )
    if "json" in str(schema.get("contentMediaType") or "").lower():
        candidates.append(schema.get("contentSchema"))
    return next(
        (
            candidate
            for candidate in candidates
            if isinstance(candidate, dict)
            and (candidate.get("type") == "array" or "items" in candidate)
        ),
        None,
    )


def _normalize_parameter(
    param: dict[str, Any], providers_set: set[str] | None = None
) -> dict[str, Any] | None:
    """Translate one OpenAPI parameter into the spec-file parameter form."""
    name = param.get("name")
    if not name or name == "chart":
        return None

    location = param.get("in", "query")
    schema = param.get("schema", {}) or {}
    json_arg = bool(param.get("_json_arg"))
    json_array = _json_encoded_array(param, schema) if location == "query" else None
    py_type, enum_choices, is_list = _resolve_schema(json_array or schema)
    described = None
    if not is_list and location in ("query", "header", "cookie"):
        described = _described_delimiter(
            param.get("description") or schema.get("description")
        )
        is_list = described is not None
    if json_arg:
        py_type, enum_choices, is_list = str, [], False
    choices: list[Any] = list(enum_choices)
    for c in _provider_choices(schema):
        if c not in choices:
            choices.append(c)

    required = bool(param.get("required")) or location == "path"
    default = schema.get("default")
    lower_choices = {str(c).lower() for c in choices}
    if (
        "json" in lower_choices
        and lower_choices & {"xml", "csv"}
        and not param.get("_no_default")
    ):
        default = "json"
    if default is not None:
        required = False

    description = param.get("description") or schema.get("description")
    providers: list[str] = (
        param_provider_membership(schema, description, providers_set)
        if providers_set and name != "provider"
        else []
    )

    example: Any = param.get("example")
    if example is None:
        examples_map = param.get("examples") or {}
        if isinstance(examples_map, dict):
            for entry in examples_map.values():
                if isinstance(entry, dict) and "value" in entry:
                    example = entry["value"]
                    break
    if example is None:
        example = schema.get("example")
    if example is None and isinstance(param.get("content"), dict):
        example = next(
            (
                media["example"]
                for media in param["content"].values()
                if isinstance(media, dict) and media.get("example") is not None
            ),
            None,
        )

    type_name = _TYPE_TO_NAME.get(py_type, "string")
    if (
        location == "path"
        and type_name == "number"
        and not re.search(r"(^|[^a-z])(lat|lon|lng|latitude|longitude)", name, re.I)
    ):
        type_name = "integer"

    if json_array is not None:
        list_style = {"list_style": "json"}
    elif is_list:
        list_style = {"list_style": described or _list_style(param, location)}
    else:
        list_style = {}
    return {
        "name": name,
        "in": location,
        "type": type_name,
        "is_list": is_list,
        **list_style,
        "required": required,
        "default": default,
        "choices": choices,
        "example": example,
        "help": param.get("description") or schema.get("description"),
        "providers": providers,
        "json_arg": json_arg,
    }


def _security_parameters(
    spec: dict[str, Any], op: dict[str, Any]
) -> list[dict[str, Any]]:
    """Materialize ``apiKey`` security schemes as optional operation parameters.

    Auth declared only through ``components.securitySchemes`` (no per-operation
    parameter) would otherwise vanish from the spec — codegen and dispatch both
    read the parameter list. Per-operation ``security`` overrides the
    document-level default, including the explicit-public ``security: []``.
    """
    requirements = op.get("security")
    if requirements is None:
        requirements = spec.get("security") or []
    schemes = (spec.get("components") or {}).get("securitySchemes") or {}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        for scheme_name in requirement:
            scheme = schemes.get(scheme_name)
            if not isinstance(scheme, dict) or scheme.get("type") != "apiKey":
                continue
            name = scheme.get("name")
            location = scheme.get("in", "query")
            if not name or name in seen or location not in ("query", "header"):
                continue
            seen.add(name)
            out.append(
                {
                    "name": name,
                    "in": location,
                    "schema": {"type": "string"},
                    "description": scheme.get("description"),
                }
            )
    return out


_GROUP_ALTERNATIVE_KEYS = frozenset({"required", "description", "title"})


def _required_groups(schema: dict[str, Any], *, required: bool) -> list[dict[str, Any]]:
    """Read the ``oneOf`` / ``anyOf`` required-property groups of an object schema.

    Each alternative must do nothing but list required properties. A
    combinator with any other kind of alternative is skipped: enforcing part
    of it would reject calls the API accepts.

    Parameters
    ----------
    schema : dict
        The object schema of a form-exploded query parameter.
    required : bool
        Whether the parameter itself is required. An optional one is only
        checked when at least one of its properties is passed.

    Returns
    -------
    list[dict]
        ``{"combinator", "alternatives", "members", "required"}`` per group;
        ``alternatives`` lists the property names each alternative requires and
        ``members`` lists every property of the object.
    """
    properties = schema.get("properties") or {}
    groups: list[dict[str, Any]] = []
    for combinator in ("oneOf", "anyOf"):
        raw_alternatives = schema.get(combinator)
        if not isinstance(raw_alternatives, list) or not raw_alternatives:
            continue
        alternatives: list[list[str]] = []
        for alternative in raw_alternatives:
            names = (
                alternative.get("required") if isinstance(alternative, dict) else None
            )
            if (
                not isinstance(names, list)
                or not names
                or set(alternative) - _GROUP_ALTERNATIVE_KEYS
                or any(not isinstance(n, str) or n not in properties for n in names)
            ):
                alternatives = []
                break
            alternatives.append(list(names))
        if alternatives:
            groups.append(
                {
                    "combinator": combinator,
                    "alternatives": alternatives,
                    "members": list(properties),
                    "required": required,
                }
            )
    return groups


def _explode_object_parameter(
    param: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Split a form-exploded object query parameter into one parameter per property.

    ``style: form`` with ``explode: true`` (the query default) sends each
    property of an object value as its own ``name=value`` pair, so each
    property is a query parameter in its own right.

    Parameters
    ----------
    param : dict
        A dereferenced OpenAPI Parameter Object.

    An optional object's own ``required`` list becomes an ``anyOf`` group that
    only applies when one of its properties is passed. Property ``default``
    values are dropped where a group must see whether the caller passed a
    value: from alternatives of a required object, and from every member of an
    optional object with groups. The server applies its own default to an
    omitted parameter.

    Returns
    -------
    tuple[list[dict], list[dict]] or None
        The per-property Parameter Objects and the object's required groups
        (see ``_required_groups``), or ``None`` when ``param`` is not a
        form-exploded object query parameter with declared properties.
    """
    if param.get("in", "query") != "query" or param.get("style", "form") != "form":
        return None
    if param.get("explode", True) is False:
        return None
    schema = merge_allof(param.get("schema"))
    if not isinstance(schema, dict):
        return None
    properties = schema.get("properties")
    schema_type = schema.get("type", "object")
    schema_types = schema_type if isinstance(schema_type, list) else [schema_type]
    if (
        not isinstance(properties, dict)
        or not properties
        or "object" not in schema_types
    ):
        return None
    param_required = bool(param.get("required"))
    declared_required = schema.get("required")
    object_required = [
        n
        for n in properties
        if isinstance(declared_required, list) and n in declared_required
    ]
    groups = _required_groups(schema, required=param_required)
    if object_required and not param_required:
        groups.append(
            {
                "combinator": "anyOf",
                "alternatives": [object_required],
                "members": list(properties),
                "required": False,
            }
        )
    if param_required:
        defaultless = {n for g in groups for alt in g["alternatives"] for n in alt}
    else:
        defaultless = set(properties) if groups else set()
    examples = _object_example(param, schema)
    exploded: list[dict[str, Any]] = []
    for name, prop_schema in properties.items():
        prop = prop_schema if isinstance(prop_schema, dict) else {}
        if name in defaultless:
            prop = {k: v for k, v in prop.items() if k != "default"}
        entry: dict[str, Any] = {
            "name": name,
            "in": "query",
            "required": param_required and name in object_required,
            "schema": prop,
        }
        if name in defaultless:
            entry["_no_default"] = True
        if name in examples:
            entry["example"] = examples[name]
        exploded.append(entry)
    return exploded, groups


def _object_example(param: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Return the first object-valued example a parameter or its schema gives.

    Looks at ``param.example``, the values of ``param.examples``, then
    ``schema.example`` and the OpenAPI 3.1 ``schema.examples`` list.
    """
    candidates: list[Any] = [param.get("example")]
    examples_map = param.get("examples")
    if isinstance(examples_map, dict):
        candidates.extend(
            entry.get("value")
            for entry in examples_map.values()
            if isinstance(entry, dict)
        )
    candidates.append(schema.get("example"))
    if isinstance(schema.get("examples"), list):
        candidates.extend(schema["examples"])
    return next((c for c in candidates if isinstance(c, dict)), {})


def _build_operation_entry(
    spec: dict[str, Any],
    url: str,
    method: str,
    op: dict[str, Any],
    path_item: dict[str, Any] | None = None,
    accept: str | None = None,
) -> dict[str, Any]:
    """Build the per-URL command entry — params, providers, schemas."""
    providers = _operation_providers(op)
    providers_set = set(providers) if providers else None
    params: list[dict[str, Any]] = []
    required_groups: list[dict[str, Any]] = []
    resolved_params = operation_parameters(spec, path_item or {}, op)
    exploded_params = [_explode_object_parameter(p) for p in resolved_params]
    taken = {
        p.get("name")
        for p, exploded in zip(resolved_params, exploded_params, strict=True)
        if exploded is None
    }
    for resolved, exploded in zip(resolved_params, exploded_params, strict=True):
        if exploded is None:
            candidates = [resolved]
        else:
            properties, groups = exploded
            candidates = [p for p in properties if p["name"] not in taken]
            skipped = {p["name"] for p in properties} - {p["name"] for p in candidates}
            taken.update(p["name"] for p in candidates)
            for group in groups:
                if skipped & {n for alt in group["alternatives"] for n in alt}:
                    continue
                members = [m for m in group["members"] if m not in skipped]
                required_groups.append({**group, "members": members})
        for candidate in candidates:
            normalized = _normalize_parameter(candidate, providers_set)
            if normalized is not None:
                params.append(normalized)
    declared = {p["name"] for p in params}
    required_groups = [
        group
        for group in required_groups
        if all(name in declared for alt in group["alternatives"] for name in alt)
    ]
    # A required header/cookie the path item declares for every operation (a
    # tenant id, a session cookie) isn't a per-call argument — it routes through
    # credentials.classify_parameter, same as an apiKey security scheme.
    for resolved in path_item_credential_parameters(spec, path_item or {}):
        if resolved["name"] in declared:
            continue
        normalized = _normalize_parameter(resolved, providers_set)
        if normalized is not None:
            params.append(normalized)
            declared.add(normalized["name"])
    for raw in _security_parameters(spec, op):
        if raw["name"] in declared:
            continue
        normalized = _normalize_parameter(raw)
        if normalized is not None:
            params.append(normalized)
    return {
        "url_path": url,
        "method": method,
        "description": (op.get("description") or op.get("summary") or "").strip(),
        "parameters": params,
        **({"required_groups": required_groups} if required_groups else {}),
        "providers": providers,
        "request_body_schema": extract_request_body_schema(spec, op),
        "response_schema": extract_response_schema(spec, op, accept),
        "response_schemas": extract_response_schemas(spec, op),
    }


def _merge_overload_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge URL overloads (same dotted name) into a single command entry.

    Each variant URL is recorded in ``url_templates`` (sorted by path-placeholder
    count, descending). All path params become optional on the merged command —
    the dispatcher picks the longest URL template whose placeholders are
    satisfied at call time. Query-/body- params are unioned by name; ``required``
    holds only when the param is required in every variant where it appears.
    Required groups are unioned the same way: one that is missing from, or
    optional in, any variant is only checked when its members are passed.
    ``template_response_schemas`` keeps the response schema of each variant
    whose schema differs from the shortest URL's. ``template_query_params``
    records the query parameters each variant declares, so a call can drop the ones its URL does not take and a variant
    can take another variant's placeholder as a query parameter
    (``/sigmets?date=`` beside ``/sigmets/{atsu}/{date}``).
    """
    entries = sorted(entries, key=lambda e: -_count_path_placeholders(e["url_path"]))
    base = entries[-1]
    by_name: dict[str, dict[str, Any]] = {}
    seen_in_count: dict[str, int] = {}
    required_everywhere: dict[str, bool] = {}
    for entry in entries:
        for p in entry["parameters"]:
            name = p["name"]
            seen_in_count[name] = seen_in_count.get(name, 0) + 1
            required_everywhere[name] = required_everywhere.get(name, True) and bool(
                p.get("required")
            )
            merged = by_name.setdefault(name, dict(p))
            if not merged.get("help") and p.get("help"):
                merged["help"] = p["help"]
            if not merged.get("choices") and p.get("choices"):
                merged["choices"] = list(p["choices"])
            if merged.get("default") is None and p.get("default") is not None:
                merged["default"] = p["default"]
            if merged.get("example") is None and p.get("example") is not None:
                merged["example"] = p["example"]
    total_entries = len(entries)
    merged_params: list[dict[str, Any]] = []
    for name, merged in by_name.items():
        if seen_in_count[name] < total_entries or not required_everywhere[name]:
            merged["required"] = False
        merged_params.append(merged)
    groups_by_key: dict[str, dict[str, Any]] = {}
    group_counts: dict[str, int] = {}
    for entry in entries:
        for group in entry.get("required_groups") or []:
            key = json.dumps(
                {k: v for k, v in group.items() if k != "required"}, sort_keys=True
            )
            merged_group = groups_by_key.setdefault(key, dict(group))
            merged_group["required"] = merged_group["required"] and group["required"]
            group_counts[key] = group_counts.get(key, 0) + 1
    required_groups: list[dict[str, Any]] = []
    for key, merged_group in groups_by_key.items():
        if group_counts[key] < total_entries:
            merged_group["required"] = False
        required_groups.append(merged_group)
    template_response_schemas = {
        entry["url_path"]: entry.get("response_schema")
        for entry in entries
        if entry.get("response_schema") != base.get("response_schema")
    }
    template_query_params = {
        entry["url_path"]: [
            p["name"] for p in entry["parameters"] if p.get("in") == "query"
        ]
        for entry in entries
    }
    description = next(
        (entry.get("description") for entry in entries if entry.get("description")),
        "",
    )
    return {
        "url_path": base["url_path"],
        "url_templates": [entry["url_path"] for entry in entries],
        "template_query_params": template_query_params,
        "method": base["method"],
        "description": description,
        "parameters": merged_params,
        **({"required_groups": required_groups} if required_groups else {}),
        "providers": base.get("providers", []),
        "request_body_schema": base.get("request_body_schema"),
        "response_schema": base.get("response_schema"),
        **(
            {"template_response_schemas": template_response_schemas}
            if template_response_schemas
            else {}
        ),
        "response_schemas": base.get("response_schemas"),
    }


def _count_path_placeholders(url: str) -> int:
    """Count ``{placeholder}`` occurrences in a URL template."""
    return url.count("{")


_BODY_DOC_KEYS = frozenset({"description", "example", "examples", "title"})


def _body_shape(schema: Any) -> Any:
    """Return a request body schema without docs and with ``required`` sorted."""
    if isinstance(schema, list):
        return [_body_shape(v) for v in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in ("properties", "patternProperties") and isinstance(value, dict):
            out[key] = {name: _body_shape(sub) for name, sub in value.items()}
        elif key == "required" and isinstance(value, list):
            out[key] = sorted(map(str, value))
        elif key not in _BODY_DOC_KEYS:
            out[key] = _body_shape(value)
    return out


def build_command_spec(
    spec: dict[str, Any], *, api_prefix: str = "/api/v1", accept: str | None = None
) -> dict[str, dict[str, Any]]:
    """Return ``{dotted_command: {url_path, method, description, parameters[]}}``.

    URLs that strip to the same dotted command (e.g. ``/x/{a}`` and
    ``/x/{a}/{b}``) are merged into a single command entry whose
    ``url_templates`` lists every variant. The dispatcher picks the longest
    fully-satisfied template at call time. GET operations merge with each
    other; POST operations merge only when they take the same request body
    (descriptions, examples and titles aside).
    When a name has GET operations, the GET command keeps it and each POST
    command becomes ``<name>_post``; further POST commands of that name, or a
    ``<name>_post`` another URL already takes, get a number
    (``<name>_post2``).
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for url, methods in spec.get("paths", {}).items():
        base_cmd = url_to_command(url, api_prefix=api_prefix)
        if not base_cmd:
            continue
        for method in ("get", "post"):
            if method in methods:
                groups.setdefault(base_cmd, []).append(
                    _build_operation_entry(
                        spec, url, method, methods[method], methods, accept
                    )
                )
    taken = set(groups)
    split: dict[str, list[dict[str, Any]]] = {}
    for cmd, entries in groups.items():
        buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for entry in entries:
            body = (
                ""
                if entry["method"] == "get"
                else json.dumps(
                    _body_shape(entry.get("request_body_schema")),
                    sort_keys=True,
                    default=str,
                )
            )
            buckets.setdefault((entry["method"], body), []).append(entry)
        keeps_name = next(
            (key for key in buckets if key[0] == "get"), next(iter(buckets))
        )
        for key, bucket in buckets.items():
            if key == keeps_name:
                name = cmd
            else:
                name, number = f"{cmd}_{key[0]}", 2
                while name in taken:
                    name, number = f"{cmd}_{key[0]}{number}", number + 1
                taken.add(name)
            split[name] = bucket
    out: dict[str, dict[str, Any]] = {}
    for cmd, entries in split.items():
        out[cmd] = entries[0] if len(entries) == 1 else _merge_overload_entries(entries)
    return out


def unnamed_paths(openapi: dict[str, Any], *, api_prefix: str) -> list[str]:
    """Return the GET/POST paths that stripping ``api_prefix`` leaves without a name.

    A path equal to the prefix, or the prefix plus only placeholders, strips
    to an empty name, so no command is built for it. Paths that have no name
    even unstripped (``/``, ``/{id}``) are not listed.
    """
    return [
        url
        for url, methods in (openapi.get("paths") or {}).items()
        if isinstance(methods, dict)
        and ("get" in methods or "post" in methods)
        and not url_to_command(url, api_prefix=api_prefix)
        and url_to_command(url, api_prefix="")
    ]


def _resolve_base_url(openapi: dict[str, Any], user_base_url: str) -> str:
    """Honor the OpenAPI ``servers[0].url`` when it adds a path component."""
    user_clean = user_base_url.rstrip("/")
    servers = openapi.get("servers") or []
    if not servers or not isinstance(servers[0], dict):
        return user_clean
    server_url = (servers[0].get("url") or "").strip()
    if not server_url:
        return user_clean
    if server_url.startswith(("http://", "https://")):
        from urllib.parse import urlsplit

        if urlsplit(user_clean).path in ("", "/"):
            return server_url.rstrip("/")
        return user_clean
    server_path = "/" + server_url.strip("/")
    if user_clean.endswith(server_path):
        return user_clean
    return user_clean + server_path


def _generator_identifier() -> str:
    """Return ``"openbb-cli==<version>"`` or just the name when unresolved."""
    try:
        return f"openbb-cli=={_pkg_version('openbb-cli')}"
    except PackageNotFoundError:
        return "openbb-cli"


def build_spec_document(
    openapi: dict[str, Any],
    *,
    base_url: str,
    api_prefix: str | None = None,
    source_url: str | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the on-disk spec dict from a fetched OpenAPI document.

    Non-credential ``headers`` (from ``--header``) are recorded in the spec and
    applied to every request; header parameters of the same name are dropped
    from each command so they are not surfaced as arguments. Credential headers
    (``API-Key``, ``Authorization``, ...) are left alone: the credential
    detection maps them to the generated ``Credentials`` objects.

    ``api_prefix`` overrides the prefix stripped from paths when naming
    commands; paths outside it keep their full name. The recorded
    ``api_prefix`` stays the prefix every path shares, so URLs resolve the
    same either way.
    """
    detected_prefix = detect_api_prefix(openapi)
    effective_prefix = api_prefix if api_prefix is not None else detected_prefix
    accept = next(
        (v for k, v in (headers or {}).items() if k.lower() == "accept"), None
    )
    commands = build_command_spec(openapi, api_prefix=effective_prefix, accept=accept)
    headers = _fixed_headers(commands, headers)
    if headers:
        _strip_fixed_headers(commands, headers)
    doc = {
        "version": SPEC_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": _generator_identifier(),
        "source_url": source_url or "",
        "api_version": str(openapi.get("openapi") or openapi.get("swagger") or ""),
        "base_url": _resolve_base_url(openapi, base_url),
        "api_prefix": (("/" + detected_prefix.strip("/")) if detected_prefix else ""),
        "commands": commands,
        "routers": build_router_map(openapi, api_prefix=effective_prefix),
        "reference": build_reference(openapi, api_prefix=effective_prefix),
    }
    for name, command in commands.items():
        path = "/" + name.replace(".", "/")
        if name not in doc["routers"]:
            doc["routers"][name] = "command"
        elif (
            command.get("method") == "get"
            or f"{name}_post" not in commands
            or path not in doc["reference"]["paths"]
        ):
            continue
        doc["reference"].setdefault("paths", {})[path] = {
            "description": command.get("description") or ""
        }
    if headers:
        doc["headers"] = dict(headers)
    return doc


def _fixed_headers(
    commands: dict[str, dict[str, Any]], headers: dict[str, str] | None
) -> dict[str, str]:
    """Return the ``--header`` entries that are not credentials."""
    from openbb_cli.codegen.credentials import (
        classify_parameter,
        is_credential_name,
        normalize_credential_key,
    )

    credential_headers = {
        normalize_credential_key(prm["name"])
        for cmd in commands.values()
        for prm in cmd.get("parameters") or []
        if prm.get("in") == "header" and classify_parameter(prm) is not None
    }
    return {
        k: v
        for k, v in (headers or {}).items()
        if not is_credential_name(k)
        and normalize_credential_key(k) not in credential_headers
    }


def _strip_fixed_headers(
    commands: dict[str, dict[str, Any]], headers: dict[str, str]
) -> None:
    """Remove header parameters supplied by ``headers`` (case-insensitive)."""
    fixed = {k.lower() for k in headers}
    for cmd in commands.values():
        cmd["parameters"] = [
            prm
            for prm in cmd.get("parameters") or []
            if not (prm.get("in") == "header" and str(prm.get("name")).lower() in fixed)
        ]


def _content_hash(spec_doc: dict[str, Any]) -> str:
    """Hash the spec doc deterministically, ignoring any existing hash field."""
    payload = {k: v for k, v in spec_doc.items() if k != "content_sha256"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def write_spec(path: str | Path, spec_doc: dict[str, Any]) -> None:
    """Write the spec doc to ``path`` as compact JSON, stamped with its SHA-256."""
    spec_doc["content_sha256"] = _content_hash(spec_doc)
    Path(path).write_text(json.dumps(spec_doc, separators=(",", ":")))


class _CommandParameter(BaseModel):
    """One parameter inside a command's ``parameters`` list."""

    model_config = ConfigDict(extra="allow")

    name: str
    in_: str = Field(default="query", alias="in")
    type: str = "string"
    is_list: bool = False
    required: bool = False
    default: Any = None
    choices: list[Any] = Field(default_factory=list)
    example: Any = None
    help: str | None = None
    providers: list[str] = Field(default_factory=list)
    json_arg: bool = False


class _CommandSpec(BaseModel):
    """One entry in ``spec["commands"]`` keyed by dotted command path."""

    model_config = ConfigDict(extra="allow")

    url_path: str
    url_templates: list[str] | None = None
    method: str
    description: str | None = None
    parameters: list[_CommandParameter] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)
    request_body_schema: dict[str, Any] | None = None
    response_schema: dict[str, Any] | None = None


class SpecDocument(BaseModel):
    """The on-disk shape of a ``.spec`` file."""

    model_config = ConfigDict(extra="allow")

    version: int
    base_url: str
    api_prefix: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    commands: dict[str, _CommandSpec]
    routers: dict[str, Any] = Field(default_factory=dict)
    reference: dict[str, Any] = Field(default_factory=dict)
    generated_at: str | None = None
    generator: str | None = None
    source_url: str | None = None
    api_version: str | None = None
    content_sha256: str | None = None


def load_spec(path: str | Path) -> dict[str, Any]:
    """Load and validate a spec doc; reject incompatible versions early."""
    spec_doc = json.loads(Path(path).read_text())
    version = spec_doc.get("version")
    if version != SPEC_VERSION:
        raise ValueError(
            f"Spec file at {path} has version {version!r}; expected {SPEC_VERSION}. "
            f"Regenerate with: openbb --server <URL> --generate-spec --output {path}"
        )
    try:
        SpecDocument.model_validate(spec_doc)
    except ValidationError as exc:
        raise ValueError(
            f"Spec file at {path} does not conform to the expected schema:\n{exc}"
        ) from exc
    recorded_hash = spec_doc.get("content_sha256")
    if recorded_hash is not None:
        actual_hash = _content_hash(spec_doc)
        if recorded_hash != actual_hash:
            raise ValueError(
                f"Spec file at {path} failed integrity check: "
                f"recorded SHA-256 {recorded_hash!r} does not match recomputed "
                f"{actual_hash!r}. The file has been modified since it was generated."
            )
    return spec_doc


def command_parameters(cmd_spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a command's full input surface: query/path params fused with body."""
    params = list(cmd_spec.get("parameters") or [])
    for body_param in request_body_parameters(cmd_spec.get("request_body_schema")):
        normalized = _normalize_parameter(body_param)
        if normalized is not None:
            params.append(normalized)
    return params


def parser_from_command_spec(
    cmd_spec: dict[str, Any],
    prog: str | None = None,
    *,
    selected_provider: str | None = None,
) -> argparse.ArgumentParser:
    """Build an ArgumentParser from one entry in ``spec["commands"]``."""
    fallback_prog = cmd_spec.get("url_path", "cmd").rsplit("/", 1)[-1] or "cmd"
    parser = argparse.ArgumentParser(
        prog=prog or fallback_prog,
        description=cmd_spec.get("description") or None,
        formatter_class=argparse.RawTextHelpFormatter,
        add_help=False,
    )
    required_group = parser.add_argument_group("required arguments")
    optional_group = parser.add_argument_group("optional arguments")
    group_members = {
        name
        for group in cmd_spec.get("required_groups") or []
        for name in group.get("members") or []
    }
    for p in command_parameters(cmd_spec):
        if not _param_visible_for_provider(p, selected_provider):
            continue
        target = required_group if p.get("required") else optional_group
        try:
            _add_normalized_parameter(
                target, p, unset_when_omitted=p.get("name") in group_members
            )
        except argparse.ArgumentError:
            continue
    return parser


def _param_visible_for_provider(
    p: dict[str, Any], selected_provider: str | None
) -> bool:
    """Whether a normalized parameter belongs in the parser for ``selected_provider``."""
    if selected_provider is None or p.get("name") == "provider":
        return True
    tags = p.get("providers") or []
    return not tags or selected_provider in tags


def _add_normalized_parameter(
    parser: argparse._ActionsContainer,
    p: dict[str, Any],
    *,
    unset_when_omitted: bool = False,
) -> None:
    """Translate one normalized parameter dict into a parser argument.

    ``unset_when_omitted`` leaves an omitted boolean flag without a value
    instead of ``False``, so a required group can tell it was not passed.
    """
    flag = f"--{p['name']}"
    py_type = _NAME_TO_TYPE.get(p.get("type", "string"), str)
    kwargs: dict[str, Any] = {"dest": p["name"], "help": _escape_help(p.get("help"))}

    if p.get("json_arg"):
        kwargs["type"] = parse_json_arg
        if p.get("required"):
            kwargs["required"] = True
        parser.add_argument(flag, **kwargs)
        return

    if py_type is bool:
        default = p.get("default")
        kwargs.update(
            action=argparse.BooleanOptionalAction,
            default=(
                None
                if default is None and unset_when_omitted
                else bool(default or False)
            ),
        )
        parser.add_argument(flag, **kwargs)
        return

    is_socrata_range_param = p.get("_socrata_op") in {"date_min", "date_max"}
    if (
        py_type is str
        and not is_socrata_range_param
        and _looks_like_datetime_param(p["name"], p.get("help"))
    ):
        kwargs["type"] = _coerce_iso_datetime
    else:
        kwargs["type"] = py_type
    if p.get("default") is not None:
        kwargs["default"] = p["default"]
    if p.get("choices") and p.get("list_style") != "json":
        kwargs["choices"] = list(p["choices"])
    if p.get("is_list"):
        kwargs["nargs"] = "+"
    if p.get("required") and "default" not in kwargs:
        kwargs["required"] = True
    parser.add_argument(flag, **kwargs)


class SpecCommandError(KeyError):
    """Raised when a dotted command path is not present in the spec."""


def parse_command_argv(
    spec_doc: dict[str, Any], argv: list[str]
) -> tuple[str, dict[str, Any]]:
    """Resolve ``argv`` against ``spec_doc['commands']`` → (command, params)."""
    if not argv:
        raise SpecCommandError(
            "missing command — usage: openbb --spec PATH <command.path> [--key value]"
        )
    command, rest = argv[0], list(argv[1:])
    cmd_spec = spec_doc.get("commands", {}).get(command)
    if cmd_spec is None:
        raise SpecCommandError(f"command not in spec: {command!r}")
    selected_provider = _peek_provider(cmd_spec, rest)
    parser = parser_from_command_spec(cmd_spec, selected_provider=selected_provider)
    ns = parser.parse_args(rest)
    params = {k: v for k, v in vars(ns).items() if v is not None}
    return command, params


def _peek_provider(cmd_spec: dict[str, Any], argv: list[str]) -> str | None:
    """Run a minimal first-pass parser to extract ``--provider`` from ``argv``."""
    providers = cmd_spec.get("providers") or []
    if not providers:
        return None
    peek = argparse.ArgumentParser(add_help=False)
    peek.add_argument("--provider", choices=list(providers))
    try:
        ns, _ = peek.parse_known_args(argv)
    except SystemExit:
        return None
    return getattr(ns, "provider", None)
