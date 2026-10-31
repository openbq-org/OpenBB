"""Build CLI menu / parser structures from an OpenAPI 3.x schema."""

from __future__ import annotations

import argparse
import json
import re
from typing import Any, NoReturn
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

import httpx

_INHERITABLE_PARAMETER_LOCATIONS = frozenset({"path", "query"})

PROVIDER_TAG_RE = re.compile(r"\s*\(provider:\s*([^)]+)\)\s*$")
PROVIDER_SECTION_SPLIT_RE = re.compile(r";\s*\n\s*")


def parse_provider_sections(text: str) -> tuple[set[str], bool]:
    """Split an OpenBB-merged help string into ``(tagged_providers, has_untagged)``."""
    tagged: set[str] = set()
    has_untagged = False
    for raw_section in PROVIDER_SECTION_SPLIT_RE.split(text):
        section = raw_section.strip()
        if not section:
            continue
        match = PROVIDER_TAG_RE.search(section)
        if match is None:
            has_untagged = True
            continue
        for p in match.group(1).split(","):
            name = p.strip().lower()
            if name:
                tagged.add(name)
    return tagged, has_untagged


def param_provider_membership(
    schema: dict[str, Any],
    description: str | None,
    providers_set: set[str],
) -> list[str]:
    """Return the providers a parameter belongs to, or ``[]`` if shared by all."""
    providers_lower = {p.lower(): p for p in providers_set}
    if description:
        tagged, has_untagged = parse_provider_sections(description)
        if has_untagged:
            return []
        if tagged:
            return [providers_lower[t] for t in tagged if t in providers_lower]
    keys = [
        k
        for k, v in schema.items()
        if k in providers_set
        and k not in _OPENAPI_RESERVED_SCHEMA_KEYS
        and isinstance(v, dict)
    ]
    if keys:
        return keys
    title = schema.get("title")
    if isinstance(title, str) and title.lower() in providers_lower:
        return [providers_lower[title.lower()]]
    return []


_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}

_OPENAPI_RESERVED_SCHEMA_KEYS = frozenset(
    {
        "type",
        "format",
        "title",
        "description",
        "default",
        "enum",
        "const",
        "anyOf",
        "oneOf",
        "allOf",
        "items",
        "properties",
        "additionalProperties",
        "required",
        "nullable",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "pattern",
    }
)


def resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    """Resolve a local OpenAPI ``$ref`` JSON pointer against ``spec``."""
    if not ref.startswith("#/"):
        return {}
    node: Any = spec
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return {}
        node = node[part]
    return node if isinstance(node, dict) else {}


def deref_parameter(spec: dict[str, Any], param: dict[str, Any]) -> dict[str, Any]:
    """Resolve a parameter that may be a ``$ref``."""
    seen: set[str] = set()
    while "$ref" in param:
        ref = param["$ref"]
        if ref in seen:
            return {}
        seen.add(ref)
        param = resolve_ref(spec, ref) or {}
    schema = param.get("schema")
    if isinstance(schema, dict):
        param = {**param, "schema": deref_schema(spec, schema)}
    return param


