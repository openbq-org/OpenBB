"""Tests for the per-institution BHCPR data fetcher model."""

from datetime import datetime
from pathlib import Path

import pytest
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import ValidationError

from openbb_federal_reserve.models.ffiec.bhcpr import (
    FederalReserveBhcprData,
    FederalReserveBhcprFetcher,
    _default_period,
    _filed_periods,
    _iso_to_display,
    _quarter_end,
    _resolve_period,
    _unit,
)

_NBSP = " "
_FIXTURE = Path(__file__).parent / "fixtures" / "bhcpr" / "1039502_20260331.csv"

_REPORTS = {
    "BHCPR": {
        "name": "BHCPR",
        "periods": [
            {"year": 2026, "quarter": 1, "month_day": "3/31"},
            {"year": 2025, "quarter": 4, "month_day": "12/31"},
        ],
    }
}

_SCHEMA = [
    {
        "section": "Summary Ratios",
        "entries": [
            {"kind": "subheader", "label": "Earnings and Profitability", "level": 0},
            {
                "kind": "item",
                "label": "Net Interest Income (Tax Equivalent)",
                "level": 1,
                "code": "BHSR028",
                "basis": "Percent of Average Assets",
                "definition": "NII on a TE basis divided by average assets.",
            },
            {
                "kind": "item",
                "label": "Average Assets ($000)",
                "level": 1,
                "code": "BHSR029",
                "basis": "Dollar Amount in Thousands",
                "definition": None,
            },
            {
                "kind": "item",
                "label": "Operating Income",
                "level": 1,
                "code": None,
                "basis": None,
                "definition": None,
            },
        ],
    },
    {
        "section": "Assets",
        "entries": [
            {
                "kind": "item",
                "label": "Total Assets",
                "level": 0,
                "code": "BHCK2170",
                "basis": "Dollar Amount in Thousands",
                "definition": None,
            },
        ],
    },
]

_DATA = {
    "identity": {
        "institution_name": "JPMORGAN CHASE & CO.",
        "city_state": "NEW YORK, NY",
        "rssd_id": "1039502",
    },
    "periods": {
        "": "20260331",
        "_4Q": "20250331",
        "_1Y": "20251231",
        "_2Y": "20241231",
        "_3Y": "20231231",
    },
    "values": {
        "BHSR028": {"": 2.15, "_4Q": 2.22, "_1Y": 2.17, "_2Y": 2.29, "_3Y": 2.35},
        "PHSR028": {"": 3.08},
        "RKSR028": {"": 11},
        "BHSR029": {"": 4759098000},
        "BHCK2170": {"": 4900475000, "_4Q": 4357856000},
    },
    "descriptions": {},
}


def _patch(monkeypatch, data=None, reports=None):
    """Patch the BHCPR fetch, holder resolution, profile lookup, and schema loader."""
    monkeypatch.setattr(
        "openbb_federal_reserve.utils.ffiec.resolve_bhcpr_holder",
        lambda rssd: rssd,
    )
    monkeypatch.setattr(
        "openbb_federal_reserve.utils.ffiec.fetch_bhcpr",
        lambda rssd_id, date: dict(data if data is not None else _DATA),
    )
    monkeypatch.setattr(
        "openbb_federal_reserve.utils.ffiec.fetch_institution_financial_reports",
        lambda rssd: dict(reports if reports is not None else _REPORTS),
    )
    monkeypatch.setattr(
        "openbb_federal_reserve.utils.bhcpr_schema.load_schema",
        lambda: [dict(entry) for entry in _SCHEMA],
    )


class TestUnit:
    """Tests for the ``_unit`` basis-to-value-type map."""

    @pytest.mark.parametrize(
        ("basis", "expected"),
        [
            ("Dollar Amount in Thousands", "USD"),
            ("Multiple (X)", "ratio"),
            ("Number", "number"),
            ("Percent of Average Assets", "percent"),
            (None, "percent"),
        ],
    )
    def test_maps_basis_to_value_type(self, basis, expected):
        """Each guide basis renders as its value type."""
        assert _unit(basis) == expected


class TestIsoToDisplay:
    """Tests for ``_iso_to_display``."""

    def test_renders_iso_as_us_date(self):
        """An ISO date renders as ``MM/DD/YYYY``."""
        assert _iso_to_display("2026-03-31") == "03/31/2026"


