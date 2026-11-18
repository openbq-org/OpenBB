"""Tests for openbb_government_us.congress model fetchers (transform + error paths)."""

import asyncio

import pytest
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils import helpers as core_helpers

from openbb_government_us.congress.models.amendment_info import (
    CongressAmendmentInfoFetcher,
    CongressAmendmentInfoQueryParams,
)
from openbb_government_us.congress.models.amendment_text import (
    CongressAmendmentTextFetcher,
    CongressAmendmentTextQueryParams,
)
from openbb_government_us.congress.models.bill_info import (
    CongressBillInfoFetcher,
    CongressBillInfoQueryParams,
)
from openbb_government_us.congress.models.bill_text import (
    CongressBillTextFetcher,
    CongressBillTextQueryParams,
)
from openbb_government_us.congress.models.congress_amendments import (
    CongressAmendmentsFetcher,
    CongressAmendmentsQueryParams,
)
from openbb_government_us.congress.models.congress_bills import (
    CongressBillsFetcher,
    CongressBillsQueryParams,
)
from openbb_government_us.congress.models.congress_committee_documents import (
    CongressCommitteeDocumentsFetcher,
    CongressCommitteeDocumentsQueryParams,
)
from openbb_government_us.congress.models.congress_committee_info import (
    CongressCommitteeInfoFetcher,
)
from openbb_government_us.congress.models.congress_members import (
    CongressMembersFetcher,
    CongressMembersQueryParams,
)
from openbb_government_us.congress.models.member_legislation import (
    CongressMemberLegislationFetcher,
)
from openbb_government_us.congress.models.member_votes import CongressMemberVotesFetcher

CREDS = {"congress_gov_api_key": "K"}


def test_bills_query_invalid_type():
    """An invalid bill_type raises an OpenBBError from the validator."""
    with pytest.raises(OpenBBError):
        CongressBillsQueryParams(bill_type="bad")


def test_bills_query_limit_zero_without_type():
    """limit=0 without bill_type raises an OpenBBError."""
    with pytest.raises(OpenBBError):
        CongressBillsQueryParams(limit=0)


def test_bills_transform_query():
    """transform_query returns a query params instance."""
    q = CongressBillsFetcher.transform_query({"bill_type": "hr", "congress": 119})
    assert isinstance(q, CongressBillsQueryParams)


def _bulk_records(congress=119, bill_type="HR"):
    """Build two slim list records for the bulk-path extract tests."""
    return [
        {
            "updateDate": "2025-01-10",
            "bill_id": f"{congress}-{bill_type.lower()}-1",
            "congress": congress,
            "number": 1,
            "originChamber": "House",
            "originChamberCode": "H",
            "type": bill_type,
            "title": "Older Bill",
            "latestAction": {"actionDate": "2025-01-10", "text": "Introduced"},
            "updateDateIncludingText": "2025-01-10T00:00:00Z",
        },
        {
            "updateDate": "2025-02-20",
            "bill_id": f"{congress}-{bill_type.lower()}-2",
            "congress": congress,
            "number": 2,
            "originChamber": "House",
            "originChamberCode": "H",
            "type": bill_type,
            "title": "Newer Bill",
            "latestAction": {"actionDate": "2025-02-20", "text": "Passed"},
            "updateDateIncludingText": "2025-02-20T00:00:00Z",
        },
    ]


def _patch_list_bills(monkeypatch, records=None, capture=None):
    """Patch bulk.list_bills, recording its (congress, bill_types, kwargs) call."""

    async def _fake(congress, bill_types, **kwargs):
        if capture is not None:
            capture.append((congress, list(bill_types), kwargs))
        return list(records if records is not None else _bulk_records())

    monkeypatch.setattr("openbb_government_us.congress.utils.bulk.list_bills", _fake)


def test_bills_extract_explicit_congress(monkeypatch):
    """An explicit congress + bill_type queries exactly that one type."""
    calls: list = []
    _patch_list_bills(monkeypatch, capture=calls)
    q = CongressBillsQueryParams(bill_type="hr", congress=119)
    result = asyncio.run(CongressBillsFetcher.aextract_data(q, CREDS))
    assert calls[0][0] == 119
    assert calls[0][1] == ["hr"]
    assert {r["number"] for r in result} == {1, 2}


def test_bills_extract_congress_from_start_date(monkeypatch):
    """A start date with no congress derives congress from the start year."""
    calls: list = []
    _patch_list_bills(monkeypatch, capture=calls)
    q = CongressBillsQueryParams(bill_type="hr", start_date="1993-01-01")
    asyncio.run(CongressBillsFetcher.aextract_data(q, CREDS))
    assert calls[0][0] == 103


def test_bills_extract_congress_from_end_date(monkeypatch):
    """An end date with no congress/start date derives congress from the end year."""
    calls: list = []
    _patch_list_bills(monkeypatch, capture=calls)
    q = CongressBillsQueryParams(bill_type="hr", end_date="2000-12-31")
    asyncio.run(CongressBillsFetcher.aextract_data(q, CREDS))
    assert calls[0][0] == 106


def test_bills_extract_congress_current(monkeypatch):
    """No congress/dates resolves to the current Congress."""
    calls: list = []
    _patch_list_bills(monkeypatch, capture=calls)
    q = CongressBillsQueryParams(bill_type="hr")
    asyncio.run(CongressBillsFetcher.aextract_data(q, CREDS))
    assert calls[0][0] >= 119


def test_bills_extract_all_types(monkeypatch):
    """No bill_type queries every bill type for the Congress."""
    from openbb_government_us.congress.utils.constants import BillTypes

    calls: list = []
    _patch_list_bills(monkeypatch, records=[], capture=calls)
    q = CongressBillsQueryParams(congress=119)
    asyncio.run(CongressBillsFetcher.aextract_data(q, CREDS))
    assert calls[0][1] == list(BillTypes)


