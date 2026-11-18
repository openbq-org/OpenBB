"""Sovereign CDS Spread Standard Model."""

from datetime import date as dateType

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import (
    DATA_DESCRIPTIONS,
    QUERY_DESCRIPTIONS,
)
from pydantic import Field


class SovereignCdsSpreadQueryParams(QueryParams):
    """Sovereign CDS Spread Query."""

    country: str | None = Field(
        default=None,
        description=QUERY_DESCRIPTIONS.get("country", "")
        + " Accepts an ISO-3166 alpha-3 code or a country name.",
    )
    as_of_date: dateType | None = Field(
        default=None,
        description="Return spreads as of this date rather than the latest available.",
    )


class SovereignCdsSpreadData(Data):
    """Sovereign CDS Spread Data."""

    date: dateType = Field(description=DATA_DESCRIPTIONS.get("date", ""))
    country: str = Field(description=DATA_DESCRIPTIONS.get("country", ""))
    cds_spread: float | None = Field(
        default=None,
        description="10-year sovereign CDS spread, as a normalized percent.",
        json_schema_extra={"x-unit_measurement": "percent", "x-frontend_multiply": 100},
    )
    cds_spread_net_of_benchmark: float | None = Field(
        default=None,
        description="CDS spread net of the lowest-risk sovereign benchmark"
        " (Switzerland in the source dataset), as a normalized percent.",
        json_schema_extra={"x-unit_measurement": "percent", "x-frontend_multiply": 100},
    )
