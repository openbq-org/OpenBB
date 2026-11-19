"""DTCC Public Price Dissemination FX Option Trades Model."""

from collections.abc import Iterable
from datetime import (
    UTC,
    date as dateType,
    datetime,
)
from typing import Any, Literal

from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import ConfigDict, Field, model_validator

from openbb_cftc.utils.fx_options import NOT_PROVIDED

_NUMERIC_FIELDS = frozenset(
    {
        "call_amount",
        "put_amount",
        "strike",
        "exchange_rate",
        "premium_amount",
        "notional_1",
        "notional_2",
        "package_price",
        "package_spread",
    }
)
_BOOL_FIELDS = frozenset({"block_trade", "prime_brokerage", "package_trade"})


class CftcFxOptionTradesQueryParams(QueryParams):
    """DTCC Public Price Dissemination FX Option Trades Query Parameters."""

    __json_schema_extra__ = {
        "action_type": {"multiple_items_allowed": False},
        "option_type": {"multiple_items_allowed": False},
    }

    pair: str | None = Field(
        default=None,
        description="Filter to a pair or currency, matched against the two reported legs."
        + " 'EURUSD', 'EUR/USD' and 'EUR USD' all match EUR/USD; a single code like 'JPY'"
        + " matches every pair with that leg. Default is every pair, deliverable and"
        + " non-deliverable.",
    )
    option_type: (
        Literal["Vanilla", "Non-Deliverable", "Digital", "Barrier", "Target"] | None
    ) = Field(
        default=None,
        description="Filter by option family: Vanilla, Non-Deliverable (cash-settled EM"
        + " options), Digital, Barrier, or Target. Default is every family.",
    )
    date: dateType | None = Field(
        default=None,
        description="Dissemination date (UTC). Default is the most recent day whose file"
        + " holds option prints; a file is published every calendar day, but weekends and"
        + " holidays carry almost none. Files are retained for 366 days.",
        json_schema_extra={"x-widget_config": {"value": "$currentDate"}},
    )
    action_type: Literal["NEWT", "MODI", "CORR", "TERM", "EROR", "REVI"] | None = Field(
        default=None,
        description="Filter by the action reported: NEWT (new), MODI (modify), CORR"
        + " (correct), TERM (terminate), EROR (error), or REVI (revive). Default is every"
        + " action; pass NEWT for newly executed trades only.",
    )
    settlement_currency: str | None = Field(
        default=None,
        description="Filter to options cash-settled in this currency, e.g. 'USD' for the"
        + " USD-settled non-deliverable options. Deliverable options carry no settlement"
        + " currency and are excluded by it. Default is every settlement.",
    )
    min_notional: float | None = Field(
        default=None,
        description="Drop prints whose larger notional leg is disseminated below this"
        + " amount. The two legs value the same trade in each currency, so the larger is a"
        + " currency-agnostic size proxy. Amounts above the reporting cap disseminate at"
        + " the cap.",
    )
    ticker: str | None = Field(
        default=None,
        description="Filter to the exact UPI ticker, the Unique Product Identifier the"
        + " source's TICKER report keys on. Default is every product. A ticker query"
        + " is answered by the source's search API, cached per day, not the daily"
        + " files.",
    )
    limit: int | None = Field(
        default=None,
        description="Number of prints to return, newest execution first. Default is all"
        + " matching.",
    )
    use_cache: bool = Field(
        default=True,
        description="Cache the daily file locally, revalidating it against the source ETag.",
    )


