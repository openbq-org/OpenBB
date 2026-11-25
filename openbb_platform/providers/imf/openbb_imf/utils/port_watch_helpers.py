"""IMF Port Watch helpers."""

from __future__ import annotations

from datetime import UTC
from typing import Any

from async_lru import alru_cache

from openbb_imf.utils.constants import (
    CHOKEPOINTS_BASE_URL,
    CONTAINER_METRICS_BASE_URL,
    DAILY_TRADE_BASE_URL,
    DAILY_TRADE_REG_BASE_URL,
    DISRUPTIONS_DATABASE_URL,
    MONTHLY_TRADENOW_BASE_URL,
    SANKEY_DATA_URL,
)


async def _arcgis_query(
    base_url: str,
    where: str = "1=1",
    *,
    order_by: str | None = None,
    page_size: int = 1000,
    extra_params: str = "",
) -> list[dict[str, Any]]:
    """Paginate an ArcGIS FeatureServer query and return raw attribute dicts."""
    from urllib.parse import quote

    from openbb_core.app.model.abstract.error import OpenBBError
    from openbb_core.provider.utils.helpers import get_async_requests_session

    encoded_where = quote(where, safe="")
    order_clause = f"&orderByFields={quote(order_by, safe='')}" if order_by else ""
    base_query = (
        f"where={encoded_where}&outFields=*{order_clause}"
        f"&returnZ=true&resultRecordCount={page_size}"
        f"&maxRecordCountFactor=5&outSR=&f=json{extra_params}"
    )

    rows: list[dict[str, Any]] = []
    offset = 0
    async with await get_async_requests_session(timeout=120) as session:
        while True:
            url = f"{base_url}{base_query}&resultOffset={offset}"
            async with await session.get(url) as response:
                if response.status != 200:
                    raise OpenBBError(
                        f"ArcGIS query failed: {response.status} -> {url}"
                    )
                data = await response.json()
            features = data.get("features") or []
            for feat in features:
                attrs = feat.get("attributes") or {}
                if attrs:
                    rows.append(attrs)
            if not data.get("exceededTransferLimit") or not features:
                break
            offset += len(features)
    return rows


def _epoch_to_iso_date(value: Any) -> str | None:
    """Convert a millisecond-epoch integer to ``YYYY-MM-DD`` (or pass through strings)."""
    from datetime import datetime

    if value is None:
        return None
    if isinstance(value, str):
        return value[:10]
    if isinstance(value, (int, float)) and value > 1e10:
        return datetime.fromtimestamp(value / 1000, tz=UTC).strftime("%Y-%m-%d")
    return str(value)


def _normalize_ymd(row: dict[str, Any]) -> dict[str, Any]:
    """Replace ``year``/``month``/``day`` triplet with a single ``date`` string."""
    from contextlib import suppress
    from datetime import datetime

    if {"year", "month", "day"}.issubset(row):
        with suppress(TypeError, ValueError):
            row["date"] = datetime(
                int(row["year"]), int(row["month"]), int(row["day"])
            ).strftime("%Y-%m-%d")
    return {
        k: v
        for k, v in row.items()
        if k not in ("year", "month", "day", "ObjectId", "GlobalID")
    }


def list_countries() -> list[dict[str, str]]:
    """List available countries for IMF Port Watch.

    Returns
    -------
    list of dict
        A list of dictionaries with 'label' and 'value' for each country.
    """
    choices: list = []
    ports = get_ports()
    seen: set = set()

    for port in ports:
        if port["ISO3"] in seen:
            continue

        seen.add(port["ISO3"])
        choices.append(
            {
                "label": port["countrynoaccents"],
                "value": port["ISO3"],
            }
        )
    return choices


def map_port_country_code(country_code: str) -> str:
    """Map the 3-letter country code to the full country name.

    Parameters
    ----------
    country_code : str
        The 3-letter ISO country code (e.g., "USA" for the United States).

    Returns
    -------
    str
        The full country name, without accents, corresponding to the provided country code.
    """
    cc = country_code.upper()
    countries = list_countries()
    code_to_country = {country["value"]: country["label"] for country in countries}
    if cc not in code_to_country:
        raise ValueError("Country code is not supported by IMF Port Watch.")

    return code_to_country.get(cc, cc)