class TestQuarterEnd:
    """Tests for ``_quarter_end``."""

    @pytest.mark.parametrize(
        ("quarter", "expected"),
        [(1, "20250331"), (2, "20250630"), (3, "20250930"), (4, "20251231")],
    )
    def test_each_quarter_maps_to_its_end(self, quarter, expected):
        """Each quarter maps to its calendar quarter-end date."""
        assert _quarter_end(2025, quarter) == expected


class TestDefaultPeriod:
    """Tests for the ``_default_period`` availability heuristic."""

    def _freeze(self, monkeypatch, when):
        """Freeze the module clock at a fixed datetime."""

        class _Now:
            """Frozen clock returning a fixed date."""

            @staticmethod
            def now():
                """Return the fixed datetime."""
                return when

        monkeypatch.setattr("openbb_federal_reserve.models.ffiec.bhcpr.datetime", _Now)

    def test_walks_back_within_year(self, monkeypatch):
        """A mid-year date walks back to the latest filed quarter without wrapping."""
        self._freeze(monkeypatch, datetime(2025, 11, 10))
        assert _default_period() == (2025, 3)

    def test_walks_back_across_year(self, monkeypatch):
        """An early-quarter date walks back across the year boundary."""
        self._freeze(monkeypatch, datetime(2025, 1, 10))
        assert _default_period() == (2024, 3)


class TestResolvePeriod:
    """Tests for ``_resolve_period``."""

    def test_explicit_period_passes_through(self):
        """A supplied YYYYMMDD period is used verbatim, trimmed."""
        assert _resolve_period(" 20260331 ", ["20251231"]) == "20260331"

    def test_blank_period_defaults_to_latest_filed(self):
        """A blank period falls back to the firm's latest filed period."""
        assert _resolve_period(None, ["20260331", "20251231"]) == "20260331"
        assert _resolve_period("", ["20260331", "20251231"]) == "20260331"

    def test_no_filed_periods_falls_back_to_heuristic(self, monkeypatch):
        """With no filed period known, the calendar-quarter heuristic is used."""
        monkeypatch.setattr(
            "openbb_federal_reserve.models.ffiec.bhcpr._default_period",
            lambda: (2025, 2),
        )
        assert _resolve_period(None, []) == "20250630"


class TestFiledPeriods:
    """Tests for ``_filed_periods``."""

    def test_returns_filed_period_ends_newest_first(self, monkeypatch):
        """The firm's filed BHCPR periods become YYYYMMDD ends, newest first."""
        monkeypatch.setattr(
            "openbb_federal_reserve.utils.ffiec.fetch_institution_financial_reports",
            lambda rssd: dict(_REPORTS),
        )
        assert _filed_periods("1039502") == ["20260331", "20251231"]

    def test_listed_quarter_with_no_report_yet_is_left_out(self, monkeypatch):
        """A quarter the NIC lists before its report is published is skipped."""
        reports = {
            "BHCPR": {
                "periods": [
                    {"year": 2026, "quarter": 3, "pdf_available": False},
                    {"year": 2026, "quarter": 2, "pdf_available": True},
                ]
            }
        }
        monkeypatch.setattr(
            "openbb_federal_reserve.utils.ffiec.fetch_institution_financial_reports",
            lambda rssd: reports,
        )
        assert _filed_periods("1039502") == ["20260630"]

    def test_blank_rssd_returns_empty(self):
        """A blank RSSD yields no filed periods without a fetch."""
        assert _filed_periods("") == []

    def test_non_mapping_profile_returns_empty(self, monkeypatch):
        """A non-mapping profile result yields no filed periods."""
        monkeypatch.setattr(
            "openbb_federal_reserve.utils.ffiec.fetch_institution_financial_reports",
            lambda rssd: ["BHCPR"],
        )
        assert _filed_periods("1039502") == []

    def test_profile_failure_returns_empty(self, monkeypatch):
        """An unavailable profile yields no filed periods rather than raising."""

        def _boom(rssd):
            """Raise to simulate an unavailable NIC profile."""
            raise RuntimeError("profile down")

        monkeypatch.setattr(
            "openbb_federal_reserve.utils.ffiec.fetch_institution_financial_reports",
            _boom,
        )
        assert _filed_periods("1039502") == []


