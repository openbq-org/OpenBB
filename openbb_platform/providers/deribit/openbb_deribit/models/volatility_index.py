"""Deribit Volatility Index Model."""

from datetime import UTC, datetime
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator

from openbb_deribit.utils.constants import (
    VOLATILITY_INDEX_CURRENCIES,
    VolatilityResolutions,
)


class DeribitVolatilityIndexQueryParams(QueryParams):
    """Deribit Volatility Index Query.

    Deribit computes DVOL for BTC and ETH only. Asking for it on a pegged
    currency returns an empty series, so none are offered.

    Source: https://docs.deribit.com/api-reference/market-data/public-get_volatility_index_data
    """

    __json_schema_extra__ = {
        "currency": {
            "multiple_items_allowed": True,
            "x-widget_config": {
                "options": [
                    {"label": name, "value": name}
                    for name in VOLATILITY_INDEX_CURRENCIES
                ]
            },
        }
    }

    currency: str = Field(
        default="BTC", description="The currency whose volatility index to read."
    )

    @field_validator("currency", mode="before")
    @classmethod
    def _listed_currencies(cls, value):
        """Accept one currency or several, and refuse any the exchange omits.

        Raises
        ------
        ValueError
            If a currency the exchange does not publish this for is asked for.
        """
        chosen = [
            item.strip().upper() for item in str(value).split(",") if item.strip()
        ]
        unlisted = [item for item in chosen if item not in VOLATILITY_INDEX_CURRENCIES]

        if unlisted:
            raise ValueError(
                f"Deribit publishes no volatility index for {unlisted}."
                f" It publishes {list(VOLATILITY_INDEX_CURRENCIES)}."
            )

        return ",".join(chosen)

    start_date: Any | None = Field(
        default=None, description="Return candles from this date onwards."
    )
    end_date: Any | None = Field(
        default=None, description="Return candles up to this date."
    )
    interval: VolatilityResolutions = Field(
        default="1d", description=QUERY_DESCRIPTIONS.get("interval", "")
    )


class DeribitVolatilityIndexData(Data):
    """Deribit Volatility Index Data."""

    date: datetime = Field(
        description="When the candle closed.",
        json_schema_extra={"x-widget_config": {"chartDataType": "category"}},
    )
    currency: str = Field(
        description="The currency the index belongs to.",
        json_schema_extra={"x-widget_config": {"chartDataType": "excluded"}},
    )
    open: float = Field(
        description="The level the candle opened at.",
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    high: float = Field(
        description="The highest level of the candle.",
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    low: float = Field(
        description="The lowest level of the candle.",
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    close: float = Field(
        description="The level the candle closed at.",
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-widget_config": {"chartDataType": "series"},
        },
    )

    @field_validator("date", mode="before", check_fields=False)
    @classmethod
    def validate_date(cls, v):
        """Read the timestamp as a datetime."""
        from openbb_deribit.utils.helpers import from_timestamp

        return from_timestamp(v)


class DeribitVolatilityIndexFetcher(
    Fetcher[DeribitVolatilityIndexQueryParams, list[DeribitVolatilityIndexData]]
):
    """Transform the query, extract and transform the data from the Deribit endpoint."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> DeribitVolatilityIndexQueryParams:
        """Transform the query."""
        return DeribitVolatilityIndexQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: DeribitVolatilityIndexQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Return the raw data from the Deribit endpoint.

        Raises
        ------
        EmptyDataError
            If the index published no candles over the span.
        """
        from datetime import (
            datetime as dt,
            timedelta,
        )

        from openbb_deribit.utils.client import gather
        from openbb_deribit.utils.constants import VOLATILITY_RESOLUTION_MAP
        from openbb_deribit.utils.helpers import to_timestamp

        now = dt.now(UTC)
        start = (
            to_timestamp(query.start_date)
            if query.start_date
            else to_timestamp(now - timedelta(days=30))
        )
        end = to_timestamp(query.end_date) if query.end_date else to_timestamp(now)
        currencies = [c.strip().upper() for c in query.currency.split(",") if c.strip()]
        results = await gather(
            [
                (
                    "get_volatility_index_data",
                    {
                        "currency": currency,
                        "start_timestamp": start,
                        "end_timestamp": end,
                        "resolution": VOLATILITY_RESOLUTION_MAP[query.interval],
                    },
                )
                for currency in currencies
            ]
        )
        data = [
            {
                "date": candle[0],
                "currency": currency,
                "open": candle[1],
                "high": candle[2],
                "low": candle[3],
                "close": candle[4],
            }
            for currency, result in zip(currencies, results)
            if isinstance(result, dict)
            for candle in result.get("data") or []
        ]

        if not data:
            raise EmptyDataError(
                f"Deribit published no volatility index candles for"
                f" {', '.join(currencies)} over the span."
            )

        return data

    @staticmethod
    def transform_data(
        query: DeribitVolatilityIndexQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[DeribitVolatilityIndexData]:
        """Transform the data to the model."""
        return [
            DeribitVolatilityIndexData.model_validate(record)
            for record in sorted(data, key=lambda d: (d["date"], d["currency"]))
        ]
