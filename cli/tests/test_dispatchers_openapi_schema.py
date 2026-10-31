"""Tests for the OpenAPI schema loader.

These exercise the pure-translation layer against synthetic spec fragments —
no live server required. The goal is to lock in the parameter → argparse
mapping behavior so it stays consistent as the CLI grows to consume the spec
from a remote ``openbb-platform-api`` server.
"""

from __future__ import annotations

import argparse

import pytest

from openbb_cli.dispatchers.openapi_schema import (
    _bundle_external_refs,
    _is_json_arg,
    _provider_choices,
    _resolve_schema,
    build_command_index,
    build_parser_from_operation,
    build_reference,
    build_router_map,
    deref_schema,
    expand_type_arrays,
    extract_request_body_schema,
    extract_response_schema,
    merge_allof,
    operation_parameters,
    parameter_to_kwargs,
    parse_json_arg,
    path_item_credential_parameters,
    request_body_parameters,
    url_to_command,
)


def test_resolve_schema_primitive_string():
    assert _resolve_schema({"type": "string"}) == (str, [], False)


def test_resolve_schema_primitive_int():
    assert _resolve_schema({"type": "integer"}) == (int, [], False)


def test_resolve_schema_primitive_number():
    assert _resolve_schema({"type": "number"}) == (float, [], False)


def test_resolve_schema_boolean():
    assert _resolve_schema({"type": "boolean"}) == (bool, [], False)


def test_resolve_schema_enum():
    py_type, choices, is_list = _resolve_schema({"type": "string", "enum": ["a", "b"]})
    assert py_type is str and choices == ["a", "b"] and is_list is False


def test_resolve_schema_array_of_strings():
    py_type, choices, is_list = _resolve_schema(
        {"type": "array", "items": {"type": "string"}}
    )
    assert py_type is str and is_list is True and choices == []


def test_resolve_schema_optional_collapses_to_inner():
    """``anyOf: [{type: string}, {type: null}]`` → str."""
    py_type, _, _ = _resolve_schema({"anyOf": [{"type": "string"}, {"type": "null"}]})
    assert py_type is str


def test_resolve_schema_union_of_str_int_falls_back_to_str():
    py_type, _, _ = _resolve_schema(
        {"anyOf": [{"type": "string"}, {"type": "integer"}]}
    )
    assert py_type is str


def test_resolve_schema_union_of_enums_unions_choices():
    _, choices, _ = _resolve_schema(
        {
            "anyOf": [
                {"type": "string", "enum": ["a", "b"]},
                {"type": "string", "enum": ["b", "c"]},
            ]
        }
    )
    assert set(choices) == {"a", "b", "c"}


def test_resolve_schema_array_in_union_marked_as_list():
    _, _, is_list = _resolve_schema(
        {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]}
    )
    assert is_list is True


def test_resolve_schema_const_treated_as_single_choice():
    py_type, choices, _ = _resolve_schema({"const": "fred"})
    assert py_type is str and choices == ["fred"]


def test_provider_choices_skips_reserved_keys():
    schema = {
        "type": "string",
        "enum": ["a", "b"],
        "default": "a",
        "title": "x",
    }
    assert _provider_choices(schema) == []


def test_provider_choices_unions_per_provider_choices():
    schema = {
        "type": "string",
        "fmp": {"choices": ["1m", "5m"]},
        "yfinance": {"choices": ["5m", "1d"]},
    }
    assert set(_provider_choices(schema)) == {"1m", "5m", "1d"}


def test_parameter_to_kwargs_skips_chart():
    """``chart`` is handled by the output adapter, not the command parser."""
    assert parameter_to_kwargs({"name": "chart", "schema": {"type": "boolean"}}) is None


def test_parameter_to_kwargs_required_string():
    flag, kwargs = parameter_to_kwargs(
        {"name": "symbol", "required": True, "schema": {"type": "string"}}
    )
    assert flag == "--symbol"
    assert kwargs["type"] is str
    assert kwargs.get("required") is True


def test_parameter_to_kwargs_optional_with_default():
    flag, kwargs = parameter_to_kwargs(
        {
            "name": "limit",
            "required": False,
            "schema": {"type": "integer", "default": 10},
        }
    )
    assert flag == "--limit"
    assert kwargs["type"] is int
    assert kwargs["default"] == 10
    assert "required" not in kwargs


def test_parameter_to_kwargs_boolean_flag():
    _, kwargs = parameter_to_kwargs(
        {"name": "verbose", "schema": {"type": "boolean", "default": False}}
    )
    assert kwargs["action"] == "store_true"
    assert kwargs["default"] is False


def test_parameter_to_kwargs_list_uses_nargs_plus():
    _, kwargs = parameter_to_kwargs(
        {
            "name": "symbols",
            "schema": {"type": "array", "items": {"type": "string"}},
        }
    )
    assert kwargs["nargs"] == "+"


def test_parameter_to_kwargs_enum_emits_choices():
    _, kwargs = parameter_to_kwargs(
        {"name": "side", "schema": {"type": "string", "enum": ["buy", "sell"]}}
    )
    assert kwargs["choices"] == ["buy", "sell"]


def test_parameter_to_kwargs_provider_choices_unioned_with_enum():
    """Per-provider ``choices`` are merged with the schema-level enum."""
    _, kwargs = parameter_to_kwargs(
        {
            "name": "interval",
            "schema": {
                "type": "string",
                "enum": ["1m", "5m"],
                "fmp": {"choices": ["5m", "1h"]},
                "yfinance": {"choices": ["1d"]},
            },
        }
    )
    assert set(kwargs["choices"]) == {"1m", "5m", "1h", "1d"}


def test_parameter_to_kwargs_help_percent_escaped():
    """A ``%`` in the description is doubled so argparse's validator accepts it."""
    _, kwargs = parameter_to_kwargs(
        {"name": "x", "description": "100% sure", "schema": {"type": "string"}}
    )
    assert kwargs["help"] == "100%% sure"


def test_parameter_to_kwargs_no_name_returns_none():
    assert parameter_to_kwargs({"schema": {"type": "string"}}) is None


def test_is_json_arg_classifies_non_scalar_shapes():
    """Objects, arrays of objects, and free-form mappings are JSON args."""
    assert _is_json_arg({"type": "object", "properties": {}}) is True
    # A free-form mapping (additionalProperties, no declared type) is a JSON arg.
    assert _is_json_arg({"additionalProperties": {"type": "number"}}) is True
    assert _is_json_arg({"type": "array", "items": {"type": "object"}}) is True
    # ...arrays of scalars and bare scalars are not.
    assert _is_json_arg({"type": "array", "items": {"type": "string"}}) is False
    assert _is_json_arg({"type": "string"}) is False
    assert _is_json_arg({"type": "array", "items": True}) is False
    # An anyOf with any non-scalar member is a JSON arg.
    assert _is_json_arg({"anyOf": [{"type": "string"}, {"type": "object"}]}) is True


def test_parse_json_arg_decodes_and_rejects_bad_json():
    assert parse_json_arg('[{"a": 1}]') == [{"a": 1}]
    with pytest.raises(argparse.ArgumentTypeError):
        parse_json_arg("{not json")


def test_request_body_parameters_flattens_object_properties():
    """Each top-level body property becomes an ``in: body`` parameter."""
    body = {
        "type": "object",
        "required": ["data"],
        "properties": {
            "data": {
                "type": "array",
                "items": {"type": "object", "title": "Datum"},
                "title": "Data",
            },
            "length": {"type": "integer", "default": 14, "description": "count"},
        },
    }
    params = request_body_parameters(body)
    by_name = {p["name"]: p for p in params}
    assert by_name["data"]["in"] == "body"
    assert by_name["data"]["required"] is True
    assert by_name["data"]["_json_arg"] is True  # array of objects
    assert by_name["length"]["required"] is False
    assert by_name["length"]["_json_arg"] is False
    assert by_name["length"]["description"] == "count"
    assert by_name["length"]["schema"]["default"] == 14


def test_request_body_parameters_skips_non_object_or_empty():
    assert request_body_parameters(None) == []
    assert request_body_parameters({}) == []
    assert request_body_parameters({"type": "string"}) == []


def test_request_body_parameters_skips_non_dict_property():
    """A property whose schema isn't a dict is skipped."""
    body = {
        "type": "object",
        "properties": {"good": {"type": "string"}, "bad": "junk"},
    }
    assert [p["name"] for p in request_body_parameters(body)] == ["good"]


def test_build_parser_from_operation_includes_request_body_fields():
    """With ``spec`` supplied, request-body fields surface as command flags."""
    op = {
        "operationId": "sma",
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/SmaQueryParams"}
                }
            }
        },
    }
    spec = {
        "components": {
            "schemas": {
                "SmaQueryParams": {
                    "type": "object",
                    "required": ["data"],
                    "properties": {
                        "data": {"type": "array", "items": {"type": "object"}},
                        "length": {"type": "integer", "default": 14},
                    },
                }
            }
        }
    }
    parser = build_parser_from_operation(op, spec)
    ns = parser.parse_args(["--data", '[{"close": 1}]', "--length", "9"])
    assert ns.data == [{"close": 1}]
    assert ns.length == 9


def test_build_parser_uses_operation_metadata():
    op = {
        "operationId": "my_cmd",
        "description": "Do the thing.",
        "parameters": [
            {"name": "name", "required": True, "schema": {"type": "string"}},
            {"name": "n", "schema": {"type": "integer", "default": 5}},
        ],
    }
    parser = build_parser_from_operation(op)
    assert parser.prog == "my_cmd"
    assert "Do the thing." in (parser.description or "")
    ns = parser.parse_args(["--name", "x", "--n", "7"])
    assert ns.name == "x" and ns.n == 7


