"""IBKR Equity Historical Price Model."""

# pylint: disable=unused-argument
from datetime import datetime
from typing import Any, Literal, Optional, Union

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.equity_historical import (
    EquityHistoricalData,
    EquityHistoricalQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field


class IBKREquityHistoricalQueryParams(EquityHistoricalQueryParams):
    """IBKR Equity Historical Price Query.

    Source: https://www.interactivebrokers.com
    """

    interval: Literal["1d", "1W", "1M"] = Field(
        default="1d",
        description="Time interval for each bar.",
    )
    what_to_show: Literal["TRADES", "MIDPOINT", "BID", "ASK"] = Field(
        default="TRADES",
        description="Type of data to retrieve. TRADES returns OHLCV. Others return bid/ask/midpoint prices.",
    )
    use_rth: bool = Field(
        default=True,
        description="If True, only data from regular trading hours is returned.",
    )


class IBKREquityHistoricalData(EquityHistoricalData):
    """IBKR Equity Historical Price Data."""

    bar_count: Optional[int] = Field(
        default=None,
        description="Number of trades that occurred during the bar.",
    )
    average: Optional[float] = Field(
        default=None,
        description="Weighted average price during the bar.",
    )


class IBKREquityHistoricalFetcher(
    Fetcher[
        IBKREquityHistoricalQueryParams,
        list[IBKREquityHistoricalData],
    ]
):
    """Fetch equity historical prices from IBKR via TWS or IB Gateway."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> IBKREquityHistoricalQueryParams:
        """Transform query params, defaulting dates if not provided."""
        now = datetime.now().date()
        if params.get("start_date") is None:
            params["start_date"] = now.replace(year=now.year - 1)
        if params.get("end_date") is None:
            params["end_date"] = now
        return IBKREquityHistoricalQueryParams(**params)

    @staticmethod
    def extract_data(
        query: IBKREquityHistoricalQueryParams,
        credentials: Optional[dict[str, str]],
        **kwargs: Any,
    ) -> list[dict]:
        """Connect to IBKR and fetch historical bar data."""
        # pylint: disable=import-outside-toplevel
        from openbb_ibkr.utils.helpers import fetch_historical_bars

        host = (credentials or {}).get("ibkr_host", "127.0.0.1")
        port = int((credentials or {}).get("ibkr_port", 4002))
        client_id = int((credentials or {}).get("ibkr_client_id", 1))

        start = query.start_date
        end = query.end_date
        duration_days = (end - start).days
        duration_str = f"{duration_days} D" if duration_days <= 365 else f"{duration_days // 365 + 1} Y"

        interval_map = {"1d": "1 day", "1W": "1 week", "1M": "1 month"}
        bar_size = interval_map.get(str(query.interval), "1 day")

        data = fetch_historical_bars(
            symbol=query.symbol,
            end_date_str=end.strftime("%Y%m%d %H:%M:%S"),
            duration_str=duration_str,
            bar_size=bar_size,
            what_to_show=query.what_to_show,
            use_rth=query.use_rth,
            host=host,
            port=port,
            client_id=client_id,
        )

        if not data:
            raise EmptyDataError()

        return data

    @staticmethod
    def transform_data(
        query: IBKREquityHistoricalQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[IBKREquityHistoricalData]:
        """Map raw IBKR bar dicts to the standardized data model."""
        return [IBKREquityHistoricalData.model_validate(d) for d in data]
