"""Tests for the Nasdaq calendar, screener, and filings models."""

import asyncio
from datetime import date

import pytest
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_nasdaq.models.calendar_dividend import NasdaqCalendarDividendFetcher
from openbb_nasdaq.models.calendar_earnings import NasdaqCalendarEarningsFetcher
from openbb_nasdaq.models.calendar_ipo import NasdaqCalendarIpoFetcher
from openbb_nasdaq.models.calendar_splits import (
    NasdaqCalendarSplitsFetcher,
    _split_ratio,
)
from openbb_nasdaq.models.company_filings import NasdaqCompanyFilingsFetcher
from openbb_nasdaq.models.economic_calendar import NasdaqEconomicCalendarFetcher
from openbb_nasdaq.models.etf_search import NasdaqEtfSearchFetcher
from openbb_nasdaq.models.index_search import NasdaqIndexSearchFetcher

from .conftest import patch_data

WINDOW = {"start_date": date(2026, 7, 24), "end_date": date(2026, 7, 24)}


class TestCalendarDividend:
    """Cover the dividend calendar."""

    def test_transforms_a_row(self, monkeypatch):
        """A calendar row resolves and sorts by ex date."""
        patch_data(
            monkeypatch,
            {
                "calendar": {
                    "rows": [
                        {
                            "symbol": "AAPL",
                            "companyName": "Apple Inc.",
                            "dividend_Ex_Date": "07/24/2026",
                            "payment_Date": "08/14/2026",
                            "record_Date": "08/11/2026",
                            "dividend_Rate": "0.26",
                            "announcement_Date": "07/31/2026",
                        }
                    ]
                }
            },
        )
        query = NasdaqCalendarDividendFetcher.transform_query(WINDOW)
        raw = asyncio.run(NasdaqCalendarDividendFetcher.aextract_data(query, None))
        rows = NasdaqCalendarDividendFetcher.transform_data(query, raw)

        assert rows[0].symbol == "AAPL"
        assert rows[0].amount == pytest.approx(0.26)

    def test_empty_raises(self):
        """A window with no dividends is reported."""
        query = NasdaqCalendarDividendFetcher.transform_query(WINDOW)

        with pytest.raises(EmptyDataError):
            NasdaqCalendarDividendFetcher.transform_data(query, [])

    def test_missing_calendar_block(self, monkeypatch):
        """A day without a calendar block contributes nothing."""
        patch_data(monkeypatch, {})
        query = NasdaqCalendarDividendFetcher.transform_query(WINDOW)

        assert (
            asyncio.run(NasdaqCalendarDividendFetcher.aextract_data(query, None)) == []
        )


class TestCalendarEarnings:
    """Cover the earnings calendar."""

    def test_transforms_a_row(self, monkeypatch):
        """The as-of date is attached to each row."""
        patch_data(
            monkeypatch,
            {
                "asOf": "Fri, Jul 24, 2026",
                "rows": [
                    {
                        "symbol": "AAPL",
                        "name": "Apple Inc.",
                        "eps": "$1.50",
                        "epsForecast": "$1.40",
                        "marketCap": "$5,000",
                        "noOfEsts": "20",
                        "time": "time-after-hours",
                        "lastYearEPS": "$1.20",
                        "lastYearRptDt": "07/25/2025",
                        "fiscalQuarterEnding": "Jun/2026",
                    }
                ],
            },
        )
        query = NasdaqCalendarEarningsFetcher.transform_query(WINDOW)
        raw = asyncio.run(NasdaqCalendarEarningsFetcher.aextract_data(query, None))
        rows = NasdaqCalendarEarningsFetcher.transform_data(query, raw)

        assert rows[0].symbol == "AAPL"
        assert rows[0].report_date == date(2026, 7, 24)

    def test_empty_raises(self):
        """A window with no reports is reported."""
        query = NasdaqCalendarEarningsFetcher.transform_query(WINDOW)

        with pytest.raises(EmptyDataError):
            NasdaqCalendarEarningsFetcher.transform_data(query, [])

    def test_missing_rows(self, monkeypatch):
        """A day without rows contributes nothing."""
        patch_data(monkeypatch, {"asOf": "Fri, Jul 24, 2026"})
        query = NasdaqCalendarEarningsFetcher.transform_query(WINDOW)

        assert (
            asyncio.run(NasdaqCalendarEarningsFetcher.aextract_data(query, None)) == []
        )


