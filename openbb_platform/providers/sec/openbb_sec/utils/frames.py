"""SEC Frames Utilities."""

import asyncio
from collections import defaultdict
from datetime import date, datetime
from warnings import warn

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils.errors import EmptyDataError
from pandas import DataFrame

from openbb_sec.utils.cache import cached_request
from openbb_sec.utils.definitions import (
    CALENDAR_PERIODS,
    CALENDAR_PERIODS_DICT,
    HEADERS,
    INSTANT_FACTS,
    SHARES_FACTS,
    TAXONOMIES,
    USD_PER_SHARE_FACTS,
)
from openbb_sec.utils.helpers import get_all_companies, symbol_map


async def fetch_data(url, use_cache, persist) -> dict | list[dict]:
    """Fetch the data from the constructed URL.

    Frames for the current year (``persist`` is True) are cached until evicted;
    historical frames refresh daily.
    """
    expire = None if persist else 3600 * 24
    return await cached_request(
        url, headers=HEADERS, use_cache=use_cache, expire=expire
    )


# Duration buckets that participate in a cumulative year-to-date chain.
_CUMULATIVE_SPANS = frozenset({"quarter", "h1", "nine_month", "annual"})
# Spans surfaced to the caller (intermediate YTD cumulatives are dropped).
_PRIMARY_SPANS = frozenset({"annual", "quarter", "instant"})


# Standard calendar quarter-end month/day pairs (Q1-Q4).
_QUARTER_END_DAYS = ((3, 31), (6, 30), (9, 30), (12, 31))


def _parse_frame(frame: str) -> tuple[int | None, str | None]:
    """Parse an SEC frame id into a ``(calendar_year, calendar_period)`` pair.

    Accepts ``CY2026`` (annual -> ``FY``), ``CY2026Q1`` and the instantaneous
    ``CY2026Q1I`` (trailing ``I`` ignored). The frame id is the SEC's own
    calendar alignment, so it is authoritative when present.
    """
    year = int(frame[2:6]) if frame[2:6].isdigit() else None
    period = "Q" + frame.split("Q", 1)[1].rstrip("I") if "Q" in frame else "FY"
    return year, period


def _nearest_quarter(end: str) -> tuple[int | None, str | None]:
    """Map an ISO period-end date to the calendar quarter it aligns with.

    The xbrl/frames API assigns each reported period to the calendar quarter
    whose standard end date (Mar 31, Jun 30, Sep 30, Dec 31) is nearest, shifting
    an off-calendar filer onto the calendar grid rather than labelling by the
    raw end month. A period ending Apr 30 aligns to Q1 (nearest Mar 31), and a
    January fiscal year-end rolls back to the prior December (Q4). Returns
    ``(None, None)`` for an unparseable date.
    """
    try:
        d = date.fromisoformat(end)
    except (ValueError, TypeError):
        return None, None
    best_year, best_q, best_dist = None, None, None
    for yy in (d.year - 1, d.year, d.year + 1):
        for q, (month, day) in enumerate(_QUARTER_END_DAYS, start=1):
            dist = abs((date(yy, month, day) - d).days)
            if best_dist is None or dist < best_dist:
                best_year, best_q, best_dist = yy, q, dist
    return best_year, f"Q{best_q}"


def _span_days(item: dict) -> int | None:
    """Return the inclusive day count of an entry, or None when instantaneous."""
    start = item.get("start")
    end = item.get("end")
    if not start or not end:
        return None
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    except (ValueError, TypeError):
        return None


def _classify_span(days: int | None) -> str:
    """Bucket a reporting duration (in days) into a span class.

    None (no start date) is instantaneous; otherwise the calendar-quarter
    multiples with the SEC's +/- 30 day tolerance: ~3mo, ~6mo, ~9mo, ~12mo.
    """
    if days is None:
        return "instant"
    if days <= 120:
        return "quarter"
    if days <= 210:
        return "h1"
    if days <= 300:
        return "nine_month"
    return "annual"


