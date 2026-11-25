"""OpenBB JODI Provider Module Helpers."""

import weakref
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

from openbb_core.app.model.abstract.error import OpenBBError

from openbb_jodi.utils.constants import (
    GAS_DOWNLOAD_URL,
    GAS_FILES_URL,
    OIL_TABLE_URLS,
)

if TYPE_CHECKING:
    import asyncio  # noqa
    from collections.abc import Generator, Mapping  # noqa
    from datetime import date as dateType  # noqa
    from pathlib import Path  # noqa
    from typing import IO  # noqa

    from pandas import DataFrame  # noqa

REVALIDATE_INTERVAL = 86400
PROBE_TIMEOUT = 60
MAX_RANGE_CONNECTIONS = 16
MIN_RANGE_CHUNK = 2 * 1024 * 1024
INGEST_CHUNK_ROWS = 1_000_000
PARTITION_ROW_GROUP = 32768

EXPECTED_COLUMNS: list = [
    "REF_AREA",
    "TIME_PERIOD",
    "ENERGY_PRODUCT",
    "FLOW_BREAKDOWN",
    "UNIT_MEASURE",
    "OBS_VALUE",
    "ASSESSMENT_CODE",
]

# Dimension columns are categorical: the full tables have millions of rows.
CSV_DTYPES: dict = {
    "REF_AREA": "category",
    "TIME_PERIOD": "category",
    "ENERGY_PRODUCT": "category",
    "FLOW_BREAKDOWN": "category",
    "UNIT_MEASURE": "category",
    "OBS_VALUE": str,
    "ASSESSMENT_CODE": "category",
}
# TIME_PERIOD stays a plain string in partitions so parquet range filters
# compare lexicographically ("YYYY-MM" sorts chronologically).
PARTITION_DTYPES: dict = {**CSV_DTYPES, "TIME_PERIOD": str, "OBS_VALUE": float}

# Per-event-loop download locks and prefetch tasks: locks coalesce concurrent
# requests for the same table, and asyncio primitives cannot cross loops.
# Weak keys drop entries when a loop is garbage collected.
_DOWNLOAD_LOCKS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_PREFETCH_TASKS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _download_lock(table: str) -> "asyncio.Lock":
    """Get the download lock for a table on the running event loop."""
    import asyncio

    loop = asyncio.get_running_loop()
    locks = _DOWNLOAD_LOCKS.setdefault(loop, {})
    if table not in locks:
        locks[table] = asyncio.Lock()
    return locks[table]


def _lock_handle_nt(handle) -> None:  # pragma: no cover - Windows-only
    """Take an exclusive byte lock, waiting for a concurrent holder."""
    import msvcrt  # noqa
    from time import sleep

    handle.seek(0)
    while True:
        try:
            msvcrt.locking(  # ty: ignore[unresolved-attribute]
                handle.fileno(),
                msvcrt.LK_NBLCK,  # ty: ignore[unresolved-attribute]
                1,
            )
            return
        except OSError:
            sleep(0.05)


def _unlock_handle_nt(handle) -> None:  # pragma: no cover - Windows-only
    """Release the exclusive byte lock."""
    import msvcrt

    handle.seek(0)
    msvcrt.locking(  # ty: ignore[unresolved-attribute]
        handle.fileno(),
        msvcrt.LK_UNLCK,  # ty: ignore[unresolved-attribute]
        1,
    )


def _lock_handle_posix(handle) -> None:  # pragma: no cover - POSIX-only
    """Take an exclusive flock, waiting for a concurrent holder."""
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)  # ty: ignore[unresolved-attribute]


def _unlock_handle_posix(handle) -> None:  # pragma: no cover - POSIX-only
    """Release the exclusive flock."""
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # ty: ignore[unresolved-attribute]


def acquire_table_lock(table: str) -> "IO[bytes]":
    """Acquire the cross-process lock for a table; released by release_table_lock.

    The asyncio locks only coalesce work within one event loop; this file lock
    serializes refreshes of the same table across processes and loops, and is
    released by the OS if the holder dies.
    """
    import os

    lock = _lock_handle_nt if os.name == "nt" else _lock_handle_posix
    path = get_cache_directory() / f"{table}.lock"
    handle = open(path, "a+b")  # noqa: SIM115
    try:
        lock(handle)
    except BaseException:
        handle.close()
        raise
    return handle