def get_port_ids_by_country(country_code: str) -> str:
    """Get all port IDs for a specific country. The country code should be a 3-letter ISO code.

    Parameters
    ----------
    country_code : str
        The 3-letter ISO country code (e.g., "USA" for the United States).

    Returns
    -------
    str
        A list of port IDs as a comma-separated string.
    """
    ports = get_ports()
    ports_ids: list = []
    for port in ports:
        if port["ISO3"] == country_code.upper():
            ports_ids.append(port["portid"])

    return ",".join(ports_ids)


def get_port_id_choices() -> list:
    """Get choices for selecting individual ports by ID.

    Returns
    -------
    list
        A list of dictionaries, with labels and values for each port ID.
    """
    choices: list = []
    ports = get_ports()

    for port in ports:
        choices.append(
            {
                "label": port["portname"],
                "value": port["portid"],
            }
        )
    return choices


@alru_cache(maxsize=25)
async def get_daily_chokepoint_data(
    chokepoint_id, start_date: str | None = None, end_date: str | None = None
) -> list:
    """Get the daily chokepoint data for a specific chokepoint and date range.

    Parameters
    ----------
    chokepoint_id : str
        The ID of the chokepoint (e.g., "chokepoint1"). 1-24 are valid IDs
    """
    from datetime import datetime  # noqa
    from openbb_core.app.model.abstract.error import OpenBBError
    from openbb_core.provider.utils.helpers import get_async_requests_session

    if start_date is not None and end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    if start_date is None and end_date is not None:
        start_date = "2019-01-01"

    def get_chokepoints_url(offset: int):
        """Construct the URL for fetching chokepoint data with offset."""
        nonlocal chokepoint_id
        return (
            (
                CHOKEPOINTS_BASE_URL
                + f"where=portid%20%3D%20%27{chokepoint_id.upper()}%27"
                + f"AND%20date%20>%3D%20TIMESTAMP%20%27{start_date}%2000%3A00%3A00%27"
                + f"%20AND%20date%20<%3D%20TIMESTAMP%20%27{end_date}%2000%3A00%3A00%27&"
                + f"outFields=*&orderByFields=date&returnZ=true&resultOffset={offset}&resultRecordCount=1000"
                + "&maxRecordCountFactor=5&outSR=&f=json"
            )
            if start_date is not None and end_date is not None
            else (
                CHOKEPOINTS_BASE_URL
                + f"where=portid%20%3D%20%27{chokepoint_id.upper()}%27&"
                + f"outFields=*&orderByFields=date&returnZ=true&resultOffset={offset}&resultRecordCount=1000"
                + "&maxRecordCountFactor=5&outSR=&f=json"
            )
        )

    offset: int = 0
    output: dict = {}
    url = get_chokepoints_url(offset)

    async with await get_async_requests_session() as session:
        async with await session.get(url) as response:
            data: dict = {}

            if response.status != 200:
                raise OpenBBError(f"Failed to fetch data: {response.status}")
            data = await response.json()

        if "features" in data:
            output = data.copy()

        while data.get("exceededTransferLimit") is True:
            offset += len(data["features"])
            url = get_chokepoints_url(offset)

            async with await session.get(url) as response:
                data = {}
                if response.status != 200:
                    raise OpenBBError(f"Failed to fetch data: {response.status}")
                data = await response.json()

            if "features" in data:
                output["features"].extend(data["features"])

        final_output: list = []

        for feature in output["features"]:
            date = datetime(
                feature["attributes"]["year"],
                feature["attributes"]["month"],
                feature["attributes"]["day"],
            ).strftime("%Y-%m-%d")
            final_output.append(
                {
                    "date": date,
                    **{
                        k: v
                        for k, v in feature["attributes"].items()
                        if k not in ["year", "month", "day", "date", "ObjectId"]
                    },
                }
            )

    return final_output


@alru_cache(maxsize=1)
async def get_all_daily_chokepoint_activity_data(
    start_date: str | None = None, end_date: str | None = None
) -> list:
    """Get the complete historical volume dataset for all chokepoints."""
    import asyncio  # noqa
    from openbb_core.app.model.abstract.error import OpenBBError

    chokepoints = [f"chokepoint{i}" for i in range(1, 25)]
    chokepoints_data: list = []

    async def _get_one_chokepoint_data(chokepoint_id):
        """Get the daily chokepoint data for a specific chokepoint."""
        try:
            data = await get_daily_chokepoint_data(chokepoint_id, start_date, end_date)
            chokepoints_data.extend(data)
        except Exception as e:
            raise OpenBBError(f"Failed to fetch data for {chokepoint_id}: {e}") from e

    try:
        gather_results = await asyncio.gather(
            *[_get_one_chokepoint_data(cp) for cp in chokepoints],
            return_exceptions=True,
        )

        for result in gather_results:
            if isinstance(result, (OpenBBError, Exception)):
                raise result

        if not chokepoints_data:
            raise OpenBBError("All requests were returned empty.")

        return chokepoints_data

    except Exception as e:
        raise OpenBBError(
            f"Error in fetching chokepoint data: {e} -> {e.args[0]}"
        ) from e


