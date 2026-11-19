"""DTCC Overnight Index Swap Curve Model."""

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
from pydantic import ConfigDict, Field, field_validator


async def _latest_fixing(
    currency: str, on_or_before: dateType, use_cache: bool
) -> tuple[dateType, float] | None:
    """Return the currency's freshest published overnight fixing on or before a date."""
    from datetime import timedelta

    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_cftc.utils.constants import FIXED_FLOAT_CURVE_SPECS, OIS_INDICES
    from openbb_cftc.utils.fixings import get_fixings

    spec = OIS_INDICES.get(currency) or FIXED_FLOAT_CURVE_SPECS[currency]
    index = spec.get("overnight_index") or spec["index"]

    try:
        fixings = await get_fixings(
            index,
            on_or_before - timedelta(days=14),
            on_or_before,
            use_cache=use_cache,
        )
    except OpenBBError:
        return None

    days = [day for day in fixings if day <= on_or_before]

    if not days:
        return None

    day = max(days)

    return day, fixings[day]


class CftcOisCurveQueryParams(QueryParams):
    """DTCC Overnight Index Swap Curve Query Parameters."""

    __json_schema_extra__ = {
        "currency": {"multiple_items_allowed": False},
        "curve_type": {"multiple_items_allowed": False},
        "granularity": {"multiple_items_allowed": False},
        "aggregation": {"multiple_items_allowed": False},
        "source": {"multiple_items_allowed": False},
        "interpolation": {"multiple_items_allowed": False},
    }

    currency: Literal[
        "USD",
        "EUR",
        "GBP",
        "JPY",
        "CAD",
        "CHF",
        "MXN",
        "SGD",
        "INR",
        "COP",
        "ZAR",
        "CLP",
        "THB",
        "ILS",
        "BRL",
        "CNY",
    ] = Field(
        default="USD",
        description="Currency of the swap curve. Each maps to that currency's overnight"
        + " benchmark rate. Currencies whose overnight index swaps are too thinly"
        + " reported to bootstrap a curve are not offered. CNY builds from FR007"
        + " fixed-float swaps, backstopped by the CFETS daily bulletin's traded curve.",
    )
    curve_type: Literal["par", "zero"] = Field(
        default="par",
        description="Which representation of the curve to return in `rate`: the par swap"
        + " rate or the annually compounded zero rate. The forward curve is a separate"
        + " endpoint, `ois_forward_curve`.",
    )
    source: Literal["search", "slice"] = Field(
        default="search",
        description="Where the trades come from. 'search' queries a window of"
        + " dissemination days and prices each tenor from the most recent day it"
        + " traded in depth. 'slice' uses a single day's cumulative file, walking a"
        + " weekend or holiday back to the most recent day that priced this currency,"
        + " which still leaves sparse tenors missing.",
    )
    date: dateType | None = Field(
        default=None,
        description="Dissemination date (UTC). With source='search' this ends the"
        + " lookback window, and defaults to today. With source='slice' it selects the"
        + " most recent day on or before it that priced this currency, defaulting to"
        + " the latest. History is retained for 366 days.",
        json_schema_extra={"x-widget_config": {"value": "$currentDate"}},
    )
    lookback_days: int = Field(
        default=7,
        ge=1,
        le=365,
        description="Number of dissemination days to look back over, ending on `date`."
        + " With source='search' a longer window fills in more tenors, at the cost of"
        + " pricing the thin ones further from today; check `staleness_days` and cap it"
        + " with `max_staleness_days`. A thinly traded currency reaches a full curve only"
        + " over a long window - the search chains 180-day sub-windows up to the one-year"
        + " horizon. With source='slice' it is how far back to walk for the most recent"
        + " day that priced this currency.",
    )
    max_staleness_days: int | None = Field(
        default=None,
        ge=0,
        description="Drop any node whose freshest print is older than this many days,"
        + " measured from the curve's own date. A wide `lookback_days` fills thin tenors"
        + " but resurrects some that last traded months ago in a different rate regime;"
        + " capping staleness keeps the curve current rather than a mosaic of old levels."
        + " Only meaningful with source='search'. None keeps every live node and reports"
        + " its age in `staleness_days`. Nodes that have already matured by the curve date"
        + " are always dropped, cap or none.",
    )
    granularity: Literal["benchmark", "observed"] = Field(
        default="benchmark",
        description="Tenor axis of the curve. 'benchmark' snaps trades to standard nodes;"
        + " 'observed' emits a node for every distinct tenor traded, including broken dates.",
    )
    aggregation: Literal["median", "mean", "vwap"] = Field(
        default="median",
        description="How each node's executed rates are reduced to a par rate."
        + " Median is the default because notionals above the reporting cap are"
        + " disseminated at the cap, which biases notional-weighted averages.",
    )
    min_trades: int = Field(
        default=1,
        description="Drop nodes priced by fewer than this many trades on their as-of day."
        + " The default keeps every node, because one executed trade is still a price;"
        + " `num_trades`, `min_rate` and `max_rate` say how thin it is. Raise it to admit"
        + " only nodes several trades agree on, at the cost of losing the tenors a thin"
        + " currency never trades in depth on any single day.",
    )
    cleared: bool = Field(
        default=False,
        description="Keep only centrally cleared or intent-to-clear trades, dropping the"
        + " bilateral uncleared prints that carry most of the off-market noise. Most"
        + " useful with granularity='observed', where thin nodes are exposed to it.",
    )
    interpolation: Literal["log_linear", "log_cubic"] = Field(
        default="log_linear",
        description="How discount factors are interpolated between pillars, on the log"
        + " of the discount factor. 'log_linear' is piecewise linear, giving"
        + " piecewise-flat instantaneous forwards. 'log_cubic' is a monotone Hermite"
        + " cubic, giving smooth forwards without overshooting into negative rates.",
    )
    overnight_anchor: bool = Field(
        default=False,
        description="Anchor the curve's front end with the benchmark's latest published"
        + " overnight fixing, as a 1-day node. The fixing is a realized rate, so the"
        + " node carries no trades and its own as-of date.",
    )
    use_cache: bool = Field(
        default=True,
        description="Cache the source data locally. Closed dissemination days are"
        + " immutable and are never re-fetched; daily files are revalidated against"
        + " the source ETag.",
    )

    @field_validator("currency", mode="before")
    @classmethod
    def _to_upper(cls, v):
        """Accept a currency in any case."""
        return v.upper() if isinstance(v, str) else v