def _enrich_entry(item: dict) -> dict:
    """Annotate a companyconcept entry with span + calendar period metadata.

    Calendar alignment follows the SEC: a ``frame`` id on the entry is
    authoritative; otherwise the period end is rounded to the nearest calendar
    quarter-end so off-calendar filers land on the same calendar grid as the
    xbrl/frames API (e.g. a period ending Apr 30 aligns to Q1, not Q2).
    """
    end = item.get("end") or ""
    span = _classify_span(_span_days(item))
    item["span"] = span
    frame = item.get("frame")
    if frame:
        cal_year, cal_period = _parse_frame(frame)
    else:
        cal_year, cal_period = _nearest_quarter(end)
        if span == "annual":
            cal_period = "FY"
    item["calendar_year"] = cal_year
    item["calendar_period"] = cal_period
    return item


def _dedup_latest_filed(records: list[dict]) -> list[dict]:
    """Keep the most recently filed value per (symbol, unit, period, span).

    A single concept is re-reported across successive filings (originals,
    restatements, prior-period comparatives). The latest filing wins so the
    reference value is used rather than an early estimate or a stale comparative.
    """
    best: dict[tuple, dict] = {}
    for r in records:
        key = (
            r.get("symbol"),
            r.get("unit"),
            r.get("start"),
            r.get("end"),
            r.get("span"),
        )
        cur = best.get(key)
        rank = (r.get("filed", ""), r.get("accn", ""))
        if cur is None or rank > (cur.get("filed", ""), cur.get("accn", "")):
            best[key] = r
    return list(best.values())


def _derive_standalone_quarters(records: list[dict]) -> list[dict]:
    """Derive standalone 3-month quarters from cumulative YTD chains.

    For each (symbol, unit, fiscal_year) the entries sharing the fiscal-year
    start date form a cumulative chain (Q1 3mo, H1 6mo, 9M, FY 12mo). Standalone
    quarters are successive differences along that chain, so Q4 falls out as
    FY - 9-month (no 10-Q is ever filed for the fourth quarter). Each derived
    value is labelled by the calendar quarter of its period end. Only
    differences spanning roughly one quarter are emitted, so a gap in the chain
    never yields a bogus multi-quarter "standalone", and a calendar quarter
    already reported directly is never double-counted.
    """
    derived: list[dict] = []
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        if r.get("span") in _CUMULATIVE_SPANS and r.get("end"):
            groups[(r.get("symbol"), r.get("unit"), r.get("fy"))].append(r)

    for entries in groups.values():
        annual = next((e for e in entries if e.get("span") == "annual"), None)
        fy_start = (
            annual.get("start")
            if annual and annual.get("start")
            else min((e["start"] for e in entries if e.get("start")), default=None)
        )
        if not fy_start:
            continue
        chain = sorted(
            (e for e in entries if e.get("start") == fy_start),
            key=lambda e: e["end"],
        )
        reported = {
            e["calendar_period"]
            for e in entries
            if e.get("span") == "quarter" and e.get("calendar_period")
        }
        prev_val = 0.0
        prev_days = 0
        prev_end = fy_start
        for e in chain:
            link_start = prev_end
            cur_val = e.get("val")
            cur_days = _span_days(e) or 0
            cur_end = e["end"]
            standalone = (cur_val - prev_val) if cur_val is not None else None
            step_days = cur_days - prev_days
            if cur_val is not None:
                prev_val = cur_val
            prev_days = cur_days
            prev_end = cur_end
            # First link is already a standalone quarter; keep it from the
            # primary set rather than re-deriving it.
            if cur_val is None or e.get("span") == "quarter":
                continue
            # A difference that is not ~one quarter means the chain skipped a
            # link; splitting it would invent data, so leave it alone.
            if not 60 <= step_days <= 120:
                continue
            cal_year, cq = _nearest_quarter(cur_end)
            if cq in reported:
                continue
            new = dict(e)
            new["val"] = standalone
            new["start"] = link_start
            new["span"] = "quarter"
            new["calendar_period"] = cq
            new["calendar_year"] = cal_year
            new.pop("frame", None)  # derived from a cumulative; not a real frame
            new["derived"] = True
            reported.add(cq)
            derived.append(new)
    return derived


