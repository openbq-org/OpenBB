"""Tests for openbb_cli.codegen.pydantic_gen — schema → Pydantic source."""

from __future__ import annotations

import ast

import pytest

from openbb_cli.codegen import pydantic_gen as pg

# --- Naming helpers ---


def test_safe_field_name_passes_through_valid_identifier():
    assert pg.safe_field_name("symbol") == ("symbol", False)


def test_safe_field_name_replaces_invalid_chars():
    assert pg.safe_field_name("X-API-Key") == ("X_API_Key", True)


def test_safe_field_name_prefixes_leading_digit_with_letter():
    """``f_`` (not ``_``) so Pydantic v2 accepts it — leading-underscore
    field names are rejected with "must not use names with leading
    underscores"."""
    assert pg.safe_field_name("404") == ("f_404", True)


def test_safe_field_name_handles_empty_input():
    safe, alias = pg.safe_field_name("")
    assert safe == "field"
    assert alias is True


def test_safe_field_name_strips_leading_dollar_for_socrata_soql_params():
    """``$select`` → ``select`` (with alias ``$select``) — the leading
    underscore that ``re.sub`` would otherwise produce trips Pydantic's
    "Fields must not use names with leading underscores" check."""
    assert pg.safe_field_name("$select") == ("select", True)


def test_safe_field_name_strips_leading_underscore_from_already_underscore_name():
    """An already-underscore-prefixed name (rare in practice) loses the
    underscore so the result is Pydantic-compatible."""
    assert pg.safe_field_name("_internal") == ("internal", True)


def test_safe_field_name_appends_underscore_for_keyword():
    assert pg.safe_field_name("class") == ("class_", True)


def test_safe_field_name_appends_underscore_for_pydantic_reserved():
    assert pg.safe_field_name("model_config") == ("model_config_", True)


def test_class_name_from_camel_cases_dotted_path():
    assert pg.class_name_from("equity.price.quote", "Data") == "EquityPriceQuoteData"


def test_class_name_from_drops_falsy_parts():
    assert pg.class_name_from("", "law", None) == "Law"  # type: ignore[arg-type]


def test_class_name_from_handles_only_special_chars():
    assert pg.class_name_from("---") == "Anonymous"


def test_class_name_from_prefixes_leading_digit():
    """Names starting with a digit get an underscore prefix to be valid identifiers."""
    out = pg.class_name_from("123start")
    assert out.startswith("_")
    assert out.isidentifier()


# --- schema_to_type primitive coverage ---


@pytest.mark.parametrize(
    "schema,expected",
    [
        ({"type": "string"}, "str"),
        ({"type": "integer"}, "int"),
        ({"type": "number"}, "float"),
        ({"type": "boolean"}, "bool"),
    ],
)
def test_schema_to_type_primitives(schema, expected):
    nested: list = []
    imports: set[str] = set()
    out = pg.schema_to_type(
        schema,
        parent_class_name="P",
        field_name="x",
        nested_classes=nested,
        imports=imports,
    )
    assert out == expected


def test_schema_to_type_string_date_format_emits_date_import():
    nested: list = []
    imports: set[str] = set()
    out = pg.schema_to_type(
        {"type": "string", "format": "date"},
        parent_class_name="P",
        field_name="x",
        nested_classes=nested,
        imports=imports,
    )
    assert out == "datetime.date"
    assert "import datetime" in imports


def test_schema_to_type_string_datetime_format_emits_datetime_import():
    imports: set[str] = set()
    out = pg.schema_to_type(
        {"type": "string", "format": "date-time"},
        parent_class_name="P",
        field_name="x",
        nested_classes=[],
        imports=imports,
    )
    assert out == "datetime.datetime"
    assert "import datetime" in imports


def test_schema_to_type_unknown_type_falls_back_to_any():
    imports: set[str] = set()
    out = pg.schema_to_type(
        {},
        parent_class_name="P",
        field_name="x",
        nested_classes=[],
        imports=imports,
    )
    assert out == "Any"
    assert "from typing import Any" in imports