def test_bills_extract_params_forwarded(monkeypatch):
    """Date window, limit, offset, and sort flow through to bulk.list_bills."""
    from datetime import date

    calls: list = []
    _patch_list_bills(monkeypatch, capture=calls)
    q = CongressBillsQueryParams(
        bill_type="hr",
        congress=119,
        start_date="2025-02-01",
        end_date="2025-03-01",
        limit=1,
        offset=1,
        sort_by="desc",
    )
    asyncio.run(CongressBillsFetcher.aextract_data(q, CREDS))
    kwargs = calls[0][2]
    assert kwargs["start_date"] == date(2025, 2, 1)
    assert kwargs["end_date"] == date(2025, 3, 1)
    assert kwargs["limit"] == 1
    assert kwargs["offset"] == 1
    assert kwargs["sort_by"] == "desc"


def test_bills_transform_data():
    """transform_data sorts bills and lifts latestAction fields."""
    q = CongressBillsQueryParams(sort_by="desc")
    data = [
        {
            "bill_id": "119-hr-1",
            "congress": 119,
            "number": 1,
            "originChamber": "House",
            "originChamberCode": "H",
            "type": "HR",
            "title": "Older",
            "updateDate": "2025-01-01",
            "latestAction": {"actionDate": "2025-01-01", "text": "Introduced"},
        },
        {
            "bill_id": "119-hr-2",
            "congress": 119,
            "number": 2,
            "originChamber": "House",
            "originChamberCode": "H",
            "type": "HR",
            "title": "Newer",
            "updateDate": "2025-02-01",
            "latestAction": {"actionDate": "2025-02-01", "text": "Passed"},
        },
    ]
    result = CongressBillsFetcher.transform_data(q, data)
    assert result[0].title == "Newer"
    assert result[0].latest_action == "Passed"


def test_bills_transform_data_no_latest_action():
    """A bill without latestAction falls back to updateDate for sorting."""
    q = CongressBillsQueryParams(sort_by="asc")
    data = [
        {
            "bill_id": "119-hr-1",
            "congress": 119,
            "number": 1,
            "originChamber": "House",
            "originChamberCode": "H",
            "type": "HR",
            "title": "NoAction",
            "updateDate": "2025-01-01",
        }
    ]
    result = CongressBillsFetcher.transform_data(q, data)
    assert result[0].latest_action is None


def test_bill_info_extract_found(monkeypatch):
    """aextract_data returns the record load_bill_record yields for the bill id."""
    captured: list = []

    async def _fake(bill_id, credentials=None):
        captured.append(bill_id)
        return {"title": "Test Bill", "number": 1947}

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.load_bill_record", _fake
    )
    q = CongressBillInfoQueryParams(bill_id="119-s-1947")
    result = asyncio.run(CongressBillInfoFetcher.aextract_data(q, CREDS))
    assert result["title"] == "Test Bill"
    assert captured == ["119-s-1947"]


def test_bill_info_extract_not_found(monkeypatch):
    """A missing bill propagates the OpenBBError from load_bill_record."""

    async def _fake(bill_id, credentials=None):
        raise OpenBBError("Bill not found in bulk data: 119/hr/999")

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.load_bill_record", _fake
    )
    q = CongressBillInfoQueryParams(bill_id="119-hr-999")
    with pytest.raises(OpenBBError, match="not found"):
        asyncio.run(CongressBillInfoFetcher.aextract_data(q, CREDS))


def test_bill_info_extract_summary_merge(monkeypatch):
    """The BILLSUM-merged summaries flow through to the extracted record."""

    async def _fake(bill_id, credentials=None):
        return {
            "title": "Merged",
            "number": 1,
            "summaries": [{"text": "CRS summary text", "actionDate": "2025-01-03"}],
        }

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.load_bill_record", _fake
    )
    q = CongressBillInfoQueryParams(bill_id="119-hr-1")
    result = asyncio.run(CongressBillInfoFetcher.aextract_data(q, CREDS))
    assert result["summaries"][0]["text"] == "CRS summary text"


def test_bill_info_transform_full():
    """transform_data renders all markdown sections including HTML conversion."""
    data = {
        "title": "Big Bill",
        "congress": 119,
        "number": 1,
        "type": "HR",
        "originChamber": "House",
        "introducedDate": "2025-01-01",
        "updateDate": "2025-02-01",
        "latestAction": {"actionDate": "2025-02-01", "text": "Passed"},
        "policyArea": {"name": "Health"},
        "relatedBills": [
            {
                "number": 2,
                "type": "S",
                "congress": 119,
                "title": "Related",
                "latestAction": {"actionDate": "2025-01-15", "text": "Read"},
                "relationshipDetails": [{"type": "Identical", "identifiedBy": "CRS"}],
            }
        ],
        "summaries": [
            {
                "text": "<p><strong>Summary Title</strong></p><ul><li>x</li></ul><ol><li>y</li></ol>"
            }
        ],
        "subjects": [{"name": "Taxes", "updateDate": "2025-01-01"}],
        "sponsors": [{"fullName": "Rep A"}],
        "cosponsors": [
            {
                "fullName": "Rep B",
                "isOriginalCosponsor": True,
                "sponsorshipDate": "2025-01-02",
            }
        ],
        "titles": [
            {
                "title": "Short Title",
                "type": "Short",
                "chamberName": "House",
                "billTextVersionName": "Introduced",
                "updateDate": "2025-01-01",
            }
        ],
        "committees": [
            {
                "name": "Ways and Means",
                "chamber": "House",
                "type": "Standing",
                "activities": [{"name": "Referred", "date": "2025-01-01"}],
                "subcommittees": [
                    {
                        "name": "Tax",
                        "activities": [{"name": "Hearing", "date": "2025-01-05"}],
                    }
                ],
            }
        ],
        "actions": [
            {"actionDate": "2025-01-01", "text": "Introduced", "type": "IntroReferral"}
        ],
    }
    q = CongressBillInfoQueryParams(bill_id="119-hr-1")
    result = CongressBillInfoFetcher.transform_data(q, data)
    md = result.markdown_content
    assert "Big Bill" in md
    assert "Policy Area" in md
    assert "Related Bills" in md
    assert "Summary Title" in md
    assert "Subjects" in md
    assert "Original Cosponsor" in md
    assert "Subcommittees" in md


