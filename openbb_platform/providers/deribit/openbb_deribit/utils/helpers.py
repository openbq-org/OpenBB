"""Shared accessors for the Deribit public API."""

from typing import Any

MAX_CHART_WINDOWS = 15
CHART_WINDOW_SIZE = 5000
SECONDS_PER_DAY = 86400
CURVE_LOOKBACK_HOURS = 24


def to_timestamp(value: Any) -> int:
    """Return a date, datetime, or string as milliseconds since the epoch."""
    from pandas import Timestamp, to_datetime

    stamp = value if isinstance(value, Timestamp) else to_datetime(value, utc=True)

    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")

    return int(stamp.timestamp() * 1000)


def from_timestamp(value: Any) -> Any:
    """Return milliseconds since the epoch as a UTC datetime."""
    from pandas import to_datetime

    return (
        to_datetime(value, unit="ms", origin="unix", utc=True)
        if value is not None
        else None
    )


def from_day_number(value: Any) -> Any:
    """Return a count of whole days since the epoch as a date."""
    from pandas import to_datetime

    return (
        to_datetime(
            int(value) * SECONDS_PER_DAY, unit="s", origin="unix", utc=True
        ).date()
        if value is not None
        else None
    )


def days_to_expiration(expiration_timestamp: Any, now: float) -> int:
    """Return the whole days left before a contract expires.

    The days are counted to the instant the exchange expires the contract, not
    to its calendar date. A date is read in the timezone of the machine asking,
    so the same contract would count a different number of days from one place
    to the next. Part of a day is dropped: a contract with hours left is at zero
    days, as is one that has already expired.

    Parameters
    ----------
    expiration_timestamp : Any
        When the contract expires, in milliseconds since the epoch.
    now : float
        The time to count from, in milliseconds since the epoch.

    Returns
    -------
    int
        The whole days left, never fewer than zero.
    """
    left = (float(expiration_timestamp) - now) / (SECONDS_PER_DAY * 1000)

    return max(int(left), 0)


def reject_options_by_settlement(currency: str, kind: "str | None") -> None:
    """Refuse a listing of option contracts scoped to a settlement currency.

    Only BTC and ETH are both a settlement currency and an underlying. USDC
    settles options written on seven different underlyings, so a listing scoped
    to it returns a mixture of unrelated assets rather than a chain, and USDT
    settles no options at all. Options are listed by the underlying they are
    written on, or by instrument name.

    Parameters
    ----------
    currency : str
        The settlement currency asked for.
    kind : str or None
        The kind of instrument asked for.

    Raises
    ------
    ValueError
        If option contracts are asked for by a currency that only settles them.
    """
    from openbb_deribit.utils.constants import OPTION_KINDS, UNDERLYING_CURRENCIES

    if currency.upper() in UNDERLYING_CURRENCIES or kind not in OPTION_KINDS:
        return

    raise ValueError(
        f"{currency.upper()} settles options, it is not an underlying, so there"
        " are no options on it to list. Ask for options by the underlying they"
        " are written on, such as BTC_USDC or SOL_USDC, using the symbol"
        " parameter."
    )


def normalize_currency(currency: str) -> str:
    """Return a currency as the exchange spells it, leaving the wildcard alone."""
    return "any" if currency.lower() in ("any", "all") else currency.upper()


async def get_currencies() -> list[dict]:
    """Return every currency the exchange lists."""
    from openbb_deribit.utils.client import request

    return await request("get_currencies")


async def get_instruments(
    currency: str = "any",
    kind: str | None = None,
    expired: bool = False,
) -> list[dict]:
    """Return the instruments of one currency, optionally of one kind.

    Parameters
    ----------
    currency : str
        The settlement currency, or 'any' for all of them.
    kind : str or None
        One of the instrument kinds, or None for all of them.
    expired : bool
        When True, returns instruments that have already expired.

    Returns
    -------
    list[dict]
        Every matching instrument.
    """
    from openbb_deribit.utils.client import request

    return await request(
        "get_instruments",
        {
            "currency": normalize_currency(currency),
            "kind": kind,
            "expired": expired,
        },
    )


async def get_instrument(symbol: str) -> dict:
    """Return the definition of one instrument."""
    from openbb_deribit.utils.client import request

    return await request("get_instrument", {"instrument_name": symbol})


def flatten_ticker(data: dict) -> dict:
    """Return a ticker with its nested statistics and greeks at the top level."""
    flat = dict(data)
    stats = flat.pop("stats", None) or {}
    greeks = flat.pop("greeks", None) or {}

    return {**flat, **stats, **greeks}


async def get_ticker(symbol: str) -> dict:
    """Return the quote and statistics of one instrument."""
    from openbb_deribit.utils.client import request

    return flatten_ticker(await request("ticker", {"instrument_name": symbol}))


async def get_tickers(symbols: list[str]) -> list[dict]:
    """Return the quotes of many instruments, skipping the ones that fail."""
    from openbb_deribit.utils.client import gather

    results = await gather([("ticker", {"instrument_name": s}) for s in symbols])

    return [
        flatten_ticker(result)
        for result in results
        if isinstance(result, dict) and result
    ]


