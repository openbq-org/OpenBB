"""Tests for openbb_cli.dispatchers._unpack — canonical response unwrapping."""

from __future__ import annotations

import pytest

from openbb_cli.dispatchers._unpack import (
    choose_url_template,
    encode_query,
    json_array,
    safe_json_loads,
    unpack_response,
)

# --- list payloads ---


def test_unpack_response_strips_single_element_list_wrapper():
    rows, metadata = unpack_response([{"a": 1}])
    assert rows == [{"a": 1}]
    assert metadata == {}


def test_unpack_response_recurses_through_single_element_list_of_envelope():
    rows, metadata = unpack_response([{"refRates": [{"x": 1}, {"x": 2}]}])
    assert rows == [{"x": 1}, {"x": 2}]
    assert metadata == {}


def test_unpack_response_keeps_multi_dict_list_as_rows():
    rows, metadata = unpack_response([{"a": 1}, {"b": 2}])
    assert rows == [{"a": 1}, {"b": 2}]
    assert metadata == {}


def test_unpack_response_tuples_hint_keeps_each_inner_array_as_one_row():
    rows, metadata = unpack_response([[1, "a"], [2, "b"]], kind="tuples")
    assert rows == [{"value": [1, "a"]}, {"value": [2, "b"]}]
    assert metadata == {}


def test_unpack_response_tuples_hint_does_not_flatten_a_single_row():
    rows, metadata = unpack_response([[1, "a", "b"]], kind="tuples")
    assert rows == [{"value": [1, "a", "b"]}]
    assert metadata == {}


def test_unpack_response_tuples_hint_falls_back_when_payload_does_not_fit():
    assert unpack_response([{"a": 1}], kind="tuples") == unpack_response([{"a": 1}])
    assert unpack_response({"a": [1]}, kind="tuples") == unpack_response({"a": [1]})


def test_unpack_response_records_hint_keeps_a_single_record_whole():
    record = {"orderListId": 1, "orders": [{"symbol": "BTCUSDT", "orderId": 2}]}
    assert unpack_response([record], kind="records") == ([record], {})


def test_unpack_response_records_hint_falls_back_when_payload_does_not_fit():
    payload = {"a": [{"b": 1}]}
    assert unpack_response(payload, kind="records") == unpack_response(payload)


def test_unpack_response_wraps_array_of_scalars_as_value_rows():
    rows, metadata = unpack_response(["2026-01-01", "2026-01-02"])
    assert rows == [{"value": "2026-01-01"}, {"value": "2026-01-02"}]
    assert metadata == {}


# --- non-dict / scalar payloads ---


def test_unpack_response_wraps_top_level_scalar_as_value_row():
    rows, metadata = unpack_response("plain text")
    assert rows == [{"value": "plain text"}]
    assert metadata == {}


def test_unpack_response_wraps_top_level_int():
    rows, metadata = unpack_response(42)
    assert rows == [{"value": 42}]
    assert metadata == {}


# --- dict payloads ---


def test_unpack_response_strips_single_array_envelope():
    rows, metadata = unpack_response(
        {"refRates": [{"effectiveDate": "2026-04-30", "type": "TGCR"}]}
    )
    assert rows == [{"effectiveDate": "2026-04-30", "type": "TGCR"}]
    assert metadata == {}


def test_unpack_response_splits_array_from_sibling_metadata():
    """Sibling scalar fields surface as metadata."""
    rows, metadata = unpack_response(
        {
            "asOfDate": "2026-04-30",
            "operations": [{"id": 1}, {"id": 2}],
        }
    )
    assert rows == [{"id": 1}, {"id": 2}]
    assert metadata == {"asOfDate": "2026-04-30"}


def test_unpack_response_descends_through_single_key_dict_envelope():
    rows, metadata = unpack_response(
        {"ambs": {"auctions": [{"operationId": "OR1"}, {"operationId": "OR2"}]}}
    )
    assert rows == [{"operationId": "OR1"}, {"operationId": "OR2"}]
    assert metadata == {}


def test_unpack_response_does_not_descend_into_scalar_single_key_value():
    """``{"symbol": "AAPL"}`` is a row dict, not an envelope around ``"AAPL"``."""
    rows, metadata = unpack_response({"symbol": "AAPL"})
    assert rows == [{"symbol": "AAPL"}]
    assert metadata == {}


