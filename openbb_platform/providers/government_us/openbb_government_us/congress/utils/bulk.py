"""GovInfo bulk-data download, cache, and parse helpers."""

import asyncio
import io
import logging
import os
import re
import zipfile
from collections.abc import Awaitable, Callable
from datetime import date as dateType

from openbb_core.app.model.abstract.error import OpenBBError

from openbb_government_us.congress.utils.helpers import BillsState

logger = logging.getLogger("uvicorn.error")


class BillNotFound(OpenBBError):
    """A bill id resolves to no record in either the bulk data or Congress.gov.

    Distinguished from a transport, credential, or parse failure so callers can
    report "this bill has no record" without masking a broken lookup.
    """


GOVINFO_BASE = "https://www.govinfo.gov"
BULKDATA_BASE = f"{GOVINFO_BASE}/bulkdata"

_DOWNLOAD_CHUNK_SIZE = 1 << 20

_WARNED: set = set()


def _warn_once(key: str, message: str, *args, level: int = logging.WARNING) -> None:
    """Log ``message`` the first time ``key`` is seen.

    ``_cache_dir`` runs on every store connection, so its diagnostics would
    otherwise repeat once per query.
    """
    if key in _WARNED:
        return
    _WARNED.add(key)
    logger.log(level, message, *args)


_CCAL_CHAMBER_CODE = {"house": "h", "senate": "s"}
_CCAL_PKG_RE = re.compile(r"CCAL-(\d+)([hs])cal-(\d{4}-\d{2}-\d{2})")

_BILL_URL_RE = re.compile(r"/bill/(\d+)/([a-z]+)/(\d+)", re.IGNORECASE)
_BILL_REF_RE = re.compile(r"^/?(\d+)[-/]([a-z]+)[-/](\d+)", re.IGNORECASE)
_AMENDMENT_URL_RE = re.compile(r"/amendment/(\d+)/([a-z]+)/(\d+)", re.IGNORECASE)
_AMENDMENT_REF_RE = re.compile(r"^/?(\d+)[-/]([a-z]+)[-/](\d+)", re.IGNORECASE)
_PKG_RE = re.compile(r"/content/pkg/([^/]+)/")

# Congress.gov API text versions point at congress.gov rather than GovInfo, e.g.
# https://www.congress.gov/107/bills/hr3162/BILLS-107hr3162enr.htm - the GovInfo
# package id is the filename stem.
_CDG_PKG_RE = re.compile(r"/((?:BILLS|PLAW)-[A-Za-z0-9]+)\.[A-Za-z]+$")


def bulk_zip_url(collection: str, congress: int, bill_type: str) -> str:
    """Build the consolidated bulk ZIP URL for a collection/congress/bill type."""
    bt = bill_type.lower()
    return (
        f"{BULKDATA_BASE}/{collection}/{congress}/{bt}/{collection}-{congress}-{bt}.zip"
    )


def parse_bill_ref(bill_ref: str) -> tuple[int, str, int]:
    """Parse a bill reference into ``(congress, bill_type, number)``."""
    match = _BILL_URL_RE.search(bill_ref) or _BILL_REF_RE.match(bill_ref)
    if not match:
        from openbb_core.app.model.abstract.error import OpenBBError

        raise OpenBBError(
            f"Could not parse a bill reference (congress/type/number) from: {bill_ref}"
        )
    return int(match.group(1)), match.group(2).lower(), int(match.group(3))


def parse_amendment_ref(amendment_ref: str) -> tuple[int, str, str]:
    """Parse an amendment reference into ``(congress, amendment_type, number)``."""
    match = _AMENDMENT_URL_RE.search(amendment_ref) or _AMENDMENT_REF_RE.match(
        amendment_ref
    )
    if not match:
        from openbb_core.app.model.abstract.error import OpenBBError

        raise OpenBBError(
            "Could not parse an amendment reference (congress/type/number)"
            f" from: {amendment_ref}"
        )
    return int(match.group(1)), match.group(2).lower(), match.group(3)


def _usable_dir(path: str) -> bool:
    """Return True if ``path`` exists (creating it if needed) and is writable."""
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return False
    return os.access(path, os.W_OK)


def _cache_dir() -> str | None:
    """Return the on-disk bulk-data cache directory, or None if none is writable."""
    from tempfile import gettempdir

    from openbb_core.app.utils import get_user_cache_directory

    preferred: str = ""

    try:
        preferred = os.path.join(get_user_cache_directory(), "congress_gov", "bulkdata")
    except Exception as exc:  # noqa: BLE001
        _warn_once(
            "cache-directory",
            "congress_gov: could not read the user cache directory: %s",
            exc,
        )

    if preferred and _usable_dir(preferred):
        return preferred

    fallback = os.path.join(gettempdir(), "openbb_congress_gov", "bulkdata")

    if _usable_dir(fallback):
        _warn_once(
            f"fallback:{preferred}",
            "congress_gov: cache directory %r is not writable; falling back to %r."
            " Bulk data will not persist across reboots - set a valid"
            " 'cache_directory' preference to keep it.",
            preferred,
            fallback,
        )
        return fallback

    _warn_once(
        f"nocache:{preferred}",
        "congress_gov: no writable cache directory (tried %r and %r). Bulk data"
        " cannot be cached and lookups will return no results.",
        preferred,
        fallback,
        level=logging.ERROR,
    )

    return None


async def _download(url: str) -> bytes:
    """Download ``url`` and return its body (no on-disk caching)."""
    import aiohttp
    from openbb_core.app.model.abstract.error import OpenBBError

    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(url) as response,
        ):
            response.raise_for_status()
            return await response.read()
    except Exception as exc:  # noqa: BLE001
        raise OpenBBError(f"Failed to download data from {url} -> {exc}") from exc


async def _stream_download(url: str, path: str) -> int:
    """Stream a URL into a file in chunks, returning the bytes written.

    Parameters
    ----------
    url : str
        The URL to download.
    path : str
        Destination file path.

    Returns
    -------
    int
        The number of bytes written.

    Raises
    ------
    OpenBBError
        If the download fails.
    """
    import aiohttp
    from openbb_core.app.model.abstract.error import OpenBBError

    written = 0
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(url, timeout=aiohttp.ClientTimeout(total=None)) as response,
        ):
            response.raise_for_status()
            with open(path, "wb") as file:
                async for chunk in response.content.iter_chunked(_DOWNLOAD_CHUNK_SIZE):
                    file.write(chunk)
                    written += len(chunk)
    except Exception as exc:  # noqa: BLE001
        raise OpenBBError(f"Failed to download data from {url} -> {exc}") from exc

    return written


async def _url_last_modified(url: str) -> str | None:
    """Return a URL's ``Last-Modified`` header via a HEAD request, or None."""
    import aiohttp

    try:
        async with (
            aiohttp.ClientSession() as session,
            session.head(url, allow_redirects=True) as response,
        ):
            if response.status >= 400:
                return None
            return response.headers.get("Last-Modified")
    except Exception:  # noqa: BLE001
        return None


async def _billstatus_listing(congress: int) -> dict[str, str]:
    """Return ``{bill_type: last_modified}`` from the GovInfo BILLSTATUS JSON listing.

    Reads ``/bulkdata/json/BILLSTATUS/{congress}``, the authoritative directory
    listing whose per-folder ``formattedLastModifiedTime`` reflects when GovInfo
    last regenerated each bill type's bulk archive.
    """
    from openbb_core.provider.utils.helpers import amake_request

    url = f"{BULKDATA_BASE}/json/BILLSTATUS/{congress}"
    try:
        data = await amake_request(url, timeout=30)
    except Exception:  # noqa: BLE001
        return {}

    listing: dict[str, str] = {}
    for entry in (data or {}).get("files", []) if isinstance(data, dict) else []:
        name = (entry.get("justFileName") or "").lower()
        modified = entry.get("formattedLastModifiedTime")
        if name and modified:
            listing[name] = modified
    return listing


async def _download_zip(collection: str, congress: int, bill_type: str) -> str:
    """Stream a bulk ZIP archive to a temporary file.

    Parameters
    ----------
    collection : str
        The bulk collection, e.g. 'BILLSTATUS' or 'PLAW'.
    congress : int
        The Congress number.
    bill_type : str
        The bill or law type.

    Returns
    -------
    str
        Path to the downloaded archive. The caller owns the file and is
        responsible for removing it.
    """
    import tempfile

    url = bulk_zip_url(collection, congress, bill_type.lower())
    handle, path = tempfile.mkstemp(suffix=".zip", dir=_cache_dir())
    os.close(handle)

    try:
        await _stream_download(url, path)
    except Exception:
        _remove_file(path)
        raise

    return path