def test_build_parser_required_arg_enforced():
    op = {
        "operationId": "x",
        "parameters": [
            {"name": "needed", "required": True, "schema": {"type": "string"}}
        ],
    }
    parser = build_parser_from_operation(op)
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_build_parser_invalid_choice_rejected():
    op = {
        "operationId": "x",
        "parameters": [
            {
                "name": "side",
                "schema": {"type": "string", "enum": ["buy", "sell"]},
            }
        ],
    }
    parser = build_parser_from_operation(op)
    with pytest.raises(SystemExit):
        parser.parse_args(["--side", "hold"])


def test_build_parser_skips_chart_parameter():
    op = {
        "operationId": "x",
        "parameters": [
            {"name": "chart", "schema": {"type": "boolean"}},
            {"name": "symbol", "schema": {"type": "string", "default": "X"}},
        ],
    }
    parser = build_parser_from_operation(op)
    optstrings = {opt for action in parser._actions for opt in action.option_strings}
    assert "--chart" not in optstrings
    assert "--symbol" in optstrings


def test_build_parser_skips_invalid_parameter_silently():
    """Duplicate flags raise ``ArgumentError`` and are skipped — first wins."""
    op = {
        "operationId": "x",
        "parameters": [
            {"name": "dup", "schema": {"type": "string", "default": "first"}},
            {"name": "dup", "schema": {"type": "integer", "default": 99}},
        ],
    }
    parser = build_parser_from_operation(op)
    ns = parser.parse_args([])
    assert ns.dup == "first"


@pytest.mark.parametrize(
    "url, expected",
    [
        ("/api/v1/equity/price/historical", "equity.price.historical"),
        ("/api/v1/commodity/price/spot", "commodity.price.spot"),
        ("/api/v1/economy", "economy"),
        ("/economy/cpi", "economy.cpi"),
    ],
)
def test_url_to_command(url, expected):
    assert url_to_command(url) == expected


def test_url_to_command_custom_prefix():
    assert url_to_command("/api/v2/foo/bar", api_prefix="/api/v2") == "foo.bar"


