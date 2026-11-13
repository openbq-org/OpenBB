"""FX forward and option valuation from DTCC PPD forex prints."""

from collections.abc import Callable, Iterable
from datetime import date as dateType

from openbb_cftc.utils.dtcc import qualified_keys

PRICEABLE_FORWARDS = frozenset({"Forward", "Non-Deliverable Forward"})
OPTION_FAMILIES = frozenset({"Van", "NDO"})
OPTION_FISN = {"Van": "NA/O Van ", "NDO": "NA/O NDO "}
DAYS_PER_YEAR = 365.0
MIN_FORWARD_NODES = 2
CURVE_MIN_NOTIONAL = 1_000.0
RATE_BAND = (0.5, 2.0)
LIVE_ACTION = "NEWT"
LIVE_EVENT = "TRAD"
NOT_PROVIDED_BY_NOTATION = {
    "1": "99999.9999999999999",
    "3": "9.9999999999",
    "4": "99999",
}


def is_not_provided(value: str | None, notation: str | None) -> bool:
    """Whether a price or spread carries the all-nines default for its notation."""
    text = (value or "").strip()

    return bool(text) and text == NOT_PROVIDED_BY_NOTATION.get((notation or "").strip())


def is_package_leg(record: dict) -> bool:
    """Whether a print is a component of a package, whose level is the package's own."""
    return (record.get("Package indicator") or "").strip().upper() == "TRUE"


def is_standard_terms(record: dict) -> bool:
    """Whether a print's terms are standardized, so its rate is a market level."""
    return (
        record.get("Non-standardized term indicator") or ""
    ).strip().upper() != "TRUE"


def is_live_print(record: dict) -> bool:
    """Whether a print is a new trade rather than a lifecycle event."""
    return (record.get("Action type") or "").strip() == LIVE_ACTION and (
        record.get("Event type") or ""
    ).strip() == LIVE_EVENT


def oriented_rate(
    value: float, basis: str | None, base: str, quote: str
) -> float | None:
    """Convert a rate stated as unit/quoted currency into quote per base."""
    parts = (basis or "").strip().upper().split("/")

    if len(parts) != 2 or not value:
        return None

    unit, quoted = parts

    if unit == base and quoted == quote:
        return value

    if unit == quote and quoted == base:
        return 1.0 / value

    return None


def orient_to_spot(rate: float, spot: float) -> float:
    """Pick the rate or its reciprocal, whichever the pair's spot supports."""
    from math import log

    if rate <= 0.0 or spot <= 0.0:
        return rate

    return (
        rate if abs(log(rate / spot)) <= abs(log((1.0 / rate) / spot)) else 1.0 / rate
    )


def exchange_rate(record: dict, base: str, quote: str) -> float | None:
    """Traded rate in quote per base, from the stated Exchange rate and its basis."""
    from openbb_cftc.utils.curve import parse_notional
    from openbb_cftc.utils.fx import pair_rate

    rate, _ = parse_notional(record.get("Exchange rate"))
    stated = (
        oriented_rate(rate, record.get("Exchange rate basis"), base, quote)
        if rate
        else None
    )

    return stated if stated is not None else pair_rate(record, base, quote)


def pair_for(record: dict) -> tuple[str, str, str] | None:
    """Return base, quote and pair key of a print's legs, in the key's convention."""
    from openbb_cftc.utils.constants import FX_PAIRS

    legs = (record.get("UPI Underlier Name") or "").strip().upper().split()

    if len(legs) != 2:
        return None

    for key in (f"{legs[0]}{legs[1]}", f"{legs[1]}{legs[0]}"):
        if key in FX_PAIRS:
            return key[:3], key[3:], key

    return None


def classify_fx_trade(record: dict) -> str | None:
    """'forward' for forwards and FX swaps, 'option' for vanilla and non-deliverable options."""
    from openbb_cftc.utils.fx_forwards import forward_product

    fisn = (record.get("UPI FISN") or "").strip()

    if forward_product(fisn) in PRICEABLE_FORWARDS:
        return "forward"

    parts = fisn.split()

    if len(parts) >= 3 and parts[0] == "NA/O" and parts[1] in OPTION_FAMILIES:
        return "option"

    return None


