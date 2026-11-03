"""Company type detection, filing-date resolution, and fiscal metadata."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from openbb_sec.utils.statement_schema._types import (
    ALL_FORMS,
    ANNUAL_FORMS,
    ANNUAL_PERIOD_FORMS,
    PRELIMINARY_FORMS,
    QUARTERLY_FORMS,
    SEMI_ANNUAL_FORMS,
    SUPERSEDED_SUFFIX,
    CompanyType,
    Frequency,
    PreliminaryFacts,
)


def detect_type(
    facts: dict[str, Any],
    *,
    insurance_is_signals: list[str],
    insurance_bs_signals: list[str],
    financial_signals: list[str],
    min_financial_signals: int,
    industrial_signals: list[str],
    diversified_signals: list[str],
    revenue_measures: list[str] | None = None,
    insurance_measures: list[str] | None = None,
    financial_measures: list[str] | None = None,
    min_insurance_share: float = 0.0,
    min_financial_share: float = 0.0,
) -> CompanyType:
    """Classify a company as industrial, financial, diversified, or insurance."""
    company_tags: set[str] = set()

    for ns_data in facts.values():
        if isinstance(ns_data, dict):
            company_tags.update(ns_data.keys())

    has_cogs = any(
        s in company_tags and _has_recent_data(facts, s) for s in industrial_signals
    )
    revenue, shares = _latest_annual_shares(
        facts,
        revenue_measures or [],
        {"insurance": insurance_measures or [], "financial": financial_measures or []},
    )
    insurance_share = shares["insurance"]
    financial_share = shares["financial"]
    ins_is = sum(1 for s in insurance_is_signals if s in company_tags)
    ins_bs = sum(1 for s in insurance_bs_signals if s in company_tags)
    ins_total = ins_is + ins_bs
    is_insurance = (
        ins_is >= 1
        and ins_total >= 2
        and (
            revenue is None
            or (insurance_share is not None and insurance_share >= min_insurance_share)
        )
    )
    fin_count = sum(1 for s in financial_signals if s in company_tags)
    is_financial = fin_count >= min_financial_signals and (
        (revenue is None and not has_cogs)
        or (financial_share is not None and financial_share >= min_financial_share)
    )

    if is_insurance and is_financial:
        return "insurance" if ins_total > fin_count else "financial"
    if is_insurance:
        return "insurance"
    if is_financial:
        return "financial"

    if has_cogs:
        return "industrial"

    has_cne = any(s in company_tags for s in diversified_signals)

    if has_cne:
        return "diversified"

    return "industrial"


def _latest_annual_shares(
    facts: dict[str, Any],
    revenue_measures: list[str],
    measure_groups: dict[str, list[str]],
) -> tuple[float | None, dict[str, float | None]]:
    """Revenue and each measure group's share of it in the latest annual filing that reports revenue."""
    latest: tuple[str, str, str, str] | None = None
    revenue_values: dict[tuple[str, str, str], float] = {}

    for ns_data in facts.values():
        if not isinstance(ns_data, dict):
            continue

        for tag in revenue_measures:
            for unit, entries in ns_data.get(tag, {}).get("units", {}).items():
                for entry in entries:
                    start, end = entry.get("start", ""), entry.get("end", "")

                    if (
                        entry.get("form", "") not in ANNUAL_FORMS
                        or not start
                        or not end
                    ):
                        continue

                    if not 300 <= (_parse(end) - _parse(start)).days <= 400:
                        continue

                    accn = entry.get("accn", "")
                    key = (accn, end, unit)
                    val = entry.get("val")

                    if val is None:
                        continue

                    if key not in revenue_values or abs(val) > abs(revenue_values[key]):
                        revenue_values[key] = val

                    candidate = (entry.get("filed", ""), accn, end, unit)

                    if latest is None or candidate[:3] > latest[:3]:
                        latest = candidate

    empty: dict[str, float | None] = dict.fromkeys(measure_groups)

    if latest is None:
        return None, empty

    _, accn, end, unit = latest
    revenue = revenue_values.get((accn, end, unit))

    if not revenue:
        return None, empty

    shares: dict[str, float | None] = {}

    for group, tags in measure_groups.items():
        found: list[float] = []

        for ns_data in facts.values():
            if not isinstance(ns_data, dict):
                continue

            for tag in tags:
                for entry in ns_data.get(tag, {}).get("units", {}).get(unit, []):
                    start = entry.get("start", "")

                    if (
                        entry.get("accn", "") == accn
                        and entry.get("end") == end
                        and start
                        and 300 <= (_parse(end) - _parse(start)).days <= 400
                        and entry.get("val") is not None
                    ):
                        found.append(entry["val"])

        shares[group] = max(found) / revenue if found else None

    return revenue, shares


