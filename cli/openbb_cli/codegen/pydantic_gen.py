"""Convert OpenAPI JSON-schema fragments into Pydantic class source code."""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass, field
from typing import Any

_PRIMITIVE_TYPES: dict[str, str] = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
}

_STRING_FORMATS: dict[str, str] = {
    "date": "datetime.date",
    "date-time": "datetime.datetime",
}

_PYTHON_RESERVED_FIELD_NAMES = frozenset(
    {"model_config", "model_fields", "model_dump", "model_validate"}
)


@dataclass
class GeneratedClass:
    """One emitted Pydantic class plus any nested classes it depends on."""

    name: str
    source: str
    nested: list[GeneratedClass] = field(default_factory=list)
    imports: set[str] = field(default_factory=set)

    def flatten(self) -> list[GeneratedClass]:
        """Return ``[nested..., self]`` in topological order, deduped by name."""
        seen: set[str] = set()
        out: list[GeneratedClass] = []
        for child in self.nested:
            for grandchild in child.flatten():
                if grandchild.name not in seen:
                    seen.add(grandchild.name)
                    out.append(grandchild)
        if self.name not in seen:
            out.append(self)
        return out

    def collect_imports(self) -> set[str]:
        """Union of ``imports`` across this class and every descendant."""
        out = set(self.imports)
        for child in self.nested:
            out.update(child.collect_imports())
        return out


def safe_field_name(name: str) -> tuple[str, bool]:
    """Normalize a JSON property name to a valid Python identifier.

    Returns ``(safe_name, needs_alias)``.
    """
    cleaned = re.sub(r"[^0-9a-zA-Z_]", "_", name).lstrip("_")
    if not cleaned:
        cleaned = "field"
    if cleaned[0].isdigit():
        cleaned = f"f_{cleaned}"
    if keyword.iskeyword(cleaned) or cleaned in _PYTHON_RESERVED_FIELD_NAMES:
        cleaned = f"{cleaned}_"
    return (cleaned, cleaned != name)


def query_field_name(name: str) -> str:
    """Snake-case attribute name for a query parameter.

    The platform exposes every query parameter in snake_case (``zoneId`` is
    passed as ``zone_id``); the original name is kept as the field alias so
    the upstream wire name is unchanged.
    """
    safe, _ = safe_field_name(name)
    snake = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", safe)
    snake = re.sub(r"(?<=[A-Z])([A-Z][a-z])", r"_\1", snake)
    snake = re.sub(r"_+", "_", snake).lower().strip("_") or "field"
    return f"{snake}_" if keyword.iskeyword(snake) else snake


def class_name_from(*parts: str) -> str:
    """Join + camel-case a set of name parts into a Python class identifier."""
    words: list[str] = []
    for part in parts:
        if not part:
            continue
        for word in re.split(r"[^0-9a-zA-Z]+", part):
            if word:
                words.append(word[:1].upper() + word[1:])
    name = "".join(words) or "Anonymous"
    if name[0].isdigit():
        name = f"_{name}"
    return name


def schema_to_type(  # noqa: PLR0911
    schema: Any,
    *,
    parent_class_name: str,
    field_name: str,
    nested_classes: list[GeneratedClass],
    imports: set[str],
) -> str:
    """Resolve a JSON schema to a Python type annotation string."""
    if not isinstance(schema, dict):
        imports.add("from typing import Any")
        return "Any"

    if "$ref" in schema:
        imports.add("from typing import Any")
        return "dict[str, Any]"

    any_of = schema.get("anyOf") or schema.get("oneOf")
    if any_of:
        return _resolve_union(
            any_of,
            parent_class_name=parent_class_name,
            field_name=field_name,
            nested_classes=nested_classes,
            imports=imports,
        )

    enum = schema.get("enum")
    if enum:
        return _enum_primitive(enum, schema.get("type"), imports)

    if "const" in schema:
        return _enum_primitive([schema["const"]], schema.get("type"), imports)

    schema_type = schema.get("type")
    if schema_type == "array":
        inner = schema_to_type(
            schema.get("items") or {},
            parent_class_name=parent_class_name,
            field_name=field_name + "_item",
            nested_classes=nested_classes,
            imports=imports,
        )
        return f"list[{inner}]"

    if schema_type == "object" or "properties" in schema:
        return _resolve_object(
            schema,
            parent_class_name=parent_class_name,
            field_name=field_name,
            nested_classes=nested_classes,
            imports=imports,
        )

    if schema_type in _PRIMITIVE_TYPES:
        py_type = _PRIMITIVE_TYPES[schema_type]
        if py_type == "str":
            fmt = schema.get("format")
            if fmt in _STRING_FORMATS:
                qualified = _STRING_FORMATS[fmt]
                imports.add("import datetime")
                return qualified
        return py_type

    imports.add("from typing import Any")
    return "Any"