class CftcFxOptionTradesData(Data):
    """DTCC Public Price Dissemination FX Option Trades Data."""

    model_config = ConfigDict(extra="ignore")

    __alias_dict__ = {
        "trade_key": "Trade Key",
        "original_trade_key": "Original Trade Key",
        "action_type": "Action type",
        "event_type": "Event type",
        "event_timestamp": "Event timestamp",
        "execution_timestamp": "Execution Timestamp",
        "effective_date": "Effective Date",
        "expiration_date": "Expiration Date",
        "first_exercise_date": "First exercise date",
        "call_currency": "Call currency",
        "call_amount": "Call amount",
        "put_currency": "Put currency",
        "put_amount": "Put amount",
        "strike": "Strike Price",
        "strike_pair": "Strike price currency/currency pair",
        "strike_notation": "Strike price notation",
        "exchange_rate": "Exchange rate",
        "exchange_rate_basis": "Exchange rate basis",
        "premium_amount": "Option Premium Amount",
        "premium_currency": "Option Premium Currency",
        "settlement_currency": "Settlement currency-Leg 1",
        "notional_1": "Notional amount-Leg 1",
        "notional_currency_1": "Notional currency-Leg 1",
        "notional_2": "Notional amount-Leg 2",
        "notional_currency_2": "Notional currency-Leg 2",
        "cleared": "Cleared",
        "venue": "Platform identifier",
        "block_trade": "Block trade election indicator",
        "prime_brokerage": "Prime brokerage transaction indicator",
        "package_trade": "Package indicator",
        "package_price": "Package transaction price",
        "package_price_currency": "Package transaction price currency",
        "package_price_notation": "Package transaction price notation",
        "package_spread": "Package transaction spread",
        "package_spread_notation": "Package transaction spread notation",
        "unique_product_identifier": "Unique Product Identifier",
        "upi_fisn": "UPI FISN",
        "underlier": "UPI Underlier Name",
    }

    event_timestamp: datetime | None = Field(
        default=None,
        description="Date and time the reported event occurred, in UTC. The tape is ordered"
        + " by it, newest first: a termination or correction of an old trade is dated when"
        + " it is reported now, not when the trade was struck.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Reported Time", "sort": "desc"}
        },
    )
    execution_timestamp: datetime = Field(
        description="Date and time the option was originally executed, in UTC. It equals the"
        + " reported time on a new trade, but predates it on an amendment or termination.",
        json_schema_extra={"x-widget_config": {"headerName": "Executed"}},
    )
    pair: str = Field(
        description="Currency pair of the option, its two reported legs.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Pair",
                "cellDataType": "text",
                "chartDataType": "category",
            }
        },
    )
    option_type: str | None = Field(
        default=None,
        description="Option family, read from the FISN: Vanilla, Non-Deliverable"
        + " (cash-settled, `settlement_currency` is the payout leg), Digital, Barrier, or"
        + " Target. Derived, not disseminated.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Type", "cellDataType": "text"}
        },
    )
    action_type: str | None = Field(
        default=None,
        description="Action reported: NEWT (new), MODI (modify), CORR (correct), TERM"
        + " (terminate), EROR (error), or REVI (revive). An amendment carries the original"
        + " trade's identifier in `original_trade_key`.",
        json_schema_extra={"x-widget_config": {"headerName": "Action"}},
    )
    call_currency: str | None = Field(
        default=None,
        description="Currency the option holder has the right to buy.",
        json_schema_extra={"x-widget_config": {"headerName": "Buy Ccy"}},
    )
    call_amount: float | None = Field(
        default=None,
        description="Notional of the currency bought, in `call_currency`.",
        json_schema_extra={"x-widget_config": {"headerName": "Buy Amount"}},
    )
    put_currency: str | None = Field(
        default=None,
        description="Currency the option holder has the right to sell.",
        json_schema_extra={"x-widget_config": {"headerName": "Sell Ccy"}},
    )
    put_amount: float | None = Field(
        default=None,
        description="Notional of the currency sold, in `put_currency`.",
        json_schema_extra={"x-widget_config": {"headerName": "Sell Amount"}},
    )
    strike: float | None = Field(
        default=None,
        description="Strike price of the option, oriented as `strike_pair` states.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Strike", "formatterFn": "none"}
        },
    )
    strike_pair: str | None = Field(
        default=None,
        description="Quotation the strike is expressed in, e.g. 'EUR/USD'. When absent, the"
        + " strike follows `exchange_rate_basis`.",
        json_schema_extra={"x-widget_config": {"headerName": "Strike Pair"}},
    )
    strike_notation: str | None = Field(
        default=None,
        description="Format the strike is expressed in, per the CFTC Part 43/45 spec:"
        + " 1 (a price, i.e. the exchange rate) or 3 (a decimal).",
        json_schema_extra={
            "x-widget_config": {"headerName": "Strike Notation", "hide": True}
        },
    )
    expiration_date: dateType | None = Field(
        default=None,
        description="Date the option expires.",
        json_schema_extra={"x-widget_config": {"headerName": "Expiry"}},
    )
    days_to_expiry: int | None = Field(
        default=None,
        description="Calendar days from execution to expiration.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Days to Expiry",
                "cellDataType": "number",
            }
        },
    )
    premium_amount: float | None = Field(
        default=None,
        description="Option premium paid, in `premium_currency`.",
        json_schema_extra={"x-widget_config": {"headerName": "Premium"}},
    )
    premium_currency: str | None = Field(
        default=None,
        description="Currency the premium is denominated in.",
        json_schema_extra={"x-widget_config": {"headerName": "Premium Ccy"}},
    )
    settlement_currency: str | None = Field(
        default=None,
        description="Currency a cash-settled option pays out in. Populated for"
        + " non-deliverable options, whose non-deliverable leg settles in this currency"
        + " rather than delivering.",
        json_schema_extra={"x-widget_config": {"headerName": "Settlement Ccy"}},
    )
    cleared: str | None = Field(
        default=None,
        description="Whether the transaction is centrally cleared: Y (cleared), N (not"
        + " cleared), or I (intent to clear).",
        json_schema_extra={"x-widget_config": {"headerName": "Cleared"}},
    )
    venue: str | None = Field(
        default=None,
        description="ISO 10383 segment MIC of the trading facility, or BILT when the"
        + " reporting counterparty could not determine the venue.",
        json_schema_extra={"x-widget_config": {"headerName": "Venue"}},
    )
    exchange_rate: float | None = Field(
        default=None,
        description="Posted exchange rate on the trade, oriented as `exchange_rate_basis`"
        + " states. A proxy for spot at execution, the pricing reference for the strike.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Exchange Rate", "formatterFn": "none"}
        },
    )
    exchange_rate_basis: str | None = Field(
        default=None,
        description="Quotation the exchange rate is expressed in, e.g. 'EUR/USD'.",
        json_schema_extra={"x-widget_config": {"headerName": "Exchange Rate Basis"}},
    )
    notional_1: float | None = Field(
        default=None,
        description="Leg 1 notional, in `notional_currency_1`.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Notional 1", "hide": True}
        },
    )
    notional_currency_1: str | None = Field(
        default=None,
        description="Currency of the leg 1 notional.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Notional Ccy 1", "hide": True}
        },
    )
    notional_2: float | None = Field(
        default=None,
        description="Leg 2 notional, in `notional_currency_2`.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Notional 2", "hide": True}
        },
    )
    notional_currency_2: str | None = Field(
        default=None,
        description="Currency of the leg 2 notional.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Notional Ccy 2", "hide": True}
        },
    )
    effective_date: dateType | None = Field(
        default=None,
        description="Date the option comes into effect.",
        json_schema_extra={"x-widget_config": {"headerName": "Effective Date"}},
    )
    first_exercise_date: dateType | None = Field(
        default=None,
        description="First date the option may be exercised.",
        json_schema_extra={"x-widget_config": {"headerName": "First Exercise"}},
    )
    event_type: str | None = Field(
        default=None,
        description="Reason for the action: TRAD (trade), NOVA (novation), ETRM (early"
        + " termination), EXER (exercise), or CLRG (clearing).",
        json_schema_extra={
            "x-widget_config": {"headerName": "Event Type", "hide": True}
        },
    )
    block_trade: bool | None = Field(
        default=None,
        description="Whether the print is reported as a block trade.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Block Trade", "hide": True}
        },
    )
    prime_brokerage: bool | None = Field(
        default=None,
        description="Whether the transaction is a prime-brokerage transaction.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Prime Brokerage", "hide": True}
        },
    )
    package_trade: bool | None = Field(
        default=None,
        description="Whether the print is one leg of a package transaction - a strategy"
        + " (straddle, risk reversal, calendar spread, ...) whose legs are negotiated and"
        + " priced together.",
        json_schema_extra={"x-widget_config": {"headerName": "Package"}},
    )
    package_id: str | None = Field(
        default=None,
        description="Grouping key shared by the legs of one package - its execution time"
        + " and package price or spread. Group on it to reassemble a strategy. Derived, not"
        + " disseminated.",
        json_schema_extra={"x-widget_config": {"headerName": "Package ID"}},
    )
    package_price: float | None = Field(
        default=None,
        description="Price of the whole package, in the format `package_price_notation`"
        + " states; the same on every leg. Present on price-quoted packages, where DTCC's"
        + " 9.9999999999 not-provided placeholder has been dropped to null.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Package Price", "formatterFn": "none"}
        },
    )
    package_price_currency: str | None = Field(
        default=None,
        description="Currency the package price is denominated in, when it is a monetary"
        + " amount.",
        json_schema_extra={"x-widget_config": {"headerName": "Package Price Ccy"}},
    )
    package_price_notation: str | None = Field(
        default=None,
        description="Format of `package_price`: 1 (a monetary amount, in"
        + " `package_price_currency`) or 3 (a decimal).",
        json_schema_extra={"x-widget_config": {"headerName": "Package Price Notation"}},
    )
    package_spread: float | None = Field(
        default=None,
        description="Spread of the whole package; the same on every leg. Present on"
        + " spread-quoted packages instead of a price.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Package Spread", "formatterFn": "none"}
        },
    )
    package_spread_notation: str | None = Field(
        default=None,
        description="Format of `package_spread`: 1 (a monetary amount) or 3 (a decimal).",
        json_schema_extra={
            "x-widget_config": {"headerName": "Package Spread Notation", "hide": True}
        },
    )
    upi_fisn: str | None = Field(
        default=None,
        description="ISO 18774 Financial Instrument Short Name, e.g. 'NA/O Van Call EUR"
        + " USD'. Its Call/Put label is unreliable; use the call and put currencies.",
        json_schema_extra={"x-widget_config": {"headerName": "UPI FISN", "hide": True}},
    )
    underlier: str | None = Field(
        default=None,
        description="UPI underlier name, the two legs of the pair as reported.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Underlier", "hide": True}
        },
    )
    unique_product_identifier: str | None = Field(
        default=None,
        description="ISO 4914 Unique Product Identifier.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Unique Product Identifier", "hide": True}
        },
    )
    dissemination_date: dateType = Field(
        description="Date the SDR publicly disseminated the print, being the report date"
        + " of the file it was published in.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Dissemination Date", "hide": True}
        },
    )
    trade_key: str | None = Field(
        default=None,
        description="Asset-class-qualified dissemination identifier, e.g."
        + " 'FX:4419821879000000101'. The qualifier keeps the 19-digit identifier out of"
        + " IEEE-754 double range, which truncates it past its 16th digit.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Trade",
                "cellDataType": "text",
                "formatterFn": "none",
            }
        },
    )
    original_trade_key: str | None = Field(
        default=None,
        description="For an action other than 'New', the qualified identifier of the"
        + " original trade being amended, corrected or terminated. Match it against a"
        + " `trade_key` to follow a trade's lifecycle.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Original Trade",
                "cellDataType": "text",
                "formatterFn": "none",
            }
        },
    )
    is_capped: bool | None = Field(
        default=None,
        description="Whether any amount on the print was disseminated at a reporting cap.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Is Capped", "hide": True}
        },
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_values(cls, values):
        """Drop empty strings, strip cap markers and separators, coerce boolean flags."""
        if not isinstance(values, dict):
            return values

        alias_to_field = {v: k for k, v in cls.__alias_dict__.items()}
        normalized: dict = {}
        capped = False

        for key, value in values.items():
            if not isinstance(value, str):
                if value is not None:
                    normalized[key] = value
                continue

            text = value.strip()

            if not text:
                continue

            field = alias_to_field.get(key, key)

            if field in _NUMERIC_FIELDS:
                if text.endswith("+"):
                    text = text[:-1]
                    capped = True

                text = text.replace(",", "")

                if not text or text in NOT_PROVIDED:
                    continue

            elif field in _BOOL_FIELDS:
                normalized[key] = text.strip().upper() == "TRUE"
                continue

            normalized[key] = text

        normalized.setdefault("is_capped", capped)

        return normalized


