"""Unit tests for ``openbb_sec.models.sec_filing``."""

import asyncio
import types
from datetime import date
from io import BytesIO
from zipfile import ZipFile

import pytest
from openbb_core.app.model.abstract.error import OpenBBError

from openbb_sec.models.sec_filing import LazyDict, SecBaseFiling, SecFilingFetcher


def _run(coro):
    """Run an async coroutine from a sync test (no pytest-asyncio)."""
    return asyncio.run(coro)


def _async_return(value):
    """Build a zero-arg awaitable returning ``value``."""

    async def _inner(*args, **kwargs):
        return value

    return _inner


# Real SEC index-headers files HTML-escape the document tags, so they survive
# into the BeautifulSoup "pre" text as literal "<DOCUMENT>" markers.
_INDEX_HTML = (
    "<html><body><pre>\n"
    "COMPANY CONFORMED NAME: ACME CORP\n"
    "CENTRAL INDEX KEY: 0000317540\n"
    "STANDARD INDUSTRIAL CLASSIFICATION: BEVERAGES [2080]\n"
    "ORGANIZATION NAME: 04 Manufacturing\n"
    "FISCAL YEAR END: 1231\n"
    "CONFORMED SUBMISSION TYPE: 8-K\n"
    "CONFORMED PERIOD OF REPORT: 20240731\n"
    "FILED AS OF DATE: 20240805\n"
    "ITEM INFORMATION: Results of Operations\n"
    "ITEM INFORMATION: Financial Statements\n"
    "&lt;DOCUMENT&gt;\n"
    "&lt;TYPE&gt;8-K\n"
    "&lt;SEQUENCE&gt;1\n"
    "&lt;FILENAME&gt;coke-20240731.htm\n"
    "&lt;DESCRIPTION&gt;8-K\n"
    "&lt;/DOCUMENT&gt;\n"
    "&lt;DOCUMENT&gt;\n"
    "&lt;TYPE&gt;EX-99.1\n"
    "&lt;SEQUENCE&gt;2\n"
    "&lt;FILENAME&gt;R1.htm\n"
    "&lt;/DOCUMENT&gt;\n"
    "</pre></body></html>"
)

_FILING_URL = (
    "https://www.sec.gov/Archives/edgar/data/317540/000031754024000045/coke.htm"
)


