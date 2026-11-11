"""Federal Reserve Bank of Kansas City Ag Finance Databook Model."""

from datetime import date as dateType
from typing import Any, Literal

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

_HISTORICAL_DOCUMENT = 7228
_TABLES_DOCUMENT = 7889

_SOURCES = {
    "historical": (_HISTORICAL_DOCUMENT, None),
    "farm_debt_all_banks": (_TABLES_DOCUMENT, "A"),
    "farm_debt_ag_banks": (_TABLES_DOCUMENT, "B"),
    "ag_bank_performance": (_TABLES_DOCUMENT, "C"),
}


class FederalReserveKansasCityAgFinanceQueryParams(QueryParams):
    """Kansas City Fed Ag Finance Databook Query Parameters."""

    __json_schema_extra__ = {
        "table": {
            "x-widget_config": {
                "options": [
                    {"label": "Historical", "value": "historical"},
                    {"label": "Farm Debt All Banks", "value": "farm_debt_all_banks"},
                    {"label": "Farm Debt Ag Banks", "value": "farm_debt_ag_banks"},
                    {"label": "Ag Bank Performance", "value": "ag_bank_performance"},
                ]
            }
        }
    }

    table: Literal[
        "historical", "farm_debt_all_banks", "farm_debt_ag_banks", "ag_bank_performance"
    ] = Field(
        default="historical",
        description="The full coded historical series, or a published Databook"
        " table: farm debt at all banks, farm debt at agricultural banks, or"
        " agricultural bank performance ratios.",
    )
    start_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("start_date", "")
    )
    end_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("end_date", "")
    )


class FederalReserveKansasCityAgFinanceData(Data):
    """Kansas City Fed Ag Finance Databook Data."""

    date: dateType = Field(description="The observation quarter-end date.")


class FederalReserveKansasCityAgFinanceFetcher(
    Fetcher[
        FederalReserveKansasCityAgFinanceQueryParams,
        list[FederalReserveKansasCityAgFinanceData],
    ]
):
    """Kansas City Fed Ag Finance Databook Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FederalReserveKansasCityAgFinanceQueryParams:
        """Transform the query params."""
        return FederalReserveKansasCityAgFinanceQueryParams(**params)

    @staticmethod
    def extract_data(
        query: FederalReserveKansasCityAgFinanceQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Download the Ag Finance Databook history from the Kansas City Fed."""
        from openbb_federal_reserve.utils.cache import (
            cached,
            seconds_until_next_release,
        )
        from openbb_federal_reserve.utils.kansas_city import fetch_kansas_city
        from openbb_federal_reserve.utils.kansas_city_ag import resolve_kc_ag_url

        document_id = _SOURCES[query.table][0]
        content = cached(
            ("kansas_city_ag_finance", query.table),
            lambda: seconds_until_next_release("quarterly"),
            lambda: fetch_kansas_city(resolve_kc_ag_url(document_id)),
        )
        if not content:
            raise EmptyDataError("The request was returned empty.")
        return [{"_raw": content}]

    @staticmethod
    def transform_data(
        query: FederalReserveKansasCityAgFinanceQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FederalReserveKansasCityAgFinanceData]:
        """Melt the codes or a table, then pivot each series to a wide column."""
        from openbb_federal_reserve.utils.kansas_city_ag import (
            parse_kc_databook,
            parse_kc_quarterly,
        )
        from openbb_federal_reserve.utils.workbook import pivot_wide

        sheet = _SOURCES[query.table][1]
        if sheet is None:
            records = parse_kc_databook(
                data[0]["_raw"],
                start_date=query.start_date,
                end_date=query.end_date,
            )
        else:
            records = parse_kc_quarterly(
                data[0]["_raw"],
                sheet,
                start_date=query.start_date,
                end_date=query.end_date,
            )
        rows = pivot_wide(records, index="date", column="series", value="value")
        return [
            FederalReserveKansasCityAgFinanceData.model_validate(record)
            for record in rows
        ]
