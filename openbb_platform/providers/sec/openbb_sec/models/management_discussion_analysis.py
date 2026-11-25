"""SEC Management & Discussion Model."""

# flake8: noqa: PLR0912, PLR0914

from datetime import date
from typing import Any, cast

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.management_discussion_analysis import (
    ManagementDiscussionAnalysisData,
    ManagementDiscussionAnalysisQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field


class SecManagementDiscussionAnalysisQueryParams(
    ManagementDiscussionAnalysisQueryParams
):
    """SEC Management & Discussion Query."""

    __json_schema_extra__ = {
        "symbol": {
            "x-widget_config": {
                "type": "endpoint",
                "optionsEndpoint": "/api/v1/sec/companies",
                "searchable": True,
                "style": {"popupWidth": 950},
                "description": "Pick a company with standardized SEC"
                " financials (ranked by market cap).",
            },
        },
        "calendar_year": {
            "x-widget_config": {
                "type": "endpoint",
                "optionsEndpoint": "/api/v1/sec/filing_options",
                "optionsParams": {"symbol": "$symbol"},
            },
        },
    }

    include_tables: bool = Field(
        default=True,
        description="Return tables formatted as markdown in the text. Default is True.",
    )
    use_cache: bool = Field(
        default=True,
        description="When True, the file will be cached for use later. Default is True.",
    )
    raw_html: bool = Field(
        default=False,
        description="When True, the raw HTML content of the entire filing will be returned. Default is False."
        + " Use this option to parse the document manually.",
    )


class SecManagementDiscussionAnalysisData(ManagementDiscussionAnalysisData):
    """SEC Management & Discussion Data."""

    url: str = Field(
        description="The URL of the filing from which the data was extracted."
    )


def _mda_from_full_text(url: str, use_cache: bool) -> str:
    """Read Item 7 (MD&A) from a filing's full-submission text.

    Old SGML filings (pre-HTML) have no locatable HTML section anchor, so the
    HTML parser cannot find the MD&A; the plain-text item extractor reads it
    from the full submission instead. Returns "" on any failure.
    """
    try:
        from openbb_sec.models.sec_financials import FinancialStatements

        item = FinancialStatements.from_url(url, use_cache).get_item("7")
    except Exception:  # noqa: BLE001
        return ""
    return (item.get("text") or "").strip() if item else ""


class SecManagementDiscussionAnalysisFetcher(
    Fetcher[
        SecManagementDiscussionAnalysisQueryParams, SecManagementDiscussionAnalysisData
    ]
):
    """SEC Management & Discussion Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> SecManagementDiscussionAnalysisQueryParams:
        """Transform the query."""
        return SecManagementDiscussionAnalysisQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: SecManagementDiscussionAnalysisQueryParams,
        credentials: dict[str, Any] | None,
        **kwargs: Any,
    ) -> dict:
        """Extract the data."""
        import re

        from pandas import offsets, to_datetime

        from openbb_sec.models.company_filings import (
            SecCompanyFilingsData,
            SecCompanyFilingsFetcher,
        )
        from openbb_sec.utils.cache import cached_request
        from openbb_sec.utils.helpers import SEC_HEADERS, sec_callback

        async def _fetch_filings(params: dict[str, Any]) -> list[SecCompanyFilingsData]:
            """Fetch company filings, always as a concrete list of filing models."""
            return cast(
                "list[SecCompanyFilingsData]",
                await SecCompanyFilingsFetcher.fetch_data(params, {}),
            )

        def _extract_exhibit_links(
            index_html: str, type_prefix: str = "EX-99"
        ) -> list[str]:
            """Parse a filing index page and return hrefs for rows
            whose Type cell starts with *type_prefix* (e.g. ``EX-99``).

            The SEC filing-index table has columns:
            Seq | Description | Document (with <a href>) | Type | Size
            The TYPE label (e.g. ``EX-99.1``) lives in the cell text,
            *not* in the href URL, so we must parse the table rows.
            """
            _row_re = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
            results: list[str] = []
            for rm in _row_re.finditer(index_html):
                cells = re.findall(r"<td[^>]*>(.*?)</td>", rm.group(1), re.I | re.S)
                if len(cells) < 4:
                    continue
                # Type is column index 3.
                _type = re.sub(r"<[^>]+>", "", cells[3]).strip()
                if not _type.upper().startswith(type_prefix.upper()):
                    continue
                # Document column (index 2) has the <a href>.
                _href_m = re.search(r'<a\b[^>]*href="([^"]+)"', cells[2], re.I)
                if not _href_m:
                    continue
                href = _href_m.group(1)
                # Strip XBRL inline viewer prefix.
                _ix = re.match(r"/ix\?doc=(/.+)", href)
                if _ix:
                    href = _ix.group(1)
                results.append(href)
            return results

        # Get the company filings to find the URL.
        # Domestic issuers file 10-K (annual) / 10-Q (quarterly).
        # Foreign private issuers file 40-F or 20-F (annual) and
        # 6-K (current/quarterly).  Search for all applicable forms
        # and let the most-recent-filing logic pick the right one.

        _form_types = "10-K,10-Q,40-F,20-F"

        if (
            query.symbol == "BLK" and query.calendar_year and query.calendar_year < 2025
        ) or query.symbol.isnumeric():
            filings = await _fetch_filings(
                {
                    "cik": "0001364742" if query.symbol == "BLK" else query.symbol,
                    "form_type": _form_types,
                    "use_cache": query.use_cache,
                }
            )

        else:
            filings = await _fetch_filings(
                {
                    "symbol": query.symbol,
                    "form_type": _form_types,
                    "use_cache": query.use_cache,
                }
            )

        if not filings:
            raise OpenBBError(
                f"Could not find any 10-K, 10-Q, 40-F, or 20-F filings for the symbol. -> {query.symbol}"
            )

        # If no calendar year or period is provided, get the most recent filing.

        target_filing: Any = None
        calendar_year: Any = None
        calendar_period: Any = None

        _is_foreign_issuer = any(
            f.report_type in ("40-F", "20-F", "40-F/A", "20-F/A") for f in filings
        )

        if query.calendar_year is None and query.calendar_period is None:
            target_filing = filings[0]
            # For foreign issuers the most-recent 10-K/10-Q/40-F/20-F
            # may be older than a 6-K that contains quarterly MD&A.
            # Check whether a newer 6-K with an MD&A exhibit exists.
            if target_filing and _is_foreign_issuer:
                _6k_recent = await _fetch_filings(
                    {
                        "symbol": query.symbol if not query.symbol.isnumeric() else "",
                        "cik": query.symbol if query.symbol.isnumeric() else "",
                        "form_type": "6-K",
                        "use_cache": query.use_cache,
                    }
                )
                if _6k_recent and _6k_recent[0].filing_date > target_filing.filing_date:
                    # A more-recent 6-K exists.  Scan its index for
                    # an EX-99 exhibit with MD&A content.
                    _mda_re = re.compile(r"(?:mda|md&a|quarterly|discussion)", re.I)
                    for _6kf in _6k_recent:
                        if _6kf.filing_date <= target_filing.filing_date:
                            break  # older than current pick; stop
                        _idx_url = cast("str", _6kf.filing_detail_url)
                        try:
                            _idx_html = await cached_request(
                                _idx_url,
                                headers=SEC_HEADERS,
                                response_callback=sec_callback,
                                use_cache=query.use_cache,
                            )
                        except Exception:  # noqa
                            continue
                        if not isinstance(_idx_html, str):
                            continue
                        _ex99_hrefs = _extract_exhibit_links(_idx_html, "EX-99")
                        for _href in _ex99_hrefs:
                            _fname = _href.rsplit("/", 1)[-1]
                            if _mda_re.search(_fname):
                                target_filing = _6kf
                                break
                        if target_filing.report_type == "6-K":
                            break

                    # Second pass: filenames didn't match.  Read the
                    # 6-K cover page for exhibit descriptions like
                    # "Q4 2025 Update", "Letter to Shareholders", etc.
                    if target_filing.report_type != "6-K":
                        _cover_re = re.compile(
                            r"Q[1-4]\s+\d{4}\s+Update|"
                            r"Letter\s+to\s+Shareholders|"
                            r"Shareholder\s+Letter|"
                            r"Earnings\s+(?:Release|Update)|"
                            r"Quarterly\s+(?:Report|Update|Results)",
                            re.IGNORECASE,
                        )
                        for _6kf in _6k_recent:
                            if _6kf.filing_date <= target_filing.filing_date:
                                break
                            try:
                                _cover_url = _6kf.report_url
                                _cover_html = await cached_request(
                                    _cover_url,
                                    headers=SEC_HEADERS,
                                    response_callback=sec_callback,
                                    use_cache=query.use_cache,
                                )
                            except Exception:  # noqa
                                continue
                            if isinstance(_cover_html, str) and _cover_re.search(
                                _cover_html
                            ):
                                target_filing = _6kf
                                break

            # Domestic issuer: check for a more-recent 8-K that
            # contains earnings results (EX-99 exhibit) filed after
            # the latest 10-K/10-Q.  This covers the gap between
            # the earnings announcement and the formal 10-K/Q filing.
            if target_filing and not _is_foreign_issuer:
                _8k_recent = await _fetch_filings(
                    {
                        "symbol": query.symbol if not query.symbol.isnumeric() else "",
                        "cik": query.symbol if query.symbol.isnumeric() else "",
                        "form_type": "8-K",
                        "use_cache": query.use_cache,
                    }
                )
                if _8k_recent and _8k_recent[0].filing_date > target_filing.filing_date:
                    # Item 2.02 = "Results of Operations and Financial
                    # Condition" — the standard 8-K item for earnings.
                    _8k_earnings_re = re.compile(
                        r"Item\s+2\.02|"
                        r"Results\s+of\s+Operations\s+and\s+Financial\s+Condition|"
                        r"Earnings\s+(?:Release|Press\s+Release|Update)|"
                        r"Financial\s+Results|"
                        r"Press\s+Release.*(?:Quarter|Annual|Fiscal)",
                        re.IGNORECASE,
                    )
                    for _8kf in _8k_recent:
                        if _8kf.filing_date <= target_filing.filing_date:
                            break  # older than current 10-K/Q; stop
                        # Check filing index for EX-99 exhibits.
                        _idx_url = cast("str", _8kf.filing_detail_url)
                        try:
                            _idx_html = await cached_request(
                                _idx_url,
                                headers=SEC_HEADERS,
                                response_callback=sec_callback,
                                use_cache=query.use_cache,
                            )
                        except Exception:  # noqa
                            continue
                        if not isinstance(_idx_html, str):
                            continue
                        _ex99_hrefs = _extract_exhibit_links(_idx_html, "EX-99")
                        if not _ex99_hrefs:
                            continue
                        # Read the 8-K filing for Item 2.02 or
                        # earnings-related language.
                        try:
                            _cover_url = _8kf.report_url
                            _cover_html = await cached_request(
                                _cover_url,
                                headers=SEC_HEADERS,
                                response_callback=sec_callback,
                                use_cache=query.use_cache,
                            )
                        except Exception:  # noqa
                            continue
                        if isinstance(_cover_html, str) and _8k_earnings_re.search(
                            _cover_html
                        ):
                            target_filing = _8kf
                            break

        if not target_filing:
            if query.calendar_period and not query.calendar_year:
                calendar_year = to_datetime("today").year
                calendar_period = to_datetime("today").quarter
            elif query.calendar_year and query.calendar_period:
                calendar_year = query.calendar_year
                calendar_period = int(query.calendar_period[1])
            elif query.calendar_year:
                calendar_year = query.calendar_year
                calendar_period = 1

            if query.calendar_year and not query.calendar_period:
                _matches = [
                    f
                    for f in filings
                    if f.report_type
                    in (
                        "10-K",
                        "40-F",
                        "20-F",
                        "40-F/A",
                        "20-F/A",
                    )
                    and f.filing_date.year == query.calendar_year
                ]
                if not _matches:
                    _matches = [
                        f for f in filings if f.filing_date.year == query.calendar_year
                    ]
                if _matches:
                    target_filing = _matches[0]

            elif calendar_year and calendar_period:
                start = to_datetime(
                    f"{calendar_year}-{3 * int(calendar_period) - 2:02d}-01"
                )
                start_date = (
                    start - offsets.QuarterBegin(1) + offsets.MonthBegin(1)
                ).date()
                end_date = (
                    to_datetime(start_date)
                    + offsets.QuarterEnd(0)
                    - offsets.MonthEnd(0)
                ).date()

                for filing in filings:
                    if start_date < filing.filing_date < end_date:
                        target_filing = filing
                        break

        # For foreign private issuer quarterly reports (6-K), the filing
        # list above only covers 10-K/10-Q/40-F/20-F.  When no match
        # was found for a specific quarter AND the issuer files foreign
        # forms, search 6-K filings for a quarterly report instead.
        #
        # Foreign issuers file many 6-Ks (press releases, certifications,
        # etc.).  Only a few contain quarterly results.  Strategy:
        #   1. Collect 6-Ks in the target date range.
        #   2. For each candidate, check the filing index page for an
        #      EX-99 exhibit whose filename suggests MD&A content
        #      (e.g. contains "mda", "md&a", or "quarterly").
        #   3. If none match by filename, fall back to the first 6-K
        #      whose EX-99 exhibit HTML contains "Discussion and Analysis".

        if (
            not target_filing
            and _is_foreign_issuer
            and calendar_year
            and calendar_period
        ):
            _6k_filings = await _fetch_filings(
                {
                    "symbol": query.symbol if not query.symbol.isnumeric() else "",
                    "cik": query.symbol if query.symbol.isnumeric() else "",
                    "form_type": "6-K",
                    "use_cache": query.use_cache,
                }
            )
            if _6k_filings:
                start = to_datetime(
                    f"{calendar_year}-{3 * int(calendar_period) - 2:02d}-01"
                )
                _6k_start_date = (
                    start - offsets.QuarterBegin(1) + offsets.MonthBegin(1)
                ).date()
                _6k_end_date = (start + offsets.QuarterEnd(0)).date()

                _candidates = [
                    f
                    for f in _6k_filings
                    if _6k_start_date <= f.filing_date <= _6k_end_date
                ]

                # Try each candidate's filing index for an MD&A exhibit.
                _mda_fname_re = re.compile(
                    r"(?:mda|md&a|quarterly|discussion)", re.IGNORECASE
                )

                async def _fetch_6k(u: str) -> str | None:
                    try:
                        return await cached_request(
                            u,
                            headers=SEC_HEADERS,
                            response_callback=sec_callback,
                            use_cache=query.use_cache,
                        )
                    except Exception:  # noqa
                        return None

                _6k_with_ex99: list[Any] = []
                for _6kf in _candidates:
                    _idx_url = cast("str", _6kf.filing_detail_url)
                    _idx_html = await _fetch_6k(_idx_url)
                    if not isinstance(_idx_html, str):
                        continue
                    # Parse the filing index table for EX-99
                    # exhibit links (using the Type cell, not the
                    # href URL which may not contain 'ex99').
                    _ex99_hrefs = _extract_exhibit_links(_idx_html, "EX-99")
                    for _href in _ex99_hrefs:
                        _fname = _href.rsplit("/", 1)[-1]
                        if _mda_fname_re.search(_fname):
                            target_filing = _6kf
                            break
                    if target_filing:
                        break
                    if _ex99_hrefs:
                        _6k_with_ex99.append(_6kf)

                # Second pass: filename didn't match but the 6-K has
                # EX-99 exhibits.  Read the actual 6-K cover page —
                # it describes the exhibits (e.g. "Q4 2025 Update",
                # "Letter to Shareholders", "Earnings Release").
                if not target_filing and _6k_with_ex99:
                    _cover_desc_re = re.compile(
                        r"Q[1-4]\s+\d{4}\s+Update|"
                        r"Letter\s+to\s+Shareholders|"
                        r"Shareholder\s+Letter|"
                        r"Earnings\s+(?:Release|Update)|"
                        r"Quarterly\s+(?:Report|Update|Results)",
                        re.IGNORECASE,
                    )
                    for _6kf in _6k_with_ex99:
                        _cover_html = await _fetch_6k(_6kf.report_url)
                        if isinstance(_cover_html, str) and _cover_desc_re.search(
                            _cover_html
                        ):
                            target_filing = _6kf
                            break

        # Domestic issuer 8-K fallback: when no 10-K/10-Q has been
        # filed yet for the requested quarter, the company may have
        # already published earnings via an 8-K press release (EX-99
        # exhibit).  Search 8-K filings in the target date range for
        # an earnings announcement.
        if (
            not target_filing
            and not _is_foreign_issuer
            and calendar_year
            and calendar_period
        ):
            _8k_filings = await _fetch_filings(
                {
                    "symbol": query.symbol if not query.symbol.isnumeric() else "",
                    "cik": query.symbol if query.symbol.isnumeric() else "",
                    "form_type": "8-K",
                    "use_cache": query.use_cache,
                }
            )
            if _8k_filings:
                start = to_datetime(
                    f"{calendar_year}-{3 * int(calendar_period) - 2:02d}-01"
                )
                _8k_start_date = (
                    start - offsets.QuarterBegin(1) + offsets.MonthBegin(1)
                ).date()
                _8k_end_date = (start + offsets.QuarterEnd(0)).date()

                _8k_candidates = [
                    f
                    for f in _8k_filings
                    if _8k_start_date <= f.filing_date <= _8k_end_date
                ]

                async def _fetch_8k(u: str) -> str | None:
                    try:
                        return await cached_request(
                            u,
                            headers=SEC_HEADERS,
                            response_callback=sec_callback,
                            use_cache=query.use_cache,
                        )
                    except Exception:  # noqa
                        return None

                _earnings_desc_re = re.compile(
                    r"Q[1-4]\s+\d{4}\s+(?:Update|Results|Earnings)|"
                    r"Earnings\s+(?:Release|Press\s+Release|Update)|"
                    r"Press\s+Release|"
                    r"Quarterly\s+(?:Report|Update|Results)|"
                    r"(?:Financial|Operating)\s+Results|"
                    r"Results\s+(?:of|for)\s+Operations",
                    re.IGNORECASE,
                )

                for _8kf in _8k_candidates:
                    _idx_url = cast("str", _8kf.filing_detail_url)
                    _idx_html = await _fetch_8k(_idx_url)
                    if not isinstance(_idx_html, str):
                        continue
                    _ex99_hrefs = _extract_exhibit_links(_idx_html, "EX-99")
                    if not _ex99_hrefs:
                        continue
                    # Read the 8-K cover page for earnings description.
                    _cover_html = await _fetch_8k(_8kf.report_url)
                    if isinstance(_cover_html, str) and _earnings_desc_re.search(
                        _cover_html
                    ):
                        target_filing = _8kf
                        break

        if not target_filing:
            raise OpenBBError(
                f"Could not find a filing for the symbol -> {query.symbol}"
            )

        target_filing = cast("SecCompanyFilingsData", target_filing)
        url = target_filing.report_url
        response = ""

        response = await cached_request(
            url,
            headers=SEC_HEADERS,
            response_callback=sec_callback,
            use_cache=query.use_cache,
        )

        # Some 10-K filings have a stub Item 7 that simply
        # cross-references the Annual Report to Stockholders filed as
        # Exhibit 13.  When we detect this pattern we pre-fetch the
        # exhibit so that transform_data can extract MD&A from it.
        exhibit_content: str | None = None
        exhibit_url: str | None = None
        _exhibit_is_full_document: bool = False
        _index_url: str | None = None
        _index_html: Any = None

        if isinstance(response, str) and re.search(
            r"incorporated\s+(?:herein\s+by\s+reference|by\s+reference\s+herein)",
            response,
            re.IGNORECASE,
        ):
            _base_dir = url.rsplit("/", 1)[0]

            # Strategy 1: look for an inline exhibit link in the HTML
            # (modern filings embed <a href="...">Annual Report to
            # Security Holders</a>).
            _ar_re = re.compile(
                r'<a\b[^>]*href="([^"]+)"[^>]*>[^<]*'
                r"Annual\s+Report\s+to\s+(?:Security|Stock|Share)\s*[Hh]olders"
                r"[^<]*</a>",
                re.IGNORECASE,
            )
            _m = _ar_re.search(response)

            # Strategy 2: fall back to the filing index page and look for
            # the EX-13 exhibit document (older filings).
            if not _m:
                _index_url = cast("str", target_filing.filing_detail_url)
                try:
                    _index_html = await cached_request(
                        _index_url,
                        headers=SEC_HEADERS,
                        response_callback=sec_callback,
                        use_cache=query.use_cache,
                    )
                    if isinstance(_index_html, str):
                        # Parse the filing index table for EX-13 rows.
                        _ex13_hrefs = _extract_exhibit_links(_index_html, "EX-13")
                        if _ex13_hrefs:
                            _href = _ex13_hrefs[0]
                            # Index page links are usually absolute paths
                            if _href.startswith("http"):
                                _m_url = _href
                            elif _href.startswith("/"):
                                _m_url = "https://www.sec.gov" + _href
                            else:
                                _m_url = _base_dir + "/" + _href

                            # Wrap in a fake match-like object
                            class _FakeMatch:
                                def group(self, n):
                                    return _m_url if n == 1 else ""

                            _m = _FakeMatch()
                except Exception:  # noqa
                    pass  # Index page unavailable; proceed without exhibit

            if _m:
                _href = _m.group(1)
                _exhibit_url: str = (
                    _href if _href.startswith("http") else _base_dir + "/" + _href
                )
                exhibit_url = _exhibit_url
                exhibit_content = await cached_request(
                    _exhibit_url,
                    headers=SEC_HEADERS,
                    response_callback=sec_callback,
                    use_cache=query.use_cache,
                )

        # Foreign private issuer filings (40-F / 20-F) typically do not
        # contain an inline MD&A section.  Instead, the MD&A is filed as
        # a separate exhibit (usually EX-99.2).  When we detect a foreign
        # filing, browse the filing index page for EX-99 exhibit links,
        # fetch each candidate, and use the first one that contains
        # "Discussion and Analysis" text.
        #
        # The same logic applies to domestic 8-K earnings releases:
        # the actual content lives in an EX-99 exhibit.
        _has_exhibit_content = target_filing.report_type in (
            "40-F",
            "20-F",
            "40-F/A",
            "20-F/A",
            "6-K",
            "8-K",
        )

        if isinstance(response, str) and _has_exhibit_content and not exhibit_content:
            _base_dir = url.rsplit("/", 1)[0]
            _index_url = cast("str", target_filing.filing_detail_url)

            async def _fetch(u: str) -> str | None:
                """Fetch a URL using cache settings."""
                try:
                    return await cached_request(
                        u,
                        headers=SEC_HEADERS,
                        response_callback=sec_callback,
                        use_cache=query.use_cache,
                    )
                except Exception:  # noqa
                    return None

            _index_html = await _fetch(_index_url)

            if isinstance(_index_html, str):
                # Parse the filing index table for EX-99 exhibit
                # links using the Type cell (the href URL itself
                # may not contain 'ex99' in the filename).
                _raw_hrefs = _extract_exhibit_links(_index_html, "EX-99")
                _ex99_links: list[str] = []
                for _href99 in _raw_hrefs:
                    if _href99.startswith("http"):
                        _abs99 = _href99
                    elif _href99.startswith("/"):
                        _abs99 = "https://www.sec.gov" + _href99
                    else:
                        _abs99 = _base_dir + "/" + _href99
                    if _abs99 not in _ex99_links:
                        _ex99_links.append(_abs99)

                # Fetch each exhibit and remember the HTML so we can
                # do a multi-pass match without re-downloading.
                _fetched_exhibits: list[tuple[str, str]] = []
                for _ex_url in _ex99_links:
                    _ex_html = await _fetch(_ex_url)
                    if isinstance(_ex_html, str):
                        _fetched_exhibits.append((_ex_url, _ex_html))

                # Two-pass approach: strong patterns first, weak
                # fallback second.  "MD&A" appears in many exhibits
                # (e.g. Annual Information Forms that merely mention
                # the abbreviation) so we must prefer exhibits whose
                # HTML contains the full section title.
                #
                # Pass 1 – strong: full "Management's Discussion and
                # Analysis" or "Operating and Financial Review" title.
                for _ex_url, _ex_html in _fetched_exhibits:
                    if re.search(
                        r"(?:Management|MANAGEMENT).{0,10}"
                        r"(?:Discussion|DISCUSSION)\s+and\s+"
                        r"(?:Analysis|ANALYSIS)",
                        _ex_html,
                    ) or re.search(
                        r"(?:Operating|OPERATING)\s+and\s+Financial\s+Review",
                        _ex_html,
                    ):
                        exhibit_content = _ex_html
                        exhibit_url = _ex_url
                        break

                # Pass 2 – weak fallback: "MD&A" abbreviation.
                if not exhibit_content:
                    for _ex_url, _ex_html in _fetched_exhibits:
                        if re.search(r"MD&amp;A", _ex_html):
                            exhibit_content = _ex_html
                            exhibit_url = _ex_url
                            break

                # Pass 3 – 6-K / 8-K presentation slide deck or
                # shareholder update.  When both MD&A passes fail,
                # the exhibit may be a slide deck or quarterly update
                # that does NOT contain a dedicated MD&A section.
                # Read the cover page for exhibit descriptions and
                # check the exhibit HTML for slide-deck structure.
                if (
                    not exhibit_content
                    and target_filing.report_type in ("6-K", "8-K")
                    and _fetched_exhibits
                ):
                    # (a) Slide-deck HTML fingerprint:
                    #     <div class="slide"> wrapping <img> tags.
                    for _ex_url, _ex_html in _fetched_exhibits:
                        if re.search(r'<div\b[^>]*\bclass="slide"', _ex_html, re.I):
                            exhibit_content = _ex_html
                            exhibit_url = _ex_url
                            _exhibit_is_full_document = True
                            break

                    # (b) The cover page describes the exhibit
                    #     (e.g. "Q4 2025 Update", "Letter to
                    #     Shareholders", "Earnings Release").
                    if not exhibit_content and isinstance(response, str):
                        _quarterly_desc_re = re.compile(
                            r"Q[1-4]\s+\d{4}\s+Update|"
                            r"Letter\s+to\s+Shareholders|"
                            r"Shareholder\s+Letter|"
                            r"Earnings\s+(?:Release|Update)|"
                            r"Quarterly\s+(?:Report|Update|Results)|"
                            r"Press\s+Release|"
                            r"Financial\s+Results|"
                            r"Results\s+of\s+Operations",
                            re.IGNORECASE,
                        )
                        if _quarterly_desc_re.search(response):
                            _ex_url, _ex_html = _fetched_exhibits[0]
                            exhibit_content = _ex_html
                            exhibit_url = _ex_url
                            _exhibit_is_full_document = True

                # 8-K filings often split content across multiple
                # EX-99 exhibits (e.g. EX-99.1 = press release,
                # EX-99.2 = infographics / supplemental data).
                # Combine all fetched exhibits into one HTML blob so
                # the downstream converter gets the full picture.
                if (
                    exhibit_content
                    and target_filing.report_type == "8-K"
                    and len(_fetched_exhibits) > 1
                ):
                    _extra_parts: list[str] = []
                    for _ex_url, _ex_html in _fetched_exhibits:
                        if _ex_html is not exhibit_content:
                            _extra_parts.append(_ex_html)
                    if _extra_parts:
                        # Wrap each extra exhibit so the converter
                        # treats them as separate sections.
                        for _part in _extra_parts:
                            exhibit_content += "\n<!-- additional exhibit -->\n" + _part

        if isinstance(response, str):
            _report_date = cast("date", target_filing.report_date)
            result: dict[str, Any] = {
                "symbol": query.symbol,
                "calendar_year": (
                    calendar_year if calendar_year else _report_date.year
                ),
                "calendar_period": (
                    calendar_period
                    if calendar_period
                    else to_datetime(_report_date).quarter
                ),
                "period_ending": _report_date,
                "report_type": target_filing.report_type,
                "url": url,
                "content": response,
            }
            if exhibit_content and exhibit_url:
                result["exhibit_content"] = exhibit_content
                result["exhibit_url"] = exhibit_url
                if _exhibit_is_full_document:
                    result["exhibit_is_full_document"] = True
            return result

        raise OpenBBError(
            f"Unexpected response received. Expected string and got -> {response.__class__.__name__} -> {response[:100]}"
        )

    @staticmethod
    def transform_data(
        query: SecManagementDiscussionAnalysisQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> SecManagementDiscussionAnalysisData:
        """Transform the data."""
        import re

        from openbb_sec.utils.html2markdown import html_to_markdown

        if query.raw_html is True:
            return SecManagementDiscussionAnalysisData(**data)

        filing_html = data.get("content", "")
        base_url = data.get("url", "")
        report_type = data.get("report_type", "")
        is_quarterly = report_type.endswith("Q")
        is_20f = report_type in ("20-F", "20-F/A")

        # Convert the full HTML filing to markdown.
        markdown = html_to_markdown(
            filing_html,
            base_url=base_url,
            keep_tables=query.include_tables,
        )

        if not markdown:
            raise EmptyDataError(
                "No content was found in the filing after HTML-to-Markdown conversion."
                f" -> {data.get('url', '')}"
                " -> The content can be analyzed by setting"
                " `raw_html=True` in the query."
            )

        # Strip leftover HTML anchor tags that the converter may leave
        # (e.g. <a id="item_2_management"></a>).  These interfere with
        # line-start-anchored regex matching.
        markdown = re.sub(r"<a\s[^>]*>\s*</a>", "", markdown)
        # Strip leading "Table of Contents" breadcrumb links that XBRL
        # authoring tools (e.g. Workiva) insert at the start of every
        # section.  These are internal markdown links like
        #   [Table of Contents](#hash)
        # or split variants like [Tab](#hash)[le of Contents](#hash).
        # They prevent ^-anchored regex patterns from matching Item
        # headers reliably.
        markdown = re.sub(
            r"^(?:\[[^\]]*\]\(#[^)]*\)\s*)+", "", markdown, flags=re.MULTILINE
        )

        def _normalize_toc_table(md: str) -> str:
            """Normalize a mangled Table of Contents markdown table.

            Foreign-filer exhibits (and some domestic filings) include a
            TOC rendered as an HTML table with colspan-driven multi-
            column layouts.  The converter produces markdown rows with
            varying column counts (4–7 cells per row).  This helper
            detects the TOC table and re-builds it as a clean 4-column
            table:  Page | Section | Page | Section.
            """
            _toc_hdr = re.compile(
                r"^\|[^\n]*Table\s+of\s+Contents[^\n]*\|",
                re.MULTILINE,
            )
            m = _toc_hdr.search(md)
            if not m:
                return md

            # Locate the full table block.
            toc_start = md.rfind("\n", 0, m.start())
            toc_start = toc_start + 1 if toc_start >= 0 else m.start()
            # Advance past the header line's trailing newline.
            toc_end = m.end()
            first_nl = md.find("\n", toc_end)
            if first_nl >= 0:
                toc_end = first_nl + 1
            while toc_end < len(md):
                nl = md.find("\n", toc_end)
                if nl < 0:
                    toc_end = len(md)
                    break
                next_line = md[toc_end:nl].strip()
                if next_line.startswith("|"):
                    toc_end = nl + 1
                else:
                    toc_end = nl
                    break

            toc_block = md[toc_start:toc_end]
            _link_re = re.compile(r"\[([^\]]*)\]\((#[^)]*)\)")

            new_rows: list[tuple[str, str, str, str]] = []
            for _toc_row in toc_block.splitlines():
                _toc_row = _toc_row.strip()
                if not _toc_row.startswith("|") or _toc_row.startswith("|---"):
                    continue
                cells = [c.strip() for c in _toc_row.strip("|").split("|")]
                if any("Table of Contents" in c for c in cells):
                    continue

                # Pair up (page_link, section_name) from non-empty cells.
                non_empty = [(i, c) for i, c in enumerate(cells) if c]
                pairs: list[tuple[str, str]] = []
                j = 0
                while j < len(non_empty):
                    _, val = non_empty[j]
                    if _link_re.match(val) or val.isdigit():
                        sect = non_empty[j + 1][1] if j + 1 < len(non_empty) else ""
                        pairs.append((val, sect))
                        j += 2
                    else:
                        pairs.append(("", val))
                        j += 1

                if len(pairs) == 1:
                    new_rows.append((pairs[0][0], pairs[0][1], "", ""))
                elif len(pairs) >= 2:
                    new_rows.append(
                        (pairs[0][0], pairs[0][1], pairs[1][0], pairs[1][1])
                    )

            if not new_rows:
                return md

            toc_lines = ["| Table of Contents | | | |", "|---|---|---|---|"]
            for p1, s1, p2, s2 in new_rows:
                toc_lines.append(f"| {p1} | {s1} | {p2} | {s2} |")
            toc_lines.append("")
            return md[:toc_start] + "\n".join(toc_lines) + md[toc_end:]

        markdown = _normalize_toc_table(markdown)

        lines = markdown.splitlines()
        # Matches an Item 7 / Item 2 header for MD&A (the formal SEC item).
        item_header_re = re.compile(
            r"^(?:#{1,4}\s*)?(?:\*{1,2})?\s*"
            r"(?:Part\s+(?:I{1,2}|1|2)[\.\s,\-\u2013\u2014]*\s*)?"
            r"(?:ITEM|Item)\s*(?:7|2)"
            r"[\.\s\-\u2013\u2014:]*"
            r"(?:Management.s|MANAGEMENT.S)\s+Discussion",
            re.IGNORECASE,
        )
        # When we see a bare Item header we check the next non-blank line for the
        # MD&A title.
        bare_item_re = re.compile(
            r"^(?:#{1,4}\s*)?(?:\*{1,2})?\s*"
            r"(?:Part\s+(?:I{1,2}|1|2)[\.\s,\-\u2013\u2014]*\s*)?"
            r"(?:ITEM|Item)\s*(?:7|2)"
            r"\s*[\.\-\u2013\u2014:]*\s*$",
            re.IGNORECASE,
        )
        mda_title_re = re.compile(
            r"^(?:#{1,4}\s*)?(?:\*{1,2})?\s*"
            r"(?:Management.s|MANAGEMENT.S)\s+Discussion",
            re.IGNORECASE,
        )

        standalone_mda_re = re.compile(
            r"^(?:#{1,4}\s*)?\*{0,2}\s*"
            r"(?:Management.s|MANAGEMENT.S)\s+Discussion\s+and\s+Analysis",
            re.IGNORECASE,
        )

        # -- 20-F: Item 5 "Operating and Financial Review and Prospects" --
        # Foreign private issuers filing on Form 20-F use Item 5 instead
        # of Item 7 for the MD&A-equivalent section.
        item5_header_re = re.compile(
            r"^(?:#{1,4}\s*)?(?:\*{1,2})?\s*"
            r"(?:Part\s+(?:I{1,2}|1|2)[\.\s,\-\u2013\u2014]*\s*)?"
            r"(?:ITEM|Item)\s*5"
            r"[\.\s\-\u2013\u2014:]*"
            r"(?:Operating|OPERATING)\s+and\s+Financial\s+Review",
            re.IGNORECASE,
        )
        bare_item5_re = re.compile(
            r"^(?:#{1,4}\s*)?(?:\*{1,2})?\s*"
            r"(?:Part\s+(?:I{1,2}|1|2)[\.\s,\-\u2013\u2014]*\s*)?"
            r"(?:ITEM|Item)\s*5"
            r"\s*[\.\-\u2013\u2014:]*\s*$",
            re.IGNORECASE,
        )
        item5_title_re = re.compile(
            r"^(?:#{1,4}\s*)?(?:\*{1,2})?\s*"
            r"(?:Operating|OPERATING)\s+and\s+Financial\s+Review",
            re.IGNORECASE,
        )
        standalone_item5_re = re.compile(
            r"^(?:#{1,4}\s*)?\*{0,2}\s*"
            r"(?:Operating|OPERATING)\s+and\s+Financial\s+Review"
            r"\s+and\s+Prospects",
            re.IGNORECASE,
        )

        # Any Item header (to detect section boundaries).
        any_item_re = re.compile(
            r"^(?:#{1,4}\s*)?\*{0,2}\s*" + r"(?:ITEM|Item)\s*\d",
            re.IGNORECASE,
        )

        # End-of-section patterns.
        end_patterns_quarterly = [
            re.compile(
                r"^(?:#{1,4}\s*)?\*{0,2}\s*"
                r"(?:ITEM|Item)\s*(?:3|4)"
                r"[.\s\-\u2013\u2014:]",
                re.IGNORECASE,
            ),
            re.compile(
                r"^(?:#{1,4}\s*)?\*{0,2}\s*SIGNATURES",
                re.IGNORECASE,
            ),
        ]

        end_patterns_annual = [
            re.compile(
                r"^(?:#{1,4}\s*)?\*{0,2}\s*"
                r"(?:ITEM|Item)\s*(?:7A|8)"
                r"[.\s\-\u2013\u2014:]",
                re.IGNORECASE,
            ),
            re.compile(
                r"^(?:#{1,4}\s*)?\*{0,2}\s*"
                r"(?:Financial\s+Statements\s+and\s+Supplementary\s+Data"
                r"|FINANCIAL\s+STATEMENTS)",
                re.IGNORECASE,
            ),
            re.compile(
                r"^(?:#{1,4}\s*)?\*{0,2}\s*SIGNATURES",
                re.IGNORECASE,
            ),
            re.compile(
                r"^(?:#{1,4}\s*)?\*{0,2}\s*PART\s+IV",
                re.IGNORECASE,
            ),
        ]

        # 20-F end patterns: Item 6 ("Directors, Senior Management …"),
        # SIGNATURES, or PART III/IV mark the end of Item 5.
        end_patterns_20f = [
            re.compile(
                r"^(?:#{1,4}\s*)?\*{0,2}\s*"
                r"(?:ITEM|Item)\s*(?:6)"
                r"[.\s\-\u2013\u2014:]",
                re.IGNORECASE,
            ),
            re.compile(
                r"^(?:#{1,4}\s*)?\*{0,2}\s*SIGNATURES",
                re.IGNORECASE,
            ),
            re.compile(
                r"^(?:#{1,4}\s*)?\*{0,2}\s*PART\s+(?:III|IV)",
                re.IGNORECASE,
            ),
        ]

        if is_20f:
            end_patterns = end_patterns_20f
        elif is_quarterly:
            end_patterns = end_patterns_quarterly
        else:
            end_patterns = end_patterns_annual

        # Select active header patterns based on filing type.
        # 20-F uses Item 5 / "Operating and Financial Review";
        # 10-K / 10-Q use Item 7/2 / "Management's Discussion".
        if is_20f:
            _active_header_re = item5_header_re
            _active_bare_re = bare_item5_re
            _active_title_re = item5_title_re
            _active_standalone_re = standalone_item5_re
        else:
            _active_header_re = item_header_re
            _active_bare_re = bare_item_re
            _active_title_re = mda_title_re
            _active_standalone_re = standalone_mda_re

        def _find_end(start: int) -> int:
            """Find the end line index for a section starting at *start*."""
            body_lines = 0
            for j in range(start + 1, len(lines)):
                stripped = lines[j].strip()
                if not stripped:
                    continue
                body_lines += 1
                if body_lines > 15:
                    for pat in end_patterns:
                        if pat.search(stripped):
                            return j
            return len(lines)

        def _is_stub(start: int) -> bool:
            """Return True if the section at *start* is a stub / cross-ref.

            A stub is a very short section (< 500 chars of body text) that
            either contains a cross-reference phrase or is immediately
            followed by another Item header with no real body content.
            """
            # Gather text until the next Item header or end of document.
            body_chars: list[str] = []
            for j in range(start + 1, min(start + 30, len(lines))):
                stripped = lines[j].strip()

                if not stripped:
                    continue
                # Hit another Item header → the section between is the body.

                if any_item_re.match(stripped):
                    break

                body_chars.append(stripped)

            body_text = " ".join(body_chars)
            # If the body is substantial, it's not a stub.
            if len(body_text) > 500:
                return False
            # Short body — check for cross-reference language.
            crossref_re = re.compile(
                r"see\s+(?:the\s+)?(?:information|discussion)|"
                r"(?:is|are)\s+(?:presented|included|incorporated)\s+(?:in|by)|"
                r"incorporated\s+herein\s+by\s+reference|"
                r"(?:refer|refers)\s+to\s+(?:Item|Part|the\s+section|pages?\s+\d)|"
                r"included\s+(?:elsewhere|herein|in\s+(?:Part|Item))|"
                r"set\s+forth\s+(?:in|under|below)|"
                r"appears?\s+on\s+page|"
                r"begins?\s+on\s+page|"
                r"found\s+(?:on|in)\s+(?:page|section)|"
                r"(?:should|must)\s+be\s+read\s+in\s+conjunction|"
                r"contained\s+(?:in|on)\s+page|"
                r"(?:is|are)\s+(?:set\s+forth|described|discussed)\s+(?:in|on|under)",
                re.IGNORECASE,
            )
            if crossref_re.search(body_text):
                return True
            # Very short body with no cross-ref — still a stub if nearly empty.
            return len(body_text) < 100

        # -- main extraction --------------------------------------------------

        # Strategy:
        #  1. Find all Item header matches (Item 7/2 for 10-K/Q,
        #     Item 5 for 20-F).
        #  2. For each, check body length to determine stub vs real.
        #  3. If all are stubs, fall back to standalone heading.

        best_start: int | None = None
        best_end: int | None = None
        _stub_anchor_id: str | None = None

        for i, line in enumerate(lines):
            stripped = line.strip()

            if not stripped:
                continue

            if _active_header_re.search(stripped):
                if _is_stub(i):
                    # Check for an internal anchor link pointing to
                    # the actual MD&A content elsewhere in the same
                    # filing (e.g., in a "Financial Section").
                    if not _stub_anchor_id:
                        _am = re.search(r"\[[^\]]*\]\(#([^)]+)\)", stripped)
                        if not _am:
                            for k in range(i + 1, min(i + 5, len(lines))):
                                ks = lines[k].strip()
                                if ks:
                                    _am = re.search(
                                        r"\[[^\]]*\]\(#([^)]+)\)",
                                        ks,
                                    )
                                    break
                        if _am:
                            _stub_anchor_id = _am.group(1)
                    continue
                best_start = i
                best_end = _find_end(i)
                break
            # Handle split headers: "Item 2." on one line, MD&A title on next.
            if _active_bare_re.search(stripped):
                # Look at the next non-blank line for the section title.
                for k in range(i + 1, min(i + 4, len(lines))):
                    next_stripped = lines[k].strip()

                    if not next_stripped:
                        continue

                    if _active_title_re.search(next_stripped) and not _is_stub(i):
                        best_start = i
                        best_end = _find_end(i)
                    break  # Only check up to the first non-blank line

                if best_start is not None:
                    break

        # Fallback: standalone section heading without Item number.
        if best_start is None:
            for i, line in enumerate(lines):
                stripped = line.strip()

                if not stripped:
                    continue

                if _active_standalone_re.search(stripped) and not _is_stub(i):
                    candidate_end = _find_end(i)
                    body = "\n".join(lines[i:candidate_end]).strip()

                    if len(body) > 200:
                        best_start = i
                        best_end = candidate_end
                        break

        # -- Internal cross-reference extraction --
        # Some filings (e.g., Chevron, ExxonMobil 10-K) place the full
        # MD&A in a "Financial Section" appended to the same document.
        # The formal Item 7 is a one-line stub such as:
        #   "Reference is made to [MD&A title](#anchor) in the
        #    Financial Section of this report."
        # Follow the embedded anchor link directly to the referenced
        # section in the raw HTML, extract it, and convert it.
        #
        # When a stub anchor is available the anchor-based extraction
        # always takes priority.  The main markdown-level extraction
        # may also find a ``best_start`` inside the Financial Section,
        # but ``_find_end()`` cannot reliably determine the section
        # boundary because the Financial Section uses its own heading
        # structure (no Item 7A / Item 8 headers).  The anchor-based
        # path reads the Table of Contents that precedes the Financial
        # Section and uses its anchor IDs to cut precisely.

        if _stub_anchor_id:
            _anchor_tag = f'id="{_stub_anchor_id}"'
            _anchor_pos = filing_html.find(_anchor_tag)
            if _anchor_pos >= 0:
                # Skip past the closing '>' of the anchor element.
                _gt = filing_html.find(">", _anchor_pos)
                _start = _gt + 1 if _gt >= 0 else _anchor_pos
                _remainder = filing_html[_start:]

                # ── Locate the end of the MD&A section ──────────────
                # The remainder begins with a Financial Table of
                # Contents whose <a href="#anchor"> links enumerate
                # every section.  Parse those links and find the first
                # anchor whose title indicates a post-MD&A section
                # (financial statements, auditor reports, etc.).
                # Cutting at the target anchor's ``id="…"`` attribute
                # is far more reliable than regex-matching section
                # titles in raw HTML (which may appear inside TOC
                # links, cross-references, etc.).

                _href_re = re.compile(
                    r'href="#([^"]+)"[^>]*>(.*?)</a>',
                    re.DOTALL | re.IGNORECASE,
                )
                _post_mda_pats = [
                    re.compile(
                        r"Consolidated\s+Financial\s+Statements",
                        re.IGNORECASE,
                    ),
                    re.compile(r"Reports?\s+of\s+Management", re.IGNORECASE),
                    re.compile(
                        r"Report\s+of\s+Independent\s+Registered",
                        re.IGNORECASE,
                    ),
                    re.compile(
                        r"To\s+the\s+(?:Stockholders|Shareholders" + r"|Board)",
                        re.IGNORECASE,
                    ),
                    re.compile(
                        r"Financial\s+Statements\s+and\s+" + r"Supplementary",
                        re.IGNORECASE,
                    ),
                    re.compile(
                        r"Changes\s+in\s+and\s+Disagreements",
                        re.IGNORECASE,
                    ),
                ]

                # Scan the TOC area (first ~80 KB should be enough).
                _toc_chunk = _remainder[:80_000]
                _end_anchor_id: str | None = None
                _start_anchor_id: str | None = None
                _seen_toc: set[str] = set()

                # Pattern to detect the MD&A section header in the TOC
                # so we can skip the TOC itself and start at the real
                # content.
                _mda_title_pat = re.compile(
                    r"Management.s\s+Discussion\s+and\s+Analysis",
                    re.IGNORECASE,
                )

                for _hm in _href_re.finditer(_toc_chunk):
                    _aid = _hm.group(1)
                    _raw = re.sub(r"<[^>]+>", " ", _hm.group(2))
                    _raw = re.sub(r"\s+", " ", _raw).strip()
                    for _ent, _ch in (
                        ("&#8217;", "\u2019"),
                        ("&#x2019;", "\u2019"),
                        ("&rsquo;", "\u2019"),
                        ("&#160;", " "),
                        ("&amp;", "&"),
                        ("&#8212;", "\u2014"),
                    ):
                        _raw = _raw.replace(_ent, _ch)
                    if len(_raw) < 4 or _aid in _seen_toc:
                        continue
                    _seen_toc.add(_aid)

                    # Track the first MD&A header anchor (to skip TOC).
                    if not _start_anchor_id and _mda_title_pat.search(_raw):
                        _start_anchor_id = _aid

                    for _pp in _post_mda_pats:
                        if _pp.search(_raw):
                            _end_anchor_id = _aid
                            break
                    if _end_anchor_id:
                        break

                # Determine HTML slice boundaries.
                # Back up to the opening '<' of the element that carries
                # the id attribute so we don't splice mid-tag and leak
                # raw attribute text into the markdown output.
                _html_start = 0
                if _start_anchor_id:
                    _start_tag = f'id="{_start_anchor_id}"'
                    _sp = _remainder.find(_start_tag)
                    if _sp > 0:
                        _lt = _remainder.rfind("<", 0, _sp)
                        _html_start = _lt if _lt >= 0 else _sp

                _cut = len(_remainder)
                if _end_anchor_id:
                    _end_tag = f'id="{_end_anchor_id}"'
                    _end_pos = _remainder.find(_end_tag)
                    if _end_pos > _html_start:
                        _cut = _end_pos

                _section_md = html_to_markdown(
                    f"<html><body>{_remainder[_html_start:_cut]}</body></html>",
                    base_url=base_url,
                    keep_tables=query.include_tables,
                )
                if _section_md and len(_section_md.strip()) > 500:
                    # Strip repeated running page headers that appear
                    # at the top of every page in the original filing
                    # (e.g., CVX 10-K: "Management's Discussion …
                    # [Financial Table of Contents](#anchor)").
                    _section_md = re.sub(
                        r"^Management.s\s+Discussion\s+and\s+Analysis"
                        r"\s+of\s+Financial\s+Condition\s+and\s+Results"
                        r"\s+of\s+Operations[^\n]*$\n?",
                        "",
                        _section_md,
                        flags=re.MULTILINE | re.IGNORECASE,
                    )
                    # Strip standalone "[Financial Table of Contents](#…)"
                    # or "[Table of Contents](#…)" breadcrumb lines.
                    _section_md = re.sub(
                        r"^\[(?:Financial\s+)?Table\s+of\s+Contents\]"
                        r"\(#[^)]+\)[^\n]*$\n?",
                        "",
                        _section_md,
                        flags=re.MULTILINE | re.IGNORECASE,
                    )
                    data["content"] = _section_md.strip()
                    return SecManagementDiscussionAnalysisData(**data)

        # -- Exhibit fallback: Annual Report / Foreign Filing Exhibits ---
        # When the main document only has a stub Item 7 (10-K) or is a
        # foreign private issuer filing (40-F / 20-F) whose MD&A lives
        # in a separately filed exhibit (EX-13 or EX-99.x),
        # aextract_data pre-fetched the exhibit HTML.

        if best_start is None and data.get("exhibit_content"):
            exhibit_base_url = data.get("exhibit_url", "")
            exhibit_md = html_to_markdown(
                data["exhibit_content"],
                base_url=exhibit_base_url,
                keep_tables=query.include_tables,
            )
            exhibit_md = re.sub(r"<a\s[^>]*>\s*</a>", "", exhibit_md)
            exhibit_md = re.sub(
                r"^(?:\[[^\]]*\]\(#[^)]*\)\s*)+",
                "",
                exhibit_md,
                flags=re.MULTILINE,
            )
            exhibit_md = _normalize_toc_table(exhibit_md)
            exhibit_lines = exhibit_md.splitlines()
            _exhibit_start_re = re.compile(
                r"^(?:#{1,4}\s*)?\*{0,2}\s*"
                r"(?:"
                r"(?:Management|MANAGEMENT).{0,3}s?\s+"
                r"(?:Discussion|DISCUSSION)"
                r"|(?:Operating|OPERATING)\s+and\s+Financial\s+Review"
                r")",
                re.IGNORECASE,
            )
            _exhibit_end_re = re.compile(
                r"^(?:#{1,4}\s*)?\*{0,2}\s*(?:"
                r"Management\s+Responsibility\s+for\s+Financial|"
                r"Management.s\s+Report\s+on\s+Internal\s+Control|"
                r"Report\s+of\s+(?:Management|Independent)|"
                r"Consolidated\s+(?:Balance\s+Sheet|Statement|Financial)|"
                r"Notes?\s+to\s+(?:Consolidated\s+)?Financial"
                r")",
                re.IGNORECASE,
            )

            for i, eline in enumerate(exhibit_lines):
                estripped = eline.strip()
                if not estripped or estripped.startswith("|"):
                    continue
                if _exhibit_start_re.search(estripped):
                    end = len(exhibit_lines)
                    body_count = 0
                    for j in range(i + 1, len(exhibit_lines)):
                        sj = exhibit_lines[j].strip()
                        if not sj:
                            continue
                        body_count += 1
                        if body_count > 15 and _exhibit_end_re.search(sj):
                            end = j
                            break
                    _content = "\n".join(exhibit_lines[i:end]).strip()
                    if len(_content) > 200:
                        data["content"] = _content
                        data["url"] = exhibit_base_url
                        return SecManagementDiscussionAnalysisData(**data)

            # Full-document fallback: 6-K presentation slide decks
            # and shareholder updates / earnings releases lack a
            # dedicated MD&A section.  Return the entire converted
            # exhibit content (with embedded markdown images).
            if (
                data.get("exhibit_is_full_document")
                and exhibit_md
                and len(exhibit_md.strip()) > 100
            ):
                data["content"] = exhibit_md.strip()
                data["url"] = exhibit_base_url
                return SecManagementDiscussionAnalysisData(**data)

        if best_start is None:
            fallback = _mda_from_full_text(data.get("url", ""), query.use_cache)
            if fallback:
                data["content"] = fallback
                return SecManagementDiscussionAnalysisData(**data)
            raise EmptyDataError(
                "Could not locate the MD&A section in the filing."
                f" -> {data.get('url', '')}"
                " -> The content can be analyzed by setting"
                " `raw_html=True` in the query."
            )

        if best_end is None:  # pragma: no cover - best_end is set with every best_start
            best_end = len(lines)

        mda_content = "\n".join(lines[best_start:best_end]).strip()

        # Strip repeated running page headers (see stub-path comment).
        mda_content = re.sub(
            r"^Management.s\s+Discussion\s+and\s+Analysis"
            r"\s+of\s+Financial\s+Condition\s+and\s+Results"
            r"\s+of\s+Operations[^\n]*$\n?",
            "",
            mda_content,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        # Strip standalone "[Financial Table of Contents](#…)" breadcrumb lines.
        mda_content = re.sub(
            r"^\[(?:Financial\s+)?Table\s+of\s+Contents\]" + r"\(#[^)]+\)[^\n]*$\n?",
            "",
            mda_content,
            flags=re.MULTILINE | re.IGNORECASE,
        )

        if not mda_content:
            raise EmptyDataError(
                "The MD&A section appears to be empty after extraction."
                f" -> {data.get('url', '')}"
                " -> The content can be analyzed by setting"
                " `raw_html=True` in the query."
            )

        # Ensure the section header has a markdown heading prefix and is
        # separated from any inline body text.  Many filings emit the
        # Item header as plain text (no <h1>/<h2> tag), so the converter
        # never inserts a '#' prefix.
        #
        # Detection strategy: ALL-CAPS words at the start of the content
        # form the section title (e.g. "ITEM 2. MANAGEMENT'S DISCUSSION
        # AND ANALYSIS …").  The title may span multiple lines; it ends
        # at the first word containing a lowercase letter.
        mda_heading_re = re.compile(
            r"^((?:Part\s+\S+[.\s,\-–—]*\s*)?Item\s+\d+\.?\s+"
            r"(?:Management.s\s+Discussion\s+and\s+Analysis"
            r"(?:\s+of\s+Financial\s+Condition\s+and\s+Results\s+of\s+Operations)?"
            r"|Operating\s+and\s+Financial\s+Review(?:\s+and\s+Prospects)?))",
            re.IGNORECASE,
        )
        mda_lines = mda_content.splitlines()
        if mda_lines:
            first = mda_lines[0].strip()
            if not first.startswith("#"):
                # Collect words from the opening lines, noting where the
                # first lowercase word appears (= end of ALL-CAPS title).
                all_words: list[str] = []
                lines_consumed = 0
                split_idx: int | None = None  # index of first lowercase word

                for i in range(min(len(mda_lines), 6)):
                    line = mda_lines[i].strip()
                    if not line:
                        lines_consumed = i + 1
                        break
                    for w in line.split():
                        if re.search(r"[a-z]", w) and split_idx is None:
                            split_idx = len(all_words)
                        all_words.append(w)
                    lines_consumed = i + 1
                    if split_idx is not None:
                        break

                if split_idx is not None:
                    title_text = " ".join(all_words[:split_idx])
                    body_text = " ".join(all_words[split_idx:])
                else:
                    title_text = " ".join(all_words)
                    body_text = ""

                is_caps_title = (
                    bool(title_text) and re.match(r"ITEM\s+\d", title_text) is not None
                )

                if is_caps_title:
                    new_lines = ["## " + title_text, ""]
                    if body_text:
                        new_lines.append(body_text)
                    mda_lines = new_lines + mda_lines[lines_consumed:]
                elif re.match(r"Item\s+\d", first, re.IGNORECASE):
                    heading_match = mda_heading_re.match(first)
                    heading = heading_match.group(1).strip() if heading_match else first
                    remainder = (
                        first[heading_match.end() :].strip() if heading_match else ""
                    )
                    new_lines = ["## " + heading, ""]
                    if remainder:
                        new_lines.append(remainder)
                    mda_lines = new_lines + mda_lines[1:]

                mda_content = "\n".join(mda_lines)

        data["content"] = mda_content

        return SecManagementDiscussionAnalysisData(**data)
