"""TMX TradingView UDF sub-router."""

import logging
from datetime import UTC
from typing import Annotated, Any

from fastapi import Query as FastAPIQuery
from openbb_core.app.router import Router

router = Router(prefix="/udf", description="TradingView UDF feed for TMX data.")

_logger = logging.getLogger(__name__)

HISTORY_FAILED = "The price history could not be read."

SUPPORTED_RESOLUTIONS = ["1", "5", "15", "30", "60", "D", "W", "M"]

INTRADAY_RESOLUTIONS = {"1": 1, "5": 5, "15": 15, "30": 30, "60": 60}

PERIOD_RESOLUTIONS = {"D": "day", "W": "week", "M": "month"}

PERIOD_ONLY_RESOLUTIONS = ["D", "W", "M"]


def _parse_resolution(resolution: str) -> tuple[str, Any]:
    """Read a TradingView resolution string.

    Parameters
    ----------
    resolution : str
        The resolution as the chart sends it.

    Returns
    -------
    tuple[str, Any]
        Either ('intraday', minutes) or ('period', 'day' | 'week' | 'month').
    """
    text = (resolution or "D").strip().upper()

    if text.isdigit():
        return "intraday", max(int(text), 1)

    multiplier, unit = text[:-1], text[-1]

    if unit == "S":
        return "intraday", 1

    period = {"D": "day", "W": "week", "M": "month"}.get(unit)

    if period is None:
        return "period", "day"

    if unit == "D" and multiplier.isdigit() and int(multiplier) > 1:
        return "period", "day"

    return "period", period


def _exchanges() -> list[dict]:
    """List the venues the chart can actually draw, for its exchange picker."""
    from openbb_tmx.utils.exchanges import CHARTABLE_VENUES, DIRECTORY_VENUES

    return [{"value": "", "name": "All Exchanges", "desc": ""}] + [
        {"value": code, "name": code, "desc": DIRECTORY_VENUES[code]}
        for code in CHARTABLE_VENUES
    ]


SYMBOL_TYPES = [
    {"name": "All types", "value": ""},
    {"name": "Stocks", "value": "stock"},
    {"name": "Funds", "value": "fund"},
    {"name": "Indices", "value": "index"},
    {"name": "Futures", "value": "futures"},
    {"name": "Forex", "value": "forex"},
    {"name": "Crypto", "value": "crypto"},
]

PREFIX_TYPES = {"^": "index", "/": "futures", "$": "forex", "~": "crypto"}

DEFAULT_SESSION = "0930-1600"
CONTINUOUS_SESSION = "24x7"

EXCHANGE_SESSIONS = {
    "US": ("America/New_York", DEFAULT_SESSION, True),
    "PA": ("Europe/Paris", "0900-1730", False),
    "AS": ("Europe/Amsterdam", "0900-1730", False),
    "BR": ("Europe/Brussels", "0900-1730", False),
    "LS": ("Europe/Lisbon", "0800-1630", False),
    "MA": ("Europe/Madrid", "0900-1730", False),
    "MI": ("Europe/Rome", "0900-1730", False),
    "FF": ("Europe/Berlin", "0800-2200", False),
    "DB": ("Europe/Berlin", "0900-1730", False),
    "BE": ("Europe/Berlin", "0800-2200", False),
    "MU": ("Europe/Berlin", "0800-2200", False),
    "SG": ("Europe/Berlin", "0800-2200", False),
    "HM": ("Europe/Berlin", "0800-2200", False),
    "HA": ("Europe/Berlin", "0800-2200", False),
    "DU": ("Europe/Berlin", "0800-2200", False),
    "SM": ("Europe/Zurich", "0900-1730", False),
    "VX": ("Europe/Zurich", "0900-1730", False),
    "ST": ("Europe/Stockholm", "0900-1730", False),
    "CO": ("Europe/Copenhagen", "0900-1700", False),
    "HI": ("Europe/Helsinki", "1000-1830", False),
    "OS": ("Europe/Oslo", "0900-1630", False),
    "IE": ("Europe/Dublin", "0800-1630", False),
    "LN": ("Europe/London", "0800-1630", False),
    "AT": ("Europe/Athens", "1000-1720", False),
    "AE": ("Asia/Dubai", "1000-1500", False),
    "HK": ("Asia/Hong_Kong", "0930-1600", False),
    "SH": ("Asia/Shanghai", "0930-1500", False),
    "CZ": ("Asia/Shanghai", "0930-1500", False),
    "NKK": ("Asia/Tokyo", "0900-1530", False),
    "MB": ("Asia/Kolkata", "0915-1530", False),
    "AU": ("Australia/Sydney", "1000-1600", False),
    "MX": ("America/Mexico_City", DEFAULT_SESSION, False),
    "BV": ("America/Sao_Paulo", "1000-1755", False),
    "AR": ("America/Argentina/Buenos_Aires", "1100-1700", False),
    "CL": ("America/Santiago", "0930-1600", False),
}

