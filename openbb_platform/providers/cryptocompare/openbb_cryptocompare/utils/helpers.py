"""Helper utilities for the CryptoCompare provider."""

from __future__ import annotations

from typing import Any

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils.errors import EmptyDataError, UnauthorizedError
from openbb_core.provider.utils.helpers import amake_request


async def _response_callback(response, _):
    """Normalize CryptoCompare responses and raise for status codes."""
    if response.status == 401:
        message = await response.text()
        raise UnauthorizedError(f"Unauthorized CryptoCompare request -> {message}")

    return await response.json()


async def get_cryptocompare_data(url: str, **kwargs: Any) -> dict:
    """Execute an HTTP request against the CryptoCompare API."""
    data = await amake_request(url, response_callback=_response_callback, **kwargs)

    if isinstance(data, dict) and data.get("Response") == "Error":
        message = data.get("Message") or data.get("Data", {}).get("Message")
        raise OpenBBError(f"CryptoCompare Error -> {message or 'unknown error'}")

    if (
        isinstance(data, dict)
        and data.get("Data")
        and isinstance(data["Data"], dict)
        and isinstance(data["Data"].get("Data"), list)
        and len(data["Data"]["Data"]) == 0
    ):
        raise EmptyDataError("CryptoCompare returned no data.")

    return data


def build_hist_url(
    query: "CryptoCompareCryptoHistoricalQueryParams",
    api_key: str | None,
) -> str:
    """Build a histogram URL for the requested query."""
    params = [
        f"fsym={query._fsym}",  # pylint: disable=protected-access
        f"tsym={query._tsym}",  # pylint: disable=protected-access
        f"aggregate={query._aggregate}",  # pylint: disable=protected-access
        f"limit={query._limit}",  # pylint: disable=protected-access
        f"toTs={query._to_ts}",  # pylint: disable=protected-access
    ]

    if api_key:
        params.append(f"api_key={api_key}")

    return f"https://min-api.cryptocompare.com/data/v2/{query._endpoint}?" + "&".join(  # pylint: disable=protected-access
        params
    )