def _remove_file(path: str) -> None:
    """Delete a file, ignoring it already being gone."""
    from contextlib import suppress

    with suppress(OSError):
        os.unlink(path)


def _zip_source(source: str | bytes):
    """Return an object ZipFile can open, wrapping raw bytes in a buffer."""
    return io.BytesIO(source) if isinstance(source, bytes) else source


def _file_size(path: str) -> int:
    """Return a file's size in bytes, or zero when it cannot be measured."""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


_WRITE_LOCKS: dict = {}


async def _db_write(fn, *args) -> None:
    """Run a store write off the loop under a single-writer lock (one writer at a time)."""
    loop = asyncio.get_running_loop()
    lock = _WRITE_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _WRITE_LOCKS[loop] = lock
    async with lock:
        await asyncio.to_thread(fn, *args)


def _text(element, path: str) -> str:
    """Return the stripped text at ``path`` under ``element`` (empty if absent)."""
    node = element.find(path)
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def _item_dict(item) -> dict:
    """Flatten a leaf XML ``<item>`` into a dict of ``{tag: text}``."""
    return {child.tag: (child.text or "").strip() for child in item}


def _first_text(element, *paths: str) -> str:
    """Return the first non-empty text among ``paths``."""
    for path in paths:
        text = _text(element, path)
        if text:
            return text
    return ""


def _first_items(element, *paths: str) -> list:
    """Return the child items at the first of ``paths`` that matches anything."""
    for path in paths:
        items = element.findall(path)
        if items:
            return items
    return []


def parse_billstatus(source: str | bytes) -> list[dict]:
    """Parse a BILLSTATUS ZIP into a list of API-shaped bill records.

    Parameters
    ----------
    source : str | bytes
        Path to the archive, or its raw bytes. A path is read member by
        member from disk, keeping the archive out of memory.
    """
    from defusedxml.ElementTree import fromstring

    records: list[dict] = []
    skipped: list[str] = []
    with zipfile.ZipFile(_zip_source(source)) as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".xml"):
                continue
            bill = fromstring(archive.read(name)).find("bill")
            if bill is None:
                continue
            record = _billstatus_record(bill)
            if record is None:
                skipped.append(name)
                continue
            records.append(record)

    if skipped:
        logger.warning(
            "congress_gov: skipped %d BILLSTATUS record(s) with no bill type or"
            " number (e.g. %s)",
            len(skipped),
            ", ".join(skipped[:3]),
        )

    return records


def _billstatus_record(bill) -> dict | None:
    """Map a single ``<bill>`` element to the API-shaped record dict."""
    congress = int(_first_text(bill, "congress") or 0)
    number_text = _first_text(bill, "number", "billNumber")
    bill_type = _first_text(bill, "type", "billType")

    if not bill_type or not number_text.isdigit():
        return None

    number = int(number_text)

    titles = [_item_dict(i) for i in bill.findall("titles/item")]
    for title in titles:
        title.setdefault("type", title.get("titleType", ""))

    cosponsors = [_item_dict(i) for i in bill.findall("cosponsors/item")]
    for cosponsor in cosponsors:
        cosponsor["isOriginalCosponsor"] = (
            cosponsor.get("isOriginalCosponsor") == "True"
        )

    summaries: list[dict] = []
    for summary in _first_items(
        bill, "summaries/summary", "summaries/billSummaries/item"
    ):
        summaries.append(
            {
                "versionCode": _text(summary, "versionCode"),
                "actionDate": _text(summary, "actionDate"),
                "actionDesc": _text(summary, "actionDesc"),
                "updateDate": _text(summary, "updateDate"),
                "text": _text(summary, "text"),
            }
        )

    return {
        "congress": congress,
        "number": number,
        "type": bill_type,
        "bill_id": f"{congress}-{bill_type.lower()}-{number}",
        "originChamber": _text(bill, "originChamber"),
        "originChamberCode": _text(bill, "originChamberCode"),
        "title": _text(bill, "title"),
        "introducedDate": _text(bill, "introducedDate"),
        "updateDate": _text(bill, "updateDate"),
        "updateDateIncludingText": _text(bill, "updateDateIncludingText"),
        "latestAction": {
            "actionDate": _text(bill, "latestAction/actionDate"),
            "text": _text(bill, "latestAction/text"),
        },
        "policyArea": {
            "name": _first_text(
                bill, "policyArea/name", "subjects/billSubjects/policyArea/name"
            )
        },
        "sponsors": [_item_dict(i) for i in bill.findall("sponsors/item")],
        "cosponsors": cosponsors,
        "actions": [_item_dict(i) for i in bill.findall("actions/item")],
        "committees": [
            _item_dict(i)
            for i in _first_items(
                bill, "committees/item", "committees/billCommittees/item"
            )
        ],
        "relatedBills": [_item_dict(i) for i in bill.findall("relatedBills/item")],
        "subjects": [
            _item_dict(i)
            for i in _first_items(
                bill,
                "subjects/legislativeSubjects/item",
                "subjects/billSubjects/legislativeSubjects/item",
            )
        ],
        "titles": titles,
        "summaries": summaries,
        "textVersions": [
            {
                "type": _text(item, "type"),
                "date": _text(item, "date"),
                "formats": [
                    {"url": _text(fmt, "url")} for fmt in item.findall("formats/item")
                ],
            }
            for item in bill.findall("textVersions/item")
        ],
        "amendments": [
            _amendment_record(am)
            for am in _first_items(
                bill,
                "amendments/amendment",
                "amendments/billAmendments/amendment",
            )
        ],
    }


def _amendment_record(am) -> dict:
    """Map a single ``<amendment>`` element to an amendment record dict."""
    congress = int(_text(am, "congress") or 0)
    number = _text(am, "number")
    amd_type = _text(am, "type")

    amended_bill: dict = {}
    ab = am.find("amendedBill")
    if ab is not None:
        amended_bill = {
            "congress": _text(ab, "congress"),
            "type": _text(ab, "type"),
            "number": _text(ab, "number"),
            "title": _text(ab, "title"),
        }

    amended_amendment: dict = {}
    aa = am.find("amendedAmendment")
    if aa is not None:
        amended_amendment = {
            "congress": _text(aa, "congress"),
            "type": _text(aa, "type"),
            "number": _text(aa, "number"),
        }

    return {
        "amendment_id": f"{congress}-{amd_type.lower()}-{number}",
        "congress": congress,
        "number": number,
        "type": amd_type,
        "description": _text(am, "description"),
        "purpose": _text(am, "purpose"),
        "chamber": _text(am, "chamber"),
        "updateDate": _text(am, "updateDate"),
        "proposedDate": _text(am, "proposedDate"),
        "submittedDate": _text(am, "submittedDate"),
        "latestAction": {
            "actionDate": _text(am, "latestAction/actionDate"),
            "actionTime": _text(am, "latestAction/actionTime"),
            "text": _text(am, "latestAction/text"),
        },
        "sponsors": [_item_dict(i) for i in am.findall("sponsors/item")],
        "cosponsors": [_item_dict(i) for i in am.findall("cosponsors/item")],
        "actions": [_item_dict(i) for i in am.findall("actions/actions/item")],
        "links": [_item_dict(i) for i in am.findall("links/link")],
        "amendedBill": amended_bill,
        "amendedAmendment": amended_amendment,
    }


_LOAD_LOCKS: dict[str, asyncio.Lock] = {}


async def _memoized(key: str, loader: Callable[[], Awaitable]):
    """Return ``BillsState.bulk[key]``, computing it once via ``loader``."""
    state = BillsState()
    cached = state.bulk.get(key)
    if cached is not None:
        return cached

    lock = _LOAD_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        cached = state.bulk.get(key)
        if cached is not None:
            return cached
        records = await loader()
        state.bulk[key] = records
        return records


def _legislation_rows_from_records(
    records: list[dict], congress: int, bill_type: str
) -> list[tuple]:
    """Derive compact sponsor/cosponsor rows from full BILLSTATUS records."""
    rows: list[tuple] = []
    for bill in records:
        sponsor = next(
            (
                s.get("bioguideId")
                for s in bill.get("sponsors") or []
                if s.get("bioguideId")
            ),
            None,
        )
        members = [(sponsor, "Sponsor")] if sponsor else []
        for cosponsor in bill.get("cosponsors") or []:
            bioguide = cosponsor.get("bioguideId")
            if bioguide and bioguide != sponsor:
                members.append((bioguide, "Cosponsor"))
        for bioguide, role in members:
            rows.append((bioguide, congress, bill_type, bill.get("bill_id"), role))
    return rows