def test_schema_to_type_treats_non_dict_as_any():
    """Defensive: a stray list / string in the schema doesn't crash."""
    imports: set[str] = set()
    out = pg.schema_to_type(
        "not-a-schema",
        parent_class_name="P",
        field_name="x",
        nested_classes=[],
        imports=imports,
    )
    assert out == "Any"


def test_schema_to_type_ref_cycle_collapses_to_dict():
    """A ``$ref`` left over from cycle detection becomes ``dict[str, Any]``."""
    imports: set[str] = set()
    out = pg.schema_to_type(
        {"$ref": "#/components/schemas/Tree"},
        parent_class_name="P",
        field_name="x",
        nested_classes=[],
        imports=imports,
    )
    assert out == "dict[str, Any]"


# --- enum / const ---


def test_schema_to_type_enum_returns_literal_with_typing_import():
    """``enum`` resolves to ``Literal[...]`` — ``generate_class`` later
    appends ``| None`` for optional fields (default=None) so the field
    accepts the choices or the omit/None case (no filter applied)."""
    imports: set[str] = set()
    out = pg.schema_to_type(
        {"type": "string", "enum": ["buy", "sell"]},
        parent_class_name="P",
        field_name="x",
        nested_classes=[],
        imports=imports,
    )
    assert out == "Literal['buy', 'sell']"
    assert "from typing import Literal" in imports


def test_schema_to_type_enum_emits_literal_when_type_omitted():
    """Spec authors sometimes omit ``type`` next to ``enum``; the values
    drive the Literal regardless."""
    imports: set[str] = set()
    out = pg.schema_to_type(
        {"enum": [1, 2, 3]},
        parent_class_name="P",
        field_name="n",
        nested_classes=[],
        imports=imports,
    )
    assert out == "Literal[1, 2, 3]"


def test_schema_to_type_const_returns_single_member_literal():
    imports: set[str] = set()
    out = pg.schema_to_type(
        {"type": "string", "const": "fred"},
        parent_class_name="P",
        field_name="x",
        nested_classes=[],
        imports=imports,
    )
    assert out == "Literal['fred']"


def test_schema_to_type_const_emits_literal_from_value_alone():
    """``const`` without an explicit ``type`` still emits ``Literal[<value>]``."""
    imports: set[str] = set()
    out = pg.schema_to_type(
        {"const": 42},
        parent_class_name="P",
        field_name="x",
        nested_classes=[],
        imports=imports,
    )
    assert out == "Literal[42]"


# --- arrays ---


def test_schema_to_type_array_of_strings():
    out = pg.schema_to_type(
        {"type": "array", "items": {"type": "string"}},
        parent_class_name="P",
        field_name="x",
        nested_classes=[],
        imports=set(),
    )
    assert out == "list[str]"


def test_schema_to_type_array_with_no_items_falls_back_to_any():
    out = pg.schema_to_type(
        {"type": "array"},
        parent_class_name="P",
        field_name="x",
        nested_classes=[],
        imports=set(),
    )
    assert out == "list[Any]"


# --- unions ---


def test_schema_to_type_optional_collapses_to_pipe_none():
    out = pg.schema_to_type(
        {"anyOf": [{"type": "string"}, {"type": "null"}]},
        parent_class_name="P",
        field_name="x",
        nested_classes=[],
        imports=set(),
    )
    assert out == "str | None"


def test_schema_to_type_union_of_two_types():
    out = pg.schema_to_type(
        {"anyOf": [{"type": "string"}, {"type": "integer"}]},
        parent_class_name="P",
        field_name="x",
        nested_classes=[],
        imports=set(),
    )
    assert out == "str | int"


def test_schema_to_type_union_dedupes_repeated_branches():
    """``anyOf: [str, str]`` → ``str``, not ``str | str``."""
    out = pg.schema_to_type(
        {"anyOf": [{"type": "string"}, {"type": "string"}]},
        parent_class_name="P",
        field_name="x",
        nested_classes=[],
        imports=set(),
    )
    assert out == "str"