def _enum_primitive(
    values: list[Any],
    declared_type: Any,  # noqa: ARG001
    imports: set[str],
) -> str:
    """Map an ``enum`` / ``const`` to a ``Literal[...]`` annotation."""
    if not values:
        imports.add("from typing import Any")
        return "Any"
    rendered_members = ", ".join(repr(v) for v in values)
    imports.add("from typing import Literal")
    return f"Literal[{rendered_members}]"


def _resolve_union(
    variants: list[Any],
    *,
    parent_class_name: str,
    field_name: str,
    nested_classes: list[GeneratedClass],
    imports: set[str],
) -> str:
    """Resolve an ``anyOf`` / ``oneOf`` list into a Python annotation."""
    non_null = [
        v for v in variants if not (isinstance(v, dict) and v.get("type") == "null")
    ]
    is_optional = len(non_null) != len(variants)

    if not non_null:
        imports.add("from typing import Any")
        return "Any"

    rendered: list[str] = []
    for index, variant in enumerate(non_null, start=1):
        # Untitled object variants would all get the same class name and
        # collapse into one; number them so every shape stays distinct.
        distinct = (
            isinstance(variant, dict)
            and len(non_null) > 1
            and (variant.get("properties") or variant.get("type") == "object")
            and not variant.get("title")
        )
        rendered.append(
            schema_to_type(
                variant,
                parent_class_name=parent_class_name,
                field_name=f"{field_name}_v{index}" if distinct else field_name,
                nested_classes=nested_classes,
                imports=imports,
            )
        )
    seen: set[str] = set()
    unique: list[str] = []
    for r in rendered:
        if r not in seen:
            seen.add(r)
            unique.append(r)

    inner = unique[0] if len(unique) == 1 else " | ".join(unique)

    if is_optional:
        return f"{inner} | None"
    return inner


def _resolve_object(
    schema: dict[str, Any],
    *,
    parent_class_name: str,
    field_name: str,
    nested_classes: list[GeneratedClass],
    imports: set[str],
) -> str:
    """Either generate a nested class or fall back to ``dict[str, Any]``."""
    properties = schema.get("properties") or {}
    if not properties:
        ap = schema.get("additionalProperties")
        if isinstance(ap, dict):
            value_type = schema_to_type(
                ap,
                parent_class_name=parent_class_name,
                field_name=field_name + "_value",
                nested_classes=nested_classes,
                imports=imports,
            )
            return f"dict[str, {value_type}]"
        imports.add("from typing import Any")
        return "dict[str, Any]"

    nested_name = schema.get("title") or class_name_from(parent_class_name, field_name)
    nested_name = class_name_from(nested_name)
    nested = generate_class(
        schema,
        class_name=nested_name,
        docstring=schema.get("description"),
    )
    nested_classes.append(nested)
    return nested_name


def render_field_default(default: Any) -> str:
    """Render a JSON default value as a Python literal for ``Field(default=...)``."""
    if isinstance(default, bool):
        return "True" if default else "False"
    if isinstance(default, (int, float)):
        return repr(default)
    if isinstance(default, str):
        return repr(default)
    if default is None:
        return "None"
    if isinstance(default, (list, tuple, dict)):
        return repr(default)
    return repr(default)


_LINE_LENGTH_BUDGET = 88


