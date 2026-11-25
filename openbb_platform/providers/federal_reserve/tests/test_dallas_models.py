"""Tests for the Dallas Fed regional models."""

import io
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_federal_reserve.models.regional.dallas_bcs import (
    FederalReserveDallasBankingData,
    FederalReserveDallasBankingFetcher,
)
from openbb_federal_reserve.models.regional.dallas_energy import (
    FederalReserveDallasEnergyData,
    FederalReserveDallasEnergyFetcher,
)
from openbb_federal_reserve.models.regional.dallas_pce import (
    FederalReserveDallasTrimmedMeanPCEData,
    FederalReserveDallasTrimmedMeanPCEFetcher,
)
from openbb_federal_reserve.models.regional.dallas_tli import (
    FederalReserveDallasLeadingIndexData,
    FederalReserveDallasLeadingIndexFetcher,
)
from openbb_federal_reserve.models.regional.dallas_tmos import (
    FederalReserveDallasManufacturingData,
    FederalReserveDallasManufacturingFetcher,
)
from openbb_federal_reserve.models.regional.dallas_tros import (
    FederalReserveDallasRetailData,
    FederalReserveDallasRetailFetcher,
)
from openbb_federal_reserve.models.regional.dallas_tssos import (
    FederalReserveDallasServiceSectorData,
    FederalReserveDallasServiceSectorFetcher,
)
from openbb_federal_reserve.models.regional.dallas_wei import (
    FederalReserveDallasWeeklyEconomicData,
    FederalReserveDallasWeeklyEconomicFetcher,
)


def _response(content: bytes) -> MagicMock:
    """Build a make_request response with the given binary body."""
    response = MagicMock()
    response.content = content
    response.raise_for_status = MagicMock()
    return response


def _workbook(sheet_name: str, rows: list[list], leading_blanks: int = 0) -> bytes:
    """Build a single-sheet workbook with an optional blank-row header offset."""
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    for _ in range(leading_blanks):
        sheet.append([None])
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _tmos_workbook() -> bytes:
    """Build a TMOS ``Index`` sheet with the survey diffusion columns."""
    header = [
        "Date",
        "Prod",
        "Fprod",
        "Capu",
        "Fcapu",
        "Vnwo",
        "Fvnwo",
        "Gro",
        "Fgro",
        "Ufil",
        "Fufil",
        "Vshp",
        "Fvshp",
        "Dtm",
        "Fdtm",
        "Fgi",
        "Ffgi",
        "Prm",
        "Fprm",
        "Pfg",
        "Fpfg",
        "Wgs",
        "Fwgs",
        "Nemp",
        "Fnemp",
        "Avgwk",
        "Favgwk",
        "Cexp",
        "Fcexp",
        "Colk",
        "Fcolk",
        "Bact",
        "Fbact",
        "Uncr",
    ]
    base = [0.0] * (len(header) - 1)

    def make(date_str: str, prod: float) -> list:
        row = [date_str, *base]
        row[1] = prod
        return row

    return _workbook("Index", [header, make("Apr-26", 26.9), make("May-26", 18.6)])


def _tssos_workbook() -> bytes:
    """Build a TSSOS ``Index`` sheet with the survey diffusion columns."""
    header = [
        "date",
        "rev",
        "frev",
        "emp",
        "femp",
        "pemp",
        "fpemp",
        "avgwk",
        "favgwk",
        "wgs",
        "fwgs",
        "inp",
        "finp",
        "sell",
        "fsell",
        "cexp",
        "fcexp",
        "colk",
        "fcolk",
        "bact",
        "fbact",
        "uncr",
    ]
    base = [0.0] * (len(header) - 1)

    def make(date_str: str, rev: float) -> list:
        row = [date_str, *base]
        row[1] = rev
        return row

    return _workbook("Index", [header, make("Apr-26", 8.7), make("May-26", 11.3)])


def _tros_workbook() -> bytes:
    """Build a TROS ``Alldata`` sheet with diffusion columns and trailing NaN."""
    header = [
        "Date",
        "revi",
        "revn",
        "revd",
        "rev",
        "empi",
        "empn",
        "empd",
        "emp",
        "pempi",
        "pempn",
        "pempd",
        "pemp",
        "avgwki",
        "avgwkn",
        "avgwkd",
        "avgwk",
        "wgsi",
        "wgsn",
        "wgsd",
        "wgs",
        "inpi",
        "inpn",
        "inpd",
        "inp",
        "selli",
        "selln",
        "selld",
        "sell",
        "invi",
        "invn",
        "invd",
        "inv",
        "cexpi",
        "cexpn",
        "cexpd",
        "cexp",
        "colki",
        "colkn",
        "colkd",
        "colk",
        "bacti",
        "bactn",
        "bactd",
        "bact",
    ]
    width = len(header) - 1
    base = [0.0] * width
    nov = [None] * width

    def make(date_str, rev) -> list:
        row = [date_str, *base]
        row[4] = rev
        return row

    return _workbook(
        "Alldata",
        [header, make("Nov-25", -10.0), make("Dec-25", -19.1), [None, *nov]],
    )


