"""Swap curve construction from DTCC PPD slice records."""

from collections.abc import Iterable
from datetime import (
    UTC,
    date as dateType,
)


def _is_closed_date(trade_date: dateType) -> bool:
    """Whether a report date's file has fully disseminated and cannot change again."""
    from datetime import datetime

    return trade_date < datetime.now(UTC).date()


def _curve_cache_key(**fields) -> str:
    """Return a stable digest of a derived curve's full parameter signature."""
    import hashlib
    import json

    signature = dict(fields)

    return hashlib.sha256(
        json.dumps(signature, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _encode_curve_dates(curve: list[dict]) -> list[dict]:
    """Return a curve's nodes with their date fields as ISO strings, for JSON storage."""
    return [
        {
            **node,
            "date": node["date"].isoformat(),
            "as_of_date": node["as_of_date"].isoformat(),
            "maturity_date": node["maturity_date"].isoformat(),
        }
        for node in curve
    ]


def _decode_curve_dates(curve: list[dict]) -> list[dict]:
    """Return a cached curve's nodes with their date fields parsed back from ISO strings."""
    return [
        {
            **node,
            "date": dateType.fromisoformat(node["date"]),
            "as_of_date": dateType.fromisoformat(node["as_of_date"]),
            "maturity_date": dateType.fromisoformat(node["maturity_date"]),
        }
        for node in curve
    ]


def parse_notional(value: str | None) -> tuple[float | None, bool]:
    """Parse a notional amount, reporting whether it was disseminated at a cap."""
    text = (value or "").strip()

    if not text:
        return None, False

    capped = text.endswith("+")
    text = text.rstrip("+")
    digits = text.replace(",", "").replace(".", "")

    if digits and set(digits) == {"9"}:
        return None, capped

    try:
        return float(text.replace(",", "")), capped
    except ValueError:
        return None, capped


def parse_rate(record: dict) -> float | None:
    """Return a trade's fixed rate, which may be reported on either leg."""
    for field in ("Fixed rate-Leg 1", "Fixed rate-Leg 2"):
        text = (record.get(field) or "").strip()

        if not text:
            continue

        try:
            rate = float(text)
        except ValueError:
            continue

        if rate:
            return rate

    return None


def parse_date(value: str | None) -> dateType | None:
    """Parse a PPD date field."""
    text = (value or "").strip()

    if not text:
        return None

    try:
        return dateType.fromisoformat(text[:10])
    except ValueError:
        return None


def tenor_label(days: int) -> str:
    """Return a compact label for a tenor expressed in days."""
    if days % 365 == 0 and days >= 365:
        return f"{days // 365}Y"

    if days >= 365:
        return f"{days}D"

    if days % 30 == 0 and days >= 30:
        return f"{days // 30}M"

    return f"{days}D"


def bucket_tenor(days: int) -> tuple[str, int] | None:
    """Snap a tenor to its benchmark node, or None when it matches no node."""
    from openbb_cftc.utils.constants import BENCHMARK_TENORS

    for label, node in BENCHMARK_TENORS:
        if abs(days - node) <= max(4, node * 0.02):
            return label, node

    return None


def record_trade_date(record: dict) -> dateType | None:
    """Return the dissemination date a search record was reported on."""
    return parse_date(record.get("Dissemination Timestamp"))


def is_vanilla_par(record: dict) -> bool:
    """Whether a rate-swap print quotes a standalone par rate."""

    def _set(field: str) -> bool:
        return bool((record.get(field) or "").strip())

    return (
        (record.get("Package indicator") or "").strip() != "TRUE"
        and not _set("Package transaction price")
        and not _set("Package transaction spread")
        and not _set("Other payment amount")
        and not _set("Spread-Leg 1")
        and not _set("Spread-Leg 2")
        and (record.get("Non-standardized term indicator") or "").strip() != "TRUE"
        and not _set("Fixed rate-Leg 2")
    )


def parse_frequency(
    period: str | None, multiplier: str | None
) -> tuple[str, int] | None:
    """Return a reported payment or reset frequency as, or None."""
    unit = (period or "").strip().upper()

    if unit == "EXPI":
        return ("EXPI", 1)

    if unit not in {"YEAR", "MNTH", "WEEK", "DAIL"}:
        return None

    text = (multiplier or "").strip()

    if not text.isdigit() or int(text) <= 0:
        return None

    return (unit, int(text))


def frequency_days(period: str | None, multiplier: str | None) -> int | None:
    """Payment period in days from a reported frequency, or None when unusable."""
    count_text = (multiplier or "").strip()

    if not count_text.isdigit():
        return None

    count = int(count_text)
    unit = {"YEAR": 365.0, "MNTH": 365.0 / 12.0, "WEEK": 7.0, "DAIL": 1.0}.get(
        (period or "").strip().upper()
    )

    if unit is None or count <= 0:
        return None

    return round(count * unit)


def _payment_period_days(record: dict) -> int | None:
    """Fixed-leg coupon period in days from a trade's reported payment frequency."""
    return frequency_days(
        record.get("Fixed rate payment frequency period-Leg 1"),
        record.get("Fixed rate payment frequency period multiplier-Leg 1"),
    )


def _observation(
    record: dict,
    trade_date: dateType,
    fisn: str,
    currency: str,
    spot_only: bool,
    spot_window: int,
) -> dict | None:
    """Reduce a priceable new trade to, or None."""
    if (record.get("UPI FISN") or "").strip() != fisn:
        return None

    if (record.get("Action type") or "").strip() != "NEWT":
        return None

    if (record.get("Event type") or "").strip() != "TRAD":
        return None

    if (record.get("Notional currency-Leg 1") or "").strip() != currency:
        return None

    rate = parse_rate(record)
    effective = parse_date(record.get("Effective Date"))
    expiration = parse_date(record.get("Expiration Date"))

    if rate is None or effective is None or expiration is None:
        return None

    forward_days = (effective - trade_date).days

    if spot_only and not 0 <= forward_days <= spot_window:
        return None

    from openbb_cftc.utils.constants import MAX_CURVE_DAYS

    tenor_days = (expiration - effective).days

    if not 0 < tenor_days <= MAX_CURVE_DAYS:
        return None

    notional, capped = parse_notional(record.get("Notional amount-Leg 1"))

    return {
        "rate": rate,
        "tenor_days": tenor_days,
        "trade_date": trade_date,
        "effective_date": effective,
        "expiration_date": expiration,
        "notional": notional,
        "is_capped": capped,
        "cleared": (record.get("Cleared") or "").strip().upper() or None,
        "day_count": (record.get("Fixed rate day count convention-leg 1") or "").strip()
        or None,
        "payment_period": _payment_period_days(record),
    }


def _is_cleared(observation: dict) -> bool:
    """Whether a trade is centrally cleared or intended for clearing, not bilateral."""
    return observation["cleared"] in ("Y", "I")


def extract_observations(
    records: Iterable[dict],
    trade_date: dateType,
    fisn: str,
    currency: str = "USD",
    spot_only: bool = True,
    spot_window: int = 5,
    cleared_only: bool = False,
) -> list[dict]:
    """Select priceable new trades and reduce them to."""
    observations: list[dict] = []

    for record in records:
        observation = _observation(
            record, trade_date, fisn, currency, spot_only, spot_window
        )

        if observation is None or (cleared_only and not _is_cleared(observation)):
            continue

        observations.append(observation)

    return observations


def extract_observations_by_day(
    records: Iterable[dict],
    fisn: str,
    currency: str = "USD",
    spot_only: bool = True,
    spot_window: int = 5,
    cleared_only: bool = False,
) -> list[dict]:
    """Select priceable new trades, dating each against its own dissemination day."""
    observations: list[dict] = []

    for record in records:
        trade_date = record_trade_date(record)

        if trade_date is None:
            continue

        observation = _observation(
            record, trade_date, fisn, currency, spot_only, spot_window
        )

        if observation is None or (cleared_only and not _is_cleared(observation)):
            continue

        observations.append(observation)

    return observations


def _percentile(ordered: list[float], pct: float) -> float:
    """Linearly interpolated percentile of a sorted list of two or more values."""
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    frac = rank - low

    return ordered[low] + frac * (ordered[low + 1] - ordered[low])


def _nearest_benchmark_days(days: int) -> int:
    """Return the benchmark tenor, in days, closest to a given tenor."""
    from openbb_cftc.utils.constants import BENCHMARK_TENORS

    return min((d for _, d in BENCHMARK_TENORS), key=lambda d: abs(d - days))


def trim_observations(observations: list[dict]) -> list[dict]:
    """Drop observations whose rate is an outlier within its nearest benchmark tenor."""
    from collections import defaultdict

    groups: dict[int, list[dict]] = defaultdict(list)

    for observation in observations:
        groups[_nearest_benchmark_days(observation["tenor_days"])].append(observation)

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


def _aggregate(rates: list[float], notionals: list[float | None], method: str) -> float:
    """Reduce a node's observations to a single par rate."""
    from statistics import fmean, median

    if method == "mean":
        return fmean(rates)

    if method == "vwap":
        weights = [n or 0.0 for n in notionals]
        total = sum(weights)

        if total > 0:
            return sum(r * w for r, w in zip(rates, weights)) / total

    return median(rates)


def _node_key(observation: dict, granularity: str) -> tuple[str, int] | None:
    """Return the curve node an observation belongs to."""
    days = observation["tenor_days"]

    if granularity == "observed":
        return tenor_label(days), days

    return bucket_tenor(days)


def _node(
    label: str,
    days: int,
    members: list[dict],
    aggregation: str,
    day_count_default: str,
) -> dict:
    """Aggregate a node's observations into a par rate and its quality markers."""
    from collections import Counter

    from openbb_cftc.utils.constants import (
        DAY_COUNT_CODES,
        OIS_PAYMENT_PERIOD_DAYS,
        day_count_basis,
    )

    rates = [m["rate"] for m in members]
    notionals = [m["notional"] for m in members]
    total = sum(n for n in notionals if n is not None)
    codes = Counter(m["day_count"] for m in members if m.get("day_count"))
    code = codes.most_common(1)[0][0] if codes else day_count_default
    periods = Counter(m["payment_period"] for m in members if m.get("payment_period"))
    period = periods.most_common(1)[0][0] if periods else OIS_PAYMENT_PERIOD_DAYS

    return {
        "tenor": label,
        "tenor_days": days,
        "tenor_years": round(days / 365.0, 6),
        "par_rate": _aggregate(rates, notionals, aggregation),
        "num_trades": len(members),
        "total_notional": total or None,
        "min_rate": min(rates),
        "max_rate": max(rates),
        "is_capped": any(m["is_capped"] for m in members),
        "day_count": DAY_COUNT_CODES.get(code, code),
        "day_count_basis": day_count_basis(code, day_count_default),
        "payment_period_days": period,
    }


def build_nodes(
    observations: list[dict],
    granularity: str = "benchmark",
    aggregation: str = "median",
    min_trades: int = 1,
    day_count_default: str = "A004",
) -> list[dict]:
    """Group observations into curve nodes and aggregate each to a par rate."""
    from collections import defaultdict

    groups: dict[tuple[str, int], list[dict]] = defaultdict(list)

    for observation in observations:
        key = _node_key(observation, granularity)

        if key is None:
            continue

        groups[key].append(observation)

    return [
        _node(label, days, members, aggregation, day_count_default)
        for (label, days), members in sorted(groups.items(), key=lambda kv: kv[0][1])
        if len(members) >= min_trades
    ]


def build_nodes_as_of(
    observations: list[dict],
    granularity: str = "benchmark",
    aggregation: str = "median",
    min_trades: int = 1,
    day_count_default: str = "A004",
) -> list[dict]:
    """Build each node from the most recent dissemination day that clears min_trades."""
    from collections import defaultdict

    groups: dict[tuple[str, int], dict[dateType, list[dict]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for observation in observations:
        key = _node_key(observation, granularity)

        if key is None:
            continue

        groups[key][observation["trade_date"]].append(observation)

    nodes: list[dict] = []

    for (label, days), by_day in sorted(groups.items(), key=lambda kv: kv[0][1]):
        for as_of in sorted(by_day, reverse=True):
            members = by_day[as_of]

            if len(members) < min_trades:
                continue

            node = _node(label, days, members, aggregation, day_count_default)
            node["as_of_date"] = as_of
            nodes.append(node)
            break

    if nodes:
        freshest = max(node["as_of_date"] for node in nodes)

        for node in nodes:
            node["staleness_days"] = (freshest - node["as_of_date"]).days

    return nodes


def _monotone_slopes(times: list[float], values: list[float]) -> list[float]:
    """Fritsch-Butland monotone Hermite slopes: shape-preserving, never overshooting."""
    count = len(values)

    if count == 1:
        return [0.0]

    widths = [times[i + 1] - times[i] for i in range(count - 1)]
    secants = [(values[i + 1] - values[i]) / widths[i] for i in range(count - 1)]
    slopes = [secants[0]] + [0.0] * (count - 2) + [secants[-1]]

    for i in range(1, count - 1):
        if secants[i - 1] * secants[i] <= 0:
            slopes[i] = 0.0
        else:
            weight_left = 2 * widths[i] + widths[i - 1]
            weight_right = widths[i] + 2 * widths[i - 1]
            slopes[i] = (weight_left + weight_right) / (
                weight_left / secants[i - 1] + weight_right / secants[i]
            )

    return slopes


def _interpolate_log_df(
    curve: list[tuple[float, float]], years: float, interpolation: str = "log_linear"
) -> float:
    """Interpolate a discount factor in time, on the log of the discount factor."""
    import bisect
    from math import exp, log

    if not curve:
        return 1.0

    times = [t for t, _ in curve]
    logs = [log(f) for _, f in curve]

    if years <= times[0]:
        return exp(logs[0] * years / times[0])

    if years >= times[-1]:
        return exp(logs[-1] * years / times[-1])

    index = bisect.bisect_left(times, years)
    t0, t1 = times[index - 1], times[index]
    y0, y1 = logs[index - 1], logs[index]

    if interpolation == "log_linear" or len(curve) < 3:
        return exp(y0 + (y1 - y0) * (years - t0) / (t1 - t0))

    slopes = _monotone_slopes(times, logs)
    width = t1 - t0
    s = (years - t0) / width
    s2 = s * s
    s3 = s2 * s
    value = (
        (2 * s3 - 3 * s2 + 1) * y0
        + (s3 - 2 * s2 + s) * width * slopes[index - 1]
        + (-2 * s3 + 3 * s2) * y1
        + (s3 - s2) * width * slopes[index]
    )

    return exp(value)


def interpolate_monotone(points: list[tuple[float, float]], x: float) -> float:
    """Shape-preserving monotone Hermite interpolation of ```` points."""
    import bisect

    if not points:
        return 0.0

    times = [t for t, _ in points]
    values = [v for _, v in points]

    if x <= times[0]:
        return values[0]

    if x >= times[-1]:
        return values[-1]

    slopes = _monotone_slopes(times, values)
    index = bisect.bisect_left(times, x)
    t0, t1 = times[index - 1], times[index]
    y0, y1 = values[index - 1], values[index]
    width = t1 - t0
    s = (x - t0) / width
    s2 = s * s
    s3 = s2 * s

    return (
        (2 * s3 - 3 * s2 + 1) * y0
        + (s3 - 2 * s2 + s) * width * slopes[index - 1]
        + (-2 * s3 + 3 * s2) * y1
        + (s3 - s2) * width * slopes[index]
    )


def _payment_offsets(tenor_days: int, period_days: int | None = None) -> list[int]:
    """Build a fixed-leg schedule rolled back from maturity, leaving a front stub."""
    from openbb_cftc.utils.constants import (
        OIS_PAYMENT_PERIOD_DAYS,
        SINGLE_PAYMENT_MAX_DAYS,
    )

    period = period_days or OIS_PAYMENT_PERIOD_DAYS
    threshold = period + (SINGLE_PAYMENT_MAX_DAYS - OIS_PAYMENT_PERIOD_DAYS)
    offsets: list[int] = []
    remaining = tenor_days

    while remaining > threshold:
        offsets.append(remaining)
        remaining -= period

    offsets.append(remaining)
    offsets.reverse()

    return offsets


def bootstrap(nodes: list[dict], interpolation: str = "log_linear") -> list[dict]:
    """Bootstrap discount factors and zero rates from par rates."""
    from math import log

    from openbb_cftc.utils.constants import (
        MAX_ABS_ZERO_RATE,
        OIS_PAYMENT_PERIOD_DAYS,
        ZERO_RATE_BASIS,
    )

    curve: list[tuple[float, float]] = []
    results: list[dict] = []

    for node in sorted(nodes, key=lambda n: n["tenor_days"]):
        days = node["tenor_days"]
        par = node["par_rate"]
        years = days / ZERO_RATE_BASIS
        basis = node["day_count_basis"]
        period = node.get("payment_period_days", OIS_PAYMENT_PERIOD_DAYS)
        result = dict(node)
        result.pop("day_count_basis", None)
        result.pop("payment_period_days", None)

        offsets = _payment_offsets(days, period)
        accrued = 0.0
        previous_offset = 0

        for offset in offsets[:-1]:
            tau_i = (offset - previous_offset) / basis
            accrued += tau_i * _interpolate_log_df(
                curve, offset / ZERO_RATE_BASIS, interpolation
            )
            previous_offset = offset

        tau_n = (offsets[-1] - previous_offset) / basis
        denominator = 1.0 + par * tau_n
        df = (1.0 - par * accrued) / denominator if denominator > 0 else 0.0

        log_zero = -log(df) / years if df > 0.0 else None

        if log_zero is None or abs(log_zero) > MAX_ABS_ZERO_RATE:
            result.update(discount_factor=None, zero_rate=None)
            results.append(result)
            continue

        result.update(discount_factor=df, zero_rate=(1.0 / df) ** (1.0 / years) - 1.0)
        results.append(result)

        curve.append((years, df))
        curve.sort()

    return results


def forward_par_rate(
    dfs: list[tuple[float, float]],
    start_years: float,
    tenor_years: float,
    basis: float,
    period_days: int | None = None,
    interpolation: str = "log_linear",
) -> float | None:
    """Forward par swap rate for a ``tenor``-year OIS starting at ``start_years``."""
    from openbb_cftc.utils.constants import ZERO_RATE_BASIS

    if not dfs or start_years < 0 or start_years > dfs[-1][0] + 1e-9:
        return None

    tenor_days = round(tenor_years * ZERO_RATE_BASIS)

    if tenor_days <= 0:
        return None

    end_years = start_years + tenor_days / ZERO_RATE_BASIS
    annuity = 0.0
    previous_offset = 0

    for offset in _payment_offsets(tenor_days, period_days):
        tau = (offset - previous_offset) / basis
        annuity += tau * _interpolate_log_df(
            dfs, start_years + offset / ZERO_RATE_BASIS, interpolation
        )
        previous_offset = offset

    df_start = _interpolate_log_df(dfs, start_years, interpolation)
    df_end = _interpolate_log_df(dfs, end_years, interpolation)

    return (df_start - df_end) / annuity


_NSS_MIN_NODES = 6
_NSS_TAU1 = tuple(0.5 + 0.25 * i for i in range(20))
_NSS_TAU2 = tuple(2.0 + 0.5 * i for i in range(37))


def _nss_basis(t: float, tau1: float, tau2: float) -> tuple[float, float, float, float]:
    """Nelson-Siegel-Svensson basis functions at ``t`` for two decay times."""
    from math import exp

    a, b = t / tau1, t / tau2
    e1, e2 = exp(-a), exp(-b)
    slope = (1.0 - e1) / a

    return 1.0, slope, slope - e1, (1.0 - e2) / b - e2


def _solve4(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Solve a 4x4 linear system by Gaussian elimination with partial pivoting, or None."""
    m = [matrix[i][:] + [rhs[i]] for i in range(4)]

    for col in range(4):
        pivot = max(range(col, 4), key=lambda r: abs(m[r][col]))
        m[col], m[pivot] = m[pivot], m[col]

        if abs(m[col][col]) < 1e-15:
            return None

        for r in range(4):
            if r != col:
                factor = m[r][col] / m[col][col]
                for k in range(col, 5):
                    m[r][k] -= factor * m[col][k]

    return [m[i][4] / m[i][i] for i in range(4)]


def fit_nss(
    points: list[tuple[float, float]], weights: list[float]
) -> tuple[float, float, float, float, float, float] | None:
    """Fit Svensson to weighted points, or None."""
    if len(points) < _NSS_MIN_NODES:
        return None

    best: tuple[float, list[float], float, float] | None = None

    for tau1 in _NSS_TAU1:
        for tau2 in _NSS_TAU2:
            if tau2 <= tau1:
                continue

            ata = [[0.0] * 4 for _ in range(4)]
            aty = [0.0] * 4

            for (t, z), w in zip(points, weights):
                f = _nss_basis(t, tau1, tau2)
                for i in range(4):
                    aty[i] += w * f[i] * z
                    for j in range(4):
                        ata[i][j] += w * f[i] * f[j]

            betas = _solve4(ata, aty)

            if betas is None:
                continue

            sse = sum(
                w
                * (
                    sum(betas[i] * fi for i, fi in enumerate(_nss_basis(t, tau1, tau2)))
                    - z
                )
                ** 2
                for (t, z), w in zip(points, weights)
            )

            if best is None or sse < best[0]:
                best = (sse, betas, tau1, tau2)

    if best is None:
        return None

    b0, b1, b2, b3 = best[1]

    return b0, b1, b2, b3, best[2], best[3]


def nss_zero(
    params: tuple[float, float, float, float, float, float], t: float
) -> float:
    """Continuously-compounded zero rate from a fitted Svensson parameter set at ``t``."""
    f = _nss_basis(t, params[4], params[5])

    return sum(params[i] * f[i] for i in range(4))


def smooth_forward_dfs(
    curve: list[dict], extend_years: float = 0.0
) -> list[tuple[float, float]]:
    """Dense discount-factor grid from a Svensson fit, weighted by trade count."""
    from math import exp, log

    nodes = sorted(
        (n["tenor_years"], n["discount_factor"], float(n["num_trades"]))
        for n in curve
        if n["discount_factor"] is not None and n["tenor_years"] > 0.0
    )
    raw = [(t, df) for t, df, _ in nodes]
    params = fit_nss(
        [(t, -log(df) / t) for t, df, _ in nodes], [w for _, _, w in nodes]
    )

    if params is None:
        return raw

    end = raw[-1][0] + max(extend_years, 0.0)
    times = [i / 12.0 for i in range(1, int(end * 12) + 1)]

    if not times or times[-1] < end - 1e-9:
        times.append(end)

    return [(t, exp(-nss_zero(params, t) * t)) for t in times]


def _local_trade_count(nodes: list[dict], start_years: float, end_years: float) -> int:
    """Trades behind the curve nodes actually spanning [start, end) years of tenor."""
    spanning = [n for n in nodes if start_years <= n["tenor_years"] < end_years]

    if spanning:
        return sum(n["num_trades"] for n in spanning)

    nearest = min(nodes, key=lambda n: abs(n["tenor_years"] - start_years))

    return nearest["num_trades"]


def forward_curve_grid(
    curve: list[dict],
    forward_tenor: float,
    step: float,
    basis: float,
    count: int | None = None,
    period_days: int | None = None,
) -> list[dict]:
    """Forward par rates off the smooth Svensson curve, at start dates ``step`` apart."""
    nodes = [n for n in curve if n["discount_factor"] is not None]
    observed = sorted(n["tenor_years"] for n in nodes)

    if not observed:
        return []

    last = observed[-1]
    dfs = smooth_forward_dfs(curve, extend_years=forward_tenor)
    points: list[dict] = []
    index = 0

    while index * step <= last + 1e-9 and (count is None or index < count):
        years = index * step
        index += 1
        points.append(
            {
                "tenor_years": years,
                "tenor_days": round(years * 365.0),
                "forward_rate": forward_par_rate(
                    dfs, years, forward_tenor, basis, period_days
                ),
                "forward_extrapolated": years + forward_tenor > last + 1e-9,
                "num_trades": _local_trade_count(nodes, years, years + forward_tenor),
            }
        )

    return points


def _par_rate_at(
    dfs: list[tuple[float, float]],
    tenor_days: int,
    basis: float,
    period_days: int | None,
    interpolation: str,
) -> float:
    """Spot-starting par swap rate at a tenor, read off a discount-factor curve."""
    from openbb_cftc.utils.constants import ZERO_RATE_BASIS

    annuity = 0.0
    previous = 0

    for offset in _payment_offsets(tenor_days, period_days):
        tau = (offset - previous) / basis
        annuity += tau * _interpolate_log_df(
            dfs, offset / ZERO_RATE_BASIS, interpolation
        )
        previous = offset

    df_end = _interpolate_log_df(dfs, tenor_days / ZERO_RATE_BASIS, interpolation)

    return (1.0 - df_end) / annuity


def _reprice_off_pillars(
    nodes: list[dict],
    pillars: list[dict],
    basis: float,
    period_days: int | None,
    interpolation: str,
) -> list[dict]:
    """Reprice observed nodes off the smooth curve fitted to the benchmark pillars."""
    from openbb_cftc.utils.constants import ZERO_RATE_BASIS

    dfs = sorted(
        (n["tenor_years"], n["discount_factor"])
        for n in pillars
        if n["discount_factor"] is not None
    )
    repriced: list[dict] = []

    for node in nodes:
        result = dict(node)
        result.pop("day_count_basis", None)
        result.pop("payment_period_days", None)
        years = node["tenor_days"] / ZERO_RATE_BASIS
        df = _interpolate_log_df(dfs, years, interpolation)
        result.update(
            par_rate=_par_rate_at(
                dfs, node["tenor_days"], basis, period_days, interpolation
            ),
            discount_factor=df,
            zero_rate=(1.0 / df) ** (1.0 / years) - 1.0,
        )
        repriced.append(result)

    return repriced


def _curve_day_count_default(currency: str) -> str:
    """Return the fallback day-count code for a currency's curve nodes."""
    from openbb_cftc.utils.constants import FIXED_FLOAT_CURVE_SPECS, OIS_INDICES

    ccy = (currency or "").strip().upper()

    return (
        OIS_INDICES.get(ccy, {}).get("day_count")
        or FIXED_FLOAT_CURVE_SPECS.get(ccy, {}).get("day_count")
        or "A004"
    )


def _overnight_node(rate: float, currency: str) -> dict:
    """Return a 1-day curve node anchored to the currency's published overnight fixing."""
    from openbb_cftc.utils.constants import FIXED_FLOAT_CURVE_SPECS, OIS_INDICES
    from openbb_cftc.utils.fixings import FIXING_BASES

    ccy = currency.upper()
    index = (
        OIS_INDICES.get(ccy, {}).get("index")
        or FIXED_FLOAT_CURVE_SPECS.get(ccy, {}).get("overnight_index")
        or ""
    )
    basis = FIXING_BASES.get(index, 360.0)
    day_count = {360.0: "ACT/360", 365.0: "ACT/365F", 252.0: "BUS/252"}.get(basis)

    return {
        "tenor": "1D",
        "tenor_days": 1,
        "tenor_years": round(1 / 365.0, 6),
        "par_rate": rate,
        "num_trades": 0,
        "total_notional": None,
        "min_rate": rate,
        "max_rate": rate,
        "is_capped": False,
        "day_count": day_count,
        "day_count_basis": basis,
        "payment_period_days": 1,
    }


def build_curve(
    records: Iterable[dict],
    trade_date: dateType,
    fisn: str,
    *,
    currency: str = "USD",
    granularity: str = "benchmark",
    aggregation: str = "median",
    min_trades: int = 1,
    interpolation: str = "log_linear",
    cleared_only: bool = False,
    use_cache: bool = True,
    overnight_rate: float | None = None,
    overnight_date: dateType | None = None,
) -> list[dict]:
    """Build a bootstrapped swap curve from one report date's slice records."""
    from datetime import timedelta

    from openbb_core.provider.utils.errors import EmptyDataError

    from openbb_cftc.utils import store
    from openbb_cftc.utils.constants import day_count_basis

    cache_key = None

    if use_cache and _is_closed_date(trade_date):
        cache_key = _curve_cache_key(
            fisn=fisn,
            currency=currency,
            trade_date=trade_date.isoformat(),
            granularity=granularity,
            aggregation=aggregation,
            min_trades=min_trades,
            interpolation=interpolation,
            cleared_only=cleared_only,
            overnight_rate=overnight_rate,
            overnight_date=overnight_date.isoformat() if overnight_date else None,
        )
        cached = store.get_curve(cache_key)

        if cached is not None:
            return _decode_curve_dates(cached)

    observations = trim_observations(
        extract_observations(
            records,
            trade_date=trade_date,
            fisn=fisn,
            currency=currency,
            spot_only=True,
            cleared_only=cleared_only,
        )
    )

    if not observations:
        raise EmptyDataError(
            f"No priceable {currency} trades matching '{fisn}' were found for {trade_date}."
        )

    day_count = _curve_day_count_default(currency)
    nodes = build_nodes(
        observations,
        granularity=granularity,
        aggregation=aggregation,
        min_trades=min_trades,
        day_count_default=day_count,
    )

    if not nodes:
        raise EmptyDataError(
            f"No curve nodes survived the filters for {trade_date}."
            + f" Try lowering min_trades (currently {min_trades})."
        )

    anchored = overnight_rate is not None and all(n["tenor_days"] > 1 for n in nodes)

    if anchored:
        nodes.insert(0, _overnight_node(overnight_rate, currency))

    basis = day_count_basis(day_count, "A004")
    period = _curve_period(observations)

    if granularity == "observed":
        pillar_nodes = build_nodes(
            observations,
            aggregation=aggregation,
            min_trades=min_trades,
            day_count_default=day_count,
        )

        if anchored:
            pillar_nodes.insert(0, _overnight_node(overnight_rate, currency))

        pillars = bootstrap(pillar_nodes, interpolation)
        curve = _reprice_off_pillars(nodes, pillars, basis, period, interpolation)
    else:
        curve = bootstrap(nodes, interpolation)

    for node in curve:
        node["date"] = trade_date
        node["as_of_date"] = trade_date
        node["staleness_days"] = 0
        node["maturity_date"] = trade_date + timedelta(days=node["tenor_days"])

        if anchored and node["tenor"] == "1D" and overnight_date is not None:
            node["as_of_date"] = overnight_date
            node["staleness_days"] = max(0, (trade_date - overnight_date).days)

    if cache_key is not None:
        store.put_curve(cache_key, trade_date.isoformat(), _encode_curve_dates(curve))

    return curve


def curve_day_count_basis(
    records: Iterable[dict],
    currency: str,
    trade_date: dateType,
    min_trades: int = 1,
) -> float:
    """Fixed-leg accrual basis a currency's rate curve is bootstrapped on."""
    from collections import Counter

    from openbb_cftc.utils.constants import (
        OIS_INDICES,
        currency_basis,
        day_count_basis,
        rate_curve_fisns,
    )

    default_code = OIS_INDICES.get(currency.upper(), {}).get("day_count", "A004")

    for fisn in rate_curve_fisns(currency):
        observations = extract_observations(
            records, trade_date=trade_date, fisn=fisn, currency=currency
        )

        if len(observations) < min_trades:
            continue

        codes = Counter(o["day_count"] for o in observations if o.get("day_count"))
        code = codes.most_common(1)[0][0] if codes else default_code

        return day_count_basis(code, default_code)

    return currency_basis(currency)


def _curve_period(observations: list[dict]) -> int:
    """Most-common reported fixed-leg coupon period among observations, annual by default."""
    from collections import Counter

    from openbb_cftc.utils.constants import OIS_PAYMENT_PERIOD_DAYS

    periods = Counter(
        o["payment_period"] for o in observations if o.get("payment_period")
    )

    return periods.most_common(1)[0][0] if periods else OIS_PAYMENT_PERIOD_DAYS


def curve_payment_period(
    records: Iterable[dict],
    currency: str,
    trade_date: dateType,
    min_trades: int = 1,
) -> int:
    """Fixed-leg coupon period a currency's rate curve is bootstrapped on, annual by default."""
    from openbb_cftc.utils.constants import OIS_PAYMENT_PERIOD_DAYS, rate_curve_fisns

    for fisn in rate_curve_fisns(currency):
        observations = extract_observations(
            records, trade_date=trade_date, fisn=fisn, currency=currency
        )

        if len(observations) < min_trades:
            continue

        return _curve_period(observations)

    return OIS_PAYMENT_PERIOD_DAYS


def build_curve_as_of(
    records: Iterable[dict],
    fisn: str,
    *,
    currency: str = "USD",
    granularity: str = "benchmark",
    aggregation: str = "median",
    min_trades: int = 1,
    interpolation: str = "log_linear",
    cleared_only: bool = False,
    max_staleness_days: int | None = None,
    overnight_rate: float | None = None,
    overnight_date: dateType | None = None,
) -> list[dict]:
    """Build a bootstrapped swap curve whose nodes are each dated to their own day."""
    from datetime import timedelta

    from openbb_core.provider.utils.errors import EmptyDataError

    from openbb_cftc.utils.constants import day_count_basis

    def _usable(nodes: list[dict]) -> list[dict]:
        live = [n for n in nodes if n["tenor_days"] > n["staleness_days"]]
        if max_staleness_days is None:
            return live
        return [n for n in live if n["staleness_days"] <= max_staleness_days]

    observations = trim_observations(
        extract_observations_by_day(
            records,
            fisn=fisn,
            currency=currency,
            spot_only=True,
            cleared_only=cleared_only,
        )
    )

    if not observations:
        raise EmptyDataError(
            f"No priceable {currency} trades matching '{fisn}' were disseminated in the"
            + " search window."
        )

    day_count = _curve_day_count_default(currency)
    nodes = build_nodes_as_of(
        observations,
        granularity=granularity,
        aggregation=aggregation,
        min_trades=min_trades,
        day_count_default=day_count,
    )

    if not nodes:
        raise EmptyDataError(
            "No curve node had a single day clearing"
            + f" min_trades (currently {min_trades})."
            + " Lower min_trades, or widen lookback_days."
        )

    nodes = _usable(nodes)
    anchored = (
        overnight_rate is not None
        and bool(nodes)
        and all(n["tenor_days"] > 1 for n in nodes)
    )
    anchor: dict | None = None

    if anchored:
        reference = max(n["as_of_date"] for n in nodes)
        anchor = _overnight_node(overnight_rate, currency)
        anchor["as_of_date"] = overnight_date or reference
        anchor["staleness_days"] = max(0, (reference - anchor["as_of_date"]).days)
        nodes.insert(0, anchor)

    basis = day_count_basis(day_count, "A004")
    period = _curve_period(observations)

    if granularity == "observed":
        pillar_nodes = _usable(
            build_nodes_as_of(
                observations,
                aggregation=aggregation,
                min_trades=min_trades,
                day_count_default=day_count,
            )
        )

        if anchor is not None:
            pillar_nodes.insert(0, dict(anchor))

        pillars = bootstrap(pillar_nodes, interpolation)
        curve = _reprice_off_pillars(nodes, pillars, basis, period, interpolation)
    else:
        curve = bootstrap(nodes, interpolation)

    curve_date = max(node["as_of_date"] for node in curve)

    for node in curve:
        node["date"] = curve_date
        node["maturity_date"] = node["as_of_date"] + timedelta(days=node["tenor_days"])

    return curve
