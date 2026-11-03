"""Row-level value extraction from SEC XBRL facts."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from math import isclose, log10
from statistics import median
from typing import Any

from openbb_sec.utils.statement_schema._rules import (
    FILER_SCALES,
    NET_POSITIONS,
    NONNEGATIVE_CONCEPTS,
    SCALE_SPAN,
    SCALED_FILING_MIN,
    WEIGHTED_SHARE_CONCEPTS,
)
from openbb_sec.utils.statement_schema._types import (
    ALL_FORMS,
    ANNUAL_FORMS,
    ANNUAL_PERIOD_FORMS,
    PRELIMINARY_FORMS,
    SEMI_ANNUAL_FORMS,
    Frequency,
    RowDef,
    ScaledFacts,
    source_tag,
)


def _get_unit_data(
    tag_data: dict,
    unit_type: str = "monetary",
    currency: str = "USD",
) -> list[dict] | None:
    """Find the best unit data array from a tag's units dict."""
    units = tag_data.get("units", {})

    if unit_type == "shares":
        if "shares" in units:
            return units["shares"]
    elif unit_type == "per_share":
        per_share_key = f"{currency}/shares"
        if per_share_key in units:
            return units[per_share_key]
        for key in units:
            if key.startswith(f"{currency}/"):
                return units[key]
    elif currency in units:
        return units[currency]

    if units:
        return next(iter(units.values()))

    return None


_EXPONENTS = tuple(round(log10(s)) for s in FILER_SCALES)
Periods = dict[tuple[str | None, str], list[dict[str, Any]]]


def _restated(val: float, factor: Decimal) -> float:
    """Return val times factor, as an integer when whole."""
    out = Decimal(str(val)) * factor

    return int(out) if out == out.to_integral_value() else float(out)


def _scaled(val: float, other: float) -> bool:
    """Return True when val is 1,000 or 1,000,000 times other, or other that many times val."""
    return any(
        isclose(val * 10.0**x, other, rel_tol=1e-3)
        or isclose(val, other * 10.0**x, rel_tol=1e-3)
        for x in _EXPONENTS
    )


def _filing_factors(
    groups: dict[tuple[str, str, str], Periods],
) -> dict[tuple[str, bool], Decimal]:
    """Return {(accession, shares): factor} for filings whose values are mostly off by a filer scale."""
    offsets: dict[tuple[str, bool], Counter] = defaultdict(Counter)

    for key, periods in groups.items():
        for group in periods.values():
            by_accn = {e.get("accn", ""): abs(e["val"]) for e in group}

            if len(by_accn) < 2:
                continue

            for accn, val in by_accn.items():
                other = median(v for a, v in by_accn.items() if a != accn)
                offset = next(
                    (
                        k
                        for x in _EXPONENTS
                        for k in (x, -x)
                        if isclose(val * 10.0**k, other, rel_tol=1e-3)
                    ),
                    0,
                )
                offsets[(accn, key[2] == "shares")][offset] += 1

    factors: dict[tuple[str, bool], Decimal] = {}

    for filing, counts in offsets.items():
        offset, count = counts.most_common(1)[0]
        total = sum(counts.values())

        if offset and total >= SCALED_FILING_MIN and count * 2 > total:
            factors[filing] = Decimal(10) ** offset

    return factors


def _cover_counts(facts: dict[str, Any]) -> dict[str, float]:
    """Return {accession: cover-page share count} for counts within SCALE_SPAN of those filed within a year."""
    filed: dict[str, tuple[datetime, float]] = {}

    for entry in (
        facts.get("dei", {})
        .get("EntityCommonStockSharesOutstanding", {})
        .get("units", {})
        .get("shares", [])
    ):
        if entry.get("val", 0) > 0 and entry.get("accn") and entry.get("filed"):
            count = max(filed.get(entry["accn"], (None, 0))[1], entry["val"])
            filed[entry["accn"]] = (
                datetime.strptime(entry["filed"], "%Y-%m-%d"),
                count,
            )

    cover: dict[str, float] = {}

    for accn, (date, count) in filed.items():
        near = [
            log10(c)
            for a, (d, c) in filed.items()
            if a != accn and abs((d - date).days) <= 366
        ]

        if near and abs(log10(count) - median(near)) < SCALE_SPAN:
            cover[accn] = count

    return cover