def _build_field_call(
    *,
    description: str | None,
    default: Any,
    has_default: bool,
    required: bool,
    alias: str | None,
    leading_width: int = 0,
) -> str:
    """Compose the ``Field(...)`` text used after ``field_name: type =``.

    Parameters
    ----------
    description : str, optional
        The field description.
    default : Any
        The literal default value, or ``None`` when ``has_default`` is False.
    has_default : bool
        Whether the schema specified an explicit default.
    required : bool
        Whether the field is required.
    alias : str, optional
        On-the-wire JSON name when it differs from the Python identifier.
    leading_width : int
        Number of characters consumed before the ``Field(...)`` call on the line.

    Returns
    -------
    str
        The full ``Field(...)`` source.
    """
    args: list[str] = []
    if has_default and not required:
        args.append(f"default={render_field_default(default)}")
    elif not required:
        args.append("default=None")
    if alias is not None:
        args.append(f"alias={alias!r}")
    if description is not None:
        args.append(f"description={_python_string_literal(description)}")
    if not args:
        return ""
    single_line = "Field(" + ", ".join(args) + ")"
    if leading_width + len(single_line) <= _LINE_LENGTH_BUDGET:
        return single_line
    inner = ",\n        ".join(args)
    return f"Field(\n        {inner},\n    )"


def _resolve_field_description(
    prop: dict[str, Any],
    field_name: str | None = None,  # noqa: ARG001
    include_choices: bool = True,
) -> str:
    """Pick the description text for a Pydantic Field."""
    text = prop.get("description") or prop.get("title")
    parts: list[str] = []
    if text:
        parts.append(text.rstrip(". ") + ".")
    elif prop.get("example") is not None:
        parts.append(f"Example: {prop['example']}.")
    enum = prop.get("enum") or (
        [prop["const"]]
        if isinstance(prop.get("const"), (str, int, float, bool))
        else None
    )
    if enum and include_choices:
        rendered = ", ".join(str(v) for v in enum)
        parts.append(f"Choices: {rendered}.")
    return " ".join(parts).rstrip()


def _nested_object_breakout(prop: dict[str, Any]) -> str:
    """Render an inline breakout of a nested object's fields."""
    target = prop
    if isinstance(prop.get("items"), dict):
        target = prop["items"]
    for combinator in ("oneOf", "anyOf"):
        variants = target.get(combinator)
        if isinstance(variants, list):
            for variant in variants:
                if isinstance(variant, dict) and isinstance(
                    variant.get("properties"), dict
                ):
                    target = variant
                    break
    properties = target.get("properties")
    if not isinstance(properties, dict) or not properties:
        return ""
    summaries: list[str] = []
    for inner_name, inner_sch in properties.items():
        if not isinstance(inner_sch, dict):
            summaries.append(inner_name)
            continue
        inner_type = _quick_schema_type(inner_sch)
        summaries.append(f"{inner_name} ({inner_type})")
    label = (
        "Inner item fields" if isinstance(prop.get("items"), dict) else "Inner fields"
    )
    return f"{label}: {', '.join(summaries)}."


def _quick_schema_type(schema: dict[str, Any]) -> str:
    """Best-effort shorthand type label for breakout text."""
    if isinstance(schema.get("enum"), list):
        return "str"
    schema_type = schema.get("type")
    if schema_type == "array":
        items = schema.get("items")
        inner = "Any"
        if isinstance(items, dict):
            inner = _quick_schema_type(items)
        return f"list[{inner}]"
    if schema_type == "object" or "properties" in schema:
        title = schema.get("title")
        return title or "object"
    if isinstance(schema_type, str):
        primitive_type = _PRIMITIVE_TYPES.get(schema_type)
        if primitive_type is not None:
            if schema_type == "string":
                fmt = schema.get("format")
                if fmt == "date":
                    return "date"
                if fmt == "date-time":
                    return "datetime"
            return primitive_type
    return "Any"


def _python_string_literal(text: str) -> str:
    """Render a docstring-safe string literal that survives multi-line text.

    Parameters
    ----------
    text : str
        The raw string to embed in generated source.

    Returns
    -------
    str
        A quoted Python literal.
    """
    if "\n" in text or "'" in text and '"' in text:
        escaped = text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
        return f'"""{escaped}"""'
    return repr(text)


