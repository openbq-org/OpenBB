"""DTCC FX Forward Points Model."""

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


class CftcFxForwardPointsQueryParams(QueryParams):
    """DTCC FX Forward Points Query Parameters."""

    __json_schema_extra__ = {
        "pair": {"multiple_items_allowed": False},
        "source": {"multiple_items_allowed": False},
    }

    pair: Literal[
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "USDCHF",
        "USDCAD",
        "AUDUSD",
        "NZDUSD",
        "USDKRW",
        "USDINR",
        "USDBRL",
        "USDTWD",
        "USDIDR",
        "USDPHP",
        "USDCLP",
        "USDCOP",
        "USDCNY",
        "USDPEN",
        "USDMYR",
    ] = Field(
        default="EURUSD",
        description="Currency pair, in market quoting convention. The USD/EM pairs"
        + " (USDKRW, USDINR, USDBRL, ...) are non-deliverable forwards.",
    )
    source: Literal["search", "slice"] = Field(
        default="search",
        description="Where the trades come from. 'search' queries a window of"
        + " dissemination days and prices each tenor from the most recent day it"
        + " traded in depth. 'slice' uses a single day's cumulative file, which"
        + " leaves thin tenors missing and yields nothing on a weekend.",
    )
    date: dateType | None = Field(
        default=None,
        description="Dissemination date (UTC). With source='search' this ends the"
        + " lookback window, and defaults to today. With source='slice' it selects one"
        + " day's file, and defaults to the most recent published."
        + " History is retained for 366 days.",
        json_schema_extra={"x-widget_config": {"value": "$currentDate"}},
    )
    lookback_days: int = Field(
        default=30,
        ge=1,
        le=180,
        description="Number of dissemination days to search back over, ending on `date`."
        + " Only used when source='search'. A longer window fills in more tenors, at"
        + " the cost of pricing the thin ones further from today; check `staleness_days`."
        + " The source caps a search at 180 days.",
    )
    min_notional: float = Field(
        default=1_000_000.0,
        description="Minimum trade notional, in the base currency."
        + " Sub-institutional prints trade percent away from the interbank market and"
        + " would otherwise dominate a tenor's median. Set to 0 to keep every trade.",
    )
    min_trades: int = Field(
        default=1,
        description="Drop tenors priced by fewer than this many trades."
        + " The default keeps every tenor, because one executed trade is still a price;"
        + " `num_trades`, `min_rate` and `max_rate` say how thin it is.",
    )
    use_cache: bool = Field(
        default=True,
        description="Cache the source data locally. Closed dissemination days are"
        + " immutable and are never re-fetched; daily files are revalidated against"
        + " the source ETag.",
    )

    @field_validator("pair", mode="before")
    @classmethod
    def _to_upper(cls, v):
        """Accept a pair in any case."""
        return v.upper() if isinstance(v, str) else v


