"""Deribit Futures Curve Model."""

from datetime import (
    UTC,
    date as dateType,
)
from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.futures_curve import (
    FuturesCurveData,
    FuturesCurveQueryParams,
)
from openbb_core.provider.utils.descriptions import (
    DATA_DESCRIPTIONS,
    QUERY_DESCRIPTIONS,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator, model_validator

from openbb_deribit.utils.constants import (
    CURVE_CHOICES_ENDPOINT,
    SYMBOL_STYLE,
)


class DeribitFuturesCurveQueryParams(FuturesCurveQueryParams):
    """Deribit Futures Curve Query.

    Source: https://docs.deribit.com/api-reference/market-data/public-ticker
    """

    __json_schema_extra__ = {
        "symbol": {
            "multiple_items_allowed": False,
            "x-widget_config": {
                "type": "endpoint",
                "optionsEndpoint": CURVE_CHOICES_ENDPOINT,
                "style": SYMBOL_STYLE,
            },
        },
        "hours_ago": {"multiple_items_allowed": True},
    }

    symbol: str = Field(
        default="BTC",
        description=QUERY_DESCRIPTIONS.get("symbol", "")
        + " The underlying root, as it appears in the instrument name.",
    )
    hours_ago: str | None = Field(
        default=None,
        description="Compare the current curve against how it stood this many"
        + " hours ago.",
    )

    @field_validator("hours_ago", mode="before", check_fields=False)
    @classmethod
    def validate_hours_ago(cls, v):
        """Read one or more hour counts as a comma-separated string."""
        if v is None:
            return None

        return ",".join(str(hour) for hour in v) if isinstance(v, list) else str(v)

    @model_validator(mode="before")
    @classmethod
    def validate_model(cls, values):
        """Reject a date, which the exchange does not serve a curve for.

        Raises
        ------
        ValueError
            If a date was given.
        """
        if isinstance(values, dict) and values.get("date"):
            raise ValueError(
                "Deribit serves no curve as of a date. Use 'hours_ago' instead."
            )

        return values


class DeribitFuturesCurveData(FuturesCurveData):
    """Deribit Futures Curve Data."""

    date: dateType | None = Field(
        default=None,
        description=DATA_DESCRIPTIONS.get("date", ""),
        json_schema_extra={"x-widget_config": {"chartDataType": "excluded"}},
    )
    expiration: str = Field(
        description="Futures expiration month.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "category", "pinned": "left"}
        },
    )
    price: float | None = Field(
        default=None,
        description="The price of the futures contract, taken from the mark.",
        json_schema_extra={
            "x-unit_measurement": "currency",
            "x-widget_config": {"chartDataType": "series"},
        },
    )
    symbol: str | None = Field(
        default=None,
        description="The name of the contract.",
        json_schema_extra={"x-widget_config": {"chartDataType": "excluded"}},
    )
    last_price: float | None = Field(
        default=None,
        description="The price the contract last traded at, which on a thin"
        + " contract can be a long way from the mark the curve is built on.",
        json_schema_extra={
            "x-unit_measurement": "currency",
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    hours_ago: int | None = Field(
        default=None,
        description="How many hours back the price was read, when the query"
        + " asked for one.",
        json_schema_extra={"x-widget_config": {"chartDataType": "excluded"}},
    )


class DeribitFuturesCurveFetcher(
    Fetcher[DeribitFuturesCurveQueryParams, list[DeribitFuturesCurveData]]
):
    """Transform the query, extract and transform the data from the Deribit endpoint.

    The current curve is priced off each contract's mark, because a thin contract's
    last trade can be a long way from where the exchange marks it. A curve read
    some hours back is priced off traded closes instead, the only history the
    exchange publishes, so it carries only the contracts that had traded by then.
    """

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> DeribitFuturesCurveQueryParams:
        """Transform the query."""
        return DeribitFuturesCurveQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: DeribitFuturesCurveQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Return the raw data from the Deribit endpoint.

        Raises
        ------
        EmptyDataError
            If none of the contracts on the curve published a quote.
        """
        from openbb_deribit.utils.helpers import (
            get_futures_curve_by_hours_ago,
            get_futures_curve_symbols,
            get_tickers,
        )

        symbols = await get_futures_curve_symbols(query.symbol)
        data = await get_tickers(symbols)

        if query.hours_ago:
            for hour in [int(h) for h in query.hours_ago.split(",") if h.strip()]:
                data.extend(await get_futures_curve_by_hours_ago(query.symbol, hour))

        if not data:
            raise EmptyDataError(
                f"Deribit published no quote for the {query.symbol} curve."
            )

        return data

    @staticmethod
    def transform_data(
        query: DeribitFuturesCurveQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[DeribitFuturesCurveData]:
        """Transform the data to the model.

        Raises
        ------
        EmptyDataError
            If every contract on the curve came back unpriced.
        """
        from datetime import datetime

        from pandas import to_datetime

        records: list[dict] = []

        for record in data:
            symbol = str(record.get("instrument_name") or "")
            code = symbol.split("-")[1] if "-" in symbol else ""
            price = record.get("mark_price") or record.get("last_price")

            if not symbol or price is None:
                continue

            records.append(
                {
                    "symbol": symbol,
                    "expiration": (
                        datetime.now(UTC).strftime("%Y-%m-%d")
                        if code == "PERPETUAL"
                        else to_datetime(code).strftime("%Y-%m-%d")
                    ),
                    "price": price,
                    "last_price": record.get("last_price"),
                    "hours_ago": record.get("hours_ago") if query.hours_ago else None,
                }
            )

        if not records:
            raise EmptyDataError(
                f"Deribit published no priced contract on the {query.symbol} curve."
            )

        return [
            DeribitFuturesCurveData.model_validate(record)
            for record in sorted(
                records, key=lambda d: (d["hours_ago"] or 0, d["expiration"])
            )
        ]