def release_table_lock(handle: "IO[bytes]") -> None:
    """Release a cross-process table lock."""
    import os

    unlock = _unlock_handle_nt if os.name == "nt" else _unlock_handle_posix
    try:
        unlock(handle)
    finally:
        handle.close()


def clear_table_temp(table: str) -> None:
    """Remove staging leftovers and spent archives; the caller holds the table lock."""
    import shutil

    for path in get_cache_directory().glob(f"{table}.*.tmp"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    # A raw archive left by an interrupted run, or by an older version.
    (get_cache_directory() / f"{table}.zip").unlink(missing_ok=True)


def get_cache_directory() -> "Path":
    """Get the JODI cache directory, creating it if needed."""
    from pathlib import Path  # noqa
    from openbb_core.app.utils import get_user_cache_directory

    cache_dir = Path(get_user_cache_directory()) / "jodi"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def table_directory(table: str) -> "Path":
    """Get the partition directory for a table."""
    return get_cache_directory() / table


def partition_filename(name: str) -> str:
    """Get a partition's file name; parquet is portable across pandas versions."""
    return f"{name}.parquet"


def write_cached_raw(filename: str, content: bytes) -> None:
    """Write bytes to a path under the cache directory, atomically."""
    import os  # noqa
    from secrets import token_hex

    path = get_cache_directory() / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{os.getpid()}{token_hex(4)}.tmp")
    temp_path.write_bytes(content)
    os.replace(temp_path, path)


async def request_range(
    url: str,
    timeout: int,
    start: int | None = None,
    end: int | None = None,
    validator: str | None = None,
) -> "tuple[int, Mapping, bytes]":
    """Make one request, optionally for a byte range guarded by a validator."""
    from openbb_core.provider.utils.helpers import amake_request

    # The JODI web server responds with a 406 error without a browser-like User-Agent.
    headers = {"User-Agent": "Mozilla/5.0"}
    if start is not None:
        headers["Range"] = f"bytes={start}-{end}"
        if validator:
            # A mid-transfer file replacement returns 200 instead of a torn 206.
            headers["If-Range"] = validator

    async def response_callback(response, _):
        """Read the status, response headers, and body."""
        return (response.status, response.headers, await response.read())

    response = await amake_request(
        url, timeout=timeout, response_callback=response_callback, headers=headers
    )
    return cast("tuple[int, Mapping, bytes]", response)


def source_meta(status: int, headers: "Mapping") -> dict:
    """Extract the cache validators from response headers."""
    total_text = str(headers.get("Content-Range", "")).rpartition("/")[2]
    if not total_text.isdigit() and status == 200:
        total_text = str(headers.get("Content-Length", ""))
    return {
        "etag": headers.get("ETag"),
        "last_modified": headers.get("Last-Modified"),
        "size": int(total_text) if total_text.isdigit() else 0,
    }


def _range_part_ok(part, start: int, end: int) -> bool:
    """Check one gathered range response for usability."""
    if isinstance(part, BaseException):
        return False
    status, _, body = part
    return status == 206 and len(body) == end - start + 1


async def download(url: str, timeout: int = 600) -> "tuple[bytes, dict]":
    """Download a file with its cache validators, using concurrent byte ranges.

    The JODI web server throttles per connection; segmented requests multiply
    the download throughput. Any unusable or failed segment falls back to one
    plain request.
    """
    import asyncio  # noqa
    from math import ceil

    status, headers, body = await request_range(url, timeout, 0, 0)
    if status == 200:
        # Ranges are not supported: the probe returned the complete file.
        return body, source_meta(status, headers)
    if status != 206:
        raise OpenBBError(f"Failed to download {url} -> Status Code: {status}")

    meta = source_meta(status, headers)
    total = meta["size"]
    if total:
        validator = meta["etag"] or meta["last_modified"] or None
        chunk_size = ceil(
            total / min(MAX_RANGE_CONNECTIONS, max(1, ceil(total / MIN_RANGE_CHUNK)))
        )
        offsets = [
            (start, min(start + chunk_size, total) - 1)
            for start in range(0, total, chunk_size)
        ]
        parts = await asyncio.gather(
            *(
                request_range(url, timeout, start, end, validator)
                for start, end in offsets
            ),
            return_exceptions=True,
        )
        if all(
            _range_part_ok(part, start, end)
            for part, (start, end) in zip(parts, offsets)
        ):
            return (
                b"".join(cast("tuple", part)[2] for part in parts),
                meta,
            )

    # The range responses were unusable: fall back to one full request.
    status, headers, body = await request_range(url, timeout)
    if status != 200:
        raise OpenBBError(f"Failed to download {url} -> Status Code: {status}")
    return body, source_meta(status, headers)


async def probe_source(url: str) -> dict | None:
    """Get the source file's current cache validators, None when unreachable."""
    try:
        status, headers, _ = await request_range(url, PROBE_TIMEOUT, 0, 0)
    except Exception:
        # The revalidation probe must never break a cached read.
        return None
    if status in (200, 206):
        return source_meta(status, headers)
    return {}


def source_unchanged(cached: dict, probed: dict) -> bool:
    """Compare cache validators, strongest first."""
    for key in ("etag", "last_modified", "size"):
        ours, theirs = cached.get(key), probed.get(key)
        if ours and theirs:
            return ours == theirs
    return False


def read_manifest(table: str) -> dict | None:
    """Read a table's cache manifest, None when missing or unreadable."""
    import json

    path = table_directory(table) / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(manifest, dict)
        or "source" not in manifest
        or "partitions" not in manifest
    ):
        return None
    return manifest