def test_build_command_index_keyed_by_dotted_path():
    spec = {
        "paths": {
            "/api/v1/equity/price/historical": {
                "get": {
                    "operationId": "eqh",
                    "parameters": [
                        {
                            "name": "symbol",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                }
            }
        }
    }
    index = build_command_index(spec)
    assert "equity.price.historical" in index
    assert isinstance(index["equity.price.historical"], argparse.ArgumentParser)


def test_build_command_index_skips_paths_without_known_method():
    spec = {"paths": {"/api/v1/x": {"delete": {"operationId": "x"}}}}
    assert build_command_index(spec) == {}


def test_build_command_index_uses_post_when_get_missing():
    spec = {
        "paths": {
            "/api/v1/run": {
                "post": {
                    "operationId": "run",
                    "parameters": [{"name": "in", "schema": {"type": "string"}}],
                }
            }
        }
    }
    assert "run" in build_command_index(spec)


def test_build_router_map_classifies_menus_and_commands():
    spec = {
        "paths": {
            "/api/v1/commodity/price/spot": {"get": {"operationId": "x"}},
            "/api/v1/equity/quote": {"get": {"operationId": "y"}},
        }
    }
    out = build_router_map(spec)
    assert out["commodity"] == "menu"
    assert out["commodity.price"] == "menu"
    assert out["commodity.price.spot"] == "command"
    assert out["equity"] == "menu"
    assert out["equity.quote"] == "command"


def test_build_router_map_ignores_paths_without_methods():
    spec = {"paths": {"/api/v1/foo": {}}}
    assert build_router_map(spec) == {}


def test_build_reference_paths_carry_descriptions():
    spec = {
        "paths": {
            "/api/v1/equity/quote": {
                "get": {
                    "operationId": "x",
                    "summary": "Quote",
                    "description": "Get a quote.",
                    "tags": ["equity"],
                }
            }
        },
        "tags": [{"name": "equity", "description": "Equity data."}],
    }
    ref = build_reference(spec)
    assert ref["paths"]["/equity/quote"]["description"] == "Get a quote."
    assert ref["routers"]["/equity/"]["description"] == "Equity data."


def test_build_reference_falls_back_to_summary_when_no_description():
    spec = {
        "paths": {
            "/api/v1/equity/quote": {
                "get": {"operationId": "x", "summary": "Just a quote.", "tags": []}
            }
        }
    }
    assert (
        build_reference(spec)["paths"]["/equity/quote"]["description"]
        == "Just a quote."
    )


def test_build_reference_router_default_description_when_tag_missing():
    spec = {
        "paths": {
            "/api/v1/x/y": {"get": {"operationId": "z", "tags": ["unknown_tag"]}},
        },
        "tags": [],
    }
    ref = build_reference(spec)
    assert ref["routers"]["/x/"]["description"] == ""


def test_resolve_schema_anyof_all_null_returns_str():
    """Edge: ``anyOf: [{type:null}]`` (no non-null types) collapses to str."""
    py_type, choices, is_list = _resolve_schema({"anyOf": [{"type": "null"}]})
    assert py_type is str and choices == [] and is_list is False


def test_resolve_schema_array_in_array_recurses():
    py_type, choices, is_list = _resolve_schema(
        {"type": "array", "items": {"type": "integer", "enum": [1, 2]}}
    )
    assert py_type is int and is_list is True and choices == [1, 2]


def test_resolve_schema_union_skips_duplicate_enum_values():
    """Duplicate enum values across union members are de-duped."""
    _, choices, _ = _resolve_schema(
        {
            "anyOf": [
                {"type": "string", "enum": ["a", "b"]},
                {"type": "string", "enum": ["a", "c"]},
            ]
        }
    )
    assert choices == ["a", "b", "c"]


def test_strip_placeholders_unbalanced_brace_breaks():
    """``{foo without closing brace`` is left untouched (the while loop breaks)."""
    from openbb_cli.dispatchers.openapi_schema import _strip_placeholders

    assert _strip_placeholders("{foo") == "{foo"


def test_strip_placeholders_close_before_open_breaks_loop():
    """``}foo{`` enters the loop (both braces present) but ``find('}', i)`` returns -1."""
    from openbb_cli.dispatchers.openapi_schema import _strip_placeholders

    assert _strip_placeholders("}foo{") == "}foo{"


def test_url_to_command_with_no_prefix_match_uses_full_path():
    """Custom prefix that isn't actually present in the URL → no stripping."""
    from openbb_cli.dispatchers.openapi_schema import url_to_command

    assert url_to_command("/x/y/z", api_prefix="/api/v1") == "x.y.z"


def test_detect_api_prefix_empty_spec_falls_back_to_default():
    from openbb_cli.dispatchers.openapi_schema import detect_api_prefix

    assert detect_api_prefix({}) == "/api/v1"
    assert detect_api_prefix({"paths": {}}) == "/api/v1"


def test_detect_api_prefix_two_paths_diverging_immediately():
    from openbb_cli.dispatchers.openapi_schema import detect_api_prefix

    spec = {"paths": {"/foo/x": {}, "/bar/y": {}}}
    assert detect_api_prefix(spec) == ""


def test_detect_api_prefix_finds_common_segments():
    from openbb_cli.dispatchers.openapi_schema import detect_api_prefix

    spec = {"paths": {"/api/foo/x": {}, "/api/bar/y": {}}}
    assert detect_api_prefix(spec) == "/api"


def test_parse_spec_text_recognizes_json_object():
    from openbb_cli.dispatchers.openapi_schema import _parse_spec_text

    out = _parse_spec_text('{"openapi": "3.0.0"}')
    assert out == {"openapi": "3.0.0"}


def test_parse_spec_text_recognizes_yaml_via_content_type():
    from openbb_cli.dispatchers.openapi_schema import _parse_spec_text

    out = _parse_spec_text("openapi: 3.0.0\npaths: {}", content_type="application/yaml")
    assert out == {"openapi": "3.0.0", "paths": {}}


def test_parse_spec_text_recognizes_yaml_via_heuristic():
    from openbb_cli.dispatchers.openapi_schema import _parse_spec_text

    out = _parse_spec_text("openapi: 3.0.0")
    assert out == {"openapi": "3.0.0"}


def test_parse_spec_text_swagger_heuristic():
    from openbb_cli.dispatchers.openapi_schema import _parse_spec_text

    out = _parse_spec_text("swagger: '2.0'\ninfo:\n  title: x")
    assert out["swagger"] == "2.0"


def test_parse_spec_text_falls_back_to_yaml_when_json_fails():
    """Last-resort branch: not JSON-shape, no content-type hint, no heuristic match."""
    from openbb_cli.dispatchers.openapi_schema import _parse_spec_text

    out = _parse_spec_text("foo: bar")
    assert out == {"foo": "bar"}


def test_parse_spec_text_recognizes_json_array_form():
    """A bare JSON array also goes through the JSON branch."""
    from openbb_cli.dispatchers.openapi_schema import _parse_spec_text

    assert _parse_spec_text("[1, 2]") == [1, 2]


def test_fetch_openapi_default_path_and_user_agent(monkeypatch):
    """Default appends ``/openapi.json`` and merges the default User-Agent."""
    from openbb_cli.dispatchers import openapi_schema

    captured: dict[str, object] = {}

    class _Resp:
        status_code = 200
        text = '{"openapi": "3.0.0"}'
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            return None

    def fake_get(url, *, timeout, follow_redirects, headers, params=None):
        captured["url"] = url
        captured["headers"] = headers
        return _Resp()

    monkeypatch.setattr(openapi_schema.httpx, "get", fake_get)
    out = openapi_schema.fetch_openapi("http://h")
    assert out == {"openapi": "3.0.0"}
    assert captured["url"] == "http://h/openapi.json"
    assert captured["headers"]["User-Agent"] == "openbb-cli/1.0"


def test_fetch_openapi_custom_path_appended(monkeypatch):
    from openbb_cli.dispatchers import openapi_schema

    captured: dict[str, object] = {}

    class _Resp:
        status_code = 200
        text = "{}"
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            return None

    def fake_get(url, *, timeout, follow_redirects, headers, params=None):
        captured["url"] = url
        return _Resp()

    monkeypatch.setattr(openapi_schema.httpx, "get", fake_get)
    openapi_schema.fetch_openapi("http://h/", path="/static/spec.yml")
    assert captured["url"] == "http://h/static/spec.yml"


def test_fetch_openapi_full_url_path_passes_through(monkeypatch):
    """If ``path`` is already absolute, ``base_url`` is ignored."""
    from openbb_cli.dispatchers import openapi_schema

    captured: dict[str, object] = {}

    class _Resp:
        status_code = 200
        text = "{}"
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            return None

    def fake_get(url, *, timeout, follow_redirects, headers, params=None):
        captured["url"] = url
        return _Resp()

    monkeypatch.setattr(openapi_schema.httpx, "get", fake_get)
    openapi_schema.fetch_openapi("http://h", path="https://elsewhere/spec.json")
    assert captured["url"] == "https://elsewhere/spec.json"


def test_resolve_schema_union_with_array_member_marks_is_list():
    """``anyOf: [array, scalar]`` propagates ``is_list=True``."""
    _, _, is_list = _resolve_schema(
        {
            "anyOf": [
                {"type": "array", "items": {"type": "string"}},
                {"type": "string"},
            ]
        }
    )
    assert is_list is True


def test_strip_placeholders_collapses_balanced_braces():
    """``latest.{format}`` → ``latest``."""
    from openbb_cli.dispatchers.openapi_schema import _strip_placeholders

    assert _strip_placeholders("latest.{format}") == "latest"


def test_detect_api_prefix_breaks_when_common_emptied():
    """Three paths whose very first segment differs across them hit the
    ``not common: break`` arm."""
    from openbb_cli.dispatchers.openapi_schema import detect_api_prefix

    spec = {"paths": {"/x/y": {}, "a/y/z": {}, "/x/q": {}}}
    detect_api_prefix(spec)


def test_build_router_map_skips_empty_command():
    """A URL that strips to an empty dotted command is skipped."""
    from openbb_cli.dispatchers.openapi_schema import build_router_map

    spec = {"paths": {"/api/v1": {"get": {"operationId": "x"}}}}
    assert build_router_map(spec) == {}


def test_build_reference_skips_paths_without_known_methods():
    """A path with only DELETE/PUT is not surfaced."""
    from openbb_cli.dispatchers.openapi_schema import build_reference

    spec = {"paths": {"/api/v1/x": {"delete": {"operationId": "x"}}}}
    out = build_reference(spec)
    assert out["paths"] == {}
    assert out["routers"] == {}


def test_build_reference_dedupes_menu_paths():
    """Two paths under the same menu → router entry recorded once."""
    from openbb_cli.dispatchers.openapi_schema import build_reference

    spec = {
        "paths": {
            "/api/v1/equity/quote": {"get": {"operationId": "q", "tags": ["e"]}},
            "/api/v1/equity/profile": {"get": {"operationId": "p", "tags": ["e"]}},
        },
        "tags": [{"name": "e", "description": "Equity."}],
    }
    out = build_reference(spec)
    assert len(out["routers"]) == 1
    assert out["routers"]["/equity/"]["description"] == "Equity."


def test_fetch_openapi_merges_caller_headers(monkeypatch):
    """Caller-supplied headers are merged with the default User-Agent."""
    from openbb_cli.dispatchers import openapi_schema

    captured: dict[str, object] = {}

    class _Resp:
        status_code = 200
        text = "{}"
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            return None

    def fake_get(url, *, timeout, follow_redirects, headers, params=None):
        captured["headers"] = headers
        return _Resp()

    monkeypatch.setattr(openapi_schema.httpx, "get", fake_get)
    openapi_schema.fetch_openapi("http://h", headers={"Authorization": "Bearer x"})
    assert captured["headers"]["User-Agent"] == "openbb-cli/1.0"
    assert captured["headers"]["Authorization"] == "Bearer x"


# --- Provider section parsing ---


def test_parse_provider_sections_separates_tagged_from_untagged():
    from openbb_cli.dispatchers.openapi_schema import parse_provider_sections

    text = (
        "Shared sentence with no tag.;\n    "
        "FMP-only bit. (provider: fmp);\n    "
        "Both intrinio and cboe. (provider: intrinio,cboe)"
    )
    tagged, has_untagged = parse_provider_sections(text)
    assert tagged == {"fmp", "intrinio", "cboe"}
    assert has_untagged is True


def test_parse_provider_sections_all_tagged():
    from openbb_cli.dispatchers.openapi_schema import parse_provider_sections

    text = "X. (provider: cboe);\n    Y. (provider: fmp)"
    tagged, has_untagged = parse_provider_sections(text)
    assert tagged == {"cboe", "fmp"}
    assert has_untagged is False


def test_param_provider_membership_description_takes_priority():
    """When the description has an untagged section, the param applies to ALL."""
    from openbb_cli.dispatchers.openapi_schema import param_provider_membership

    # Schema has explicit per-provider keys EXCLUDING intrinio,
    # but the description has an untagged section → applies to all.
    schema = {
        "type": "string",
        "cboe": {"x": 1},
        "fmp": {"x": 1},
    }
    desc = "Shared description.;\n    Intrinio variant. (provider: intrinio)"
    membership = param_provider_membership(
        schema, desc, providers_set={"cboe", "fmp", "intrinio"}
    )
    # Untagged section signals "shared" → empty list
    assert membership == []


def test_param_provider_membership_returns_only_tagged_when_no_untagged():
    """All sections tagged → return the union (intersected with declared providers)."""
    from openbb_cli.dispatchers.openapi_schema import param_provider_membership

    desc = "X. (provider: cboe);\n    Y. (provider: fmp,unknown_provider)"
    membership = param_provider_membership(
        {}, desc, providers_set={"cboe", "fmp", "intrinio"}
    )
    # unknown_provider drops out (not in declared set), order independent
    assert sorted(membership) == ["cboe", "fmp"]


def test_param_provider_membership_falls_back_to_schema_keys():
    """No description tags → use per-provider schema extension keys."""
    from openbb_cli.dispatchers.openapi_schema import param_provider_membership

    schema = {
        "type": "string",
        "intrinio": {"choices": ["x"]},
    }
    membership = param_provider_membership(
        schema, None, providers_set={"cboe", "intrinio"}
    )
    assert membership == ["intrinio"]


def test_param_provider_membership_falls_back_to_title():
    """Last resort: schema title naming a single provider."""
    from openbb_cli.dispatchers.openapi_schema import param_provider_membership

    schema = {"type": "boolean", "title": "cboe"}
    membership = param_provider_membership(schema, None, providers_set={"cboe", "fmp"})
    assert membership == ["cboe"]


def test_param_provider_membership_returns_empty_for_neutral_param():
    """A param with no signal at all (e.g. the ``provider`` discriminator) is shared."""
    from openbb_cli.dispatchers.openapi_schema import param_provider_membership

    schema = {"type": "string", "title": "Provider"}
    membership = param_provider_membership(schema, None, providers_set={"cboe", "fmp"})
    assert membership == []


# --- Request body schema extraction ---


def test_extract_request_body_schema_returns_inlined_json_schema():
    from openbb_cli.dispatchers.openapi_schema import extract_request_body_schema

    spec = {}
    op = {
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {"x": {"type": "integer"}},
                    }
                }
            }
        }
    }
    schema = extract_request_body_schema(spec, op)
    assert schema == {"type": "object", "properties": {"x": {"type": "integer"}}}


def test_extract_request_body_schema_dereferences_ref():
    from openbb_cli.dispatchers.openapi_schema import extract_request_body_schema

    spec = {
        "components": {
            "schemas": {
                "Body": {"type": "object", "properties": {"y": {"type": "string"}}}
            }
        }
    }
    op = {
        "requestBody": {
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/Body"}}
            }
        }
    }
    schema = extract_request_body_schema(spec, op)
    assert schema["properties"]["y"]["type"] == "string"


def test_extract_request_body_schema_returns_none_when_absent():
    from openbb_cli.dispatchers.openapi_schema import extract_request_body_schema

    assert extract_request_body_schema({}, {}) is None
    assert extract_request_body_schema({}, {"requestBody": {}}) is None


# --- Embedded spec extraction & fetch_openapi fallback ---


def test_find_matching_brace_returns_position_after_close():
    from openbb_cli.dispatchers.openapi_schema import _find_matching_brace

    text = '{"a": {"b": 1}, "c": 2}rest'
    end = _find_matching_brace(text, 0)
    assert text[:end] == '{"a": {"b": 1}, "c": 2}'


def test_find_matching_brace_returns_none_when_unbalanced():
    from openbb_cli.dispatchers.openapi_schema import _find_matching_brace

    assert _find_matching_brace('{"a": 1', 0) is None


