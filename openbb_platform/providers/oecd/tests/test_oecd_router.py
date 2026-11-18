"""Coverage tests for openbb_oecd.oecd_router."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from openbb_core.app.model.abstract.error import OpenBBError

from openbb_oecd.oecd_router import (
    _APPS_WIDGET_ID_FALLBACK_MAP,
    _parse_annotation,
    _parse_defaults,
    _parse_not_displayed,
    _rewrite_widget_ids,
    get_dataflow_parameters,
    get_oecd_apps_json,
    get_table_detail,
    indicator_choices,
    list_dataflow_choices,
    list_dataflows,
    list_subtopic_choices,
    list_table_choices,
    list_tables,
    list_topic_choices,
    list_topics,
    presentation_table,
    presentation_table_choices,
    presentation_table_dim_choices,
)

_FULL_ID = "DSD_TEST@DF_TEST"
_SHORT_ID = "DF_TEST"


def _seed_taxonomy(meta):
    """Attach a minimal taxonomy referencing the seeded dataflow."""
    meta._taxonomy_tree = [
        {
            "id": "ECO",
            "name": "Economy",
            "path": "ECO",
            "children": [
                {
                    "id": "PRICES",
                    "name": "Prices",
                    "path": "ECO.PRICES",
                    "children": [],
                },
            ],
        }
    ]
    meta._category_to_dfs = {"ECO.PRICES": [_FULL_ID]}
    meta._df_to_categories = {_FULL_ID: ["ECO.PRICES"]}
    meta._category_names = {"ECO": "Economy", "ECO.PRICES": "Prices"}
    meta._taxonomy_loaded = True


def _seed_availability(meta, **overrides):
    """Pre-populate availability cache so OecdParamsBuilder is offline-safe."""
    base = {"REF_AREA": ["USA", "GBR"], "MEASURE": ["CPI"], "FREQ": ["A", "Q"]}
    base.update(overrides)
    meta._availability_cache[f"{_FULL_ID}::"] = dict(base)


class TestParseAnnotation:
    """Pure helper parsing of NOT_DISPLAYED / DEFAULT annotation strings."""

    def test_empty_returns_empty(self):
        assert _parse_annotation("") == {}

    def test_single_pair(self):
        assert _parse_annotation("FREQ=A") == {"FREQ": "A"}

    def test_parenthesized_value_stripped(self):
        assert _parse_annotation("FREQ=(A)") == {"FREQ": "A"}

    def test_multiple_pairs(self):
        result = _parse_annotation("FREQ=A, MEASURE=CPI")
        assert result == {"FREQ": "A", "MEASURE": "CPI"}

    def test_token_without_equals(self):
        result = _parse_annotation("BARE,FREQ=A")
        assert result["BARE"] == ""
        assert result["FREQ"] == "A"

    def test_blank_parts_skipped(self):
        result = _parse_annotation(" , FREQ=A , ")
        assert result == {"FREQ": "A"}

    def test_parse_not_displayed(self):
        annotations = {"NOT_DISPLAYED": "FREQ=A"}
        assert _parse_not_displayed(annotations) == {"FREQ": "A"}

    def test_parse_not_displayed_missing(self):
        assert _parse_not_displayed({}) == {}

    def test_parse_defaults(self):
        annotations = {"DEFAULT": "FREQ=Q"}
        assert _parse_defaults(annotations) == {"FREQ": "Q"}


@pytest.mark.asyncio
class TestListTopicChoices:
    async def test_returns_topic_with_counts(self, seeded_meta):
        _seed_taxonomy(seeded_meta)
        result = await list_topic_choices(seeded_meta)
        assert result
        assert result[0]["value"] == "ECO"
        assert "Economy" in result[0]["label"]

    async def test_empty_when_no_taxonomy(self, seeded_meta):
        seeded_meta._taxonomy_tree = []
        seeded_meta._taxonomy_loaded = True
        result = await list_topic_choices(seeded_meta)
        assert result == []


@pytest.mark.asyncio
class TestListSubtopicChoices:
    async def test_no_topic_returns_empty(self, seeded_meta):
        assert await list_subtopic_choices(seeded_meta, topic=None) == []

    async def test_blank_topic_returns_empty(self, seeded_meta):
        assert await list_subtopic_choices(seeded_meta, topic="") == []

    async def test_unknown_topic_returns_empty(self, seeded_meta):
        _seed_taxonomy(seeded_meta)
        result = await list_subtopic_choices(seeded_meta, topic="ZZZ")
        assert result == []

    async def test_known_topic_returns_subtopic(self, seeded_meta):
        _seed_taxonomy(seeded_meta)
        result = await list_subtopic_choices(seeded_meta, topic="ECO")
        assert result
        assert result[0]["value"] == "PRICES"
        assert "(" in result[0]["label"]

    async def test_subtopic_with_zero_count_excluded(self, seeded_meta, monkeypatch):
        _seed_taxonomy(seeded_meta)
        topics = [
            {
                "id": "ECO",
                "name": "Economy",
                "subtopics": [
                    {"id": "EMPTY", "name": "Empty", "dataflow_count": 0},
                    {"id": "PRICES", "name": "Prices", "dataflow_count": 1},
                ],
                "dataflow_count": 1,
            }
        ]
        monkeypatch.setattr(seeded_meta, "list_topics", lambda: topics)
        result = await list_subtopic_choices(seeded_meta, topic="ECO")
        values = [r["value"] for r in result]
        assert "EMPTY" not in values
        assert "PRICES" in values


@pytest.mark.asyncio
class TestListDataflows:
    async def test_returns_all_without_filter(self, seeded_meta):
        _seed_taxonomy(seeded_meta)
        result = await list_dataflows(seeded_meta)
        assert result.results
        row = result.results[0]
        assert row["dataflow_id"] == _SHORT_ID
        assert row["topic"] == "Economy"

    async def test_subtopic_filter_match(self, seeded_meta):
        _seed_taxonomy(seeded_meta)
        result = await list_dataflows(seeded_meta, subtopic="PRICES")
        assert result.results

    async def test_subtopic_filter_excludes(self, seeded_meta):
        _seed_taxonomy(seeded_meta)
        result = await list_dataflows(seeded_meta, subtopic="UNKNOWN")
        assert result.results == []

    async def test_short_id_branch_when_no_at(self, seeded_meta, monkeypatch):
        monkeypatch.setattr(
            seeded_meta,
            "list_dataflows",
            lambda topic=None: [{"value": "FLATID", "label": "Flat"}],
        )
        result = await list_dataflows(seeded_meta)
        assert result.results[0]["dataflow_id"] == "FLATID"


@pytest.mark.asyncio
class TestListDataflowChoices:
    async def test_returns_label_value_sorted(self, seeded_meta):
        _seed_taxonomy(seeded_meta)
        result = await list_dataflow_choices(seeded_meta)
        assert isinstance(result, list)
        assert {"label", "value"} <= set(result[0].keys())


@pytest.mark.asyncio
class TestListTopics:
    async def test_includes_subtopics(self, seeded_meta):
        _seed_taxonomy(seeded_meta)
        obj = await list_topics(seeded_meta)
        assert obj.results
        row = obj.results[0]
        assert row["topic_id"] == "ECO"
        assert row["subtopic_id"] == "PRICES"

    async def test_query_filter(self, seeded_meta):
        _seed_taxonomy(seeded_meta)
        obj = await list_topics(seeded_meta, query="econ")
        assert obj.results
        obj_empty = await list_topics(seeded_meta, query="zzznomatch")
        assert obj_empty.results == []

    async def test_topic_without_subtopics(self, seeded_meta, monkeypatch):
        monkeypatch.setattr(
            seeded_meta,
            "list_topics",
            lambda: [
                {
                    "id": "TOP",
                    "name": "TopLevel",
                    "dataflow_count": 5,
                    "subtopics": [],
                }
            ],
        )
        obj = await list_topics(seeded_meta)
        assert obj.results[0]["subtopic"] == ""

    async def test_topic_with_zero_dataflows_skipped(self, seeded_meta, monkeypatch):
        monkeypatch.setattr(
            seeded_meta,
            "list_topics",
            lambda: [
                {"id": "EMPTY", "name": "Empty", "dataflow_count": 0, "subtopics": []},
                {
                    "id": "ECO",
                    "name": "Economy",
                    "dataflow_count": 1,
                    "subtopics": [
                        {"id": "X", "name": "X", "dataflow_count": 0},
                        {"id": "P", "name": "P", "dataflow_count": 1},
                    ],
                },
            ],
        )
        obj = await list_topics(seeded_meta)
        ids = {r["topic_id"] for r in obj.results}
        assert "EMPTY" not in ids
        sub_ids = {r["subtopic_id"] for r in obj.results if r["topic_id"] == "ECO"}
        assert sub_ids == {"P"}


@pytest.mark.asyncio
class TestGetDataflowParameters:
    async def test_json_format(self, seeded_meta):
        result = await get_dataflow_parameters(
            seeded_meta, dataflow_id=_SHORT_ID, output_format="json"
        )
        assert "REF_AREA" in result.results

    async def test_markdown_format(self, seeded_meta):
        result = await get_dataflow_parameters(
            seeded_meta, dataflow_id=_SHORT_ID, output_format="markdown"
        )
        assert isinstance(result.results, str)
        assert "REF_AREA" in result.results
        assert "<details>" in result.results


@pytest.mark.asyncio
class TestListTables:
    async def test_basic_list(self, seeded_meta):
        _seed_taxonomy(seeded_meta)
        obj = await list_tables(seeded_meta)
        assert obj.results
        assert obj.results[0]["table_id"] == _SHORT_ID

    async def test_query_filter(self, seeded_meta):
        _seed_taxonomy(seeded_meta)
        obj = await list_tables(seeded_meta, query="Test")
        assert obj.results

    async def test_dataflow_id_filter(self, seeded_meta):
        _seed_taxonomy(seeded_meta)
        obj = await list_tables(seeded_meta, dataflow_id="DF_TEST")
        assert obj.results
        obj_no = await list_tables(seeded_meta, dataflow_id="DF_NOMATCH")
        assert obj_no.results == []


@pytest.mark.asyncio
class TestGetTableDetail:
    async def test_returns_markdown(self, seeded_meta):
        _seed_taxonomy(seeded_meta)
        seeded_meta._dataflow_indicators_cache[_FULL_ID] = []
        obj = await get_table_detail(seeded_meta, table_id=_SHORT_ID)
        assert isinstance(obj.results, str)
        assert "Test Dataflow" in obj.results
        assert "Dimensions" in obj.results

    async def test_includes_description_path(self, seeded_meta):
        _seed_taxonomy(seeded_meta)
        seeded_meta._dataflow_indicators_cache[_FULL_ID] = []
        seeded_meta.dataflows[_FULL_ID]["description"] = "A description."
        obj = await get_table_detail(seeded_meta, table_id=_SHORT_ID)
        assert "A description." in obj.results
        assert "Category" in obj.results

    async def test_with_table_groups_and_indicators(self, seeded_meta, monkeypatch):
        _seed_taxonomy(seeded_meta)
        seeded_meta._dataflow_indicators_cache[_FULL_ID] = []
        detail = {
            "dataflow_id": _FULL_ID,
            "short_id": _SHORT_ID,
            "name": "Test Dataflow",
            "description": "Desc",
            "dimensions": [
                {
                    "id": "TABLE_IDENTIFIER",
                    "name": "Tbl",
                    "values": [{"value": "T1", "label": "Tbl1"}],
                    "constrained_codes": 1,
                },
                {
                    "id": "MEASURE",
                    "name": "Measure",
                    "values": [
                        {
                            "value": "CPI",
                            "label": "Consumer Price Index",
                            "description": "Consumer Price Index",
                        },
                        {
                            "value": "PPI",
                            "label": "Producer",
                            "description": "Other description",
                        },
                    ],
                    "constrained_codes": 2,
                },
            ],
            "table_groups": [
                {
                    "value": "T1",
                    "label": "Tbl1",
                    "description": "Tbl1 group full description",
                },
                {"value": "T2", "label": "Tbl2", "description": "Tbl2"},
            ],
            "indicator_dimension": "MEASURE",
            "indicator_count": 2,
            "indicator_tree": [
                {
                    "code": "CPI",
                    "label": "CPI",
                    "children": [{"code": "CORE", "label": "Core", "children": []}],
                }
            ],
        }
        monkeypatch.setattr(seeded_meta, "describe_dataflow", lambda _id: detail)
        obj = await get_table_detail(seeded_meta, table_id=_SHORT_ID)
        text = obj.results
        assert "Tables" in text
        assert "Indicator tree" in text
        assert "TABLE_IDENTIFIER" not in text.split("## Dimensions")[1]

    async def test_table_row_not_found_short_id_match(self, seeded_meta, monkeypatch):
        seeded_meta._dataflow_indicators_cache[_FULL_ID] = []
        detail = {
            "dataflow_id": "OTHER",
            "short_id": "OTHER",
            "name": "Other",
            "description": "",
            "dimensions": [],
            "table_groups": [],
            "indicator_dimension": "",
            "indicator_count": 0,
            "indicator_tree": [],
        }
        monkeypatch.setattr(seeded_meta, "describe_dataflow", lambda _id: detail)
        monkeypatch.setattr(seeded_meta, "table_map", lambda: [])
        obj = await get_table_detail(seeded_meta, table_id="OTHER")
        assert isinstance(obj.results, str)


@pytest.mark.asyncio
class TestListTableChoices:
    async def test_returns_unique_choices(self, seeded_meta):
        _seed_taxonomy(seeded_meta)
        result = await list_table_choices(seeded_meta)
        assert result
        first = result[0]
        assert {"label", "value", "extraInfo"} <= set(first.keys())

    async def test_topic_filter(self, seeded_meta):
        _seed_taxonomy(seeded_meta)
        result = await list_table_choices(seeded_meta, topic="ECO")
        assert result


@pytest.mark.asyncio
class TestIndicatorChoices:
    async def test_no_symbol(self, seeded_meta):
        assert await indicator_choices(seeded_meta) == []

    async def test_blank_symbol_after_strip(self, seeded_meta):
        assert await indicator_choices(seeded_meta, symbol=" , ") == []

    async def test_unknown_dataflow(self, seeded_meta, monkeypatch):
        def boom(_):
            raise KeyError("missing")

        monkeypatch.setattr(seeded_meta, "get_dimension_order", boom)
        result = await indicator_choices(seeded_meta, symbol="UNKNOWN::FOO")
        assert result == []

    async def test_country_step(self, seeded_meta):
        result = await indicator_choices(
            seeded_meta, symbol=f"{_SHORT_ID}::CPI", country="true"
        )
        assert result[0]["value"] == "*"
        assert any(o["value"] == "USA" for o in result)

    async def test_country_step_no_country_dim(self, seeded_meta, monkeypatch):
        seeded_meta.datastructures[_FULL_ID]["dimensions"] = [
            d
            for d in seeded_meta.datastructures[_FULL_ID]["dimensions"]
            if d["id"] != "REF_AREA"
        ]
        result = await indicator_choices(
            seeded_meta, symbol=f"{_SHORT_ID}::CPI", country="true"
        )
        assert result == []

    async def test_frequency_step(self, seeded_meta):
        result = await indicator_choices(
            seeded_meta, symbol=f"{_SHORT_ID}::CPI", frequency="true"
        )
        codes = {o["value"] for o in result}
        assert {"A", "Q"} <= codes

    async def test_frequency_step_no_freq_dim(self, seeded_meta):
        seeded_meta.datastructures[_FULL_ID]["dimensions"] = [
            d
            for d in seeded_meta.datastructures[_FULL_ID]["dimensions"]
            if d["id"] != "FREQ"
        ]
        result = await indicator_choices(
            seeded_meta, symbol=f"{_SHORT_ID}::CPI", frequency="true"
        )
        assert result == []

    async def test_frequency_step_blocked_by_not_displayed(self, seeded_meta):
        seeded_meta.dataflows[_FULL_ID]["annotations"] = {"NOT_DISPLAYED": "FREQ=A"}
        result = await indicator_choices(
            seeded_meta, symbol=f"{_SHORT_ID}::CPI", frequency="true"
        )
        assert result == []

    async def test_transform_step_no_dim(self, seeded_meta):
        result = await indicator_choices(
            seeded_meta, symbol=f"{_SHORT_ID}::CPI", transform="true"
        )
        assert result == []

    async def test_transform_step_with_dim(self, seeded_meta):
        seeded_meta.datastructures[_FULL_ID]["dimensions"].append(
            {
                "id": "TRANSFORMATION",
                "position": 4,
                "codelist_id": "OECD:CL_FREQ(1.0)",
                "concept_id": "TRANSFORMATION",
                "name": "Transformation",
            }
        )
        seeded_meta._dataflow_constraints[_FULL_ID]["TRANSFORMATION"] = ["A"]
        seeded_meta._dataflow_parameters_cache.pop(_FULL_ID, None)
        result = await indicator_choices(
            seeded_meta, symbol=f"{_SHORT_ID}::CPI", transform="true"
        )
        assert result
        assert result[0]["value"] == "*"

    async def test_transform_step_blocked_by_not_displayed(self, seeded_meta):
        seeded_meta.datastructures[_FULL_ID]["dimensions"].append(
            {
                "id": "TRANSFORMATION",
                "position": 4,
                "codelist_id": "OECD:CL_FREQ(1.0)",
                "concept_id": "TRANSFORMATION",
                "name": "Transformation",
            }
        )
        seeded_meta.dataflows[_FULL_ID]["annotations"] = {
            "NOT_DISPLAYED": "TRANSFORMATION=A"
        }
        result = await indicator_choices(
            seeded_meta, symbol=f"{_SHORT_ID}::CPI", transform="true"
        )
        assert result == []

    async def test_default_dispatch_returns_empty(self, seeded_meta):
        result = await indicator_choices(seeded_meta, symbol=f"{_SHORT_ID}::CPI")
        assert result == []

    async def test_bare_symbol_no_indicator(self, seeded_meta):
        result = await indicator_choices(seeded_meta, symbol=_SHORT_ID, country="true")
        assert any(o["value"] == "USA" for o in result)

    async def test_empty_after_unquote(self, seeded_meta):
        result = await indicator_choices(seeded_meta, symbol="%20%20%20%2C%20%20")
        assert result == []

    async def test_symbol_with_empty_dataflow_part(self, seeded_meta):
        result = await indicator_choices(seeded_meta, symbol="::FOO")
        assert result == []

    async def test_metadata_raises_returns_empty(self, seeded_meta, monkeypatch):
        def boom(_):
            raise ValueError("nope")

        monkeypatch.setattr(seeded_meta, "get_dimension_order", boom)
        result = await indicator_choices(
            seeded_meta, symbol=f"{_SHORT_ID}::CPI", country="true"
        )
        assert result == []


@pytest.mark.asyncio
class TestPresentationTableChoices:
    async def test_step0_returns_topics(self, seeded_meta):
        _seed_taxonomy(seeded_meta)
        result = await presentation_table_choices(seeded_meta)
        assert result
        assert result[0]["value"] == "ECO"

    async def test_step1_returns_subtopics(self, seeded_meta):
        _seed_taxonomy(seeded_meta)
        result = await presentation_table_choices(seeded_meta, topic="ECO")
        assert result
        assert result[0]["value"] == "PRICES"

    async def test_step1_unknown_topic_message(self, seeded_meta):
        _seed_taxonomy(seeded_meta)
        result = await presentation_table_choices(seeded_meta, topic="UNKNOWN")
        assert result == [{"label": "No subtopics found for this topic", "value": ""}]

    async def test_step1_multiple_subtopics(self, seeded_meta, monkeypatch):
        monkeypatch.setattr(
            seeded_meta,
            "list_topics",
            lambda: [
                {
                    "id": "ECO",
                    "name": "Economy",
                    "subtopics": [
                        {"id": "PRICES", "name": "Prices"},
                        {"id": "TRADE", "name": "Trade"},
                    ],
                }
            ],
        )
        monkeypatch.setattr(
            seeded_meta,
            "table_map",
            lambda: [
                {"topic_id": "ECO", "subtopic_id": "PRICES"},
                {"topic_id": "ECO", "subtopic_id": "TRADE"},
            ],
        )
        result = await presentation_table_choices(seeded_meta, topic="ECO")
        values = {r["value"] for r in result}
        assert {"PRICES", "TRADE"} == values

    async def test_step1_single_subtopic_auto(self, seeded_meta, monkeypatch):
        _seed_taxonomy(seeded_meta)
        monkeypatch.setattr(
            seeded_meta,
            "list_topics",
            lambda: [
                {
                    "id": "ECO",
                    "name": "Economy",
                    "subtopics": [{"id": "ONLY", "name": "Only one"}],
                }
            ],
        )
        monkeypatch.setattr(
            seeded_meta,
            "table_map",
            lambda: [{"topic_id": "ECO", "subtopic_id": "ONLY"}],
        )
        result = await presentation_table_choices(seeded_meta, topic="ECO")
        assert result == [{"label": "Only one (1 tables)", "value": "ONLY"}]

    async def test_step2_returns_tables(self, seeded_meta, monkeypatch):
        _seed_taxonomy(seeded_meta)
        seeded_meta.dataflows[_FULL_ID]["all_subtopics"] = ["PRICES"]
        monkeypatch.setattr(
            seeded_meta,
            "list_dataflows",
            lambda topic=None: [
                {
                    "label": "Test Dataflow",
                    "value": _FULL_ID,
                    "subtopic": "PRICES",
                    "all_subtopics": ["PRICES"],
                }
            ],
        )
        monkeypatch.setattr(seeded_meta, "_detect_section_families", lambda: {})
        monkeypatch.setattr(seeded_meta, "_detect_country_families", lambda: {})
        result = await presentation_table_choices(
            seeded_meta, topic="ECO", subtopic="PRICES"
        )
        assert result
        assert result[0]["value"] == _SHORT_ID

    async def test_step2_with_table_groups(self, seeded_meta, monkeypatch):
        _seed_taxonomy(seeded_meta)
        seeded_meta.datastructures[_FULL_ID]["dimensions"].append(
            {
                "id": "TABLE_IDENTIFIER",
                "position": 99,
                "codelist_id": "OECD:CL_TBL(1.0)",
                "concept_id": "TABLE_IDENTIFIER",
                "name": "Table",
            }
        )
        seeded_meta.codelists["OECD:CL_TBL(1.0)"] = {"T01": "Table One"}
        seeded_meta._dataflow_constraints[_FULL_ID]["TABLE_IDENTIFIER"] = ["T01"]
        seeded_meta._dataflow_parameters_cache.pop(_FULL_ID, None)
        seeded_meta._dataflow_indicators_cache[_FULL_ID] = [
            {
                "indicator": "CPI",
                "label": "CPI",
                "dimension_id": "MEASURE",
                "dataflow_id": _SHORT_ID,
                "dataflow_name": "Test",
                "description": "",
                "symbol": "",
            }
        ]
        monkeypatch.setattr(
            seeded_meta,
            "list_dataflows",
            lambda topic=None: [
                {
                    "label": "Test Dataflow",
                    "value": _FULL_ID,
                    "subtopic": "PRICES",
                    "all_subtopics": ["PRICES"],
                }
            ],
        )
        monkeypatch.setattr(seeded_meta, "_detect_section_families", lambda: {})
        monkeypatch.setattr(seeded_meta, "_detect_country_families", lambda: {})
        result = await presentation_table_choices(
            seeded_meta, topic="ECO", subtopic="PRICES"
        )
        assert any("::" in r["value"] for r in result)

    async def test_step2_tiny_group_ratio_flattens(self, seeded_meta, monkeypatch):
        _seed_taxonomy(seeded_meta)
        seeded_meta.datastructures[_FULL_ID]["dimensions"].append(
            {
                "id": "TABLE_IDENTIFIER",
                "position": 99,
                "codelist_id": "OECD:CL_TBL(1.0)",
                "concept_id": "TABLE_IDENTIFIER",
                "name": "Table",
            }
        )
        seeded_meta.codelists["OECD:CL_TBL(1.0)"] = {
            "T01": "Table One",
            "T02": "Table Two",
            "T03": "Table Three",
        }
        seeded_meta._dataflow_constraints[_FULL_ID]["TABLE_IDENTIFIER"] = [
            "T01",
            "T02",
            "T03",
        ]
        seeded_meta._dataflow_parameters_cache.pop(_FULL_ID, None)
        seeded_meta._dataflow_indicators_cache[_FULL_ID] = [
            {
                "indicator": "CPI",
                "label": "CPI",
                "dimension_id": "MEASURE",
                "dataflow_id": _SHORT_ID,
                "dataflow_name": "Test",
                "description": "",
                "symbol": "",
            }
        ]
        monkeypatch.setattr(
            seeded_meta,
            "list_dataflows",
            lambda topic=None: [
                {
                    "label": "Test Dataflow",
                    "value": _FULL_ID,
                    "subtopic": "PRICES",
                    "all_subtopics": ["PRICES"],
                }
            ],
        )
        monkeypatch.setattr(seeded_meta, "_detect_section_families", lambda: {})
        monkeypatch.setattr(seeded_meta, "_detect_country_families", lambda: {})
        result = await presentation_table_choices(
            seeded_meta, topic="ECO", subtopic="PRICES"
        )
        assert any(r["value"] == _SHORT_ID for r in result)

    async def test_step2_section_family_resolves(self, seeded_meta, monkeypatch):
        _seed_taxonomy(seeded_meta)
        section_child_full = "DSD_TEST@DF_TEST_SECTION"
        seeded_meta.dataflows[section_child_full] = {
            "id": section_child_full,
            "short_id": "DF_TEST_SECTION",
            "agency_id": "OECD",
            "version": "1.0",
            "name": "Section Child",
        }
        seeded_meta._short_id_map["DF_TEST_SECTION"] = section_child_full
        seeded_meta.dataflows[_FULL_ID]["annotations"] = {
            "NonProductionDataflow": "true"
        }
        monkeypatch.setattr(
            seeded_meta,
            "list_dataflows",
            lambda topic=None: [
                {
                    "label": "Test Dataflow",
                    "value": _FULL_ID,
                    "subtopic": "PRICES",
                    "all_subtopics": ["PRICES"],
                },
                {
                    "label": "Section Child",
                    "value": section_child_full,
                    "subtopic": "PRICES",
                    "all_subtopics": ["PRICES"],
                },
            ],
        )
        monkeypatch.setattr(
            seeded_meta,
            "_detect_section_families",
            lambda: {section_child_full: _FULL_ID},
        )
        monkeypatch.setattr(seeded_meta, "_detect_country_families", lambda: {})
        result = await presentation_table_choices(
            seeded_meta, topic="ECO", subtopic="PRICES"
        )
        values = [r["value"] for r in result]
        assert "DF_TEST_SECTION" in values

    async def test_step2_country_family_keeps_only_rep(self, seeded_meta, monkeypatch):
        _seed_taxonomy(seeded_meta)
        member_full = "DSD_TEST@DF_TEST_USA"
        seeded_meta.dataflows[member_full] = {
            "id": member_full,
            "short_id": "DF_TEST_USA",
            "agency_id": "OECD",
            "version": "1.0",
            "name": "USA",
        }
        seeded_meta._short_id_map["DF_TEST_USA"] = member_full
        monkeypatch.setattr(
            seeded_meta,
            "list_dataflows",
            lambda topic=None: [
                {
                    "label": "Test Dataflow",
                    "value": _FULL_ID,
                    "subtopic": "PRICES",
                    "all_subtopics": ["PRICES"],
                },
                {
                    "label": "USA",
                    "value": member_full,
                    "subtopic": "PRICES",
                    "all_subtopics": ["PRICES"],
                },
            ],
        )
        monkeypatch.setattr(seeded_meta, "_detect_section_families", lambda: {})
        monkeypatch.setattr(
            seeded_meta,
            "_detect_country_families",
            lambda: {
                _FULL_ID: {"representative": _FULL_ID},
                member_full: {"representative": _FULL_ID},
            },
        )
        result = await presentation_table_choices(
            seeded_meta, topic="ECO", subtopic="PRICES"
        )
        values = [r["value"] for r in result]
        assert "DF_TEST_USA" not in values

    async def test_step3_country_choices_no_country_dim(self, seeded_meta, monkeypatch):
        seeded_meta.datastructures[_FULL_ID]["dimensions"] = [
            d
            for d in seeded_meta.datastructures[_FULL_ID]["dimensions"]
            if d["id"] != "REF_AREA"
        ]
        result = await presentation_table_choices(
            seeded_meta, topic="ECO", subtopic="PRICES", table=f"{_SHORT_ID}::T01"
        )
        assert result == [{"label": "Select a Table", "value": ""}]

    async def test_step3_country_choices_returned(self, seeded_meta):
        _seed_availability(seeded_meta)
        seeded_meta.dataflows[_FULL_ID]["annotations"] = {"DEFAULT": "REF_AREA=USA"}
        result = await presentation_table_choices(
            seeded_meta, topic="ECO", subtopic="PRICES", table=f"{_SHORT_ID}::T01"
        )
        defaults = [o for o in result if o.get("default") == "true"]
        assert defaults
        assert defaults[0]["value"] == "USA"

    async def test_step3_with_nd_avail_pin_for_dim(self, seeded_meta):
        _seed_availability(seeded_meta)
        seeded_meta._availability_cache[f"{_FULL_ID}::MEASURE=CPI"] = {
            "REF_AREA": ["USA", "GBR"],
            "MEASURE": ["CPI"],
            "FREQ": ["A", "Q"],
        }
        seeded_meta.dataflows[_FULL_ID]["annotations"] = {
            "NOT_DISPLAYED": "MEASURE=CPI"
        }
        result = await presentation_table_choices(
            seeded_meta, topic="ECO", subtopic="PRICES", table=f"{_SHORT_ID}::T01"
        )
        assert result

    async def test_step4_freq_no_dim(self, seeded_meta):
        seeded_meta.datastructures[_FULL_ID]["dimensions"] = [
            d
            for d in seeded_meta.datastructures[_FULL_ID]["dimensions"]
            if d["id"] != "FREQ"
        ]
        _seed_availability(
            seeded_meta,
            **{k: v for k, v in {"REF_AREA": ["USA"], "MEASURE": ["CPI"]}.items()},
        )
        result = await presentation_table_choices(
            seeded_meta,
            topic="ECO",
            subtopic="PRICES",
            table=f"{_SHORT_ID}::T01",
            country="USA",
        )
        assert result == [{"label": "N/A (no frequency dimension)", "value": "_NA"}]

    async def test_step4_freq_pin_via_not_displayed(self, seeded_meta):
        _seed_availability(seeded_meta)
        seeded_meta.dataflows[_FULL_ID]["annotations"] = {"NOT_DISPLAYED": "FREQ=A"}
        result = await presentation_table_choices(
            seeded_meta,
            topic="ECO",
            subtopic="PRICES",
            table=f"{_SHORT_ID}::T01",
            country="USA",
        )
        assert result == [{"label": "Annual", "value": "A"}]

    async def test_step4_freq_pin_empty(self, seeded_meta):
        _seed_availability(seeded_meta)
        seeded_meta.dataflows[_FULL_ID]["annotations"] = {"NOT_DISPLAYED": "FREQ="}
        result = await presentation_table_choices(
            seeded_meta,
            topic="ECO",
            subtopic="PRICES",
            table=f"{_SHORT_ID}::T01",
            country="USA",
        )
        assert result == []

    async def test_step4_freq_default_marked(self, seeded_meta):
        _seed_availability(seeded_meta)
        _seed_availability(
            seeded_meta,
            **{"REF_AREA": ["USA"]},
        )
        seeded_meta._availability_cache[f"{_FULL_ID}::REF_AREA=USA"] = {
            "REF_AREA": ["USA"],
            "MEASURE": ["CPI"],
            "FREQ": ["A", "Q"],
        }
        seeded_meta.dataflows[_FULL_ID]["annotations"] = {"DEFAULT": "FREQ=Q"}
        result = await presentation_table_choices(
            seeded_meta,
            topic="ECO",
            subtopic="PRICES",
            table=f"{_SHORT_ID}::T01",
            country="USA",
        )
        defaults = [o for o in result if o.get("default") == "true"]
        assert defaults
        assert defaults[0]["value"] == "Q"

    async def test_all_specified_returns_empty(self, seeded_meta):
        _seed_availability(seeded_meta)
        seeded_meta._availability_cache[f"{_FULL_ID}::REF_AREA=USA"] = {
            "REF_AREA": ["USA"],
            "MEASURE": ["CPI"],
            "FREQ": ["A"],
        }
        result = await presentation_table_choices(
            seeded_meta,
            topic="ECO",
            subtopic="PRICES",
            table=f"{_SHORT_ID}::T01",
            country="USA",
            frequency="A",
        )
        assert result == []

    async def test_nd_pin_with_plus_skipped(self, seeded_meta):
        _seed_availability(seeded_meta)
        seeded_meta.dataflows[_FULL_ID]["annotations"] = {
            "NOT_DISPLAYED": "MEASURE=CPI+PPI"
        }
        result = await presentation_table_choices(
            seeded_meta, topic="ECO", subtopic="PRICES", table=f"{_SHORT_ID}::T01"
        )
        assert result


@pytest.mark.asyncio
class TestPresentationTableDimChoices:
    async def test_no_table(self, seeded_meta):
        result = await presentation_table_dim_choices(
            seeded_meta, table="", dimension="unit_measure"
        )
        assert result == []

    async def test_dim_blocked_by_not_displayed(self, seeded_meta):
        seeded_meta.dataflows[_FULL_ID]["annotations"] = {
            "NOT_DISPLAYED": "MEASURE=CPI"
        }
        result = await presentation_table_dim_choices(
            seeded_meta, table=f"{_SHORT_ID}::T01", dimension="MEASURE"
        )
        assert result == []

    async def test_dim_not_in_dsd(self, seeded_meta):
        result = await presentation_table_dim_choices(
            seeded_meta, table=f"{_SHORT_ID}::T01", dimension="unit_measure"
        )
        assert result == []

    async def test_dim_options_returned(self, seeded_meta):
        _seed_availability(seeded_meta)
        _seed_availability(
            seeded_meta,
            **{"REF_AREA": ["USA"], "MEASURE": ["CPI", "PPI"], "FREQ": ["A"]},
        )
        seeded_meta._availability_cache[f"{_FULL_ID}::FREQ=A|REF_AREA=USA"] = {
            "REF_AREA": ["USA"],
            "MEASURE": ["CPI", "PPI"],
            "FREQ": ["A"],
        }
        seeded_meta.codelists["OECD:CL_MEASURE(1.0)"]["PPI"] = "Producer Price Index"
        seeded_meta._dataflow_constraints[_FULL_ID]["MEASURE"] = ["CPI", "PPI"]
        seeded_meta._dataflow_parameters_cache.pop(_FULL_ID, None)
        seeded_meta.dataflows[_FULL_ID]["annotations"] = {"DEFAULT": "MEASURE=CPI"}
        result = await presentation_table_dim_choices(
            seeded_meta,
            table=f"{_SHORT_ID}::T01",
            dimension="MEASURE",
            country="USA",
            frequency="A",
        )
        values = [r["value"] for r in result]
        assert "auto" in values
        assert "all" in values
        defaults = [o for o in result if o.get("default") is True]
        assert defaults

    async def test_single_option_returned_directly(self, seeded_meta):
        _seed_availability(
            seeded_meta,
            **{"REF_AREA": ["USA"], "MEASURE": ["CPI"], "FREQ": ["A"]},
        )
        seeded_meta._availability_cache[f"{_FULL_ID}::FREQ=A|REF_AREA=USA"] = {
            "REF_AREA": ["USA"],
            "MEASURE": ["CPI"],
            "FREQ": ["A"],
        }
        result = await presentation_table_dim_choices(
            seeded_meta,
            table=f"{_SHORT_ID}::T01",
            dimension="MEASURE",
            country="USA",
            frequency="A",
        )
        assert len(result) == 1

    async def test_filters_out_not_applicable_labels(self, seeded_meta):
        seeded_meta.codelists["OECD:CL_MEASURE(1.0)"]["NA1"] = "Not Applicable"
        seeded_meta._dataflow_constraints[_FULL_ID]["MEASURE"] = ["NA1"]
        seeded_meta._dataflow_parameters_cache.pop(_FULL_ID, None)
        _seed_availability(seeded_meta, **{"MEASURE": ["NA1"]})
        seeded_meta._availability_cache[f"{_FULL_ID}::FREQ=A|REF_AREA=USA"] = {
            "REF_AREA": ["USA"],
            "MEASURE": ["NA1"],
            "FREQ": ["A"],
        }
        result = await presentation_table_dim_choices(
            seeded_meta,
            table=f"{_SHORT_ID}::T01",
            dimension="MEASURE",
            country="USA",
            frequency="A",
        )
        assert result == []

    async def test_with_nd_pin_for_dim(self, seeded_meta):
        seeded_meta.codelists["OECD:CL_MEASURE(1.0)"]["PPI"] = "Producer Price Index"
        seeded_meta._dataflow_constraints[_FULL_ID]["MEASURE"] = ["CPI", "PPI"]
        seeded_meta._dataflow_parameters_cache.pop(_FULL_ID, None)
        _seed_availability(seeded_meta, **{"MEASURE": ["CPI", "PPI"]})
        seeded_meta._availability_cache[
            f"{_FULL_ID}::FREQ=A|MEASURE=CPI|REF_AREA=USA"
        ] = {
            "REF_AREA": ["USA"],
            "MEASURE": ["CPI", "PPI"],
            "FREQ": ["A"],
        }
        seeded_meta.dataflows[_FULL_ID]["annotations"] = {
            "NOT_DISPLAYED": "MEASURE=CPI"
        }
        result = await presentation_table_dim_choices(
            seeded_meta,
            table=f"{_SHORT_ID}::T01",
            dimension="REF_AREA",
            country="USA",
            frequency="A",
        )
        assert isinstance(result, list)

    async def test_frequency_autoselect_when_single(self, seeded_meta):
        _seed_availability(
            seeded_meta,
            **{"REF_AREA": ["USA"], "MEASURE": ["CPI"], "FREQ": ["A"]},
        )
        seeded_meta._availability_cache[f"{_FULL_ID}::REF_AREA=USA"] = {
            "REF_AREA": ["USA"],
            "MEASURE": ["CPI"],
            "FREQ": ["A"],
        }
        seeded_meta._availability_cache[f"{_FULL_ID}::FREQ=A|REF_AREA=USA"] = {
            "REF_AREA": ["USA"],
            "MEASURE": ["CPI"],
            "FREQ": ["A"],
        }
        result = await presentation_table_dim_choices(
            seeded_meta,
            table=f"{_SHORT_ID}::T01",
            dimension="MEASURE",
            country="USA",
        )
        assert result


def _make_table_result(rows, fixed_dims=None, unit="USD", currency="", price_base=""):
    return {
        "data": rows,
        "table_metadata": {
            "fixed_dimensions": fixed_dims or {},
            "unit_measure": unit,
            "currency": currency,
            "price_base": price_base,
        },
    }


@pytest.mark.asyncio
class TestPresentationTable:
    async def test_missing_table_raises(self):
        with pytest.raises(OpenBBError):
            await presentation_table()

    async def test_missing_country_raises(self):
        with pytest.raises(OpenBBError):
            await presentation_table(table=f"{_SHORT_ID}::T01")

    async def test_builder_error_wrapped(self):
        with patch(
            "openbb_oecd.utils.table_builder.OecdTableBuilder.get_table",
            side_effect=ValueError("boom"),
        ):
            with pytest.raises(OpenBBError):
                await presentation_table(table=f"{_SHORT_ID}::T01", country="USA")

    async def test_no_data_rows_raises(self):
        with patch(
            "openbb_oecd.utils.table_builder.OecdTableBuilder.get_table",
            return_value=_make_table_result([]),
        ):
            with pytest.raises(OpenBBError):
                await presentation_table(table=f"{_SHORT_ID}::T01", country="USA")

    async def test_happy_path_uniform_units(self):
        rows = [
            {
                "time_period": "2024-Q1",
                "ref_area": "USA",
                "label": "GDP",
                "value": 1.0,
                "order": 0,
                "level": 0,
                "_acct_sort": 0,
                "_child_order": 0,
                "_sub_order": 0,
                "_compound_order": 0,
                "code": "GDP",
                "is_category_header": False,
                "unit_measure": "USD",
                "currency_denom": "USD",
                "currency": "USD",
                "price_base": "Current prices",
            },
            {
                "time_period": "2024-Q2",
                "ref_area": "USA",
                "label": "GDP",
                "value": 1.1,
                "order": 0,
                "level": 1,
                "_acct_sort": 0,
                "_child_order": 0,
                "_sub_order": 0,
                "_compound_order": 0,
                "code": "GDP",
                "is_category_header": False,
                "unit_measure": "USD",
                "currency_denom": "USD",
                "currency": "USD",
                "price_base": "Current prices",
            },
        ]
        fixed = {"REF_AREA": {"label": "United States"}}
        with patch(
            "openbb_oecd.utils.table_builder.OecdTableBuilder.get_table",
            return_value=_make_table_result(
                rows,
                fixed_dims=fixed,
                unit="USD",
                currency="USD",
                price_base="Current prices",
            ),
        ):
            result = await presentation_table(
                table=f"{_SHORT_ID}::T01",
                country="USA",
                frequency="Q",
                limit=2,
            )
        assert isinstance(result, list)
        title_row = result[0]
        assert title_row["title"]

    async def test_currency_added_when_different_from_unit(self):
        rows = [
            {
                "time_period": "2024",
                "ref_area": "USA",
                "label": "GDP",
                "value": 1.0,
                "order": 0,
                "level": 0,
                "_acct_sort": 0,
                "_child_order": 0,
                "_sub_order": 0,
                "_compound_order": 0,
                "code": "GDP",
                "is_category_header": False,
            }
        ]
        with patch(
            "openbb_oecd.utils.table_builder.OecdTableBuilder.get_table",
            return_value=_make_table_result(
                rows, unit="Persons", currency="USD", price_base="Current"
            ),
        ):
            result = await presentation_table(table=f"{_SHORT_ID}::T01", country="USA")
        assert isinstance(result, list)
        # Title row carries the subtitle with both unit and currency.
        assert "USD" in result[0]["title"]

    async def test_units_vary_appended(self):
        rows = [
            {
                "time_period": "2024",
                "ref_area": "USA",
                "label": "Indicator A",
                "value": 5.0,
                "order": 0,
                "level": 0,
                "_acct_sort": 0,
                "_child_order": 0,
                "_sub_order": 0,
                "_compound_order": 0,
                "code": "A",
                "is_category_header": False,
                "unit_measure": "USD",
            },
            {
                "time_period": "2024",
                "ref_area": "USA",
                "label": "Indicator B",
                "value": 6.0,
                "order": 1,
                "level": 0,
                "_acct_sort": 0,
                "_child_order": 0,
                "_sub_order": 0,
                "_compound_order": 0,
                "code": "B",
                "is_category_header": False,
                "unit_measure": "EUR",
            },
            {
                "time_period": "2024",
                "ref_area": "USA",
                "label": "Header",
                "value": 7.0,
                "order": 2,
                "level": 0,
                "_acct_sort": 0,
                "_child_order": 0,
                "_sub_order": 0,
                "_compound_order": 0,
                "code": "H",
                "is_category_header": True,
                "unit_measure": "GBP",
            },
        ]
        with patch(
            "openbb_oecd.utils.table_builder.OecdTableBuilder.get_table",
            return_value=_make_table_result(rows, unit=""),
        ):
            result = await presentation_table(
                table=f"{_SHORT_ID}::T01",
                country="USA",
            )
        titles = [r.get("title", "") for r in result]
        assert any("(USD)" in t for t in titles) or any("(EUR)" in t for t in titles)

    async def test_dimension_values_parsed_and_special_values(self):
        rows = [
            {
                "time_period": "",
                "ref_area": "",
                "label": "Foo",
                "value": 1.0,
                "order": 0,
                "level": 0,
                "_acct_sort": 0,
                "_child_order": 0,
                "_sub_order": 0,
                "_compound_order": 0,
                "code": "X",
                "is_category_header": False,
            }
        ]
        with patch(
            "openbb_oecd.utils.table_builder.OecdTableBuilder.get_table",
            return_value=_make_table_result(rows),
        ) as mock_get:
            await presentation_table(
                table=f"{_SHORT_ID}::T01",
                country="USA",
                counterpart="all",
                unit_measure="auto",
                adjustment="Y",
                transformation="all",
                dimension_values=["DIM_X:VAL1,DIM_Y:VAL2"],
                frequency="_NA",
            )
        call_kwargs = mock_get.call_args.kwargs
        extras = call_kwargs.get("dimension_filters") or {}
        assert call_kwargs.get("frequency") is None
        assert extras.get("ADJUSTMENT") == "Y"
        assert extras.get("COUNTERPART_AREA") == "*"
        assert extras.get("TRANSFORMATION") == "*"
        assert extras.get("DIM_X") == "VAL1"
        assert extras.get("DIM_Y") == "VAL2"

    async def test_dimension_values_string_form(self):
        rows = [
            {
                "time_period": "2024",
                "ref_area": "USA",
                "label": "GDP",
                "value": 1.0,
                "order": 0,
                "level": 0,
                "_acct_sort": 0,
                "_child_order": 0,
                "_sub_order": 0,
                "_compound_order": 0,
                "code": "GDP",
                "is_category_header": False,
            }
        ]
        with patch(
            "openbb_oecd.utils.table_builder.OecdTableBuilder.get_table",
            return_value=_make_table_result(rows),
        ) as mock_get:
            await presentation_table(
                table=f"{_SHORT_ID}::T01",
                country="USA",
                dimension_values="DIM_Z:VALZ",
            )
        assert (mock_get.call_args.kwargs.get("dimension_filters") or {}).get(
            "DIM_Z"
        ) == "VALZ"

    async def test_dimension_values_with_bad_entries(self):
        rows = [
            {
                "time_period": "2024",
                "ref_area": "USA",
                "label": "GDP",
                "value": 1.0,
                "order": 0,
                "level": 0,
                "_acct_sort": 0,
                "_child_order": 0,
                "_sub_order": 0,
                "_compound_order": 0,
                "code": "GDP",
                "is_category_header": False,
            }
        ]
        with patch(
            "openbb_oecd.utils.table_builder.OecdTableBuilder.get_table",
            return_value=_make_table_result(rows),
        ) as mock_get:
            await presentation_table(
                table=f"{_SHORT_ID}::T01",
                country="USA",
                dimension_values=["", None, "INVALID_NO_COLON"],
            )
        # Garbage entries are ignored, but call still succeeds.
        assert mock_get.called

    async def test_pivot_failure_falls_back(self):
        rows = [
            {
                "time_period": "2024",
                "ref_area": "USA",
                "label": "GDP",
                "value": 1.0,
                "order": 0,
                "level": 0,
                "_acct_sort": 0,
                "_child_order": 0,
                "_sub_order": 0,
                "_compound_order": 0,
                "code": "GDP",
                "is_category_header": False,
            }
        ]
        from pandas import DataFrame as RealDF

        original_pivot = RealDF.pivot_table

        def broken_pivot(self, *args, **kwargs):
            raise ValueError("pivot failed")

        with (
            patch(
                "openbb_oecd.utils.table_builder.OecdTableBuilder.get_table",
                return_value=_make_table_result(rows),
            ),
            patch.object(RealDF, "pivot_table", broken_pivot),
        ):
            try:
                result = await presentation_table(
                    table=f"{_SHORT_ID}::T01", country="USA"
                )
            finally:
                RealDF.pivot_table = original_pivot
        assert isinstance(result, list)

    async def test_fixed_country_fallback_from_metadata(self):
        rows = [
            {
                "time_period": "2024",
                "ref_area": "",
                "country": "",
                "label": "X",
                "value": 1.0,
                "order": 0,
                "level": 0,
                "_acct_sort": 0,
                "_child_order": 0,
                "_sub_order": 0,
                "_compound_order": 0,
                "code": "X",
                "is_category_header": False,
            }
        ]
        with patch(
            "openbb_oecd.utils.table_builder.OecdTableBuilder.get_table",
            return_value=_make_table_result(
                rows, fixed_dims={"COUNTRY": {"label": "USA"}}
            ),
        ):
            result = await presentation_table(table=f"{_SHORT_ID}::T01", country="USA")
        # country column dropped because only one value
        assert all("country" not in r for r in result)


@pytest.mark.asyncio
class TestGetOecdAppsJson:
    async def test_returns_list(self):
        result = await get_oecd_apps_json()
        assert isinstance(result, list)

    async def test_presentation_table_opens_without_an_end_date(self):
        """A saved end_date plus the widget's row limit asked OECD for no data."""
        import json

        assert '"end_date"' not in json.dumps(await get_oecd_apps_json())

    async def test_returns_empty_on_missing_file(self, monkeypatch, tmp_path):
        from openbb_oecd import oecd_router as router_mod

        fake_apps = tmp_path / "nonexistent_apps.json"
        original_init_file = router_mod.__file__
        monkeypatch.setattr(
            router_mod, "__file__", str(fake_apps.parent / "fake_router.py")
        )
        result = await get_oecd_apps_json()
        assert isinstance(result, list)
        router_mod.__file__ = original_init_file


