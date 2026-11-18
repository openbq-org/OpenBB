"""Fed in Print public faceted-search client, shared across Reserve Banks."""

from __future__ import annotations

import html
import re
import threading
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

BASE = "https://fedinprint.org"
SEARCH_URL = f"{BASE}/search"
PAGE_SIZE = 10

REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "fedinprint" / "districts.json"
)

Fetch = Callable[[str], str]


def _get_session() -> Any:
    """Return the calling thread's ``curl_cffi`` session (Fed in Print is unwalled)."""
    from openbb_federal_reserve.utils.curl_session import get_session

    return get_session(f"fedinprint:{threading.get_ident()}", lambda _session: None)


def fetch_text(url: str) -> str:
    """Fetch a URL as text through a per-thread session, retrying once on a 403."""
    from openbb_federal_reserve.utils.curl_session import reset_session

    response = _get_session().get(url, timeout=180)
    if response.status_code == 403:
        reset_session(f"fedinprint:{threading.get_ident()}")
        response = _get_session().get(url, timeout=180)
    response.raise_for_status()
    return response.text


_PDF_META = re.compile(r'citation_pdf_url"\s*content="([^"]+)"')
_DOI_META = re.compile(r'citation_doi"\s*content="([^"]+)"')
_OG_URL = re.compile(r'og:url"\s*content="([^"]+)"')
_PDF_HREF = re.compile(r'href="([^"]+\.pdf)"', re.IGNORECASE)
_FILE_HREF = re.compile(r"File\(s\).*?href=\"([^\"]+)\"", re.DOTALL)
_BLOCK = re.compile(r'search-result-detail">\s*<p>(.*?)</p>', re.DOTALL)
_TYPE = re.compile(r'content-type">\s*(\S.*?)\s*</span>', re.DOTALL)
_LINK = re.compile(r'href="(/item/[^"]+)"\s+class="title">\s*(.*?)\s*</a>', re.DOTALL)
_META = re.compile(r'class="meta">\s*(.*?)\s*(?:,|<br|</span>)', re.DOTALL)
_BYLINE = re.compile(r'class="byline">(.*?)</span>', re.DOTALL)
_DATE = re.compile(r"\((\d{4})(?:-(\d{2})(?:-(\d{2}))?)?\)")
_FACET_COUNT = re.compile(
    r'data-facet-value="hasparentname_literal_array:([^"]+)".*?'
    r'<span class="text-muted">\s*([\d,]+)&nbsp;items',
    re.DOTALL,
)


def clean_label(value: str) -> str:
    """Collapse whitespace in a raw facet value for display."""
    return re.sub(r"\s+", " ", value).strip()


def _search_url(facets: list[str], start: int) -> str:
    """Build a faceted-search URL sorted newest-first at the given offset."""
    from urllib.parse import urlencode

    params = [("facets[]", facet) for facet in facets]
    params += [("sort", "sort_date_text desc"), ("start", str(start))]
    return f"{SEARCH_URL}?{urlencode(params)}"


def _parse_block(block: str, series: str) -> dict[str, Any] | None:
    """Parse a search-result block into a candidate record.

    Blocks without a content type are web-only items (blogs, podcasts) that
    publish no document, and are skipped.
    """
    if not _TYPE.search(block):
        return None
    link = _LINK.search(block)
    if not link:
        return None
    title = html.unescape(re.sub(r"\s+", " ", link.group(2)).strip())
    meta = _META.search(block)
    parsed_series = clean_label(html.unescape(meta.group(1))) if meta else ""
    byline = _BYLINE.search(block)
    published = ""
    if byline:
        stamp = _DATE.search(byline.group(1))
        if stamp:
            year, month, day = (
                stamp.group(1),
                stamp.group(2) or "01",
                stamp.group(3) or "01",
            )
            published = f"{year}-{month}-{day}"
    return {
        "series": series or parsed_series,
        "date": published,
        "title": title,
        "url": f"{BASE}{link.group(1)}",
    }