def _select_periods(
    records: list[dict], year: int | None, calendar_period: str | None
) -> list[dict]:
    """Filter parsed records to the requested calendar year and period.

    ``calendar_period`` selects in calendar space: ``"fy"`` selects annual
    figures (or, for an instant concept, the calendar year-end balance);
    ``"q1"``-``"q4"`` select the standalone quarter whose period end falls in
    that calendar quarter. With no ``calendar_period`` the annual + standalone
    quarter + instant figures are returned (YTD cumulatives are dropped).
    """
    primary = [r for r in records if r.get("span") in _PRIMARY_SPANS]
    fp = (calendar_period or "").lower()
    if fp == "fy":
        selected = [r for r in primary if r.get("calendar_period") == "FY"]
        if not selected:  # instant-only concept: use the calendar year-end point
            selected = [
                r
                for r in primary
                if r.get("span") == "instant" and r.get("calendar_period") == "Q4"
            ]
    elif fp in {"q1", "q2", "q3", "q4"}:
        target = fp.upper()
        selected = [r for r in primary if r.get("calendar_period") == target]
    else:
        selected = primary
    if year is not None:
        selected = [r for r in selected if r.get("calendar_year") == year]
    return selected


async def get_frame(
    fact: str = "Revenues",
    year: int | None = None,
    calendar_period: CALENDAR_PERIODS | None = None,
    taxonomy: TAXONOMIES | None = "us-gaap",
    units: str | None = "USD",
    instantaneous: bool = False,
    use_cache: bool = True,
) -> dict:
    """Get a frame of data for a given fact.

    Source: https://www.sec.gov/edgar/sec-api-documentation

    The xbrl/frames API aggregates one fact for each reporting entity
    that is last filed that most closely fits the calendrical period requested.

    This API supports for annual, quarterly and instantaneous data:

    https://data.sec.gov/api/xbrl/frames/us-gaap/AccountsPayableCurrent/USD/CY2019Q1I.json

    Where the units of measure specified in the XBRL contains a numerator and a denominator,
    these are separated by “-per-” such as “USD-per-shares”. Note that the default unit in XBRL is “pure”.

    The period format is CY#### for annual data (duration 365 days +/- 30 days),
    CY####Q# for quarterly data (duration 91 days +/- 30 days).

    Because company financial calendars can start and end on any month or day and even change in length from quarter to
    quarter according to the day of the week, the frame data is assembled by the dates that best align with a calendar
    quarter or year. Data users should be mindful different reporting start and end dates for facts contained in a frame.

    Parameters
    ----------
    fact : str
        The fact to retrieve. This should be a valid fact from the SEC taxonomy, in UpperCamelCase.
        Defaults to "Revenues".
        AAPL, MSFT, GOOG, BRK-A all report revenue as, "RevenueFromContractWithCustomerExcludingAssessedTax".
        In previous years, they may have reported as "Revenues".
    year : int, optional
        The year to retrieve the data for. If not provided, the current year is used.
    calendar_period: Literal["fy", "q1", "q2", "q3", "q4"], optional
        The calendar period to retrieve the data for. If not provided, the most recent quarter is used.
    taxonomy : Literal["us-gaap", "dei", "ifrs-full", "srt"], optional
        The taxonomy to use. Defaults to "us-gaap".
    units : str, optional
        The units to use. Defaults to "USD". This should be a valid unit from the SEC taxonomy, see the notes above.
        The most common units are "USD", "shares", and "USD-per-shares". EPS and outstanding shares facts will
        automatically set.
    instantaneous: bool
        Whether to retrieve instantaneous data. See the notes above for more information. Defaults to False.
        Some facts are only available as instantaneous data.
        The function will automatically attempt to retrieve the data if the initial fiscal quarter request fails.
    use_cache: bool
        Whether to use cache for the request. Defaults to True.

    Returns
    -------
    Dict:
        Nested dictionary with keys, "metadata" and "data".
        The "metadata" key contains information about the frame.
    """
    from numpy import nan

    current_date = datetime.now().date()
    quarter = CALENDAR_PERIODS_DICT.get(calendar_period) if calendar_period else None
    if year is None and quarter is None:
        quarter = (current_date.month - 1) // 3
        year = current_date.year

    if year is None:
        year = current_date.year

    persist = current_date.year == year

    if fact in SHARES_FACTS:
        units = "shares"

    if fact in USD_PER_SHARE_FACTS:
        units = "USD-per-shares"

    url = f"https://data.sec.gov/api/xbrl/frames/{taxonomy}/{fact}/{units}/CY{year}"

    if quarter:
        url = url + f"Q{quarter}"

    if instantaneous:
        url = url + "I"

    url = url + ".json"
    response: dict | list[dict] = {}
    try:
        response = await fetch_data(url, use_cache, persist)
    except Exception as e:
        message = (
            "No frame was found with the combination of parameters supplied."
            + " Try adjusting the period."
            + " Not all GAAP measures have frames available."
        )
        if url.endswith("I.json"):
            warn("No instantaneous frame was found, trying calendar period data.")
            url = url.replace("I.json", ".json")
            try:
                response = await fetch_data(url, use_cache, persist)
            except Exception:
                raise OpenBBError(message) from e
        elif "Q" in url and not url.endswith("I.json"):
            warn(
                "No frame was found for the requested quarter, trying instantaneous data."
            )
            url = url.replace(".json", "I.json")
            try:
                response = await fetch_data(url, use_cache, persist)
            except Exception:
                raise OpenBBError(message) from e
        else:
            raise OpenBBError(message) from e

    data = sorted(response.get("data", {}), key=lambda x: x["val"], reverse=True)  # ty: ignore[missing-union-attribute]
    metadata = {
        "frame": response.get("ccp", ""),  # ty: ignore[missing-union-attribute]
        "tag": response.get("tag", ""),  # ty: ignore[missing-union-attribute]
        "label": response.get("label", ""),  # ty: ignore[missing-union-attribute]
        "description": response.get("description", ""),  # ty: ignore[missing-union-attribute]
        "taxonomy": response.get("taxonomy", ""),  # ty: ignore[missing-union-attribute]
        "unit": response.get("uom", ""),  # ty: ignore[missing-union-attribute]
        "count": response.get("pts", ""),  # ty: ignore[missing-union-attribute]
    }
    df = DataFrame(data)
    companies = await get_all_companies(use_cache=use_cache)
    cik_to_symbol = companies.set_index("cik")["symbol"].to_dict()
    df["symbol"] = df["cik"].astype(str).map(cik_to_symbol)
    df["unit"] = metadata.get("unit")
    df["fact"] = metadata.get("label")
    df["frame"] = metadata.get("frame")
    cal_year, cal_period = _parse_frame(metadata.get("frame", "") or "")
    df["calendar_period"] = cal_period
    df["calendar_year"] = cal_year if cal_year is not None else year
    df = df.replace({nan: None})
    results = {"metadata": metadata, "data": df.to_dict("records")}

    return results


