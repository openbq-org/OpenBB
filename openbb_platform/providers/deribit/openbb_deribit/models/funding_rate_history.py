"""Deribit Funding Rate History Model."""

from datetime import UTC, datetime
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator

from openbb_deribit.utils.constants import (
    PERPETUAL_CHOICES_ENDPOINT,
    SYMBOL_STYLE,
)


class DeribitFundingRateHistoryQueryParams(QueryParams):
    """Deribit Funding Rate History Query.

    Source: https://docs.deribit.com/api-reference/market-data/public-get_funding_rate_history
    """

    __json_schema_extra__ = {
        "symbol": {
            "multiple_items_allowed": True,
            "x-widget_config": {
                "type": "endpoint",
                "optionsEndpoint": PERPETUAL_CHOICES_ENDPOINT,
                "style": SYMBOL_STYLE,
            },
        }
    }

    symbol: str = Field(
        default="BTC-PERPETUAL",
        description="One or more perpetual instrument names. A perpetual can also"
        + " be given by its shortened root, such as 'SOLUSDC'.",
    )
    start_date: Any | None = Field(
        default=None, description="Return rates from this date onwards."
    )
    end_date: Any | None = Field(
        default=None, description="Return rates up to this date."
    )


class DeribitFundingRateHistoryData(Data):
    """Deribit Funding Rate History Data."""

    __alias_dict__ = {"date": "timestamp"}

    date: datetime = Field(
        description="The hour the rate applied to.",
        json_schema_extra={"x-widget_config": {"chartDataType": "category"}},
    )
    symbol: str = Field(
        description="The name of the instrument.",
        json_schema_extra={"x-widget_config": {"chartDataType": "excluded"}},
    )
    interest_1h: float | None = Field(
        default=None,
        description="The funding rate over the hour.",
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-widget_config": {
                "headerName": "Interest 1H",
                "chartDataType": "excluded",
            },
        },
    )
    interest_8h: float | None = Field(
        default=None,
        description="The funding rate over the trailing eight hours.",
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-widget_config": {
                "headerName": "Interest 8H",
                "chartDataType": "series",
            },
        },
    )
    index_price: float | None = Field(
        default=None,
        description="The level of the index at the end of the hour.",
        json_schema_extra={
            "x-unit_measurement": "currency",
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    prev_index_price: float | None = Field(
        default=None,
        description="The level of the index at the start of the hour.",
        json_schema_extra={
            "x-unit_measurement": "currency",
            "x-widget_config": {
                "headerName": "Previous Index Price",
                "chartDataType": "excluded",
            },
        },
    )

    @field_validator("date", mode="before", check_fields=False)
    @classmethod
    def validate_date(cls, v):
        """Read the timestamp as a datetime."""
        from openbb_deribit.utils.helpers import from_timestamp

        return from_timestamp(v)

    @field_validator(
        "interest_1h",
        "interest_8h",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def as_percent(cls, v):
        """Return a rate the exchange sends as a fraction in percent units."""
        return v * 100 if v is not None else None


class DeribitFundingRateHistoryFetcher(
    Fetcher[DeribitFundingRateHistoryQueryParams, list[DeribitFundingRateHistoryData]]
):
    """Transform the query, extract and transform the data from the Deribit endpoint."""

    require_credentials = False

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> DeribitFundingRateHistoryQueryParams:
        """Transform the query."""
        return DeribitFundingRateHistoryQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: DeribitFundingRateHistoryQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Return the raw data from the Deribit endpoint.

        Raises
        ------
        EmptyDataError
            If none of the instruments paid funding over the span.
        """
        from datetime import (
            datetime as dt,
            timedelta,
        )

        from openbb_deribit.utils.client import gather
        from openbb_deribit.utils.helpers import get_perpetual_symbols, to_timestamp

        now = dt.now(UTC)
        start = (
            to_timestamp(query.start_date)
            if query.start_date
            else to_timestamp(now - timedelta(days=7))
        )
        end = to_timestamp(query.end_date) if query.end_date else to_timestamp(now)
        symbols = [s.strip().upper() for s in query.symbol.split(",") if s.strip()]
        perpetuals = await get_perpetual_symbols()
        resolved = [perpetuals.get(symbol, symbol) for symbol in symbols]
        results = await gather(
            [
                (
                    "get_funding_rate_history",
                    {
                        "instrument_name": symbol,
                        "start_timestamp": start,
                        "end_timestamp": end,
                    },
                )
                for symbol in resolved
            ]
        )
        data = [
            {"symbol": symbol, **record}
            for symbol, result in zip(resolved, results)
            if isinstance(result, list)
            for record in result
        ]

        if not data:
            raise EmptyDataError(
                f"Deribit published no funding over the span for {', '.join(resolved)}."
            )

        return data

    @staticmethod
    def transform_data(
        query: DeribitFundingRateHistoryQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[DeribitFundingRateHistoryData]:
        """Transform the data to the model."""
        return [
            DeribitFundingRateHistoryData.model_validate(record)
            for record in sorted(
                data, key=lambda d: (d.get("timestamp") or 0, d["symbol"])
            )
        ]
