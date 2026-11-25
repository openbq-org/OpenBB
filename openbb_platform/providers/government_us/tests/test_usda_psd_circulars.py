"""Tests for the USDA FAS PSD circular utils and model."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from openbb_core.app.model.abstract.error import OpenBBError

from openbb_government_us.usda.models.commodity_psd_report import (
    UsdaCommodityPsdReportFetcher,
    UsdaCommodityPsdReportQueryParams,
)
from openbb_government_us.usda.utils import psd_circulars as P

FOLDERS = [
    (2026, 7),
    (2026, 6),
    (2026, 5),
    (2026, 4),
    (2026, 3),
    (2026, 2),
    (2026, 1),
    (2025, 12),
    (2025, 11),
    (2025, 9),
]

PUBLISHED = {
    "grain": [
        (2025, 9),
        (2025, 11),
        (2025, 12),
        (2026, 1),
        (2026, 2),
        (2026, 3),
        (2026, 4),
        (2026, 5),
        (2026, 6),
        (2026, 7),
    ],
    "citrus": [(2025, 9), (2026, 1)],
    "tree_nuts": [(2026, 1)],
}

LISTING_BODY = json.dumps(
    {
        "DownloadPath": "/downloads/circulars/",
        "CircularSets": [
            {
                "CalendarYear": "2026",
                "Months": [
                    {"Item1": f"{month:02d}", "Item2": "x"}
                    for year, month in FOLDERS
                    if year == 2026
                ],
            },
            {
                "CalendarYear": "2025",
                "Months": [
                    {"Item1": f"{month:02d}", "Item2": "x"}
                    for year, month in FOLDERS
                    if year == 2025
                ],
            },
        ],
    }
)

NEXT_RELEASE_BODY = '"7/22/2026 3:00PM              "'


class _FakeResponse:
    """Mirrors the platform session's response, whose readers are awaited."""

    def __init__(self, status=200, headers=None, body=b"", text=""):
        self.status = status
        self.headers = headers or {}
        self._body = body
        self._text = text

    async def read(self):
        """Return the canned body bytes."""
        return self._body

    async def text(self):
        """Return the canned text body."""
        return self._text


class _FakeSession:
    """Mirrors the platform session, whose get and head are coroutines."""

    def __init__(self, handler):
        self._handler = handler
        self.requests: list = []
        self.closed = False

    async def get(self, url, **kwargs):
        """Record the request and return the handler's response."""
        self.requests.append(("GET", url, (kwargs.get("headers") or {}).get("Accept")))
        return self._handler("GET", url)

    async def head(self, url, **kwargs):
        """Record the request and return the handler's response."""
        self.requests.append(("HEAD", url, (kwargs.get("headers") or {}).get("Accept")))
        return self._handler("HEAD", url)

    async def close(self):
        """Mark the session closed."""
        self.closed = True


class _FakeSource:
    """Serves a synthetic carry-forward grid, as the source does.

    Every folder holds a copy of each commodity's most recent circular, so a
    folder answers with the ETag of the newest circular published on or before
    that folder's month, and 404s when the commodity had not published yet.
    """

    def __init__(self, published=None, folders=None):
        self.published = PUBLISHED if published is None else published
        self.folders = FOLDERS if folders is None else folders
        self.requests: list = []
        self.sessions: list = []

    def report_month(self, commodity, year, month):
        """Return the circular a folder carries for a commodity."""
        months = sorted(self.published.get(commodity, []))
        current = [p for p in months if p <= (year, month)]
        return current[-1] if current else None

    def handle(self, method, url):
        """Answer a request against the synthetic grid."""
        self.requests.append((method, url))
        if url == P.NEXT_RELEASE_URL:
            return _FakeResponse(text=NEXT_RELEASE_BODY)
        if url == P.LISTING_URL:
            return _FakeResponse(text=LISTING_BODY)
        circular = P.circular_from_url(url)
        published = self.report_month(
            circular["commodity"], circular["year"], circular["month"]
        )
        if published is None:
            return _FakeResponse(status=404)
        tag = f"{circular['commodity']}-{published[0]}{published[1]:02d}"
        return _FakeResponse(
            status=200,
            headers={
                "ETag": f'"{tag}"',
                "Last-Modified": "Fri, 30 Jan 2026 19:42:41 GMT",
                "Content-Length": str(len(tag) * 1000),
            },
            body=b"%PDF-1.7 " + tag.encode(),
        )

    def install(self, monkeypatch):
        """Point the module's session factory at this source."""

        async def _fake_session():
            session = _FakeSession(self.handle)
            self.sessions.append(session)
            return session

        monkeypatch.setattr(P, "_get_session", _fake_session)
        return self

    def heads(self):
        """Return every HEAD request the source received."""
        return [url for method, url in self.requests if method == "HEAD"]


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    """Point the disk cache at a per-test directory."""
    monkeypatch.setenv(P.CACHE_ENV_VAR, str(tmp_path / "cache"))