def test_bill_info_transform_committee_no_chamber():
    """A committee without a chamber renders just the name."""
    data = {
        "title": "B",
        "committees": [{"name": "Solo Committee"}],
    }
    q = CongressBillInfoQueryParams(bill_id="119-hr-1")
    result = CongressBillInfoFetcher.transform_data(q, data)
    assert "Solo Committee" in result.markdown_content


def test_bill_info_html_to_markdown_no_title():
    """A summary with no <p><strong> title still converts cleanly."""
    data = {"title": "B", "summaries": [{"text": "<p>Plain text</p>"}]}
    q = CongressBillInfoQueryParams(bill_id="119-hr-1")
    result = CongressBillInfoFetcher.transform_data(q, data)
    assert "Plain text" in result.markdown_content


def test_bill_info_html_to_markdown_title_prefix_repeat():
    """A title repeated at the start of the body is stripped a second time."""
    data = {
        "title": "B",
        "summaries": [
            {"text": "<p><strong>Heading</strong></p>Heading then more body"}
        ],
    }
    q = CongressBillInfoQueryParams(bill_id="119-hr-1")
    result = CongressBillInfoFetcher.transform_data(q, data)
    assert "**Heading**" in result.markdown_content


def test_bill_info_transform_query():
    """transform_query builds bill info query params."""
    q = CongressBillInfoFetcher.transform_query({"bill_id": "119-s-1"})
    assert isinstance(q, CongressBillInfoQueryParams)


def test_bill_text_invalid_url(monkeypatch):
    """A non-congress URL is reported as invalid."""
    q = CongressBillTextQueryParams(urls=["https://example.com/x.pdf"])
    result = asyncio.run(CongressBillTextFetcher.aextract_data(q))
    assert result[0]["error_type"] == "invalid_url"


def test_bill_text_pdf_and_text(monkeypatch):
    """A PDF URL is base64-encoded; a non-PDF returns text."""

    class _Resp:
        def __init__(self, content, text):
            self.content = content
            self.text = text

        def raise_for_status(self):
            """No-op."""

    def _route(url):
        if url.endswith(".pdf"):
            return _Resp(b"%PDF data", "")
        return _Resp(b"", "plain html")

    monkeypatch.setattr(core_helpers, "make_request", _route)
    q = CongressBillTextQueryParams(
        urls=[
            "https://www.congress.gov/a.pdf",
            "https://www.congress.gov/b.htm",
        ]
    )
    result = asyncio.run(CongressBillTextFetcher.aextract_data(q))
    assert result[0]["data_format"]["data_type"] == "pdf"
    assert result[1]["data_format"]["data_type"] == "text"


def test_bill_text_download_error(monkeypatch):
    """A download exception is captured."""

    def _boom(url):
        raise RuntimeError("down")

    monkeypatch.setattr(core_helpers, "make_request", _boom)
    q = CongressBillTextQueryParams(urls="https://www.congress.gov/a.pdf")
    result = asyncio.run(CongressBillTextFetcher.aextract_data(q))
    assert result[0]["error_type"] == "download_error"


def test_bill_text_dict_urls(monkeypatch):
    """A dict body with a 'urls' key is unwrapped."""
    monkeypatch.setattr(core_helpers, "make_request", lambda url: None)
    q = CongressBillTextQueryParams(urls={"urls": ["https://example.com/x.pdf"]})
    result = asyncio.run(CongressBillTextFetcher.aextract_data(q))
    assert result[0]["error_type"] == "invalid_url"


def test_bill_text_transform_data():
    """transform_data wraps the raw dicts into data models."""
    q = CongressBillTextQueryParams(urls=["https://www.congress.gov/x.pdf"])
    result = CongressBillTextFetcher.transform_data(
        q, [{"content": "abc", "data_format": {"data_type": "pdf"}}]
    )
    assert result[0].content == "abc"


def test_bill_text_transform_query():
    """transform_query builds query params."""
    q = CongressBillTextFetcher.transform_query(
        {"urls": ["https://www.congress.gov/x.pdf"]}
    )
    assert isinstance(q, CongressBillTextQueryParams)


def test_amendment_text_invalid_url():
    """A non-GovInfo URL is reported as invalid for amendment text."""
    q = CongressAmendmentTextQueryParams(urls="https://example.com/x.pdf")
    result = asyncio.run(CongressAmendmentTextFetcher.aextract_data(q))
    assert result[0]["error_type"] == "invalid_url"


def test_amendment_text_pdf_text_and_error(monkeypatch):
    """Amendment text handles PDF, text, and download-error cases."""

    class _Resp:
        def __init__(self, content, text):
            self.content = content
            self.text = text

        def raise_for_status(self):
            """No-op."""

    def _route(url):
        if "boom" in url:
            raise RuntimeError("down")
        if url.endswith(".pdf"):
            return _Resp(b"%PDF", "")
        return _Resp(b"", "txt")

    monkeypatch.setattr(core_helpers, "make_request", _route)
    q = CongressAmendmentTextQueryParams(
        urls=[
            "https://www.govinfo.gov/a.pdf",
            "https://www.govinfo.gov/b.txt",
            "https://www.govinfo.gov/boom.pdf",
        ]
    )
    result = asyncio.run(CongressAmendmentTextFetcher.aextract_data(q))
    assert result[0]["data_format"]["data_type"] == "pdf"
    assert result[1]["data_format"]["data_type"] == "text"
    assert result[2]["error_type"] == "download_error"


def test_amendment_text_transform_query_and_data():
    """transform_query/transform_data round-trip for amendment text."""
    q = CongressAmendmentTextFetcher.transform_query(
        {"urls": ["https://www.govinfo.gov/x.pdf"]}
    )
    assert isinstance(q, CongressAmendmentTextQueryParams)
    result = CongressAmendmentTextFetcher.transform_data(q, [{"content": "z"}])
    assert result[0].content == "z"


