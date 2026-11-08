"""Federal Reserve Bank of Atlanta Sticky-Price CPI Model."""

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
    "/research-and-data/data/sticky-price/sticky-price-data.xlsx"
)

_NA_VALUES = ["na", ".", "#N/A", "#N/A N/A"]
_TRANSFORMS = ["monthly", "1-month annualized", "3-month annualized", "12-month"]

_TRANSFORM_OPTIONS = [
    {"label": "Monthly", "value": "monthly"},
    {"label": "1-Month Annualized", "value": "1-month annualized"},
    {"label": "3-Month Annualized Rate", "value": "3-month annualized"},
    {"label": "12-Month", "value": "12-month"},
]


def _measure_name(raw: str) -> str:
    """Normalize a block-leading column header into a measure name."""
    name = str(raw).split("(")[0]
    name = name.replace("EX_shelter", "ex-shelter").replace(
        "_ex shelter", " ex-shelter"
    )
    return " ".join(name.split())


class FederalReserveAtlantaStickyCpiQueryParams(QueryParams):
    """Atlanta Fed Sticky-Price CPI Query Parameters."""

    __json_schema_extra__ = {
        "transform": {"x-widget_config": {"options": _TRANSFORM_OPTIONS}},
    }

    transform: Literal[
        "monthly", "1-month annualized", "3-month annualized", "12-month"
    ] = Field(
        default="1-month annualized",
        description="The transform to return for every measure: the monthly level,"
        " the 1-month annualized percent change, the 3-month annualized rate, or the"
        " 12-month percent change.",
    )
    start_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("start_date", "")
    )
    end_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("end_date", "")
    )


class FederalReserveAtlantaStickyCpiData(Data):
    """Atlanta Fed Sticky-Price CPI Data."""

    date: dateType = Field(description="The observation month.")


class FederalReserveAtlantaStickyCpiFetcher(
    Fetcher[
        FederalReserveAtlantaStickyCpiQueryParams,
        list[FederalReserveAtlantaStickyCpiData],
    ]
):
    """Atlanta Fed Sticky-Price CPI Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FederalReserveAtlantaStickyCpiQueryParams:
        """Transform the query params."""
        return FederalReserveAtlantaStickyCpiQueryParams(**params)

    @staticmethod
    def extract_data(
        query: FederalReserveAtlantaStickyCpiQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Download the Sticky-Price CPI workbook from the Atlanta Fed."""
        from openbb_core.provider.utils.helpers import make_request

        from openbb_federal_reserve.utils.cache import (
            cached,
            seconds_until_next_release,
        )

        def _producer() -> bytes:
            """Fetch the raw Sticky-Price CPI workbook bytes."""
            response = make_request(URL)
            response.raise_for_status()
            return response.content

        content = cached(
            "atlanta_sticky_cpi",
            lambda: seconds_until_next_release("monthly"),
            _producer,
        )
        if not content:
            raise EmptyDataError("The request was returned empty.")
        return [{"_raw": content}]

    @staticmethod
    def transform_data(
        query: FederalReserveAtlantaStickyCpiQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FederalReserveAtlantaStickyCpiData]:
        """Pivot the selected transform to wide ``date`` + per-measure rows."""
        from datetime import datetime
        from io import BytesIO

        from pandas import isna, read_excel, to_datetime, to_numeric

        frame = read_excel(
            BytesIO(data[0]["_raw"]),
            engine="openpyxl",
            sheet_name="Data",
            header=None,
            na_values=_NA_VALUES,
        )
        first_data = next(
            (i for i, v in enumerate(frame[0]) if isinstance(v, (datetime, dateType))),
            None,
        )
        if first_data is None:
            raise EmptyDataError("The request was returned empty.")
        header = frame.iloc[first_data - 1]

        value_columns = [
            column
            for column in frame.columns[1:]
            if not isna(header[column]) and str(header[column]).strip()
        ]
        measure_columns: dict[str, Any] = {}
        measure = ""
        for position, column in enumerate(value_columns):
            transform = position % 4
            if transform == 0:
                measure = _measure_name(str(header[column]))
            if _TRANSFORMS[transform] == query.transform:
                measure_columns[measure] = column

        body = frame.iloc[first_data:].copy()
        body["date"] = to_datetime(
            body[0].astype(str).str.strip(), format="mixed", errors="coerce"
        )
        body = body.dropna(subset=["date"])
        body["date"] = body["date"].dt.date
        for column in measure_columns.values():
            body[column] = to_numeric(body[column], errors="coerce")
        if query.start_date:
            body = body[body["date"] >= query.start_date]
        if query.end_date:
            body = body[body["date"] <= query.end_date]

        records: list[FederalReserveAtlantaStickyCpiData] = []
        for row in body.sort_values("date").to_dict(orient="records"):
            record: dict[str, Any] = {"date": row["date"]}
            for measure, column in measure_columns.items():
                cell = row[column]
                record[measure] = (
                    None if isinstance(cell, float) and isna(cell) else cell
                )
            if any(record[measure] is not None for measure in measure_columns):
                records.append(
                    FederalReserveAtlantaStickyCpiData.model_validate(record)
                )
        if not records:
            raise EmptyDataError("The request was returned empty.")
        return records