def _parse(date: str) -> datetime:
    return datetime.strptime(date, "%Y-%m-%d")


def _has_recent_data(facts: dict[str, Any], tag: str, max_age_years: int = 5) -> bool:
    """Check if a tag has data from a recent annual filing."""
    cutoff_year = datetime.now().year - max_age_years

    for ns_data in facts.values():
        if not isinstance(ns_data, dict) or tag not in ns_data:
            continue

        tag_data = ns_data[tag]

        for entries in tag_data.get("units", {}).values():
            for entry in entries:
                if entry.get("form", "") in ANNUAL_FORMS:
                    end = entry.get("end", "")
                    if end and int(end[:4]) >= cutoff_year:
                        return True

    return False


def _anchor_distance(dt: datetime, month: int, day: int) -> int:
    """Days from ``dt`` to the nearest ``month``-``day`` anchor in the adjacent years."""
    distances: list[int] = []

    for year in (dt.year - 1, dt.year, dt.year + 1):
        try:
            anchor = datetime(year, month, day)
        except ValueError:
            anchor = datetime(year, month, min(day, 28))
        distances.append(abs((dt - anchor).days))

    return min(distances)


def _collapse_near_dates(
    dates: set[str], anchors: set[str], weights: Counter[str]
) -> set[str]:
    """Drop interim ends within 7 days of a fiscal-year end or of a better-supported interim end."""
    anchor_dts = [datetime.strptime(a, "%Y-%m-%d") for a in anchors]
    kept: list[tuple[str, datetime]] = []

    for date in sorted(dates):
        dt = datetime.strptime(date, "%Y-%m-%d")

        if any(abs((dt - a).days) <= 7 for a in anchor_dts):
            continue

        if kept and (dt - kept[-1][1]).days <= 7:
            if weights[date] > weights[kept[-1][0]]:
                kept[-1] = (date, dt)
            continue

        kept.append((date, dt))

    return {d for d, _ in kept}


