"""DTCC Public Price Dissemination search client."""

from datetime import (
    UTC,
    date as dateType,
)
from typing import Any

SEARCH_ROW_CAP = 10000

SEARCH_MAX_RANGE_DAYS = 180

SEARCH_MAX_RETENTION_DAYS = 365

SEARCH_MAX_NOTIONAL = 999_999_999_999.0

SEARCH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

SEARCH_ASSET_CLASSES = {
    "rates": "RATES",
    "credits": "CREDITS",
    "equities": "EQUITY",
    "forex": "FOREIGNEXCHANGE",
    "commodities": "COMMODITIES",
}

SEARCH_ALIASES: dict[str, str] = {
    "uniqueproductidentifiershortname": "UPI FISN",
    "uniqueproductidentifierunderliername": "UPI Underlier Name",
    "disseminationtimestamp": "Dissemination Timestamp",
    "callamountleg1": "Call amount",
    "callcurrencyleg1": "Call currency",
    "putamountleg1": "Put amount",
    "putcurrencyleg1": "Put currency",
    "settlementlocationleg1": "Settlement location",
    "strikepricecurrencyorcurrencypair": "Strike price currency/currency pair",
}


def _normalize_key(key: str) -> str:
    """Reduce a field name to its alphanumeric lowercase form."""
    return "".join(c for c in key.lower() if c.isalnum())


def _header_by_key() -> dict[str, str]:
    """Slice header by normalized key, built once."""
    from openbb_cftc.utils.constants import SLICE_HEADERS

    return {_normalize_key(header): header for header in SLICE_HEADERS}


_HEADER_BY_KEY = _header_by_key()


def normalize_search_asset_class(asset_class: str) -> str:
    """Map an asset class key to its search payload value."""
    from openbb_core.app.model.abstract.error import OpenBBError

    key = (asset_class or "").strip().lower()

    if key not in SEARCH_ASSET_CLASSES:
        raise OpenBBError(
            f"Invalid asset class: '{asset_class}'."
            + " Valid asset classes are: "
            + ", ".join(SEARCH_ASSET_CLASSES)
        )

    return SEARCH_ASSET_CLASSES[key]


def format_search_datetime(value: dateType, end_of_day: bool = False) -> str:
    """Format a date as a dissemination timestamp bound."""
    clock = "23:59:59.999" if end_of_day else "00:00:00.000"

    return f"{value.isoformat()}T{clock}Z"


def map_search_record(record: dict) -> dict:
    """Map a search record to the CSV headers the curve and FX paths read."""
    from urllib.parse import unquote

    mapped: dict = {}

    for key, value in record.items():
        normalized = _normalize_key(key)
        header = SEARCH_ALIASES.get(normalized) or _HEADER_BY_KEY.get(normalized)

        if header is None:
            continue

        mapped[header] = unquote(value) if isinstance(value, str) else value

    return mapped


def build_search_payload(
    asset_class: str,
    currency: str | None = None,
    upi_short_name: str | None = None,
    upi: str | None = None,
    product_id: str | None = None,
    underlying_asset: str | None = None,
    min_notional: float = 0.0,
    max_notional: float = SEARCH_MAX_NOTIONAL,
) -> dict[str, Any]:
    """Build a search payload. Every field must be present, including the null ones."""
    from openbb_cftc.utils.constants import JURISDICTION

    asset = normalize_search_asset_class(asset_class)
    commodities = asset == "COMMODITIES"

    return {
        "jurisdiction": JURISDICTION,
        "assetClass": asset,
        "currency": None if commodities else currency,
        "minNotionalAmount": str(int(min_notional)),
        "maxNotionalAmount": str(int(max_notional)),
        "displayType": "w",
        "disseminationDateTimeLow": None,
        "disseminationDateTimeHigh": None,
        "productId": product_id if commodities else None,
        "underlyingAsset": underlying_asset if commodities else None,
        "upi": None if commodities else upi,
        "upiShortName": None if commodities else upi_short_name,
        "name": None,
        "searchIndicator": "post",
    }