def _settle_disputes(periods: Periods, values: dict[int, float]) -> None:
    """Restate each value that differs from another filing's value for its period by a filer scale."""

    def value(entry: dict[str, Any]) -> float:
        return values.get(id(entry), entry["val"])

    disputed: dict[tuple[str | None, str], float] = {}
    own: dict[str, list[float]] = defaultdict(list)

    for period, group in periods.items():
        vals = [abs(value(e)) for e in group]
        top = max(vals)

        if any(_scaled(v, top) for v in vals):
            disputed[period] = top

    for period, group in periods.items():
        if period not in disputed:
            for e in group:
                own[e.get("accn", "")].append(log10(abs(value(e))))

    if not disputed or not own:
        return

    center = median(v for logs in own.values() for v in logs)

    for period, top in disputed.items():
        fits = [
            x for x in (0, *_EXPONENTS) if abs(log10(top) - x - center) < SCALE_SPAN
        ]
        right = [
            e
            for e in periods[period]
            if len(fits) == 1
            and isclose(abs(value(e)) * 10.0 ** fits[0], top, rel_tol=1e-3)
        ]

        if not right:
            continue

        chosen = abs(value(min(right, key=lambda e: e.get("filed", ""))))

        for e in periods[period]:
            logs = own.get(e.get("accn", ""))

            if _scaled(abs(value(e)), chosen) and (
                logs is None or abs(log10(abs(value(e))) - median(logs)) >= SCALE_SPAN
            ):
                values[id(e)] = chosen if value(e) > 0 else -chosen


def rescaled_facts(facts: dict[str, Any]) -> ScaledFacts:
    """Return facts with dollar values and weighted-average share counts at the filer's scale.

    A filing whose dollar values (or share counts) for periods other filings report are,
    for most of them, 1/1,000 or 1/1,000,000 of those values or 1,000 or 1,000,000 times
    them has all its dollar values (or share counts) restated. A share count at least
    SCALE_SPAN orders of magnitude from its filing's cover-page share count takes the scale
    within SCALE_SPAN of it. A value that differs from another filing's value for the same
    concept and period by such a factor takes the scale within SCALE_SPAN of the median of
    the concept's undisputed values, unless it is within SCALE_SPAN of its own filing's
    undisputed values of the concept; a restated value keeps its sign.
    """
    series: dict[tuple[str, str, str], list[dict[str, Any]]] = {
        (ns, tag, unit): entries
        for ns, ns_facts in facts.items()
        if ns != "dei" and isinstance(ns_facts, dict)
        for tag, tag_data in ns_facts.items()
        for unit, entries in tag_data.get("units", {}).items()
        if (len(unit) == 3 and unit.isupper())
        or (unit == "shares" and f"{ns}:{tag}" in WEIGHTED_SHARE_CONCEPTS)
    }
    groups: dict[tuple[str, str, str], Periods] = {}

    for key, entries in series.items():
        groups[key] = defaultdict(list)

        for entry in entries:
            if entry.get("val") and entry.get("end") and entry.get("form") in ALL_FORMS:
                groups[key][(entry.get("start"), entry["end"])].append(entry)

    factors = _filing_factors(groups)
    values: dict[int, float] = {
        id(entry): _restated(entry["val"], factors[(entry["accn"], unit == "shares")])
        for (_, _, unit), entries in series.items()
        for entry in entries
        if entry.get("val") and (entry.get("accn"), unit == "shares") in factors
    }
    cover = _cover_counts(facts)

    for (_, _, unit), entries in series.items():
        if unit != "shares":
            continue

        for entry in entries:
            count = cover.get(entry.get("accn", ""))

            if not count or not entry.get("val"):
                continue

            gap = log10(abs(values.get(id(entry), entry["val"]))) - log10(count)
            fits = [
                k
                for x in _EXPONENTS
                for k in (x, -x)
                if abs(gap) >= SCALE_SPAN and abs(gap + k) < SCALE_SPAN
            ]

            if len(fits) == 1:
                values[id(entry)] = _restated(
                    values.get(id(entry), entry["val"]), Decimal(10) ** fits[0]
                )

    for periods in groups.values():
        _settle_disputes(periods, values)

    result = ScaledFacts(facts)

    for (ns, tag, unit), entries in series.items():
        if not any(id(e) in values for e in entries):
            continue

        if result[ns] is facts[ns]:
            result[ns] = dict(facts[ns])

        if result[ns][tag] is facts[ns][tag]:
            result[ns][tag] = {
                **facts[ns][tag],
                "units": dict(facts[ns][tag]["units"]),
            }

        result[ns][tag]["units"][unit] = [
            {**e, "val": values[id(e)]} if id(e) in values else e for e in entries
        ]

    return result