def test_find_matching_brace_skips_braces_inside_strings():
    from openbb_cli.dispatchers.openapi_schema import _find_matching_brace

    text = '{"a": "{not-a-brace}"}'
    end = _find_matching_brace(text, 0)
    assert text[:end] == text  # whole thing


def test_find_matching_brace_handles_escaped_quotes():
    from openbb_cli.dispatchers.openapi_schema import _find_matching_brace

    text = r'{"a": "with \"quote\""}rest'
    end = _find_matching_brace(text, 0)
    assert text[:end].endswith('"}')


def test_find_matching_brace_returns_none_when_start_not_brace():
    from openbb_cli.dispatchers.openapi_schema import _find_matching_brace

    assert _find_matching_brace("no brace here", 0) is None


def test_extract_embedded_spec_finds_var_form():
    from openbb_cli.dispatchers.openapi_schema import _extract_embedded_spec

    html = '<html><script>var spec = {"openapi": "3.0.0", "paths": {}};</script></html>'
    spec = _extract_embedded_spec(html)
    assert spec is not None
    assert spec.get("openapi") == "3.0.0"


def test_extract_embedded_spec_finds_window_form():
    from openbb_cli.dispatchers.openapi_schema import _extract_embedded_spec

    html = 'window.spec = {"openapi": "3.0.0"};'
    spec = _extract_embedded_spec(html)
    assert spec is not None


def test_extract_embedded_spec_returns_none_when_object_unbalanced():
    from openbb_cli.dispatchers.openapi_schema import _extract_embedded_spec

    html = "var spec = {oops"
    assert _extract_embedded_spec(html) is None


def test_extract_embedded_spec_skips_non_openapi_objects():
    """A JS object that parses but isn't an OpenAPI spec is rejected."""
    from openbb_cli.dispatchers.openapi_schema import _extract_embedded_spec

    html = 'var spec = {"unrelated": 1};'
    assert _extract_embedded_spec(html) is None


def test_extract_embedded_spec_returns_none_when_no_marker():
    from openbb_cli.dispatchers.openapi_schema import _extract_embedded_spec

    assert _extract_embedded_spec("<html>boring page</html>") is None


def test_fetch_openapi_returns_parsed_json(monkeypatch):
    from openbb_cli.dispatchers import openapi_schema

    captured = {}

    class _R:
        status_code = 200
        text = '{"openapi": "3.0.0", "paths": {}}'
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            pass

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _R()

    monkeypatch.setattr(openapi_schema.httpx, "get", fake_get)
    spec = openapi_schema.fetch_openapi("https://api.example.com")
    assert spec["openapi"] == "3.0.0"
    assert captured["url"].endswith("/openapi.json")


def test_fetch_openapi_falls_back_to_landing_for_embedded(monkeypatch):
    """When ``/openapi.json`` doesn't parse, scrape the landing page for an embedded spec."""
    from openbb_cli.dispatchers import openapi_schema

    class _R:
        status_code = 404
        text = "<html>not here</html>"
        headers = {"content-type": "text/html"}

        def raise_for_status(self):
            raise openapi_schema.httpx.HTTPStatusError(
                "404", request=None, response=None
            )

    class _Landing:
        status_code = 200
        text = 'window.spec = {"openapi": "3.0.0", "paths": {}};'
        headers = {"content-type": "text/html"}

        def raise_for_status(self):
            pass

    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _R() if "openapi.json" in url else _Landing()

    monkeypatch.setattr(openapi_schema.httpx, "get", fake_get)
    spec = openapi_schema.fetch_openapi("https://h.example.com")
    assert spec.get("openapi") == "3.0.0"
    # Tried the JSON endpoint first, then the landing page
    assert any("openapi.json" in u for u in calls)
    assert any(u.endswith("h.example.com/") for u in calls)


# --- Cycle / depth / fallback paths in deref + extractors ---


def test_resolve_ref_returns_empty_for_non_local_refs():
    from openbb_cli.dispatchers.openapi_schema import resolve_ref

    assert resolve_ref({}, "https://other-host/spec#/X") == {}


def test_resolve_ref_returns_empty_when_pointer_missing():
    from openbb_cli.dispatchers.openapi_schema import resolve_ref

    assert resolve_ref({"components": {}}, "#/components/schemas/Missing") == {}


def test_deref_parameter_breaks_ref_cycle():
    """A ``$ref`` cycle resolves to an empty dict instead of recursing forever."""
    from openbb_cli.dispatchers.openapi_schema import deref_parameter

    spec = {
        "components": {
            "parameters": {
                "a": {"$ref": "#/components/parameters/b"},
                "b": {"$ref": "#/components/parameters/a"},
            }
        }
    }
    out = deref_parameter(spec, {"$ref": "#/components/parameters/a"})
    assert out == {}


def test_deref_parameter_resolves_schema_ref():
    from openbb_cli.dispatchers.openapi_schema import deref_parameter

    spec = {"components": {"schemas": {"Limit": {"type": "integer", "minimum": 1}}}}
    out = deref_parameter(
        spec,
        {"name": "limit", "schema": {"$ref": "#/components/schemas/Limit"}},
    )
    assert out["schema"]["type"] == "integer"


def test_deref_schema_returns_node_when_max_depth_zero():
    from openbb_cli.dispatchers.openapi_schema import deref_schema

    sentinel = {"type": "object"}
    assert deref_schema({}, sentinel, max_depth=0) is sentinel


def test_deref_schema_marks_self_reference_with_ref_stub():
    """A schema whose nested ref points back to itself returns ``{"$ref": ref}``."""
    from openbb_cli.dispatchers.openapi_schema import deref_schema

    spec = {
        "components": {
            "schemas": {
                "Tree": {
                    "type": "object",
                    "properties": {"child": {"$ref": "#/components/schemas/Tree"}},
                }
            }
        }
    }
    out = deref_schema(spec, {"$ref": "#/components/schemas/Tree"})
    # The cycle is preserved as a $ref stub on the inner property
    assert out["properties"]["child"] == {"$ref": "#/components/schemas/Tree"}


def test_deref_schema_returns_node_when_ref_unresolvable():
    """Unresolvable ``$ref`` returns the original node, not None."""
    from openbb_cli.dispatchers.openapi_schema import deref_schema

    node = {"$ref": "#/components/schemas/Missing"}
    assert deref_schema({"components": {}}, node) == node


def test_deref_schema_recurses_into_lists():
    from openbb_cli.dispatchers.openapi_schema import deref_schema

    spec = {"components": {"schemas": {"X": {"type": "string"}}}}
    out = deref_schema(spec, [{"$ref": "#/components/schemas/X"}, "raw-string"])
    assert out == [{"type": "string"}, "raw-string"]


def test_deref_response_resolves_ref():
    from openbb_cli.dispatchers.openapi_schema import _deref_response

    spec = {"components": {"responses": {"OK": {"description": "ok", "content": {}}}}}
    out = _deref_response(spec, {"$ref": "#/components/responses/OK"})
    assert out["description"] == "ok"


# --- extract_response_schema branches ---


def test_extract_response_schema_never_uses_an_error_response():
    """4xx/5xx schemas are not row models, and ``default`` is an error catch-all."""
    from openbb_cli.dispatchers.openapi_schema import extract_response_schema

    err = {"content": {"application/json": {"schema": {"type": "object"}}}}
    assert extract_response_schema({}, {"responses": {"418": err}}) is None
    # a redirect-only operation: ``default`` is the error, not the data
    assert (
        extract_response_schema({}, {"responses": {"301": {}, "default": err}}) is None
    )
    # ``default`` is the success response only when it is the sole response
    assert extract_response_schema({}, {"responses": {"default": err}}) == {
        "type": "object"
    }
    # any other 2xx beats ``default``
    ok = {"content": {"application/json": {"schema": {"type": "array"}}}}
    assert extract_response_schema({}, {"responses": {"default": err, "206": ok}}) == {
        "type": "array"
    }


def test_extract_response_schema_falls_back_to_first_content_type():
    """When no JSON content type is offered, the first content-type's schema is used."""
    from openbb_cli.dispatchers.openapi_schema import extract_response_schema

    op = {
        "responses": {"200": {"content": {"text/csv": {"schema": {"type": "string"}}}}}
    }
    schema = extract_response_schema({}, op)
    assert schema == {"type": "string"}


def test_extract_response_schema_returns_none_when_no_schema():
    from openbb_cli.dispatchers.openapi_schema import extract_response_schema

    op = {"responses": {"200": {"content": {"application/json": {}}}}}
    assert extract_response_schema({}, op) is None


def test_extract_response_schema_returns_none_when_no_responses():
    from openbb_cli.dispatchers.openapi_schema import extract_response_schema

    assert extract_response_schema({}, {}) is None


# --- extract_request_body_schema branches ---


def test_extract_request_body_schema_dereferences_request_body_ref():
    """The whole ``requestBody`` may itself be a $ref."""
    from openbb_cli.dispatchers.openapi_schema import extract_request_body_schema

    spec = {
        "components": {
            "requestBodies": {
                "Body": {
                    "content": {"application/json": {"schema": {"type": "object"}}}
                }
            }
        }
    }
    op = {"requestBody": {"$ref": "#/components/requestBodies/Body"}}
    schema = extract_request_body_schema(spec, op)
    assert schema == {"type": "object"}


def test_extract_request_body_schema_falls_back_to_first_content_type():
    from openbb_cli.dispatchers.openapi_schema import extract_request_body_schema

    op = {
        "requestBody": {
            "content": {"multipart/form-data": {"schema": {"type": "object"}}}
        }
    }
    schema = extract_request_body_schema({}, op)
    assert schema == {"type": "object"}


