"""SEC Institutions Search Model."""

from typing import Any

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field


class SecInstitutionsSearchQueryParams(QueryParams):
    """SEC Institutions Search Query.

    Source: https://sec.gov/
    """

    query: str | None = Field(
        description="Search query.",
        default=None,
        json_schema_extra={"sec": {"x-widget_config": {"optional": False}}},
    )

    use_cache: bool = Field(
        default=True,
        description="Whether or not to use cache.",
    )


class SecInstitutionsSearchData(Data):
    """SEC Institutions Search Data."""

    __alias_dict__ = {
        "name": "Institution",
        "cik": "CIK Number",
    }

    name: str | None = Field(
        default=None,
        description="The name of the institution.",
    )
    cik: str | int | None = Field(
        default=None,
        description="Central Index Key (CIK)",
    )


class SecInstitutionsSearchFetcher(
    Fetcher[
        SecInstitutionsSearchQueryParams,
        list[SecInstitutionsSearchData],
    ]
):
    """SEC Institutions Search Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> SecInstitutionsSearchQueryParams:
        """Transform the query."""
        return SecInstitutionsSearchQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: SecInstitutionsSearchQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Return the raw data from the SEC endpoint."""
        from openbb_sec.utils.helpers import get_all_ciks

        if not query.query:
            raise OpenBBError("Enter an institution name to search for.")
        institutions = await get_all_ciks(use_cache=query.use_cache)
        hp = institutions["Institution"].str.contains(query.query, case=False)
        return institutions[hp].astype(str).to_dict("records")

    @staticmethod
    def transform_data(
        query: SecInstitutionsSearchQueryParams, data: list[dict], **kwargs: Any
    ) -> list[SecInstitutionsSearchData]:
        """Transform the data to the standard format."""
        return [SecInstitutionsSearchData.model_validate(d) for d in data]