def _get_annual_values(
    facts: dict[str, Any],
    row: RowDef,
    currency: str = "USD",
    include_preliminary: bool = False,
    ref_filed_map: dict[str, str] | None = None,
) -> dict[str, tuple[str, float, str]]:
    """Return {fy_end_date: (fy_start_date, value, xbrl_source)} for annual periods, resolved at the reference filing when a map is given."""
    if row.period_type != "duration":
        return {}

    tag_candidates: list[dict[str, dict[str, tuple[str, float]]]] = []

    for xbrl_entry in row.xbrl_tags:
        ns_facts = facts.get(xbrl_entry["namespace"], {})
        tag_data = ns_facts.get(xbrl_entry["tag"])

        if not tag_data:
            tag_candidates.append({})
            continue

        unit_data = _get_unit_data(tag_data, row.unit, currency)

        if not unit_data:
            tag_candidates.append({})
            continue

        entries_by_date: dict[str, dict[str, tuple[str, float]]] = {}
        net_side = NET_POSITIONS.get(f"{xbrl_entry['namespace']}:{xbrl_entry['tag']}")
        magnitude = (
            f"{xbrl_entry['namespace']}:{xbrl_entry['tag']}" in NONNEGATIVE_CONCEPTS
        )

        for entry in unit_data:
            _av_allowed = (
                ANNUAL_PERIOD_FORMS | PRELIMINARY_FORMS
                if include_preliminary
                else ANNUAL_PERIOD_FORMS
            )
            if entry.get("form", "") not in _av_allowed:
                continue
            start, end = entry.get("start", ""), entry.get("end", "")

            if not start or not end or start == end:
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

            val = entry.get("val")

            if val is None or (val < 0 and net_side == row.balance):
                continue

            filed = entry.get("filed", "")

            if end not in entries_by_date:
                entries_by_date[end] = {}

            if filed not in entries_by_date[end]:
                entries_by_date[end][filed] = (start, abs(val) if magnitude else val)

        tag_candidates.append(entries_by_date)

    all_dates: set[str] = set()

    for tc in tag_candidates:
        all_dates.update(tc.keys())

    result: dict[str, tuple[str, float, str]] = {}

    for end_date in sorted(all_dates):
        if ref_filed_map is not None:
            ref_filed = ref_filed_map.get(end_date)

            if ref_filed is None:
                continue

            for i, tc in enumerate(tag_candidates):
                filings = tc.get(end_date)

                if filings and ref_filed in filings:
                    start, val = filings[ref_filed]
                    xbrl_e = row.xbrl_tags[i]
                    result[end_date] = (
                        start,
                        val,
                        f"{xbrl_e['namespace']}:{xbrl_e['tag']}",
                    )
                    break
            else:
                for i, tc in enumerate(tag_candidates):
                    filings = tc.get(end_date)

                    if filings:
                        before = [f for f in filings if f <= ref_filed]
                        best = max(before) if before else min(filings)
                        start, val = filings[best]
                        xbrl_e = row.xbrl_tags[i]
                        result[end_date] = (
                            start,
                            val,
                            f"{xbrl_e['namespace']}:{xbrl_e['tag']}(fallback)",
                        )
                        break

            continue

        ref_filed = None

        for tc in tag_candidates:
            filings = tc.get(end_date)

            if filings:
                earliest = min(filings)

                if ref_filed is None or earliest < ref_filed:
                    ref_filed = earliest

        if (
            ref_filed is None
        ):  # pragma: no cover - all_dates keys guarantee a ref filing
            continue

        for i, tc in enumerate(tag_candidates):
            filings = tc.get(end_date)

            if filings and ref_filed in filings:
                start, val = filings[ref_filed]
                xbrl_e = row.xbrl_tags[i]
                xbrl_src = f"{xbrl_e['namespace']}:{xbrl_e['tag']}"
                result[end_date] = (start, val, xbrl_src)
                break

    return result