async def post_search(payload: dict) -> list[dict]:
    """POST a search payload and return its trade list."""
    import aiohttp
    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_cftc.utils.constants import PPD_API_URL

    url = f"{PPD_API_URL}/search/webdisplay"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": SEARCH_USER_AGENT,
    }

    try:
        async with (
            aiohttp.ClientSession() as session,
            session.post(url, json=payload, headers=headers) as response,
        ):
            response.raise_for_status()
            body = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        raise OpenBBError(f"Failed to query the PPD search endpoint -> {exc}") from exc

    if not isinstance(body, dict):
        raise OpenBBError(f"Unexpected PPD search response: {body!r}")

    errors = body.get("errorList") or []

    if errors:
        raise OpenBBError(
            "The PPD search endpoint rejected the query -> "
            + "; ".join(str(e.get("errorMessage") or e) for e in errors)
        )

    return body.get("tradeList") or []


def _date_range(start_date: dateType, end_date: dateType) -> list[dateType]:
    """Return every calendar date from start to end, inclusive."""
    from datetime import timedelta

    return [
        start_date + timedelta(days=offset)
        for offset in range((end_date - start_date).days + 1)
    ]


def _chunk_windows(
    start_date: dateType, end_date: dateType, max_days: int
) -> list[tuple[dateType, dateType]]:
    """Split a range into consecutive sub-windows of at most ``max_days`` days each."""
    from datetime import timedelta

    chunks: list[tuple[dateType, dateType]] = []
    low = start_date

    while low <= end_date:
        high = min(low + timedelta(days=max_days - 1), end_date)
        chunks.append((low, high))
        low = high + timedelta(days=1)

    return chunks


def _contiguous_runs(days: list[dateType]) -> list[tuple[dateType, dateType]]:
    """Group dates into contiguous ```` runs, so only gaps are re-fetched."""
    from datetime import timedelta

    runs: list[tuple[dateType, dateType]] = []

    for day in sorted(days):
        if runs and day == runs[-1][1] + timedelta(days=1):
            runs[-1] = (runs[-1][0], day)
        else:
            runs.append((day, day))

    return runs


async def search_window(
    payload: dict,
    start_date: dateType,
    end_date: dateType,
) -> list[dict]:
    """Query a window, splitting past the cap: by date, then by notional on a single day."""
    import asyncio
    from datetime import timedelta

    window = dict(payload)
    window["disseminationDateTimeLow"] = format_search_datetime(start_date)
    window["disseminationDateTimeHigh"] = format_search_datetime(
        end_date, end_of_day=True
    )

    rows = await post_search(window)

    if len(rows) < SEARCH_ROW_CAP:
        return rows

    if start_date != end_date:
        midpoint = start_date + (end_date - start_date) // 2
        left, right = await asyncio.gather(
            search_window(payload, start_date, midpoint),
            search_window(payload, midpoint + timedelta(days=1), end_date),
        )

        return left + right

    return await _search_day_by_notional(payload, start_date)


def _notional_band_edges(low: int, high: int, count: int = 32) -> list[int]:
    """Return log-spaced notional band edges spanning ``low`` to ``high`` inclusive."""
    lo = max(low, 1)

    if high <= lo:
        return []

    ratio = (high / lo) ** (1.0 / count)
    edges = {low, high}
    value = float(lo)

    for _ in range(count - 1):
        value *= ratio
        edges.add(int(value))

    return sorted(edges)


async def _search_day_by_notional(payload: dict, day: dateType) -> list[dict]:
    """Split a single capped day across a fixed set of geometric notional bands."""
    import asyncio

    from openbb_core.app.model.abstract.error import OpenBBError

    low = int(payload.get("minNotionalAmount") or 0)
    high = int(payload.get("maxNotionalAmount") or int(SEARCH_MAX_NOTIONAL))
    edges = _notional_band_edges(low, high)

    if len(edges) < 2:
        raise OpenBBError(
            f"The PPD search for {day} returned the {SEARCH_ROW_CAP}-record cap within a"
            + " single notional value, so it cannot be narrowed further by notional."
        )

    bands = await asyncio.gather(
        *(
            _search_notional_band(payload, day, lo, hi)
            for lo, hi in zip(edges, edges[1:])
        )
    )

    return [row for band in bands for row in band]