async def _ingest_billstatus(congress: int, bill_type: str) -> None:
    """Download a BILLSTATUS archive, parse it, and store its rows in the database."""
    import time

    from openbb_government_us.congress.utils import store

    bt = bill_type.lower()
    started = time.perf_counter()
    logger.info("congress_gov: ingesting BILLSTATUS %s-%s (full)...", congress, bt)
    zip_path = await _download_zip("BILLSTATUS", congress, bt)
    try:
        size = _file_size(zip_path)
        records = await asyncio.to_thread(parse_billstatus, zip_path)
    finally:
        _remove_file(zip_path)
    leg_rows = _legislation_rows_from_records(records, congress, bt)
    await _db_write(store.ingest_bills, congress, bt, records, leg_rows)
    logger.info(
        "congress_gov: ingested BILLSTATUS %s-%s (%d bills, %.1fMB) in %.1fs",
        congress,
        bt,
        len(records),
        size / 1e6,
        time.perf_counter() - started,
    )


async def ensure_billstatus(congress: int, bill_type: str) -> None:
    """Ingest a Congress/type's BILLSTATUS into the database if not already present."""
    from openbb_government_us.congress.utils import store

    bt = bill_type.lower()

    async def _load():
        if not store.bills_loaded(congress, bt):
            await _ingest_billstatus(congress, bt)
        return True

    await _memoized(f"BILLSTATUS_{congress}_{bt}", _load)


async def ensure_api_bills(
    congress: int, bill_type: str, credentials: dict[str, str] | None
) -> None:
    """Ingest a pre-bulk Congress/type's bill list from the Congress.gov API.

    Stored in the same ``bills`` table the bulk path fills, so listing, sorting,
    filtering, and pagination all run against SQLite either way. Rows land
    without their nested collections; ``load_bill_record`` hydrates a row from
    the detail endpoint the first time that single bill is opened.
    """
    import time

    from openbb_government_us.congress.utils import congress_api, store

    bt = bill_type.lower()

    async def _load():
        if not store.bills_loaded(congress, bt):
            started = time.perf_counter()
            logger.info(
                "congress_gov: fetching %s-%s from the Congress.gov API...",
                congress,
                bt,
            )
            records = await congress_api.fetch_bill_list(congress, bt, credentials)
            await _db_write(store.ingest_bills, congress, bt, records, [])
            logger.info(
                "congress_gov: cached %s-%s (%d bills) in %.1fs",
                congress,
                bt,
                len(records),
                time.perf_counter() - started,
            )
        return True

    await _memoized(f"CONGRESSAPI_{congress}_{bt}", _load)


def _loaded_archives() -> dict[int, dict[str, str]]:
    """Map every ingested Congress to ``{bill_type: ingest_kind}``.

    ``ingest_kind`` is ``"bills"`` for archives stored with full records or
    ``"legislation"`` for the slim member-legislation-only archives. When a
    Congress/type exists under both, the full-record kind wins.
    """
    from openbb_government_us.congress.utils import store

    archives: dict[int, dict[str, str]] = {}
    for kind in ("legislation", "bills"):
        for key in store.loaded_keys(kind):
            congress_str, _, bt = key.partition("-")
            if congress_str.isdigit() and bt:
                archives.setdefault(int(congress_str), {})[bt] = kind
    return archives


async def _reingest_archive(congress: int, bill_type: str, kind: str) -> None:
    """Re-ingest one archive using the same path it was originally loaded with."""
    if kind == "bills":
        await _ingest_billstatus(congress, bill_type)
    else:
        await _ingest_legislation(congress, bill_type)


async def seed_billstatus_markers() -> None:
    """Record each ingested archive's listing stamp after a fresh warmup.

    Stamps every loaded Congress so the first refresh tick compares equal and
    does not needlessly re-download what was just warmed.
    """
    from openbb_government_us.congress.utils import store

    for congress in sorted(_loaded_archives()):
        listing = await _billstatus_listing(congress)
        for bt, modified in listing.items():
            await _db_write(
                store.put_parsed, f"lm:BILLSTATUS_{congress}_{bt}", modified
            )


async def refresh_billstatus() -> None:
    """Re-ingest any ingested BILLSTATUS archive that GovInfo has regenerated.

    GovInfo re-publishes both current and historical Congresses, so every
    Congress we hold is polled. For each one the JSON listing is read once and
    each bill type's ``formattedLastModifiedTime`` is compared against the stamp
    stored at last ingest; only changed archives are re-ingested, via the same
    path (full records or slim legislation) they were originally loaded with.
    """
    from openbb_government_us.congress.utils import store

    refreshed = 0
    for congress, types in sorted(_loaded_archives().items()):
        listing = await _billstatus_listing(congress)
        if not listing:
            continue
        for bt, kind in types.items():
            remote = listing.get(bt)
            if not remote or remote == store.get_parsed(
                f"lm:BILLSTATUS_{congress}_{bt}"
            ):
                continue
            try:
                await _reingest_archive(congress, bt, kind)
                await _db_write(
                    store.put_parsed, f"lm:BILLSTATUS_{congress}_{bt}", remote
                )
                refreshed += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "congress_gov: refresh of BILLSTATUS %s-%s failed: %s",
                    congress,
                    bt,
                    exc,
                )
    if refreshed:
        logger.info("congress_gov: refreshed %d BILLSTATUS archive(s)", refreshed)


async def list_bills(
    congress: int,
    bill_types: list[str],
    *,
    start_date: dateType | None = None,
    end_date: dateType | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort_by: str = "desc",
    credentials: dict[str, str] | None = None,
) -> list[dict]:
    """Ingest the Congress's archives if needed, then query the bills list.

    Congresses older than the GovInfo bulk archives are served from the
    Congress.gov API instead, which returns the same list shape.
    """
    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_government_us.congress.utils import store

    if congress < _BILLSTATUS_MIN_CONGRESS:
        source = "the Congress.gov API"
        loaders = [ensure_api_bills(congress, bt, credentials) for bt in bill_types]
    else:
        source = "bulk data"
        loaders = [ensure_billstatus(congress, bt) for bt in bill_types]

    results = await asyncio.gather(*loaders, return_exceptions=True)
    failures = [
        (bt, result)
        for bt, result in zip(bill_types, results)
        if isinstance(result, BaseException)
    ]

    for bill_type, error in failures:
        logger.error(
            "congress_gov: ingest of %s-%s failed: %s",
            congress,
            bill_type,
            error,
            exc_info=error,
        )

    if len(failures) == len(bill_types):
        raise OpenBBError(
            f"Could not load any bill data for Congress {congress} from"
            f" {source}: {failures[0][1]}"
        )

    return store.list_bills(
        congress,
        [bt.lower() for bt in bill_types],
        start_date,
        end_date,
        limit,
        offset,
        sort_by,
    )


def package_urls(pkg: str) -> dict:
    """Build the PDF/HTM/XML content URLs for a GovInfo package id."""
    base = f"https://www.govinfo.gov/content/pkg/{pkg}"
    return {
        "pdf": f"{base}/pdf/{pkg}.pdf",
        "htm": f"{base}/html/{pkg}.htm",
        "xml": f"{base}/xml/{pkg}.xml",
    }


def derive_text_formats(version: dict) -> dict | None:
    """Build PDF/HTM/XML URLs for a text version from either source.

    BILLSTATUS links straight at a GovInfo package, while the Congress.gov API
    links at congress.gov and carries the package id in the filename. Both are
    reduced to the same GovInfo package so the viewer gets one set of formats.
    """
    package = ""

    for fmt in version.get("formats") or []:
        url = fmt.get("url") or ""
        match = _PKG_RE.search(url) or _CDG_PKG_RE.search(url)
        if match:
            package = match.group(1)
            break

    if not package:
        return None

    return {
        "version_type": version.get("type") or "",
        "version_date": (version.get("date") or "")[:10],
        **package_urls(package),
    }