def test_schema_to_type_union_only_null_falls_back_to_any():
    out = pg.schema_to_type(
        {"anyOf": [{"type": "null"}]},
        parent_class_name="P",
        field_name="x",
        nested_classes=[],
        imports=set(),
    )
    assert out == "Any"


def test_schema_to_type_oneof_treated_same_as_anyof():
    out = pg.schema_to_type(
        {"oneOf": [{"type": "string"}, {"type": "null"}]},
        parent_class_name="P",
        field_name="x",
        nested_classes=[],
        imports=set(),
    )
    assert out == "str | None"


# --- nested objects ---


def test_schema_to_type_object_with_properties_creates_nested_class():
    nested: list = []
    out = pg.schema_to_type(
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "title": "Inner",
        },
        parent_class_name="Outer",
        field_name="security",
        nested_classes=nested,
        imports=set(),
    )
    assert out == "Inner"
    assert len(nested) == 1
    assert nested[0].name == "Inner"
    assert "name: str | None" in nested[0].source


def test_schema_to_type_object_without_title_derives_name_from_parent_field():
    """Anonymous nested object names come from ``<parent><field>`` Camel."""
    nested: list = []
    out = pg.schema_to_type(
        {"type": "object", "properties": {"v": {"type": "integer"}}},
        parent_class_name="Wrapper",
        field_name="payload",
        nested_classes=nested,
        imports=set(),
    )
    assert out == "WrapperPayload"
    assert nested[0].name == "WrapperPayload"


def test_schema_to_type_open_object_falls_back_to_dict_any():
    """``additionalProperties: true`` with no properties → ``dict[str, Any]``."""
    imports: set[str] = set()
    out = pg.schema_to_type(
        {"type": "object", "additionalProperties": True},
        parent_class_name="P",
        field_name="x",
        nested_classes=[],
        imports=imports,
    )
    assert out == "dict[str, Any]"


def test_schema_to_type_typed_additional_properties_keeps_value_type():
    """``additionalProperties: {"type": "number"}`` → ``dict[str, float]``."""
    out = pg.schema_to_type(
        {"type": "object", "additionalProperties": {"type": "number"}},
        parent_class_name="P",
        field_name="coeffs",
        nested_classes=[],
        imports=set(),
    )
    assert out == "dict[str, float]"


def test_schema_to_type_nested_typed_additional_properties():
    """``dict[str, dict[str, float]]`` — confidence-interval style."""
    out = pg.schema_to_type(
        {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "additionalProperties": {"type": "number"},
            },
        },
        parent_class_name="P",
        field_name="conf_int",
        nested_classes=[],
        imports=set(),
    )
    assert out == "dict[str, dict[str, float]]"


# --- generate_class ---


def test_generate_class_required_and_optional_fields():
    schema = {
        "type": "object",
        "required": ["symbol"],
        "properties": {
            "symbol": {"type": "string", "description": "Ticker."},
            "limit": {"type": "integer", "default": 5, "description": "Page size."},
            "label": {"type": "string", "description": "Pretty label."},
        },
    }
    cls = pg.generate_class(schema, class_name="Quote")
    src = cls.source
    assert "class Quote(BaseModel):" in src
    assert "symbol: str = Field(description='Ticker.')" in src
    assert "limit: int | None = Field(default=5, description='Page size.')" in src
    assert "label: str | None = Field(default=None, description='Pretty label.')" in src