class TestCacheDirectory:
    """Tests for resolving the cache directory."""

    def test_environment_override_wins(self, tmp_path):
        """The environment variable overrides the platform cache directory."""
        assert P.cache_directory() == str(tmp_path / "cache")

    def test_defaults_under_the_platform_cache(self, monkeypatch):
        """Without an override the cache lives under the platform directory."""
        monkeypatch.delenv(P.CACHE_ENV_VAR, raising=False)
        assert Path(P.cache_directory()).as_posix().endswith("/usda/psd")

    def test_get_cache_opens_the_resolved_directory(self, tmp_path):
        """The store is opened at the resolved directory."""
        with P.get_cache() as cache:
            cache.set("k", "v")
        with P.get_cache() as cache:
            assert cache.get("k") == "v"
        assert (tmp_path / "cache").is_dir()


class TestComputeTtl:
    """Tests for the release-derived cache TTL."""

    NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)

    def test_no_release_uses_the_default(self):
        """Without a release timestamp the TTL is the one-day default."""
        assert P.compute_ttl(None) == P.DEFAULT_TTL
        assert P.compute_ttl("") == P.DEFAULT_TTL

    def test_unparsable_release_uses_the_default(self):
        """A timestamp the source did not format as expected is ignored."""
        assert P.compute_ttl("not a timestamp") == P.DEFAULT_TTL

    def test_expires_at_the_next_release(self):
        """The TTL runs out when the next circular is released."""
        ttl = P.compute_ttl("7/22/2026 3:00PM", now=self.NOW)
        assert ttl == int(
            (datetime(2026, 7, 22, 15, 0, tzinfo=UTC) - self.NOW).total_seconds()
        )

    def test_trailing_padding_is_ignored(self):
        """The source pads the timestamp with spaces."""
        assert P.compute_ttl("7/22/2026 3:00PM   ", now=self.NOW) == P.compute_ttl(
            "7/22/2026 3:00PM", now=self.NOW
        )

    def test_a_past_release_uses_the_default(self):
        """A release that already happened falls back to the default."""
        assert (
            P.compute_ttl("7/22/2026 3:00PM", now=datetime(2026, 8, 1, tzinfo=UTC))
            == P.DEFAULT_TTL
        )

    def test_an_imminent_release_is_clamped(self):
        """A release minutes away still caches for the minimum."""
        now = datetime(2026, 7, 22, 14, 59, tzinfo=UTC)
        assert P.compute_ttl("7/22/2026 3:00PM", now=now) == P.MIN_TTL

    def test_defaults_to_the_current_time(self):
        """Omitting the reference time uses the current time."""
        assert P.compute_ttl("7/22/2036 3:00PM") > P.MIN_TTL


class TestGetSession:
    """Tests for the session accessor."""

    def test_delegates_to_the_platform_session(self, monkeypatch):
        """The circular fetch uses a platform session."""

        async def fake_session():
            return "session"

        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.get_async_requests_session",
            fake_session,
        )
        assert asyncio.run(P._get_session()) == "session"


class TestGetNextRelease:
    """Tests for the release schedule that sets the cache TTL."""

    def test_reads_and_unquotes_the_timestamp(self, monkeypatch):
        """The source answers with a padded, quoted timestamp."""
        _FakeSource().install(monkeypatch)
        assert asyncio.run(P.get_next_release()) == "7/22/2026 3:00PM"

    def test_is_cached(self, monkeypatch):
        """The schedule is read once, not on every cached lookup."""
        source = _FakeSource().install(monkeypatch)
        asyncio.run(P.get_next_release())
        asyncio.run(P.get_next_release())
        assert source.requests.count(("GET", P.NEXT_RELEASE_URL)) == 1

    def test_a_non_200_yields_no_timestamp(self, monkeypatch):
        """A schedule the source does not serve is not an error."""
        monkeypatch.setattr(
            P,
            "_get_session",
            lambda: _wrap(_FakeSession(lambda m, u: _FakeResponse(status=404))),
        )
        assert asyncio.run(P.get_next_release()) is None

    def test_an_empty_body_yields_no_timestamp(self, monkeypatch):
        """An empty schedule is not an error."""
        monkeypatch.setattr(
            P,
            "_get_session",
            lambda: _wrap(_FakeSession(lambda m, u: _FakeResponse(text='""'))),
        )
        assert asyncio.run(P.get_next_release()) is None

    def test_a_request_failure_yields_no_timestamp(self, monkeypatch):
        """The schedule only sets a TTL, so a failure never breaks a fetch."""

        async def _boom():
            raise RuntimeError("schedule down")

        monkeypatch.setattr(P, "_get_session", _boom)
        assert asyncio.run(P.get_next_release()) is None

    def test_cache_ttl_derives_from_the_schedule(self, monkeypatch):
        """The TTL is computed from the next release timestamp."""
        _FakeSource().install(monkeypatch)
        assert asyncio.run(P.cache_ttl()) == P.compute_ttl("7/22/2026 3:00PM")


