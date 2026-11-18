"""Tests for openbb_government_us.congress.utils.bulk (GovInfo bulk-data path)."""

import asyncio
import io
import os
import tempfile
import zipfile
from datetime import date
from pathlib import Path

import pytest
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils import helpers as core_helpers

from openbb_government_us.congress.utils import bulk
from openbb_government_us.congress.utils.helpers import BillsState

_BILLSTATUS_29 = """<billStatus><bill>
  <number>29</number><congress>119</congress><type>HR</type>
  <originChamber>House</originChamber><originChamberCode>H</originChamberCode>
  <introducedDate>2025-01-03</introducedDate>
  <updateDate>2025-11-30T06:37:21Z</updateDate>
  <updateDateIncludingText>2025-11-30T06:37:21Z</updateDateIncludingText>
  <title>Laken Riley Act</title>
  <latestAction><actionDate>2025-02-10</actionDate><text>Read the second time.</text></latestAction>
  <policyArea><name>Immigration</name></policyArea>
  <sponsors><item><bioguideId>C001129</bioguideId><fullName>Rep. Collins</fullName></item></sponsors>
  <cosponsors><item><fullName>Rep. Allen</fullName><isOriginalCosponsor>True</isOriginalCosponsor><sponsorshipDate>2025-01-03</sponsorshipDate></item></cosponsors>
  <actions><item><actionDate>2025-02-10</actionDate><text>Read.</text><type>Calendars</type></item></actions>
  <committees><item><systemCode>hsju00</systemCode><name>Judiciary Committee</name><chamber>House</chamber><type>Standing</type></item></committees>
  <relatedBills><item><title>Companion</title><congress>119</congress><number>5</number><type>S</type></item></relatedBills>
  <subjects><legislativeSubjects><item><name>Border security</name><updateDate>2025-01-08T19:36:54Z</updateDate></item></legislativeSubjects><policyArea><name>Immigration</name></policyArea></subjects>
  <titles><item><titleType>Short Title</titleType><title>Laken Riley Act</title><chamberName>Senate</chamberName><billTextVersionName>Introduced</billTextVersionName><updateDate>2025-02-12T02:53:16Z</updateDate></item><item><title>No Type Title</title></item></titles>
  <summaries><summary><versionCode>00</versionCode><actionDate>2025-01-03</actionDate><actionDesc>Introduced in House</actionDesc><updateDate>2025-01-13T16:36:38Z</updateDate><text>&lt;p&gt;&lt;strong&gt;Laken Riley Act&lt;/strong&gt;&lt;/p&gt;&lt;p&gt;This bill.&lt;/p&gt;</text></summary></summaries>
  <textVersions><item><type>Introduced in House</type><date>2025-01-03T05:00:00Z</date><formats><item><url>https://www.govinfo.gov/content/pkg/BILLS-119hr29ih/xml/BILLS-119hr29ih.xml</url></item></formats></item></textVersions>
  <amendments>
    <amendment>
      <number>10</number><congress>119</congress><type>HAMDT</type>
      <description>An amendment in the nature of a substitute.</description><purpose>To amend.</purpose>
      <chamber>House of Representatives</chamber>
      <updateDate>2025-02-09T08:00:00Z</updateDate>
      <proposedDate>2025-02-08T05:00:00Z</proposedDate>
      <submittedDate>2025-02-08T05:00:00Z</submittedDate>
      <latestAction><actionDate>2025-02-09</actionDate><actionTime>10:00</actionTime><text>Agreed.</text></latestAction>
      <sponsors><item><fullName>Rep. Collins</fullName></item></sponsors>
      <cosponsors><item><fullName>Rep. Allen</fullName></item></cosponsors>
      <actions><actions><item><actionDate>2025-02-09</actionDate><text>Agreed.</text><type>X</type></item></actions></actions>
      <links><link><name>House Report 119-1</name><url>https://www.congress.gov/x</url></link></links>
      <amendedBill><congress>119</congress><type>HR</type><number>29</number><title>Laken Riley Act</title></amendedBill>
    </amendment>
    <amendment>
      <number>11</number><congress>119</congress><type>SAMDT</type>
      <description>Senate amendment.</description>
      <updateDate>2025-02-11T08:00:00Z</updateDate>
      <latestAction><actionDate>2025-02-11</actionDate><text>Submitted.</text></latestAction>
      <amendedAmendment><congress>119</congress><type>HAMDT</type><number>10</number></amendedAmendment>
    </amendment>
  </amendments>
</bill></billStatus>"""

_BILLSTATUS_5 = """<billStatus><bill>
  <number>5</number><congress>119</congress><type>HR</type>
  <originChamber>House</originChamber><originChamberCode>H</originChamberCode>
  <introducedDate>2025-03-01</introducedDate>
  <updateDate>2025-03-15T00:00:00Z</updateDate>
  <updateDateIncludingText>2025-03-15T00:00:00Z</updateDateIncludingText>
  <title>Other Act</title>
  <latestAction><actionDate>2025-03-20</actionDate><text>Passed House.</text></latestAction>
  <policyArea><name>Health</name></policyArea>
  <sponsors><item><fullName>Rep. Smith</fullName></item></sponsors>
</bill></billStatus>"""

_BILLSTATUS_NO_BILL = "<billStatus><notabill/></billStatus>"


def _zip_bytes(members: dict[str, str]) -> bytes:
    """Build an in-memory ZIP archive from ``{member_name: text}``."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return buf.getvalue()


def _billstatus_zip() -> bytes:
    """Return a BILLSTATUS ZIP with two bills, a non-bill member, and a non-XML file."""
    return _zip_bytes(
        {
            "BILLSTATUS-119hr29.xml": _BILLSTATUS_29,
            "BILLSTATUS-119hr5.xml": _BILLSTATUS_5,
            "BILLSTATUS-119hr7.xml": _BILLSTATUS_NO_BILL,
            "README.txt": "ignored non-xml member",
        }
    )


def test_bulk_zip_url():
    """bulk_zip_url builds the canonical GovInfo bulk ZIP URL."""
    url = bulk.bulk_zip_url("BILLSTATUS", 119, "HR")
    assert url == (
        "https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hr/BILLSTATUS-119-hr.zip"
    )


def test_parse_bill_ref_ok():
    """Dash id, shorthand, leading-slash, and full-URL references parse correctly."""
    assert bulk.parse_bill_ref("119-hr-29") == (119, "hr", 29)
    assert bulk.parse_bill_ref("119-HR-29") == (119, "hr", 29)
    assert bulk.parse_bill_ref("119/hr/29") == (119, "hr", 29)
    assert bulk.parse_bill_ref("/119/HR/29") == (119, "hr", 29)
    assert bulk.parse_bill_ref(
        "https://api.congress.gov/v3/bill/119/s/1947?format=json"
    ) == (119, "s", 1947)


def test_parse_bill_ref_raises():
    """An unparseable reference raises OpenBBError."""
    with pytest.raises(OpenBBError, match="Could not parse"):
        bulk.parse_bill_ref("not-a-bill")


def test_cache_dir(monkeypatch, tmp_path):
    """_cache_dir builds and creates the bulkdata cache path under the user cache."""
    from openbb_core.app import utils as core_utils

    monkeypatch.setattr(core_utils, "get_user_cache_directory", lambda: str(tmp_path))
    path = bulk._cache_dir()
    assert path == os.path.join(str(tmp_path), "congress_gov", "bulkdata")
    assert os.path.isdir(path)


def test_cache_dir_not_writable(monkeypatch, tmp_path):
    """_cache_dir returns None when the cache directory cannot be created."""
    from openbb_core.app import utils as core_utils

    monkeypatch.setattr(core_utils, "get_user_cache_directory", lambda: str(tmp_path))

    def _raise(*_args, **_kwargs):
        raise PermissionError("read-only file system")

    monkeypatch.setattr(bulk.os, "makedirs", _raise)
    assert bulk._cache_dir() is None


def test_text_empty_self_closing():
    """_text returns an empty string when the found node has no text."""
    from defusedxml.ElementTree import fromstring

    root = fromstring("<bill><title/></bill>")
    assert bulk._text(root, "title") == ""
    assert bulk._text(root, "missing") == ""


def test_parse_billstatus_all_blocks():
    """parse_billstatus maps every nested block from the BILLSTATUS XML."""
    records = bulk.parse_billstatus(_billstatus_zip())
    by_number = {r["number"]: r for r in records}
    assert set(by_number) == {29, 5}

    rec = by_number[29]
    assert rec["congress"] == 119
    assert rec["type"] == "HR"
    assert rec["bill_id"] == "119-hr-29"
    assert rec["originChamber"] == "House"
    assert rec["originChamberCode"] == "H"
    assert rec["title"] == "Laken Riley Act"
    assert rec["introducedDate"] == "2025-01-03"
    assert rec["latestAction"] == {
        "actionDate": "2025-02-10",
        "text": "Read the second time.",
    }
    assert rec["policyArea"] == {"name": "Immigration"}
    assert rec["sponsors"][0]["fullName"] == "Rep. Collins"
    assert rec["cosponsors"][0]["isOriginalCosponsor"] is True
    assert rec["actions"][0]["type"] == "Calendars"
    assert rec["committees"][0]["systemCode"] == "hsju00"
    assert rec["relatedBills"][0]["number"] == "5"
    assert rec["subjects"][0]["name"] == "Border security"
    assert rec["titles"][0]["type"] == "Short Title"
    assert rec["titles"][1]["type"] == ""
    assert "Laken Riley Act" in rec["summaries"][0]["text"]
    assert rec["summaries"][0]["versionCode"] == "00"
    assert rec["textVersions"][0]["type"] == "Introduced in House"
    assert rec["textVersions"][0]["formats"][0]["url"].endswith(
        "/BILLS-119hr29ih/xml/BILLS-119hr29ih.xml"
    )


def test_derive_text_formats():
    """derive_text_formats builds pdf/htm/xml URLs from the package id."""
    version = {
        "type": "Introduced in House",
        "date": "2025-01-03T05:00:00Z",
        "formats": [
            {
                "url": "https://www.govinfo.gov/content/pkg/BILLS-119hr29ih/xml/BILLS-119hr29ih.xml"
            }
        ],
    }
    out = bulk.derive_text_formats(version)
    assert out["version_type"] == "Introduced in House"
    assert out["pdf"].endswith("/content/pkg/BILLS-119hr29ih/pdf/BILLS-119hr29ih.pdf")
    assert out["htm"].endswith("/content/pkg/BILLS-119hr29ih/html/BILLS-119hr29ih.htm")
    assert out["xml"].endswith("/content/pkg/BILLS-119hr29ih/xml/BILLS-119hr29ih.xml")


def test_derive_text_formats_congress_gov_urls():
    """Congress.gov API text versions resolve to the same GovInfo package.

    The API links at congress.gov (no ``/content/pkg/`` segment), carrying the
    package id only in the filename, so the viewer produced no choices at all
    for any Congress served by the API.
    """
    version = {
        "type": "Enrolled Bill",
        "date": None,
        "formats": [
            {
                "type": "Formatted Text",
                "url": "https://www.congress.gov/107/bills/hr3162/BILLS-107hr3162enr.htm",
            },
            {
                "type": "PDF",
                "url": "https://www.congress.gov/107/bills/hr3162/BILLS-107hr3162enr.pdf",
            },
        ],
    }
    out = bulk.derive_text_formats(version)

    assert out["version_type"] == "Enrolled Bill"
    assert out["version_date"] == ""
    assert out["pdf"].endswith(
        "/content/pkg/BILLS-107hr3162enr/pdf/BILLS-107hr3162enr.pdf"
    )
    assert out["htm"].endswith(
        "/content/pkg/BILLS-107hr3162enr/html/BILLS-107hr3162enr.htm"
    )
    assert out["xml"].endswith(
        "/content/pkg/BILLS-107hr3162enr/xml/BILLS-107hr3162enr.xml"
    )


def test_derive_text_formats_scans_every_format():
    """A package id is found even when it is not on the first format listed."""
    version = {
        "type": "Introduced in House",
        "date": "2001-10-23T04:00:00Z",
        "formats": [
            {"type": "TXT", "url": "https://example.com/not-a-package.txt"},
            {
                "type": "PDF",
                "url": "https://www.congress.gov/107/bills/hr3162/BILLS-107hr3162ih.pdf",
            },
        ],
    }
    out = bulk.derive_text_formats(version)

    assert out["version_date"] == "2001-10-23"
    assert out["pdf"].endswith("/BILLS-107hr3162ih.pdf")


def test_load_bill_record_does_not_warm_the_whole_congress(monkeypatch, tmp_path):
    """Opening one API bill fetches that bill only, not its Congress's full list."""
    from openbb_government_us.congress.utils import congress_api, store

    monkeypatch.setattr(bulk, "_cache_dir", lambda: str(tmp_path))
    store.reset()
    BillsState().bulk.clear()

    async def _never_list(*_args, **_kwargs):
        raise AssertionError("a single bill must not warm the Congress's bill list")

    async def _detail(congress, bill_type, number, credentials):
        return {
            "bill_id": f"{congress}-{bill_type.lower()}-{number}",
            "congress": congress,
            "number": number,
            "type": bill_type.upper(),
            "title": "USA PATRIOT Act",
            "latestAction": {"actionDate": "2001-10-26", "text": "Became law."},
            "_detailed": True,
        }

    monkeypatch.setattr(congress_api, "fetch_bill_list", _never_list)
    monkeypatch.setattr(congress_api, "bill_record", _detail)

    record = asyncio.run(
        bulk.load_bill_record("107-hr-3162", {"congress_gov_api_key": "k"})
    )

    assert record["title"] == "USA PATRIOT Act"
    assert store.get_bill("107-hr-3162")["_detailed"] is True