def test_generate_class_normalized_nullable_fields_keep_format_and_enum():
    """The 3.1 chain end-to-end: ``expand_type_arrays`` copies siblings into
    ``anyOf`` variants, so nullable date/enum fields type as ``datetime.date``
    / ``Literal`` — not ``str``. Guards against a bare-variant normalizer
    (one that emits ``{"type": t}`` only) ever reappearing upstream."""
    from openbb_cli.dispatchers.openapi_schema import expand_type_arrays

    schema = expand_type_arrays(
        {
            "type": "object",
            "properties": {
                "date": {"type": ["string", "null"], "format": "date"},
                "rating": {"type": ["string", "null"], "enum": ["AAA", "AA"]},
                "close": {"type": ["number", "null"]},
            },
        }
    )
    cls = pg.generate_class(schema, class_name="Row")
    src = cls.source
    assert "date: datetime.date | None" in src
    assert "rating: Literal['AAA', 'AA'] | None" in src
    assert "close: float | None" in src
    assert "import datetime" in cls.collect_imports()


def test_generate_class_field_alias_for_dotted_property_name():
    schema = {
        "type": "object",
        "properties": {"X-API-Key": {"type": "string"}},
    }
    cls = pg.generate_class(schema, class_name="Headers")
    assert "X_API_Key:" in cls.source
    assert "alias='X-API-Key'" in cls.source


def test_generate_class_no_properties_emits_pass_body():
    cls = pg.generate_class({"type": "object"}, class_name="Empty")
    assert "    pass" in cls.source


def test_generate_class_uses_provided_docstring_summary():
    cls = pg.generate_class(
        {"type": "object", "properties": {"x": {"type": "string"}}},
        class_name="C",
        docstring="Custom docs.",
    )
    # Summary appears at the top of the Numpy-style block
    assert '"""Custom docs.' in cls.source


def test_generate_class_falls_back_to_class_name_when_no_docstring():
    """Summary defaults to the bare class name when the schema has none."""
    cls = pg.generate_class(
        {"type": "object", "properties": {"x": {"type": "string"}}},
        class_name="C",
    )
    assert '"""C.' in cls.source


def test_generate_class_emits_numpy_parameters_block():
    """Each field appears in the Numpy ``Parameters`` block with type + description."""
    schema = {
        "type": "object",
        "required": ["symbol"],
        "properties": {
            "symbol": {"type": "string", "description": "Ticker."},
            "limit": {"type": "integer", "default": 5, "description": "Page size."},
        },
    }
    cls = pg.generate_class(schema, class_name="Quote")
    src = cls.source
    assert "Parameters" in src
    assert "----------" in src
    # Required field: bare type
    assert "symbol : str" in src
    # Optional field: ``, optional`` suffix + default in description
    assert "limit : int, optional" in src
    assert "(default: 5)" in src


def test_generate_class_docstring_summary_gets_trailing_period():
    """A summary without a trailing ``.`` has one added — matches D415."""
    cls = pg.generate_class(
        {"type": "object", "properties": {"x": {"type": "string"}}},
        class_name="C",
        docstring="Custom docs",
    )
    assert '"""Custom docs.' in cls.source


def test_generate_class_docstring_field_with_no_description_omits_body_line():
    """A field with no description renders as ``name : type`` only."""
    cls = pg.generate_class(
        {"type": "object", "properties": {"x": {"type": "string"}}},
        class_name="C",
    )
    block = cls.source.split('"""')[1]
    assert "x : str, optional" in block
    lines = block.split("\n")
    x_idx = next(i for i, line in enumerate(lines) if "x : str" in line)
    next_line = lines[x_idx + 1] if x_idx + 1 < len(lines) else ""
    assert next_line.strip() != "."


def test_generate_class_handles_nested_object_via_separate_class():
    """A plain nested object becomes its own ``BaseModel`` class so Pydantic
    can recursively validate the runtime row."""
    schema = {
        "type": "object",
        "properties": {
            "inner": {
                "type": "object",
                "title": "Inner",
                "properties": {"v": {"type": "integer"}},
            }
        },
    }
    cls = pg.generate_class(schema, class_name="Outer")
    assert cls.nested
    assert cls.nested[0].name == "Inner"
    assert "inner: Inner | None" in cls.source


