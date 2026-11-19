"""The FINRA traded-security list, classified by security type."""


def read_asset() -> dict:
    """Return the bundled security-type asset.

    Returns
    -------
    dict
        The classification of every symbol known at build time, and the
        symbols that could not be classified.
    """
    import gzip
    import json

    from openbb_finra.utils.generate_securities import ASSET_PATH

    try:
        return json.loads(gzip.decompress(ASSET_PATH.read_bytes()))
    except (OSError, ValueError):
        return {"securities": {}, "unresolved": []}


async def load_universe() -> dict[str, dict]:
    """Return every symbol FINRA published OTC or ATS volume for in its latest weeks.

    Returns
    -------
    dict[str, dict]
        The FINRA issue name, tier, and product type of each symbol.
    """
    import asyncio

    from openbb_finra.utils.client import query_api_session
    from openbb_finra.utils.generate_securities import (
        SUMMARY_TYPES,
        latest_weeks,
        merge_universe,
        universe_payload,
    )

    async with query_api_session() as api:
        weeks = latest_weeks(await api.partitions("otcMarket", "weeklySummary"))
        pages = await asyncio.gather(
            *(
                api.query(
                    "otcMarket",
                    "weeklySummary",
                    universe_payload(week, tier, summary_type),
                )
                for tier, week in sorted(weeks.items())
                for summary_type in SUMMARY_TYPES
            )
        )

    universe: dict[str, dict] = {}

    for rows in pages:
        merge_universe(universe, rows)

    return universe


async def list_securities() -> list[dict]:
    """Return every traded symbol with its FINRA and bundled classification details.

    Returns
    -------
    list[dict]
        One row per symbol, sorted by symbol.
    """
    from openbb_finra.utils.constants import MARKET_DATA_DETAIL_URL
    from openbb_finra.utils.generate_securities import CLASS_FIELDS

    universe = await load_universe()
    asset = read_asset()
    classes = asset.get("securities") or {}
    rows = []

    for symbol, finra in sorted(universe.items()):
        row = {
            "symbol": symbol,
            **finra,
            **dict(zip(CLASS_FIELDS, classes.get(symbol) or [])),
        }
        listing, performance = row.get("listing_market_id"), row.get("performance_id")
        row["url"] = (
            f"{MARKET_DATA_DETAIL_URL}?query={listing}:{performance}"
            if listing and performance
            else None
        )
        rows.append(row)

    return rows
