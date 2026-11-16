"""Federal Reserve Bank of Atlanta Market Probability Tracker Model."""

import re
from datetime import date as dateType
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_federal_reserve.models.regional.atlanta_publications import api_prefix

URL = (
    "https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents"
    "/research-and-data/data/market-probability-tracker/mpt_histdata.xlsx"
)

_BIN_PATTERN = re.compile(r"^Prob: (\d+)bps - (\d+)bps$")


def _meetings_with_distribution(latest_frame: Any) -> list[dateType]:
    """Return the ascending reference meetings that carry probability bins."""
    with_bins = latest_frame[
        latest_frame["field"].astype(str).str.match(_BIN_PATTERN.pattern)
    ]
    return sorted(set(with_bins["reference_start"]))


def _load_meetings(content: bytes) -> tuple[dateType, list[dateType]]:
    """Return the latest observation date and its meetings that have a distribution."""
    from io import BytesIO

    from pandas import read_excel, to_datetime

    frame = read_excel(BytesIO(content), engine="openpyxl", sheet_name="DATA")
    frame["date"] = to_datetime(frame["date"], errors="coerce")
    frame["reference_start"] = to_datetime(frame["reference_start"], errors="coerce")
    frame = frame.dropna(subset=["date", "reference_start"])
    if frame.empty:
        raise EmptyDataError("The request was returned empty.")
    frame["date"] = frame["date"].dt.date
    frame["reference_start"] = frame["reference_start"].dt.date
    latest = max(frame["date"])
    meetings = _meetings_with_distribution(frame[frame["date"] == latest])
    if not meetings:
        raise EmptyDataError("The request was returned empty.")
    return latest, meetings


def _nearest_meeting(meetings: list[dateType]) -> dateType:
    """Pick the nearest upcoming meeting, falling back to the earliest available."""
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date()
    upcoming = [meeting for meeting in meetings if meeting >= today]
    return min(upcoming) if upcoming else min(meetings)


class FederalReserveAtlantaMarketProbabilityQueryParams(QueryParams):
    """Atlanta Fed Market Probability Tracker Query Parameters."""

    __json_schema_extra__ = {
        "meeting": {
            "x-widget_config": {
                "type": "endpoint",
                "optionsEndpoint": (
                    f"{api_prefix}/federal_reserve/market_probability_meetings"
                ),
            }
        },
    }

    meeting: str | None = Field(
        default=None,
        description="The reference FOMC meeting date (ISO) whose implied"
        " target-rate-range distribution to return. When omitted, the nearest"
        " upcoming meeting is used.",
    )
    start_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("start_date", "")
    )
    end_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("end_date", "")
    )


class FederalReserveAtlantaMarketProbabilityData(Data):
    """Atlanta Fed Market Probability Tracker Data."""

    target_range: str = Field(
        description="The target federal-funds-rate range label for the bin."
    )
    probability: float | None = Field(
        default=None,
        description="The implied probability for the bin at the selected meeting.",
    )


class FederalReserveAtlantaMarketProbabilityFetcher(
    Fetcher[
        FederalReserveAtlantaMarketProbabilityQueryParams,
        list[FederalReserveAtlantaMarketProbabilityData],
    ]
):
    """Atlanta Fed Market Probability Tracker Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FederalReserveAtlantaMarketProbabilityQueryParams:
        """Transform the query params."""
        return FederalReserveAtlantaMarketProbabilityQueryParams(**params)

    @staticmethod
    def extract_data(
        query: FederalReserveAtlantaMarketProbabilityQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Download the Market Probability Tracker workbook from the Atlanta Fed."""
        from openbb_core.provider.utils.helpers import make_request

        from openbb_federal_reserve.utils.cache import (
            cached,
            seconds_until_next_release,
        )

        def _producer() -> bytes:
            """Fetch the raw Market Probability Tracker workbook bytes."""
            response = make_request(URL)
            response.raise_for_status()
            return response.content

        content = cached(
            "atlanta_market_probability",
            lambda: seconds_until_next_release("daily"),
            _producer,
        )
        if not content:
            raise EmptyDataError("The request was returned empty.")
        return [{"_raw": content}]

    @staticmethod
    def transform_data(
        query: FederalReserveAtlantaMarketProbabilityQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FederalReserveAtlantaMarketProbabilityData]:
        """Return the selected meeting's distribution bins for the latest date."""
        from io import BytesIO

        from pandas import isna, read_excel, to_datetime

        frame = read_excel(
            BytesIO(data[0]["_raw"]), engine="openpyxl", sheet_name="DATA"
        )
        frame["date"] = to_datetime(frame["date"], errors="coerce")
        frame["reference_start"] = to_datetime(
            frame["reference_start"], errors="coerce"
        )
        frame = frame.dropna(subset=["date", "reference_start"])
        frame["date"] = frame["date"].dt.date
        frame["reference_start"] = frame["reference_start"].dt.date

        if query.start_date:
            frame = frame[frame["date"] >= query.start_date]
        if query.end_date:
            frame = frame[frame["date"] <= query.end_date]
        if frame.empty:
            raise EmptyDataError("The request was returned empty.")

        latest = max(frame["date"])
        frame = frame[frame["date"] == latest]

        meetings = _meetings_with_distribution(frame)
        if not meetings:
            raise EmptyDataError("The request was returned empty.")
        meeting = None
        if query.meeting:
            meeting = dateType.fromisoformat(query.meeting)
            if meeting not in meetings:
                meeting = None
        if meeting is None:
            meeting = _nearest_meeting(meetings)
        frame = frame[frame["reference_start"] == meeting]

        bins: dict[str, dict[str, Any]] = {}
        order: dict[str, int] = {}
        for row in frame.to_dict(orient="records"):
            match = _BIN_PATTERN.match(str(row["field"]))
            if match is None:
                continue
            low, high = int(match.group(1)), int(match.group(2))
            label = f"{low / 100:.2f}–{high / 100:.2f}%"
            order[label] = low
            value = row["value"]
            value = None if isinstance(value, float) and isna(value) else value
            bins[label] = {"target_range": label, "probability": value}

        return [
            FederalReserveAtlantaMarketProbabilityData.model_validate(bins[label])
            for label in sorted(bins, key=lambda label: order[label])
        ]
