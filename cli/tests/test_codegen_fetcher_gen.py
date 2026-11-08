"""Tests for openbb_cli.codegen.fetcher_gen — fetcher module emission."""

from __future__ import annotations

import ast
import re

import pytest

from openbb_cli.codegen import fetcher_gen as fg

# --- _module_name_from_command ---


def test_module_name_from_command_snake_cases_dotted_path():
    assert fg._module_name_from_command("equity.price.historical") == (
        "equity_price_historical"
    )


def test_module_name_from_command_replaces_special_chars():
    assert fg._module_name_from_command("Foo-Bar/Baz") == "foo_bar_baz"


def test_module_name_from_command_falls_back_when_empty():
    assert fg._module_name_from_command("___") == "command"


def test_module_name_from_command_prefixes_underscore_when_starts_with_digit():
    assert fg._module_name_from_command("3legged.path") == "_3legged_path"


# --- _path_template_keys ---


def test_path_template_keys_extracts_placeholders_in_order():
    assert fg._path_template_keys("/v3/{congress}/bill/{billNumber}") == [
        "congress",
        "billNumber",
    ]


def test_path_template_keys_returns_empty_when_no_placeholders():
    assert fg._path_template_keys("/static/path") == []


# --- _resolve_url_path ---


def test_resolve_url_path_appends_prefix_when_missing():
    assert fg._resolve_url_path("/api/v1", "/equity/search") == "/api/v1/equity/search"


def test_resolve_url_path_skips_prefix_when_already_present():
    assert (
        fg._resolve_url_path("/api/v1", "/api/v1/equity/search")
        == "/api/v1/equity/search"
    )


def test_resolve_url_path_handles_blank_prefix():
    assert fg._resolve_url_path("", "/equity/search") == "/equity/search"


def test_resolve_url_path_normalizes_missing_leading_slash():
    assert fg._resolve_url_path("/api", "equity/search") == "/api/equity/search"


def test_resolve_url_path_keeps_path_when_prefix_partially_matches_without_trailing_sep():
    # ``path == prefix`` (no trailing /) — don't double-prefix.
    assert fg._resolve_url_path("/api/v1", "/api/v1") == "/api/v1"


# --- _query_params_schema ---


def test_query_params_schema_drops_provider_and_filtered_creds():
    cmd = {
        "parameters": [
            {"name": "symbol", "type": "string", "required": True},
            {"name": "provider", "type": "string"},  # discriminator, dropped
            {"name": "api_key", "type": "string", "in": "query"},  # credential, dropped
        ]
    }
    out = fg._query_params_schema(cmd, provider_name="fmp")
    assert "symbol" in out["properties"]
    assert "provider" not in out["properties"]
    assert "api_key" not in out["properties"]
    assert out["required"] == ["symbol"]


def test_query_params_schema_filters_params_not_in_provider_list():
    cmd = {
        "parameters": [
            {"name": "symbol", "type": "string"},
            {"name": "use_cache", "type": "boolean", "providers": ["cboe"]},
        ]
    }
    out = fg._query_params_schema(cmd, provider_name="fmp")
    assert "symbol" in out["properties"]
    # use_cache is cboe-only — must not leak into fmp
    assert "use_cache" not in out["properties"]


def test_query_params_schema_keeps_param_when_provider_matches():
    cmd = {
        "parameters": [
            {"name": "use_cache", "type": "boolean", "providers": ["cboe", "fmp"]},
        ]
    }
    out = fg._query_params_schema(cmd, provider_name="cboe")
    assert "use_cache" in out["properties"]


def test_query_params_schema_strips_trailing_provider_tag_from_help():
    cmd = {
        "parameters": [
            {
                "name": "symbol",
                "type": "string",
                "help": "The ticker symbol. (provider: fmp)",
            },
        ]
    }
    out = fg._query_params_schema(cmd, provider_name="fmp")
    assert out["properties"]["symbol"]["description"] == "The ticker symbol."


def test_query_params_schema_falls_back_to_description_when_help_missing():
    cmd = {
        "parameters": [
            {"name": "symbol", "type": "string", "description": "Ticker."},
        ]
    }
    out = fg._query_params_schema(cmd, provider_name="fmp")
    assert out["properties"]["symbol"]["description"] == "Ticker."


def test_query_params_schema_handles_list_param_with_choices():
    cmd = {
        "parameters": [
            {
                "name": "tickers",
                "type": "string",
                "is_list": True,
                "choices": ["AAPL", "MSFT"],
                "help": "Tickers.",
            },
        ]
    }
    out = fg._query_params_schema(cmd, provider_name="fmp")
    tickers = out["properties"]["tickers"]
    assert tickers["type"] == "string"
    assert tickers["x-multiple-items"] is True
    assert tickers["x-choices"] == ["AAPL", "MSFT"]
    assert tickers["description"] == "Tickers."


def test_query_params_schema_skips_unnamed_parameters():
    cmd = {"parameters": [{"type": "string"}, {"name": "ok", "type": "string"}]}
    out = fg._query_params_schema(cmd, provider_name="fmp")
    assert list(out["properties"]) == ["ok"]


def test_query_params_schema_merges_request_body_properties():
    cmd = {
        "parameters": [{"name": "symbol", "type": "string"}],
        "request_body_schema": {
            "properties": {
                "data": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["data"],
        },
    }
    out = fg._query_params_schema(cmd, provider_name="tools")
    assert "symbol" in out["properties"]
    assert "data" in out["properties"]
    assert "data" in out["required"]


def test_query_params_schema_does_not_overwrite_existing_property_from_body():
    cmd = {
        "parameters": [{"name": "data", "type": "string"}],
        "request_body_schema": {
            "properties": {"data": {"type": "array"}},
            "required": ["data"],
        },
    }
    out = fg._query_params_schema(cmd, provider_name="tools")
    # Original parameter wins; body version is skipped.
    assert out["properties"]["data"] == {"type": "string"}
    assert out["required"] == []


def test_query_params_schema_marks_required_param():
    cmd = {
        "parameters": [{"name": "symbol", "type": "string", "required": True}],
    }
    out = fg._query_params_schema(cmd, provider_name="fmp")
    assert out["required"] == ["symbol"]


def test_query_params_schema_promotes_path_number_to_integer():
    """Path-typed ``number`` is integer in practice -- routes match int form only."""
    cmd = {
        "parameters": [
            {"name": "n", "in": "path", "type": "number", "required": True},
        ]
    }
    out = fg._query_params_schema(cmd, provider_name="fmp")
    assert out["properties"]["n"]["type"] == "integer"


def test_query_params_schema_keeps_non_path_number_as_number():
    cmd = {
        "parameters": [
            {"name": "ratio", "in": "query", "type": "number", "required": True},
        ]
    }
    out = fg._query_params_schema(cmd, provider_name="fmp")
    assert out["properties"]["ratio"]["type"] == "number"


# --- _data_schema ---


def test_data_schema_descends_into_obbject_anyof_array_items():
    response = {
        "properties": {
            "results": {
                "anyOf": [
                    {"type": "null"},
                    {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"symbol": {"type": "string"}},
                        },
                    },
                ]
            }
        }
    }
    out = fg._data_schema({"response_schema": response})
    assert out == {
        "type": "object",
        "properties": {"symbol": {"type": "string"}},
    }


def test_data_schema_merges_oneof_variants_inside_results():
    response = {
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "oneOf": [
                        {"type": "object", "properties": {"a": {"type": "string"}}},
                        {"type": "object", "properties": {"b": {"type": "integer"}}},
                    ]
                },
            }
        }
    }
    out = fg._data_schema({"response_schema": response})
    assert out["properties"] == {"a": {"type": "string"}, "b": {"type": "integer"}}


def test_data_schema_returns_top_level_for_multi_field_non_obbject_response():
    """Multi-property dict with no clear single data array -> whole dict is the row."""
    response = {
        "type": "object",
        "properties": {"x": {"type": "integer"}, "y": {"type": "string"}},
    }
    out = fg._data_schema({"response_schema": response})
    assert out == response