class TestCalendarSplits:
    """Cover the stock splits calendar."""

    def test_transforms_and_filters(self, monkeypatch):
        """Rows outside the window drop and the ratio is decomposed."""
        patch_data(
            monkeypatch,
            {
                "rows": [
                    {
                        "symbol": "SGLY",
                        "name": "Singularity",
                        "executionDate": "07/24/2026",
                        "ratio": "1 : 10",
                    },
                    {
                        "symbol": "OLD",
                        "name": "Old Split",
                        "executionDate": "01/01/2020",
                        "ratio": "2 : 1",
                    },
                    {"symbol": "NODATE", "executionDate": "N/A"},
                ]
            },
        )
        query = NasdaqCalendarSplitsFetcher.transform_query(WINDOW)
        raw = asyncio.run(NasdaqCalendarSplitsFetcher.aextract_data(query, None))
        rows = NasdaqCalendarSplitsFetcher.transform_data(query, raw)

        assert len(rows) == 1
        assert rows[0].numerator == 1
        assert rows[0].denominator == 10
        assert rows[0].split_ratio == pytest.approx(0.1)

    def test_drops_rows_after_the_window(self, monkeypatch):
        """A split later than the window is dropped."""
        query = NasdaqCalendarSplitsFetcher.transform_query(WINDOW)
        rows = NasdaqCalendarSplitsFetcher.transform_data(
            query, [{"symbol": "X", "executionDate": "12/31/2026", "ratio": "2 : 1"}]
        )

        assert rows == []

    def test_keeps_a_row_whose_ratio_has_no_two_parts(self):
        """A percentage stock dividend ('5%') keeps its row and published ratio."""
        query = NasdaqCalendarSplitsFetcher.transform_query(WINDOW)
        rows = NasdaqCalendarSplitsFetcher.transform_data(
            query,
            [
                {"symbol": "AAA", "executionDate": "07/24/2026", "ratio": "1 : 10"},
                {"symbol": "BBB", "executionDate": "07/24/2026", "ratio": "1-for-10"},
                {"symbol": "CCC", "executionDate": "07/24/2026", "ratio": "5%"},
            ],
        )

        assert [
            (r.symbol, r.numerator, r.denominator, r.ratio_display) for r in rows
        ] == [
            ("AAA", 1.0, 10.0, "1 : 10"),
            ("BBB", None, None, "1-for-10"),
            ("CCC", None, None, "5%"),
        ]

    @pytest.mark.parametrize(
        ("ratio", "expected"),
        [
            ("1 : 10", (1.0, 10.0)),
            ("16 : 1", (16.0, 1.0)),
            ("no ratio", (None, None)),
            ("1 : 0", (None, None)),
            (42, (None, None)),
            (None, (None, None)),
        ],
    )
    def test_split_ratio(self, ratio, expected):
        """A display ratio decomposes into its two parts."""
        assert _split_ratio(ratio) == expected

    def test_empty_raises(self, monkeypatch):
        """A day with no splits is reported."""
        patch_data(monkeypatch, {})
        query = NasdaqCalendarSplitsFetcher.transform_query(WINDOW)

        with pytest.raises(EmptyDataError, match="No stock splits"):
            asyncio.run(NasdaqCalendarSplitsFetcher.aextract_data(query, None))


