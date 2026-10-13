"""FFIEC List of Banks in Peer Group Model."""

from typing import Any

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_federal_reserve.utils.peer_groups import (
    STATIC_PEER_GROUPS,
    peer_group_options,
)

_PEER_GROUP_OPTIONS = peer_group_options()
_PEER_GROUP_NAMES = list(STATIC_PEER_GROUPS)


class FederalReserveListOfBanksPeerGroupQueryParams(QueryParams):
    """FFIEC List of Banks in Peer Group Query Parameters."""

    __json_schema_extra__ = {
        "peer_group": {
            "x-widget_config": {"options": _PEER_GROUP_OPTIONS},
        },
    }

    peer_group: str = Field(
        default="1",
        description="The UBPR peer-group name (e.g. '1', 'NATIONAL', 'ALCOM').",
        json_schema_extra={"choices": list(_PEER_GROUP_NAMES)},
    )
    date: str | None = Field(
        default=None,
        description="The reporting period end date; defaults to the latest cycle.",
    )


class FederalReserveListOfBanksPeerGroupData(Data):
    """FFIEC List of Banks in Peer Group Data."""

    rssd_id: str | None = Field(default=None, description="The bank's RSSD identifier.")
    fdic_cert: str | None = Field(
        default=None, description="The bank's FDIC certificate number."
    )
    charter_class: str | None = Field(
        default=None, description="The bank's charter class code."
    )
    name: str | None = Field(default=None, description="The bank's legal name.")
    city: str | None = Field(default=None, description="The bank's city.")
    state: str | None = Field(
        default=None, description="The bank's state abbreviation."
    )
    state_name: str | None = Field(default=None, description="The bank's state name.")
    offices: int | None = Field(
        default=None, description="The bank's number of offices."
    )
    average_assets: int | None = Field(
        default=None, description="The bank's average assets, in U.S. dollars."
    )
    net_income: int | None = Field(
        default=None,
        description="The bank's quarterly net income, in U.S. dollars.",
    )
    latitude: float | None = Field(
        default=None, description="The bank's headquarters latitude."
    )
    longitude: float | None = Field(
        default=None, description="The bank's headquarters longitude."
    )


class FederalReserveListOfBanksPeerGroupFetcher(
    Fetcher[
        FederalReserveListOfBanksPeerGroupQueryParams,
        list[FederalReserveListOfBanksPeerGroupData],
    ]
):
    """FFIEC List of Banks in Peer Group Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FederalReserveListOfBanksPeerGroupQueryParams:
        """Transform the query params."""
        query = FederalReserveListOfBanksPeerGroupQueryParams(**params)
        if not str(query.peer_group).strip():
            raise OpenBBError(
                ValueError("Provide a `peer_group` to identify the peer group.")
            )
        return query

    @staticmethod
    def extract_data(
        query: FederalReserveListOfBanksPeerGroupQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch the peer-group roster from the FFIEC CDR report router."""
        from openbb_federal_reserve.utils.ubpr_report import (
            fetch_list_of_banks,
            report_cycles,
        )

        cycles = report_cycles()
        if not cycles:
            raise EmptyDataError("The reporting-cycle list could not be retrieved.")
        cycle = next(
            (c for c in cycles if c["enddateformatted"] == query.date),
            cycles[0],
        )
        rows = fetch_list_of_banks(query.peer_group, cycle["reportingcycleid"])
        if not rows:
            raise EmptyDataError("The request was returned empty.")
        return rows

    @staticmethod
    def transform_data(
        query: FederalReserveListOfBanksPeerGroupQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FederalReserveListOfBanksPeerGroupData]:
        """Scale dollar amounts to U.S. dollars and sort by average assets."""
        for row in data:
            for field in ("average_assets", "net_income"):
                amount = row.get(field)
                if amount is not None:
                    row[field] = round(amount * 1000)
        ordered = sorted(
            data,
            key=lambda r: (
                r.get("average_assets") is None,
                -(r.get("average_assets") or 0),
            ),
        )
        return [
            FederalReserveListOfBanksPeerGroupData.model_validate(row)
            for row in ordered
        ]
