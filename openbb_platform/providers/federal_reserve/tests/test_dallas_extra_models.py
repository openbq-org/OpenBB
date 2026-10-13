"""Tests for the additional Dallas Fed regional dataset models."""

import io
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_federal_reserve.models.regional.dallas_agsurvey import (
    FederalReserveDallasAgSurveyData,
    FederalReserveDallasAgSurveyFetcher,
)
from openbb_federal_reserve.models.regional.dallas_breakeven import (
    FederalReserveDallasBreakevenData,
    FederalReserveDallasBreakevenFetcher,
)
from openbb_federal_reserve.models.regional.dallas_dgei import (
    FederalReserveDallasDgeiData,
    FederalReserveDallasDgeiFetcher,
)
from openbb_federal_reserve.models.regional.dallas_gigafactory import (
    FederalReserveDallasGigafactoryData,
    FederalReserveDallasGigafactoryFetcher,
)
from openbb_federal_reserve.models.regional.dallas_govdebt import (
    FederalReserveDallasGovernmentDebtData,
    FederalReserveDallasGovernmentDebtFetcher,
)
from openbb_federal_reserve.models.regional.dallas_igrea import (
    FederalReserveDallasIgreaData,
    FederalReserveDallasIgreaFetcher,
)
from openbb_federal_reserve.models.regional.dallas_lithium import (
    FederalReserveDallasLithiumData,
    FederalReserveDallasLithiumFetcher,
)


def _save(sheets: dict[str, list[list]]) -> bytes:
    """Build an xlsx workbook from a mapping of sheet name to rows."""
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        sheet = workbook.create_sheet(title=title)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _response(content: bytes) -> MagicMock:
    """Build a make_request response with the given binary body."""
    response = MagicMock()
    response.content = content
    response.raise_for_status = MagicMock()
    return response


def _patch(monkeypatch, content: bytes) -> None:
    """Point make_request at fixture workbook bytes."""
    monkeypatch.setattr(
        "openbb_core.provider.utils.helpers.make_request",
        lambda *a, **k: _response(content),
    )


class TestIgrea:
    """Tests for the IGREA fetcher."""

    def test_parses_and_filters(self, monkeypatch):
        """The single-series sheet parses and filters by date."""
        _patch(
            monkeypatch,
            _save(
                {
                    "IGREA": [
                        ["Date", None],
                        [datetime(2026, 4, 1), -5.1],
                        [datetime(2026, 5, 1), -4.2],
                    ]
                }
            ),
        )
        query = FederalReserveDallasIgreaFetcher.transform_query(
            {"start_date": "2026-05-01"}
        )
        rows = FederalReserveDallasIgreaFetcher.extract_data(query, None)
        result = FederalReserveDallasIgreaFetcher.transform_data(query, rows)
        assert all(isinstance(r, FederalReserveDallasIgreaData) for r in result)
        assert [(r.date, r.value) for r in result] == [(date(2026, 5, 1), -4.2)]

    def test_reads_the_renamed_sheet(self, monkeypatch):
        """The Dallas Fed renamed the sheet to ``Kilian Index``."""
        _patch(
            monkeypatch,
            _save({"Kilian Index": [["Date", None], [datetime(2026, 4, 1), -5.1]]}),
        )
        query = FederalReserveDallasIgreaFetcher.transform_query({})
        rows = FederalReserveDallasIgreaFetcher.extract_data(query, None)
        result = FederalReserveDallasIgreaFetcher.transform_data(query, rows)
        assert [(r.date, r.value) for r in result] == [(date(2026, 4, 1), -5.1)]

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        _patch(monkeypatch, b"")
        query = FederalReserveDallasIgreaFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveDallasIgreaFetcher.extract_data(query, None)

    def test_end_date_filter(self, monkeypatch):
        """The ``end_date`` filter drops later observations."""
        _patch(
            monkeypatch,
            _save(
                {
                    "IGREA": [
                        ["Date", None],
                        [datetime(2026, 4, 1), -5.1],
                        [datetime(2026, 5, 1), -4.2],
                    ]
                }
            ),
        )
        query = FederalReserveDallasIgreaFetcher.transform_query(
            {"end_date": "2026-04-30"}
        )
        rows = FederalReserveDallasIgreaFetcher.extract_data(query, None)
        result = FederalReserveDallasIgreaFetcher.transform_data(query, rows)
        assert [(r.date, r.value) for r in result] == [(date(2026, 4, 1), -5.1)]