def _wrap(session):
    """Return a coroutine yielding the session, as the factory does."""

    async def _factory():
        return session

    return _factory()


class TestFetchFolders:
    """Tests for the month listing that bounds the folder universe."""

    def test_returns_every_folder_newest_first(self, monkeypatch):
        """The listing is normalized to newest-first (year, month) pairs."""
        _FakeSource().install(monkeypatch)
        assert asyncio.run(P.fetch_folders()) == FOLDERS

    def test_a_month_the_source_omits_is_never_invented(self, monkeypatch):
        """October 2025 was never published, so it is absent."""
        _FakeSource().install(monkeypatch)
        folders = asyncio.run(P.fetch_folders())
        assert (2025, 10) not in folders
        assert (2025, 11) in folders
        assert (2025, 9) in folders

    def test_is_cached(self, monkeypatch):
        """The listing is read once, then served from the cache."""
        source = _FakeSource().install(monkeypatch)
        asyncio.run(P.fetch_folders())
        asyncio.run(P.fetch_folders())
        assert source.requests.count(("GET", P.LISTING_URL)) == 1

    def test_a_non_200_raises(self, monkeypatch):
        """A listing the source does not serve raises."""
        monkeypatch.setattr(
            P,
            "_get_session",
            lambda: _wrap(_FakeSession(lambda m, u: _FakeResponse(status=500))),
        )
        with pytest.raises(OpenBBError, match="listing request failed with status 500"):
            asyncio.run(P.fetch_folders())

    def test_an_empty_listing_raises(self, monkeypatch):
        """An empty listing raises rather than reporting no months."""
        monkeypatch.setattr(
            P,
            "_get_session",
            lambda: _wrap(
                _FakeSession(
                    lambda m, u: _FakeResponse(
                        text=json.dumps({"CircularSets": [{"CalendarYear": "2026"}]})
                    )
                )
            ),
        )
        with pytest.raises(OpenBBError, match="listing is empty"):
            asyncio.run(P.fetch_folders())

    def test_a_listing_without_sets_raises(self, monkeypatch):
        """A payload carrying no circular sets raises."""
        monkeypatch.setattr(
            P,
            "_get_session",
            lambda: _wrap(_FakeSession(lambda m, u: _FakeResponse(text="{}"))),
        )
        with pytest.raises(OpenBBError, match="listing is empty"):
            asyncio.run(P.fetch_folders())

    def test_the_session_is_closed(self, monkeypatch):
        """The listing fetch releases its session."""
        source = _FakeSource().install(monkeypatch)
        asyncio.run(P.fetch_folders())
        assert all(session.closed for session in source.sessions)


class TestCircularUrl:
    """Tests for the static circular URL."""

    def test_builds_the_static_path(self):
        """The URL is the static path the source's app renders."""
        assert (
            P.circular_url(2026, 1, "citrus")
            == "https://apps.fas.usda.gov/PSDOnline/Circulars/2026/01/Citrus.pdf"
        )

    def test_the_month_is_zero_padded(self):
        """Single digit months are padded, as the folders are named."""
        assert P.circular_url(2026, 7, "grain").endswith("/2026/07/Grain.pdf")

    def test_every_commodity_maps_to_its_source_name(self):
        """The source names several commodities unlike their keys."""
        assert P.circular_url(2026, 1, "livestock").endswith("Livestock_poultry.pdf")
        assert P.circular_url(2026, 1, "stone_fruit").endswith("StoneFruit.pdf")
        assert P.circular_url(2026, 1, "tree_nuts").endswith("TreeNuts.pdf")
        assert P.circular_url(2026, 1, "world_production").endswith("production.pdf")

    def test_the_commodity_is_normalized(self):
        """A mixed-case, padded commodity resolves."""
        assert P.circular_url(2026, 1, " Citrus ") == P.circular_url(2026, 1, "citrus")

    def test_an_unsupported_commodity_raises(self):
        """A commodity the source does not publish is rejected."""
        with pytest.raises(OpenBBError, match="Unsupported PSD commodity"):
            P.circular_url(2026, 1, "unicorns")

    def test_it_is_not_the_carry_forward_downloader(self):
        """The .ashx downloader serves carry-forward copies and is not used."""
        assert "CircularDownloader.ashx" not in P.circular_url(2026, 1, "citrus")


