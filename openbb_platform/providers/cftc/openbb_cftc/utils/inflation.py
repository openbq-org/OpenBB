"""Published inflation index histories and zero-coupon inflation curves."""

from collections.abc import Iterable
from datetime import (
    UTC,
    date as dateType,
)

BLS_TIMESERIES_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data"

ONS_TIMESERIES_URL = (
    "https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries"
)

EUROSTAT_URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_minr"
)

INFLATION_FISN_PREFIX = "NA/Swap Infl Idx"


def inflation_fisn(currency: str) -> str:
    """Return the UPI FISN of a currency's zero-coupon inflation swap."""
    return f"{INFLATION_FISN_PREFIX} {currency.upper()}"


INFLATION_INDICES: dict[str, dict] = {
    "USCPI": {
        "label": "US CPI-U NSA",
        "currency": "USD",
        "source": "bls",
        "series": "CUUR0000SA0",
        "lag_months": 3,
        "interpolate": True,
    },
    "UKRPI": {
        "label": "UK RPI",
        "currency": "GBP",
        "source": "ons",
        "series": "chaw/mm23",
        "lag_months": 2,
        "interpolate": False,
    },
    "EURHICPXT": {
        "label": "Euro area HICP excluding tobacco",
        "currency": "EUR",
        "source": "eurostat",
        "series": "M.I15.TOT_X_TBC.EA",
        "lag_months": 3,
        "interpolate": True,
    },
}

_UNDERLIER_TOKENS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("UK-RPI", "GB-RPI", "UKRPI"), "UKRPI"),
    (("EXT-CPI", "HICP", "EUR-CPI"), "EURHICPXT"),
    (("CPI-U", "CPURNSA", "USA-CPI", "US-CPI"), "USCPI"),
)


def index_for_inflation_underlier(underlier: str | None) -> str | None:
    """Return the published index an inflation underlier references, or None."""
    name = (underlier or "").strip().upper().replace(" ", "-")

    if not name:
        return None

    for tokens, key in _UNDERLIER_TOKENS:
        if any(token in name for token in tokens):
            return key

    return None


def _month_start(day: dateType) -> dateType:
    """First day of a date's month."""
    return day.replace(day=1)


