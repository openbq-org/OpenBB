"""OpenBB EIA provider helpers."""

from typing import TYPE_CHECKING

from async_lru import alru_cache
from openbb_core.app.model.abstract.error import OpenBBError

if TYPE_CHECKING:
    from pandas import ExcelFile

API_BASE = "https://api.eia.gov/v2"


async def response_callback(response, _) -> dict:
    """Read an EIA API response, surfacing authentication errors.

    Parameters
    ----------
    response : aiohttp.ClientResponse
        The response to read.

    Returns
    -------
    dict
        The decoded JSON body.
    """
    if response.status == 403:
        res = await response.json()
        code = res.get("error", {}).get("code", "")
        msg = res.get("error", {}).get("message", "An invalid api_key was supplied.")
        raise OpenBBError(f"{code} -> {msg}")
    result = await response.json()
    if isinstance(result, dict) and "error" in result and "response" not in result:
        error = result["error"]
        detail = error.get("message", error) if isinstance(error, dict) else error
        raise OpenBBError(f"EIA API error -> {detail}")
    return result


def build_data_url(request: dict, offset: int, length: int) -> str:
    """Render one page of an EIA data request as a URL.

    Parameters
    ----------
    request : dict
        Request description with 'path', 'api_key', 'frequency', 'data_columns',
        'facets', 'start', 'end', and 'sort' keys.
    offset : int
        Row offset of the page.
    length : int
        Number of rows to request.

    Returns
    -------
    str
        The request URL.
    """
    from urllib.parse import urlencode

    pairs: list[tuple[str, str]] = [("api_key", request["api_key"])]
    if request.get("frequency"):
        pairs.append(("frequency", request["frequency"]))
    for position, column in enumerate(request.get("data_columns") or []):
        pairs.append((f"data[{position}]", column))
    for facet_id, values in (request.get("facets") or {}).items():
        pairs.extend((f"facets[{facet_id}][]", value) for value in values)
    if request.get("start"):
        pairs.append(("start", request["start"]))
    if request.get("end"):
        pairs.append(("end", request["end"]))
    pairs.extend(
        [
            ("sort[0][column]", "period"),
            ("sort[0][direction]", request.get("sort", "desc")),
            ("offset", str(offset)),
            ("length", str(length)),
        ]
    )
    return f"{API_BASE}/{request['path']}/data/?{urlencode(pairs)}"


@alru_cache(maxsize=14)
async def download_excel_file(url: str, use_cache: bool = True) -> "ExcelFile":
    """Download an Excel file, caching it for the session.

    Parameters
    ----------
    url : str
        The file URL.
    use_cache : bool
        Set False to invalidate the cached copy and download again.

    Returns
    -------
    pandas.ExcelFile
        The downloaded workbook.
    """
    from io import BytesIO

    from openbb_core.provider.utils.helpers import amake_request
    from pandas import ExcelFile

    async def callback(response, _) -> "ExcelFile":
        return ExcelFile(BytesIO(await response.read()), engine="calamine")

    if use_cache is False:
        download_excel_file.cache_invalidate(url, True)
        download_excel_file.cache_invalidate(url, False)

    try:
        return await amake_request(url, response_callback=callback)  # ty: ignore[invalid-return-type,invalid-argument-type]
    except Exception as e:
        raise OpenBBError(f"Error downloading the file from the EIA site -> {e}") from e