class TestGovernmentDebt:
    """Tests for the Government Debt fetcher."""

    def test_two_level_header_melts(self, monkeypatch):
        """The par/market two-level header joins onto the debt measures."""
        _patch(
            monkeypatch,
            _save(
                {
                    "data": [
                        ["Par and Market Value", None, None],
                        [None, "Par value", "Market value"],
                        [None, "Gross federal debt", "Gross federal debt"],
                        [datetime(2026, 1, 1), 36000.0, 38000.0],
                    ]
                }
            ),
        )
        query = FederalReserveDallasGovernmentDebtFetcher.transform_query({})
        rows = FederalReserveDallasGovernmentDebtFetcher.extract_data(query, None)
        result = FederalReserveDallasGovernmentDebtFetcher.transform_data(query, rows)
        assert all(
            isinstance(r, FederalReserveDallasGovernmentDebtData) for r in result
        )
        assert len(result) == 1
        by_series = result[0].model_dump()
        assert by_series["Par value - Gross federal debt"] == 36000.0
        assert by_series["Market value - Gross federal debt"] == 38000.0

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        _patch(monkeypatch, b"")
        query = FederalReserveDallasGovernmentDebtFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveDallasGovernmentDebtFetcher.extract_data(query, None)


class TestAgSurvey:
    """Tests for the Agricultural Survey fetcher."""

    def test_quarter_dates_and_missing(self, monkeypatch):
        """Quarter labels decode and ``n.a.`` maps to a missing value."""
        _patch(
            monkeypatch,
            _save(
                {
                    "indexes": [
                        ["Anticipated Conditions"],
                        [None, "Credit"],
                        ["Date", "Index1", "Standards"],
                        ["2026: Q1", 16.2, "n.a."],
                    ]
                }
            ),
        )
        query = FederalReserveDallasAgSurveyFetcher.transform_query({"table": "credit"})
        rows = FederalReserveDallasAgSurveyFetcher.extract_data(query, None)
        result = FederalReserveDallasAgSurveyFetcher.transform_data(query, rows)
        assert all(isinstance(r, FederalReserveDallasAgSurveyData) for r in result)
        assert all(r.date == date(2026, 3, 31) for r in result)
        assert len(result) == 1
        by_series = result[0].model_dump()
        assert by_series["Credit - Index1"] == 16.2
        assert by_series["Credit - Standards"] is None

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        _patch(monkeypatch, b"")
        query = FederalReserveDallasAgSurveyFetcher.transform_query({"table": "credit"})
        with pytest.raises(EmptyDataError):
            FederalReserveDallasAgSurveyFetcher.extract_data(query, None)


class TestBreakeven:
    """Tests for the Oil Break-Even Prices fetcher."""

    def test_play_by_quarter_melts(self, monkeypatch):
        """The play-by-quarter table melts to long records, dropping ``-`` cells."""
        _patch(
            monkeypatch,
            _save(
                {
                    "New Wells": [
                        ["Special Question"],
                        ["Last Update"],
                        ["Average Responses"],
                        ["Play", "2025:Q1", "2026:Q1"],
                        ["Permian Basin", "-", 62.0],
                        ["Eagle Ford", 55.0, 60.0],
                    ]
                }
            ),
        )
        query = FederalReserveDallasBreakevenFetcher.transform_query(
            {"well_type": "new"}
        )
        rows = FederalReserveDallasBreakevenFetcher.extract_data(query, None)
        result = FederalReserveDallasBreakevenFetcher.transform_data(query, rows)
        assert all(isinstance(r, FederalReserveDallasBreakevenData) for r in result)
        assert all(r.value is not None for r in result)
        by_key = {(r.date, r.play): r.value for r in result}
        assert (date(2025, 3, 31), "Permian Basin") not in by_key
        assert by_key[(date(2026, 3, 31), "Permian Basin")] == 62.0
        assert by_key[(date(2025, 3, 31), "Eagle Ford")] == 55.0

    def test_all_dashes_raises_empty(self, monkeypatch):
        """A table whose every value cell is ``-`` raises ``EmptyDataError``."""
        _patch(
            monkeypatch,
            _save(
                {
                    "New Wells": [
                        ["Play", "2025:Q1", "2026:Q1"],
                        ["Permian Basin", "-", "-"],
                        ["Eagle Ford", "-", "-"],
                    ]
                }
            ),
        )
        query = FederalReserveDallasBreakevenFetcher.transform_query(
            {"well_type": "new"}
        )
        rows = FederalReserveDallasBreakevenFetcher.extract_data(query, None)
        with pytest.raises(EmptyDataError):
            FederalReserveDallasBreakevenFetcher.transform_data(query, rows)

    def test_date_window_drops_out_of_range_quarters(self, monkeypatch):
        """The ``start_date``/``end_date`` window drops earlier and later quarters."""
        _patch(
            monkeypatch,
            _save(
                {
                    "New Wells": [
                        ["Play", "2024:Q1", "2025:Q1", "2026:Q1"],
                        ["Permian Basin", 50.0, 55.0, 62.0],
                    ]
                }
            ),
        )
        query = FederalReserveDallasBreakevenFetcher.transform_query(
            {"well_type": "new", "start_date": "2025-01-01", "end_date": "2025-12-31"}
        )
        rows = FederalReserveDallasBreakevenFetcher.extract_data(query, None)
        result = FederalReserveDallasBreakevenFetcher.transform_data(query, rows)
        assert [(r.date, r.value) for r in result] == [(date(2025, 3, 31), 55.0)]

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        _patch(monkeypatch, b"")
        query = FederalReserveDallasBreakevenFetcher.transform_query(
            {"well_type": "new"}
        )
        with pytest.raises(EmptyDataError):
            FederalReserveDallasBreakevenFetcher.extract_data(query, None)


