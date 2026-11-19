"""USDA FAS PSD commodity circular discovery and download."""

import os
import re
from datetime import UTC, datetime
from typing import Any

CIRCULAR_HOST = "apps.fas.usda.gov"
LISTING_URL = f"https://{CIRCULAR_HOST}/psdonline/CircularsHandler.ashx"
CIRCULARS_BASE_URL = f"https://{CIRCULAR_HOST}/PSDOnline/Circulars/"
NEXT_RELEASE_URL = (
    f"https://{CIRCULAR_HOST}/PSDOnlineApi/api/downloadableData/GetNextRelease"
)

CACHE_ENV_VAR = "OPENBB_USDA_CACHE_DIR"
PDF_HEADERS = {"Accept": "application/pdf"}
RELEASE_FORMAT = "%m/%d/%Y %I:%M%p"
DEFAULT_TTL = 86400
MIN_TTL = 3600
MAX_CARRY_FORWARD = 13

COMMODITIES = {
    "citrus": "Citrus",
    "coffee": "Coffee",
    "cotton": "Cotton",
    "dairy": "Dairy",
    "fruit": "Fruit",
    "grain": "Grain",
    "livestock": "Livestock_poultry",
    "oilseeds": "Oilseeds",
    "stone_fruit": "StoneFruit",
    "sugar": "Sugar",
    "tree_nuts": "TreeNuts",
    "world_production": "production",
}

CIRCULAR_PATH_PATTERN = re.compile(
    r"^/PSDOnline/Circulars/(\d{4})/(\d{2})/([A-Za-z_]+)\.pdf$",
    re.IGNORECASE,
)

_MISSING = object()


def cache_directory() -> str:
    """Resolve the PSD cache directory, honoring the environment override."""
    from openbb_core.app.utils import get_user_cache_directory

    return os.environ.get(CACHE_ENV_VAR) or os.path.join(
        get_user_cache_directory(), "usda", "psd"
    )


def get_cache() -> Any:
    """Open the diskcache store at the resolved cache directory."""
    from diskcache import Cache

    return Cache(cache_directory())


def compute_ttl(next_release: str | None, now: datetime | None = None) -> int:
    """Compute a cache TTL in seconds, expiring at the next circular release.

    Parameters
    ----------
    next_release : str | None
        The next release timestamp as M/D/YYYY H:MMAM, when the source
        publishes one.
    now : datetime | None
        Reference time, defaulting to the current UTC time.

    Returns
    -------
    int
        Seconds until the next release, clamped to at least one hour; the
        one-day default when no future release timestamp is known.
    """
    if not next_release:
        return DEFAULT_TTL
    try:
        expiry = datetime.strptime(next_release.strip(), RELEASE_FORMAT).replace(
            tzinfo=UTC
        )
    except ValueError:
        return DEFAULT_TTL
    remaining = int((expiry - (now or datetime.now(UTC))).total_seconds())
    if remaining <= 0:
        return DEFAULT_TTL
    return max(remaining, MIN_TTL)


async def _get_session():
    """Return an aiohttp session for the PSD Online host."""
    from openbb_core.provider.utils.helpers import get_async_requests_session

    return await get_async_requests_session()


async def get_next_release() -> str | None:
    """Get the next circular release timestamp, as the source reports it.

    Returns
    -------
    str | None
        The timestamp string, or None when the source does not report one.
        The release schedule only sets a cache TTL, so a failure to read it
        is not an error.
    """
    key = "next_release"
    with get_cache() as cache:
        cached = cache.get(key, default=_MISSING)
        if cached is not _MISSING:
            return cached
    release: str | None = None
    try:
        session = await _get_session()
        try:
            response = await session.get(NEXT_RELEASE_URL)
            if response.status == 200:
                release = (await response.text()).strip().strip('"').strip() or None
        finally:
            await session.close()
    except Exception:  # noqa: BLE001
        return None
    with get_cache() as cache:
        cache.set(key, release, expire=MIN_TTL)
    return release


async def cache_ttl() -> int:
    """Get the cache TTL in seconds, expiring at the next circular release."""
    return compute_ttl(await get_next_release())


