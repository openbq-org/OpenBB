"""Federal Reserve Bank of Dallas Index of Global Real Economic Activity Model."""

from datetime import date as dateType
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

URL = "https://www.dallasfed.org/-/media/Documents/research/igrea/igrea.xlsx"


class FederalReserveDallasIgreaQueryParams(QueryParams):
    """Dallas Fed Index of Global Real Economic Activity Query Parameters."""

    start_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("start_date", "")
    )
    end_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("end_date", "")
    )


class FederalReserveDallasIgreaData(Data):
    """Dallas Fed Index of Global Real Economic Activity Data."""

    date: dateType = Field(description="The observation month.")
    value: float | None = Field(
        default=None, description="The index value, in percent deviation from trend."
    )


class FederalReserveDallasIgreaFetcher(
    Fetcher[
        FederalReserveDallasIgreaQueryParams,
        list[FederalReserveDallasIgreaData],
    ]
):
    """Dallas Fed Index of Global Real Economic Activity Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FederalReserveDallasIgreaQueryParams:
        """Transform the query params."""
        return FederalReserveDallasIgreaQueryParams(**params)

    @staticmethod
    def extract_data(
        query: FederalReserveDallasIgreaQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Download the IGREA workbook from the Dallas Fed."""
        from openbb_core.provider.utils.helpers import make_request

        from openbb_federal_reserve.utils.cache import (
            cached,
            seconds_until_next_release,
        )

        def _producer() -> bytes:
            """Fetch the raw IGREA workbook bytes."""
            response = make_request(URL)
            response.raise_for_status()
            return response.content

        content = cached(
            "dallas_igrea", lambda: seconds_until_next_release("monthly"), _producer
        )
        if not content:
            raise EmptyDataError("The request was returned empty.")
        return [{"_raw": content}]

    @staticmethod
    def transform_data(
        query: FederalReserveDallasIgreaQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FederalReserveDallasIgreaData]:
        """Parse the index series and apply the date filters."""
        from io import BytesIO

        from pandas import ExcelFile, isna, read_excel, to_datetime

        # The workbook's sheet was renamed upstream: old name, new name, then the only sheet.
        sheets = ExcelFile(BytesIO(data[0]["_raw"])).sheet_names
        sheet = next(
            (s for s in ("IGREA", "Kilian Index") if s in sheets),
            sheets[0] if len(sheets) == 1 else "IGREA",
        )
        frame = read_excel(BytesIO(data[0]["_raw"]), sheet_name=sheet)
        frame = frame.rename(
            columns={frame.columns[0]: "date", frame.columns[1]: "value"}
        )
        frame["date"] = to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date"])
        frame["date"] = frame["date"].dt.date

        if query.start_date:
            frame = frame[frame["date"] >= query.start_date]
        if query.end_date:
            frame = frame[frame["date"] <= query.end_date]

        return [
            FederalReserveDallasIgreaData.model_validate(
                {
                    "date": row["date"],
                    "value": (
                        None
                        if isinstance(row["value"], float) and isna(row["value"])
                        else row["value"]
                    ),
                }
            )
            for row in frame.sort_values("date").to_dict(orient="records")
        ]
