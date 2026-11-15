"""Tests for the USDA FAS report calendar utils and model."""

import asyncio
from datetime import UTC, date, datetime

import pytest
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_government_us.usda.models.report_calendar import (
    FasReportCalendarFetcher,
    FasReportCalendarQueryParams,
)
from openbb_government_us.usda.utils import fas_report_calendar
from openbb_government_us.usda.utils.fas_report_calendar import (
    CALENDAR_URL,
    COMMODITIES,
    REPORT_TYPES,
    build_url,
    parse_calendar,
    parse_result_count,
)

SCHEDULED_ROW = """
      <div  class="c-view__row">
<div  class="c-card">
  <div class="fas-date__month-day">Jul 22</div>
  <span class="fas-date__dow">Wed</span>
  <span class="fas-date__time">3:00 PM</span>
  <div class="c-card__tags">
    <span>World Production, Markets, and Trade Report</span></div>
  <a href="/report-release-announcement/coffee-world-markets-and-trade-10" class="c-card__url">
    <h3 class="c-card__title">Coffee: World Markets and Trade</h3></a>
  <a href="data:text/calendar;charset=utf8,BEGIN%3AVCALENDAR%0D%0ADTSTART%3A20260722T190000Z%0D%0AEND%3AVCALENDAR">iCalendar</a>
</div></div>
"""

RELEASED_ROW = """
      <div  class="c-view__row">
<div  class="c-card">
  <div class="fas-date__month-day">Jul 16</div>
  <span class="fas-date__dow">Thu</span>
  <span class="fas-date__time">8:30 AM</span>
  <div class="c-card__tags">
    <span>Export Sales Report</span></div>
  <a href="/report-release-announcement/weekly-export-sales-293" class="c-card__url">
    <h3 class="c-card__title">Weekly Export Sales</h3></a>
</div></div>
"""

SAMPLE_HTML = (
    '<div class="c-view__header">All times in ET.</div>'
    '<div class="source-summary-count">2 results found</div>'
    + SCHEDULED_ROW
    + RELEASED_ROW
)


class TestFasReportCalendarUtils:
    """Tests for the fas_report_calendar utils module."""

    def test_facet_vocabularies(self):
        """The facet maps carry the published term ids."""
        assert REPORT_TYPES == {
            "export_sales": "10254",
            "trade_forecast": "10257",
            "world_markets_trade": "10259",
        }
        assert COMMODITIES["cotton"] == "6"
        assert COMMODITIES["soybeans"] == "27"
        assert len(COMMODITIES) == 19

    def test_build_url_unfiltered(self):
        """No filters yields the bare calendar URL."""
        assert build_url() == CALENDAR_URL

    def test_build_url_indexes_repeated_facets(self):
        """Each facet occupies its own indexed report_releases slot."""
        url = build_url(report_type="export_sales", commodity="cotton")
        assert "report_releases[0]=report_type:10254" in url
        assert "report_releases[1]=report_listing_commodities:6" in url

    def test_build_url_commodity_only_uses_first_slot(self):
        """A commodity filter alone occupies slot zero."""
        url = build_url(commodity="wheat")
        assert "report_releases[0]=report_listing_commodities:15" in url

    def test_build_url_keyword(self):
        """The keyword filter passes through."""
        assert "keyword=cotton" in build_url(keyword="cotton")

    def test_parse_result_count(self):
        """The stated result count parses."""
        assert parse_result_count(SAMPLE_HTML) == 2
        assert parse_result_count('<div class="x">1,234 results found</div>') == 1234
        assert parse_result_count("<div></div>") is None

    def test_parse_calendar_reads_dtstart_for_the_year(self):
        """The release timestamp comes from the embedded calendar entry."""
        rows = parse_calendar(SAMPLE_HTML)
        assert len(rows) == 2
        scheduled = rows[0]
        assert scheduled["release_datetime"] == datetime(
            2026, 7, 22, 19, 0, tzinfo=UTC
        )
        assert scheduled["title"] == "Coffee: World Markets and Trade"
        assert scheduled["report_type"] == "World Production, Markets, and Trade Report"
        assert scheduled["day_of_week"] == "Wed"
        assert scheduled["release_time"] == "3:00 PM"
        assert scheduled["url"] == (
            "https://www.fas.usda.gov/report-release-announcement"
            "/coffee-world-markets-and-trade-10"
        )
        assert scheduled["released"] is False

    def test_parse_calendar_tolerates_missing_calendar_entry(self):
        """A card whose release time has passed carries no timestamp."""
        released = parse_calendar(SAMPLE_HTML)[1]
        assert released["release_datetime"] is None
        assert released["released"] is True
        assert released["title"] == "Weekly Export Sales"

    def test_parse_calendar_skips_rows_without_a_title(self):
        """Rows lacking a title are not emitted."""
        assert parse_calendar('<div  class="c-view__row">no card</div>') == []

    def test_afetch_calendar_uses_the_shared_session(self, monkeypatch):
        """The fetch routes through the shared impersonating session."""
        calls: list[str] = []

        class _Response:
            status_code = 200
            text = SAMPLE_HTML

        class _Session:
            @staticmethod
            async def get(url):
                calls.append(url)
                return _Response()

        async def fake_get_session():
            return _Session()

        monkeypatch.setattr(fas_report_calendar, "_get_session", fake_get_session)
        html = asyncio.run(fas_report_calendar.afetch_calendar(CALENDAR_URL))
        assert html == SAMPLE_HTML
        assert calls == [CALENDAR_URL]

    def test_afetch_calendar_raises_on_error_status(self, monkeypatch):
        """A non-200 response raises OpenBBError."""

        class _Response:
            status_code = 403
            text = ""

        class _Session:
            @staticmethod
            async def get(url):
                return _Response()

        async def fake_get_session():
            return _Session()

        monkeypatch.setattr(fas_report_calendar, "_get_session", fake_get_session)
        with pytest.raises(OpenBBError, match="status 403"):
            asyncio.run(fas_report_calendar.afetch_calendar(CALENDAR_URL))

    def test_get_session_delegates_to_the_shared_helper(self, monkeypatch):
        """The module's session accessor delegates to the shared helper."""
        captured: list[str] = []

        async def fake_get_session(key, warmup=None):
            captured.append(key)
            return "session"

        monkeypatch.setattr(
            "openbb_government_us.utils.curl_session.get_session", fake_get_session
        )
        assert asyncio.run(fas_report_calendar._get_session()) == "session"
        assert captured == [fas_report_calendar.SESSION_KEY]


