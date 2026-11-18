"""Congress.gov Fetchers tests."""

from datetime import datetime

import pytest
from openbb_core.app.service.user_service import UserService

from openbb_government_us.congress.models.amendment_info import (
    CongressAmendmentInfoFetcher,
)
from openbb_government_us.congress.models.amendment_text import (
    CongressAmendmentTextFetcher,
)
from openbb_government_us.congress.models.bill_info import CongressBillInfoFetcher
from openbb_government_us.congress.models.bill_text import CongressBillTextFetcher
from openbb_government_us.congress.models.congress_amendments import (
    CongressAmendmentsFetcher,
)
from openbb_government_us.congress.models.congress_bills import CongressBillsFetcher
from openbb_government_us.congress.models.congress_calendars import (
    CongressCalendarsFetcher,
)
from openbb_government_us.congress.models.congress_committee_documents import (
    CongressCommitteeDocumentsFetcher,
)
from openbb_government_us.congress.models.congress_committee_info import (
    CongressCommitteeInfoFetcher,
)
from openbb_government_us.congress.models.congress_laws import CongressLawsFetcher
from openbb_government_us.congress.models.congress_mandated_reports import (
    CongressMandatedReportsFetcher,
)
from openbb_government_us.congress.models.congress_members import CongressMembersFetcher
from openbb_government_us.congress.models.congress_search import CongressSearchFetcher
from openbb_government_us.congress.models.member_legislation import (
    CongressMemberLegislationFetcher,
)
from openbb_government_us.congress.models.member_votes import CongressMemberVotesFetcher
from openbb_government_us.congress.utils.helpers import year_to_congress

test_credentials = UserService().default_user_settings.credentials.model_dump(
    mode="json"
)
test_credentials = (
    test_credentials
    if test_credentials and test_credentials.get("congress_gov_api_key")
    else {"congress_gov_api_key": "MOCK_API_KEY"}
)


@pytest.fixture(scope="module")
def vcr_config():
    """VCR configuration."""
    return {
        "filter_headers": [
            ("User-Agent", None),
            ("api_key", "MOCK_API_KEY"),
        ],
        "filter_query_parameters": [
            ("api_key", "MOCK_API_KEY"),
        ],
    }


def test_year_to_congress():
    """Test year to congress conversion."""
    current_year = datetime.now().year
    assert year_to_congress(current_year) >= 119
    assert year_to_congress(2000) == 106
    assert year_to_congress(1993) == 103
    with pytest.raises(ValueError):
        year_to_congress(1930)


_BULK_BILL_RECORD = {
    "congress": 119,
    "number": 1947,
    "type": "S",
    "bill_id": "119-s-1947",
    "originChamber": "Senate",
    "originChamberCode": "S",
    "title": "A Test Bill",
    "introducedDate": "2025-01-03",
    "updateDate": "2025-11-30T06:37:21Z",
    "updateDateIncludingText": "2025-11-30T06:37:21Z",
    "latestAction": {"actionDate": "2025-02-10", "text": "Read the second time."},
    "policyArea": {"name": "Immigration"},
    "sponsors": [{"fullName": "Sen. Example"}],
    "cosponsors": [],
    "actions": [{"actionDate": "2025-02-10", "text": "Read.", "type": "Calendars"}],
    "committees": [],
    "relatedBills": [],
    "subjects": [{"name": "Border security", "updateDate": "2025-01-08"}],
    "titles": [{"title": "A Test Bill", "type": "Short Title"}],
    "summaries": [{"text": "<p>Summary.</p>", "actionDate": "2025-01-03"}],
}


def test_congress_bills_fetcher(monkeypatch, credentials=test_credentials):
    """Test Congress Bills fetcher offline against the GovInfo bulk path."""

    async def _fake_list_bills(congress, bill_types, **kwargs):
        return [
            {
                "updateDate": "2025-11-30",
                "bill_id": "119-s-1947",
                "congress": 119,
                "number": 1947,
                "originChamber": "Senate",
                "originChamberCode": "S",
                "type": "S",
                "title": "A Test Bill",
                "latestAction": {
                    "actionDate": "2025-02-10",
                    "text": "Read the second time.",
                },
                "updateDateIncludingText": "2025-11-30T06:37:21Z",
            }
        ]

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.list_bills", _fake_list_bills
    )
    params = {
        "limit": 1,
    }

    fetcher = CongressBillsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


