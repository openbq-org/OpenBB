"""FX forward point construction from DTCC PPD records."""

from collections.abc import Iterable
from datetime import date as dateType


def pair_rate(record: dict, base: str, quote: str) -> float | None:
    """Return units of quote per unit of base, derived from the leg notionals."""
    from openbb_cftc.utils.curve import parse_notional

    first, _ = parse_notional(record.get("Notional amount-Leg 1"))
    second, _ = parse_notional(record.get("Notional amount-Leg 2"))
    first_ccy = (record.get("Notional currency-Leg 1") or "").strip()
    second_ccy = (record.get("Notional currency-Leg 2") or "").strip()

    if not first or not second:
        return None

    if first_ccy == base and second_ccy == quote:
        return second / first

    if second_ccy == base and first_ccy == quote:
        return first / second

    return None


def base_notional(record: dict, base: str) -> float | None:
    """Return the trade's notional expressed in the base currency."""
    from openbb_cftc.utils.curve import parse_notional

    first, _ = parse_notional(record.get("Notional amount-Leg 1"))
    second, _ = parse_notional(record.get("Notional amount-Leg 2"))

    if (record.get("Notional currency-Leg 1") or "").strip() == base:
        return first

    if (record.get("Notional currency-Leg 2") or "").strip() == base:
        return second

    return None


def resolve_pair(pair: str) -> tuple[str, dict]:
    """Return a pair's canonical key and its spec."""
    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_cftc.utils.constants import FX_PAIRS

    key = (pair or "").strip().upper()

    if key not in FX_PAIRS:
        raise OpenBBError(
            f"Invalid pair: '{pair}'. Valid pairs are: " + ", ".join(FX_PAIRS)
        )

    return key, FX_PAIRS[key]


def _fx_observation(
    record: dict,
    trade_date: dateType,
    spec: dict,
    min_notional: float,
) -> dict | None:
    """Reduce a deliverable forward or FX swap to, or None."""
    from openbb_cftc.utils.curve import parse_date

    base, quote = spec["base"], spec["quote"]
    fisn = (record.get("UPI FISN") or "").strip()

    if fisn not in {spec["forward_fisn"], spec["swap_fisn"]}:
        return None

    if (record.get("Action type") or "").strip() != "NEWT":
        return None

    if (record.get("Event type") or "").strip() != "TRAD":
        return None

    rate = pair_rate(record, base, quote)
    expiration = parse_date(record.get("Expiration Date"))

    if rate is None or rate <= 0 or expiration is None:
        return None

    notional = base_notional(record, base)

    if notional is None or notional < min_notional:
        return None

    days = (expiration - trade_date).days

    if days < 0:
        return None

    return {
        "days": days,
        "trade_date": trade_date,
        "rate": rate if not spec["invert"] else 1.0 / rate,
        "notional": notional,
        "is_swap": fisn == spec["swap_fisn"],
        "dissemination_identifier": (
            record.get("Dissemination Identifier") or ""
        ).strip(),
    }


CARRY_FLOOR = 0.03
CARRY_PER_YEAR = 0.25


def carry_bound(days: int) -> float:
    """Largest log distance from spot a forward's carry can open over a tenor."""
    return CARRY_FLOOR + CARRY_PER_YEAR * max(days, 0) / 365.0


def _stated_rate(record: dict, anchor: float) -> float | None:
    """Return the record's exchange rate, oriented to the pair's prevailing level."""
    from math import log

    from openbb_cftc.utils.curve import parse_notional

    rate, _ = parse_notional(record.get("Exchange rate"))

    if not rate or rate <= 0.0 or anchor <= 0.0:
        return None

    return (
        rate
        if abs(log(rate / anchor)) <= abs(log((1.0 / rate) / anchor))
        else 1.0 / rate
    )


def extract_fx_observations(
    records: Iterable[dict],
    pair: str,
    trade_date: dateType,
    min_notional: float = 1_000_000.0,
) -> list[dict]:
    """Select deliverable forwards and FX swaps for a pair, above a notional floor."""
    from math import log
    from statistics import median

    _, spec = resolve_pair(pair)
    candidates: list[tuple[dict, dict]] = []

    for record in records:
        observation = _fx_observation(record, trade_date, spec, min_notional)

        if observation is not None:
            candidates.append((record, observation))

    if not candidates:
        return []

    anchor = median(observation["rate"] for _, observation in candidates)
    observations: list[dict] = []

    for record, observation in candidates:
        stated = _stated_rate(record, anchor)
        rate = stated if stated is not None else observation["rate"]

        if abs(log(rate / anchor)) <= carry_bound(observation["days"]):
            observations.append({**observation, "rate": rate})

    return observations


def extract_fx_observations_by_day(
    records: Iterable[dict],
    pair: str,
    min_notional: float = 1_000_000.0,
) -> list[dict]:
    """Select a pair's trades, dating each against its own dissemination day."""
    from openbb_cftc.utils.curve import record_trade_date

    _, spec = resolve_pair(pair)
    observations: list[dict] = []

    for record in records:
        trade_date = record_trade_date(record)

        if trade_date is None:
            continue

        observation = _fx_observation(record, trade_date, spec, min_notional)

        if observation is not None:
            observations.append(observation)

    return observations