def write_manifest(table: str, manifest: dict) -> None:
    """Write a table's cache manifest."""
    import json

    write_cached_raw(f"{table}/manifest.json", json.dumps(manifest).encode("utf-8"))


def manifest_is_fresh(manifest: dict) -> bool:
    """Check whether a manifest was validated within the revalidation interval."""
    from time import time

    return time() - manifest.get("checked_at", 0) <= REVALIDATE_INTERVAL


def bump_checked_at(table: str, snapshot: dict) -> dict:
    """Refresh a manifest's checked_at without clobbering a concurrent refresh."""
    from time import time

    handle = acquire_table_lock(table)
    try:
        current = read_manifest(table)
        if current is not None and current.get("source") != snapshot.get("source"):
            # A concurrent refresh installed a newer manifest: keep it.
            return current
        manifest = current or snapshot
        manifest["checked_at"] = time()
        write_manifest(table, manifest)
        return manifest
    finally:
        release_table_lock(handle)


@contextmanager
def open_archive_csv(path: "Path") -> "Generator":
    """Open the CSV stream inside a raw source file, unzipping when needed."""
    import zipfile

    with open(path, "rb") as handle:
        if handle.read(4) == b"PK\x03\x04":
            handle.seek(0)
            try:
                archive = zipfile.ZipFile(handle)
            except zipfile.BadZipFile as exc:
                raise OpenBBError(f"The JODI archive is unreadable. -> {exc}") from exc
            with archive:
                members = [n for n in archive.namelist() if n.lower().endswith(".csv")]
                if not members:
                    raise OpenBBError("No CSV member was found in the JODI archive.")
                with archive.open(members[0]) as stream:
                    yield stream
        else:
            handle.seek(0)
            yield handle


def clean_chunk(chunk: "DataFrame") -> "DataFrame":
    """Validate a parsed CSV chunk and drop the non-numeric observations."""
    from pandas import to_numeric

    if list(chunk.columns) != EXPECTED_COLUMNS:
        raise OpenBBError(
            "Unexpected JODI file format."
            + f" Expected columns: {EXPECTED_COLUMNS} Got: {list(chunk.columns)}"
        )
    chunk["OBS_VALUE"] = to_numeric(chunk["OBS_VALUE"], errors="coerce")
    return chunk[chunk["OBS_VALUE"].notna()]


