"""DTCC Swap Valuation Model."""

from collections.abc import Iterable
from datetime import (
    UTC,
    date as dateType,
)
from typing import Any, Literal

from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field, field_validator


class CftcSwapValuationQueryParams(QueryParams):
    """DTCC Swap Valuation Query Parameters."""

    __json_schema_extra__ = {
        "currency": {"multiple_items_allowed": False},
        "side": {"multiple_items_allowed": False},
    }

    currency: str = Field(
        default="USD",
        description="Currency of the swap, priced off that currency's reported rate curve -"
        + " its OIS, or its fixed-vs-floating IRS when it has no OIS (CNY, TWD, MYR, ...).",
    )
    dissemination_identifier: str | None = Field(
        default=None,
        description="The disseminated trade to value, as printed on the Swap Transactions"
        + " tape. Any non-matured print is valuable by its own identifier. Default is the"
        + " day's largest standalone par print; a package leg or off-par print's rate may"
        + " reflect a package structure rather than a market level, flagged"
        + " `is_vanilla_par` in the metadata rather than excluded.",
    )
    trade_date: dateType | None = Field(
        default=None,
        description="Dissemination date the trade printed on (UTC). Default is the curve"
        + " date, today's tape; an older print is looked up on the day it was disseminated"
        + " and valued on its remaining life against the current curve. Slices are"
        + " retained for 366 days.",
    )
    side: Literal["pay", "receive"] = Field(
        default="pay",
        description="Whether the position pays or receives the fixed rate. The net present"
        + " value is signed to this side; dissemination does not say which side either"
        + " counterparty took.",
    )
    min_notional: float = Field(
        default=0.0,
        description="Only consider prints at least this large when defaulting to the day's"
        + " largest. Ignored when a dissemination identifier is given.",
    )
    date: dateType | None = Field(
        default=None,
        description="Dissemination date (UTC) of the trades and the rate curve. Default is"
        + " the most recent published. History is retained for 366 days.",
        json_schema_extra={"x-widget_config": {"value": "$currentDate"}},
    )
    min_trades: int = Field(
        default=1,
        description="Minimum trades for a curve node. The default keeps every traded tenor,"
        + " because thin EM curves would otherwise lose their pillars.",
    )
    use_cache: bool = Field(
        default=True,
        description="Cache the source data locally, revalidating against the source ETag.",
    )

    @field_validator("currency", mode="before")
    @classmethod
    def _to_upper(cls, v):
        """Accept a currency in any case."""
        return v.upper() if isinstance(v, str) else v

    @field_validator("dissemination_identifier", mode="before")
    @classmethod
    def _drop_qualifier(cls, v):
        """Accept the asset-class-qualified trade key printed on the tape."""
        return v.rsplit(":", 1)[-1].strip() if isinstance(v, str) else v


