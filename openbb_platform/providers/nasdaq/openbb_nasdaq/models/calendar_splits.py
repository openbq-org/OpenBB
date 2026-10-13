"""Nasdaq Splits Calendar Model."""

from datetime import date as dateType
from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.calendar_splits import (
    CalendarSplitsData,
    CalendarSplitsQueryParams,
)
from openbb_core.provider.utils.descriptions import DATA_DESCRIPTIONS
from pydantic import Field

from openbb_nasdaq.utils.constants import CELL_CLICK_SYMBOL


class NasdaqCalendarSplitsQueryParams(CalendarSplitsQueryParams):
    """Nasdaq Splits Calendar Query.

    Source: https://www.nasdaq.com/market-activity/stock-splits
    """


class NasdaqCalendarSplitsData(CalendarSplitsData):
    """Nasdaq Splits Calendar Data."""

    symbol: str = Field(
        description=DATA_DESCRIPTIONS.get("symbol", ""),
        json_schema_extra={"x-widget_config": CELL_CLICK_SYMBOL},
    )
    name: str | None = Field(default=None, description="The name of the company.")
    numerator: float | None = Field(
        default=None, description="Numerator of the stock split."
    )
    denominator: float | None = Field(
        default=None, description="Denominator of the stock split."
    )
    ratio_display: str | None = Field(
        default=None, description="The split ratio, as published - i.e., '16 : 1'."
    )
    payable_date: dateType | None = Field(
        default=None, description="The effective date of the split."
    )


class NasdaqCalendarSplitsFetcher(
    Fetcher[
        NasdaqCalendarSplitsQueryParams,
        list[NasdaqCalendarSplitsData],
    ]
):
    """Transform the query, extract and transform the data from the Nasdaq endpoints."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> NasdaqCalendarSplitsQueryParams:
        """Transform the query params, defaulting to the coming month."""
        from datetime import date, timedelta

        transformed = params.copy()
        today = date.today()

        if transformed.get("start_date") is None:
            transformed["start_date"] = today

        if transformed.get("end_date") is None:
            transformed["end_date"] = today + timedelta(days=30)

        return NasdaqCalendarSplitsQueryParams(**transformed)

    @staticmethod
    async def aextract_data(
        query: NasdaqCalendarSplitsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Return the raw data from the Nasdaq endpoint."""
        from openbb_core.provider.utils.errors import EmptyDataError

        from openbb_nasdaq.utils.helpers import get_nasdaq_data, rows_from_table

        data = await get_nasdaq_data(f"calendar/splits?date={query.start_date}")
        rows = rows_from_table(data)

        if not rows:
            raise EmptyDataError("No stock splits were returned.")

        return rows

    @staticmethod
    def transform_data(
        query: NasdaqCalendarSplitsQueryParams, data: list[dict], **kwargs: Any
    ) -> list[NasdaqCalendarSplitsData]:
        """Transform the data to the standard format."""
        from openbb_nasdaq.utils.helpers import to_date, to_number

        results: list[NasdaqCalendarSplitsData] = []

        for row in data:
            effective = to_date(row.get("executionDate"))

            if effective is None:
                continue

            if query.start_date and effective < query.start_date:
                continue

            if query.end_date and effective > query.end_date:
                continue

            ratio = row.get("ratio")
            numerator, denominator = _split_ratio(ratio)
            results.append(
                NasdaqCalendarSplitsData.model_validate(
                    {
                        "date": effective,
                        "payable_date": effective,
                        "symbol": row.get("symbol"),
                        "name": row.get("name"),
                        "ratio_display": ratio,
                        "numerator": numerator,
                        "denominator": denominator,
                        "split_ratio": (
                            numerator / denominator
                            if numerator and denominator
                            else to_number(ratio)
                        ),
                    }
                )
            )

        return sorted(results, key=lambda r: r.date)


def _split_ratio(ratio: Any) -> tuple[float | None, float | None]:
    """Split a '16 : 1' ratio string into its numerator and denominator.

    Parameters
    ----------
    ratio : Any
        The published ratio string.

    Returns
    -------
    tuple[float | None, float | None]
        The numerator and the denominator.
    """
    from openbb_nasdaq.utils.helpers import to_number

    if not isinstance(ratio, str) or ":" not in ratio:
        return None, None

    parts = [to_number(p) for p in ratio.split(":", 1)]

    if len(parts) != 2 or parts[0] is None or not parts[1]:
        return None, None

    return parts[0], parts[1]
