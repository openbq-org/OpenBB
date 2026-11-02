"""Tests for the Weekly Petroleum Status Report and Short Term Energy Outlook models."""

from datetime import date, datetime
from io import BytesIO

import pytest
from openbb_core.app.model.abstract.error import OpenBBError
from pandas import DataFrame, ExcelFile, ExcelWriter

from openbb_us_eia.models.petroleum_status_report import (
    EiaPetroleumStatusReportFetcher,
)
from openbb_us_eia.models.short_term_energy_outlook import (
    EiaShortTermEnergyOutlookFetcher,
)


def _wpsr_sheet(dates):
    """Build one WPSR-style sheet: banner row, symbol/title headers, data rows."""
    rows = [
        ["Back to Contents", "Data 1: Test Table"],
        ["Sourcekey", "WTOTUSA"],
        ["Date", "U.S. Ending Stocks of Crude Oil (Thousand Barrels)"],
    ]
    rows += [[datetime(d.year, d.month, d.day), 100.0 + i] for i, d in enumerate(dates)]
    return DataFrame(rows)


def _wpsr_file(sheets):
    """Write sheets into an in-memory workbook and open it as an ExcelFile."""
    buffer = BytesIO()
    with ExcelWriter(buffer) as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, header=False, index=False)
    return ExcelFile(BytesIO(buffer.getvalue()), engine="calamine")


class TestPetroleumStatusReportQuery:
    """Category and table validation."""

    def test_all_invalid_for_weekly_estimates(self):
        with pytest.raises(OpenBBError, match="not a supported choice"):
            EiaPetroleumStatusReportFetcher.transform_query(
                {"category": "weekly_estimates", "table": "all"}
            )

    def test_all_with_other_tables_warns_and_drops_all(self):
        with pytest.warns(UserWarning, match="Ignoring 'all'"):
            query = EiaPetroleumStatusReportFetcher.transform_query(
                {"category": "balance_sheet", "table": "all,stocks"}
            )
        assert query.table == "stocks"

    def test_invalid_table_raises(self):
        with pytest.raises(OpenBBError, match="Invalid table choice"):
            EiaPetroleumStatusReportFetcher.transform_query(
                {"category": "balance_sheet", "table": "imports"}
            )

    def test_weekly_estimates_defaults_to_stocks(self):
        query = EiaPetroleumStatusReportFetcher.transform_query(
            {"category": "weekly_estimates"}
        )
        assert query.table == "stocks"


class TestPetroleumStatusReportPipeline:
    """Extraction error wrapping and workbook transformation."""

    @pytest.mark.asyncio
    async def test_extract_wraps_download_errors(self, monkeypatch):
        from openbb_us_eia.utils import helpers

        async def failing_download(url, use_cache=True):
            raise OpenBBError("download failed")

        monkeypatch.setattr(helpers, "download_excel_file", failing_download)
        query = EiaPetroleumStatusReportFetcher.transform_query({})
        with pytest.raises(OpenBBError, match="Error extracting data"):
            await EiaPetroleumStatusReportFetcher.aextract_data(query, None)

    def test_transform_requires_excel_file(self):
        query = EiaPetroleumStatusReportFetcher.transform_query({})
        with pytest.raises(OpenBBError, match="Expected an ExcelFile"):
            EiaPetroleumStatusReportFetcher.transform_data(query, {"file": None})

    def test_transform_flattens_and_filters_dates(self):
        file = _wpsr_file(
            {
                "Data 1": _wpsr_sheet([date(2024, 1, 5), date(2024, 1, 12)]),
                "Data 2": _wpsr_sheet([date(2020, 1, 3)]),
            }
        )
        query = EiaPetroleumStatusReportFetcher.transform_query(
            {
                "category": "retail_prices",
                "table": "weekly,monthly",
                "start_date": date(2024, 1, 1),
                "end_date": date(2024, 1, 31),
            }
        )
        with pytest.warns(UserWarning, match="No data for table: monthly"):
            rows = EiaPetroleumStatusReportFetcher.transform_data(query, {"file": file})
        assert [row.date for row in rows] == [date(2024, 1, 5), date(2024, 1, 12)]
        record = rows[0].model_dump()
        assert record["symbol"] == "WTOTUSA"
        assert record["title"] == "U.S. Ending Stocks of Crude Oil"
        assert record["unit"] == "Thousand Barrels"
        assert record["table"] == "Data 01: Test Table"

    def test_transform_all_tables_empty_raises(self):
        file = _wpsr_file(
            {
                "Data 1": _wpsr_sheet([date(2020, 1, 3)]),
                "Data 2": _wpsr_sheet([date(2020, 1, 3)]),
            }
        )
        query = EiaPetroleumStatusReportFetcher.transform_query(
            {"category": "retail_prices", "start_date": date(2024, 1, 1)}
        )
        with (
            pytest.warns(UserWarning, match="No data for table"),
            pytest.raises(OpenBBError, match="Error transforming the data"),
        ):
            EiaPetroleumStatusReportFetcher.transform_data(query, {"file": file})


