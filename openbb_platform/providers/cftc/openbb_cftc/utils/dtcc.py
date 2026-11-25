"""DTCC Public Price Dissemination client."""

from collections.abc import Callable, Iterable, Iterator
from datetime import (
    UTC,
    date as dateType,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openbb_cftc.utils.store import SliceRecords

MAX_LOOKBACK_DAYS = 10

MANIFEST_TTL_SECONDS = 3600


def normalize_asset_class(asset_class: str) -> str:
    """Map an asset class key to its PPD path segment."""
    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_cftc.utils.constants import ASSET_CLASSES

    key = (asset_class or "").strip().lower()

    if key not in ASSET_CLASSES:
        raise OpenBBError(
            f"Invalid asset class: '{asset_class}'."
            + " Valid asset classes are: "
            + ", ".join(ASSET_CLASSES)
        )

    return ASSET_CLASSES[key]


def qualified_keys(record: dict) -> dict:
    """Asset-class-qualified identifiers - 19-digit ids exceed IEEE-754 precision."""
    asset = (record.get("Asset Class") or "NA").strip() or "NA"
    keys: dict = {}

    for source, target in (
        ("Dissemination Identifier", "Trade Key"),
        ("Original Dissemination Identifier", "Original Trade Key"),
    ):
        value = (record.get(source) or "").strip()

        if value:
            keys[target] = f"{asset}:{value}"

    return keys


async def get_manifest(asset_class: str) -> list[dict]:
    """Fetch the cumulative-slice manifest for an asset class, caching it briefly."""
    from datetime import datetime

    from openbb_core.app.model.abstract.error import OpenBBError
    from openbb_core.provider.utils.helpers import amake_request

    from openbb_cftc.utils import store
    from openbb_cftc.utils.constants import JURISDICTION, PPD_API_URL

    juris = JURISDICTION
    asset = normalize_asset_class(asset_class)
    cached = store.get_manifest(juris, asset)

    if cached is not None:
        fetched_at = datetime.fromisoformat(cached["fetched_at"])
        age = (datetime.now(UTC) - fetched_at).total_seconds()

        if age < MANIFEST_TTL_SECONDS:
            return cached["payload"]

    url = f"{PPD_API_URL}/cumulative/{juris}/{asset}"

    try:
        response = await amake_request(url)
    except Exception as exc:  # noqa: BLE001
        if cached is not None:
            return cached["payload"]

        raise OpenBBError(
            f"Failed to fetch the PPD manifest from {url} -> {exc}"
        ) from exc

    if not response or not isinstance(response, list):
        if cached is not None:
            return cached["payload"]

        raise OpenBBError(f"No PPD manifest entries returned for {juris}/{asset}.")

    store.put_manifest(juris, asset, response)

    return response


def manifest_by_date(manifest: list[dict]) -> dict[str, dict]:
    """Index a manifest by its report date, parsed from the file name."""
    index: dict[str, dict] = {}

    for entry in manifest:
        name = entry.get("fileName") or ""
        stem = name.rsplit(".", 1)[0]
        parts = stem.split("_")

        if len(parts) < 3:
            continue

        year, month, day = parts[-3:]

        if not (year.isdigit() and month.isdigit() and day.isdigit()):
            continue

        index[f"{year}-{month}-{day}"] = entry

    return index


async def download_file(url: str, etag: str | None = None) -> tuple[bytes | None, dict]:
    """Download a file, returning ```` when the ETag still matches."""
    from typing import cast

    from openbb_core.app.model.abstract.error import OpenBBError
    from openbb_core.provider.utils.helpers import amake_request

    headers = {"If-None-Match": etag} if etag else {}

    async def _callback(response, _session):
        if response.status == 304:
            return {"not_modified": True}

        response.raise_for_status()

        return {
            "not_modified": False,
            "body": await response.read(),
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
        }

    try:
        result = cast(
            dict,
            await amake_request(url, headers=headers, response_callback=_callback),
        )
    except Exception as exc:  # noqa: BLE001
        raise OpenBBError(f"Failed to download {url} -> {exc}") from exc

    if result["not_modified"]:
        return None, {"etag": etag}

    return result["body"], {
        "etag": result["etag"],
        "last_modified": result["last_modified"],
    }


def iter_slice_csv(payload: bytes) -> Iterator[dict]:
    """Stream the CSV member of a slice zip as records."""
    import csv
    import io
    import zipfile

    from openbb_core.app.model.abstract.error import OpenBBError

    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise OpenBBError(
            f"The PPD payload is not a valid zip archive -> {exc}"
        ) from exc

    members = [name for name in archive.namelist() if name.lower().endswith(".csv")]

    if not members:
        raise OpenBBError("The PPD archive contains no CSV member.")

    def _rows() -> Iterator[dict]:
        with archive.open(members[0]) as member:
            text = io.TextIOWrapper(member, encoding="utf-8-sig", errors="replace")
            yield from csv.DictReader(text)

    return _rows()


def parse_slice_csv(payload: bytes) -> list[dict]:
    """Read the CSV member of a slice zip into records."""
    return list(iter_slice_csv(payload))


def _ingest_slice(
    asset: str, report_date: str, payload: bytes
) -> "SliceRecords | list[dict]":
    """Stream a slice payload into its parquet shard and return the shard view."""
    from openbb_cftc.utils import store

    store.write_slice_records(asset, report_date, iter_slice_csv(payload))
    view = store.slice_records(asset, report_date)

    if view is None:
        return parse_slice_csv(payload)

    return view


async def get_slice(
    asset_class: str,
    report_date: str,
    use_cache: bool = True,
) -> "SliceRecords | list[dict]":
    """Return one report date's slice records, revalidating any cached copy."""
    from datetime import datetime

    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_cftc.utils import store
    from openbb_cftc.utils.constants import JURISDICTION

    juris = JURISDICTION
    asset = normalize_asset_class(asset_class)
    cached = store.get_slice(juris, asset, report_date) if use_cache else None
    view = store.slice_records(asset, report_date) if use_cache else None
    is_closed = report_date < datetime.now(UTC).date().isoformat()
    is_final = bool(cached) and (cached.get("fetched_at") or "")[:10] > report_date

    if view is not None and is_closed and is_final:
        store.shed_slice_payload(juris, asset, report_date)

        return view

    manifest = await get_manifest(asset_class)
    entry = manifest_by_date(manifest).get(report_date)

    if entry is None:
        raise OpenBBError(
            f"No PPD file published for {juris}/{asset} on {report_date}."
            + " Cumulative files are retained for 366 days."
        )

    url = entry.get("fullFilePath") or ""

    if not use_cache:
        payload, _ = await download_file(url)

        return _ingest_slice(asset, report_date, payload or b"")

    etag = cached.get("etag") if cached and view is not None else None

    try:
        payload, validators = await download_file(url, etag=etag)
    except OpenBBError:
        if view is None:
            raise

        return view

    if payload is None and view is not None:
        return view

    if payload is None:
        raise OpenBBError(f"No payload returned for {url}.")

    store.put_slice(
        juris,
        asset,
        report_date,
        etag=validators.get("etag"),
        last_modified=validators.get("last_modified"),
    )

    return _ingest_slice(asset, report_date, payload)


async def get_available_dates(asset_class: str) -> list[str]:
    """Return the report dates available for an asset class."""
    manifest = await get_manifest(asset_class)

    return sorted(manifest_by_date(manifest))


async def get_rates_slice_for(
    report_date: str, currencies: list[str], use_cache: bool = True
) -> tuple[Iterable[dict], str]:
    """Return the most recent rates slice on or before a date holding OIS for each currency."""
    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_cftc.utils.constants import ois_fisn

    dates = await get_available_dates("rates")
    candidates = [day for day in dates if day <= report_date] or [dates[0]]
    wanted = {ois_fisn(c) for c in currencies}

    for rates_date in reversed(candidates[-MAX_LOOKBACK_DAYS:]):
        records = await get_slice("rates", rates_date, use_cache=use_cache)
        present = {(r.get("UPI FISN") or "").strip() for r in records}

        if wanted <= present:
            return await _append_todays_rates(
                records, rates_date, report_date, currencies, use_cache
            )

    raise OpenBBError(
        f"No rates file in the {MAX_LOOKBACK_DAYS} days to {candidates[-1]} priced "
        + ", ".join(sorted(currencies))
        + "."
    )


async def _append_todays_rates(
    records: Iterable[dict],
    rates_date: str,
    report_date: str,
    currencies: list[str],
    use_cache: bool,
) -> tuple[Iterable[dict], str]:
    """Append today's not-yet-published OIS prints from search to a published slice."""
    from datetime import datetime, timedelta

    from openbb_cftc.utils.constants import ois_fisn
    from openbb_cftc.utils.search import search_trades
    from openbb_cftc.utils.store import RecordChain

    today = datetime.now(UTC).date().isoformat()

    if not currencies or report_date < today or rates_date >= today:
        return records, rates_date

    from openbb_core.app.model.abstract.error import OpenBBError

    start = dateType.fromisoformat(rates_date) + timedelta(days=1)
    end = dateType.fromisoformat(today)
    extra: list[dict] = []

    for currency in currencies:
        try:
            extra += await search_trades(
                "rates",
                start_date=start,
                end_date=end,
                currency=currency,
                upi_short_name=ois_fisn(currency),
                use_cache=use_cache,
            )
        except OpenBBError:
            continue

    if not extra:
        return records, rates_date

    return RecordChain(records, extra), rates_date


async def get_latest_viable_slice(
    asset_class: str,
    is_viable: Callable[[Iterable[dict], dateType], bool],
    use_cache: bool = True,
    max_lookback: int = MAX_LOOKBACK_DAYS,
    end_date: str | None = None,
) -> tuple[Iterable[dict], str]:
    """Return the most recent report date whose records satisfy ``is_viable``."""
    from openbb_core.app.model.abstract.error import OpenBBError

    dates = await get_available_dates(asset_class)

    if end_date is not None:
        dates = [day for day in dates if day <= end_date]

    if not dates:
        raise OpenBBError(f"No PPD {asset_class} files are currently published.")

    candidates = dates[-max_lookback:]

    for report_date in reversed(candidates):
        records = await get_slice(asset_class, report_date, use_cache=use_cache)

        if is_viable(records, dateType.fromisoformat(report_date)):
            return records, report_date

    raise OpenBBError(
        f"No {asset_class} file in the {len(candidates)} days to {dates[-1]} held usable"
        " data for this query. Widen the filters, or pass an explicit date."
    )