def _bcs_workbook(sheet_name: str = "CSV_BCS_Index_Results") -> bytes:
    """Build a BCS sheet with datetime dates and the diffusion columns."""
    header = [
        "date",
        "LVol",
        "LDem",
        "LNon",
        "LPrice",
        "LStds",
        "CIVol",
        "CINP",
        "CIStds",
        "CREVol",
        "CRENP",
        "CREStds",
        "RREVol",
        "RRENP",
        "RREStds",
        "CVol",
        "CNP",
        "CStds",
        "ColkDem",
        "ColkNP",
        "Bact",
        "Fbact",
        "OCorVol",
        "OCstFds",
        "ONintMar",
        "ONintInc",
    ]
    base = [0.0] * (len(header) - 1)

    def make(dt: datetime, lvol: float, bact: float) -> list:
        row = [dt, *base]
        row[1] = lvol
        row[20] = bact
        return row

    return _workbook(
        sheet_name,
        [
            header,
            make(datetime(2026, 3, 30), 15.3, 5.0),
            make(datetime(2026, 5, 18), 35.6, 10.2),
        ],
    )


def _energy_workbook() -> bytes:
    """Build a multi-sheet DES workbook with quarter-end dates."""
    from openpyxl import Workbook

    workbook = Workbook()
    sheets = {
        "All Firms": (
            [
                "date",
                "Qbac",
                "Qcexp",
                "Qsdtm",
                "Qemp",
                "Qemphr",
                "Qwgs",
                "Qolk",
                "Quncr",
            ],
            46.1,
        ),
        "E+P Firms": (
            [
                "date",
                "Qbac",
                "Qoprd",
                "Qgprd",
                "Qcexp",
                "Qfexp",
                "Qsdtm",
                "Qemp",
                "Qemphr",
                "Qwgs",
                "Qdvcst",
                "Qlsexp",
                "Qolk",
                "Quncr",
            ],
            48.2,
        ),
        "O+G Support Services Firms": (
            [
                "date",
                "Qbac",
                "Qeqput",
                "Qcexp",
                "Qsdtm",
                "Qlgtm",
                "Qemp",
                "Qemphr",
                "Qwgs",
                "Qinp",
                "Qsell",
                "Qopmgn",
                "Qolk",
                "Quncr",
            ],
            30.3,
        ),
    }
    for index, (title, (header, bac)) in enumerate(sheets.items()):
        sheet = workbook.active if index == 0 else workbook.create_sheet()
        sheet.title = title
        sheet.append(header)
        first = [datetime(2026, 3, 31), *[0.0] * (len(header) - 1)]
        last = [datetime(2026, 6, 30), *[0.0] * (len(header) - 1)]
        last[1] = bac
        sheet.append(first)
        sheet.append(last)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _pce_workbook() -> bytes:
    """Build a PCE ``Web - Historical`` sheet with a header offset and ``#NAN``."""
    return _workbook(
        "Web - Historical",
        [
            ["Unnamed: 0", "1-month", "6-month", "12-month", "Unnamed: 4"],
            [datetime(1977, 1, 1), "#NAN", "#NAN", "#NAN", None],
            [datetime(2026, 3, 1), 2.93, 2.17, 2.36, None],
            [datetime(2026, 4, 1), 2.55, 2.33, 2.35, None],
        ],
        leading_blanks=3,
    )


def _pce_partial_workbook() -> bytes:
    """Build a PCE sheet with an all-``#NAN`` row and a one-month-only row."""
    return _workbook(
        "Web - Historical",
        [
            ["Unnamed: 0", "1-month", "6-month", "12-month", "Unnamed: 4"],
            [datetime(1977, 1, 1), "#NAN", "#NAN", "#NAN", None],
            [datetime(2026, 4, 1), 2.55, "#NAN", "#NAN", None],
        ],
        leading_blanks=3,
    )