def test_congress_bill_info_fetcher(monkeypatch, credentials=test_credentials):
    """Test Congress Bill Info fetcher offline against the GovInfo bulk path."""

    async def _fake_load_bill_record(bill_id, credentials=None):
        return dict(_BULK_BILL_RECORD)

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.load_bill_record",
        _fake_load_bill_record,
    )
    params = {
        "bill_id": "119-s-1947",
    }

    fetcher = CongressBillInfoFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_congress_bill_text_fetcher(credentials=test_credentials):
    """Test Congress Bill Text fetcher."""
    params = {
        "urls": [
            "https://www.govinfo.gov/content/pkg/BILLS-119hr29ih/pdf/BILLS-119hr29ih.pdf"
        ],
    }

    fetcher = CongressBillTextFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


_BULK_AMENDMENT_RECORD = {
    "amendment_id": "119-hamdt-2",
    "congress": 119,
    "number": "2",
    "type": "HAMDT",
    "description": "An amendment in the nature of a substitute.",
    "purpose": "To amend.",
    "chamber": "House of Representatives",
    "updateDate": "2025-02-10T08:00:00Z",
    "proposedDate": "",
    "submittedDate": "2025-02-09T05:00:00Z",
    "latestAction": {
        "actionDate": "2025-02-10",
        "actionTime": "",
        "text": "Agreed to without objection.",
    },
    "sponsors": [{"fullName": "Rep. Example", "party": "R"}],
    "cosponsors": [],
    "actions": [{"actionDate": "2025-02-10", "text": "Agreed.", "type": "X"}],
    "links": [],
    "amendedBill": {"congress": "119", "type": "HR", "number": "1", "title": "A Bill"},
    "amendedAmendment": {},
}


def test_congress_amendments_fetcher(monkeypatch, credentials=test_credentials):
    """Test Congress Amendments fetcher offline against the bulk path."""

    async def _fake_load_amendments(congress, amendment_type=None):
        return [dict(_BULK_AMENDMENT_RECORD)]

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.load_amendments",
        _fake_load_amendments,
    )
    params = {"congress": 119, "limit": 1}

    fetcher = CongressAmendmentsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


def test_congress_amendment_info_fetcher(monkeypatch, credentials=test_credentials):
    """Test Congress Amendment Info fetcher offline against the bulk path."""

    async def _fake_load_amendment_record(amendment_id):
        return dict(_BULK_AMENDMENT_RECORD)

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.load_amendment_record",
        _fake_load_amendment_record,
    )
    params = {"amendment_id": "119-hamdt-2"}

    fetcher = CongressAmendmentInfoFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_congress_amendment_text_fetcher(credentials=test_credentials):
    """Test Congress Amendment Text fetcher against a GovInfo CREC document."""
    params = {
        "urls": [
            "https://www.govinfo.gov/content/pkg/CREC-2026-03-21/pdf/CREC-2026-03-21-pt1-PgS1484-6.pdf"
        ],
    }

    fetcher = CongressAmendmentTextFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


def test_congress_committee_documents_fetcher(
    monkeypatch, credentials=test_credentials
):
    """Test Congress Committee Documents fetcher offline against the keyless path."""

    async def _fake_fetch(system_code, congress, doc_type="all", limit=20, offset=0):
        return [
            {
                "doc_type": "report",
                "citation": "S. Rept. 119-5",
                "title": "A Committee Report",
                "date": "2026-05-04",
                "congress": 119,
                "chamber": "Senate",
                "package_id": "CRPT-119srpt5",
                "doc_url": "https://www.govinfo.gov/content/pkg/CRPT-119srpt5/pdf/CRPT-119srpt5.pdf",
            }
        ]

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.committees.fetch_committee_documents",
        _fake_fetch,
    )
    params = {
        "chamber": "senate",
        "committee": "slin00",
        "doc_type": "report",
        "congress": 119,
        "limit": 5,
    }

    fetcher = CongressCommitteeDocumentsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


def test_congress_committee_info_fetcher(monkeypatch, credentials=test_credentials):
    """Test Congress Committee Info fetcher offline against the keyless path."""

    async def _fake_overview(system_code, chamber):
        return {
            "chamber": chamber,
            "system_code": system_code,
            "detail": {
                "name": "Senate Committee on Indian Affairs",
                "chamber": chamber,
                "type": "senate",
                "website": "https://www.indian.senate.gov",
                "jurisdiction": "Indian affairs.",
                "is_subcommittee": False,
                "parent_name": "",
                "subcommittees": [],
            },
            "members": [{"name": "Sen. Chair", "party": "majority", "title": "Chair"}],
        }

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.committees.get_committee_overview",
        _fake_overview,
    )
    params = {
        "chamber": "senate",
        "committee": "slin00",
    }

    fetcher = CongressCommitteeInfoFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


_LAW_RECORD = {
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
}