def test_derive_text_formats_no_package():
    """derive_text_formats returns None when no package id can be found."""
    assert bulk.derive_text_formats({"formats": []}) is None
    assert (
        bulk.derive_text_formats({"formats": [{"url": "https://example.com/x"}]})
        is None
    )


def _window_records() -> list[dict]:
    """Three HR bills spanning January-March 2025 for store.list_bills tests."""
    return [
        {
            "bill_id": "119-hr-1",
            "number": 1,
            "type": "HR",
            "title": "Jan",
            "originChamber": "House",
            "originChamberCode": "H",
            "updateDate": "2025-01-10T00:00:00Z",
            "updateDateIncludingText": "2025-01-10T00:00:00Z",
            "latestAction": {"actionDate": "2025-01-10", "text": "Introduced"},
        },
        {
            "bill_id": "119-hr-2",
            "number": 2,
            "type": "HR",
            "title": "Feb",
            "originChamber": "House",
            "originChamberCode": "H",
            "updateDate": "2025-02-20T00:00:00Z",
            "updateDateIncludingText": "2025-02-20T00:00:00Z",
            "latestAction": {"actionDate": "2025-02-20", "text": "Passed"},
        },
        {
            "bill_id": "119-hr-3",
            "number": 3,
            "type": "HR",
            "title": "Mar",
            "originChamber": "House",
            "originChamberCode": "H",
            "updateDate": "2025-03-30T00:00:00Z",
            "updateDateIncludingText": "2025-03-30T00:00:00Z",
            "latestAction": {},
        },
    ]


def test_list_bills_window_and_sort_desc(monkeypatch, tmp_path):
    """A start/end window filters records and desc sort orders newest first."""
    store = _point_store_at(monkeypatch, tmp_path)
    store.ingest_bills(119, "hr", _window_records(), [])
    out = store.list_bills(
        119, ["hr"], date(2025, 1, 15), date(2025, 3, 1), None, None, "desc"
    )
    assert [r["number"] for r in out] == [2]


def test_list_bills_sort_asc(monkeypatch, tmp_path):
    """Ascending sort orders oldest first; missing actionDate falls back to updateDate."""
    store = _point_store_at(monkeypatch, tmp_path)
    store.ingest_bills(119, "hr", _window_records(), [])
    out = store.list_bills(119, ["hr"], None, None, None, None, "asc")
    assert [r["number"] for r in out] == [1, 2, 3]


def test_list_bills_offset_and_limit(monkeypatch, tmp_path):
    """offset skips records and a positive limit caps the result."""
    store = _point_store_at(monkeypatch, tmp_path)
    store.ingest_bills(119, "hr", _window_records(), [])
    out = store.list_bills(119, ["hr"], None, None, 1, 1, "asc")
    assert [r["number"] for r in out] == [2]


def test_list_bills_limit_none_caps_at_100(monkeypatch, tmp_path):
    """limit=None caps the output at 100 records."""
    store = _point_store_at(monkeypatch, tmp_path)
    records = [
        {
            "bill_id": f"119-hr-{i}",
            "number": i,
            "type": "HR",
            "updateDate": "2025-01-01",
        }
        for i in range(150)
    ]
    store.ingest_bills(119, "hr", records, [])
    assert len(store.list_bills(119, ["hr"], None, None, None, None, "desc")) == 100


def test_list_bills_limit_zero_no_cap(monkeypatch, tmp_path):
    """limit=0 returns all records uncapped."""
    store = _point_store_at(monkeypatch, tmp_path)
    records = [
        {
            "bill_id": f"119-hr-{i}",
            "number": i,
            "type": "HR",
            "updateDate": "2025-01-01",
        }
        for i in range(150)
    ]
    store.ingest_bills(119, "hr", records, [])
    assert len(store.list_bills(119, ["hr"], None, None, 0, None, "desc")) == 150


def test_list_bills_empty_types(monkeypatch, tmp_path):
    """An empty bill-type list short-circuits to an empty result."""
    store = _point_store_at(monkeypatch, tmp_path)
    assert store.list_bills(119, [], None, None, None, None, "desc") == []


class _FakeContent:
    """Stand-in for an aiohttp response's streaming body."""

    def __init__(self, body: bytes, chunk_exc=None):
        self._body = body
        self._chunk_exc = chunk_exc

    async def iter_chunked(self, size):
        """Yield the canned body in chunks, or raise mid-stream."""
        for start in range(0, len(self._body), size):
            yield self._body[start : start + size]
            if self._chunk_exc is not None:
                raise self._chunk_exc


class _FakeResponse:
    """Settable stand-in for an aiohttp response."""

    def __init__(
        self, status=200, headers=None, body=b"", raise_exc=None, chunk_exc=None
    ):
        self.status = status
        self.headers = headers or {}
        self._body = body
        self._raise_exc = raise_exc
        self.content = _FakeContent(body, chunk_exc)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def read(self):
        """Return the canned body."""
        return self._body

    def raise_for_status(self):
        """Raise the configured error, if any."""
        if self._raise_exc is not None:
            raise self._raise_exc


class _FakeSession:
    """Fake aiohttp.ClientSession yielding a fixed response (or raising on get)."""

    def __init__(self, response=None, get_exc=None):
        self._response = response
        self._get_exc = get_exc
        self.requested_headers = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, url, headers=None, **kwargs):
        """Return the canned response context manager (or raise)."""
        self.requested_headers = headers
        self.requested_url = url
        if self._get_exc is not None:
            raise self._get_exc
        return self._response

    def head(self, url, allow_redirects=True, **kwargs):
        """Return the canned response context manager (or raise)."""
        self.requested_url = url
        if self._get_exc is not None:
            raise self._get_exc
        return self._response


def _patch_session(monkeypatch, **kwargs):
    """Patch aiohttp.ClientSession to construct the supplied fake session."""
    import aiohttp

    session = _FakeSession(**kwargs)
    monkeypatch.setattr(aiohttp, "ClientSession", lambda *a, **k: session)
    return session


@pytest.fixture
def _cache(monkeypatch, tmp_path):
    """Point bulk._cache_dir at a temporary directory."""
    monkeypatch.setattr(bulk, "_cache_dir", lambda: str(tmp_path))
    return str(tmp_path)


def _as_zip_file(body: bytes) -> str:
    """Write archive bytes to a temp file, mirroring what _download_zip returns.

    The production caller owns the file and removes it, so nothing leaks.
    """
    handle, path = tempfile.mkstemp(suffix=".zip")
    with os.fdopen(handle, "wb") as file:
        file.write(body)
    return path


def test_download_zip_streams_to_a_file(monkeypatch, _cache):
    """_download_zip streams the archive to a file rather than into memory."""
    body = _billstatus_zip()
    _patch_session(monkeypatch, response=_FakeResponse(status=200, body=body))
    path = asyncio.run(bulk._download_zip("BILLSTATUS", 119, "HR"))
    try:
        assert path.startswith(_cache)
        assert Path(path).read_bytes() == body
    finally:
        bulk._remove_file(path)


def test_download_zip_chunks_the_body(monkeypatch, _cache):
    """The body is consumed in chunks, never read whole."""
    body = b"x" * ((1 << 20) * 2 + 17)
    response = _FakeResponse(status=200, body=body)
    _patch_session(monkeypatch, response=response)
    chunks: list = []
    original = response.content.iter_chunked

    async def _counting(size):
        async for chunk in original(size):
            chunks.append(len(chunk))
            yield chunk

    response.content.iter_chunked = _counting
    path = asyncio.run(bulk._download_zip("BILLSTATUS", 119, "HR"))
    try:
        assert Path(path).stat().st_size == len(body)
        assert chunks == [1 << 20, 1 << 20, 17]
    finally:
        bulk._remove_file(path)


def test_download_zip_removes_the_file_when_the_stream_fails(monkeypatch, _cache):
    """A truncated download leaves no partial file behind."""
    _patch_session(
        monkeypatch,
        response=_FakeResponse(
            status=200, body=b"x" * 32, chunk_exc=RuntimeError("truncated")
        ),
    )
    with pytest.raises(OpenBBError, match="Failed to download data"):
        asyncio.run(bulk._download_zip("BILLSTATUS", 119, "HR"))
    assert list(Path(_cache).glob("*.zip")) == []


def test_stream_download_returns_bytes_written(monkeypatch, tmp_path):
    """The stream reports how many bytes it wrote."""
    body = b"abcdef" * 100
    _patch_session(monkeypatch, response=_FakeResponse(status=200, body=body))
    target = tmp_path / "out.zip"
    written = asyncio.run(bulk._stream_download("https://x/data.zip", str(target)))
    assert written == len(body)
    assert target.read_bytes() == body


def test_remove_file_tolerates_a_missing_file(tmp_path):
    """Removing an absent file is a no-op."""
    bulk._remove_file(str(tmp_path / "gone.zip"))


def test_file_size_of_a_missing_file_is_zero(tmp_path):
    """An unmeasurable file reports zero bytes."""
    assert bulk._file_size(str(tmp_path / "gone.zip")) == 0


def test_parse_billstatus_accepts_a_path(tmp_path):
    """The parser reads an archive from disk as well as from bytes."""
    path = tmp_path / "b.zip"
    path.write_bytes(_billstatus_zip())
    from_path = bulk.parse_billstatus(str(path))
    from_bytes = bulk.parse_billstatus(_billstatus_zip())
    assert from_path == from_bytes
    assert {r["number"] for r in from_path} == {29, 5}


def test_parse_plaw_accepts_a_path(tmp_path):
    """The law parser reads an archive from disk as well as from bytes."""
    path = tmp_path / "p.zip"
    path.write_bytes(_plaw_zip())
    assert bulk.parse_plaw(str(path)) == bulk.parse_plaw(_plaw_zip())


def test_download_returns_the_body(monkeypatch):
    """_download reads a small body whole, for sitemaps and metadata."""
    _patch_session(monkeypatch, response=_FakeResponse(status=200, body=b"<xml/>"))
    assert asyncio.run(bulk._download("https://x/sitemap.xml")) == b"<xml/>"


def test_download_raises_on_network_error(monkeypatch):
    """A network error surfaces as an OpenBBError."""
    _patch_session(monkeypatch, get_exc=RuntimeError("network down"))
    with pytest.raises(OpenBBError, match="Failed to download data"):
        asyncio.run(bulk._download("https://x/data.zip"))


def test_photo_link():
    """photo_link builds the 225x275 portrait URL for a bioguide id."""
    assert bulk.photo_link("A000055").endswith("/images/congress/225x275/A000055.jpg")


def test_member_photo_url_exists(monkeypatch):
    """A 200 HEAD resolves to the portrait URL and is memoized."""
    BillsState().bulk.clear()
    _patch_session(monkeypatch, response=_FakeResponse(status=200))
    url = asyncio.run(bulk.member_photo_url("A000055"))
    assert url.endswith("/A000055.jpg")
    assert BillsState().bulk["photo_A000055"] == url


def test_member_photo_url_missing(monkeypatch):
    """A 404 HEAD (e.g. a newly seated member) resolves to an empty string."""
    BillsState().bulk.clear()
    _patch_session(monkeypatch, response=_FakeResponse(status=404))
    assert asyncio.run(bulk.member_photo_url("Z999999")) is None


def test_member_photo_url_error_and_empty(monkeypatch):
    """A network error or an empty bioguide resolves to an empty string."""
    BillsState().bulk.clear()
    _patch_session(monkeypatch, get_exc=RuntimeError("boom"))
    assert asyncio.run(bulk.member_photo_url("X000001")) is None
    assert asyncio.run(bulk.member_photo_url("")) is None


def test_ensure_billstatus_ingests_once_then_serves_from_store(monkeypatch, tmp_path):
    """ensure_billstatus ingests once, memoizes in-process, then reads from the DB."""
    store = _point_store_at(monkeypatch, tmp_path)
    BillsState().bulk.clear()
    body = _billstatus_zip()
    calls = {"n": 0}

    async def _download(collection, congress, bill_type):
        calls["n"] += 1
        return _as_zip_file(body)

    monkeypatch.setattr(bulk, "_download_zip", _download)
    asyncio.run(bulk.ensure_billstatus(119, "hr"))
    rows = store.list_bills(119, ["hr"], None, None, None, None, "desc")
    assert {r["number"] for r in rows} == {29, 5}
    assert calls["n"] == 1

    asyncio.run(bulk.ensure_billstatus(119, "HR"))
    assert calls["n"] == 1

    BillsState().bulk.clear()
    asyncio.run(bulk.ensure_billstatus(119, "hr"))
    assert calls["n"] == 1


def test_list_bills_ingests_then_queries(monkeypatch, tmp_path):
    """bulk.list_bills ensures BILLSTATUS then queries the store, lowercasing types."""
    _point_store_at(monkeypatch, tmp_path)
    BillsState().bulk.clear()
    body = _billstatus_zip()

    async def _download(collection, congress, bill_type):
        return _as_zip_file(body)

    monkeypatch.setattr(bulk, "_download_zip", _download)
    rows = asyncio.run(bulk.list_bills(119, ["HR"], limit=10))
    assert {r["number"] for r in rows} == {29, 5}


