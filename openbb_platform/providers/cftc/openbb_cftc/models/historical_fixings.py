"""CFTC Historical Fixings Model."""

from datetime import (
    UTC,
    date as dateType,
)
from typing import Any

from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field, field_validator

from openbb_cftc.utils.fixings import FIXING_SOURCES, fixing_profile

FIXING_CHOICES = sorted(
    FIXING_SOURCES, key=lambda index: (fixing_profile(index)[1], index)
)
DEFAULT_LOOKBACK_DAYS = 365


def index_options() -> list[dict]:
    """Dropdown entries naming each index and the country it is published for."""
    options: list[dict] = []

    for index in FIXING_CHOICES:
        name, country = fixing_profile(index)
        options.append(
            {
                "label": index,
                "value": index,
                "extraInfo": {
                    "description": f"{name} | {country}",
                    "rightOfDescription": country,
                },
            }
        )

    return options


class CftcHistoricalFixingsQueryParams(QueryParams):
    """CFTC Historical Fixings Query Parameters."""

    __json_schema_extra__ = {
        "index": {
            "multiple_items_allowed": False,
            "x-widget_config": {"options": index_options()},
        },
    }

    index: str = Field(
        default="SOFR",
        description="Published benchmark to return fixings for.",
    )
    start_date: dateType | None = Field(
        default=None,
        description="Start date of the window. Default is one year back.",
    )
    end_date: dateType | None = Field(
        default=None,
        description="End date of the window. Default is today.",
    )
    use_cache: bool = Field(
        default=True,
        description="Cache the published fixings locally.",
    )

    @field_validator("index", mode="before")
    @classmethod
    def _to_upper(cls, v):
        """Accept an index in any case."""
        return v.upper() if isinstance(v, str) else v


class CftcHistoricalFixingsData(Data):
    """CFTC Historical Fixings Data."""

    date: dateType = Field(
        description="Effective date of the fixing.",
        json_schema_extra={"x-widget_config": {"headerName": "Date"}},
    )
    rate: float = Field(
        description="Published fixing, as a percent.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Rate",
                "cellDataType": "number",
                "formatterFn": "none",
                "decimalPlaces": 5,
                "suffix": " %",
            }
        },
    )
    change_bps: float | None = Field(
        default=None,
        description="Change from the previous published fixing, in basis points.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Change (bps)",
                "cellDataType": "number",
                "formatterFn": "none",
                "decimalPlaces": 2,
            }
        },
    )


def build_series(fixings: dict[dateType, float]) -> list[dict]:
    """Order the fixings oldest first and attach the day-on-day change."""
    rows: list[dict] = []
    previous: float | None = None

    for day in sorted(fixings):
        rate = 100.0 * fixings[day]
        rows.append(
            {
                "date": day,
                "rate": rate,
                "change_bps": (
                    None if previous is None else round(100.0 * (rate - previous), 2)
                ),
            }
        )
        previous = rate

    return rows


class CftcHistoricalFixingsFetcher(
    Fetcher[CftcHistoricalFixingsQueryParams, list[CftcHistoricalFixingsData]]
):
    """CFTC Historical Fixings Fetcher."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> CftcHistoricalFixingsQueryParams:
        """Transform the query params."""
        from datetime import datetime, timedelta

        transformed = dict(params)
        today = datetime.now(UTC).date()

        if not transformed.get("end_date"):
            transformed["end_date"] = today

        if not transformed.get("start_date"):
            transformed["start_date"] = transformed["end_date"] - timedelta(
                days=DEFAULT_LOOKBACK_DAYS
            )

        return CftcHistoricalFixingsQueryParams(**transformed)

    @staticmethod
    async def aextract_data(
        query: CftcHistoricalFixingsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict[dateType, float]:
        """Fetch the index's published fixings over the window."""
        from datetime import datetime, timedelta

        from openbb_core.provider.utils.errors import EmptyDataError

        from openbb_cftc.utils.fixings import get_fixings

        if query.index not in FIXING_SOURCES:
            raise EmptyDataError(
                f"'{query.index}' is not a published benchmark. Choose one of:"
                f" {', '.join(FIXING_CHOICES)}."
            )

        end_date = query.end_date or datetime.now(UTC).date()
        start_date = query.start_date or end_date - timedelta(
            days=DEFAULT_LOOKBACK_DAYS
        )
        fixings = await get_fixings(
            query.index, start_date, end_date, use_cache=query.use_cache
        )

        if not fixings:
            raise EmptyDataError(
                f"No {query.index} fixings were published between"
                f" {start_date} and {end_date}."
            )

        return fixings

    @staticmethod
    def transform_data(
        query: CftcHistoricalFixingsQueryParams,
        data: dict[dateType, float],
        **kwargs: Any,
    ) -> AnnotatedResult[list[CftcHistoricalFixingsData]]:
        """Order the series and summarize the window."""
        from openbb_cftc.utils.fixings import fixing_basis

        rows = build_series(data)
        rates = [row["rate"] for row in rows]
        source, path = FIXING_SOURCES[query.index]

        return AnnotatedResult(
            result=[CftcHistoricalFixingsData.model_validate(r) for r in rows],
            metadata={
                "index": query.index,
                "source": source,
                "series": path or None,
                "basis": fixing_basis(query.index),
                "observations": len(rows),
                "start_date": rows[0]["date"].isoformat(),
                "end_date": rows[-1]["date"].isoformat(),
                "latest": rates[-1],
                "low": min(rates),
                "high": max(rates),
            },
        )