class TestTransformQuery:
    """Tests for ``transform_query`` validation."""

    def test_requires_rssd_id(self):
        """Omitting the required rssd_id raises a validation error."""
        with pytest.raises(ValidationError):
            FederalReserveBhcprFetcher.transform_query({})

    def test_defaults_section_to_summary_ratios(self):
        """The section defaults to Summary Ratios."""
        query = FederalReserveBhcprFetcher.transform_query({"rssd_id": "1039502"})
        assert query.section == "Summary Ratios"


class TestExtractData:
    """Tests for ``extract_data`` selection and period defaulting."""

    def test_fetches_resolved_holder_and_period(self, monkeypatch):
        """The resolved holder RSSD and period drive the fetch."""
        captured: dict = {}
        _patch(monkeypatch)
        monkeypatch.setattr(
            "openbb_federal_reserve.utils.ffiec.fetch_bhcpr",
            lambda rssd_id, date: (
                captured.update(rssd=rssd_id, date=date) or dict(_DATA)
            ),
        )
        query = FederalReserveBhcprFetcher.transform_query(
            {"rssd_id": "1039502", "period": "20260331"}
        )
        data = FederalReserveBhcprFetcher.extract_data(query, None)
        assert captured == {"rssd": "1039502", "date": "20260331"}
        assert data["values"]["BHSR028"][""] == 2.15

    def test_defaults_period_to_latest_filed_when_omitted(self, monkeypatch):
        """Omitting the period defaults it to the firm's latest filed period."""
        captured: dict = {}
        _patch(monkeypatch)
        monkeypatch.setattr(
            "openbb_federal_reserve.utils.ffiec.fetch_bhcpr",
            lambda rssd_id, date: captured.update(date=date) or dict(_DATA),
        )
        query = FederalReserveBhcprFetcher.transform_query({"rssd_id": "1039502"})
        FederalReserveBhcprFetcher.extract_data(query, None)
        assert captured["date"] == "20260331"

    def test_empty_values_raise_empty(self, monkeypatch):
        """A payload with no coded values raises ``EmptyDataError``."""
        _patch(monkeypatch, {**_DATA, "values": {}})
        query = FederalReserveBhcprFetcher.transform_query(
            {"rssd_id": "1039502", "period": "20250331"}
        )
        with pytest.raises(EmptyDataError):
            FederalReserveBhcprFetcher.extract_data(query, None)