def test_extract_request_body_schema_returns_none_when_schema_missing():
    from openbb_cli.dispatchers.openapi_schema import extract_request_body_schema

    op = {"requestBody": {"content": {"application/json": {}}}}
    assert extract_request_body_schema({}, op) is None


# --- extract_response_schemas branches ---


def test_extract_response_schemas_skips_non_dict_responses():
    from openbb_cli.dispatchers.openapi_schema import extract_response_schemas

    op = {
        "responses": {
            "200": {"content": {"application/json": {"schema": {"type": "object"}}}},
            "default": "not-a-dict",
        }
    }
    out = extract_response_schemas({}, op)
    assert "200" in out
    assert "default" not in out


# --- _extract_embedded_spec marker variants ---


def test_extract_embedded_spec_skips_whitespace_after_marker():
    """Whitespace and newlines between marker and ``{`` are tolerated."""
    from openbb_cli.dispatchers.openapi_schema import _extract_embedded_spec

    html = 'var spec =   \n   {"openapi": "3.0.0"};'
    spec = _extract_embedded_spec(html)
    assert spec is not None


def test_extract_embedded_spec_continues_past_invalid_json_match():
    """A marker followed by invalid JSON doesn't abort — keeps scanning."""
    from openbb_cli.dispatchers.openapi_schema import _extract_embedded_spec

    html = 'var spec = {bad-json};\nwindow.spec = {"openapi": "3.0.0"};'
    spec = _extract_embedded_spec(html)
    assert spec is not None
    assert spec["openapi"] == "3.0.0"


# --- fetch_openapi explicit path / landing fallback raise ---


def test_fetch_openapi_explicit_path_calls_target_url(monkeypatch):
    """An explicit ``path`` is honored — fetched URL is ``base_url + path``."""
    from openbb_cli.dispatchers import openapi_schema

    captured: dict[str, str] = {}

    class _R:
        status_code = 200
        text = '{"openapi": "3.0.0"}'
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            pass

    def fake_get(url, **kw):
        captured["url"] = url
        return _R()

    monkeypatch.setattr(openapi_schema.httpx, "get", fake_get)
    spec = openapi_schema.fetch_openapi("http://h", path="/static/openapi.yml")
    assert spec["openapi"] == "3.0.0"
    assert captured["url"].endswith("/static/openapi.yml")


def test_fetch_openapi_raises_when_no_embedded_spec_and_landing_succeeds(monkeypatch):
    """No-marker landing page → re-raise the original JSON-fetch error."""
    from openbb_cli.dispatchers import openapi_schema

    class _Bad:
        status_code = 404
        text = "<html>nope</html>"
        headers = {"content-type": "text/html"}

        def raise_for_status(self):
            raise openapi_schema.httpx.HTTPStatusError(
                "404", request=None, response=None
            )

    class _Landing:
        status_code = 200
        text = "<html>boring</html>"
        headers = {"content-type": "text/html"}

        def raise_for_status(self):
            pass

    def fake_get(url, **kw):
        return _Bad() if "openapi.json" in url else _Landing()

    monkeypatch.setattr(openapi_schema.httpx, "get", fake_get)
    with pytest.raises(openapi_schema.httpx.HTTPStatusError):
        openapi_schema.fetch_openapi("http://h")


# --- parse_provider_sections empty section ---


def test_parse_provider_sections_skips_empty_sections():
    """Whitespace-only sections (after a trailing separator) are skipped."""
    from openbb_cli.dispatchers.openapi_schema import parse_provider_sections

    text = "Real. (provider: cboe);\n   ;\n    "
    tagged, has_untagged = parse_provider_sections(text)
    assert tagged == {"cboe"}
    assert has_untagged is False


def test_extract_response_schema_returns_none_when_no_schema_in_any_content_type():
    """Content has entries but none expose a schema → None, not crash."""
    from openbb_cli.dispatchers.openapi_schema import extract_response_schema

    op = {
        "responses": {
            "200": {
                "content": {
                    "text/csv": "not-a-dict",
                    "application/x-protobuf": {},
                }
            }
        }
    }
    assert extract_response_schema({}, op) is None


def test_extract_response_schemas_skips_non_dict_media():
    """Inside a per-content-type loop, non-dict media entries are dropped."""
    from openbb_cli.dispatchers.openapi_schema import extract_response_schemas

    op = {
        "responses": {
            "200": {
                "content": {
                    "application/json": {"schema": {"type": "object"}},
                    "broken": "not-a-dict",
                }
            }
        }
    }
    out = extract_response_schemas({}, op)
    assert "application/json" in out["200"]
    assert "broken" not in out["200"]


def test_fetch_openapi_falls_through_to_raise_when_landing_has_no_embedded(monkeypatch):
    """Landing page with no embedded spec re-raises the original openapi.json error."""
    from openbb_cli.dispatchers import openapi_schema

    class _R:
        status_code = 500
        text = "internal"
        headers = {"content-type": "text/html"}

        def raise_for_status(self):
            raise openapi_schema.httpx.HTTPStatusError(
                "500", request=None, response=None
            )

    class _Landing:
        status_code = 200
        text = "<html>nothing useful</html>"
        headers = {"content-type": "text/html"}

        def raise_for_status(self):
            pass

    def fake_get(url, **kw):
        return _R() if "openapi.json" in url else _Landing()

    monkeypatch.setattr(openapi_schema.httpx, "get", fake_get)
    with pytest.raises(openapi_schema.httpx.HTTPStatusError):
        openapi_schema.fetch_openapi("http://h")


def test_fetch_openapi_swallows_initial_parse_error_and_scrapes_landing(monkeypatch):
    """200 with unparsable body → fall through to landing-page scrape."""
    from openbb_cli.dispatchers import openapi_schema

    class _Bad:
        status_code = 200
        text = "{not-valid-json"  # leading { → JSON-only path → JSONDecodeError
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            pass

    class _Landing:
        status_code = 200
        text = 'window.spec = {"openapi": "3.0.0", "paths": {}};'
        headers = {"content-type": "text/html"}

        def raise_for_status(self):
            pass

    def fake_get(url, **kw):
        return _Bad() if "openapi.json" in url else _Landing()

    monkeypatch.setattr(openapi_schema.httpx, "get", fake_get)
    spec = openapi_schema.fetch_openapi("http://h")
    assert spec.get("openapi") == "3.0.0"


def test_fetch_openapi_with_explicit_path_reparses_and_raises(monkeypatch):
    """Explicit ``path`` + unparsable body re-raises after the initial swallow."""
    from openbb_cli.dispatchers import openapi_schema

    class _Bad:
        status_code = 200
        text = "{not-valid-json"
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(openapi_schema.httpx, "get", lambda url, **kw: _Bad())
    with pytest.raises((ValueError,)):  # JSONDecodeError is a ValueError subclass
        openapi_schema.fetch_openapi("http://h", path="/custom.json")


def test_fetch_openapi_final_parse_attempt_runs_when_landing_empty(monkeypatch):
    """Initial parse fails, landing has no embedded spec, no explicit path:
    re-attempt the original parse — which raises again, propagating the error."""
    from openbb_cli.dispatchers import openapi_schema

    class _Bad:
        status_code = 200
        text = "{not-valid-json"
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            pass

    class _Landing:
        status_code = 200
        text = "<html>nothing relevant</html>"
        headers = {"content-type": "text/html"}

        def raise_for_status(self):
            pass

    def fake_get(url, **kw):
        return _Bad() if "openapi.json" in url else _Landing()

    monkeypatch.setattr(openapi_schema.httpx, "get", fake_get)
    with pytest.raises((ValueError,)):
        openapi_schema.fetch_openapi("http://h")


def test_fetch_openapi_rejects_non_dict_body(monkeypatch):
    """A 200 response that parses to a string (not a dict) raises a clear error."""
    from openbb_cli.dispatchers import openapi_schema

    class _Resp:
        status_code = 200
        text = '"hello"'
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            return None

    monkeypatch.setattr(openapi_schema.httpx, "get", lambda *a, **k: _Resp())
    with pytest.raises(ValueError, match="not an OpenAPI document"):
        openapi_schema.fetch_openapi("http://h", path="/swagger/v1/swagger.json")


# --- expand_type_arrays (OpenAPI 3.1 type arrays → anyOf unions) ---


def test_expand_type_arrays_nullable_scalar_becomes_anyof():
    out = expand_type_arrays({"type": ["number", "null"], "description": "px"})
    assert "type" not in out
    assert out["description"] == "px"
    assert out["anyOf"] == [
        {"type": "number", "description": "px"},
        {"type": "null"},
    ]


def test_expand_type_arrays_copies_structural_siblings_into_variants():
    out = expand_type_arrays(
        {"type": ["string", "null"], "format": "date", "enum": ["a", None]}
    )
    non_null = [v for v in out["anyOf"] if v.get("type") != "null"]
    assert non_null == [{"type": "string", "format": "date", "enum": ["a", None]}]


def test_expand_type_arrays_multi_type_union_keeps_every_variant():
    out = expand_type_arrays({"type": ["string", "number", "integer", "null"]})
    assert [v["type"] for v in out["anyOf"]] == [
        "string",
        "number",
        "integer",
        "null",
    ]


def test_expand_type_arrays_leaves_existing_combinators_alone():
    node = {"type": ["string", "null"], "anyOf": [{"type": "string"}]}
    assert expand_type_arrays(node) == node
    one_of = {"type": ["string", "null"], "oneOf": [{"type": "string"}]}
    assert expand_type_arrays(one_of) == one_of


