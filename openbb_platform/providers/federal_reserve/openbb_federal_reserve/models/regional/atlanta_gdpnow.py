"""Federal Reserve Bank of Atlanta GDPNow Model."""

from datetime import (
    date as dateType,
    datetime,
)
from typing import Any, Literal

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

URL = (
    "https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents"
    "/research-and-data/data/gdpnow/GDPTrackingModelDataAndForecasts.xlsx"
)


def _number(value: Any) -> float | None:
    """Coerce a cell to a float, returning None for blanks and markers."""
    from math import isnan

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return None if isnan(value) else float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _label(value: Any) -> str | None:
    """Return a trimmed string label, or None when blank or NaN."""
    from math import isnan

    if value is None or (isinstance(value, float) and isnan(value)):
        return None
    text = " ".join(str(value).split())
    return text or None


def _melt_table(
    grid: list[list[Any]], header_row: int, value_start: int, label_column: int | None
) -> list[dict[str, Any]]:
    """Melt a dated table to long rows, carrying an optional release label column."""
    header = grid[header_row]
    records: list[dict[str, Any]] = []
    for row in grid[header_row + 1 :]:
        if not row or not isinstance(row[0], (datetime, dateType)):
            continue
        observation = row[0].date() if isinstance(row[0], datetime) else row[0]
        release = _label(row[label_column]) if label_column is not None else None
        for column in range(value_start, len(header)):
            name = _label(header[column])
            value = _number(row[column]) if column < len(row) else None
            if name and value is not None and column != label_column:
                records.append(
                    {
                        "date": observation,
                        "series": name,
                        "value": value,
                        "major_release": release,
                    }
                )
    return records


def _flat_table(grid: list[list[Any]], header_row: int) -> list[dict[str, Any]]:
    """Build already-wide rows from a fixed-column sheet, preserving date cells."""
    header = grid[header_row]
    records: list[dict[str, Any]] = []
    for row in grid[header_row + 1 :]:
        if not row or not isinstance(row[0], (datetime, dateType)):
            continue
        record: dict[str, Any] = {
            "date": row[0].date() if isinstance(row[0], datetime) else row[0]
        }
        for column in range(1, len(header)):
            name = _label(header[column])
            if not name:
                continue
            cell = row[column] if column < len(row) else None
            if isinstance(cell, datetime):
                record[name] = cell.date()
            elif isinstance(cell, dateType):
                record[name] = cell
            else:
                record[name] = _number(cell)
        records.append(record)
    return records


def _melt_evolution(grid: list[list[Any]]) -> list[dict[str, Any]]:
    """Melt the three side-by-side quarter blocks of the evolution sheet."""
    width = max((len(row) for row in grid), default=0)
    records: list[dict[str, Any]] = []
    for block in range(0, width, 3):
        for row in grid[1:]:
            if len(row) <= block or not isinstance(row[block], (datetime, dateType)):
                continue
            observation = (
                row[block].date() if isinstance(row[block], datetime) else row[block]
            )
            value = _number(row[block + 2]) if block + 2 < len(row) else None
            if value is not None:
                records.append(
                    {
                        "date": observation,
                        "series": "GDP nowcast",
                        "value": value,
                        "major_release": _label(row[block + 1])
                        if block + 1 < len(row)
                        else None,
                    }
                )
    return records


class FederalReserveAtlantaGdpNowQueryParams(QueryParams):
    """Atlanta Fed GDPNow Query Parameters."""

    __json_schema_extra__ = {
        "table": {
            "x-widget_config": {
                "options": [
                    {"label": "Nowcast Evolution", "value": "evolution"},
                    {"label": "Component Contributions", "value": "contributions"},
                    {
                        "label": "Change in Contributions",
                        "value": "change_in_contributions",
                    },
                    {"label": "Component Growth-Rate Table", "value": "table"},
                    {
                        "label": "Component Contributions Table",
                        "value": "table_contributions",
                    },
                    {"label": "Track Record", "value": "track_record"},
                ]
            }
        },
    }

    table: Literal[
        "evolution",
        "contributions",
        "change_in_contributions",
        "table",
        "table_contributions",
        "track_record",
    ] = Field(
        default="evolution",
        description="The GDPNow table to return: the current-quarter nowcast"
        " evolution, the component contributions to the forecast, the change in"
        " contributions per release, the latest-release component growth-rate"
        " table, the latest-release component contributions table, or the model's"
        " historical track record.",
    )
    start_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("start_date", "")
    )
    end_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("end_date", "")
    )


class FederalReserveAtlantaGdpNowData(Data):
    """Atlanta Fed GDPNow Data."""

    date: dateType = Field(description="The observation date.")


class FederalReserveAtlantaGdpNowFetcher(
    Fetcher[
        FederalReserveAtlantaGdpNowQueryParams,
        list[FederalReserveAtlantaGdpNowData],
    ]
):
    """Atlanta Fed GDPNow Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FederalReserveAtlantaGdpNowQueryParams:
        """Transform the query params."""
        return FederalReserveAtlantaGdpNowQueryParams(**params)

    @staticmethod
    def extract_data(
        query: FederalReserveAtlantaGdpNowQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Download the GDPNow tracking workbook from the Atlanta Fed."""
        from openbb_core.provider.utils.helpers import make_request

        from openbb_federal_reserve.utils.cache import (
            cached,
            seconds_until_next_release,
        )

        def _producer() -> bytes:
            """Fetch the raw GDPNow tracking workbook bytes."""
            response = make_request(URL)
            response.raise_for_status()
            return response.content

        content = cached(
            "atlanta_gdpnow", lambda: seconds_until_next_release("daily"), _producer
        )
        if not content:
            raise EmptyDataError("The request was returned empty.")
        return [{"_raw": content}]

    @staticmethod
    def transform_data(
        query: FederalReserveAtlantaGdpNowQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FederalReserveAtlantaGdpNowData]:
        """Pivot the selected GDPNow table to wide ``date`` + per-series columns."""
        from io import BytesIO

        from pandas import read_excel

        from openbb_federal_reserve.utils.workbook import pivot_wide

        sheets = {
            "evolution": "CurrentQtrEvolution",
            "contributions": "Contributions",
            "change_in_contributions": "ChangeInContributions",
            "table": "Table",
            "table_contributions": "TableCont",
            "track_record": "TrackRecord",
        }
        frame = read_excel(
            BytesIO(data[0]["_raw"]),
            engine="openpyxl",
            sheet_name=sheets[query.table],
            header=None,
        )
        grid = frame.where(frame.notna(), None).values.tolist()

        if query.table == "track_record":
            records = _flat_table(grid, header_row=0)
        elif query.table == "evolution":
            records = _melt_evolution(grid)
        elif query.table in ("contributions", "change_in_contributions"):
            records = _melt_table(grid, header_row=1, value_start=2, label_column=11)
        else:
            records = _melt_table(grid, header_row=0, value_start=2, label_column=1)

        if query.start_date:
            records = [r for r in records if r["date"] >= query.start_date]
        if query.end_date:
            records = [r for r in records if r["date"] <= query.end_date]
        if not records:
            raise EmptyDataError("The request was returned empty.")

        if query.table == "track_record":
            rows = sorted(records, key=lambda r: r["date"])
        else:
            ordered = sorted(records, key=lambda r: (r["date"], r["series"]))
            rows = pivot_wide(
                ordered,
                index=("date", "major_release"),
                column="series",
                value="value",
            )
        return [
            FederalReserveAtlantaGdpNowData.model_validate(record) for record in rows
        ]