class TestFasReportCalendar:
    """Tests for the FasReportCalendar model."""

    def test_transform_query(self):
        """transform_query builds the query params model."""
        query = FasReportCalendarFetcher.transform_query(
            {"report_type": "export_sales"}
        )
        assert isinstance(query, FasReportCalendarQueryParams)
        assert query.report_type == "export_sales"

    def test_extract_builds_the_filtered_url(self, monkeypatch):
        """The fetcher requests the URL carrying its facet filters."""
        calls: list[str] = []

        async def fake_afetch(url):
            calls.append(url)
            return SAMPLE_HTML

        monkeypatch.setattr(fas_report_calendar, "afetch_calendar", fake_afetch)
        query = FasReportCalendarFetcher.transform_query(
            {"report_type": "export_sales", "commodity": "cotton", "keyword": "wheat"}
        )
        rows = asyncio.run(FasReportCalendarFetcher.aextract_data(query, None))
        assert len(rows) == 2
        assert "report_type:10254" in calls[0]
        assert "report_listing_commodities:6" in calls[0]
        assert "keyword=wheat" in calls[0]

    def test_transform_data_converts_to_eastern(self):
        """The release date is the Eastern-Time day of the UTC timestamp."""
        query = FasReportCalendarFetcher.transform_query({})
        results = FasReportCalendarFetcher.transform_data(
            query, parse_calendar(SCHEDULED_ROW)
        )
        assert len(results) == 1
        assert results[0].release_date == date(2026, 7, 22)
        assert results[0].release_datetime == datetime(
            2026, 7, 22, 19, 0, tzinfo=UTC
        )
        assert results[0].released is False

    def test_transform_data_dates_a_released_row_today(self):
        """A row whose time has passed is dated the current Eastern day."""
        from zoneinfo import ZoneInfo

        query = FasReportCalendarFetcher.transform_query({})
        results = FasReportCalendarFetcher.transform_data(
            query, parse_calendar(RELEASED_ROW)
        )
        assert (
            results[0].release_date
            == datetime.now(tz=ZoneInfo("America/New_York")).date()
        )
        assert results[0].released is True
        assert results[0].release_datetime is None

    def test_transform_data_applies_the_date_window(self):
        """Releases outside the requested window are dropped."""
        query = FasReportCalendarFetcher.transform_query(
            {"start_date": "2026-07-01", "end_date": "2026-07-21"}
        )
        with pytest.raises(EmptyDataError):
            FasReportCalendarFetcher.transform_data(
                query, parse_calendar(SCHEDULED_ROW)
            )

        query = FasReportCalendarFetcher.transform_query({"start_date": "2026-07-23"})
        with pytest.raises(EmptyDataError):
            FasReportCalendarFetcher.transform_data(
                query, parse_calendar(SCHEDULED_ROW)
            )

        query = FasReportCalendarFetcher.transform_query(
            {"start_date": "2026-07-22", "end_date": "2026-07-22"}
        )
        assert (
            len(
                FasReportCalendarFetcher.transform_data(
                    query, parse_calendar(SCHEDULED_ROW)
                )
            )
            == 1
        )

    def test_transform_data_sorts_by_date_then_title(self):
        """Results sort by release date, then title."""
        query = FasReportCalendarFetcher.transform_query({})
        results = FasReportCalendarFetcher.transform_data(
            query, parse_calendar(SAMPLE_HTML)
        )
        assert [r.release_date for r in results] == sorted(
            r.release_date for r in results
        )

    def test_transform_data_empty_raises(self):
        """No rows raises EmptyDataError."""
        query = FasReportCalendarFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FasReportCalendarFetcher.transform_data(query, [])

    def test_fallback_date_without_month_day_raises(self):
        """A row carrying neither a timestamp nor a date raises."""
        from openbb_government_us.usda.models.report_calendar import _fallback_date

        with pytest.raises(OpenBBError, match="neither a timestamp nor a date"):
            _fallback_date(None, None)
