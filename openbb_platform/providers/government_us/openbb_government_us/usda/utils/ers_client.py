"""USDA ERS file download client with disk caching."""

import os
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any

CACHE_ENV_VAR = "OPENBB_USDA_CACHE_DIR"
BASE_URL = "https://www.ers.usda.gov"
PAGE_TTL = 86400
DEFAULT_FILE_TTL = 86400
MIN_FILE_TTL = 3600

ITEM_CLASS = "usa-collection__item"
HEADING_CLASS = "usa-collection__heading"
MEDIA_PATTERN = re.compile(r"^(/media/\d+/[^?]+)")
TIME_KIND_PATTERN = re.compile(r"(Last Updated|Next Update)")
HEADING_PATTERN = re.compile(
    r'<h3 class="usa-collection__heading">([^<]+)</h3>',
)
LINK_PATTERN = re.compile(
    r'href="(/media/\d+/[^"?]+)(?:\?v=\d+)?"',
)


class _CollectionParser(HTMLParser):
    """Collect usa-collection items, keeping each item's own metadata.

    An item nests a usa-collection__meta list holding its Last Updated and
    Next Update times, so item boundaries are tracked by tag depth rather
    than by matching markup, which cannot bound nesting correctly.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict] = []
        self._item: dict | None = None
        self._depth = 0
        self._heading = False
        self._time: str | None = None

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> str:
        """Return an attribute list's class value."""
        return dict(attrs).get("class") or ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Open an item, heading, link, or time."""
        values = dict(attrs)
        if tag == "li" and ITEM_CLASS in self._classes(attrs):
            if self._item is not None:
                self.items.append(self._item)
            self._item = {"title": None, "paths": [], "dates": {}}
            self._depth = 1
            return
        if self._item is None:
            return
        if tag == "li":
            self._depth += 1
        elif tag == "h3" and HEADING_CLASS in self._classes(attrs):
            self._heading = True
        elif tag == "a":
            match = MEDIA_PATTERN.match(values.get("href") or "")
            if match:
                self._item["paths"].append(match.group(1))
        elif tag == "time":
            self._time = values.get("datetime")

    def handle_endtag(self, tag: str) -> None:
        """Close an item, heading, or time."""
        if self._item is None:
            return
        if tag == "h3":
            self._heading = False
        elif tag == "time":
            self._time = None
        elif tag == "li":
            self._depth -= 1
            if self._depth == 0:
                self.items.append(self._item)
                self._item = None

    def handle_data(self, data: str) -> None:
        """Capture heading text and time labels."""
        if self._item is None:
            return
        if self._heading:
            self._item["title"] = (self._item["title"] or "") + data
        elif self._time:
            kind = TIME_KIND_PATTERN.search(data)
            if kind:
                self._item["dates"][kind.group(1)] = self._time

    def close(self) -> None:
        """Flush an item left open by unbalanced markup."""
        super().close()
        if self._item is not None:
            self.items.append(self._item)
            self._item = None


def cache_directory() -> str:
    """Resolve the ERS cache directory, honoring the environment override."""
    from openbb_core.app.utils import get_user_cache_directory

    return os.environ.get(CACHE_ENV_VAR) or os.path.join(
        get_user_cache_directory(), "usda", "ers"
    )


def get_cache() -> Any:
    """Open the diskcache store at the resolved cache directory."""
    from diskcache import Cache

    return Cache(cache_directory())


def compute_ttl(next_update: str | None, now: datetime | None = None) -> int:
    """Compute a cache TTL in seconds, expiring at the item's next update date.

    Parameters
    ----------
    next_update : str | None
        The 'Next Update' date as YYYY-MM-DD, when the product page shows one.
    now : datetime | None
        Reference time, defaulting to the current UTC time.

    Returns
    -------
    int
        Seconds until the end of the next-update day, clamped to at least one
        hour; the one-day default when no future next-update date is known.
    """
    if not next_update:
        return DEFAULT_FILE_TTL
    current = now or datetime.now(UTC)
    expiry = datetime.fromisoformat(next_update).replace(
        hour=23, minute=59, second=59, tzinfo=UTC
    )
    remaining = int((expiry - current).total_seconds())
    if remaining <= 0:
        return DEFAULT_FILE_TTL
    return max(remaining, MIN_FILE_TTL)


def parse_product_page(html: str) -> dict[str, dict]:
    """Parse an ERS data-product page into per-file metadata.

    Returns
    -------
    dict[str, dict]
        Keyed by the media path without the cache-busting query (e.g.
        '/media/4962/corn.csv'), each entry holding title, url,
        last_updated, and next_update.
    """
    parser = _CollectionParser()
    parser.feed(html)
    parser.close()
    files: dict[str, dict] = {}
    for item in parser.items:
        title = (item["title"] or "").strip()
        for path in item["paths"]:
            files[path] = {
                "title": title or None,
                "url": f"{BASE_URL}{path}",
                "last_updated": item["dates"].get("Last Updated"),
                "next_update": item["dates"].get("Next Update"),
            }
    return files


async def _download(url: str) -> bytes:
    """Download a URL as raw bytes."""
    from openbb_core.app.model.abstract.error import OpenBBError
    from openbb_core.provider.utils.helpers import amake_request

    async def read_bytes(response, _session) -> bytes:
        if response.status != 200:
            raise OpenBBError(
                f"ERS request failed with status {response.status} -> {url}"
            )
        return await response.read()

    result = await amake_request(
        url,
        response_callback=read_bytes,  # ty: ignore[invalid-argument-type]
    )
    return result  # ty: ignore[invalid-return-type]


async def get_product_files(product: str) -> dict[str, dict]:
    """Get the file inventory of an ERS data-product page, cached for a day.

    Parameters
    ----------
    product : str
        The page path after https://www.ers.usda.gov/, e.g.
        'data-products/commodity-costs-and-returns'.
    """
    key = f"page:{product}"
    with get_cache() as cache:
        cached = cache.get(key)
        if cached is not None:
            return cached
    url = f"{BASE_URL}/{product.strip('/')}"
    html = (await _download(url)).decode("utf-8", errors="replace")
    files = parse_product_page(html)
    with get_cache() as cache:
        cache.set(key, files, expire=PAGE_TTL)
    return files


async def afetch_ers_file(
    media_path: str,
    product: str | None = None,
    ttl: int | None = None,
) -> bytes:
    """Fetch an ERS media file through the disk cache.

    Parameters
    ----------
    media_path : str
        The media path, e.g. '/media/4962/corn.csv'.
    product : str | None
        Product page path used to resolve the file's next-update date for
        the TTL. Ignored when ttl is given.
    ttl : int | None
        Explicit TTL override in seconds.

    Returns
    -------
    bytes
        The raw file content.
    """
    key = f"file:{media_path}"
    with get_cache() as cache:
        cached = cache.get(key)
        if cached is not None:
            return cached
    if ttl is None and product is not None:
        files = await get_product_files(product)
        meta = files.get(media_path)
        ttl = compute_ttl(meta.get("next_update") if meta else None)
    content = await _download(f"{BASE_URL}{media_path}")
    with get_cache() as cache:
        cache.set(key, content, expire=ttl or DEFAULT_FILE_TTL)
    return content