def _full_amendment(number, amd_type="SAMDT", **over):
    """Build a full bulk amendment record for the extract tests."""
    rec = {
        "amendment_id": f"119-{amd_type.lower()}-{number}",
        "congress": 119,
        "number": number,
        "type": amd_type,
        "description": "An amendment",
        "purpose": "To clarify",
        "chamber": "Senate",
        "updateDate": "2025-02-01T00:00:00Z",
        "proposedDate": "",
        "submittedDate": "2025-01-15T00:00:00Z",
        "latestAction": {
            "actionDate": "2025-02-01",
            "actionTime": "",
            "text": "Agreed",
        },
        "sponsors": [{"fullName": "Sen. A"}],
        "cosponsors": [],
        "actions": [],
        "links": [],
        "amendedBill": {"congress": "119", "type": "S", "number": "2", "title": "Bill"},
        "amendedAmendment": {},
    }
    rec.update(over)
    return rec


def test_amendments_query_invalid_type():
    """An invalid amendment_type raises an OpenBBError."""
    with pytest.raises(OpenBBError):
        CongressAmendmentsQueryParams(amendment_type="bad")


def test_amendments_query_limit_zero_without_type():
    """limit=0 without amendment_type raises an OpenBBError."""
    with pytest.raises(OpenBBError):
        CongressAmendmentsQueryParams(limit=0)


def test_amendments_extract_default_congress(monkeypatch):
    """With no congress, the current Congress is resolved and passed through."""
    from openbb_government_us.congress.utils.helpers import year_to_congress

    captured = {}

    async def _fake_load(congress, amendment_type=None):
        captured["congress"] = congress
        captured["type"] = amendment_type
        return [_full_amendment("1"), _full_amendment("2")]

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.load_amendments", _fake_load
    )
    q = CongressAmendmentsQueryParams()
    result = asyncio.run(CongressAmendmentsFetcher.aextract_data(q, CREDS))
    from datetime import datetime

    assert captured["congress"] == year_to_congress(datetime.now().year)
    assert captured["type"] is None
    assert result[0]["amendment_id"].startswith("119-samdt-")
    assert "latestAction" in result[0]


def test_amendments_extract_with_type_and_filters(monkeypatch):
    """A congress, type, and date/limit filters are applied post-fetch."""

    async def _fake_load(congress, amendment_type=None):
        return [
            _full_amendment("1", updateDate="2025-01-05T00:00:00Z"),
            _full_amendment("2", updateDate="2025-03-05T00:00:00Z"),
            _full_amendment("3", updateDate="2025-06-05T00:00:00Z"),
        ]

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.load_amendments", _fake_load
    )
    q = CongressAmendmentsQueryParams(
        congress=119,
        amendment_type="samdt",
        start_date="2025-02-01",
        end_date="2025-05-01",
        limit=5,
    )
    result = asyncio.run(CongressAmendmentsFetcher.aextract_data(q, CREDS))
    assert len(result) == 1
    assert result[0]["number"] == "2"


def test_amendments_transform_data():
    """transform_data lifts action/sponsor/amended fields and trims dates."""
    q = CongressAmendmentsQueryParams(sort_by="desc")
    data = [
        {
            "amendment_id": "119-hamdt-1",
            "congress": 119,
            "type": "HAMDT",
            "number": "1",
            "updateDate": "2025-02-01",
            "latestAction": {
                "actionDate": "2025-02-01",
                "actionTime": "10:00",
                "text": "Agreed",
            },
            "amendedBill": {"type": "HR", "number": "5", "title": "Bill Title"},
            "sponsors": [{"fullName": "Rep A"}],
            "submittedDate": "2025-01-15T00:00:00Z",
        },
        {
            "amendment_id": "119-hamdt-2",
            "congress": 119,
            "type": "HAMDT",
            "number": "2",
            "updateDate": "",
            "latestAction": {"actionDate": "", "actionTime": "", "text": ""},
            "amendedBill": {},
            "amendedAmendment": {"type": "SAMDT", "number": "9"},
            "sponsors": [],
        },
    ]
    result = CongressAmendmentsFetcher.transform_data(q, data)
    by_id = {r.amendment_id: r for r in result}
    assert by_id["119-hamdt-1"].amended_bill == "HR 5"
    assert by_id["119-hamdt-1"].sponsor == "Rep A"
    assert by_id["119-hamdt-1"].submitted_date is not None
    assert by_id["119-hamdt-1"].latest_action == "Agreed"
    assert by_id["119-hamdt-2"].latest_action is None
    assert by_id["119-hamdt-2"].amended_bill == "Amdt. SAMDT 9"
    assert by_id["119-hamdt-2"].update_date is None


def test_amendments_transform_query():
    """transform_query builds amendment query params."""
    q = CongressAmendmentsFetcher.transform_query({"congress": 119})
    assert isinstance(q, CongressAmendmentsQueryParams)


def test_amendment_info_extract(monkeypatch):
    """aextract_data returns the bulk record load_amendment_record yields."""
    captured = []

    async def _fake(amendment_id):
        captured.append(amendment_id)
        return {"number": "2", "type": "HAMDT", "congress": 119}

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.load_amendment_record", _fake
    )
    q = CongressAmendmentInfoQueryParams(amendment_id="119-hamdt-2")
    result = asyncio.run(CongressAmendmentInfoFetcher.aextract_data(q, CREDS))
    assert result["number"] == "2"
    assert captured == ["119-hamdt-2"]


def test_amendment_info_transform_full():
    """transform_data renders all amendment markdown sections."""
    data = {
        "number": "2",
        "type": "HAMDT",
        "congress": 119,
        "description": "An amendment to do things",
        "purpose": "To clarify the act",
        "chamber": "House",
        "submittedDate": "2025-01-01",
        "updateDate": "2025-02-01",
        "latestAction": {"actionDate": "2025-02-01", "text": "Agreed"},
        "amendedBill": {"congress": 119, "type": "HR", "number": "1", "title": "Bill"},
        "amendedAmendment": {"congress": 119, "type": "SAMDT", "number": "9"},
        "sponsors": [{"fullName": "Rep A", "party": "R"}],
        "cosponsors": [{"fullName": "Rep B", "party": "D"}],
        "textVersions": [
            {
                "date": "2025-01-01",
                "type": "CR",
                "formats": [{"type": "PDF", "url": "u"}],
            }
        ],
        "actions": [{"actionDate": "2025-01-01", "text": "t", "type": "X"}],
    }
    q = CongressAmendmentInfoQueryParams(amendment_id="119-hamdt-2")
    result = CongressAmendmentInfoFetcher.transform_data(q, data)
    md = result.markdown_content
    assert "Latest Action" in md
    assert "Amended Bill" in md
    assert "Amends Amendment" in md
    assert "Sponsors" in md
    assert "Cosponsors" in md
    assert "Text Versions" in md
    assert "Actions" in md