class CftcOisCurveData(Data):
    """DTCC Overnight Index Swap Curve Data."""

    model_config = ConfigDict(extra="ignore")

    date: dateType = Field(
        description="Date of the curve, being that of its freshest node.",
        json_schema_extra={"x-widget_config": {"chartDataType": "excluded"}},
    )
    currency: str = Field(
        description="Currency of the curve.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Currency", "chartDataType": "excluded"}
        },
    )
    benchmark: str = Field(
        description="Overnight benchmark rate the swaps reference (SOFR, ESTR, ...).",
        json_schema_extra={
            "x-widget_config": {"headerName": "Benchmark", "chartDataType": "excluded"}
        },
    )
    index: str = Field(
        description="Curve index plotted on the chart and used as the row index: the tenor"
        + " label under 'benchmark' granularity, else the node's maturity date under"
        + " 'observed' granularity.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Index",
                "cellDataType": "text",
                "chartDataType": "category",
            }
        },
    )
    as_of_date: dateType | None = Field(
        default=None,
        description="Dissemination date the node's trades were reported on. Nodes are"
        + " priced from the most recent day that cleared min_trades, so a thin tenor"
        + " is dated earlier than a deep one.",
        json_schema_extra={
            "x-widget_config": {"headerName": "As Of", "chartDataType": "excluded"}
        },
    )
    staleness_days: int | None = Field(
        default=None,
        description="Days between the node's as-of date and the curve's date."
        + " Zero on the freshest nodes.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Staleness (Days)",
                "cellDataType": "number",
                "chartDataType": "excluded",
            }
        },
    )
    tenor: str = Field(
        description="Tenor of the curve node.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Tenor",
                "cellDataType": "text",
                "chartDataType": "excluded",
            }
        },
    )
    tenor_days: int = Field(
        description="Tenor of the node, in days.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Tenor (Days)",
                "cellDataType": "number",
                "chartDataType": "excluded",
            }
        },
    )
    tenor_years: float = Field(
        description="Tenor of the node, in years, on an ACT/365F basis.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Tenor (Years)",
                "cellDataType": "number",
                "chartDataType": "excluded",
            }
        },
    )
    maturity_date: dateType = Field(
        description="Maturity date implied by the node's tenor, from its as-of date."
        + " Under 'observed' granularity this is also the curve's index.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Maturity Date",
                "cellDataType": "date",
                "chartDataType": "excluded",
            }
        },
    )
    rate: float | None = Field(
        default=None,
        description="Rate of the selected `curve_type` at the node, in percent (4.32 is"
        + " 4.32%): the par swap rate or the annually compounded zero rate. In percent"
        + " rather than a decimal so the chart axis reads as a rate - the grid formatter is"
        + " not applied to the chart. Omitted where the bootstrap degenerates.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Rate",
                "cellDataType": "number",
                "chartDataType": "series",
                "formatterFn": "percent",
            },
        },
    )
    curve_type: str = Field(
        description="Which representation `rate` holds: par or zero.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Curve Type", "chartDataType": "excluded"}
        },
    )
    discount_factor: float | None = Field(
        default=None,
        description="Discount factor bootstrapped to the node's maturity.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Discount Factor",
                "cellDataType": "number",
                "chartDataType": "excluded",
                "formatterFn": "none",
            }
        },
    )
    day_count: str | None = Field(
        default=None,
        description="Fixed-leg day count convention the node's trades reported, used to"
        + " accrue the fixed leg in the bootstrap. ACT/360 for USD, EUR, CHF, MXN, COP"
        + " and CLP; ACT/365F for GBP, JPY, CAD, SGD, INR, ZAR, THB, ILS, AUD and NZD."
        + " BRL reports BUS/252, recovered to the same year fraction on calendar days.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Day Count", "hide": True}
        },
    )
    num_trades: int = Field(
        description="Number of executed trades aggregated into the node.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Trades",
                "cellDataType": "number",
                "chartDataType": "excluded",
            }
        },
    )
    total_notional: float | None = Field(
        default=None,
        description="Sum of the leg 1 notional of the node's trades.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Total Notional",
                "cellDataType": "number",
                "chartDataType": "excluded",
            }
        },
    )
    min_rate: float | None = Field(
        default=None,
        description="Lowest executed rate at the node, in percent (4.32 is 4.32%).",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Min Rate",
                "cellDataType": "number",
                "chartDataType": "excluded",
                "formatterFn": "percent",
            },
        },
    )
    max_rate: float | None = Field(
        default=None,
        description="Highest executed rate at the node, in percent (4.32 is 4.32%).",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Max Rate",
                "cellDataType": "number",
                "chartDataType": "excluded",
                "formatterFn": "percent",
            },
        },
    )
    is_capped: bool | None = Field(
        default=None,
        description="Whether any trade at the node had its notional disseminated at the"
        + " reporting cap.",
        json_schema_extra={"x-widget_config": {"headerName": "Is Capped"}},
    )


