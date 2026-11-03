"""Income Statement Standard Model."""

from datetime import date as dateType

from pydantic import Field, NonNegativeInt, field_validator

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import (
    QUERY_DESCRIPTIONS,
)


class IncomeStatementQueryParams(QueryParams):
    """Income Statement Query."""

    symbol: str = Field(description=QUERY_DESCRIPTIONS.get("symbol", ""))
    limit: NonNegativeInt | None = Field(
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


class IncomeStatementData(Data):
    """Income Statement Data."""

    period_ending: dateType = Field(description="The end date of the reporting period.")
    fiscal_period: str | None = Field(
        description="The fiscal period of the report.", default=None
    )
    fiscal_year: int | None = Field(
        description="The fiscal year of the fiscal period.", default=None
    )
    filing_date: dateType | None = Field(
        description="The filing date of the report.", default=None
    )
    is_restated: bool | None = Field(
        description="Whether the period data has been restated in a subsequent filing.",
        default=None,
    )
