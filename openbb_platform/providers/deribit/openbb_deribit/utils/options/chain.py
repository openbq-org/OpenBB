"""Loading a Deribit option chain for analysis.

The chain endpoint subscribes to every contract over a websocket to collect the
greeks the exchange publishes, which takes about twelve seconds for BTC. The
analysis views need quotes, a volatility and the contract specification rather
than the exchange's own greeks, and all three are reachable over REST in under
a second, so this is where they are read from. The greeks are modelled from the
quoted volatility instead.
"""

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pandas import DataFrame

CHAIN_TTL = 120.0

_LOADED: dict = {}
_LOCKS: dict = {}

_SETTLEMENT = {"BTC": "BTC", "ETH": "ETH"}


def settlement_of(root: str) -> str:
    """Return the currency a root's options are collateralised in."""
    return _SETTLEMENT.get(root, "USDC")


async def _source(root: str) -> tuple:
    """Read the quotes, specifications, and index level of one underlying.

    The specification is what names a contract's strike, side, size, and
    settlement style, so it is read rather than parsed back out of the
    instrument name, which spells a fractional strike with a letter.
    """
    from openbb_deribit.utils.client import request
    from openbb_deribit.utils.helpers import get_instruments

    currency = settlement_of(root)
    summary, instruments = await asyncio.gather(
        request(
            "get_book_summary_by_currency", {"currency": currency, "kind": "option"}
        ),
        get_instruments(currency, "option"),
    )
    specs = {
        str(spec["instrument_name"]): spec
        for spec in instruments
        if str(spec["instrument_name"]).split("-")[0] == root
    }
    quotes = [row for row in summary if str(row["instrument_name"]) in specs]
    index = next(iter(specs.values()), {}).get("price_index")
    level = await request("get_index_price", {"index_name": index}) if index else {}

    return quotes, specs, float((level or {}).get("index_price") or 0)


def _rows(quotes: list, specs: dict, spot: float) -> list:
    """Build one analysis row per quoted contract.

    An inverse contract is quoted in the coin, so its premium is carried to the
    quote currency at the index level, which is what the chain endpoint does and
    what the valuation layer expects.
    """
    from datetime import datetime, timezone

    from openbb_deribit.utils.helpers import days_to_expiration, from_timestamp
    from openbb_deribit.utils.options.greeks import SECONDS_PER_YEAR, greeks

    now = datetime.now(timezone.utc).timestamp()
    built: list[dict] = []

    for quote in quotes:
        name = str(quote["instrument_name"])
        spec = specs[name]
        option_type = str(spec["option_type"])
        strike = float(spec["strike"])
        inverse = str(spec.get("instrument_type")) == "reversed"
        carry = spot if inverse else 1.0
        forward = float(quote.get("underlying_price") or 0)
        volatility = quote.get("mark_iv")
        years = (float(spec["expiration_timestamp"]) / 1000 - now) / SECONDS_PER_YEAR
        modelled = greeks(
            forward, strike, years, float(volatility or 0) / 100, option_type
        )
        built.append(
            {
                "contract_symbol": name,
                "expiration": from_timestamp(spec["expiration_timestamp"]).date(),
                "dte": days_to_expiration(spec["expiration_timestamp"], now * 1000),
                "strike": strike,
                "option_type": option_type,
                "contract_size": float(spec.get("contract_size") or 1),
                "tick_size": _carried(spec.get("tick_size"), carry),
                "is_inverse": inverse,
                "mark": _carried(quote.get("mark_price"), carry),
                "bid": _carried(quote.get("bid_price"), carry),
                "ask": _carried(quote.get("ask_price"), carry),
                "last": _carried(quote.get("last"), carry),
                "implied_volatility": volatility,
                "open_interest": quote.get("open_interest"),
                "volume": quote.get("volume"),
                "volume_notional": quote.get("volume_usd"),
                "underlying_price": forward,
                "underlying_spot_price": spot,
                **modelled,
            }
        )

    return built


def _carried(value: Any, carry: float) -> "float | None":
    """Carry one quoted price to the currency the position is measured in."""
    return None if value is None else float(value) * carry


async def load_chain(symbol: str, use_cache: bool = True) -> "DataFrame":
    """Return the full chain of one underlying as a frame.

    Reading a chain is three REST calls, so a dashboard showing several views of
    one underlying would make them once per view, and every parameter a reader
    changes would make them again. The last read is held and shared instead: a
    nine-widget tab costs three calls, and changing what is drawn costs none.

    Parameters
    ----------
    symbol : str
        The underlying root, as it appears in the instrument name.
    use_cache : bool
        Whether a read taken moments ago may be reused.

    Returns
    -------
    DataFrame
        One row per contract, with its quote, greeks, and settlement style.

    Raises
    ------
    EmptyDataError
        If the exchange published no option quotes for the underlying.
    """
    from time import monotonic

    from openbb_core.provider.utils.errors import EmptyDataError
    from pandas import DataFrame

    root = symbol.upper()
    lock = _LOCKS.setdefault(root, asyncio.Lock())

    async with lock:
        held = _LOADED.get(root)

        if use_cache and held and monotonic() - held[0] < CHAIN_TTL:
            return held[1].copy()

        quotes, specs, spot = await _source(root)
        frame = DataFrame(_rows(quotes, specs, spot))

        if frame.empty:
            raise EmptyDataError(f"Deribit published no option quotes for {root}.")

        _LOADED[root] = (monotonic(), frame)

        return frame.copy()


