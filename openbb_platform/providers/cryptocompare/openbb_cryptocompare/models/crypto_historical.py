"""CryptoCompare Crypto Historical Price Model."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, time, timedelta, timezone
from math import ceil
from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.crypto_historical import (
    CryptoHistoricalData,
    CryptoHistoricalQueryParams,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import (
    Field,
    PrivateAttr,
    PositiveInt,
    field_validator,
    model_validator,
)


INTERVAL_SPECS: dict[str, tuple[str, int, int]] = {
    "1m": ("histominute", 1, 60),
    "5m": ("histominute", 5, 60),
    "15m": ("histominute", 15, 60),
    "30m": ("histominute", 30, 60),
    "1h": ("histohour", 1, 3600),
    "4h": ("histohour", 4, 3600),
    "6h": ("histohour", 6, 3600),
    "12h": ("histohour", 12, 3600),
    "1d": ("histoday", 1, 86400),
}


class CryptoCompareCryptoHistoricalQueryParams(CryptoHistoricalQueryParams):
    """CryptoCompare Crypto Historical Price Query."""

    interval: Literal[
        "1m",
        "5m",
        "15m",
        "30m",
        "1h",
        "4h",
        "6h",
        "12h",
        "1d",
    ] = Field(
        default="1d",
        description=QUERY_DESCRIPTIONS.get("interval", "")
        + " Supported values: "
        + ", ".join(INTERVAL_SPECS.keys()),
    )
    limit: PositiveInt | None = Field(
        default=None,
        description="Override the calculated number of data points to request (1-2000).",
        le=2000,
    )

    _fsym: str = PrivateAttr(default="")
    _tsym: str = PrivateAttr(default="")
    _endpoint: str = PrivateAttr(default="histoday")
    _aggregate: PositiveInt = PrivateAttr(default=1)
    _interval_seconds: PositiveInt = PrivateAttr(default=86400)
    _to_ts: int = PrivateAttr(default=0)
    _limit: PositiveInt = PrivateAttr(default=1)

    @field_validator("symbol", mode="before")
    @classmethod
    def _cleanup_symbol(cls, v: str) -> str:
        """Normalize trading pair symbols."""
        if not isinstance(v, str):
            raise ValueError("symbol must be a string.")
        return v.replace("/", "-").upper()

    @field_validator("interval", mode="before")
    @classmethod
    def _lower_interval(cls, v: str) -> str:
        """Lowercase the interval before validation."""
        return str(v).lower()

    @model_validator(mode="after")
    def _set_internal_fields(cls, values: "CryptoCompareCryptoHistoricalQueryParams"):
        """Populate internal attributes for downstream fetchers."""
        if not values.symbol or "-" not in values.symbol:
            msg = "Symbol must be in the format 'BASE-QUOTE', e.g., 'BTC-USD'."
            raise ValueError(msg)

        base, quote = values.symbol.split("-", maxsplit=1)
        values._fsym = base.upper()  # pylint: disable=protected-access
        values._tsym = quote.upper()  # pylint: disable=protected-access

        if values.interval not in INTERVAL_SPECS:
            raise ValueError(f"Unsupported interval '{values.interval}'.")

        endpoint, aggregate, seconds = INTERVAL_SPECS[values.interval]
        values._endpoint = endpoint  # pylint: disable=protected-access
        values._aggregate = aggregate  # pylint: disable=protected-access
        values._interval_seconds = seconds  # pylint: disable=protected-access

        if values.start_date is None or values.end_date is None:
            raise ValueError("start_date and end_date are required.")

        start_dt = datetime.combine(
            values.start_date,
            time.min,
            tzinfo=timezone.utc,
        )
        end_dt = datetime.combine(
            values.end_date,
            time.min,
            tzinfo=timezone.utc,
        )

        range_seconds = (end_dt - start_dt).total_seconds()
        if range_seconds <= 0:
            range_seconds = values._interval_seconds  # pylint: disable=protected-access

        step = values._interval_seconds * values._aggregate  # pylint: disable=protected-access
        calculated = max(1, ceil(range_seconds / step) + 1)
        limited = min(2000, calculated)

        values._limit = (values.limit or limited)  # pylint: disable=protected-access
        values._to_ts = int(end_dt.timestamp())  # pylint: disable=protected-access

        return values


class CryptoCompareCryptoHistoricalData(CryptoHistoricalData):
    """CryptoCompare Crypto Historical Price Data."""

    symbol: str = Field(description="Trading pair in BASE-QUOTE format.")
    base_volume: float | None = Field(
        default=None, description="Volume traded in the base asset."
    )
    quote_volume: float | None = Field(
        default=None, description="Volume traded in the quote asset."
    )


class CryptoCompareCryptoHistoricalFetcher(
    Fetcher[
        CryptoCompareCryptoHistoricalQueryParams,
        list[CryptoCompareCryptoHistoricalData],
    ]
):
    """CryptoCompare Crypto Historical Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any]
    ) -> CryptoCompareCryptoHistoricalQueryParams:
        """Fill defaults and validate query parameters."""
        transformed_params = params.copy()
        today = datetime.utcnow().date()

        if transformed_params.get("end_date") is None:
            transformed_params["end_date"] = today

        if transformed_params.get("start_date") is None:
            transformed_params["start_date"] = today - timedelta(days=30)

        if transformed_params["start_date"] > transformed_params["end_date"]:
            raise ValueError("start_date must be earlier than end_date.")

        return CryptoCompareCryptoHistoricalQueryParams(**transformed_params)

    @staticmethod
    async def aextract_data(
        query: CryptoCompareCryptoHistoricalQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Extract raw data from the CryptoCompare endpoint."""
        # pylint: disable=import-outside-toplevel
        from openbb_cryptocompare.utils.helpers import (
            build_hist_url,
            get_cryptocompare_data,
        )

        api_key = credentials.get("cryptocompare_api_key") if credentials else None
        url = build_hist_url(query, api_key)
        return await get_cryptocompare_data(url, **kwargs)

    @staticmethod
    def transform_data(
        query: CryptoCompareCryptoHistoricalQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> list[CryptoCompareCryptoHistoricalData]:
        """Transform the CryptoCompare payload into standardized data."""
        rows = data.get("Data", {}).get("Data", [])
        if not rows:
            raise EmptyDataError()

        transformed = []
        for item in rows:
            timestamp = item.get("time")
            if timestamp is None:
                continue

            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            if (
                isinstance(query.start_date, date_type)
                and dt.date() < query.start_date
            ) or (isinstance(query.end_date, date_type) and dt.date() > query.end_date):
                continue

            formatted_date: date_type | datetime
            if query._endpoint == "histoday":  # pylint: disable=protected-access
                formatted_date = dt.date()
            else:
                formatted_date = dt

            volume_from = item.get("volumefrom")
            volume_to = item.get("volumeto")
            vwap = None
            if volume_from and volume_to and volume_from != 0:
                vwap = volume_to / volume_from

            transformed.append(
                {
                    "symbol": query.symbol,
                    "date": formatted_date,
                    "open": item.get("open"),
                    "high": item.get("high"),
                    "low": item.get("low"),
                    "close": item.get("close"),
                    "volume": volume_to,
                    "base_volume": volume_from,
                    "quote_volume": volume_to,
                    "vwap": vwap,
                }
            )

        if not transformed:
            raise EmptyDataError("No data returned for the requested date range.")

        transformed = sorted(transformed, key=lambda x: x["date"])
        return [
            CryptoCompareCryptoHistoricalData.model_validate(item)
            for item in transformed
        ]