def get_filing_dates(  # noqa: PLR0912
    facts: dict[str, Any],
    frequency: Frequency = "annual",
    include_preliminary: bool = False,
) -> set[str]:
    """Determine canonical period-end dates from facts filed after the period ends."""
    filing_dates: set[str] = set()
    preliminary_candidates: set[str] = set()
    weights: Counter[str] = Counter()

    for ns_facts in facts.values():
        for tag_data in ns_facts.values():
            for entries in tag_data.get("units", {}).values():
                for entry in entries:
                    form = entry.get("form", "")
                    start = entry.get("start", "")
                    end = entry.get("end", "")

                    if (
                        not start
                        or not end
                        or start == end
                        or entry.get("filed", "") <= end
                    ):
                        continue
                    try:
                        days = (
                            datetime.strptime(end, "%Y-%m-%d")
                            - datetime.strptime(start, "%Y-%m-%d")
                        ).days
                    except (ValueError, TypeError):
                        continue

                    if frequency == "annual":
                        if form in ANNUAL_PERIOD_FORMS and 300 <= days <= 400:
                            filing_dates.add(end)
                            weights[end] += 1
                        elif (
                            include_preliminary
                            and form in PRELIMINARY_FORMS
                            and 300 <= days <= 400
                        ):
                            preliminary_candidates.add(end)
                    else:
                        if form in QUARTERLY_FORMS and 60 <= days <= 135:
                            filing_dates.add(end)
                            weights[end] += 1
                        if form in SEMI_ANNUAL_FORMS and (
                            60 <= days <= 135
                            or 150 <= days <= 200
                            or 240 <= days <= 310
                        ):
                            filing_dates.add(end)
                            weights[end] += 1
                        if (
                            include_preliminary
                            and form in PRELIMINARY_FORMS
                            and 60 <= days <= 135
                        ):
                            preliminary_candidates.add(end)

    if include_preliminary:
        filing_dates |= preliminary_candidates - filing_dates

    if frequency != "annual" and filing_dates:
        canonical_annual = get_filing_dates(
            facts, "annual", include_preliminary=include_preliminary
        )
        interim_dates = filing_dates - canonical_annual

        # Discontinuity guard: if interim reporting has lapsed — the most
        # recent interim period lags the most recent annual period by more
        # than ~15 months — the quarterly series would be sparse and stale
        # (common for 40-F/MJDS filers that report only annually via 6-K).
        # Treat that as no quarterly data so callers fall back to annual.
        if interim_dates and canonical_annual:
            latest_annual = datetime.strptime(max(canonical_annual), "%Y-%m-%d")
            latest_interim = datetime.strptime(max(interim_dates), "%Y-%m-%d")
            if (latest_annual - latest_interim).days > 460:
                return set()

        interim_dates = _collapse_near_dates(interim_dates, canonical_annual, weights)
        filing_dates = interim_dates | (filing_dates & canonical_annual)

        # Fold a fiscal year-end into the quarterly series only when that
        # fiscal year actually has at least one interim period.
        sorted_annual = sorted(canonical_annual)
        for i, annual_end in enumerate(sorted_annual):
            fy_start = sorted_annual[i - 1] if i else ""
            if any(fy_start < qd < annual_end for qd in interim_dates):
                filing_dates.add(annual_end)

    if frequency == "annual" and len(filing_dates) > 3:
        parsed = sorted((d, datetime.strptime(d, "%Y-%m-%d")) for d in filing_dates)
        anchors = sorted({(dt.month, dt.day) for _, dt in parsed})
        support = {
            md: (
                sum(weights[d] for d, dt in parsed if _anchor_distance(dt, *md) <= 7),
                sum(weights[d] for d, dt in parsed if (dt.month, dt.day) == md),
            )
            for md in anchors
        }
        dom_m, dom_d = max(anchors, key=support.__getitem__)
        canonical_pairs = [
            (d, dt) for d, dt in parsed if _anchor_distance(dt, dom_m, dom_d) <= 7
        ]

        if len(canonical_pairs) >= max(3, len(parsed) * 0.4):
            canonical: set[str] = {d for d, _ in canonical_pairs}
            canonical_dts: list[datetime] = [dt for _, dt in canonical_pairs]
            non_canonical: list[tuple[str, datetime]] = [
                (d, dt) for d, dt in parsed if d not in canonical
            ]

            clusters: list[list[tuple[str, datetime]]] = []

            for d, dt in sorted(canonical_pairs):
                if clusters and (dt - clusters[-1][-1][1]).days <= 10:
                    clusters[-1].append((d, dt))
                else:
                    clusters.append([(d, dt)])

            filtered = {
                max(
                    cluster,
                    key=lambda p: (
                        weights[p[0]],
                        (p[1].month, p[1].day) == (dom_m, dom_d),
                    ),
                )[0]
                for cluster in clusters
            }

            for d, dt in non_canonical:
                has_nearby = any(abs((dt - ct).days) <= 200 for ct in canonical_dts)
                if not has_nearby:
                    filtered.add(d)

            filing_dates = filtered

    assets_forms = ALL_FORMS if frequency == "quarterly" else ANNUAL_PERIOD_FORMS
    if include_preliminary:
        assets_forms = assets_forms | PRELIMINARY_FORMS

    while len(filing_dates) > 1:
        earliest = min(filing_dates)
        has_assets = False

        for ns_facts in facts.values():
            assets_data = ns_facts.get("Assets", {})

            for entries in assets_data.get("units", {}).values():
                for entry in entries:
                    if (
                        entry.get("form", "") in assets_forms
                        and entry.get("end") == earliest
                        and not entry.get("start")
                    ):
                        has_assets = True
                        break

                if has_assets:
                    break

            if has_assets:
                break

        if not has_assets:
            filing_dates.discard(earliest)
        else:
            break

    return filing_dates


def _reference_year(date: str) -> int:
    """Calendar year of the day 45 days before a fiscal year end."""
    return (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=45)).year


def annual_fiscal_years(
    facts: dict[str, Any], annual_dates: set[str]
) -> dict[str, int]:
    """Fiscal year per annual period end from the original annual filing that reports it after it ends."""
    period_end: dict[str, str] = {}
    first: dict[str, tuple[str, str, int]] = {}

    for namespace, ns_facts in facts.items():
        if namespace == "dei" or not isinstance(ns_facts, dict):
            continue

        for tag_data in ns_facts.values():
            for entries in tag_data.get("units", {}).values():
                for entry in entries:
                    start = entry.get("start", "")
                    end = entry.get("end", "")
                    filed = entry.get("filed", "")

                    if (
                        entry.get("form", "") not in ANNUAL_FORMS
                        or not start
                        or not end
                        or filed <= end
                    ):
                        continue

                    try:
                        days = (
                            datetime.strptime(end, "%Y-%m-%d")
                            - datetime.strptime(start, "%Y-%m-%d")
                        ).days
                    except (ValueError, TypeError):
                        continue

                    if not 300 <= days <= 400:
                        continue

                    filing = entry.get("accn") or filed

                    if end > period_end.get(filing, ""):
                        period_end[filing] = end

                    fy = entry.get("fy")

                    if (
                        end in annual_dates
                        and fy is not None
                        and (end not in first or (filed, filing) < first[end][:2])
                    ):
                        first[end] = (filed, filing, fy)

    years = {
        end: fy
        - round(
            (
                datetime.strptime(period_end[filing], "%Y-%m-%d")
                - datetime.strptime(end, "%Y-%m-%d")
            ).days
            / 365.25
        )
        for end, (_, filing, fy) in first.items()
    }
    offsets = Counter(year - _reference_year(end) for end, year in years.items())
    offset = max(sorted(offsets), key=offsets.__getitem__) if offsets else 0
    ordered = sorted(annual_dates)

    for end in ordered:
        years.setdefault(end, _reference_year(end) + offset)

    for i, end in enumerate(ordered):
        expected = _reference_year(end) + offset

        if years[end] == expected:
            continue

        if (i > 0 and years[ordered[i - 1]] >= years[end]) or (
            i + 1 < len(ordered) and years[ordered[i + 1]] <= years[end]
        ):
            years[end] = expected

    return years


