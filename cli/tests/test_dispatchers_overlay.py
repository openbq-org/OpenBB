"""Tests for openbb_cli.dispatchers.overlay — OpenAPI Overlay application."""

from __future__ import annotations

import pytest

from openbb_cli.dispatchers.overlay import (
    apply_overlay,
    load_overlay,
    parse_target,
    select,
)


def test_parse_target_dotted_names():
    assert parse_target("$.components.schemas.aggTrade") == [
        "components",
        "schemas",
        "aggTrade",
    ]


def test_parse_target_quoted_names_indexes_and_wildcards():
    assert parse_target("$.paths['/api/v3/klines'].get") == [
        "paths",
        "/api/v3/klines",
        "get",
    ]
    assert parse_target('$["a.b"][0][*].*') == ["a.b", 0, None, None]
    assert parse_target("$['it\\'s']") == ["it's"]
    assert parse_target("$.a[-1]") == ["a", -1]


def test_parse_target_root_only():
    assert parse_target("$") == []


@pytest.mark.parametrize(
    "target",
    [
        "components.schemas",
        "$..schemas",
        "$.a[?(@.x)]",
        "$.a[0:2]",
        "$['a','b']",
        "$['unterminated",
        "$.a.",
    ],
)
def test_parse_target_rejects_unsupported_or_malformed(target):
    with pytest.raises(ValueError):
        parse_target(target)


def test_select_matches_numeric_keys_written_as_strings():
    doc = {"responses": {200: {"description": "ok"}}}
    [(_, key, node)] = select(doc, parse_target("$.responses['200']"))
    assert key == 200
    assert node == {"description": "ok"}


def test_select_wildcards_over_objects_and_arrays():
    doc = {"a": {"x": [1, 2], "y": [3]}}
    nodes = [node for _, _, node in select(doc, parse_target("$.a.*[*]"))]
    assert nodes == [1, 2, 3]


def test_select_returns_nothing_for_missing_paths():
    assert select({"a": {}}, parse_target("$.a.b.c")) == []
    assert select({"a": [1]}, parse_target("$.a[5]")) == []


def _overlay(*actions):
    return {
        "overlay": "1.0.0",
        "info": {"title": "t", "version": "1"},
        "actions": list(actions),
    }


def test_apply_overlay_merges_update_without_mutating_input():
    openapi = {
        "components": {
            "schemas": {
                "aggTrade": {
                    "properties": {"T": {"type": "boolean", "description": "Timestamp"}}
                }
            }
        }
    }
    doc, unmatched = apply_overlay(
        openapi,
        _overlay(
            {
                "target": "$.components.schemas.aggTrade.properties.T",
                "update": {"type": "integer", "format": "int64"},
            }
        ),
    )
    assert unmatched == []
    assert doc["components"]["schemas"]["aggTrade"]["properties"]["T"] == {
        "type": "integer",
        "description": "Timestamp",
        "format": "int64",
    }
    assert openapi["components"]["schemas"]["aggTrade"]["properties"]["T"] == {
        "type": "boolean",
        "description": "Timestamp",
    }


def test_apply_overlay_merges_integer_keys_into_string_keys():
    doc = {"responses": {"200": {"description": "ok"}}}
    out, _ = apply_overlay(
        doc,
        {"actions": [{"target": "$.responses", "update": {200: {"x-row": True}}}]},
    )
    assert out["responses"] == {"200": {"description": "ok", "x-row": True}}


def test_apply_overlay_reads_yaml_integer_keys_as_strings():
    import json

    doc = {"responses": {200: {"description": "ok"}}}
    out, _ = apply_overlay(
        doc,
        {"actions": [{"target": "$.responses", "update": {"404": {"x": 1}}}]},
    )
    assert out["responses"] == {"200": {"description": "ok"}, "404": {"x": 1}}
    json.dumps(out, sort_keys=True)


def test_apply_overlay_treats_non_ascii_digit_keys_as_names():
    out, _ = apply_overlay(
        {"x": {}}, {"actions": [{"target": "$.x", "update": {"²": 1, "--1": 2}}]}
    )
    assert out["x"] == {"²": 1, "--1": 2}
    with pytest.raises(ValueError, match="unsupported JSONPath syntax"):
        parse_target("$.x[²]")


def test_apply_overlay_merges_nested_objects_and_replaces_other_values():
    doc, _ = apply_overlay(
        {"a": {"b": {"keep": 1, "list": [1, 2]}}},
        _overlay({"target": "$.a", "update": {"b": {"list": [3], "new": True}}}),
    )
    assert doc == {"a": {"b": {"keep": 1, "list": [3], "new": True}}}