def _annotation_for_docstring(annotation: str) -> tuple[str, bool]:
    """Strip ``| None`` from a type annotation for Numpy-style ``:`` lines.

    Parameters
    ----------
    annotation : str
        The Python type annotation.

    Returns
    -------
    tuple of (str, bool)
        The bare type without ``| None`` suffix, and an optional flag.
    """
    suffix = " | None"
    if annotation.endswith(suffix):
        return (annotation[: -len(suffix)].strip(), True)
    return (annotation, False)


def _render_numpy_parameters(
    fields: list[tuple[str, str, str | None, bool, Any, bool]],
) -> str:
    """Build a Numpy-style ``Parameters`` block for a class / function docstring.

    Parameters
    ----------
    fields : list of tuple
        Each tuple is ``(name, annotation, description, has_default, default, optional)``.

    Returns
    -------
    str
        The full block.
    """
    if not fields:
        return ""
    lines = ["Parameters", "----------"]
    for name, annotation, description, has_default, default, optional in fields:
        bare, _ = _annotation_for_docstring(annotation)
        type_label = f"{bare}, optional" if optional else bare
        lines.append(f"{name} : {type_label}")
        body = description or ""
        if has_default and default is not None:
            suffix = f"(default: {render_field_default(default)})"
            body = f"{body} {suffix}".strip() if body else suffix
        if body:
            for piece in body.split("\n"):
                lines.append(f"    {piece}")
    return "\n".join(lines)


def _render_class_docstring(
    summary: str,
    fields: list[tuple[str, str, str | None, bool, Any, bool]],
) -> str:
    """Render a Numpy-style class docstring and indent every line by four spaces.

    Parameters
    ----------
    summary : str
        The summary sentence shown immediately after the opening quotes.
    fields : list of tuple
        Tuples consumed by ``_render_numpy_parameters``.

    Returns
    -------
    str
        The full triple-double-quoted block.
    """
    summary_clean = summary.strip()
    if not summary_clean.endswith("."):
        summary_clean += "."
    lines = [f'    """{summary_clean}']
    params_block = _render_numpy_parameters(fields)
    if params_block:
        lines.append("")
        for line in params_block.split("\n"):
            lines.append(f"    {line}" if line else "")
    lines.append('    """')
    return "\n".join(lines)


def render_function_docstring(
    summary: str,
    *,
    parameters: list[tuple[str, str, str | None]] | None = None,
    returns: tuple[str, str | None] | None = None,
    indent: str = "    ",
) -> str:
    """Render a Numpy-style function / method docstring.

    Parameters
    ----------
    summary : str
        The one-line summary sentence.
    parameters : list of (name, type, description) tuples, optional
        Each tuple becomes one entry under the ``Parameters`` section.
    returns : tuple of (type, description), optional
        When supplied, emits a ``Returns`` section.
    indent : str
        The indentation prefix for every line of the rendered block.

    Returns
    -------
    str
        The full triple-double-quoted block.
    """
    summary_clean = summary.strip()
    if not summary_clean.endswith("."):
        summary_clean += "."
    lines = [f'{indent}"""{summary_clean}']
    if parameters:
        lines.append("")
        lines.append(f"{indent}Parameters")
        lines.append(f"{indent}----------")
        for name, type_label, description in parameters:
            lines.append(f"{indent}{name} : {type_label}")
            if description:
                for piece in description.split("\n"):
                    lines.append(f"{indent}    {piece}")
    if returns is not None:
        return_type, return_desc = returns
        lines.append("")
        lines.append(f"{indent}Returns")
        lines.append(f"{indent}-------")
        lines.append(f"{indent}{return_type}")
        if return_desc:
            for piece in return_desc.split("\n"):
                lines.append(f"{indent}    {piece}")
    lines.append(f'{indent}"""')
    return "\n".join(lines)


_BUILTIN_TYPE_NAMES = (
    "list",
    "dict",
    "set",
    "tuple",
    "str",
    "int",
    "float",
    "bool",
    "bytes",
)


_QUOTED = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")