def test_amendment_info_transform_minimal_and_cosponsor_count():
    """A minimal amendment with a cosponsor count dict renders the count line."""
    data = {
        "number": "2",
        "type": "HAMDT",
        "congress": 119,
        "description": "",
        "purpose": "",
        "cosponsors": {"count": 3},
        "proposedDate": "2025-01-01",
        "latestAction": {"actionDate": "", "text": ""},
    }
    q = CongressAmendmentInfoQueryParams(amendment_id="119-hamdt-2")
    result = CongressAmendmentInfoFetcher.transform_data(q, data)
    md = result.markdown_content
    assert "Amendment 119 HAMDT 2" in md
    assert "Count" in md
    assert "Latest Action" not in md


def test_amendment_info_transform_query():
    """transform_query builds amendment info query params."""
    q = CongressAmendmentInfoFetcher.transform_query({"amendment_id": "119-hamdt-2"})
    assert isinstance(q, CongressAmendmentInfoQueryParams)


def test_committee_info_extract(monkeypatch):
    """Committee info delegates to the keyless get_committee_overview loader."""
    captured = {}

    async def _fake_overview(system_code, chamber):
        captured["system_code"] = system_code
        captured["chamber"] = chamber
        return {
            "chamber": chamber,
            "system_code": system_code,
            "detail": {"name": "House Committee on the Judiciary"},
            "members": [{"name": "M", "party": "majority", "title": "Chair"}],
        }

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.committees.get_committee_overview",
        _fake_overview,
    )
    q = CongressCommitteeInfoFetcher.transform_query(
        {"chamber": "house", "committee": "HSJU00"}
    )
    result = asyncio.run(CongressCommitteeInfoFetcher.aextract_data(q, CREDS))
    assert captured["system_code"] == "hsju00"
    assert captured["chamber"] == "house"
    assert result["members"][0]["name"] == "M"


def test_committee_info_extract_subcommittee(monkeypatch):
    """A subcommittee code is preferred over the parent committee code."""
    captured = {}

    async def _fake_overview(system_code, chamber):
        captured["system_code"] = system_code
        return {
            "chamber": chamber,
            "system_code": system_code,
            "detail": {},
            "members": [],
        }

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.committees.get_committee_overview",
        _fake_overview,
    )
    q = CongressCommitteeInfoFetcher.transform_query(
        {"chamber": "house", "committee": "hsju00", "subcommittee": "hsju03"}
    )
    asyncio.run(CongressCommitteeInfoFetcher.aextract_data(q, CREDS))
    assert captured["system_code"] == "hsju03"


def test_committee_info_transform_full():
    """transform_data renders overview, jurisdiction, subcommittees, and members."""
    data = {
        "chamber": "house",
        "system_code": "hsju00",
        "detail": {
            "name": "House Committee on the Judiciary",
            "chamber": "house",
            "type": "house",
            "website": "https://judiciary.house.gov",
            "jurisdiction": "Judicial matters.",
            "is_subcommittee": False,
            "parent_name": "",
            "subcommittees": [
                {"name": "Subcommittee on Courts", "systemCode": "hsju03"},
                {"name": "", "systemCode": "hsju99"},
            ],
        },
        "members": [
            {"name": "Chair P", "party": "majority", "title": "Chair"},
            {"name": "Ranking P", "party": "minority", "title": "Ranking Member"},
            {"name": "Member P", "party": "majority", "title": ""},
        ],
    }
    q = CongressCommitteeInfoFetcher.transform_query(
        {"chamber": "house", "committee": "hsju00"}
    )
    result = CongressCommitteeInfoFetcher.transform_data(q, data)
    md = result.markdown_content
    assert "House Committee on the Judiciary" in md
    assert "Jurisdiction" in md
    assert "Judicial matters." in md
    assert "Subcommittees (2)" in md
    assert "Subcommittee on Courts" in md
    assert "Website" in md
    assert "Members (3)" in md
    assert "| Member P | majority | Member |" in md


def test_committee_info_transform_subcommittee_parent_row():
    """A subcommittee renders the parent-committee meta row."""
    data = {
        "chamber": "house",
        "system_code": "hsju03",
        "detail": {
            "name": "House Committee on the Judiciary — Subcommittee on Courts",
            "chamber": "house",
            "type": "house",
            "website": "",
            "jurisdiction": "",
            "is_subcommittee": True,
            "parent_name": "House Committee on the Judiciary",
            "subcommittees": [],
        },
        "members": [],
    }
    q = CongressCommitteeInfoFetcher.transform_query(
        {"chamber": "house", "committee": "hsju00", "subcommittee": "hsju03"}
    )
    result = CongressCommitteeInfoFetcher.transform_data(q, data)
    md = result.markdown_content
    assert "Parent Committee" in md
    assert "House Committee on the Judiciary" in md


def test_committee_info_transform_no_name_no_members():
    """No name falls back to the upper-cased code and a no-data note."""
    data = {
        "chamber": "house",
        "system_code": "hsag00",
        "detail": {},
        "members": [],
    }
    q = CongressCommitteeInfoFetcher.transform_query(
        {"chamber": "house", "committee": "hsag00"}
    )
    result = CongressCommitteeInfoFetcher.transform_data(q, data)
    md = result.markdown_content
    assert "HSAG00" in md
    assert "Member data not available" in md


def test_committee_documents_extract(monkeypatch):
    """Committee documents delegates to fetch_committee_documents."""

    async def _fake(**kwargs):
        return [{"doc_type": "report", "title": "R", "doc_url": "u"}]

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.committees.fetch_committee_documents",
        _fake,
    )
    q = CongressCommitteeDocumentsQueryParams(
        chamber="senate", committee="ssaf00", doc_type="report"
    )
    result = asyncio.run(CongressCommitteeDocumentsFetcher.aextract_data(q, CREDS))
    assert result[0]["doc_type"] == "report"