class CftcSwapValuationData(Data):
    """DTCC Swap Valuation Data."""

    period: int = Field(
        description="Coupon period, ordered from the first payment to maturity.",
        json_schema_extra={"x-widget_config": {"headerName": "Period"}},
    )
    start_date: dateType = Field(
        description="Start of the accrual period.",
        json_schema_extra={"x-widget_config": {"headerName": "Start"}},
    )
    payment_date: dateType = Field(
        description="Payment date at the end of the accrual period.",
        json_schema_extra={"x-widget_config": {"headerName": "Payment"}},
    )
    year_fraction: float = Field(
        description="Accrual year fraction of the period, on the currency's money-market"
        + " day count.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Year Frac", "decimalPlaces": 4}
        },
    )
    discount_factor: float = Field(
        description="Discount factor to the payment date, off the bootstrapped curve.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Discount Factor",
                "cellDataType": "number",
                "formatterFn": "none",
                "decimalPlaces": 6,
            }
        },
    )
    forward_rate: float | None = Field(
        default=None,
        description="Curve-implied forward rate for the period, in percent. Reported on"
        + " the fixed leg's rows where the floating leg's periods align with them.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Forward Rate",
                "cellDataType": "number",
                "decimalPlaces": 4,
            }
        },
    )
    floating_rate: float | None = Field(
        default=None,
        description="Floating rate applied to the period, in percent - the curve's implied"
        + " forward plus the contract spread.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Floating Rate",
                "cellDataType": "number",
                "decimalPlaces": 4,
            }
        },
    )
    notional: float = Field(
        description="Notional outstanding over the period, as the trade reported it - an"
        + " amortising schedule steps down.",
        json_schema_extra={"x-widget_config": {"headerName": "Notional"}},
    )
    fixed_rate: float = Field(
        description="Fixed rate applied to the period, in percent - the rate the trade"
        + " printed at.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Fixed Rate",
                "cellDataType": "number",
                "decimalPlaces": 4,
            }
        },
    )
    fixed_cashflow: float = Field(
        description="Fixed-leg cash flow paid at the payment date.",
        json_schema_extra={"x-widget_config": {"headerName": "Fixed Cashflow"}},
    )
    fixed_pv: float = Field(
        description="Present value of the fixed-leg cash flow.",
        json_schema_extra={"x-widget_config": {"headerName": "Fixed PV"}},
    )
    floating_cashflow: float | None = Field(
        default=None,
        description="Floating-leg cash flow at the period's forward rate.",
        json_schema_extra={"x-widget_config": {"headerName": "Floating Cashflow"}},
    )
    floating_pv: float | None = Field(
        default=None,
        description="Present value of the floating-leg cash flow.",
        json_schema_extra={"x-widget_config": {"headerName": "Floating PV"}},
    )
    index_ratio: float | None = Field(
        default=None,
        description="Total index ratio applied to the period on an inflation swap -"
        + " the reference index at maturity over the trade's base index.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Index Ratio",
                "cellDataType": "number",
                "formatterFn": "none",
                "decimalPlaces": 6,
            }
        },
    )
    realized_ratio: float | None = Field(
        default=None,
        description="The part of the index ratio already fixed by published index"
        + " levels, on a seasoned inflation swap.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Realized Ratio",
                "cellDataType": "number",
                "formatterFn": "none",
                "decimalPlaces": 6,
            }
        },
    )
    projected_ratio: float | None = Field(
        default=None,
        description="The part of the index ratio still projected off the curve's"
        + " forward breakeven, on an inflation swap.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Projected Ratio",
                "cellDataType": "number",
                "formatterFn": "none",
                "decimalPlaces": 6,
            }
        },
    )


def _realized_metadata(query, trade, fixings, curve_date, rates, currency) -> dict:
    """Realized carry from published fixings, signed to the side, or its absence."""
    from openbb_cftc.utils.curve import curve_day_count_basis, curve_payment_period
    from openbb_cftc.utils.swap import realized_carry

    if trade["effective_date"] >= curve_date:
        return {"settled_carry": 0.0, "accrued_carry": 0.0}

    if not fixings:
        return {
            "settled_carry": None,
            "accrued_carry": None,
            "carry_note": "The elapsed floating accrual compounds the"
            " index's published fixings, which are not available for this trade.",
        }

    carry = realized_carry(
        trade,
        fixings,
        curve_date,
        curve_day_count_basis(rates, currency, curve_date, query.min_trades),
        curve_payment_period(rates, currency, curve_date, query.min_trades),
    )

    if carry is None:
        return {
            "settled_carry": None,
            "accrued_carry": None,
            "carry_note": "The published fixings do not cover the trade's"
            " elapsed accrual span.",
        }

    sign = 1.0 if query.side == "pay" else -1.0
    settled = carry["floating_settled"] - carry["fixed_settled"]
    accrued = carry["floating_accrued"] - carry["fixed_accrued"]

    return {
        "floating_settled": round(carry["floating_settled"], 2),
        "fixed_settled": round(carry["fixed_settled"], 2),
        "floating_accrued": round(carry["floating_accrued"], 2),
        "fixed_accrued": round(carry["fixed_accrued"], 2),
        "settled_carry": round(sign * settled, 2),
        "accrued_carry": round(sign * accrued, 2),
    }