def test_generate_class_handles_deep_nesting_via_flatten():
    """Nested → nested objects all show up in topological order in ``flatten``."""
    schema = {
        "type": "object",
        "properties": {
            "a": {
                "type": "object",
                "title": "A",
                "properties": {
                    "b": {
                        "type": "object",
                        "title": "B",
                        "properties": {"v": {"type": "integer"}},
                    }
                },
            }
        },
    }
    cls = pg.generate_class(schema, class_name="Root")
    flat = cls.flatten()
    names = [c.name for c in flat]
    # B comes before A because A depends on B; Root last because it depends on A
    assert names.index("B") < names.index("A")
    assert names.index("A") < names.index("Root")


def test_generate_class_collect_imports_unions_descendants():
    schema = {
        "type": "object",
        "properties": {
            "when": {"type": "string", "format": "date"},
            "limit": {"type": "integer"},
        },
    }
    cls = pg.generate_class(schema, class_name="C")
    imports = cls.collect_imports()
    assert "import datetime" in imports
    assert "from pydantic import BaseModel, Field" in imports


def test_generate_class_array_of_objects_emits_nested_item_class():
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "title": "Item",
                    "properties": {"id": {"type": "integer"}},
                },
            }
        },
    }
    cls = pg.generate_class(schema, class_name="List")
    assert any(c.name == "Item" for c in cls.nested)
    assert "items: list[Item]" in cls.source


# --- render_module ---


def test_render_module_emits_imports_then_classes_in_topological_order():
    schema = {
        "type": "object",
        "title": "Outer",
        "properties": {
            "inner": {
                "type": "object",
                "title": "Inner",
                "properties": {"x": {"type": "integer"}},
            }
        },
    }
    cls = pg.generate_class(schema, class_name="Outer")
    rendered = pg.render_module(cls, module_docstring="Generated module.")
    # Docstring at the top (single-line form is fine, just must be present first)
    assert rendered.lstrip().startswith(("'", '"'))
    assert "Generated module." in rendered.split("\n", 3)[0]
    # Inner class defined before Outer
    assert rendered.index("class Inner") < rendered.index("class Outer")
    # Pydantic import present
    assert "from pydantic import BaseModel, Field" in rendered


def test_render_module_compiles_to_valid_python():
    """The emitted source actually parses and produces working Pydantic models."""
    import ast
    import importlib.util
    import sys
    import textwrap

    schema = {
        "type": "object",
        "required": ["symbol"],
        "properties": {
            "symbol": {"type": "string"},
            "side": {"type": "string", "enum": ["buy", "sell"]},
            "qty": {"type": "integer", "default": 1},
            "tags": {"type": "array", "items": {"type": "string"}},
            "when": {"type": "string", "format": "date-time"},
            "details": {
                "type": "object",
                "title": "Details",
                "properties": {"note": {"type": "string"}},
            },
            "freeform": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
        },
    }
    cls = pg.generate_class(schema, class_name="Order")
    rendered = pg.render_module(cls)
    # 1. parses
    ast.parse(rendered)
    # 2. evaluating it produces a real Pydantic class with the expected fields
    spec = importlib.util.spec_from_loader("generated_test_mod", loader=None)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["generated_test_mod"] = mod
    try:
        exec(textwrap.dedent(rendered), mod.__dict__)  # noqa: S102 — controlled source
        Order = mod.Order
        instance = Order(symbol="AAPL", side="buy", details={"note": "x"})
        assert instance.symbol == "AAPL"
        assert instance.side == "buy"
        assert instance.qty == 1
        assert instance.details.note == "x"
    finally:
        sys.modules.pop("generated_test_mod", None)


@pytest.mark.parametrize(
    "default,expected",
    [
        (True, "True"),
        (False, "False"),
        (42, "42"),
        (1.5, "1.5"),
        ("text", "'text'"),
        (None, "None"),
        ([1, 2], "[1, 2]"),
        ((1, 2), "(1, 2)"),
        ({"k": "v"}, "{'k': 'v'}"),
        (object(), "<"),  # Falls through to repr() for unknown types
    ],
)
def test_render_field_default_covers_every_branch(default, expected):
    """Every literal branch in ``render_field_default`` round-trips correctly."""
    out = pg.render_field_default(default)
    assert expected in out