def _shadowed_builtins(properties: dict[str, Any], class_name: str) -> set[str]:
    """Builtin type names that a field would shadow inside its class's annotations.

    A field named ``list`` binds ``list`` in the class body, so a later
    ``list[...]`` annotation (its own included) fails when the class is built.
    Returns the builtin names some field is called and some annotation uses
    outside a string (``Literal['list']`` uses none).
    """
    names = {safe_field_name(raw)[0] for raw in properties} | {
        query_field_name(raw) for raw in properties
    }
    candidates = names & set(_BUILTIN_TYPE_NAMES)
    if not candidates:
        return set()
    annotations = " ".join(
        schema_to_type(
            prop if isinstance(prop, dict) else {},
            parent_class_name=class_name,
            field_name=safe_field_name(raw)[0],
            nested_classes=[],
            imports=set(),
        )
        for raw, prop in properties.items()
    )
    annotations = _QUOTED.sub("''", annotations)
    return {name for name in candidates if re.search(rf"\b{name}\b", annotations)}


def _unique_field_names(
    properties: dict[str, Any], class_name: str, *, query_params: bool
) -> dict[str, str]:
    """Map each property name to a field name no other property of the class uses.

    Names are made safe the usual way (``query_field_name`` for query
    parameters), and a builtin some annotation needs gets a ``_`` suffix. When
    two properties land on one name (``@id`` and ``id``), the property already
    spelled that way keeps it and the others get ``_`` suffixes.
    """
    shadowed = _shadowed_builtins(properties, class_name)
    wanted: dict[str, str] = {}
    for raw in properties:
        safe = query_field_name(raw) if query_params else safe_field_name(raw)[0]
        wanted[raw] = f"{safe}_" if safe in shadowed else safe
    taken: set[str] = set()
    out: dict[str, str] = {}
    for raw in sorted(properties, key=lambda r: wanted[r] != r):
        name = wanted[raw]
        while name in taken:
            name = f"{name}_"
        taken.add(name)
        out[raw] = name
    return {raw: out[raw] for raw in properties}


def query_params_field_names(
    properties: dict[str, Any], class_name: str
) -> dict[str, str]:
    """Map each parameter to its field name in a ``QueryParams`` class.

    The names ``generate_class`` gives the fields of ``class_name`` built from
    ``properties``, for code that reads those fields back.
    """
    return _unique_field_names(properties, class_name, query_params=True)