async def load_bill_record(
    bill_id: str, credentials: dict[str, str] | None = None
) -> dict:
    """Load a single bill's full record by id (summaries come from BILLSTATUS).

    Congresses older than the GovInfo bulk archives are served from the
    Congress.gov API instead, which returns the same record shape.
    """

    from openbb_government_us.congress.utils import congress_api, store

    congress, bill_type, number = parse_bill_ref(bill_id)
    key = f"{congress}-{bill_type.lower()}-{number}"

    if congress < _BILLSTATUS_MIN_CONGRESS:
        # Deliberately does not warm the Congress's whole bill list: opening one
        # bill must not wait on ingesting the other several thousand. A cached
        # row is used when it is already detailed, otherwise this bill alone is
        # fetched and written back.
        record = store.get_bill(key)

        if record is None or not record.get("_detailed"):
            record = await congress_api.bill_record(
                congress, bill_type, number, credentials
            )
            await _db_write(store.upsert_bill, congress, bill_type.lower(), record)

        return record

    await ensure_billstatus(congress, bill_type)
    record = store.get_bill(key)

    if record is None:
        raise BillNotFound(
            f"Bill not found in bulk data: {congress}/{bill_type}/{number}"
        )

    return record


def to_amendment_list_item(record: dict) -> dict:
    """Project a full amendment record to the slim ``amendments`` list shape."""
    return {
        "amendment_id": record.get("amendment_id"),
        "congress": record.get("congress"),
        "number": record.get("number"),
        "type": record.get("type"),
        "description": record.get("description") or None,
        "purpose": record.get("purpose") or None,
        "updateDate": (record.get("updateDate") or "")[:10] or None,
        "submittedDate": record.get("submittedDate"),
        "latestAction": record.get("latestAction") or {},
        "sponsors": record.get("sponsors") or [],
        "amendedBill": record.get("amendedBill") or {},
        "amendedAmendment": record.get("amendedAmendment") or {},
    }


async def _ensure_congress_billstatus(congress: int) -> None:
    """Ingest every bill type's BILLSTATUS for a Congress (amendments live in bills)."""
    from openbb_government_us.congress.utils.constants import BillTypes

    await asyncio.gather(*[ensure_billstatus(congress, bt) for bt in BillTypes])


async def load_amendments(
    congress: int, amendment_type: str | None = None
) -> list[dict]:
    """Ingest the Congress's BILLSTATUS if needed, then return its amendments."""
    from openbb_government_us.congress.utils import store

    await _ensure_congress_billstatus(congress)
    return store.list_amendments(congress, amendment_type)


async def load_amendment_record(amendment_id: str) -> dict:
    """Load a single amendment's full record by id from the database."""
    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_government_us.congress.utils import store

    congress, amendment_type, number = parse_amendment_ref(amendment_id)
    await _ensure_congress_billstatus(congress)
    record = store.get_amendment(f"{congress}-{amendment_type.lower()}-{number}")

    if record is None:
        raise OpenBBError(
            f"Amendment not found in bulk data: {congress}/{amendment_type}/{number}"
        )

    return record


def filter_amendments(
    records: list[dict],
    *,
    start_date: dateType | None = None,
    end_date: dateType | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort_by: str = "desc",
) -> list[dict]:
    """Apply post-fetch filtering, sorting, and pagination to amendment records."""

    def updated(record: dict) -> str:
        return (record.get("updateDate") or "")[:10]

    def sort_key(record: dict) -> str:
        latest = record.get("latestAction") or {}
        return latest.get("actionDate") or record.get("updateDate") or ""

    out = records
    if start_date is not None:
        out = [r for r in out if updated(r) and updated(r) >= str(start_date)]
    if end_date is not None:
        out = [r for r in out if updated(r) and updated(r) <= str(end_date)]

    out = sorted(out, key=sort_key, reverse=sort_by == "desc")
    out = out[offset or 0 :]

    if limit is None:
        return out[:100]
    if limit == 0:
        return out
    return out[:limit]


async def _resolve_link(url: str) -> str | None:
    """Resolve a GovInfo link-service URL to its final document URL."""
    import aiohttp

    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(url, allow_redirects=False) as response,
        ):
            if response.status in (301, 302, 303, 307, 308):
                return response.headers.get("Location")
            return None
    except Exception:  # noqa: BLE001
        return None


def amendment_link_base(record: dict) -> str | None:
    """Build the GovInfo link-service base URL for an amendment record."""
    congress = record.get("congress")
    number = record.get("number")
    amd_type = (record.get("type") or "").upper()

    if amd_type == "HAMDT":
        amended_bill = record.get("amendedBill") or {}
        bill_type = (amended_bill.get("type") or "").lower()
        bill_number = amended_bill.get("number")
        if not bill_type or not bill_number:
            return None
        return (
            f"{GOVINFO_BASE}/link/crec/hamendment"
            f"/{congress}/{bill_type}/{bill_number}/{number}"
        )

    return f"{GOVINFO_BASE}/link/crec/samendment/{congress}/{number}"


async def resolve_amendment_text(record: dict) -> list[dict]:
    """Resolve an amendment's Congressional Record documents via the link service."""
    base = amendment_link_base(record)
    if base is None:
        return []

    formats = [("HTML", "htm", ""), ("PDF", "pdf", "pdf")]
    resolved = await asyncio.gather(
        *[
            _resolve_link(base + (f"?link-type={lt}" if lt else ""))
            for _, _, lt in formats
        ]
    )

    out: list[dict] = []
    for (label, key, _), url in zip(formats, resolved):
        if not url:
            continue
        date_match = re.search(r"CREC-(\d{4}-\d{2}-\d{2})", url)
        out.append(
            {
                "format": label,
                "format_key": key,
                "date": date_match.group(1) if date_match else "",
                "url": url,
            }
        )

    return out


def _local(tag: str) -> str:
    """Return an XML tag's local name, stripping any namespace prefix."""
    return tag.rsplit("}", maxsplit=1)[-1]


def parse_plaw(source: str | bytes) -> list[dict]:
    """Parse a PLAW ZIP into a list of enacted-law records.

    Parameters
    ----------
    source : str | bytes
        Path to the archive, or its raw bytes.
    """
    from defusedxml.ElementTree import fromstring

    records: list[dict] = []
    with zipfile.ZipFile(_zip_source(source)) as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".xml"):
                continue
            pkg = name.rsplit("/", 1)[-1][:-4]
            root = fromstring(archive.read(name))
            meta = next((el for el in root.iter() if _local(el.tag) == "meta"), None)
            if meta is None:
                continue
            records.append(_plaw_record(meta, pkg))
    return records


def _plaw_record(meta, pkg: str) -> dict:
    """Map a USLM ``<meta>`` element and package id to a law record dict."""
    fields: dict = {}
    citations: list[str] = []
    for child in meta:
        tag = _local(child.tag)
        text = (child.text or "").strip()
        if tag == "citableAs":
            citations.append(text)
        else:
            fields.setdefault(tag, text)

    congress = int(fields.get("congress") or 0)
    number = int(fields.get("docNumber") or 0)
    full_title = fields.get("title", "")
    title = full_title.split(": ", 1)[1] if ": " in full_title else full_title

    return {
        "congress": congress,
        "law_number": number,
        "law_type": fields.get("publicPrivate", ""),
        "law_id": f"{congress}-{number}",
        "package_id": pkg,
        "title": title,
        "citation": citations[0] if citations else fields.get("type", ""),
        "statute_citation": citations[1] if len(citations) > 1 else "",
        "enacted_date": fields.get("approvedDate") or fields.get("date") or None,
        **package_urls(pkg),
    }


async def load_plaw(congress: int, law_type: str) -> list[dict]:
    """Load PLAW law records for a Congress/type from the store, ingesting first."""
    from openbb_government_us.congress.utils import store

    lt = law_type.lower()
    name = f"plaw-{congress}-{lt}"

    async def _load():
        records = store.get_parsed(name)
        if records is None:
            zip_path = await _download_zip("PLAW", congress, lt)
            try:
                records = await asyncio.to_thread(parse_plaw, zip_path)
            finally:
                _remove_file(zip_path)
            await _db_write(store.put_parsed, name, records)
        return records

    return await _memoized(f"PLAW_{congress}_{lt}", _load)


def filter_laws(
    records: list[dict],
    *,
    limit: int | None = None,
    offset: int | None = None,
    sort_by: str = "desc",
) -> list[dict]:
    """Sort enacted-law records by law number and apply pagination."""
    out = sorted(
        records, key=lambda r: r.get("law_number", 0), reverse=sort_by == "desc"
    )
    out = out[offset or 0 :]
    if limit is None:
        return out[:100]
    if limit == 0:
        return out
    return out[:limit]


def _congress_years(congress: int) -> list[int]:
    """Return the two calendar years spanned by a Congress (e.g. 119 -> [2025, 2026])."""
    start = 1789 + 2 * (congress - 1)
    return [start, start + 1]


