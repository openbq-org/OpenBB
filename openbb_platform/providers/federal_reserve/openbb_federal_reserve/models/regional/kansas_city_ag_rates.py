"""Federal Reserve Bank of Kansas City Agricultural Interest Rates Model."""

from datetime import date as dateType
from typing import Any, Literal

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

_FILES = {
    "variable": 7622,
    "fixed": 7621,
}

_SHEETS = {
    "operating": "Operating",
    "intermediate": "Intermediate",
    "real_estate": "Real Estate",
}


class FederalReserveKansasCityAgRatesQueryParams(QueryParams):
    """Kansas City Fed Agricultural Interest Rates Query Parameters."""

    __json_schema_extra__ = {
        "rate_type": {
            "x-widget_config": {
                "options": [
                    {"label": "Variable", "value": "variable"},
                    {"label": "Fixed", "value": "fixed"},
                ]
            }
        },
        "loan_type": {
            "x-widget_config": {
                "options": [
                    {"label": "Operating", "value": "operating"},
                    {"label": "Intermediate", "value": "intermediate"},
                    {"label": "Real Estate", "value": "real_estate"},
                ]
            }
        },
    }

    rate_type: Literal["variable", "fixed"] = Field(
        default="variable",
        description="Variable or fixed interest rates.",
    )
    loan_type: Literal["operating", "intermediate", "real_estate"] = Field(
        default="operating",
        description="The loan type: operating, intermediate, or real estate.",
    )
    start_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("start_date", "")
    )
    end_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("end_date", "")
    )


class FederalReserveKansasCityAgRatesData(Data):
    """Kansas City Fed Agricultural Interest Rates Data."""

    date: dateType = Field(description="The survey quarter-end date.")


class FederalReserveKansasCityAgRatesFetcher(
    Fetcher[
        FederalReserveKansasCityAgRatesQueryParams,
        list[FederalReserveKansasCityAgRatesData],
    ]
):
    """Kansas City Fed Agricultural Interest Rates Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FederalReserveKansasCityAgRatesQueryParams:
        """Transform the query params."""
        return FederalReserveKansasCityAgRatesQueryParams(**params)

    @staticmethod
    def extract_data(
        query: FederalReserveKansasCityAgRatesQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Download the requested interest-rate workbook from the Kansas City Fed."""
        from openbb_federal_reserve.utils.cache import (
            cached,
            seconds_until_next_release,
        )
        from openbb_federal_reserve.utils.kansas_city import fetch_kansas_city
        from openbb_federal_reserve.utils.kansas_city_ag import resolve_kc_ag_url

        document_id = _FILES[query.rate_type]
        content = cached(
            ("kansas_city_ag_rates", query.rate_type),
            lambda: seconds_until_next_release("quarterly"),
            lambda: fetch_kansas_city(resolve_kc_ag_url(document_id)),
        )
        if not content:
            raise EmptyDataError("The request was returned empty.")
        return [{"_raw": content}]

    @staticmethod
    def transform_data(
        query: FederalReserveKansasCityAgRatesQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FederalReserveKansasCityAgRatesData]:
        """Melt the loan type's rates by state, then pivot each to a wide column."""
        from openbb_federal_reserve.utils.kansas_city_ag import parse_kc_quarterly
        from openbb_federal_reserve.utils.workbook import pivot_wide

        records = parse_kc_quarterly(
            data[0]["_raw"],
            _SHEETS[query.loan_type],
            start_date=query.start_date,
            end_date=query.end_date,
        )
        rows = pivot_wide(records, index="date", column="series", value="value")
        return [
            FederalReserveKansasCityAgRatesData.model_validate(record)
            for record in rows
        ]