def test_committee_documents_extract_default_congress(monkeypatch):
    """A None congress defaults to the current congress."""
    captured = {}

    async def _fake(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.committees.fetch_committee_documents",
        _fake,
    )
    q = CongressCommitteeDocumentsQueryParams(
        chamber="house", committee="hsju00", subcommittee="hsju03"
    )
    asyncio.run(CongressCommitteeDocumentsFetcher.aextract_data(q, CREDS))
    assert captured["congress"] >= 119
    assert captured["system_code"] == "hsju03"


def test_committee_documents_extract_error(monkeypatch):
    """An OpenBBError from the helper is re-raised."""

    async def _boom(**kwargs):
        raise OpenBBError("rate limit")

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.committees.fetch_committee_documents",
        _boom,
    )
    q = CongressCommitteeDocumentsQueryParams(chamber="senate", committee="ssaf00")
    with pytest.raises(OpenBBError):
        asyncio.run(CongressCommitteeDocumentsFetcher.aextract_data(q, CREDS))


def test_committee_documents_transform_query():
    """transform_query builds committee documents query params."""
    q = CongressCommitteeDocumentsFetcher.transform_query(
        {"chamber": "senate", "committee": "ssaf00"}
    )
    assert isinstance(q, CongressCommitteeDocumentsQueryParams)


def test_committee_documents_transform_data():
    """transform_data validates dicts (incl. date/package_id/doc_url) into models."""
    from datetime import date

    q = CongressCommitteeDocumentsQueryParams(chamber="senate", committee="ssaf00")
    result = CongressCommitteeDocumentsFetcher.transform_data(
        q,
        [
            {
                "doc_type": "report",
                "citation": "H. Rept. 119-637",
                "title": "R",
                "date": "2026-05-04",
                "congress": 119,
                "chamber": "House",
                "package_id": "CRPT-119hrpt637",
                "doc_url": "https://x/CRPT-119hrpt637.pdf",
            }
        ],
    )
    assert result[0].doc_type == "report"
    assert result[0].date == date(2026, 5, 4)
    assert result[0].package_id == "CRPT-119hrpt637"
    assert result[0].doc_url == "https://x/CRPT-119hrpt637.pdf"


_LAW_RECORDS = [
    {
        "law_id": "119-1",
        "law_number": 1,
        "law_type": "public",
        "congress": 119,
        "title": "Act One",
        "citation": "Public Law 119-1",
        "statute_citation": "139 Stat. 3",
        "package_id": "PLAW-119publ1",
        "enacted_date": "2025-01-29",
        "pdf": "https://x/PLAW-119publ1.pdf",
        "htm": "https://x/PLAW-119publ1.htm",
        "xml": "https://x/PLAW-119publ1.xml",
    },
    {
        "law_id": "119-2",
        "law_number": 2,
        "law_type": "public",
        "congress": 119,
        "title": "Act Two",
        "citation": "Public Law 119-2",
        "statute_citation": "",
        "package_id": "PLAW-119publ2",
        "enacted_date": "2025-02-15",
        "pdf": "https://x/PLAW-119publ2.pdf",
        "htm": "https://x/PLAW-119publ2.htm",
        "xml": "https://x/PLAW-119publ2.xml",
    },
]


def _patch_load_plaw(monkeypatch, capture=None):
    """Patch bulk.load_plaw, recording each (congress, law_type) call."""

    async def _fake(congress, law_type):
        if capture is not None:
            capture.append((congress, law_type))
        return list(_LAW_RECORDS)

    monkeypatch.setattr("openbb_government_us.congress.utils.bulk.load_plaw", _fake)


def test_laws_transform_query():
    """transform_query builds the laws query params with defaults."""
    from openbb_government_us.congress.models.congress_laws import CongressLawsFetcher

    q = CongressLawsFetcher.transform_query({"congress": 119})
    assert q.congress == 119
    assert q.law_type == "public"


def test_laws_extract_explicit_congress(monkeypatch):
    """Explicit congress/law_type is passed through and the limit is applied."""
    from openbb_government_us.congress.models.congress_laws import (
        CongressLawsFetcher,
        CongressLawsQueryParams,
    )

    calls: list = []
    _patch_load_plaw(monkeypatch, capture=calls)
    q = CongressLawsQueryParams(congress=119, law_type="public", limit=1)
    result = asyncio.run(CongressLawsFetcher.aextract_data(q, None))
    assert calls == [(119, "public")]
    assert len(result) == 1
    assert result[0]["law_number"] == 2


def test_laws_extract_current_congress(monkeypatch):
    """No congress resolves to the current Congress."""
    from openbb_government_us.congress.models.congress_laws import (
        CongressLawsFetcher,
        CongressLawsQueryParams,
    )

    calls: list = []
    _patch_load_plaw(monkeypatch, capture=calls)
    asyncio.run(CongressLawsFetcher.aextract_data(CongressLawsQueryParams(), None))
    assert calls[0][0] >= 119
    assert calls[0][1] == "public"


def test_laws_transform_data():
    """transform_data builds CongressLawsData models with typed fields."""
    from datetime import date

    from openbb_government_us.congress.models.congress_laws import (
        CongressLawsFetcher,
        CongressLawsQueryParams,
    )

    out = CongressLawsFetcher.transform_data(
        CongressLawsQueryParams(), list(_LAW_RECORDS)
    )
    assert out[0].law_id == "119-1"
    assert out[0].enacted_date == date(2025, 1, 29)
    assert out[0].pdf.endswith("PLAW-119publ1.pdf")