def test_load_bill_record_found(monkeypatch, tmp_path):
    """load_bill_record returns the stored full record (no summary merge)."""
    _point_store_at(monkeypatch, tmp_path)
    BillsState().bulk.clear()
    body = _billstatus_zip()

    async def _download(collection, congress, bill_type):
        return _as_zip_file(body)

    monkeypatch.setattr(bulk, "_download_zip", _download)
    record = asyncio.run(bulk.load_bill_record("119/hr/29"))
    assert record["number"] == 29
    assert "Laken Riley Act" in record["summaries"][0]["text"]


def test_load_bill_record_not_found(monkeypatch, tmp_path):
    """A missing bill number raises OpenBBError."""
    _point_store_at(monkeypatch, tmp_path)
    BillsState().bulk.clear()
    body = _billstatus_zip()

    async def _download(collection, congress, bill_type):
        return _as_zip_file(body)

    monkeypatch.setattr(bulk, "_download_zip", _download)
    with pytest.raises(OpenBBError, match="Bill not found in bulk data"):
        asyncio.run(bulk.load_bill_record("119/hr/999"))


_PLAW_1 = """<uslm xmlns="http://xml.house.gov/schemas/uslm/1.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <meta>
    <dc:title>Public Law 119-1: To require the Secretary to act.</dc:title>
    <dc:type>Public Law</dc:type>
    <docNumber>1</docNumber>
    <citableAs>Public Law 119-1</citableAs>
    <citableAs>139 Stat. 3</citableAs>
    <approvedDate>2025-01-29</approvedDate>
    <congress>119</congress>
    <publicPrivate>public</publicPrivate>
  </meta>
</uslm>"""

_PLAW_2 = """<uslm xmlns:dc="http://purl.org/dc/elements/1.1/">
  <meta>
    <dc:title>A short title with no prefix</dc:title>
    <docNumber>2</docNumber>
    <citableAs>Public Law 119-2</citableAs>
    <approvedDate>2025-02-15</approvedDate>
    <congress>119</congress>
    <publicPrivate>public</publicPrivate>
  </meta>
</uslm>"""

_PLAW_NO_META = "<uslm><main/></uslm>"


def _plaw_zip() -> bytes:
    """Return a PLAW ZIP with two laws, a meta-less member, and a non-XML file."""
    return _zip_bytes(
        {
            "PLAW-119publ1.xml": _PLAW_1,
            "PLAW-119publ2.xml": _PLAW_2,
            "PLAW-119publ9.xml": _PLAW_NO_META,
            "README.txt": "ignored",
        }
    )


def test_parse_plaw():
    """parse_plaw maps the USLM meta header and derives package text URLs."""
    records = bulk.parse_plaw(_plaw_zip())
    by_number = {r["law_number"]: r for r in records}
    assert set(by_number) == {1, 2}

    rec = by_number[1]
    assert rec["law_id"] == "119-1"
    assert rec["law_type"] == "public"
    assert rec["title"] == "To require the Secretary to act."
    assert rec["citation"] == "Public Law 119-1"
    assert rec["statute_citation"] == "139 Stat. 3"
    assert rec["enacted_date"] == "2025-01-29"
    assert rec["pdf"].endswith("/content/pkg/PLAW-119publ1/pdf/PLAW-119publ1.pdf")
    assert rec["xml"].endswith("/content/pkg/PLAW-119publ1/xml/PLAW-119publ1.xml")

    rec2 = by_number[2]
    assert rec2["title"] == "A short title with no prefix"
    assert rec2["statute_citation"] == ""


_PLAW_NO_DATE = """<uslm xmlns:dc="http://purl.org/dc/elements/1.1/">
  <meta>
    <dc:title>Public Law 115-285: Jack H. Brown Post Office Building</dc:title>
    <docNumber>285</docNumber>
    <citableAs>Public Law 115-285</citableAs>
    <citableAs>132 Stat. 4369</citableAs>
    <congress>115</congress>
    <publicPrivate>public</publicPrivate>
  </meta>
</uslm>"""


def test_parse_plaw_without_an_approved_date():
    """A law whose meta carries no approvedDate or date enacts as None, not ''."""
    records = bulk.parse_plaw(_zip_bytes({"PLAW-115publ285.xml": _PLAW_NO_DATE}))
    assert len(records) == 1
    assert records[0]["law_id"] == "115-285"
    assert records[0]["enacted_date"] is None


def test_filter_laws():
    """filter_laws sorts by law number and paginates."""
    records = bulk.parse_plaw(_plaw_zip())
    desc = bulk.filter_laws(records, sort_by="desc")
    assert [r["law_number"] for r in desc] == [2, 1]
    asc = bulk.filter_laws(records, sort_by="asc")
    assert [r["law_number"] for r in asc] == [1, 2]
    assert [r["law_number"] for r in bulk.filter_laws(records, offset=1)] == [1]
    assert len(bulk.filter_laws(records, limit=1)) == 1
    assert len(bulk.filter_laws(records, limit=0)) == 2


def test_load_plaw_ingests_then_serves_from_store(monkeypatch, tmp_path):
    """load_plaw parses once into the store, then serves without re-downloading."""
    _point_store_at(monkeypatch, tmp_path)
    BillsState().bulk.clear()
    body = _plaw_zip()
    calls = {"n": 0}

    async def _download(collection, congress, law_type):
        calls["n"] += 1
        return _as_zip_file(body)

    monkeypatch.setattr(bulk, "_download_zip", _download)
    records = asyncio.run(bulk.load_plaw(119, "public"))
    assert {r["law_number"] for r in records} == {1, 2}
    assert calls["n"] == 1

    BillsState().bulk.clear()
    again = asyncio.run(bulk.load_plaw(119, "PUBLIC"))
    assert {r["law_number"] for r in again} == {1, 2}
    assert calls["n"] == 1


_CCAL_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset>
  <url><loc>https://www.govinfo.gov/app/details/CCAL-119hcal-2025-01-03</loc></url>
  <url><loc>https://www.govinfo.gov/app/details/CCAL-119hcal-2025-01-07</loc></url>
  <url><loc>https://www.govinfo.gov/app/details/CCAL-119scal-2025-01-03</loc></url>
  <url><loc>https://www.govinfo.gov/app/details/CCAL-118hcal-2024-12-20</loc></url>
</urlset>"""


def test_congress_years():
    """_congress_years maps a Congress to its two calendar years."""
    assert bulk._congress_years(119) == [2025, 2026]
    assert bulk._congress_years(118) == [2023, 2024]


def test_load_calendars_filter_and_reuse(monkeypatch, tmp_path):
    """load_calendars parses package ids into the store and serves without re-fetching."""
    _point_store_at(monkeypatch, tmp_path)
    BillsState().bulk.clear()
    calls = {"n": 0}

    async def _dl(url):
        calls["n"] += 1
        return _CCAL_SITEMAP.encode("utf-8")

    monkeypatch.setattr(bulk, "_download", _dl)
    house = asyncio.run(bulk.load_calendars(119, "house"))
    assert [r["package_id"] for r in house] == [
        "CCAL-119hcal-2025-01-03",
        "CCAL-119hcal-2025-01-07",
    ]
    assert house[0]["pdf"].endswith("/CCAL-119hcal-2025-01-03.pdf")
    assert house[0]["chamber"] == "house"
    assert calls["n"] == 2

    BillsState().bulk.clear()
    cached = asyncio.run(bulk.load_calendars(119, "house"))
    assert [r["package_id"] for r in cached] == [r["package_id"] for r in house]
    assert calls["n"] == 2


def test_filter_calendars():
    """filter_calendars handles mostrecent, a specific date, and pagination."""
    records = [
        {"package_id": "a", "calendar_date": "2025-01-03"},
        {"package_id": "b", "calendar_date": "2025-01-07"},
        {"package_id": "c", "calendar_date": "2025-02-01"},
    ]
    assert (
        bulk.filter_calendars(records, publishdate="mostrecent")[0]["package_id"] == "c"
    )
    assert [
        r["package_id"]
        for r in bulk.filter_calendars(records, publishdate="2025-01-07")
    ] == ["b"]
    desc = bulk.filter_calendars(records, sort_by="desc")
    assert [r["calendar_date"] for r in desc] == [
        "2025-02-01",
        "2025-01-07",
        "2025-01-03",
    ]
    assert [r["package_id"] for r in bulk.filter_calendars(records, offset=2)] == ["a"]
    assert len(bulk.filter_calendars(records, limit=1)) == 1
    assert len(bulk.filter_calendars(records, limit=0)) == 3


def test_fetch_cmr(monkeypatch):
    """fetch_cmr reads the GovInfo search and maps each hit to a report record."""
    captured = {}

    async def _search(query, **kwargs):
        captured.update(kwargs, query=query)
        return {
            "resultSet": [
                {
                    "line1": "Quarterly Report",
                    "line2": (
                        "Congressionally Mandated Reports. Veterans Affairs"
                        " Department. 119th Congress, Received by Committee on"
                        " Veterans' Affairs. Friday, November 6, 2026."
                    ),
                    "fieldMap": {"packageid": "CMR-VA1-00203071"},
                }
            ]
        }

    monkeypatch.setattr(bulk, "wssearch", _search)
    out = asyncio.run(bulk.fetch_cmr(119, pagesize=5, offset=10))
    # The search pages by index: offset 10 at 5 per page is page 2.
    assert captured == {
        "query": "collection:CMR AND congress:119",
        "offset": 2,
        "pagesize": 5,
    }
    assert out == [
        {
            "package_id": "CMR-VA1-00203071",
            "title": "Quarterly Report",
            "submitting_agency": "Veterans Affairs Department",
            "publication_date": "2026-11-06",
            "pdf": "https://www.govinfo.gov/content/pkg/CMR-VA1-00203071/pdf/CMR-VA1-00203071.pdf",
            "details_link": "https://www.govinfo.gov/app/details/CMR-VA1-00203071",
        }
    ]


def test_fetch_cmr_search_item_without_agency_or_date(monkeypatch):
    """A search item whose summary line has no agency or date is still listed."""

    async def _search(query, **kwargs):
        return {"resultSet": [{"line1": "T", "line2": "", "fieldMap": {}}]}

    monkeypatch.setattr(bulk, "wssearch", _search)
    out = asyncio.run(bulk.fetch_cmr(119))
    assert out[0]["submitting_agency"] == ""
    assert out[0]["publication_date"] is None
    assert out[0]["pdf"] == ""


_WSSEARCH_ITEM = {
    "line1": "H. Rept. 119-637 - NO FEDERAL FUNDS FOR CASHLESS BAIL ACT",
    "line2": (
        "Congressional Reports. Committee on the Judiciary. "
        "To accompany H.R. 5213. Monday, May 4, 2026."
    ),
    "fieldMap": {
        "packageid": "CRPT-119hrpt637",
        "pdffile": "pdf/CRPT-119hrpt637.pdf",
        "title": "NO FEDERAL FUNDS FOR CASHLESS BAIL ACT",
        "collectionCode": "CRPT",
    },
}

_COMMITTEES_CURRENT = [
    {
        "type": "house",
        "name": "House Committee on the Judiciary",
        "url": "https://judiciary.house.gov",
        "thomas_id": "HSJU",
        "jurisdiction": "Judicial matters.",
        "subcommittees": [{"name": "Subcommittee on Courts", "thomas_id": "03"}],
    }
]

_MODS = """<?xml version="1.0" encoding="UTF-8"?>
<mods xmlns="http://www.loc.gov/mods/v3">
  <extension>
    <witness>Jane Doe</witness>
    <witness>John Roe</witness>
    <witness>  </witness>
    <heldDate>2026-05-04</heldDate>
  </extension>
  <relatedItem type="constituent">
    <accessId>CHRG-119hhrg12345-Wstate-DoeJ-20260504</accessId>
    <titleInfo><title>Statement of Jane Doe</title></titleInfo>
  </relatedItem>
  <relatedItem type="constituent">
    <titleInfo><title>No access id here</title></titleInfo>
  </relatedItem>
  <relatedItem type="otherFormat">
    <accessId>IGNORED</accessId>
  </relatedItem>