def option_family(record: dict) -> str | None:
    """FISN prefix of the option family a print belongs to."""
    parts = (record.get("UPI FISN") or "").strip().split()

    if len(parts) < 3 or parts[0] != "NA/O":
        return None

    return OPTION_FISN.get(parts[1])


def extract_fx_trade(
    record: dict, curve_date: dateType, min_notional: float = 0.0
) -> dict | None:
    """Traded terms of an FX forward or option print, or None when they are unpriceable."""
    from openbb_cftc.utils.curve import parse_date, parse_notional
    from openbb_cftc.utils.fx import base_notional
    from openbb_cftc.utils.fx_forwards import forward_product
    from openbb_cftc.utils.fx_vol import _option_is_call

    family = classify_fx_trade(record)
    resolved = pair_for(record)

    if family is None or resolved is None or not is_live_print(record):
        return None

    if is_package_leg(record) or not is_standard_terms(record):
        return None

    base, quote, key = resolved
    expiry = parse_date(record.get("Expiration Date"))

    if expiry is None or (expiry - curve_date).days <= 0:
        return None

    notional = base_notional(record, base)

    if not notional or notional < min_notional:
        return None

    fisn = (record.get("UPI FISN") or "").strip()
    trade = {
        "dissemination_identifier": (
            record.get("Dissemination Identifier") or ""
        ).strip(),
        "trade_key": qualified_keys(record).get("Trade Key"),
        "trade_type": f"fx_{family}",
        "pair": key,
        "base": base,
        "quote": quote,
        "currency": quote,
        "notional": notional,
        "expiration_date": expiry,
        "effective_date": parse_date(record.get("Effective Date")),
        "days": (expiry - curve_date).days,
        "product": forward_product(fisn),
        "upi_fisn": fisn,
        "underlier": (record.get("UPI Underlier Name") or "").strip(),
        "cleared": (record.get("Cleared") or "").strip() or None,
    }

    if family == "forward":
        rate = exchange_rate(record, base, quote)

        if not rate:
            return None

        trade["traded_rate"] = rate

        return trade

    raw_strike, _ = parse_notional(record.get("Strike Price"))
    strike = (
        oriented_rate(
            raw_strike,
            record.get("Strike price currency/currency pair"),
            base,
            quote,
        )
        if raw_strike
        else None
    )

    if strike is None:
        strike = exchange_rate(record, base, quote)

    premium, _ = parse_notional(record.get("Option Premium Amount"))
    premium_ccy = (record.get("Option Premium Currency") or "").strip()
    is_call = _option_is_call(
        (record.get("Call currency") or "").strip(),
        (record.get("Put currency") or "").strip(),
        base,
        quote,
    )

    if not strike or not premium or is_call is None or premium_ccy not in (base, quote):
        return None

    trade["strike"] = strike
    trade["premium"] = premium
    trade["premium_currency"] = premium_ccy
    trade["is_call"] = is_call
    trade["option_family"] = option_family(record)

    return trade


def pair_records(fx_records: Iterable[dict], base: str, quote: str) -> list[dict]:
    """One pass reducing a day's prints to those whose FISN names both legs."""
    subset: list[dict] = []

    for record in fx_records:
        parts = (record.get("UPI FISN") or "").split()

        if base in parts and quote in parts:
            subset.append(record)

    return subset


def _pair_subset(fx_records: Iterable[dict], trade: dict, memo: dict) -> list[dict]:
    """Return the pair's own prints, extracted once per day and reused across trades."""
    key = f"fx-pair:{trade['base']}/{trade['quote']}"

    if key not in memo:
        memo[key] = pair_records(fx_records, trade["base"], trade["quote"])

    return memo[key]