def test_unpack_response_keeps_record_with_scalar_list_field_whole():
    """A record whose single list holds scalars is a row, not an envelope."""
    rows, metadata = unpack_response({"id": "x", "tags": ["a", "b"]})
    assert rows == [{"id": "x", "tags": ["a", "b"]}]
    assert metadata == {}


def test_unpack_response_returns_multi_property_dict_as_single_row():
    rows, metadata = unpack_response({"a": 1, "b": 2})
    assert rows == [{"a": 1, "b": 2}]
    assert metadata == {}


def test_unpack_response_promotes_scalar_array_under_single_key_envelope():
    """Single-key wrapper around an array of strings -> ``{value: x}`` rows."""
    rows, metadata = unpack_response({"asOfDates": ["2026-04-30", "2026-04-23"]})
    assert rows == [{"value": "2026-04-30"}, {"value": "2026-04-23"}]
    assert metadata == {}


def test_unpack_response_returns_empty_when_payload_is_none():
    rows, metadata = unpack_response(None)
    assert rows == [{"value": None}]
    assert metadata == {}


# --- safe_json_loads ---


def test_safe_json_loads_parses_well_formed_payload_directly():
    """Strict ``json.loads`` succeeds on the fast path — no rewrite triggered."""
    assert safe_json_loads('{"a": 1, "b": [2, 3]}') == {"a": 1, "b": [2, 3]}


def test_safe_json_loads_substitutes_bare_asterisk_with_null():
    """NY Fed-style ``"foo": *`` sentinel becomes ``null`` so the rest of
    the payload still parses instead of failing on the first asterisk."""
    text = '{"a": 1, "b": *, "c": [{"d": *}], "e": "kept"}'
    assert safe_json_loads(text) == {
        "a": 1,
        "b": None,
        "c": [{"d": None}],
        "e": "kept",
    }


def test_safe_json_loads_propagates_unfixable_errors():
    """Genuinely malformed JSON (not just bare ``*``) still raises after
    the sanitization fallback — the fallback isn't a magical rescue."""
    with pytest.raises(ValueError):
        safe_json_loads('{"a": ,}')


def test_encode_query_encodes_reserved_characters():
    assert encode_query({"timeZone": "+8"}) == "timeZone=%2B8"
    assert encode_query({"q": "a b&c=d#e%"}) == "q=a%20b%26c%3Dd%23e%25"
    assert (
        encode_query({"symbols": '["BTCUSDT","ETHUSDT"]'})
        == "symbols=%5B%22BTCUSDT%22,%22ETHUSDT%22%5D"
    )


def test_encode_query_keeps_delimiters_literal_and_matches_old_shape():
    assert encode_query({"ids": "a,b", "at": "12:30", "path": "a/b"}) == (
        "ids=a,b&at=12:30&path=a/b"
    )
    assert encode_query({"a": ["x", "y"], "b": None, "c": True, "d": 5}) == (
        "a=x&a=y&c=true&d=5"
    )
    assert encode_query({}) == ""
    assert encode_query({"$where": "x > 1"}) == "$where=x%20%3E%201"


def test_json_array_from_comma_list_or_json_string():
    assert json_array("BTCUSDT, ETHUSDT,") == '["BTCUSDT","ETHUSDT"]'
    assert json_array('["BTCUSDT", "ETHUSDT"]') == '["BTCUSDT","ETHUSDT"]'
    assert json_array("BTCUSDT") == '["BTCUSDT"]'
    assert json_array("[not json") == '["[not json"]'


_SIGMETS = (
    ("/sigmets/{atsu}/{date}/{time}", ("atsu", "date", "time"), ()),
    ("/sigmets/{atsu}/{date}", ("atsu", "date"), ()),
    ("/sigmets/{atsu}", ("atsu",), ()),
    ("/sigmets", (), ("date", "atsu", "start")),
)
_NO_VALUES = {"atsu": None, "date": None, "time": None}


def test_choose_url_template_picks_most_specific_fit():
    assert choose_url_template(
        _SIGMETS, {**_NO_VALUES, "atsu": "KKCI", "date": "2026-10-18"}
    ) == ("/sigmets/KKCI/2026-10-18", ["atsu", "date"], [])
    assert choose_url_template(_SIGMETS, _NO_VALUES) == (
        "/sigmets",
        [],
        ["date", "atsu", "start"],
    )