class TestCircularFromUrl:
    """Tests for reading a circular back out of its URL."""

    def test_every_commodity_round_trips(self):
        """A URL built for a circular resolves back to that circular."""
        for commodity in P.COMMODITIES:
            url = P.circular_url(2026, 3, commodity)
            assert P.circular_from_url(url) == {
                "commodity": commodity,
                "year": 2026,
                "month": 3,
            }

    def test_foreign_host_raises(self):
        """Only the PSD host is fetched, so other hosts are rejected."""
        with pytest.raises(OpenBBError, match="Invalid PSD circular URL"):
            P.circular_from_url(
                "https://evil.example.com/PSDOnline/Circulars/2026/01/Citrus.pdf"
            )

    def test_other_path_on_the_same_host_raises(self):
        """A PSD URL that is not a circular is rejected."""
        with pytest.raises(OpenBBError, match="Invalid PSD circular URL"):
            P.circular_from_url(P.LISTING_URL)

    def test_the_carry_forward_downloader_is_rejected(self):
        """The .ashx downloader never 404s, so its URLs are not accepted."""
        with pytest.raises(OpenBBError, match="Invalid PSD circular URL"):
            P.circular_from_url(
                "https://apps.fas.usda.gov/PSDOnline/CircularDownloader.ashx"
                "?year=2026&month=02&commodity=Citrus"
            )

    def test_a_malformed_month_raises(self):
        """A path that is not a year and zero-padded month is rejected."""
        with pytest.raises(OpenBBError, match="Invalid PSD circular URL"):
            P.circular_from_url(
                "https://apps.fas.usda.gov/PSDOnline/Circulars/2026/1/Citrus.pdf"
            )

    def test_a_non_pdf_raises(self):
        """A path that does not address a PDF is rejected."""
        with pytest.raises(OpenBBError, match="Invalid PSD circular URL"):
            P.circular_from_url(
                "https://apps.fas.usda.gov/PSDOnline/Circulars/2026/01/Citrus.exe"
            )

    def test_an_unknown_commodity_raises(self):
        """A well-formed URL naming an unpublished commodity is rejected."""
        with pytest.raises(OpenBBError, match="Unknown PSD commodity"):
            P.circular_from_url(
                "https://apps.fas.usda.gov/PSDOnline/Circulars/2026/01/Unicorns.pdf"
            )


class TestCircularFileName:
    """Tests for the downloaded file's name."""

    def test_names_the_commodity_and_its_report_month(self):
        """The file name is derived entirely from the URL."""
        url = P.circular_url(2026, 1, "citrus")
        assert P.circular_file_name(url) == "psd_report_citrus_2026_01.pdf"

    def test_the_month_is_zero_padded(self):
        """The name pads the month, matching the folder."""
        url = P.circular_url(2025, 9, "stone_fruit")
        assert P.circular_file_name(url) == "psd_report_stone_fruit_2025_09.pdf"

    def test_an_invalid_url_raises(self):
        """A URL that is not a circular has no file name."""
        with pytest.raises(OpenBBError, match="Invalid PSD circular URL"):
            P.circular_file_name("https://evil.example.com/x.pdf")


class TestReleasedAt:
    """Tests for parsing the release timestamp."""

    def test_parses_an_http_date(self):
        """A Last-Modified header becomes an aware datetime."""
        assert P._released_at("Fri, 30 Jan 2026 19:42:41 GMT") == datetime(
            2026, 1, 30, 19, 42, 41, tzinfo=UTC
        )

    def test_no_header_yields_none(self):
        """A missing header yields no timestamp."""
        assert P._released_at(None) is None
        assert P._released_at("") is None

    def test_an_unparsable_header_yields_none(self):
        """A header the source did not format as a date yields no timestamp."""
        assert P._released_at("whenever") is None