def test_expand_type_arrays_recurses_into_nested_schemas():
    doc = {
        "paths": {
            "/x": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "close": {"type": ["number", "null"]}
                                            },
                                        },
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    out = expand_type_arrays(doc)
    close = out["paths"]["/x"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["items"]["properties"]["close"]
    assert close == {"anyOf": [{"type": "number"}, {"type": "null"}]}


def test_expand_type_arrays_passthrough_for_scalars_and_plain_types():
    assert expand_type_arrays("x") == "x"
    assert expand_type_arrays({"type": "string"}) == {"type": "string"}
    assert expand_type_arrays([{"type": ["integer", "null"]}]) == [
        {"anyOf": [{"type": "integer"}, {"type": "null"}]}
    ]


def test_request_body_parameters_accepts_normalized_nullable_object():
    """A 3.1 nullable-object body still yields body params after normalization."""
    body = expand_type_arrays(
        {
            "type": ["object", "null"],
            "required": ["symbol"],
            "properties": {"symbol": {"type": "string"}},
        }
    )
    assert "type" not in body  # moved into anyOf variants
    params = request_body_parameters(body)
    assert [p["name"] for p in params] == ["symbol"]
    assert params[0]["required"] is True


def test_fetch_openapi_normalizes_type_arrays(monkeypatch):
    from openbb_cli.dispatchers import openapi_schema

    class _R:
        status_code = 200
        text = (
            '{"openapi": "3.1.0", "paths": {"/x": {"get": {"responses": {"200": '
            '{"content": {"application/json": {"schema": '
            '{"type": ["number", "null"]}}}}}}}}}'
        )
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            return None

    monkeypatch.setattr(openapi_schema.httpx, "get", lambda *a, **k: _R())
    spec = openapi_schema.fetch_openapi("https://api.example.com")
    schema = spec["paths"]["/x"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert schema == {"anyOf": [{"type": "number"}, {"type": "null"}]}


def test_fetch_openapi_normalizes_type_arrays_in_embedded_spec(monkeypatch):
    from openbb_cli.dispatchers import openapi_schema

    class _R:
        status_code = 404
        text = "<html>not here</html>"
        headers = {"content-type": "text/html"}

        def raise_for_status(self):
            raise openapi_schema.httpx.HTTPStatusError(
                "404", request=None, response=None
            )

    class _Landing:
        status_code = 200
        text = (
            'window.spec = {"openapi": "3.1.0", "paths": {"/x": {"get": '
            '{"responses": {"200": {"content": {"application/json": {"schema": '
            '{"type": ["string", "null"]}}}}}}}}};'
        )
        headers = {"content-type": "text/html"}

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        openapi_schema.httpx,
        "get",
        lambda url, **k: _R() if "openapi.json" in url else _Landing(),
    )
    spec = openapi_schema.fetch_openapi("https://h.example.com")
    schema = spec["paths"]["/x"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert schema == {"anyOf": [{"type": "string"}, {"type": "null"}]}


# --- literal dots inside URL segments ---


def test_url_to_command_sanitizes_literal_dots_in_segments():
    assert (
        url_to_command("/v1.1/fundamentals/{ticker}", api_prefix="")
        == "v1_1.fundamentals"
    )


def test_build_reference_sanitizes_dotted_segments_to_match_router_map():
    spec = {
        "paths": {
            "/v1.1/fundamentals/{ticker}": {"get": {"summary": "F"}},
            "/v1.1/bulk": {"get": {"summary": "B"}},
        }
    }
    ref = build_reference(spec, api_prefix="")
    assert "/v1_1/fundamentals" in ref["paths"]
    assert "/v1_1/bulk" in ref["paths"]
    assert "/v1_1/" in ref["routers"]


# --- _bundle_external_refs (same-origin modular spec resolution) ---


def test_bundle_external_refs_resolves_nested_same_origin_documents(monkeypatch):
    from openbb_cli.dispatchers import openapi_schema

    documents = {
        "https://api.example/spec/paths/items.json": (
            '{"post":{"requestBody":{"content":{"application/json":'
            '{"schema":{"$ref":"../schemas/body.json"}}}}}}'
        ),
        "https://api.example/spec/schemas/body.json": (
            '{"type":["object","null"],"properties":{"symbol":{"type":"string"}}}'
        ),
    }

    class _Response:
        status_code = 200
        headers = {"content-type": "application/json"}
        is_redirect = False
        encoding = "utf-8"

        def __init__(self, url):
            self.url = url
            self.text = documents[url]
            self.content = self.text.encode()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def iter_bytes(self, *, chunk_size):
            assert chunk_size == 64 * 1024
            yield self.content

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        openapi_schema.httpx,
        "stream",
        lambda _method, url, **_kwargs: _Response(url),
    )
    bundled = _bundle_external_refs(
        {"openapi": "3.1.0", "paths": {"/items": {"$ref": "paths/items.json"}}},
        "https://api.example/spec/openapi.json",
        timeout=1,
        headers={},
    )

    schema = bundled["paths"]["/items"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    # ``_ensure_openapi_dict`` normalizes each loaded document, so the 3.1
    # type array arrives as sibling-preserving anyOf variants.
    assert schema["anyOf"] == [
        {"type": "object", "properties": {"symbol": {"type": "string"}}},
        {"type": "null"},
    ]
    assert schema["properties"] == {"symbol": {"type": "string"}}
    assert request_body_parameters(schema)[0]["name"] == "symbol"


def test_bundle_external_refs_rejects_redirects(monkeypatch):
    from openbb_cli.dispatchers import openapi_schema

    class _Redirect:
        status_code = 302
        headers = {"location": "http://169.254.169.254/latest/meta-data"}
        text = ""
        content = b""
        is_redirect = True
        encoding = "utf-8"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(
        openapi_schema.httpx, "stream", lambda *_args, **_kwargs: _Redirect()
    )

    with pytest.raises(ValueError, match="Redirects are not allowed"):
        _bundle_external_refs(
            {"openapi": "3.1.0", "paths": {"/x": {"$ref": "x.json"}}},
            "https://api.example/openapi.json",
            timeout=1,
            headers={},
        )


def test_bundle_external_refs_rejects_oversized_content_length(monkeypatch):
    from openbb_cli.dispatchers import openapi_schema

    class _Oversized:
        status_code = 200
        headers = {"content-length": str(8 * 1024 * 1024 + 1)}
        is_redirect = False
        encoding = "utf-8"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            raise AssertionError("body must not be buffered")

    monkeypatch.setattr(
        openapi_schema.httpx, "stream", lambda *_args, **_kwargs: _Oversized()
    )
    with pytest.raises(ValueError, match="size limit"):
        _bundle_external_refs(
            {"openapi": "3.1.0", "paths": {"/x": {"$ref": "x.json"}}},
            "https://api.example/openapi.json",
            timeout=1,
            headers={},
        )


def test_bundle_external_refs_rejects_oversized_stream(monkeypatch):
    from openbb_cli.dispatchers import openapi_schema

    class _Oversized:
        status_code = 200
        headers = {}
        is_redirect = False
        encoding = "utf-8"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

        def iter_bytes(self, *, chunk_size):
            assert chunk_size == 64 * 1024
            yield b"x" * (8 * 1024 * 1024 + 1)

    monkeypatch.setattr(
        openapi_schema.httpx, "stream", lambda *_args, **_kwargs: _Oversized()
    )
    with pytest.raises(ValueError, match="size limit"):
        _bundle_external_refs(
            {"openapi": "3.1.0", "paths": {"/x": {"$ref": "x.json"}}},
            "https://api.example/openapi.json",
            timeout=1,
            headers={},
        )


def test_bundle_external_refs_rejects_cross_origin_urls():
    with pytest.raises(ValueError, match="same-origin"):
        _bundle_external_refs(
            {
                "openapi": "3.1.0",
                "paths": {"/x": {"$ref": "https://other.example/x.json"}},
            },
            "https://api.example/openapi.json",
            timeout=1,
            headers={},
        )


def test_bundle_external_refs_rejects_resource_identifiers():
    with pytest.raises(ValueError, match="resource identifiers"):
        _bundle_external_refs(
            {"openapi": "3.1.0", "$id": "nested.json", "paths": {}},
            "https://api.example/openapi.json",
            timeout=1,
            headers={},
        )


def test_bundle_external_refs_leaves_type_arrays_to_ingestion_normalization():
    """Bundling only inlines refs — 3.1 type arrays are ``expand_type_arrays``'
    job inside ``_ensure_openapi_dict``, which every fetched document passes
    through before bundling."""
    bundled = _bundle_external_refs(
        {"openapi": "3.1.0", "type": ["integer", "number"], "paths": {}},
        "https://api.example/openapi.json",
        timeout=1,
        headers={},
    )
    assert bundled["type"] == ["integer", "number"]


def test_bundle_external_refs_rejects_schema_ref_siblings(monkeypatch):
    from openbb_cli.dispatchers import openapi_schema

    class _Response:
        status_code = 200
        headers = {"content-type": "application/json"}
        is_redirect = False
        encoding = "utf-8"
        content = b'{"type":"integer"}'

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def iter_bytes(self, *, chunk_size):
            assert chunk_size == 64 * 1024
            yield self.content

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        openapi_schema.httpx, "stream", lambda *_args, **_kwargs: _Response()
    )
    with pytest.raises(ValueError, match="reference siblings"):
        _bundle_external_refs(
            {
                "openapi": "3.1.0",
                "paths": {"/x": {"$ref": "x.json", "minimum": 1}},
            },
            "https://api.example/openapi.json",
            timeout=1,
            headers={},
        )


def test_operation_parameters_returns_own_when_no_path_item_params():
    """Without inherited parameters the operation's own list is returned, dereferenced."""
    op = {"parameters": [{"name": "symbol", "in": "query"}]}
    assert operation_parameters({}, {}, op) == [{"name": "symbol", "in": "query"}]


def test_operation_parameters_inherits_from_path_item():
    """Path-item parameters come first, then the operation's own."""
    path_item = {"parameters": [{"name": "record_id", "in": "path"}]}
    op = {"parameters": [{"name": "symbol", "in": "query"}]}
    assert [p["name"] for p in operation_parameters({}, path_item, op)] == [
        "record_id",
        "symbol",
    ]


def test_operation_parameters_drops_inherited_headers_and_cookies():
    """Headers and cookies are transport concerns, not command arguments."""
    path_item = {
        "parameters": [
            {"name": "x-tenant-id", "in": "header"},
            {"name": "session", "in": "cookie"},
            {"name": "record_id", "in": "path"},
        ]
    }
    assert [p["name"] for p in operation_parameters({}, path_item, {})] == ["record_id"]


def test_operation_parameters_keeps_operation_level_headers():
    """An operation's own header parameter is untouched by the inheritance filter."""
    op = {"parameters": [{"name": "x-request-id", "in": "header"}]}
    path_item = {"parameters": [{"name": "record_id", "in": "path"}]}
    assert [p["name"] for p in operation_parameters({}, path_item, op)] == [
        "record_id",
        "x-request-id",
    ]


def test_operation_parameters_operation_overrides_inherited():
    """An operation parameter replaces an inherited one matching (name, in)."""
    path_item = {"parameters": [{"name": "limit", "in": "query", "required": False}]}
    op = {"parameters": [{"name": "limit", "in": "query", "required": True}]}
    out = operation_parameters({}, path_item, op)
    assert out == [{"name": "limit", "in": "query", "required": True}]


def test_operation_parameters_resolves_refs_on_both_levels():
    """``$ref`` entries are resolved before they are compared or returned."""
    spec = {
        "components": {
            "parameters": {
                "record_id": {"name": "record_id", "in": "path"},
                "symbol": {"name": "symbol", "in": "query"},
            }
        }
    }
    path_item = {"parameters": [{"$ref": "#/components/parameters/record_id"}]}
    op = {"parameters": [{"$ref": "#/components/parameters/symbol"}]}
    assert [p["name"] for p in operation_parameters(spec, path_item, op)] == [
        "record_id",
        "symbol",
    ]


def test_operation_parameters_skips_unresolvable_and_unnamed_entries():
    """Unresolvable refs, non-dicts, and nameless entries are dropped."""
    path_item = {
        "parameters": [
            {"$ref": "#/components/parameters/missing"},
            "not-a-dict",
            {"in": "query"},
            {"name": "record_id", "in": "path"},
        ]
    }
    assert [p["name"] for p in operation_parameters({}, path_item, {})] == ["record_id"]


def test_path_item_credential_parameters_returns_required_header_and_cookie():
    path_item = {
        "parameters": [
            {"name": "xero-tenant-id", "in": "header", "required": True},
            {"name": "xero-session", "in": "cookie", "required": True},
        ]
    }
    out = path_item_credential_parameters({}, path_item)
    assert [p["name"] for p in out] == ["xero-tenant-id", "xero-session"]


def test_path_item_credential_parameters_skips_optional_header_or_cookie():
    """An optional path-item header/cookie has no clear destination; it's dropped."""
    path_item = {
        "parameters": [
            {"name": "If-Modified-Since", "in": "header"},
            {"name": "session", "in": "cookie", "required": False},
        ]
    }
    assert path_item_credential_parameters({}, path_item) == []


def test_path_item_credential_parameters_ignores_path_and_query():
    """Path/query params are ``operation_parameters``'s job, not this one's."""
    path_item = {
        "parameters": [
            {"name": "record_id", "in": "path", "required": True},
            {"name": "page", "in": "query", "required": True},
        ]
    }
    assert path_item_credential_parameters({}, path_item) == []


def test_path_item_credential_parameters_resolves_refs():
    spec = {
        "components": {
            "parameters": {
                "tenant": {
                    "name": "xero-tenant-id",
                    "in": "header",
                    "required": True,
                }
            }
        }
    }
    path_item = {"parameters": [{"$ref": "#/components/parameters/tenant"}]}
    out = path_item_credential_parameters(spec, path_item)
    assert [p["name"] for p in out] == ["xero-tenant-id"]


def test_path_item_credential_parameters_skips_malformed_entries():
    path_item = {
        "parameters": [
            "not-a-dict",
            {"$ref": "#/components/parameters/missing"},
            {"in": "header", "required": True},
        ]
    }
    assert path_item_credential_parameters({}, path_item) == []


def test_build_command_index_inherits_path_item_parameters():
    """The interactive parser also picks up parameters shared by the path item."""
    spec = {
        "paths": {
            "/api/v1/x": {
                "parameters": [
                    {"name": "record_id", "in": "path", "schema": {"type": "string"}}
                ],
                "get": {
                    "operationId": "x",
                    "parameters": [
                        {"name": "symbol", "in": "query", "schema": {"type": "string"}}
                    ],
                },
            }
        }
    }
    parser = build_command_index(spec)["x"]
    dests = {a.dest for a in parser._actions}
    assert "record_id" in dests
    assert "symbol" in dests


def test_build_parser_from_operation_without_spec_ignores_path_item():
    """Called without a spec the parser keeps its previous operation-only behavior."""
    op = {
        "parameters": [{"name": "symbol", "in": "query", "schema": {"type": "string"}}]
    }
    parser = build_parser_from_operation(op)
    assert {a.dest for a in parser._actions} == {"symbol"}


def test_merge_allof_unions_properties_and_required():
    schema = {
        "allOf": [
            {"type": "object", "properties": {"results": {"type": "array"}}},
            {
                "type": "object",
                "properties": {"pageNumber": {"type": "integer"}},
                "required": ["pageNumber"],
            },
        ]
    }
    merged = merge_allof(schema)
    assert merged["type"] == "object"
    assert set(merged["properties"]) == {"results", "pageNumber"}
    assert merged["required"] == ["pageNumber"]


def test_merge_allof_first_member_wins_on_conflict():
    schema = {
        "allOf": [
            {"properties": {"value": {"type": "string"}}},
            {"properties": {"value": {"type": "integer"}}},
        ]
    }
    assert merge_allof(schema)["properties"]["value"] == {"type": "string"}


def test_merge_allof_sibling_keywords_outrank_members():
    schema = {
        "properties": {"value": {"type": "boolean"}},
        "required": ["value"],
        "allOf": [{"properties": {"value": {"type": "string"}}}],
    }
    merged = merge_allof(schema)
    assert merged["properties"]["value"] == {"type": "boolean"}
    assert merged["required"] == ["value"]


def test_merge_allof_nested_inside_properties():
    schema = {
        "type": "object",
        "properties": {
            "row": {
                "allOf": [
                    {"properties": {"a": {"type": "string"}}},
                    {"properties": {"b": {"type": "string"}}},
                ]
            }
        },
    }
    merged = merge_allof(schema)
    assert set(merged["properties"]["row"]["properties"]) == {"a", "b"}


def test_merge_allof_leaves_non_object_compositions_alone():
    # A member carrying its own combinator, or a non-object type, is not a
    # plain intersection of property bags and must not be flattened.
    with_combinator = {
        "allOf": [
            {"properties": {"a": {"type": "string"}}},
            {"oneOf": [{"type": "object"}, {"type": "null"}]},
        ]
    }
    scalar_member = {"allOf": [{"type": "string"}, {"properties": {"a": {}}}]}

    assert merge_allof(with_combinator) == with_combinator
    assert merge_allof(scalar_member) == scalar_member


def test_merge_allof_boolean_member_blocks_merge():
    """A boolean schema member is not a property bag."""
    schema = {"allOf": [True, {"properties": {"a": {"type": "string"}}}]}
    assert merge_allof(schema) == schema


def test_merge_allof_stops_at_max_depth():
    """At zero remaining depth the node is returned unmerged."""
    schema = {"allOf": [{"properties": {"a": {}}}, {"properties": {"b": {}}}]}
    assert merge_allof(schema, max_depth=0) is schema


def test_merge_allof_ignores_schemas_without_allof():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    assert merge_allof(schema) == schema


def test_extract_response_schema_merges_allof_composition():
    spec = {
        "components": {
            "schemas": {
                "Paged": {
                    "type": "object",
                    "properties": {"pageNumber": {"type": "integer"}},
                    "required": ["pageNumber"],
                },
                "Bills": {
                    "allOf": [
                        {
                            "type": "object",
                            "properties": {
                                "results": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/Bill"},
                                }
                            },
                        },
                        {"$ref": "#/components/schemas/Paged"},
                    ]
                },
                "Bill": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                },
            }
        }
    }
    op = {
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/Bills"}
                    }
                }
            }
        }
    }

    schema = extract_response_schema(spec, op)
    assert set(schema["properties"]) == {"results", "pageNumber"}
    assert schema["required"] == ["pageNumber"]
    # The nested reference inside the merged member is still resolved.
    items = schema["properties"]["results"]["items"]
    assert items["properties"]["id"] == {"type": "string"}


