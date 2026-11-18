"""Federal Reserve Bank of Dallas Texas Service Sector Outlook Survey Model."""

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
    "/surveys/tssos/documents/tssos_index.xls"
)


class FederalReserveDallasServiceSectorQueryParams(QueryParams):
    """Dallas Fed Texas Service Sector Outlook Survey Query Parameters."""

    start_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("start_date", "")
    )
    end_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("end_date", "")
    )


class FederalReserveDallasServiceSectorData(Data):
    """Dallas Fed Texas Service Sector Outlook Survey Data."""

    date: dateType = Field(description="The survey month.")


class FederalReserveDallasServiceSectorFetcher(
    Fetcher[
        FederalReserveDallasServiceSectorQueryParams,
        list[FederalReserveDallasServiceSectorData],
    ]
):
    """Dallas Fed Texas Service Sector Outlook Survey Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FederalReserveDallasServiceSectorQueryParams:
        """Transform the query params."""
        return FederalReserveDallasServiceSectorQueryParams(**params)

    @staticmethod
    def extract_data(
        query: FederalReserveDallasServiceSectorQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Download the Texas Service Sector Outlook Survey workbook."""
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
            "dallas_tssos", lambda: seconds_until_next_release("monthly"), _producer
        )
        if not content:
            raise EmptyDataError("The request was returned empty.")
        return [{"_raw": content}]

    @staticmethod
    def transform_data(
        query: FederalReserveDallasServiceSectorQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FederalReserveDallasServiceSectorData]:
        """Decode every indicator, then pivot indicator-horizon to wide rows."""
        from io import BytesIO

        from pandas import ExcelFile

        from openbb_federal_reserve.utils.dallas_survey import (
            SERVICE_INDICATORS,
            parse_survey,
        )
        from openbb_federal_reserve.utils.workbook import pivot_wide

        # The workbook's sheet was renamed upstream: old name, new name, then the only sheet.
        sheets = ExcelFile(BytesIO(data[0]["_raw"])).sheet_names
        names = ("Index", "Sheet1")
        sheet = next(
            (s for s in names if s in sheets), sheets[0] if len(sheets) == 1 else None
        )
        if sheet is None:  # renamed again, in a workbook of several sheets
            from openbb_core.app.model.abstract.error import OpenBBError

            raise OpenBBError(
                f"The Dallas Fed workbook has no sheet named {' or '.join(names)}; it has {', '.join(sheets)}."
            )
        records = parse_survey(
            data[0]["_raw"],
            sheet,
            SERVICE_INDICATORS,
            date_format="%b-%y",
            start_date=query.start_date,
            end_date=query.end_date,
        )
        for record in records:
            record["column"] = f"{record['indicator']} ({record['horizon']})"
        rows = pivot_wide(records, index="date", column="column", value="value")
        return [
            FederalReserveDallasServiceSectorData.model_validate(record)
            for record in rows
        ]
