"""Federal Reserve Bank of Atlanta Taylor Rule Utility Models."""

from datetime import date as dateType
from typing import Any, Literal

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

URL = (
    "https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents"
    "/research-and-data/data/taylor-rule/taylor-rule-data.xlsx"
)

_NA_VALUES = ["#N/A", "#N/A N/A", "na", "."]

_CHART_SHEETS = {
    "taylor_93_unemployment": "FOMCTaylor93UR",
    "taylor_99_unemployment": "FOMCTaylor99UR",
    "taylor_93_gdp": "Taylor93GDP",
}
_MEASURE_SHEETS = {
    "natural_rate": "NaturalRateMeasures",
    "gap": "GapMeasures",
    "inflation": "InflationMeasures",
    "inflation_target": "InflationTargetMeasures",
    "fed_funds": "FedFundsRates",
}
_HEATMAP_SHEETS = {
    "latest": "HeatMapLatestQuarter",
    "previous": "HeatMapPreviousQuarter",
}


def _workbook() -> bytes:
    """Download the Taylor Rule workbook bytes (cached quarterly)."""
    from openbb_core.provider.utils.helpers import make_request

    from openbb_federal_reserve.utils.cache import cached, seconds_until_next_release

    def _producer() -> bytes:
        """Fetch the raw Taylor Rule workbook bytes."""
        response = make_request(URL)
        response.raise_for_status()
        return response.content

    content = cached(
        "atlanta_taylor_rule",
        lambda: seconds_until_next_release("quarterly"),
        _producer,
    )
    if not content:
        raise EmptyDataError("The request was returned empty.")
    return content


class FederalReserveAtlantaTaylorRuleQueryParams(QueryParams):
    """Atlanta Fed Taylor Rule prescription Query Parameters."""

    start_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("start_date", "")
    )
    end_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("end_date", "")
    )


class FederalReserveAtlantaTaylorRuleData(Data):
    """Atlanta Fed Taylor Rule prescription Data."""

    date: dateType = Field(description="The mid-quarter observation date.")
    actual_fed_funds_rate: float | None = Field(
        default=None, description="The actual federal funds rate."
    )
    taylor_93_unemployment: float | None = Field(
        default=None,
        description="1993 rule prescription (r*=FOMC median, gap=FOMC U-3 gap,"
        " gap weight=0.5).",
    )
    taylor_99_unemployment: float | None = Field(
        default=None,
        description="1999 balanced-approach prescription (r*=FOMC median,"
        " gap=FOMC U-3 gap, gap weight=1.0).",
    )
    taylor_93_gdp: float | None = Field(
        default=None,
        description="1993 rule prescription (r*=LW 1-sided, gap=CBO GDP gap,"
        " gap weight=0.5).",
    )


class FederalReserveAtlantaTaylorRuleFetcher(
    Fetcher[
        FederalReserveAtlantaTaylorRuleQueryParams,
        list[FederalReserveAtlantaTaylorRuleData],
    ]
):
    """Atlanta Fed Taylor Rule prescription Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FederalReserveAtlantaTaylorRuleQueryParams:
        """Transform the query params."""
        return FederalReserveAtlantaTaylorRuleQueryParams(**params)

    @staticmethod
    def extract_data(
        query: FederalReserveAtlantaTaylorRuleQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Download the Taylor Rule workbook from the Atlanta Fed."""
        return [{"_raw": _workbook()}]

    @staticmethod
    def transform_data(
        query: FederalReserveAtlantaTaylorRuleQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FederalReserveAtlantaTaylorRuleData]:
        """Overlay each rule's prescription with the actual rate, keyed by date."""
        from io import BytesIO

        from pandas import isna, read_excel

        from openbb_federal_reserve.utils.workbook import cell_dates

        frames = read_excel(
            BytesIO(data[0]["_raw"]),
            engine="openpyxl",
            sheet_name=list(_CHART_SHEETS.values()),
            header=1,
            na_values=_NA_VALUES,
        )
        merged: dict[dateType, dict[str, Any]] = {}
        actual_by_date: dict[dateType, float | None] = {}
        for field, sheet in _CHART_SHEETS.items():
            frame = frames[sheet]
            prescribed = next(
                (c for c in frame.columns if str(c).startswith(sheet)), None
            )
            actual = next(
                (c for c in frame.columns if str(c).strip() == "Actual Fed Funds Rate"),
                None,
            )
            dates = cell_dates(frame[frame.columns[0]])
            for index in range(len(frame)):
                observation = dates[index]
                if observation is None:
                    continue
                record = merged.setdefault(observation, {"date": observation})
                cell = frame[prescribed].iloc[index] if prescribed else None
                record[field] = None if cell is None or isna(cell) else float(cell)
                if actual is not None and observation not in actual_by_date:
                    value = frame[actual].iloc[index]
                    actual_by_date[observation] = None if isna(value) else float(value)

        records = []
        for observation, record in merged.items():
            if query.start_date and observation < query.start_date:
                continue
            if query.end_date and observation > query.end_date:
                continue
            record["actual_fed_funds_rate"] = actual_by_date.get(observation)
            records.append(FederalReserveAtlantaTaylorRuleData.model_validate(record))
        return sorted(records, key=lambda record: record.date)