async def load_calendars(congress: int, chamber: str) -> list[dict]:
    """Load Congressional Calendar editions for a Congress/chamber from the store."""
    from openbb_government_us.congress.utils import store

    chamber = chamber.lower()
    code = _CCAL_CHAMBER_CODE[chamber]
    name = f"ccal-{congress}-{chamber}"

    async def _load():
        cached = store.get_parsed(name)
        if cached is not None:
            return cached
        records: list[dict] = []
        seen: set[str] = set()
        for year in _congress_years(congress):
            body = await _download(f"{GOVINFO_BASE}/sitemap/CCAL_{year}_sitemap.xml")
            text = body.decode("utf-8", errors="replace")
            for match in _CCAL_PKG_RE.finditer(text):
                pkg_congress, pkg_code, date = match.groups()
                if (
                    int(pkg_congress) != congress
                    or pkg_code != code
                    or match.group(0) in seen
                ):
                    continue
                seen.add(match.group(0))
                records.append(
                    {
                        "package_id": match.group(0),
                        "congress": congress,
                        "chamber": chamber,
                        "calendar_date": date,
                        "title": f"{chamber.title()} Calendar - {date}",
                        **package_urls(match.group(0)),
                    }
                )
        await _db_write(store.put_parsed, name, records)
        return records

    return await _memoized(f"CCAL_{congress}_{chamber}", _load)


def filter_calendars(
    records: list[dict],
    *,
    publishdate: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort_by: str = "desc",
) -> list[dict]:
    """Filter calendar editions by publish date and paginate."""
    out = sorted(records, key=lambda r: r["calendar_date"], reverse=sort_by == "desc")

    if publishdate == "mostrecent":
        return out[:1]
    if publishdate:
        return [r for r in out if r["calendar_date"] == publishdate]

    out = out[offset or 0 :]
    if limit is None:
        return out[:100]
    if limit == 0:
        return out
    return out[:limit]


_CMR_LINE2_RE = re.compile(r"Reports\. (.*?)\. \d+\w\w Congress")


async def fetch_cmr(congress: int, pagesize: int = 100, offset: int = 0) -> list[dict]:
    """Fetch Congressionally Mandated Reports from the keyless GovInfo search.

    Newest first. The search pages by index, so ``offset`` is rounded down to a
    whole page of ``pagesize``.
    """
    from datetime import datetime

    response = await wssearch(
        f"collection:CMR AND congress:{congress}",
        offset=offset // max(pagesize, 1),
        pagesize=pagesize,
    )
    records: list[dict] = []
    for item in response.get("resultSet", []):
        pkg = item.get("fieldMap", {}).get("packageid", "")
        line2 = item.get("line2", "")
        agency = _CMR_LINE2_RE.search(line2)
        date = _DATE_RE.search(line2)
        records.append(
            {
                "package_id": pkg,
                "title": item.get("line1", ""),
                "submitting_agency": agency.group(1) if agency else "",
                "publication_date": (
                    datetime.strptime(date.group(1), "%B %d, %Y").date().isoformat()
                    if date
                    else None
                ),
                "pdf": package_urls(pkg)["pdf"] if pkg else "",
                "details_link": f"{GOVINFO_BASE}/app/details/{pkg}",
            }
        )
    return records


WSSEARCH_URL = f"{GOVINFO_BASE}/wssearch/search"

DOC_TYPE_COLLECTION = {
    "report": "CRPT",
    "publication": "CPRT",
    "meeting": "CHRG",
    "legislation": "BILLS",
}

_CITATION_RE = re.compile(r"^(.*?)\s+-\s+", re.DOTALL)
_DATE_RE = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")
_PKG_CHAMBER_RE = re.compile(r"-\d+([hsj])")


async def wssearch(
    query: str, *, offset: int = 0, pagesize: int = 20, sort: str = "2"
) -> dict:
    """Query the keyless GovInfo ``wssearch`` backend and return the parsed JSON."""
    import aiohttp
    from openbb_core.app.model.abstract.error import OpenBBError

    body = {
        "query": query,
        "offset": offset,
        "pageSize": pagesize,
        "sortBy": sort,
        "historical": False,
    }
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.post(WSSEARCH_URL, json=body) as response,
        ):
            response.raise_for_status()
            return await response.json()
    except Exception as exc:  # noqa: BLE001
        raise OpenBBError(f"GovInfo search failed for '{query}' -> {exc}") from exc


def _chamber_from_package(package_id: str) -> str | None:
    """Infer the chamber (House/Senate/Joint) from a package id."""
    match = _PKG_CHAMBER_RE.search(package_id)
    return {"h": "House", "s": "Senate", "j": "Joint"}.get(
        match.group(1) if match else ""
    )


def _wssearch_record(item: dict, doc_type: str, congress: int) -> dict:
    """Map a wssearch ``resultSet`` item to a committee-document record."""
    field_map = item.get("fieldMap", {})
    package_id = field_map.get("packageid", "")
    line1 = item.get("line1", "")
    line2 = item.get("line2", "")

    citation_match = _CITATION_RE.match(line1)
    citation = citation_match.group(1).strip() if citation_match else None

    date = None
    date_match = _DATE_RE.search(line2)
    if date_match:
        from datetime import datetime

        try:
            date = (
                datetime.strptime(date_match.group(1), "%B %d, %Y").date().isoformat()
            )
        except ValueError:
            date = None

    return {
        "doc_type": doc_type,
        "citation": citation,
        "title": field_map.get("title") or line1,
        "congress": congress,
        "chamber": _chamber_from_package(package_id),
        "date": date,
        "package_id": package_id,
        "doc_url": package_urls(package_id)["pdf"] if package_id else None,
    }