def ingest_table(table: str, source_path: "Path") -> dict[str, list[str]]:
    """Split a raw source file into per-product-and-flow partition files.

    The CSV is streamed in chunks: the full table is never held in memory.
    The caller holds the table lock.
    """
    import os  # noqa
    import shutil
    from secrets import token_hex
    from time import sleep

    from pandas import read_csv

    directory = table_directory(table)
    staging = directory.with_name(f"{directory.name}.{os.getpid()}{token_hex(4)}.tmp")
    staging.mkdir(parents=True)
    partitions: dict[str, list[str]] = {}
    try:
        with open_archive_csv(source_path) as stream:
            try:
                for chunk in read_csv(
                    stream, dtype=CSV_DTYPES, chunksize=INGEST_CHUNK_ROWS
                ):
                    groups = clean_chunk(chunk).groupby(
                        ["ENERGY_PRODUCT", "FLOW_BREAKDOWN"],
                        observed=True,
                        sort=False,
                    )
                    for key, rows in groups:
                        product, flow = cast("tuple[str, str]", key)
                        name = f"{product}_{flow}"
                        rows.to_csv(
                            staging / f"{name}.csv",
                            mode="a",
                            header=name not in partitions,
                            index=False,
                        )
                        partitions[name] = [str(product), str(flow)]
            except ValueError as exc:
                raise OpenBBError(f"Unexpected JODI file format. -> {exc}") from exc
        if not partitions:
            # Committing an empty table would destroy the existing good cache.
            raise OpenBBError("The JODI source file contains no observations.")
        for name in partitions:
            csv_path = staging / f"{name}.csv"
            # Sorting groups each country into contiguous row groups, so the
            # parquet statistics prune non-matching row groups at read time.
            read_csv(csv_path, dtype=PARTITION_DTYPES).sort_values(
                ["REF_AREA", "TIME_PERIOD"]
            ).to_parquet(
                staging / partition_filename(name),
                engine="pyarrow",
                index=False,
                row_group_size=PARTITION_ROW_GROUP,
            )
            csv_path.unlink()
        for attempt in range(3):
            try:
                if directory.exists():
                    shutil.rmtree(directory)
                os.replace(staging, directory)
                break
            except OSError:
                # A reader may hold a partition file open (Windows).
                if attempt == 2:
                    raise
                sleep(0.25)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return partitions


def store_table(table: str, url: str, raw: bytes, meta: dict) -> dict:
    """Ingest downloaded bytes into partitions and write the manifest.

    The caller holds the table lock. The raw archive is deleted after ingest:
    the partitions are the cache.
    """
    import os  # noqa
    from secrets import token_hex
    from time import time

    directory = get_cache_directory()
    temp_path = directory / f"{table}.zip.{os.getpid()}{token_hex(4)}.tmp"
    temp_path.write_bytes(raw)
    try:
        partitions = ingest_table(table, temp_path)
    finally:
        temp_path.unlink(missing_ok=True)
    manifest = {
        "source": {"url": url, **meta},
        "checked_at": time(),
        "partitions": partitions,
    }
    write_manifest(table, manifest)
    return manifest


async def resolve_source_url(table: str) -> str:
    """Get a table's current download URL; the gas URL rotates per publication."""
    import json

    if table != "gas_world":
        return OIL_TABLE_URLS[table.removeprefix("oil_")]
    listing, _ = await download(GAS_FILES_URL)
    info = json.loads(listing)
    files = [
        f
        for f in info.get("files", [])
        if f.get("format") == "CSV" and not f.get("ignore")
    ]
    if not files:
        raise OpenBBError("No CSV file is listed by the JODI-Gas publisher API.")
    return GAS_DOWNLOAD_URL.format(
        publication_id=info.get("publicationId"), filename=files[0].get("filename")
    )


async def source_changed(table: str, manifest: dict) -> bool | None:
    """Check a cached table against the source: True/False, or None if unknowable."""
    url = manifest["source"]["url"]
    if table == "gas_world":
        try:
            url = await resolve_source_url(table)
        except (OpenBBError, ValueError):
            return None
        if url != manifest["source"]["url"]:
            return True  # a new publication is listed
    probed = await probe_source(url)
    if not probed:
        # Unreachable, or an HTTP error status: keep serving the cache.
        return None
    return not source_unchanged(manifest["source"], probed)