def _pce_all_none_workbook() -> bytes:
    """Build a PCE sheet whose only value row is entirely ``#NAN``."""
    return _workbook(
        "Web - Historical",
        [
            ["Unnamed: 0", "1-month", "6-month", "12-month", "Unnamed: 4"],
            [datetime(1977, 1, 1), "#NAN", "#NAN", "#NAN", None],
        ],
        leading_blanks=3,
    )


def _wei_workbook() -> bytes:
    """Build a WEI ``2008-current`` sheet with string dates and vintage columns."""
    return _workbook(
        "2008-current",
        [
            ["Date", "WEI", "WEI as of 9/25/2025"],
            ["06/06/2026", 2.90, 2.91],
            ["06/13/2026", 3.10, 3.11],
        ],
    )


def _tli_workbook() -> bytes:
    """Build a TLI ``LEADI`` sheet with a five-row header offset."""
    return _workbook(
        "LEADI",
        [
            [
                "Date",
                "Index",
                "Annual Average",
                "Year/Year Pct Change",
                "Dec/Dec Pct Change",
            ],
            [datetime(2026, 4, 1), 128.095183, None, None, None],
            [datetime(2026, 5, 1), 127.610494, None, None, None],
        ],
        leading_blanks=5,
    )


class TestManufacturing:
    """Tests for the TMOS fetcher."""

    def test_decodes_indicators_and_filters(self, monkeypatch):
        """Every indicator decodes to a labelled current/future long row."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(_tmos_workbook()),
        )
        query = FederalReserveDallasManufacturingFetcher.transform_query(
            {"start_date": "2026-05-01", "end_date": "2026-05-31"}
        )
        rows = FederalReserveDallasManufacturingFetcher.extract_data(query, None)
        result = FederalReserveDallasManufacturingFetcher.transform_data(query, rows)
        assert all(isinstance(r, FederalReserveDallasManufacturingData) for r in result)
        assert all(r.date == date(2026, 5, 1) for r in result)
        # One wide row per date carries the 17 indicators in current/future columns.
        assert len(result) == 1
        columns = result[0].model_dump()
        assert "Production (current)" in columns
        assert "Production (future)" in columns
        assert columns["Production (current)"] == 18.6

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(b""),
        )
        query = FederalReserveDallasManufacturingFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveDallasManufacturingFetcher.extract_data(query, None)


class TestServiceSector:
    """Tests for the TSSOS fetcher."""

    def test_decodes_indicators_and_filters(self, monkeypatch):
        """Every indicator decodes to a labelled current/future long row."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(_tssos_workbook()),
        )
        query = FederalReserveDallasServiceSectorFetcher.transform_query(
            {"start_date": "2026-05-01", "end_date": "2026-05-31"}
        )
        rows = FederalReserveDallasServiceSectorFetcher.extract_data(query, None)
        result = FederalReserveDallasServiceSectorFetcher.transform_data(query, rows)
        assert all(isinstance(r, FederalReserveDallasServiceSectorData) for r in result)
        assert all(r.date == date(2026, 5, 1) for r in result)
        assert len(result) == 1
        columns = result[0].model_dump()
        assert "Revenue (current)" in columns
        assert "Revenue (future)" in columns
        assert columns["Revenue (current)"] == 11.3

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(b""),
        )
        query = FederalReserveDallasServiceSectorFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveDallasServiceSectorFetcher.extract_data(query, None)