def _get_ytd9_values(
    facts: dict[str, Any],
    row: RowDef,
    currency: str = "USD",
) -> dict[str, float]:
    """Return {fy_end_date: Q4_value} derived via FY - YTD_9mo."""
    if row.period_type != "duration":
        return {}

    annual_entries: dict[str, dict[str, tuple[str, float]]] = {}
    ytd9_entries: dict[str, dict[str, float]] = {}

    for xbrl_entry in row.xbrl_tags:
        ns_facts = facts.get(xbrl_entry["namespace"], {})
        tag_data = ns_facts.get(xbrl_entry["tag"])

        if not tag_data:
            continue

        unit_data = _get_unit_data(tag_data, row.unit, currency)

        if not unit_data:
            continue

        for entry in unit_data:
            start = entry.get("start", "")
            end = entry.get("end", "")

            if not start or not end or start == end:
                continue

            try:
                days = (
                    datetime.strptime(end, "%Y-%m-%d")
                    - datetime.strptime(start, "%Y-%m-%d")
                ).days
            except (ValueError, TypeError):
                continue

            val = entry.get("val")

            if val is None:
                continue

            filed = entry.get("filed", "")

            if 300 <= days <= 400:
                if end not in annual_entries:
                    annual_entries[end] = {}
                if filed not in annual_entries[end]:
                    annual_entries[end][filed] = (start, val)
            elif 240 <= days <= 310:
                if end not in ytd9_entries:
                    ytd9_entries[end] = {}
                if filed not in ytd9_entries[end]:
                    ytd9_entries[end][filed] = val

        if annual_entries or ytd9_entries:
            break

    if not annual_entries or not ytd9_entries:
        return {}

    result: dict[str, float] = {}

    for fy_end, fy_filings in annual_entries.items():
        ytd_end_match = None

        for ytd_end in ytd9_entries:
            for filed, (fy_start, _) in fy_filings.items():
                if fy_start < ytd_end < fy_end:
                    ytd_end_match = ytd_end
                    break

            if ytd_end_match:
                break

        if not ytd_end_match:
            continue

        ytd_filings = ytd9_entries[ytd_end_match]

        common = set(fy_filings) & set(ytd_filings)

        if common:
            best = max(common)
            _, fy_val = fy_filings[best]
            ytd_val = ytd_filings[best]
        else:
            latest_fy = max(fy_filings)
            _, fy_val = fy_filings[latest_fy]
            ytd_val = ytd_filings[max(ytd_filings)]

        result[fy_end] = fy_val - ytd_val

    return result


