"""Federal Reserve Bank of Minneapolis Business Conditions Survey Model."""

from datetime import date as dateType
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

BASE_URL = (
    "https://www.minneapolisfed.org/~/media/Assets/Pages/regional-economic-indicators"
)
PRICES_URL = f"{BASE_URL}/business_conditions_prices.csv"
PERFORMANCE_URL = f"{BASE_URL}/business_conditions_performance.csv"

_PRICES_MAP = {
    "Benefits": "benefits",
    "Input prices": "input_prices",
    "Sales prices": "sales_prices",
    "Wages": "wages",
}
_PERFORMANCE_MAP = {
    "Investment": "investment",
    "Headcount": "headcount",
    "Hiring": "hiring",
    "Inventories": "inventories",
    "Profits": "profits",
    "Sales": "sales",
}


class FederalReserveMinneapolisBusinessConditionsQueryParams(QueryParams):
    """Minneapolis Fed Business Conditions Survey Query Parameters."""

    start_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("start_date", "")
    )
    end_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("end_date", "")
    )


class FederalReserveMinneapolisBusinessConditionsData(Data):
    """Minneapolis Fed Business Conditions Survey Data."""

    date: dateType = Field(description="The survey month.")
    is_flash: bool = Field(
        default=False,
        description="Whether the reading is a flash (forecast) estimate rather than a"
        " final survey result.",
    )
    benefits: float | None = Field(
        default=None, description="Diffusion index for benefits costs."
    )
    input_prices: float | None = Field(
        default=None, description="Diffusion index for input prices."
    )
    sales_prices: float | None = Field(
        default=None, description="Diffusion index for sales prices."
    )
    wages: float | None = Field(default=None, description="Diffusion index for wages.")
    investment: float | None = Field(
        default=None, description="Diffusion index for capital investment."
    )
    headcount: float | None = Field(
        default=None, description="Diffusion index for headcount."
    )
    hiring: float | None = Field(
        default=None, description="Diffusion index for hiring difficulty."
    )
    inventories: float | None = Field(
        default=None, description="Diffusion index for inventories."
    )
    profits: float | None = Field(
        default=None, description="Diffusion index for profits."
    )
    sales: float | None = Field(
        default=None, description="Diffusion index for sales revenue."
    )


class FederalReserveMinneapolisBusinessConditionsFetcher(
    Fetcher[
        FederalReserveMinneapolisBusinessConditionsQueryParams,
        list[FederalReserveMinneapolisBusinessConditionsData],
    ]
):
    """Minneapolis Fed Business Conditions Survey Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FederalReserveMinneapolisBusinessConditionsQueryParams:
        """Transform the query params."""
        return FederalReserveMinneapolisBusinessConditionsQueryParams(**params)

    @staticmethod
    def extract_data(
        query: FederalReserveMinneapolisBusinessConditionsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Download the prices and performance survey CSVs from the Minneapolis Fed."""
        from openbb_core.provider.utils.helpers import make_request

        from openbb_federal_reserve.utils.cache import (
            cached,
            seconds_until_next_release,
        )

        def _producer(url: str) -> str:
            """Fetch the raw survey CSV text for a given URL."""
            response = make_request(url)
            response.raise_for_status()
            return response.text

        prices = cached(
            "minneapolis_business_conditions_prices",
            lambda: seconds_until_next_release("monthly"),
            lambda: _producer(PRICES_URL),
        )
        performance = cached(
            "minneapolis_business_conditions_performance",
            lambda: seconds_until_next_release("monthly"),
            lambda: _producer(PERFORMANCE_URL),
        )
        if not prices or not performance:
            raise EmptyDataError("The request was returned empty.")
        return [{"_prices": prices, "_performance": performance}]

    @staticmethod
    def transform_data(
        query: FederalReserveMinneapolisBusinessConditionsQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FederalReserveMinneapolisBusinessConditionsData]:
        """Parse and merge the two survey CSVs and apply the date filters."""
        from io import StringIO

        from pandas import isna, read_csv, to_datetime

        prices = read_csv(StringIO(data[0]["_prices"])).rename(columns=_PRICES_MAP)
        # The bank has published the period column as "Date" and as "month".
        prices = prices.rename(columns={prices.columns[0]: "month"})
        prices["is_flash"] = prices["month"].str.contains(r"\(F\)", regex=True)
        prices["date"] = prices["month"].str.replace(r"\s*\(F\)\s*$", "", regex=True)
        prices["date"] = to_datetime(prices["date"], format="%b %Y").dt.date
        prices = prices.drop(columns=["month"])

        performance = read_csv(StringIO(data[0]["_performance"])).rename(
            columns=_PERFORMANCE_MAP
        )
        performance = performance.rename(columns={performance.columns[0]: "month"})
        performance["is_flash"] = performance["month"].str.contains(
            r"\(F\)", regex=True
        )
        performance["date"] = performance["month"].str.replace(
            r"\s*\(F\)\s*$", "", regex=True
        )
        performance["date"] = to_datetime(performance["date"], format="%b %Y").dt.date
        performance = performance.drop(columns=["month"])

        frame = prices.merge(
            performance, on="date", how="outer", suffixes=("_prices", "_performance")
        )
        frame["is_flash"] = (
            frame[["is_flash_prices", "is_flash_performance"]].fillna(False).any(axis=1)
        )
        frame = frame.drop(columns=["is_flash_prices", "is_flash_performance"])

        if query.start_date:
            frame = frame[frame["date"] >= query.start_date]
        if query.end_date:
            frame = frame[frame["date"] <= query.end_date]

        return [
            FederalReserveMinneapolisBusinessConditionsData.model_validate(
                {
                    k: (None if isinstance(v, float) and isna(v) else v)
                    for k, v in row.items()
                }
            )
            for row in frame.sort_values("date").to_dict(orient="records")
        ]