def test_apply_overlay_appends_update_to_selected_array():
    doc, _ = apply_overlay(
        {"tags": [{"name": "a"}]},
        _overlay({"target": "$.tags", "update": {"name": "b"}}),
    )
    assert doc["tags"] == [{"name": "a"}, {"name": "b"}]


def test_apply_overlay_removes_selected_nodes():
    doc, _ = apply_overlay(
        {"filters": {"properties": {"x": {}}, "required": ["x"], "type": "object"}},
        _overlay(
            {"target": "$.filters.properties", "remove": True},
            {"target": "$.filters.required", "remove": True},
            {"target": "$.filters", "update": {"additionalProperties": True}},
        ),
    )
    assert doc == {"filters": {"type": "object", "additionalProperties": True}}


def test_apply_overlay_removes_every_wildcard_array_match():
    doc, _ = apply_overlay(
        {"a": [1, 2, 3], "b": [4]},
        _overlay({"target": "$.a[*]", "remove": True}),
    )
    assert doc == {"a": [], "b": [4]}


def test_apply_overlay_reports_targets_that_match_nothing():
    doc, unmatched = apply_overlay(
        {"a": 1}, _overlay({"target": "$.missing", "update": {"x": 1}})
    )
    assert doc == {"a": 1}
    assert unmatched == ["$.missing"]


def test_apply_overlay_action_without_update_or_remove_is_a_no_op():
    doc, unmatched = apply_overlay({"a": {"b": 1}}, _overlay({"target": "$.a"}))
    assert doc == {"a": {"b": 1}}
    assert unmatched == []


@pytest.mark.parametrize(
    "action",
    [
        {"update": {"x": 1}},
        {"target": 5, "update": {"x": 1}},
        {"target": "$.a", "update": {"x": 1}},
        {"target": "$.b", "update": "scalar"},
        {"target": "$", "remove": True},
    ],
)
def test_apply_overlay_rejects_invalid_actions(action):
    with pytest.raises(ValueError):
        apply_overlay({"a": 1, "b": {}}, _overlay(action))


def test_load_overlay_reads_yaml(tmp_path):
    path = tmp_path / "fix.overlay.yaml"
    path.write_text(
        "overlay: 1.0.0\n"
        "info: {title: fix, version: '1'}\n"
        "actions:\n"
        "  - target: $.info\n"
        "    update: {title: patched}\n"
    )
    overlay = load_overlay(path)
    assert overlay["actions"] == [{"target": "$.info", "update": {"title": "patched"}}]


def test_load_overlay_reads_json(tmp_path):
    path = tmp_path / "fix.overlay.json"
    path.write_text('{"overlay": "1.0.0", "actions": []}')
    assert load_overlay(path)["actions"] == []


def test_load_overlay_reads_keys_and_dates_as_json_would(tmp_path):
    path = tmp_path / "fix.overlay.yaml"
    path.write_text(
        "overlay: 1.0.0\n"
        "actions:\n"
        "  - target: $.paths['/x'].get.responses\n"
        "    update: {200: {description: ok, x-since: 2024-01-01}}\n"
    )
    update = load_overlay(path)["actions"][0]["update"]
    assert update == {"200": {"description": "ok", "x-since": "2024-01-01"}}


def test_load_overlay_reads_tab_indented_json(tmp_path):
    path = tmp_path / "fix.overlay.json"
    path.write_text('{\n\t"overlay": "1.0.0",\n\t"actions": []\n}')
    assert load_overlay(path)["actions"] == []


def test_load_overlay_reads_tab_indented_json_with_a_byte_order_mark(tmp_path):
    path = tmp_path / "fix.overlay.json"
    path.write_bytes(b'\xef\xbb\xbf{\n\t"overlay": "1.0.0",\n\t"actions": []\n}')
    assert load_overlay(path)["actions"] == []


def test_apply_overlay_reads_update_keys_as_strings():
    out, _ = apply_overlay(
        {"responses": {"200": {}}},
        {"actions": [{"target": "$.responses", "update": {404: {"x": 1}}}]},
    )
    assert out["responses"] == {"200": {}, "404": {"x": 1}}


def test_load_overlay_reports_invalid_yaml_as_value_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("overlay: 1.0.0\nactions: [\n")
    with pytest.raises(ValueError, match="not valid YAML or JSON"):
        load_overlay(path)


@pytest.mark.parametrize(
    "text",
    [
        "openapi: 3.0.0\npaths: {}\n",
        "overlay: 1.0.0\nactions: {}\n",
        "- just\n- a list\n",
    ],
)
def test_load_overlay_rejects_non_overlay_documents(tmp_path, text):
    path = tmp_path / "bad.yaml"
    path.write_text(text)
    with pytest.raises(ValueError):
        load_overlay(path)