class CftcFxForwardPointsData(Data):
    """DTCC FX Forward Points Data."""

    date: dateType = Field(
        description="Date of the curve, being that of its freshest tenor.",
        json_schema_extra={"x-widget_config": {"hide": True}},
    )
    as_of_date: dateType | None = Field(
        default=None,
        description="Dissemination date the tenor's trades were reported on.",
        json_schema_extra={"x-widget_config": {"headerName": "As Of", "hide": True}},
    )
    staleness_days: int | None = Field(
        default=None,
        description="Days between the tenor's as-of date and the curve's date."
        + " Zero on the freshest tenors.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Staleness (Days)", "hide": True}
        },
    )
    pair: str = Field(
        description="Currency pair, in market quoting convention.",
        json_schema_extra={"x-widget_config": {"headerName": "Pair", "hide": True}},
    )
    tenor: str = Field(
        description="Tenor bucket of the observation.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Tenor",
                "cellDataType": "text",
                "chartDataType": "category",
            }
        },
    )
    tenor_days: int = Field(
        description="Lower bound of the tenor bucket, in days.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Tenor (Days)",
                "cellDataType": "number",
                "chartDataType": "excluded",
                "hide": True,
            }
        },
    )
    spot_rate: float = Field(
        description="Spot rate of the tenor's as-of date, the median of that day's"
        + " trades settling within two days, or of its shortest-dated tenor for a"
        + " non-deliverable pair.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Spot",
                "cellDataType": "number",
                "decimalPlaces": 5,
            }
        },
    )
    forward_rate: float = Field(
        description="Median executed forward rate at the tenor.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Forward",
                "cellDataType": "number",
                "decimalPlaces": 5,
            }
        },
    )
    forward_points: float = Field(
        description="Executed forward rate less spot, in pips.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Forward Points",
                "cellDataType": "number",
                "decimalPlaces": 4,
            }
        },
    )
    theoretical_points: float | None = Field(
        default=None,
        description="Covered-interest-parity forward points from the two legs' rate curves,"
        + " in pips - each leg's OIS, or its fixed-float IRS for an EM currency with no OIS."
        + " Present only when both legs have a curve; for a non-deliverable pair its gap to"
        + " the executed points (`basis_points`) is the NDF basis to onshore rates.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "CIP Points",
                "cellDataType": "number",
                "decimalPlaces": 4,
            }
        },
    )
    basis_points: float | None = Field(
        default=None,
        description="Executed points less the CIP points, in pips: positive where the"
        + " market pays over covered-interest-parity fair value, negative under.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Basis",
                "cellDataType": "number",
                "decimalPlaces": 4,
            }
        },
    )
    quotation: str | None = Field(
        default=None,
        description="Whether the base is at a forward premium (executed points positive,"
        + " forward above spot) or a discount (points negative, forward below spot).",
    )
    carry: str | None = Field(
        default=None,
        description="Whether a long base-currency forward position earns or pays the"
        + " points to the forward date. It earns at a discount - the base out-yields the"
        + " quote, so it is bought forward below spot - and pays at a premium. The"
        + " short-base side is the opposite (Lehman Brothers, FX Training Manual: pay or"
        + " earn the points).",
    )
    num_trades: int = Field(
        description="Number of executed trades aggregated into the tenor.",
        json_schema_extra={"x-widget_config": {"headerName": "Trades"}},
    )
    total_notional: float | None = Field(
        default=None,
        description="Sum of the base currency notional of the tenor's trades.",
    )
    min_rate: float | None = Field(
        default=None,
        description="Lowest executed rate aggregated into the tenor. A wide gap to"
        + " `max_rate` marks a dispersed bucket whose median may be off-market - read it"
        + " alongside `num_trades` before relying on the point.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Min Rate",
                "cellDataType": "number",
                "formatterFn": "none",
                "decimalPlaces": 5,
            }
        },
    )
    max_rate: float | None = Field(
        default=None,
        description="Highest executed rate aggregated into the tenor. A wide gap to"
        + " `min_rate` marks a dispersed bucket whose median may be off-market - read it"
        + " alongside `num_trades` before relying on the point.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Max Rate",
                "cellDataType": "number",
                "decimalPlaces": 5,
            }
        },
    )