class TestCalendarIpo:
    """Cover the IPO calendar."""

    @staticmethod
    def _row():
        """Return one priced offering."""
        return {
            "proposedTickerSymbol": "ABC",
            "companyName": "ABC Inc.",
            "proposedExchange": "NASDAQ",
            "dealID": "123",
            "pricedDate": "07/24/2026",
            "proposedSharePrice": "20.00",
            "sharesOffered": "1,000,000",
            "dollarValueOfSharesOffered": "$20,000,000",
            "dealStatus": "Priced",
        }

    def test_transforms_a_priced_offering(self, monkeypatch):
        """A priced offering resolves every column."""
        patch_data(monkeypatch, {"priced": {"rows": [self._row()]}})
        query = NasdaqCalendarIpoFetcher.transform_query(WINDOW)
        raw = asyncio.run(NasdaqCalendarIpoFetcher.aextract_data(query, None))
        rows = NasdaqCalendarIpoFetcher.transform_data(query, raw)

        assert rows[0].symbol == "ABC"
        assert rows[0].ipo_date == date(2026, 7, 24)
        assert rows[0].share_count == 1000000
        assert rows[0].offer_amount == pytest.approx(20000000)

    def test_upcoming_uses_its_own_table(self, monkeypatch):
        """The upcoming status reads the nested upcoming table."""
        patch_data(
            monkeypatch,
            {
                "upcoming": {
                    "upcomingTable": {
                        "rows": [
                            {
                                "proposedTickerSymbol": "NEW",
                                "expectedPriceDate": "08/01/2026",
                            }
                        ]
                    }
                }
            },
        )
        query = NasdaqCalendarIpoFetcher.transform_query(
            {**WINDOW, "status": "upcoming"}
        )
        raw = asyncio.run(NasdaqCalendarIpoFetcher.aextract_data(query, None))
        rows = NasdaqCalendarIpoFetcher.transform_data(query, raw)

        assert rows[0].expected_price_date == date(2026, 8, 1)

    def test_spo_changes_the_path(self, monkeypatch):
        """The SPO flag switches the offering type."""
        seen: list[str] = []
        patch_data(monkeypatch, {"priced": {"rows": [self._row()]}}, seen)
        query = NasdaqCalendarIpoFetcher.transform_query({**WINDOW, "is_spo": True})
        asyncio.run(NasdaqCalendarIpoFetcher.aextract_data(query, None))

        assert "type=spo" in seen[0]

    def test_defaults_the_window(self):
        """The window defaults to the trailing three hundred days."""
        query = NasdaqCalendarIpoFetcher.transform_query({})

        assert (query.end_date - query.start_date).days == 300

    def test_empty_raises(self):
        """A window with no offerings is reported."""
        query = NasdaqCalendarIpoFetcher.transform_query(WINDOW)

        with pytest.raises(EmptyDataError, match="offerings"):
            NasdaqCalendarIpoFetcher.transform_data(query, [])


class TestEconomicCalendar:
    """Cover the economic calendar."""

    def test_transforms_an_event(self, monkeypatch):
        """The GMT column becomes a timestamp."""
        patch_data(
            monkeypatch,
            {
                "rows": [
                    {
                        "gmt": "08:30",
                        "country": "United States",
                        "eventName": "Initial Jobless Claims",
                        "actual": "220K",
                        "consensus": "225K",
                        "previous": "230K",
                        "description": "Weekly claims.",
                    },
                    {
                        "gmt": "All Day",
                        "country": "Japan",
                        "eventName": "Holiday",
                    },
                ]
            },
        )
        query = NasdaqEconomicCalendarFetcher.transform_query(WINDOW)
        raw = asyncio.run(NasdaqEconomicCalendarFetcher.aextract_data(query, None))
        rows = NasdaqEconomicCalendarFetcher.transform_data(query, raw)

        assert len(rows) == 2
        assert rows[0].country in {"United States", "Japan"}

    def test_skips_weekends(self, monkeypatch):
        """A window of only weekend days requests nothing and reports empty."""
        seen: list[str] = []
        patch_data(monkeypatch, {"rows": []}, seen)
        query = NasdaqEconomicCalendarFetcher.transform_query(
            {"start_date": date(2026, 7, 25), "end_date": date(2026, 7, 26)}
        )

        with pytest.raises(OpenBBError, match="returned empty"):
            asyncio.run(NasdaqEconomicCalendarFetcher.aextract_data(query, None))

        assert seen == []

    def test_filters_by_country(self, monkeypatch):
        """The country filter narrows the published events."""
        patch_data(
            monkeypatch,
            {
                "rows": [
                    {"gmt": "08:30", "country": "United States", "eventName": "Claims"},
                    {"gmt": "09:00", "country": "Japan", "eventName": "CPI"},
                ]
            },
        )
        query = NasdaqEconomicCalendarFetcher.transform_query(
            {**WINDOW, "country": "united_states"}
        )
        raw = asyncio.run(NasdaqEconomicCalendarFetcher.aextract_data(query, None))

        assert [r["country"] for r in raw] == ["United States"]

    def test_first_failure_propagates(self, monkeypatch):
        """A failure with nothing collected yet is surfaced."""

        async def _data(path, **kwargs):
            raise OpenBBError("upstream")

        monkeypatch.setattr("openbb_nasdaq.utils.helpers.get_nasdaq_data", _data)
        query = NasdaqEconomicCalendarFetcher.transform_query(WINDOW)

        with pytest.raises(OpenBBError):
            asyncio.run(NasdaqEconomicCalendarFetcher.aextract_data(query, None))


