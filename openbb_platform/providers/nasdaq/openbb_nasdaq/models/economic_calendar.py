"""Nasdaq Economic Calendar Model."""

from typing import Any

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.economic_calendar import (
    EconomicCalendarData,
    EconomicCalendarQueryParams,
)
from openbb_core.provider.utils.country_utils import Country
from pydantic import Field, field_validator


class NasdaqEconomicCalendarQueryParams(EconomicCalendarQueryParams):
    """Nasdaq Economic Calendar Query.

    Source: https://www.nasdaq.com/market-activity/economic-calendar
    """

    __json_schema_extra__ = {
        "country": {
            "multiple_items_allowed": True,
            "choices": None,
        }
    }

    country: str | None = Field(
        default=None,
        description="Country of the event. Accepts country names, "
        "ISO 3166-1 alpha-2/alpha-3 codes. Multiple comma-separated values allowed.",
    )

    @field_validator("country", mode="before", check_fields=False)
    @classmethod
    def validate_country(cls, c: str):
        """Validate and normalize country input."""
        if c is None:
            return c
        results = []
        for item in c.split(","):
            stripped = item.strip()
            # Try to convert via Country type
            try:
                country = Country(stripped)
                results.append(country.name.lower().replace(" ", "_"))
            except ValueError:
                # Keep original format (lowercase snake_case)
                results.append(stripped.lower().replace(" ", "_"))
        return ",".join(results)


class NasdaqEconomicCalendarData(EconomicCalendarData):
    """Nasdaq Economic Calendar Data."""

    __alias_dict__ = {
        "event": "eventName",
    }
    description: str | None = Field(default=None, description="Event description.")

    @field_validator(
        "actual", "previous", "consensus", mode="before", check_fields=False
    )
    @classmethod
    def clean_fields(cls, v: str):
        """Replace non-breaking space HTML entity."""
        return v.replace("&nbsp;", "-")

    @field_validator("description", mode="before", check_fields=False)
    @classmethod
    def clean_html(cls, v: str):
        """Format HTML entities to normal."""
        import html

        from openbb_nasdaq.utils.helpers import remove_html_tags

        if v:
            v = (
                html.unescape(v)
                .replace("\r\n\r\n", " ")
                .replace("\r\n", " ")
                .replace("''", "'")
            )
            v = remove_html_tags(v)
        return v if v else None


class NasdaqEconomicCalendarFetcher(
    Fetcher[
        NasdaqEconomicCalendarQueryParams,
        list[NasdaqEconomicCalendarData],
    ]
):
    """Transform the query, extract and transform the data from the Nasdaq endpoints."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> NasdaqEconomicCalendarQueryParams:
        """Transform the query params."""
        from datetime import datetime, timedelta

        now = datetime.today().date()
        transformed_params = params

        if params.get("start_date") is None:
            transformed_params["start_date"] = now - timedelta(days=2)

        if params.get("end_date") is None:
            transformed_params["end_date"] = now + timedelta(days=3)

        return NasdaqEconomicCalendarQueryParams(**transformed_params)

    @staticmethod
    async def aextract_data(
        query: NasdaqEconomicCalendarQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Return the raw data from the Nasdaq endpoint."""
        import asyncio

        from openbb_nasdaq.utils.helpers import date_range, get_nasdaq_data

        data: list[dict] = []
        # Weekends are kept, Nasdaq lists Friday's releases under Saturday's date.
        dates = [
            date.strftime("%Y-%m-%d")
            for date in date_range(query.start_date, query.end_date)
        ]

        async def get_calendar_data(date: str):
            """Get the calendar data for a single date."""
            response: list = []

            try:
                payload = await get_nasdaq_data(f"calendar/economicevents?date={date}")
            except OpenBBError:
                if not data:
                    raise
                return

            if payload:
                response = payload.get("rows")

            if response:
                response = [
                    {
                        **{k: v for k, v in item.items() if k != "gmt"},
                        "date": (
                            f"{date} 00:00"
                            if item.get("gmt") == "All Day"
                            else f"{date} {item.get('gmt', '')}".replace(
                                "Tentative", "00:00"
                            ).replace("24H", "00:00")
                        ),
                    }
                    for item in response
                ]
                data.extend(response)

        await asyncio.gather(*[get_calendar_data(date) for date in dates])

        if not data:
            raise OpenBBError(
                "There was an error with the request and it was returned empty."
            )

        if query.country:
            country = (
                query.country.split(",") if "," in query.country else query.country
            )
            country = [country] if isinstance(country, str) else country

            return [
                d
                for d in data
                if d.get("country", "").lower().replace(" ", "_") in country
            ]

        return data

    @staticmethod
    def transform_data(
        query: NasdaqEconomicCalendarQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[NasdaqEconomicCalendarData]:
        """Return the transformed data."""
        return [NasdaqEconomicCalendarData.model_validate(d) for d in data]