def test_extract_request_body_schema_merges_allof_composition():
    spec = {
        "components": {
            "schemas": {
                "Timestamps": {
                    "type": "object",
                    "properties": {"modifiedDate": {"type": "string"}},
                },
                "BillPrototype": {
                    "allOf": [
                        {
                            "type": "object",
                            "properties": {"reference": {"type": "string"}},
                            "required": ["reference"],
                        },
                        {"$ref": "#/components/schemas/Timestamps"},
                    ]
                },
            }
        }
    }
    op = {
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/BillPrototype"}
                }
            }
        }
    }

    schema = extract_request_body_schema(spec, op)
    assert set(schema["properties"]) == {"reference", "modifiedDate"}
    assert schema["required"] == ["reference"]

    # A composition body now flattens into body parameters instead of none.
    names = {p["name"] for p in request_body_parameters(schema)}
    assert names == {"reference", "modifiedDate"}


def test_merge_allof_annotation_keywords_do_not_block_merge():
    # Codat's PagingInfo carries `definitions` alongside its properties. Treating
    # any unrecognized keyword as disqualifying left those compositions unmerged,
    # which is what kept the response model empty.
    schema = {
        "title": "Paged results",
        "x-internal": True,
        "allOf": [
            {"type": "object", "properties": {"results": {"type": "array"}}},
            {
                "title": "Pagination information",
                "properties": {"pageNumber": {"type": "integer"}},
                "definitions": {"links": {"type": "object"}},
                "additionalProperties": False,
            },
        ],
    }
    merged = merge_allof(schema)
    assert set(merged["properties"]) == {"results", "pageNumber"}
    assert merged["type"] == "object"