async def _search_notional_band(
    payload: dict, day: dateType, low: int, high: int
) -> list[dict]:
    """Query one notional band of a single day, refusing a band that still caps."""
    from openbb_core.app.model.abstract.error import OpenBBError

    window = dict(payload)
    window["disseminationDateTimeLow"] = format_search_datetime(day)
    window["disseminationDateTimeHigh"] = format_search_datetime(day, end_of_day=True)
    window["minNotionalAmount"] = str(low)
    window["maxNotionalAmount"] = str(high)

    rows = await post_search(window)

    if len(rows) >= SEARCH_ROW_CAP:
        raise OpenBBError(
            f"The PPD search for {day} returned the {SEARCH_ROW_CAP}-record cap within the"
            + f" {low:,} to {high:,} notional band; narrow the date or notional range."
        )

    return rows


def _cache_key(payload: dict) -> str:
    """Return a stable digest of a payload's non-window fields."""
    import hashlib
    import json

    signature = {
        key: value
        for key, value in payload.items()
        if key not in ("disseminationDateTimeLow", "disseminationDateTimeHigh")
    }

    return hashlib.sha256(
        json.dumps(signature, sort_keys=True).encode("utf-8")
    ).hexdigest()


async def search_trades(
    asset_class: str,
    start_date: dateType,
    end_date: dateType,
    *,
    currency: str | None = None,
    upi_short_name: str | None = None,
    upi: str | None = None,
    product_id: str | None = None,
    underlying_asset: str | None = None,
    min_notional: float = 0.0,
    use_cache: bool = True,
) -> list[dict]:
    """Return a dissemination window's records, mapped onto the slice's CSV headers."""
    from datetime import datetime, timedelta

    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_cftc.utils import store

    if end_date < start_date:
        raise OpenBBError(
            f"The search window ends before it starts: {start_date} to {end_date}."
        )

    today_date = datetime.now(UTC).date()
    horizon = today_date - timedelta(days=SEARCH_MAX_RETENTION_DAYS - 1)

    start_date = max(start_date, horizon)

    if start_date > end_date:
        raise OpenBBError(
            f"The search window predates the {SEARCH_MAX_RETENTION_DAYS}-day search"
            + " horizon; use source='slice' for older data."
        )

    payload = build_search_payload(
        asset_class,
        currency=currency,
        upi_short_name=upi_short_name,
        upi=upi,
        product_id=product_id,
        underlying_asset=underlying_asset,
        min_notional=min_notional,
    )
    key = _cache_key(payload)
    days = _date_range(start_date, end_date)
    cached = (
        store.get_search_days(key, [day.isoformat() for day in days])
        if use_cache
        else {}
    )
    missing = [day for day in days if day.isoformat() not in cached]
    by_day: dict[str, list[dict]] = dict(cached)

    if missing:
        import asyncio

        fetched: dict[str, list[dict]] = {day.isoformat(): [] for day in missing}
        windows = [
            window
            for run_low, run_high in _contiguous_runs(missing)
            for window in _chunk_windows(run_low, run_high, SEARCH_MAX_RANGE_DAYS)
        ]
        results = await asyncio.gather(
            *(search_window(payload, lo, hi) for lo, hi in windows)
        )
        seen: set[str] = set()

        for records in results:
            for record in records:
                row = map_search_record(record)
                day = (row.get("Dissemination Timestamp") or "")[:10]

                if day not in fetched:
                    continue

                identifier = row.get("Dissemination Identifier")

                if identifier:
                    if identifier in seen:
                        continue
                    seen.add(identifier)

                fetched[day].append(row)

        by_day.update(fetched)

        if use_cache:
            store.put_search_days(key, fetched)

        from openbb_cftc.utils.constants import ASSET_CLASSES

        asset = ASSET_CLASSES.get((asset_class or "").strip().lower())

        if asset:
            for day, rows in fetched.items():
                store.write_search_records(asset, day, rows)

    return [row for day in days for row in by_day.get(day.isoformat(), [])]
