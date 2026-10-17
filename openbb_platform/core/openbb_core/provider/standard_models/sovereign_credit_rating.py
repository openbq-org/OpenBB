"""Sovereign Credit Rating Standard Model."""

from datetime import date as dateType

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import (
    DATA_DESCRIPTIONS,
    QUERY_DESCRIPTIONS,
)
from pydantic import Field


class SovereignCreditRatingQueryParams(QueryParams):
    """Sovereign Credit Rating Query."""

    country: str | None = Field(
        default=None,
        description=QUERY_DESCRIPTIONS.get("country", "")
        + " Accepts an ISO-3166 alpha-3 code or a country name.",
    )
    as_of_date: dateType | None = Field(
        default=None,
        description="Return ratings as of this date rather than the latest available.",
    )


class SovereignCreditRatingData(Data):
    """Sovereign Credit Rating Data."""

    date: dateType = Field(description=DATA_DESCRIPTIONS.get("date", ""))
    country: str = Field(description=DATA_DESCRIPTIONS.get("country", ""))
    moodys_rating: str | None = Field(
        default=None, description="Moody's long-term foreign-currency sovereign rating."
    )
    sp_rating: str | None = Field(
        default=None, description="S&P long-term foreign-currency sovereign rating."
    )
    fitch_rating: str | None = Field(
        default=None, description="Fitch long-term foreign-currency sovereign rating."
    )