def extract_row_values(  # noqa: PLR0912
    facts: dict[str, Any],
    row: RowDef,
    frequency: Frequency = "annual",
    currency: str = "USD",
    ref_filed_map: dict[str, str] | None = None,
    cross_targets: dict[str, float] | None = None,
    statement: str = "",
    include_preliminary: bool = False,
    annual_ref_map: dict[str, str] | None = None,
) -> tuple[dict[str, float], dict[str, str]]:
    """Extract values for a single schema row across all periods."""
    period_type = row.period_type
    values_by_date: dict[str, float] = {}
    sources_by_date: dict[str, str] = {}
    _base_forms = ANNUAL_PERIOD_FORMS if frequency == "annual" else ALL_FORMS
    allowed_forms = (
        _base_forms | PRELIMINARY_FORMS if include_preliminary else _base_forms
    )
    tag_candidates: list[dict[str, dict[str, float]]] = []
    collect_ytd = (
        frequency == "quarterly" and period_type == "duration" and row.unit != "shares"
    )
    ytd_tag_candidates: list[dict[str, dict[str, tuple[str, float]]]] = []

    for xbrl_entry in row.xbrl_tags:
        ns_facts = facts.get(xbrl_entry["namespace"], {})
        tag_data = ns_facts.get(xbrl_entry["tag"])

        if not tag_data:
            tag_candidates.append({})

            if collect_ytd:
                ytd_tag_candidates.append({})

            continue

        unit_data = _get_unit_data(tag_data, row.unit, currency)

        if not unit_data:
            tag_candidates.append({})

            if collect_ytd:
                ytd_tag_candidates.append({})

            continue

        entries_by_date: dict[str, dict[str, float]] = {}
        _dur_by_date: dict[str, dict[str, int]] = {}
        ytd_entries_by_date: dict[str, dict[str, tuple[str, float]]] = {}
        net_side = NET_POSITIONS.get(f"{xbrl_entry['namespace']}:{xbrl_entry['tag']}")
        magnitude = (
            f"{xbrl_entry['namespace']}:{xbrl_entry['tag']}" in NONNEGATIVE_CONCEPTS
        )

        for entry in unit_data:
            form = entry.get("form", "")

            if form not in allowed_forms:
                continue

            end_date = entry.get("end", "")

            if not end_date:
                continue

            days = 0

            if period_type == "duration":
                start_date = entry.get("start", "")

                if not start_date or start_date == end_date:
                    continue
                try:
                    days = (
                        datetime.strptime(end_date, "%Y-%m-%d")
                        - datetime.strptime(start_date, "%Y-%m-%d")
                    ).days
                except (ValueError, TypeError):
                    continue

                if frequency == "annual":
                    if not 300 <= days <= 400:
                        continue
                elif form in SEMI_ANNUAL_FORMS:
                    if not (
                        60 <= days <= 135 or 150 <= days <= 200 or 240 <= days <= 310
                    ):
                        continue
                elif form in ANNUAL_FORMS and row.unit == "monetary":
                    continue
                elif not 60 <= days <= 135:
                    if collect_ytd and 136 <= days <= 310:
                        ytd_val = entry.get("val")
                        if ytd_val is not None and magnitude:
                            ytd_val = abs(ytd_val)
                        if ytd_val is not None and not (
                            ytd_val < 0 and net_side == row.balance
                        ):
                            filed = entry.get("filed", "")
                            if end_date not in ytd_entries_by_date:
                                ytd_entries_by_date[end_date] = {}
                            if filed not in ytd_entries_by_date[end_date]:
                                ytd_entries_by_date[end_date][filed] = (
                                    start_date,
                                    ytd_val,
                                )
                    continue

            elif entry.get("start", end_date) != end_date:
                continue

            val = entry.get("val")

            if val is None or (val < 0 and net_side == row.balance):
                continue

            if magnitude:
                val = abs(val)

            filed = entry.get("filed", "")

            if end_date not in entries_by_date:
                entries_by_date[end_date] = {}
                _dur_by_date[end_date] = {}
            if filed not in entries_by_date[end_date] or days < _dur_by_date[
                end_date
            ].get(filed, 9999):
                entries_by_date[end_date][filed] = val
                _dur_by_date[end_date][filed] = days

        tag_candidates.append(entries_by_date)

        if collect_ytd:
            ytd_tag_candidates.append(ytd_entries_by_date)

    all_dates: set[str] = set()
    rank_by_date: dict[str, int] = {}
    n_tags = len(row.xbrl_tags)

    for tc in tag_candidates:
        all_dates.update(tc.keys())

    for end_date in sorted(all_dates):
        if ref_filed_map is not None:
            ref_filed = ref_filed_map.get(end_date)
        else:
            ref_filed = None

            for tc in tag_candidates:
                filings = tc.get(end_date)
                if filings:
                    earliest = min(filings)
                    if ref_filed is None or earliest < ref_filed:
                        ref_filed = earliest

        if ref_filed is None:
            continue

        matched_identity = False

        if cross_targets and end_date in cross_targets:
            target_val = cross_targets[end_date]
            for i, tc in enumerate(tag_candidates):
                filings = tc.get(end_date)
                if not filings:
                    continue
                for val in filings.values():
                    if isclose(val, target_val, rel_tol=1e-5, abs_tol=1.0):
                        values_by_date[end_date] = val
                        rank_by_date[end_date] = i
                        xbrl_e = row.xbrl_tags[i]
                        sources_by_date[end_date] = (
                            f"{xbrl_e['namespace']}:{xbrl_e['tag']}(identity_lock:{statement})"
                        )
                        matched_identity = True
                        break

                if matched_identity:
                    break

        if matched_identity:
            continue

        for i, tc in enumerate(tag_candidates):
            filings = tc.get(end_date)

            if filings and ref_filed in filings:
                values_by_date[end_date] = filings[ref_filed]
                rank_by_date[end_date] = i
                xbrl_e = row.xbrl_tags[i]
                sources_by_date[end_date] = f"{xbrl_e['namespace']}:{xbrl_e['tag']}"
                break
        else:
            for i, tc in enumerate(tag_candidates):
                filings = tc.get(end_date)

                if filings:
                    before = [f for f in filings if f <= ref_filed]
                    best = max(before) if before else min(filings)
                    values_by_date[end_date] = filings[best]
                    rank_by_date[end_date] = n_tags + i
                    xbrl_e = row.xbrl_tags[i]
                    sources_by_date[end_date] = (
                        f"{xbrl_e['namespace']}:{xbrl_e['tag']}(fallback)"
                    )
                    break

    nine_months: dict[str, tuple[str, float, str]] = {}

    def concept_annual(
        concept: str | None, fy_end: str
    ) -> tuple[str, float, str] | None:
        chain = tuple(
            x for x in row.xbrl_tags if f"{x['namespace']}:{x['tag']}" == concept
        )

        return _get_annual_values(
            facts,
            replace(row, xbrl_tags=chain),
            currency,
            include_preliminary=include_preliminary,
            ref_filed_map=annual_ref_map,
        ).get(fy_end)

    if frequency == "quarterly" and period_type == "duration":
        annual_vals = _get_annual_values(
            facts,
            row,
            currency,
            include_preliminary=include_preliminary,
            ref_filed_map=annual_ref_map,
        )

        if collect_ytd and ytd_tag_candidates:
            ytd_resolved: dict[str, tuple[str, float, str]] = {}
            ytd_rank: dict[str, int] = {}
            ytd_all_dates: set[str] = set()

            for ytc in ytd_tag_candidates:
                ytd_all_dates.update(ytc.keys())

            for end_date in sorted(ytd_all_dates):
                if ref_filed_map is not None:
                    ref = ref_filed_map.get(end_date)
                else:
                    ref = None
                    for ytc in ytd_tag_candidates:
                        ytd_fdata = ytc.get(end_date)

                        if ytd_fdata:
                            earliest = min(ytd_fdata)
                            if ref is None or earliest < ref:
                                ref = earliest

                if ref is None:
                    continue

                chosen = next(
                    (
                        i
                        for i, ytc in enumerate(ytd_tag_candidates)
                        if ref in ytc.get(end_date, {})
                    ),
                    None,
                )

                if chosen is None:
                    chosen = next(
                        i
                        for i, ytc in enumerate(ytd_tag_candidates)
                        if ytc.get(end_date)
                    )

                ytd_fdata = ytd_tag_candidates[chosen][end_date]

                if ref in ytd_fdata:
                    start_d, val = ytd_fdata[ref]
                    ytd_rank[end_date] = chosen
                else:
                    before = [f for f in ytd_fdata if f <= ref]
                    best = max(before) if before else min(ytd_fdata)
                    start_d, val = ytd_fdata[best]
                    ytd_rank[end_date] = n_tags + chosen

                xbrl_e = row.xbrl_tags[chosen]
                ytd_resolved[end_date] = (
                    start_d,
                    val,
                    f"{xbrl_e['namespace']}:{xbrl_e['tag']}",
                )

            if ytd_resolved:
                by_fy_start: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
                for end_d, (start_d, val, src) in ytd_resolved.items():
                    by_fy_start[start_d].append((end_d, val, src))

                fy_boundaries = {
                    fy_start: fy_end for fy_end, (fy_start, _, _) in annual_vals.items()
                }

                for fy_start, ytd_list in by_fy_start.items():
                    ytd_list.sort()
                    ytd_map = {d: (v, s) for d, v, s in ytd_list}
                    fy_end = fy_boundaries.get(fy_start)

                    if fy_end:
                        fy_q_dates = sorted(
                            d for d in values_by_date if fy_start < d < fy_end
                        )
                    else:
                        latest_ytd = ytd_list[-1][0]
                        fy_q_dates = sorted(
                            d for d in values_by_date if fy_start < d <= latest_ytd
                        )

                    all_q_dates = sorted(set(fy_q_dates) | set(ytd_map.keys()))

                    prev_cum = 0
                    prev_tag: int | None = None
                    prev_end = fy_start
                    contiguous = True

                    for d, v, s in ytd_list:
                        if (
                            240
                            <= (
                                datetime.strptime(d, "%Y-%m-%d")
                                - datetime.strptime(fy_start, "%Y-%m-%d")
                            ).days
                            <= 310
                        ):
                            nine_months[fy_start] = (d, v, s)

                    for d in all_q_dates:
                        has_ytd = d in ytd_map
                        adjacent = (
                            contiguous
                            and (
                                datetime.strptime(d, "%Y-%m-%d")
                                - datetime.strptime(prev_end, "%Y-%m-%d")
                            ).days
                            <= 135
                        )
                        has_standalone = d in values_by_date and not (
                            has_ytd
                            and ytd_rank[d] < rank_by_date.get(d, -1)
                            and prev_tag == ytd_rank[d] % n_tags
                        )

                        if not has_standalone and has_ytd and adjacent:
                            ytd_val, ytd_src = ytd_map[d]
                            values_by_date[d] = ytd_val - prev_cum
                            sources_by_date[d] = f"ytd_derived({ytd_src})"

                        if has_ytd:
                            prev_cum = ytd_map[d][0]
                            prev_tag = ytd_rank[d] % n_tags
                            contiguous = True
                        elif has_standalone:
                            prev_cum += values_by_date[d]
                            prev_tag = (
                                rank_by_date[d] % n_tags if d in rank_by_date else -1
                            )
                            contiguous = adjacent

                        prev_end = d

        if row.unit == "monetary":
            for fy_end, (fy_start, fy_val, fy_xbrl_src) in annual_vals.items():
                q_sum = 0
                q_count = 0
                for q_end, q_val in values_by_date.items():
                    if fy_start < q_end < fy_end:
                        q_sum += q_val
                        q_count += 1
                if q_count == 3:
                    q_srcs = [
                        sources_by_date.get(q_end, "")
                        for q_end in sorted(values_by_date)
                        if fy_start < q_end < fy_end
                    ]
                    q_tags = {source_tag(src) for src in q_srcs}
                    base_val, base_src = fy_val, fy_xbrl_src

                    if (
                        len(q_tags) == 1
                        and None not in q_tags
                        and q_tags != {source_tag(fy_xbrl_src)}
                    ):
                        own = concept_annual(next(iter(q_tags)), fy_end)

                        if own is not None:
                            _, base_val, base_src = own

                    q_labels = "+".join(f"Q{i + 1}[{s}]" for i, s in enumerate(q_srcs))
                    values_by_date[fy_end] = base_val - q_sum
                    sources_by_date[fy_end] = f"Q4: FY[{base_src}] \u2212 ({q_labels})"
                elif (
                    fy_start in nine_months
                    and fy_start < nine_months[fy_start][0] < fy_end
                ):
                    _, nine_val, nine_src = nine_months[fy_start]
                    base = (
                        (fy_start, fy_val, fy_xbrl_src)
                        if source_tag(fy_xbrl_src) == nine_src
                        else concept_annual(nine_src, fy_end)
                    )

                    if base is not None:
                        values_by_date[fy_end] = base[1] - nine_val
                        sources_by_date[fy_end] = (
                            f"Q4: FY[{base[2]}] \u2212 9M[{nine_src}]"
                        )
                elif q_count == 1:
                    interim_date = next(
                        q_end for q_end in values_by_date if fy_start < q_end < fy_end
                    )
                    fy_days = (
                        datetime.strptime(fy_end, "%Y-%m-%d")
                        - datetime.strptime(fy_start, "%Y-%m-%d")
                    ).days
                    interim_days = (
                        datetime.strptime(interim_date, "%Y-%m-%d")
                        - datetime.strptime(fy_start, "%Y-%m-%d")
                    ).days
                    if abs(interim_days - fy_days / 2) <= 45:
                        h1_src = sources_by_date.get(interim_date, "")
                        values_by_date[fy_end] = fy_val - q_sum
                        sources_by_date[fy_end] = (
                            f"H2: FY[{fy_xbrl_src}] \u2212 H1[{h1_src}]"
                        )

    return values_by_date, sources_by_date


