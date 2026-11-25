"""DTCC FX Forward Curve Model."""

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


class CftcFxForwardCurveQueryParams(QueryParams):
    """DTCC FX Forward Curve Query Parameters."""

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
        default="USDJPY",
        description="Currency pair. The curve is quoted as the foreign currency per one US"
        + " dollar whichever way the pair is named. The USD/EM pairs (USDKRW, USDINR, ...)"
        + " are non-deliverable forwards.",
    )
    source: Literal["search", "slice"] = Field(
        default="search",
        description="Where the trades come from. 'search' queries a window of dissemination"
        + " days and prices each tenor from the most recent day it traded in depth; 'slice'"
        + " uses a single day's cumulative file, which leaves thin tenors missing.",
    )
    date: dateType | None = Field(
        default=None,
        description="Dissemination date (UTC). With source='search' this ends the lookback"
        + " window, defaulting to today. With source='slice' it selects the most recent day"
        + " on or before it that priced this pair. History is retained for 366 days.",
        json_schema_extra={"x-widget_config": {"value": "$currentDate"}},
    )
    lookback_days: int = Field(
        default=30,
        ge=1,
        le=180,
        description="Number of dissemination days to search back over, ending on `date`."
        + " Only used when source='search'. A longer window fills in more tenors, at the"
        + " cost of pricing the thin ones further from today; check `staleness_days`.",
    )
    min_notional: float = Field(
        default=1_000_000.0,
        description="Minimum trade notional, in the base currency. Set to 0 to keep every trade.",
    )
    min_trades: int = Field(
        default=1,
        description="Drop tenors priced by fewer than this many trades.",
    )
    use_cache: bool = Field(
        default=True,
        description="Cache the source data locally, revalidating against the source ETag.",
    )

    @field_validator("pair", mode="before")
    @classmethod
    def _to_upper(cls, v):
        """Accept a pair in any case."""
        return v.upper() if isinstance(v, str) else v


class CftcFxForwardCurveData(Data):
    """DTCC FX Forward Curve Data."""

    date: dateType = Field(
        description="Date of the curve.",
        json_schema_extra={"x-widget_config": {"chartDataType": "excluded"}},
    )
    pair: str = Field(
        description="Currency pair the curve is built for.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Pair", "chartDataType": "excluded"}
        },
    )
    index: str = Field(
        description="Settlement tenor of the node - the row and chart index.",
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
            }
        },
    )
    rate: float = Field(
        description="Outright forward rate, in units of the foreign currency per US dollar.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Per USD",
                "cellDataType": "number",
                "chartDataType": "series",
                "decimalPlaces": 5,
                "formatterFn": "none",
            }
        },
    )
    spot: float = Field(
        description="Spot rate of the tenor's as-of date, per US dollar.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Spot",
                "cellDataType": "number",
                "chartDataType": "excluded",
                "decimalPlaces": 5,
                "formatterFn": "none",
            }
        },
    )
    num_trades: int = Field(
        description="Number of executed trades aggregated into the tenor.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Trades", "chartDataType": "excluded"}
        },
    )
    total_notional: float | None = Field(
        default=None,
        description="Sum of the base currency notional of the tenor's trades.",
        json_schema_extra={"x-widget_config": {"chartDataType": "excluded"}},
    )
    min_rate: float | None = Field(
        default=None,
        description="Lowest executed rate at the node, per US dollar.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Min",
                "cellDataType": "number",
                "chartDataType": "excluded",
                "decimalPlaces": 5,
                "formatterFn": "none",
            }
        },
    )
    max_rate: float | None = Field(
        default=None,
        description="Highest executed rate at the node, per US dollar.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Max",
                "cellDataType": "number",
                "chartDataType": "excluded",
                "decimalPlaces": 5,
                "formatterFn": "none",
            }
        },
    )
    as_of_date: dateType | None = Field(
        default=None,
        description="Dissemination date the tenor's trades were reported on.",
        json_schema_extra={
            "x-widget_config": {"headerName": "As Of", "chartDataType": "excluded"}
        },
    )
    staleness_days: int | None = Field(
        default=None,
        description="Days between the tenor's as-of date and the curve's date.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Staleness",
                "cellDataType": "number",
                "chartDataType": "excluded",
            }
        },
    )


class CftcFxForwardCurveFetcher(
    Fetcher[CftcFxForwardCurveQueryParams, list[CftcFxForwardCurveData]]
):
    """DTCC FX Forward Curve Fetcher."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> CftcFxForwardCurveQueryParams:
        """Transform the query params."""
        return CftcFxForwardCurveQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: CftcFxForwardCurveQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> tuple[Iterable[dict], str | None]:
        """Fetch the FX forwards and FX swaps the curve is built from."""
        from datetime import datetime, timedelta

        from openbb_cftc.utils.constants import FX_PAIRS
        from openbb_cftc.utils.dtcc import get_latest_viable_slice, get_slice
        from openbb_cftc.utils.search import search_trades

        spec = FX_PAIRS[query.pair]
        fisns = (spec["forward_fisn"], spec["swap_fisn"])

        if query.source == "slice":
            if query.date:
                report_date = query.date.isoformat()
                records = await get_slice(
                    "forex", report_date, use_cache=query.use_cache
                )
            else:
                records, report_date = await get_latest_viable_slice(
                    "forex",
                    lambda recs, _day: any(
                        (r.get("UPI FISN") or "").strip() in fisns for r in recs
                    ),
                    use_cache=query.use_cache,
                )

            return records, report_date

        end_date = query.date or datetime.now(UTC).date()
        start_date = end_date - timedelta(days=query.lookback_days - 1)
        records: list[dict] = []

        for fisn in fisns:
            records += await search_trades(
                "forex",
                start_date=start_date,
                end_date=end_date,
                upi_short_name=fisn,
                use_cache=query.use_cache,
            )

        return records, None

    @staticmethod
    def transform_data(
        query: CftcFxForwardCurveQueryParams,
        data: tuple[Iterable[dict], str | None],
        **kwargs: Any,
    ) -> AnnotatedResult[list[CftcFxForwardCurveData]]:
        """Build the outright forward curve and insert metadata."""
        from openbb_cftc.utils.fx import (
            build_fx_forward_curve,
            build_fx_forward_curve_as_of,
        )

        records, report_date = data

        if report_date is None:
            nodes = build_fx_forward_curve_as_of(
                records,
                pair=query.pair,
                min_notional=query.min_notional,
                min_trades=query.min_trades,
            )
        else:
            nodes = build_fx_forward_curve(
                records,
                pair=query.pair,
                trade_date=dateType.fromisoformat(report_date),
                min_notional=query.min_notional,
                min_trades=query.min_trades,
            )

        for node in nodes:
            node["pair"] = query.pair
            node["index"] = node["tenor"]

        return AnnotatedResult(
            result=[CftcFxForwardCurveData.model_validate(node) for node in nodes],
            metadata={
                "pair": query.pair,
                "curve_date": nodes[0]["date"].isoformat(),
                "spot": nodes[0]["spot"],
                "tenors": len(nodes),
                "trades": sum(node["num_trades"] for node in nodes),
                "min_notional": query.min_notional,
            },
        )
