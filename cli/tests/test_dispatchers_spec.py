"""Tests for the precomputed .spec format and command lookup."""

from __future__ import annotations

import json

import pytest

from openbb_cli.dispatchers.spec import (
    SPEC_VERSION,
    SpecCommandError,
    _normalize_parameter,
    build_command_spec,
    build_spec_document,
    command_parameters,
    load_spec,
    parse_command_argv,
    parser_from_command_spec,
    write_spec,
)


def test_normalize_parameter_skips_chart():
    assert (
        _normalize_parameter({"name": "chart", "schema": {"type": "boolean"}}) is None
    )


def test_normalize_parameter_required_string():
    out = _normalize_parameter(
        {"name": "symbol", "required": True, "schema": {"type": "string"}}
    )
    assert out == {
        "name": "symbol",
        "in": "query",
        "type": "string",
        "is_list": False,
        "required": True,
        "default": None,
        "choices": [],
        "example": None,
        "help": None,
        "providers": [],
        "json_arg": False,
    }


def test_normalize_parameter_path_param_is_required_even_without_required_flag():
    """OpenAPI lets ``in: path`` parameters omit ``required: true`` — normalize."""
    out = _normalize_parameter(
        {"name": "operation", "in": "path", "schema": {"type": "string"}}
    )
    assert out["in"] == "path"
    assert out["required"] is True


def test_normalize_parameter_records_query_location_by_default():
    out = _normalize_parameter({"name": "x", "schema": {"type": "string"}})
    assert out["in"] == "query"


def test_normalize_parameter_with_default_not_required():
    """A schema-level default flips ``required`` off — same as argparse semantics."""
    out = _normalize_parameter(
        {
            "name": "limit",
            "required": True,
            "schema": {"type": "integer", "default": 10},
        }
    )
    assert out["required"] is False
    assert out["default"] == 10