def test_data_schema_unwraps_single_key_envelope():
    """``{"refRates": [...rate...]}`` -> rate item schema."""
    response = {
        "type": "object",
        "properties": {
            "refRates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"effectiveDate": {"type": "string"}},
                },
            }
        },
    }
    out = fg._data_schema({"response_schema": response})
    assert out == {
        "type": "object",
        "properties": {"effectiveDate": {"type": "string"}},
    }


def test_data_schema_unwraps_top_level_array():
    response = {
        "type": "array",
        "items": {"type": "object", "properties": {"a": {"type": "integer"}}},
    }
    out = fg._data_schema({"response_schema": response})
    assert out == {"type": "object", "properties": {"a": {"type": "integer"}}}


def test_data_schema_recurses_into_nested_single_key_envelope():
    """Two layers of single-key envelope unwrap fully."""
    response = {
        "type": "object",
        "properties": {
            "outer": {
                "type": "object",
                "properties": {
                    "inner": {
                        "type": "object",
                        "properties": {"v": {"type": "integer"}},
                    }
                },
            }
        },
    }
    out = fg._data_schema({"response_schema": response})
    assert out == {"type": "object", "properties": {"v": {"type": "integer"}}}


def test_data_schema_keeps_array_with_non_dict_items():
    """Single array property whose items aren't a dict -> nothing to unwrap."""
    response = {
        "type": "object",
        "properties": {"refRates": {"type": "array", "items": "scalar"}},
    }
    out = fg._data_schema({"response_schema": response})
    assert out == response


def test_data_schema_keeps_array_without_items():
    """Single array property with no items schema -> nothing to unwrap."""
    response = {
        "type": "object",
        "properties": {"refRates": {"type": "array"}},
    }
    out = fg._data_schema({"response_schema": response})
    assert out == response


def test_data_schema_keeps_single_key_with_scalar_value():
    """Single property whose value isn't a dict -> nothing to unwrap."""
    response = {
        "type": "object",
        "properties": {"x": "not a dict"},
    }
    out = fg._data_schema({"response_schema": response})
    assert out == response


def test_data_schema_returns_schema_when_no_properties():
    response = {"type": "object"}
    out = fg._data_schema({"response_schema": response})
    assert out == response


def test_data_schema_top_level_array_with_non_dict_items_returns_empty():
    response = {"type": "array", "items": "scalar"}
    out = fg._data_schema({"response_schema": response})
    assert out == {}


def test_data_schema_unwraps_array_of_scalars_to_value_field():
    """``{"asOfDates": ["2026-01-01", ...]}`` → Data class with ``value: str`` field."""
    response = {
        "type": "object",
        "properties": {"asOfDates": {"type": "array", "items": {"type": "string"}}},
    }
    out = fg._data_schema({"response_schema": response})
    assert out == {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }


def test_data_schema_top_level_array_of_scalars_unwraps_to_value_field():
    response = {"type": "array", "items": {"type": "integer"}}
    out = fg._data_schema({"response_schema": response})
    assert out == {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
    }


def test_data_schema_does_not_unwrap_inside_a_row():
    """Envelopes are unwrapped down to the rows, and no further.

    ``ambs -> auctions`` are single-property wrappers; the auctions are the
    rows (that is what ``unpack_response`` returns), so a row that happens to
    hold one array of records (``details``) keeps all of its own fields.
    """
    response = {
        "type": "object",
        "properties": {
            "ambs": {
                "type": "object",
                "properties": {
                    "auctions": {
                        "type": "array",
                        "items": {
                            "properties": {
                                "auctionStatus": {"type": "string"},
                                "operationId": {"type": "string"},
                                "operationDate": {"type": "string"},
                                "details": {
                                    "type": "array",
                                    "items": {
                                        "properties": {"flag": {"type": "string"}}
                                    },
                                },
                            }
                        },
                    }
                },
            }
        },
    }
    out = fg._data_schema({"response_schema": response})
    assert set(out["properties"]) == {
        "auctionStatus",
        "operationId",
        "operationDate",
        "details",
    }


def test_row_with_several_arrays_is_not_unwrapped_into_one_of_them():
    """An alert has ``affectedZones`` (strings) and ``references`` (records): it is the row."""
    alert = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "affectedZones": {"type": "array", "items": {"type": "string"}},
            "references": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"identifier": {"type": "string"}},
                },
            },
        },
    }
    response = {
        "type": "object",
        "properties": {
            "@graph": {"type": "array", "items": alert},
            "title": {"type": "string"},
        },
    }
    out = fg._data_schema({"response_schema": response})
    assert set(out["properties"]) == {"id", "affectedZones", "references"}


def test_data_schema_merges_oneOf_variants_after_envelope_strip():
    """A ``oneOf`` of object shapes models every variant, not just the first."""
    response = {
        "type": "object",
        "properties": {
            "wrapper": {
                "type": "array",
                "items": {
                    "oneOf": [
                        {"properties": {"a": {"type": "string"}}},
                        {"properties": {"b": {"type": "integer"}}},
                    ]
                },
            }
        },
    }
    out = fg._data_schema({"response_schema": response})
    assert out.get("properties") == {"a": {"type": "string"}, "b": {"type": "integer"}}


def test_unwrap_schema_envelopes_returns_empty_for_non_dict_input():
    assert fg._unwrap_schema_envelopes("not a dict") == {}  # type: ignore[arg-type]
    assert fg._unwrap_schema_envelopes(None) == {}  # type: ignore[arg-type]


def test_data_schema_returns_empty_when_no_response():
    assert fg._data_schema({}) == {}


def test_data_schema_returns_empty_for_non_dict_response():
    assert fg._data_schema({"response_schema": "not a dict"}) == {}


def test_data_schema_returns_response_when_results_field_is_not_dict():
    response = {"properties": {"results": "not a dict"}}
    out = fg._data_schema({"response_schema": response})
    assert out == response


def test_data_schema_descends_through_anyof_single_property_envelope():
    """``results.anyOf`` is a recognized envelope shape — even when the only
    variant is ``null``, the envelope is unwrapped (yielding a degenerate
    schema) so codegen doesn't emit ``results: Any`` as a real field."""
    response = {"properties": {"results": {"anyOf": [{"type": "null"}]}}}
    out = fg._data_schema({"response_schema": response})
    assert out == {"anyOf": [{"type": "null"}]}


# --- _credential_lookup_lines ---


def test_credential_lookup_lines_emits_one_assignment_per_credential():
    creds = {
        "api_key": {"name": "apikey", "in": "query"},
        "authorization": {"name": "Authorization", "in": "header"},
    }
    lines = fg._credential_lookup_lines(creds, provider_name="myprov")
    assert lines == [
        '        _cred_api_key = _creds.get("myprov_api_key", "")',
        '        _cred_authorization = _creds.get("myprov_authorization", "")',
    ]


# --- _query_dict_construction ---


def test_query_dict_construction_excludes_path_and_body_fields():
    cmd = {
        "request_body_schema": {"properties": {"data": {"type": "array"}}},
    }
    out = fg._query_dict_construction(
        cmd, creds={}, path_params=["symbol"], provider_name="fmp"
    )
    assert "exclude={'data', 'symbol'}" in out


def test_query_dict_construction_no_excludes_when_no_path_or_body():
    out = fg._query_dict_construction({}, creds={}, path_params=[], provider_name="fmp")
    # ``by_alias=True`` is always emitted so wire names with non-identifier
    # characters (Socrata's ``$select`` / ``$where``) survive serialization;
    # fields without aliases are unaffected since their alias equals the
    # field name.
    assert (
        out
        == "        _query_dict = query.model_dump(by_alias=True, exclude_none=True)"
    )


def test_query_dict_construction_emits_by_alias_for_aliased_wire_names():
    """Excluded-fields branch carries ``by_alias=True`` too."""
    cmd = {"request_body_schema": {"properties": {"data": {"type": "array"}}}}
    out = fg._query_dict_construction(
        cmd, creds={}, path_params=["symbol"], provider_name="fmp"
    )
    assert "by_alias=True" in out


def test_query_dict_construction_pins_provider_when_command_declares_one():
    cmd = {"parameters": [{"name": "provider", "type": "string"}]}
    out = fg._query_dict_construction(
        cmd, creds={}, path_params=[], provider_name="fmp"
    )
    assert "_query_dict[\"provider\"] = 'fmp'" in out