async def fetch_folders() -> list[tuple[int, int]]:
    """Get every month folder the source publishes, newest first.

    Returns
    -------
    list[tuple[int, int]]
        (year, month) pairs, newest first. The source omits months it never
        published, so this bounds the month universe.

    Raises
    ------
    OpenBBError
        If the listing cannot be read, or is empty.
    """
    import json

    from openbb_core.app.model.abstract.error import OpenBBError

    key = "folders"
    with get_cache() as cache:
        cached = cache.get(key)
        if cached is not None:
            return cached

    session = await _get_session()
    try:
        response = await session.get(LISTING_URL)
        status = response.status
        body = await response.text()
    finally:
        await session.close()

    if status != 200:
        raise OpenBBError(
            f"The PSD circular listing request failed with status {status}"
            f" -> {LISTING_URL}"
        )
    payload = json.loads(body)
    folders = sorted(
        {
            (int(year["CalendarYear"]), int(month["Item1"]))
            for year in payload.get("CircularSets") or []
            for month in year.get("Months") or []
        },
        reverse=True,
    )
    if not folders:
        raise OpenBBError(f"The PSD circular listing is empty -> {LISTING_URL}")
    with get_cache() as cache:
        cache.set(key, folders, expire=await cache_ttl())
    return folders


def _commodity_key(commodity: str) -> str:
    """Normalize a commodity to its key.

    Parameters
    ----------
    commodity : str
        A commodity key, in any case.

    Returns
    -------
    str
        The normalized key.

    Raises
    ------
    OpenBBError
        If the commodity is not one the source publishes.
    """
    from openbb_core.app.model.abstract.error import OpenBBError

    key = commodity.lower().strip()
    if key not in COMMODITIES:
        raise OpenBBError(
            f"Unsupported PSD commodity -> '{commodity}'."
            f" Expected one of: {', '.join(COMMODITIES)}."
        )
    return key


def circular_url(year: int, month: int, commodity: str) -> str:
    """Build the static URL of a commodity's circular in a month folder.

    Parameters
    ----------
    year : int
        The folder's calendar year.
    month : int
        The folder's month.
    commodity : str
        A supported commodity key.

    Returns
    -------
    str
        The circular's URL.

    Raises
    ------
    OpenBBError
        If the commodity is not one the source publishes.
    """
    api_commodity = COMMODITIES[_commodity_key(commodity)]
    return f"{CIRCULARS_BASE_URL}{year}/{month:02d}/{api_commodity}.pdf"


def circular_from_url(url: str) -> dict:
    """Return the circular a static PSD URL addresses.

    Parameters
    ----------
    url : str
        A circular URL, as built by ``circular_url``.

    Returns
    -------
    dict
        The commodity key, year, and month the URL addresses.

    Raises
    ------
    OpenBBError
        If the URL does not address a PSD circular, or names a commodity the
        source does not publish.
    """
    from urllib.parse import urlparse

    from openbb_core.app.model.abstract.error import OpenBBError

    parsed = urlparse(url)
    match = CIRCULAR_PATH_PATTERN.match(parsed.path)
    if parsed.netloc != CIRCULAR_HOST or match is None:
        raise OpenBBError(
            f"Invalid PSD circular URL -> {url}. Expected a"
            f" https://{CIRCULAR_HOST}/PSDOnline/Circulars/YYYY/MM/Commodity.pdf URL."
        )
    year, month, api_commodity = match.groups()
    for key, name in COMMODITIES.items():
        if name.lower() == api_commodity.lower():
            return {"commodity": key, "year": int(year), "month": int(month)}
    raise OpenBBError(f"Unknown PSD commodity -> '{api_commodity}' in {url}.")


def circular_file_name(url: str) -> str:
    """Build a descriptive PDF file name for a circular URL."""
    circular = circular_from_url(url)
    return (
        f"psd_report_{circular['commodity']}"
        f"_{circular['year']}_{circular['month']:02d}.pdf"
    )


async def head_circular(url: str) -> dict | None:
    """Read a circular's headers without downloading it.

    Parameters
    ----------
    url : str
        A circular URL, as built by ``circular_url``.

    Returns
    -------
    dict | None
        The etag, last_modified, and length, or None when the source does not
        hold the file.

    Raises
    ------
    OpenBBError
        If the source answers with anything but 200 or 404.
    """
    from openbb_core.app.model.abstract.error import OpenBBError

    key = f"head:{url}"
    with get_cache() as cache:
        cached = cache.get(key, default=_MISSING)
        if cached is not _MISSING:
            return cached

    session = await _get_session()
    try:
        response = await session.head(url, headers=PDF_HEADERS)
        status = response.status
        headers = response.headers
    finally:
        await session.close()

    if status not in (200, 404):
        raise OpenBBError(
            f"The PSD circular request failed with status {status} -> {url}"
        )
    head: dict | None = None
    if status == 200:
        length = headers.get("Content-Length")
        head = {
            "etag": headers.get("ETag"),
            "last_modified": headers.get("Last-Modified"),
            "length": int(length) if length else None,
        }
    with get_cache() as cache:
        cache.set(key, head, expire=await cache_ttl())
    return head


def _released_at(last_modified: str | None) -> datetime | None:
    """Parse an HTTP Last-Modified header into a datetime."""
    from email.utils import parsedate_to_datetime

    if not last_modified:
        return None
    try:
        return parsedate_to_datetime(last_modified)
    except (TypeError, ValueError):
        return None