def _bucket_of(days: int) -> str | None:
    """Return the tenor bucket a settlement horizon falls in."""
    from openbb_cftc.utils.constants import FX_TENOR_BUCKETS

    for label, low, high in FX_TENOR_BUCKETS:
        if low <= days <= high:
            return label

    return None


def _percentile(ordered: list[float], pct: float) -> float:
    """Linearly interpolated percentile of a sorted list of two or more values."""
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    frac = rank - low

    return ordered[low] + frac * (ordered[low + 1] - ordered[low])


def trim_fx_observations(observations: list[dict]) -> list[dict]:
    """Drop observations whose rate is an outlier within its own tenor bucket."""
    from collections import defaultdict

    groups: dict[str, list[dict]] = defaultdict(list)

    for observation in observations:
        label = _bucket_of(observation["days"])

        if label is not None:
            groups[label].append(observation)

    kept: list[dict] = []

    for members in groups.values():
        if len(members) < 3:
            kept.extend(members)
            continue

        ordered = sorted(m["rate"] for m in members)
        low = _percentile(ordered, 5)
        high = _percentile(ordered, 95)
        kept.extend(m for m in members if low <= m["rate"] <= high)

    return kept


def _spot_rate(observations: list[dict], spot_max_days: int) -> float | None:
    """Proxy spot with the median of the shortest-dated trades, or None if none are near."""
    from statistics import median

    rates = [o["rate"] for o in observations if o["days"] <= spot_max_days]

    return median(rates) if rates else None


def _ndf_spot(observations: list[dict]) -> float | None:
    """Recover a T+2 spot for a non-deliverable pair from its two shortest tenor buckets."""
    from collections import defaultdict
    from statistics import median

    from openbb_cftc.utils.constants import FX_TENOR_BUCKETS

    buckets: dict[str, list[dict]] = defaultdict(list)

    for observation in observations:
        label = _bucket_of(observation["days"])

        if label is not None:
            buckets[label].append(observation)

    nodes: list[tuple[float, float]] = []

    for label, _low, _high in FX_TENOR_BUCKETS:
        members = buckets.get(label)

        if members:
            day = median([m["days"] for m in members])
            rate = median([m["rate"] for m in members])
            nodes.append((day, rate))

    if not nodes:
        return None

    if len(nodes) == 1:
        return nodes[0][1]

    (day_near, rate_near), (day_next, rate_next) = nodes[0], nodes[1]
    slope = (rate_next - rate_near) / (day_next - day_near)

    return rate_near + slope * (2.0 - day_near)


def _establish_spot(
    observations: list[dict], spec: dict, spot_max_days: int
) -> float | None:
    """Spot from the shortest NDF tenor, or the near-dated trades of a deliverable pair."""
    if spec.get("ndf"):
        return _ndf_spot(observations)

    return _spot_rate(observations, spot_max_days)


def _drop_ndf_spot_window(observations: list[dict], spot_max_days: int) -> list[dict]:
    """Drop the stray trades inside the spot window of a non-deliverable pair."""
    return [o for o in observations if o["days"] > spot_max_days]


def _point(
    label: str,
    tenor_days: int,
    members: list[dict],
    spot: float,
    spec: dict,
    pair: str,
) -> dict:
    """Reduce a bucket's trades to a forward rate and its distance from spot."""
    from statistics import median

    rates = [m["rate"] for m in members]
    rate = median(rates)

    return {
        "pair": pair,
        "tenor": label,
        "tenor_days": tenor_days,
        "spot_rate": spot,
        "forward_rate": rate,
        "forward_points": (rate - spot) * spec["pip"],
        "num_trades": len(members),
        "total_notional": sum(m["notional"] for m in members),
        "min_rate": min(rates),
        "max_rate": max(rates),
    }


def build_forward_points(
    records: Iterable[dict],
    pair: str,
    trade_date: dateType,
    min_notional: float = 1_000_000.0,
    min_trades: int = 1,
    spot_max_days: int = 2,
) -> list[dict]:
    """Build a pair's spot rate and forward points per tenor bucket, on one day."""
    from collections import defaultdict

    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_cftc.utils.constants import FX_TENOR_BUCKETS

    key, spec = resolve_pair(pair)
    observations = extract_fx_observations(
        records, pair=key, trade_date=trade_date, min_notional=min_notional
    )

    if not observations:
        raise OpenBBError(
            f"No {key} forwards or FX swaps at or above a"
            f" {min_notional:,.0f} {spec['base']} notional were reported for {trade_date}."
        )

    observations = trim_fx_observations(observations)

    if spec.get("ndf"):
        observations = _drop_ndf_spot_window(observations, spot_max_days)

    spot = _establish_spot(observations, spec, spot_max_days)

    if spot is None:
        horizon = "any tenor bucket" if spec.get("ndf") else f"{spot_max_days} days"
        raise OpenBBError(
            f"No {key} trades inside {horizon} were reported for {trade_date}, so spot"
            " cannot be established."
        )

    groups: dict[str, list[dict]] = defaultdict(list)

    for observation in observations:
        label = _bucket_of(observation["days"])

        if label is not None:
            groups[label].append(observation)

    results: list[dict] = []

    for label, low, _ in FX_TENOR_BUCKETS:
        members = groups.get(label)

        if not members or len(members) < min_trades:
            continue

        point = _point(label, low, members, spot, spec, key)
        point["date"] = trade_date
        point["as_of_date"] = trade_date
        point["staleness_days"] = 0
        results.append(point)

    if not results:
        raise OpenBBError(
            f"No {key} tenor buckets had at least {min_trades} trades on {trade_date}."
        )

    return results