async def search_committee_docs(
    system_code: str,
    doc_type: str,
    congress: int,
    *,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Search GovInfo for a committee's documents of a given doc type (keyless)."""
    collection = DOC_TYPE_COLLECTION[doc_type]
    query = (
        f'committee:"{system_code.lower()}" AND collection:{collection} '
        f"AND congress:{congress}"
    )
    response = await wssearch(query, offset=offset, pagesize=limit)
    result_set = response.get("resultSet", []) if isinstance(response, dict) else []
    return [_wssearch_record(item, doc_type, congress) for item in result_set]


async def load_committee_structure() -> list[dict]:
    """Load (cached) the unitedstates committees-current dataset."""
    from openbb_core.provider.utils.helpers import amake_request

    state = BillsState()
    if "committee_structure" not in state.bulk:
        url = (
            "https://unitedstates.github.io/congress-legislators/"
            "committees-current.json"
        )
        try:
            data = await amake_request(url, timeout=30)
        except Exception:  # noqa: BLE001
            data = []
        state.bulk["committee_structure"] = data if isinstance(data, list) else []
    return state.bulk["committee_structure"]


async def fetch_package_mods(package_id: str) -> bytes:
    """Fetch the keyless MODS metadata for a GovInfo package."""
    return await _download(f"{GOVINFO_BASE}/metadata/pkg/{package_id}/mods.xml")


def parse_mods(mods_bytes: bytes, package_id: str) -> dict:
    """Parse a package MODS document for committee-document detail."""
    from defusedxml.ElementTree import fromstring

    root = fromstring(mods_bytes)
    witnesses = [
        (el.text or "").strip()
        for el in root.iter()
        if _local(el.tag) == "witness" and (el.text or "").strip()
    ]
    held_dates = [
        (el.text or "").strip()
        for el in root.iter()
        if _local(el.tag) == "heldDate" and (el.text or "").strip()
    ]

    documents: list[dict] = []
    for related in root:
        if _local(related.tag) != "relatedItem" or related.get("type") != "constituent":
            continue
        access_id = next(
            (
                (e.text or "").strip()
                for e in related.iter()
                if _local(e.tag) == "accessId"
            ),
            "",
        )
        title = next(
            (
                (e.text or "").strip()
                for e in related.iter()
                if _local(e.tag) == "title" and (e.text or "").strip()
            ),
            "",
        )
        if access_id:
            documents.append(
                {
                    "granule_id": access_id,
                    "title": title,
                    "pdf": (
                        f"{GOVINFO_BASE}/content/pkg/{package_id}/pdf/{access_id}.pdf"
                    ),
                }
            )

    return {
        "witnesses": witnesses,
        "held_dates": held_dates,
        "documents": documents,
    }


CONGRESSIONAL_COLLECTIONS = [
    "BILLS",
    "CRPT",
    "CHRG",
    "CPRT",
    "CREC",
    "CCAL",
    "CMR",
    "PLAW",
]
COLLECTION_LABELS = {
    "BILLS": "Bills",
    "CRPT": "Committee Reports",
    "CHRG": "Hearings",
    "CPRT": "Committee Prints",
    "CREC": "Congressional Record",
    "CCAL": "Calendars",
    "CMR": "Mandated Reports",
    "PLAW": "Public Laws",
}

_PKG_CONGRESS_RE = re.compile(r"^[A-Z]+-(\d+)")


def _search_record(item: dict) -> dict:
    """Map a wssearch result item to a full-text search record."""
    field_map = item.get("fieldMap", {})
    package_id = field_map.get("packageid", "")
    base = _wssearch_record(item, "", 0)
    congress_match = _PKG_CONGRESS_RE.match(package_id)
    return {
        "title": base["title"],
        "collection": field_map.get("collectionCode", ""),
        "date": base["date"],
        "congress": int(congress_match.group(1)) if congress_match else None,
        "citation": base["citation"],
        "package_id": package_id,
        "doc_url": base["doc_url"],
    }


async def search_govinfo(
    query: str,
    *,
    collection: str | None = None,
    congress: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Full-text search across the congressional GovInfo collections (keyless)."""
    parts = [query]

    if collection:
        parts.append(f"collection:{collection}")
    else:
        parts.append(
            "("
            + " OR ".join(f"collection:{c}" for c in CONGRESSIONAL_COLLECTIONS)
            + ")"
        )

    if congress is not None:
        parts.append(f"congress:{congress}")

    if start_date or end_date:
        from datetime import datetime

        lower = start_date or "1789-01-01"
        upper = end_date or datetime.now().date().isoformat()
        parts.append(f"publishdate:range({lower},{upper})")

    response = await wssearch(" AND ".join(parts), offset=offset, pagesize=limit)
    result_set = response.get("resultSet", []) if isinstance(response, dict) else []
    records = [_search_record(item) for item in result_set]
    records.sort(key=lambda r: r.get("date") or "", reverse=True)
    return records


_PHOTO_BASE = "https://unitedstates.github.io/images/congress/225x275"


def photo_link(bioguide: str) -> str:
    """Build the unitedstates portrait URL for a bioguide id."""
    return f"{_PHOTO_BASE}/{bioguide}.jpg"


async def member_photo_url(bioguide: str | None) -> str | None:
    """Return the member's portrait URL if it exists, else None."""
    if not bioguide:
        return None

    async def _load():
        import aiohttp

        url = photo_link(bioguide)
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.head(url, allow_redirects=True) as response,
            ):
                return url if response.status == 200 else None
        except Exception:  # noqa: BLE001
            return None

    return await _memoized(f"photo_{bioguide}", _load)


async def load_legislators() -> dict:
    """Load (cached) current legislators, indexed by bioguide id."""
    from openbb_core.provider.utils.helpers import amake_request

    state = BillsState()
    if "legislators" not in state.bulk:
        url = (
            "https://unitedstates.github.io/congress-legislators/"
            "legislators-current.json"
        )
        try:
            data = await amake_request(url, timeout=30)
        except Exception:  # noqa: BLE001
            data = []

        index: dict = {}
        for member in data if isinstance(data, list) else []:
            bioguide = member.get("id", {}).get("bioguide")
            if not bioguide:
                continue
            term = (member.get("terms") or [{}])[-1]
            index[bioguide] = {
                "party": term.get("party", ""),
                "state": term.get("state", ""),
                "full_name": member.get("name", {}).get("official_full", ""),
                "birthday": member.get("bio", {}).get("birthday", ""),
                "photo_url": photo_link(bioguide),
            }
        state.bulk["legislators"] = index

    return state.bulk["legislators"]


_LEGISLATORS_BASE = "https://unitedstates.github.io/congress-legislators"
_BILLSTATUS_MIN_CONGRESS = 108

VOTEVIEW_BASE = "https://voteview.com/static/data/out"
_CAST_CODES = {
    "1": "Yea",
    "2": "Yea",
    "3": "Yea",
    "4": "Nay",
    "5": "Nay",
    "6": "Nay",
    "7": "Present",
    "8": "Present",
    "9": "Not Voting",
}
_YEA_CODES = {"1", "2", "3"}
_NAY_CODES = {"4", "5", "6"}
_BILL_NUMBER_RE = re.compile(r"^([A-Z]+)(\d+)$")
_BILL_NUMBER_TYPES = {
    "HR",
    "S",
    "HRES",
    "SRES",
    "HJRES",
    "SJRES",
    "HCONRES",
    "SCONRES",
}


def _bill_number_to_id(bill_number: str, congress: int) -> str | None:
    """Convert a Voteview ``bill_number`` to a canonical bill id."""
    match = _BILL_NUMBER_RE.match((bill_number or "").strip().upper())
    if not match or match.group(1) not in _BILL_NUMBER_TYPES:
        return None
    return f"{congress}-{match.group(1).lower()}-{match.group(2)}"


def _chamber_from_term_type(term_type: str) -> str:
    """Map a term ``type`` (``rep``/``sen``) to a chamber label."""
    return {"rep": "house", "sen": "senate"}.get(term_type, "")


async def load_members() -> list[dict]:
    """Load (cached) the current members of Congress from the unitedstates dataset."""
    from openbb_core.provider.utils.helpers import amake_request

    state = BillsState()
    if "members" not in state.bulk:
        try:
            data = await amake_request(
                f"{_LEGISLATORS_BASE}/legislators-current.json", timeout=30
            )
        except Exception:  # noqa: BLE001
            data = []
        state.bulk["members"] = data if isinstance(data, list) else []
    return state.bulk["members"]


async def load_social_media() -> dict:
    """Load (cached) members' social-media handles, indexed by bioguide id."""
    from openbb_core.provider.utils.helpers import amake_request

    state = BillsState()
    if "social_media" not in state.bulk:
        try:
            data = await amake_request(
                f"{_LEGISLATORS_BASE}/legislators-social-media.json", timeout=30
            )
        except Exception:  # noqa: BLE001
            data = []
        index: dict = {}
        for entry in data if isinstance(data, list) else []:
            bioguide = entry.get("id", {}).get("bioguide")
            if bioguide:
                index[bioguide] = entry.get("social", {})
        state.bulk["social_media"] = index
    return state.bulk["social_media"]


async def load_committee_membership() -> dict:
    """Load (cached) the current committee-membership dataset (by THOMAS id)."""
    from openbb_core.provider.utils.helpers import amake_request

    state = BillsState()
    if "committee_membership" not in state.bulk:
        try:
            data = await amake_request(
                f"{_LEGISLATORS_BASE}/committee-membership-current.json", timeout=30
            )
        except Exception:  # noqa: BLE001
            data = {}
        state.bulk["committee_membership"] = data if isinstance(data, dict) else {}
    return state.bulk["committee_membership"]


async def member_committees(bioguide: str) -> list[dict]:
    """Return the committees and subcommittees a member sits on."""
    membership = await load_committee_membership()
    structure = await load_committee_structure()

    names: dict[str, str] = {}
    for committee in structure:
        tid = committee.get("thomas_id", "")
        if tid:
            names[tid] = committee.get("name", tid)
        for sub in committee.get("subcommittees") or []:
            sub_tid = f"{tid}{sub.get('thomas_id', '')}"
            names[sub_tid] = f"{committee.get('name', tid)} — {sub.get('name', '')}"

    out: list[dict] = []
    for tid, members in membership.items():
        for member in members:
            if member.get("bioguide") == bioguide:
                out.append(
                    {
                        "committee": names.get(tid, tid),
                        "rank": member.get("rank"),
                        "title": member.get("title", ""),
                        "side": member.get("party", ""),
                        "is_subcommittee": len(tid) > 4,
                    }
                )
    out.sort(key=lambda c: (c["is_subcommittee"], c["committee"]))
    return out


async def load_member_record(bioguide: str) -> dict:
    """Load a single current member's full record by bioguide id."""
    from openbb_core.app.model.abstract.error import OpenBBError

    members = await load_members()
    record = next(
        (m for m in members if m.get("id", {}).get("bioguide") == bioguide), None
    )
    if record is None:
        raise OpenBBError(f"Member not found in current Congress: {bioguide}")
    return record


def to_member_list_item(record: dict) -> dict:
    """Project a full member record to the slim ``members`` list shape."""
    term = (record.get("terms") or [{}])[-1]
    ids = record.get("id", {})
    name = record.get("name", {})
    return {
        "bioguide_id": ids.get("bioguide", ""),
        "name": name.get("official_full")
        or f"{name.get('first', '')} {name.get('last', '')}".strip(),
        "chamber": _chamber_from_term_type(term.get("type", "")),
        "party": term.get("party", ""),
        "state": term.get("state", ""),
        "district": term.get("district"),
        "term_start": term.get("start"),
        "term_end": term.get("end"),
        "website": term.get("url") or None,
    }


def filter_members(
    records: list[dict],
    *,
    chamber: str | None = None,
    state: str | None = None,
    party: str | None = None,
) -> list[dict]:
    """Filter slim member items by chamber, state, and party; sort by name."""
    out = records
    if chamber is not None:
        out = [r for r in out if r.get("chamber") == chamber]
    if state is not None:
        out = [r for r in out if (r.get("state") or "").upper() == state.upper()]
    if party is not None:
        out = [r for r in out if (r.get("party") or "").lower() == party.lower()]
    return sorted(out, key=lambda r: r.get("name") or "")


def member_served_congresses(record: dict) -> list[int]:
    """Return the Congress numbers a member served, newest first."""
    from openbb_government_us.congress.utils.helpers import year_to_congress

    congresses: set[int] = set()
    for term in record.get("terms") or []:
        start = (term.get("start") or "")[:4]
        if not start.isdigit():
            continue
        try:
            congress = year_to_congress(int(start))
        except ValueError:
            continue
        if congress >= _BILLSTATUS_MIN_CONGRESS:
            congresses.add(congress)
    return sorted(congresses, reverse=True)


def member_service(record: dict) -> list[tuple[int, str]]:
    """Return the ``(congress, chamber)`` pairs a member served, newest first."""
    from openbb_government_us.congress.utils.helpers import year_to_congress

    seen: dict[int, str] = {}
    for term in record.get("terms") or []:
        start = (term.get("start") or "")[:4]
        if not start.isdigit():
            continue
        try:
            congress = year_to_congress(int(start))
        except ValueError:
            continue
        seen[congress] = "H" if term.get("type") == "rep" else "S"
    return [(c, seen[c]) for c in sorted(seen, reverse=True)]


_INDEX_CONCURRENCY = 16


async def _ingest_legislation(congress: int, bill_type: str) -> None:
    """Download a BILLSTATUS archive and store only its compact legislation rows."""
    from openbb_government_us.congress.utils import store

    bt = bill_type.lower()
    zip_path = await _download_zip("BILLSTATUS", congress, bt)
    try:
        records = await asyncio.to_thread(parse_billstatus, zip_path)
    finally:
        _remove_file(zip_path)
    leg_rows = _legislation_rows_from_records(records, congress, bt)
    await _db_write(store.ingest_legislation, congress, bt, records, leg_rows)


async def ingest_billstatus_range(congresses: list[int]) -> None:
    """Warm the member-legislation rows for a range of Congresses (no full records)."""
    import time

    from openbb_government_us.congress.utils import store
    from openbb_government_us.congress.utils.constants import BillTypes

    done = store.loaded_keys("bills") | store.loaded_keys("legislation")
    units = [
        (c, bt.lower())
        for c in congresses
        for bt in BillTypes
        if f"{c}-{bt.lower()}" not in done
    ]
    if not units:
        logger.info("congress_gov: legislation already warmed for %s", congresses)
        return
    logger.info(
        "congress_gov: warming legislation for Congresses %s-%s (%d archives)...",
        min(congresses),
        max(congresses),
        len(units),
    )
    started = time.perf_counter()
    progress = {"n": 0}
    semaphore = asyncio.Semaphore(_INDEX_CONCURRENCY)

    async def _unit(congress: int, bill_type: str) -> None:
        async with semaphore:
            try:
                await _ingest_legislation(congress, bill_type)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "congress_gov: legislation %s-%s failed: %s",
                    congress,
                    bill_type,
                    exc,
                )
                return
        progress["n"] += 1
        logger.info(
            "congress_gov: legislation %s-%s done (%d/%d)",
            congress,
            bill_type,
            progress["n"],
            len(units),
        )

    await asyncio.gather(*[_unit(c, bt) for c, bt in units])
    logger.info(
        "congress_gov: legislation warm complete (%d archives in %.0fs)",
        len(units),
        time.perf_counter() - started,
    )