def test_query_dict_construction_merges_query_credentials():
    creds = {"api_key": {"name": "apikey", "in": "query"}}
    out = fg._query_dict_construction(
        {}, creds=creds, path_params=[], provider_name="fmp"
    )
    assert "if _cred_api_key:" in out
    assert "_query_dict['apikey'] = _cred_api_key" in out


def test_query_dict_construction_skips_header_credentials():
    creds = {"authorization": {"name": "Authorization", "in": "header"}}
    out = fg._query_dict_construction(
        {}, creds=creds, path_params=[], provider_name="fmp"
    )
    # Header-credential should not be merged into the query string
    assert "Authorization" not in out


def test_query_dict_construction_emits_wire_name_renames():
    """Socrata pagination uses clean ``limit`` / ``offset`` user-facing
    names with ``wire_name='$limit'`` / ``'$offset'``; fetcher_gen has to
    emit a runtime rewrite so the URL carries the SoQL-prefixed form."""
    cmd = {
        "parameters": [
            {"name": "limit", "in": "query", "type": "integer", "wire_name": "$limit"},
            {
                "name": "offset",
                "in": "query",
                "type": "integer",
                "wire_name": "$offset",
            },
        ]
    }
    out = fg._query_dict_construction(
        cmd, creds={}, path_params=[], provider_name="socrata"
    )
    # Rename loop is emitted and lists both rewrites.
    assert "for _src, _dst in (" in out
    assert "('limit', '$limit')" in out
    assert "('offset', '$offset')" in out
    assert "_query_dict[_dst] = _query_dict.pop(_src)" in out


def test_query_dict_construction_skips_wire_name_rename_when_already_matching():
    """If ``wire_name`` equals ``name`` (no actual rename needed), the
    rewrite block is omitted entirely."""
    cmd = {
        "parameters": [
            {"name": "limit", "in": "query", "type": "integer", "wire_name": "limit"},
        ]
    }
    out = fg._query_dict_construction(
        cmd, creds={}, path_params=[], provider_name="socrata"
    )
    assert "for _src, _dst in (" not in out


def test_query_dict_construction_ignores_non_dict_parameter_entries():
    """Defensive: a stray non-dict in ``cmd_spec.parameters`` doesn't
    crash the rename loop — it gets skipped silently."""
    cmd = {
        "parameters": [
            "not-a-dict",
            {"name": "limit", "type": "integer", "wire_name": "$limit"},
        ]
    }
    out = fg._query_dict_construction(
        cmd, creds={}, path_params=[], provider_name="socrata"
    )
    assert "('limit', '$limit')" in out


# --- _socrata_where_clause_lines ---


def test_socrata_where_clause_emits_runtime_lines_for_date_range_params():
    """Socrata range params (``start_date`` / ``end_date``) compose into a
    single SoQL ``$where`` clause at runtime — the fetcher emits the
    builder code that runs against the validated query model."""
    range_params = [
        {
            "name": "start_date",
            "_socrata_op": "date_min",
            "_socrata_column": "month_year",
        },
        {
            "name": "end_date",
            "_socrata_op": "date_max",
            "_socrata_column": "month_year",
        },
    ]
    out_lines = fg._socrata_where_clause_lines(range_params)
    out = "\n".join(out_lines)
    # Each range param contributes a typed lookup against the query model.
    assert "_range_start_date = getattr(query, 'start_date', None)" in out
    assert "_range_end_date = getattr(query, 'end_date', None)" in out
    # The SoQL operators reflect the date_min / date_max marker.
    assert "month_year >=" in out
    assert "month_year <=" in out
    # Final ``$where`` is composed (with AND-prefixing if a clause already
    # came in via the user) and lands in ``_query_dict['$where']``.
    assert "_query_dict['$where'] = _socrata_where" in out
    assert "_existing_where" in out


def test_column_metadata_from_data_schema_extracts_units_and_format_hints():
    """Per-column ``description`` (carries units like 'dollars per ton')
    and ``socrata_format`` (currency / decimal-separator rendering hints)
    flow into ``AnnotatedResult.metadata['columns']``."""
    schema = {
        "type": "object",
        "properties": {
            "price": {
                "type": "number",
                "description": "Price, measured in dollars per ton.",
                "socrata_format": {"precisionStyle": "currency"},
            },
            "region": {"type": "string", "description": "Region name."},
            "no_meta": {"type": "string"},
        },
    }
    out = fg._column_metadata_from_data_schema(schema)
    assert out == {
        "price": {
            "description": "Price, measured in dollars per ton.",
            "socrata_format": {"precisionStyle": "currency"},
        },
        "region": {"description": "Region name."},
    }
    # Columns with no metadata are omitted entirely — keeps the
    # constant embedded in the fetcher source compact.
    assert "no_meta" not in out


def test_column_metadata_from_data_schema_skips_non_dict_property_entries():
    """Defensive: a non-dict property entry (malformed schema) gets skipped
    rather than blowing up the codegen pass. ``format`` alone (no
    description / socrata_format) still survives so format hints don't
    silently disappear.
    """
    schema = {
        "type": "object",
        "properties": {
            "ok": {"type": "string", "format": "date"},
            "garbage": "not-a-dict",  # skipped by the defensive guard
        },
    }
    out = fg._column_metadata_from_data_schema(schema)
    assert out == {"ok": {"format": "date"}}


def test_column_metadata_from_data_schema_handles_none_input():
    """``None`` input → empty mapping. The codegen path passes
    ``data_schema or {}`` for safety, so this should be a no-op."""
    assert fg._column_metadata_from_data_schema(None) == {}
    assert fg._column_metadata_from_data_schema({}) == {}


def test_generate_fetcher_module_embeds_column_metadata_in_annotated_result():
    """When a spec carries column descriptions / format hints, the
    generated ``transform_data`` always returns ``AnnotatedResult``
    with a ``columns`` key under ``metadata`` (so callers can read
    ``obbject.extra['results_metadata']['columns']``)."""
    cmd_spec = {
        "url_path": "/resource/abc.json",
        "method": "get",
        "parameters": [],
        "request_body_schema": None,
        "response_schema": {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "price": {
                                "type": "number",
                                "description": "Price in dollars per ton.",
                                "socrata_format": {"precisionStyle": "currency"},
                            },
                        },
                    },
                }
            },
        },
    }
    spec = fg.FetcherCommandSpec(
        name="prices.query",
        cmd_spec=cmd_spec,
        base_url="https://x",
        api_prefix="",
        provider_name="prov",
    )
    out = fg.generate_fetcher_module(spec)
    src = out.source
    # ``AnnotatedResult`` always returned (since ``_metadata`` is now
    # always populated with the columns dict) — ensure the column
    # metadata literal lands verbatim.
    assert "'price'" in src
    assert "'Price in dollars per ton.'" in src
    assert "'precisionStyle': 'currency'" in src
    assert "_metadata.setdefault('columns', _column_metadata)" in src


def test_generate_fetcher_module_skips_column_metadata_when_no_descriptions():
    """A spec with no per-column descriptions / format hints falls
    back to the original ``return _typed`` path — no empty constant
    embedded, no AnnotatedResult on every response."""
    cmd_spec = {
        "url_path": "/x.json",
        "method": "get",
        "parameters": [],
        "request_body_schema": None,
        "response_schema": {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"x": {"type": "string"}},
                    },
                }
            },
        },
    }
    spec = fg.FetcherCommandSpec(
        name="bare.query",
        cmd_spec=cmd_spec,
        base_url="https://x",
        api_prefix="",
        provider_name="prov",
    )
    out = fg.generate_fetcher_module(spec)
    assert "_column_metadata" not in out.source


def test_socrata_range_params_default_order_to_date_column_descending():
    """When the spec carries date-range params, the generated fetcher
    defaults ``$order`` to ``<date_col> DESC`` — so ``limit=N`` returns
    the most recent N records instead of arbitrary storage-order rows."""
    cmd = {
        "parameters": [
            {
                "name": "start_date",
                "_socrata_op": "date_min",
                "_socrata_column": "month_year",
            },
            {
                "name": "end_date",
                "_socrata_op": "date_max",
                "_socrata_column": "month_year",
            },
        ]
    }
    out = fg._query_dict_construction(
        cmd, creds={}, path_params=[], provider_name="socrata"
    )
    # ``setdefault`` so a user-supplied $order isn't overwritten.
    assert "_query_dict.setdefault('$order', 'month_year' + ' DESC')" in out