class TestRetail:
    """Tests for the TROS fetcher."""

    def test_decodes_responses_and_filters(self, monkeypatch):
        """The increase/no-change/decrease/net responses decode and dates filter."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(_tros_workbook()),
        )
        query = FederalReserveDallasRetailFetcher.transform_query(
            {"start_date": "2025-01-01", "end_date": "2025-12-31"}
        )
        rows = FederalReserveDallasRetailFetcher.extract_data(query, None)
        result = FederalReserveDallasRetailFetcher.transform_data(query, rows)
        assert all(isinstance(r, FederalReserveDallasRetailData) for r in result)
        columns = result[0].model_dump()
        assert "Retail Sales (current, net)" in columns
        assert "Retail Sales (current, increase)" in columns
        assert "Retail Sales (current, no change)" in columns
        assert "Retail Sales (current, decrease)" in columns
        december = next(r for r in result if r.date == date(2025, 12, 1))
        assert december.model_dump()["Retail Sales (current, net)"] == -19.1

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(b""),
        )
        query = FederalReserveDallasRetailFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveDallasRetailFetcher.extract_data(query, None)


class TestBanking:
    """Tests for the BCS fetcher."""

    def test_decodes_categories_and_filters(self, monkeypatch):
        """The loan/funding/outlook categories decode and the date filter narrows."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(_bcs_workbook()),
        )
        query = FederalReserveDallasBankingFetcher.transform_query(
            {"start_date": "2026-04-01", "end_date": "2026-05-31"}
        )
        rows = FederalReserveDallasBankingFetcher.extract_data(query, None)
        result = FederalReserveDallasBankingFetcher.transform_data(query, rows)
        assert all(isinstance(r, FederalReserveDallasBankingData) for r in result)
        assert all(r.date == date(2026, 5, 18) for r in result)
        assert len(result) == 1
        columns = result[0].model_dump()
        assert columns["Total Loan Volume (current)"] == 35.6
        assert columns["General Business Activity (current)"] == 10.2

    def test_reads_the_renamed_sheet(self, monkeypatch):
        """The Dallas Fed renamed the sheet to ``BCS_Index_Results``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(_bcs_workbook("BCS_Index_Results")),
        )
        query = FederalReserveDallasBankingFetcher.transform_query({})
        rows = FederalReserveDallasBankingFetcher.extract_data(query, None)
        result = FederalReserveDallasBankingFetcher.transform_data(query, rows)
        assert [r.date for r in result] == [date(2026, 3, 30), date(2026, 5, 18)]
        assert result[-1].model_dump()["Total Loan Volume (current)"] == 35.6

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(b""),
        )
        query = FederalReserveDallasBankingFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveDallasBankingFetcher.extract_data(query, None)


class TestEnergy:
    """Tests for the DES fetcher."""

    def test_default_firm_group_parses_and_filters(self, monkeypatch):
        """The default ``all`` sheet decodes to labelled long rows and filters."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(_energy_workbook()),
        )
        query = FederalReserveDallasEnergyFetcher.transform_query(
            {"start_date": "2026-04-01"}
        )
        rows = FederalReserveDallasEnergyFetcher.extract_data(query, None)
        result = FederalReserveDallasEnergyFetcher.transform_data(query, rows)
        assert all(isinstance(r, FederalReserveDallasEnergyData) for r in result)
        assert all(r.date == date(2026, 6, 30) for r in result)
        assert len(result) == 1
        assert result[0].model_dump()["Business Activity"] == 46.1

    def test_selected_firm_group_exposes_specific_indicators(self, monkeypatch):
        """The E+P sheet exposes its production-specific indicator columns."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(_energy_workbook()),
        )
        query = FederalReserveDallasEnergyFetcher.transform_query(
            {"firm_group": "exploration_production", "end_date": "2026-06-30"}
        )
        rows = FederalReserveDallasEnergyFetcher.extract_data(query, None)
        result = FederalReserveDallasEnergyFetcher.transform_data(query, rows)
        columns = result[0].model_dump()
        assert "Oil Production" in columns
        assert "Natural Gas Production" in columns

    def test_all_data_decodes_response_shares(self, monkeypatch):
        """The all_data table decodes the increase/no-change/decrease shares."""
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "All Firms"
        sheet.append(["date", "Qbac", "Qbacd", "Qbaci", "Qbacn"])
        sheet.append([datetime(2026, 6, 30), 46.1, 10.0, 56.1, 33.9])
        buffer = io.BytesIO()
        workbook.save(buffer)
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(buffer.getvalue()),
        )
        query = FederalReserveDallasEnergyFetcher.transform_query({"table": "all_data"})
        rows = FederalReserveDallasEnergyFetcher.extract_data(query, None)
        result = FederalReserveDallasEnergyFetcher.transform_data(query, rows)
        by_indicator = result[0].model_dump()
        assert by_indicator["Business Activity"] == 46.1
        assert by_indicator["Business Activity (% Reporting Decrease)"] == 10.0
        assert by_indicator["Business Activity (% Reporting Increase)"] == 56.1

    def test_price_forecasts_decode(self, monkeypatch):
        """The price forecasts table decodes the per-product statistics."""
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "All Firms"
        sheet.append(["date", "Refoprc", "Avgoprc", "Medngprc"])
        sheet.append([datetime(2026, 6, 30), 70.0, 72.5, 3.5])
        buffer = io.BytesIO()
        workbook.save(buffer)
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(buffer.getvalue()),
        )
        query = FederalReserveDallasEnergyFetcher.transform_query(
            {"table": "price_forecasts"}
        )
        rows = FederalReserveDallasEnergyFetcher.extract_data(query, None)
        result = FederalReserveDallasEnergyFetcher.transform_data(query, rows)
        by_indicator = result[0].model_dump()
        assert by_indicator["WTI Oil Price (Reference)"] == 70.0
        assert by_indicator["WTI Oil Price (Average)"] == 72.5
        assert by_indicator["Henry Hub Natural Gas Price (Median)"] == 3.5

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(b""),
        )
        query = FederalReserveDallasEnergyFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveDallasEnergyFetcher.extract_data(query, None)


class TestTrimmedMeanPCE:
    """Tests for the Trimmed Mean PCE fetcher."""

    def test_coerces_nan_strings_and_filters(self, monkeypatch):
        """The all-``#NAN`` leading row drops while later rows survive and filter."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(_pce_workbook()),
        )
        query = FederalReserveDallasTrimmedMeanPCEFetcher.transform_query(
            {"start_date": "1977-01-01", "end_date": "2026-04-30"}
        )
        rows = FederalReserveDallasTrimmedMeanPCEFetcher.extract_data(query, None)
        result = FederalReserveDallasTrimmedMeanPCEFetcher.transform_data(query, rows)
        assert all(
            isinstance(r, FederalReserveDallasTrimmedMeanPCEData) for r in result
        )
        assert all(r.date != date(1977, 1, 1) for r in result)
        assert result[0].date == date(2026, 3, 1)
        assert result[0].twelve_month == 2.36
        assert result[-1].date == date(2026, 4, 1)
        assert result[-1].twelve_month == 2.35

    def test_drops_all_none_rows_keeps_partial(self, monkeypatch):
        """An all-``#NAN`` row drops while a partially-populated row survives."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(_pce_partial_workbook()),
        )
        query = FederalReserveDallasTrimmedMeanPCEFetcher.transform_query({})
        rows = FederalReserveDallasTrimmedMeanPCEFetcher.extract_data(query, None)
        result = FederalReserveDallasTrimmedMeanPCEFetcher.transform_data(query, rows)
        assert len(result) == 1
        assert result[0].date == date(2026, 4, 1)
        assert result[0].one_month == 2.55
        assert result[0].six_month is None
        assert result[0].twelve_month is None

    def test_all_none_raises_empty(self, monkeypatch):
        """A frame with only all-``#NAN`` value rows raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(_pce_all_none_workbook()),
        )
        query = FederalReserveDallasTrimmedMeanPCEFetcher.transform_query({})
        rows = FederalReserveDallasTrimmedMeanPCEFetcher.extract_data(query, None)
        with pytest.raises(EmptyDataError):
            FederalReserveDallasTrimmedMeanPCEFetcher.transform_data(query, rows)

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(b""),
        )
        query = FederalReserveDallasTrimmedMeanPCEFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveDallasTrimmedMeanPCEFetcher.extract_data(query, None)


