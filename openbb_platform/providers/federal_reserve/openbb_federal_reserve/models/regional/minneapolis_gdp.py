"""Federal Reserve Bank of Minneapolis Regional GDP Model."""

from datetime import date as dateType
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

URL = (
    "https://www.minneapolisfed.org/~/media/Assets/Pages"
    "/regional-economic-indicators/real_gdp.csv"
)

_GEOGRAPHIES = ["US", "MN", "MT", "ND", "SD", "WI"]


class FederalReserveMinneapolisGdpQueryParams(QueryParams):
    """Minneapolis Fed Regional GDP Query Parameters."""

    start_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("start_date", "")
    )
    end_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("end_date", "")
    )


class FederalReserveMinneapolisGdpData(Data):
    """Minneapolis Fed Regional GDP Data."""

    date: dateType = Field(description="The start of the observation quarter.")


class FederalReserveMinneapolisGdpFetcher(
    Fetcher[
        FederalReserveMinneapolisGdpQueryParams,
        list[FederalReserveMinneapolisGdpData],
    ]
):
    """Minneapolis Fed Regional GDP Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FederalReserveMinneapolisGdpQueryParams:
        """Transform the query params."""
        return FederalReserveMinneapolisGdpQueryParams(**params)

    @staticmethod
    def extract_data(
        query: FederalReserveMinneapolisGdpQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Download the regional GDP CSV from the Minneapolis Fed."""
        from openbb_core.provider.utils.helpers import make_request

        from openbb_federal_reserve.utils.cache import (
            cached,
            seconds_until_next_release,
        )

        def _producer() -> str:
            """Fetch the raw regional GDP CSV text."""
            response = make_request(URL)
            response.raise_for_status()
            return response.text

        text = cached(
            "minneapolis_gdp",
            lambda: seconds_until_next_release("quarterly"),
            _producer,
        )
        if not text:
            raise EmptyDataError("The request was returned empty.")
        return [{"_raw": text}]

    @staticmethod
    def transform_data(
        query: FederalReserveMinneapolisGdpQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FederalReserveMinneapolisGdpData]:
        """Parse the quarter labels and return one column per geography."""
        from io import StringIO

        from pandas import PeriodIndex, Series, isna, read_csv, to_numeric

        frame = read_csv(StringIO(data[0]["_raw"]))
        period = frame["Period"].str.replace(r"Q(\d)\s+(\d{4})", r"\2Q\1", regex=True)
        date_index = PeriodIndex(period, freq="Q").to_timestamp()
        frame["date"] = Series(date_index, index=frame.index).dt.date
        value_columns = [c for c in _GEOGRAPHIES if c in frame.columns]
        for column in value_columns:
            frame[column] = to_numeric(frame[column], errors="coerce")

        if query.start_date:
            frame = frame[frame["date"] >= query.start_date]
        if query.end_date:
            frame = frame[frame["date"] <= query.end_date]

        records: list[FederalReserveMinneapolisGdpData] = []
        for row in frame.sort_values("date").to_dict(orient="records"):
            record = {
                "date": row["date"],
                **{
                    column: (None if isna(row[column]) else row[column])
                    for column in value_columns
                },
            }
            if any(record[column] is not None for column in value_columns):
                records.append(FederalReserveMinneapolisGdpData.model_validate(record))
        if not records:
            raise EmptyDataError("The request was returned empty.")
        return records