class TestSearchModels:
    """Cover the ETF and index screeners."""

    def test_etf_search(self, monkeypatch):
        """The ETF screener filters and transforms."""
        seen: list[str] = []
        patch_data(
            monkeypatch,
            {
                "records": {
                    "data": {
                        "rows": [
                            {
                                "symbol": "QQQ",
                                "companyName": "Invesco QQQ",
                                "lastSalePrice": "$684.23",
                                "percentageChange": "-1.12%",
                                "oneYearPercentage": "+20.00%",
                            },
                            {"symbol": None},
                        ]
                    }
                }
            },
            seen,
        )
        query = NasdaqEtfSearchFetcher.transform_query({"sector": "biotech"})
        raw = asyncio.run(NasdaqEtfSearchFetcher.aextract_data(query, None))
        rows = NasdaqEtfSearchFetcher.transform_data(query, raw)

        assert "sector=" in seen[0]
        assert len(rows) == 1
        assert rows[0].one_year_percent == pytest.approx(0.2)

    def test_etf_search_narrows_by_query(self, monkeypatch):
        """A free-text query narrows the screener output."""
        query = NasdaqEtfSearchFetcher.transform_query({"query": "invesco"})
        rows = NasdaqEtfSearchFetcher.transform_data(
            query,
            [
                {"symbol": "QQQ", "companyName": "Invesco QQQ"},
                {"symbol": "SPY", "companyName": "SPDR"},
            ],
        )

        assert [r.symbol for r in rows] == ["QQQ"]

    def test_etf_search_empty_raises(self, monkeypatch):
        """No matching funds is reported."""
        patch_data(monkeypatch, {})
        query = NasdaqEtfSearchFetcher.transform_query({})

        with pytest.raises(EmptyDataError, match="No ETFs"):
            asyncio.run(NasdaqEtfSearchFetcher.aextract_data(query, None))

    def test_etf_search_paginates_a_capped_listing(self, monkeypatch):
        """A response capped below the total record count is paged to completion."""
        seen: list[str] = []

        def _payload(path):
            if "offset=0" in path:
                return {
                    "records": {
                        "totalrecords": 3,
                        "limit": 2,
                        "data": {
                            "rows": [
                                {"symbol": "AAA", "companyName": "Fund A"},
                                {"symbol": "BBB", "companyName": "Fund B"},
                            ]
                        },
                    }
                }

            return {
                "records": {
                    "totalrecords": 3,
                    "limit": 2,
                    "data": {"rows": [{"symbol": "CCC", "companyName": "Fund C"}]},
                }
            }

        patch_data(monkeypatch, _payload, seen)
        query = NasdaqEtfSearchFetcher.transform_query({})
        raw = asyncio.run(NasdaqEtfSearchFetcher.aextract_data(query, None))

        assert {row["symbol"] for row in raw} == {"AAA", "BBB", "CCC"}
        assert any("offset=2" in path for path in seen)

    def test_etf_search_gives_up_on_a_refused_page(self, monkeypatch):
        """A page that never answers is dropped rather than retried forever."""

        def _payload(path):
            if "offset=0" in path:
                return {
                    "records": {
                        "totalrecords": 4,
                        "limit": 2,
                        "data": {
                            "rows": [
                                {"symbol": "AAA", "companyName": "Fund A"},
                                {"symbol": "BBB", "companyName": "Fund B"},
                            ]
                        },
                    }
                }

            raise OSError("refused")

        patch_data(monkeypatch, _payload)
        monkeypatch.setattr("openbb_nasdaq.models.etf_search._RETRY_BACKOFF", 0)
        query = NasdaqEtfSearchFetcher.transform_query({})
        raw = asyncio.run(NasdaqEtfSearchFetcher.aextract_data(query, None))

        assert {row["symbol"] for row in raw} == {"AAA", "BBB"}

    def test_index_search(self, monkeypatch):
        """The index screener filters and transforms."""
        seen: list[str] = []
        patch_data(
            monkeypatch,
            {
                "records": {
                    "data": {
                        "rows": [
                            {
                                "symbol": "COMP",
                                "companyName": "NASDAQ Composite",
                                "lastSalePrice": "24,975.82",
                                "netChange": "-161.87",
                                "percentageChange": "-0.64%",
                            }
                        ]
                    }
                }
            },
            seen,
        )
        query = NasdaqIndexSearchFetcher.transform_query({"index_type": "us"})
        raw = asyncio.run(NasdaqIndexSearchFetcher.aextract_data(query, None))
        rows = NasdaqIndexSearchFetcher.transform_data(query, raw)

        assert "indextype=US" in seen[0]
        assert rows[0].change_percent == pytest.approx(-0.0064)

    def test_index_search_narrows_by_query(self):
        """A free-text query matches the symbol or the name."""
        rows = NasdaqIndexSearchFetcher.transform_data(
            NasdaqIndexSearchFetcher.transform_query({"query": "composite"}),
            [
                {"symbol": "COMP", "companyName": "NASDAQ Composite"},
                {"symbol": "NDX", "companyName": "NASDAQ-100"},
            ],
        )

        assert [r.symbol for r in rows] == ["COMP"]

    def test_index_search_by_symbol(self):
        """A symbol-only query matches the ticker."""
        rows = NasdaqIndexSearchFetcher.transform_data(
            NasdaqIndexSearchFetcher.transform_query(
                {"query": "ndx", "is_symbol": True}
            ),
            [
                {"symbol": "COMP", "companyName": "NASDAQ Composite"},
                {"symbol": "NDX", "companyName": "NASDAQ-100"},
            ],
        )

        assert [r.symbol for r in rows] == ["NDX"]

    def test_index_search_empty_raises(self, monkeypatch):
        """No matching indexes is reported."""
        patch_data(monkeypatch, {})
        query = NasdaqIndexSearchFetcher.transform_query({})

        with pytest.raises(EmptyDataError, match="No indexes"):
            asyncio.run(NasdaqIndexSearchFetcher.aextract_data(query, None))