def test_merge_allof_blocks_on_structural_keywords():
    # enum, const and items are scalar/array constraints, not property bags.
    for blocking in ({"enum": ["a"]}, {"const": 1}, {"items": {"type": "string"}}):
        schema = {"allOf": [{"properties": {"a": {}}}, blocking]}
        assert merge_allof(schema) == schema


def test_merge_allof_leaves_instance_data_untouched():
    """``default`` / ``example`` / ``enum`` hold instance data, not subschemas.

    A default value that happens to contain an ``allOf`` key was rewritten into
    ``{"type": "object"}``, destroying the value.
    """
    schema = {
        "type": "object",
        "properties": {
            "cfg": {
                "type": "object",
                "default": {"allOf": [{"a": 1}, {"b": 2}]},
                "example": {"allOf": [{"p": 1}]},
            },
            "mode": {"type": "string", "enum": [{"allOf": [{"q": 1}]}]},
        },
        "x-vendor": {"allOf": [{"z": 1}, {"w": 2}]},
    }
    merged = merge_allof(schema)

    assert merged["properties"]["cfg"]["default"] == {"allOf": [{"a": 1}, {"b": 2}]}
    assert merged["properties"]["cfg"]["example"] == {"allOf": [{"p": 1}]}
    assert merged["properties"]["mode"]["enum"] == [{"allOf": [{"q": 1}]}]
    assert merged["x-vendor"] == {"allOf": [{"z": 1}, {"w": 2}]}


def test_deref_schema_leaves_instance_data_untouched():
    """A ``$ref`` key inside a default value is a literal, not a reference."""
    spec = {"components": {"schemas": {"Thing": {"type": "integer"}}}}
    node = {
        "type": "object",
        "properties": {
            "payload": {
                "type": "object",
                "default": {"$ref": "#/components/schemas/Thing"},
            },
            "real": {"$ref": "#/components/schemas/Thing"},
        },
        "x-sample": {"$ref": "#/components/schemas/Thing"},
    }
    out = deref_schema(spec, node)

    # The literal survives, the genuine reference resolves.
    assert out["properties"]["payload"]["default"] == {
        "$ref": "#/components/schemas/Thing"
    }
    assert out["x-sample"] == {"$ref": "#/components/schemas/Thing"}
    assert out["properties"]["real"] == {"type": "integer"}


def _serve_documents(monkeypatch, documents):
    from openbb_cli.dispatchers import openapi_schema

    fetched: list[str] = []

    class _Response:
        status_code = 200
        headers = {"content-type": "application/json"}
        is_redirect = False
        encoding = "utf-8"

        def __init__(self, url):
            fetched.append(url)
            self.content = documents[url].encode()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def iter_bytes(self, *, chunk_size):
            yield self.content

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        openapi_schema.httpx,
        "stream",
        lambda _method, url, **_kwargs: _Response(url),
    )
    return fetched


def test_bundle_external_refs_fetches_each_document_once(monkeypatch):
    fetched = _serve_documents(
        monkeypatch,
        {
            "https://api.example/defs.json": '{"a": {"type": "string"}, "b": {"type": "integer"}}'
        },
    )
    bundled = _bundle_external_refs(
        {
            "openapi": "3.1.0",
            "components": {
                "schemas": {
                    "A": {"$ref": "defs.json#/a"},
                    "B": {"$ref": "defs.json#/b"},
                }
            },
        },
        "https://api.example/openapi.json",
        timeout=1,
        headers={},
    )
    assert bundled["components"]["schemas"] == {
        "A": {"type": "string"},
        "B": {"type": "integer"},
    }
    assert fetched == ["https://api.example/defs.json"]


def test_bundle_external_refs_rejects_too_many_documents(monkeypatch):
    documents = {f"https://api.example/d{i}.json": "{}" for i in range(520)}
    _serve_documents(monkeypatch, documents)
    paths = {f"/p{i}": {"$ref": f"d{i}.json"} for i in range(520)}
    with pytest.raises(ValueError, match="document limit"):
        _bundle_external_refs(
            {"openapi": "3.1.0", "paths": paths},
            "https://api.example/openapi.json",
            timeout=1,
            headers={},
        )


def test_bundle_external_refs_rejects_excessive_depth():
    node: dict = {"type": "string"}
    for _ in range(130):
        node = {"nested": node}
    with pytest.raises(ValueError, match="depth limit"):
        _bundle_external_refs(
            {"openapi": "3.1.0", "components": node},
            "https://api.example/openapi.json",
            timeout=1,
            headers={},
        )


def test_bundle_external_refs_rejects_anchor_fragments():
    with pytest.raises(ValueError, match="anchors are not supported"):
        _bundle_external_refs(
            {"openapi": "3.1.0", "paths": {"/x": {"$ref": "x.json#anchor"}}},
            "https://api.example/openapi.json",
            timeout=1,
            headers={},
        )


def test_bundle_external_refs_keeps_circular_references_as_refs(monkeypatch):
    _serve_documents(
        monkeypatch,
        {
            "https://api.example/a.json": '{"child": {"$ref": "b.json"}}',
            "https://api.example/b.json": '{"parent": {"$ref": "a.json"}}',
        },
    )
    bundled = _bundle_external_refs(
        {"openapi": "3.1.0", "components": {"schemas": {"A": {"$ref": "a.json"}}}},
        "https://api.example/openapi.json",
        timeout=1,
        headers={},
    )
    assert bundled["components"]["schemas"]["A"] == {
        "child": {"parent": {"$ref": "https://api.example/a.json#"}}
    }


def test_bundle_external_refs_returns_non_object_targets_as_is(monkeypatch):
    _serve_documents(
        monkeypatch, {"https://api.example/values.json": '{"items": ["a", "b"]}'}
    )
    bundled = _bundle_external_refs(
        {"openapi": "3.1.0", "x-values": {"$ref": "values.json#/items"}},
        "https://api.example/openapi.json",
        timeout=1,
        headers={},
    )
    assert bundled["x-values"] == ["a", "b"]


def test_resolve_json_pointer_walks_lists_and_unescapes_tokens():
    from openbb_cli.dispatchers.openapi_schema import _resolve_json_pointer

    document = {"a/b": [{"~key": 1}]}
    assert _resolve_json_pointer(document, "/a~1b/0/~0key") == 1


def test_resolve_json_pointer_rejects_relative_and_scalar_paths():
    from openbb_cli.dispatchers.openapi_schema import _resolve_json_pointer

    with pytest.raises(ValueError, match="Unsupported OpenAPI reference fragment"):
        _resolve_json_pointer({"a": 1}, "a")
    with pytest.raises(ValueError, match="Invalid OpenAPI reference fragment"):
        _resolve_json_pointer({"a": 1}, "/a/b")


def test_url_origin_rejects_non_http_urls():
    from openbb_cli.dispatchers.openapi_schema import _url_origin

    with pytest.raises(ValueError, match="Unsupported OpenAPI reference URL"):
        _url_origin("file:///etc/passwd")


def test_request_body_parameters_unwraps_single_object_anyof_member():
    body = {
        "anyOf": [
            {"type": "object", "properties": {"symbol": {"type": "string"}}},
            {"type": "null"},
        ]
    }
    assert [p["name"] for p in request_body_parameters(body)] == ["symbol"]


def test_fetch_openapi_raises_generic_error_when_response_has_no_parse_error(
    monkeypatch,
):
    """A failing status that ``raise_for_status`` lets through still raises."""
    from openbb_cli.dispatchers import openapi_schema

    class _Resp:
        status_code = 404
        text = "{}"
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            return None

    monkeypatch.setattr(openapi_schema.httpx, "get", lambda *a, **k: _Resp())
    with pytest.raises(ValueError, match="Could not load an OpenAPI document"):
        openapi_schema.fetch_openapi("http://h", path="/custom.json")


def test_url_to_command_drops_placeholder_only_segments():
    from openbb_cli.dispatchers.openapi_schema import url_to_command

    assert (
        url_to_command("/gridpoints/{wfo}/{x},{y}/forecast", api_prefix="")
        == "gridpoints.forecast"
    )
    assert url_to_command("/points/{latitude},{longitude}", api_prefix="") == "points"