def test_query_dict_construction_threads_socrata_range_params_into_where_clause():
    """End-to-end: ``_query_dict_construction`` invokes
    ``_socrata_where_clause_lines`` when range params are present AND
    excludes those params from ``model_dump`` (they don't ride the wire
    as flat ``?<name>=<value>`` pairs)."""
    cmd = {
        "parameters": [
            {
                "name": "start_date",
                "_socrata_op": "date_min",
                "_socrata_column": "ts",
            },
            {
                "name": "end_date",
                "_socrata_op": "date_max",
                "_socrata_column": "ts",
            },
        ]
    }
    out = fg._query_dict_construction(
        cmd, creds={}, path_params=[], provider_name="socrata"
    )
    # Range params land in the model_dump exclusion set (so they don't
    # double-up as URL params) AND show up in the $where builder.
    assert "exclude={'end_date', 'start_date'}" in out
    assert "_socrata_where_parts" in out
    assert "ts >=" in out
    assert "ts <=" in out


# --- _header_dict_construction ---


def test_header_dict_construction_emits_header_credentials():
    creds = {"authorization": {"name": "Authorization", "in": "header"}}
    out = fg._header_dict_construction(creds)
    assert "_headers: dict[str, str] = {}" in out
    assert "if _cred_authorization:" in out
    assert "_headers['Authorization'] = _cred_authorization" in out


def test_header_dict_construction_skips_query_credentials():
    creds = {"api_key": {"name": "apikey", "in": "query"}}
    out = fg._header_dict_construction(creds)
    assert "apikey" not in out


# --- _cookie_dict_construction ---


def test_cookie_dict_construction_emits_cookie_credentials():
    creds = {"xero_session": {"name": "xero-session", "in": "cookie"}}
    out = fg._cookie_dict_construction(creds)
    assert "_cookies: dict[str, str] = {}" in out
    assert "if _cred_xero_session:" in out
    assert "_cookies['xero-session'] = _cred_xero_session" in out


def test_cookie_dict_construction_skips_header_and_query_credentials():
    creds = {
        "authorization": {"name": "Authorization", "in": "header"},
        "api_key": {"name": "apikey", "in": "query"},
    }
    out = fg._cookie_dict_construction(creds)
    assert "Authorization" not in out
    assert "apikey" not in out


# --- generate_fetcher_module (end-to-end) ---


def test_generate_fetcher_module_get_endpoint_emits_valid_python():
    spec = fg.FetcherCommandSpec(
        name="equity.search",
        cmd_spec={
            "parameters": [
                {"name": "query", "type": "string", "required": True, "help": "Search."}
            ],
            "url_path": "/equity/search",
            "method": "get",
            "description": "Search equities.",
            "response_schema": {
                "type": "object",
                "properties": {
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"symbol": {"type": "string"}},
                        },
                    }
                },
            },
        },
        base_url="https://api.example.com/",
        api_prefix="api/v1",
        provider_name="fmp",
    )
    out = fg.generate_fetcher_module(spec)

    assert isinstance(out, fg.GeneratedFetcher)
    assert out.module_name == "equity_search"
    assert out.model_name == "EquitySearch"
    assert out.query_params_class == "EquitySearchQueryParams"
    assert out.data_class == "EquitySearchData"
    assert out.fetcher_class == "EquitySearchFetcher"

    src = out.source
    ast.parse(src)
    assert (
        "class EquitySearchFetcher(Fetcher[EquitySearchQueryParams, "
        "list[EquitySearchData]])"
    ) in src
    assert "class EquitySearchQueryParams(QueryParams)" in src
    assert "class EquitySearchData(Data)" in src
    assert "https://api.example.com/api/v1/equity/search" in src
    assert "_session.request(_method, _url" in src
    assert '_method = "GET"' in src
    assert "get_async_requests_session" in src
    assert "raise OpenBBError(" in src


def test_generate_fetcher_module_streaming_endpoint_emits_stream_data():
    spec = fg.FetcherCommandSpec(
        name="crypto.feed",
        cmd_spec={
            "parameters": [
                {"name": "limit", "type": "integer", "help": "Number of ticks."}
            ],
            "url_path": "/crypto/feed",
            "method": "get",
            "description": "Live crypto feed.",
            "response_schemas": {
                "200": {"text/event-stream": {"schema": {"type": "string"}}}
            },
            "response_schema": {
                "type": "object",
                "properties": {"tick": {"type": "integer"}},
            },
        },
        base_url="https://api.example.com/",
        api_prefix="api/v1",
        provider_name="wargame",
    )
    out = fg.generate_fetcher_module(spec)

    assert out.is_streaming is True
    src = out.source
    ast.parse(src)
    assert "AsyncIterator" in src
    assert "async def aextract_data" in src
    assert "async def stream_data" in src
    assert "httpx.AsyncClient" in src


def test_generate_fetcher_module_path_params_substituted_into_url():
    spec = fg.FetcherCommandSpec(
        name="us_congress.bill",
        cmd_spec={
            "parameters": [
                {
                    "name": "congress",
                    "type": "integer",
                    "required": True,
                    "help": "Congress number.",
                }
            ],
            "url_path": "/v3/bill/{congress}",
            "method": "get",
            "description": "Bill data.",
            "response_schema": {"type": "object"},
        },
        base_url="https://api.congress.gov",
        api_prefix="",
        provider_name="us_congress",
    )
    out = fg.generate_fetcher_module(spec)
    assert "'/v3/bill/{congress}'.format(congress=getattr(query, 'congress'))" in (
        out.source
    )
    ast.parse(out.source)


def test_generate_fetcher_module_post_endpoint_emits_json_body_call():
    spec = fg.FetcherCommandSpec(
        name="econometrics.regression",
        cmd_spec={
            "parameters": [],
            "url_path": "/econometrics/regression",
            "method": "post",
            "description": "Linear regression.",
            "request_body_schema": {
                "type": "object",
                "properties": {
                    "data": {"type": "array", "items": {"type": "object"}},
                    "target": {"type": "string"},
                },
                "required": ["data", "target"],
            },
            "response_schema": {"type": "object"},
        },
        base_url="https://api.example.com",
        api_prefix="",
        provider_name="tools",
    )
    out = fg.generate_fetcher_module(spec)
    src = out.source
    assert '_method = "POST"' in src
    assert '"json": _body' in src
    assert "_body = {" in src
    assert "_session.request(_method, _url" in src
    ast.parse(src)


def test_generate_fetcher_module_uses_default_description_when_missing():
    spec = fg.FetcherCommandSpec(
        name="x.y",
        cmd_spec={
            "parameters": [],
            "url_path": "/x/y",
            "method": "get",
            "response_schema": {"type": "object"},
        },
        base_url="https://api.example.com",
        api_prefix="",
        provider_name="fmp",
    )
    out = fg.generate_fetcher_module(spec)
    # Falls back to ``Fetch <name>.``
    assert "Fetch x.y." in out.source


def test_generate_fetcher_module_credentials_round_trip_to_query_string():
    spec = fg.FetcherCommandSpec(
        name="equity.search",
        cmd_spec={
            "parameters": [
                {"name": "query", "type": "string", "required": True},
                {"name": "apikey", "type": "string", "in": "query"},
            ],
            "url_path": "/equity/search",
            "method": "get",
            "description": "Search.",
            "response_schema": {"type": "object"},
        },
        base_url="https://api.example.com",
        api_prefix="",
        provider_name="fmp",
    )
    out = fg.generate_fetcher_module(spec)
    canonical = next(iter(out.credentials_used))
    assert out.credentials_used[canonical]["name"] == "apikey"
    src = out.source
    assert f'_cred_{canonical} = _creds.get("fmp_{canonical}", "")' in src
    assert f"_query_dict['apikey'] = _cred_{canonical}" in src