@alru_cache(maxsize=1)
async def get_all_daily_port_activity_data() -> list:
    """Get all port activity data as a bulk download CSV.

    Returns
    -------
    list
        A list of dictionaries, each representing a row of port activity data.
    """
    from io import StringIO  # noqa
    from openbb_core.app.model.abstract.error import OpenBBError
    from openbb_core.provider.utils.helpers import get_async_requests_session
    from pandas import read_csv, to_datetime

    url = (
        "https://hub.arcgis.com/api/v3/datasets/959214444157458aad969389b3ebe1a0_0/"
        + "downloads/data?format=csv&spatialRefId=4326&where=1%3D1"
    )
    content = ""
    try:
        async with (
            await get_async_requests_session(timeout=120) as session,
            await session.get(url) as response,
        ):
            if response.status != 200:
                raise OpenBBError(
                    f"Failed to fetch port activity data: {response.status} - {response.reason}"
                )
            if response.content is None:
                raise OpenBBError("No content returned from the request.")
            content = await response.text()

        df = read_csv(StringIO(content))
        df.date = to_datetime(df.date).dt.date
        df = df.drop(
            columns=[
                d
                for d in ["ObjectId", "GlobalID", "year", "month", "day"]
                if d in df.columns
            ]
        )

        return df.to_dict(orient="records")

    except Exception as e:
        raise OpenBBError(f"Error fetching port activity data: {e} -> {e.args}") from e


@alru_cache(maxsize=125)
async def get_daily_port_activity_data(
    port_id, start_date: str | None = None, end_date: str | None = None
) -> list:
    """Get the daily port activity data for a specific port ID.

    Parameters
    ----------
    port_id : str
        The port ID for which to fetch daily activity data.

    Returns
    -------
    list
        A list of dictionaries, each representing daily activity data for the specified port.
    """
    from datetime import datetime  # noqa
    from openbb_core.app.model.abstract.error import OpenBBError
    from openbb_core.provider.utils.helpers import get_async_requests_session

    if port_id is None:
        raise OpenBBError(
            ValueError("Either port_id or country_code must be provided.")
        )

    if start_date is not None and end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    if start_date is None and end_date is not None:
        start_date = "2019-01-01"

    def get_port_url(offset: int):
        """Construct the URL for fetching chokepoint data with offset."""
        nonlocal port_id, start_date, end_date
        return (
            (
                DAILY_TRADE_BASE_URL
                + f"where=portid%20%3D%20%27{port_id.upper()}%27&"
                + f"outFields=*&orderByFields=date&returnZ=true&resultOffset={offset}&resultRecordCount=1000"
                + "&maxRecordCountFactor=5&outSR=&f=json"
            )
            if start_date is None and end_date is None
            else (
                DAILY_TRADE_BASE_URL
                + f"where=portid%20%3D%20%27{port_id.upper()}%27%20"
                + f"AND%20date%20>%3D%20TIMESTAMP%20%27{start_date}%2000%3A00%3A00%27"
                + f"%20AND%20date%20<%3D%20TIMESTAMP%20%27{end_date}%2000%3A00%3A00%27&"
                + f"outFields=*&orderByFields=date&returnZ=true&resultOffset={offset}&resultRecordCount=1000"
                + "&maxRecordCountFactor=5&outSR=&f=json"
            )
        )

    offset: int = 0
    output: dict = {}
    url = get_port_url(offset)

    async with await get_async_requests_session() as session:
        async with await session.get(url) as response:
            data = {}

            if response.status != 200:
                raise OpenBBError(f"Failed to fetch data: {response.status}")
            data = await response.json()

        if "features" in data:
            output = data.copy()

        while data.get("exceededTransferLimit") is True:
            offset += len(data["features"])
            url = get_port_url(offset)

            async with await session.get(url) as response:
                data = {}
                if response.status != 200:
                    raise OpenBBError(f"Failed to fetch data: {response.status}")
                data = await response.json()

            if "features" in data:
                output["features"].extend(data["features"])

        final_output: list = []

        for feature in output["features"]:
            date = datetime(
                feature["attributes"]["year"],
                feature["attributes"]["month"],
                feature["attributes"]["day"],
            ).strftime("%Y-%m-%d")
            final_output.append(
                {
                    "date": date,
                    **{
                        k: v
                        for k, v in feature["attributes"].items()
                        if k not in ["year", "month", "day", "date", "ObjectId"]
                    },
                }
            )

    return final_output