def _spread_realized_metadata(query, trade, fixings, curve_date, rates) -> dict:
    """Realized carry for a basis/cross-currency trade, from both legs' own published."""
    from openbb_cftc.utils.curve import curve_day_count_basis, curve_payment_period
    from openbb_cftc.utils.swap import spread_realized_carry

    if trade["effective_date"] >= curve_date:
        return {"settled_carry": 0.0, "accrued_carry": 0.0}

    spread_fixings = fixings.get("spread") or {}
    other_fixings = fixings.get("other") or {}

    if not spread_fixings or not other_fixings:
        return {
            "settled_carry": None,
            "accrued_carry": None,
            "carry_note": "The elapsed accrual compounds both legs' own"
            " published fixings; one or both indices are not available for this"
            " trade.",
        }

    carry = spread_realized_carry(
        trade,
        spread_fixings,
        other_fixings,
        curve_date,
        curve_day_count_basis(rates, trade["currency"], curve_date, query.min_trades),
        curve_payment_period(rates, trade["currency"], curve_date, query.min_trades),
    )

    if carry is None:
        return {
            "settled_carry": None,
            "accrued_carry": None,
            "carry_note": "The published fixings do not cover the trade's"
            " elapsed accrual span.",
        }

    sign = 1.0 if query.side == "pay" else -1.0
    settled = carry["spread_leg_settled"] - carry["other_leg_settled"]
    accrued = carry["spread_leg_accrued"] - carry["other_leg_accrued"]

    return {
        "spread_leg_settled": round(carry["spread_leg_settled"], 2),
        "other_leg_settled": round(carry["other_leg_settled"], 2),
        "spread_leg_accrued": round(carry["spread_leg_accrued"], 2),
        "other_leg_accrued": round(carry["other_leg_accrued"], 2),
        "settled_carry": round(sign * settled, 2),
        "accrued_carry": round(sign * accrued, 2),
    }


def _economics_metadata(trade: dict, query, metadata: dict) -> None:
    """Fold the print's disseminated other payments into its net economics."""
    payments = trade.get("other_payments") or []
    currency = metadata["currency"]

    if payments:
        metadata["other_payments"] = [
            {
                "type": p["type"],
                "amount": round(p["amount"], 2),
                "currency": p["currency"],
            }
            for p in payments
        ]

    if trade.get("package_indicator"):
        metadata["package_indicator"] = True

    if trade.get("package_price"):
        metadata["package_price"] = round(trade["package_price"]["amount"], 2)
        metadata["package_price_currency"] = trade["package_price"]["currency"]

    upfront = sum(
        p["amount"]
        for p in payments
        if p["type"] == "UFRO" and (p["currency"] or currency) == currency
    )

    if any(
        p["type"] == "UFRO" and p["currency"] and p["currency"] != currency
        for p in payments
    ):
        metadata["other_payment_note"] = (
            "Upfront amounts in currencies other than the trade currency are"
            " reported in other_payments, not netted into entry_cost."
        )

    npv = metadata["npv"]
    entry_cost = 0.0

    if upfront:
        metadata["upfront_amount"] = round(upfront, 2)
        entry_cost = upfront if npv >= 0 else -upfront
        metadata["entry_cost"] = round(entry_cost, 2)

    carry = (metadata.get("settled_carry") or 0.0) + (
        metadata.get("accrued_carry") or 0.0
    )
    net = npv + carry - entry_cost
    metadata["net_pnl"] = round(net, 2)
    net_pay = net if query.side == "pay" else -net
    metadata["winning_side"] = (
        "pay" if net_pay > 0 else "receive" if net_pay < 0 else "flat"
    )


