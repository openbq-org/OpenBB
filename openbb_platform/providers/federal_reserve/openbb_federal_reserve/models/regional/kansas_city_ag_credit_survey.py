"""Federal Reserve Bank of Kansas City Agricultural Credit Survey Model."""

from datetime import date as dateType
from typing import Any, Literal

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

_TABLES = {
    "land_values": (
        7623,
        "Sheet1",
    ),
    "credit_conditions": (
        7620,
        "Sheet1",
    ),
}


class FederalReserveKansasCityAgCreditSurveyQueryParams(QueryParams):
    """Kansas City Fed Agricultural Credit Survey Query Parameters."""

    __json_schema_extra__ = {
        "table": {
            "x-widget_config": {
                "options": [
                    {"label": "Land Values", "value": "land_values"},
                    {"label": "Credit Conditions", "value": "credit_conditions"},
                ]
            }
        }
    }

    table: Literal["land_values", "credit_conditions"] = Field(
        default="land_values",
        description="Farmland value changes by land class, or the diffusion indexes"
        " of farm credit conditions.",
    )
    start_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("start_date", "")
    )
    end_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("end_date", "")
    )


class FederalReserveKansasCityAgCreditSurveyData(Data):
    """Kansas City Fed Agricultural Credit Survey Data."""

    date: dateType = Field(description="The survey quarter-end date.")


class FederalReserveKansasCityAgCreditSurveyFetcher(
    Fetcher[
        FederalReserveKansasCityAgCreditSurveyQueryParams,
        list[FederalReserveKansasCityAgCreditSurveyData],
    ]
):
    """Kansas City Fed Agricultural Credit Survey Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FederalReserveKansasCityAgCreditSurveyQueryParams:
        """Transform the query params."""
        return FederalReserveKansasCityAgCreditSurveyQueryParams(**params)

    @staticmethod
    def extract_data(
        query: FederalReserveKansasCityAgCreditSurveyQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Download the requested survey workbook from the Kansas City Fed."""
        from openbb_federal_reserve.utils.cache import (
            cached,
            seconds_until_next_release,
        )
        from openbb_federal_reserve.utils.kansas_city import fetch_kansas_city
        from openbb_federal_reserve.utils.kansas_city_ag import resolve_kc_ag_url

        document_id = _TABLES[query.table][0]
        content = cached(
            ("kansas_city_ag_credit_survey", query.table),
            lambda: seconds_until_next_release("quarterly"),
            lambda: fetch_kansas_city(resolve_kc_ag_url(document_id)),
        )
        if not content:
            raise EmptyDataError("The request was returned empty.")
        return [{"_raw": content}]

    @staticmethod
    def transform_data(
        query: FederalReserveKansasCityAgCreditSurveyQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FederalReserveKansasCityAgCreditSurveyData]:
        """Melt the survey blocks, then pivot each series to a wide column."""
        from openbb_federal_reserve.utils.kansas_city_ag import parse_kc_quarterly
        from openbb_federal_reserve.utils.workbook import pivot_wide

        records = parse_kc_quarterly(
            data[0]["_raw"],
            _TABLES[query.table][1],
            start_date=query.start_date,
            end_date=query.end_date,
        )
        rows = pivot_wide(records, index="date", column="series", value="value")
        return [
            FederalReserveKansasCityAgCreditSurveyData.model_validate(record)
            for record in rows
        ]