</mods>"""


class _FakeJSONSession:
    """Fake aiohttp.ClientSession whose POST yields canned JSON (or raises)."""

    def __init__(self, payload=None, post_exc=None):
        self._payload = payload
        self._post_exc = post_exc
        self.body = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def post(self, url, json=None):
        """Return the canned JSON response context manager (or raise)."""
        self.body = json
        if self._post_exc is not None:
            raise self._post_exc
        return _FakeJSONResponse(self._payload)


class _FakeJSONResponse:
    """Async context-manager stand-in returning fixed JSON."""

    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        """No-op for a successful response."""

    async def json(self):
        """Return the canned JSON payload."""
        return self._payload


def test_wssearch_success(monkeypatch):
    """wssearch posts the query body and returns the parsed JSON."""
    import aiohttp

    session = _FakeJSONSession(
        payload={"iTotalCount": 1, "resultSet": [_WSSEARCH_ITEM]}
    )
    monkeypatch.setattr(aiohttp, "ClientSession", lambda *a, **k: session)

    result = asyncio.run(bulk.wssearch('committee:"hsju00"', offset=5, pagesize=10))
    assert result["iTotalCount"] == 1
    assert session.body["query"] == 'committee:"hsju00"'
    assert session.body["offset"] == 5
    assert session.body["pageSize"] == 10


def test_wssearch_exception(monkeypatch):
    """A request failure is wrapped in an OpenBBError."""
    import aiohttp

    session = _FakeJSONSession(post_exc=RuntimeError("down"))
    monkeypatch.setattr(aiohttp, "ClientSession", lambda *a, **k: session)

    with pytest.raises(OpenBBError, match="GovInfo search failed"):
        asyncio.run(bulk.wssearch("q"))


def test_chamber_from_package():
    """_chamber_from_package maps the chamber code in a package id."""
    assert bulk._chamber_from_package("CRPT-119hrpt637") == "House"
    assert bulk._chamber_from_package("CRPT-119srpt1") == "Senate"
    assert bulk._chamber_from_package("CHRG-119jhrg1") == "Joint"
    assert bulk._chamber_from_package("BADID") is None


def test_wssearch_record_full():
    """_wssearch_record parses citation, date, title, chamber, and the PDF URL."""
    record = bulk._wssearch_record(_WSSEARCH_ITEM, "report", 119)
    assert record["doc_type"] == "report"
    assert record["citation"] == "H. Rept. 119-637"
    assert record["title"] == "NO FEDERAL FUNDS FOR CASHLESS BAIL ACT"
    assert record["congress"] == 119
    assert record["chamber"] == "House"
    assert record["date"] == "2026-05-04"
    assert record["package_id"] == "CRPT-119hrpt637"
    assert record["doc_url"].endswith("/CRPT-119hrpt637/pdf/CRPT-119hrpt637.pdf")


def test_wssearch_record_no_date_no_citation_no_package():
    """A record with no parseable date/citation/package falls back gracefully."""
    item = {"line1": "PlainTitleNoSeparator", "line2": "no date here", "fieldMap": {}}
    record = bulk._wssearch_record(item, "meeting", 119)
    assert record["citation"] is None
    assert record["date"] is None
    assert record["title"] == "PlainTitleNoSeparator"
    assert record["doc_url"] is None


def test_wssearch_record_bad_date():
    """An unparseable date string yields a None date."""
    item = {
        "line1": "S. Hrg. 119-1 - Title",
        "line2": "Held February 30, 2026.",
        "fieldMap": {"packageid": "CHRG-119shrg1"},
    }
    record = bulk._wssearch_record(item, "meeting", 119)
    assert record["citation"] == "S. Hrg. 119-1"
    assert record["date"] is None


def test_search_committee_docs(monkeypatch):
    """search_committee_docs builds the faceted query and maps the resultSet."""
    captured = {}

    async def _wssearch(query, *, offset=0, pagesize=20, sort="2"):
        captured["query"] = query
        captured["offset"] = offset
        captured["pagesize"] = pagesize
        return {"resultSet": [_WSSEARCH_ITEM]}

    monkeypatch.setattr(bulk, "wssearch", _wssearch)
    out = asyncio.run(
        bulk.search_committee_docs("HSJU00", "report", 119, limit=5, offset=10)
    )
    assert captured["query"] == (
        'committee:"hsju00" AND collection:CRPT AND congress:119'
    )
    assert captured["pagesize"] == 5
    assert captured["offset"] == 10
    assert out[0]["package_id"] == "CRPT-119hrpt637"


def test_search_committee_docs_non_dict(monkeypatch):
    """A non-dict wssearch response yields no records."""

    async def _wssearch(query, *, offset=0, pagesize=20, sort="2"):
        return ["not", "a", "dict"]

    monkeypatch.setattr(bulk, "wssearch", _wssearch)
    out = asyncio.run(bulk.search_committee_docs("hsju00", "meeting", 119))
    assert out == []


def test_load_committee_structure_cold_cached_and_non_list(monkeypatch):
    """Structure loads cold, memoizes, and tolerates a non-list payload."""
    BillsState().bulk.clear()
    calls = {"n": 0}

    async def _list(url, *args, **kwargs):
        calls["n"] += 1
        return list(_COMMITTEES_CURRENT)

    monkeypatch.setattr(core_helpers, "amake_request", _list)
    first = asyncio.run(bulk.load_committee_structure())
    assert first[0]["thomas_id"] == "HSJU"
    second = asyncio.run(bulk.load_committee_structure())
    assert second is first
    assert calls["n"] == 1

    BillsState().bulk.clear()

    async def _bad(url, *args, **kwargs):
        return {"not": "a list"}

    monkeypatch.setattr(core_helpers, "amake_request", _bad)
    assert asyncio.run(bulk.load_committee_structure()) == []


def test_load_committee_structure_exception(monkeypatch):
    """A request exception yields an empty structure list."""
    BillsState().bulk.clear()

    async def _boom(url, *args, **kwargs):
        raise RuntimeError("net")

    monkeypatch.setattr(core_helpers, "amake_request", _boom)
    assert asyncio.run(bulk.load_committee_structure()) == []


def test_fetch_package_mods(monkeypatch):
    """fetch_package_mods downloads and returns the MODS body bytes."""
    captured = {}

    async def _dl(url):
        captured["url"] = url
        return b"<mods/>"

    monkeypatch.setattr(bulk, "_download", _dl)
    body = asyncio.run(bulk.fetch_package_mods("CHRG-119hhrg1"))
    assert body == b"<mods/>"
    assert captured["url"].endswith("/metadata/pkg/CHRG-119hhrg1/mods.xml")


def test_parse_mods():
    """parse_mods extracts witnesses, held dates, and constituent granule docs."""
    detail = bulk.parse_mods(_MODS.encode("utf-8"), "CHRG-119hhrg12345")
    assert detail["witnesses"] == ["Jane Doe", "John Roe"]
    assert detail["held_dates"] == ["2026-05-04"]
    assert len(detail["documents"]) == 1
    doc = detail["documents"][0]
    assert doc["granule_id"] == "CHRG-119hhrg12345-Wstate-DoeJ-20260504"
    assert doc["title"] == "Statement of Jane Doe"
    assert doc["pdf"].endswith(
        "/CHRG-119hhrg12345/pdf/CHRG-119hhrg12345-Wstate-DoeJ-20260504.pdf"
    )


def test_parse_mods_no_constituents():
    """A MODS with no constituent documents yields an empty documents list."""
    mods = (
        '<mods xmlns="http://www.loc.gov/mods/v3"><titleInfo>'
        "<title>Standalone</title></titleInfo></mods>"
    )
    detail = bulk.parse_mods(mods.encode("utf-8"), "CHRG-1")
    assert detail["documents"] == []
    assert detail["witnesses"] == []
    assert detail["held_dates"] == []


_SEARCH_RESPONSE = {
    "iTotalCount": 2,
    "resultSet": [
        {
            "line1": "H. Rept. 119-637 - NO FEDERAL FUNDS",
            "line2": "Congressional Reports. Committee on the Judiciary. Monday, May 4, 2026.",
            "fieldMap": {
                "packageid": "CRPT-119hrpt637",
                "title": "NO FEDERAL FUNDS",
                "collectionCode": "CRPT",
            },
        },
        {
            "line1": "Union Calendar",
            "line2": "Congressional Calendars. Tuesday, June 3, 2026.",
            "fieldMap": {
                "packageid": "CCAL-119hcal-2026-06-03",
                "title": "Union Calendar",
                "collectionCode": "CCAL",
            },
        },
    ],
}


def test_search_record():
    """_search_record maps a wssearch item to a search record with congress + collection."""
    rec = bulk._search_record(_SEARCH_RESPONSE["resultSet"][0])
    assert rec["collection"] == "CRPT"
    assert rec["congress"] == 119
    assert rec["citation"] == "H. Rept. 119-637"
    assert rec["date"] == "2026-05-04"
    assert rec["package_id"] == "CRPT-119hrpt637"
    assert rec["doc_url"].endswith("/CRPT-119hrpt637.pdf")


def test_search_govinfo_all_collections(monkeypatch):
    """With no collection, the query ORs all congressional collections + adds filters."""
    captured = {}

    async def _fake(query, *, offset=0, pagesize=20, sort="2"):
        captured["query"] = query
        captured["pagesize"] = pagesize
        return _SEARCH_RESPONSE

    monkeypatch.setattr(bulk, "wssearch", _fake)
    out = asyncio.run(
        bulk.search_govinfo(
            "immigration",
            congress=119,
            start_date="2025-01-01",
            end_date="2026-06-03",
            limit=5,
        )
    )
    assert "immigration" in captured["query"]
    assert (
        "collection:CHRG" in captured["query"]
        and "collection:CRPT" in captured["query"]
    )
    assert "BILLSTATUS" not in captured["query"]
    assert "congress:119" in captured["query"]
    assert "publishdate:range(2025-01-01,2026-06-03)" in captured["query"]
    assert captured["pagesize"] == 5
    assert {r["collection"] for r in out} == {"CRPT", "CCAL"}


def test_search_govinfo_single_collection_and_open_range(monkeypatch):
    """A single collection is used verbatim; a one-sided date still forms a range."""
    captured = {}

    async def _fake(query, *, offset=0, pagesize=20, sort="2"):
        captured["query"] = query
        return {"resultSet": []}

    monkeypatch.setattr(bulk, "wssearch", _fake)
    asyncio.run(bulk.search_govinfo("ai", collection="CHRG", start_date="2025-01-01"))
    assert "collection:CHRG" in captured["query"]
    assert " OR " not in captured["query"]
    assert "publishdate:range(2025-01-01," in captured["query"]


def test_search_govinfo_non_dict(monkeypatch):
    """A non-dict search response yields an empty list."""

    async def _fake(query, **kwargs):
        return None

    monkeypatch.setattr(bulk, "wssearch", _fake)
    assert asyncio.run(bulk.search_govinfo("x")) == []


_LEGISLATORS = [
    {
        "id": {"bioguide": "C001129"},
        "name": {"official_full": "Mike Collins"},
        "bio": {"birthday": "1970-04-15"},
        "terms": [{"party": "Republican", "state": "GA"}],
    },
    {"id": {}, "name": {}, "terms": [{}]},
]


def test_load_legislators_cold_cached_and_non_list(monkeypatch):
    """load_legislators indexes by bioguide, caches, and tolerates non-list payloads."""
    BillsState().bulk.clear()
    calls = {"n": 0}

    async def _fake(url, *args, **kwargs):
        calls["n"] += 1
        return _LEGISLATORS

    monkeypatch.setattr(core_helpers, "amake_request", _fake)
    index = asyncio.run(bulk.load_legislators())
    assert set(index) == {"C001129"}
    assert index["C001129"]["party"] == "Republican"
    assert index["C001129"]["birthday"] == "1970-04-15"
    assert index["C001129"]["photo_url"].endswith("/C001129.jpg")
    asyncio.run(bulk.load_legislators())
    assert calls["n"] == 1

    BillsState().bulk.clear()

    async def _bad(url, *args, **kwargs):
        return None

    monkeypatch.setattr(core_helpers, "amake_request", _bad)
    assert asyncio.run(bulk.load_legislators()) == {}


def test_load_legislators_download_error(monkeypatch):
    """A failed legislators download yields an empty index."""
    BillsState().bulk.clear()

    async def _boom(url, *args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(core_helpers, "amake_request", _boom)
    assert asyncio.run(bulk.load_legislators()) == {}


def test_memoized_dedupes_concurrent_loads(monkeypatch, tmp_path):
    """Concurrent loads of the same key share one download (in-flight dedup)."""
    store = _point_store_at(monkeypatch, tmp_path)
    BillsState().bulk.clear()
    bulk._LOAD_LOCKS.clear()
    calls = {"n": 0}

    async def _slow_download(collection, congress, bill_type):
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return _as_zip_file(_billstatus_zip())

    monkeypatch.setattr(bulk, "_download_zip", _slow_download)

    async def _run():
        return await asyncio.gather(
            bulk.ensure_billstatus(119, "hr"),
            bulk.ensure_billstatus(119, "hr"),
        )

    asyncio.run(_run())
    assert calls["n"] == 1
    assert store.bills_loaded(119, "hr")


def test_ensure_billstatus_in_memory_short_circuit(monkeypatch):
    """A warmed key returns instantly without any download."""
    BillsState().bulk.clear()
    bulk._LOAD_LOCKS.clear()
    BillsState().bulk["BILLSTATUS_119_hr"] = True

    async def _boom(*args, **kwargs):
        raise AssertionError("warmed cache must not hit the network")

    monkeypatch.setattr(bulk, "_download_zip", _boom)
    asyncio.run(bulk.ensure_billstatus(119, "hr"))


def test_parse_amendment_ref_ok():
    """Dash id, shorthand, and full-URL amendment references parse correctly."""
    assert bulk.parse_amendment_ref("119-hamdt-2") == (119, "hamdt", "2")
    assert bulk.parse_amendment_ref("119/samdt/97") == (119, "samdt", "97")
    assert bulk.parse_amendment_ref(
        "https://api.congress.gov/v3/amendment/119/samdt/97?format=json"
    ) == (119, "samdt", "97")


def test_parse_amendment_ref_raises():
    """An unparseable amendment reference raises OpenBBError."""
    with pytest.raises(OpenBBError, match="Could not parse an amendment"):
        bulk.parse_amendment_ref("not-an-amendment")


def test_parse_billstatus_amendments():
    """The <amendments> block is parsed onto the bill record."""
    rec = {r["number"]: r for r in bulk.parse_billstatus(_billstatus_zip())}[29]
    amendments = rec["amendments"]
    assert len(amendments) == 2
    hamdt = amendments[0]
    assert hamdt["amendment_id"] == "119-hamdt-10"
    assert hamdt["type"] == "HAMDT"
    assert hamdt["amendedBill"] == {
        "congress": "119",
        "type": "HR",
        "number": "29",
        "title": "Laken Riley Act",
    }
    assert hamdt["sponsors"][0]["fullName"] == "Rep. Collins"
    assert hamdt["actions"][0]["text"] == "Agreed."
    assert hamdt["links"][0]["name"] == "House Report 119-1"
    samdt = amendments[1]
    assert samdt["amendedBill"] == {}
    assert samdt["amendedAmendment"]["number"] == "10"


def test_to_amendment_list_item():
    """to_amendment_list_item projects to the slim shape and trims the date."""
    rec = {r["number"]: r for r in bulk.parse_billstatus(_billstatus_zip())}[29]
    item = bulk.to_amendment_list_item(rec["amendments"][0])
    assert item["amendment_id"] == "119-hamdt-10"
    assert item["updateDate"] == "2025-02-09"
    assert item["amendedBill"]["number"] == "29"
    assert "sponsors" in item


def _patch_congress_billstatus(monkeypatch, tmp_path):
    """Ingest the HR fixture for one Congress, stubbing every other bill type empty."""
    store = _point_store_at(monkeypatch, tmp_path)
    BillsState().bulk.clear()
    body = _billstatus_zip()
    real_parse = bulk.parse_billstatus

    async def _download(collection, congress, bill_type):
        return _as_zip_file(body if bill_type == "hr" else b"empty")

    def _parse(source):
        data = Path(source).read_bytes() if isinstance(source, str) else source
        return real_parse(data) if data == body else []

    monkeypatch.setattr(bulk, "_download_zip", _download)
    monkeypatch.setattr(bulk, "parse_billstatus", _parse)
    return store


def test_load_amendments_aggregates_and_filters(monkeypatch, tmp_path):
    """load_amendments ingests every bill type then filters amendments by type."""
    _patch_congress_billstatus(monkeypatch, tmp_path)

    all_amds = asyncio.run(bulk.load_amendments(119))
    assert {a["amendment_id"] for a in all_amds} == {"119-hamdt-10", "119-samdt-11"}

    hamdt = asyncio.run(bulk.load_amendments(119, "hamdt"))
    assert [a["amendment_id"] for a in hamdt] == ["119-hamdt-10"]


def test_load_amendment_record_found_and_missing(monkeypatch, tmp_path):
    """load_amendment_record finds a record by id and raises when absent."""
    _patch_congress_billstatus(monkeypatch, tmp_path)

    rec = asyncio.run(bulk.load_amendment_record("119-hamdt-10"))
    assert rec["number"] == "10"

    with pytest.raises(OpenBBError, match="Amendment not found"):
        asyncio.run(bulk.load_amendment_record("119-hamdt-999"))


def test_filter_amendments():
    """filter_amendments applies date filters, sorting, offset, and limit."""
    records = [
        {"number": "1", "updateDate": "2025-01-05", "latestAction": {}},
        {"number": "2", "latestAction": {"actionDate": "2025-03-05"}},
        {"number": "3", "updateDate": "2025-06-05", "latestAction": {}},
    ]
    out = bulk.filter_amendments(
        records, start_date=date(2025, 2, 1), end_date=date(2025, 5, 1)
    )
    assert [r["number"] for r in out] == []

    out = bulk.filter_amendments(records)
    assert [r["number"] for r in out] == ["3", "2", "1"]

    out = bulk.filter_amendments(records, offset=1, limit=1, sort_by="asc")
    assert len(out) == 1

    assert len(bulk.filter_amendments(records, limit=0)) == 3


def test_resolve_link_redirect(monkeypatch):
    """_resolve_link returns the Location header on a redirect."""
    resp = _FakeResponse(status=302, headers={"Location": "https://x/doc.htm"})
    _patch_session(monkeypatch, response=resp)
    assert asyncio.run(bulk._resolve_link("https://link")) == "https://x/doc.htm"


def test_resolve_link_no_redirect(monkeypatch):
    """_resolve_link returns None when the service answers without a redirect."""
    _patch_session(monkeypatch, response=_FakeResponse(status=400))
    assert asyncio.run(bulk._resolve_link("https://link")) is None


def test_resolve_link_exception(monkeypatch):
    """_resolve_link swallows network errors and returns None."""
    _patch_session(monkeypatch, get_exc=RuntimeError("boom"))
    assert asyncio.run(bulk._resolve_link("https://link")) is None


def test_amendment_link_base():
    """amendment_link_base builds hamendment/samendment URLs and guards missing bills."""
    hamdt = {
        "congress": 119,
        "number": "10",
        "type": "HAMDT",
        "amendedBill": {"type": "HR", "number": "29"},
    }
    assert bulk.amendment_link_base(hamdt) == (
        "https://www.govinfo.gov/link/crec/hamendment/119/hr/29/10"
    )
    samdt = {"congress": 119, "number": "97", "type": "SAMDT"}
    assert bulk.amendment_link_base(samdt) == (
        "https://www.govinfo.gov/link/crec/samendment/119/97"
    )
    assert bulk.amendment_link_base({"type": "HAMDT", "amendedBill": {}}) is None


def test_resolve_amendment_text_senate(monkeypatch):
    """resolve_amendment_text resolves HTML/PDF and parses the CREC date."""
    urls = {
        "": "https://www.govinfo.gov/content/pkg/CREC-2025-01-01/html/CREC-2025-01-01-pt1-PgS1.htm",
        "pdf": "https://www.govinfo.gov/content/pkg/CREC-2025-01-01/pdf/CREC-2025-01-01-pt1-PgS1.pdf",
    }

    async def _fake_resolve(url):
        return urls["pdf"] if "link-type=pdf" in url else urls[""]

    monkeypatch.setattr(bulk, "_resolve_link", _fake_resolve)
    out = asyncio.run(
        bulk.resolve_amendment_text({"congress": 119, "number": "97", "type": "SAMDT"})
    )
    assert {d["format"] for d in out} == {"HTML", "PDF"}
    assert out[0]["date"] == "2025-01-01"


def test_resolve_amendment_text_no_base():
    """resolve_amendment_text returns [] when no link base can be built."""
    out = asyncio.run(bulk.resolve_amendment_text({"type": "HAMDT", "amendedBill": {}}))
    assert out == []


def test_resolve_amendment_text_unresolved(monkeypatch):
    """resolve_amendment_text drops formats the link service does not resolve."""

    async def _none(url):
        return None

    monkeypatch.setattr(bulk, "_resolve_link", _none)
    out = asyncio.run(
        bulk.resolve_amendment_text({"congress": 119, "number": "97", "type": "SAMDT"})
    )
    assert out == []


_MEMBERS_DATA = [
    {
        "id": {"bioguide": "A000055", "govtrack": 400004, "wikipedia": "Bob Aderholt"},
        "name": {
            "first": "Robert",
            "last": "Aderholt",
            "official_full": "Robert B. Aderholt",
        },
        "bio": {"birthday": "1965-07-22", "gender": "M"},
        "terms": [
            {
                "type": "rep",
                "state": "AL",
                "district": 4,
                "party": "Republican",
                "start": "1997-01-07",
                "end": "1999-01-03",
            },
            {
                "type": "rep",
                "state": "AL",
                "district": 4,
                "party": "Republican",
                "start": "2025-01-03",
                "end": "2027-01-03",
                "url": "https://aderholt.house.gov",
            },
        ],
    },
    {
        "id": {"bioguide": "C000127"},
        "name": {
            "first": "Maria",
            "last": "Cantwell",
            "official_full": "Maria Cantwell",
        },
        "bio": {"birthday": "1958-10-13", "gender": "F"},
        "terms": [
            {
                "type": "sen",
                "state": "WA",
                "party": "Democrat",
                "start": "2025-01-03",
                "end": "2031-01-03",
            }
        ],
    },
]


def test_load_members_cold_cached_and_non_list(monkeypatch):
    """load_members fetches once, caches, and tolerates a non-list payload."""
    BillsState().bulk.clear()
    calls = {"n": 0}

    async def _fake(url, *a, **k):
        calls["n"] += 1
        return _MEMBERS_DATA

    monkeypatch.setattr(core_helpers, "amake_request", _fake)
    members = asyncio.run(bulk.load_members())
    assert len(members) == 2
    asyncio.run(bulk.load_members())
    assert calls["n"] == 1

    BillsState().bulk.clear()

    async def _bad(url, *a, **k):
        return None

    monkeypatch.setattr(core_helpers, "amake_request", _bad)
    assert asyncio.run(bulk.load_members()) == []


def test_load_members_download_error(monkeypatch):
    """A failed members download yields an empty list."""
    BillsState().bulk.clear()

    async def _boom(url, *a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(core_helpers, "amake_request", _boom)
    assert asyncio.run(bulk.load_members()) == []


def test_to_member_list_item():
    """to_member_list_item projects rep (with district) and sen (no district)."""
    rep = bulk.to_member_list_item(_MEMBERS_DATA[0])
    assert rep["bioguide_id"] == "A000055"
    assert rep["chamber"] == "house"
    assert rep["district"] == 4
    assert rep["website"] == "https://aderholt.house.gov"
    sen = bulk.to_member_list_item(_MEMBERS_DATA[1])
    assert sen["chamber"] == "senate"
    assert sen["district"] is None
    empty = bulk.to_member_list_item({})
    assert empty["bioguide_id"] == ""
    assert empty["name"] == ""


def test_filter_members():
    """filter_members filters by chamber/state/party and sorts by name."""
    items = [bulk.to_member_list_item(m) for m in _MEMBERS_DATA]
    assert [m["name"] for m in bulk.filter_members(items)] == [
        "Maria Cantwell",
        "Robert B. Aderholt",
    ]
    assert len(bulk.filter_members(items, chamber="house")) == 1
    assert len(bulk.filter_members(items, state="wa")) == 1
    assert len(bulk.filter_members(items, party="republican")) == 1


def test_load_member_record_found_and_missing(monkeypatch):
    """load_member_record finds by bioguide and raises when absent."""
    BillsState().bulk.clear()

    async def _fake(url, *a, **k):
        return _MEMBERS_DATA

    monkeypatch.setattr(core_helpers, "amake_request", _fake)
    rec = asyncio.run(bulk.load_member_record("C000127"))
    assert rec["name"]["last"] == "Cantwell"
    with pytest.raises(OpenBBError, match="Member not found"):
        asyncio.run(bulk.load_member_record("ZZZ"))


def test_load_social_media(monkeypatch):
    """load_social_media indexes by bioguide and skips entries without one."""
    BillsState().bulk.clear()

    async def _fake(url, *a, **k):
        return [
            {"id": {"bioguide": "A000055"}, "social": {"twitter": "Robert_Aderholt"}},
            {"id": {}, "social": {"twitter": "x"}},
        ]

    monkeypatch.setattr(core_helpers, "amake_request", _fake)
    index = asyncio.run(bulk.load_social_media())
    assert index == {"A000055": {"twitter": "Robert_Aderholt"}}

    BillsState().bulk.clear()

    async def _bad(url, *a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(core_helpers, "amake_request", _bad)
    assert asyncio.run(bulk.load_social_media()) == {}


def test_load_committee_membership(monkeypatch):
    """load_committee_membership caches a dict and coerces non-dicts to {}."""
    BillsState().bulk.clear()

    async def _fake(url, *a, **k):
        return {
            "HSAP": [
                {"bioguide": "A000055", "rank": 1, "title": "", "party": "majority"}
            ]
        }

    monkeypatch.setattr(core_helpers, "amake_request", _fake)
    assert "HSAP" in asyncio.run(bulk.load_committee_membership())

    BillsState().bulk.clear()

    async def _bad(url, *a, **k):
        return ["not", "a", "dict"]

    monkeypatch.setattr(core_helpers, "amake_request", _bad)
    assert asyncio.run(bulk.load_committee_membership()) == {}

    BillsState().bulk.clear()

    async def _boom(url, *a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(core_helpers, "amake_request", _boom)
    assert asyncio.run(bulk.load_committee_membership()) == {}


def test_member_committees(monkeypatch):
    """member_committees inverts membership and resolves committee/subcommittee names."""

    async def _membership():
        return {
            "HSAP": [
                {"bioguide": "A000055", "rank": 1, "title": "", "party": "majority"}
            ],
            "HSAP01": [
                {
                    "bioguide": "A000055",
                    "rank": 1,
                    "title": "Chair",
                    "party": "majority",
                }
            ],
            "HSAG": [
                {"bioguide": "B000000", "rank": 2, "title": "", "party": "minority"}
            ],
        }

    async def _structure():
        return [
            {
                "thomas_id": "HSAP",
                "name": "House Committee on Appropriations",
                "subcommittees": [{"thomas_id": "01", "name": "Defense"}],
            }
        ]

    monkeypatch.setattr(bulk, "load_committee_membership", _membership)
    monkeypatch.setattr(bulk, "load_committee_structure", _structure)

    out = asyncio.run(bulk.member_committees("A000055"))
    names = [c["committee"] for c in out]
    assert "House Committee on Appropriations" in names
    assert "House Committee on Appropriations — Defense" in names
    assert out[0]["is_subcommittee"] is False
    assert any(c["title"] == "Chair" for c in out)


async def _fake_vv_members(congress, chamber):
    """One member mapped to an icpsr id, for the passage-index tests."""
    return {"C000127": "39310"}


async def _fake_vv_rollcalls(congress, chamber):
    """Two final-passage questions and one procedural question."""
    return {
        "1": {"question": "On Passage of the Bill"},
        "2": {"question": "On the Motion to Recommit"},
        "3": {"question": "On the Joint Resolution"},
    }


async def _fake_vv_votes(congress, chamber):
    """A yea on rollcall 1 and a nay on rollcall 3, plus an unknown member."""
    return {"39310": [("1", "1"), ("2", "6"), ("3", "4")], "99999": [("1", "1")]}


def _point_store_at(monkeypatch, tmp_path):
    """Route the cache/store at an isolated temp dir and start it empty."""
    from openbb_government_us.congress.utils import store

    monkeypatch.setattr(bulk, "_cache_dir", lambda: str(tmp_path))
    store.reset()
    return store


def test_legislation_rows_from_records():
    """Legislation rows derive from full records: sponsor + distinct cosponsors only."""
    records = [
        {
            "bill_id": "119-hr-1",
            "title": "Bill",
            "introducedDate": "2025-01-01",
            "latestAction": {"actionDate": "2025-02-01", "text": "Acted"},
            "sponsors": [{"bioguideId": "S000001"}],
            "cosponsors": [{"bioguideId": "C000002"}, {"bioguideId": "S000001"}],
        },
        {
            "bill_id": "119-hr-2",
            "sponsors": [{"fullName": "No Bioguide"}],
            "cosponsors": [],
        },
    ]
    rows = bulk._legislation_rows_from_records(records, 119, "hr")
    assert {(r[0], r[4]) for r in rows} == {
        ("S000001", "Sponsor"),
        ("C000002", "Cosponsor"),
    }
    assert all(r[1] == 119 and r[2] == "hr" for r in rows)


def test_ingest_billstatus_and_query(monkeypatch, tmp_path):
    """ingest_billstatus_range stores slim legislation rows; members read from the DB."""
    store = _point_store_at(monkeypatch, tmp_path)
    BillsState().bulk.clear()
    body = _billstatus_zip()
    calls: list = []

    real_parse = bulk.parse_billstatus

    async def _download(collection, congress, bill_type):
        calls.append(bill_type)
        return _as_zip_file(body if bill_type == "hr" else b"empty")

    def _parse(source):
        data = Path(source).read_bytes() if isinstance(source, str) else source
        return real_parse(data) if data == body else []

    monkeypatch.setattr(bulk, "_download_zip", _download)
    monkeypatch.setattr(bulk, "parse_billstatus", _parse)

    asyncio.run(bulk.ingest_billstatus_range([119]))
    assert "119-hr" in store.loaded_keys("legislation")
    assert store.loaded_keys("bills") == set()

    leg = asyncio.run(bulk.member_legislation("C001129", [119]))
    assert [b["bill_id"] for b in leg] == ["119-hr-29"]

    calls.clear()
    asyncio.run(bulk.ingest_billstatus_range([119]))
    assert calls == []


def test_ingest_billstatus_skips_failed_archive(monkeypatch, tmp_path):
    """A failed archive download leaves the unit un-ingested without raising."""
    store = _point_store_at(monkeypatch, tmp_path)

    async def _download(collection, congress, bill_type):
        raise RuntimeError("network down")

    monkeypatch.setattr(bulk, "_download_zip", _download)
    asyncio.run(bulk.ingest_billstatus_range([119]))
    assert store.loaded_keys("bills") == set()
    assert asyncio.run(bulk.member_legislation("C001129", [119])) == []


def test_member_legislation_empty_without_store(monkeypatch, tmp_path):
    """With nothing ingested, member_legislation returns an empty list."""
    _point_store_at(monkeypatch, tmp_path)
    assert asyncio.run(bulk.member_legislation("A000055", [119])) == []


def test_member_served_congresses():
    """member_served_congresses derives Congresses from terms, floored at the 108th."""
    record = {
        "terms": [
            {"start": "1789-03-04"},
            {"start": "1997-01-07"},
            {"start": "2017-01-03"},
            {"start": "2025-01-03"},
            {"start": ""},
        ]
    }
    assert bulk.member_served_congresses(record) == [119, 115]


def test_member_service():
    """member_service maps each served Congress to its chamber, newest first."""
    record = {
        "terms": [
            {"type": "rep", "start": "1789-03-04"},
            {"type": "rep", "start": "2013-01-03"},
            {"type": "sen", "start": "2025-01-03"},
            {"type": "rep", "start": ""},
        ]
    }
    assert bulk.member_service(record) == [(119, "S"), (113, "H")]


def test_bill_number_to_id():
    """Voteview bill_number values convert to bill ids; nominations return None."""
    assert bulk._bill_number_to_id("HR29", 119) == "119-hr-29"
    assert bulk._bill_number_to_id("HRES5", 119) == "119-hres-5"
    assert bulk._bill_number_to_id("SCONRES1", 119) == "119-sconres-1"
    assert bulk._bill_number_to_id("S5", 119) == "119-s-5"
    assert bulk._bill_number_to_id("PN1", 119) is None
    assert bulk._bill_number_to_id("", 119) is None
    assert bulk._bill_number_to_id("MOTION", 119) is None


_VV_MEMBERS = (
    "congress,chamber,icpsr,bioguide_id\n119,Senate,39310,C000127\n119,Senate,99999,\n"
)
_VV_ROLLCALLS = (
    "congress,chamber,rollnumber,date,bill_number,vote_result,vote_desc,vote_question\n"
    "119,Senate,1,2026-01-10,S5,Passed,A bill to do things,On Passage of the Bill\n"
    "119,Senate,2,2026-01-11,PN1,Confirmed,A nominee,On the Nomination\n"
    "119,Senate,3,2026-01-12,S9,Rejected,Another bill,On Passage of the Bill\n"
)
_VV_VOTES = (
    "congress,chamber,rollnumber,icpsr,cast_code,prob\n"
    "119,Senate,1,39310,1,99\n"
    "119,Senate,2,39310,1,99\n"
    "119,Senate,3,39310,6,99\n"
    "119,Senate,4,39310,0,99\n"
    "119,Senate,1,99999,1,99\n"
)


def _patch_voteview(monkeypatch, tmp_path):
    """Point the store at a temp DB and serve the synthetic Voteview CSV text."""
    _point_store_at(monkeypatch, tmp_path)
    texts = {
        "members": _VV_MEMBERS,
        "rollcalls": _VV_ROLLCALLS,
        "votes": _VV_VOTES,
    }

    async def _text(kind, congress, chamber):
        return texts[kind]

    monkeypatch.setattr(bulk, "_voteview_text", _text)


def test_load_voteview_members(monkeypatch, tmp_path):
    """load_voteview_members indexes bioguide -> icpsr and skips blank bioguides."""
    BillsState().bulk.clear()
    _patch_voteview(monkeypatch, tmp_path)
    index = asyncio.run(bulk.load_voteview_members(119, "S"))
    assert index == {"C000127": "39310"}


def test_load_voteview_rollcalls(monkeypatch, tmp_path):
    """load_voteview_rollcalls maps rollnumber -> metadata."""
    BillsState().bulk.clear()
    _patch_voteview(monkeypatch, tmp_path)
    rolls = asyncio.run(bulk.load_voteview_rollcalls(119, "S"))
    assert rolls["1"]["bill_number"] == "S5"
    assert rolls["1"]["question"] == "On Passage of the Bill"


def test_load_voteview_votes(monkeypatch, tmp_path):
    """load_voteview_votes indexes (rollnumber, cast_code) by icpsr."""
    BillsState().bulk.clear()
    _patch_voteview(monkeypatch, tmp_path)
    index = asyncio.run(bulk.load_voteview_votes(119, "S"))
    assert index["39310"] == [("1", "1"), ("2", "1"), ("3", "6"), ("4", "0")]
    assert index["99999"] == [("1", "1")]


def test_voteview_text_download_error(monkeypatch):
    """A failed Voteview fetch degrades to an empty string."""

    async def _boom(url):
        raise RuntimeError("down")

    monkeypatch.setattr(bulk, "_download", _boom)
    assert asyncio.run(bulk._voteview_text("members", 119, "S")) == ""


def test_voteview_text_decodes_body(monkeypatch):
    """A successful Voteview fetch decodes the CSV body to text."""

    async def _dl(url):
        assert url.endswith("/members/S119_members.csv")
        return b"a,b\n1,2\n"

    monkeypatch.setattr(bulk, "_download", _dl)
    assert asyncio.run(bulk._voteview_text("members", 119, "S")) == "a,b\n1,2\n"


def test_load_voteview_serves_cached(monkeypatch, tmp_path):
    """A Voteview file cached in the store is returned without a download."""
    store = _point_store_at(monkeypatch, tmp_path)
    BillsState().bulk.clear()
    store.put_parsed("vv-members-S119", {"C000127": "39310"})

    async def _boom(url):
        raise AssertionError("cached Voteview must not hit the network")

    monkeypatch.setattr(bulk, "_download", _boom)
    assert asyncio.run(bulk.load_voteview_members(119, "S")) == {"C000127": "39310"}


def test_member_congress_votes(monkeypatch, tmp_path):
    """member_congress_votes joins votes to rollcalls and maps cast codes."""
    BillsState().bulk.clear()
    _patch_voteview(monkeypatch, tmp_path)
    votes = asyncio.run(bulk.member_congress_votes("C000127", 119, "S"))
    assert len(votes) == 3
    by_roll = {v["rollnumber"]: v for v in votes}
    assert by_roll[1]["position"] == "Yea"
    assert by_roll[1]["bill_id"] == "119-s-5"
    assert by_roll[1]["chamber"] == "senate"
    assert by_roll[2]["bill_id"] is None
    assert by_roll[3]["position"] == "Nay"


def test_member_congress_votes_member_absent(monkeypatch, tmp_path):
    """A member not present in a Congress yields no votes."""
    BillsState().bulk.clear()
    _patch_voteview(monkeypatch, tmp_path)
    assert asyncio.run(bulk.member_congress_votes("ZZZ", 119, "S")) == []


def test_member_votes(monkeypatch, tmp_path):
    """member_votes keeps legislative votes only, newest-first, capped at limit."""
    BillsState().bulk.clear()
    _patch_voteview(monkeypatch, tmp_path)
    out = asyncio.run(bulk.member_votes("C000127", [(119, "S")], limit=5))
    assert [v["bill_id"] for v in out] == ["119-s-9", "119-s-5"]
    capped = asyncio.run(bulk.member_votes("C000127", [(119, "S")], limit=1))
    assert len(capped) == 1


def test_member_votes_short_circuits_old_congresses(monkeypatch):
    """Once the limit is met, older Congresses are not loaded."""
    loaded: list = []

    async def _votes(bioguide, congress, chamber):
        loaded.append(congress)
        return [
            {"bill_id": f"{congress}-s-1", "date": f"{congress}", "rollnumber": 1},
            {"bill_id": f"{congress}-s-2", "date": f"{congress}", "rollnumber": 2},
        ]

    monkeypatch.setattr(bulk, "member_congress_votes", _votes)
    out = asyncio.run(
        bulk.member_votes("X", [(119, "S"), (118, "S"), (117, "S")], limit=2)
    )
    assert loaded == [119]
    assert [v["bill_id"] for v in out] == ["119-s-2", "119-s-1"]

    loaded.clear()
    asyncio.run(bulk.member_votes("X", [(119, "S"), (118, "S")], limit=4))
    assert loaded == [119, 118]


def test_member_passage_record_absent(monkeypatch, tmp_path):
    """A member with no ingested votes and no buildable units yields a zeroed record."""
    _point_store_at(monkeypatch, tmp_path)

    async def _no_units(bioguide):
        return None

    monkeypatch.setattr(bulk, "ensure_member_passage", _no_units)

    rec = asyncio.run(bulk.member_passage_record("C000127"))
    assert rec == {"yea": 0, "nay": 0, "total": 0, "yea_pct": None}


def test_member_passage_record_builds_on_demand(monkeypatch, tmp_path):
    """An unbuilt index is built for the member being viewed.

    Only the startup warmup built this, behind minutes of bill archives, so any
    bio opened first - or after a restart - reported no voting record at all.
    """
    _point_store_at(monkeypatch, tmp_path)
    BillsState().bulk.clear()

    async def _members():
        return [
            {
                "id": {"bioguide": "C000127"},
                "terms": [{"start": "2021-01-03", "type": "sen"}],
            }
        ]

    monkeypatch.setattr(bulk, "load_members", _members)
    monkeypatch.setattr(bulk, "load_voteview_members", _fake_vv_members)
    monkeypatch.setattr(bulk, "load_voteview_rollcalls", _fake_vv_rollcalls)
    monkeypatch.setattr(bulk, "load_voteview_votes", _fake_vv_votes)

    rec = asyncio.run(bulk.member_passage_record("C000127"))

    assert rec == {"yea": 1, "nay": 1, "total": 2, "yea_pct": 50.0}


def test_member_passage_record_survives_a_failed_build(monkeypatch, tmp_path, caplog):
    """A build failure logs and still renders the bio with an empty tally."""
    _point_store_at(monkeypatch, tmp_path)

    async def _boom(bioguide):
        raise OpenBBError("voteview unreachable")

    monkeypatch.setattr(bulk, "ensure_member_passage", _boom)

    with caplog.at_level("ERROR"):
        rec = asyncio.run(bulk.member_passage_record("C000127"))

    assert rec["total"] == 0
    assert "could not build the passage index" in caplog.text


def test_ensure_member_passage_skips_already_loaded_units(monkeypatch, tmp_path):
    """Units already in the store are not re-downloaded."""
    store = _point_store_at(monkeypatch, tmp_path)
    BillsState().bulk.clear()

    async def _members():
        return [
            {
                "id": {"bioguide": "C000127"},
                "terms": [{"start": "2021-01-03", "type": "sen"}],
            }
        ]

    calls: list = []

    async def _vv_members(congress, chamber):
        calls.append((congress, chamber))
        return {"C000127": "39310"}

    monkeypatch.setattr(bulk, "load_members", _members)
    monkeypatch.setattr(bulk, "load_voteview_members", _vv_members)
    monkeypatch.setattr(bulk, "load_voteview_rollcalls", _fake_vv_rollcalls)
    monkeypatch.setattr(bulk, "load_voteview_votes", _fake_vv_votes)

    asyncio.run(bulk.ensure_member_passage("C000127"))
    assert len(calls) == 1

    # Already stored, and the in-process memo is cleared, so the store guard alone
    # has to prevent a second download.
    BillsState().bulk.clear()
    asyncio.run(bulk.ensure_member_passage("C000127"))
    assert len(calls) == 1
    assert store.loaded_keys("passage") == {"117-S"}


def test_ensure_member_passage_tolerates_a_bad_unit(monkeypatch, tmp_path, caplog):
    """One unavailable Voteview file does not sink the rest of the member's units."""
    _point_store_at(monkeypatch, tmp_path)
    BillsState().bulk.clear()

    async def _members():
        return [
            {
                "id": {"bioguide": "C000127"},
                "terms": [
                    {"start": "2021-01-03", "type": "sen"},
                    {"start": "2023-01-03", "type": "sen"},
                ],
            }
        ]

    async def _vv_members(congress, chamber):
        if congress == 118:
            raise OpenBBError("404 from voteview")
        return {"C000127": "39310"}

    monkeypatch.setattr(bulk, "load_members", _members)
    monkeypatch.setattr(bulk, "load_voteview_members", _vv_members)
    monkeypatch.setattr(bulk, "load_voteview_rollcalls", _fake_vv_rollcalls)
    monkeypatch.setattr(bulk, "load_voteview_votes", _fake_vv_votes)

    with caplog.at_level("WARNING"):
        asyncio.run(bulk.ensure_member_passage("C000127"))

    assert "passage votes for S118 unavailable" in caplog.text
    assert asyncio.run(bulk.member_passage_record("C000127"))["total"] == 2