def _fiscal_position(
    date: str, ends: list[str], years: dict[str, int]
) -> tuple[int, int]:
    """Fiscal year and quarter number (1-4) of a period end on the fiscal-year-end grid."""
    dt = datetime.strptime(date, "%Y-%m-%d")
    index = min(bisect_left(ends, date), len(ends) - 1)
    fye = datetime.strptime(ends[index], "%Y-%m-%d")
    fiscal_year = years[ends[index]]

    while (fye - dt).days >= 355:
        fye -= timedelta(days=365)
        fiscal_year -= 1

    while (dt - fye).days > 10:
        fye += timedelta(days=365)
        fiscal_year += 1

    fye_date = fye.strftime("%Y-%m-%d")
    position = bisect_left(ends, fye_date)
    prev = fye - timedelta(days=365)

    if position < len(ends) and ends[position] == fye_date and position > 0:
        candidate = datetime.strptime(ends[position - 1], "%Y-%m-%d")
        if 330 <= (fye - candidate).days <= 400:
            prev = candidate

    return fiscal_year, min(4, max(1, round((dt - prev).days / 91.31)))


def get_fiscal_meta(
    facts: dict[str, Any],
    frequency: Frequency,
    filing_dates: set[str],
) -> dict[str, dict[str, Any]]:
    """Build fiscal year and period labels for each period-end date."""
    if not filing_dates:
        return {}

    annual_dates = get_filing_dates(facts, "annual")
    grid = annual_dates | filing_dates if frequency == "annual" else annual_dates
    years = annual_fiscal_years(facts, grid)

    if frequency == "annual":
        return {
            date: {"fiscal_year": years[date], "fiscal_period": "FY"}
            for date in filing_dates
        }

    if not years:
        first_year = min(int(d[:4]) for d in filing_dates)
        last_year = max(int(d[:4]) for d in filing_dates)
        years = {f"{y}-12-31": y for y in range(first_year - 1, last_year + 2)}

    quarterly_dates: set[str] = set()
    semi_dates: set[str] = set()

    for ns_facts in facts.values():
        for tag_data in ns_facts.values():
            for entries in tag_data.get("units", {}).values():
                for entry in entries:
                    end = entry.get("end", "")
                    form = entry.get("form", "")

                    if end not in filing_dates or not entry.get("filed"):
                        continue

                    if form in QUARTERLY_FORMS:
                        quarterly_dates.add(end)
                    elif form in SEMI_ANNUAL_FORMS and entry.get("start"):
                        days = (
                            datetime.strptime(end, "%Y-%m-%d")
                            - datetime.strptime(entry["start"], "%Y-%m-%d")
                        ).days
                        if 60 <= days <= 135 or 240 <= days <= 310:
                            quarterly_dates.add(end)
                        elif 150 <= days <= 200:
                            semi_dates.add(end)

    end_period = "Q4"

    if not quarterly_dates and semi_dates:
        non_annual = filing_dates - annual_dates
        end_period = "Q4" if len(non_annual) > len(annual_dates) else "H2"

    ends = sorted(years)
    result: dict[str, dict[str, Any]] = {}

    for date in filing_dates:
        fiscal_year, quarter = _fiscal_position(date, ends, years)

        if quarter == 4:
            period = end_period
        elif date in semi_dates and date not in quarterly_dates:
            period = "H1"
        else:
            period = f"Q{quarter}"

        result[date] = {"fiscal_year": fiscal_year, "fiscal_period": period}

    return result