class TestCompanyFilings:
    """Cover the SEC filings model."""

    def test_requires_a_symbol(self):
        """A filings request without a symbol is refused."""
        query = NasdaqCompanyFilingsFetcher.transform_query({"symbol": ""})

        with pytest.raises(OpenBBError, match="Symbol field is required"):
            NasdaqCompanyFilingsFetcher.extract_data(query, None)

    def test_transforms_rows(self):
        """The view links are flattened onto each filing."""
        query = NasdaqCompanyFilingsFetcher.transform_query({"symbol": "AAPL"})
        rows = NasdaqCompanyFilingsFetcher.transform_data(
            query,
            {
                "rows": [
                    {
                        "companyName": "Apple Inc.",
                        "reportType": "8-K",
                        "filed": "07/24/2026",
                        "period": "07/24/2026",
                        "view": {"htmlLink": "https://x/a.html"},
                    }
                ]
            },
        )

        assert rows[0].report_type == "8-K"
        assert rows[0].report_url == "https://x/a.html"

    def test_falls_back_to_latest(self):
        """A payload with only the latest block still yields filings."""
        query = NasdaqCompanyFilingsFetcher.transform_query({"symbol": "AAPL"})
        rows = NasdaqCompanyFilingsFetcher.transform_data(
            query,
            {
                "rows": [],
                "latest": [
                    {
                        "label": "8-K",
                        "value": "https://x/a.pdf?dateFiled=2026-07-24",
                    }
                ],
            },
        )

        assert rows[0].report_type == "8-K"
        assert rows[0].filing_date == date(2026, 7, 24)


class TestCalendarDefaults:
    """Cover the default windows each calendar applies."""

    @pytest.mark.parametrize(
        ("fetcher", "back", "forward"),
        [
            (NasdaqCalendarDividendFetcher, 0, 3),
            (NasdaqCalendarEarningsFetcher, 0, 3),
            (NasdaqEconomicCalendarFetcher, 2, 3),
        ],
        ids=["dividend", "earnings", "economic"],
    )
    def test_default_window(self, fetcher, back, forward):
        """Each calendar defaults to its own window around today."""
        from datetime import datetime, timedelta

        today = datetime.today().date()
        query = fetcher.transform_query({})

        assert query.start_date == today - timedelta(days=back)
        assert query.end_date == today + timedelta(days=forward)

    def test_splits_default_window(self):
        """The splits calendar defaults to the next thirty days."""
        from datetime import datetime, timedelta

        today = datetime.today().date()
        query = NasdaqCalendarSplitsFetcher.transform_query({})

        assert query.start_date == today
        assert query.end_date == today + timedelta(days=30)