class TestHeadCircular:
    """Tests for reading a circular's headers."""

    def test_returns_the_etag_length_and_timestamp(self, monkeypatch):
        """A served circular reports the headers that identify it."""
        _FakeSource().install(monkeypatch)
        head = asyncio.run(P.head_circular(P.circular_url(2026, 1, "citrus")))
        assert head == {
            "etag": '"citrus-202601"',
            "last_modified": "Fri, 30 Jan 2026 19:42:41 GMT",
            "length": 13000,
        }

    def test_asks_for_a_pdf(self, monkeypatch):
        """The host answers 406 unless the request accepts a PDF."""
        source = _FakeSource().install(monkeypatch)
        asyncio.run(P.head_circular(P.circular_url(2026, 1, "citrus")))
        assert source.sessions[0].requests[0][2] == "application/pdf"

    def test_a_missing_folder_yields_none(self, monkeypatch):
        """The static path 404s for a folder the source does not hold."""
        _FakeSource().install(monkeypatch)
        assert (
            asyncio.run(P.head_circular(P.circular_url(2025, 9, "tree_nuts"))) is None
        )

    def test_a_response_without_a_length_yields_none(self, monkeypatch):
        """A circular served without a length reports no size."""
        monkeypatch.setattr(
            P,
            "_get_session",
            lambda: _wrap(
                _FakeSession(lambda m, u: _FakeResponse(headers={"ETag": '"x"'}))
            ),
        )
        head = asyncio.run(P.head_circular(P.circular_url(2026, 1, "citrus")))
        assert head == {"etag": '"x"', "last_modified": None, "length": None}

    def test_an_unexpected_status_raises(self, monkeypatch):
        """A status that is neither 200 nor 404 raises."""
        monkeypatch.setattr(
            P,
            "_get_session",
            lambda: _wrap(_FakeSession(lambda m, u: _FakeResponse(status=406))),
        )
        with pytest.raises(OpenBBError, match="request failed with status 406"):
            asyncio.run(P.head_circular(P.circular_url(2026, 1, "citrus")))

    def test_both_hits_and_misses_are_cached(self, monkeypatch):
        """A 404 caches too, so a missing folder is asked for once."""
        source = _FakeSource().install(monkeypatch)
        url = P.circular_url(2025, 9, "tree_nuts")
        assert asyncio.run(P.head_circular(url)) is None
        assert asyncio.run(P.head_circular(url)) is None
        assert source.heads().count(url) == 1

    def test_the_session_is_closed(self, monkeypatch):
        """The head request releases its session."""
        source = _FakeSource().install(monkeypatch)
        asyncio.run(P.head_circular(P.circular_url(2026, 1, "citrus")))
        assert all(session.closed for session in source.sessions)