class TestSecFilingHelpers:
    """Static helpers on SecBaseFiling."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Millions", 1_000_000),
            ("Hundreds of Thousands", 100_000),
            ("Tens of Thousands", 10_000),
            ("Thousands", 1_000),
            ("Hundreds", 100),
            ("Tens", 10),
            ("anything else", 1),
        ],
    )
    def test_multiplier_map(self, text, expected):
        assert SecBaseFiling._multiplier_map(text) == expected

    def test_try_html_table_success(self):
        html = "<table><tr><th>a</th></tr><tr><td>1</td></tr></table>"
        tables = SecBaseFiling.try_html_table(html)
        assert len(tables) == 1

    def test_try_html_table_no_table_raises(self):
        with pytest.raises(RuntimeError, match="Failed to parse table"):
            SecBaseFiling.try_html_table("no tables here")


class TestSecFilingInitValidation:
    """SecBaseFiling.__init__ URL validation branches."""

    def test_empty_url_raises(self):
        with pytest.raises(ValueError, match="Please enter a URL"):
            SecBaseFiling("")

    def test_url_without_data_segment_raises(self):
        with pytest.raises(ValueError, match="must be a filing URL"):
            SecBaseFiling("https://www.sec.gov/Archives/edgar/foo/bar/")

    def test_url_with_bad_accession_length_raises(self):
        with pytest.raises(ValueError, match="must be a filing URL"):
            SecBaseFiling(
                "https://www.sec.gov/Archives/edgar/data/317540/123/short.htm"
            )

    def test_url_with_invalid_scheme_raises(self):
        with pytest.raises(ValueError, match="http or https scheme"):
            SecBaseFiling(
                "ftp://www.sec.gov/Archives/edgar/data/317540/000031754024000045/x.htm"
            )

    def test_url_with_non_sec_host_raises(self):
        with pytest.raises(ValueError, match="host must be sec.gov"):
            SecBaseFiling(
                "https://evil.com/Archives/edgar/data/317540/000031754024000045/x.htm"
            )

    def test_url_with_lookalike_host_raises(self):
        with pytest.raises(ValueError, match="host must be sec.gov"):
            SecBaseFiling(
                "https://sec.gov.evil.com/Archives/edgar/data/317540/000031754024000045/x.htm"
            )

    def test_url_with_non_digit_accession_raises(self):
        with pytest.raises(ValueError, match="must be a filing URL"):
            SecBaseFiling(
                "https://www.sec.gov/Archives/edgar/data/317540/00003175402400004X/x.htm"
            )

    def test_url_with_missing_accession_segment_raises(self):
        with pytest.raises(ValueError, match="must be a filing URL"):
            SecBaseFiling("https://www.sec.gov/Archives/edgar/data/317540")


class TestSecFilingDownloadFile:
    """SecBaseFiling.download_file branches."""

    def test_adownload_file_delegates_to_cached_request(self, monkeypatch):
        captured: dict = {}

        async def fake_cached_request(url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return "payload"

        monkeypatch.setattr(
            "openbb_sec.utils.cache.cached_request", fake_cached_request
        )
        out = _run(
            SecBaseFiling._adownload_file("https://www.sec.gov/x.htm", use_cache=False)
        )
        assert out == "payload"
        assert captured["url"] == "https://www.sec.gov/x.htm"
        assert captured["kwargs"]["use_cache"] is False
        assert captured["kwargs"]["raise_for_status"] is True
        assert captured["kwargs"]["headers"]["Host"] == "www.sec.gov"
        assert "response_callback" in captured["kwargs"]

    def test_adownload_file_strips_host_for_xbrl_sec_gov(self, monkeypatch):
        from openbb_sec.utils import definitions

        captured: dict = {}

        async def fake_cached_request(url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return "payload"

        monkeypatch.setattr(
            "openbb_sec.utils.cache.cached_request", fake_cached_request
        )
        monkeypatch.setitem(
            definitions.SEC_HEADERS, "User-Agent", "Test Co test@co.com"
        )
        out = _run(
            SecBaseFiling._adownload_file(
                "https://xbrl.sec.gov/dei/2025/dei-2025_lab.xsd", use_cache=False
            )
        )
        assert out == "payload"
        assert "Host" not in captured["kwargs"]["headers"]
        assert captured["kwargs"]["headers"]["User-Agent"] == "Test Co test@co.com"

    def test_adownload_file_uses_headers_ua_fallback_for_non_sec_host(
        self, monkeypatch
    ):
        from openbb_sec.utils import definitions

        captured: dict = {}

        async def fake_cached_request(url, **kwargs):
            captured["kwargs"] = kwargs
            return "payload"

        monkeypatch.setattr(
            "openbb_sec.utils.cache.cached_request", fake_cached_request
        )
        monkeypatch.setitem(
            definitions.HEADERS, "User-Agent", "Headers Co headers@co.com"
        )
        _run(
            SecBaseFiling._adownload_file(
                "https://xbrl.sec.gov/country/2025/country-entire-2025.xsd",
                use_cache=False,
            )
        )
        assert "Host" not in captured["kwargs"]["headers"]
        assert (
            captured["kwargs"]["headers"]["User-Agent"] == "Headers Co headers@co.com"
        )

    def test_non_html_with_read_table_warns_and_returns(self, monkeypatch):
        monkeypatch.setattr(SecBaseFiling, "_adownload_file", _async_return("rawtext"))
        with pytest.warns(Warning, match="not a HTML file"):
            out = SecBaseFiling.download_file(
                "https://www.sec.gov/x.txt",
                read_html_table=True,
                use_cache=False,
            )
        assert out == "rawtext"

    def test_html_table_parsed(self, monkeypatch):
        monkeypatch.setattr(
            SecBaseFiling,
            "_adownload_file",
            _async_return("<table><tr><th>a</th></tr><tr><td>1</td></tr></table>"),
        )
        res = SecBaseFiling.download_file(
            "https://www.sec.gov/x.htm", read_html_table=True, use_cache=False
        )
        assert len(res) == 1

    def test_download_error_wrapped(self, monkeypatch):
        async def boom(*args, **kwargs):
            raise ValueError("kaboom")

        monkeypatch.setattr(SecBaseFiling, "_adownload_file", boom)
        with pytest.raises(RuntimeError, match="Failed to download file"):
            SecBaseFiling.download_file("https://www.sec.gov/x.htm", use_cache=False)

    def test_plain_download_returns_raw_response(self, monkeypatch):
        # read_html_table=False returns the raw downloaded payload untouched.
        monkeypatch.setattr(
            SecBaseFiling, "_adownload_file", _async_return("raw-bytes")
        )
        out = SecBaseFiling.download_file(
            "https://www.sec.gov/x.htm", read_html_table=False, use_cache=False
        )
        assert out == "raw-bytes"


class TestSecFilingIndexHeaders:
    """SecBaseFiling end-to-end with a synthetic index-headers document."""

    def test_index_headers_parsed_no_cover(self, monkeypatch):
        # No R1.htm-derived cover page is fetched because cik_map returns a
        # symbol up-front, but the second document IS an R1.htm. To isolate the
        # index-header parsing without the cover page, return index HTML for all
        # URLs and let the cover-page download fail gracefully.
        def fake_download_file(url, read_html_table=False, use_cache=True):
            if read_html_table:
                # Cover page request: return empty -> RuntimeError path is
                # caught inside _download_cover_page (re-raised as RuntimeError),
                # so instead give a minimal valid frame.
                import pandas

                return [pandas.DataFrame({0: ["Document Type"], 1: ["8-K"]})]
            return _INDEX_HTML

        monkeypatch.setattr(
            SecBaseFiling, "download_file", staticmethod(fake_download_file)
        )
        monkeypatch.setattr("openbb_sec.utils.helpers.cik_map", _async_return("KO"))
        f = SecBaseFiling(_FILING_URL, use_cache=False)
        assert f.base_url.endswith("/000031754024000045/")
        assert f.name == "ACME CORP"
        assert f.cik == "0000317540"
        assert f.sic == "BEVERAGES [2080]"
        assert f.sic_organization_name == "04 Manufacturing"
        assert f.filing_date == date(2024, 8, 5)
        assert f.period_ending == date(2024, 7, 31)
        assert f.fiscal_year_end == "12-31"
        assert f.document_type == "8-K"
        # Two ITEM INFORMATION lines are concatenated
        assert f.description == "Results of Operations; Financial Statements"
        assert len(f.document_urls) == 2
        # cik_map returned "KO" but the cover page also yields symbols; the
        # trading symbols list is populated.
        assert f.trading_symbols is not None

    def test_repr_lists_computed_fields(self, monkeypatch):
        def fake_download_file(url, read_html_table=False, use_cache=True):
            if read_html_table:
                import pandas

                return [pandas.DataFrame({0: ["Document Type"], 1: ["8-K"]})]
            return _INDEX_HTML

        monkeypatch.setattr(
            SecBaseFiling, "download_file", staticmethod(fake_download_file)
        )
        monkeypatch.setattr("openbb_sec.utils.helpers.cik_map", _async_return("KO"))
        f = SecBaseFiling(_FILING_URL, use_cache=False)
        # __repr__ reads ``model_computed_fields`` off the instance, which is
        # deprecated in Pydantic >=2.11 and emits a deprecation warning.
        with pytest.warns(DeprecationWarning):
            text = repr(f)
        assert text.startswith("SEC Filing(")
        assert "base_url" in text
        assert "document_urls" in text

    def test_index_headers_download_error_wrapped(self, monkeypatch):
        def boom(url, read_html_table=False, use_cache=True):
            raise RuntimeError("network down")

        monkeypatch.setattr(SecBaseFiling, "download_file", staticmethod(boom))
        with pytest.raises(RuntimeError, match="index headers table"):
            SecBaseFiling(_FILING_URL, use_cache=False)

    def test_missing_period_and_item_limit_break(self, monkeypatch):
        # 9 distinct counted items are reached (7 base fields + 3 ITEM
        # INFORMATION lines), so the loop breaks before the trailing CONFORMED
        # PERIOD OF REPORT line is processed -> period_ending stays None.
        index_html = (
            "<html><body><pre>\n"
            "COMPANY CONFORMED NAME: ACME\n"
            "CONFORMED SUBMISSION TYPE: 8-K\n"
            "CENTRAL INDEX KEY: 0000317540\n"
            "STANDARD INDUSTRIAL CLASSIFICATION: BEV [2080]\n"
            "ORGANIZATION NAME: 04 Mfg\n"
            "FISCAL YEAR END: 1231\n"
            "FILED AS OF DATE: 20240805\n"
            "ITEM INFORMATION: A\n"
            "ITEM INFORMATION: B\n"
            "ITEM INFORMATION: C\n"
            "CONFORMED PERIOD OF REPORT: 20240731\n"
            "&lt;DOCUMENT&gt;\n"
            "&lt;TYPE&gt;8-K\n"
            "&lt;SEQUENCE&gt;1\n"
            "&lt;FILENAME&gt;doc.htm\n"
            "&lt;/DOCUMENT&gt;\n"
            "</pre></body></html>"
        )

        def fake_download_file(url, read_html_table=False, use_cache=True):
            return index_html

        monkeypatch.setattr(
            SecBaseFiling, "download_file", staticmethod(fake_download_file)
        )
        monkeypatch.setattr("openbb_sec.utils.helpers.cik_map", _async_return(None))
        f = SecBaseFiling(_FILING_URL, use_cache=False)
        # Break hit at the 9th item -> trailing period line never processed.
        assert f.period_ending is None
        assert f.description == "A; B"
        # Calling _download_index_headers again reuses the cached download
        # instead of re-fetching (the else-branch).
        f._download_index_headers()
        assert f.name == "ACME"


class TestSecFilingCoverPage:
    """Cover page parsing variations."""

    def test_cover_page_with_trading_symbols(self, monkeypatch):
        import pandas

        cover_df = pandas.DataFrame(
            {
                0: [
                    "Document Type",
                    "Document Fiscal Year Focus",
                    "Document Fiscal Period Focus",
                    "Entity Registrant Name",
                    "Title of 12(b) Security",
                    "Trading Symbol",
                    "Security Exchange Name",
                ],
                1: [
                    "8-K",
                    "2024",
                    "Q2",
                    "ACME CORP",
                    "Common Stock",
                    "KO",
                    "NYSE",
                ],
            }
        )

        def fake_download_file(url, read_html_table=False, use_cache=True):
            if url.endswith("R1.htm"):
                return [cover_df]
            return _INDEX_HTML

        monkeypatch.setattr(
            SecBaseFiling, "download_file", staticmethod(fake_download_file)
        )
        # cik_map returns None -> the cover-page trading symbols are used.
        monkeypatch.setattr("openbb_sec.utils.helpers.cik_map", _async_return(None))
        f = SecBaseFiling(_FILING_URL, use_cache=True)
        cover = f.cover_page
        assert cover["Document Fiscal Year Focus"] == "2024"
        assert cover["SIC"] == "BEVERAGES [2080]"
        # 12(b) securities list assembled from title/symbol/exchange
        assert cover["12(b) Securities"] == [
            {"Title": "Common Stock", "Symbol": "KO", "Exchange": "NYSE"}
        ]
        assert f.trading_symbols == ["KO"]

    def test_cover_page_multiindex_columns_droplevel(self, monkeypatch):
        import pandas

        # MultiIndex columns exercise the droplevel(0) branch.
        cols = pandas.MultiIndex.from_tuples(
            [
                ("Cover [Abstract]", "lbl"),
                ("v1", "val1"),
                ("v2", "2024-07-31"),
            ]
        )
        cover_df = pandas.DataFrame(
            [
                ["Document Type", "10-K", None],
                ["Document Fiscal Year Focus", "2024", None],
                ["Document Fiscal Period Focus", "FY", None],
                ["Trading Symbol", "KO", None],
                ["Title of 12(b) Security", "Common Stock", None],
                ["Security Exchange Name", "NYSE", None],
            ],
            columns=cols,
        )

        def fake_download_file(url, read_html_table=False, use_cache=True):
            if url.endswith("R1.htm"):
                return [cover_df]
            return _INDEX_HTML

        monkeypatch.setattr(
            SecBaseFiling, "download_file", staticmethod(fake_download_file)
        )
        monkeypatch.setattr("openbb_sec.utils.helpers.cik_map", _async_return(None))
        f = SecBaseFiling(_FILING_URL, use_cache=True)
        # MultiIndex columns are dropped to a single level; cover parsed fine.
        assert f.cover_page["Document Fiscal Period Focus"] == "FY"
        assert f.cover_page["12(b) Securities"][0]["Symbol"] == "KO"

    def test_cover_page_shares_outstanding_assignment(self, monkeypatch):
        import pandas

        # Single-level columns where the first column name carries the
        # "- shares in thousands" marker and the third column holds the as-of
        # date + shares-outstanding value. This reaches the shares-outstanding
        # multiplier assignment block.
        cover_df = pandas.DataFrame(
            [
                ["Document Type", "10-K", None],
                ["Document Fiscal Year Focus", "2024", None],
                ["Document Fiscal Period Focus", "FY", None],
                ["Entity Common Stock, Shares Outstanding", None, 1000],
                ["Trading Symbol", "KO", None],
                ["Title of 12(b) Security", "Common Stock", None],
                ["Security Exchange Name", "NYSE", None],
            ],
            columns=["Cover - shares in thousands", "val1", "2024-07-31"],
        )

        def fake_download_file(url, read_html_table=False, use_cache=True):
            if url.endswith("R1.htm"):
                return [cover_df]
            return _INDEX_HTML

        monkeypatch.setattr(
            SecBaseFiling, "download_file", staticmethod(fake_download_file)
        )
        monkeypatch.setattr("openbb_sec.utils.helpers.cik_map", _async_return(None))
        f = SecBaseFiling(_FILING_URL, use_cache=True)
        # shares_outstanding stored as {date: shares * multiplier}
        assert f._shares_outstanding == {"2024-07-31": 1_000_000}
        assert f.cover_page["12(b) Securities"][0]["Symbol"] == "KO"

    def test_cover_page_download_failure_wrapped(self, monkeypatch):
        def fake_download_file(url, read_html_table=False, use_cache=True):
            if url.endswith("R1.htm"):
                raise RuntimeError("cover boom")
            return _INDEX_HTML

        monkeypatch.setattr(
            SecBaseFiling, "download_file", staticmethod(fake_download_file)
        )
        monkeypatch.setattr("openbb_sec.utils.helpers.cik_map", _async_return(None))
        with pytest.raises(RuntimeError, match="cover page table"):
            SecBaseFiling(_FILING_URL, use_cache=True)

    def test_cover_page_empty_response_raises(self, monkeypatch):
        # An empty cover-page response trips the "Failed to download cover page
        # table" guard, which is re-wrapped by the outer handler.
        def fake_download_file(url, read_html_table=False, use_cache=True):
            if url.endswith("R1.htm"):
                return []
            return _INDEX_HTML

        monkeypatch.setattr(
            SecBaseFiling, "download_file", staticmethod(fake_download_file)
        )
        monkeypatch.setattr("openbb_sec.utils.helpers.cik_map", _async_return(None))
        with pytest.raises(RuntimeError, match="Failed to download cover page table"):
            SecBaseFiling(_FILING_URL, use_cache=True)

    def test_cover_page_empty_dataframe_raises(self, monkeypatch):
        # A response holding an empty DataFrame trips the "Failed to read cover
        # page table" guard.
        import pandas

        def fake_download_file(url, read_html_table=False, use_cache=True):
            if url.endswith("R1.htm"):
                return [pandas.DataFrame()]
            return _INDEX_HTML

        monkeypatch.setattr(
            SecBaseFiling, "download_file", staticmethod(fake_download_file)
        )
        monkeypatch.setattr("openbb_sec.utils.helpers.cik_map", _async_return(None))
        with pytest.raises(RuntimeError, match="Failed to read cover page table"):
            SecBaseFiling(_FILING_URL, use_cache=True)

    def test_cover_page_index_error_swallowed(self, monkeypatch):
        # A single-column frame containing a "Document Fiscal Year Focus" row
        # raises IndexError when the parser reads the second column; that error
        # is silently swallowed, leaving the cover page unset.
        import pandas

        def fake_download_file(url, read_html_table=False, use_cache=True):
            if url.endswith("R1.htm"):
                return [pandas.DataFrame({0: ["Document Fiscal Year Focus"]})]
            return _INDEX_HTML

        monkeypatch.setattr(
            SecBaseFiling, "download_file", staticmethod(fake_download_file)
        )
        monkeypatch.setattr("openbb_sec.utils.helpers.cik_map", _async_return(None))
        f = SecBaseFiling(_FILING_URL, use_cache=True)
        # IndexError was swallowed -> cover page never populated.
        assert not f._cover_page


class TestSecFilingFetcher:
    """SecFilingFetcher transform_query/aextract_data/transform_data."""

    def test_transform_query(self):
        qp = SecFilingFetcher.transform_query({"url": _FILING_URL})
        assert qp.url == _FILING_URL

    def test_aextract_error_wrapped(self):
        q = types.SimpleNamespace(
            url="https://www.sec.gov/Archives/edgar/foo/bar/", use_cache=False
        )
        with pytest.raises(OpenBBError):
            _run(SecFilingFetcher.aextract_data(q, None))

    def test_aextract_empty_url_resolves_default(self, monkeypatch):
        monkeypatch.setattr(
            SecFilingFetcher,
            "_default_filing_url",
            staticmethod(_async_return(_FILING_URL)),
        )

        def fake_download_file(url, read_html_table=False, use_cache=True):
            if read_html_table:
                import pandas

                return [pandas.DataFrame({0: ["Document Type"], 1: ["8-K"]})]
            return _INDEX_HTML

        monkeypatch.setattr(
            SecBaseFiling, "download_file", staticmethod(fake_download_file)
        )
        monkeypatch.setattr("openbb_sec.utils.helpers.cik_map", _async_return("KO"))
        q = types.SimpleNamespace(url="", use_cache=False)
        out = _run(SecFilingFetcher.aextract_data(q, None))
        assert out["name"] == "ACME CORP"

    def test_default_filing_url_returns_first(self, monkeypatch):
        class _Filing:
            report_url = "https://www.sec.gov/Archives/edgar/data/320193/x/aapl.htm"

        async def fake_fetch(self, params, credentials, **kwargs):
            return [_Filing()]

        monkeypatch.setattr(
            "openbb_sec.models.company_filings.SecCompanyFilingsFetcher.fetch_data",
            fake_fetch,
        )
        out = _run(SecFilingFetcher._default_filing_url(False))
        assert out.endswith("aapl.htm")

    def test_default_filing_url_annotated_result(self, monkeypatch):
        from openbb_core.provider.abstract.annotated_result import AnnotatedResult

        class _Filing:
            report_url = "https://www.sec.gov/Archives/edgar/data/320193/x/aapl.htm"

        async def fake_fetch(self, params, credentials, **kwargs):
            return AnnotatedResult(result=[_Filing()])

        monkeypatch.setattr(
            "openbb_sec.models.company_filings.SecCompanyFilingsFetcher.fetch_data",
            fake_fetch,
        )
        out = _run(SecFilingFetcher._default_filing_url(False))
        assert out.endswith("aapl.htm")

    def test_default_filing_url_empty_raises(self, monkeypatch):
        async def fake_fetch(self, params, credentials, **kwargs):
            return []

        monkeypatch.setattr(
            "openbb_sec.models.company_filings.SecCompanyFilingsFetcher.fetch_data",
            fake_fetch,
        )
        with pytest.raises(OpenBBError):
            _run(SecFilingFetcher._default_filing_url(False))

    def test_aextract_success_returns_model_dump(self, monkeypatch):
        # A successful SecBaseFiling build returns its model_dump payload.
        def fake_download_file(url, read_html_table=False, use_cache=True):
            if read_html_table:
                import pandas

                return [pandas.DataFrame({0: ["Document Type"], 1: ["8-K"]})]
            return _INDEX_HTML

        monkeypatch.setattr(
            SecBaseFiling, "download_file", staticmethod(fake_download_file)
        )
        monkeypatch.setattr("openbb_sec.utils.helpers.cik_map", _async_return("KO"))
        q = types.SimpleNamespace(url=_FILING_URL, use_cache=False)
        out = _run(SecFilingFetcher.aextract_data(q, None))
        assert isinstance(out, dict)
        assert out["name"] == "ACME CORP"
        assert out["cik"] == "0000317540"

    def test_transform_data_validates_model(self):
        data = {
            "base_url": "https://www.sec.gov/Archives/edgar/data/317540/x/",
            "name": "ACME CORP",
            "cik": "0000317540",
            "sic": "2080",
            "sic_organization_name": "04 Manufacturing",
            "filing_date": "2024-08-05",
            "document_type": "8-K",
            "has_cover_page": False,
            "document_urls": [{"type": "8-K", "url": "x"}],
        }
        out = SecFilingFetcher.transform_data(types.SimpleNamespace(), data)
        assert out.name == "ACME CORP"
        assert out.document_type == "8-K"


_BASE_URL = "https://www.sec.gov/Archives/edgar/data/317540/000031754024000045/"


def _make_filing(**private):
    """Build a Filing without running __init__, seeding private attributes."""
    filing = SecBaseFiling.model_construct()
    filing._url = _BASE_URL
    for key, value in private.items():
        setattr(filing, f"_{key}", value)
    return filing


class TestLazyDict:
    """LazyDict load/cache/lookup behaviour."""

    def test_keys_and_labels(self):
        ld = LazyDict({"a": "Label A", "b": "Label B"}, lambda k: k.upper())
        assert set(ld.keys()) == {"a", "b"}
        assert ld.labels() == {"a": "Label A", "b": "Label B"}

    def test_getitem_loads_and_caches(self):
        calls: list = []

        def loader(key):
            calls.append(key)
            return key * 2

        ld = LazyDict({"x": "X"}, loader)
        assert ld["x"] == "xx"
        assert ld["x"] == "xx"
        assert calls == ["x"]

    def test_getitem_unknown_key_raises(self):
        ld = LazyDict({"a": "A"}, lambda k: k)
        with pytest.raises(KeyError):
            ld["missing"]

    def test_get_known_and_default(self):
        ld = LazyDict({"a": "A"}, lambda k: "val")
        assert ld.get("a") == "val"
        assert ld.get("missing", "fallback") == "fallback"

    def test_iter_len_contains(self):
        ld = LazyDict({"a": "A", "b": "B"}, lambda k: k)
        assert list(iter(ld)) == ["a", "b"]
        assert len(ld) == 2
        assert "a" in ld
        assert "z" not in ld

    def test_items_and_values(self):
        ld = LazyDict({"a": "A", "b": "B"}, lambda k: k.upper())
        assert dict(ld.items()) == {"a": "A", "b": "B"}
        assert sorted(ld.values()) == ["A", "B"]

    def test_repr(self):
        ld = LazyDict({"a": "A"}, lambda k: k)
        assert repr(ld) == "LazyDict(keys=['a'])"


class TestGetMainDocumentUrl:
    """Filing.get_main_document_url branches."""

    def test_no_documents_returns_none(self):
        filing = _make_filing(document_urls=[])
        assert filing.get_main_document_url() is None

    def test_primary_type_html_match(self):
        filing = _make_filing(
            document_urls=[
                {"type": "8-K", "url": _BASE_URL + "doc.htm"},
            ]
        )
        assert filing.get_main_document_url() == _BASE_URL + "doc.htm"

    def test_fallback_to_first_html_not_r1(self):
        filing = _make_filing(
            document_urls=[
                {"type": "GRAPHIC", "url": _BASE_URL + "img.jpg"},
                {"type": "EX-99.1", "url": _BASE_URL + "ex.htm"},
            ]
        )
        assert filing.get_main_document_url() == _BASE_URL + "ex.htm"

    def test_only_r1_html_returns_none(self):
        filing = _make_filing(
            document_urls=[
                {"type": "COVER", "url": _BASE_URL + "R1.htm"},
                {"type": "GRAPHIC", "url": _BASE_URL + "img.jpg"},
            ]
        )
        assert filing.get_main_document_url() is None


class TestGetMainDocumentContent:
    """Filing.get_main_document_content branches."""

    def test_no_url_returns_none(self):
        filing = _make_filing(document_urls=[])
        assert filing.get_main_document_content() is None

    def test_bytes_content_decoded(self, monkeypatch):
        filing = _make_filing(
            document_urls=[{"type": "8-K", "url": _BASE_URL + "doc.htm"}]
        )
        monkeypatch.setattr(filing, "_get_document", lambda *a, **k: b"hello bytes")
        assert filing.get_main_document_content() == "hello bytes"

    def test_str_content_returned(self, monkeypatch):
        filing = _make_filing(
            document_urls=[{"type": "8-K", "url": _BASE_URL + "doc.htm"}]
        )
        monkeypatch.setattr(filing, "_get_document", lambda *a, **k: "plain str")
        assert filing.get_main_document_content() == "plain str"

    def test_inline_content_fallback_primary(self):
        filing = _make_filing(
            document_urls=[
                {"type": "GRAPHIC", "content": "ignored", "url": ""},
                {"type": "10-K", "content": "main body", "url": ""},
            ]
        )
        assert filing.get_main_document_content() == "main body"

    def test_inline_content_fallback_first(self):
        filing = _make_filing(
            document_urls=[{"type": "GRAPHIC", "content": "only body", "url": ""}]
        )
        assert filing.get_main_document_content() == "only body"


class TestGetEmbeddedDocument:
    """Filing.get_embedded_document branches."""

    def test_no_documents_returns_none(self):
        filing = _make_filing(document_urls=[])
        assert filing.get_embedded_document("EX-99.1") is None

    def test_match_with_bytes_content(self, monkeypatch):
        filing = _make_filing(
            document_urls=[{"type": "EX-99.1", "url": _BASE_URL + "ex.htm"}]
        )
        monkeypatch.setattr(filing, "_get_document", lambda *a, **k: b"exhibit")
        assert filing.get_embedded_document("ex-99.1") == "exhibit"

    def test_match_with_str_content(self, monkeypatch):
        filing = _make_filing(
            document_urls=[{"type": "EX-99.1", "url": _BASE_URL + "ex.htm"}]
        )
        monkeypatch.setattr(filing, "_get_document", lambda *a, **k: "exhibit")
        assert filing.get_embedded_document("EX-99.1") == "exhibit"

    def test_match_with_empty_url_skipped(self):
        filing = _make_filing(
            document_urls=[
                {"type": "EX-99.1", "url": ""},
                {"type": "OTHER", "url": _BASE_URL + "o.htm"},
            ]
        )
        assert filing.get_embedded_document("EX-99.1") is None

    def test_no_type_match_returns_none(self):
        filing = _make_filing(
            document_urls=[{"type": "8-K", "url": _BASE_URL + "doc.htm"}]
        )
        assert filing.get_embedded_document("EX-99.1") is None


class TestAccessionDash:
    """Filing._accession_dash branches."""

    def test_valid_accession(self):
        filing = _make_filing()
        assert filing._accession_dash() == "0000317540-24-000045"

    def test_invalid_accession_returns_none(self):
        filing = SecBaseFiling.model_construct()
        filing._url = "https://www.sec.gov/Archives/edgar/data/317540/short/"
        assert filing._accession_dash() is None


class TestMembersFromZip:
    """Filing._members_from_zip member-map construction."""

    def test_zip_members_mapped(self, monkeypatch):
        buf = BytesIO()
        with ZipFile(buf, "w") as zf:
            zf.writestr("sub/MetaLinks.json", '{"k": 1}')
            zf.writestr("R1.htm", "<html></html>")
            zf.writestr("nested/", "")
        raw = buf.getvalue()

        monkeypatch.setattr(
            "openbb_sec.utils.cache.cached_bytes",
            lambda *a, **k: raw,
        )
        out = SecBaseFiling._members_from_zip("http://x/f-xbrl.zip", use_cache=False)
        assert out["MetaLinks.json"] == b'{"k": 1}'
        assert out["R1.htm"] == b"<html></html>"
        assert "nested" not in out

    def test_empty_bytes_returns_empty(self, monkeypatch):
        monkeypatch.setattr("openbb_sec.utils.cache.cached_bytes", lambda *a, **k: b"")
        assert SecBaseFiling._members_from_zip("http://x/f.zip") == {}

    def test_bad_zip_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            "openbb_sec.utils.cache.cached_bytes", lambda *a, **k: b"not a zip"
        )
        assert SecBaseFiling._members_from_zip("http://x/f.zip") == {}


class TestMembersFromTxt:
    """Filing._members_from_txt member-map construction."""

    def test_txt_documents_mapped(self, monkeypatch):
        text = (
            "<SEC-DOCUMENT>\n"
            "<DOCUMENT>\n"
            "<TYPE>8-K\n"
            "<FILENAME>doc.htm\n"
            "<TEXT>\n<html>body</html>\n</TEXT>\n"
            "</DOCUMENT>\n"
            "<DOCUMENT>\n"
            "<TYPE>EX-99.1\n"
            "<FILENAME>ex.htm\n"
            "<TEXT>\nexhibit text\n</TEXT>\n"
            "</DOCUMENT>\n"
            "</SEC-DOCUMENT>\n"
        )
        monkeypatch.setattr("openbb_sec.utils.cache.cached_text", lambda *a, **k: text)
        out = SecBaseFiling._members_from_txt("http://x/f.txt", use_cache=False)
        assert "doc.htm" in out
        assert "<html>body</html>" in out["doc.htm"]
        assert "exhibit text" in out["ex.htm"]

    def test_document_without_filename_skipped(self, monkeypatch):
        text = "<DOCUMENT>\n<TYPE>8-K\n<TEXT>\nbody\n</TEXT>\n</DOCUMENT>\n"
        monkeypatch.setattr("openbb_sec.utils.cache.cached_text", lambda *a, **k: text)
        assert SecBaseFiling._members_from_txt("http://x/f.txt") == {}

    def test_document_without_text_uses_full_doc(self, monkeypatch):
        text = "<DOCUMENT>\n<TYPE>8-K\n<FILENAME>doc.htm\nno text tag\n</DOCUMENT>\n"
        monkeypatch.setattr("openbb_sec.utils.cache.cached_text", lambda *a, **k: text)
        out = SecBaseFiling._members_from_txt("http://x/f.txt")
        assert "no text tag" in out["doc.htm"]

    def test_empty_text_returns_empty(self, monkeypatch):
        monkeypatch.setattr("openbb_sec.utils.cache.cached_text", lambda *a, **k: "")
        assert SecBaseFiling._members_from_txt("http://x/f.txt") == {}

    def test_exception_returns_empty(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr("openbb_sec.utils.cache.cached_text", boom)
        assert SecBaseFiling._members_from_txt("http://x/f.txt") == {}


class TestMaterialize:
    """Filing._materialize type-conversion branches."""

    def test_json_bytes(self):
        out = SecBaseFiling._materialize("MetaLinks.json", b'{"a": 1}')
        assert out == {"a": 1}

    def test_json_str(self):
        out = SecBaseFiling._materialize("MetaLinks.json", '{"a": 2}')
        assert out == {"a": 2}

    def test_read_html_table_from_bytes(self):
        html = b"<table><tr><th>a</th></tr><tr><td>1</td></tr></table>"
        out = SecBaseFiling._materialize("R1.htm", html, read_html_table=True)
        assert len(out) == 1

    def test_str_passthrough(self):
        assert SecBaseFiling._materialize("doc.txt", "plain") == "plain"

    def test_html_bytes_latin1_decode(self):
        out = SecBaseFiling._materialize("doc.htm", b"<html>x</html>")
        assert out == "<html>x</html>"

    def test_other_bytes_utf8_decode(self):
        out = SecBaseFiling._materialize("data.xml", b"<xml/>")
        assert out == "<xml/>"


class TestLoadArchive:
    """Filing._load_archive and _load_txt_members guards."""

    def test_load_archive_invalid_accession_noop(self):
        filing = SecBaseFiling.model_construct()
        filing._url = "https://www.sec.gov/Archives/edgar/data/317540/short/"
        filing._load_archive()
        assert filing._archive_loaded is True
        assert filing._archive == {}

    def test_load_archive_populates_from_zip(self, monkeypatch):
        filing = _make_filing(use_cache=False)
        monkeypatch.setattr(
            SecBaseFiling,
            "_members_from_zip",
            staticmethod(lambda url, use_cache=True: {"R1.htm": b"<html/>"}),
        )
        filing._load_archive()
        assert filing._archive["R1.htm"] == b"<html/>"

    def test_load_txt_invalid_accession_noop(self):
        filing = SecBaseFiling.model_construct()
        filing._url = "https://www.sec.gov/Archives/edgar/data/317540/short/"
        filing._load_txt_members()
        assert filing._txt_loaded is True
        assert filing._archive == {}

    def test_load_txt_populates_from_txt(self, monkeypatch):
        filing = _make_filing(use_cache=False)
        monkeypatch.setattr(
            SecBaseFiling,
            "_members_from_txt",
            staticmethod(lambda url, use_cache=True: {"doc.htm": "body"}),
        )
        filing._load_txt_members()
        assert filing._archive["doc.htm"] == "body"


class TestGetDocument:
    """Filing._get_document archive-first then download fallback."""

    def test_served_from_zip_archive(self, monkeypatch):
        filing = _make_filing(use_cache=False)
        monkeypatch.setattr(
            SecBaseFiling,
            "_members_from_zip",
            staticmethod(lambda url, use_cache=True: {"doc.htm": b"<html>z</html>"}),
        )
        out = filing._get_document(_BASE_URL + "doc.htm")
        assert out == "<html>z</html>"

    def test_falls_back_to_txt_when_zip_empty(self, monkeypatch):
        filing = _make_filing(use_cache=False)
        monkeypatch.setattr(
            SecBaseFiling,
            "_members_from_zip",
            staticmethod(lambda url, use_cache=True: {}),
        )
        monkeypatch.setattr(
            SecBaseFiling,
            "_members_from_txt",
            staticmethod(lambda url, use_cache=True: {"doc.htm": "txt body"}),
        )
        out = filing._get_document(_BASE_URL + "doc.htm")
        assert out == "txt body"

    def test_download_fallback_json_parsed(self, monkeypatch):
        filing = _make_filing(use_cache=False, archive_loaded=True, txt_loaded=True)
        filing._archive = {"existing.htm": b"x"}
        monkeypatch.setattr(
            SecBaseFiling,
            "download_file",
            staticmethod(lambda url, rt=False, uc=True: '{"k": 5}'),
        )
        out = filing._get_document(_BASE_URL + "MetaLinks.json")
        assert out == {"k": 5}

    def test_download_fallback_invalid_json_returned_raw(self, monkeypatch):
        filing = _make_filing(use_cache=False, archive_loaded=True, txt_loaded=True)
        filing._archive = {"existing.htm": b"x"}
        monkeypatch.setattr(
            SecBaseFiling,
            "download_file",
            staticmethod(lambda url, rt=False, uc=True: "not json"),
        )
        out = filing._get_document(_BASE_URL + "data.json")
        assert out == "not json"

    def test_download_fallback_non_json(self, monkeypatch):
        filing = _make_filing(use_cache=False, archive_loaded=True, txt_loaded=True)
        filing._archive = {"existing.htm": b"x"}
        monkeypatch.setattr(
            SecBaseFiling,
            "download_file",
            staticmethod(lambda url, rt=False, uc=True: "<html>net</html>"),
        )
        out = filing._get_document(_BASE_URL + "doc.htm")
        assert out == "<html>net</html>"


class TestExhibitsAndItems:
    """Filing.exhibits and Filing.items LazyDict properties."""

    def test_exhibits_keyed_by_type(self):
        filing = _make_filing(
            document_urls=[
                {"type": "8-K", "url": _BASE_URL + "doc.htm"},
                {
                    "type": "EX-99.1",
                    "description": "Press Release",
                    "url": _BASE_URL + "ex.htm",
                },
                {"type": "EX-101", "url": _BASE_URL + "ex2.htm"},
            ]
        )
        ex = filing.exhibits
        assert set(ex.keys()) == {"EX-99.1", "EX-101"}
        assert ex.labels()["EX-99.1"] == "Press Release"
        assert ex.labels()["EX-101"] == "EX-101"
        assert ex["EX-99.1"]["url"].endswith("ex.htm")

    def test_items_with_dict_values(self):
        filing = _make_filing(items={"Item 1": {"name": "Business"}, "Item 2": "plain"})
        it = filing.items
        assert it.labels() == {"Item 1": "Business", "Item 2": "Item 2"}
        assert it["Item 1"] == {"name": "Business"}

    def test_items_empty(self):
        filing = _make_filing(items={})
        assert dict(filing.items.labels()) == {}


class TestEnsureBytes:
    """Filing._ensure_bytes coercion branches."""

    def test_bytes_passthrough(self):
        assert SecBaseFiling._ensure_bytes(b"abc") == b"abc"

    def test_bytearray(self):
        assert SecBaseFiling._ensure_bytes(bytearray(b"abc")) == b"abc"

    def test_str(self):
        assert SecBaseFiling._ensure_bytes("abc") == b"abc"

    def test_other(self):
        assert SecBaseFiling._ensure_bytes(123) == b"123"


class TestCleanHtmlToText:
    """Filing._clean_html_to_text conversion branches."""

    def test_empty_returns_empty(self):
        filing = _make_filing()
        assert filing._clean_html_to_text("") == ""

    def test_bytes_input(self):
        filing = _make_filing()
        out = filing._clean_html_to_text(b"<p>hello world</p>")
        assert "hello world" in out

    def test_table_kept(self):
        filing = _make_filing()
        html = "<table><tr><td>a</td><td>b</td></tr></table>"
        out = filing._clean_html_to_text(html, keep_tables=True)
        assert "a" in out and "b" in out