def compute_ref_filings(
    facts: dict[str, Any],
    rows_def: list,
    frequency: Frequency,
    currency: str,
    include_preliminary: bool = False,
    pit_mode: bool = False,
) -> dict[str, str]:
    """Compute the reference filing date per end_date across all rows."""
    _base_forms = ANNUAL_PERIOD_FORMS if frequency == "annual" else ALL_FORMS
    allowed_forms = (
        _base_forms | PRELIMINARY_FORMS if include_preliminary else _base_forms
    )
    ref_map: dict[str, str] = {}

    for row_def in rows_def:
        period_type = row_def.period_type

        for xbrl_entry in row_def.xbrl_tags:
            ns_facts = facts.get(xbrl_entry["namespace"], {})
            tag_data = ns_facts.get(xbrl_entry["tag"])

            if not tag_data:
                continue

            unit_data = _get_unit_data(tag_data, row_def.unit, currency)

            if not unit_data:
                continue

            for entry in unit_data:
                form = entry.get("form", "")

                if form not in allowed_forms:
                    continue

                end_date = entry.get("end", "")

                if not end_date:
                    continue

                if period_type == "duration":
                    start_date = entry.get("start", "")

                    if not start_date or start_date == end_date:
                        continue

                    try:
                        days = (
                            datetime.strptime(end_date, "%Y-%m-%d")
                            - datetime.strptime(start_date, "%Y-%m-%d")
                        ).days
                    except (ValueError, TypeError):
                        continue

                    if frequency == "annual":
                        if not 300 <= days <= 400:
                            continue
                    elif form in SEMI_ANNUAL_FORMS:
                        if not (
                            60 <= days <= 135
                            or 150 <= days <= 200
                            or 240 <= days <= 310
                        ):
                            continue
                    elif (
                        form in ANNUAL_FORMS
                        and row_def.unit == "monetary"
                        or not 60 <= days <= 135
                    ):
                        continue
                elif entry.get("start", end_date) != end_date:
                    continue

                filed = entry.get("filed", "")

                if not filed:
                    continue

                if not pit_mode:
                    try:
                        _gap = (
                            datetime.strptime(filed, "%Y-%m-%d")
                            - datetime.strptime(end_date, "%Y-%m-%d")
                        ).days
                    except (ValueError, TypeError):
                        continue
                    if _gap > 450:
                        continue

                if (
                    end_date not in ref_map
                    or pit_mode
                    and filed < ref_map[end_date]
                    or not pit_mode
                    and filed > ref_map[end_date]
                ):
                    ref_map[end_date] = filed

    return ref_map