def test_generate_fetcher_module_required_cookie_reaches_the_request():
    """A required path-item cookie (Xero's tenant-scoped session, e.g.) is sent.

    Regression guard for the case ``operation_parameters`` intentionally never
    fixes: a required header/cookie the path item declares for every operation
    isn't a CLI/Python-interface argument, it's a stored credential — but it
    still has to actually reach the outgoing request.
    """
    spec = fg.FetcherCommandSpec(
        name="accounting.accounts",
        cmd_spec={
            "parameters": [
                {
                    "name": "xero-tenant-id",
                    "type": "string",
                    "in": "header",
                    "required": True,
                },
                {
                    "name": "xero-session",
                    "type": "string",
                    "in": "cookie",
                    "required": True,
                },
            ],
            "url_path": "/Accounts",
            "method": "get",
            "description": "List accounts.",
            "response_schema": {"type": "object"},
        },
        base_url="https://api.xero.com/api.xro/2.0",
        api_prefix="",
        provider_name="xero",
    )
    out = fg.generate_fetcher_module(spec)
    assert set(out.credentials_used) == {"xero_tenant_id", "xero_session"}
    src = out.source
    assert "_cred_xero_tenant_id" in src
    assert "_cred_xero_session" in src
    assert "_headers['xero-tenant-id'] = _cred_xero_tenant_id" in src
    assert "_cookies['xero-session'] = _cred_xero_session" in src
    assert "cookies=_cookies" in src
    ast.parse(src)


def test_query_field_name_snake_cases_with_wire_alias():
    from openbb_cli.codegen.pydantic_gen import generate_class, query_field_name

    assert query_field_name("zoneId") == "zone_id"
    assert query_field_name("User-Agent") == "user_agent"
    assert query_field_name("HTTPStatus") == "http_status"
    src = generate_class(
        {
            "type": "object",
            "properties": {"zoneId": {"type": "string"}},
            "required": ["zoneId"],
        },
        class_name="Q",
        base_class="QueryParams",
    ).source
    assert "zone_id: str = Field(" in src and "zoneId" in src


def test_response_shape_is_decided_by_the_schema_only():
    arr = {
        "type": "array",
        "items": {"type": "object", "properties": {"a": {"type": "string"}}},
    }
    # exactly one array property -> its items are the rows, whatever the siblings
    env = {
        "properties": {
            "@context": {"anyOf": [{"type": "array"}, {"type": "object"}]},
            "title": {"type": "string"},
            "features": arr,
        }
    }
    assert fg._response_shape(env) == ("features", "list")
    # items declared without ``type: array`` still count as an array
    assert fg._response_shape({"properties": {"x": {"items": {"type": "object"}}}}) == (
        "x",
        "list",
    )
    # two arrays: ambiguous, so the object itself is the row
    two = {"properties": {"a": arr, "b": arr, "c": {"type": "string"}}}
    assert fg._response_shape(two) == (None, "single")
    assert 'kind="single"' in fg._unpack_hint({"response_schema": two})
    assert (
        fg._unpack_hint({"response_schema": env})
        == ", rows_key='features', kind='list'"
    )


def test_unpack_response_follows_schema_hint_and_keeps_everything():
    from openbb_cli.dispatchers._unpack import unpack_response

    payload = {
        "@context": ["u"],
        "title": "t",
        "features": [{"id": 1}],
        "other": [{"z": 1}],
    }
    rows, meta = unpack_response(payload, rows_key="features", kind="list")
    assert rows == [{"id": 1}]
    assert meta == {"@context": ["u"], "title": "t", "other": [{"z": 1}]}
    rows, meta = unpack_response(payload, kind="single")
    assert rows == [payload] and meta == {}
    # GeoJSON features are returned as the schema defines them: untouched
    feat = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {"a": 1}}],
    }
    assert (
        unpack_response(feat, rows_key="features", kind="list")[0] == feat["features"]
    )


def test_response_shape_uses_item_types_to_pick_among_arrays_and_unpacks_maps():
    obj = {"type": "object", "properties": {"id": {"type": "string"}}}
    graph = {"type": "array", "items": obj}
    urls = {"type": "array", "items": {"type": "string"}}
    # station list: objects in ``@graph``, the same stations as URLs beside it
    assert fg._response_shape(
        {"properties": {"@graph": graph, "observationStations": urls}}
    ) == ("@graph", "list")
    # two arrays of objects stay ambiguous: the object is the row (an observation)
    assert fg._response_shape(
        {"properties": {"a": graph, "b": graph, "t": {"type": "string"}}}
    ) == (None, "single")
    # a lone free-form map unpacks to key/value rows
    mapped = {
        "properties": {
            "@context": {"type": "array"},
            "locations": {"type": "object", "additionalProperties": {"type": "string"}},
        }
    }
    assert fg._response_shape(mapped) == ("locations", "map")
    row = fg._unwrap_schema_envelopes(mapped)
    assert set(row["properties"]) == {"key", "value"}

    from openbb_cli.dispatchers._unpack import unpack_response

    rows, meta = unpack_response(
        {"@context": [], "locations": {"A": "x", "B": None}},
        rows_key="locations",
        kind="map",
    )
    assert rows == [
        {"key": "A", "value": "x"},
        {"key": "B", "value": None},
    ] and meta == {"@context": []}


def test_merge_object_variants_unions_fields_enums_and_required():
    status = {"type": "string", "enum": ["Released", "Cancelled"]}
    schema = {
        "anyOf": [
            {
                "properties": {
                    "id": {"type": "string"},
                    "status": status,
                    "x": {"type": "integer"},
                },
                "required": ["id", "x"],
            },
            # results shape: ``status`` is the plain string "Results" (no enum), has its own fields
            {
                "properties": {
                    "id": {"type": "string"},
                    "status": {"type": "string"},
                    "totals": {"type": "number"},
                },
                "required": ["id"],
            },
        ]
    }
    out = fg._merge_object_variants(schema)
    assert set(out["properties"]) == {"id", "status", "x", "totals"}
    # an enum in one variant and the plain type in another admits both
    assert "enum" not in out["properties"]["status"]
    # a field is required only if every variant requires it
    assert out["required"] == ["id"]
    # same-typed enums are unioned
    a = {"type": "string", "enum": ["A", "B"]}
    b = {"type": "string", "enum": ["B", "C"]}
    assert fg._merge_prop_schemas(a, b)["enum"] == ["A", "B", "C"]
    # not a union of 2+ objects -> no merge
    assert (
        fg._merge_object_variants({"anyOf": [{"type": "string"}, {"type": "null"}]})
        is None
    )


def test_scalar_array_beside_other_fields_is_a_field_not_the_rows():
    soma = {
        "type": "object",
        "properties": {
            "soma": {
                "type": "object",
                "properties": {
                    "asOfDate": {"type": "string"},
                    "wam": {"type": "number"},
                    "securityTypes": {"type": "array", "items": {"type": "string"}},
                },
            }
        },
    }
    out = fg._data_schema({"response_schema": soma})
    assert set(out["properties"]) == {"asOfDate", "wam", "securityTypes"}
    # ...but a scalar array standing alone (beside JSON-LD keys) is the rows
    types = {
        "type": "object",
        "properties": {
            "@context": {"type": "array"},
            "eventTypes": {"type": "array", "items": {"type": "string"}},
        },
    }
    assert set(fg._data_schema({"response_schema": types})["properties"]) == {"value"}


def test_oneof_of_wrapper_variants_models_the_rows_inside_each():
    def variant(key, field):
        return {
            "properties": {
                key: {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "details": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {field: {"type": "string"}},
                            },
                        },
                    },
                }
            }
        }

    response = {
        "type": "object",
        "properties": {
            "guidesheet": {
                "type": "object",
                "oneOf": [
                    variant("si", "cusip"),
                    variant("wi", "cusip"),
                    variant("fs", "formLine"),
                ],
            }
        },
    }
    out = fg._data_schema({"response_schema": response})
    assert set(out["properties"]) == {"cusip", "formLine"}
    # one-field *rows* in a union are not wrappers
    flat = {
        "oneOf": [
            {"properties": {"a": {"type": "string"}}},
            {"properties": {"b": {"type": "string"}}},
        ]
    }
    assert fg._wrapper_choice_rows(flat) is None


_KLINES_RESPONSE = {
    "type": "array",
    "items": {
        "type": "array",
        "items": {"oneOf": [{"type": "integer"}, {"type": "string"}]},
    },
}


