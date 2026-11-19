"""DTCC Overnight Index Swap Forward Rate Curve Model."""

from collections.abc import Iterable
from datetime import (
    UTC,
    date as dateType,
)
from typing import Any, Literal

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field, field_validator


class CftcOisForwardCurveQueryParams(QueryParams):
    """DTCC Overnight Index Swap Forward Rate Curve Query Parameters."""

    __json_schema_extra__ = {
        "currency": {"multiple_items_allowed": False},
        "forward_tenor": {"multiple_items_allowed": False},
        "forward_step": {"multiple_items_allowed": False},
        "method": {"multiple_items_allowed": False},
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
    ] = Field(
        default="USD",
        description="Currency of the swap curve.",
    )
    forward_tenor: Literal["1M", "3M", "6M", "9M", "1Y", "18M", "2Y", "3Y", "5Y"] = (
        Field(
            default="1Y",
            description="Length of the forward swap - the tenor of the swap priced at each"
            + " forward start date. Independent of the spacing between starts.",
        )
    )
    forward_step: Literal["1M", "3M", "6M", "1Y", "2Y"] = Field(
        default="3M",
        description="Spacing between forward start dates. Set it apart from `forward_tenor`"
        + " to plot, say, the 5Y forward at yearly starts (forward_tenor='5Y',"
        + " forward_step='1Y').",
    )
    forward_count: int | None = Field(
        default=None,
        ge=1,
        description="Number of forward start dates to plot. Defaults to the whole curve out"
        + " to its last pillar; set it to plot only the first N steps (e.g. 10 with a 1Y"
        + " step is the next ten years of the forward).",
    )
    method: Literal["implied", "observed"] = Field(
        default="implied",
        description="How the forward rates are formed. 'implied' reads them off the"
        + " Nelson-Siegel-Svensson fit of the bootstrapped spot curve. 'observed' takes the"
        + " fixed rates of the forward-starting swaps of the tenor directly, medianed by"
        + " start and smoothed onto the grid - the market's own forward quotes, which reach"
        + " only as far as that forward has traded.",
    )
    source: Literal["search", "slice"] = Field(
        default="search",
        description="Where the trades come from. 'search' queries a window of"
        + " dissemination days; 'slice' uses a single day's cumulative file, walking a"
        + " weekend or holiday back to the most recent day that priced this currency.",
    )
    date: dateType | None = Field(
        default=None,
        description="Dissemination date (UTC). Ends the search window, or selects the"
        + " most recent slice on or before it that priced this currency. History is"
        + " retained for 366 days.",
        json_schema_extra={"x-widget_config": {"value": "$currentDate"}},
    )
    lookback_days: int = Field(
        default=7,
        ge=1,
        le=365,
        description="Days to look back over: the search window with source='search', or"
        + " how far to walk back for the most recent priced day with source='slice'. The"
        + " search chains 180-day sub-windows up to the one-year horizon, so a thin"
        + " currency can fill its forwards from a full year of prints.",
    )
    max_staleness_days: int | None = Field(
        default=None,
        ge=0,
        description="Drop any underlying node whose freshest print is older than this many"
        + " days. A wide `lookback_days` fills thin tenors but resurrects some that last"
        + " traded months ago; capping staleness keeps the forward strip current. Only"
        + " meaningful with source='search'.",
    )
    aggregation: Literal["median", "mean", "vwap"] = Field(
        default="median",
        description="How each node's executed rates are reduced to a par rate.",
    )
    min_trades: int = Field(
        default=1,
        description="Drop nodes priced by fewer than this many trades.",
    )
    interpolation: Literal["log_linear", "log_cubic"] = Field(
        default="log_linear",
        description="Discount-factor interpolation for the bootstrap the Nelson-Siegel-"
        + "Svensson forward fit is drawn from.",
    )
    use_cache: bool = Field(
        default=True,
        description="Cache the source data locally, revalidating against the source ETag.",
    )

    @field_validator("currency", "forward_tenor", "forward_step", mode="before")
    @classmethod
    def _to_upper(cls, v):
        """Accept a currency or tenor in any case."""
        return v.upper() if isinstance(v, str) else v


class CftcOisForwardCurveData(Data):
    """DTCC Overnight Index Swap Forward Rate Curve Data."""

    date: dateType = Field(
        description="Date of the curve.",
        json_schema_extra={"x-widget_config": {"chartDataType": "excluded"}},
    )
    currency: str = Field(
        description="Currency of the curve.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Currency", "chartDataType": "excluded"}
        },
    )
    index: str = Field(
        description="Forward start date of the swap - the row and chart index.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Forward Start",
                "cellDataType": "date",
                "chartDataType": "category",
            }
        },
    )
    tenor: str = Field(
        description="The forward swap and its start, e.g. '1Y @ 5.00Y' (a 1Y swap 5Y out).",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Forward",
                "cellDataType": "text",
                "chartDataType": "excluded",
            }
        },
    )
    start_years: float = Field(
        description="Forward start of the swap, in years. 0 is spot.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Start (Years)",
                "cellDataType": "number",
                "chartDataType": "excluded",
            }
        },
    )
    forward_rate: float = Field(
        description="Forward par swap rate, in percent (4.32 is 4.32%).",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Forward Rate",
                "cellDataType": "number",
                "chartDataType": "series",
                "formatterFn": "percent",
            },
        },
    )
    extrapolated: bool = Field(
        default=False,
        description="Whether the swap's tail ran past the last pillar, extended by the fit.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Extrapolated", "hide": True}
        },
    )
    num_trades: int = Field(
        description="Trades behind the curve nodes spanning this forward's start-to-tenor"
        + " span, or the nearest node's when none fall inside it.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Trades", "chartDataType": "excluded"}
        },
    )


