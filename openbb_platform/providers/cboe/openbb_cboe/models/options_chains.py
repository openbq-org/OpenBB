"""Cboe Options Chains Model."""

from datetime import datetime
from typing import Any

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.options_chains import (
    OptionsChainsData,
    OptionsChainsQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pandas import Timedelta
from pydantic import Field

from openbb_cboe.utils.constants import EQUITY_CHOICES_ENDPOINT

EXPIRY_HOUR = Timedelta(hours=16)


class CboeOptionsChainsQueryParams(OptionsChainsQueryParams):
    """Cboe Options Chains Query.

    Source: https://www.cboe.com/
    """

    __json_schema_extra__ = {
        "symbol": {
            "x-widget_config": {
                "type": "endpoint",
                "optionsEndpoint": EQUITY_CHOICES_ENDPOINT,
                "style": {"popupWidth": 600},
            },
        },
    }

    use_cache: bool = Field(
        default=True,
        description="When True, the company directories will be cached for"
        + "24 hours and are used to validate symbols."
        + " The results of the function are not cached. Set as False to bypass.",
    )


class CboeOptionsChainsData(OptionsChainsData):
    """Cboe Options Chains Data."""

    __doc__ = OptionsChainsData.__doc__


class CboeOptionsChainsFetcher(
    Fetcher[
        CboeOptionsChainsQueryParams,
        CboeOptionsChainsData,
    ]
):
    """Transform the query, extract and transform the data from the Cboe endpoints."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> CboeOptionsChainsQueryParams:
        """Transform the query."""
        return CboeOptionsChainsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: CboeOptionsChainsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Return the raw data from the Cboe endpoint.

        Raises
        ------
        OpenBBError
            If the symbol is not listed in the Cboe options directory.
        """
        from openbb_core.provider.utils.helpers import amake_request

        from openbb_cboe.utils.helpers import (
            TICKER_EXCEPTIONS,
            get_company_directory,
            get_index_directory,
        )

        symbol = query.symbol.replace("^", "").split(",")[0].upper()
        indexes = await get_index_directory(use_cache=query.use_cache)
        company_directory = await get_company_directory(use_cache=query.use_cache)
        indexes = indexes.set_index("index_symbol")

        if symbol not in company_directory.index:
            raise OpenBBError(f"{symbol} was not found in the Cboe options directory.")

        quotes_url = (
            f"https://cdn.cboe.com/api/global/delayed_quotes/options/_{symbol}.json"
            if symbol in TICKER_EXCEPTIONS or symbol in indexes.index
            else f"https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json"
        )

        return await amake_request(quotes_url)  # ty: ignore[invalid-return-type]

    @staticmethod
    def transform_data(
        query: CboeOptionsChainsQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> AnnotatedResult[CboeOptionsChainsData]:
        """Transform the data to the standard format."""
        from zoneinfo import ZoneInfo

        from pandas import DataFrame, DatetimeIndex, Series, to_datetime

        if not data:
            raise EmptyDataError()

        options = data.get("data", {}).pop("options", [])
        change_percent = data["data"].get("percent_change")
        iv30_percent = data["data"].get("iv30_change_percent")

        if change_percent:
            change_percent = change_percent / 100

        if iv30_percent:
            iv30_percent = iv30_percent / 100

        last_timestamp = data["data"].get("last_trade_time")

        if last_timestamp:
            last_timestamp = to_datetime(
                last_timestamp, format="%Y-%m-%dT%H:%M:%S"
            ).strftime("%Y-%m-%d %H:%M:%S")

        results_metadata = {
            "symbol": data["data"].get("symbol"),
            "security_type": data["data"].get("security_type"),
            "bid": data["data"].get("bid"),
            "bid_size": data["data"].get("bid_size"),
            "ask": data["data"].get("ask"),
            "ask_size": data["data"].get("ask_size"),
            "open": data["data"].get("open"),
            "high": data["data"].get("high"),
            "low": data["data"].get("low"),
            "close": data["data"].get("close"),
            "volume": data["data"].get("volume"),
            "current_price": data["data"].get("current_price"),
            "prev_close": data["data"].get("prev_day_close"),
            "change": data["data"].get("price_change"),
            "change_percent": change_percent,
            "iv30": data["data"].get("iv30"),
            "iv30_change": data["data"].get("iv30_change"),
            "iv30_change_percent": iv30_percent,
            "last_tick": data["data"].get("tick"),
            "last_trade_timestamp": last_timestamp,
        }
        results_metadata = {k: v for k, v in results_metadata.items() if v is not None}

        options_df = DataFrame.from_records(options)
        options_df = options_df.rename(
            columns={
                "option": "contract_symbol",
                "iv": "implied_volatility",
                "theo": "theoretical_price",
                "percent_change": "change_percent",
                "prev_day_close": "prev_close",
            }
        )
        occ_regex = (
            r"^(?P<Ticker>.*?)(?P<expiration>\d{6})(?P<option_type>[CP])(?P<strike>\d{8})$"
        )
        option_df_index = options_df["contract_symbol"].str.extract(occ_regex)

        if option_df_index["expiration"].isna().any():
            fallback_regex = (
                r"^(?P<Ticker>\D*)(?P<expiration>\d{1,6})(?P<option_type>[CP])(?P<strike>\d*)"
            )
            missing_mask = option_df_index["expiration"].isna()
            fallback = options_df.loc[missing_mask, "contract_symbol"].str.extract(
                fallback_regex
            )
            option_df_index.update(fallback)

        valid_mask = (
            option_df_index["expiration"].notna()
            & option_df_index["option_type"].notna()
            & option_df_index["strike"].notna()
        )
        option_df_index = option_df_index[valid_mask]
        options_df = options_df.loc[option_df_index.index]

        option_df_index.option_type = option_df_index.option_type.str.replace(
            "C", "call"
        ).str.replace("P", "put")
        option_df_index.strike = [ele.lstrip("0") for ele in option_df_index.strike]
        option_df_index.strike = Series(
            option_df_index.strike, index=option_df_index.index
        ).astype(float)
        option_df_index.strike = option_df_index.strike * (1 / 1000)
        option_df_index.strike = option_df_index.strike.to_list()
        option_df_index.expiration = to_datetime(
            option_df_index.expiration, format="%y%m%d", errors="coerce"
        ).dt.strftime("%Y-%m-%d")

        valid_date_mask = option_df_index.expiration.notna()
        option_df_index = option_df_index[valid_date_mask]
        options_df = options_df.loc[option_df_index.index]

        option_df_index = option_df_index.rename(
            columns={"Ticker": "underlying_symbol"}
        )

        quotes = option_df_index.join(options_df)
        eastern = ZoneInfo("America/New_York")
        expires = DatetimeIndex(quotes.expiration).tz_localize(eastern) + EXPIRY_HOUR
        quotes["dte"] = (expires - datetime.now(tz=eastern)).days
        quotes["last_trade_time"] = (
            to_datetime(quotes["last_trade_time"], format="%Y-%m-%dT%H:%M:%S")
            .fillna(value="-")
            .replace("-", None)
        )
        quotes = quotes.set_index(
            keys=["expiration", "strike", "option_type"]
        ).sort_index()

        if results_metadata.get("current_price"):
            quotes["underlying_price"] = results_metadata["current_price"]

        for col in ("open_interest", "volume", "bid_size", "ask_size"):
            quotes[col] = quotes[col].astype("int64")

        quotes["change_percent"] = quotes["change_percent"] / 100

        return AnnotatedResult(
            result=CboeOptionsChainsData.model_validate(
                quotes.reset_index().to_dict("list")
            ),
            metadata=results_metadata,
        )