class CftcSwapValuationFetcher(
    Fetcher[CftcSwapValuationQueryParams, list[CftcSwapValuationData]]
):
    """DTCC Swap Valuation Fetcher."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> CftcSwapValuationQueryParams:
        """Transform the query params."""
        return CftcSwapValuationQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: CftcSwapValuationQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> tuple[dict, Iterable[dict], str, dict, str, str]:
        """Fetch the selected trade's own record, the curve slice, and its realized fixings."""
        from datetime import datetime

        from openbb_core.app.model.abstract.error import OpenBBError

        from openbb_cftc.utils import store
        from openbb_cftc.utils.constants import OIS_INDICES
        from openbb_cftc.utils.dtcc import (
            get_latest_viable_slice,
            get_rates_slice_for,
            get_slice,
        )
        from openbb_cftc.utils.fixings import get_fixings, index_for_underlier
        from openbb_cftc.utils.search import search_trades
        from openbb_cftc.utils.swap import (
            classify_rates_swap,
            extract_spread_trade,
            parse_spread,
            record_disseminated_day,
            select_swap_trade,
        )

        report_date = (
            query.date.isoformat()
            if query.date
            else datetime.now(UTC).date().isoformat()
        )
        currency = query.currency
        other_currency: str | None = None
        raw_record: dict | None = None
        trade_date_str = query.trade_date.isoformat() if query.trade_date else None

        if query.dissemination_identifier and query.trade_date is None:
            target = query.dissemination_identifier.strip()
            raw_record = store.get_trade_record(query.dissemination_identifier)

            if raw_record is not None:
                trade_date_str = record_disseminated_day(raw_record)
            else:

                def _carries_trade(recs: Iterable[dict], _day) -> bool:
                    nonlocal raw_record

                    for record in recs:
                        candidate = (
                            record.get("Dissemination Identifier") or ""
                        ).strip()

                        if candidate == target:
                            raw_record = record
                            return True

                    return False

                try:
                    _, trade_date_str = await get_latest_viable_slice(
                        "rates",
                        _carries_trade,
                        use_cache=query.use_cache,
                        end_date=report_date,
                    )
                except OpenBBError as exc:
                    today_date = datetime.now(UTC).date()
                    search_records = await search_trades(
                        "rates",
                        start_date=today_date,
                        end_date=today_date,
                        use_cache=query.use_cache,
                    )

                    if not _carries_trade(search_records, today_date):
                        from openbb_core.provider.utils.errors import EmptyDataError

                        from openbb_cftc.utils.dtcc import MAX_LOOKBACK_DAYS

                        raise EmptyDataError(
                            f"'{query.dissemination_identifier}' was not found in"
                            f" the {MAX_LOOKBACK_DAYS} days of published files to"
                            f" {report_date}."
                        ) from exc

                    trade_date_str = today_date.isoformat()

                if raw_record is not None:
                    found_day = record_disseminated_day(raw_record)

                    if found_day:
                        store.write_search_records("IR", found_day, [raw_record])

            if raw_record is not None:
                today = datetime.now(UTC).date()
                trade_type = classify_rates_swap(raw_record, today)
                spread = (
                    parse_spread(raw_record)
                    if trade_type in ("basis", "cross_currency")
                    else None
                )
                leg = spread[0] if spread else 1
                currency = (
                    raw_record.get(f"Notional currency-Leg {leg}") or ""
                ).strip() or currency

                if trade_type == "cross_currency":
                    other_leg = 2 if leg == 1 else 1
                    other_currency = (
                        raw_record.get(f"Notional currency-Leg {other_leg}") or ""
                    ).strip() or None

        anchor = [currency] if currency in OIS_INDICES else ["USD"]

        if other_currency and other_currency not in anchor:
            anchor.append(other_currency)

        rates, rates_date = await get_rates_slice_for(
            report_date, anchor, query.use_cache
        )
        curve_date = dateType.fromisoformat(rates_date)

        if (
            raw_record is not None
            and classify_rates_swap(raw_record, curve_date) == "inflation"
        ):
            from openbb_cftc.utils.swap import extract_inflation_trade

            trade = extract_inflation_trade(
                raw_record, curve_date, min_notional=query.min_notional
            )

            if trade is None:
                from openbb_core.provider.utils.errors import EmptyDataError

                raise EmptyDataError(
                    f"'{query.dissemination_identifier}' has no priceable"
                    + " zero-coupon inflation terms."
                )
        elif raw_record is not None and classify_rates_swap(raw_record, curve_date) in (
            "basis",
            "cross_currency",
        ):
            trade = extract_spread_trade(
                raw_record, curve_date, min_notional=query.min_notional
            )

            if trade is None:
                from openbb_core.provider.utils.errors import EmptyDataError

                raise EmptyDataError(
                    f"'{query.dissemination_identifier}' has no priceable"
                    + " spread-leg terms - an unpriced spread on both legs, or (for a"
                    + " cross-currency print) a missing or non-positive other-leg"
                    + " notional."
                )
        elif raw_record is not None:
            trade = select_swap_trade(
                [raw_record],
                currency,
                curve_date,
                dissemination_identifier=query.dissemination_identifier,
                min_notional=query.min_notional,
            )
        else:
            if query.trade_date and query.trade_date.isoformat() != rates_date:
                trade_records = await get_slice(
                    "rates", query.trade_date.isoformat(), use_cache=query.use_cache
                )
            else:
                trade_records = rates

            trade = select_swap_trade(
                trade_records,
                currency,
                curve_date,
                dissemination_identifier=query.dissemination_identifier,
                min_notional=query.min_notional,
            )

        if trade_date_str is None:
            trade_date_str = rates_date

        fixings: dict = {}

        if trade.get("trade_type") == "inflation":
            from openbb_cftc.utils.inflation import (
                build_breakeven_curve,
                get_inflation_index,
            )

            if not build_breakeven_curve(rates, currency, curve_date, query.min_trades):
                try:
                    breakevens, breakeven_date = await get_latest_viable_slice(
                        "rates",
                        lambda recs, day: bool(
                            build_breakeven_curve(recs, currency, day, query.min_trades)
                        ),
                        use_cache=query.use_cache,
                        end_date=rates_date,
                    )
                    fixings["breakeven_records"] = breakevens
                    fixings["breakeven_date"] = breakeven_date
                except OpenBBError:
                    pass

            if trade["index"] and trade["effective_date"] < curve_date:
                try:
                    fixings["levels"] = await get_inflation_index(
                        trade["index"], use_cache=query.use_cache
                    )
                except OpenBBError:
                    fixings["levels"] = {}
        elif "traded_spread" in trade:
            if trade["effective_date"] < curve_date:

                async def _leg_fixings(index: str | None) -> dict:
                    if index is None:
                        return {}

                    return await get_fixings(
                        index,
                        trade["effective_date"],
                        curve_date,
                        use_cache=query.use_cache,
                    )

                fixings = {
                    "spread": await _leg_fixings(trade["spread_index"]),
                    "other": await _leg_fixings(trade["other_index"]),
                }

            if trade["trade_type"] == "cross_currency":
                from openbb_core.provider.utils.errors import EmptyDataError

                from openbb_cftc.utils.fx_vol import fx_spot

                fx_records = await get_slice(
                    "forex", rates_date, use_cache=query.use_cache
                )
                spot = fx_spot(
                    fx_records, trade["other_currency"], currency, curve_date
                )

                if spot is None:
                    raise EmptyDataError(
                        f"No {trade['other_currency']}/{currency} spot could be"
                        + f" established from forex prints on {rates_date}."
                    )

                fixings["spot"] = spot
        else:
            index = index_for_underlier(trade["underlier"])

            if trade["effective_date"] < curve_date and index is not None:
                fixings = await get_fixings(
                    index,
                    trade["effective_date"],
                    curve_date,
                    use_cache=query.use_cache,
                )

        return trade, rates, rates_date, fixings, currency, trade_date_str

    @staticmethod
    def transform_data(
        query: CftcSwapValuationQueryParams,
        data: tuple[dict, Iterable[dict], str, dict, str, str],
        **kwargs: Any,
    ) -> AnnotatedResult[list[CftcSwapValuationData]]:
        """Value the selected disseminated trade on its own terms and insert the summary."""
        from openbb_cftc.utils.swap import (
            value_cross_currency_swap,
            value_inflation_swap,
            value_spread_swap,
            value_swap,
        )

        trade, rates, rates_date, fixings, currency, trade_date_str = data
        curve_date = dateType.fromisoformat(rates_date)
        is_spread_trade = "traded_spread" in trade
        is_cross_currency = trade.get("trade_type") == "cross_currency"
        is_inflation = trade.get("trade_type") == "inflation"

        if is_inflation:
            breakeven_date = fixings.get("breakeven_date")
            schedule, summary = value_inflation_swap(
                rates,
                trade,
                curve_date,
                levels=fixings.get("levels"),
                side=query.side,
                min_trades=query.min_trades,
                breakeven_records=fixings.get("breakeven_records"),
                breakeven_date=(
                    dateType.fromisoformat(breakeven_date) if breakeven_date else None
                ),
            )
            contract_rate = trade["traded_breakeven"]
        elif is_cross_currency:
            schedule, summary = value_cross_currency_swap(
                rates,
                trade,
                curve_date,
                fixings["spot"],
                side=query.side,
                min_trades=query.min_trades,
            )
            contract_rate = trade["traded_spread"]
        elif is_spread_trade:
            schedule, summary = value_spread_swap(
                rates, trade, curve_date, side=query.side, min_trades=query.min_trades
            )
            contract_rate = trade["traded_spread"]
        else:
            schedule, summary = value_swap(
                rates,
                currency=currency,
                trade_date=curve_date,
                maturity_days=trade["maturity_days"],
                fixed_rate=trade["fixed_rate"],
                notional=trade["notional"],
                side=query.side,
                min_trades=query.min_trades,
                start_days=trade["start_days"],
                fixed_schedule=trade["fixed_schedule"],
                floating_schedule=trade["floating_schedule"],
                fixed_basis=trade["fixed_basis"],
                floating_basis=trade["floating_basis"],
                fixed_frequency=trade["fixed_frequency"],
                floating_frequency=trade["floating_frequency"],
            )
            contract_rate = trade["fixed_rate"]

        for row in schedule:
            row["fixed_rate"] *= 100.0

            if row.get("forward_rate") is not None:
                row["forward_rate"] *= 100.0
                row["floating_rate"] *= 100.0

        metadata = {
            "dissemination_identifier": trade["dissemination_identifier"],
            "trade_key": trade.get("trade_key"),
            "upi_fisn": trade["upi_fisn"],
            "trade_date": trade_date_str,
            "winning_side": "pay" if summary["par_rate"] > contract_rate else "receive",
            "currency": currency,
            "curve_date": rates_date,
            "effective_date": trade["effective_date"].isoformat(),
            "expiration_date": trade["expiration_date"].isoformat(),
            "notional": trade["notional"],
            "notional_capped": trade["is_capped"],
            "cleared": trade["cleared"],
            "side": query.side,
            "fixed_rate": round(contract_rate * 100.0, 6),
            "par_rate": round(summary["par_rate"] * 100.0, 6),
            "annuity": round(summary["annuity"], 6),
            "fixed_leg_pv": round(summary["fixed_leg_pv"], 2),
            "floating_leg_pv": round(summary["floating_leg_pv"], 2),
            "npv": round(summary["npv"], 2),
            "dv01": round(summary["dv01"], 2),
        }

        if is_inflation:
            metadata.update(
                trade_type=trade["trade_type"],
                underlier=trade["underlier"],
                inflation_index=trade["index"],
                index_ratio=round(summary["index_ratio"], 8),
                realized_ratio=round(summary["realized_ratio"], 8)
                if summary["realized_ratio"] is not None
                else None,
                projected_ratio=round(summary["projected_ratio"], 8),
                forward_breakeven=round(summary["forward_breakeven"] * 100.0, 6),
                elapsed_years=round(summary["elapsed_years"], 4),
                remaining_years=round(summary["remaining_years"], 4),
                reference_trade_count=summary["reference_count"],
                breakeven_date=summary["breakeven_date"].isoformat(),
                settled_carry=None,
                accrued_carry=None,
            )
        elif is_cross_currency:
            metadata.update(
                trade_type=trade["trade_type"],
                underlier=trade["underlier"],
                other_currency=trade["other_currency"],
                spot=fixings["spot"],
                exchange_pv=round(summary["exchange_pv"], 2),
                **_spread_realized_metadata(query, trade, fixings, curve_date, rates),
            )
        elif is_spread_trade:
            metadata.update(
                trade_type=trade["trade_type"],
                underlier=trade["underlier"],
                reference_trade_count=summary["reference_trade_count"],
                **_spread_realized_metadata(query, trade, fixings, curve_date, rates),
            )
        else:
            metadata.update(
                is_vanilla_par=trade["is_vanilla_par"],
                **_realized_metadata(
                    query, trade, fixings, curve_date, rates, currency
                ),
            )

        _economics_metadata(trade, query, metadata)

        return AnnotatedResult(
            result=[CftcSwapValuationData.model_validate(r) for r in schedule],
            metadata=metadata,
        )