_CAL_RECORDS = [
    {
        "package_id": "CCAL-119hcal-2025-01-07",
        "congress": 119,
        "chamber": "house",
        "calendar_date": "2025-01-07",
        "title": "House Calendar - 2025-01-07",
        "pdf": "https://x/CCAL-119hcal-2025-01-07.pdf",
        "htm": "https://x/CCAL-119hcal-2025-01-07.htm",
        "xml": "https://x/CCAL-119hcal-2025-01-07.xml",
    },
    {
        "package_id": "CCAL-119hcal-2025-01-03",
        "congress": 119,
        "chamber": "house",
        "calendar_date": "2025-01-03",
        "title": "House Calendar - 2025-01-03",
        "pdf": "https://x/CCAL-119hcal-2025-01-03.pdf",
        "htm": "https://x/CCAL-119hcal-2025-01-03.htm",
        "xml": "https://x/CCAL-119hcal-2025-01-03.xml",
    },
]


def _patch_load_calendars(monkeypatch, capture=None):
    """Patch bulk.load_calendars to return canned CCAL records."""

    async def _fake(congress, chamber):
        if capture is not None:
            capture.append((congress, chamber))
        return list(_CAL_RECORDS)

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.load_calendars", _fake
    )


def test_calendars_transform_query():
    """transform_query builds the calendars query params with defaults."""
    from openbb_government_us.congress.models.congress_calendars import (
        CongressCalendarsFetcher,
    )

    q = CongressCalendarsFetcher.transform_query({"chamber": "senate"})
    assert q.chamber == "senate"


def test_calendars_extract_mostrecent(monkeypatch):
    """calendar_date=mostrecent returns the latest edition; current congress resolves."""
    from openbb_government_us.congress.models.congress_calendars import (
        CongressCalendarsFetcher,
        CongressCalendarsQueryParams,
    )

    calls: list = []
    _patch_load_calendars(monkeypatch, capture=calls)
    q = CongressCalendarsQueryParams(chamber="house", calendar_date="mostrecent")
    result = asyncio.run(CongressCalendarsFetcher.aextract_data(q, None))
    assert len(result) == 1
    assert result[0]["calendar_date"] == "2025-01-07"
    assert calls[0][0] >= 119
    assert calls[0][1] == "house"


def test_calendars_extract_both_chambers(monkeypatch):
    """chamber=both loads House and Senate editions and merges them."""
    from openbb_government_us.congress.models.congress_calendars import (
        CongressCalendarsFetcher,
        CongressCalendarsQueryParams,
    )

    calls: list = []
    _patch_load_calendars(monkeypatch, capture=calls)
    q = CongressCalendarsQueryParams(chamber="both", congress=119)
    result = asyncio.run(CongressCalendarsFetcher.aextract_data(q, None))
    assert {c for _, c in calls} == {"house", "senate"}
    assert len(result) == 4


def test_calendars_transform_data(monkeypatch):
    """transform_data builds CongressCalendarsData models."""
    from datetime import date

    from openbb_government_us.congress.models.congress_calendars import (
        CongressCalendarsFetcher,
        CongressCalendarsQueryParams,
    )

    out = CongressCalendarsFetcher.transform_data(
        CongressCalendarsQueryParams(), list(_CAL_RECORDS)
    )
    assert out[0].package_id == "CCAL-119hcal-2025-01-07"
    assert out[0].calendar_date == date(2025, 1, 7)


_CMR_RECORDS = [
    {
        "package_id": "CMR-A98-1",
        "title": "Report One",
        "submitting_agency": "Agency X",
        "publication_date": "2026-03-13",
        "pdf": "https://x/CMR-A98-1.pdf",
        "details_link": "https://x/details",
    },
]


def test_mandated_reports_extract_and_transform(monkeypatch):
    """fetch_cmr is called with a capped pagesize; transform builds models."""
    from datetime import date

    from openbb_government_us.congress.models.congress_mandated_reports import (
        CongressMandatedReportsFetcher,
        CongressMandatedReportsQueryParams,
    )

    captured: dict = {}

    async def _fake_fetch(congress, pagesize=100, offset=0):
        captured["congress"] = congress
        captured["pagesize"] = pagesize
        captured["offset"] = offset
        return list(_CMR_RECORDS)

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.fetch_cmr", _fake_fetch
    )
    q = CongressMandatedReportsQueryParams(congress=119, limit=5000, offset=20)
    result = asyncio.run(CongressMandatedReportsFetcher.aextract_data(q, None))
    assert captured["congress"] == 119
    assert captured["pagesize"] == 1000
    assert captured["offset"] == 20

    out = CongressMandatedReportsFetcher.transform_data(q, result)
    assert out[0].package_id == "CMR-A98-1"
    assert out[0].submitting_agency == "Agency X"
    assert out[0].publication_date == date(2026, 3, 13)


def test_mandated_reports_transform_query():
    """transform_query returns a mandated-reports query params instance."""
    from openbb_government_us.congress.models.congress_mandated_reports import (
        CongressMandatedReportsFetcher,
        CongressMandatedReportsQueryParams,
    )

    q = CongressMandatedReportsFetcher.transform_query({"congress": 119})
    assert isinstance(q, CongressMandatedReportsQueryParams)
    assert q.congress == 119


def test_mandated_reports_default_congress(monkeypatch):
    """No congress resolves to the current Congress; default pagesize is 100."""
    from openbb_government_us.congress.models.congress_mandated_reports import (
        CongressMandatedReportsFetcher,
        CongressMandatedReportsQueryParams,
    )

    captured: dict = {}

    async def _fake_fetch(congress, pagesize=100, offset=0):
        captured["congress"] = congress
        captured["pagesize"] = pagesize
        return []

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.fetch_cmr", _fake_fetch
    )
    asyncio.run(
        CongressMandatedReportsFetcher.aextract_data(
            CongressMandatedReportsQueryParams(), None
        )
    )
    assert captured["congress"] >= 119
    assert captured["pagesize"] == 100


_SEARCH_RECORDS = [
    {
        "title": "A Hearing",
        "collection": "CHRG",
        "date": "2026-03-25",
        "congress": 119,
        "citation": "S. Hrg. 119-1",
        "package_id": "CHRG-119shrg1",
        "doc_url": "https://x/CHRG-119shrg1.pdf",
    },
]