class TestRewriteWidgetIds:
    """Tests for ``_rewrite_widget_ids`` and the apps.json fallback path."""

    def test_rewrites_mapped_ids_and_preserves_unmapped(self):
        """Only IDs in the fallback map are rewritten; everything else passes through."""
        apps = [
            {
                "tabs": {
                    "a": {
                        "layout": [
                            {"i": "economy_cpi_oecd_obb"},
                            {"i": "oecd_presentation_table_custom_obb"},
                        ]
                    },
                    "b": {
                        "layout": [
                            {"i": "economy_gdp_real_oecd_obb"},
                        ]
                    },
                }
            }
        ]
        out = _rewrite_widget_ids(apps)
        layout_a = [w["i"] for w in out[0]["tabs"]["a"]["layout"]]
        layout_b = [w["i"] for w in out[0]["tabs"]["b"]["layout"]]
        assert layout_a == [
            _APPS_WIDGET_ID_FALLBACK_MAP["economy_cpi_oecd_obb"],
            "oecd_presentation_table_custom_obb",
        ]
        assert layout_b == [_APPS_WIDGET_ID_FALLBACK_MAP["economy_gdp_real_oecd_obb"]]

    def test_tolerates_missing_tabs_and_layout(self):
        """Apps without ``tabs`` or with ``layout=None`` are skipped gracefully."""
        apps = [
            {},
            {"tabs": {}},
            {"tabs": {"x": {}}},
            {"tabs": {"x": {"layout": None}}},
            {"tabs": {"x": {"layout": [{"i": "economy_cpi_oecd_obb"}]}}},
        ]
        out = _rewrite_widget_ids(apps)
        rewritten = out[-1]["tabs"]["x"]["layout"][0]["i"]
        assert rewritten == _APPS_WIDGET_ID_FALLBACK_MAP["economy_cpi_oecd_obb"]

    @pytest.mark.asyncio
    async def test_get_oecd_apps_json_rewrites_when_economy_absent(
        self, tmp_path, monkeypatch
    ):
        """When ``ECONOMY_INSTALLED`` is False the served apps.json has rewritten IDs."""
        from openbb_oecd import oecd_router as router_module

        apps_path = tmp_path / "apps.json"
        apps_path.write_text(
            '[{"tabs": {"cpi": {"layout": [{"i": "economy_cpi_oecd_obb"}]}}}]',
            encoding="utf-8",
        )
        monkeypatch.setattr(router_module, "__file__", str(tmp_path / "oecd_router.py"))
        monkeypatch.setattr(router_module, "ECONOMY_INSTALLED", False)

        apps = await get_oecd_apps_json()
        assert (
            apps[0]["tabs"]["cpi"]["layout"][0]["i"]
            == (_APPS_WIDGET_ID_FALLBACK_MAP["economy_cpi_oecd_obb"])
        )