class CftcFxForwardPointsFetcher(
    Fetcher[CftcFxForwardPointsQueryParams, list[CftcFxForwardPointsData]]
):
    """DTCC FX Forward Points Fetcher."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> CftcFxForwardPointsQueryParams:
        """Transform the query params."""
        return CftcFxForwardPointsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: CftcFxForwardPointsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> tuple[Iterable[dict], Iterable[dict], str | None, str]:
        """Fetch the FX transactions and the rates slice that prices CIP fair value."""
        from datetime import datetime, timedelta

        from openbb_cftc.utils.constants import FX_PAIRS, OIS_INDICES
        from openbb_cftc.utils.dtcc import (
            get_latest_viable_slice,
            get_rates_slice_for,
            get_slice,
        )
        from openbb_cftc.utils.search import search_trades

        base, quote = query.pair[:3], query.pair[3:]
        spec = FX_PAIRS[query.pair]
        fisns = (spec["forward_fisn"], spec["swap_fisn"])
        ois_legs = [leg for leg in (base, quote) if leg in OIS_INDICES]
        records: Iterable[dict] = []

        if query.source == "slice":
            if query.date:
                report_date = query.date.isoformat()
                records = await get_slice(
                    "forex", report_date, use_cache=query.use_cache
                )
            else:
                records, report_date = await get_latest_viable_slice(
                    "forex",
                    lambda recs, _d: any(
                        (r.get("UPI FISN") or "").strip() in fisns for r in recs
                    ),
                    use_cache=query.use_cache,
                )

            rates, rates_date = await get_rates_slice_for(
                report_date, ois_legs, query.use_cache
            )

            return records, rates, report_date, rates_date

        end_date = query.date or datetime.now(UTC).date()
        start_date = end_date - timedelta(days=query.lookback_days - 1)

        for fisn in fisns:
            records += await search_trades(
                "forex",
                start_date=start_date,
                end_date=end_date,
                upi_short_name=fisn,
                use_cache=query.use_cache,
            )

        rates, rates_date = await get_rates_slice_for(
            end_date.isoformat(), ois_legs, query.use_cache
        )

        return records, rates, None, rates_date

    @staticmethod
    def transform_data(
        query: CftcFxForwardPointsQueryParams,
        data: tuple[Iterable[dict], Iterable[dict], str | None, str],
        **kwargs: Any,
    ) -> AnnotatedResult[list[CftcFxForwardPointsData]]:
        """Build the forward point curve, its CIP fair value, and insert metadata."""
        from openbb_core.provider.utils.errors import EmptyDataError

        from openbb_cftc.utils.constants import FX_PAIRS, currency_basis
        from openbb_cftc.utils.fx import (
            build_forward_points,
            build_forward_points_as_of,
        )
        from openbb_cftc.utils.fx_theory import cip_forward_rate
        from openbb_cftc.utils.fx_vol import rate_discount_factor

        records, rates, report_date, rates_date = data

        if report_date is None:
            points = build_forward_points_as_of(
                records,
                pair=query.pair,
                min_notional=query.min_notional,
                min_trades=query.min_trades,
            )
        else:
            points = build_forward_points(
                records,
                pair=query.pair,
                trade_date=dateType.fromisoformat(report_date),
                min_notional=query.min_notional,
                min_trades=query.min_trades,
            )

        base, quote = query.pair[:3], query.pair[3:]

        df_quote = df_base = None
        rate_date = dateType.fromisoformat(rates_date)
        quote_min = 1 if FX_PAIRS[query.pair].get("ndf") else 3

        try:
            df_quote = rate_discount_factor(
                rates, quote, rate_date, quote_min, forward_aware=True
            )
            df_base = rate_discount_factor(
                rates, base, rate_date, min_trades=3, forward_aware=True
            )
        except EmptyDataError:
            df_quote = df_base = None

        if df_quote is not None and df_base is not None:
            pip = FX_PAIRS[query.pair]["pip"]
            basis_quote = currency_basis(quote)
            basis_base = currency_basis(base)

            for point in points:
                days = point["tenor_days"]

                if days <= 0:
                    continue

                years = days / 365.0
                r_q = (1.0 / df_quote(years) - 1.0) * basis_quote / days
                r_b = (1.0 / df_base(years) - 1.0) * basis_base / days
                forward = cip_forward_rate(
                    point["spot_rate"], r_q, r_b, days, basis_quote, basis_base
                )
                theoretical = (forward - point["spot_rate"]) * pip
                point["theoretical_points"] = theoretical
                point["basis_points"] = point["forward_points"] - theoretical

        for point in points:
            forward_points = point.get("forward_points")

            if not forward_points:
                point["quotation"] = "--"
                point["carry"] = "--"
                continue

            point["quotation"] = "premium" if forward_points > 0 else "discount"
            point["carry"] = "pay" if forward_points > 0 else "earn"

        as_of_dates = [p["as_of_date"] for p in points]

        return AnnotatedResult(
            result=[CftcFxForwardPointsData(**p) for p in points],
            metadata={
                "source": query.source,
                "curve_date": points[0]["date"].isoformat(),
                "freshest_tenor": max(as_of_dates).isoformat(),
                "stalest_tenor": min(as_of_dates).isoformat(),
                "pair": query.pair,
                "spot_rate": points[0]["spot_rate"],
                "tenors": len(points),
                "trades": sum(p["num_trades"] for p in points),
                "min_notional": query.min_notional,
                "lookback_days": query.lookback_days if report_date is None else None,
            },
        )