CANADIAN_SESSION = ("America/Toronto", DEFAULT_SESSION, True)


def _session_for(symbol: str) -> tuple:
    """Return the timezone, trading session, and intraday support for a symbol.

    Parameters
    ----------
    symbol : str
        The resolved symbol, with any prefix or exchange suffix.

    Returns
    -------
    tuple
        The timezone, the session string, and whether intraday bars exist.
    """
    if symbol[:1] in ("$", "~"):
        return "Etc/UTC", CONTINUOUS_SESSION, True

    if symbol[:1] == "/":
        return "America/Toronto", CONTINUOUS_SESSION, True

    suffix = symbol.rsplit(":", 1)[1] if ":" in symbol else None

    return EXCHANGE_SESSIONS.get(suffix, CANADIAN_SESSION)


FILTERED_PAGE = 2000

TYPE_MAP = {
    "Equity": "stock",
    "ETF": "fund",
    "Mutual Fund": "fund",
    "Money Market Fund": "fund",
    "Index": "index",
    "Future": "futures",
    "Forex": "forex",
    "Crypto": "crypto",
}

ISSUE_TYPE_CODES = {
    "CS": "stock",
    "PS": "stock",
    "RE": "stock",
    "UN": "stock",
    "RT": "stock",
    "WT": "stock",
    "AD": "stock",
    "ET": "fund",
    "MF": "fund",
    "CE": "fund",
    "ID": "index",
    "FU": "futures",
    "FX": "forex",
}


def _instrument_type(symbol: str, issue_type: str | None) -> str:
    """Classify an instrument for the chart.

    Parameters
    ----------
    symbol : str
        The normalized symbol.
    issue_type : str or None
        The issue type as either source reported it.

    Returns
    -------
    str
        One of the types advertised in the feed configuration.
    """
    if symbol[:1] in PREFIX_TYPES:
        return PREFIX_TYPES[symbol[:1]]

    if not issue_type:
        return "stock"

    return TYPE_MAP.get(issue_type) or ISSUE_TYPE_CODES.get(issue_type, "stock")


@router.api_router.get("/config", include_in_schema=False)
async def config() -> dict:
    """Describe the capabilities of this UDF feed."""
    return {
        "supported_resolutions": SUPPORTED_RESOLUTIONS,
        "supports_group_request": False,
        "supports_marks": False,
        "supports_search": True,
        "supports_timescale_marks": False,
        "supports_time": True,
        "exchanges": _exchanges(),
        "symbols_types": SYMBOL_TYPES,
    }


@router.api_router.get("/search", include_in_schema=False)
async def search(
    query: Annotated[str, FastAPIQuery(description="The search query.")] = "",
    limit: Annotated[int, FastAPIQuery(description="Maximum results.")] = 30,
    exchange: Annotated[
        str, FastAPIQuery(description="Restrict to one exchange.")
    ] = "",
    type: Annotated[  # noqa: A002
        str, FastAPIQuery(description="Restrict to one symbol type.")
    ] = "",
) -> list[dict]:
    """Search the instrument symbology for the chart's symbol picker."""
    from openbb_tmx.utils.directory import browse_symbols, lookup_symbols
    from openbb_tmx.utils.exchanges import CHARTABLE_VENUES

    page = FILTERED_PAGE if (exchange or type) else max(limit * 3, 30)
    rows = (
        await browse_symbols(limit=page, country=None)
        if not query
        else await lookup_symbols(query, limit=page, country=None)
    )
    results: list[dict] = []

    for row in rows:
        symbol = str(row.get("symbol") or "")
        symbol_type = _instrument_type(symbol, row.get("symbolType"))
        venue = row.get("exchangeShortName") or ""

        if venue not in CHARTABLE_VENUES:
            continue

        if exchange and venue != exchange:
            continue

        if type and symbol_type != type:
            continue

        results.append(
            {
                "symbol": row.get("symbol"),
                "full_name": row.get("symbol"),
                "description": row.get("name") or "",
                "exchange": venue,
                "ticker": row.get("symbol"),
                "type": symbol_type,
            }
        )

        if len(results) >= limit:
            break

    return results