def test_response_shape_marks_array_of_arrays_as_tuples():
    assert fg._response_shape(_KLINES_RESPONSE) == (None, "tuples")
    assert fg._response_shape({"type": "array", "items": {"items": {}}}) == (
        None,
        "tuples",
    )
    assert fg._response_shape({"type": "array", "items": {"type": "object"}}) == (
        None,
        "records",
    )
    union_items = {"oneOf": [{"type": "object"}, {"type": "array"}]}
    assert fg._response_shape({"type": "array", "items": union_items}) == (
        None,
        None,
    )


def test_unpack_hint_for_array_of_arrays():
    assert fg._unpack_hint({"response_schema": _KLINES_RESPONSE}) == ', kind="tuples"'


def test_data_schema_array_of_arrays_is_one_row_per_inner_array():
    out = fg._data_schema({"response_schema": _KLINES_RESPONSE})
    assert out == {
        "type": "object",
        "properties": {"value": _KLINES_RESPONSE["items"]},
        "required": ["value"],
    }


def test_generate_fetcher_module_types_tuple_rows_as_lists():
    spec = fg.FetcherCommandSpec(
        name="klines",
        cmd_spec={
            "url_path": "/api/v3/klines",
            "method": "get",
            "parameters": [],
            "request_body_schema": None,
            "response_schema": _KLINES_RESPONSE,
        },
        base_url="https://x",
        api_prefix="",
        provider_name="prov",
    )
    src = fg.generate_fetcher_module(spec).source
    assert "value: list[int | str]" in src
    assert 'unpack_response(_payload, kind="tuples")' in src
    ast.parse(src)


_GROUP = {
    "combinator": "oneOf",
    "alternatives": [["symbol"], ["symbols"]],
    "members": ["symbol", "symbols"],
    "required": True,
}


def _grouped_cmd_spec(groups):
    return {
        "url_path": "/api/v3/ticker",
        "method": "get",
        "parameters": [
            {"name": "symbol", "in": "query", "type": "string"},
            {"name": "symbols", "in": "query", "type": "string"},
        ],
        "required_groups": groups,
        "request_body_schema": None,
        "response_schema": {"type": "object", "properties": {"x": {"type": "string"}}},
    }


def test_query_params_schema_carries_required_groups():
    schema = fg._query_params_schema(_grouped_cmd_spec([_GROUP]), "prov")
    assert schema["x-required-groups"] == [_GROUP]


def test_query_params_schema_drops_groups_naming_missing_fields():
    stale = {**_GROUP, "alternatives": [["symbol"], ["gone"]]}
    schema = fg._query_params_schema(_grouped_cmd_spec([stale]), "prov")
    assert "x-required-groups" not in schema


def test_generate_fetcher_module_enforces_required_groups():
    spec = fg.FetcherCommandSpec(
        name="ticker",
        cmd_spec=_grouped_cmd_spec([_GROUP]),
        base_url="https://x",
        api_prefix="",
        provider_name="prov",
    )
    src = fg.generate_fetcher_module(spec).source
    model = _exec_query_params(src, "TickerQueryParams")
    model(symbol="BTCUSDT")
    with pytest.raises(
        ValueError, match=re.escape("Pass exactly one of: symbol | symbols")
    ):
        model()


def _exec_query_params(src: str, class_name: str):
    """Exec a generated fetcher module with its package-relative imports stubbed."""
    import re
    import sys
    import types

    assert re.search(r"^from pydantic import .*\bmodel_validator\b", src, re.M)
    utils = types.ModuleType("_generated_utils")
    from openbb_cli.dispatchers import _unpack

    utils.__dict__.update(_unpack.__dict__)
    sys.modules["_generated_utils"] = utils
    try:
        namespace: dict = {}
        exec(  # noqa: S102
            src.replace("from ....utils import", "from _generated_utils import"),
            namespace,
        )
        return namespace[class_name]
    finally:
        sys.modules.pop("_generated_utils", None)


def test_generate_streaming_fetcher_module_enforces_required_groups():
    cmd_spec = _grouped_cmd_spec([_GROUP])
    cmd_spec["response_schemas"] = {"200": {"text/event-stream": {}}}
    spec = fg.FetcherCommandSpec(
        name="ticker",
        cmd_spec=cmd_spec,
        base_url="https://x",
        api_prefix="",
        provider_name="prov",
    )
    out = fg.generate_fetcher_module(spec)
    assert out.is_streaming
    model = _exec_query_params(out.source, "TickerQueryParams")
    with pytest.raises(ValueError, match="Pass exactly one of"):
        model(symbol="A", symbols="B")


def test_generated_fetchers_url_encode_the_query():
    spec = fg.FetcherCommandSpec(
        name="klines",
        cmd_spec=_grouped_cmd_spec([]),
        base_url="https://x",
        api_prefix="",
        provider_name="prov",
    )
    src = fg.generate_fetcher_module(spec).source
    assert "_query_string = encode_query(_query_dict)" in src
    assert "get_querystring" not in src


def test_json_list_param_is_sent_as_a_json_array():
    cmd_spec = _grouped_cmd_spec([])
    cmd_spec["parameters"][1].update(is_list=True, list_style="json")
    spec = fg.FetcherCommandSpec(
        name="ticker",
        cmd_spec=cmd_spec,
        base_url="https://x",
        api_prefix="",
        provider_name="prov",
    )
    src = fg.generate_fetcher_module(spec).source
    assert '_query_dict["symbols"] = json_array(_query_dict["symbols"])' in src or (
        "_query_dict['symbols'] = json_array(_query_dict['symbols'])" in src
    )
    assert re.search(r"^from \.\.\.\.utils import .*\bjson_array\b", src, re.M)
    assert (
        '"multiple_items_allowed": True' in src
        or "'multiple_items_allowed': True" in src
    )
    ast.parse(src)


def test_list_param_lines_json_style():
    lines = fg._list_param_lines("symbols", "json")
    assert lines == [
        "        if isinstance(_query_dict.get('symbols'), str):",
        "            _query_dict['symbols'] = json_array(_query_dict['symbols'])",
    ]


def _merged_cmd_spec(**extra):
    return {
        "url_path": "/aviation/sigmets",
        "url_templates": [
            "/aviation/sigmets/{atsu}/{issueDate}",
            "/aviation/sigmets/{atsu}",
            "/aviation/sigmets",
        ],
        "template_query_params": {
            "/aviation/sigmets/{atsu}/{issueDate}": [],
            "/aviation/sigmets/{atsu}": [],
            "/aviation/sigmets": ["issueDate", "limit"],
        },
        "method": "get",
        "parameters": [
            {"name": "atsu", "in": "path", "type": "string", "required": False},
            {"name": "issueDate", "in": "path", "type": "string", "required": False},
            {"name": "limit", "in": "query", "type": "integer", "default": 500},
        ],
        "request_body_schema": None,
        "response_schema": {"type": "object", "properties": {"x": {"type": "string"}}},
        **extra,
    }


def _merged_spec(**extra):
    return fg.FetcherCommandSpec(
        name="aviation.sigmets",
        cmd_spec=_merged_cmd_spec(**extra),
        base_url="https://x",
        api_prefix="",
        provider_name="prov",
    )


def test_url_choices_only_for_merged_commands():
    attributes = {"atsu": "atsu", "issueDate": "issue_date", "limit": "limit"}
    assert fg.url_choices_for({"url_path": "/x/{a}"}, "", attributes) is None
    choices = fg.url_choices_for(_merged_cmd_spec(), "/api", attributes)
    assert choices.templates == [
        ("/api/aviation/sigmets/{atsu}/{issueDate}", ("atsu", "issueDate"), ()),
        ("/api/aviation/sigmets/{atsu}", ("atsu",), ()),
        ("/api/aviation/sigmets", (), ("issueDate", "limit")),
    ]
    assert choices.names == ["atsu", "issueDate", "limit"]
    assert choices.defaults == {}