async def get_concept(
    symbol: str,
    fact: str = "Revenues",
    year: int | None = None,
    calendar_period: CALENDAR_PERIODS | None = None,
    taxonomy: TAXONOMIES | None = "us-gaap",
    use_cache: bool = True,
) -> dict:
    """Return all the XBRL disclosures from a single company (CIK) Concept (a taxonomy and tag) into a single JSON file.

    Each entry contains a separate array of facts for each units of measure that the company has chosen to disclose
    (e.g. net profits reported in U.S. dollars and in Canadian dollars).

    Parameters
    ----------
    symbol: str
        The ticker symbol to look up.
    fact : str
        The fact to retrieve. This should be a valid fact from the SEC taxonomy, in UpperCamelCase.
        Defaults to "Revenues".
        AAPL, MSFT, GOOG, BRK-A all report revenue as, "RevenueFromContractWithCustomerExcludingAssessedTax".
        In previous years, they may have reported as "Revenues".
    year : int, optional
        The calendar year to retrieve the data for. If not provided, all reported values
        are returned. Values are aligned to the calendar quarter/year of the period end,
        not the company's fiscal calendar, so off-calendar filers stay comparable.
    calendar_period: Literal["fy", "q1", "q2", "q3", "q4"], optional
        The calendar period to retrieve. "fy" returns annual figures; "q1"-"q4" return the
        standalone (3-month) quarter whose period end falls in that calendar quarter.
        Cumulative year-to-date figures are reduced to standalone quarters and the fourth
        quarter is derived as FY - 9-month. If not provided, all periods are returned.
    taxonomy : Literal["us-gaap", "dei", "ifrs-full", "srt"], optional
        The taxonomy to use. Defaults to "us-gaap".
    use_cache: bool
        Whether to use cache for the request. Defaults to True.

    Returns
    -------
    Dict:
        Nested dictionary with keys, "metadata" and "data".
        The "metadata" key contains information about the company concept.
    """
    symbols = symbol.split(",")
    results: list[dict] = []
    messages: list = []
    metadata: dict = {}

    async def get_one(ticker):
        """Get data for one symbol."""
        ticker = ticker.upper()
        message = f"Symbol Error: No data was found for, {ticker} and {fact}"
        cik = await symbol_map(ticker)
        if cik == "":
            message = f"Symbol Error: No CIK was found for, {ticker}"
            warn(message)
            messages.append(message)
        else:
            url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{fact}.json"
            response: dict | list[dict] = {}
            try:
                response = await fetch_data(url, use_cache, False)
            except Exception as _:
                warn(message)
                messages.append(message)
            if response:
                units = response.get("units", {})  # ty: ignore[missing-union-attribute]
                metadata[ticker] = {
                    "cik": response.get("cik", ""),  # ty: ignore[missing-union-attribute]
                    "taxonomy": response.get("taxonomy", ""),  # ty: ignore[missing-union-attribute]
                    "tag": response.get("tag", ""),  # ty: ignore[missing-union-attribute]
                    "label": response.get("label", ""),  # ty: ignore[missing-union-attribute]
                    "description": response.get("description", ""),  # ty: ignore[missing-union-attribute]
                    "name": response.get("entityName", ""),  # ty: ignore[missing-union-attribute]
                    "units": (
                        list(units) if units and len(units) > 1 else list(units)[0]
                    ),
                }
                for k, v in units.items():
                    unit = k
                    values = v
                    for item in values:
                        item["unit"] = unit
                        item["symbol"] = ticker
                        item["cik"] = metadata[ticker]["cik"]
                        item["name"] = metadata[ticker]["name"]
                        item["fact"] = metadata[ticker]["label"]
                    results.extend(values)

    await asyncio.gather(*[get_one(ticker) for ticker in symbols])

    if not results:
        raise EmptyDataError(f"{messages}")

    # Dedup re-reported values (latest filing wins), then reduce cumulative
    # year-to-date figures to standalone quarters (deriving Q4 = FY - 9-month).
    parsed = _dedup_latest_filed([_enrich_entry(r) for r in results])
    parsed.extend(_derive_standalone_quarters(parsed))

    final = _select_periods(parsed, year, calendar_period)
    if not final and (year is not None or calendar_period):
        warn(
            f"No results were found for {fact} in the requested calendar period."
            " Returning all reported values instead."
            " Concept and fact names may differ by company and year."
        )
        final = [r for r in parsed if r.get("span") in _PRIMARY_SPANS]

    return {
        "metadata": metadata,
        "data": sorted(
            final, key=lambda x: (x.get("filed", ""), x.get("end", "")), reverse=True
        ),
    }