@alru_cache(maxsize=1)
async def list_ports() -> list[dict[str, Any]]:
    """List all available ports from the IMF Port Watch dataset.

    Returns
    -------
    list[dict]
        A list of dictionaries, each representing a port with its details.
    """
    from openbb_core.app.model.abstract.error import OpenBBError
    from openbb_core.provider.utils.helpers import get_async_requests_session

    url = (
        "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/PortWatch_ports_database/"
        + "FeatureServer/0/query?where=1%3D1&outFields=countrynoaccents,portid,lon,lat,portname,ISO3,continent,fullname"
        + "+&returnGeometry=false&orderByFields=vessel_count_total%20DESC&outSR=&f=json"
    )
    ports: list[dict] = []

    try:
        async with (
            await get_async_requests_session() as session,
            await session.get(url) as response,
        ):
            if response.status != 200:
                raise OpenBBError(
                    f"Failed to fetch ports data: {response.status} - {response.reason}"
                )
            data = await response.json()

            for feature in data.get("features", []):
                ports.append(feature.get("attributes", {}))

        return ports

    except Exception as e:
        raise OpenBBError(f"Error fetching ports data: {e} -> {e.args}") from e


def _run_list_ports_sync() -> list[dict[str, Any]]:
    """Run ``list_ports`` synchronously in a worker thread."""
    import asyncio

    return asyncio.run(list_ports())


def get_ports() -> list[dict[str, Any]]:
    """Get the list of all ports synchronously."""
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(_run_list_ports_sync)
        return future.result()


def _date_where_clause(field: str, start_date: str | None, end_date: str | None) -> str:
    """Compose an ArcGIS ``WHERE`` clause restricting ``field`` to a date range."""
    clauses: list[str] = []
    if start_date:
        clauses.append(f"{field} >= TIMESTAMP '{start_date} 00:00:00'")
    if end_date:
        clauses.append(f"{field} <= TIMESTAMP '{end_date} 23:59:59'")
    if not clauses:
        return "1=1"
    return " AND ".join(clauses)


