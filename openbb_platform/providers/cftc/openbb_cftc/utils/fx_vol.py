"""FX option implied-volatility analytics from DTCC PPD records."""

from collections.abc import Callable, Iterable
from datetime import date as dateType

from openbb_cftc.utils.fx_theory import implied_vol

_STRIKE_OFFSETS = (
    -1000,
    -500,
    -250,
    -150,
    -100,
    -50,
    -25,
    0,
    25,
    50,
    100,
    150,
    250,
    500,
    1000,
)
_STRIKE_MAX_OFFSET = 1250.0

_MONEYNESS_OFFSETS = (
    -1500,
    -1000,
    -750,
    -500,
    -300,
    -200,
    -100,
    -50,
    0,
    50,
    100,
    200,
    300,
    500,
    750,
    1000,
    1500,
)
_MONEYNESS_MAX_OFFSET = 1750.0

_VOL_TRIM_MIN = 0.5
_VOL_TRIM_MAX = 2.0

FORWARD_MIN_DAYS = 2
NEAR_MAX_DAYS = 9


def resolve_major_pair(pair: str) -> tuple[str, str, float]:
    """Return a major pair's, or raise for an unsupported one."""
    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_cftc.utils.constants import MAJOR_FX_PAIRS

    key = (pair or "").strip().upper()

    if key not in MAJOR_FX_PAIRS:
        raise OpenBBError(
            f"Invalid pair: '{pair}'. Valid pairs are: " + ", ".join(MAJOR_FX_PAIRS)
        )

    spec = MAJOR_FX_PAIRS[key]

    return spec["base"], spec["quote"], spec["pip"]


def is_ndf_vol_pair(pair: str) -> bool:
    """Whether a vol pair is non-deliverable, priced from NDF forwards and NDO options."""
    from openbb_cftc.utils.constants import MAJOR_FX_PAIRS

    return bool(MAJOR_FX_PAIRS.get((pair or "").strip().upper(), {}).get("ndf"))


def _pair_matches(fisn: str, base: str, quote: str) -> bool:
    """Whether a FISN names both legs of the pair, in either order."""
    parts = fisn.split()

    return base in parts and quote in parts


def has_vanilla_options(
    records: Iterable[dict], base: str, quote: str, family: str = "NA/O Van "
) -> bool:
    """Whether any record is an option of the family naming both legs of the pair."""
    return any(
        (r.get("UPI FISN") or "").startswith(family)
        and _pair_matches(r.get("UPI FISN") or "", base, quote)
        for r in records
    )


def ois_discount_factor(
    records: Iterable[dict],
    currency: str,
    trade_date: dateType,
    min_trades: int = 3,
    forward_aware: bool = False,
) -> Callable[[float], float]:
    """Return a callable mapping a year-fraction to a currency's OIS discount factor."""
    from openbb_cftc.utils.constants import ois_fisn

    return _discount_factor(
        records, ois_fisn(currency), currency, trade_date, min_trades, forward_aware
    )


def rate_discount_factor(
    records: Iterable[dict],
    currency: str,
    trade_date: dateType,
    min_trades: int = 3,
    forward_aware: bool = False,
) -> Callable[[float], float]:
    """Discount factor from a currency's rate curve, deepest swap family first."""
    from openbb_core.provider.utils.errors import EmptyDataError

    from openbb_cftc.utils.constants import rate_curve_fisns

    for fisn in rate_curve_fisns(currency):
        try:
            return _discount_factor(
                records, fisn, currency, trade_date, min_trades, forward_aware
            )
        except EmptyDataError:
            continue

    raise EmptyDataError(f"No rate curve could be built for {currency}.")