def _discount_for(
    rates_records: Iterable[dict],
    currency: str,
    curve_date: dateType,
    min_trades: int,
    memo: dict,
) -> Callable[[float], float] | None:
    """Return the currency's discount function, built once per day, or None."""
    from openbb_core.provider.utils.errors import EmptyDataError

    from openbb_cftc.utils.fx_vol import rate_discount_factor

    key = f"fx-df:{currency}:{min_trades}"

    if key not in memo:
        try:
            memo[key] = rate_discount_factor(
                rates_records, currency, curve_date, min_trades
            )
        except EmptyDataError:
            memo[key] = None

    return memo[key]


def _pair_curve(
    fx_records: Iterable[dict], trade: dict, curve_date: dateType, memo: dict
) -> dict:
    """Return the pair's forward curve for the day, built once and shared by its prints."""
    from openbb_cftc.utils.fx import extract_fx_observations
    from openbb_cftc.utils.fx_vol import ndf_forward_curve

    key = f"fx-curve:{trade['pair']}:{curve_date.isoformat()}"

    if key not in memo:
        records = _pair_subset(fx_records, trade, memo)
        observations = extract_fx_observations(
            records,
            pair=trade["pair"],
            trade_date=curve_date,
            min_notional=CURVE_MIN_NOTIONAL,
        )
        spot, forward = ndf_forward_curve(
            records, trade["pair"], curve_date, min_notional=CURVE_MIN_NOTIONAL
        )
        memo[key] = {
            "nodes": len({o["days"] for o in observations if o["days"] > 2}),
            "near": [o["rate"] for o in observations if o["days"] <= 9],
            "spot": spot,
            "forward": forward,
        }

    return memo[key]


def _cip_market(
    near: list[float],
    rates_records: Iterable[dict],
    trade: dict,
    curve_date: dateType,
    min_trades: int,
    memo: dict,
) -> dict | None:
    """Both legs' curves and a covered-interest-parity forward, when prints are sparse."""
    from statistics import median

    if not near:
        return None

    spot = median(near)

    if spot <= 0.0:
        return None

    df_base = _discount_for(rates_records, trade["base"], curve_date, min_trades, memo)
    df_quote = _discount_for(
        rates_records, trade["quote"], curve_date, min_trades, memo
    )

    if df_base is None or df_quote is None:
        return None

    def forward(years: float, _s=spot, _b=df_base, _q=df_quote) -> float:
        return _s * _b(years) / _q(years)

    return {"spot": spot, "forward": forward, "df_base": df_base, "df_quote": df_quote}


def _curve_market(
    spot: float,
    forward: Callable[[float], float],
    rates_records: Iterable[dict],
    trade: dict,
    curve_date: dateType,
    min_trades: int,
    memo: dict,
) -> dict | None:
    """Both legs' discount curves around an observed forward curve."""
    from openbb_cftc.utils.fx_vol import implied_df

    df_base = _discount_for(rates_records, trade["base"], curve_date, min_trades, memo)

    if df_base is not None:
        df_quote = implied_df(df_base, spot, forward)
    else:
        df_quote = _discount_for(
            rates_records, trade["quote"], curve_date, min_trades, memo
        )

        if df_quote is None:
            return None

        def _base_df(years: float, _quote=df_quote) -> float:
            return _quote(years) * forward(years) / spot

        df_base = _base_df

    return {"spot": spot, "forward": forward, "df_base": df_base, "df_quote": df_quote}


def fx_market(
    fx_records: Iterable[dict],
    rates_records: Iterable[dict],
    trade: dict,
    curve_date: dateType,
    min_trades: int = 1,
    memo: dict | None = None,
) -> dict | None:
    """Spot, forward interpolator and both legs' discount curves for a pair, or None."""
    memo = {} if memo is None else memo
    key = f"fx-market:{trade['pair']}:{curve_date.isoformat()}:{min_trades}"

    if key in memo:
        return memo[key]

    curve = _pair_curve(fx_records, trade, curve_date, memo)
    spot, forward = curve["spot"], curve["forward"]

    if (
        curve["nodes"] < MIN_FORWARD_NODES
        or spot is None
        or forward is None
        or spot <= 0.0
    ):
        market = _cip_market(
            curve["near"], rates_records, trade, curve_date, min_trades, memo
        )
    else:
        market = _curve_market(
            spot, forward, rates_records, trade, curve_date, min_trades, memo
        )

    if market is not None:
        market["key"] = key

    memo[key] = market

    return market


