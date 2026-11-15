"""USDA FAS report release calendar scraper."""

import re
from datetime import UTC, datetime
from urllib.parse import unquote

BASE_URL = "https://www.fas.usda.gov"
CALENDAR_URL = f"{BASE_URL}/data/scheduled-reports"
SESSION_KEY = "fas.usda.gov"

REPORT_TYPES = {
    "export_sales": "10254",
    "trade_forecast": "10257",
    "world_markets_trade": "10259",
}

COMMODITIES = {
    "coffee": "609",
    "cotton_and_hemp": "13040",
    "cotton": "6",
    "dairy_livestock_and_poultry": "13005",
    "beef": "13008",
    "dairy_products": "13012",
    "pork": "13009",
    "poultry": "13010",
    "fruits_and_vegetables": "8",
    "fresh_fruit": "13013",
    "grains_feeds_and_fodders": "13",
    "corn": "14",
    "rice": "16",
    "wheat": "15",
    "oilseeds": "26",
    "oilseeds_excluding_soybean": "28",
    "soybeans": "27",
    "processed_food_products": "31",
    "tree_nuts": "30",
}

ROW_PATTERN = re.compile(
    r'<div\s+class="c-view__row">(.*?)(?=<div\s+class="c-view__row">|\Z)', re.S
)
MONTH_DAY_PATTERN = re.compile(r'class="fas-date__month-day">([^<]+)<')
DOW_PATTERN = re.compile(r'class="fas-date__dow">([^<]+)<')
TIME_PATTERN = re.compile(r'class="fas-date__time">([^<]+)<')
TAG_PATTERN = re.compile(r'class="c-card__tags">\s*<span>([^<]+)</span>', re.S)
TITLE_PATTERN = re.compile(r'class="c-card__title">([^<]+)<')
URL_PATTERN = re.compile(r'href="([^"]+)"\s+class="c-card__url"')
DTSTART_PATTERN = re.compile(r"DTSTART:(\d{8}T\d{6}Z)")
COUNT_PATTERN = re.compile(r"([\d,]+) results found")


def build_url(
    report_type: str | None = None,
    commodity: str | None = None,
    keyword: str | None = None,
) -> str:
    """Build the calendar URL with optional facet filters.

    Parameters
    ----------
    report_type : str | None
        Report type slug from REPORT_TYPES.
    commodity : str | None
        Commodity slug from COMMODITIES.
    keyword : str | None
        Free-text filter; matches associated commodities, not only titles.

    Returns
    -------
    str
        The calendar URL with any facet query params applied.
    """
    params: list[str] = []
    index = 0
    if report_type is not None:
        params.append(
            f"report_releases[{index}]=report_type:{REPORT_TYPES[report_type]}"
        )
        index += 1
    if commodity is not None:
        params.append(
            f"report_releases[{index}]=report_listing_commodities:{COMMODITIES[commodity]}"
        )
    if keyword is not None:
        params.append(f"keyword={keyword}")
    return f"{CALENDAR_URL}?{'&'.join(params)}" if params else CALENDAR_URL


def _search(pattern: re.Pattern, text: str) -> str | None:
    """Return the first capture group of a pattern, or None."""
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def parse_calendar(html: str) -> list[dict]:
    """Parse the calendar listing HTML into release records.

    The release timestamp comes from each card's embedded iCalendar DTSTART,
    which is the only source carrying a year; the visible date shows just the
    month and day. Cards for releases whose time has already passed omit the
    calendar block, so the timestamp is optional.

    Parameters
    ----------
    html : str
        The listing page HTML.

    Returns
    -------
    list[dict]
        Records with release_date, release_time, day_of_week, report_type,
        title, url, and released keys.
    """
    records: list[dict] = []
    for match in ROW_PATTERN.finditer(html):
        row = match.group(1)
        title = _search(TITLE_PATTERN, row)
        if title is None:
            continue
        url = _search(URL_PATTERN, row)
        dtstart = _search(DTSTART_PATTERN, unquote(row))
        released = dtstart is None
        release_datetime = (
            datetime.strptime(dtstart, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            if dtstart
            else None
        )
        records.append(
            {
                "release_datetime": release_datetime,
                "month_day": _search(MONTH_DAY_PATTERN, row),
                "day_of_week": _search(DOW_PATTERN, row),
                "release_time": _search(TIME_PATTERN, row),
                "report_type": _search(TAG_PATTERN, row),
                "title": title,
                "url": f"{BASE_URL}{url}" if url else None,
                "released": released,
            }
        )
    return records


def parse_result_count(html: str) -> int | None:
    """Parse the listing's stated result count, used to validate the parse."""
    count = _search(COUNT_PATTERN, html)
    return int(count.replace(",", "")) if count else None


async def _get_session():
    """Return the shared Chrome-impersonating session for fas.usda.gov."""
    from openbb_government_us.utils.curl_session import get_session

    return await get_session(SESSION_KEY)


async def afetch_calendar(url: str) -> str:
    """Fetch the calendar listing HTML.

    Parameters
    ----------
    url : str
        The calendar URL, optionally carrying facet filters.

    Returns
    -------
    str
        The response body.

    Raises
    ------
    OpenBBError
        If the request is rejected or returns a non-200 status.
    """
    from openbb_core.app.model.abstract.error import OpenBBError

    session = await _get_session()
    response = await session.get(url)
    if response.status_code != 200:
        raise OpenBBError(
            f"FAS request failed with status {response.status_code} -> {url}"
        )
    return response.text