def _steo_response(rows, total=None):
    return {
        "response": {
            "data": rows,
            "total": str(total if total is not None else len(rows)),
        }
    }


def _steo_rows(period, symbols):
    return [
        {
            "period": period,
            "seriesId": symbol,
            "seriesDescription": symbol,
            "value": "1",
        }
        for symbol in symbols
    ]


class TestShortTermEnergyOutlookExtract:
    """Date formatting, chunking, pagination, and message handling."""

    @pytest.mark.parametrize(
        ("frequency", "start", "end"),
        [
            ("month", "start=2024-01", "end=2024-04"),
            ("quarter", "start=2024-Q1", "end=2024-Q2"),
            ("annual", "start=2024", "end=2024"),
        ],
    )
    @pytest.mark.asyncio
    async def test_date_params_formatted_per_frequency(
        self, monkeypatch, frequency, start, end
    ):
        from openbb_core.provider.utils import helpers as core_helpers

        urls: list[str] = []

        async def fake_amake_request(url, response_callback=None, **kwargs):
            urls.append(url)
            return _steo_response(_steo_rows("2024-01", ["WTIPUUS"]))

        monkeypatch.setattr(core_helpers, "amake_request", fake_amake_request)
        query = EiaShortTermEnergyOutlookFetcher.transform_query(
            {
                "symbol": "WTIPUUS",
                "frequency": frequency,
                "start_date": date(2024, 1, 1),
                "end_date": date(2024, 4, 1),
            }
        )
        await EiaShortTermEnergyOutlookFetcher.aextract_data(
            query, {"eia_api_key": "MOCK_KEY"}
        )
        assert start in urls[0]
        assert end in urls[0]

    @pytest.mark.asyncio
    async def test_paginates_when_total_exceeds_page(self, monkeypatch):
        from openbb_core.provider.utils import helpers as core_helpers

        first_page = _steo_rows("2024-01", [f"S{i}" for i in range(5000)])
        second_page = _steo_rows("2024-02", ["S0"])
        calls = {"n": 0}

        async def fake_amake_request(url, response_callback=None, **kwargs):
            calls["n"] += 1
            if "offset=0" in url:
                return _steo_response(first_page, total=5001)
            return _steo_response(second_page, total=5001)

        monkeypatch.setattr(core_helpers, "amake_request", fake_amake_request)
        query = EiaShortTermEnergyOutlookFetcher.transform_query({"symbol": "WTIPUUS"})
        rows = await EiaShortTermEnergyOutlookFetcher.aextract_data(
            query, {"eia_api_key": "MOCK_KEY"}
        )
        assert len(rows) == 5001
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_pagination_stops_on_empty_page_with_warning(self, monkeypatch):
        from openbb_core.provider.utils import helpers as core_helpers

        first_page = _steo_rows("2024-01", [f"S{i}" for i in range(5000)])

        async def fake_amake_request(url, response_callback=None, **kwargs):
            if "offset=0" in url:
                return _steo_response(first_page, total=5001)
            return _steo_response([], total=5001)

        monkeypatch.setattr(core_helpers, "amake_request", fake_amake_request)
        query = EiaShortTermEnergyOutlookFetcher.transform_query({"symbol": "WTIPUUS"})
        with pytest.warns(UserWarning, match="No additional data returned"):
            rows = await EiaShortTermEnergyOutlookFetcher.aextract_data(
                query, {"eia_api_key": "MOCK_KEY"}
            )
        assert len(rows) == 5000

    @pytest.mark.asyncio
    async def test_all_empty_raises_messages(self, monkeypatch):
        from openbb_core.provider.utils import helpers as core_helpers

        async def fake_amake_request(url, response_callback=None, **kwargs):
            return _steo_response([])

        monkeypatch.setattr(core_helpers, "amake_request", fake_amake_request)
        query = EiaShortTermEnergyOutlookFetcher.transform_query({"symbol": "WTIPUUS"})
        with pytest.raises(OpenBBError, match="No data returned"):
            await EiaShortTermEnergyOutlookFetcher.aextract_data(
                query, {"eia_api_key": "MOCK_KEY"}
            )

    @pytest.mark.asyncio
    async def test_request_error_wrapped(self, monkeypatch):
        from openbb_core.provider.utils import helpers as core_helpers

        async def fake_amake_request(url, response_callback=None, **kwargs):
            raise ValueError("socket closed")

        monkeypatch.setattr(core_helpers, "amake_request", fake_amake_request)
        query = EiaShortTermEnergyOutlookFetcher.transform_query({"symbol": "WTIPUUS"})
        with pytest.raises(OpenBBError, match="Error fetching data"):
            await EiaShortTermEnergyOutlookFetcher.aextract_data(
                query, {"eia_api_key": "MOCK_KEY"}
            )

    @pytest.mark.asyncio
    async def test_partial_results_warn(self, monkeypatch):
        from openbb_core.provider.utils import helpers as core_helpers

        async def fake_amake_request(url, response_callback=None, **kwargs):
            if "WTIPUUS" in url:
                return _steo_response(_steo_rows("2024-01", ["WTIPUUS"]))
            return _steo_response([])

        monkeypatch.setattr(core_helpers, "amake_request", fake_amake_request)
        symbols = ",".join(["WTIPUUS"] + [f"S{i}" for i in range(10)])
        query = EiaShortTermEnergyOutlookFetcher.transform_query({"symbol": symbols})
        with pytest.warns(UserWarning, match="No data returned"):
            rows = await EiaShortTermEnergyOutlookFetcher.aextract_data(
                query, {"eia_api_key": "MOCK_KEY"}
            )
        assert len(rows) == 1


class TestShortTermEnergyOutlookTransform:
    """Period parsing and missing-symbol warnings."""

    def test_missing_symbols_warn(self):
        query = EiaShortTermEnergyOutlookFetcher.transform_query(
            {"symbol": "WTIPUUS,BREPUUS"}
        )
        rows = _steo_rows("2024-Q1", ["WTIPUUS"])
        for row in rows:
            row["value"] = 80.0
        query = query.model_copy(update={"frequency": "quarter"})
        with pytest.warns(UserWarning, match="No data was returned for: BREPUUS"):
            out = EiaShortTermEnergyOutlookFetcher.transform_data(query, rows)
        assert out[0].date == date(2024, 1, 1)

    def test_table_mode_orders_and_labels(self):
        query = EiaShortTermEnergyOutlookFetcher.transform_query({"table": "01"})
        rows = _steo_rows("2024-01", ["WTIPUUS", "COPRPUS"])
        for row in rows:
            row["value"] = 1.0
        out = EiaShortTermEnergyOutlookFetcher.transform_data(query, rows)
        record = out[0].model_dump()
        assert record["table"].startswith("STEO - 1:")
        assert record["order"] == 1