def _forward_fill(
    nodes: list[tuple[float, float]],
    records: Iterable[dict],
    fisn: str,
    currency: str,
    trade_date: dateType,
) -> list[tuple[float, float]]:
    """Extend spot DF nodes with single-payment forward-starting swaps of the same family."""
    from collections import defaultdict
    from statistics import median

    from openbb_cftc.utils.constants import SINGLE_PAYMENT_MAX_DAYS, currency_basis
    from openbb_cftc.utils.curve import _interpolate_log_df
    from openbb_cftc.utils.policy import extract_forward_observations

    observations = [
        observation
        for observation in extract_forward_observations(
            records, fisn, currency, trade_date
        )
        if observation["tenor_days"] <= SINGLE_PAYMENT_MAX_DAYS
    ]

    if not observations:
        return nodes

    groups: dict[tuple[int, int], dict[dateType, list[dict]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for observation in observations:
        key = (
            round(observation["forward_days"] / 30.0),
            round(observation["tenor_days"] / 30.0),
        )
        groups[key][observation["as_of_date"]].append(observation)

    basis = currency_basis(currency)
    forwards: list[tuple[dateType, dateType, float]] = []

    for by_day in groups.values():
        members = by_day[max(by_day)]
        representative = sorted(members, key=lambda m: m["effective_date"])[
            len(members) // 2
        ]
        forwards.append(
            (
                representative["effective_date"],
                representative["expiration_date"],
                median(member["rate"] for member in members),
            )
        )

    enriched = list(nodes)

    for effective, expiration, rate in sorted(forwards, key=lambda f: f[1]):
        start_years = (effective - trade_date).days / 365.0
        end_years = (expiration - trade_date).days / 365.0
        denominator = 1.0 + rate * (expiration - effective).days / basis

        if denominator <= 0 or any(
            abs(years - end_years) < 0.04 for years, _ in enriched
        ):
            continue

        df_end = _interpolate_log_df(enriched, start_years) / denominator
        enriched.append((end_years, df_end))
        enriched.sort()

    return enriched


def _discount_factor(
    records: Iterable[dict],
    fisn: str,
    currency: str,
    trade_date: dateType,
    min_trades: int,
    forward_aware: bool = False,
) -> Callable[[float], float]:
    """Bootstrap a currency's curve from one swap family and interpolate its DF by tenor."""
    from openbb_cftc.utils.curve import _interpolate_log_df, build_curve

    curve = build_curve(
        records,
        trade_date=trade_date,
        fisn=fisn,
        currency=currency,
        min_trades=min_trades,
    )
    nodes = sorted(
        (n["tenor_years"], n["discount_factor"])
        for n in curve
        if n["discount_factor"] is not None
    )

    if forward_aware:
        nodes = _forward_fill(nodes, records, fisn, currency, trade_date)

    def lookup(years: float) -> float:
        return _interpolate_log_df(nodes, years)

    return lookup


def _deliverable_spot(
    records: Iterable[dict], base: str, quote: str, as_of: dateType
) -> float | None:
    """Median quote-per-base from the pair's own shortest-dated deliverable forwards."""
    from statistics import median

    from openbb_cftc.utils.curve import parse_date, parse_notional

    rates = []

    for record in records:
        fisn = (record.get("UPI FISN") or "").strip()
        parts = fisn.split()

        if (
            len(parts) != 3
            or parts[0] not in ("NA/Fwd", "NA/Swaps")
            or {parts[1], parts[2]} != {base, quote}
        ):
            continue

        if (record.get("Action type") or "").strip() != "NEWT":
            continue

        effective = parse_date(record.get("Effective Date"))
        first, _ = parse_notional(record.get("Notional amount-Leg 1"))
        second, _ = parse_notional(record.get("Notional amount-Leg 2"))
        ccy1 = (record.get("Notional currency-Leg 1") or "").strip()
        ccy2 = (record.get("Notional currency-Leg 2") or "").strip()

        if not (effective and first and second) or (effective - as_of).days > 2:
            continue

        if ccy1 == base and ccy2 == quote:
            rates.append(second / first)
        elif ccy2 == base and ccy1 == quote:
            rates.append(first / second)

    return median(rates) if rates else None


def fx_spot(
    records: Iterable[dict], base: str, quote: str, as_of: dateType
) -> float | None:
    """Spot in quote per base from deliverable forwards."""
    direct = _deliverable_spot(records, base, quote, as_of)

    if direct is not None or base == "USD" or quote == "USD":
        return direct

    usd_per_base = _deliverable_spot(records, base, "USD", as_of)
    usd_per_quote = _deliverable_spot(records, quote, "USD", as_of)

    if usd_per_base is None or usd_per_quote is None:
        return None

    return usd_per_base / usd_per_quote


def ndf_forward_curve(
    records: Iterable[dict],
    pair: str,
    as_of: dateType,
    min_notional: float = 0.0,
) -> tuple[float | None, Callable[[float], float] | None]:
    """Spot and a year-fraction forward interpolator from a pair's non-deliverable forwards."""
    from openbb_cftc.utils.fx import extract_fx_observations

    return observation_curve(
        extract_fx_observations(
            records, pair=pair, trade_date=as_of, min_notional=min_notional
        )
    )


def _interpolator(
    days: list[int], nodes: list[tuple[int, float]]
) -> Callable[[float], float]:
    """Year-fraction forward interpolator over tenor nodes, flat beyond the ends."""
    from bisect import bisect_right

    def forward(years: float) -> float:
        target = years * 365.0

        if target <= days[0]:
            return nodes[0][1]

        if target >= days[-1]:
            return nodes[-1][1]

        upper = bisect_right(days, target)
        day_low, rate_low = nodes[upper - 1]
        day_high, rate_high = nodes[upper]
        weight = (target - day_low) / (day_high - day_low)

        return rate_low + weight * (rate_high - rate_low)

    return forward


def _spot(pool: list[float], nodes: list[tuple[int, float]]) -> float:
    """Median of the near-tenor rates, or the shortest node's rate when there are none."""
    from statistics import median

    return median(pool) if pool else nodes[0][1]


class ObservationCurve:
    """Spot and forward curve of a pair's observations, able to leave one print out."""

    def __init__(self, observations: list[dict]):
        from statistics import median

        self._where: dict[str, tuple[int, float] | None] = {}
        self._near: list[float] = []
        self._pool: list[float] = []
        self._by_day: dict[int, list[float]] = {}

        for observation in observations:
            days, rate = observation["days"], observation["rate"]
            identifier = observation["dissemination_identifier"]

            if identifier:
                self._where[identifier] = (
                    None if identifier in self._where else (days, rate)
                )

            if days <= NEAR_MAX_DAYS:
                self._near.append(rate)

            if days > FORWARD_MIN_DAYS:
                self._by_day.setdefault(days, []).append(rate)

                if days <= NEAR_MAX_DAYS:
                    self._pool.append(rate)

        self._near.sort()
        self._pool.sort()

        for rates in self._by_day.values():
            rates.sort()

        self._nodes = [
            (days, median(rates)) for days, rates in sorted(self._by_day.items())
        ]
        self._days = [node[0] for node in self._nodes]
        self._curve: tuple[float | None, Callable[[float], float] | None, int] = (
            (
                _spot(self._pool, self._nodes),
                _interpolator(self._days, self._nodes),
                len(self._nodes),
            )
            if self._nodes
            else (None, None, 0)
        )

    def __contains__(self, identifier: str) -> bool:
        """Whether an identifier names exactly one of the observations."""
        return self._where.get(identifier) is not None

    def curve(
        self, without: str = ""
    ) -> tuple[float | None, Callable[[float], float] | None, int]:
        """Spot, forward interpolator and node count, leaving out one print when given."""
        from bisect import bisect_left
        from statistics import median

        entry = self._where.get(without)

        if entry is None or entry[0] <= FORWARD_MIN_DAYS:
            return self._curve

        days, rate = entry
        rates = self._by_day[days]
        position = bisect_left(rates, rate)
        peers = rates[:position] + rates[position + 1 :]
        index = bisect_left(self._days, days)
        nodes = list(self._nodes)
        node_days = self._days

        if peers:
            nodes[index] = (days, median(peers))
        else:
            del nodes[index]
            node_days = node_days[:index] + node_days[index + 1 :]

        if not nodes:
            return None, None, 0

        pool = self._pool

        if days <= NEAR_MAX_DAYS:
            position = bisect_left(pool, rate)
            pool = pool[:position] + pool[position + 1 :]

        spot = self._curve[0] if pool is self._pool and pool else _spot(pool, nodes)

        return spot, _interpolator(node_days, nodes), len(nodes)

    def near_rates(self, without: str = "") -> list[float]:
        """Sorted rates of the near-tenor observations, leaving out one print when given."""
        from bisect import bisect_left

        entry = self._where.get(without)

        if entry is None or entry[0] > NEAR_MAX_DAYS:
            return list(self._near)

        position = bisect_left(self._near, entry[1])

        return self._near[:position] + self._near[position + 1 :]


def observation_curve(
    observations: list[dict],
) -> tuple[float | None, Callable[[float], float] | None]:
    """Spot and a year-fraction forward interpolator from a pair's forward observations."""
    spot, forward, _ = ObservationCurve(observations).curve()

    return spot, forward


def implied_df(
    df_base: Callable[[float], float],
    spot: float,
    forward: Callable[[float], float],
) -> Callable[[float], float]:
    """Domestic discount factor implied by the base DF and the observed forward curve."""

    def lookup(years: float) -> float:
        return df_base(years) * spot / forward(years)

    return lookup


def _option_is_call(call_ccy: str, put_ccy: str, base: str, quote: str) -> bool | None:
    """Whether the option is a call on the base, from the currency bought and sold."""
    if call_ccy == base or put_ccy == quote:
        return True

    if put_ccy == base or call_ccy == quote:
        return False

    return None


def extract_vanilla_options(
    records: Iterable[dict],
    base: str,
    quote: str,
    as_of: dateType,
    spot: float,
    family: str = "NA/O Van ",
) -> list[dict]:
    """Reduce a pair's options of the family to."""
    from math import log

    from openbb_cftc.utils.curve import parse_date, parse_notional

    options: list[dict] = []

    for record in records:
        fisn = (record.get("UPI FISN") or "").strip()

        if not fisn.startswith(family):
            continue

        if not _pair_matches(fisn, base, quote):
            continue

        if (record.get("Action type") or "").strip() != "NEWT":
            continue

        if (record.get("Event type") or "").strip() != "TRAD":
            continue

        if (record.get("Execution Timestamp") or "")[:10] != as_of.isoformat():
            continue

        strike, _ = parse_notional(record.get("Strike Price"))

        if not strike:
            strike, _ = parse_notional(record.get("Exchange rate"))

        premium, _ = parse_notional(record.get("Option Premium Amount"))
        premium_ccy = (record.get("Option Premium Currency") or "").strip()
        expiration = parse_date(record.get("Expiration Date"))
        call_ccy = (record.get("Call currency") or "").strip()
        put_ccy = (record.get("Put currency") or "").strip()
        call_amount, _ = parse_notional(record.get("Call amount"))
        put_amount, _ = parse_notional(record.get("Put amount"))
        is_call = _option_is_call(call_ccy, put_ccy, base, quote)

        if call_ccy == base:
            base_notional = call_amount
        elif put_ccy == base:
            base_notional = put_amount
        else:
            first, _ = parse_notional(record.get("Notional amount-Leg 1"))
            second, _ = parse_notional(record.get("Notional amount-Leg 2"))
            ccy1 = (record.get("Notional currency-Leg 1") or "").strip()
            base_notional = first if ccy1 == base else second

        if not (strike and premium and expiration and base_notional) or is_call is None:
            continue

        if abs(log((1.0 / strike) / spot)) < abs(log(strike / spot)):
            strike = 1.0 / strike

        tenor_days = (expiration - as_of).days

        if tenor_days <= 0:
            continue

        per_unit = premium / base_notional

        if premium_ccy == base:
            per_unit *= spot
        elif premium_ccy != quote:
            continue

        options.append(
            {
                "tenor_days": tenor_days,
                "strike": strike,
                "premium": per_unit,
                "is_call": is_call,
            }
        )

    return options


def price_options(
    options: list[dict],
    spot: float,
    df_quote: Callable[[float], float],
    df_base: Callable[[float], float],
) -> list[dict]:
    """Attach an implied volatility to each out-of-the-money priceable option."""
    from math import log

    priced: list[dict] = []

    for option in options:
        years = option["tenor_days"] / 365.0
        disc_quote = df_quote(years)
        disc_base = df_base(years)
        r_dom = -log(disc_quote) / years
        r_for = -log(disc_base) / years
        forward = spot * disc_base / disc_quote
        strike = option["strike"]

        if (option["is_call"] and strike < forward) or (
            not option["is_call"] and strike > forward
        ):
            continue

        vol = implied_vol(
            option["premium"], spot, strike, years, r_dom, r_for, option["is_call"]
        )

        if vol is None:
            continue

        priced.append({**option, "implied_vol": vol})

    return priced


def _tenor_of(days: int) -> str | None:
    """Label an option's tenor by the FX bucket it falls in."""
    from openbb_cftc.utils.constants import FX_TENOR_BUCKETS

    for label, low, high in FX_TENOR_BUCKETS:
        if label != "SPOT" and low <= days <= high:
            return label

    return None


def _price_decimals(pip: float) -> int:
    """Decimal places to round a strike price to, one past the pip."""
    return len(str(int(pip)))


def _snap_offset(pips: float) -> int | None:
    """Snap a strike's distance from spot, in points, to the nearest grid offset, or None."""
    if abs(pips) > _STRIKE_MAX_OFFSET:
        return None

    return min(_STRIKE_OFFSETS, key=lambda offset: abs(offset - pips))


def _snap_moneyness(bp: float) -> int | None:
    """Snap a strike's distance from spot, in basis points, to the nearest grid offset."""
    if abs(bp) > _MONEYNESS_MAX_OFFSET:
        return None

    return min(_MONEYNESS_OFFSETS, key=lambda offset: abs(offset - bp))


def _grid_offsets(moneyness: bool) -> tuple[int, ...]:
    """Strike-grid offsets for the pair: basis points of spot, or pips."""
    return _MONEYNESS_OFFSETS if moneyness else _STRIKE_OFFSETS


def _snap_strike(strike: float, spot: float, pip: float, moneyness: bool) -> int | None:
    """Snap a strike to its grid offset, in basis points of spot or in pips."""
    if moneyness:
        return _snap_moneyness((strike / spot - 1.0) * 10_000.0)

    return _snap_offset((strike - spot) * pip)


def _offset_strike(offset: int, spot: float, pip: float, moneyness: bool) -> float:
    """Strike price at a grid offset, read as basis points of spot or as pips."""
    if moneyness:
        return spot * (1.0 + offset / 10_000.0)

    return spot + offset / pip


def _tenor_column(label: str) -> str:
    """Column key for an expiry's vols on the surface."""
    return f"vol_{label.lower()}"


def vol_surface(
    priced: list[dict], spot: float, pip: float, moneyness: bool = False
) -> list[dict]:
    """Empirical vol surface: median vol per."""
    from collections import defaultdict
    from statistics import median

    from openbb_cftc.utils.constants import FX_TENOR_BUCKETS

    tenors = [label for label, _, _ in FX_TENOR_BUCKETS if label != "SPOT"]
    decimals = _price_decimals(pip)
    by_tenor: dict[str, list[tuple[int, float]]] = defaultdict(list)

    for option in priced:
        tenor = _tenor_of(option["tenor_days"])
        offset = _snap_strike(option["strike"], spot, pip, moneyness)

        if tenor is None or offset is None:
            continue

        by_tenor[tenor].append((offset, option["implied_vol"]))

    cells: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for tenor, points in by_tenor.items():
        ref = median([vol for _, vol in points])
        low, high = _VOL_TRIM_MIN * ref, _VOL_TRIM_MAX * ref

        for offset, vol in points:
            if low <= vol <= high:
                cells[offset][tenor].append(vol)

    rows: list[dict] = []

    for offset in sorted(cells):
        row: dict = {
            "strike": round(_offset_strike(offset, spot, pip, moneyness), decimals),
            "strike_offset": float(offset),
        }
        num_options = 0

        for tenor in tenors:
            vols = cells[offset].get(tenor)
            row[_tenor_column(tenor)] = median(vols) if vols else None
            num_options += len(vols) if vols else 0

        row["num_options"] = num_options
        rows.append(row)

    return rows


def theoretical_surface(
    priced: list[dict],
    spot: float,
    df_quote: Callable[[float], float],
    df_base: Callable[[float], float],
    pip: float,
    moneyness: bool = False,
) -> tuple[list[dict], dict[str, dict]]:
    """SABR-fitted vol surface on the strike grid."""
    from collections import defaultdict
    from statistics import median

    from openbb_cftc.utils.constants import FX_TENOR_BUCKETS
    from openbb_cftc.utils.fx_theory import calibrate_sabr, sabr_vol

    tenors = [label for label, _, _ in FX_TENOR_BUCKETS if label != "SPOT"]
    decimals = _price_decimals(pip)
    by_tenor: dict[str, list[dict]] = defaultdict(list)

    for option in priced:
        tenor = _tenor_of(option["tenor_days"])

        if tenor is not None:
            by_tenor[tenor].append(option)

    fits: dict[str, dict] = {}

    for tenor, options in by_tenor.items():
        years = median([o["tenor_days"] for o in options]) / 365.0
        forward = spot * df_base(years) / df_quote(years)
        ref = median([o["implied_vol"] for o in options])
        low, high = _VOL_TRIM_MIN * ref, _VOL_TRIM_MAX * ref
        pts = [
            (o["strike"], o["implied_vol"])
            for o in options
            if low <= o["implied_vol"] <= high
        ]
        near = [v for strike, v in pts if abs(strike / forward - 1.0) < 0.015]
        fit = calibrate_sabr(forward, years, median(near) if near else ref, pts)

        if fit is not None:
            alpha, rho, nu = fit
            fits[tenor] = {
                "forward": forward,
                "years": years,
                "alpha": alpha,
                "rho": rho,
                "nu": nu,
            }

    rows: list[dict] = []

    for offset in _grid_offsets(moneyness):
        strike = _offset_strike(offset, spot, pip, moneyness)
        row: dict = {
            "strike": round(strike, decimals),
            "strike_offset": float(offset),
        }
        num_fits = 0

        for tenor in tenors:
            fit = fits.get(tenor)

            if fit is None:
                row[_tenor_column(tenor)] = None
                continue

            row[_tenor_column(tenor)] = sabr_vol(
                fit["forward"],
                strike,
                fit["years"],
                fit["alpha"],
                fit["rho"],
                fit["nu"],
            )
            num_fits += 1

        row["num_options"] = num_fits
        rows.append(row)

    return rows, fits