async def load_combos(symbol: str, use_cache: bool = True) -> list:
    """Return the combo books listed on an underlying's options, with their quotes.

    Parameters
    ----------
    symbol : str
        The underlying root, as it appears in the instrument name.
    use_cache : bool
        Whether a read taken moments ago may be reused.

    Returns
    -------
    list
        One record per combo: its name, its legs as (instrument, amount) pairs,
        and its bid and ask in the currency the combo is quoted in.
    """
    from time import monotonic

    from openbb_deribit.utils.client import request

    root = symbol.upper()
    key = f"{root}#combos"
    lock = _LOCKS.setdefault(key, asyncio.Lock())

    async with lock:
        held = _LOADED.get(key)

        if use_cache and held and monotonic() - held[0] < CHAIN_TTL:
            return list(held[1])

        currency = settlement_of(root)
        listed, quoted = await asyncio.gather(
            request("get_combos", {"currency": currency}),
            request(
                "get_book_summary_by_currency",
                {"currency": currency, "kind": "option_combo"},
            ),
        )
        quotes = {str(row["instrument_name"]): row for row in quoted or []}
        books = []

        for combo in listed or []:
            legs = [
                (str(leg["instrument_name"]), int(leg["amount"]))
                for leg in combo["legs"]
            ]

            if not all(
                name.split("-")[0] == root and len(name.split("-")) == 4
                for name, _ in legs
            ):
                continue

            quote = quotes.get(str(combo["id"]), {})
            books.append(
                {
                    "name": str(combo["id"]),
                    "legs": legs,
                    "bid": quote.get("bid_price"),
                    "ask": quote.get("ask_price"),
                }
            )

        _LOADED[key] = (monotonic(), books)

        return list(books)


def underlying_price(frame: "DataFrame") -> float:
    """Return the spot price of the underlying the chain was quoted against."""
    spot = frame["underlying_spot_price"].dropna()

    return float(spot.iloc[0]) if not spot.empty else 0.0


def is_inverse(frame: "DataFrame") -> bool:
    """Return whether the chain's contracts settle in the underlying."""
    return bool(frame["is_inverse"].any())


def settlement_currency(frame: "DataFrame", symbol: str) -> str:
    """Return what a position in this chain settles in."""
    root = symbol.split("_", maxsplit=1)[0].upper()

    return root if is_inverse(frame) else "USDC"


def expirations(frame: "DataFrame") -> list:
    """Return every expiration on the chain, nearest first."""
    return sorted(frame["expiration"].dropna().unique())


def nearest_expiration(frame: "DataFrame", target: Any) -> Any:
    """Return the expiration closest to a date.

    Parameters
    ----------
    frame : DataFrame
        The chain.
    target : Any
        The date the position is held to.

    Returns
    -------
    Any
        The listed expiration nearest the target.
    """
    from pandas import to_datetime

    wanted = to_datetime(target).date()
    listed = expirations(frame)

    return min(listed, key=lambda day: abs((day - wanted).days))


def far_expiration(frame: "DataFrame", near: Any, gap: int = 30) -> Any:
    """Return the expiration a calendar sells the near one against.

    Parameters
    ----------
    frame : DataFrame
        The chain.
    near : Any
        The expiration being traded.
    gap : int
        How many days past it the far expiration is sought.

    Returns
    -------
    Any
        The later expiration nearest the gap, or None when nothing is later.
    """
    later = [day for day in expirations(frame) if day > near]

    if not later:
        return None

    return min(later, key=lambda day: abs((day - near).days - gap))


def quotes_at(frame: "DataFrame", expiration: Any = None) -> "DataFrame":
    """Return the tradeable contracts, entered at no less than one tick.

    Parameters
    ----------
    frame : DataFrame
        The chain.
    expiration : Any
        The expiration to keep. None keeps every expiration.

    Returns
    -------
    DataFrame
        The contracts with a price, each with the price it is entered and left at.
    """
    at = (
        frame.copy()
        if expiration is None
        else frame[frame["expiration"] == expiration].copy()
    )

    for column in ("bid", "ask", "mark", "tick_size"):
        at[column] = at[column].astype(float)

    entry = at["ask"].where(at["ask"] > 0, at["mark"])
    at["entry"] = entry.combine(at["tick_size"].fillna(0), max).where(entry > 0, 0.0)
    at["exit"] = at["bid"].where(at["bid"] > 0, at["mark"])

    return at[at["entry"] > 0].sort_values(["option_type", "strike"])
