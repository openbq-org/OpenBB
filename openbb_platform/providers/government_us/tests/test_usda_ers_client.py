"""Tests for the USDA ERS disk-cache client."""

import asyncio
from datetime import UTC, datetime

import pytest
from openbb_core.app.model.abstract.error import OpenBBError

from openbb_government_us.usda.utils import ers_client

SAMPLE_PAGE = """
<li class="usa-collection__item maxw-full custom-list-item">
<div class="usa-collection__body">
<h3 class="usa-collection__heading">Corn</h3>
<a href="/media/4961/corn.xlsx?v=20628">Download (XLSX)</a>
 | <a href="/media/4962/corn.csv?v=35795">Download (CSV)</a>
<ul class="usa-collection__meta" aria-label="More information">
<li class="usa-collection__meta-item">
<time datetime="2026-05-01">Last Updated 5/1/2026</time>
</li>
<li class="usa-collection__meta-item">
<time datetime="2026-10-01">Next Update 10/1/2026</time>
</li>
</ul>
</div>
</li>
<li class="usa-collection__item maxw-full custom-list-item">
<div class="usa-collection__body">
<h3 class="usa-collection__heading">Archive</h3>
<a href="/media/4900/archive.zip?v=1">Download (ZIP)</a>
<ul class="usa-collection__meta" aria-label="More information">
<li class="usa-collection__meta-item">
<time datetime="2011-10-05">Last Updated 10/5/2011</time>
</li>
</ul>
</div>
</li>
"""


UNCLOSED_PAGE = """
<li class="usa-collection__item">
<h3 class="usa-collection__heading">First</h3>
<a href="/media/1/first.csv?v=1">Download (CSV)</a>
<time datetime="2026-01-01">Last Updated 1/1/2026</time>
<li class="usa-collection__item">
<h3 class="usa-collection__heading">Second</h3>
<a href="/media/2/second.csv?v=2">Download (CSV)</a>
<time datetime="2026-09-01">Next Update 9/1/2026</time>
"""


STRAY_MARKUP_PAGE = """
<div class="page-header"><p>Data Products</p></div>
<li class="usa-collection__item">
<h3 class="usa-collection__heading">Only</h3>
<a href="/media/3/only.csv?v=3">Download (CSV)</a>
</li>
<div class="page-footer"><p>Contact us</p></div>
"""


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    async def read(self) -> bytes:
        return self._body


def _patch_download(monkeypatch, pages: dict[str, bytes], calls: list[str]):
    async def fake_amake_request(url, response_callback=None, **kwargs):
        calls.append(url)
        return await response_callback(_FakeResponse(pages[url]), None)

    monkeypatch.setattr(
        "openbb_core.provider.utils.helpers.amake_request", fake_amake_request
    )


class TestCacheDirectory:
    """Tests for cache directory resolution."""

    def test_env_var_override(self, monkeypatch, tmp_path):
        """The environment variable overrides the default location."""
        monkeypatch.setenv(ers_client.CACHE_ENV_VAR, str(tmp_path / "custom"))
        assert ers_client.cache_directory() == str(tmp_path / "custom")

    def test_default_under_user_cache(self, monkeypatch):
        """Without the override, the platform user cache directory is used."""
        monkeypatch.delenv(ers_client.CACHE_ENV_VAR, raising=False)
        path = ers_client.cache_directory()
        assert path.endswith("usda/ers") or path.endswith("usda\\ers")