def test_python_string_literal_handles_multiline_text():
    """Multi-line text uses triple-quoted form."""
    out = pg._python_string_literal("line one\nline two")
    assert out.startswith('"""')
    assert out.endswith('"""')
    assert "line one" in out
    assert "line two" in out


def test_python_string_literal_escapes_embedded_triple_quotes():
    """A description containing ``\"\"\"`` mustn't break the literal."""
    out = pg._python_string_literal('contains """ inside\nmore text')
    # The triple quotes inside the string are escaped, not closed
    assert out.count('"""') == 2  # only the opening and closing


def test_generate_class_optional_field_emits_default_none_with_empty_description():
    """Optional field with no spec text emits ``description=''`` (not omitted) so
    openbb-core's DocstringGenerator doesn't render the literal string ``"None"``."""
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    cls = pg.generate_class(schema, class_name="C")
    assert "x: str | None = Field(default=None, description='')" in cls.source


def test_generate_class_uses_triple_quoted_docstring_for_multiline():
    """A multi-line docstring lands as a triple-quoted block."""
    cls = pg.generate_class(
        {"type": "object", "properties": {"x": {"type": "string"}}},
        class_name="C",
        docstring="line one\nline two",
    )
    assert '"""' in cls.source
    assert "line two" in cls.source


# --- render_function_docstring ---


def test_render_function_docstring_minimum_summary_only():
    out = pg.render_function_docstring("Fetch the data")
    assert out == '    """Fetch the data.\n    """'


def test_render_function_docstring_summary_keeps_existing_period():
    out = pg.render_function_docstring("Already punctuated.")
    assert "Already punctuated." in out
    # No double period
    assert "..\n" not in out


def test_render_function_docstring_emits_parameters_section():
    out = pg.render_function_docstring(
        "Send a request",
        parameters=[
            ("query", "QueryParams", "Validated query parameters."),
            ("credentials", "dict[str, str] | None", None),
        ],
    )
    assert "Parameters" in out
    assert "----------" in out
    assert "query : QueryParams" in out
    assert "        Validated query parameters." in out
    assert "credentials : dict[str, str] | None" in out
    cred_idx = out.index("credentials :")
    after = out[cred_idx:]
    next_line = after.split("\n", 2)[1] if "\n" in after else ""
    assert next_line.strip() != "."


def test_render_function_docstring_emits_returns_section():
    out = pg.render_function_docstring(
        "Build something",
        returns=("BillData", "The fetched bill record."),
    )
    assert "Returns" in out
    assert "-------" in out
    assert "BillData" in out
    assert "        The fetched bill record." in out


def test_render_function_docstring_returns_section_with_no_description():
    out = pg.render_function_docstring(
        "Build something",
        returns=("int", None),
    )
    assert "Returns" in out
    assert "int" in out
    assert "        ." not in out


def test_render_function_docstring_custom_indent_for_nested_definitions():
    """Method docstrings indent by 8 spaces (4 for class + 4 for method body)."""
    out = pg.render_function_docstring("Nested method.", indent="        ")
    assert out.startswith('        """')


# --- _annotation_for_docstring ---


def test_annotation_for_docstring_strips_pipe_none():
    assert pg._annotation_for_docstring("str | None") == ("str", True)


def test_annotation_for_docstring_keeps_required_type_intact():
    assert pg._annotation_for_docstring("list[int]") == ("list[int]", False)