async def member_legislation(bioguide: str, congresses: list[int]) -> list[dict]:
    """Return bills a member sponsored or cosponsored across the given Congresses."""
    from openbb_government_us.congress.utils import store

    return store.get_legislation(bioguide, list(congresses))


async def _voteview_text(kind: str, congress: int, chamber: str) -> str:
    """Download a Voteview CSV for a Congress and chamber (empty string on failure)."""
    url = f"{VOTEVIEW_BASE}/{kind}/{chamber}{congress}_{kind}.csv"
    try:
        data = await _download(url)
    except Exception:  # noqa: BLE001
        return ""
    return data.decode("utf-8", "replace")


async def _load_voteview(kind: str, congress: int, chamber: str, parser):
    """Return a parsed Voteview file from the store, downloading and parsing first."""
    from openbb_government_us.congress.utils import store

    name = f"vv-{kind}-{chamber}{congress}"

    async def _load():
        cached = store.get_parsed(name)
        if cached is not None:
            return cached
        text = await _voteview_text(kind, congress, chamber)
        parsed = await asyncio.to_thread(parser, text)
        await _db_write(store.put_parsed, name, parsed)
        return parsed

    return await _memoized(f"VV_{kind.upper()}_{chamber}{congress}", _load)


def _parse_voteview_members(text: str) -> dict[str, str]:
    """Parse a Voteview members CSV into ``{bioguide_id: icpsr}``."""
    import csv
    import io

    index: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(text)):
        bioguide = row.get("bioguide_id")
        icpsr = row.get("icpsr")
        if bioguide and icpsr:
            index[bioguide] = icpsr
    return index


def _parse_voteview_rollcalls(text: str) -> dict[str, dict]:
    """Parse a Voteview rollcalls CSV into ``{rollnumber: metadata}``."""
    import csv
    import io

    rolls: dict[str, dict] = {}
    for row in csv.DictReader(io.StringIO(text)):
        rolls[row.get("rollnumber", "")] = {
            "bill_number": row.get("bill_number", ""),
            "question": row.get("vote_question", ""),
            "result": row.get("vote_result", ""),
            "title": row.get("vote_desc", ""),
            "date": row.get("date", ""),
        }
    return rolls