def test_congress_laws_fetcher(monkeypatch, credentials=test_credentials):
    """Test Congress Laws fetcher offline against the GovInfo PLAW bulk path."""

    async def _fake_load_plaw(congress, law_type):
        return [dict(_LAW_RECORD)]

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.load_plaw", _fake_load_plaw
    )
    params = {"congress": 119, "law_type": "public", "limit": 1}

    fetcher = CongressLawsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


_CALENDAR_RECORD = {
    "package_id": "CCAL-119hcal-2025-01-07",
    "congress": 119,
    "chamber": "house",
    "calendar_date": "2025-01-07",
    "title": "House Calendar - 2025-01-07",
    "pdf": "https://x/CCAL-119hcal-2025-01-07.pdf",
    "htm": "https://x/CCAL-119hcal-2025-01-07.htm",
    "xml": "https://x/CCAL-119hcal-2025-01-07.xml",
}


def test_congress_calendars_fetcher(monkeypatch, credentials=test_credentials):
    """Test Congress Calendars fetcher offline against the GovInfo CCAL path."""

    async def _fake_load_calendars(congress, chamber):
        return [dict(_CALENDAR_RECORD)]

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.load_calendars", _fake_load_calendars
    )
    params = {"chamber": "house", "calendar_date": "mostrecent"}

    fetcher = CongressCalendarsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


_CMR_RECORD = {
    "package_id": "CMR-A98-1",
    "title": "Report One",
    "submitting_agency": "Agency X",
    "publication_date": "2026-03-13",
    "pdf": "https://x/CMR-A98-1.pdf",
    "details_link": "https://x/details",
}


def test_congress_mandated_reports_fetcher(monkeypatch, credentials=test_credentials):
    """Test Congress Mandated Reports fetcher offline against the GovInfo CMR path."""

    async def _fake_fetch_cmr(congress, pagesize=100, offset=0):
        return [dict(_CMR_RECORD)]

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.fetch_cmr", _fake_fetch_cmr
    )
    params = {"congress": 119, "limit": 5}

    fetcher = CongressMandatedReportsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


_SEARCH_RECORD = {
    "title": "A Hearing",
    "collection": "CHRG",
    "date": "2026-03-25",
    "congress": 119,
    "citation": "S. Hrg. 119-1",
    "package_id": "CHRG-119shrg1",
    "doc_url": "https://x/CHRG-119shrg1.pdf",
}


def test_congress_search_fetcher(monkeypatch, credentials=test_credentials):
    """Test Congress Search fetcher offline against the GovInfo wssearch path."""

    async def _fake_search_govinfo(query, **kwargs):
        return [dict(_SEARCH_RECORD)]

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.search_govinfo", _fake_search_govinfo
    )
    params = {"query": "immigration", "collection": "CHRG", "congress": 119}

    fetcher = CongressSearchFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


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
        },
    ],
}


def test_congress_members_fetcher(monkeypatch, credentials=test_credentials):
    """Test Congress Members fetcher offline against the legislators dataset."""

    async def _fake_load_members():
        return [dict(_MEMBER_RECORD)]

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.load_members", _fake_load_members
    )
    params = {"chamber": "house", "state": "AL", "party": "Republican"}

    fetcher = CongressMembersFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


def test_congress_member_votes_fetcher(monkeypatch, credentials=test_credentials):
    """Test Congress Member Votes fetcher offline against the Voteview path."""

    async def _fake_load_member_record(bioguide):
        return dict(_MEMBER_RECORD)

    async def _fake_member_votes(bioguide, service, *, limit):
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
            }
        ]

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.load_member_record",
        _fake_load_member_record,
    )
    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.member_votes", _fake_member_votes
    )
    params = {"bioguide_id": "A000055", "limit": 25}

    fetcher = CongressMemberVotesFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


def test_congress_member_legislation_fetcher(monkeypatch, credentials=test_credentials):
    """Test Congress Member Legislation fetcher offline against the bulk path."""

    async def _fake_load_member_record(bioguide):
        return dict(_MEMBER_RECORD)

    async def _fake_member_legislation(bioguide, congresses):
        return [
            {
                "bill_id": "119-hr-1",
                "congress": 119,
                "role": "Sponsor",
                "title": "Bill One",
                "introduced_date": "2025-01-03",
                "latest_action_date": "2025-02-01",
                "latest_action": "Referred",
            }
        ]

    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.load_member_record",
        _fake_load_member_record,
    )
    monkeypatch.setattr(
        "openbb_government_us.congress.utils.bulk.member_legislation",
        _fake_member_legislation,
    )
    params = {"bioguide_id": "A000055"}

    fetcher = CongressMemberLegislationFetcher()
    result = fetcher.test(params, credentials)
    assert result is None