class CftcOisForwardCurveFetcher(
    Fetcher[CftcOisForwardCurveQueryParams, list[CftcOisForwardCurveData]]
):
    """DTCC Overnight Index Swap Forward Rate Curve Fetcher."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> CftcOisForwardCurveQueryParams:
        """Transform the query params."""
        return CftcOisForwardCurveQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: CftcOisForwardCurveQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> tuple[Iterable[dict], str | None]:
        """Fetch the interest-rate transactions the curve is built from."""
        from datetime import datetime, timedelta

        from openbb_cftc.utils.constants import ois_fisn
        from openbb_cftc.utils.curve import extract_observations
        from openbb_cftc.utils.dtcc import get_latest_viable_slice
        from openbb_cftc.utils.search import search_trades

        if query.source == "slice":
            fisn = ois_fisn(query.currency)
            records, report_date = await get_latest_viable_slice(
                "rates",
                lambda recs, day: bool(
                    extract_observations(
                        recs,
                        trade_date=day,
                        fisn=fisn,
                        currency=query.currency,
                    )
                ),
                use_cache=query.use_cache,
                max_lookback=query.lookback_days,
                end_date=query.date.isoformat() if query.date else None,
            )

            return records, report_date

        end_date = query.date or datetime.now(UTC).date()
        records = await search_trades(
            "rates",
            start_date=end_date - timedelta(days=query.lookback_days - 1),
            end_date=end_date,
            currency=query.currency,
            upi_short_name=ois_fisn(query.currency),
            use_cache=query.use_cache,
        )

        return records, None

    @staticmethod
    def transform_data(
        query: CftcOisForwardCurveQueryParams,
        data: tuple[Iterable[dict], str | None],
        **kwargs: Any,
    ) -> AnnotatedResult[list[CftcOisForwardCurveData]]:
        """Build the curve, then read the forward strip off it, implied or observed."""
        from datetime import timedelta

        from openbb_cftc.utils.constants import (
            OIS_INDICES,
            day_count_basis,
            ois_fisn,
            tenor_to_years,
        )
        from openbb_cftc.utils.curve import (
            _par_rate_at,
            build_curve,
            build_curve_as_of,
            curve_payment_period,
            forward_curve_grid,
        )
        from openbb_cftc.utils.policy import observed_forward_grid

        records, report_date = data
        fisn = ois_fisn(query.currency)
        spec = OIS_INDICES[query.currency]
        forward_years = tenor_to_years(query.forward_tenor)
        step_years = tenor_to_years(query.forward_step)

        if report_date is None:
            curve = build_curve_as_of(
                records,
                fisn=fisn,
                currency=query.currency,
                aggregation=query.aggregation,
                min_trades=query.min_trades,
                interpolation=query.interpolation,
                max_staleness_days=query.max_staleness_days,
            )
            curve_date = curve[0]["date"]
        else:
            curve = build_curve(
                records,
                trade_date=dateType.fromisoformat(report_date),
                fisn=fisn,
                currency=query.currency,
                aggregation=query.aggregation,
                min_trades=query.min_trades,
                interpolation=query.interpolation,
                use_cache=query.use_cache,
            )
            curve_date = dateType.fromisoformat(report_date)

        basis = day_count_basis(spec["day_count"], "A004")
        period = curve_payment_period(
            records, query.currency, curve_date, query.min_trades
        )

        if query.method == "observed":
            spot_dfs = sorted(
                (node["tenor_years"], node["discount_factor"])
                for node in curve
                if node["discount_factor"] is not None
            )
            forward_tenor_days = round(forward_years * 365.0)
            grid = observed_forward_grid(
                records,
                fisn,
                query.currency,
                curve_date,
                forward_tenor_days=forward_tenor_days,
                step_years=step_years,
                count=query.forward_count,
                min_trades=query.min_trades,
                spot_rate=_par_rate_at(
                    spot_dfs, forward_tenor_days, basis, period, query.interpolation
                ),
            )
        else:
            grid = forward_curve_grid(
                curve, forward_years, step_years, basis, query.forward_count, period
            )

        rows: list[dict] = []

        for point in grid:
            start = curve_date + timedelta(days=point["tenor_days"])
            rows.append(
                {
                    "date": curve_date,
                    "currency": query.currency,
                    "index": start.isoformat(),
                    "tenor": f"{query.forward_tenor} @ {point['tenor_years']:.2f}Y",
                    "start_years": point["tenor_years"],
                    "forward_rate": point["forward_rate"] * 100.0,
                    "extrapolated": point["forward_extrapolated"],
                    "num_trades": point["num_trades"],
                }
            )

        if not rows:
            raise OpenBBError(
                f"No {query.currency} forward curve could be built for the requested date."
            )

        return AnnotatedResult(
            result=[CftcOisForwardCurveData.model_validate(r) for r in rows],
            metadata={
                "currency": query.currency,
                "index": spec["index"],
                "method": query.method,
                "forward_tenor": query.forward_tenor,
                "forward_step": query.forward_step,
                "forward_count": query.forward_count,
                "points": len(rows),
            },
        )