def test_url_choices_leave_out_urls_with_placeholders_that_have_no_field():
    cmd_spec = _merged_cmd_spec()
    cmd_spec["url_templates"].append("/aviation/sigmets/key/{key}")
    choices = fg.url_choices_for(
        cmd_spec, "", {"atsu": "atsu", "issueDate": "issue_date", "limit": "limit"}
    )
    assert all("{key}" not in template for template, _, _ in choices.templates)
    assert fg.url_choices_for(cmd_spec, "", {"limit": "limit"}) is None


def test_url_choices_from_a_spec_without_template_query_params_keep_query_params():
    cmd_spec = _merged_cmd_spec()
    del cmd_spec["template_query_params"]
    choices = fg.url_choices_for(
        cmd_spec, "", {"atsu": "atsu", "issueDate": "issue_date", "limit": "limit"}
    )
    assert all(query == ("limit",) for _, _, query in choices.templates)


class _FakeResponse:
    status = 200
    headers = {"Content-Type": "application/json"}

    async def read(self):
        return b"[]"

    def get_encoding(self):
        return "utf-8"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, urls):
        self.urls = urls

    async def request(self, method, url, **kwargs):
        self.urls.append(url)
        return _FakeResponse()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _exec_fetcher(src: str, class_name: str, urls: list[str]):
    """Exec a generated module with a fake HTTP session that records each URL."""
    import sys
    import types

    from openbb_cli.dispatchers import _unpack

    utils = types.ModuleType("_generated_utils")
    utils.__dict__.update(_unpack.__dict__)
    sys.modules["_generated_utils"] = utils
    try:
        namespace: dict = {}
        exec(  # noqa: S102
            src.replace("from ....utils import", "from _generated_utils import"),
            namespace,
        )
    finally:
        sys.modules.pop("_generated_utils", None)

    async def fake_session(*args, **kwargs):
        return _FakeSession(urls)

    namespace["get_async_requests_session"] = fake_session
    return namespace[class_name]


def test_merged_command_fetcher_requests_the_url_that_fits():
    import asyncio

    src = fg.generate_fetcher_module(_merged_spec()).source
    assert "_path, _used, _query_names = choose_url_template(" in src
    urls: list[str] = []
    fetcher = _exec_fetcher(src, "AviationSigmetsFetcher", urls)
    for params in (
        {},
        {"issue_date": "2026-10-18"},
        {"atsu": "KKCI"},
        {"atsu": "KKCI", "issue_date": "2026-10-18"},
        {"atsu": "KKCI", "limit": 5},
    ):
        query = fetcher.transform_query(params)
        asyncio.run(fetcher.aextract_data(query, {}))
    assert urls == [
        "https://x/aviation/sigmets?limit=500",
        "https://x/aviation/sigmets?issueDate=2026-10-18&limit=500",
        "https://x/aviation/sigmets/KKCI",
        "https://x/aviation/sigmets/KKCI/2026-10-18",
        "https://x/aviation/sigmets/KKCI",
    ]


def test_merged_command_query_params_reject_values_that_form_no_url():
    src = fg.generate_fetcher_module(
        _merged_spec(
            template_query_params={
                "/aviation/sigmets/{atsu}/{issueDate}": [],
                "/aviation/sigmets/{atsu}": [],
                "/aviation/sigmets": ["limit"],
            }
        )
    ).source
    model = _exec_query_params(src, "AviationSigmetsQueryParams")
    with pytest.raises(
        ValueError, match=r"Path parameters \(issue_date\) do not form a URL"
    ):
        model(issue_date="2026-10-18")
    model(atsu="KKCI")


def test_single_url_fetcher_code_is_unchanged_by_template_support():
    cmd_spec = _merged_cmd_spec()
    del cmd_spec["url_templates"], cmd_spec["template_query_params"]
    cmd_spec["url_path"] = "/aviation/sigmets/{atsu}"
    spec = fg.FetcherCommandSpec(
        name="aviation.sigmets",
        cmd_spec=cmd_spec,
        base_url="https://x",
        api_prefix="",
        provider_name="prov",
    )
    src = fg.generate_fetcher_module(spec).source
    assert "choose_url_template" not in src
    assert re.search(
        r"_path = ['\"]/aviation/sigmets/\{atsu\}['\"]\.format\(atsu=getattr\(query, ['\"]atsu['\"]\)\)",
        src,
    )


def test_streaming_fetcher_builds_path_from_placeholders():
    cmd_spec = _merged_cmd_spec(response_schemas={"200": {"text/event-stream": {}}})
    spec = fg.FetcherCommandSpec(
        name="aviation.sigmets",
        cmd_spec=cmd_spec,
        base_url="https://x",
        api_prefix="",
        provider_name="prov",
    )
    out = fg.generate_fetcher_module(spec)
    assert out.is_streaming
    assert '_url = f"https://x{_path}"' in out.source
    assert "_path, _used, _query_names = choose_url_template(" in out.source
    ast.parse(out.source)


def test_json_list_param_converts_items_to_their_type():
    lines = fg._list_param_lines("orderIds", "json", "integer")
    assert lines[1] == (
        "            _query_dict['orderIds'] = json_array(_query_dict['orderIds'], 'integer')"
    )


def test_required_group_members_with_empty_values_are_not_sent():
    import asyncio

    cmd_spec = _grouped_cmd_spec([_GROUP])
    cmd_spec["parameters"][1].update(is_list=True, list_style="json")
    spec = fg.FetcherCommandSpec(
        name="ticker",
        cmd_spec=cmd_spec,
        base_url="https://x",
        api_prefix="",
        provider_name="prov",
    )
    urls: list[str] = []
    fetcher = _exec_fetcher(
        fg.generate_fetcher_module(spec).source, "TickerFetcher", urls
    )
    query = fetcher.transform_query({"symbol": "BTCUSDT", "symbols": ""})
    asyncio.run(fetcher.aextract_data(query, {}))
    assert urls == ["https://x/api/v3/ticker?symbol=BTCUSDT"]


def test_json_list_choices_are_not_checked_as_comma_items():
    cmd_spec = _grouped_cmd_spec([])
    cmd_spec["parameters"][1].update(
        is_list=True, list_style="json", choices=["SPOT", "MARGIN"]
    )
    schema = fg._query_params_schema(cmd_spec, "prov")
    assert "x-choices" not in schema["properties"]["symbols"]


def test_null_empty_marker_does_not_become_a_field_named_properties():
    """GeoJSON features have a field literally named ``properties``."""
    schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "properties": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
            },
        },
    }
    marked = fg._mark_null_empty(schema)
    assert set(marked["properties"]) == {"id", "properties"}
    assert marked["x-null-empty"] is True
    assert marked["properties"]["properties"]["x-null-empty"] is True


def test_array_of_records_with_a_nested_record_list_models_the_records():
    """Petstore ``/pet/findByStatus``: Pet rows, not their ``tags``."""
    pet = {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string"},
            "tags": {
                "type": "array",
                "items": {"type": "object", "properties": {"id": {}, "name": {}}},
            },
            "status": {"type": "string"},
        },
    }
    out = fg._data_schema({"response_schema": {"type": "array", "items": pet}})
    assert list(out["properties"]) == ["id", "name", "tags", "status"]


def test_module_name_for_keyword_command_gets_a_suffix():
    assert fg._module_name_from_command("class") == "class_"
    assert fg._module_name_from_command("data.import") == "data_import"
    assert fg._module_name_from_command("24hr") == "_24hr"


def _per_url_cmd_spec():
    item = {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "owner": {"type": "string"}},
        "required": ["id"],
    }
    listing = {
        "type": "object",
        "properties": {
            "pets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"},
                    },
                    "required": ["id", "name"],
                },
            },
            "total": {"type": "integer"},
        },
    }
    return {
        "url_path": "/pets",
        "url_templates": ["/pets/{petId}", "/pets"],
        "template_query_params": {"/pets/{petId}": [], "/pets": []},
        "template_response_schemas": {"/pets/{petId}": item},
        "method": "get",
        "parameters": [{"name": "petId", "in": "path", "type": "integer"}],
        "request_body_schema": None,
        "response_schema": listing,
    }


def test_merged_command_data_model_covers_every_url():
    out = fg._merged_data_schema(_per_url_cmd_spec())
    assert list(out["properties"]) == ["id", "name", "owner"]
    assert out["required"] == ["id"]