def test_ensure_member_passage_no_terms(monkeypatch, tmp_path):
    """A record with no datable terms asks for nothing."""
    _point_store_at(monkeypatch, tmp_path)

    async def _members():
        return [{"id": {"bioguide": "C000127"}, "terms": []}]

    async def _never(*_args, **_kwargs):
        raise AssertionError("no units should be ingested")

    monkeypatch.setattr(bulk, "load_members", _members)
    monkeypatch.setattr(bulk, "load_voteview_members", _never)

    asyncio.run(bulk.ensure_member_passage("C000127"))


def test_is_passage_question():
    """Final-passage questions match across both chambers; procedural ones do not."""
    passage = [
        "On Passage",
        "On Passage of the Bill",
        "Passage, Objections of the President To The Contrary Notwithstanding",
        "On the Joint Resolution",
        "On the Concurrent Resolution",
        "On Agreeing to the Concurrent Resolution",
        "On Motion to Suspend the Rules and Pass",
        "On Motion to Suspend the Rules and Pass, as Amended",
    ]
    procedural = [
        "On the Cloture Motion",
        "On the Nomination",
        "On the Amendment",
        "On the Motion to Proceed",
        "On Agreeing to the Resolution",
        "On the Resolution",
        "On the Motion to Recommit",
        "",
        None,
    ]
    assert all(bulk._is_passage_question(q) for q in passage)
    assert not any(bulk._is_passage_question(q) for q in procedural)


