"""DTCC FX Implied Volatility Model."""

from collections.abc import Iterable
from datetime import date as dateType
from typing import Any, Literal

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field, field_validator
from pydantic.config import JsonDict

_VOL_COLOR_RULES: JsonDict = {
    "colorRules": [
        {"condition": "lt", "value": 5, "color": "#2e7d32", "fill": True},
        {
            "condition": "between",
            "range": {"min": 5, "max": 6.5},
            "color": "#7cb342",
            "fill": True,
        },
        {
            "condition": "between",
            "range": {"min": 6.5, "max": 8},
            "color": "#c9a227",
            "fill": True,
        },
        {
            "condition": "between",
            "range": {"min": 8, "max": 11},
            "color": "#e07b1c",
            "fill": True,
        },
        {"condition": "gt", "value": 11, "color": "#c0392b", "fill": True},
    ]
}


class CftcFxImpliedVolQueryParams(QueryParams):
    """DTCC FX Implied Volatility Query Parameters."""

    __json_schema_extra__ = {
        "pair": {"multiple_items_allowed": False},
        "basis": {"multiple_items_allowed": False},
    }

    pair: Literal[
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "USDCHF",
        "USDCAD",
        "EURGBP",
        "USDBRL",
        "USDKRW",
        "USDINR",
        "USDTWD",
        "USDCOP",
    ] = Field(
        default="EURUSD",
        description="Currency pair, in market quoting convention. Limited to the pairs whose"
        + " options are reported to the CFTC in enough depth to build a surface each day. The"
        + " USD/EM pairs (USDBRL, USDKRW, ...) are built from non-deliverable options against"
        + " a spot and forward taken from the reported non-deliverable forwards.",
    )
    basis: Literal["empirical", "theoretical"] = Field(
        default="empirical",
        description="How the surface is built: 'empirical' medians the traded options at"
        + " each grid strike (gaps where nothing traded); 'theoretical' fits a lognormal-SABR"
        + " smile per expiry and evaluates it on the grid (smooth, gap-free).",
    )
    date: dateType | None = Field(
        default=None,
        description="Dissemination date (UTC) of the options. Defaults to the most"
        + " recent published. History is retained for 366 days.",
        json_schema_extra={"x-widget_config": {"value": "$currentDate"}},
    )
    min_trades: int = Field(
        default=3,
        description="Minimum trades for an OIS curve node used to price the rate legs.",
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


class CftcFxImpliedVolData(Data):
    """DTCC FX Implied Volatility Data."""

    date: dateType = Field(
        description="Dissemination date of the options.",
        json_schema_extra={"x-widget_config": {"chartDataType": "excluded"}},
    )
    pair: str = Field(
        description="Currency pair.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Pair", "chartDataType": "excluded"}
        },
    )
    strike: float = Field(
        description="Strike price of the underlying, on a grid of offsets from spot.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Strike",
                "cellDataType": "number",
                "chartDataType": "category",
                "formatterFn": "none",
            }
        },
    )
    strike_offset: float = Field(
        description="The strike's distance from spot, positive above spot: in points for a"
        + " deliverable major, in basis points of spot for a non-deliverable USD/EM pair.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Offset",
                "cellDataType": "number",
                "chartDataType": "excluded",
            }
        },
    )
    vol_1w: float | None = Field(
        default=None,
        description="1-week implied volatility at the strike, in percent (5.4 is 5.4%).",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "1W",
                "cellDataType": "number",
                "chartDataType": "series",
                "formatterFn": "percent",
                "renderFn": "columnColor",
                "renderFnParams": _VOL_COLOR_RULES,
            }
        },
    )
    vol_2w: float | None = Field(
        default=None,
        description="2-week implied volatility at the strike, in percent (5.4 is 5.4%).",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "2W",
                "cellDataType": "number",
                "chartDataType": "series",
                "formatterFn": "percent",
                "renderFn": "columnColor",
                "renderFnParams": _VOL_COLOR_RULES,
            }
        },
    )
    vol_1m: float | None = Field(
        default=None,
        description="1-month implied volatility at the strike, in percent (5.4 is 5.4%).",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "1M",
                "cellDataType": "number",
                "chartDataType": "series",
                "formatterFn": "percent",
                "renderFn": "columnColor",
                "renderFnParams": _VOL_COLOR_RULES,
            }
        },
    )
    vol_2m: float | None = Field(
        default=None,
        description="2-month implied volatility at the strike, in percent (5.4 is 5.4%).",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "2M",
                "cellDataType": "number",
                "chartDataType": "series",
                "formatterFn": "percent",
                "renderFn": "columnColor",
                "renderFnParams": _VOL_COLOR_RULES,
            }
        },
    )
    vol_3m: float | None = Field(
        default=None,
        description="3-month implied volatility at the strike, in percent (5.4 is 5.4%).",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "3M",
                "cellDataType": "number",
                "chartDataType": "series",
                "formatterFn": "percent",
                "renderFn": "columnColor",
                "renderFnParams": _VOL_COLOR_RULES,
            }
        },
    )
    vol_6m: float | None = Field(
        default=None,
        description="6-month implied volatility at the strike, in percent (5.4 is 5.4%).",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "6M",
                "cellDataType": "number",
                "chartDataType": "series",
                "formatterFn": "percent",
                "renderFn": "columnColor",
                "renderFnParams": _VOL_COLOR_RULES,
            }
        },
    )
    vol_9m: float | None = Field(
        default=None,
        description="9-month implied volatility at the strike, in percent (5.4 is 5.4%).",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "9M",
                "cellDataType": "number",
                "chartDataType": "series",
                "formatterFn": "percent",
                "renderFn": "columnColor",
                "renderFnParams": _VOL_COLOR_RULES,
            }
        },
    )
    vol_1y: float | None = Field(
        default=None,
        description="1-year implied volatility at the strike, in percent (5.4 is 5.4%).",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "1Y",
                "cellDataType": "number",
                "chartDataType": "series",
                "formatterFn": "percent",
                "renderFn": "columnColor",
                "renderFnParams": _VOL_COLOR_RULES,
            }
        },
    )
    vol_2y: float | None = Field(
        default=None,
        description="2-year implied volatility at the strike, in percent (5.4 is 5.4%).",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "2Y",
                "cellDataType": "number",
                "chartDataType": "series",
                "formatterFn": "percent",
                "renderFn": "columnColor",
                "renderFnParams": _VOL_COLOR_RULES,
            }
        },
    )
    num_options: int = Field(
        description="Number of options aggregated into the strike row, across expiries.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Options",
                "cellDataType": "number",
                "chartDataType": "excluded",
            }
        },
    )


