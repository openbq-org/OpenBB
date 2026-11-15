"""On-disk cache for DTCC PPD data, built on ``diskcache``."""
from datetime import UTC

SEARCH_INTRADAY_TTL_SECONDS = 300

_CACHES: dict = {}

_SIZE_LIMITS: dict[str, int] = {
    "blobs": 2**34,
    "queries": 2**33,
}

RECORD_ROW_GROUP_SIZE = 2048


def _cache_dir() -> str | None:
    """Return the on-disk cache directory, or None if it is not writable."""
    import os

    from openbb_core.app.utils import get_user_cache_directory

    path = os.path.join(get_user_cache_directory(), "cftc", "dtcc")

    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return None

    return path


def _cache(name: str):
    """Return the named diskcache, opening it once per directory, or None."""
    import os

    import diskcache

    base = _cache_dir()

    if not base:
        return None

    path = os.path.join(base, name)

    if path not in _CACHES:
        try:
            _CACHES[path] = diskcache.Cache(
                path, size_limit=_SIZE_LIMITS.get(name, 2**30)
            )
        except Exception:  # noqa: BLE001
            return None

    return _CACHES[path]


def close() -> None:
    """Close every open cache handle."""
    for cache in _CACHES.values():
        cache.close()

    _CACHES.clear()


def get_slice(jurisdiction: str, asset_class: str, report_date: str) -> dict | None:
    """Return a cached slice file's validators, or None if absent."""
    cache = _cache("blobs")

    if cache is None:
        return None

    return cache.get((jurisdiction, asset_class, report_date))


def put_slice(
    jurisdiction: str,
    asset_class: str,
    report_date: str,
    etag: str | None = None,
    last_modified: str | None = None,
) -> None:
    """Store a slice file's validators."""
    from datetime import datetime

    cache = _cache("blobs")

    if cache is None:
        return

    cache.set(
        (jurisdiction, asset_class, report_date),
        {
            "etag": etag,
            "last_modified": last_modified,
            "fetched_at": datetime.now(UTC).isoformat(),
        },
    )


def shed_slice_payload(jurisdiction: str, asset_class: str, report_date: str) -> None:
    """Drop a legacy cached payload, keeping the validators."""
    cache = _cache("blobs")

    if cache is None:
        return

    key = (jurisdiction, asset_class, report_date)
    meta = cache.get(key)

    if meta and "payload" in meta:
        cache.set(key, {k: v for k, v in meta.items() if k != "payload"})


def cached_dates(jurisdiction: str, asset_class: str) -> set:
    """Return the report dates already cached for a jurisdiction and asset class."""
    cache = _cache("blobs")

    if cache is None:
        return set()

    return {
        key[2]
        for key in cache.iterkeys()
        if key[0] == jurisdiction and key[1] == asset_class
    }


def get_curve(cache_key: str):
    """Return a cached curve by key, or None if absent."""
    cache = _cache("curves")

    if cache is None:
        return None

    return cache.get(cache_key)


def put_curve(cache_key: str, report_date: str, value) -> None:
    """Store a derived curve under a key."""
    cache = _cache("curves")

    if cache is None:
        return

    cache.set(cache_key, value)


def get_search_days(cache_key: str, dates: list[str]) -> dict[str, list]:
    """Return a search's cached records, by dissemination date."""
    cache = _cache("queries")

    if cache is None or not dates:
        return {}

    result: dict[str, list] = {}

    for day in dates:
        rows = cache.get((cache_key, day))

        if rows is not None:
            result[day] = rows

    return result


def put_search_days(cache_key: str, days: dict[str, list]) -> None:
    """Store a search's records, partitioned by dissemination date."""
    from datetime import datetime

    cache = _cache("queries")

    if cache is None or not days:
        return

    today = datetime.now(UTC).date().isoformat()

    with cache.transact():
        for day, rows in days.items():
            cache.set(
                (cache_key, day),
                rows,
                expire=None if day < today else SEARCH_INTRADAY_TTL_SECONDS,
            )