def test_merged_command_unpacks_with_the_hint_of_the_url_it_used():
    import asyncio

    spec = fg.FetcherCommandSpec(
        name="pets",
        cmd_spec=_per_url_cmd_spec(),
        base_url="https://x",
        api_prefix="",
        provider_name="prov",
    )
    src = fg.generate_fetcher_module(spec).source
    assert ".get(tuple(sorted(_used)), {})" in src
    urls: list[str] = []
    fetcher = _exec_fetcher(src, "PetsFetcher", urls)
    bodies = iter(
        [
            b'{"id": 1, "owner": "ann"}',
            b'{"pets": [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}], "total": 2}',
        ]
    )

    async def read(self):
        return next(bodies)

    original = _FakeResponse.read
    _FakeResponse.read = read
    try:
        item = asyncio.run(
            fetcher.aextract_data(fetcher.transform_query({"pet_id": 1}), {})
        )
        listing = asyncio.run(fetcher.aextract_data(fetcher.transform_query({}), {}))
    finally:
        _FakeResponse.read = original
    assert item["rows"] == [{"id": 1, "owner": "ann"}]
    assert listing["rows"] == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    assert listing["metadata"] == {"total": 2}
    assert urls == ["https://x/pets/1", "https://x/pets"]


def _extract_with_body(fetcher, params, body: bytes):
    import asyncio

    async def read(self):
        return body

    original = _FakeResponse.read
    _FakeResponse.read = read
    try:
        query = fetcher.transform_query(params)
        return asyncio.run(fetcher.aextract_data(query, {}))
    finally:
        _FakeResponse.read = original


def test_array_of_records_fetcher_keeps_a_single_record_whole():
    order = {"type": "object", "properties": {"symbol": {"type": "string"}}}
    order_list = {
        "type": "object",
        "properties": {
            "orderListId": {"type": "integer"},
            "orders": {"type": "array", "items": order},
        },
        "required": ["orderListId"],
    }
    spec = fg.FetcherCommandSpec(
        name="allOrderList",
        cmd_spec={
            "url_path": "/allOrderList",
            "method": "get",
            "parameters": [],
            "request_body_schema": None,
            "response_schema": {"type": "array", "items": order_list},
        },
        base_url="https://x",
        api_prefix="",
        provider_name="prov",
    )
    src = fg.generate_fetcher_module(spec).source
    assert 'kind="records"' in src
    fetcher = _exec_fetcher(src, "AllOrderListFetcher", [])
    out = _extract_with_body(
        fetcher, {}, b'[{"orderListId": 7, "orders": [{"symbol": "BTCUSDT"}]}]'
    )
    assert out["rows"] == [{"orderListId": 7, "orders": [{"symbol": "BTCUSDT"}]}]


def test_merged_data_model_takes_every_type_a_field_is_declared_with():
    cmd_spec = _per_url_cmd_spec()
    cmd_spec["template_response_schemas"]["/pets/{petId}"]["properties"]["name"] = {
        "type": "array",
        "items": {"type": "string"},
    }
    cmd_spec["response_schema"]["properties"]["pets"]["items"]["properties"]["name"][
        "description"
    ] = "Pet name."
    out = fg._merged_data_schema(cmd_spec)
    assert out["properties"]["name"] == {
        "anyOf": [
            {"type": "string", "description": "Pet name."},
            {"type": "array", "items": {"type": "string"}},
        ],
        "description": "Pet name.",
    }


def _flag_spec(**extra_params):
    return fg.FetcherCommandSpec(
        name="flags",
        cmd_spec={
            "url_path": "/flags/{active}",
            "method": "get",
            "parameters": [
                {"name": "active", "in": "path", "type": "boolean", "required": True},
                *extra_params.values(),
            ],
            "request_body_schema": None,
            "response_schema": {"type": "object", "properties": {"ok": {}}},
        },
        base_url="https://x",
        api_prefix="",
        provider_name="prov",
    )


def test_single_url_fetcher_sends_boolean_path_values_lowercase():
    src = fg.generate_fetcher_module(_flag_spec()).source
    assert "wire_value" in _utils_import(src)
    urls: list[str] = []
    fetcher = _exec_fetcher(src, "FlagsFetcher", urls)
    _extract_with_body(fetcher, {"active": True}, b'{"ok": 1}')
    assert urls == ["https://x/flags/true"]


def test_renamed_query_field_is_read_back_under_its_field_name():
    spec = fg.FetcherCommandSpec(
        name="items",
        cmd_spec={
            "url_path": "/items/{ID}",
            "method": "get",
            "parameters": [
                {"name": "ID", "in": "path", "type": "string", "required": True},
                {"name": "id", "in": "query", "type": "string"},
            ],
            "request_body_schema": None,
            "response_schema": {"type": "object", "properties": {"ok": {}}},
        },
        base_url="https://x",
        api_prefix="",
        provider_name="prov",
    )
    src = fg.generate_fetcher_module(spec).source
    urls: list[str] = []
    fetcher = _exec_fetcher(src, "ItemsFetcher", urls)
    _extract_with_body(fetcher, {"ID": "A1", "id": "x"}, b'{"ok": 1}')
    assert urls == ["https://x/items/A1?id=x"]


def test_merged_data_model_keeps_one_type_when_urls_differ_only_in_docs():
    cmd_spec = _per_url_cmd_spec()
    item = cmd_spec["template_response_schemas"]["/pets/{petId}"]
    item["properties"]["name"] = {"type": "string", "example": "rex"}
    out = fg._merged_data_schema(cmd_spec)
    assert out["properties"]["name"] == {"type": "string"}


def test_streaming_fetcher_sends_boolean_path_values_lowercase():
    spec = _flag_spec()
    spec.cmd_spec["response_schemas"] = {"200": {"text/event-stream": {}}}
    out = fg.generate_fetcher_module(spec)
    assert out.is_streaming
    assert "wire_value" in _utils_import(out.source)
    assert "active=wire_value(getattr(query, 'active'))" in out.source
    ast.parse(out.source)


def test_fetcher_without_boolean_path_values_does_not_import_wire_value():
    spec = _flag_spec()
    spec.cmd_spec["parameters"][0]["type"] = "string"
    assert "wire_value" not in fg.generate_fetcher_module(spec).source
    spec.cmd_spec["response_schemas"] = {"200": {"text/event-stream": {}}}
    assert "wire_value" not in fg.generate_fetcher_module(spec).source


def _utils_import(source: str) -> str:
    return next(line for line in source.splitlines() if "from ....utils import" in line)


def test_merged_data_model_counts_doc_and_nullable_variants_as_one():
    cmd_spec = _per_url_cmd_spec()
    obj = {"type": "object", "properties": {"url": {"type": "string"}}}
    listing_row = cmd_spec["response_schema"]["properties"]["pets"]["items"]
    listing_row["properties"]["photo"] = {**obj, "example": {"url": "a"}}
    item = cmd_spec["template_response_schemas"]["/pets/{petId}"]
    item["properties"]["photo"] = {
        "anyOf": [{**obj, "example": {"url": "b"}}, {"type": "null"}]
    }
    cmd_spec["url_templates"].append("/pets/{petId}/tags")
    cmd_spec["template_query_params"]["/pets/{petId}/tags"] = []
    cmd_spec["template_response_schemas"]["/pets/{petId}/tags"] = {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "photo": {"type": "array", "items": {"type": "string"}},
        },
    }
    photo = fg._merged_data_schema(cmd_spec)["properties"]["photo"]
    assert photo == {
        "anyOf": [
            {**obj, "example": {"url": "a"}},
            {"type": "array", "items": {"type": "string"}},
        ],
        "example": {"url": "a"},
    }


def test_merged_data_model_ignores_nested_nullability_differences():
    cmd_spec = _per_url_cmd_spec()
    row = cmd_spec["response_schema"]["properties"]["pets"]["items"]
    row["properties"]["owner"] = {
        "type": "object",
        "properties": {"city": {"type": "string"}},
    }
    item = cmd_spec["template_response_schemas"]["/pets/{petId}"]
    item["properties"]["owner"] = {
        "type": "object",
        "properties": {"city": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
    }
    owner = fg._merged_data_schema(cmd_spec)["properties"]["owner"]
    assert owner == row["properties"]["owner"]