def generate_class(
    schema: dict[str, Any],
    *,
    class_name: str,
    base_class: str = "BaseModel",
    docstring: str | None = None,
) -> GeneratedClass:
    """Build a Pydantic class definition from an OpenAPI ``object`` schema."""
    properties: dict[str, Any] = schema.get("properties") or {}
    required_set: set[str] = set(schema.get("required") or [])
    nested_classes: list[GeneratedClass] = []
    imports: set[str] = {"from pydantic import BaseModel, Field"}
    body_lines: list[str] = []
    doc_fields: list[tuple[str, str, str | None, bool, Any, bool]] = []
    optional_object_fields: list[str] = []
    multiple_items: dict[str, dict[str, Any]] = {}
    field_names: dict[str, str] = {}
    unique_names = _unique_field_names(
        properties, class_name, query_params=base_class == "QueryParams"
    )

    for raw_name, prop_schema in properties.items():
        safe_name = unique_names[raw_name]
        needs_alias = safe_name != raw_name
        field_names[raw_name] = safe_name
        annotation = schema_to_type(
            prop_schema if isinstance(prop_schema, dict) else {},
            parent_class_name=class_name,
            field_name=safe_name,
            nested_classes=nested_classes,
            imports=imports,
        )
        is_required = raw_name in required_set
        prop = prop_schema if isinstance(prop_schema, dict) else {}
        if prop.get("x-multiple-items"):
            extra: dict[str, Any] = {"multiple_items_allowed": True}
            if prop.get("x-choices"):
                extra["choices"] = list(prop["x-choices"])
            multiple_items[safe_name] = extra
        if not is_required and (prop.get("type") == "object" or "properties" in prop):
            optional_object_fields.append(safe_name)
        has_default = "default" in prop
        nullable = bool(schema.get("x-null-empty"))  # response rows: null == empty
        if (not is_required or nullable) and "None" not in annotation:
            annotation = f"{annotation} | None"
        # The platform lists a query parameter's choices itself ("Choices for
        # <provider>: ..."); repeating them in the description duplicates them.
        description = _resolve_field_description(
            prop, field_name=raw_name, include_choices=base_class != "QueryParams"
        )
        breakout = _nested_object_breakout(prop)
        if breakout:
            description = (
                f"{description} {breakout}".strip() if description else breakout
            )
        prefix = f"    {safe_name}: {annotation} = "
        field_call = _build_field_call(
            description=description,
            default=prop.get("default"),
            has_default=has_default,
            required=is_required,
            alias=raw_name if needs_alias else None,
            leading_width=len(prefix),
        )
        line = f"    {safe_name}: {annotation}"
        if field_call:
            line += f" = {field_call}"
        body_lines.append(line)

        doc_fields.append(
            (
                safe_name,
                annotation,
                description,
                has_default,
                prop.get("default"),
                not is_required,
            )
        )

    if not body_lines:
        body_lines.append("    pass")

    if optional_object_fields:
        # PHP-style serializers emit [] where the schema declares an object
        # (empty associative array quirk); [] is never a valid JSON-object value.
        imports.add("from pydantic import field_validator")
        imports.add("from typing import Any")
        names = ", ".join(repr(n) for n in optional_object_fields)
        body_lines.append(
            f'\n    @field_validator({names}, mode="before")\n'
            "    @classmethod\n"
            "    def _empty_list_to_none(cls, v: Any) -> Any:\n"
            '        """Coerce `[]` to None."""\n'
            "        return None if v == [] else v"
        )

    if multiple_items:
        imports.add("from pydantic import field_validator")
        imports.add("from typing import Any")
        names = ", ".join(repr(n) for n in multiple_items)
        body_lines.append(f"\n    __json_schema_extra__ = {multiple_items!r}")
        body_lines.append(
            f'\n    @field_validator({names}, mode="before")\n'
            "    @classmethod\n"
            "    def _join_multiple_items(cls, v: Any) -> Any:\n"
            '        """Accept a list and join it into a comma-separated string."""\n'
            "        if isinstance(v, (list, tuple, set)):\n"
            '            return ",".join(str(i) for i in v)\n'
            "        return v"
        )

    if schema.get("x-null-empty"):
        imports.add("from pydantic import model_validator")
        imports.add("from typing import Any")
        body_lines.append(
            '\n    @model_validator(mode="before")\n'
            "    @classmethod\n"
            "    def _empty_string_is_null(cls, values: Any) -> Any:\n"
            '        """Treat empty strings as null."""\n'
            "        if isinstance(values, dict):\n"
            '            return {k: (None if v == "" else v) for k, v in values.items()}\n'
            "        return values"
        )

    required_groups = [
        group
        for group in schema.get("x-required-groups") or []
        if _group_maps_to_distinct_fields(group, field_names)
    ]
    if required_groups:
        imports.add("from pydantic import model_validator")
        imports.add("from typing import Any")
        defaults = {
            field_names[raw]: prop["default"]
            for raw, prop in properties.items()
            if isinstance(prop, dict) and prop.get("default") is not None
        }
        body_lines.append(
            _render_required_groups_validator(required_groups, field_names, defaults)
        )

    summary = docstring or class_name
    doc_block = _render_class_docstring(summary, doc_fields)

    source = (
        f"class {class_name}({base_class}):\n"
        f"{doc_block}\n\n" + "\n".join(body_lines) + "\n"
    )

    return GeneratedClass(
        name=class_name,
        source=source,
        nested=nested_classes,
        imports=imports,
    )


def _group_maps_to_distinct_fields(
    group: dict[str, Any], field_names: dict[str, str]
) -> bool:
    """Whether every name in a required group is a field of its own.

    A name with no field, or two names that collapse to one field (``Symbol``
    and ``symbol``), would make the group impossible to satisfy.
    """
    alternatives = group.get("alternatives") or []
    names = {name for alt in alternatives for name in alt}
    names.update(name for name in group.get("members") or [] if name in field_names)
    if not alternatives or any(name not in field_names for name in names):
        return False
    return len({field_names[name] for name in names}) == len(names)