class CftcFxOptionTradesFetcher(
    Fetcher[CftcFxOptionTradesQueryParams, list[CftcFxOptionTradesData]]
):
    """DTCC Public Price Dissemination FX Option Trades Fetcher."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> CftcFxOptionTradesQueryParams:
        """Transform the query params."""
        return CftcFxOptionTradesQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: CftcFxOptionTradesQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch one dissemination date's option prints, by UPI search or forex file."""
        from openbb_cftc.utils.dtcc import get_latest_viable_slice, get_slice
        from openbb_cftc.utils.fx_options import extract_option_trades

        def _select(records: Iterable[dict], report_date: dateType) -> list[dict]:
            return extract_option_trades(
                records,
                dissemination_date=report_date,
                pair=query.pair,
                action_type=query.action_type,
                option_kind=query.option_type,
                settled=query.settlement_currency,
                min_notional=query.min_notional,
                ticker=query.ticker,
                limit=query.limit,
            )

        if query.ticker:
            from datetime import datetime, timedelta

            from openbb_cftc.utils.dtcc import MAX_LOOKBACK_DAYS
            from openbb_cftc.utils.search import search_trades
            from openbb_cftc.utils.swap import record_disseminated_day

            end_date = query.date or datetime.now(UTC).date()
            start_date = query.date or end_date - timedelta(days=MAX_LOOKBACK_DAYS - 1)
            records = await search_trades(
                "forex",
                start_date,
                end_date,
                upi=query.ticker.strip().upper(),
                use_cache=query.use_cache,
            )
            by_day: dict[str, list[dict]] = {}

            for record in records:
                day = record_disseminated_day(record) or ""

                if day:
                    by_day.setdefault(day, []).append(record)

            for day in sorted(by_day, reverse=True):
                prints = _select(by_day[day], dateType.fromisoformat(day))

                if prints:
                    return prints

            raise EmptyDataError(
                f"No FX option prints matched the query between"
                f" {start_date} and {end_date}."
            )

        if query.date:
            records = await get_slice(
                "forex", query.date.isoformat(), use_cache=query.use_cache
            )
            prints = _select(records, query.date)

            if not prints:
                raise EmptyDataError(
                    f"No FX option prints matched the query for {query.date.isoformat()}."
                )

            return prints

        records, report_date = await get_latest_viable_slice(
            "forex",
            lambda recs, day: bool(_select(recs, day)),
            use_cache=query.use_cache,
        )

        return _select(records, dateType.fromisoformat(report_date))

    @staticmethod
    def transform_data(
        query: CftcFxOptionTradesQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> AnnotatedResult[list[CftcFxOptionTradesData]]:
        """Validate the prints and insert metadata."""
        from openbb_cftc.utils.dtcc import qualified_keys

        results = [
            CftcFxOptionTradesData.model_validate({**d, **qualified_keys(d)})
            for d in data
        ]

        return AnnotatedResult(
            result=results,
            metadata={
                "dissemination_date": results[0].dissemination_date.isoformat(),
                "prints": len(results),
                "pairs": sorted({r.pair for r in results if r.pair}),
                "option_types": sorted(
                    {r.option_type for r in results if r.option_type}
                ),
                "capped_prints": sum(1 for r in results if r.is_capped),
            },
        )