DAILY_ONLY_VENUES = {"CMF", "NMF"}

VENUE_CURRENCIES = {
    "TSX": "CAD",
    "TSXV": "CAD",
    "ALPHA": "CAD",
    "CSE": "CAD",
    "NEO-L": "CAD",
    "NEO-D": "CAD",
    "NEO-N": "CAD",
    "CXD": "CAD",
    "MOE": "CAD",
    "CMF": "CAD",
    "TSXSTAT": "CAD",
    "TSVST": "CAD",
}

CURRENCY_CODES = {
    "AUD",
    "BRL",
    "CAD",
    "CHF",
    "CNY",
    "DKK",
    "EUR",
    "GBP",
    "GBX",
    "HKD",
    "ILS",
    "INR",
    "JPY",
    "KRW",
    "MXN",
    "NOK",
    "NZD",
    "PLN",
    "SEK",
    "SGD",
    "TRY",
    "TWD",
    "USD",
    "ZAR",
}


def _pair_currency(symbol: str) -> str | None:
    """Read the quote currency out of a currency or crypto pair.

    Parameters
    ----------
    symbol : str
        The pair symbol, with its prefix and any exchange suffix.

    Returns
    -------
    str or None
        The quote currency, or None when the symbol is not a pair.
    """
    if symbol[:1] not in ("$", "~"):
        return None

    body = symbol[1:].split(":", 1)[0]

    return body[3:] if len(body) >= 6 else None


def _currency_for(symbol: str, venue: str | None, reported: str | None) -> str | None:
    """Settle the currency a symbol is quoted in.

    Parameters
    ----------
    symbol : str
        The instrument symbol.
    venue : str or None
        The exchange short name.
    reported : str or None
        The currency the quote feed reported, when it reported one.

    Returns
    -------
    str or None
        The currency code, or None when no source establishes one.
    """
    if reported:
        return reported

    pair = _pair_currency(symbol)

    if pair:
        return pair

    if venue and venue in VENUE_CURRENCIES:
        return VENUE_CURRENCIES[venue]

    suffix = symbol.rsplit(":", 1)[-1] if ":" in symbol else ""

    if suffix and suffix in CURRENCY_CODES:
        return suffix

    return "USD" if venue else None


async def _resolve_symbol(resolved: str) -> dict:
    """Resolve a symbol against every symbology the feed can reach.

    Parameters
    ----------
    resolved : str
        The normalized symbol.

    Returns
    -------
    dict
        The description, venue, currency, and issue type that could be read.
    """
    from openbb_tmx.utils import gql
    from openbb_tmx.utils.cache import amake_gql_request

    found: dict = {}

    try:
        response = await amake_gql_request(
            "getQuoteBySymbol",
            gql.QUOTE_BY_SYMBOL,
            {"symbol": resolved, "locale": "en"},
            symbol=resolved,
        )
        quote = (response or {}).get("getQuoteBySymbol") or {}
        found = {
            "description": quote.get("name"),
            "venue": quote.get("exShortName") or quote.get("exchangeName"),
            "currency": quote.get("currency"),
            "issue_type": quote.get("issueType"),
        }
    except Exception:  # noqa: BLE001
        found = {}

    if found.get("description") and found.get("currency") and found.get("issue_type"):
        return found

    try:
        response = await amake_gql_request(
            "getQuoteForSymbols",
            gql.QUOTE_FOR_SYMBOLS,
            {"symbols": [resolved]},
            symbol=resolved,
        )
        rows = (response or {}).get("getQuoteForSymbols") or []
        row = rows[0] if rows else {}
    except Exception:  # noqa: BLE001
        row = {}

    found.setdefault("issue_type", None)
    found["description"] = found.get("description") or row.get("longname")
    found["venue"] = found.get("venue") or row.get("exchange")
    found["currency"] = found.get("currency") or row.get("currency")

    if found.get("description") and found.get("venue") and found.get("issue_type"):
        return found

    from openbb_tmx.utils.directory import lookup_symbols

    try:
        entries = await lookup_symbols(
            resolved, limit=10, country=None, symbol_only=True
        )
    except Exception:  # noqa: BLE001
        entries = []

    entry = next((e for e in entries if e.get("symbol") == resolved), {})
    found["description"] = found.get("description") or entry.get("name")
    found["venue"] = found.get("venue") or entry.get("exchangeShortName")
    found["issue_type"] = found.get("issue_type") or entry.get("symbolType")

    return found