def _render_required_groups_validator(
    groups: list[dict[str, Any]],
    field_names: dict[str, str],
    defaults: dict[str, Any] | None = None,
) -> str:
    """Render an ``after`` model validator enforcing ``oneOf`` / ``anyOf`` groups.

    Parameters
    ----------
    groups : list[dict]
        Required groups in the spec form (``combinator``, ``alternatives``,
        ``members``, ``required``), naming properties by their schema name.
    field_names : dict[str, str]
        Schema property name to generated field name.
    defaults : dict[str, Any], optional
        Field name to default value. An optional group is only checked when a
        member is passed, and a member left at its default was not passed.

    Returns
    -------
    str
        The indented validator method source. ``None``, ``""`` and ``[]``
        count as not passed.
    """
    defaults = defaults or {}
    lines = [
        '\n    @model_validator(mode="after")',
        "    def _check_required_groups(self) -> Any:",
        '        """Enforce the parameter combinations the API requires."""',
    ]
    for group in groups:
        alternatives = tuple(
            tuple(field_names[name] for name in alt) for alt in group["alternatives"]
        )
        exactly_one = group.get("combinator") == "oneOf"
        described = " | ".join(
            alt[0] if len(alt) == 1 else f"({', '.join(alt)})" for alt in alternatives
        )
        message = f"Pass {'exactly' if exactly_one else 'at least'} one of: {described}"
        indent = "        "
        if not group.get("required", True):
            members = tuple(
                field_names[name]
                for name in group.get("members") or []
                if name in field_names
            )
            if any(name in defaults for name in members):
                pairs = tuple((name, defaults.get(name)) for name in members)
                lines.extend(
                    [
                        f"{indent}if any(",
                        f"{indent}    getattr(self, _name) not in (None, '', [])",
                        f"{indent}    and getattr(self, _name) != _default",
                        f"{indent}    for _name, _default in {pairs!r}",
                        f"{indent}):",
                    ]
                )
            else:
                lines.append(
                    f"{indent}if any(getattr(self, _name) not in (None, '', []) "
                    f"for _name in {members!r}):"
                )
            indent += "    "
        lines.extend(
            [
                f"{indent}_satisfied = sum(",
                f"{indent}    all(getattr(self, _name) not in (None, '', []) for _name in _names)",
                f"{indent}    for _names in {alternatives!r}",
                f"{indent})",
                f"{indent}if _satisfied {'!= 1' if exactly_one else '< 1'}:",
                f"{indent}    raise ValueError({message!r})",
            ]
        )
    lines.append("        return self")
    return "\n".join(lines)


def consolidate_imports(imports: set[str]) -> list[str]:
    """Merge multiple ``from X import A`` / ``from X import B`` into one line.

    Parameters
    ----------
    imports : set of str
        Raw import statements.

    Returns
    -------
    list of str
        Sorted list with same-module ``from`` imports collapsed.
    """
    from_imports: dict[str, set[str]] = {}
    bare_imports: set[str] = set()
    for raw_line in imports:
        line = raw_line.strip()
        if line.startswith("from ") and " import " in line:
            module, _, names = line[len("from ") :].partition(" import ")
            for raw_name in names.split(","):
                name = raw_name.strip()
                if name:
                    from_imports.setdefault(module.strip(), set()).add(name)
        else:
            bare_imports.add(line)
    out: list[str] = sorted(bare_imports)
    for module in sorted(from_imports):
        names = ", ".join(sorted(from_imports[module]))
        out.append(f"from {module} import {names}")
    return out


def render_module(
    cls: GeneratedClass,
    *,
    module_docstring: str | None = None,
) -> str:
    """Render a ``cls`` and its nested classes as a single importable module."""
    classes = cls.flatten()
    imports = consolidate_imports(cls.collect_imports())

    stdlib: list[str] = []
    third_party: list[str] = []
    for imp in imports:
        if (
            imp.startswith("from typing")
            or imp.startswith("from datetime")
            or imp.startswith("import typing")
            or imp.startswith("import datetime")
        ):
            stdlib.append(imp)
        else:
            third_party.append(imp)

    parts: list[str] = []
    if module_docstring:
        summary = module_docstring.strip()
        if not summary.endswith("."):
            summary += "."
        parts.append(f'"""{summary}"""')
        parts.append("")
    if stdlib:
        parts.extend(stdlib)
        parts.append("")
    if third_party:
        parts.extend(third_party)
        parts.append("")
    parts.append("")
    parts.extend(c.source for c in classes)
    return "\n".join(parts).rstrip() + "\n"