async def _resolve_latest(
    commodity: str, folders: list[tuple[int, int]]
) -> dict | None:
    """Resolve a commodity's newest circular and the month that published it.

    Parameters
    ----------
    commodity : str
        A supported commodity key.
    folders : list[tuple[int, int]]
        The published month folders, newest first.

    Returns
    -------
    dict | None
        The resolved circular, or None when no folder holds the commodity.
    """
    window = folders[: MAX_CARRY_FORWARD + 1]
    anchor = -1
    head: dict | None = None
    for index, (year, month) in enumerate(window):
        head = await head_circular(circular_url(year, month, commodity))
        if head is not None:
            anchor = index
            break
    if head is None:
        return None

    etag = head["etag"]
    low, high = anchor, len(window) - 1
    while low < high:
        mid = (low + high + 1) // 2
        year, month = window[mid]
        candidate = await head_circular(circular_url(year, month, commodity))
        if candidate is not None and candidate["etag"] == etag:
            low = mid
        else:
            high = mid - 1

    year, month = window[low]
    return {
        "commodity": commodity,
        "api_commodity": COMMODITIES[commodity],
        "year": year,
        "month": month,
        "url": circular_url(year, month, commodity),
        "released_at": _released_at(head["last_modified"]),
        "size": head["length"],
    }


async def latest_circulars(commodity: str | None = None) -> list[dict]:
    """Get the newest circular for each commodity, with its true report month.

    Parameters
    ----------
    commodity : str | None
        A supported commodity key, or None for every commodity.

    Returns
    -------
    list[dict]
        One record per commodity that resolves, carrying the commodity key,
        the source's commodity name, the year and month that published the
        circular, its URL, its release timestamp, and its size in bytes.

    Raises
    ------
    OpenBBError
        If the commodity is not one the source publishes, or the month
        listing cannot be read.
    """
    import asyncio

    keys = [_commodity_key(commodity)] if commodity else list(COMMODITIES)
    folders = await fetch_folders()
    resolved = await asyncio.gather(*(_resolve_latest(k, folders) for k in keys))
    return [circular for circular in resolved if circular is not None]


async def historical_circulars(commodity: str) -> list[dict]:
    """Get every distinct historical circular for one commodity, newest first.

    Parameters
    ----------
    commodity : str
        A supported commodity key.

    Returns
    -------
    list[dict]
        One record per distinct published circular, carrying the commodity key,
        the source's commodity name, the year and month that published it, its
        URL, its release timestamp, and its size in bytes. The source carries a
        circular forward into later month folders, so folders that share an etag
        are collapsed to the earliest one, the month that actually published it.

    Raises
    ------
    OpenBBError
        If the commodity is not one the source publishes, or the month listing
        cannot be read.
    """
    import asyncio

    key = _commodity_key(commodity)
    folders = await fetch_folders()
    heads = await asyncio.gather(
        *(head_circular(circular_url(year, month, key)) for year, month in folders)
    )
    by_etag: dict[str, dict] = {}
    for (year, month), head in zip(folders, heads):
        if head is None:
            continue
        by_etag[head["etag"]] = {
            "commodity": key,
            "api_commodity": COMMODITIES[key],
            "year": year,
            "month": month,
            "url": circular_url(year, month, key),
            "released_at": _released_at(head["last_modified"]),
            "size": head["length"],
        }
    return sorted(
        by_etag.values(), key=lambda item: (item["year"], item["month"]), reverse=True
    )


async def afetch_circular(url: str) -> bytes:
    """Fetch a circular's PDF bytes from its static URL.

    Parameters
    ----------
    url : str
        A circular URL, as built by ``circular_url``.

    Returns
    -------
    bytes
        The PDF content.

    Raises
    ------
    OpenBBError
        If the URL does not address a PSD circular, the source does not serve
        it, or the response is not a PDF.
    """
    from openbb_core.app.model.abstract.error import OpenBBError

    circular_from_url(url)
    key = f"file:{url}"
    with get_cache() as cache:
        cached = cache.get(key)
        if cached is not None:
            return cached

    session = await _get_session()
    try:
        response = await session.get(url, headers=PDF_HEADERS)
        status = response.status
        content = await response.read()
    finally:
        await session.close()

    if status != 200:
        raise OpenBBError(
            f"The PSD circular request failed with status {status} -> {url}"
        )
    if not content.startswith(b"%PDF"):
        raise OpenBBError(
            f"The PSD circular at {url} returned {len(content)} bytes"
            " that are not a PDF."
        )
    with get_cache() as cache:
        cache.set(key, content, expire=await cache_ttl())
    return content