def value_fx_forward(trade: dict, market: dict) -> dict:
    """Mark a forward to the pair's forward curve and discount to the curve date."""
    years = trade["days"] / DAYS_PER_YEAR
    market_rate = market["forward"](years)
    discount = market["df_quote"](years)
    npv = trade["notional"] * (market_rate - trade["traded_rate"]) * discount

    return {
        "market_rate": market_rate,
        "discount_factor": discount,
        "npv": npv,
        "spot": market["spot"],
        "years": years,
    }


def option_vol(
    fx_records: Iterable[dict],
    trade: dict,
    market: dict,
    curve_date: dateType,
    memo: dict | None = None,
) -> float | None:
    """Implied volatility for a trade's strike, from the day's prints of its own family."""
    from statistics import median

    from openbb_cftc.utils.fx_vol import extract_vanilla_options, price_options

    family = trade.get("option_family")

    if family is None:
        return None

    memo = {} if memo is None else memo
    key = f"fx-options:{market['key']}:{family}" if market.get("key") else None

    if key is not None and key in memo:
        priced = memo[key]
    else:
        options = extract_vanilla_options(
            _pair_subset(fx_records, trade, memo),
            trade["base"],
            trade["quote"],
            curve_date,
            market["spot"],
            family=family,
        )
        priced = price_options(
            options, market["spot"], market["df_quote"], market["df_base"]
        )

        if key is not None:
            memo[key] = priced

    if not priced:
        return None

    nearest = min(abs(o["tenor_days"] - trade["days"]) for o in priced)
    at_tenor = [o for o in priced if abs(o["tenor_days"] - trade["days"]) == nearest]

    return median(o["implied_vol"] for o in at_tenor)


def value_fx_option(trade: dict, market: dict, vol: float) -> dict:
    """Garman-Kohlhagen mark of a vanilla FX option against the premium paid."""
    from math import log

    from openbb_cftc.utils.fx_theory import garman_kohlhagen

    years = trade["days"] / DAYS_PER_YEAR
    disc_quote = market["df_quote"](years)
    disc_base = market["df_base"](years)
    rate_dom = -log(disc_quote) / years
    rate_for = -log(disc_base) / years
    per_unit = garman_kohlhagen(
        market["spot"],
        trade["strike"],
        years,
        rate_dom,
        rate_for,
        vol,
        trade["is_call"],
    )
    mark = per_unit * trade["notional"]
    premium = trade["premium"]

    if trade["premium_currency"] == trade["base"]:
        premium *= market["spot"]

    return {
        "market_rate": market["spot"] * disc_base / disc_quote,
        "discount_factor": disc_quote,
        "implied_vol": vol,
        "mark": mark,
        "premium": premium,
        "npv": mark - premium,
        "spot": market["spot"],
        "years": years,
    }


def value_fx_trade(
    record: dict,
    fx_records: Iterable[dict],
    rates_records: Iterable[dict],
    curve_date: dateType,
    min_notional: float = 0.0,
    min_trades: int = 1,
    memo: dict | None = None,
) -> dict | None:
    """Value an FX print end to end, or None when the day's prints cannot price it."""
    trade = extract_fx_trade(record, curve_date, min_notional)

    if trade is None:
        return None

    memo = {} if memo is None else memo
    market = fx_market(fx_records, rates_records, trade, curve_date, min_trades, memo)

    if market is None:
        return None

    from math import log

    from openbb_cftc.utils.fx import carry_bound

    spot = market["spot"]
    field = "traded_rate" if trade["trade_type"] == "fx_forward" else "strike"
    trade[field] = orient_to_spot(trade[field], spot)

    if abs(log(trade[field] / spot)) > carry_bound(trade["days"]):
        return None

    if trade["trade_type"] == "fx_forward":
        return {**trade, **value_fx_forward(trade, market)}

    vol = option_vol(fx_records, trade, market, curve_date, memo)

    if vol is None:
        return None

    return {**trade, **value_fx_option(trade, market, vol)}