class TestEarningsSurprisePercent:
    """Cover the earnings surprise percent validator."""

    def test_normalizes_and_blanks(self):
        """A published percent is normalized and N/A becomes None."""
        from openbb_nasdaq.models.calendar_earnings import NasdaqCalendarEarningsData

        validator = NasdaqCalendarEarningsData.__pydantic_validator__

        assert NasdaqCalendarEarningsData.model_validate(
            {
                "report_date": date(2026, 7, 24),
                "symbol": "AAPL",
                "surprise_percent": "7.14",
            }
        ).surprise_percent == pytest.approx(0.0714)
        assert (
            NasdaqCalendarEarningsData.model_validate(
                {
                    "report_date": date(2026, 7, 24),
                    "symbol": "AAPL",
                    "surprise_percent": "N/A",
                }
            ).surprise_percent
            is None
        )
        assert validator is not None


class TestEconomicCountryNames:
    """Cover the economic calendar country normalization."""

    def test_normalizes_known_and_unknown(self):
        """Known countries map through the Country type; others pass through."""
        query = NasdaqEconomicCalendarFetcher.transform_query(
            {**WINDOW, "country": "united_states,atlantis"}
        )

        assert "united_states" in query.country
        assert "atlantis" in query.country


class TestCompanyFilingsRequest:
    """Cover the SEC filings request and its pagination."""

    class _Response:
        """A canned requests response."""

        def __init__(self, payload, status=200, reason="OK"):
            self._payload = payload
            self.status_code = status
            self.reason = reason

        def json(self):
            """Return the payload."""
            return self._payload

    @staticmethod
    def _session(monkeypatch, responses, recorder):
        """Point the filings request at a sequence of canned responses."""

        class _Session:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url, **kwargs):
                recorder.append(url)

                return responses[min(len(recorder) - 1, len(responses) - 1)]

        def _open_session():
            """Return the canned session."""
            return _Session()

        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.get_requests_session", _open_session
        )

    def test_paginates_until_complete(self, monkeypatch):
        """Pages are requested until the total record count is met."""
        seen: list[str] = []
        self._session(
            monkeypatch,
            [
                self._Response(
                    {"data": {"rows": [{"reportType": "8-K"}], "totalRecords": "2"}}
                ),
                self._Response(
                    {"data": {"rows": [{"reportType": "10-K"}], "totalRecords": "2"}}
                ),
            ],
            seen,
        )
        query = NasdaqCompanyFilingsFetcher.transform_query({"symbol": "AAPL"})
        data = NasdaqCompanyFilingsFetcher.extract_data(query, None)

        assert len(seen) == 2
        assert "offset=1" in seen[1]
        assert len(data["rows"]) == 2

    def test_stops_on_an_empty_page(self, monkeypatch):
        """Pagination stops when a page returns nothing."""
        seen: list[str] = []
        self._session(
            monkeypatch,
            [
                self._Response(
                    {"data": {"rows": [{"reportType": "8-K"}], "totalRecords": "5"}}
                ),
                self._Response({"data": {"rows": [], "totalRecords": "5"}}),
            ],
            seen,
        )
        query = NasdaqCompanyFilingsFetcher.transform_query({"symbol": "AAPL"})
        data = NasdaqCompanyFilingsFetcher.extract_data(query, None)

        assert len(data["rows"]) == 1

    def test_reports_a_bad_status(self, monkeypatch):
        """A non-200 response is reported."""
        seen: list[str] = []
        self._session(
            monkeypatch, [self._Response({}, status=403, reason="Forbidden")], seen
        )
        query = NasdaqCompanyFilingsFetcher.transform_query({"symbol": "AAPL"})

        with pytest.raises(OpenBBError, match="403"):
            NasdaqCompanyFilingsFetcher.extract_data(query, None)

    def test_reports_no_filings(self, monkeypatch):
        """A symbol with no filings for the year is reported."""
        seen: list[str] = []
        self._session(
            monkeypatch,
            [self._Response({"data": {"rows": [], "totalRecords": "0"}})],
            seen,
        )
        query = NasdaqCompanyFilingsFetcher.transform_query(
            {"symbol": "AAPL", "year": 2026}
        )

        with pytest.raises(OpenBBError, match="No data found"):
            NasdaqCompanyFilingsFetcher.extract_data(query, None)

    def test_retries_a_read_timeout(self, monkeypatch):
        """A read timeout is retried once before it is reported."""
        from requests.exceptions import ReadTimeout

        attempts: list[int] = []

        class _Session:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url, **kwargs):
                attempts.append(1)
                raise ReadTimeout("timed out")

        def _open_session():
            """Return the canned session."""
            return _Session()

        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.get_requests_session", _open_session
        )
        monkeypatch.setattr("time.sleep", lambda seconds: None)
        query = NasdaqCompanyFilingsFetcher.transform_query({"symbol": "AAPL"})

        with pytest.raises(OpenBBError):
            NasdaqCompanyFilingsFetcher.extract_data(query, None)

        assert len(attempts) == 2