class FederalReserveAtlantaTaylorRuleMeasuresQueryParams(QueryParams):
    """Atlanta Fed Taylor Rule input-measures Query Parameters."""

    __json_schema_extra__ = {
        "measure": {
            "x-widget_config": {
                "options": [
                    {"label": "Natural Real Rate (r*)", "value": "natural_rate"},
                    {"label": "Resource Gap", "value": "gap"},
                    {"label": "Inflation", "value": "inflation"},
                    {"label": "Inflation Target", "value": "inflation_target"},
                    {"label": "Federal Funds Rate", "value": "fed_funds"},
                ]
            }
        },
    }

    measure: Literal[
        "natural_rate", "gap", "inflation", "inflation_target", "fed_funds"
    ] = Field(
        default="natural_rate",
        description="The menu of candidate input measures to return: natural real"
        " rate (r*), resource gap, inflation, inflation target, or funds rate.",
    )
    start_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("start_date", "")
    )
    end_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("end_date", "")
    )


class FederalReserveAtlantaTaylorRuleMeasuresData(Data):
    """Atlanta Fed Taylor Rule input-measures Data."""

    date: dateType = Field(description="The mid-quarter observation date.")


class FederalReserveAtlantaTaylorRuleMeasuresFetcher(
    Fetcher[
        FederalReserveAtlantaTaylorRuleMeasuresQueryParams,
        list[FederalReserveAtlantaTaylorRuleMeasuresData],
    ]
):
    """Atlanta Fed Taylor Rule input-measures Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FederalReserveAtlantaTaylorRuleMeasuresQueryParams:
        """Transform the query params."""
        return FederalReserveAtlantaTaylorRuleMeasuresQueryParams(**params)

    @staticmethod
    def extract_data(
        query: FederalReserveAtlantaTaylorRuleMeasuresQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Download the Taylor Rule workbook from the Atlanta Fed."""
        return [{"_raw": _workbook()}]

    @staticmethod
    def transform_data(
        query: FederalReserveAtlantaTaylorRuleMeasuresQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FederalReserveAtlantaTaylorRuleMeasuresData]:
        """Pivot the selected measure sheet to wide ``date`` + per-measure columns."""
        from io import BytesIO

        from pandas import isna, read_excel, to_datetime, to_numeric

        frame = read_excel(
            BytesIO(data[0]["_raw"]),
            engine="openpyxl",
            sheet_name=_MEASURE_SHEETS[query.measure],
            header=1,
            na_values=_NA_VALUES,
        )
        measures = [str(column) for column in frame.columns[1:]]
        frame.columns = ["date", *measures]
        frame["date"] = to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date"])
        for column in measures:
            frame[column] = to_numeric(frame[column], errors="coerce")
        frame["date"] = frame["date"].dt.date
        if query.start_date:
            frame = frame[frame["date"] >= query.start_date]
        if query.end_date:
            frame = frame[frame["date"] <= query.end_date]

        records: list[FederalReserveAtlantaTaylorRuleMeasuresData] = []
        for row in frame.sort_values("date").to_dict(orient="records"):
            record: dict[str, Any] = {"date": row["date"]}
            for measure in measures:
                cell = row[measure]
                record[measure] = (
                    None if isinstance(cell, float) and isna(cell) else cell
                )
            if any(record[measure] is not None for measure in measures):
                records.append(
                    FederalReserveAtlantaTaylorRuleMeasuresData.model_validate(record)
                )
        if not records:
            raise EmptyDataError("The request was returned empty.")
        return records