def operation_parameters(
    spec: dict[str, Any], path_item: dict[str, Any], op: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return an operation's parameters, including those inherited from its path item.

    OpenAPI 3.x lets a Path Item Object declare ``parameters`` that apply to every
    operation under that path. An operation-level parameter overrides an inherited
    one when both match on ``(name, in)``; anything else is inherited as-is.

    Only ``in: path`` and ``in: query`` are inherited. A path-item ``in: header``
    or ``in: cookie`` entry is deliberately dropped: those do not translate into a
    Python interface function, and outbound headers belong to transport
    configuration (``SystemSettings.PythonSettings.http.headers``, the CLI's
    ``-H``) or to security-scheme handling — not to a per-command argument.

    Entries are returned dereferenced, inherited first, then the operation's own.
    """
    inherited = path_item.get("parameters") or []
    own_raw = op.get("parameters") or []
    own = [deref_parameter(spec, p) for p in own_raw if isinstance(p, dict)]
    own = [p for p in own if p]
    if not inherited:
        return own
    overridden = {(p.get("name"), p.get("in")) for p in own}
    merged: list[dict[str, Any]] = []
    for raw in inherited:
        if not isinstance(raw, dict):
            continue
        resolved = deref_parameter(spec, raw)
        if not resolved or not resolved.get("name"):
            continue
        if resolved.get("in") not in _INHERITABLE_PARAMETER_LOCATIONS:
            continue
        if (resolved.get("name"), resolved.get("in")) in overridden:
            continue
        merged.append(resolved)
    merged.extend(own)
    return merged


def path_item_credential_parameters(
    spec: dict[str, Any], path_item: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return the path item's required ``header``/``cookie`` parameters, dereferenced.

    These are exactly what :func:`operation_parameters` drops: a value every
    operation under the path needs (a tenant id, a session cookie) that isn't a
    per-call argument. They're a per-integration secret, not different per
    request, so they route through ``openbb_cli.codegen.credentials`` the same
    way an ``apiKey`` security scheme does, rather than becoming a required
    argument the caller has to supply on every command.

    A path-item parameter that is optional is left for the caller to notice —
    only a required one is dead-on-arrival without this.
    """
    out: list[dict[str, Any]] = []
    for raw in path_item.get("parameters") or []:
        if not isinstance(raw, dict):
            continue
        resolved = deref_parameter(spec, raw)
        if not resolved or not resolved.get("name"):
            continue
        if resolved.get("in") not in ("header", "cookie"):
            continue
        if not resolved.get("required"):
            continue
        out.append(resolved)
    return out


_NON_SCHEMA_KEYWORDS = frozenset({"default", "example", "examples", "enum", "const"})


def deref_schema(
    spec: dict[str, Any],
    node: Any,
    seen: frozenset[str] | None = None,
    max_depth: int = 32,
) -> Any:
    """Recursively expand every ``$ref`` inside an OpenAPI schema fragment."""
    if max_depth <= 0:
        return node
    if seen is None:
        seen = frozenset()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            if ref in seen:
                return {"$ref": ref}
            target = resolve_ref(spec, ref)
            if not target:
                return node
            return deref_schema(spec, target, seen | {ref}, max_depth - 1)
        # Instance data (``default``, ``example(s)``, ``enum``, ``const``) and
        # vendor extensions are not subschemas: a ``$ref`` key inside one is a
        # literal value, not a reference to resolve.
        return {
            k: (
                v
                if k in _NON_SCHEMA_KEYWORDS or k.startswith("x-")
                else deref_schema(spec, v, seen, max_depth - 1)
            )
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [deref_schema(spec, v, seen, max_depth - 1) for v in node]
    return node


_ALLOF_BLOCKING_KEYS = frozenset(
    {"oneOf", "anyOf", "allOf", "not", "$ref", "enum", "const", "items"}
)


def _mergeable_allof_members(members: list[Any]) -> list[dict[str, Any]] | None:
    """Return the members if every one is a plain object subschema, else ``None``.

    A member is not mergeable when it carries its own combinator (``oneOf`` /
    ``anyOf`` / a nested ``allOf`` that did not collapse), an unresolved
    ``$ref`` left behind by a reference cycle, a scalar constraint (``enum`` /
    ``const`` / ``items``), or a ``type`` other than ``object``. Any of those
    means the composition is not a plain intersection of property bags, and
    merging it would describe something the spec does not.

    Everything else is annotation that does not affect the intersection —
    ``title``, ``description``, ``examples``, ``definitions``, vendor ``x-``
    keys — and does not block the merge. Keying off a blocklist rather than a
    whitelist matters: Codat's ``PagingInfo`` carries ``definitions``, and
    treating that as disqualifying left the composition unmerged.
    """
    out: list[dict[str, Any]] = []
    for member in members:
        if not isinstance(member, dict):
            return None
        if member.keys() & _ALLOF_BLOCKING_KEYS:
            return None
        declared = member.get("type")
        if declared is not None and declared != "object":
            return None
        out.append(member)
    return out


def merge_allof(node: Any, max_depth: int = 32) -> Any:
    """Collapse ``allOf`` compositions of object subschemas into one object schema.

    An ``allOf`` is an intersection: the instance must satisfy every member. A
    consumer reading ``properties`` off the composition itself finds nothing,
    because the properties live one level down inside the members. This merges
    them into a single object schema so the composition can be read like any
    other object.

    ``properties`` are unioned, with the first member to declare a name winning
    on conflict, and any sibling ``properties`` on the ``allOf`` node itself
    taking precedence over all members. ``required`` is unioned. Compositions
    that are not a plain intersection of object subschemas are returned
    unchanged.
    """
    if max_depth <= 0:
        return node
    if isinstance(node, list):
        return [merge_allof(v, max_depth - 1) for v in node]
    if not isinstance(node, dict):
        return node

    # ``default``, ``example(s)``, ``enum`` and ``const`` hold instance data, not
    # subschemas, and a vendor extension can hold anything. Recursing into them
    # would rewrite a value that merely happens to contain an ``allOf`` key —
    # a default of ``{"allOf": [...]}`` came back as ``{"type": "object"}``.
    node = {
        k: (
            v
            if k in _NON_SCHEMA_KEYWORDS or k.startswith("x-")
            else merge_allof(v, max_depth - 1)
        )
        for k, v in node.items()
    }

    members = node.get("allOf")
    if not isinstance(members, list) or not members:
        return node

    mergeable = _mergeable_allof_members(members)
    if mergeable is None:
        return node

    properties: dict[str, Any] = {}
    required: list[str] = []
    for member in mergeable:
        for name, subschema in (member.get("properties") or {}).items():
            properties.setdefault(name, subschema)
        for name in member.get("required") or []:
            if name not in required:
                required.append(name)

    siblings = {k: v for k, v in node.items() if k != "allOf"}
    # Keywords written next to the ``allOf`` describe the composition itself and
    # outrank anything the members declare.
    for name, subschema in (siblings.get("properties") or {}).items():
        properties[name] = subschema
    for name in siblings.get("required") or []:
        if name not in required:
            required.append(name)

    merged: dict[str, Any] = {**siblings, "type": "object"}
    if properties:
        merged["properties"] = properties
    if required:
        merged["required"] = required
    return merged


_SUCCESS_PRIORITY = ("200", "2XX", "201", "default")
_JSON_CONTENT_TYPES = ("application/json", "application/vnd.api+json")


def _deref_response(spec: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    if "$ref" in response:
        return resolve_ref(spec, response["$ref"]) or {}
    return response


def _accepted_content_types(accept: str | None) -> list[str]:
    """Media types from an ``Accept`` header value, in the order given."""
    return [
        part.split(";")[0].strip().lower()
        for part in (accept or "").split(",")
        if part.split(";")[0].strip()
    ]


def extract_response_schema(
    spec: dict[str, Any], operation: dict[str, Any], accept: str | None = None
) -> dict[str, Any] | None:
    """Pull the primary success-response JSON schema for an operation.

    When ``accept`` (an ``Accept`` header sent with every request) names a
    media type the response declares, that schema is used, since it is the
    shape the server will actually return.
    """
    responses = operation.get("responses") or {}
    response: dict[str, Any] | None = None
    # Success responses only. ``default`` is the catch-all for *errors* whenever
    # the operation declares any explicit status code, so it only counts when it
    # is the operation's sole response; a 4xx/5xx schema is never a row model.
    success = [
        k
        for k in responses
        if str(k).upper() in _SUCCESS_PRIORITY[:-1] or str(k).startswith("2")
    ]
    candidates = sorted(
        success,
        key=lambda k: (
            _SUCCESS_PRIORITY.index(str(k).upper())
            if str(k).upper() in _SUCCESS_PRIORITY
            else len(_SUCCESS_PRIORITY)
        ),
    )
    if not candidates and set(responses) == {"default"}:
        candidates = ["default"]
    for key in candidates:
        candidate = responses.get(key)
        if isinstance(candidate, dict):
            response = _deref_response(spec, candidate)
            break
    if response is None:
        return None
    content = response.get("content") or {}
    media: dict[str, Any] | None = None
    for ct in [*_accepted_content_types(accept), *_JSON_CONTENT_TYPES]:
        candidate = content.get(ct)
        if isinstance(candidate, dict):
            media = candidate
            break
    if media is None:
        for value in content.values():
            if isinstance(value, dict) and "schema" in value:
                media = value
                break
    if media is None:
        return None
    schema = media.get("schema")
    if not isinstance(schema, dict):
        return None
    return merge_allof(deref_schema(spec, schema))


def extract_request_body_schema(
    spec: dict[str, Any], operation: dict[str, Any]
) -> dict[str, Any] | None:
    """Pull the primary request-body JSON schema for an operation."""
    rb = operation.get("requestBody")
    if not isinstance(rb, dict):
        return None
    if "$ref" in rb:
        rb = resolve_ref(spec, rb["$ref"]) or {}
    content = rb.get("content") or {}
    media: dict[str, Any] | None = None
    for ct in _JSON_CONTENT_TYPES:
        candidate = content.get(ct)
        if isinstance(candidate, dict):
            media = candidate
            break
    if media is None:
        for value in content.values():
            if isinstance(value, dict) and "schema" in value:
                media = value
                break
    if media is None:
        return None
    schema = media.get("schema")
    if not isinstance(schema, dict):
        return None
    return merge_allof(deref_schema(spec, schema))


def extract_response_schemas(
    spec: dict[str, Any], operation: dict[str, Any]
) -> dict[str, dict[str, dict[str, Any]]]:
    """Return every response schema as ``{status_code: {content_type: schema}}``."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    responses = operation.get("responses") or {}
    for status, response in responses.items():
        if not isinstance(response, dict):
            continue
        deref_resp = _deref_response(spec, response)
        content = deref_resp.get("content") or {}
        per_content: dict[str, dict[str, Any]] = {}
        for content_type, media in content.items():
            if not isinstance(media, dict):
                continue
            schema = media.get("schema")
            if isinstance(schema, dict):
                per_content[content_type] = merge_allof(deref_schema(spec, schema))
        if per_content:
            out[status] = per_content
    return out


def _resolve_schema(schema: dict[str, Any]) -> tuple[type, list[Any], bool]:
    """Resolve an OpenAPI parameter schema to ``(py_type, choices, is_list)``."""
    combinator = "anyOf" if "anyOf" in schema else "oneOf" if "oneOf" in schema else ""
    if combinator:
        non_null = [s for s in schema[combinator] if s.get("type") != "null"]
        if not non_null:
            return (str, [], False)
        if len(non_null) == 1:
            return _resolve_schema(non_null[0])
        choices: list[Any] = []
        is_list = False
        for s in non_null:
            schema_type = s.get("type")
            if schema_type == "array" or (
                isinstance(schema_type, list) and "array" in schema_type
            ):
                is_list = True
            for v in s.get("enum", []):
                if v not in choices:
                    choices.append(v)
        return (str, choices, is_list)

    schema_type = schema.get("type", "string")
    schema_types = schema_type if isinstance(schema_type, list) else [schema_type]
    if "array" in schema_types:
        items = schema.get("items", {}) or {}
        py_type, item_choices, _ = _resolve_schema(items)
        return (py_type, item_choices, True)

    if "const" in schema:
        return (type(schema["const"]), [schema["const"]], False)

    scalar_type = next(
        (item for item in schema_types if item not in {"array", "null"}), "string"
    )
    py_type = _TYPE_MAP.get(scalar_type, str)
    return (py_type, list(schema.get("enum", [])), False)


def _is_json_arg(schema: dict[str, Any]) -> bool:
    """Whether a request-body field must be supplied as a raw JSON value."""
    schema_type = schema.get("type")
    schema_types = schema_type if isinstance(schema_type, list) else [schema_type]
    if "object" in schema_types or "properties" in schema:
        return True
    if schema.get("additionalProperties"):
        return True
    if "array" in schema_types:
        items = schema.get("items")
        return isinstance(items, dict) and _is_json_arg(items)
    return any(
        isinstance(member, dict) and _is_json_arg(member)
        for member in schema.get("anyOf", []) or []
    )


def parse_json_arg(raw: str) -> Any:
    """Decode a CLI argument value that carries a JSON document."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"invalid JSON: {exc}") from exc


def request_body_parameters(
    body_schema: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Flatten a dereferenced request-body schema into OpenAPI parameter objects.

    A body counts as an object when it declares ``type: object`` or carries
    ``properties`` — the latter is how a normalized 3.1 nullable object
    (``type: ["object", "null"]``) arrives: ``expand_type_arrays`` moves the
    type into ``anyOf`` variants while ``properties`` stays on the parent.
    Failing both, an ``anyOf`` with exactly one object variant is unwrapped
    to that variant.
    """
    if not isinstance(body_schema, dict):
        return []
    body_type = body_schema.get("type")
    body_types = body_type if isinstance(body_type, list) else [body_type]
    if "object" not in body_types and "properties" not in body_schema:
        object_members = [
            member
            for member in body_schema.get("anyOf", [])
            if isinstance(member, dict)
            and (
                "object"
                in (
                    member.get("type")
                    if isinstance(member.get("type"), list)
                    else [member.get("type")]
                )
                or "properties" in member
            )
        ]
        if len(object_members) != 1:
            return []
        body_schema = {**body_schema, **object_members[0]}
    required = set(body_schema.get("required") or [])
    out: list[dict[str, Any]] = []
    for name, prop in (body_schema.get("properties") or {}).items():
        if not isinstance(prop, dict):
            continue
        out.append(
            {
                "name": name,
                "in": "body",
                "required": name in required,
                "description": prop.get("description") or prop.get("title"),
                "schema": prop,
                "_json_arg": _is_json_arg(prop),
            }
        )
    return out


def _provider_choices(schema: dict[str, Any]) -> list[Any]:
    """Union of per-provider ``choices`` lists found in OpenBB extension keys."""
    out: list[Any] = []
    for key, value in schema.items():
        if key in _OPENAPI_RESERVED_SCHEMA_KEYS:
            continue
        if isinstance(value, dict) and isinstance(value.get("choices"), list):
            for c in value["choices"]:
                if c not in out:
                    out.append(c)
    return out


def _escape_help(text: str | None) -> str | None:
    """Escape lone ``%`` so argparse's %-formatting validator accepts the help text."""
    if text is None:
        return None
    return text.replace("%", "%%")


def parameter_to_kwargs(param: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Translate one OpenAPI parameter to ``(flag, add_argument kwargs)``."""
    name = param.get("name")
    if not name or name == "chart":
        return None

    schema = param.get("schema", {}) or {}
    py_type, enum_choices, is_list = _resolve_schema(schema)
    provider_choices = _provider_choices(schema)
    choices: list[Any] = list(enum_choices)
    for c in provider_choices:
        if c not in choices:
            choices.append(c)

    kwargs: dict[str, Any] = {
        "dest": name,
        "help": _escape_help(param.get("description") or schema.get("description")),
    }

    if param.get("_json_arg"):
        kwargs["type"] = parse_json_arg
        if param.get("required"):
            kwargs["required"] = True
        return (f"--{name}", kwargs)

    if py_type is bool:
        kwargs.update(action="store_true", default=bool(schema.get("default", False)))
        return (f"--{name}", kwargs)

    kwargs["type"] = py_type
    if "default" in schema:
        kwargs["default"] = schema["default"]
    if choices:
        kwargs["choices"] = choices
    if is_list:
        kwargs["nargs"] = "+"
    if param.get("required") and "default" not in kwargs:
        kwargs["required"] = True

    return (f"--{name}", kwargs)


def build_parser_from_operation(
    op: dict[str, Any],
    spec: dict[str, Any] | None = None,
    path_item: dict[str, Any] | None = None,
) -> argparse.ArgumentParser:
    """Build an ``ArgumentParser`` from an OpenAPI operation object.

    When ``path_item`` is given, parameters shared by every operation under that
    path are inherited by the parser (see :func:`operation_parameters`).
    """
    parser = argparse.ArgumentParser(
        prog=op.get("operationId", "cmd"),
        description=(op.get("description") or op.get("summary") or "").strip() or None,
        add_help=False,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    body_params = (
        request_body_parameters(extract_request_body_schema(spec, op))
        if spec is not None
        else []
    )
    params = (
        operation_parameters(spec, path_item or {}, op)
        if spec is not None
        else list(op.get("parameters", []) or [])
    )
    for param in [*params, *body_params]:
        translated = parameter_to_kwargs(param)
        if translated is None:
            continue
        flag, kwargs = translated
        try:
            parser.add_argument(flag, **kwargs)
        except argparse.ArgumentError:
            continue
    return parser


def _strip_placeholders(segment: str) -> str:
    """Remove ``{placeholder}`` substrings from a URL segment."""
    out = segment
    while "{" in out and "}" in out:
        i = out.find("{")
        j = out.find("}", i)
        if j < 0:
            break
        out = out[:i] + out[j + 1 :]
    # A segment made only of placeholders and punctuation (``{x},{y}``) is not a name.
    if not any(ch.isalnum() for ch in out):
        return ""
    return out.strip(".")


def detect_api_prefix(spec: dict[str, Any]) -> str:
    """Compute the longest slash-segmented prefix shared by every path."""
    paths = list(spec.get("paths", {}).keys())
    if not paths:
        return "/api/v1"
    parts_lists = [p.split("/")[:-1] for p in paths]
    common: list[str] = parts_lists[0]
    for parts in parts_lists[1:]:
        new_common: list[str] = []
        for a, b in zip(common, parts):
            if a == b:
                new_common.append(a)
            else:
                break
        common = new_common
        if not common:
            break
    prefix = "/".join(common).rstrip("/")
    return prefix or ""


def url_to_command(url: str, api_prefix: str = "/api/v1") -> str:
    """Convert a URL path to a dotted command, dropping ``{path_params}``.

    A literal ``.`` inside a URL segment (``/v1.1/fundamentals``) becomes
    ``_`` — dots in command names are exclusively namespace separators.
    """
    prefix_parts = [p for p in api_prefix.strip("/").split("/") if p]
    parts = [p for p in url.strip("/").split("/") if p]
    if parts[: len(prefix_parts)] == prefix_parts:
        parts = parts[len(prefix_parts) :]
    cleaned = [_strip_placeholders(p).replace(".", "_") for p in parts]
    return ".".join(p for p in cleaned if p)


def build_command_index(
    spec: dict[str, Any], *, api_prefix: str = "/api/v1"
) -> dict[str, argparse.ArgumentParser]:
    """Map each ``paths`` entry in the spec to an ArgumentParser by dotted command."""
    index: dict[str, argparse.ArgumentParser] = {}
    for url, methods in spec.get("paths", {}).items():
        op = methods.get("get") or methods.get("post")
        if not op:
            continue
        index[url_to_command(url, api_prefix=api_prefix)] = build_parser_from_operation(
            op, spec, methods
        )
    return index


def build_router_map(
    spec: dict[str, Any], *, api_prefix: str = "/api/v1"
) -> dict[str, str]:
    """Classify every dotted path in ``spec`` as ``"menu"`` or ``"command"``."""
    out: dict[str, str] = {}
    for url, methods in spec.get("paths", {}).items():
        if not (methods.get("get") or methods.get("post")):
            continue
        cmd = url_to_command(url, api_prefix=api_prefix)
        if not cmd:
            continue
        parts = cmd.split(".")
        for i in range(1, len(parts)):
            out[".".join(parts[:i])] = "menu"
        out.setdefault(cmd, "command")
    return out


def build_reference(
    spec: dict[str, Any], *, api_prefix: str = "/api/v1"
) -> dict[str, Any]:
    """Mimic ``obb.reference`` — ``paths`` for commands, ``routers`` for menus."""
    prefix_parts = [p for p in api_prefix.strip("/").split("/") if p]
    tag_descriptions: dict[str, str] = {
        t["name"]: t.get("description", "")
        for t in spec.get("tags", [])
        if isinstance(t, dict) and t.get("name")
    }

    router_map = build_router_map(spec, api_prefix=api_prefix)

    paths_out: dict[str, dict[str, Any]] = {}
    routers_out: dict[str, dict[str, Any]] = {}
    for url, methods in spec.get("paths", {}).items():
        op = methods.get("get") or methods.get("post")
        if not op:
            continue
        parts = [p for p in url.strip("/").split("/") if p]
        if parts[: len(prefix_parts)] == prefix_parts:
            parts = parts[len(prefix_parts) :]
        non_template = [
            p.replace(".", "_")
            for p in parts
            if not (p.startswith("{") and p.endswith("}"))
        ]
        cli_path = "/" + "/".join(non_template)
        op_desc = (op.get("description") or op.get("summary") or "").strip()
        if cli_path not in paths_out or not paths_out[cli_path].get("description"):
            paths_out[cli_path] = {"description": op_desc}
        tags = op.get("tags") or []
        tag_desc = tag_descriptions.get(tags[0]) if tags else ""
        for i in range(1, len(non_template) + 1):
            dotted = ".".join(non_template[:i])
            if router_map.get(dotted) != "menu":
                continue
            menu_path = "/" + "/".join(non_template[:i]) + "/"
            if not routers_out.get(menu_path, {}).get("description"):
                routers_out[menu_path] = {"description": tag_desc or ""}
    return {"paths": paths_out, "routers": routers_out}


def _parse_spec_text(text: str, *, content_type: str = "") -> dict[str, Any]:
    """Parse a fetched spec body, choosing JSON or YAML by content sniff."""
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        return json.loads(text)
    if "yaml" in content_type or "yml" in content_type:
        return _yaml_load(text)
    if stripped[:8] in ("openapi:", "swagger:"):
        return _yaml_load(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _yaml_load(text)


def _yaml_load(text: str) -> dict[str, Any]:
    """Parse a YAML document."""
    import yaml

    return yaml.safe_load(text)


_EMBEDDED_SPEC_MARKERS: tuple[str, ...] = (
    "var spec = ",
    "const spec = ",
    "let spec = ",
    "window.spec = ",
    '"spec":',
    "spec:",
)


def _find_matching_brace(text: str, start: int) -> int | None:
    """Return the index *after* the ``}`` that matches the ``{`` at ``start``."""
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def _extract_embedded_spec(html: str) -> dict[str, Any] | None:
    """Scan an HTML page for an embedded OpenAPI / Swagger spec."""
    for marker in _EMBEDDED_SPEC_MARKERS:
        idx = 0
        while True:
            i = html.find(marker, idx)
            if i < 0:
                break
            start = i + len(marker)
            while start < len(html) and html[start] in " \t\r\n":
                start += 1
            end = _find_matching_brace(html, start)
            if end is None:
                idx = i + 1
                continue
            try:
                obj = json.loads(html[start:end])
            except json.JSONDecodeError:
                idx = i + 1
                continue
            if isinstance(obj, dict) and ("openapi" in obj or "swagger" in obj):
                return obj
            idx = end
    return None


def _resolve_json_pointer(document: Any, fragment: str) -> Any:
    """Resolve a URI-fragment JSON pointer within one OpenAPI document."""
    if not fragment:
        return document
    pointer = unquote(fragment)
    if not pointer.startswith("/"):
        raise ValueError(f"Unsupported OpenAPI reference fragment: #{fragment}")
    node = document
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            node = node[part]
        elif isinstance(node, list):
            node = node[int(part)]
        else:
            raise ValueError(f"Invalid OpenAPI reference fragment: #{fragment}")
    return node


def _url_origin(url: str) -> tuple[str, str, int | None]:
    """Return a normalized HTTP(S) origin for reference security checks."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"Unsupported OpenAPI reference URL: {url}")
    default_port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme, parsed.hostname.lower(), parsed.port or default_port


def _bundle_external_refs(
    document: dict[str, Any],
    source_url: str,
    *,
    timeout: float,
    headers: dict[str, str],
) -> dict[str, Any]:
    """Inline same-origin external refs while preserving root-local refs."""
    max_documents = 512
    max_document_bytes = 8 * 1024 * 1024
    read_chunk_bytes = 64 * 1024
    max_depth = 128
    root_url, _ = urldefrag(source_url)
    root_origin = _url_origin(root_url)
    documents: dict[str, dict[str, Any]] = {root_url: document}

    def load_document(url: str) -> dict[str, Any]:
        cached = documents.get(url)
        if cached is not None:
            return cached
        if _url_origin(url) != root_origin:
            raise ValueError(f"External OpenAPI reference must be same-origin: {url}")
        if len(documents) >= max_documents:
            raise ValueError("OpenAPI reference graph exceeds the document limit")
        with httpx.stream(
            "GET",
            url,
            timeout=timeout,
            follow_redirects=False,
            headers=headers,
        ) as response:
            if response.is_redirect:
                raise ValueError(
                    "Redirects are not allowed for external OpenAPI references"
                )
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > max_document_bytes:
                raise ValueError("External OpenAPI reference exceeds the size limit")
            content = bytearray()
            for chunk in response.iter_bytes(chunk_size=read_chunk_bytes):
                if len(chunk) > max_document_bytes - len(content):
                    raise ValueError(
                        "External OpenAPI reference exceeds the size limit"
                    )
                content.extend(chunk)
            text = bytes(content).decode(response.encoding or "utf-8")
            content_type = response.headers.get("content-type", "")
        parsed = _ensure_openapi_dict(
            _parse_spec_text(
                text,
                content_type=content_type,
            ),
            url,
        )
        documents[url] = parsed
        return parsed

    def visit(
        node: Any,
        current_url: str,
        current_document: dict[str, Any],
        *,
        imported: bool,
        seen: frozenset[tuple[str, str]],
        depth: int,
    ) -> Any:
        if depth > max_depth:
            raise ValueError("OpenAPI reference graph exceeds the depth limit")
        if isinstance(node, dict):
            if "$id" in node:
                raise ValueError("OpenAPI $id resource identifiers are not supported")
            ref = node.get("$ref")
            if isinstance(ref, str) and (imported or not ref.startswith("#")):
                target_url, fragment = urldefrag(urljoin(current_url, ref))
                if fragment and not fragment.startswith("/"):
                    raise ValueError("OpenAPI reference anchors are not supported")
                marker = (target_url, fragment)
                if marker in seen:
                    return {"$ref": f"{target_url}#{fragment}"}
                target_document = (
                    current_document
                    if target_url == current_url
                    else load_document(target_url)
                )
                target = _resolve_json_pointer(target_document, fragment)
                resolved = visit(
                    target,
                    target_url,
                    target_document,
                    imported=True,
                    seen=seen | {marker},
                    depth=depth + 1,
                )
                unsupported_siblings = set(node) - {"$ref", "summary", "description"}
                if unsupported_siblings:
                    raise ValueError(
                        "OpenAPI reference siblings other than summary and description "
                        "are not supported"
                    )
                siblings = {
                    key: visit(
                        value,
                        current_url,
                        current_document,
                        imported=imported,
                        seen=seen,
                        depth=depth + 1,
                    )
                    for key, value in node.items()
                    if key != "$ref"
                }
                if isinstance(resolved, dict):
                    return {**resolved, **siblings}
                return resolved
            return {
                key: visit(
                    value,
                    current_url,
                    current_document,
                    imported=imported,
                    seen=seen,
                    depth=depth + 1,
                )
                for key, value in node.items()
            }
        if isinstance(node, list):
            return [
                visit(
                    value,
                    current_url,
                    current_document,
                    imported=imported,
                    seen=seen,
                    depth=depth + 1,
                )
                for value in node
            ]
        return node

    return visit(
        document,
        root_url,
        document,
        imported=False,
        seen=frozenset(),
        depth=0,
    )


def _raise_fetch_failure(
    response: Any, parse_error: ValueError | None, url: str
) -> NoReturn:
    """Raise why the spec at ``url`` could not be loaded.

    Parameters
    ----------
    response : Any
        The response for the spec URL.
    parse_error : ValueError | None
        The error from parsing a successful response, if any.
    url : str
        The spec URL.

    Raises
    ------
    httpx.HTTPStatusError
        If the response has an error status.
    ValueError
        If the response body is not a parseable OpenAPI document.
    """
    response.raise_for_status()
    raise parse_error or ValueError(f"Could not load an OpenAPI document from {url}")


def fetch_openapi(
    base_url: str,
    *,
    timeout: float = 10.0,
    path: str | None = None,
    headers: dict[str, str] | None = None,
    query_params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Fetch the OpenAPI spec at ``base_url`` and return the parsed dict."""
    explicit_path = path is not None
    full_url = (
        path
        if path and (path.startswith("http://") or path.startswith("https://"))
        else f"{base_url.rstrip('/')}{path or '/openapi.json'}"
    )
    merged_headers = {"User-Agent": "openbb-cli/1.0"}
    if headers:
        merged_headers.update(headers)

    response = httpx.get(
        full_url,
        timeout=timeout,
        follow_redirects=True,
        headers=merged_headers,
        params=query_params or None,
    )
    parse_error: ValueError | None = None
    if response.status_code < 400:
        try:
            parsed = _ensure_openapi_dict(
                _parse_spec_text(
                    response.text,
                    content_type=response.headers.get("content-type", ""),
                ),
                full_url,
            )
            return _bundle_external_refs(
                parsed,
                str(getattr(response, "url", full_url)),
                timeout=timeout,
                headers=merged_headers,
            )
        except ValueError as exc:
            parse_error = exc

    if explicit_path:
        _raise_fetch_failure(response, parse_error, full_url)

    landing_url = base_url.rstrip("/") + "/"
    landing = httpx.get(
        landing_url,
        timeout=timeout,
        follow_redirects=True,
        headers=merged_headers,
        params=query_params or None,
    )
    landing.raise_for_status()
    embedded = _extract_embedded_spec(landing.text)
    if embedded is not None:
        return _bundle_external_refs(
            _ensure_openapi_dict(embedded, landing_url),
            str(getattr(landing, "url", landing_url)),
            timeout=timeout,
            headers=merged_headers,
        )

    _raise_fetch_failure(response, parse_error, full_url)


def _ensure_openapi_dict(parsed: Any, source_url: str) -> dict[str, Any]:
    """Reject parsed bodies that aren't a JSON object (and thus can't be an OpenAPI doc)."""
    if not isinstance(parsed, dict):
        raise ValueError(
            f"{source_url!r} returned a "
            f"{type(parsed).__name__}, not an OpenAPI document. "
            "Pass --openapi-path to point at the real spec endpoint "
            "(e.g. /swagger/v1/swagger.json)."
        )
    return expand_type_arrays(parsed)


def expand_type_arrays(node: Any) -> Any:
    """Rewrite JSON-Schema ``type`` arrays (OpenAPI 3.1) into ``anyOf`` unions.

    ``{"type": ["number", "null"]}`` becomes
    ``{"anyOf": [{"type": "number"}, {"type": "null"}]}`` — the OpenAPI 3.0
    shape every schema consumer already understands. Sibling keywords are
    copied into each non-null variant so type-scoped keys (``format``,
    ``items``, ``enum``) survive the split. Schemas that already declare
    ``anyOf`` / ``oneOf`` are left alone: consumers resolve the combinator
    before ever reading ``type``.
    """
    if isinstance(node, list):
        return [expand_type_arrays(v) for v in node]
    if not isinstance(node, dict):
        return node
    out = {k: expand_type_arrays(v) for k, v in node.items()}
    types = out.get("type")
    if not isinstance(types, list) or "anyOf" in out or "oneOf" in out:
        return out
    rest = {k: v for k, v in out.items() if k != "type"}
    variants = [{"type": "null"} if t == "null" else {**rest, "type": t} for t in types]
    return {**rest, "anyOf": variants}