async def get_index_names(extended: bool = False) -> list:
    """Return the names of every published index."""
    from openbb_deribit.utils.client import request

    return await request("get_index_price_names", {"extended": extended})


async def get_expirations(
    currency: str = "any",
    kind: str = "any",
    currency_pair: str | None = None,
) -> dict:
    """Return the expirations listed for one currency and kind."""
    from openbb_deribit.utils.client import request

    return await request(
        "get_expirations",
        {"currency": currency, "kind": kind, "currency_pair": currency_pair},
    )


def _roots(instruments: list[dict]) -> dict[str, list[dict]]:
    """Group instruments by the root of their name."""
    grouped: dict[str, list[dict]] = {}

    for instrument in instruments:
        root = str(instrument.get("instrument_name") or "").split("-")[0]

        if root:
            grouped.setdefault(root, []).append(instrument)

    return grouped


async def get_options_roots() -> list[str]:
    """Return every underlying the exchange currently lists options on."""
    return sorted(_roots(await get_instruments("any", "option")))


async def get_futures_roots() -> list[str]:
    """Return every underlying the exchange currently lists dated futures on."""
    grouped = _roots(await get_instruments("any", "future"))

    return sorted(
        root
        for root, listed in grouped.items()
        if sum(1 for d in listed if d.get("settlement_period") != "perpetual") > 1
    )


async def get_options_symbols(symbol: str = "BTC") -> dict[str, list[str]]:
    """Return the option symbols of one underlying, keyed by expiration.

    Parameters
    ----------
    symbol : str
        The underlying root, as it appears in the instrument name.

    Returns
    -------
    dict[str, list[str]]
        Every contract symbol, keyed by its expiration date.

    Raises
    ------
    OpenBBError
        If the exchange lists no options on the underlying.
    """
    from openbb_core.app.model.abstract.error import OpenBBError
    from pandas import to_datetime

    root = symbol.upper()
    grouped = _roots(await get_instruments("any", "option"))
    listed = grouped.get(root)

    if not listed:
        raise OpenBBError(
            f"Deribit lists no options on {root}."
            f" Underlyings with listed options are: {', '.join(sorted(grouped))}"
        )

    symbols = sorted(
        str(d["instrument_name"])
        for d in listed
        if str(d.get("instrument_name", "")).endswith(("-C", "-P"))
    )
    expirations: dict[str, list[str]] = {}

    for contract in symbols:
        code = contract.split("-")[1]
        expiration = to_datetime(code).date().strftime("%Y-%m-%d")
        expirations.setdefault(expiration, []).append(contract)

    return dict(sorted(expirations.items()))


async def get_futures_curve_symbols(symbol: str = "BTC") -> list[str]:
    """Return the dated future symbols of one underlying.

    Parameters
    ----------
    symbol : str
        The underlying root, as it appears in the instrument name.

    Returns
    -------
    list[str]
        Every contract symbol on the curve, nearest expiration first.

    Raises
    ------
    OpenBBError
        If the exchange lists no curve for the underlying.
    """
    from openbb_core.app.model.abstract.error import OpenBBError

    root = symbol.upper()
    grouped = _roots(await get_instruments("any", "future"))
    listed = [
        d
        for d in grouped.get(root, [])
        if d.get("settlement_period") != "perpetual"
        and str(d.get("instrument_name", "")).split("-")[0] == root
    ]

    if not listed:
        roots = await get_futures_roots()

        raise OpenBBError(
            f"Deribit lists no futures curve for {root}."
            f" Underlyings with a curve are: {', '.join(roots)}"
        )

    return [
        str(d["instrument_name"])
        for d in sorted(listed, key=lambda d: d.get("expiration_timestamp") or 0)
    ]


async def get_perpetual_symbols() -> dict[str, str]:
    """Return every perpetual symbol, keyed by its shortened root."""
    instruments = await get_instruments("any", "future")

    return {
        str(d["instrument_name"]).split("-")[0].replace("_", ""): str(
            d["instrument_name"]
        )
        for d in instruments
        if d.get("settlement_period") == "perpetual"
    }


async def get_futures_symbols() -> list[str]:
    """Return every listed future symbol."""
    instruments = await get_instruments("any", "future")

    return sorted(str(d["instrument_name"]) for d in instruments)


async def resolve_symbol(symbol: str) -> str:
    """Return the instrument name a symbol refers to.

    Parameters
    ----------
    symbol : str
        An instrument name, or the shortened root of a perpetual.

    Returns
    -------
    str
        The instrument name the exchange knows the symbol by.

    Raises
    ------
    OpenBBError
        If the exchange lists no such instrument.
    """
    from openbb_core.app.model.abstract.error import OpenBBError

    candidate = symbol.upper()
    perpetuals = await get_perpetual_symbols()

    if candidate in perpetuals:
        return perpetuals[candidate]

    instruments = await get_instruments("any", None)
    listed = {str(d.get("instrument_name")) for d in instruments}

    if candidate in listed:
        return candidate

    raise OpenBBError(f"Deribit lists no instrument named {symbol}.")