def test_build_passage_index(monkeypatch, tmp_path):
    """build_passage_index sums passage Yea/Nay into the store, idempotently, and prunes."""
    store = _point_store_at(monkeypatch, tmp_path)
    members = {"C000127": "39310"}
    rollcalls = {
        "1": {"question": "On Passage of the Bill"},
        "2": {"question": "On the Motion to Recommit"},
        "3": {"question": "On the Joint Resolution"},
    }
    votes = {
        "39310": [("1", "1"), ("2", "6"), ("3", "4")],
        "99999": [("1", "1")],
    }

    async def _members(congress, chamber):
        return dict(members)

    async def _rollcalls(congress, chamber):
        return dict(rollcalls)

    async def _votes(congress, chamber):
        return {k: list(v) for k, v in votes.items()}

    BillsState().bulk["VV_VOTES_S117"] = "sentinel"
    BillsState().bulk["VV_ROLLCALLS_S117"] = "sentinel"
    monkeypatch.setattr(bulk, "load_voteview_members", _members)
    monkeypatch.setattr(bulk, "load_voteview_rollcalls", _rollcalls)
    monkeypatch.setattr(bulk, "load_voteview_votes", _votes)

    async def _already_built(bioguide):
        return None

    monkeypatch.setattr(bulk, "ensure_member_passage", _already_built)

    asyncio.run(bulk.build_passage_index([119, 118, 117]))
    rec = asyncio.run(bulk.member_passage_record("C000127"))
    assert rec == {"yea": 6, "nay": 6, "total": 12, "yea_pct": 50.0}
    assert store.get_passage("99999") is None
    assert "VV_VOTES_S117" not in BillsState().bulk
    assert "VV_ROLLCALLS_S117" not in BillsState().bulk

    asyncio.run(bulk.build_passage_index([119, 118, 117]))
    assert asyncio.run(bulk.member_passage_record("C000127")) == rec