def preliminary_view(facts: dict[str, Any], pit_mode: bool = False) -> PreliminaryFacts:
    """Return facts in which an 8-K entry keeps its form only while no regular filing had reported its period when it was filed.

    Outside pit_mode an 8-K entry is also superseded once any regular filing reports its period.
    """
    regular: list[tuple[str, str]] = []
    reported: set[str] = set()

    for namespace, ns_facts in facts.items():
        if namespace == "dei" or not isinstance(ns_facts, dict):
            continue

        for tag_data in ns_facts.values():
            for entries in tag_data.get("units", {}).values():
                for entry in entries:
                    end = entry.get("end", "")
                    filed = entry.get("filed", "")

                    if entry.get("form", "") in ALL_FORMS and end and filed > end:
                        regular.append((filed, end))
                        reported.add(end)

    regular.sort()
    filed_dates = [filed for filed, _ in regular]
    latest: list[str] = []

    for _, end in regular:
        latest.append(max(end, latest[-1]) if latest else end)

    view = PreliminaryFacts()
    view.pit_mode = pit_mode

    for namespace, ns_facts in facts.items():
        if not isinstance(ns_facts, dict):
            view[namespace] = ns_facts
            continue

        view_ns: dict[str, Any] = {}

        for tag, tag_data in ns_facts.items():
            units = tag_data.get("units", {})

            if not any(
                entry.get("form", "") in PRELIMINARY_FORMS
                for entries in units.values()
                for entry in entries
            ):
                view_ns[tag] = tag_data
                continue

            view_units: dict[str, list[dict[str, Any]]] = {}

            for unit, entries in units.items():
                view_entries: list[dict[str, Any]] = []

                for entry in entries:
                    form = entry.get("form", "")
                    view_entry = entry

                    if form in PRELIMINARY_FORMS:
                        end = entry.get("end", "")
                        filed = entry.get("filed", "")
                        index = bisect_right(filed_dates, filed)
                        known = latest[index - 1] if index else ""

                        if not (
                            end
                            and filed > end
                            and end > known
                            and (pit_mode or end not in reported)
                        ):
                            view_entry = {
                                **entry,
                                "form": form + SUPERSEDED_SUFFIX,
                            }

                    view_entries.append(view_entry)

                view_units[unit] = view_entries

            view_ns[tag] = {**tag_data, "units": view_units}

        view[namespace] = view_ns

    return view


def detect_reporting_currency(facts: dict[str, Any]) -> str:
    """Detect the reporting currency from the SEC facts data."""
    currency_counts: dict[str, int] = {}
    skip = frozenset(
        {
            "shares",
            "pure",
        }
    )

    for ns_facts in facts.values():
        for tag_data in ns_facts.values():
            for unit_key in tag_data.get("units", {}):
                if unit_key in skip or "/" in unit_key:
                    continue

                if len(unit_key) == 3 and unit_key.isalpha() and unit_key.isupper():
                    currency_counts[unit_key] = currency_counts.get(unit_key, 0) + 1

    if not currency_counts:
        return "USD"

    return max(currency_counts, key=lambda _k: currency_counts[_k])


def prior_period_end(date: str) -> str | None:
    """Return the prior quarter-end date string for a given period end."""
    _PRIOR = {
        3: lambda y: f"{y - 1}-12-31",
        6: lambda y: f"{y}-03-31",
        9: lambda y: f"{y}-06-30",
        12: lambda y: f"{y}-09-30",
        1: lambda y: f"{y - 1}-10-31",
        4: lambda y: f"{y}-01-31",
    }

    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None

    fn = _PRIOR.get(dt.month)

    return fn(dt.year) if fn else None


def filter_facts_as_of(
    facts: dict[str, Any], as_of_date: Any
) -> dict[str, Any]:
    """Return a copy of facts containing only entries filed on or before as_of_date."""
    cutoff = str(as_of_date)[:10]
    filtered: dict[str, Any] = {}

    for ns, ns_facts in facts.items():
        if not isinstance(ns_facts, dict):
            filtered[ns] = ns_facts
            continue

        ns_out: dict[str, Any] = {}
        for tag, tag_data in ns_facts.items():
            if not isinstance(tag_data, dict) or "units" not in tag_data:
                ns_out[tag] = tag_data
                continue

            units_out: dict[str, list[dict[str, Any]]] = {}
            for unit, entries in tag_data.get("units", {}).items():
                kept = [
                    e
                    for e in entries
                    if e.get("filed", "")
                    and e["filed"] <= cutoff
                    and (not e.get("end") or e["end"] <= cutoff)
                ]
                if kept:
                    units_out[unit] = kept

            if units_out:
                ns_out[tag] = {**tag_data, "units": units_out}

        if ns_out:
            filtered[ns] = ns_out

    return filtered