class TestTransformData:
    """Tests for ``transform_data`` grouped rendering."""

    def _result(self, monkeypatch, params=None):
        """Run the full extract/transform pipeline against the miniature payload."""
        _patch(monkeypatch)
        query = FederalReserveBhcprFetcher.transform_query(
            {"rssd_id": "1039502", "period": "20260331", **(params or {})}
        )
        data = FederalReserveBhcprFetcher.extract_data(query, None)
        return FederalReserveBhcprFetcher.transform_data(query, data)

    def test_returns_annotated_result_with_metadata(self, monkeypatch):
        """The result is annotated with the RSSD, name, city/state, and date."""
        result = self._result(monkeypatch)
        assert isinstance(result, AnnotatedResult)
        assert result.metadata == {
            "rssd_id": "1039502",
            "name": "JPMORGAN CHASE & CO.",
            "city_state": "NEW YORK, NY",
            "section": "Summary Ratios",
            "reporting_date": "2026-03-31",
        }

    def test_emits_section_header(self, monkeypatch):
        """The selected section opens with a header row carrying no unit."""
        rows = self._result(monkeypatch).result
        assert rows[0].label == "Summary Ratios"
        assert rows[0].is_header is True
        assert rows[0].unit is None

    def test_subheader_rendered_as_indented_header(self, monkeypatch):
        """A section's sub-header is an indented header row."""
        rows = self._result(monkeypatch).result
        sub = next(r for r in rows if r.label.strip() == "Earnings and Profitability")
        assert sub.is_header is True
        assert sub.label == _NBSP * 2 + "Earnings and Profitability"

    def test_ratio_row_carries_bhc_peer_and_percentile(self, monkeypatch):
        """A ratio row carries the BHC value, peer average, and percentile rank."""
        rows = self._result(monkeypatch).result
        ratio = next(r for r in rows if r.label.endswith("(Tax Equivalent)"))
        assert ratio.unit == "percent"
        dumped = ratio.model_dump()
        assert dumped["03/31/2026 BHC"] == 2.15
        assert dumped["03/31/2026 Peer #"] == 3.08
        assert dumped["03/31/2026 Pct"] == 11
        assert dumped["03/31/2025 BHC"] == 2.22

    def test_dollar_row_scaled_and_unit_suffix_stripped(self, monkeypatch):
        """A dollar row scales thousands to full dollars and drops the ``($000)``."""
        rows = self._result(monkeypatch).result
        avg = next(r for r in rows if not r.is_header and "Average Assets" in r.label)
        assert avg.unit == "USD"
        assert "($000)" not in avg.label
        assert avg.model_dump()["03/31/2026"] == 4759098000000

    def test_uncoded_row_has_no_unit_or_values(self, monkeypatch):
        """A schema item with no bound code renders as a label-only row."""
        rows = self._result(monkeypatch).result
        row = next(r for r in rows if r.label.endswith("Operating Income"))
        assert row.is_header is False
        assert row.unit is None
        dumped = row.model_dump()
        value_cols = [
            col
            for col in dumped
            if col not in ("label", "is_header", "narrative", "unit")
        ]
        assert value_cols and all(dumped[col] is None for col in value_cols)

    def test_metric_carries_guide_narrative(self, monkeypatch):
        """A metric row carries its guide definition as the narrative."""
        rows = self._result(monkeypatch).result
        ratio = next(r for r in rows if r.label.endswith("(Tax Equivalent)"))
        assert ratio.narrative == "NII on a TE basis divided by average assets."

    def test_metric_without_definition_has_no_narrative(self, monkeypatch):
        """A metric with no published definition carries a null narrative."""
        rows = self._result(monkeypatch).result
        avg = next(r for r in rows if not r.is_header and "Average Assets" in r.label)
        assert avg.narrative is None

    def test_empty_value_columns_excluded(self, monkeypatch):
        """A dollar-only section drops peer/percentile columns entirely."""
        rows = self._result(monkeypatch, {"section": "Assets"}).result
        loans = next(r for r in rows if r.label.endswith("Total Assets"))
        dumped = loans.model_dump()
        assert dumped["03/31/2026"] == 4900475000000
        assert not any("BHC" in key or "Peer" in key or "Pct" in key for key in dumped)

    def test_section_selects_by_title_case_insensitively(self, monkeypatch):
        """A section given by title selects only that section."""
        labels = {
            r.label for r in self._result(monkeypatch, {"section": "assets"}).result
        }
        assert "Assets" in labels
        assert "Summary Ratios" not in labels

    def test_all_sections_when_selected(self, monkeypatch):
        """The 'All Sections' choice renders every section's header."""
        rows = self._result(monkeypatch, {"section": "All Sections"}).result
        headers = {r.label for r in rows if r.is_header}
        assert {"Summary Ratios", "Assets"} <= headers

    def test_all_sections_when_section_blank(self, monkeypatch):
        """A blank section also renders every section."""
        rows = self._result(monkeypatch, {"section": ""}).result
        headers = {r.label for r in rows if r.is_header}
        assert {"Summary Ratios", "Assets"} <= headers

    def test_unknown_section_raises(self, monkeypatch):
        """A section matching no title raises ``OpenBBError``."""
        with pytest.raises(OpenBBError):
            self._result(monkeypatch, {"section": "Nonexistent"})

    def test_falls_back_to_query_rssd_and_missing_date(self, monkeypatch):
        """Absent identity and dates, the query RSSD stands in and the date drops."""
        _patch(monkeypatch, {"identity": {}, "periods": {}, "values": _DATA["values"]})
        query = FederalReserveBhcprFetcher.transform_query(
            {"rssd_id": "1039502", "period": "20260331"}
        )
        data = FederalReserveBhcprFetcher.extract_data(query, None)
        result = FederalReserveBhcprFetcher.transform_data(query, data)
        assert result.metadata["rssd_id"] == "1039502"
        assert "reporting_date" not in result.metadata
        assert "name" not in result.metadata


class TestData:
    """Tests for the output data model."""

    def test_accepts_dynamic_value_columns(self):
        """Dynamic period/sub-column fields validate as extra fields."""
        row = FederalReserveBhcprData.model_validate(
            {"label": "x", "is_header": False, "03/31/2026 BHC": 2.15}
        )
        assert row.model_dump()["03/31/2026 BHC"] == 2.15