def test_render_module_against_real_openbb_response_schema():
    """End-to-end: shape resembling a real OBBject inner data class."""
    import ast

    # Truncated copy of OLSRegressionResults's properties
    schema = {
        "type": "object",
        "title": "OLSRegressionResults",
        "required": ["params", "rsquared", "nobs"],
        "properties": {
            "params": {
                "type": "object",
                "additionalProperties": {"type": "number"},
                "description": "Coefficient estimates.",
            },
            "rsquared": {"type": "number", "description": "R-squared."},
            "nobs": {"type": "integer", "description": "Observation count."},
            "fvalue": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "description": "F-statistic.",
            },
        },
    }
    cls = pg.generate_class(schema, class_name="OLSRegressionResults")
    rendered = pg.render_module(cls)
    ast.parse(rendered)
    assert "rsquared: float = Field(description='R-squared.')" in rendered
    assert "fvalue: float | None" in rendered


def test_build_field_call_wraps_when_single_line_exceeds_budget():
    """Lines 355-356: long Field args force the multi-line wrap path."""
    long_description = "This is a deliberately verbose description " * 4
    out = pg._build_field_call(
        description=long_description,
        default=None,
        has_default=False,
        required=True,
        alias=None,
        leading_width=20,
    )
    assert out.startswith("Field(\n        ")
    assert out.endswith(",\n    )")


def test_field_falls_back_to_example_when_no_description():
    """Schema with only ``example`` (no ``description``) gets ``"Example: <val>"``
    so the rendered Field / docstring shows useful text instead of ``None``."""
    schema = {
        "type": "object",
        "properties": {"auctionStatus": {"type": "string", "example": "Results"}},
    }
    cls = pg.generate_class(schema, class_name="C")
    src = cls.source
    assert "description='Example: Results.'" in src
    # And the docstring section also picks up the example
    block = src.split('"""')[1]
    assert "Example: Results" in block


def test_field_keeps_description_over_example_when_both_present():
    schema = {
        "type": "object",
        "properties": {
            "x": {"type": "string", "description": "Real description.", "example": "EX"}
        },
    }
    cls = pg.generate_class(schema, class_name="C")
    assert "Real description." in cls.source
    assert "Example: EX" not in cls.source


def test_optional_enum_field_emits_literal_with_optional_none_suffix():
    """``{type: string, enum: [P, S]}`` becomes ``Literal['P', 'S'] | None``
    so Pydantic enforces the choices at construction time. ``None``
    (the default) means "no filter applied"; passing ``'P'`` / ``'S'``
    constrains; passing anything else raises. The openbb-core renderer
    fix in the same change set keeps ``Literal[...] | None`` from
    collapsing to the bogus ``Optional[None]`` in docstrings."""
    schema = {
        "type": "object",
        "properties": {
            "operationDirection": {
                "type": "string",
                "enum": ["P", "S"],
                "example": "P",
            }
        },
    }
    cls = pg.generate_class(schema, class_name="Auction")
    src = cls.source
    assert "operationDirection: Literal['P', 'S'] | None" in src
    # Choices still surface in the description for user-facing context.
    assert "Choices: P, S" in src
    assert "Example: P" in src


def test_field_with_no_description_no_example_emits_empty_description():
    """No spec text -> ``description=''``, not omitted. Empty string keeps
    openbb-core's DocstringGenerator from rendering the literal ``"None"``."""
    schema = {
        "type": "object",
        "properties": {"numDealers": {"type": "integer"}},
    }
    cls = pg.generate_class(schema, class_name="C")
    assert "description=''" in cls.source
    assert "None" not in cls.source.split("class C")[1].split("\n", 5)[0]


def test_render_module_appends_period_to_docstring_summary():
    """Line 681: a docstring without trailing punctuation gets a period."""
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    cls = pg.generate_class(schema, class_name="P")
    rendered = pg.render_module(cls, module_docstring="No trailing period")
    first_line = rendered.split("\n", 1)[0]
    assert first_line == '"""No trailing period."""'


# --- _enum_primitive ---


def test_enum_primitive_renders_string_values_as_literal():
    imports: set[str] = set()
    assert pg._enum_primitive(["A", "B"], None, imports) == "Literal['A', 'B']"
    assert "from typing import Literal" in imports