def _first_file_link(page: str) -> str:
    """Return the citation PDF URL, or the ``File(s)`` link, from an item page."""
    meta = _PDF_META.search(page)
    if meta:
        return html.unescape(meta.group(1))
    href = _FILE_HREF.search(page)
    return html.unescape(href.group(1)) if href else ""


def _doi_pdf(page: str, fetch: Fetch) -> str:
    """Return the first PDF linked from an item's DOI landing page, or ``""``.

    Atlanta's items carry only a DOI (no ``citation_pdf_url`` or ``File(s)``
    link); the DOI lands on the paper's web page, which links the PDF.
    """
    doi = _DOI_META.search(page)
    if not doi:
        return ""
    landing = fetch(f"https://doi.org/{html.unescape(doi.group(1))}")
    href, base = _PDF_HREF.search(landing), _OG_URL.search(landing)
    if not (href and base):
        return ""
    return urljoin(html.unescape(base.group(1)), html.unescape(href.group(1)))


def _host(url: str) -> str:
    """Return the lowercased hostname of a URL, or an empty string."""
    return (urlparse(url).hostname or "").lower()


def _is_file(url: str) -> bool:
    """Return whether a URL points at a downloadable document rather than a page."""
    low = url.lower()
    host = _host(url)
    is_doi = host == "doi.org" or host.endswith(".doi.org")
    return low.endswith(".pdf") or is_doi or "/files/" in low


_CMS_HOST = re.compile(r"^(https?://)([a-z0-9-]+)cm\.ws\.frb\.org")


def _public_url(url: str) -> str:
    """Rewrite a Reserve Bank CMS staging host to its public equivalent."""
    return _CMS_HOST.sub(r"\1www.\2.org", url)


def resolve_file(item_url: str, fetch: Fetch) -> str | None:
    """Resolve an item page to its direct document URL, or ``None``.

    An item points at either a direct file, a catalog page (e.g. FRASER) that in
    turn names the file, a DOI whose landing page links the file, or an HTML
    article with no document. Only the first three resolve to a downloadable URL,
    the last two at the cost of one more request. CMS staging hosts are rewritten
    to public ones.
    """
    page = fetch(item_url)
    link = _first_file_link(page) or _doi_pdf(page, fetch)
    if not link:
        return None
    if _host(link) == "fraser.stlouisfed.org" and "/files/" not in link:
        inner = _first_file_link(fetch(link))
        if inner:
            link = inner
    return _public_url(link) if _is_file(link) else None