class TestLatestCirculars:
    """Tests for resolving each commodity's newest circular."""

    def test_resolves_the_true_report_month_not_the_newest_folder(self, monkeypatch):
        """Citrus last published in January, though every later folder holds it."""
        _FakeSource().install(monkeypatch)
        rows = asyncio.run(P.latest_circulars("citrus"))
        assert len(rows) == 1
        assert (rows[0]["year"], rows[0]["month"]) == (2026, 1)
        assert rows[0]["url"] == P.circular_url(2026, 1, "citrus")

    def test_a_carry_forward_month_is_never_offered(self, monkeypatch):
        """February holds a byte-identical copy, so it is not a report."""
        _FakeSource().install(monkeypatch)
        rows = asyncio.run(P.latest_circulars("citrus"))
        offered = {(row["year"], row["month"]) for row in rows}
        assert (2026, 2) not in offered
        assert (2026, 7) not in offered
        assert offered == {(2026, 1)}

    def test_a_commodity_published_in_the_newest_folder(self, monkeypatch):
        """Grain published this month, so the newest folder is its report."""
        _FakeSource().install(monkeypatch)
        rows = asyncio.run(P.latest_circulars("grain"))
        assert (rows[0]["year"], rows[0]["month"]) == (2026, 7)

    def test_folders_predating_a_commodity_are_handled(self, monkeypatch):
        """Tree nuts 404 before their first circular, which is not a gap."""
        _FakeSource().install(monkeypatch)
        rows = asyncio.run(P.latest_circulars("tree_nuts"))
        assert (rows[0]["year"], rows[0]["month"]) == (2026, 1)

    def test_reports_the_full_record(self, monkeypatch):
        """Each record carries the source's own name, size and timestamp."""
        _FakeSource().install(monkeypatch)
        assert asyncio.run(P.latest_circulars("tree_nuts"))[0] == {
            "commodity": "tree_nuts",
            "api_commodity": "TreeNuts",
            "year": 2026,
            "month": 1,
            "url": P.circular_url(2026, 1, "tree_nuts"),
            "released_at": datetime(2026, 1, 30, 19, 42, 41, tzinfo=UTC),
            "size": 16000,
        }

    def test_every_commodity_is_resolved_by_default(self, monkeypatch):
        """Without a commodity every published commodity is offered."""
        _FakeSource().install(monkeypatch)
        rows = asyncio.run(P.latest_circulars())
        assert {row["commodity"] for row in rows} == set(PUBLISHED)

    def test_a_commodity_no_folder_holds_is_dropped(self, monkeypatch):
        """A commodity the source never published is not offered."""
        _FakeSource().install(monkeypatch)
        rows = asyncio.run(P.latest_circulars())
        assert "coffee" not in {row["commodity"] for row in rows}
        assert asyncio.run(P.latest_circulars("coffee")) == []

    def test_the_commodity_is_normalized(self, monkeypatch):
        """A mixed-case, padded commodity resolves."""
        _FakeSource().install(monkeypatch)
        assert asyncio.run(P.latest_circulars(" Citrus "))[0]["commodity"] == "citrus"

    def test_an_unsupported_commodity_raises(self, monkeypatch):
        """A commodity the source does not publish is rejected."""
        _FakeSource().install(monkeypatch)
        with pytest.raises(OpenBBError, match="Unsupported PSD commodity"):
            asyncio.run(P.latest_circulars("unicorns"))

    def test_the_walk_is_bounded(self, monkeypatch):
        """A run longer than the bound stops at the window's edge."""
        folders = [(2026, month) for month in range(12, 0, -1)] + [
            (2025, month) for month in range(12, 0, -1)
        ]
        source = _FakeSource(
            published={"citrus": [(2025, 1)]}, folders=folders
        ).install(monkeypatch)
        monkeypatch.setattr(P, "fetch_folders", _folders(folders))
        rows = asyncio.run(P.latest_circulars("citrus"))
        assert rows[0] == {
            "commodity": "citrus",
            "api_commodity": "Citrus",
            "year": folders[P.MAX_CARRY_FORWARD][0],
            "month": folders[P.MAX_CARRY_FORWARD][1],
            "url": P.circular_url(*folders[P.MAX_CARRY_FORWARD], "citrus"),
            "released_at": datetime(2026, 1, 30, 19, 42, 41, tzinfo=UTC),
            "size": 13000,
        }
        assert len(source.heads()) <= P.MAX_CARRY_FORWARD + 1

    def test_the_default_does_not_probe_every_folder(self, monkeypatch):
        """Carry-forward means the newest folder answers for every commodity."""
        source = _FakeSource().install(monkeypatch)
        asyncio.run(P.latest_circulars("citrus"))
        assert len(source.heads()) < len(FOLDERS)


class TestHistoricalCirculars:
    """Tests for enumerating every historical circular of one commodity."""

    def test_returns_each_distinct_publication_newest_first(self, monkeypatch):
        """Citrus published twice; carry-forward copies collapse to those two."""
        _FakeSource().install(monkeypatch)
        rows = asyncio.run(P.historical_circulars("citrus"))
        assert [(row["year"], row["month"]) for row in rows] == [(2026, 1), (2025, 9)]

    def test_every_month_publishes_a_distinct_circular(self, monkeypatch):
        """Grain publishes in every folder, so each is its own report."""
        _FakeSource().install(monkeypatch)
        rows = asyncio.run(P.historical_circulars("grain"))
        assert [(row["year"], row["month"]) for row in rows] == sorted(
            PUBLISHED["grain"], reverse=True
        )

    def test_folders_predating_the_first_circular_are_skipped(self, monkeypatch):
        """Tree nuts 404 before January, so only the one report is offered."""
        _FakeSource().install(monkeypatch)
        rows = asyncio.run(P.historical_circulars("tree_nuts"))
        assert [(row["year"], row["month"]) for row in rows] == [(2026, 1)]

    def test_reports_the_full_record(self, monkeypatch):
        """Each record carries the source name, size, timestamp, and url."""
        _FakeSource().install(monkeypatch)
        assert asyncio.run(P.historical_circulars("tree_nuts"))[0] == {
            "commodity": "tree_nuts",
            "api_commodity": "TreeNuts",
            "year": 2026,
            "month": 1,
            "url": P.circular_url(2026, 1, "tree_nuts"),
            "released_at": datetime(2026, 1, 30, 19, 42, 41, tzinfo=UTC),
            "size": 16000,
        }

    def test_a_commodity_no_folder_holds_is_empty(self, monkeypatch):
        """A commodity the source never published yields no circulars."""
        _FakeSource().install(monkeypatch)
        assert asyncio.run(P.historical_circulars("coffee")) == []

    def test_an_unsupported_commodity_raises(self, monkeypatch):
        """A commodity the source does not publish is rejected."""
        _FakeSource().install(monkeypatch)
        with pytest.raises(OpenBBError, match="Unsupported PSD commodity"):
            asyncio.run(P.historical_circulars("unicorns"))