def _load_standalone_router_module():
    """Re-execute ``oecd_router`` with ``ECONOMY_INSTALLED`` forced to False.

    Loaded under a private module name so the global ``openbb_oecd.oecd_router``
    used elsewhere in the suite is untouched. ``Router.command`` is replaced
    during load with a passthrough decorator so the fallback endpoints bind
    without requiring the OECD-prefixed models to exist in the live provider
    registry or FastAPI's response-model machinery.
    """
    import importlib.util
    from pathlib import Path

    from openbb_core.app.router import Router

    import openbb_oecd

    spec = importlib.util.spec_from_file_location(
        "openbb_oecd_oecd_router_standalone",
        Path(openbb_oecd.__file__).parent / "oecd_router.py",
    )
    module = importlib.util.module_from_spec(spec)
    original_economy = openbb_oecd.ECONOMY_INSTALLED
    original_command = Router.command
    openbb_oecd.ECONOMY_INSTALLED = False

    def _passthrough_command(self, func=None, **_kwargs):
        """Bind ``func`` to the caller without touching the underlying FastAPI router."""
        if func is None:
            return lambda f: _passthrough_command(self, f, **_kwargs)
        return func

    Router.command = _passthrough_command  # type: ignore[assignment]
    try:
        spec.loader.exec_module(module)
    finally:
        openbb_oecd.ECONOMY_INSTALLED = original_economy
        Router.command = original_command  # type: ignore[assignment]
    return module