def build_forward_points_as_of(
    records: Iterable[dict],
    pair: str,
    min_notional: float = 1_000_000.0,
    min_trades: int = 1,
    spot_max_days: int = 2,
) -> list[dict]:
    """Build forward points per tenor from that tenor's most recent qualifying day."""
    from collections import defaultdict

    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_cftc.utils.constants import FX_TENOR_BUCKETS

    key, spec = resolve_pair(pair)
    observations = extract_fx_observations_by_day(
        records, pair=key, min_notional=min_notional
    )

    if not observations:
        raise OpenBBError(
            f"No {key} forwards or FX swaps at or above a"
            f" {min_notional:,.0f} {spec['base']} notional were disseminated in the"
            " search window."
        )

    if spec.get("ndf"):
        observations = _drop_ndf_spot_window(observations, spot_max_days)

    by_day: dict[dateType, list[dict]] = defaultdict(list)

    for observation in observations:
        by_day[observation["trade_date"]].append(observation)

    spots: dict[dateType, float] = {}
    buckets: dict[str, dict[dateType, list[dict]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for day, raw_members in by_day.items():
        members = trim_fx_observations(raw_members)
        spot = _establish_spot(members, spec, spot_max_days)

        if spot is None:
            continue

        spots[day] = spot

        for observation in members:
            label = _bucket_of(observation["days"])

            if label is not None:
                buckets[label][day].append(observation)

    if not spots:
        horizon = "any tenor bucket" if spec.get("ndf") else f"{spot_max_days} days"
        raise OpenBBError(
            f"No {key} trades inside {horizon} were disseminated in the search window,"
            " so spot cannot be established."
        )

    results: list[dict] = []

    for label, low, _ in FX_TENOR_BUCKETS:
        for day in sorted(buckets.get(label, {}), reverse=True):
            members = buckets[label][day]

            if len(members) < min_trades:
                continue

            point = _point(label, low, members, spots[day], spec, key)
            point["as_of_date"] = day
            results.append(point)
            break

    if not results:
        raise OpenBBError(
            f"No {key} tenor bucket had a single day with at least {min_trades} trades"
            " in the search window."
        )

    freshest = max(point["as_of_date"] for point in results)

    for point in results:
        point["date"] = freshest
        point["staleness_days"] = (freshest - point["as_of_date"]).days

    return results


def _per_usd_curve(points: list[dict], pair: str) -> list[dict]:
    """Reorient a pair's forward points to the outright forward in the currency per USD."""
    invert = not pair.upper().startswith("USD")
    nodes: list[dict] = []

    for point in points:
        forward, spot = point["forward_rate"], point["spot_rate"]
        low, high = point["min_rate"], point["max_rate"]
        nodes.append(
            {
                "tenor": point["tenor"],
                "tenor_days": point["tenor_days"],
                "rate": 1.0 / forward if invert else forward,
                "spot": 1.0 / spot if invert else spot,
                "num_trades": point["num_trades"],
                "total_notional": point["total_notional"],
                "min_rate": 1.0 / high if invert else low,
                "max_rate": 1.0 / low if invert else high,
                "date": point["date"],
                "as_of_date": point["as_of_date"],
                "staleness_days": point["staleness_days"],
            }
        )

    return nodes


def build_fx_forward_curve(
    records: Iterable[dict],
    pair: str,
    trade_date: dateType,
    min_notional: float = 1_000_000.0,
    min_trades: int = 1,
) -> list[dict]:
    """Outright forward curve, the currency per USD, from one day's forward points."""
    return _per_usd_curve(
        build_forward_points(
            records,
            pair=pair,
            trade_date=trade_date,
            min_notional=min_notional,
            min_trades=min_trades,
        ),
        pair,
    )


def build_fx_forward_curve_as_of(
    records: Iterable[dict],
    pair: str,
    min_notional: float = 1_000_000.0,
    min_trades: int = 1,
) -> list[dict]:
    """Outright forward curve, each tenor priced from its most recent qualifying day."""
    return _per_usd_curve(
        build_forward_points_as_of(
            records, pair=pair, min_notional=min_notional, min_trades=min_trades
        ),
        pair,
    )