@router.api_router.get("/symbols", include_in_schema=False)
async def symbols(
    symbol: Annotated[str, FastAPIQuery(description="The symbol to resolve.")],
) -> dict:
    """Resolve a symbol for the chart.

    Raises
    ------
    OpenBBError
        If neither the quote feed nor the symbology recognises the symbol.
    """
    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_tmx.utils.helpers import normalize_symbol

    resolved = normalize_symbol(symbol)
    found = await _resolve_symbol(resolved)
    description = found.get("description")
    exchange = found.get("venue")
    issue_type = found.get("issue_type")

    if not description and not exchange:
        raise OpenBBError(f"{symbol} did not resolve to a quotable instrument.")

    currency = _currency_for(resolved, exchange, found.get("currency"))
    timezone_name, session, has_intraday = _session_for(resolved)

    if exchange in DAILY_ONLY_VENUES:
        has_intraday = False

    return {
        "name": resolved,
        "ticker": resolved,
        "full_name": resolved,
        "description": description or resolved,
        "type": _instrument_type(resolved, issue_type),
        "exchange": exchange,
        "listed_exchange": exchange,
        "currency_code": currency,
        "pricescale": 100,
        "minmov": 1,
        "fractional": False,
        "has_intraday": has_intraday,
        "has_daily": True,
        "has_weekly_and_monthly": True,
        "supported_resolutions": (
            SUPPORTED_RESOLUTIONS if has_intraday else PERIOD_ONLY_RESOLUTIONS
        ),
        "session": session,
        "timezone": timezone_name,
        "data_status": "delayed_streaming",
    }


@router.api_router.get("/history", include_in_schema=False)
async def history(
    symbol: str = FastAPIQuery(..., description="The symbol."),
    resolution: str = FastAPIQuery(default="D", description="The bar resolution."),
    to: int = FastAPIQuery(..., description="Unix timestamp of the last bar."),
    from_: int = FastAPIQuery(
        default=0, alias="from", description="Unix timestamp of the first bar."
    ),
    countback: int | None = FastAPIQuery(
        default=None, description="The number of bars to return, counting back."
    ),
) -> dict:
    """Return OHLCV bars in the UDF envelope."""
    from datetime import datetime

    from openbb_tmx.utils.helpers import (
        get_intraday_price_history,
        get_timeseries_history,
        normalize_symbol,
    )

    resolution = resolution if isinstance(resolution, str) else "D"
    countback = countback if isinstance(countback, int) else None
    resolved = normalize_symbol(symbol)
    kind, unit = _parse_resolution(resolution)
    end = datetime.now(tz=UTC).date()

    try:
        if kind == "intraday":
            bars = await get_intraday_price_history(resolved, None, end, unit)
        else:
            bars = await get_timeseries_history(resolved, None, end, unit)
    except Exception:  # noqa: BLE001
        _logger.exception(HISTORY_FAILED)

        return {"s": "error", "errmsg": HISTORY_FAILED}

    if not bars:
        return {"s": "no_data"}

    envelope: dict[str, Any] = {
        "s": "ok",
        "t": [],
        "o": [],
        "h": [],
        "l": [],
        "c": [],
        "v": [],
    }

    for bar in bars:
        stamp = bar.get("dateTime")

        if not stamp or bar.get("close") is None:
            continue

        moment = datetime.fromisoformat(str(stamp))

        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)

        envelope["t"].append(int(moment.timestamp()))
        envelope["o"].append(bar.get("open"))
        envelope["h"].append(bar.get("high"))
        envelope["l"].append(bar.get("low"))
        envelope["c"].append(bar.get("close"))
        envelope["v"].append(bar.get("volume") or 0)

    if not envelope["t"]:
        return {"s": "no_data"}

    if all(value is None for key in ("o", "h", "l") for value in envelope[key]):
        for key in ("o", "h", "l"):
            del envelope[key]

    return envelope


@router.api_router.get("/time", include_in_schema=False)
async def time() -> int:
    """Return the server time, as a Unix timestamp."""
    from datetime import datetime

    return int(datetime.now(tz=UTC).timestamp())
