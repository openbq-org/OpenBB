"""Federal Reserve Bank of Atlanta Wage Growth Tracker Model."""

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
    "/research-and-data/data/wage-growth-tracker/wage-growth-data.xlsx"
)

_CUTS: dict[str, str] = {
    "overall": "data_overall",
    "race": "Race",
    "education": "Education",
    "age": "Age",
    "sex": "Sex",
    "occupation": "Occupation",
    "industry": "Industry",
    "census_division": "Census Divisions",
    "work_status": "Full-Time or Part-Time",
    "job_switcher": "Job Switcher",
    "metro": "MSA or non-MSA",
    "wage_quartile": "Average Wage Quartile",
    "paid_hourly": "Paid Hourly",
    "non_smoothed": "data_chart1",
    "distribution": "data_chart2",
    "zero_changes": "data_chart3",
    "since_1983": "WGT_1983",
    "weighted": "Overall 12ma",
    "alternative": "Alternative WGT",
}

_DROP_SERIES = frozenset({"Recession"})


class FederalReserveAtlantaWageGrowthQueryParams(QueryParams):
    """Atlanta Fed Wage Growth Tracker Query Parameters."""

    __json_schema_extra__ = {
        "cut": {
            "x-widget_config": {
                "options": [
                    {"label": "Overall", "value": "overall"},
                    {"label": "Race", "value": "race"},
                    {"label": "Education", "value": "education"},
                    {"label": "Age", "value": "age"},
                    {"label": "Sex", "value": "sex"},
                    {"label": "Occupation", "value": "occupation"},
                    {"label": "Industry", "value": "industry"},
                    {"label": "Census Division", "value": "census_division"},
                    {"label": "Full-Time or Part-Time", "value": "work_status"},
                    {"label": "Job Switcher", "value": "job_switcher"},
                    {"label": "MSA or non-MSA", "value": "metro"},
                    {"label": "Average Wage Quartile", "value": "wage_quartile"},
                    {"label": "Paid Hourly", "value": "paid_hourly"},
                    {"label": "Non-Smoothed", "value": "non_smoothed"},
                    {"label": "Distribution", "value": "distribution"},
                    {"label": "Zero Changes", "value": "zero_changes"},
                    {"label": "Since 1983", "value": "since_1983"},
                    {"label": "Weighted", "value": "weighted"},
                    {"label": "Alternative", "value": "alternative"},
                ]
            }
        },
    }

    cut: Literal[
        "overall",
        "race",
        "education",
        "age",
        "sex",
        "occupation",
        "industry",
        "census_division",
        "work_status",
        "job_switcher",
        "metro",
        "wage_quartile",
        "paid_hourly",
        "non_smoothed",
        "distribution",
        "zero_changes",
        "since_1983",
        "weighted",
        "alternative",
    ] = Field(
        default="overall",
        description="The Wage Growth Tracker breakdown to return.",
    )
    start_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("start_date", "")
    )
    end_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("end_date", "")
    )


class FederalReserveAtlantaWageGrowthData(Data):
    """Atlanta Fed Wage Growth Tracker Data."""

    date: dateType = Field(description="The observation month.")


class FederalReserveAtlantaWageGrowthFetcher(
    Fetcher[
        FederalReserveAtlantaWageGrowthQueryParams,
        list[FederalReserveAtlantaWageGrowthData],
    ]
):
    """Atlanta Fed Wage Growth Tracker Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FederalReserveAtlantaWageGrowthQueryParams:
        """Transform the query params."""
        return FederalReserveAtlantaWageGrowthQueryParams(**params)

    @staticmethod
    def extract_data(
        query: FederalReserveAtlantaWageGrowthQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Download the Wage Growth Tracker workbook from the Atlanta Fed."""
        from openbb_core.provider.utils.helpers import make_request

        from openbb_federal_reserve.utils.cache import (
            cached,
            seconds_until_next_release,
        )

        def _producer() -> bytes:
            """Fetch the raw Wage Growth Tracker workbook bytes."""
            response = make_request(URL)
            response.raise_for_status()
            return response.content

        content = cached(
            "atlanta_wage_growth",
            lambda: seconds_until_next_release("monthly"),
            _producer,
        )
        if not content:
            raise EmptyDataError("The request was returned empty.")
        return [{"_raw": content}]

    @staticmethod
    def transform_data(
        query: FederalReserveAtlantaWageGrowthQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FederalReserveAtlantaWageGrowthData]:
        """Pivot the selected cut's sheet to wide ``date`` + per-category columns."""
        from openbb_federal_reserve.utils.workbook import melt_sheet, pivot_wide

        records = melt_sheet(
            data[0]["_raw"],
            _CUTS[query.cut],
            start_date=query.start_date,
            end_date=query.end_date,
        )
        kept = [
            {
                "date": record["date"],
                "category": record["series"],
                "wage_growth": record["value"],
            }
            for record in records
            if record["series"] not in _DROP_SERIES
        ]
        rows = pivot_wide(kept, index="date", column="category", value="wage_growth")
        return [
            FederalReserveAtlantaWageGrowthData.model_validate(record)
            for record in rows
        ]