async def refresh_table(table: str, use_cache: bool = True) -> dict:
    """Download a table's source archive and rebuild its partitioned cache.

    Ingest and file I/O run in a thread so the event loop stays responsive;
    the cross-process table lock is held for the whole refresh.
    """
    import asyncio

    handle = await asyncio.to_thread(acquire_table_lock, table)
    try:
        # A concurrent process may have refreshed while this one waited.
        manifest = read_manifest(table) if use_cache else None
        if manifest is not None and manifest_is_fresh(manifest):
            return manifest
        await asyncio.to_thread(clear_table_temp, table)
        url = await resolve_source_url(table)
        raw, meta = await download(url)
        return await asyncio.to_thread(store_table, table, url, raw, meta)
    finally:
        await asyncio.to_thread(release_table_lock, handle)


async def ensure_table(table: str, use_cache: bool = True) -> dict:
    """Get a table's cache manifest, revalidating or downloading as needed.

    A cached table is revalidated against the source's validators at most once
    per day; the archive is downloaded again only when the source has changed.
    A failed revalidation or refresh serves the cached table instead of erroring.
    """
    import asyncio

    manifest = read_manifest(table) if use_cache else None
    if manifest is not None and manifest_is_fresh(manifest):
        return manifest
    async with _download_lock(table):
        # A concurrent request may have refreshed the table while waiting.
        manifest = read_manifest(table) if use_cache else None
        if manifest is not None and manifest_is_fresh(manifest):
            return manifest
        if manifest is not None:
            changed = await source_changed(table, manifest)
            if not changed:
                # Unchanged, or the source could not be checked: keep the cache.
                return await asyncio.to_thread(bump_checked_at, table, manifest)
        try:
            return await refresh_table(table, use_cache)
        except Exception:
            if manifest is not None:
                # The refresh failed but a readable table is on disk: serve it.
                return await asyncio.to_thread(bump_checked_at, table, manifest)
            raise


def partition_filters(
    countries: set[str] | None,
    units: set[str] | None,
    start_date: "dateType | None",
    end_date: "dateType | None",
) -> list | None:
    """Build parquet predicate-pushdown filters for the in-file dimensions."""
    filters: list = []
    if countries is not None:
        filters.append(("REF_AREA", "in", sorted(countries)))
    if units is not None:
        filters.append(("UNIT_MEASURE", "in", sorted(units)))
    if start_date is not None:
        filters.append(("TIME_PERIOD", ">=", start_date.strftime("%Y-%m")))
    if end_date is not None:
        filters.append(("TIME_PERIOD", "<=", end_date.strftime("%Y-%m")))
    return filters or None


def load_partitions(
    table: str,
    product_codes: set[str] | None,
    flow_codes: set[str] | None,
    manifest: dict,
    countries: set[str] | None = None,
    units: set[str] | None = None,
    start_date: "dateType | None" = None,
    end_date: "dateType | None" = None,
) -> "DataFrame | None":
    """Read the partition slices for the requested codes, None on a broken cache.

    The partition files select the product and flow; the country, unit, and
    period predicates push down into the parquet reads.
    """
    from pandas import DataFrame, concat, read_parquet

    filters = partition_filters(countries, units, start_date, end_date)
    frames: list[DataFrame] = []
    for name, (product, flow) in manifest["partitions"].items():
        if product_codes is not None and product not in product_codes:
            continue
        if flow_codes is not None and flow not in flow_codes:
            continue
        try:
            frame = read_parquet(
                table_directory(table) / partition_filename(name),
                engine="pyarrow",
                filters=filters,
            )
        except Exception:
            # Any unreadable partition invalidates the table cache.
            return None
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return DataFrame({column: [] for column in EXPECTED_COLUMNS})
    return concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]


async def get_table_slice(
    table: str,
    product_codes: set[str] | None,
    flow_codes: set[str] | None,
    use_cache: bool = True,
    countries: set[str] | None = None,
    units: set[str] | None = None,
    start_date: "dateType | None" = None,
    end_date: "dateType | None" = None,
) -> "DataFrame":
    """Get the requested slices of one JODI table, with predicate pushdown."""
    import asyncio
    from functools import partial

    load = partial(
        load_partitions,
        table,
        product_codes,
        flow_codes,
        countries=countries,
        units=units,
        start_date=start_date,
        end_date=end_date,
    )
    manifest = await ensure_table(table, use_cache)
    df = await asyncio.to_thread(load, manifest)
    if df is not None:
        return df
    async with _download_lock(table):
        # A concurrent request may have healed the table while waiting.
        manifest = read_manifest(table) or manifest
        df = await asyncio.to_thread(load, manifest)
        if df is not None:
            return df
        # Self-heal: the raw archive is not kept, so download fresh.
        healed = await refresh_table(table, use_cache=False)
        df = await asyncio.to_thread(load, healed)
        if df is None:
            raise OpenBBError(f"The cached JODI table '{table}' could not be read.")
        return df


