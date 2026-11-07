"""Federal Reserve Bank of Dallas Banking Conditions Survey Model."""

from datetime import date as dateType
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

URL = (
    "https://www.dallasfed.org/~/media/Documents/research"
    "/surveys/bcs/documents/BCS_Index_Results.xls"
)


class FederalReserveDallasBankingQueryParams(QueryParams):
    """Dallas Fed Banking Conditions Survey Query Parameters."""

    start_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("start_date", "")
    )
    end_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("end_date", "")
    )


class FederalReserveDallasBankingData(Data):
    """Dallas Fed Banking Conditions Survey Data."""

    date: dateType = Field(description="The survey period end date.")


class FederalReserveDallasBankingFetcher(
    Fetcher[
        FederalReserveDallasBankingQueryParams,
        list[FederalReserveDallasBankingData],
    ]
):
    """Dallas Fed Banking Conditions Survey Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FederalReserveDallasBankingQueryParams:
        """Transform the query params."""
        return FederalReserveDallasBankingQueryParams(**params)

    @staticmethod
    def extract_data(
        query: FederalReserveDallasBankingQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Download the Banking Conditions Survey workbook."""
        from openbb_core.provider.utils.helpers import make_request

        from openbb_federal_reserve.utils.cache import (
            cached,
            seconds_until_next_release,
        )

        def _producer() -> bytes:
            """Fetch the raw survey workbook bytes."""
            response = make_request(URL)
            response.raise_for_status()
            return response.content

        content = cached(
            "dallas_bcs", lambda: seconds_until_next_release("monthly"), _producer
        )
        if not content:
            raise EmptyDataError("The request was returned empty.")
        return [{"_raw": content}]

    @staticmethod
    def transform_data(
        query: FederalReserveDallasBankingQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FederalReserveDallasBankingData]:
        """Decode every index, then pivot indicator-horizon to wide rows."""
        from io import BytesIO

        from pandas import ExcelFile

        from openbb_federal_reserve.utils.dallas_survey import (
            BANKING_INDICATORS,
            parse_keyed_survey,
        )
        from openbb_federal_reserve.utils.workbook import pivot_wide

        # The workbook's sheet was renamed upstream: old name, new name, then the only sheet.
        sheets = ExcelFile(BytesIO(data[0]["_raw"])).sheet_names
        sheet = next(
            (s for s in ("CSV_BCS_Index_Results", "BCS_Index_Results") if s in sheets),
            sheets[0] if len(sheets) == 1 else "CSV_BCS_Index_Results",
        )
        records = parse_keyed_survey(
            data[0]["_raw"],
            sheet,
            BANKING_INDICATORS,
            start_date=query.start_date,
            end_date=query.end_date,
        )
        for record in records:
            record["column"] = f"{record['indicator']} ({record['horizon']})"
        rows = pivot_wide(records, index="date", column="column", value="value")
        return [
            FederalReserveDallasBankingData.model_validate(record) for record in rows
        ]
