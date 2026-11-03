"""Key Metrics Standard Model."""

from datetime import date as dateType

from pydantic import Field, field_validator

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import (
    DATA_DESCRIPTIONS,
    QUERY_DESCRIPTIONS,
)


class KeyMetricsQueryParams(QueryParams):
    """Key Metrics Query."""

    symbol: str = Field(description=QUERY_DESCRIPTIONS.get("symbol", ""))
    as_of_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("as_of_date", "")
    )

    @field_validator("symbol", mode="before", check_fields=False)
    @classmethod
    def to_upper(cls, v: str) -> str:
        """Convert field to uppercase."""
        return v.upper()


class KeyMetricsData(Data):
    """Key Metrics Data."""

    symbol: str = Field(description=DATA_DESCRIPTIONS.get("symbol", ""))
    period_ending: dateType | None = Field(
        default=None, description="End date of the reporting period."
    )
    fiscal_year: int | None = Field(
        default=None, description="Fiscal year for the fiscal period, if available."
    )
    fiscal_period: str | None = Field(
        default=None, description="Fiscal period for the data, if available."
    )
    filing_date: dateType | None = Field(
        default=None, description="The filing date of the report."
    )
    is_restated: bool | None = Field(
        default=None,
        description="Whether the period data has been restated in a subsequent filing.",
    )
    currency: str | None = Field(
        default=None,
        description="Currency in which the data is reported.",
    )
    market_cap: int | float | None = Field(
        default=None, description=DATA_DESCRIPTIONS.get("market_cap", "")
    )