def test_normalize_parameter_unions_provider_choices_with_enum():
    out = _normalize_parameter(
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
    assert set(out["choices"]) == {"1m", "5m", "1h", "1d"}


def test_normalize_parameter_array_marked_as_list():
    out = _normalize_parameter(
        {"name": "symbols", "schema": {"type": "array", "items": {"type": "string"}}}
    )
    assert out["is_list"] is True
    assert out["type"] == "string"


def test_normalize_parameter_help_falls_back_to_schema_description():
    out = _normalize_parameter(
        {"name": "x", "schema": {"type": "string", "description": "from schema"}}
    )
    assert out["help"] == "from schema"


def test_build_command_spec_keys_by_dotted_path():
    openapi = {
        "paths": {
            "/api/v1/equity/quote": {
                "get": {
                    "operationId": "eq",
                    "summary": "Quote",
                    "description": "Get quote.",
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
    out = build_command_spec(openapi)
    assert "equity.quote" in out
    entry = out["equity.quote"]
    assert entry["url_path"] == "/api/v1/equity/quote"
    assert entry["method"] == "get"
    assert entry["description"] == "Get quote."
    assert entry["parameters"][0]["name"] == "symbol"


def test_build_command_spec_uses_post_when_get_missing():
    openapi = {"paths": {"/api/v1/x": {"post": {"operationId": "x"}}}}
    assert build_command_spec(openapi)["x"]["method"] == "post"


def test_build_command_spec_skips_other_methods():
    openapi = {"paths": {"/api/v1/x": {"delete": {"operationId": "x"}}}}
    assert build_command_spec(openapi) == {}


def test_build_command_spec_drops_chart_parameter():
    openapi = {
        "paths": {
            "/api/v1/x": {
                "get": {
                    "operationId": "x",
                    "parameters": [
                        {"name": "chart", "schema": {"type": "boolean"}},
                        {"name": "symbol", "schema": {"type": "string"}},
                    ],
                }
            }
        }
    }
    params = build_command_spec(openapi)["x"]["parameters"]
    assert {p["name"] for p in params} == {"symbol"}


def test_build_spec_document_carries_metadata():
    openapi = {
        "paths": {
            "/api/v1/x": {"get": {"operationId": "x", "summary": "X", "tags": ["x"]}}
        },
        "tags": [{"name": "x", "description": "X stuff."}],
    }
    doc = build_spec_document(openapi, base_url="http://h:1/")
    assert doc["version"] == SPEC_VERSION
    assert doc["base_url"] == "http://h:1"
    assert doc["api_prefix"] == "/api/v1"
    assert "x" in doc["commands"]
    assert "x" in doc["routers"]
    assert "/x" in doc["reference"]["paths"]


def test_write_then_load_round_trip(tmp_path):
    openapi = {"paths": {"/api/v1/x": {"get": {"operationId": "x", "parameters": []}}}}
    doc = build_spec_document(openapi, base_url="http://h")
    target = tmp_path / "out.spec"
    write_spec(target, doc)
    loaded = load_spec(target)
    assert loaded["base_url"] == "http://h"
    assert "x" in loaded["commands"]


def test_load_spec_rejects_unknown_version(tmp_path):
    target = tmp_path / "bad.spec"
    target.write_text(json.dumps({"version": SPEC_VERSION + 99, "commands": {}}))
    with pytest.raises(ValueError, match="version"):
        load_spec(target)


def test_build_spec_document_records_provenance():
    openapi = {
        "openapi": "3.1.0",
        "paths": {"/api/v1/x": {"get": {"operationId": "x", "parameters": []}}},
    }
    doc = build_spec_document(
        openapi,
        base_url="http://h",
        source_url="https://example.com/openapi.json",
    )
    assert doc["source_url"] == "https://example.com/openapi.json"
    assert doc["api_version"] == "3.1.0"
    assert doc["generator"].startswith("openbb-cli")
    assert doc["generated_at"]


def test_build_spec_document_falls_back_to_swagger_field():
    """Pre-OpenAPI 3 specs use ``swagger: "2.0"`` instead of ``openapi``."""
    openapi = {"swagger": "2.0", "paths": {}}
    doc = build_spec_document(openapi, base_url="http://h")
    assert doc["api_version"] == "2.0"
    assert doc["source_url"] == ""


def test_normalize_parameter_captures_example_from_param_object():
    out = _normalize_parameter(
        {
            "name": "symbol",
            "required": True,
            "example": "AAPL",
            "schema": {"type": "string"},
        }
    )
    assert out["example"] == "AAPL"


def test_normalize_parameter_captures_example_from_examples_map():
    """OpenAPI 3.x ``examples`` map: pick the first entry's ``value`` field."""
    out = _normalize_parameter(
        {
            "name": "symbol",
            "required": True,
            "examples": {"primary": {"value": "MSFT"}, "alt": {"value": "GOOG"}},
            "schema": {"type": "string"},
        }
    )
    assert out["example"] == "MSFT"


def test_normalize_parameter_captures_example_from_schema_when_param_has_none():
    out = _normalize_parameter(
        {
            "name": "n",
            "required": True,
            "schema": {"type": "integer", "example": 5},
        }
    )
    assert out["example"] == 5


def test_normalize_parameter_promotes_path_number_to_integer():
    """``--number 10`` against ``/last/{number}.{format}`` would otherwise
    cast to ``10.0`` and produce ``/last/10.0.json`` which the API rejects."""
    out = _normalize_parameter(
        {
            "name": "number",
            "in": "path",
            "required": True,
            "schema": {"type": "number"},
        }
    )
    assert out["type"] == "integer"


def test_normalize_parameter_keeps_query_number_as_number():
    """Non-path numerics stay floats — only path placeholders flip to int."""
    out = _normalize_parameter(
        {
            "name": "ratio",
            "in": "query",
            "required": True,
            "schema": {"type": "number"},
        }
    )
    assert out["type"] == "number"


def test_normalize_parameter_examples_map_skips_non_dict_entries():
    out = _normalize_parameter(
        {
            "name": "x",
            "required": True,
            "examples": {"bad": "not a dict", "good": {"value": "ok"}},
            "schema": {"type": "string"},
        }
    )
    assert out["example"] == "ok"


def test_generator_identifier_falls_back_when_package_not_installed(monkeypatch):
    """When ``importlib.metadata.version`` raises, the identifier degrades gracefully."""
    import openbb_cli.dispatchers.spec as spec_mod

    def _raise(_name):
        raise spec_mod.PackageNotFoundError("openbb-cli")

    monkeypatch.setattr(spec_mod, "_pkg_version", _raise)
    assert spec_mod._generator_identifier() == "openbb-cli"


# --- Schema validation ---


def _minimal_valid_spec():
    return {
        "version": SPEC_VERSION,
        "base_url": "https://example.com",
        "api_prefix": "/api",
        "commands": {
            "x.y": {
                "url_path": "/api/x/y",
                "method": "get",
                "description": "X",
                "parameters": [
                    {
                        "name": "symbol",
                        "in": "query",
                        "type": "string",
                        "is_list": False,
                        "required": True,
                        "default": None,
                        "choices": [],
                        "help": "Ticker.",
                        "providers": [],
                    }
                ],
                "providers": [],
            }
        },
        "routers": {},
        "reference": {},
    }


def test_load_spec_accepts_minimal_valid_document(tmp_path):
    target = tmp_path / "ok.spec"
    target.write_text(json.dumps(_minimal_valid_spec()))
    loaded = load_spec(target)
    assert loaded["base_url"] == "https://example.com"
    assert "x.y" in loaded["commands"]


def test_load_spec_rejects_missing_required_top_level_key(tmp_path):
    spec = _minimal_valid_spec()
    del spec["commands"]
    target = tmp_path / "missing.spec"
    target.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="does not conform"):
        load_spec(target)


def test_load_spec_rejects_command_missing_url_path(tmp_path):
    spec = _minimal_valid_spec()
    del spec["commands"]["x.y"]["url_path"]
    target = tmp_path / "bad_cmd.spec"
    target.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="url_path"):
        load_spec(target)


def test_load_spec_rejects_parameter_missing_name(tmp_path):
    spec = _minimal_valid_spec()
    spec["commands"]["x.y"]["parameters"][0].pop("name")
    target = tmp_path / "bad_param.spec"
    target.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="name"):
        load_spec(target)


def test_load_spec_rejects_wrong_type_for_field(tmp_path):
    spec = _minimal_valid_spec()
    spec["base_url"] = 123  # should be a string
    target = tmp_path / "wrong_type.spec"
    target.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="does not conform"):
        load_spec(target)


def test_load_spec_tolerates_unknown_top_level_fields(tmp_path):
    """Forward-compat: extra fields from a newer generator must not break loading."""
    spec = _minimal_valid_spec()
    spec["future_field"] = {"some": "metadata"}
    spec["commands"]["x.y"]["future_command_field"] = "ok"
    target = tmp_path / "future.spec"
    target.write_text(json.dumps(spec))
    loaded = load_spec(target)
    assert loaded["future_field"] == {"some": "metadata"}


def test_round_trip_real_built_spec_validates(tmp_path):
    """A spec produced by ``build_spec_document`` must round-trip through validation."""
    openapi = {
        "openapi": "3.0.0",
        "paths": {
            "/api/v1/x": {
                "get": {
                    "operationId": "x",
                    "parameters": [
                        {
                            "name": "symbol",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                }
            }
        },
    }
    doc = build_spec_document(openapi, base_url="http://h")
    target = tmp_path / "real.spec"
    write_spec(target, doc)
    loaded = load_spec(target)
    assert loaded["commands"]["x"]["url_path"] == "/api/v1/x"


# --- SHA-256 integrity check ---


def test_write_spec_stamps_content_sha256(tmp_path):
    spec = _minimal_valid_spec()
    target = tmp_path / "stamped.spec"
    write_spec(target, spec)
    raw = json.loads(target.read_text())
    assert "content_sha256" in raw
    assert len(raw["content_sha256"]) == 64  # hex-encoded sha256


def test_load_spec_accepts_genuine_hash(tmp_path):
    spec = _minimal_valid_spec()
    target = tmp_path / "ok.spec"
    write_spec(target, spec)
    loaded = load_spec(target)
    assert loaded["content_sha256"]


def test_load_spec_rejects_tampered_content(tmp_path):
    """Hand-edits after generation must trip the integrity check."""
    spec = _minimal_valid_spec()
    target = tmp_path / "tamper.spec"
    write_spec(target, spec)
    raw = json.loads(target.read_text())
    raw["base_url"] = "https://attacker.example"
    target.write_text(json.dumps(raw, separators=(",", ":")))
    with pytest.raises(ValueError, match="failed integrity check"):
        load_spec(target)


def test_load_spec_skips_hash_check_when_field_absent(tmp_path):
    """Specs from older generators predate the hash field — must still load."""
    spec = _minimal_valid_spec()
    target = tmp_path / "legacy.spec"
    target.write_text(json.dumps(spec, separators=(",", ":")))
    loaded = load_spec(target)
    assert loaded.get("content_sha256") is None


def test_content_hash_is_stable_under_unrelated_field_order(tmp_path):
    """Canonical JSON ordering means a re-saved doc with identical content
    must hash identically regardless of original key insertion order."""
    from openbb_cli.dispatchers.spec import _content_hash

    spec_a = {"version": SPEC_VERSION, "base_url": "h", "commands": {}, "x": 1}
    spec_b = {"x": 1, "commands": {}, "base_url": "h", "version": SPEC_VERSION}
    assert _content_hash(spec_a) == _content_hash(spec_b)


def test_write_spec_is_compact(tmp_path):
    """Spec files should be compact (no whitespace) to keep them small on disk."""
    target = tmp_path / "x.spec"
    write_spec(target, {"version": SPEC_VERSION, "commands": {}})
    text = target.read_text()
    assert "\n" not in text
    assert ", " not in text
    assert ": " not in text


def test_parser_from_command_spec_required_arg_enforced():
    cmd_spec = {
        "url_path": "/api/v1/x",
        "method": "get",
        "description": "x",
        "parameters": [
            {
                "name": "symbol",
                "type": "string",
                "is_list": False,
                "required": True,
                "default": None,
                "choices": [],
                "help": None,
            }
        ],
    }
    parser = parser_from_command_spec(cmd_spec)
    with pytest.raises(SystemExit):
        parser.parse_args([])
    ns = parser.parse_args(["--symbol", "AAPL"])
    assert ns.symbol == "AAPL"


def test_command_parameters_fuses_request_body_fields():
    """``command_parameters`` flattens request-body fields into the parameter list."""
    cmd_spec = {
        "url_path": "/api/v1/technical/sma",
        "method": "post",
        "parameters": [],
        "request_body_schema": {
            "type": "object",
            "required": ["data"],
            "properties": {
                "data": {"type": "array", "items": {"type": "object"}},
                "length": {"type": "integer", "default": 14},
            },
        },
    }
    by_name = {p["name"]: p for p in command_parameters(cmd_spec)}
    assert by_name["data"]["in"] == "body"
    assert by_name["data"]["json_arg"] is True
    assert by_name["data"]["type"] == "string"
    assert by_name["length"]["json_arg"] is False
    assert by_name["length"]["type"] == "integer"


def test_parser_from_command_spec_json_arg_decodes_body_fields():
    """``json_arg`` body fields parse their value as a JSON document."""
    cmd_spec = {
        "url_path": "/api/v1/technical/screen",
        "method": "post",
        "parameters": [],
        "request_body_schema": {
            "type": "object",
            "required": ["conditions"],
            "properties": {
                "conditions": {"type": "array", "items": {"type": "object"}},
                "data": {"type": "array", "items": {"type": "object"}},
            },
        },
    }
    parser = parser_from_command_spec(cmd_spec)
    with pytest.raises(SystemExit):
        parser.parse_args([])
    ns = parser.parse_args(
        ["--conditions", '[{"indicator": "rsi"}]', "--data", '[{"close": 1}]']
    )
    assert ns.conditions == [{"indicator": "rsi"}]
    assert ns.data == [{"close": 1}]


def test_parser_from_command_spec_choices_list_default():
    cmd_spec = {
        "url_path": "/api/v1/x",
        "method": "get",
        "description": "",
        "parameters": [
            {
                "name": "interval",
                "type": "string",
                "is_list": False,
                "required": False,
                "default": "1d",
                "choices": ["1m", "5m", "1d"],
                "help": None,
            },
            {
                "name": "symbols",
                "type": "string",
                "is_list": True,
                "required": False,
                "default": None,
                "choices": [],
                "help": None,
            },
        ],
    }
    parser = parser_from_command_spec(cmd_spec)
    ns = parser.parse_args(["--symbols", "A", "B", "C"])
    assert ns.symbols == ["A", "B", "C"]
    assert ns.interval == "1d"
    with pytest.raises(SystemExit):
        parser.parse_args(["--interval", "bogus"])


def test_parser_from_command_spec_boolean_flag():
    cmd_spec = {
        "url_path": "/api/v1/x",
        "method": "get",
        "description": "",
        "parameters": [
            {
                "name": "verbose",
                "type": "boolean",
                "is_list": False,
                "required": False,
                "default": False,
                "choices": [],
                "help": None,
            }
        ],
    }
    parser = parser_from_command_spec(cmd_spec)
    ns = parser.parse_args(["--verbose"])
    assert ns.verbose is True


def test_parser_from_command_spec_skips_duplicate_parameter():
    """Duplicate names in the spec — first wins, second silently dropped."""
    cmd_spec = {
        "url_path": "/api/v1/x",
        "method": "get",
        "description": "",
        "parameters": [
            {
                "name": "x",
                "type": "string",
                "is_list": False,
                "required": False,
                "default": "first",
                "choices": [],
                "help": None,
            },
            {
                "name": "x",
                "type": "integer",
                "is_list": False,
                "required": False,
                "default": 99,
                "choices": [],
                "help": None,
            },
        ],
    }
    parser = parser_from_command_spec(cmd_spec)
    ns = parser.parse_args([])
    assert ns.x == "first"


def _spec_with(commands: dict) -> dict:
    return {
        "version": SPEC_VERSION,
        "base_url": "http://h",
        "api_prefix": "/api/v1",
        "commands": commands,
        "routers": {},
        "reference": {"paths": {}, "routers": {}},
    }


def test_parse_command_argv_returns_command_and_params():
    spec_doc = _spec_with(
        {
            "equity.quote": {
                "url_path": "/api/v1/equity/quote",
                "method": "get",
                "description": "",
                "parameters": [
                    {
                        "name": "symbol",
                        "type": "string",
                        "is_list": False,
                        "required": True,
                        "default": None,
                        "choices": [],
                        "help": None,
                    }
                ],
            }
        }
    )
    cmd, params = parse_command_argv(spec_doc, ["equity.quote", "--symbol", "AAPL"])
    assert cmd == "equity.quote"
    assert params == {"symbol": "AAPL"}


def test_parse_command_argv_empty_argv_raises():
    with pytest.raises(SpecCommandError, match="missing command"):
        parse_command_argv(_spec_with({}), [])


def test_parse_command_argv_unknown_command_raises():
    with pytest.raises(SpecCommandError, match="not in spec"):
        parse_command_argv(_spec_with({}), ["nope"])


def test_build_command_spec_skips_empty_command():
    """A URL that strips to an empty dotted command is skipped."""
    spec = {"paths": {"/api/v1": {"get": {"operationId": "x", "parameters": []}}}}
    assert build_command_spec(spec) == {}


def test_build_command_spec_merges_url_overloads():
    """URLs that strip to the same dotted command merge into one entry with ``url_templates``."""
    spec = {
        "paths": {
            "/api/x/{a}": {"get": {"operationId": "first", "parameters": []}},
            "/api/x/{a}/{b}": {"get": {"operationId": "second", "parameters": []}},
            "/api/x/{c}/{d}": {"get": {"operationId": "third", "parameters": []}},
        }
    }
    out = build_command_spec(spec, api_prefix="/api")
    assert list(out.keys()) == ["x"]
    entry = out["x"]
    assert sorted(entry["url_templates"]) == sorted(
        ["/api/x/{a}", "/api/x/{a}/{b}", "/api/x/{c}/{d}"]
    )
    assert entry["url_path"] == "/api/x/{a}"


def test_build_command_spec_marks_overload_path_params_optional():
    """Path params that only appear in some variants of an overload become optional."""
    param_country = {
        "name": "country",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
    }
    param_d1 = {
        "name": "d1",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
    }
    param_d2 = {
        "name": "d2",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
    }
    spec = {
        "paths": {
            "/api/ratings/historical/{country}": {
                "get": {"parameters": [param_country]}
            },
            "/api/ratings/historical/{country}/{d1}/{d2}": {
                "get": {"parameters": [param_country, param_d1, param_d2]}
            },
        }
    }
    out = build_command_spec(spec, api_prefix="/api")
    entry = out["ratings.historical"]
    by_name = {p["name"]: p for p in entry["parameters"]}
    assert by_name["country"]["required"] is True
    assert by_name["d1"]["required"] is False
    assert by_name["d2"]["required"] is False


def test_merge_overload_backfills_missing_param_metadata():
    """When one overload entry omits help/choices/default/example, fill from a sibling."""
    long_param = {
        "name": "fmt",
        "in": "query",
        "required": False,
        "schema": {"type": "string"},
    }
    short_param = {
        "name": "fmt",
        "in": "query",
        "required": False,
        "description": "Response format.",
        "schema": {
            "type": "string",
            "enum": ["json", "csv"],
            "default": "json",
            "example": "json",
        },
    }
    spec = {
        "paths": {
            "/api/x/{a}/{b}": {"get": {"parameters": [long_param]}},
            "/api/x/{a}": {"get": {"parameters": [short_param]}},
        }
    }
    out = build_command_spec(spec, api_prefix="/api")
    by_name = {p["name"]: p for p in out["x"]["parameters"]}
    fmt = by_name["fmt"]
    assert fmt["help"] == "Response format."
    assert fmt["choices"] == ["json", "csv"]
    assert fmt["default"] == "json"
    assert fmt["example"] == "json"


def test_parse_command_argv_drops_none_params():
    """Optional flags left at their default ``None`` shouldn't go on the wire."""
    spec_doc = _spec_with(
        {
            "x": {
                "url_path": "/api/v1/x",
                "method": "get",
                "description": "",
                "parameters": [
                    {
                        "name": "a",
                        "type": "string",
                        "is_list": False,
                        "required": False,
                        "default": None,
                        "choices": [],
                        "help": None,
                    },
                    {
                        "name": "b",
                        "type": "string",
                        "is_list": False,
                        "required": False,
                        "default": "hi",
                        "choices": [],
                        "help": None,
                    },
                ],
            }
        }
    )
    _, params = parse_command_argv(spec_doc, ["x"])
    assert params == {"b": "hi"}


# --- Multi-provider parser narrowing ---


def test_operation_providers_extracts_enum_from_provider_param():
    from openbb_cli.dispatchers.spec import _operation_providers

    op = {
        "parameters": [
            {"name": "provider", "schema": {"enum": ["cboe", "fmp", "intrinio"]}},
            {"name": "symbol", "schema": {"type": "string"}},
        ]
    }
    assert _operation_providers(op) == ["cboe", "fmp", "intrinio"]


def test_operation_providers_returns_empty_when_no_provider_param():
    from openbb_cli.dispatchers.spec import _operation_providers

    op = {"parameters": [{"name": "x", "schema": {"type": "string"}}]}
    assert _operation_providers(op) == []


def test_operation_providers_extracts_const_for_single_provider():
    """A single-provider endpoint uses ``const`` instead of ``enum``."""
    from openbb_cli.dispatchers.spec import _operation_providers

    op = {"parameters": [{"name": "provider", "schema": {"const": "eia"}}]}
    assert _operation_providers(op) == ["eia"]


def test_operation_providers_returns_empty_when_provider_schema_lacks_enum_or_const():
    """``provider`` parameter without ``enum`` and without ``const`` → ``[]``."""
    from openbb_cli.dispatchers.spec import _operation_providers

    op = {"parameters": [{"name": "provider", "schema": {"type": "string"}}]}
    assert _operation_providers(op) == []


def test_normalize_parameter_records_providers_for_multi_provider_op():
    """The ``providers`` field is populated only when ``providers_set`` is supplied."""
    out = _normalize_parameter(
        {"name": "use_cache", "schema": {"type": "boolean", "title": "cboe"}},
        providers_set={"cboe", "fmp"},
    )
    assert out["providers"] == ["cboe"]


def test_normalize_parameter_provider_param_itself_has_no_providers_tag():
    """The ``provider`` discriminator applies to all backends; tags stay empty."""
    out = _normalize_parameter(
        {"name": "provider", "schema": {"enum": ["cboe", "fmp"], "type": "string"}},
        providers_set={"cboe", "fmp"},
    )
    assert out["providers"] == []


def test_param_visible_for_provider_keeps_shared_and_matching():
    from openbb_cli.dispatchers.spec import _param_visible_for_provider

    shared = {"name": "symbol", "providers": []}
    cboe_only = {"name": "use_cache", "providers": ["cboe"]}
    intrinio_only = {"name": "source", "providers": ["intrinio"]}
    provider_param = {"name": "provider", "providers": []}

    # No selected provider: everything visible
    for p in (shared, cboe_only, intrinio_only):
        assert _param_visible_for_provider(p, None) is True

    # provider=cboe: shared + cboe-only visible, intrinio hidden
    assert _param_visible_for_provider(shared, "cboe") is True
    assert _param_visible_for_provider(cboe_only, "cboe") is True
    assert _param_visible_for_provider(intrinio_only, "cboe") is False
    # provider discriminator always visible
    assert _param_visible_for_provider(provider_param, "cboe") is True


def test_parser_from_command_spec_narrows_to_selected_provider():
    cmd_spec = {
        "url_path": "/q",
        "parameters": [
            {
                "name": "provider",
                "type": "string",
                "required": True,
                "choices": ["cboe", "intrinio"],
                "providers": [],
            },
            {"name": "symbol", "type": "string", "required": True, "providers": []},
            {"name": "use_cache", "type": "boolean", "providers": ["cboe"]},
            {"name": "source", "type": "string", "providers": ["intrinio"]},
        ],
    }
    parser = parser_from_command_spec(cmd_spec, selected_provider="cboe")
    flags = {a.option_strings[0] for a in parser._actions if a.option_strings}
    # cboe sees use_cache (and its --no-use_cache pair) but NOT source
    assert "--symbol" in flags
    assert "--use_cache" in flags
    assert "--source" not in flags


def test_parse_command_argv_two_pass_narrows_by_provider():
    """End-to-end: --provider intrinio --use_cache fails because use_cache is cboe-only."""
    spec_doc = {
        "version": SPEC_VERSION,
        "commands": {
            "q": {
                "url_path": "/q",
                "method": "get",
                "providers": ["cboe", "intrinio"],
                "parameters": [
                    {
                        "name": "provider",
                        "in": "query",
                        "type": "string",
                        "is_list": False,
                        "required": True,
                        "choices": ["cboe", "intrinio"],
                        "default": None,
                        "help": None,
                        "providers": [],
                    },
                    {
                        "name": "symbol",
                        "in": "query",
                        "type": "string",
                        "is_list": False,
                        "required": True,
                        "default": None,
                        "choices": [],
                        "help": None,
                        "providers": [],
                    },
                    {
                        "name": "use_cache",
                        "in": "query",
                        "type": "boolean",
                        "is_list": False,
                        "required": False,
                        "default": True,
                        "choices": [],
                        "help": None,
                        "providers": ["cboe"],
                    },
                ],
            }
        },
    }
    # Valid: cboe with use_cache toggled off
    _, params = parse_command_argv(
        spec_doc, ["q", "--provider", "cboe", "--symbol", "AAPL", "--no-use_cache"]
    )
    assert params == {"provider": "cboe", "symbol": "AAPL", "use_cache": False}

    # Invalid: intrinio + use_cache → argparse SystemExit on unrecognized
    with pytest.raises(SystemExit):
        parse_command_argv(
            spec_doc,
            ["q", "--provider", "intrinio", "--symbol", "AAPL", "--use_cache"],
        )


def test_parse_command_argv_falls_back_to_full_parser_without_provider():
    """Single-provider commands skip the peek pass and use the full parser."""
    spec_doc = {
        "version": SPEC_VERSION,
        "commands": {
            "x": {
                "url_path": "/x",
                "method": "get",
                "providers": [],
                "parameters": [
                    {
                        "name": "y",
                        "in": "query",
                        "type": "string",
                        "is_list": False,
                        "required": True,
                        "default": None,
                        "choices": [],
                        "help": None,
                        "providers": [],
                    },
                ],
            }
        },
    }
    _, params = parse_command_argv(spec_doc, ["x", "--y", "1"])
    assert params == {"y": "1"}


def test_boolean_param_supports_no_flag_form():
    """``BooleanOptionalAction`` lets ``--no-flag`` flip a True default."""
    cmd_spec = {
        "url_path": "/x",
        "parameters": [
            {"name": "use_cache", "type": "boolean", "default": True, "providers": []},
        ],
    }
    parser = parser_from_command_spec(cmd_spec)
    ns = parser.parse_args(["--no-use_cache"])
    assert ns.use_cache is False
    ns = parser.parse_args(["--use_cache"])
    assert ns.use_cache is True


# --- _resolve_base_url branches ---


def test_resolve_base_url_absolute_server_replaces_when_user_has_no_path():
    from openbb_cli.dispatchers.spec import _resolve_base_url

    openapi = {"servers": [{"url": "https://api.example.com/v3"}]}
    assert _resolve_base_url(openapi, "https://api.example.com") == (
        "https://api.example.com/v3"
    )


def test_resolve_base_url_absolute_server_keeps_user_when_user_has_path():
    """If the user already supplied a path, don't replace it."""
    from openbb_cli.dispatchers.spec import _resolve_base_url

    openapi = {"servers": [{"url": "https://api.example.com/v3"}]}
    assert _resolve_base_url(openapi, "https://api.example.com/custom") == (
        "https://api.example.com/custom"
    )


def test_resolve_base_url_relative_server_appends_to_user():
    from openbb_cli.dispatchers.spec import _resolve_base_url

    openapi = {"servers": [{"url": "/v3"}]}
    assert _resolve_base_url(openapi, "https://api.example.com") == (
        "https://api.example.com/v3"
    )


def test_resolve_base_url_relative_server_skips_if_user_already_has_it():
    """User-supplied URL ending with the server path: no double-append."""
    from openbb_cli.dispatchers.spec import _resolve_base_url

    openapi = {"servers": [{"url": "/v3"}]}
    assert _resolve_base_url(openapi, "https://api.example.com/v3") == (
        "https://api.example.com/v3"
    )


def test_resolve_base_url_no_servers_returns_user():
    from openbb_cli.dispatchers.spec import _resolve_base_url

    assert _resolve_base_url({}, "https://api.example.com/") == (
        "https://api.example.com"
    )


def test_resolve_base_url_empty_server_url_returns_user():
    from openbb_cli.dispatchers.spec import _resolve_base_url

    assert _resolve_base_url({"servers": [{"url": "  "}]}, "http://x") == "http://x"


# --- _peek_provider edges ---


def test_peek_provider_returns_none_when_no_providers_declared():
    from openbb_cli.dispatchers.spec import _peek_provider

    assert _peek_provider({"providers": []}, ["--whatever"]) is None


def test_peek_provider_returns_chosen_provider():
    from openbb_cli.dispatchers.spec import _peek_provider

    assert (
        _peek_provider(
            {"providers": ["cboe", "intrinio"]},
            ["--symbol", "AAPL", "--provider", "intrinio", "--use_cache"],
        )
        == "intrinio"
    )


def test_peek_provider_returns_none_when_provider_invalid():
    """A bogus --provider value triggers SystemExit in argparse → return None."""
    from openbb_cli.dispatchers.spec import _peek_provider

    assert (
        _peek_provider(
            {"providers": ["cboe", "intrinio"]},
            ["--provider", "bogus"],
        )
        is None
    )


def test_peek_provider_returns_none_when_provider_absent():
    from openbb_cli.dispatchers.spec import _peek_provider

    assert (
        _peek_provider(
            {"providers": ["cboe"]},
            ["--symbol", "AAPL"],  # no --provider
        )
        is None
    )


# --- Datetime param coercion ---


def test_coerce_iso_datetime_expands_date_to_rfc3339():
    from openbb_cli.dispatchers.spec import _coerce_iso_datetime

    assert _coerce_iso_datetime("2025-01-01") == "2025-01-01T00:00:00Z"


def test_coerce_iso_datetime_appends_z_to_full_timestamp():
    from openbb_cli.dispatchers.spec import _coerce_iso_datetime

    assert _coerce_iso_datetime("2025-01-01T12:34:56") == "2025-01-01T12:34:56Z"


def test_coerce_iso_datetime_passthrough_for_other_forms():
    from openbb_cli.dispatchers.spec import _coerce_iso_datetime

    assert _coerce_iso_datetime("not-a-date") == "not-a-date"


def test_looks_like_datetime_param_detects_camelcase_suffix():
    from openbb_cli.dispatchers.spec import _looks_like_datetime_param

    assert _looks_like_datetime_param("fromDateTime", None) is True
    assert _looks_like_datetime_param("from_datetime", None) is True


def test_looks_like_datetime_param_detects_timestamp_help():
    from openbb_cli.dispatchers.spec import _looks_like_datetime_param

    assert _looks_like_datetime_param("when", "ISO timestamp") is True
    assert _looks_like_datetime_param("when", "format YYYY-MM-DD") is True


def test_looks_like_datetime_param_returns_false_for_unrelated():
    from openbb_cli.dispatchers.spec import _looks_like_datetime_param

    assert _looks_like_datetime_param("symbol", "stock ticker") is False


def test_normalize_parameter_xml_default_flips_to_json():
    """When ``xml`` and ``json`` are both offered, default flips to ``json``."""
    out = _normalize_parameter(
        {
            "name": "format",
            "schema": {"type": "string", "enum": ["xml", "json"]},
        }
    )
    assert out["default"] == "json"


def test_normalize_parameter_csv_default_flips_to_json():
    """When ``csv`` and ``json`` are both offered, default flips to ``json``."""
    out = _normalize_parameter(
        {
            "name": "fmt",
            "schema": {"type": "string", "enum": ["json", "csv"]},
        }
    )
    assert out["default"] == "json"
    assert out["required"] is False


def test_normalize_parameter_json_only_enum_keeps_no_default():
    """A lone ``json`` choice is not a format toggle — no default injected."""
    out = _normalize_parameter(
        {
            "name": "fmt",
            "schema": {"type": "string", "enum": ["json"]},
        }
    )
    assert out["default"] is None


# --- securitySchemes → synthetic credential parameters ---


def _apikey_spec(**op_extra):
    return {
        "security": [{"KeyAuth": []}],
        "components": {
            "securitySchemes": {
                "KeyAuth": {
                    "type": "apiKey",
                    "in": "query",
                    "name": "api_token",
                    "description": "API key.",
                }
            }
        },
        "paths": {"/data": {"get": {"summary": "Data", **op_extra}}},
    }


def test_build_command_spec_materializes_global_apikey_as_optional_param():
    commands = build_command_spec(_apikey_spec(), api_prefix="")
    params = {p["name"]: p for p in commands["data"]["parameters"]}
    assert "api_token" in params
    assert params["api_token"]["in"] == "query"
    assert params["api_token"]["required"] is False
    assert params["api_token"]["help"] == "API key."


def test_build_command_spec_operation_security_empty_suppresses_global():
    commands = build_command_spec(_apikey_spec(security=[]), api_prefix="")
    names = [p["name"] for p in commands["data"]["parameters"]]
    assert "api_token" not in names


def test_build_command_spec_declared_param_not_duplicated_by_security():
    spec = _apikey_spec(
        parameters=[{"name": "api_token", "in": "query", "schema": {"type": "string"}}]
    )
    commands = build_command_spec(spec, api_prefix="")
    names = [p["name"] for p in commands["data"]["parameters"]]
    assert names.count("api_token") == 1


def test_security_parameters_header_scheme_and_non_apikey():
    from openbb_cli.dispatchers.spec import _security_parameters

    spec = {
        "security": [{"HeaderAuth": []}, {"Bearer": []}, {"CookieAuth": []}],
        "components": {
            "securitySchemes": {
                "HeaderAuth": {"type": "apiKey", "in": "header", "name": "X-Api-Key"},
                "Bearer": {"type": "http", "scheme": "bearer"},
                "CookieAuth": {"type": "apiKey", "in": "cookie", "name": "sid"},
            }
        },
    }
    out = _security_parameters(spec, {})
    assert out == [
        {
            "name": "X-Api-Key",
            "in": "header",
            "schema": {"type": "string"},
            "description": None,
        }
    ]


def test_security_parameters_dedupes_repeated_scheme_name():
    from openbb_cli.dispatchers.spec import _security_parameters

    spec = {
        "security": [{"KeyAuth": []}, {"KeyAuth": []}],
        "components": {
            "securitySchemes": {
                "KeyAuth": {"type": "apiKey", "in": "query", "name": "api_token"}
            }
        },
    }
    assert len(_security_parameters(spec, {})) == 1


def test_security_parameters_skips_malformed_requirements():
    from openbb_cli.dispatchers.spec import _security_parameters

    spec = {
        "security": ["not-a-dict", {"Missing": []}, {"NoName": []}],
        "components": {
            "securitySchemes": {"NoName": {"type": "apiKey", "in": "query"}}
        },
    }
    assert _security_parameters(spec, {}) == []


def test_operation_providers_skips_non_dict_param_entries():
    """Defensive: a malformed parameter entry doesn't crash provider extraction."""
    from openbb_cli.dispatchers.spec import _operation_providers

    op = {
        "parameters": [
            "not-a-dict",  # skipped
            {"name": "other"},  # not provider
            {"name": "provider", "schema": {"enum": ["cboe"]}},
        ]
    }
    assert _operation_providers(op) == ["cboe"]


def test_build_command_spec_skips_unresolvable_ref_param():
    """Param with a $ref that doesn't resolve gets dropped, not crashed."""
    openapi = {
        "paths": {
            "/api/v1/x": {
                "get": {
                    "operationId": "x",
                    "parameters": [
                        {"$ref": "#/components/parameters/missing"},
                        {"name": "kept", "schema": {"type": "string"}},
                    ],
                }
            }
        }
    }
    out = build_command_spec(openapi)
    names = [p["name"] for p in out["x"]["parameters"]]
    assert names == ["kept"]


def test_add_normalized_parameter_with_datetime_param_uses_coercer():
    """Datetime-named params get ``_coerce_iso_datetime`` as the type converter."""
    import argparse

    from openbb_cli.dispatchers.spec import (
        _add_normalized_parameter,
        _coerce_iso_datetime,
    )

    p = argparse.ArgumentParser()
    _add_normalized_parameter(
        p,
        {"name": "fromDateTime", "type": "string", "providers": []},
    )
    action = next(a for a in p._actions if a.dest == "fromDateTime")
    assert action.type is _coerce_iso_datetime


def test_build_command_spec_inherits_path_item_parameters():
    """Path and query parameters declared on the path item apply to the operation."""
    openapi = {
        "paths": {
            "/api/v1/x/{record_id}": {
                "parameters": [
                    {"name": "record_id", "in": "path", "required": True},
                    {"name": "page", "in": "query", "schema": {"type": "integer"}},
                ],
                "get": {
                    "operationId": "x",
                    "parameters": [{"name": "symbol", "schema": {"type": "string"}}],
                },
            }
        }
    }
    out = build_command_spec(openapi)
    names = [p["name"] for p in out["x"]["parameters"]]
    assert names == ["record_id", "page", "symbol"]
    record = next(p for p in out["x"]["parameters"] if p["name"] == "record_id")
    assert record["required"] is True


def test_build_command_spec_routes_required_path_item_headers_to_credentials():
    """A required path-item header/cookie is kept as a credential, not a CLI arg.

    An optional one (``session`` here) still has nowhere to go and is dropped,
    same as before — only a required value is the "every operation needs
    this static secret" profile that credential handling exists for.
    """
    openapi = {
        "paths": {
            "/api/v1/x": {
                "parameters": [
                    {"name": "x-tenant-id", "in": "header", "required": True},
                    {"name": "x-session", "in": "cookie", "required": True},
                    {"name": "session", "in": "cookie"},
                    {"name": "page", "in": "query", "schema": {"type": "integer"}},
                ],
                "get": {"operationId": "x"},
            }
        }
    }
    out = build_command_spec(openapi)
    params = {p["name"]: p for p in out["x"]["parameters"]}
    assert set(params) == {"page", "x-tenant-id", "x-session"}
    assert params["x-tenant-id"]["in"] == "header"
    assert params["x-tenant-id"]["required"] is True
    assert params["x-session"]["in"] == "cookie"
    assert params["x-session"]["required"] is True


def test_build_command_spec_operation_header_overrides_path_item_credential():
    """An operation's own header wins over a same-named required path-item header."""
    openapi = {
        "paths": {
            "/api/v1/x": {
                "parameters": [
                    {"name": "x-tenant-id", "in": "header", "required": True}
                ],
                "get": {
                    "operationId": "x",
                    "parameters": [
                        {
                            "name": "x-tenant-id",
                            "in": "header",
                            "description": "Tenant.",
                        }
                    ],
                },
            }
        }
    }
    out = build_command_spec(openapi)
    params = [p for p in out["x"]["parameters"] if p["name"] == "x-tenant-id"]
    assert len(params) == 1
    assert params[0]["required"] is False
    assert params[0]["help"] == "Tenant."


def test_build_command_spec_resolves_path_item_ref_parameters():
    """A path-item parameter given as a $ref is resolved before inheriting."""
    openapi = {
        "components": {
            "parameters": {
                "companyId": {
                    "name": "companyId",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            }
        },
        "paths": {
            "/api/v1/accounts/{companyId}": {
                "parameters": [{"$ref": "#/components/parameters/companyId"}],
                "get": {"operationId": "accounts"},
            }
        },
    }
    out = build_command_spec(openapi)
    assert [p["name"] for p in out["accounts"]["parameters"]] == ["companyId"]


def test_build_command_spec_operation_parameter_overrides_path_item():
    """An operation parameter wins over an inherited one with the same name and location."""
    openapi = {
        "paths": {
            "/api/v1/x": {
                "parameters": [
                    {"name": "limit", "in": "query", "schema": {"type": "string"}}
                ],
                "get": {
                    "operationId": "x",
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                },
            }
        }
    }
    out = build_command_spec(openapi)
    params = out["x"]["parameters"]
    assert len(params) == 1
    assert params[0]["type"] == "integer"
    assert params[0]["required"] is True


def test_build_command_spec_path_item_param_kept_when_location_differs():
    """Overriding is keyed on (name, in) — a same-named param elsewhere is kept."""
    openapi = {
        "paths": {
            "/api/v1/x": {
                "parameters": [
                    {"name": "id", "in": "path", "schema": {"type": "string"}}
                ],
                "get": {
                    "operationId": "x",
                    "parameters": [
                        {"name": "id", "in": "query", "schema": {"type": "string"}}
                    ],
                },
            }
        }
    }
    out = build_command_spec(openapi)
    locations = sorted(p["in"] for p in out["x"]["parameters"] if p["name"] == "id")
    assert locations == ["path", "query"]


def test_build_command_spec_path_item_parameters_apply_to_every_operation():
    """Both operations under one path item inherit its shared parameters."""
    openapi = {
        "paths": {
            "/api/v1/x": {
                "parameters": [
                    {"name": "page", "in": "query", "schema": {"type": "integer"}}
                ],
                "get": {"operationId": "x"},
            },
            "/api/v1/y": {
                "parameters": [
                    {"name": "page", "in": "query", "schema": {"type": "integer"}}
                ],
                "post": {"operationId": "y"},
            },
        }
    }
    out = build_command_spec(openapi)
    assert [p["name"] for p in out["x"]["parameters"]] == ["page"]
    assert [p["name"] for p in out["y"]["parameters"]] == ["page"]


def test_build_command_spec_skips_unresolvable_path_item_ref_param():
    """An unresolvable path-item $ref is dropped rather than crashing."""
    openapi = {
        "paths": {
            "/api/v1/x": {
                "parameters": [{"$ref": "#/components/parameters/missing"}],
                "get": {
                    "operationId": "x",
                    "parameters": [{"name": "kept", "schema": {"type": "string"}}],
                },
            }
        }
    }
    out = build_command_spec(openapi)
    assert [p["name"] for p in out["x"]["parameters"]] == ["kept"]


def test_build_command_spec_ignores_malformed_path_item_parameters():
    """Non-dict path-item parameter entries are skipped defensively."""
    openapi = {
        "paths": {
            "/api/v1/x": {
                "parameters": ["not-a-dict", {"in": "query"}],
                "get": {
                    "operationId": "x",
                    "parameters": [{"name": "kept", "schema": {"type": "string"}}],
                },
            }
        }
    }
    out = build_command_spec(openapi)
    assert [p["name"] for p in out["x"]["parameters"]] == ["kept"]


def test_description_stating_a_delimited_list_makes_the_param_an_array():
    from openbb_cli.dispatchers.spec import _normalize_parameter

    def norm(desc, **extra):
        return _normalize_parameter(
            {
                "name": "op",
                "in": "query",
                "description": desc,
                "schema": {"type": "string", "enum": ["Repo", "Reverse Repo"]},
                **extra,
            }
        )

    got = norm("The operation types (comma-delimited) by which to filter.")
    assert got["is_list"] is True and got["list_style"] == "csv"
    assert got["choices"] == ["Repo", "Reverse Repo"]
    assert norm("Pipe separated list of ids.")["list_style"] == "pipe"
    assert not norm("Values are not comma-delimited.")["is_list"]
    assert not norm("A single value.")["is_list"]
    # an explicit array schema keeps its own style
    arr = _normalize_parameter(
        {
            "name": "x",
            "in": "query",
            "description": "comma-delimited",
            "style": "form",
            "explode": True,
            "schema": {"type": "array", "items": {"type": "string"}},
        }
    )
    assert arr["list_style"] == "multi"