def test_choose_url_template_lets_a_template_take_path_names_as_query():
    path, used, query_names = choose_url_template(
        _SIGMETS, {**_NO_VALUES, "date": "2026-10-18"}
    )
    assert (path, used) == ("/sigmets", [])
    assert "date" in query_names


def test_choose_url_template_rejects_values_that_form_no_url():
    with pytest.raises(ValueError) as exc:
        choose_url_template(
            _SIGMETS, {**_NO_VALUES, "time": "0000"}, {"atsu": "atsu_id"}
        )
    message = str(exc.value)
    assert "Path parameters (time) do not form a URL" in message
    assert "atsu_id + date + time | atsu_id + date | atsu_id | none" in message


def test_choose_url_template_treats_empty_string_as_not_passed():
    values = {**_NO_VALUES, "atsu": "K", "date": ""}
    assert choose_url_template(_SIGMETS, values)[0] == "/sigmets/K"


def test_choose_url_template_handles_sets_that_do_not_nest():
    member = (
        ("/member/{stateCode}/{district}", ("stateCode", "district"), ()),
        ("/member/{bioguideId}", ("bioguideId",), ()),
        ("/member/{stateCode}", ("stateCode",), ()),
        ("/member", (), ()),
    )
    values = {"stateCode": None, "district": None, "bioguideId": None}
    assert choose_url_template(member, {**values, "stateCode": "AZ"})[0] == "/member/AZ"
    with pytest.raises(ValueError):
        choose_url_template(member, {**values, "stateCode": "AZ", "bioguideId": "S1"})
    with pytest.raises(ValueError):
        choose_url_template(member, {**values, "district": 7})


_REPORTS = (
    ("/reports/{id}.{format}", ("id", "format"), ()),
    ("/reports", (), ("year",)),
)


def test_choose_url_template_default_never_picks_or_blocks_a_url():
    defaults = {"format": "json"}
    assert (
        choose_url_template(_REPORTS, {"id": None, "format": "json"}, None, defaults)[0]
        == "/reports"
    )
    rates = (("/rates/{fmt}", ("fmt",), ()), ("/rates", (), ()))
    assert choose_url_template(rates, {"fmt": "json"}, None, {"fmt": "json"})[0] == (
        "/rates"
    )
    assert choose_url_template(rates, {"fmt": "xml"}, None, {"fmt": "json"})[0] == (
        "/rates/xml"
    )
    flags = (("/v/{n}/{flag}", ("n", "flag"), ()), ("/v", (), ("q",)))
    assert (
        choose_url_template(flags, {"n": None, "flag": False}, None, {"flag": False})[0]
        == "/v"
    )


def test_choose_url_template_default_completes_a_url_the_caller_picked():
    assert choose_url_template(
        _REPORTS, {"id": 5, "format": "json"}, None, {"format": "json"}
    )[:2] == ("/reports/5.json", ["id", "format"])


def test_choose_url_template_default_shared_by_every_url_fills_the_shortest():
    asof = (
        ("/asof/{holding}/{date}.{format}", ("holding", "date", "format"), ()),
        ("/summary.{format}", ("format",), ()),
    )
    values = {"holding": None, "date": None, "format": "json"}
    assert choose_url_template(asof, values, None, {"format": "json"})[0] == (
        "/summary.json"
    )


def test_json_array_converts_comma_items_to_the_item_type():
    assert json_array("1, 2", "integer") == "[1,2]"
    assert json_array("1.5,2", "number") == "[1.5,2.0]"
    assert json_array("true,False", "boolean") == "[true,false]"
    assert json_array("[1, 2]", "string") == "[1,2]"
    assert json_array("  ") is None
    assert json_array("") is None


def test_encode_query_sends_booleans_lowercase():
    assert encode_query({"active": True, "flags": [True, False]}) == (
        "active=true&flags=true&flags=false"
    )


def test_choose_url_template_fills_boolean_path_values_lowercase():
    templates = (("/v/{flag}", ("flag",), ()), ("/v", (), ()))
    assert choose_url_template(templates, {"flag": True})[0] == "/v/true"