class TestWeeklyEconomic:
    """Tests for the WEI fetcher."""

    def test_parses_string_dates_and_filters(self, monkeypatch):
        """Only Date and WEI are kept, string dates parse, and dates filter."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(_wei_workbook()),
        )
        query = FederalReserveDallasWeeklyEconomicFetcher.transform_query(
            {"start_date": "2026-06-10", "end_date": "2026-06-20"}
        )
        rows = FederalReserveDallasWeeklyEconomicFetcher.extract_data(query, None)
        result = FederalReserveDallasWeeklyEconomicFetcher.transform_data(query, rows)
        assert all(
            isinstance(r, FederalReserveDallasWeeklyEconomicData) for r in result
        )
        assert len(result) == 1
        assert result[0].date == date(2026, 6, 13)
        assert result[0].wei == 3.10

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(b""),
        )
        query = FederalReserveDallasWeeklyEconomicFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveDallasWeeklyEconomicFetcher.extract_data(query, None)


class TestLeadingIndex:
    """Tests for the TLI fetcher."""

    def test_parses_header_offset_and_filters(self, monkeypatch):
        """The five-row header offset parses and the end_date filter narrows it."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(_tli_workbook()),
        )
        query = FederalReserveDallasLeadingIndexFetcher.transform_query(
            {"start_date": "2026-01-01", "end_date": "2026-05-31"}
        )
        rows = FederalReserveDallasLeadingIndexFetcher.extract_data(query, None)
        result = FederalReserveDallasLeadingIndexFetcher.transform_data(query, rows)
        assert all(isinstance(r, FederalReserveDallasLeadingIndexData) for r in result)
        assert result[-1].date == date(2026, 5, 1)
        assert result[-1].index == 127.610494
        assert result[-1].annual_average is None

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _response(b""),
        )
        query = FederalReserveDallasLeadingIndexFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveDallasLeadingIndexFetcher.extract_data(query, None)