def _folders(folders):
    """Return a fetch_folders stand-in serving a fixed folder list."""

    async def _fetch():
        return folders

    return _fetch


class TestAfetchCircular:
    """Tests for downloading a circular."""

    def test_returns_pdf_bytes(self, monkeypatch):
        """A served circular is returned as raw bytes."""
        _FakeSource().install(monkeypatch)
        content = asyncio.run(P.afetch_circular(P.circular_url(2026, 1, "citrus")))
        assert content == b"%PDF-1.7 citrus-202601"

    def test_asks_for_a_pdf(self, monkeypatch):
        """The host answers 406 unless the request accepts a PDF."""
        source = _FakeSource().install(monkeypatch)
        asyncio.run(P.afetch_circular(P.circular_url(2026, 1, "citrus")))
        assert source.sessions[0].requests[0][2] == "application/pdf"

    def test_rejects_a_foreign_url_before_fetching(self, monkeypatch):
        """A URL outside the PSD host never reaches the network."""
        source = _FakeSource().install(monkeypatch)
        with pytest.raises(OpenBBError, match="Invalid PSD circular URL"):
            asyncio.run(P.afetch_circular("https://evil.example.com/x.pdf"))
        assert source.requests == []

    def test_a_missing_circular_raises(self, monkeypatch):
        """The static path 404s rather than serving a carry-forward copy."""
        _FakeSource().install(monkeypatch)
        with pytest.raises(OpenBBError, match="request failed with status 404"):
            asyncio.run(P.afetch_circular(P.circular_url(2025, 9, "tree_nuts")))

    def test_a_non_pdf_raises(self, monkeypatch):
        """A response that is not a PDF raises rather than returning junk."""
        monkeypatch.setattr(
            P,
            "_get_session",
            lambda: _wrap(
                _FakeSession(lambda m, u: _FakeResponse(body=b"<html>error</html>"))
            ),
        )
        with pytest.raises(OpenBBError, match="bytes that are not a PDF"):
            asyncio.run(P.afetch_circular(P.circular_url(2026, 1, "citrus")))

    def test_is_cached(self, monkeypatch):
        """A downloaded circular is served from the cache."""
        source = _FakeSource().install(monkeypatch)
        url = P.circular_url(2026, 1, "citrus")
        first = asyncio.run(P.afetch_circular(url))
        second = asyncio.run(P.afetch_circular(url))
        assert first == second
        assert source.requests.count(("GET", url)) == 1

    def test_the_session_is_closed(self, monkeypatch):
        """The download releases its session."""
        source = _FakeSource().install(monkeypatch)
        asyncio.run(P.afetch_circular(P.circular_url(2026, 1, "citrus")))
        assert all(session.closed for session in source.sessions)


