"""FRED Balance Of Payments Model."""

from datetime import date as dateType
from typing import Any

from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.balance_of_payments import (
    BalanceOfPaymentsQueryParams,
    BP6BopUsdData,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator

from openbb_fred.models.series import (
    FredSeriesFetcher,
    FredSeriesQueryParams,
)
from openbb_fred.utils.fred_helpers import (
    BOP_COUNTRIES,
    BOP_COUNTRY_CHOICES,
    get_bop_series,
)
from openbb_fred.utils.query import UseCacheQueryParams

PERCENT_COLUMN: dict[str, Any] = {"x-unit_measurement": "percent"}


class FredBalanceOfPaymentsQueryParams(
    UseCacheQueryParams, BalanceOfPaymentsQueryParams
):
    """FRED Balance Of Payments Query Parameters."""

    __json_schema_extra__ = {
        "country": {
            "multiple_items_allowed": False,
            "choices": list(BOP_COUNTRIES),
        }
    }

    country: BOP_COUNTRY_CHOICES = Field(
        default="united_states",
        description=QUERY_DESCRIPTIONS.get("country", "")
        + " Enter as a 3-letter ISO country code, default is USA.",
    )
    start_date: dateType | None = Field(
        default=None,
        description=QUERY_DESCRIPTIONS.get("start_date", ""),
    )
    end_date: dateType | None = Field(
        default=None,
        description=QUERY_DESCRIPTIONS.get("end_date", ""),
    )


class FredBalanceOfPaymentsData(BP6BopUsdData):
    """FRED Balance Of Payments Data."""

    __alias_dict__ = {"period": "date"}

    balance_percent_of_gdp: float | None = Field(
        default=None,
        description="Current Account Balance as Percent of GDP",
        json_schema_extra=PERCENT_COLUMN,
    )
    credits_services_percent_of_goods_and_services: float | None = Field(
        default=None,
        description="Current Account Credits Services as Percent of Goods and Services",
        json_schema_extra=PERCENT_COLUMN,
    )
    credits_services_percent_of_current_account: float | None = Field(
        default=None,
        description="Current Account Credits Services as Percent of Current Account",
        json_schema_extra=PERCENT_COLUMN,
    )
    debits_services_percent_of_goods_and_services: float | None = Field(
        default=None,
        description="Current Account Debits Services as Percent of Goods and Services",
        json_schema_extra=PERCENT_COLUMN,
    )
    debits_services_percent_of_current_account: float | None = Field(
        default=None,
        description="Current Account Debits Services as Percent of Current Account",
        json_schema_extra=PERCENT_COLUMN,
    )

    @field_validator(
        "balance_percent_of_gdp",
        "credits_services_percent_of_goods_and_services",
        "credits_services_percent_of_current_account",
        "debits_services_percent_of_goods_and_services",
        "debits_services_percent_of_current_account",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def normalize_percent(cls, v):
        """Normalize the percent value."""
        return None if v is None or v == "" else float(v)


def _series(query: "FredBalanceOfPaymentsQueryParams") -> dict:
    """Return the series ids the country's report is built from."""
    return get_bop_series(BOP_COUNTRIES.get(query.country or "", "USA"))


class FredBalanceOfPaymentsFetcher(
    Fetcher[FredBalanceOfPaymentsQueryParams, list[FredBalanceOfPaymentsData]]
):
    """FRED Balance Of Payments Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FredBalanceOfPaymentsQueryParams:
        """Transform query."""
        return FredBalanceOfPaymentsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FredBalanceOfPaymentsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Extract data."""
        fred_fetcher = FredSeriesFetcher()
        query_dict = query.model_dump(exclude_none=True)
        query_dict["symbol"] = ",".join(_series(query).values())
        fred_query = FredSeriesQueryParams(**query_dict)

        return await fred_fetcher.aextract_data(fred_query, credentials)

    @staticmethod
    def transform_data(
        query: FredBalanceOfPaymentsQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> AnnotatedResult[list[FredBalanceOfPaymentsData]]:
        """Transform data.

        Raises
        ------
        EmptyDataError
            If the country publishes no observations.
        """
        from pandas import DataFrame

        from openbb_fred.utils.api import unwrap_series

        if not data:
            raise EmptyDataError(f"No data was found for, {query.country}.")

        fred_fetcher = FredSeriesFetcher()
        series_ids = _series(query)
        query_dict = query.model_dump(exclude_none=True)
        query_dict["symbol"] = ",".join(series_ids.values())
        fred_query = FredSeriesQueryParams(**query_dict)
        rows, metadata = unwrap_series(fred_fetcher.transform_data(fred_query, data))
        col_map = {v: k for k, v in series_ids.items()}
        df = (
            DataFrame([d.model_dump() for d in rows])
            .set_index("date")
            .sort_index(ascending=False)
        )
        df = df.rename(columns=col_map)
        out = df.reset_index()
        records = out.astype(object).where(out.notna(), None).to_dict("records")

        return AnnotatedResult(
            result=[FredBalanceOfPaymentsData.model_validate(r) for r in records],
            metadata=metadata,
        )