def _chart_windows(
    start: int, end: int, resolution: str, window: int = CHART_WINDOW_SIZE
) -> list[tuple[int, int]]:
    """Split a span into windows of at most one page of candles each."""
    from pandas import date_range

    freq = "1D" if resolution == "1D" else f"{resolution}min"
    stamps = date_range(start=from_timestamp(start), end=from_timestamp(end), freq=freq)

    if len(stamps) <= 1:
        return [(start, end)]

    return [
        (
            int(stamps[index].timestamp() * 1000),
            int(stamps[min(index + window, len(stamps) - 1)].timestamp() * 1000),
        )
        for index in range(0, len(stamps), window)
    ]


async def get_ohlc_data(
    symbol: str,
    start_date: Any,
    end_date: Any,
    interval: str = "1d",
) -> list[dict]:
    """Return the candles of one instrument over a span.

    Parameters
    ----------
    symbol : str
        The instrument name.
    start_date : Any
        The first date of the span.
    end_date : Any
        The last date of the span.
    interval : str
        One of the supported candle intervals.

    Returns
    -------
    list[dict]
        One record per candle, oldest first.

    Raises
    ------
    OpenBBError
        If the span needs more pages than the exchange will serve at once.
    EmptyDataError
        If the instrument published no candles over the span.
    """
    from openbb_core.app.model.abstract.error import OpenBBError
    from openbb_core.provider.utils.errors import EmptyDataError

    from openbb_deribit.utils.client import gather
    from openbb_deribit.utils.constants import INTERVAL_MAP

    resolution = INTERVAL_MAP.get(interval, interval)
    instruments = await get_instruments("any", None)
    created = {
        str(d.get("instrument_name")): d.get("creation_timestamp") for d in instruments
    }

    if symbol not in created:
        raise OpenBBError(f"Deribit lists no instrument named {symbol}.")

    start = max(to_timestamp(start_date), int(created[symbol] or 0))
    end = to_timestamp(end_date)
    windows = _chart_windows(start, end, resolution)

    if len(windows) > MAX_CHART_WINDOWS:
        raise OpenBBError(
            f"The span covers {len(windows)} pages of {interval} candles, and"
            f" Deribit serves at most {MAX_CHART_WINDOWS} at a time."
            " Narrow the dates, or widen the interval."
        )

    results = await gather(
        [
            (
                "get_tradingview_chart_data",
                {
                    "instrument_name": symbol,
                    "start_timestamp": window_start,
                    "end_timestamp": window_end,
                    "resolution": resolution,
                },
            )
            for window_start, window_end in windows
        ]
    )
    records: dict[int, dict] = {}

    for result in results:
        if not isinstance(result, dict) or not result.get("ticks"):
            continue

        for index, tick in enumerate(result["ticks"]):
            records[tick] = {
                "date": from_timestamp(tick),
                "symbol": symbol,
                "open": result["open"][index],
                "high": result["high"][index],
                "low": result["low"][index],
                "close": result["close"][index],
                "volume": result["volume"][index],
                "volume_notional": result["cost"][index],
            }

    if not records:
        raise EmptyDataError(f"Deribit published no {interval} candles for {symbol}.")

    ordered = [records[tick] for tick in sorted(records)]

    if resolution == "1D":
        for record in ordered:
            record["date"] = record["date"].date()

    return ordered


async def get_futures_curve_by_hours_ago(symbol: str, hours: int) -> list[dict]:
    """Return the futures curve of one underlying as it stood some hours ago.

    Parameters
    ----------
    symbol : str
        The underlying root.
    hours : int
        How many hours back to read the curve.

    Returns
    -------
    list[dict]
        The last price of each contract that had traded by that hour. A contract
        the exchange published no candle for is left out, because a curve that
        carries the current price under a past label is not a past curve.
    """
    from datetime import datetime, timedelta, timezone

    from openbb_deribit.utils.client import gather

    symbols = await get_futures_curve_symbols(symbol)
    now = datetime.now(timezone.utc).replace(microsecond=0, second=0, minute=0)
    target = to_timestamp(now - timedelta(hours=hours))
    start = to_timestamp(now - timedelta(hours=hours + CURVE_LOOKBACK_HOURS))
    results = await gather(
        [
            (
                "get_tradingview_chart_data",
                {
                    "instrument_name": contract,
                    "start_timestamp": start,
                    "end_timestamp": target,
                    "resolution": "60",
                },
            )
            for contract in symbols
        ]
    )
    curve: list[dict] = []

    for contract, result in zip(symbols, results):
        if not isinstance(result, dict) or not result.get("ticks"):
            continue

        ticks = result["ticks"]
        index = min(
            range(len(ticks)), key=lambda position: abs(ticks[position] - target)
        )
        curve.append(
            {
                "instrument_name": contract,
                "hours_ago": hours,
                "last_price": result["close"][index],
            }
        )

    return curve