async def prefetch_tables() -> None:
    """Warm the partitioned cache for every JODI table."""
    import asyncio

    await asyncio.gather(
        ensure_table("oil_primary"),
        ensure_table("oil_secondary"),
        ensure_table("gas_world"),
        return_exceptions=True,
    )


def start_prefetch() -> None:
    """Start one background prefetch of all tables per event loop."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = _PREFETCH_TASKS.get(loop)
    if task is None or task.done():
        _PREFETCH_TASKS[loop] = loop.create_task(prefetch_tables())


def apply_filters(
    df: "DataFrame",
    countries: set[str] | None,
    products: set[str] | None,
    flows: set[str] | None,
    units: set[str] | None,
    start_date: "dateType",
    end_date: "dateType",
) -> "DataFrame":
    """Filter a JODI DataFrame by dimension codes and period."""
    if countries is not None:
        df = df[df["REF_AREA"].isin(countries)]
    if products is not None:
        df = df[df["ENERGY_PRODUCT"].isin(products)]
    if flows is not None:
        df = df[df["FLOW_BREAKDOWN"].isin(flows)]
    if units is not None:
        df = df[df["UNIT_MEASURE"].isin(units)]
    # The period filter runs on the reduced frame: TIME_PERIOD is categorical.
    period = df["TIME_PERIOD"].astype(str)
    df = df[
        (period >= start_date.strftime("%Y-%m"))
        & (period <= end_date.strftime("%Y-%m"))
    ]
    return df.reset_index(drop=True)


def normalize_country_names(v) -> list[str]:
    """Normalize country input into snake names, accepting names or ISO codes."""
    from openbb_jodi.utils.constants import CODE_TO_COUNTRY, COUNTRIES

    items = v if isinstance(v, list) else str(v).split(",")
    result: list[str] = []
    for item in items:
        country = str(item).strip().lower().replace(" ", "_")
        if country in COUNTRIES:
            result.append(country)
        elif country.upper() in CODE_TO_COUNTRY:
            result.append(CODE_TO_COUNTRY[country.upper()])
        else:
            raise OpenBBError(
                f"Invalid country: '{item}'. Valid values are: {list(COUNTRIES)}"
            )
    return list(dict.fromkeys(result))


def validate_country_param(v, multiple: bool, default: str | None) -> str | None:
    """Validate a country query parameter."""
    if not v:
        return default
    names = normalize_country_names(v)
    if not multiple and len(names) > 1:
        raise OpenBBError("Only one country can be selected for this endpoint.")
    return ",".join(names)


def normalize_token(v, default: str) -> str:
    """Normalize a single-select token parameter."""
    if not v:
        return default
    return str(v).strip().lower().replace(" ", "_")


def resolve_date_range(start_date, end_date, start_year: int) -> tuple:
    """Apply the full-history default date range and check the order."""
    from datetime import date

    start_date = start_date or date(start_year, 1, 1)
    end_date = end_date or date.today()
    if start_date > end_date:
        raise OpenBBError("The start_date must be on, or before, the end_date.")
    return start_date, end_date


def check_oil_dates(start_date, end_date) -> None:
    """Check the date range against the JODI-Oil data coverage."""
    from openbb_jodi.utils.constants import OIL_START_YEAR

    if end_date.year < OIL_START_YEAR:
        raise OpenBBError(
            f"No JODI-Oil data is available between {start_date} and {end_date}."
            + f" The data starts in {OIL_START_YEAR}."
        )


def check_gas_dates(start_date, end_date) -> None:
    """Check the date range against the JODI-Gas data coverage."""
    from openbb_jodi.utils.constants import GAS_START_YEAR

    if end_date.year < GAS_START_YEAR:
        raise OpenBBError(
            f"No JODI-Gas data is available between {start_date} and {end_date}."
            + f" The data starts in {GAS_START_YEAR}."
        )


async def get_filtered_oil(
    tables: list[str],
    countries: set[str] | None,
    product_codes: set[str],
    flow_codes: set[str],
    unit_codes: set[str],
    start_date,
    end_date,
    use_cache: bool = True,
) -> list[dict]:
    """Get filtered JODI-Oil records for the requested view."""
    import asyncio  # noqa
    from openbb_core.provider.utils.errors import EmptyDataError
    from pandas import concat

    check_oil_dates(start_date, end_date)
    frames = await asyncio.gather(
        *(
            get_table_slice(
                f"oil_{table}",
                product_codes,
                flow_codes,
                use_cache,
                countries=countries,
                units=unit_codes,
                start_date=start_date,
                end_date=end_date,
            )
            for table in tables
        )
    )
    frames = [frame for frame in frames if not frame.empty] or frames[:1]
    df = frames[0] if len(frames) == 1 else concat(frames, ignore_index=True)
    df = apply_filters(
        df, countries, product_codes, flow_codes, unit_codes, start_date, end_date
    )
    if df.empty:
        raise EmptyDataError("No results were found with the given query parameters.")
    return df.to_dict(orient="records")


async def get_filtered_gas(
    countries: set[str] | None,
    flow_codes: set[str],
    unit_codes: set[str],
    start_date,
    end_date,
    use_cache: bool = True,
) -> list[dict]:
    """Get filtered JODI-Gas records for the requested view."""
    from openbb_core.provider.utils.errors import EmptyDataError

    check_gas_dates(start_date, end_date)
    df = await get_table_slice(
        "gas_world",
        None,
        flow_codes,
        use_cache,
        countries=countries,
        units=unit_codes,
        start_date=start_date,
        end_date=end_date,
    )
    df = apply_filters(
        df, countries, None, flow_codes, unit_codes, start_date, end_date
    )
    if df.empty:
        raise EmptyDataError("No results were found with the given query parameters.")
    return df.to_dict(orient="records")


def _to_wide(df, columns: str, column_order: list[str]) -> list[dict]:
    """Pivot filtered records into date rows with the given column order."""
    from datetime import date

    wide = (
        df.pivot_table(
            index="TIME_PERIOD", columns=columns, values="OBS_VALUE", aggfunc="first"
        )
        .reindex(columns=[c for c in column_order if c in df[columns].unique()])
        .sort_index()
        .reset_index()
    )
    wide = wide.astype(object).where(wide.notna(), other=None)
    records = wide.to_dict(orient="records")
    for row in records:
        row["date"] = date.fromisoformat(f"{row.pop('TIME_PERIOD')}-01")
    return [{"date": row.pop("date"), **row} for row in records]


def build_field_table(
    records: list[dict], code_column: str, field_map: dict[str, str]
) -> list[dict]:
    """Build date rows with one typed field per item code."""
    from pandas import DataFrame

    df = DataFrame(records)
    df["field"] = df[code_column].map(field_map)
    return _to_wide(df, "field", list(dict.fromkeys(field_map.values())))


def build_country_table(records: list[dict]) -> list[dict]:
    """Build date rows with one field per country, alphabetical."""
    from pandas import DataFrame

    from openbb_jodi.utils.constants import CODE_TO_COUNTRY

    df = DataFrame(records)
    df["country"] = df["REF_AREA"].map(lambda c: CODE_TO_COUNTRY.get(c, c))
    return _to_wide(df, "country", sorted(df["country"].unique()))


def build_assessments(
    records: list[dict], code_column: str, name_map: dict[str, str]
) -> dict[str, str]:
    """Get the most recent JODI assessment label for each series."""
    from openbb_jodi.utils.constants import ASSESSMENT_LABELS

    assessments: dict[str, str] = {}
    for row in sorted(records, key=lambda r: str(r["TIME_PERIOD"])):
        key = name_map.get(row[code_column], row[code_column])
        label = ASSESSMENT_LABELS.get(str(row["ASSESSMENT_CODE"]))
        if label:
            assessments[key] = label
    return assessments