class CftcFxImpliedVolFetcher(
    Fetcher[CftcFxImpliedVolQueryParams, list[CftcFxImpliedVolData]]
):
    """DTCC FX Implied Volatility Fetcher."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> CftcFxImpliedVolQueryParams:
        """Transform the query params."""
        return CftcFxImpliedVolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: CftcFxImpliedVolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> tuple[Iterable[dict], Iterable[dict], str, str]:
        """Fetch a day's FX options and the rates slice that prices the legs."""
        from openbb_cftc.utils.dtcc import get_latest_viable_slice, get_rates_slice_for
        from openbb_cftc.utils.fx_vol import (
            has_vanilla_options,
            is_ndf_vol_pair,
            market_spot,
            pair_curve,
            resolve_major_pair,
        )

        base, quote, _ = resolve_major_pair(query.pair)
        ndf = is_ndf_vol_pair(query.pair)
        family = "NA/O NDO " if ndf else "NA/O Van "

        def _viable(recs: Iterable[dict], day: dateType) -> bool:
            if not has_vanilla_options(recs, base, quote, family):
                return False

            curve = pair_curve(recs, query.pair, day)

            return market_spot(curve, recs, base, quote, day)[0] is not None

        forex, report_date = await get_latest_viable_slice(
            "forex",
            _viable,
            use_cache=query.use_cache,
            end_date=query.date.isoformat() if query.date else None,
        )

        rates, rates_date = await get_rates_slice_for(
            report_date, [base] if ndf else [base, quote], query.use_cache
        )

        return forex, rates, report_date, rates_date

    @staticmethod
    def transform_data(
        query: CftcFxImpliedVolQueryParams,
        data: tuple[Iterable[dict], Iterable[dict], str, str],
        **kwargs: Any,
    ) -> AnnotatedResult[list[CftcFxImpliedVolData]]:
        """Invert the options to implied vols and aggregate the smiles by tenor."""
        from openbb_cftc.utils import fx_vol

        forex, rates, report_date, rates_date = data
        as_of = dateType.fromisoformat(report_date)
        base, quote, _pip = fx_vol.resolve_major_pair(query.pair)
        ndf = fx_vol.is_ndf_vol_pair(query.pair)
        rate_date = dateType.fromisoformat(rates_date)

        market = fx_vol.build_market(
            fx_vol.pair_curve(forex, query.pair, as_of),
            forex,
            base,
            quote,
            as_of,
            fx_vol.market_discount(rates, rate_date, query.min_trades),
        )

        if market is None:
            raise OpenBBError(
                f"No spot could be established for {query.pair} on {report_date}."
            )

        spot, df_base, df_quote = market["spot"], market["df_base"], market["df_quote"]
        options = fx_vol.extract_vanilla_options(
            forex, base, quote, as_of, spot, "NA/O NDO " if ndf else "NA/O Van "
        )
        priced = fx_vol.price_options(options, spot, df_quote, df_base)

        fits: dict = {}

        if query.basis == "theoretical":
            rows, fits = fx_vol.theoretical_surface(
                priced, spot, df_quote, df_base, _pip, ndf
            )
        else:
            rows = fx_vol.vol_surface(priced, spot, _pip, ndf)

        if not rows or all(row["num_options"] == 0 for row in rows):
            raise OpenBBError(
                f"No {query.pair} {query.basis} volatility surface could be built on"
                f" {report_date}. Try the 'empirical' basis, or another date."
            )

        vol_fields = (
            "vol_1w",
            "vol_2w",
            "vol_1m",
            "vol_2m",
            "vol_3m",
            "vol_6m",
            "vol_9m",
            "vol_1y",
            "vol_2y",
        )
        for row in rows:
            row["date"] = as_of
            row["pair"] = query.pair
            for field in vol_fields:
                if row.get(field) is not None:
                    row[field] *= 100.0

        for field in {key for row in rows for key in row}:
            if all(row.get(field) is None for row in rows):
                for row in rows:
                    row.pop(field, None)

        return AnnotatedResult(
            result=[CftcFxImpliedVolData.model_validate(r) for r in rows],
            metadata={
                "pair": query.pair,
                "basis": query.basis,
                "date": report_date,
                "rates_date": rates_date,
                "spot": spot,
                "options_priced": len(priced),
                "sabr_fits": {
                    t: {k: round(v, 4) for k, v in f.items()} for t, f in fits.items()
                },
                "tenors": len(rows),
            },
        )