def search(
    provider: str,
    fetch: Fetch,
    series_facet: str | None = None,
    min_year: str = "",
    start: int = 0,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return one page of a Reserve Bank's Fed in Print publications, newest first.

    This is the fast metadata path: it parses the faceted-search result pages
    only and does not fetch item pages. The returned ``url`` is the Fed in Print
    item page; it is resolved to a downloadable document on demand at download
    time, keeping every list request to a single search fetch.

    Parameters
    ----------
    provider : str
        The ``provider_literal_array`` facet value, e.g. the full bank name.
    fetch : Callable[[str], str]
        A URL-to-text fetcher supplied by the calling bank client.
    series_facet : str | None
        A ``hasparentname_literal_array`` series facet to narrow to one series.
    min_year : str
        The earliest four-digit year to keep; scanning stops once results fall
        below it, since results are newest-first.
    start : int
        The result offset to begin scanning from, for pagination.
    limit : int
        The maximum number of records to return.

    Returns
    -------
    list[dict[str, Any]]
        One record per publication with ``series``, ``date``, ``title``, and the
        Fed in Print item ``url``, newest first.
    """
    from concurrent.futures import ThreadPoolExecutor

    facets = [f"provider_literal_array:{provider}"]
    if series_facet:
        facets.append(f"hasparentname_literal_array:{series_facet}")
    label = clean_label(series_facet) if series_facet else ""

    pages_needed = -(-limit // PAGE_SIZE) + 1
    offsets = [start + i * PAGE_SIZE for i in range(pages_needed)]
    with ThreadPoolExecutor(max_workers=len(offsets)) as pool:
        pages = list(pool.map(lambda o: fetch(_search_url(facets, o)), offsets))

    seen: set[str] = set()
    records: list[dict[str, Any]] = []
    stop = False
    for page in pages:
        if stop:
            break
        for block in _BLOCK.findall(page):
            record = _parse_block(block, label)
            if record is None:
                continue
            if min_year and record["date"] and record["date"][:4] < min_year:
                stop = True
                break
            if record["url"] in seen:
                continue
            seen.add(record["url"])
            records.append(record)
            if len(records) >= limit:
                stop = True
                break

    records.sort(key=lambda r: (r["date"] or "", r["title"]), reverse=True)
    return records[:limit]


def series_counts(provider: str, fetch: Fetch) -> dict[str, int]:
    """Return the document count for each of a provider's publication series.

    Parameters
    ----------
    provider : str
        The ``provider_literal_array`` facet value, e.g. the full bank name.
    fetch : Callable[[str], str]
        A URL-to-text fetcher supplied by the calling bank client.

    Returns
    -------
    dict[str, int]
        The item count for each series, keyed by its clean display label.
    """
    page = fetch(_search_url([f"provider_literal_array:{provider}"], 0))
    return {
        clean_label(facet): int(count.replace(",", ""))
        for facet, count in _FACET_COUNT.findall(page)
    }


@lru_cache(maxsize=1)
def load_registry() -> dict[str, dict[str, Any]]:
    """Return the committed per-district provider and document-series registry."""
    import json

    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def districts() -> tuple[str, ...]:
    """Return the district keys covered by the registry."""
    return tuple(load_registry())


def provider(district: str) -> str:
    """Return the fedinprint provider name for a district."""
    return load_registry()[district]["provider"]


def _facets(district: str) -> dict[str, str]:
    """Return the ``slug -> facet`` map for a district's document series."""
    return {slug: facet for slug, facet in load_registry()[district]["series"]}


def series_choices(district: str) -> list[dict[str, str]]:
    """Return series dropdown options mapping each label to its slug value."""
    return [
        {"label": clean_label(facet), "value": slug}
        for slug, facet in load_registry()[district]["series"]
    ]


_RESOLVE_TTL = 30 * 86400


def _safe_resolve(url: str) -> str | None:
    """Resolve an item URL to its document, caching the immutable mapping.

    Fed in Print item pages throttle concurrent requests, so each item-to-document
    mapping is cached for 30 days; a page's second load and its weekly refresh then
    resolve only genuinely new items. Failures return ``None`` and are not cached,
    so a transient error is retried on the next request.
    """
    from openbb_federal_reserve.utils.cache import cached

    def _producer() -> str | None:
        try:
            return resolve_file(url, fetch_text)
        except Exception:  # noqa: BLE001
            return None

    return cached(("fedinprint_resolve", url), _RESOLVE_TTL, _producer)


def resolve_records(
    records: list[dict[str, Any]], limit: int, workers: int = 10
) -> list[dict[str, Any]]:
    """Resolve item URLs to documents, dropping the items without a downloadable file.

    Records are resolved newest-first in bounded-parallel chunks until ``limit``
    downloadable documents are collected; each kept record's ``url`` is replaced
    with its resolved direct-document URL so the download needs no second lookup.
    """
    from concurrent.futures import ThreadPoolExecutor

    viewable: list[dict[str, Any]] = []
    index = 0
    while index < len(records) and len(viewable) < limit:
        chunk = records[index : index + workers]
        with ThreadPoolExecutor(max_workers=len(chunk)) as pool:
            targets = list(pool.map(lambda record: _safe_resolve(record["url"]), chunk))
        viewable.extend(
            {**record, "url": target}
            for record, target in zip(chunk, targets)
            if target
        )
        index += workers
    return viewable[:limit]


def resolved_page(
    provider_name: str,
    facets_map: dict[str, str],
    series: str | None,
    min_year: str,
    start: int,
    limit: int,
) -> list[dict[str, Any]]:
    """Return one page of resolved, downloadable documents for a provider.

    A known ``series`` is searched directly; otherwise the provider's primary
    document series is used. Candidates are over-fetched and resolved so the
    requested page holds only openable documents, with each ``url`` rewritten to
    its resolved direct-document link.
    """
    facet = facets_map.get(series) if series else None
    if facet is None:
        facet = next(iter(facets_map.values()), None)
    if facet is None:
        return []
    need = start + limit
    candidates = search(
        provider_name,
        fetch_text,
        series_facet=facet,
        min_year=min_year,
        start=0,
        limit=need * 2 + PAGE_SIZE,
    )
    return resolve_records(candidates, need)[start:]


def search_publications(
    district: str,
    series: str | None = None,
    min_year: str = "",
    start: int = 0,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return a page of a district's publications, resolved to direct documents."""
    return resolved_page(
        provider(district), _facets(district), series, min_year, start, limit
    )


def list_publications(
    district: str,
    series: str | None = None,
    start_date: Any = None,
    start: int = 0,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return a cached page of a district's publications, newest first."""
    from openbb_federal_reserve.utils.cache import cached, seconds_until_next_release

    slug = series if series in _facets(district) else None
    min_year = str(start_date.year) if start_date else ""
    return cached(
        ("fedinprint_publications", district, slug, min_year, start, limit),
        lambda: seconds_until_next_release("weekly"),
        lambda: search_publications(district, slug, min_year, start, limit),
    )


def list_series(district: str) -> list[dict[str, Any]]:
    """Return a district's supported document series with live counts, cached weekly."""
    from openbb_federal_reserve.utils.cache import cached, seconds_until_next_release

    def _producer() -> list[dict[str, Any]]:
        counts = series_counts(provider(district), fetch_text)
        return [
            {
                "series": slug,
                "name": clean_label(facet),
                "count": counts.get(clean_label(facet), 0),
            }
            for slug, facet in load_registry()[district]["series"]
        ]

    return cached(
        ("fedinprint_series", district),
        lambda: seconds_until_next_release("weekly"),
        _producer,
    )


def _slugify(name: str) -> str:
    """Reduce a facet name to a lower-snake slug."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _is_document(prov: str, facet: str, sample: int = 12) -> bool:
    """Return whether a series' recent items resolve to downloadable documents."""
    facets = [
        f"provider_literal_array:{prov}",
        f"hasparentname_literal_array:{facet}",
    ]
    items = []
    for block in _BLOCK.findall(fetch_text(_search_url(facets, 0))):
        if not _TYPE.search(block):
            continue
        link = _LINK.search(block)
        if link:
            items.append(f"{BASE}{link.group(1)}")
    for item in items[:sample]:
        try:
            if resolve_file(item, fetch_text):
                return True
        except Exception:  # noqa: BLE001, S110
            pass
    return False


def build_registry(banks: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Classify each bank's document series and build the district registry.

    Parameters
    ----------
    banks : dict[str, str]
        A mapping of district key to fedinprint provider name.

    Returns
    -------
    dict[str, dict[str, Any]]
        A ``{district: {"provider", "series": [[slug, facet], ...]}}`` registry
        holding only series whose items resolve to downloadable documents.
    """
    from concurrent.futures import ThreadPoolExecutor

    pairs = [
        (district, prov, facet)
        for district, prov in banks.items()
        for facet in series_counts(prov, fetch_text)
    ]
    with ThreadPoolExecutor(max_workers=16) as pool:
        flags = list(pool.map(lambda p: _is_document(p[1], p[2]), pairs))

    registry: dict[str, dict[str, Any]] = {
        district: {"provider": prov, "series": []} for district, prov in banks.items()
    }
    seen: dict[str, set[str]] = {district: set() for district in banks}
    for (district, _prov, facet), keep in zip(pairs, flags):
        if not keep:
            continue
        slug = _slugify(facet)
        if slug in seen[district]:
            continue
        seen[district].add(slug)
        registry[district]["series"].append([slug, facet])
    return registry


def write_registry(banks: dict[str, str]) -> Path:
    """Classify the banks and write the district registry asset."""
    import json

    payload = build_registry(banks)
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    load_registry.cache_clear()
    return REGISTRY_PATH