class TestComputeTtl:
    """Tests for TTL computation from next-update dates."""

    def test_future_next_update(self):
        """TTL runs to the end of the next-update day."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
        ttl = ers_client.compute_ttl("2026-07-17", now=now)
        assert ttl == int(
            (
                datetime(2026, 7, 17, 23, 59, 59, tzinfo=UTC) - now
            ).total_seconds()
        )

    def test_past_next_update_falls_back(self):
        """A stale next-update date falls back to the one-day default."""
        now = datetime(2026, 7, 16, tzinfo=UTC)
        assert ers_client.compute_ttl("2026-07-01", now=now) == (
            ers_client.DEFAULT_FILE_TTL
        )

    def test_missing_next_update_falls_back(self):
        """No next-update date falls back to the one-day default."""
        assert ers_client.compute_ttl(None) == ers_client.DEFAULT_FILE_TTL

    def test_minimum_clamp(self):
        """Imminent next-update dates clamp to the one-hour minimum."""
        now = datetime(2026, 7, 17, 23, 59, 0, tzinfo=UTC)
        assert ers_client.compute_ttl("2026-07-17", now=now) == ers_client.MIN_FILE_TTL


class TestParseProductPage:
    """Tests for product page parsing."""

    def test_parses_items_links_and_dates(self):
        """Each media link maps to its item's title and update dates."""
        files = ers_client.parse_product_page(SAMPLE_PAGE)
        assert set(files) == {
            "/media/4961/corn.xlsx",
            "/media/4962/corn.csv",
            "/media/4900/archive.zip",
        }
        corn = files["/media/4962/corn.csv"]
        assert corn["title"] == "Corn"
        assert corn["url"] == "https://www.ers.usda.gov/media/4962/corn.csv"
        assert corn["last_updated"] == "2026-05-01"
        assert corn["next_update"] == "2026-10-01"
        archive = files["/media/4900/archive.zip"]
        assert archive["last_updated"] == "2011-10-05"
        assert archive["next_update"] is None

    def test_unclosed_items_are_still_collected(self):
        """Items left open by missing </li> are closed at the next item and at EOF."""
        files = ers_client.parse_product_page(UNCLOSED_PAGE)
        assert files == {
            "/media/1/first.csv": {
                "title": "First",
                "url": "https://www.ers.usda.gov/media/1/first.csv",
                "last_updated": "2026-01-01",
                "next_update": None,
            },
            "/media/2/second.csv": {
                "title": "Second",
                "url": "https://www.ers.usda.gov/media/2/second.csv",
                "last_updated": None,
                "next_update": "2026-09-01",
            },
        }

    def test_markup_outside_the_collection_is_ignored(self):
        """Page chrome around the collection contributes no files or titles."""
        files = ers_client.parse_product_page(STRAY_MARKUP_PAGE)
        assert files == {
            "/media/3/only.csv": {
                "title": "Only",
                "url": "https://www.ers.usda.gov/media/3/only.csv",
                "last_updated": None,
                "next_update": None,
            }
        }


class TestDownload:
    """Tests for the raw download helper."""

    def test_non_200_raises(self, monkeypatch):
        """Non-200 responses raise OpenBBError."""

        async def fake_amake_request(url, response_callback=None, **kwargs):
            return await response_callback(_FakeResponse(b"", status=404), None)

        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.amake_request", fake_amake_request
        )
        with pytest.raises(OpenBBError, match="status 404"):
            asyncio.run(ers_client._download("https://www.ers.usda.gov/x"))


class TestFetchWithCache:
    """Tests for cached page and file fetching."""

    def test_product_files_cached(self, monkeypatch):
        """The product page is fetched once and served from cache after."""
        calls: list[str] = []
        _patch_download(
            monkeypatch,
            {"https://www.ers.usda.gov/data-products/x": SAMPLE_PAGE.encode()},
            calls,
        )
        first = asyncio.run(ers_client.get_product_files("data-products/x"))
        second = asyncio.run(ers_client.get_product_files("data-products/x"))
        assert first == second
        assert len(calls) == 1

    def test_file_fetch_uses_page_ttl_and_caches(self, monkeypatch):
        """File fetches resolve the TTL from the page and cache the bytes."""
        calls: list[str] = []
        _patch_download(
            monkeypatch,
            {
                "https://www.ers.usda.gov/data-products/x": SAMPLE_PAGE.encode(),
                "https://www.ers.usda.gov/media/4962/corn.csv": b"data",
            },
            calls,
        )
        first = asyncio.run(
            ers_client.afetch_ers_file(
                "/media/4962/corn.csv", product="data-products/x"
            )
        )
        second = asyncio.run(
            ers_client.afetch_ers_file(
                "/media/4962/corn.csv", product="data-products/x"
            )
        )
        assert first == second == b"data"
        assert calls == [
            "https://www.ers.usda.gov/data-products/x",
            "https://www.ers.usda.gov/media/4962/corn.csv",
        ]

    def test_file_fetch_with_explicit_ttl_skips_page(self, monkeypatch):
        """An explicit TTL bypasses the product page lookup."""
        calls: list[str] = []
        _patch_download(
            monkeypatch,
            {"https://www.ers.usda.gov/media/4900/archive.zip": b"zip"},
            calls,
        )
        content = asyncio.run(
            ers_client.afetch_ers_file("/media/4900/archive.zip", ttl=60)
        )
        assert content == b"zip"
        assert calls == ["https://www.ers.usda.gov/media/4900/archive.zip"]

    def test_file_fetch_unknown_media_path_uses_default_ttl(self, monkeypatch):
        """A file missing from the page metadata still fetches with defaults."""
        calls: list[str] = []
        _patch_download(
            monkeypatch,
            {
                "https://www.ers.usda.gov/data-products/x": SAMPLE_PAGE.encode(),
                "https://www.ers.usda.gov/media/9999/other.csv": b"other",
            },
            calls,
        )
        content = asyncio.run(
            ers_client.afetch_ers_file(
                "/media/9999/other.csv", product="data-products/x"
            )
        )
        assert content == b"other"
