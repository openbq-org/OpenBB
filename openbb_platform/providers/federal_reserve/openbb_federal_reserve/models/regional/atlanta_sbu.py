"""Federal Reserve Bank of Atlanta Survey of Business Uncertainty Model."""

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
    "/research-and-data/surveys/business-uncertainty/sbu-data.xlsx"
)

_TABLES: dict[str, tuple[str, bool]] = {
    "index_smoothed": ("Index Values (smoothed)", False),
    "index_unsmoothed": ("Index Values (unsmoothed) ", False),
    "cost_price_smoothed": ("Cost & Price Index (Smoothed)", False),
    "cost_price_unsmoothed": ("Cost & Price Index (unsmoothed)", False),
    "reallocation": ("Reallocation measures", False),
    "expected_sales_distribution": ("Distrib. of Exp. Sales Growth", False),
    "realized_growth": ("Realized Growth Rate Indexes", False),
    "realized_sales_distribution": ("Distrib. of Realized Sales Gr. ", False),
    "historical_research": ("Historical Data for Research", False),
    "discontinued": ("Dicontinued Series", True),
}


class FederalReserveAtlantaBusinessUncertaintyQueryParams(QueryParams):
    """Atlanta Fed Survey of Business Uncertainty Query Parameters."""

    __json_schema_extra__ = {
        "table": {
            "x-widget_config": {
                "options": [
                    {"label": sheet.strip(), "value": code}
                    for code, (sheet, _) in _TABLES.items()
                ]
            }
        },
    }

    table: Literal[
        "index_smoothed",
        "index_unsmoothed",
        "cost_price_smoothed",
        "cost_price_unsmoothed",
        "reallocation",
        "expected_sales_distribution",
        "realized_growth",
        "realized_sales_distribution",
        "historical_research",
        "discontinued",
    ] = Field(
        default="index_smoothed",
        description="The Survey of Business Uncertainty table to return.",
    )
    start_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("start_date", "")
    )
    end_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("end_date", "")
    )


class FederalReserveAtlantaBusinessUncertaintyData(Data):
    """Atlanta Fed Survey of Business Uncertainty Data."""

    date: dateType = Field(description="The survey month.")


class FederalReserveAtlantaBusinessUncertaintyFetcher(
    Fetcher[
        FederalReserveAtlantaBusinessUncertaintyQueryParams,
        list[FederalReserveAtlantaBusinessUncertaintyData],
    ]
):
    """Atlanta Fed Survey of Business Uncertainty Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FederalReserveAtlantaBusinessUncertaintyQueryParams:
        """Transform the query params."""
        return FederalReserveAtlantaBusinessUncertaintyQueryParams(**params)

    @staticmethod
    def extract_data(
        query: FederalReserveAtlantaBusinessUncertaintyQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Download the SBU workbook from the Atlanta Fed."""
        from openbb_core.provider.utils.helpers import make_request

        from openbb_federal_reserve.utils.cache import (
            cached,
            seconds_until_next_release,
        )

        def _producer() -> bytes:
            """Fetch the raw SBU workbook bytes."""
            response = make_request(URL)
            response.raise_for_status()
            return response.content

        content = cached(
            "atlanta_sbu", lambda: seconds_until_next_release("monthly"), _producer
        )
        if not content:
            raise EmptyDataError("The request was returned empty.")
        return [{"_raw": content}]

    @staticmethod
    def transform_data(
        query: FederalReserveAtlantaBusinessUncertaintyQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FederalReserveAtlantaBusinessUncertaintyData]:
        """Pivot the selected table to wide ``date`` + measure-column rows."""
        from openbb_federal_reserve.utils.workbook import melt_sheet, pivot_wide

        sheet, group_header = _TABLES[query.table]
        records = pivot_wide(
            melt_sheet(
                data[0]["_raw"],
                sheet,
                group_header=group_header,
                start_date=query.start_date,
                end_date=query.end_date,
            )
        )
        return [
            FederalReserveAtlantaBusinessUncertaintyData.model_validate(record)
            for record in records
        ]