def test_search_extract_and_transform(monkeypatch):
    """CongressSearch passes filters to search_govinfo and builds models."""
    from openbb_government_us.congress.models.congress_search import (
        CongressSearchFetcher,
    )

    captured: dict = {}

    async def _fake(query, **kwargs):
        captured["query"] = query
        captured.update(kwargs)
        return list(_SEARCH_RECORDS)

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.search_govinfo", _fake
    )
    q = CongressSearchFetcher.transform_query(
        {
            "query": "immigration",
            "collection": "CHRG",
            "congress": 119,
            "start_date": "2025-01-01",
        }
    )
    out = asyncio.run(CongressSearchFetcher.aextract_data(q, None))
    assert captured["query"] == "immigration"
    assert captured["collection"] == "CHRG"
    assert captured["congress"] == 119
    assert captured["start_date"] == "2025-01-01"

    models = CongressSearchFetcher.transform_data(q, out)
    assert models[0].package_id == "CHRG-119shrg1"
    assert models[0].collection == "CHRG"


_MEMBER_RECORD = {
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
            "start": "2013-01-03",
            "end": "2015-01-03",
        },
        {
            "type": "rep",
            "state": "AL",
            "district": 4,
            "party": "Republican",
            "start": "2025-01-03",
            "end": "2027-01-03",
            "url": "https://aderholt.house.gov",
            "phone": "202-225-4876",
            "office": "266 Cannon",
            "contact_form": "https://x/contact",
        },
    ],
}


def test_members_extract_and_transform(monkeypatch):
    """The members fetcher loads, filters, and builds models."""

    async def _load():
        return [_MEMBER_RECORD]

    monkeypatch.setattr("openbb_government_us.congress.utils.bulk.load_members", _load)
    q = CongressMembersQueryParams(chamber="house", state="AL", party="Republican")
    rows = CongressMembersFetcher.transform_data(
        q, asyncio.run(CongressMembersFetcher.aextract_data(q, None))
    )
    assert rows[0].bioguide_id == "A000055"
    assert rows[0].district == 4
    assert rows[0].chamber == "house"


def test_members_transform_query():
    """transform_query builds the members query params."""
    q = CongressMembersFetcher.transform_query({"chamber": "senate"})
    assert isinstance(q, CongressMembersQueryParams)


def test_member_votes_extract_full_tenure(monkeypatch):
    """Votes span every served (congress, chamber); a congress filter narrows it."""
    captured = {}

    async def _record(bioguide):
        return _MEMBER_RECORD

    async def _votes(bioguide, service, *, limit):
        captured["service"] = service
        return [
            {
                "congress": 119,
                "chamber": "house",
                "rollnumber": 207,
                "position": "Yea",
                "cast_code": "1",
                "bill_id": "119-hr-1",
                "legislation": "HR1",
                "title": "A Bill",
                "question": "On Passage",
                "result": "Passed",
                "date": "2026-06-04",
            },
            {
                "congress": 113,
                "chamber": "house",
                "rollnumber": 5,
                "position": "Nay",
                "cast_code": "6",
                "bill_id": "113-hr-2",
                "legislation": "HR2",
                "title": "Older Bill",
                "question": "On Passage",
                "result": "Failed",
                "date": "",
            },
        ]

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.load_member_record", _record
    )
    monkeypatch.setattr("openbb_government_us.congress.utils.bulk.member_votes", _votes)

    q = CongressMemberVotesFetcher.transform_query({"bioguide_id": "A000055"})
    rows = CongressMemberVotesFetcher.transform_data(
        q, asyncio.run(CongressMemberVotesFetcher.aextract_data(q, None))
    )
    assert (119, "H") in captured["service"] and (113, "H") in captured["service"]
    assert rows[0].bill_id == "119-hr-1"
    assert rows[0].chamber == "house"
    assert str(rows[0].date) == "2026-06-04"
    assert rows[1].date is None
    assert not hasattr(rows[0], "cast_code") or "cast_code" not in rows[0].model_dump()

    q2 = CongressMemberVotesFetcher.transform_query(
        {"bioguide_id": "A000055", "congress": 113}
    )
    asyncio.run(CongressMemberVotesFetcher.aextract_data(q2, None))
    assert captured["service"] == [(113, "H")]


def test_member_votes_extract_no_service(monkeypatch):
    """A member with no terms (no service) returns an empty list."""

    async def _record(bioguide):
        return {"id": {"bioguide": "X"}, "name": {}, "terms": []}

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.load_member_record", _record
    )
    q = CongressMemberVotesFetcher.transform_query({"bioguide_id": "X"})
    assert asyncio.run(CongressMemberVotesFetcher.aextract_data(q, None)) == []


def test_member_legislation_extract_full_history(monkeypatch):
    """With no congress, legislation spans every Congress the member served."""
    captured = {}

    async def _record(bioguide):
        return _MEMBER_RECORD

    async def _leg(bioguide, congresses):
        captured["congresses"] = congresses
        return [
            {
                "bill_id": "119-hr-1",
                "congress": 119,
                "role": "Sponsor",
                "title": "Bill One",
                "introduced_date": "2025-01-03",
                "latest_action_date": "2025-02-01",
                "latest_action": "Referred",
            },
        ]

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.load_member_record", _record
    )
    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.member_legislation", _leg
    )
    q = CongressMemberLegislationFetcher.transform_query({"bioguide_id": "A000055"})
    rows = CongressMemberLegislationFetcher.transform_data(
        q, asyncio.run(CongressMemberLegislationFetcher.aextract_data(q, None))
    )
    assert 119 in captured["congresses"] and len(captured["congresses"]) > 1
    assert rows[0].bill_id == "119-hr-1"
    assert rows[0].congress == 119
    assert rows[0].role == "Sponsor"


def test_member_legislation_extract_single_congress(monkeypatch):
    """An explicit congress restricts the scan to that one Congress."""
    captured = {}

    async def _leg(bioguide, congresses):
        captured["congresses"] = congresses
        return []

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.member_legislation", _leg
    )
    q = CongressMemberLegislationFetcher.transform_query(
        {"bioguide_id": "A000055", "congress": 118}
    )
    asyncio.run(CongressMemberLegislationFetcher.aextract_data(q, None))
    assert captured["congresses"] == [118]
