"""DTCC OIS Policy-Path Model."""

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


class CftcOisPolicyPathQueryParams(QueryParams):
    """DTCC OIS Policy-Path Query Parameters."""

    __json_schema_extra__ = {"currency": {"multiple_items_allowed": False}}

    currency: Literal["USD", "EUR", "GBP", "JPY", "CAD", "AUD"] = Field(
        default="USD",
        description="Currency of the policy path, read from its forward-starting OIS. Only"
        + " the currencies whose central banks trade meeting-dated OIS in depth are offered.",
    )
    date: dateType | None = Field(
        default=None,
        description="Dissemination date (UTC) the path is built as of; defaults to the most"
        + " recent. It anchors the forward start, so a window ending here is used and a"
        + " trade whose start has since rolled to spot drops out.",
        json_schema_extra={"x-widget_config": {"value": "$currentDate"}},
    )
    lookback_days: int = Field(
        default=10,
        ge=1,
        le=30,
        description="Number of recent daily files to combine, ending on `date`. Meeting-dated"
        + " OIS are thin on any single day, so a handful of files are pooled to price each"
        + " forward start in depth; a node's own freshest day is reported as `as_of_date`.",
    )
    min_trades: int = Field(
        default=3,
        description="Drop a forward start priced by fewer than this many trades across the"
        + " window. The default trims the one-off prints that are not meeting nodes.",
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


class CftcOisPolicyPathData(Data):
    """DTCC OIS Policy-Path Data."""

    date: dateType = Field(
        description="Date the path is built as of.",
        json_schema_extra={"x-widget_config": {"chartDataType": "excluded"}},
    )
    currency: str = Field(
        description="Currency of the path.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Currency", "chartDataType": "excluded"}
        },
    )
    index: str = Field(
        description="Forward start date of the period - the row and chart index.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Forward Start",
                "cellDataType": "date",
                "chartDataType": "category",
            }
        },
    )
    rate: float = Field(
        description="Expected average overnight rate over the period, in percent.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Rate",
                "cellDataType": "number",
                "chartDataType": "series",
                "formatterFn": "percent",
            }
        },
    )
    forward_days: int = Field(
        description="Days from the curve date to the period's start.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Forward (Days)",
                "chartDataType": "excluded",
            }
        },
    )
    start_date: dateType = Field(
        description="Start (effective date) of the period.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Start", "chartDataType": "excluded"}
        },
    )
    end_date: dateType = Field(
        description="End (maturity) of the period.",
        json_schema_extra={
            "x-widget_config": {"headerName": "End", "chartDataType": "excluded"}
        },
    )
    tenor_days: int = Field(
        description="Length of the period, in days.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Tenor (Days)",
                "cellDataType": "number",
                "chartDataType": "excluded",
            }
        },
    )
    num_trades: int = Field(
        description="Trades pricing the node across the window.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Trades",
                "cellDataType": "number",
                "chartDataType": "excluded",
            }
        },
    )
    as_of_date: dateType = Field(
        description="Freshest day the node's trades were disseminated on.",
        json_schema_extra={
            "x-widget_config": {"headerName": "As Of", "chartDataType": "excluded"}
        },
    )
    staleness_days: int = Field(
        description="Days between the node's as-of day and the path's freshest node.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Staleness",
                "cellDataType": "number",
                "chartDataType": "excluded",
            }
        },
    )
    min_rate: float = Field(
        description="Lowest executed rate at the node, in percent.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Min Rate",
                "cellDataType": "number",
                "chartDataType": "excluded",
            }
        },
    )
    max_rate: float = Field(
        description="Highest executed rate at the node, in percent.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Max Rate",
                "cellDataType": "number",
                "chartDataType": "excluded",
            }
        },
    )
    is_capped: bool = Field(
        description="Whether any trade at the node had its notional disseminated at the cap.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Is Capped", "chartDataType": "excluded"}
        },
    )


class CftcOisPolicyPathFetcher(
    Fetcher[CftcOisPolicyPathQueryParams, list[CftcOisPolicyPathData]]
):
    """DTCC OIS Policy-Path Fetcher."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> CftcOisPolicyPathQueryParams:
        """Transform the query params."""
        return CftcOisPolicyPathQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: CftcOisPolicyPathQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> tuple[list[dict], str]:
        """Combine a short window of daily files, keeping the currency's OIS prints."""
        from datetime import datetime

        from openbb_core.app.model.abstract.error import OpenBBError

        from openbb_cftc.utils.constants import ois_fisn
        from openbb_cftc.utils.dtcc import get_available_dates, get_slice

        fisn = ois_fisn(query.currency)
        end = (query.date or datetime.now(UTC).date()).isoformat()
        dates = await get_available_dates("rates")
        window = [day for day in dates if day <= end][-query.lookback_days :]

        if not window:
            raise OpenBBError(
                f"No rates files are published on or before {end}."
                + " History is retained for 366 days."
            )

        combined: list[dict] = []

        for day in window:
            records = await get_slice("rates", day, use_cache=query.use_cache)
            stamp = f"{day}T00:00:00Z"

            for record in records:
                if (record.get("UPI FISN") or "").strip() == fisn:
                    combined.append({**record, "Dissemination Timestamp": stamp})

        return combined, window[-1]

    @staticmethod
    def transform_data(
        query: CftcOisPolicyPathQueryParams,
        data: tuple[list[dict], str],
        **kwargs: Any,
    ) -> AnnotatedResult[list[CftcOisPolicyPathData]]:
        """Build the policy path and insert metadata."""
        from openbb_cftc.utils.constants import OIS_INDICES, ois_fisn
        from openbb_cftc.utils.policy import build_policy_path

        records, reference_date = data
        spec = OIS_INDICES[query.currency]

        path = build_policy_path(
            records,
            fisn=ois_fisn(query.currency),
            currency=query.currency,
            curve_date=dateType.fromisoformat(reference_date),
            min_trades=query.min_trades,
        )

        for node in path:
            node["date"] = dateType.fromisoformat(reference_date)
            node["currency"] = query.currency
            node["index"] = node["start_date"].isoformat()
            for field in ("rate", "min_rate", "max_rate"):
                node[field] *= 100.0

        return AnnotatedResult(
            result=[CftcOisPolicyPathData.model_validate(node) for node in path],
            metadata={
                "currency": query.currency,
                "benchmark": spec["index"],
                "central_bank": spec["central_bank"],
                "curve_date": reference_date,
                "lookback_days": query.lookback_days,
                "nodes": len(path),
            },
        )
