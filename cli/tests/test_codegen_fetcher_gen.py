"""Tests for openbb_cli.codegen.fetcher_gen — fetcher module emission."""

from __future__ import annotations

import ast

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