class TestRemainingBranches:
    """Cover the guards each model applies to sparse upstream data."""

    def test_economic_country_passthrough(self):
        """A country already in Nasdaq's snake-case form is kept as given."""
        query = NasdaqEconomicCalendarFetcher.transform_query(
            {**WINDOW, "country": "united_states"}
        )

        assert query.country == "united_states"

    def test_economic_later_failure_is_swallowed(self, monkeypatch):
        """A failure after data is collected does not sink the request."""
        calls: list[str] = []

        async def _data(path, **kwargs):
            calls.append(path)

            if len(calls) == 1:
                return {
                    "rows": [
                        {"gmt": "08:30", "country": "United States", "eventName": "X"}
                    ]
                }

            raise OpenBBError("upstream")

        monkeypatch.setattr("openbb_nasdaq.utils.helpers.get_nasdaq_data", _data)
        query = NasdaqEconomicCalendarFetcher.transform_query(
            {"start_date": date(2026, 7, 27), "end_date": date(2026, 7, 28)}
        )
        raw = asyncio.run(NasdaqEconomicCalendarFetcher.aextract_data(query, None))

        assert len(raw) == 1

    def test_filings_reports_a_bad_paginated_status(self, monkeypatch):
        """A non-200 on a later page is reported."""

        class _Response:
            def __init__(self, payload, status=200, reason="OK"):
                self._payload = payload
                self.status_code = status
                self.reason = reason

            def json(self):
                """Return the payload."""
                return self._payload

        pages = [
            _Response({"data": {"rows": [{"reportType": "8-K"}], "totalRecords": "2"}}),
            _Response({}, status=500, reason="Server Error"),
        ]
        calls: list[int] = []

        class _Session:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url, **kwargs):
                calls.append(1)

                return pages[min(len(calls) - 1, len(pages) - 1)]

        def _open_session():
            """Return the canned session."""
            return _Session()

        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.get_requests_session", _open_session
        )
        query = NasdaqCompanyFilingsFetcher.transform_query({"symbol": "AAPL"})

        with pytest.raises(OpenBBError, match="500"):
            NasdaqCompanyFilingsFetcher.extract_data(query, None)

    def test_filings_reports_an_empty_result_set(self, monkeypatch):
        """A page count that never yields rows is reported."""

        class _Response:
            status_code = 200
            reason = "OK"

            def json(self):
                """Return a payload whose rows vanish after the count."""
                return {"data": {"rows": [], "totalRecords": "1"}}

        class _Session:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url, **kwargs):
                return _Response()

        def _open_session():
            """Return the canned session."""
            return _Session()

        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.get_requests_session", _open_session
        )
        query = NasdaqCompanyFilingsFetcher.transform_query({"symbol": "AAPL"})

        with pytest.raises(OpenBBError, match="No reports"):
            NasdaqCompanyFilingsFetcher.extract_data(query, None)

    def test_economic_country_none_passes_through(self):
        """An explicitly unset country is left as None."""
        from openbb_nasdaq.models.economic_calendar import (
            NasdaqEconomicCalendarQueryParams,
        )

        assert NasdaqEconomicCalendarQueryParams(**WINDOW, country=None).country is None