class TestStandaloneFallbackEndpoints:
    """Tests for the twelve endpoints registered only when ``openbb-economy`` is absent."""

    _STANDALONE_NAMES = (
        "available_indicators",
        "indicators",
        "balance_of_payments",
        "composite_leading_indicator",
        "cpi",
        "country_interest_rates",
        "gdp_nominal",
        "gdp_real",
        "gdp_forecast",
        "house_price_index",
        "share_price_index",
        "unemployment",
    )

    def test_standalone_module_binds_all_fallback_endpoint_names(self):
        """All twelve fallback endpoint names exist as module attributes after reload."""
        module = _load_standalone_router_module()
        for name in self._STANDALONE_NAMES:
            assert callable(getattr(module, name, None)), f"missing {name}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint_name", _STANDALONE_NAMES)
    async def test_standalone_endpoint_body_delegates_to_from_query(
        self, endpoint_name
    ):
        """Each fallback endpoint body calls ``OBBject.from_query(OBBQuery(**locals()))``."""
        from unittest.mock import AsyncMock, MagicMock

        module = _load_standalone_router_module()
        fn = getattr(module, endpoint_name)

        sentinel = object()
        with (
            patch.object(module, "OBBQuery", new=MagicMock()),
            patch.object(
                module.OBBject,
                "from_query",
                new=AsyncMock(return_value=sentinel),
            ) as mock_from_query,
        ):
            out = await fn(
                cc=MagicMock(),
                provider_choices=MagicMock(),
                standard_params=MagicMock(),
                extra_params=MagicMock(),
            )
        assert out is sentinel
        mock_from_query.assert_awaited_once()


class TestWarmupHook:
    """Coverage for the FastAPI startup warmup hook."""

    def test_warm_oecd_metadata_primes_singleton_and_table_map(self, monkeypatch):
        """``_warm_oecd_metadata`` instantiates the singleton and walks ``table_map``."""
        from openbb_oecd import oecd_router as router_module
        from openbb_oecd.utils import metadata as metadata_pkg

        calls: list[str] = []

        class _Stub:
            def table_map(self_inner):
                calls.append("table_map")
                return []

        stub = _Stub()
        monkeypatch.setattr(metadata_pkg, "OecdMetadata", lambda: stub)
        router_module._warm_oecd_metadata()
        assert calls == ["table_map"]