class FederalReserveAtlantaTaylorRuleHeatmapQueryParams(QueryParams):
    """Atlanta Fed Taylor Rule heat-map Query Parameters."""

    __json_schema_extra__ = {
        "quarter": {
            "x-widget_config": {
                "options": [
                    {"label": "Latest Quarter", "value": "latest"},
                    {"label": "Previous Quarter", "value": "previous"},
                ]
            }
        },
    }

    quarter: Literal["latest", "previous"] = Field(
        default="latest",
        description="Which quarterly heat-map snapshot to return.",
    )


class FederalReserveAtlantaTaylorRuleHeatmapData(Data):
    """Atlanta Fed Taylor Rule heat-map Data."""

    r_star_measure: str = Field(
        description="The natural-real-rate (r*) measure labeling the row."
    )


class FederalReserveAtlantaTaylorRuleHeatmapFetcher(
    Fetcher[
        FederalReserveAtlantaTaylorRuleHeatmapQueryParams,
        list[FederalReserveAtlantaTaylorRuleHeatmapData],
    ]
):
    """Atlanta Fed Taylor Rule heat-map Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FederalReserveAtlantaTaylorRuleHeatmapQueryParams:
        """Transform the query params."""
        return FederalReserveAtlantaTaylorRuleHeatmapQueryParams(**params)

    @staticmethod
    def extract_data(
        query: FederalReserveAtlantaTaylorRuleHeatmapQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Download the Taylor Rule workbook from the Atlanta Fed."""
        return [{"_raw": _workbook()}]

    @staticmethod
    def transform_data(
        query: FederalReserveAtlantaTaylorRuleHeatmapQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FederalReserveAtlantaTaylorRuleHeatmapData]:
        """Parse the r* x gap prescription grid out of the heat-map sheet."""
        from io import BytesIO

        from pandas import isna, read_excel

        frame = read_excel(
            BytesIO(data[0]["_raw"]),
            engine="openpyxl",
            sheet_name=_HEATMAP_SHEETS[query.quarter],
            header=None,
        )
        grid = frame.values.tolist()

        def _text(value) -> str:
            """Return a trimmed string for a cell, or an empty string for blanks."""
            if value is None or (isinstance(value, float) and isna(value)):
                return ""
            return str(value).strip()

        gap_header_row = next(
            (
                i + 1
                for i, row in enumerate(grid)
                if any("Measure of Gap" in _text(c) for c in row)
            ),
            None,
        )
        if gap_header_row is None:
            raise EmptyDataError("The request was returned empty.")

        gap_columns: dict[int, str] = {}
        for j in range(2, len(grid[gap_header_row])):
            label = _text(grid[gap_header_row][j])
            if not label:
                break
            gap_columns[j] = label

        records: list[FederalReserveAtlantaTaylorRuleHeatmapData] = []
        for row in grid[gap_header_row + 1 :]:
            label = _text(row[1]) if len(row) > 1 else ""
            if not label or label.lower() == "nan":
                continue
            if not any(ch.isalpha() for ch in label):
                continue
            record: dict[str, Any] = {"r_star_measure": label}
            has_value = False
            for column, gap in gap_columns.items():
                cell = row[column] if column < len(row) else None
                if isinstance(cell, (int, float)) and not isinstance(cell, bool):
                    record[gap] = float(cell)
                    has_value = True
            if has_value:
                records.append(
                    FederalReserveAtlantaTaylorRuleHeatmapData.model_validate(record)
                )
        if not records:
            raise EmptyDataError("The request was returned empty.")
        return records
