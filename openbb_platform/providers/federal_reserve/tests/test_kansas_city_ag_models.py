"""Tests for the Kansas City Fed agricultural dataset models."""

import io
from datetime import date

import pytest
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_federal_reserve.models.regional.kansas_city_ag_credit_survey import (
    FederalReserveKansasCityAgCreditSurveyData,
    FederalReserveKansasCityAgCreditSurveyFetcher,
)
from openbb_federal_reserve.models.regional.kansas_city_ag_finance import (
    FederalReserveKansasCityAgFinanceData,
    FederalReserveKansasCityAgFinanceFetcher,
)
from openbb_federal_reserve.models.regional.kansas_city_ag_rates import (
    FederalReserveKansasCityAgRatesData,
    FederalReserveKansasCityAgRatesFetcher,
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


def _patch(monkeypatch, content: bytes) -> None:
    """Bypass URL resolution and point the fetch helper at fixture workbook bytes."""
    monkeypatch.setattr(
        "openbb_federal_reserve.utils.kansas_city_ag.resolve_kc_ag_url",
        lambda document_id: "https://example.test/file.xlsx",
    )
    monkeypatch.setattr(
        "openbb_federal_reserve.utils.kansas_city.fetch_kansas_city",
        lambda *a, **k: content,
    )


class TestAgCreditSurvey:
    """Tests for the Agricultural Credit Survey fetcher."""

    def test_land_values_ffills_year_and_melts(self, monkeypatch):
        """The year forward-fills and each land class melts to long rows."""
        _patch(
            monkeypatch,
            _save(
                {
                    "Sheet1": [
                        ["Farmland Values"],
                        [None],
                        [None, None, "Sample percent change"],
                        ["Year", "Qtr.", "NonIrrigated", "Irrigated", "Ranchland"],
                        [1980, 1, 12.49, 9.99, 12.76],
                        [None, 2, 6.79, 5.23, 6.45],
                    ]
                }
            ),
        )
        query = FederalReserveKansasCityAgCreditSurveyFetcher.transform_query(
            {"table": "land_values"}
        )
        rows = FederalReserveKansasCityAgCreditSurveyFetcher.extract_data(query, None)
        result = FederalReserveKansasCityAgCreditSurveyFetcher.transform_data(
            query, rows
        )
        assert all(
            isinstance(r, FederalReserveKansasCityAgCreditSurveyData) for r in result
        )
        by_date = {r.date: r.model_dump() for r in result}
        assert by_date[date(1980, 3, 31)]["NonIrrigated"] == 12.49
        assert by_date[date(1980, 6, 30)]["Ranchland"] == 6.45

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        _patch(monkeypatch, b"")
        query = FederalReserveKansasCityAgCreditSurveyFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveKansasCityAgCreditSurveyFetcher.extract_data(query, None)


class TestAgRates:
    """Tests for the Agricultural Interest Rates fetcher."""

    def test_states_melt_and_missing(self, monkeypatch):
        """State columns melt and an all-``.`` period is dropped as missing."""
        _patch(
            monkeypatch,
            _save(
                {
                    "Operating": [
                        ["Agricultural Variable Rates"],
                        [None],
                        [None],
                        [None],
                        ["Year", "Qtr.", "Kansas", "Missouri"],
                        [2002, 1, ".", "."],
                        [None, 2, 7.86, 7.24],
                    ]
                }
            ),
        )
        query = FederalReserveKansasCityAgRatesFetcher.transform_query(
            {"rate_type": "variable", "loan_type": "operating"}
        )
        rows = FederalReserveKansasCityAgRatesFetcher.extract_data(query, None)
        result = FederalReserveKansasCityAgRatesFetcher.transform_data(query, rows)
        assert all(isinstance(r, FederalReserveKansasCityAgRatesData) for r in result)
        by_date = {r.date: r.model_dump() for r in result}
        # Every state in 2002Q1 is the "." placeholder, leaving the row all-None,
        # so it is dropped rather than surfacing as a blank table row.
        assert date(2002, 3, 31) not in by_date
        assert by_date[date(2002, 6, 30)]["Kansas"] == 7.86

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        _patch(monkeypatch, b"")
        query = FederalReserveKansasCityAgRatesFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveKansasCityAgRatesFetcher.extract_data(query, None)


class TestAgFinance:
    """Tests for the Ag Finance Databook fetcher."""

    def test_codes_resolve_labels_and_missing(self, monkeypatch):
        """Codes resolve to descriptions; an all-``---`` period is dropped."""
        _patch(
            monkeypatch,
            _save(
                {
                    "Data": [
                        ["Date", "A001"],
                        ["2025Q1", 10.5],
                        ["2025Q2", "---"],
                    ],
                    "Descriptions": [
                        ["Statistic Identifier", "Statistic", "Description"],
                        ["A001", "Total Agricultural Loans", "Sum of farm loans"],
                    ],
                }
            ),
        )
        query = FederalReserveKansasCityAgFinanceFetcher.transform_query({})
        rows = FederalReserveKansasCityAgFinanceFetcher.extract_data(query, None)
        result = FederalReserveKansasCityAgFinanceFetcher.transform_data(query, rows)
        assert all(isinstance(r, FederalReserveKansasCityAgFinanceData) for r in result)
        by_date = {r.date: r.model_dump() for r in result}
        assert by_date[date(2025, 3, 31)]["Total Agricultural Loans"] == 10.5
        # 2025Q2 carries only the "---" placeholder, leaving the row all-None, so
        # it is dropped rather than surfacing as a blank table row.
        assert date(2025, 6, 30) not in by_date

    def test_published_table_uses_quarterly_sheet(self, monkeypatch):
        """A non-historical table parses the named sheet via ``parse_kc_quarterly``."""
        _patch(
            monkeypatch,
            _save(
                {
                    "A": [
                        ["Farm Debt at All Banks"],
                        [None],
                        [None, None, "Billions of dollars"],
                        ["Year", "Qtr.", "Real Estate", "Non-Real Estate"],
                        [2024, 1, 100.0, 200.0],
                    ]
                }
            ),
        )
        query = FederalReserveKansasCityAgFinanceFetcher.transform_query(
            {"table": "farm_debt_all_banks"}
        )
        rows = FederalReserveKansasCityAgFinanceFetcher.extract_data(query, None)
        result = FederalReserveKansasCityAgFinanceFetcher.transform_data(query, rows)
        by_date = {r.date: r.model_dump() for r in result}
        assert by_date[date(2024, 3, 31)]["Real Estate"] == 100.0
        assert by_date[date(2024, 3, 31)]["Non-Real Estate"] == 200.0

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        _patch(monkeypatch, b"")
        query = FederalReserveKansasCityAgFinanceFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveKansasCityAgFinanceFetcher.extract_data(query, None)


@pytest.mark.parametrize(
    "fetcher, params, document_id",
    [
        (FederalReserveKansasCityAgCreditSurveyFetcher, {"table": "land_values"}, 7623),
        (
            FederalReserveKansasCityAgCreditSurveyFetcher,
            {"table": "credit_conditions"},
            7620,
        ),
        (FederalReserveKansasCityAgRatesFetcher, {"rate_type": "variable"}, 7622),
        (FederalReserveKansasCityAgRatesFetcher, {"rate_type": "fixed"}, 7621),
        (FederalReserveKansasCityAgFinanceFetcher, {"table": "historical"}, 7228),
        (
            FederalReserveKansasCityAgFinanceFetcher,
            {"table": "ag_bank_performance"},
            7889,
        ),
    ],
)
def test_workbook_url_is_resolved_from_the_index(
    monkeypatch, fetcher, params, document_id
):
    """The file names carry the quarter, so each table resolves its document id."""
    resolved = f"https://www.kansascityfed.org/documents/{document_id}/Q226-file.xlsx"
    fetched: list[str] = []
    monkeypatch.setattr(
        "openbb_federal_reserve.utils.kansas_city_ag.resolve_kc_ag_url",
        lambda doc: resolved if doc == document_id else "unexpected",
    )
    monkeypatch.setattr(
        "openbb_federal_reserve.utils.kansas_city.fetch_kansas_city",
        lambda url, *a, **k: fetched.append(url) or b"workbook",
    )
    query = fetcher.transform_query(params)
    assert fetcher.extract_data(query, None) == [{"_raw": b"workbook"}]
    assert fetched == [resolved]