class CftcOisCurveFetcher(Fetcher[CftcOisCurveQueryParams, list[CftcOisCurveData]]):
    """DTCC Overnight Index Swap Curve Fetcher."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> CftcOisCurveQueryParams:
        """Transform the query params."""
        return CftcOisCurveQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: CftcOisCurveQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> tuple[Iterable[dict], str | None, tuple[dateType, float] | None]:
        """Fetch the interest-rate transactions the curve is built from."""
        from datetime import datetime, timedelta

        from openbb_core.app.model.abstract.error import OpenBBError

        from openbb_cftc.utils.cfets import cny_curve_records
        from openbb_cftc.utils.constants import curve_fisn
        from openbb_cftc.utils.curve import extract_observations
        from openbb_cftc.utils.dtcc import (
            get_available_dates,
            get_latest_viable_slice,
            get_slice,
        )
        from openbb_cftc.utils.search import search_trades
        from openbb_cftc.utils.store import RecordChain

        fisn = curve_fisn(query.currency)

        if query.source == "slice":
            if query.currency == "CNY":
                dates = await get_available_dates("rates")

                if query.date:
                    dates = [d for d in dates if d <= query.date.isoformat()]

                if not dates:
                    raise OpenBBError(
                        "No PPD rates files are currently published for the window."
                    )

                report_date = dates[-1]
                records = await get_slice(
                    "rates", report_date, use_cache=query.use_cache
                )
                extra = await cny_curve_records(
                    dateType.fromisoformat(report_date), use_cache=query.use_cache
                )

                if extra:
                    records = RecordChain(records, extra)
            else:
                records, report_date = await get_latest_viable_slice(
                    "rates",
                    lambda recs, day: bool(
                        extract_observations(
                            recs,
                            trade_date=day,
                            fisn=fisn,
                            currency=query.currency,
                            cleared_only=query.cleared,
                        )
                    ),
                    use_cache=query.use_cache,
                    max_lookback=query.lookback_days,
                    end_date=query.date.isoformat() if query.date else None,
                )

            anchor = (
                await _latest_fixing(
                    query.currency,
                    dateType.fromisoformat(report_date),
                    query.use_cache,
                )
                if query.overnight_anchor
                else None
            )

            return records, report_date, anchor

        end_date = query.date or datetime.now(UTC).date()
        records = await search_trades(
            "rates",
            start_date=end_date - timedelta(days=query.lookback_days - 1),
            end_date=end_date,
            currency=query.currency,
            upi_short_name=fisn,
            use_cache=query.use_cache,
        )

        if query.currency == "CNY":
            extra = await cny_curve_records(end_date, use_cache=query.use_cache)

            if extra:
                records = RecordChain(records, extra)

        anchor = (
            await _latest_fixing(query.currency, end_date, query.use_cache)
            if query.overnight_anchor
            else None
        )

        return records, None, anchor

    @staticmethod
    def transform_data(
        query: CftcOisCurveQueryParams,
        data: tuple[Iterable[dict], str | None, tuple[dateType, float] | None],
        **kwargs: Any,
    ) -> AnnotatedResult[list[CftcOisCurveData]]:
        """Build the curve and insert metadata."""
        from openbb_cftc.utils.constants import curve_fisn, curve_spec
        from openbb_cftc.utils.curve import build_curve, build_curve_as_of

        records, report_date, anchor = data
        spec = curve_spec(query.currency)
        overnight_date, overnight_rate = anchor if anchor else (None, None)

        if report_date is None:
            curve = build_curve_as_of(
                records,
                fisn=curve_fisn(query.currency),
                currency=query.currency,
                granularity=query.granularity,
                aggregation=query.aggregation,
                min_trades=query.min_trades,
                interpolation=query.interpolation,
                cleared_only=query.cleared,
                max_staleness_days=query.max_staleness_days,
                overnight_rate=overnight_rate,
                overnight_date=overnight_date,
            )
        else:
            curve = build_curve(
                records,
                trade_date=dateType.fromisoformat(report_date),
                fisn=curve_fisn(query.currency),
                currency=query.currency,
                granularity=query.granularity,
                aggregation=query.aggregation,
                min_trades=query.min_trades,
                interpolation=query.interpolation,
                cleared_only=query.cleared,
                use_cache=query.use_cache,
                overnight_rate=overnight_rate,
                overnight_date=overnight_date,
            )

        rate_key = {"par": "par_rate", "zero": "zero_rate"}[query.curve_type]

        for node in curve:
            node["currency"] = query.currency
            node["benchmark"] = spec["index"]
            node["curve_type"] = query.curve_type
            rate = node.get(rate_key)
            node["rate"] = None if rate is None else rate * 100.0
            for field in ("min_rate", "max_rate"):
                if node.get(field) is not None:
                    node[field] *= 100.0
            node["index"] = (
                node["tenor"]
                if query.granularity == "benchmark"
                else node["maturity_date"].isoformat()
            )

        as_of_dates = [node["as_of_date"] for node in curve]

        return AnnotatedResult(
            result=[CftcOisCurveData.model_validate(node) for node in curve],
            metadata={
                "source": query.source,
                "curve_date": curve[0]["date"].isoformat(),
                "freshest_node": max(as_of_dates).isoformat(),
                "stalest_node": min(as_of_dates).isoformat(),
                "currency": query.currency,
                "benchmark": spec["index"],
                "central_bank": spec["central_bank"],
                "curve_type": query.curve_type,
                "cleared_only": query.cleared,
                "nodes": len(curve),
                "trades": sum(node["num_trades"] for node in curve),
                "granularity": query.granularity,
                "aggregation": query.aggregation,
                "lookback_days": query.lookback_days if report_date is None else None,
                "overnight_anchor": (
                    {"date": anchor[0].isoformat(), "rate": anchor[1] * 100.0}
                    if anchor
                    else ("unavailable" if query.overnight_anchor else False)
                ),
            },
        )