RESPONSE_TTL_SECONDS = 3600


def get_response(url: str):
    """Return a cached API response by its token-free URL, or None if absent."""
    cache = _cache("responses")

    if cache is None:
        return None

    return cache.get(url)


def put_response(url: str, payload) -> None:
    """Cache an API response under its token-free URL, with the response TTL."""
    cache = _cache("responses")

    if cache is None:
        return

    cache.set(url, payload, expire=RESPONSE_TTL_SECONDS)


def get_document(key: str):
    """Return a cached document by key, or None if absent."""
    cache = _cache("documents")

    if cache is None:
        return None

    return cache.get(key)


def put_document(key: str, value) -> None:
    """Store a document under a key, for as long as the key stays valid."""
    cache = _cache("documents")

    if cache is None:
        return

    cache.set(key, value)


def get_manifest(jurisdiction: str, asset_class: str) -> dict | None:
    """Return a cached manifest and when it was fetched, or None if absent."""
    cache = _cache("manifests")

    if cache is None:
        return None

    return cache.get((jurisdiction, asset_class))


def put_manifest(jurisdiction: str, asset_class: str, payload) -> None:
    """Store a manifest response, stamped with when it was fetched."""
    from datetime import datetime

    cache = _cache("manifests")

    if cache is None:
        return

    cache.set(
        (jurisdiction, asset_class),
        {
            "payload": payload,
            "fetched_at": datetime.now(UTC).isoformat(),
        },
    )


def _records_dir() -> str | None:
    """Return the parquet record-shard directory, or None if it is not writable."""
    import os

    base = _cache_dir()

    if not base:
        return None

    path = os.path.join(base, "record_shards")

    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return None

    return path


def _shard_file(asset: str, report_date: str, kind: str) -> str:
    """File name of one record shard."""
    return f"CFTC_{asset}_{kind}_{report_date}.parquet"


def _record_shards() -> list[str]:
    """Record shard paths, newest dissemination date first."""
    import glob
    import os

    directory = _records_dir()

    if not directory:
        return []

    paths = glob.glob(os.path.join(directory, "*.parquet"))

    return sorted(paths, key=lambda p: p.rsplit("_", 1)[-1], reverse=True)


def _normalize_rows(records: list[dict]) -> list[dict]:
    """Stringify record values so every shard shares an all-string schema."""
    return sorted(
        (
            {key: "" if value is None else str(value) for key, value in record.items()}
            for record in records
        ),
        key=lambda row: row.get("Dissemination Identifier", ""),
    )


def _write_shard(path: str, rows: list[dict]) -> None:
    """Atomically write one sorted record shard."""
    import os

    import pyarrow as pa
    import pyarrow.parquet as pq

    table = (
        pa.Table.from_pylist(rows)
        if rows
        else pa.table({"Dissemination Identifier": pa.array([], pa.string())})
    )
    tmp = f"{path}.tmp{os.getpid()}"
    pq.write_table(table, tmp, row_group_size=RECORD_ROW_GROUP_SIZE)
    os.replace(tmp, path)


def _stream_shard(path: str, records) -> None:
    """Atomically write a shard from an iterable, one row-group batch at a time."""
    import os

    import pyarrow as pa
    import pyarrow.parquet as pq

    tmp = f"{path}.tmp{os.getpid()}"
    writer = None
    schema = None
    batch: list[dict] = []

    try:
        for record in records:
            batch.append(
                {
                    key: "" if value is None else str(value)
                    for key, value in record.items()
                }
            )

            if len(batch) >= RECORD_ROW_GROUP_SIZE:
                if writer is None:
                    schema = pa.schema((name, pa.string()) for name in batch[0])
                    writer = pq.ParquetWriter(tmp, schema)

                writer.write_table(pa.Table.from_pylist(batch, schema=schema))
                batch.clear()

        if writer is None:
            schema = (
                pa.schema((name, pa.string()) for name in batch[0])
                if batch
                else pa.schema([("Dissemination Identifier", pa.string())])
            )
            writer = pq.ParquetWriter(tmp, schema)

        writer.write_table(pa.Table.from_pylist(batch, schema=schema))
    except Exception:
        import contextlib

        if writer is not None:
            writer.close()

        with contextlib.suppress(OSError):
            os.remove(tmp)

        raise

    writer.close()
    os.replace(tmp, path)