def _shift_months(day: dateType, months: int) -> dateType:
    """Shift a month-start date back by a number of months."""
    total = (day.year * 12 + day.month - 1) - months

    return dateType(total // 12, total % 12 + 1, 1)


def _days_in_month(day: dateType) -> int:
    """Return the number of days in a date's month."""
    import calendar

    return calendar.monthrange(day.year, day.month)[1]


def backfill_gaps(levels: dict[dateType, float]) -> dict[dateType, float]:
    """Fill months the publisher skipped, interpolating between the levels around them."""
    if len(levels) < 2:
        return dict(levels)

    ordered = sorted(levels)
    filled = dict(levels)

    for earlier, later in zip(ordered, ordered[1:]):
        span = (later.year * 12 + later.month) - (earlier.year * 12 + earlier.month)

        if span <= 1:
            continue

        step = (levels[later] - levels[earlier]) / span

        for offset in range(1, span):
            filled[_shift_months(earlier, -offset)] = levels[earlier] + step * offset

    return filled


def reference_index(
    levels: dict[dateType, float],
    day: dateType,
    lag_months: int,
    interpolate: bool,
) -> float | None:
    """Return the reference index for a date, on the TIPS lag and interpolation."""
    base = _shift_months(_month_start(day), lag_months)
    first = levels.get(base)

    if first is None:
        return None

    if not interpolate:
        return first

    following = levels.get(_shift_months(base, -1))

    if following is None:
        return None

    return first + (day.day - 1) / _days_in_month(day) * (following - first)


def index_ratio(
    levels: dict[dateType, float],
    base_date: dateType,
    day: dateType,
    lag_months: int,
    interpolate: bool,
) -> float | None:
    """Return a trade's index ratio between its base date and a later date."""
    base = reference_index(levels, base_date, lag_months, interpolate)
    current = reference_index(levels, day, lag_months, interpolate)

    if base is None or current is None or base <= 0:
        return None

    return current / base


BLS_MAX_YEARS = 10

INDEX_HISTORY_YEARS = 30


async def _fetch_bls_window(
    series: str, start_year: int, end_year: int
) -> dict[dateType, float]:
    """Fetch one BLS window of at most ten years, from the key-free public API."""
    import json

    import aiohttp
    from openbb_core.app.model.abstract.error import OpenBBError

    payload = {
        "seriesid": [series],
        "startyear": str(start_year),
        "endyear": str(end_year),
    }

    async with (
        aiohttp.ClientSession() as session,
        session.post(
            BLS_TIMESERIES_URL,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        ) as response,
    ):
        response.raise_for_status()
        body = await response.json()

    series_list = (body or {}).get("Results", {}).get("series")

    if not series_list:
        reported = "; ".join((body or {}).get("message") or [])

        raise OpenBBError(
            f"The BLS API did not return {series}"
            + (f" -> {reported}" if reported else ".")
        )

    levels: dict[dateType, float] = {}

    for row in series_list[0].get("data") or []:
        period = (row.get("period") or "").strip()

        if not period.startswith("M") or period == "M13":
            continue

        try:
            level = float((row.get("value") or "").strip())
        except ValueError:
            continue

        levels[dateType(int(row["year"]), int(period[1:]), 1)] = level

    return levels


async def _fetch_bls(
    series: str, start_year: int, end_year: int
) -> dict[dateType, float]:
    """Fetch a BLS timeseries, split into the ten-year windows the API serves."""
    import asyncio

    bounds = [
        (year, min(year + BLS_MAX_YEARS - 1, end_year))
        for year in range(start_year, end_year + 1, BLS_MAX_YEARS)
    ]
    windows = await asyncio.gather(
        *(_fetch_bls_window(series, low, high) for low, high in bounds)
    )
    levels: dict[dateType, float] = {}

    for window in windows:
        levels.update(window)

    return levels


async def _fetch_ons(series: str) -> dict[dateType, float]:
    """Fetch an ONS monthly timeseries, served as JSON."""
    import aiohttp
    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_cftc.utils.search import SEARCH_USER_AGENT

    url = f"{ONS_TIMESERIES_URL}/{series}/data"

    async with (
        aiohttp.ClientSession(headers={"User-Agent": SEARCH_USER_AGENT}) as session,
        session.get(url) as response,
    ):
        response.raise_for_status()
        body = await response.json(content_type=None)

    months = (body or {}).get("months")

    if not months:
        raise OpenBBError(f"Unexpected ONS response from {url}.")

    from datetime import datetime

    levels: dict[dateType, float] = {}

    for row in months:
        label = (row.get("date") or "").strip()
        value = (row.get("value") or "").strip()

        if not label or not value:
            continue

        levels[datetime.strptime(label, "%Y %b").date()] = float(value)

    return levels


async def _fetch_eurostat(series: str) -> dict[dateType, float]:
    """Fetch a Eurostat HICP monthly index, served as SDMX-JSON."""
    from openbb_core.app.model.abstract.error import OpenBBError
    from openbb_core.provider.utils.helpers import amake_request

    freq, unit, coicop, geo = series.split(".")
    url = (
        f"{EUROSTAT_URL}?format=JSON&freq={freq}&unit={unit}"
        f"&coicop18={coicop}&geo={geo}"
    )
    response = await amake_request(url)

    if not isinstance(response, dict):
        raise OpenBBError(f"Unexpected Eurostat response from {url}.")

    try:
        periods = response["dimension"]["time"]["category"]["index"]
        values = response["value"]
    except (KeyError, TypeError) as exc:
        raise OpenBBError(f"Unexpected Eurostat response from {url}.") from exc

    by_position = {position: label for label, position in periods.items()}
    levels: dict[dateType, float] = {}

    for position, value in values.items():
        label = by_position.get(int(position))

        if label is None or value is None:
            continue

        year, month = label.split("-")
        levels[dateType(int(year), int(month), 1)] = float(value)

    return levels


async def get_inflation_index(
    index: str, use_cache: bool = True
) -> dict[dateType, float]:
    """Return a published index's monthly levels, by the first of each month."""
    from datetime import datetime

    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_cftc.utils import store

    spec = INFLATION_INDICES.get(index)

    if spec is None:
        raise OpenBBError(f"No published source is configured for '{index}'.")

    today = datetime.now(UTC).date()
    key = f"inflation-{index}-{_month_start(today).isoformat()}"
    cached = store.get_document(key) if use_cache else None

    if cached:
        return {dateType.fromisoformat(day): level for day, level in cached.items()}

    source = spec["source"]

    try:
        if source == "bls":
            levels = await _fetch_bls(
                spec["series"], today.year - INDEX_HISTORY_YEARS, today.year
            )
        elif source == "ons":
            levels = await _fetch_ons(spec["series"])
        else:
            levels = await _fetch_eurostat(spec["series"])
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, OpenBBError):
            raise

        raise OpenBBError(f"Failed to fetch the {index} index -> {exc}") from exc

    if not levels:
        raise OpenBBError(f"No published levels were returned for {index}.")

    levels = backfill_gaps(levels)

    if use_cache:
        store.put_document(
            key, {day.isoformat(): level for day, level in sorted(levels.items())}
        )

    return levels


def build_breakeven_curve(
    records: Iterable[dict],
    currency: str,
    trade_date: dateType,
    min_trades: int = 1,
) -> list[tuple[float, float]]:
    """Return the day's traded zero-coupon breakevens as curve nodes."""
    from openbb_cftc.utils.curve import (
        build_nodes,
        extract_observations,
        trim_observations,
    )

    observations = trim_observations(
        extract_observations(
            records,
            trade_date=trade_date,
            fisn=inflation_fisn(currency),
            currency=currency,
            spot_only=False,
        )
    )

    if not observations:
        return []

    nodes = build_nodes(
        observations,
        granularity="benchmark",
        min_trades=min_trades,
        day_count_default="A020",
    )

    return [(node["tenor_years"], node["par_rate"]) for node in nodes]


def breakeven_at(curve: list[tuple[float, float]], years: float) -> float | None:
    """Interpolate the zero-coupon breakeven at a tenor, flat past either end."""
    if not curve or years <= 0:
        return None

    if len(curve) == 1:
        return curve[0][1]

    if years <= curve[0][0]:
        return curve[0][1]

    if years >= curve[-1][0]:
        return curve[-1][1]

    low_years, low_rate = next(
        (node for node in reversed(curve) if node[0] <= years), curve[0]
    )
    high_years, high_rate = next(
        (node for node in curve if node[0] >= years), curve[-1]
    )
    span = high_years - low_years

    if span <= 0:
        return low_rate

    return low_rate + (years - low_years) / span * (high_rate - low_rate)
