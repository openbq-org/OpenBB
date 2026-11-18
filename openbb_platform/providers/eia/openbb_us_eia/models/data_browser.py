"""EIA Data Browser model."""

from datetime import date as dateType
from typing import Any, Literal

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from pydantic import Field, field_validator

from openbb_us_eia.utils.api_query import EiaApiData, _snake, maybe_float, paginate


class EiaDataBrowserQueryParams(QueryParams):
    """EIA Data Browser query parameters."""

    route: str = Field(
        description="The API route to query, e.g. 'petroleum/pri/spt' or"
        " 'electricity/rto/region-data'.",
    )
    frequency: str | None = Field(
        default=None,
        description="The data frequency id, e.g. 'monthly'."
        " The default is the route's native frequency.",
    )
    data_type: str | None = Field(
        default=None,
        description="Data column id(s) to return, comma-separated,"
        " e.g. 'value' or 'quantity,price'."
        " The default returns every column available for the route.",
    )
    facets: str | None = Field(
        default=None,
        description="Facet filters as 'facetId:value' pairs separated by"
        " semicolons, with multiple values comma-separated,"
        " e.g. 'duoarea:NUS;product:EPD2D,EPD2DXL0'.",
    )
    start_date: dateType | None = Field(
        default=None,
        description=QUERY_DESCRIPTIONS.get("start_date", ""),
    )
    end_date: dateType | None = Field(
        default=None,
        description=QUERY_DESCRIPTIONS.get("end_date", ""),
    )
    sort: Literal["asc", "desc"] = Field(
        default="asc",
        description="Sort the results by date.",
    )
    limit: int | None = Field(
        default=None,
        gt=0,
        description="Maximum number of rows to return."
        " The default returns all rows, paginating requests as needed."
        " A request matching more than 500,000 rows returns the newest 5,000"
        " unless a limit is set.",
    )

    @field_validator("route", mode="after")
    @classmethod
    def _clean_route(cls, value: str) -> str:
        """Strip separators and any trailing '/data' segment from the route."""
        route = value.strip().strip("/")
        return route.removesuffix("/data")

    @property
    def facet_query(self) -> dict[str, list[str]]:
        """Parse the facets string into a facet id to values mapping."""
        query: dict[str, list[str]] = {}
        for raw_pair in (self.facets or "").split(";"):
            pair = raw_pair.strip()
            if not pair:
                continue
            if ":" not in pair:
                raise OpenBBError(
                    ValueError(
                        f"Invalid facet filter '{pair}'."
                        " Use 'facetId:value1,value2' pairs separated by semicolons."
                    )
                )
            facet_id, values = pair.split(":", 1)
            query[facet_id.strip()] = [
                item.strip() for item in values.split(",") if item.strip()
            ]
        return query


class EiaDataBrowserData(EiaApiData):
    """EIA Data Browser data."""


class EiaDataBrowserFetcher(
    Fetcher[EiaDataBrowserQueryParams, list[EiaDataBrowserData]]
):
    """EIA Data Browser fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> EiaDataBrowserQueryParams:
        """Transform the query parameters."""
        query = EiaDataBrowserQueryParams(**params)
        _ = query.facet_query
        return query

    @staticmethod
    async def aextract_data(
        query: EiaDataBrowserQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Resolve the route's metadata and request all pages of data."""
        from openbb_core.provider.utils.helpers import amake_request, amake_requests

        from openbb_us_eia.utils.catalog import format_period
        from openbb_us_eia.utils.helpers import (
            API_BASE,
            build_data_url,
            response_callback,
        )

        api_key = credentials.get("eia_api_key", "") if credentials else ""
        metadata = await amake_request(
            f"{API_BASE}/{query.route}?api_key={api_key}",
            response_callback=response_callback,
        )
        node = metadata.get("response", {})  # ty: ignore[unresolved-attribute]
        if node.get("routes"):
            children = ", ".join(child["id"] for child in node["routes"])
            raise OpenBBError(
                f"'{query.route}' is not a data route. Child routes: {children}"
            )
        frequencies = {freq["id"]: freq for freq in node.get("frequency", []) or []}
        if not frequencies:
            raise OpenBBError(f"'{query.route}' is not a valid EIA data route.")
        frequency = query.frequency or node.get("defaultFrequency")
        if frequency not in frequencies:
            raise OpenBBError(
                f"Frequency '{query.frequency}' is not available for"
                f" '{query.route}'. Choices: {', '.join(frequencies)}"
            )
        period_format = frequencies[frequency].get("format", "YYYY-MM-DD")

        data_columns = list(node.get("data") or {})
        if query.data_type:
            requested = [
                item.strip() for item in query.data_type.split(",") if item.strip()
            ]
            invalid = [item for item in requested if item not in data_columns]
            if invalid:
                raise OpenBBError(
                    f"Invalid data_type value(s) {', '.join(invalid)} for"
                    f" '{query.route}'. Choices: {', '.join(data_columns)}"
                )
            data_columns = requested

        facet_ids = {facet["id"] for facet in node.get("facets", []) or []}
        facets = query.facet_query
        unknown = sorted(set(facets) - facet_ids)
        if unknown:
            raise OpenBBError(
                f"Invalid facet id(s) {', '.join(unknown)} for '{query.route}'."
                f" Choices: {', '.join(sorted(facet_ids))}"
            )

        request = {
            "path": query.route,
            "api_key": api_key,
            "frequency": frequency,
            "data_columns": data_columns,
            "facets": facets,
            "facet_params": {facet_id: facet_id for facet_id in facet_ids},
            "coverage": (node.get("startPeriod"), node.get("endPeriod")),
            "start": (
                format_period(query.start_date, period_format)
                if query.start_date
                else None
            ),
            "end": (
                format_period(query.end_date, period_format) if query.end_date else None
            ),
            "sort": query.sort,
        }
        result = await paginate(
            build_data_url,
            request,
            limit=query.limit,
            amake_request=amake_request,
            amake_requests=amake_requests,
            response_callback=response_callback,
        )
        result["period_format"] = period_format
        result["data_columns"] = data_columns
        return result

    @staticmethod
    def transform_data(
        query: EiaDataBrowserQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> list[EiaDataBrowserData]:
        """Normalize column names, parse periods, and sort the rows."""
        from openbb_us_eia.utils.catalog import parse_period

        date_format = data.get("date_format") or data["period_format"]
        numeric = {_snake(column) for column in data["data_columns"]}
        rows: list[dict] = []
        for row in data["rows"]:
            record: dict[str, Any] = {
                "date": parse_period(str(row["period"]), date_format)
            }
            for key, value in row.items():
                if key == "period":
                    continue
                name = _snake(key)
                record[name] = maybe_float(value) if name in numeric else value
            rows.append(record)
        rows.sort(key=lambda row: row["date"], reverse=query.sort == "desc")
        if query.limit is not None:
            rows = rows[: query.limit]
        return [EiaDataBrowserData(**row) for row in rows]