def compute_period_pit_meta(
    facts: dict[str, Any],
    rows_def: list,
    frequency: Frequency,
    currency: str,
    ref_filed_map: dict[str, str],
    include_preliminary: bool = False,
) -> dict[str, dict[str, Any]]:
    """Compute per-period PIT metadata (filing_date, original_filing_date, latest_filing_date, is_restated)."""
    earliest_map = compute_ref_filings(
        facts,
        rows_def,
        frequency,
        currency,
        include_preliminary=include_preliminary,
        pit_mode=True,
    )
    latest_map = compute_ref_filings(
        facts,
        rows_def,
        frequency,
        currency,
        include_preliminary=include_preliminary,
        pit_mode=False,
    )

    _base_forms = ANNUAL_PERIOD_FORMS if frequency == "annual" else ALL_FORMS
    allowed_forms = (
        _base_forms | PRELIMINARY_FORMS if include_preliminary else _base_forms
    )

    amended_dates: set[str] = set()
    restated_dates: set[str] = set()

    for row_def in rows_def:
        period_type = row_def.period_type
        for xbrl_entry in row_def.xbrl_tags:
            ns_facts = facts.get(xbrl_entry["namespace"], {})
            tag_data = ns_facts.get(xbrl_entry["tag"])
            if not tag_data:
                continue
            unit_data = _get_unit_data(tag_data, row_def.unit, currency)
            if not unit_data:
                continue

            by_period: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
            for entry in unit_data:
                form = entry.get("form", "")
                if form not in allowed_forms:
                    continue
                end_date = entry.get("end", "")
                filed = entry.get("filed", "")
                val = entry.get("val")
                if not end_date or not filed or val is None:
                    continue

                if period_type == "duration":
                    start_date = entry.get("start", "")
                    if not start_date or start_date == end_date:
                        continue
                    try:
                        days = (
                            datetime.strptime(end_date, "%Y-%m-%d")
                            - datetime.strptime(start_date, "%Y-%m-%d")
                        ).days
                    except (ValueError, TypeError):
                        continue
                    if frequency == "annual":
                        if not 300 <= days <= 400:
                            continue
                    elif form in SEMI_ANNUAL_FORMS:
                        if not (
                            60 <= days <= 135
                            or 150 <= days <= 200
                            or 240 <= days <= 310
                        ):
                            continue
                    elif (
                        form in ANNUAL_FORMS
                        and row_def.unit == "monetary"
                        or not 60 <= days <= 135
                    ):
                        continue
                    key = (start_date, end_date)
                elif entry.get("start", end_date) != end_date:
                    continue
                else:
                    key = ("", end_date)

                if form.endswith("/A"):
                    amended_dates.add(end_date)

                latest_ref = latest_map.get(end_date)
                if latest_ref and filed > latest_ref:
                    continue
                by_period[key][filed] = float(val)

            for (_, end_date), fvals in by_period.items():
                if len(fvals) > 1:
                    earliest_f = min(fvals)
                    latest_f = max(fvals)
                    if not isclose(
                        fvals[earliest_f], fvals[latest_f], rel_tol=1e-5, abs_tol=1.0
                    ):
                        restated_dates.add(end_date)

    all_dates = set(ref_filed_map) | set(earliest_map) | set(latest_map)
    meta: dict[str, dict[str, Any]] = {}
    for end_date in all_dates:
        f_date = (
            ref_filed_map.get(end_date)
            or latest_map.get(end_date)
            or earliest_map.get(end_date)
        )
        orig_date = earliest_map.get(end_date, f_date)
        lat_date = latest_map.get(end_date, f_date)
        meta[end_date] = {
            "filing_date": f_date,
            "original_filing_date": orig_date,
            "latest_filing_date": lat_date,
            "is_restated": bool(
                end_date in restated_dates or end_date in amended_dates
            ),
        }

    return meta