def test_url_last_modified_ok(monkeypatch):
    """_url_last_modified returns the Last-Modified header on a successful HEAD."""
    resp = _FakeResponse(status=200, headers={"Last-Modified": "Mon, 01 Jan 2025"})
    _patch_session(monkeypatch, response=resp)
    assert asyncio.run(bulk._url_last_modified("https://x")) == "Mon, 01 Jan 2025"


def test_url_last_modified_error_status(monkeypatch):
    """A 4xx/5xx HEAD response yields None."""
    _patch_session(monkeypatch, response=_FakeResponse(status=404))
    assert asyncio.run(bulk._url_last_modified("https://x")) is None


def test_url_last_modified_exception(monkeypatch):
    """A network error during the HEAD yields None."""
    _patch_session(monkeypatch, get_exc=RuntimeError("boom"))
    assert asyncio.run(bulk._url_last_modified("https://x")) is None


def test_billstatus_listing(monkeypatch):
    """_billstatus_listing maps each bill type's folder to its last-modified stamp."""

    async def _req(url, *args, **kwargs):
        assert url.endswith("/json/BILLSTATUS/119")
        return {
            "files": [
                {"justFileName": "HR", "formattedLastModifiedTime": "2025-01-01"},
                {"justFileName": "S", "formattedLastModifiedTime": "2025-01-02"},
                {"justFileName": "", "formattedLastModifiedTime": "2025-01-03"},
                {"justFileName": "SRES"},
            ]
        }

    monkeypatch.setattr(core_helpers, "amake_request", _req)
    listing = asyncio.run(bulk._billstatus_listing(119))
    assert listing == {"hr": "2025-01-01", "s": "2025-01-02"}


def test_billstatus_listing_error_and_non_dict(monkeypatch):
    """A failed request or a non-dict listing yields an empty mapping."""

    async def _boom(url, *args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(core_helpers, "amake_request", _boom)
    assert asyncio.run(bulk._billstatus_listing(119)) == {}

    async def _list(url, *args, **kwargs):
        return ["not", "a", "dict"]

    monkeypatch.setattr(core_helpers, "amake_request", _list)
    assert asyncio.run(bulk._billstatus_listing(119)) == {}


def test_loaded_archives(monkeypatch, tmp_path):
    """_loaded_archives maps each Congress to its bill types, full records winning."""
    store = _point_store_at(monkeypatch, tmp_path)
    store.ingest_bills(119, "hr", [], [])
    store.ingest_legislation(119, "hr", [], [])
    store.ingest_legislation(118, "s", [], [])
    archives = bulk._loaded_archives()
    assert archives[119]["hr"] == "bills"
    assert archives[118]["s"] == "legislation"


def test_seed_billstatus_markers(monkeypatch, tmp_path):
    """seed_billstatus_markers stamps every loaded archive's last-modified time."""
    store = _point_store_at(monkeypatch, tmp_path)
    store.ingest_bills(119, "hr", [], [])

    async def _listing(congress):
        return {"hr": "2025-01-01"}

    monkeypatch.setattr(bulk, "_billstatus_listing", _listing)
    asyncio.run(bulk.seed_billstatus_markers())
    assert store.get_parsed("lm:BILLSTATUS_119_hr") == "2025-01-01"


def test_refresh_billstatus_reingests_changed(monkeypatch, tmp_path):
    """refresh_billstatus re-ingests only archives whose remote stamp changed."""
    store = _point_store_at(monkeypatch, tmp_path)
    store.ingest_bills(119, "hr", [], [])
    store.ingest_legislation(118, "s", [], [])
    store.put_parsed("lm:BILLSTATUS_119_hr", "old")
    store.put_parsed("lm:BILLSTATUS_118_s", "same")

    async def _listing(congress):
        return {"hr": "new"} if congress == 119 else {"s": "same"}

    reingested: list = []

    async def _reingest(congress, bill_type, kind):
        reingested.append((congress, bill_type, kind))

    monkeypatch.setattr(bulk, "_billstatus_listing", _listing)
    monkeypatch.setattr(bulk, "_reingest_archive", _reingest)
    asyncio.run(bulk.refresh_billstatus())
    assert reingested == [(119, "hr", "bills")]
    assert store.get_parsed("lm:BILLSTATUS_119_hr") == "new"


def test_refresh_billstatus_skips_empty_listing_and_errors(monkeypatch, tmp_path):
    """An empty listing is skipped; a re-ingest error is caught and logged."""
    store = _point_store_at(monkeypatch, tmp_path)
    store.ingest_bills(119, "hr", [], [])
    store.ingest_legislation(118, "s", [], [])
    store.put_parsed("lm:BILLSTATUS_118_s", "old")

    async def _listing(congress):
        return {} if congress == 119 else {"s": "new"}

    async def _reingest(congress, bill_type, kind):
        raise RuntimeError("ingest failed")

    monkeypatch.setattr(bulk, "_billstatus_listing", _listing)
    monkeypatch.setattr(bulk, "_reingest_archive", _reingest)
    asyncio.run(bulk.refresh_billstatus())
    assert store.get_parsed("lm:BILLSTATUS_118_s") == "old"


def test_reingest_archive_dispatches(monkeypatch):
    """_reingest_archive routes to the full or slim ingest path by kind."""
    calls: list = []

    async def _full(congress, bill_type):
        calls.append(("full", congress, bill_type))

    async def _slim(congress, bill_type):
        calls.append(("slim", congress, bill_type))

    monkeypatch.setattr(bulk, "_ingest_billstatus", _full)
    monkeypatch.setattr(bulk, "_ingest_legislation", _slim)
    asyncio.run(bulk._reingest_archive(119, "hr", "bills"))
    asyncio.run(bulk._reingest_archive(118, "s", "legislation"))
    assert calls == [("full", 119, "hr"), ("slim", 118, "s")]


def test_invalidate_voteview(monkeypatch, tmp_path):
    """_invalidate_voteview drops the cached Voteview blobs for a Congress/chamber."""
    store = _point_store_at(monkeypatch, tmp_path)
    BillsState().bulk["VV_MEMBERS_S119"] = "x"
    store.put_parsed("vv-members-S119", {"a": "b"})
    bulk._invalidate_voteview(119, "S")
    assert "VV_MEMBERS_S119" not in BillsState().bulk
    assert store.get_parsed("vv-members-S119") is None


def test_ingest_passage_keep_and_prune(monkeypatch, tmp_path):
    """_ingest_passage stores tallies and prunes cached votes unless keep is set."""
    store = _point_store_at(monkeypatch, tmp_path)

    async def _members(congress, chamber):
        return {"C000127": "39310"}

    async def _rollcalls(congress, chamber):
        return {"1": {"question": "On Passage of the Bill"}}

    async def _votes(congress, chamber):
        return {"39310": [("1", "1")]}

    monkeypatch.setattr(bulk, "load_voteview_members", _members)
    monkeypatch.setattr(bulk, "load_voteview_rollcalls", _rollcalls)
    monkeypatch.setattr(bulk, "load_voteview_votes", _votes)

    BillsState().bulk["VV_VOTES_S119"] = "x"
    BillsState().bulk["VV_ROLLCALLS_S119"] = "x"
    asyncio.run(bulk._ingest_passage(119, "S", keep=False))
    assert store.get_passage("C000127") == (1, 0)
    assert "VV_VOTES_S119" not in BillsState().bulk

    BillsState().bulk["VV_VOTES_S119"] = "x"
    asyncio.run(bulk._ingest_passage(119, "S", keep=True))
    assert BillsState().bulk["VV_VOTES_S119"] == "x"


def test_refresh_passage_reingests_when_changed(monkeypatch, tmp_path):
    """refresh_passage re-ingests a chamber when its votes file changed."""
    store = _point_store_at(monkeypatch, tmp_path)
    from datetime import datetime

    from openbb_government_us.congress.utils.helpers import year_to_congress

    congress = year_to_congress(datetime.now().year)
    store.put_parsed(f"lm:VV_H{congress}", "old")
    store.put_parsed(f"lm:VV_S{congress}", "same")

    async def _last_modified(url):
        return "same" if f"S{congress}" in url else "new"

    ingested: list = []

    async def _ingest(c, chamber, *, keep):
        ingested.append((c, chamber, keep))

    invalidated: list = []
    monkeypatch.setattr(bulk, "_url_last_modified", _last_modified)
    monkeypatch.setattr(bulk, "_ingest_passage", _ingest)
    monkeypatch.setattr(
        bulk, "_invalidate_voteview", lambda c, ch: invalidated.append((c, ch))
    )
    asyncio.run(bulk.refresh_passage())
    assert ingested == [(congress, "H", True)]
    assert invalidated == [(congress, "H")]
    assert store.get_parsed(f"lm:VV_H{congress}") == "new"


def test_refresh_passage_handles_ingest_error(monkeypatch, tmp_path):
    """A passage re-ingest error is caught and logged; the marker is left unchanged."""
    store = _point_store_at(monkeypatch, tmp_path)
    from datetime import datetime

    from openbb_government_us.congress.utils.helpers import year_to_congress

    congress = year_to_congress(datetime.now().year)

    async def _last_modified(url):
        return "new"

    async def _ingest(c, chamber, *, keep):
        raise RuntimeError("ingest failed")

    monkeypatch.setattr(bulk, "_url_last_modified", _last_modified)
    monkeypatch.setattr(bulk, "_ingest_passage", _ingest)
    monkeypatch.setattr(bulk, "_invalidate_voteview", lambda c, ch: None)
    asyncio.run(bulk.refresh_passage())
    assert store.get_parsed(f"lm:VV_H{congress}") is None


_BILLSTATUS_LEGACY = """<billStatus><bill>
  <billNumber>9</billNumber><congress>117</congress><billType>HR</billType>
  <originChamber>House</originChamber><originChamberCode>H</originChamberCode>
  <title>Reserved for the Speaker.</title>
  <introducedDate>2021-01-03</introducedDate><updateDate>2021-08-05T14:33:24Z</updateDate>
  <latestAction><actionDate>2021-01-03</actionDate><text>Introduced in House</text></latestAction>
  <committees><billCommittees><item><systemCode>hsju00</systemCode><name>Judiciary</name></item></billCommittees></committees>
  <summaries><billSummaries><item><versionCode>00</versionCode><actionDate>2021-01-03</actionDate><text>Legacy summary.</text></item></billSummaries></summaries>
  <subjects><billSubjects><policyArea><name>Congress</name></policyArea>
    <legislativeSubjects><item><name>House rules</name></item></legislativeSubjects></billSubjects></subjects>
  <titles><item><titleType>Official Title as Introduced</titleType><title>Reserved for the Speaker.</title></item></titles>
  <actions><item><actionDate>2021-01-03</actionDate><text>Introduced in House</text><type>IntroReferral</type></item></actions>
</bill></billStatus>"""


def test_parse_billstatus_legacy_schema():
    """The legacy BILLSTATUS schema maps to the same record shape as the current one.

    GovInfo still serves ``billNumber``/``billType`` and ``bill*``-wrapped blocks
    for bills it has not regenerated (the numbers reserved for the Speaker, for
    example). Reading only the current field names left those records with no
    type and number 0, collapsing them onto a single shared bill_id.
    """
    records = bulk.parse_billstatus(
        _zip_bytes({"BILLSTATUS-117hr9.xml": _BILLSTATUS_LEGACY})
    )
    assert len(records) == 1

    rec = records[0]
    assert rec["bill_id"] == "117-hr-9"
    assert rec["congress"] == 117
    assert rec["number"] == 9
    assert rec["type"] == "HR"
    assert rec["title"] == "Reserved for the Speaker."
    assert rec["committees"][0]["systemCode"] == "hsju00"
    assert rec["summaries"][0]["text"] == "Legacy summary."
    assert rec["policyArea"] == {"name": "Congress"}
    assert rec["subjects"][0]["name"] == "House rules"
    assert rec["titles"][0]["type"] == "Official Title as Introduced"


def test_parse_billstatus_skips_unusable_records():
    """A record with no bill type or number is dropped rather than given a junk id."""
    records = bulk.parse_billstatus(
        _zip_bytes(
            {
                "BILLSTATUS-117hr0.xml": (
                    "<billStatus><bill><congress>117</congress></bill></billStatus>"
                ),
                "BILLSTATUS-117hr9.xml": _BILLSTATUS_LEGACY,
            }
        )
    )
    assert [r["bill_id"] for r in records] == ["117-hr-9"]


def test_cache_dir_falls_back_when_preference_unwritable(monkeypatch, tmp_path):
    """An unwritable cache_directory preference falls back instead of disabling the cache."""
    from openbb_core.app import utils as core_utils

    unwritable = tmp_path / "gone"
    monkeypatch.setattr(core_utils, "get_user_cache_directory", lambda: str(unwritable))
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))

    real_makedirs = os.makedirs

    def _makedirs(path, *args, **kwargs):
        if str(path).startswith(str(unwritable)):
            raise PermissionError("read-only file system")
        return real_makedirs(path, *args, **kwargs)

    monkeypatch.setattr(bulk.os, "makedirs", _makedirs)
    bulk._WARNED.clear()

    path = bulk._cache_dir()
    assert path == os.path.join(
        str(tmp_path / "tmp"), "openbb_congress_gov", "bulkdata"
    )
    assert os.path.isdir(path)