async def get_universe_quarter4(
    fact: str = "Revenues",
    year: int | None = None,
    taxonomy: TAXONOMIES | None = "us-gaap",
    units: str | None = "USD",
    use_cache: bool = True,
) -> dict:
    """Derive a standalone calendar-Q4 universe frame as FY - (Q1 + Q2 + Q3).

    The xbrl/frames API has no standalone fourth-quarter duration frame: no 10-Q
    covers Q4, and the 10-K reports the full year. This fetches the annual frame
    and the three quarterly frames and subtracts, per filer, to produce a
    standalone calendar-Q4 figure. Only filers that reported all three earlier
    quarters are included, since a partial subtraction would be wrong.

    This applies to flow (duration) concepts. Instantaneous balance-sheet
    concepts already have a populated ``CY####Q4I`` frame and do not need this.
    """
    from numpy import nan

    if year is None:
        year = datetime.now().date().year

    # Instantaneous (balance-sheet) concepts already have a populated year-end
    # ``CY####Q4I`` frame, so fetch that directly. Subtracting earlier quarters
    # is meaningful only for flow concepts; for a point-in-time balance it would
    # be nonsense.
    if fact in INSTANT_FACTS:
        return await get_frame(
            fact=fact,
            year=year,
            calendar_period="q4",
            instantaneous=True,
            taxonomy=taxonomy,
            units=units,
            use_cache=use_cache,
        )

    if fact in SHARES_FACTS:
        units = "shares"
    if fact in USD_PER_SHARE_FACTS:
        units = "USD-per-shares"

    persist = datetime.now().date().year == year
    base = f"https://data.sec.gov/api/xbrl/frames/{taxonomy}/{fact}/{units}/CY{year}"

    try:
        annual_resp = await fetch_data(base + ".json", use_cache, persist)
    except Exception:
        # No annual (duration) frame exists for this concept: it is reported as
        # a point-in-time balance not captured by INSTANT_FACTS. Fall back to the
        # year-end instant frame so the request still resolves ("if the frame
        # does not already exist").
        return await get_frame(
            fact=fact,
            year=year,
            calendar_period="q4",
            instantaneous=True,
            taxonomy=taxonomy,
            units=units,
            use_cache=use_cache,
        )

    quarter_sums: dict = defaultdict(float)
    quarter_counts: dict = defaultdict(int)
    for q in (1, 2, 3):
        try:
            qresp = await fetch_data(f"{base}Q{q}.json", use_cache, persist)
        except Exception:  # noqa: S112
            continue
        for row in qresp.get("data", []):  # ty: ignore[missing-union-attribute]
            cik = row.get("cik")
            if cik is None or row.get("val") is None:
                continue
            quarter_sums[cik] += row["val"]
            quarter_counts[cik] += 1

    data: list[dict] = []
    for row in annual_resp.get("data", []):  # ty: ignore[missing-union-attribute]
        cik = row.get("cik")
        if cik is None or row.get("val") is None or quarter_counts.get(cik, 0) < 3:
            continue
        new = dict(row)
        new["val"] = row["val"] - quarter_sums[cik]
        data.append(new)

    metadata = {
        "frame": f"CY{year}Q4",
        "tag": annual_resp.get("tag", ""),  # ty: ignore[missing-union-attribute]
        "label": annual_resp.get("label", ""),  # ty: ignore[missing-union-attribute]
        "description": annual_resp.get("description", ""),  # ty: ignore[missing-union-attribute]
        "taxonomy": annual_resp.get("taxonomy", ""),  # ty: ignore[missing-union-attribute]
        "unit": annual_resp.get("uom", ""),  # ty: ignore[missing-union-attribute]
        "count": len(data),
        "note": (
            "Q4 derived as FY - (Q1 + Q2 + Q3);"
            " only filers reporting all three earlier quarters are included."
        ),
    }

    data = sorted(data, key=lambda x: x["val"], reverse=True)
    df = DataFrame(data)
    companies = await get_all_companies(use_cache=use_cache)
    cik_to_symbol = companies.set_index("cik")["symbol"].to_dict()
    if not df.empty:
        df["symbol"] = df["cik"].astype(str).map(cik_to_symbol)
        df["unit"] = metadata.get("unit")
        df["fact"] = metadata.get("label")
        df["frame"] = metadata["frame"]
        df["calendar_year"] = year
        df["calendar_period"] = "Q4"
        df = df.replace({nan: None})

    return {"metadata": metadata, "data": df.to_dict("records")}