class TestUsdaCommodityPsdReport:
    """Tests for the UsdaCommodityPsdReport model."""

    URL_CITRUS = P.circular_url(2026, 1, "citrus")
    URL_GRAIN = P.circular_url(2026, 7, "grain")

    def test_urls_are_required(self):
        """A request without a file selection is rejected."""
        with pytest.raises(ValueError, match="urls"):
            UsdaCommodityPsdReportQueryParams()

    def test_multiple_items_are_allowed_for_urls(self):
        """The Workspace reads the multi-file contract off the schema."""
        assert UsdaCommodityPsdReportQueryParams.__json_schema_extra__["urls"] == {
            "multiple_items_allowed": True
        }

    @staticmethod
    def _patch(monkeypatch, pdf=b"%PDF-1.7 circular"):
        requested: list = []

        async def fake_fetch(url):
            requested.append(url)
            if isinstance(pdf, Exception):
                raise pdf
            return pdf

        monkeypatch.setattr(
            "openbb_government_us.usda.utils.psd_circulars.afetch_circular",
            fake_fetch,
        )
        return requested

    @staticmethod
    def _fetch(urls, monkeypatch, pdf=b"%PDF-1.7 circular"):
        requested = TestUsdaCommodityPsdReport._patch(monkeypatch, pdf)
        query = UsdaCommodityPsdReportFetcher.transform_query({"urls": urls})
        raw = asyncio.run(UsdaCommodityPsdReportFetcher.aextract_data(query, None))
        return requested, UsdaCommodityPsdReportFetcher.transform_data(query, raw)

    def test_urls_accepts_a_list(self, monkeypatch):
        """Each URL in a list is downloaded."""
        requested, results = self._fetch([self.URL_CITRUS, self.URL_GRAIN], monkeypatch)
        assert requested == [self.URL_CITRUS, self.URL_GRAIN]
        assert len(results) == 2

    def test_urls_accepts_a_comma_separated_string(self, monkeypatch):
        """A single string of URLs is split and whitespace is trimmed."""
        requested, results = self._fetch(
            f" {self.URL_CITRUS} , {self.URL_GRAIN} ", monkeypatch
        )
        assert requested == [self.URL_CITRUS, self.URL_GRAIN]
        assert len(results) == 2

    def test_urls_accepts_the_workspace_dict_form(self, monkeypatch):
        """The Workspace posts the file selection as a dict."""
        requested, results = self._fetch({"urls": [self.URL_CITRUS]}, monkeypatch)
        assert requested == [self.URL_CITRUS]
        assert len(results) == 1

    def test_encodes_the_pdf_with_a_descriptive_filename(self, monkeypatch):
        """The PDF is base64 encoded and named after the circular it addresses."""
        import base64

        _, results = self._fetch([self.URL_CITRUS], monkeypatch)
        row = results[0]
        assert base64.b64decode(row.content) == b"%PDF-1.7 circular"
        assert row.error_type is None
        assert row.filename == "psd_report_citrus_2026_01.pdf"
        assert row.data_format == {
            "data_type": "pdf",
            "filename": "psd_report_citrus_2026_01.pdf",
        }

    def test_an_unpopulated_field_is_omitted(self, monkeypatch):
        """A successful row carries no error, so no error column is rendered."""
        _, results = self._fetch([self.URL_CITRUS], monkeypatch)
        assert "error_type" not in results[0].model_dump()

    def test_an_invalid_url_reports_without_downloading(self, monkeypatch):
        """A URL the source does not serve is reported, not fetched."""
        requested, results = self._fetch(
            ["https://evil.example.com/PSDOnline/Circulars/2026/01/Citrus.pdf"],
            monkeypatch,
        )
        assert requested == []
        assert results[0].error_type == "invalid_url"
        assert results[0].filename is None
        assert "Invalid PSD circular URL" in results[0].content

    def test_the_carry_forward_downloader_is_rejected(self, monkeypatch):
        """The .ashx downloader never 404s, so it is not a valid selection."""
        requested, results = self._fetch(
            [
                "https://apps.fas.usda.gov/PSDOnline/CircularDownloader.ashx"
                "?year=2026&month=02&commodity=Citrus"
            ],
            monkeypatch,
        )
        assert requested == []
        assert results[0].error_type == "invalid_url"

    def test_a_download_failure_reports_that_url_only(self, monkeypatch):
        """One failed circular does not discard the circulars that succeeded."""
        calls: list = []

        async def fake_fetch(url):
            calls.append(url)
            if url == self.URL_CITRUS:
                raise OpenBBError("the PSD circular request failed with status 404")
            return b"%PDF-1.7 circular"

        monkeypatch.setattr(
            "openbb_government_us.usda.utils.psd_circulars.afetch_circular",
            fake_fetch,
        )
        query = UsdaCommodityPsdReportFetcher.transform_query(
            {"urls": [self.URL_CITRUS, self.URL_GRAIN]}
        )
        raw = asyncio.run(UsdaCommodityPsdReportFetcher.aextract_data(query, None))
        results = UsdaCommodityPsdReportFetcher.transform_data(query, raw)
        assert calls == [self.URL_CITRUS, self.URL_GRAIN]
        assert results[0].error_type == "download_error"
        assert results[0].filename == "psd_report_citrus_2026_01.pdf"
        assert "status 404" in results[0].content
        assert results[1].error_type is None