def test_enum_primitive_renders_numeric_values_as_literal():
    imports: set[str] = set()
    assert pg._enum_primitive([1, 2, 3], None, imports) == "Literal[1, 2, 3]"


def test_enum_primitive_renders_boolean_values_as_literal():
    imports: set[str] = set()
    assert pg._enum_primitive([True, False], None, imports) == "Literal[True, False]"


def test_enum_primitive_falls_back_to_any_for_empty_choice_set():
    """``enum: []`` carries no information — collapse to ``Any`` rather
    than emit a ``Literal[]`` that Pydantic can't construct."""
    imports: set[str] = set()
    out = pg._enum_primitive([], None, imports)
    assert out == "Any"
    assert "from typing import Any" in imports


# --- _build_field_call empty branch ---


def test_build_field_call_returns_empty_when_no_metadata_to_emit():
    """A required field with no description / alias yields no ``Field(...)``
    so the caller drops the trailing ``=`` entirely."""
    out = pg._build_field_call(
        description=None,
        default=None,
        has_default=False,
        required=True,
        alias=None,
        leading_width=10,
    )
    assert out == ""


# --- _nested_object_breakout ---


def test_nested_object_breakout_descends_into_oneof_variant():
    """``{oneOf: [{properties: {...}}]}`` items expose their inner fields."""
    prop = {
        "items": {
            "oneOf": [
                {"properties": {"flag": {"type": "string"}, "id": {"type": "integer"}}}
            ]
        }
    }
    out = pg._nested_object_breakout(prop)
    assert "flag (str)" in out
    assert "id (int)" in out
    assert out.startswith("Inner item fields:")


def test_nested_object_breakout_handles_non_dict_inner_schema():
    """A property whose inner schema is a stray scalar still names the field
    in the breakout — it just can't render a type label for it."""
    prop = {"properties": {"a": "not-a-dict", "b": {"type": "integer"}}}
    out = pg._nested_object_breakout(prop)
    assert "a, b (int)" in out


def test_nested_object_breakout_returns_empty_for_primitive_field():
    """No nested properties anywhere → no breakout to render."""
    assert pg._nested_object_breakout({"type": "string"}) == ""


# --- _quick_schema_type ---


def test_quick_schema_type_returns_str_for_enum():
    """An ``enum`` schema labels the field as ``str`` regardless of declared type."""
    assert pg._quick_schema_type({"enum": ["A", "B"]}) == "str"


def test_quick_schema_type_renders_array_with_inner_type():
    assert pg._quick_schema_type({"type": "array", "items": {"type": "integer"}}) == (
        "list[int]"
    )


def test_quick_schema_type_array_without_items_falls_back_to_any():
    assert pg._quick_schema_type({"type": "array"}) == "list[Any]"


def test_quick_schema_type_recurses_into_nested_array():
    assert (
        pg._quick_schema_type(
            {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}
        )
        == "list[list[str]]"
    )


def test_quick_schema_type_renders_date_format():
    assert pg._quick_schema_type({"type": "string", "format": "date"}) == "date"


def test_quick_schema_type_renders_datetime_format():
    assert pg._quick_schema_type({"type": "string", "format": "date-time"}) == (
        "datetime"
    )


def test_quick_schema_type_unknown_type_falls_back_to_any():
    """A schema with no ``type`` and no other handled keys collapses to ``Any``."""
    assert pg._quick_schema_type({}) == "Any"


def test_union_of_untitled_object_variants_keeps_distinct_classes():
    schema = {
        "type": "object",
        "properties": {
            "loc": {
                "oneOf": [
                    {"type": "object", "properties": {"type": {"type": "string"}}},
                    {"type": "object", "properties": {"city": {"type": "string"}}},
                ]
            }
        },
    }
    src = pg.render_module(pg.generate_class(schema, class_name="Pt"))
    assert "city:" in src and "type:" in src
    ast.parse(src)
    assert len({line for line in src.splitlines() if line.startswith("class ")}) >= 3
