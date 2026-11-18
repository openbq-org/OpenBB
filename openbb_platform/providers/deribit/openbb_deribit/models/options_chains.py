"""Deribit Options Chains Model."""

from datetime import (
    date as dateType,
    datetime,
    timezone,
)
from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.options_chains import (
    OptionsChainsData,
    OptionsChainsQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator

from openbb_deribit.utils.constants import (
    SYMBOL_STYLE,
    UNDERLYING_CHOICES_ENDPOINT,
)

INVERSE_QUOTED = ("BTC", "ETH")
PRICE_FIELDS = (
    "last_price",
    "settlement_price",
    "mark_price",
    "min_price",
    "max_price",
    "best_ask_price",
    "best_bid_price",
    "high",
    "low",
)
# Deribit expires every option at 08:00 UTC on the date in its name.
EXPIRATION_TIME = "08:00"


class DeribitOptionsChainsQueryParams(OptionsChainsQueryParams):
    """Deribit Options Chains Query.

    Source: https://docs.deribit.com/api-reference/market-data/public-ticker
    """

    __json_schema_extra__ = {
        "symbol": {
            "multiple_items_allowed": False,
            "x-widget_config": {
                "type": "endpoint",
                "optionsEndpoint": UNDERLYING_CHOICES_ENDPOINT,
                "style": SYMBOL_STYLE,
            },
        }
    }


class DeribitOptionsChainsData(OptionsChainsData):
    """Deribit Options Chains Data."""

    __alias_dict__ = {
        "contract_symbol": "instrument_name",
        "change_percent": "price_change",
        "underlying_symbol": "underlying_index",
        "underlying_spot_price": "index_price",
        "bid_size": "best_bid_amount",
        "ask_size": "best_ask_amount",
        "bid": "best_bid_price",
        "ask": "best_ask_price",
        "implied_volatility": "mark_iv",
        "mark": "mark_price",
        "last_trade_price": "last_price",
        "volume_notional": "volume_usd",
    }

    __doc__ = OptionsChainsData.__doc__

    contract_symbol: list[str] = Field(
        description="The symbol of the contract.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Contract",
                "chartDataType": "excluded",
                "pinned": "left",
            },
        },
    )
    expiration: list[dateType] = Field(
        description="The expiration date of the contract.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    dte: list[int | None] = Field(
        description="The number of days until expiration.",
        json_schema_extra={
            "x-widget_config": {"headerName": "DTE", "chartDataType": "excluded"},
        },
    )
    strike: list[float] = Field(
        description="The strike price of the contract.",
        json_schema_extra={
            "x-unit_measurement": "currency",
            "x-widget_config": {"chartDataType": "category"},
        },
    )
    option_type: list[str] = Field(
        description="Whether the contract is a call or a put.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Type", "chartDataType": "excluded"},
        },
    )
    mark: list[float | None] = Field(
        description="The mark price of the contract.",
        json_schema_extra={
            "x-unit_measurement": "currency",
            "x-widget_config": {"chartDataType": "series"},
        },
    )
    bid: list[float | None] = Field(
        description="The highest price bid.",
        json_schema_extra={
            "x-unit_measurement": "currency",
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    bid_size: list[int | float | None] = Field(
        description="The size resting at the best bid.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    ask: list[float | None] = Field(
        description="The lowest price offered.",
        json_schema_extra={
            "x-unit_measurement": "currency",
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    ask_size: list[int | float | None] = Field(
        description="The size resting at the best offer.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    last_trade_price: list[float | None] = Field(
        description="The price the contract last traded at.",
        json_schema_extra={
            "x-unit_measurement": "currency",
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    open_interest: list[int | float | None] = Field(
        description="The contracts left outstanding.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    volume: list[int | float | None] = Field(
        description="The volume of the session.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    volume_notional: list[float | None] = Field(
        description="The notional volume of the contract, in USD or USDC.",
        json_schema_extra={
            "x-unit_measurement": "currency",
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    high: list[float | None] = Field(
        description="The highest price of the session.",
        json_schema_extra={
            "x-unit_measurement": "currency",
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    low: list[float | None] = Field(
        description="The lowest price of the session.",
        json_schema_extra={
            "x-unit_measurement": "currency",
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    change_percent: list[float | None] = Field(
        description="The price change over the session.",
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    implied_volatility: list[float | None] = Field(
        description="The volatility implied by the mark price.",
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-widget_config": {"headerName": "Mark IV", "chartDataType": "excluded"},
        },
    )
    bid_iv: list[float | None] = Field(
        description="The volatility implied by the bid price.",
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-widget_config": {"headerName": "Bid IV", "chartDataType": "excluded"},
        },
    )
    ask_iv: list[float | None] = Field(
        description="The volatility implied by the ask price.",
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-widget_config": {"headerName": "Ask IV", "chartDataType": "excluded"},
        },
    )
    delta: list[float | None] = Field(
        description="The sensitivity to the underlying's price.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    gamma: list[float | None] = Field(
        description="The sensitivity of delta to the underlying's price.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    theta: list[float | None] = Field(
        description="The sensitivity to the passage of time.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    vega: list[float | None] = Field(
        description="The sensitivity to implied volatility.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    rho: list[float | None] = Field(
        description="The sensitivity to the interest rate.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    interest_rate: list[float | None] = Field(
        description="The rate the exchange prices the greeks at.",
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    settlement_price: list[float | None] = Field(
        description="The price the contract last settled at.",
        json_schema_extra={
            "x-unit_measurement": "currency",
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    min_price: list[float | None] = Field(
        description="The lowest price an order will be accepted at.",
        json_schema_extra={
            "x-unit_measurement": "currency",
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    max_price: list[float | None] = Field(
        description="The highest price an order will be accepted at.",
        json_schema_extra={
            "x-unit_measurement": "currency",
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    underlying_symbol: list[str | None] = Field(
        description="The future or index the contract is priced against.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    underlying_price: list[float | None] = Field(
        description="The price of the underlying the contract is priced against.",
        json_schema_extra={
            "x-unit_measurement": "currency",
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    underlying_spot_price: list[float] = Field(
        description="The spot price of the underlying the option is based on.",
        json_schema_extra={
            "x-unit_measurement": "currency",
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    contract_size: list[int | float | None] = Field(
        description="The size of one contract, in units of the underlying.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    is_inverse: list[bool | None] = Field(
        default_factory=list,
        description="Whether the contract settles in the underlying rather than"
        + " in the quote currency, which changes how its payoff is valued.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Is Inverse",
                "cellDataType": "boolean",
                "chartDataType": "excluded",
            }
        },
    )
    timestamp: list[datetime] = Field(
        description="When the quote was published, as America/New_York time.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded"},
        },
    )
    eod_date: list[dateType | None] = Field(
        default_factory=list,
        description="The end-of-day date. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "EOD Date",
                "chartDataType": "excluded",
                "hide": True,
            }
        },
    )
    theoretical_price: list[float | None] = Field(
        default_factory=list,
        description="The theoretical price of the contract. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    last_trade_size: list[int | float | None] = Field(
        default_factory=list,
        description="The size of the last trade. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    last_trade_time: list[datetime | None] = Field(
        default_factory=list,
        description="When the last trade printed. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    tick: list[str | None] = Field(
        default_factory=list,
        description="The direction of the last price move. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    bid_time: list[datetime | None] = Field(
        default_factory=list,
        description="When the bid was published. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    bid_exchange: list[str | None] = Field(
        default_factory=list,
        description="The exchange the bid came from. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    ask_time: list[datetime | None] = Field(
        default_factory=list,
        description="When the offer was published. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    ask_exchange: list[str | None] = Field(
        default_factory=list,
        description="The exchange the offer came from. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    open: list[float | None] = Field(
        default_factory=list,
        description="The opening price of the session. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    open_bid: list[float | None] = Field(
        default_factory=list,
        description="The opening bid of the session. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    open_ask: list[float | None] = Field(
        default_factory=list,
        description="The opening offer of the session. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    bid_high: list[float | None] = Field(
        default_factory=list,
        description="The highest bid of the session. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    ask_high: list[float | None] = Field(
        default_factory=list,
        description="The highest offer of the session. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    bid_low: list[float | None] = Field(
        default_factory=list,
        description="The lowest bid of the session. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    ask_low: list[float | None] = Field(
        default_factory=list,
        description="The lowest offer of the session. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    close: list[float | None] = Field(
        default_factory=list,
        description="The closing price of the session. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    close_size: list[int | float | None] = Field(
        default_factory=list,
        description="The size of the closing trade. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    close_time: list[datetime | None] = Field(
        default_factory=list,
        description="When the closing trade printed. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    close_bid: list[float | None] = Field(
        default_factory=list,
        description="The closing bid of the session. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    close_bid_size: list[int | float | None] = Field(
        default_factory=list,
        description="The size at the closing bid. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    close_bid_time: list[datetime | None] = Field(
        default_factory=list,
        description="When the closing bid was published. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    close_ask: list[float | None] = Field(
        default_factory=list,
        description="The closing offer of the session. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    close_ask_size: list[int | float | None] = Field(
        default_factory=list,
        description="The size at the closing offer. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    close_ask_time: list[datetime | None] = Field(
        default_factory=list,
        description="When the closing offer was published. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    prev_close: list[float | None] = Field(
        default_factory=list,
        description="The closing price of the previous session. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )
    change: list[float | None] = Field(
        default_factory=list,
        description="The price change over the session. Deribit publishes none.",
        json_schema_extra={
            "x-widget_config": {"chartDataType": "excluded", "hide": True}
        },
    )

    @field_validator(
        "interest_rate",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def as_percent(cls, v):
        """Return a rate the exchange sends as a fraction in percent units."""
        return v * 100 if v is not None else None


class DeribitOptionsChainsFetcher(
    Fetcher[DeribitOptionsChainsQueryParams, DeribitOptionsChainsData]
):
    """Transform the query, extract and transform the data from the Deribit endpoint."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> DeribitOptionsChainsQueryParams:
        """Transform the query."""
        return DeribitOptionsChainsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: DeribitOptionsChainsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Return the raw data from the Deribit websocket.

        Raises
        ------
        OpenBBError
            If every expiration failed.
        EmptyDataError
            If the subscriptions returned nothing at all.
        """
        import asyncio
        from warnings import warn

        from openbb_core.app.model.abstract.error import OpenBBError
        from pandas import to_datetime

        from openbb_deribit.utils.helpers import (
            days_to_expiration,
            flatten_ticker,
            get_instruments,
            get_options_symbols,
            to_timestamp,
        )
        from openbb_deribit.utils.websocket import subscribe_tickers

        by_expiration = await get_options_symbols(query.symbol)
        specs = {
            str(d["instrument_name"]): d for d in await get_instruments("any", "option")
        }
        messages: set = set()
        subscriptions = await asyncio.gather(
            *(
                subscribe_tickers(symbols, messages)
                for symbols in by_expiration.values()
            ),
            return_exceptions=True,
        )
        now = datetime.now(timezone.utc).timestamp() * 1000
        results: list[dict] = []

        for subscription in subscriptions:
            if not isinstance(subscription, dict):
                continue

            for symbol, ticker in subscription.items():
                parts = symbol.split("-")
                strike = parts[2].replace("d", ".")
                flat = flatten_ticker(ticker)
                flat.pop("state", None)
                published = flat.pop("timestamp", None)

                if flat.get("underlying_index") == "index_price":
                    flat["underlying_index"] = parts[0].replace("_", "-")

                if flat.get("estimated_delivery_price") == flat.get("index_price"):
                    flat.pop("estimated_delivery_price", None)

                expiration = to_datetime(parts[1]).date()
                spec = specs.get(symbol, {})
                expires = spec.get("expiration_timestamp") or to_timestamp(
                    f"{expiration} {EXPIRATION_TIME}"
                )
                results.append(
                    {
                        "expiration": expiration,
                        "strike": float(strike),
                        "option_type": "call" if symbol.endswith("-C") else "put",
                        "dte": days_to_expiration(expires, now),
                        "contract_size": spec.get("contract_size"),
                        "is_inverse": spec.get("instrument_type") == "reversed",
                        "timestamp": to_datetime(
                            published, unit="ms", utc=True
                        ).tz_convert("America/New_York"),
                        **flat,
                    }
                )

        if messages and not results:
            raise OpenBBError(", ".join(sorted(messages)))

        for message in sorted(messages):
            warn(message)

        if not results:
            raise EmptyDataError(
                f"Deribit published no option quotes for {query.symbol}."
            )

        return results

    @staticmethod
    def transform_data(
        query: DeribitOptionsChainsQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> DeribitOptionsChainsData:
        """Transform the data to the model.

        Contracts on BTC and ETH are quoted in the underlying, so their prices are
        carried to USD at the index level the quote was published against.
        """
        from numpy import nan
        from pandas import DataFrame

        frame = DataFrame(data)
        inverse = bool(frame["is_inverse"].any())

        for column in frame.columns:
            if column in PRICE_FIELDS and inverse:
                frame[column] = frame[column].astype(float) * frame["index_price"]

        frame = frame.replace({nan: None})
        frame = frame.sort_values(["expiration", "strike", "option_type"])
        frame = frame.reset_index(drop=True)
        return DeribitOptionsChainsData.model_validate(frame.to_dict(orient="list"))