class SliceRecords:
    """One report date's slice shard as a re-iterable stream of records."""

    def __init__(self, path: str):
        self.path = path

    def __iter__(self):
        """Yield the shard's records one row-group batch at a time."""
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(self.path)

        try:
            for batch in parquet.iter_batches(RECORD_ROW_GROUP_SIZE):
                yield from batch.to_pylist()
        finally:
            parquet.close()


class RecordChain:
    """Re-iterable concatenation of record sources."""

    def __init__(self, *sources):
        self.sources = sources

    def __iter__(self):
        """Yield every source's records in order."""
        for source in self.sources:
            yield from source


def slice_records(asset: str, report_date: str) -> SliceRecords | None:
    """Return a streaming view over a report date's slice shard, or None if absent."""
    import os

    directory = _records_dir()

    if not directory:
        return None

    path = os.path.join(directory, _shard_file(asset, report_date, "slice"))

    return SliceRecords(path) if os.path.exists(path) else None


def has_slice_records(asset: str, report_date: str) -> bool:
    """Whether a report date's slice records are already sharded."""
    import os

    directory = _records_dir()

    if not directory:
        return False

    return os.path.exists(
        os.path.join(directory, _shard_file(asset, report_date, "slice"))
    )


def write_slice_records(asset: str, report_date: str, records) -> None:
    """Stream one report date's slice records into a parquet shard."""
    import os

    directory = _records_dir()

    if directory is None:
        return

    path = os.path.join(directory, _shard_file(asset, report_date, "slice"))

    try:
        _stream_shard(path, records)
    except Exception:  # noqa: BLE001
        return


def write_search_records(asset: str, day: str, records: list[dict]) -> None:
    """Merge a search day's records into its parquet shard, keyed by identifier."""
    import os

    directory = _records_dir()

    if directory is None or not day or not records:
        return

    path = os.path.join(directory, _shard_file(asset, day, "search"))
    merged: dict[str, dict] = {}

    if os.path.exists(path):
        try:
            import pyarrow.parquet as pq

            for row in pq.read_table(path).to_pylist():
                identifier = (row.get("Dissemination Identifier") or "").strip()

                if identifier:
                    merged[identifier] = row
        except Exception:  # noqa: BLE001
            merged = {}

    for row in _normalize_rows(records):
        identifier = row.get("Dissemination Identifier", "").strip()

        if identifier:
            merged[identifier] = row

    try:
        _write_shard(path, _normalize_rows(list(merged.values())))
    except Exception:  # noqa: BLE001
        return


def get_trade_record(dissemination_identifier: str) -> dict | None:
    """Return a trade record by its own exact identifier, or None if absent."""
    import pyarrow.parquet as pq

    target = (dissemination_identifier or "").strip()

    if not target:
        return None

    for path in _record_shards():
        try:
            table = pq.read_table(
                path, filters=[("Dissemination Identifier", "==", target)]
            )
        except Exception:  # noqa: BLE001, S112
            continue

        if table.num_rows:
            return table.to_pylist()[0]

    return None


def compact() -> None:
    """Cull expired entries and reclaim free space."""
    for name in ("blobs", "queries", "manifests", "curves", "responses", "documents"):
        cache = _cache(name)

        if cache is not None:
            cache.expire()


def reset() -> None:
    """Clear all cached data."""
    import os
    import shutil

    for name in ("blobs", "queries", "manifests", "curves", "responses", "documents"):
        cache = _cache(name)

        if cache is not None:
            cache.clear()

    base = _cache_dir()

    if base:
        shutil.rmtree(os.path.join(base, "record_shards"), ignore_errors=True)