def test_list_bills_routes_pre_bulk_congress_to_the_api(monkeypatch, tmp_path):
    """A pre-108 Congress is fetched from the API and cached like a bulk archive."""
    from openbb_government_us.congress.utils import congress_api, store

    monkeypatch.setattr(bulk, "_cache_dir", lambda: str(tmp_path))
    store.reset()
    BillsState().bulk.clear()

    calls: list = []

    async def _fetch(congress, bill_type, credentials):
        calls.append((congress, bill_type, credentials))
        return [
            congress_api.slim_record(
                {
                    "congress": congress,
                    "type": bill_type.upper(),
                    "number": "8410",
                    "title": "Labor Reform Act",
                    "updateDate": "1978-06-22T00:00:00Z",
                    "latestAction": {"actionDate": "1978-06-22", "text": "Passed."},
                }
            )
        ]

    async def _never(*_args, **_kwargs):
        raise AssertionError("the bulk path must not run for a pre-108 Congress")

    monkeypatch.setattr(congress_api, "fetch_bill_list", _fetch)
    monkeypatch.setattr(bulk, "ensure_billstatus", _never)

    creds = {"congress_gov_api_key": "k"}
    rows = asyncio.run(bulk.list_bills(95, ["hr"], limit=5, credentials=creds))

    assert [r["bill_id"] for r in rows] == ["95-hr-8410"]
    assert calls == [(95, "hr", creds)]

    # The rows are cached, so a second call serves from SQLite without refetching.
    assert store.loaded_keys("bills") == {"95-hr"}
    BillsState().bulk.clear()
    again = asyncio.run(bulk.list_bills(95, ["hr"], limit=5, credentials=creds))
    assert [r["bill_id"] for r in again] == ["95-hr-8410"]
    assert len(calls) == 1


def test_load_bill_record_hydrates_and_caches_the_detail(monkeypatch, tmp_path):
    """An API bill is detailed once, written back, and served from cache after."""
    from openbb_government_us.congress.utils import congress_api, store

    monkeypatch.setattr(bulk, "_cache_dir", lambda: str(tmp_path))
    store.reset()
    BillsState().bulk.clear()

    detail_calls: list = []

    async def _fetch(congress, bill_type, credentials):
        return [
            congress_api.slim_record(
                {
                    "congress": congress,
                    "type": bill_type.upper(),
                    "number": "8410",
                    "title": "Labor Reform Act",
                }
            )
        ]

    async def _detail(congress, bill_type, number, credentials):
        detail_calls.append((congress, bill_type, number))
        return {
            "bill_id": f"{congress}-{bill_type.lower()}-{number}",
            "congress": congress,
            "number": number,
            "type": bill_type.upper(),
            "title": "Labor Reform Act",
            "latestAction": {"actionDate": "1978-06-22", "text": "Passed."},
            "actions": [{"actionDate": "1978-06-22", "text": "Passed."}],
            "_detailed": True,
        }

    async def _never(*_args, **_kwargs):
        raise AssertionError("the bulk path must not run for a pre-108 Congress")

    monkeypatch.setattr(congress_api, "fetch_bill_list", _fetch)
    monkeypatch.setattr(congress_api, "bill_record", _detail)
    monkeypatch.setattr(bulk, "ensure_billstatus", _never)

    creds = {"congress_gov_api_key": "k"}
    record = asyncio.run(bulk.load_bill_record("95-hr-8410", creds))

    assert record["title"] == "Labor Reform Act"
    assert len(record["actions"]) == 1
    assert detail_calls == [(95, "hr", 8410)]

    # The hydrated record replaced the slim row, so no second detail call.
    cached = store.get_bill("95-hr-8410")
    assert cached["_detailed"] is True
    assert len(cached["actions"]) == 1

    BillsState().bulk.clear()
    again = asyncio.run(bulk.load_bill_record("95-hr-8410", creds))
    assert len(again["actions"]) == 1
    assert len(detail_calls) == 1


def test_congress_api_key_required_message(monkeypatch):
    """Without a key anywhere, the API path names the credential and where to get one."""
    from openbb_government_us.congress.utils import congress_api

    monkeypatch.setattr(congress_api, "user_credentials", dict)

    with pytest.raises(OpenBBError, match="congress_gov_api_key"):
        congress_api.api_key({})

    assert congress_api.api_key({"congress_gov_api_key": "k"}) == "k"


def test_congress_api_key_falls_back_to_user_settings(monkeypatch):
    """Router endpoints get no injected credentials, so the key is read from settings."""
    from openbb_government_us.congress.utils import congress_api

    monkeypatch.setattr(
        congress_api,
        "user_credentials",
        lambda: {"congress_gov_api_key": "from-settings"},
    )

    assert congress_api.api_key(None) == "from-settings"
    assert congress_api.api_key({}) == "from-settings"
    # An explicitly supplied key still wins.
    assert congress_api.api_key({"congress_gov_api_key": "explicit"}) == "explicit"


def test_congress_api_rejects_congress_below_api_coverage():
    """A Congress older than the API's own floor fails with a clear explanation."""
    from openbb_government_us.congress.utils import congress_api

    with pytest.raises(OpenBBError, match="predates structured bill data"):
        asyncio.run(
            congress_api.bill_record(50, "hr", 1, {"congress_gov_api_key": "k"})
        )


def test_list_bills_degrades_when_one_bill_type_fails(monkeypatch, tmp_path, caplog):
    """One failing archive still returns the types that loaded."""
    from openbb_government_us.congress.utils import store

    monkeypatch.setattr(bulk, "_cache_dir", lambda: str(tmp_path))
    store.reset()
    BillsState().bulk.clear()

    async def _ensure(congress, bill_type):
        if bill_type == "s":
            raise OpenBBError("archive 404")
        store.ingest_bills(
            congress,
            bill_type,
            [{"bill_id": "119-hr-1", "number": 1, "title": "A"}],
            [],
        )

    monkeypatch.setattr(bulk, "ensure_billstatus", _ensure)

    with caplog.at_level("ERROR"):
        rows = asyncio.run(bulk.list_bills(119, ["hr", "s"]))

    assert [r["bill_id"] for r in rows] == ["119-hr-1"]
    assert "ingest of 119-s failed" in caplog.text


def test_list_bills_raises_when_every_bill_type_fails(monkeypatch, tmp_path):
    """Nothing loadable is an error, naming the source that was tried."""
    monkeypatch.setattr(bulk, "_cache_dir", lambda: str(tmp_path))
    BillsState().bulk.clear()

    async def _ensure(congress, bill_type):
        raise OpenBBError("archive 404")

    monkeypatch.setattr(bulk, "ensure_billstatus", _ensure)

    with pytest.raises(OpenBBError, match="from bulk data"):
        asyncio.run(bulk.list_bills(119, ["hr", "s"]))


def test_list_bills_all_failed_names_the_api_source(monkeypatch, tmp_path):
    """The pre-108 path reports Congress.gov rather than the bulk archives."""
    from openbb_government_us.congress.utils import congress_api

    monkeypatch.setattr(bulk, "_cache_dir", lambda: str(tmp_path))
    BillsState().bulk.clear()

    async def _boom(congress, bill_type, credentials):
        raise OpenBBError("api down")

    monkeypatch.setattr(congress_api, "fetch_bill_list", _boom)

    with pytest.raises(OpenBBError, match="from the Congress.gov API"):
        asyncio.run(
            bulk.list_bills(95, ["hr"], credentials={"congress_gov_api_key": "k"})
        )


def test_warn_once_logs_a_key_a_single_time(caplog):
    """Diagnostics that run per store connection are logged once, not per query."""
    bulk._WARNED.discard("unit-test-key")

    with caplog.at_level("WARNING"):
        bulk._warn_once("unit-test-key", "first %s", "time")
        bulk._warn_once("unit-test-key", "second %s", "time")

    assert caplog.text.count("time") == 1
    bulk._WARNED.discard("unit-test-key")


def test_cache_dir_when_the_preference_cannot_be_read(monkeypatch, tmp_path, caplog):
    """An unreadable settings file still yields a usable fallback directory."""
    from openbb_core.app import utils as core_utils

    def _raise():
        raise RuntimeError("settings unreadable")

    monkeypatch.setattr(core_utils, "get_user_cache_directory", _raise)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    bulk._WARNED.clear()

    with caplog.at_level("WARNING"):
        path = bulk._cache_dir()

    assert path == os.path.join(
        str(tmp_path / "tmp"), "openbb_congress_gov", "bulkdata"
    )
    assert "could not read the user cache directory" in caplog.text