class TestRealFixtureIntegration:
    """End-to-end tests over a committed real BHCPR CSV and the live schema asset."""

    def _fixture_bytes(self):
        """Return the committed real JPMorgan BHCPR CSV bytes."""
        return _FIXTURE.read_bytes()

    def _patch_fetch(self, monkeypatch):
        """Serve the real CSV through the download layer; resolve identity as-is."""
        from openbb_federal_reserve.utils.bhcpr_csv import parse_bhcpr_csv

        monkeypatch.setattr(
            "openbb_federal_reserve.utils.ffiec.resolve_bhcpr_holder",
            lambda rssd: rssd,
        )
        monkeypatch.setattr(
            "openbb_federal_reserve.utils.ffiec.fetch_institution_financial_reports",
            lambda rssd: {"BHCPR": {"periods": [{"year": 2026, "quarter": 1}]}},
        )
        monkeypatch.setattr(
            "openbb_federal_reserve.utils.ffiec.fetch_bhcpr",
            lambda rssd_id, date: parse_bhcpr_csv(self._fixture_bytes()),
        )

    def test_fetch_bhcpr_parses_downloaded_csv(self, monkeypatch):
        """``fetch_bhcpr`` downloads the CSV and parses it into coded values."""
        from openbb_federal_reserve.utils.ffiec import fetch_bhcpr

        monkeypatch.setattr(
            "openbb_federal_reserve.utils.ffiec._fetch_bytes",
            lambda path, referer=None: self._fixture_bytes(),
        )
        data = fetch_bhcpr("1039502", "20260331")
        assert data["identity"]["rssd_id"] == "1039502"
        assert data["periods"][""] == "20260331"
        assert data["values"]["BHCK2170"][""] == 4900475000

    def test_summary_ratios_render_from_real_csv(self, monkeypatch):
        """The live schema renders real Summary Ratios values, typed and scaled."""
        self._patch_fetch(monkeypatch)
        query = FederalReserveBhcprFetcher.transform_query({"rssd_id": "1039502"})
        data = FederalReserveBhcprFetcher.extract_data(query, None)
        result = FederalReserveBhcprFetcher.transform_data(query, data)
        assert result.metadata["rssd_id"] == "1039502"
        assert result.metadata["name"] == "JPMORGAN CHASE & CO."
        assert result.metadata["reporting_date"] == "2026-03-31"
        rows = result.result

        def _find(label, unit):
            """Return the first row matching a cleaned label and value type."""
            return next(
                r
                for r in rows
                if r.label.lstrip(">").strip() == label and r.unit == unit
            )

        assert rows[0].label == "Summary Ratios"
        assert rows[0].is_header is True
        assert (
            _find("Average Assets", "USD").model_dump()["03/31/2026"] == 4759098000000
        )
        assert _find("Net Income", "USD").model_dump()["03/31/2026"] == 16494000000
        assert (
            _find("Number of BHCs in Peer Group", "number").model_dump()["03/31/2026"]
            == 130
        )

    def test_dollar_section_renders_full_dollars(self, monkeypatch):
        """A dollar section renders thousands scaled to full dollars from real data."""
        self._patch_fetch(monkeypatch)
        query = FederalReserveBhcprFetcher.transform_query(
            {"rssd_id": "1039502", "section": "Assets"}
        )
        data = FederalReserveBhcprFetcher.extract_data(query, None)
        rows = FederalReserveBhcprFetcher.transform_data(query, data).result
        loans = next(
            r for r in rows if r.label.lstrip(">").strip() == "Real Estate Loans"
        )
        assert loans.unit == "USD"
        assert loans.model_dump()["03/31/2026"] == 504352000000

    def test_all_sections_render_every_section(self, monkeypatch):
        """'All Sections' renders every schema section over the real payload."""
        from openbb_federal_reserve.utils.bhcpr_schema import section_titles

        self._patch_fetch(monkeypatch)
        query = FederalReserveBhcprFetcher.transform_query(
            {"rssd_id": "1039502", "section": "All Sections"}
        )
        data = FederalReserveBhcprFetcher.extract_data(query, None)
        rows = FederalReserveBhcprFetcher.transform_data(query, data).result
        headers = {r.label for r in rows if r.is_header}
        assert set(section_titles()) <= headers