def _parse_voteview_votes(text: str) -> dict[str, list[tuple]]:
    """Parse a Voteview votes CSV into ``{icpsr: [(rollnumber, cast_code)]}``."""
    import csv
    import io

    index: dict[str, list[tuple]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        index.setdefault(row.get("icpsr", ""), []).append(
            (row.get("rollnumber", ""), row.get("cast_code", ""))
        )
    return index


async def load_voteview_members(congress: int, chamber: str) -> dict[str, str]:
    """Load a Voteview members file as ``{bioguide_id: icpsr}`` from the store."""
    return await _load_voteview("members", congress, chamber, _parse_voteview_members)


async def load_voteview_rollcalls(congress: int, chamber: str) -> dict[str, dict]:
    """Load a Voteview rollcalls file as ``{rollnumber: metadata}`` from the store."""
    return await _load_voteview(
        "rollcalls", congress, chamber, _parse_voteview_rollcalls
    )


async def load_voteview_votes(congress: int, chamber: str) -> dict[str, list[tuple]]:
    """Load a Voteview votes file as ``{icpsr: [(rollnumber, cast_code)]}`` from the store."""
    return await _load_voteview("votes", congress, chamber, _parse_voteview_votes)


async def member_congress_votes(
    bioguide: str, congress: int, chamber: str
) -> list[dict]:
    """Return a member's roll-call votes for one Congress/chamber, from Voteview."""
    members = await load_voteview_members(congress, chamber)
    icpsr = members.get(bioguide)
    if icpsr is None:
        return []

    rollcalls = await load_voteview_rollcalls(congress, chamber)
    votes = await load_voteview_votes(congress, chamber)

    chamber_name = "house" if chamber == "H" else "senate"
    out: list[dict] = []
    for rollnumber, cast_code in votes.get(icpsr, []):
        position = _CAST_CODES.get(cast_code)
        if position is None:
            continue
        meta = rollcalls.get(rollnumber, {})
        out.append(
            {
                "congress": congress,
                "chamber": chamber_name,
                "rollnumber": int(rollnumber or 0),
                "position": position,
                "cast_code": cast_code,
                "bill_id": _bill_number_to_id(meta.get("bill_number", ""), congress),
                "legislation": meta.get("bill_number") or None,
                "title": meta.get("title") or None,
                "question": meta.get("question") or None,
                "result": meta.get("result") or None,
                "date": meta.get("date") or None,
            }
        )
    return out


async def member_votes(
    bioguide: str, service: list[tuple[int, str]], *, limit: int = 25
) -> list[dict]:
    """Return a member's most recent roll-call votes on legislation across tenure."""
    votes: list[dict] = []
    for congress, chamber in service:
        group = await member_congress_votes(bioguide, congress, chamber)
        votes.extend(vote for vote in group if vote.get("bill_id"))
        if len(votes) >= limit:
            break
    votes.sort(
        key=lambda v: (v.get("date") or "", v.get("rollnumber") or 0), reverse=True
    )
    return votes[:limit]


def _is_passage_question(question: str | None) -> bool:
    """Return True for a final-passage roll call (bill or joint/concurrent resolution)."""
    text = (question or "").strip().lower()
    return (
        text.startswith(("on passage", "passage,"))
        or "joint resolution" in text
        or "concurrent resolution" in text
        or "suspend the rules and pass" in text
    )


def _partial_passage_index(
    members: dict, rollcalls: dict, votes: dict
) -> dict[str, tuple[int, int]]:
    """Tally each member's final-passage Yea/Nay counts for one Congress/chamber."""
    icpsr_to_bioguide = {icpsr: bioguide for bioguide, icpsr in members.items()}
    partial: dict[str, tuple[int, int]] = {}
    for icpsr, casts in votes.items():
        bioguide = icpsr_to_bioguide.get(icpsr)
        if not bioguide:
            continue
        yea = nay = 0
        for rollnumber, cast_code in casts:
            meta = rollcalls.get(rollnumber)
            if not meta or not _is_passage_question(meta.get("question")):
                continue
            if cast_code in _YEA_CODES:
                yea += 1
            elif cast_code in _NAY_CODES:
                nay += 1
        if yea or nay:
            partial[bioguide] = (yea, nay)
    return partial


def _invalidate_voteview(congress: int, chamber: str) -> None:
    """Drop cached Voteview members/rollcalls/votes so they re-download next load."""
    from openbb_government_us.congress.utils import store

    state = BillsState()
    for kind in ("members", "rollcalls", "votes"):
        state.bulk.pop(f"VV_{kind.upper()}_{chamber}{congress}", None)
        store.delete_parsed(f"vv-{kind}-{chamber}{congress}")


async def _ingest_passage(congress: int, chamber: str, *, keep: bool) -> None:
    """Compute and store one Congress/chamber's final-passage Yea/Nay tallies."""
    from openbb_government_us.congress.utils import store

    members = await load_voteview_members(congress, chamber)
    rollcalls = await load_voteview_rollcalls(congress, chamber)
    votes = await load_voteview_votes(congress, chamber)
    tallies = await asyncio.to_thread(_partial_passage_index, members, rollcalls, votes)
    await _db_write(store.add_passage, congress, chamber, tallies)
    if not keep:
        state = BillsState()
        state.bulk.pop(f"VV_ROLLCALLS_{chamber}{congress}", None)
        state.bulk.pop(f"VV_VOTES_{chamber}{congress}", None)


async def build_passage_index(
    congresses: list[int], keep_votes: list[int] | None = None
) -> None:
    """Ingest each member's final-passage Yea/Nay record into the store from Voteview."""
    import time

    from openbb_government_us.congress.utils import store

    keep = set(congresses[:2] if keep_votes is None else keep_votes)
    loaded = store.loaded_keys("passage")
    units = [
        (c, ch) for c in congresses for ch in ("H", "S") if f"{c}-{ch}" not in loaded
    ]
    if not units:
        return
    logger.info(
        "congress_gov: warming passage votes for Congresses %s-%s (%d files)...",
        min(congresses),
        max(congresses),
        len(units),
    )
    started = time.perf_counter()
    semaphore = asyncio.Semaphore(_INDEX_CONCURRENCY)

    async def _unit(congress: int, chamber: str) -> None:
        async with semaphore:
            # Shares the per-unit memo with the on-demand path so a bio opened
            # mid-warmup cannot start a second download of the same files.
            async def _load():
                await _ingest_passage(congress, chamber, keep=congress in keep)
                return True

            await _memoized(f"PASSAGE_{congress}_{chamber}", _load)

    await asyncio.gather(*[_unit(c, ch) for c, ch in units])
    logger.info(
        "congress_gov: passage votes warm complete (%d files in %.0fs)",
        len(units),
        time.perf_counter() - started,
    )


async def refresh_passage() -> None:
    """Re-ingest the current Congress's Voteview passage votes when they change.

    Voteview adds roll calls in near real time while a chamber is in session, so
    the active Congress is re-polled on a slower cadence than the bill data. The
    votes CSV ``Last-Modified`` gates the work: unchanged files are skipped, and
    older Congresses (final once the term ends) are never touched here.
    """
    from datetime import datetime

    from openbb_government_us.congress.utils import store
    from openbb_government_us.congress.utils.helpers import year_to_congress

    congress = year_to_congress(datetime.now().year)
    refreshed = 0
    for chamber in ("H", "S"):
        url = f"{VOTEVIEW_BASE}/votes/{chamber}{congress}_votes.csv"
        remote = await _url_last_modified(url)
        marker = f"lm:VV_{chamber}{congress}"
        if remote is not None and remote == store.get_parsed(marker):
            continue
        try:
            _invalidate_voteview(congress, chamber)
            await _ingest_passage(congress, chamber, keep=True)
            if remote is not None:
                await _db_write(store.put_parsed, marker, remote)
            refreshed += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "congress_gov: refresh of passage %s-%s failed: %s",
                congress,
                chamber,
                exc,
            )
    if refreshed:
        logger.info(
            "congress_gov: refreshed %d current-Congress passage file(s)", refreshed
        )


def _passage_ratio(yea: int, nay: int) -> dict:
    """Build the Yea/Nay summary dict from raw counts."""
    total = yea + nay
    return {
        "yea": yea,
        "nay": nay,
        "total": total,
        "yea_pct": round(100 * yea / total, 1) if total else None,
    }


async def ensure_passage(congress: int, chamber: str) -> None:
    """Ingest one Congress/chamber's Voteview passage tallies if not already stored."""
    from openbb_government_us.congress.utils import store

    async def _load():
        if f"{congress}-{chamber}" not in store.loaded_keys("passage"):
            await _ingest_passage(congress, chamber, keep=False)
        return True

    await _memoized(f"PASSAGE_{congress}_{chamber}", _load)


async def ensure_member_passage(bioguide: str) -> None:
    """Build the passage index for every Congress/chamber a member served.

    The startup warmup builds this index too, but it runs behind the bill
    archives and takes minutes, so a bio opened before it gets there - or after a
    warmup that failed or was restarted - would report no voting record at all.

    Every unit the member served is ingested, not just the missing ones nearest
    to hand, because ``get_passage`` sums across all of them: a partial build
    would answer with a confidently wrong career tally and never correct itself.
    """
    from openbb_government_us.congress.utils import store

    record = await load_member_record(bioguide)
    units = member_service(record)

    if not units:
        return

    loaded = store.loaded_keys("passage")
    missing = [(c, ch) for c, ch in units if f"{c}-{ch}" not in loaded]

    if not missing:
        return

    logger.info(
        "congress_gov: building passage votes for %s (%d Congress/chamber file(s))...",
        bioguide,
        len(missing),
    )
    semaphore = asyncio.Semaphore(_INDEX_CONCURRENCY)

    async def _unit(congress: int, chamber: str) -> None:
        async with semaphore:
            try:
                await ensure_passage(congress, chamber)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "congress_gov: passage votes for %s%s unavailable: %s",
                    chamber,
                    congress,
                    exc,
                )

    await asyncio.gather(*[_unit(c, ch) for c, ch in missing])


async def member_passage_record(bioguide: str) -> dict:
    """Return a member's career Yea/Nay record on final-passage votes from the store."""
    from openbb_government_us.congress.utils import store

    try:
        await ensure_member_passage(bioguide)
    except Exception as exc:  # noqa: BLE001
        # A bio page is still worth rendering without its voting panel.
        logger.error(
            "congress_gov: could not build the passage index for %s: %s", bioguide, exc
        )

    row = store.get_passage(bioguide)
    yea, nay = row if row else (0, 0)
    return _passage_ratio(yea, nay)
