"""Congress Mandated Reports Model."""

from datetime import (
    date as dateType,
    datetime,
)
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from pydantic import ConfigDict, Field

MAX_PAGESIZE = 1000


class CongressMandatedReportsQueryParams(QueryParams):
    """Congress Mandated Reports Query Parameters."""

    __json_schema_extra__ = {
        "congress": {
            "x-widget_config": {"type": "number"},
        },
    }

    congress: int | None = Field(
        default=None,
        description="Congress number (e.g., 119 for the 119th Congress)."
        + " When None, defaults to the current Congress.",
    )
    limit: int | None = Field(
        default=None,
        description=QUERY_DESCRIPTIONS.get("limit", "")
        + f" When None, default sets to 100. Maximum is {MAX_PAGESIZE} per request.",
    )
    offset: int | None = Field(
        default=None,
        description="The starting record returned. 0 is the first record.",
    )


class CongressMandatedReportsData(Data):
    """Congress Mandated Reports Data."""

    model_config = ConfigDict(
        json_schema_extra={
            "x-widget_config": {
                "$.name": "Congressionally Mandated Reports",
                "$.category": "Government",
                "$.subCategory": "Congress",
                "$.description": "Reports submitted to Congress by federal agencies.",
                "$.params": [
                    {
                        "paramName": "package_id",
                        "label": "Package ID",
                        "description": "Ghost parameter to group by the report package."
                        + " Create a group and use the 'Mandated Report Viewer' widget"
                        + " to view the report.",
                        "type": "text",
                        "value": None,
                        "show": True,
                    },
                ],
                "$.refetchInterval": False,
            },
        }
    )

    package_id: str = Field(
        description="The GovInfo package identifier for the report.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "▸ Group: Package ID",
                "headerTooltip": "Click a cell here to group by this report and view"
                + " it in the 'Mandated Report Viewer' widget.",
                "pinned": "left",
                "renderFn": "cellOnClick",
                "renderFnParams": {
                    "actionType": "groupBy",
                    "groupByParamName": "package_id",
                },
            },
        },
    )
    publication_date: dateType | None = Field(
        default=None, description="The date the report was published."
    )
    title: str = Field(description="The report title.")
    submitting_agency: str = Field(description="The agency that submitted the report.")
    pdf: str = Field(
        description="URL to the report in PDF format.",
        json_schema_extra={"x-widget_config": {"hide": True}},
    )
    details_link: str | None = Field(
        default=None,
        description="URL to the GovInfo details page for the report.",
        json_schema_extra={"x-widget_config": {"hide": True}},
    )


class CongressMandatedReportsFetcher(
    Fetcher[
        CongressMandatedReportsQueryParams,
        list[CongressMandatedReportsData],
    ]
):
    """Transform the query, extract and transform data from the GovInfo search."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> CongressMandatedReportsQueryParams:
        """Transform the query params."""
        return CongressMandatedReportsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: CongressMandatedReportsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list:
        """Extract Congressionally Mandated Reports from the GovInfo search."""
        from openbb_government_us.congress.utils.bulk import fetch_cmr
        from openbb_government_us.congress.utils.helpers import year_to_congress

        congress = (
            query.congress
            if query.congress is not None
            else year_to_congress(datetime.now().year)
        )
        pagesize = min(query.limit if query.limit else 100, MAX_PAGESIZE)

        return await fetch_cmr(congress, pagesize=pagesize, offset=query.offset or 0)

    @staticmethod
    def transform_data(
        query: CongressMandatedReportsQueryParams, data: list, **kwargs: Any
    ) -> list[CongressMandatedReportsData]:
        """Transform raw report records into CongressMandatedReportsData models."""
        return [CongressMandatedReportsData(**record) for record in data]