class TestDgei:
    """Tests for the Global Economic Indicators fetcher."""

    def test_side_by_side_blocks(self, monkeypatch):
        """The two measure blocks melt with the measure joined onto each aggregate."""
        _patch(
            monkeypatch,
            _save(
                {
                    "World Trade Weights": [
                        ["Database of Global Economic Indicators"],
                        ["Real GDP"],
                        ["Quarterly"],
                        ["Last Updated"],
                        ["Downloaded"],
                        [None],
                        ["Percent Change", None, None, "Index", None],
                        ["Date", "World", "US", "Date", "World"],
                        [datetime(2026, 1, 1), 2.5, 3.0, datetime(2026, 1, 1), 105.0],
                    ]
                }
            ),
        )
        query = FederalReserveDallasDgeiFetcher.transform_query(
            {"indicator": "gdp", "weighting": "world_trade"}
        )
        rows = FederalReserveDallasDgeiFetcher.extract_data(query, None)
        result = FederalReserveDallasDgeiFetcher.transform_data(query, rows)
        assert all(isinstance(r, FederalReserveDallasDgeiData) for r in result)
        assert len(result) == 1
        by_series = result[0].model_dump()
        assert by_series["World - Percent Change"] == 2.5
        assert by_series["US - Percent Change"] == 3.0
        assert by_series["World - Index"] == 105.0

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        _patch(monkeypatch, b"")
        query = FederalReserveDallasDgeiFetcher.transform_query(
            {"indicator": "gdp", "weighting": "world_trade"}
        )
        with pytest.raises(EmptyDataError):
            FederalReserveDallasDgeiFetcher.extract_data(query, None)


class TestGigafactoryAndLithium:
    """Tests for the gigafactory and lithium map fetchers."""

    def test_gigafactory_records(self, monkeypatch):
        """Facility rows read into snake_cased records with raw coordinates."""
        _patch(
            monkeypatch,
            _save(
                {
                    "Data 1": [
                        ["Latitude", "Longitude", "Operator", "Facility name (x)"],
                        [39.6598992048024, -119.896477716134, "AESC", "Bowling Green"],
                    ]
                }
            ),
        )
        query = FederalReserveDallasGigafactoryFetcher.transform_query(
            {"table": "battery_cells"}
        )
        rows = FederalReserveDallasGigafactoryFetcher.extract_data(query, None)
        result = FederalReserveDallasGigafactoryFetcher.transform_data(query, rows)
        assert all(isinstance(r, FederalReserveDallasGigafactoryData) for r in result)
        assert result[0].operator == "AESC"
        assert result[0].facility_name == "Bowling Green"
        assert result[0].latitude == 39.6598992048024
        assert result[0].longitude == -119.896477716134

    def test_lithium_records(self, monkeypatch):
        """Project rows read into snake_cased records."""
        _patch(
            monkeypatch,
            _save(
                {
                    "Data": [
                        ["Project Name", "Company", "Stage", "Latitude"],
                        ["Thacker Pass", "Lithium Americas", "Construction", 41.7],
                    ]
                }
            ),
        )
        query = FederalReserveDallasLithiumFetcher.transform_query({})
        rows = FederalReserveDallasLithiumFetcher.extract_data(query, None)
        result = FederalReserveDallasLithiumFetcher.transform_data(query, rows)
        assert all(isinstance(r, FederalReserveDallasLithiumData) for r in result)
        assert result[0].project_name == "Thacker Pass"
        assert result[0].stage == "Construction"

    def test_gigafactory_empty_raises(self, monkeypatch):
        """An empty gigafactory response raises ``EmptyDataError``."""
        _patch(monkeypatch, b"")
        query = FederalReserveDallasGigafactoryFetcher.transform_query(
            {"table": "battery_cells"}
        )
        with pytest.raises(EmptyDataError):
            FederalReserveDallasGigafactoryFetcher.extract_data(query, None)

    def test_lithium_empty_raises(self, monkeypatch):
        """An empty lithium response raises ``EmptyDataError``."""
        _patch(monkeypatch, b"")
        query = FederalReserveDallasLithiumFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveDallasLithiumFetcher.extract_data(query, None)
