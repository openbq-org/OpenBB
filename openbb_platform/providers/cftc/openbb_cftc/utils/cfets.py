"""CFETS/NIFC daily bulletin client for CNY interest rate swaps."""

from datetime import (
    UTC,
    date as dateType,
)

CFETS_IRS_BULLETIN_URL = "https://www.chinamoney.com.cn/ags/ms/cm-u-dlrp/IrsDlyBltn"
MAX_BULLETIN_LOOKBACK_DAYS = 10

IRS_LEG_CONVENTIONS: dict[str, dict] = {
    "FR007": {"day_count": "ACT/365F", "basis": 365.0, "payment_period_days": 91},
    "SHIBOR3M": {"day_count": "ACT/360", "basis": 360.0, "payment_period_days": 91},
    "SHIBORO/N": {"day_count": "ACT/360", "basis": 360.0, "payment_period_days": 91},
    "LPR1Y": {"day_count": "ACT/365F", "basis": 365.0, "payment_period_days": 91},
    "LPR5Y": {"day_count": "ACT/365F", "basis": 365.0, "payment_period_days": 91},
}


def mentions_cny(record: dict) -> bool:
    """Whether a print names CNY in its FISN or underlier."""
    tokens = (record.get("UPI Underlier Name") or "").split() + (
        record.get("UPI FISN") or ""
    ).split()

    return "CNY" in tokens


def normalize_reference(name: str) -> str:
    """Collapse a reference-rate name to its case- and space-insensitive key."""
    return (name or "").replace(" ", "").upper()


def _today_cct() -> dateType:
    """Return the current trading date in China Coordinated Time (UTC+8)."""
    from datetime import datetime, timedelta

    return (datetime.now(UTC) + timedelta(hours=8)).date()


async def _download_bulletin(search_date: str) -> dict:
    """POST the daily bulletin service for one search date."""
    import json
    import ssl

    import aiohttp
    import certifi
    from openbb_core.app.model.abstract.error import OpenBBError

    context = ssl.create_default_context(cafile=certifi.where())
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
        "Referer": "https://www.chinamoney.com.cn/english/mdtrptdbl/",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    try:
        async with (
            aiohttp.ClientSession(
                headers=headers, connector=aiohttp.TCPConnector(ssl=context)
            ) as session,
            session.post(
                CFETS_IRS_BULLETIN_URL, data=f"lang=en&searchDate={search_date}"
            ) as response,
        ):
            response.raise_for_status()
            payload = json.loads(await response.text())
    except OpenBBError:
        raise
    except Exception as exc:
        raise OpenBBError(f"Failed to fetch the IRS bulletin -> {exc}") from exc

    if (payload.get("head") or {}).get("rep_code") != "200" or not payload.get(
        "records"
    ):
        raise OpenBBError(
            f"Unexpected IRS bulletin response from CFETS for {search_date}."
        )

    return payload


async def fetch_irs_bulletin(
    search_date: dateType | None, use_cache: bool = True
) -> dict:
    """Return one day's IRS bulletin, served from the document store when closed."""
    from datetime import timedelta

    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_cftc.utils import store

    today = _today_cct()
    target = search_date or today
    key = f"cfets-irs-bulletin:{target.isoformat()}"

    if use_cache and search_date is not None:
        cached = store.get_document(key)

        if cached is not None:
            return cached

    payload: dict = {}

    for offset in range(MAX_BULLETIN_LOOKBACK_DAYS):
        day = target - timedelta(days=offset)

        try:
            payload = await _download_bulletin(day.isoformat())
            break
        except OpenBBError:
            if offset == MAX_BULLETIN_LOOKBACK_DAYS - 1:
                raise
    last_date = (payload.get("data") or {}).get("lastDate") or ""

    if use_cache and last_date and last_date < today.isoformat():
        store.put_document(f"cfets-irs-bulletin:{last_date}", payload)

        if search_date is not None and target.isoformat() != last_date:
            store.put_document(key, payload)

    return payload


async def cny_curve_records(day: dateType, use_cache: bool = True) -> list[dict]:
    """Return the FR007 par curve as tape-shaped CNY IRS records, for curve building."""
    from datetime import timedelta

    from openbb_core.app.model.abstract.error import OpenBBError
    from openbb_core.provider.utils.errors import EmptyDataError

    try:
        payload = await fetch_irs_bulletin(day, use_cache=use_cache)
        nodes = bulletin_nodes(payload, "FR007")
    except (OpenBBError, EmptyDataError):
        return []

    records: list[dict] = []

    for node in nodes:
        volume = node["volume"]
        notional = volume * 1_000_000.0 if volume else 1_000_000.0
        records.append(
            {
                "UPI FISN": "NA/Swap Fxd Flt CNY",
                "UPI Underlier Name": "CNY-CNREPOFIX=CFXS-Reuters",
                "Action type": "NEWT",
                "Event type": "TRAD",
                "Notional currency-Leg 1": "CNY",
                "Notional currency-Leg 2": "CNY",
                "Fixed rate-Leg 1": f"{node['par_rate']:.8f}",
                "Effective Date": day.isoformat(),
                "Expiration Date": (
                    day + timedelta(days=node["tenor_days"])
                ).isoformat(),
                "Notional amount-Leg 1": f"{notional:,.0f}",
                "Fixed rate day count convention-leg 1": "A005",
                "Fixed rate payment frequency period-Leg 1": "MNTH",
                "Fixed rate payment frequency period multiplier-Leg 1": "3",
                "Cleared": "Y",
                "Dissemination Timestamp": f"{day.isoformat()}T00:00:00Z",
            }
        )

    return records


def bulletin_reference_names(payload: dict) -> list[str]:
    """Return the reference rates the bulletin published, in its own order."""
    return [
        record.get("refIntrstRateNmEn") or record.get("refIntrstRateNm") or ""
        for record in payload.get("records") or []
    ]


def bulletin_nodes(payload: dict, reference_rate: str) -> list[dict]:
    """Return one reference rate's traded par nodes, sorted by tenor."""
    from openbb_core.provider.utils.errors import EmptyDataError

    wanted = normalize_reference(reference_rate)
    conventions = IRS_LEG_CONVENTIONS.get(wanted, {})

    for record in payload.get("records") or []:
        name = record.get("refIntrstRateNmEn") or record.get("refIntrstRateNm") or ""

        if normalize_reference(name) != wanted:
            continue

        nodes: list[dict] = []

        for row in record.get("rateList") or []:
            try:
                rate = float(row.get("wghtdAvgFxngRate"))
                days = int(row.get("sortNo"))
            except (TypeError, ValueError):
                continue

            try:
                volume = float(row.get("trdVol"))
            except (TypeError, ValueError):
                volume = None

            nodes.append(
                {
                    "tenor": (row.get("prd") or "").strip(),
                    "tenor_days": days,
                    "tenor_years": round(days / 365.0, 6),
                    "par_rate": rate / 100.0,
                    "volume": volume,
                    "is_fixing": False,
                    "day_count": conventions.get("day_count"),
                    "day_count_basis": conventions.get("basis"),
                    "payment_period_days": conventions.get("payment_period_days"),
                }
            )

        nodes.sort(key=lambda node: node["tenor_days"])

        return nodes

    available = ", ".join(name for name in bulletin_reference_names(payload) if name)

    raise EmptyDataError(
        f"'{reference_rate}' was not published in the bulletin for"
        f" {(payload.get('data') or {}).get('lastDate')}."
        + (f" Published reference rates: {available}." if available else "")
    )