@alru_cache(maxsize=64)
async def get_country_daily_activity(
    iso3: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """Daily country-level maritime activity from ``Daily_Trade_Data_REG``."""
    code = iso3.strip().upper()
    where = _date_where_clause("date", start_date, end_date)
    where = f"ISO3 = '{code}'" + ("" if where == "1=1" else f" AND ({where})")
    rows = await _arcgis_query(DAILY_TRADE_REG_BASE_URL, where=where, order_by="date")
    return [_normalize_ymd(r) for r in rows]


@alru_cache(maxsize=64)
async def get_monthly_trade(
    iso3: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """Monthly TradeNow indices for an ISO3 country."""
    code = iso3.strip().upper()
    where = _date_where_clause("date", start_date, end_date)
    where = f"ISO3 = '{code}'" + ("" if where == "1=1" else f" AND ({where})")
    rows = await _arcgis_query(MONTHLY_TRADENOW_BASE_URL, where=where, order_by="date")
    out: list[dict[str, Any]] = []
    for r in rows:
        r["date"] = _epoch_to_iso_date(r.get("date"))
        out.append(_normalize_ymd(r))
    return out


@alru_cache(maxsize=64)
async def get_container_metrics(
    port_ids: tuple[str, ...] | None = None,
    metric: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """Container-specific port metrics from ``Container_Metrics`` in long format.

    Always returns ``[{metric, portid, date, value}]``. When ``port_ids`` is
    ``None``, every port column from the wide source row is emitted; pass a
    tuple of port ids (uppercase) to restrict the output.
    """
    where = _date_where_clause("date_in", start_date, end_date)
    if metric:
        where = f"metric = '{metric}'" + ("" if where == "1=1" else f" AND ({where})")
    rows = await _arcgis_query(
        CONTAINER_METRICS_BASE_URL, where=where, order_by="date_in"
    )
    keep = {p.upper() for p in port_ids} if port_ids else None
    skip = {
        "OBJECTID",
        "OBJECTID_1",
        "METRIC",
        "DATE",
        "DATE_IN",
        "GLOBALID",
        "YEAR",
        "MONTH",
        "DAY",
    }
    out: list[dict[str, Any]] = []
    for r in rows:
        date_str = _epoch_to_iso_date(r.get("date") or r.get("date_in"))
        metric_val = r.get("metric")
        for col, val in r.items():
            col_up = col.upper()
            if col_up in skip or not col_up.startswith("PORT"):
                continue
            if val is None:
                continue
            if keep is not None and col_up not in keep:
                continue
            out.append(
                {
                    "metric": metric_val,
                    "portid": col_up,
                    "date": date_str,
                    "value": val,
                }
            )
    return out


@alru_cache(maxsize=32)
async def get_disruption_events(
    iso3: str | None = None,
    eventtype: str | None = None,
    alertlevel: str | None = None,
    active_only: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """Disruption events from ``portwatch_disruptions_database``."""
    clauses: list[str] = []
    if iso3:
        clauses.append(f"country = '{iso3.strip().upper()}'")
    if eventtype:
        clauses.append(f"eventtype = '{eventtype}'")
    if alertlevel:
        clauses.append(f"alertlevel = '{alertlevel.upper()}'")
    if active_only:
        clauses.append("(todate IS NULL OR todate >= CURRENT_TIMESTAMP)")
    date_clause = _date_where_clause("fromdate", start_date, end_date)
    if date_clause != "1=1":
        clauses.append(date_clause)
    where = " AND ".join(clauses) if clauses else "1=1"
    rows = await _arcgis_query(
        DISRUPTIONS_DATABASE_URL, where=where, order_by="fromdate DESC"
    )
    for r in rows:
        for field in ("fromdate", "todate", "editdate"):
            if field in r:
                r[field] = _epoch_to_iso_date(r[field])
    return rows


@alru_cache(maxsize=32)
async def get_disruption_sankey_edges(event_id: int) -> list[dict[str, Any]]:
    """Capacity spillover edges for a disruption event."""
    where = f"eventid = {int(event_id)}"
    return await _arcgis_query(SANKEY_DATA_URL, where=where)


async def get_tradenow_region_choices() -> list[dict[str, str]]:
    """Distinct ``[{label: region, value: ISO3}]`` from ``Monthly_TradeNow``."""
    rows = await _arcgis_query(
        MONTHLY_TRADENOW_BASE_URL,
        where="ISO3 IS NOT NULL",
        extra_params="&returnDistinctValues=true&outFields=region,ISO3",
    )
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for r in rows:
        iso3 = r.get("ISO3")
        region = r.get("region") or iso3
        if not iso3 or iso3 in seen:
            continue
        seen.add(iso3)
        out.append({"label": str(region), "value": str(iso3)})
    return sorted(out, key=lambda c: c["label"])


async def get_container_port_choices() -> list[dict[str, str]]:
    """Distinct port columns from the wide ``Container_Metrics`` table."""
    rows = await _arcgis_query(
        CONTAINER_METRICS_BASE_URL, where="1=1", extra_params="&resultRecordCount=1"
    )
    if not rows:
        return []
    ignored = {"OBJECTID", "OBJECTID_1", "METRIC", "DATE", "DATE_IN", "GLOBALID"}
    ports = sorted(
        k.upper()
        for k in rows[0]
        if k.upper().startswith("PORT") and k.upper() not in ignored
    )
    name_map = await get_container_port_name_map()
    return [{"label": name_map.get(p, p), "value": p} for p in ports]


@alru_cache(maxsize=1)
async def get_container_port_name_map() -> dict[str, str]:
    """Map every container-metrics port id (e.g. ``PORT1065``) to a friendly name."""
    ports = await list_ports()
    out: dict[str, str] = {}
    for p in ports:
        pid = (p.get("portid") or "").upper()
        if not pid:
            continue
        out[pid] = p.get("fullname") or p.get("portname") or pid
    return out


async def get_sankey_event_choices() -> list[dict[str, str]]:
    """Distinct disruption events that have Sankey spillover edges."""
    rows = await _arcgis_query(
        DISRUPTIONS_DATABASE_URL,
        where="1=1",
        order_by="fromdate DESC",
        extra_params="&outFields=eventid,eventname,fromdate",
    )
    out: list[dict[str, str]] = []
    for r in rows:
        eid = r.get("eventid")
        if eid is None:
            continue
        name = r.get("eventname") or f"event {eid}"
        fromdate = _epoch_to_iso_date(r.get("fromdate")) or ""
        label = f"{name} ({fromdate})" if fromdate else str(name)
        out.append({"label": label, "value": str(eid)})
    return out
