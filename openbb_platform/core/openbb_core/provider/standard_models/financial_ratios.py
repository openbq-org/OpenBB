"""Financial Ratios Standard Model."""

from datetime import date as dateType

from pydantic import Field, field_validator

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import (
    DATA_DESCRIPTIONS,
    QUERY_DESCRIPTIONS,
)


class FinancialRatiosQueryParams(QueryParams):
    """Financial Ratios Query."""

    symbol: str = Field(description=QUERY_DESCRIPTIONS.get("symbol", ""))
    limit: int | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("limit", "")
    )
    as_of_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("as_of_date", "")
    )

    @field_validator("symbol", mode="before", check_fields=False)
    @classmethod
    def to_upper(cls, v: str):
        """Convert field to uppercase."""
        return v.upper()


class FinancialRatiosData(Data):
    """Financial Ratios Standard Model."""

    symbol: str | None = Field(
        default=None, description=DATA_DESCRIPTIONS.get("symbol", "")
    )
    period_ending: dateType | None = Field(
        default=None, description=DATA_DESCRIPTIONS.get("date", "")
    )
    fiscal_period: str | None = Field(
        default=None, description="Period of the financial ratios."
    )
    fiscal_year: int | None = Field(default=None, description="Fiscal year.")
    filing_date: dateType | None = Field(
        default=None, description="The filing date of the report."
    )
    is_restated: bool | None = Field(
        default=None,
        description="Whether the period data has been restated in a subsequent filing.",
    )
