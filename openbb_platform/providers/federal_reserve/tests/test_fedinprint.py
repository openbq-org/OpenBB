"""Tests for the shared Fed in Print faceted-search client."""

import pytest

from openbb_federal_reserve.utils import fedinprint


def _block(code, item_id, title, byline, meta, content_type="Working Paper") -> str:
    """Render one fedinprint search-result block."""
    type_span = (
        f'<span class="content-type">{content_type}</span><br>' if content_type else ""
    )
    return (
        '<div class="col-sm-9 col-md-10 search-result-detail">\n<p>'
        f"{type_span}"
        f'<a href="/item/{code}/{item_id}" class="title">\n{title}\n</a>\n<br>'
        f'<span class="byline">{byline}</span>\n<br>'
        '<span class="description">summary</span>'
        f'<span class="meta">\n{meta}\n</span>'
        "</p></div>"
    )


def _page(*blocks) -> str:
    """Wrap result blocks in a search-results container."""
    return '<div class="search-results">' + "".join(blocks) + "</div>"


def _item(*, citation=None, files_href=None) -> str:
    """Render a fedinprint item page with an optional citation URL / File(s) link."""
    parts = []
    if citation:
        parts.append(f'<meta name="citation_pdf_url" content="{citation}">')
    if files_href:
        parts.append(f'<strong>File(s): </strong><a href="{files_href}">link</a>')
    return "<html>" + "".join(parts) + "</html>"


def _fetch_from(search_pages=None, item_pages=None):
    """Build a fetch callable serving scripted search and item pages by URL token."""
    search_pages = search_pages or {}
    item_pages = item_pages or {}

    def fetch(url):
        if "fedinprint.org/search" in url:
            for token, page in search_pages.items():
                if token in url:
                    return page
            return _page()
        for token, page in item_pages.items():
            if token in url:
                return page
        return "<html></html>"

    return fetch


class TestParsing:
    """Tests for label cleaning, URL building, and block parsing."""

    def test_clean_label_collapses_whitespace(self):
        """Doubled whitespace collapses to a single space."""
        assert fedinprint.clean_label("On  the  Economy") == "On the Economy"

    def test_search_url_encodes_facets_sort_and_offset(self):
        """Facets, the newest-first sort, and the offset are encoded."""
        url = fedinprint._search_url(
            ["provider_literal_array:X", "hasparentname_literal_array:Review"], 20
        )
        assert url.count("facets%5B%5D=") == 2
        assert "sort=sort_date_text+desc" in url
        assert url.endswith("start=20")

    def test_parse_full_record(self):
        """A block yields series, date, title, and the item URL."""
        block = _block(
            "fedlwp", "1/2", "The &quot;Real&quot;  Wage", "Doe, J (2023-09)", "WP , 5"
        )
        assert fedinprint._parse_block(block, "Working Papers") == {
            "series": "Working Papers",
            "date": "2023-09-01",
            "title": 'The "Real" Wage',
            "url": "https://fedinprint.org/item/fedlwp/1/2",
        }

    def test_parse_series_falls_back_to_meta(self):
        """With no series supplied, the series is read from the meta line."""
        block = _block("fedles", "9", "T", "A (2020)", "Economic Synopses")
        record = fedinprint._parse_block(block, "")
        assert record["series"] == "Economic Synopses"
        assert record["date"] == "2020-01-01"

    def test_parse_full_date_kept(self):
        """A byline carrying a full date keeps the day."""
        block = _block("fedlwp", "9", "T", "A (2021-12-31)", "WP")
        assert fedinprint._parse_block(block, "x")["date"] == "2021-12-31"

    def test_parse_missing_date_is_empty(self):
        """A byline without a parenthesised date yields an empty date."""
        block = _block("fedlwp", "9", "T", "Author only", "WP")
        assert fedinprint._parse_block(block, "x")["date"] == ""

    def test_parse_no_content_type_skipped(self):
        """A web-only block without a content type is dropped."""
        block = _block("l00001", "9", "T", "A (2026)", "Blog", content_type="")
        assert fedinprint._parse_block(block, "") is None

    def test_parse_no_link_skipped(self):
        """A block missing the title link is dropped."""
        block = 'search-result-detail">\n<p><span class="content-type">X</span></p>'
        assert fedinprint._parse_block(block, "x") is None


class TestFileResolution:
    """Tests for file-link extraction and document resolution."""

    def test_first_file_link_prefers_citation(self):
        """The citation PDF URL is preferred over the File(s) link."""
        page = _item(citation="https://x/a.pdf", files_href="https://x/b")
        assert fedinprint._first_file_link(page) == "https://x/a.pdf"

    def test_first_file_link_falls_back_to_files(self):
        """Absent a citation URL, the File(s) link is used."""
        assert fedinprint._first_file_link(_item(files_href="https://x/b.pdf")) == (
            "https://x/b.pdf"
        )

    def test_first_file_link_none(self):
        """A page with neither link yields an empty string."""
        assert fedinprint._first_file_link("<html></html>") == ""

    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://x/doc.pdf", True),
            ("https://doi.org/10.20955/wp.2018.032", True),
            ("https://dx.doi.org/10.20955/wp.2018.032", True),
            ("https://fraser.stlouisfed.org/files/x.pdf", True),
            ("https://www.stlouisfed.org/on-the-economy/article", False),
            ("https://evil.example/path/doi.org/x", False),
        ],
    )
    def test_is_file(self, url, expected):
        """Only document URLs are recognised as downloadable files."""
        assert fedinprint._is_file(url) is expected

    def test_resolve_direct_citation(self):
        """A direct citation PDF URL resolves without a second hop."""
        fetch = _fetch_from(item_pages={"item": _item(citation="https://x/a.pdf")})
        assert fedinprint.resolve_file("https://x/item", fetch) == "https://x/a.pdf"

    def test_resolve_doi_only_item_through_its_landing_page(self):
        """An item that carries only a DOI resolves to the landing page's PDF."""
        pages = {
            "https://fedinprint.org/item/fedawp/1/original": (
                '<meta name="citation_doi" content="10.29338/wp2026-19">'
            ),
            "https://doi.org/10.29338/wp2026-19": (
                '<meta property="og:url" content="https://www.atlantafed.org/'
                'research-and-data/publications/wp/19">'
                '<a href="/-/media/Project/Atlanta/FRBA/Documents/wp/19.pdf">'
                "Full text</a>"
            ),
        }
        assert fedinprint.resolve_file(
            "https://fedinprint.org/item/fedawp/1/original", pages.__getitem__
        ) == (
            "https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/"
            "wp/19.pdf"
        )

    def test_resolve_fraser_two_hop(self):
        """A FRASER catalog page is followed to the underlying document."""
        fetch = _fetch_from(
            item_pages={
                "fedinprint.org/item/fedliv/1": _item(
                    citation="https://fraser.stlouisfed.org/title/6107/item/9"
                ),
                "fraser.stlouisfed.org/title/6107/item/9": _item(
                    citation="https://fraser.stlouisfed.org/files/x.pdf"
                ),
            }
        )
        out = fedinprint.resolve_file("https://fedinprint.org/item/fedliv/1", fetch)
        assert out == "https://fraser.stlouisfed.org/files/x.pdf"

    def test_public_url_rewrites_cms_host(self):
        """A CMS staging host is rewritten to the public one; others are unchanged."""
        assert (
            fedinprint._public_url("https://atlantafedcm.ws.frb.org/-/media/x.pdf")
            == "https://www.atlantafed.org/-/media/x.pdf"
        )
        assert fedinprint._public_url("https://www.frbsf.org/x.pdf") == (
            "https://www.frbsf.org/x.pdf"
        )

    def test_resolve_rewrites_cms_host(self):
        """A resolved CMS-hosted document is returned on the public host."""
        fetch = _fetch_from(
            item_pages={
                "item": _item(citation="https://atlantafedcm.ws.frb.org/-/media/wp.pdf")
            }
        )
        assert fedinprint.resolve_file("https://x/item", fetch) == (
            "https://www.atlantafed.org/-/media/wp.pdf"
        )

    def test_resolve_rejects_spoofed_fraser_host(self):
        """A look-alike FRASER host is not followed and resolves to ``None``."""
        calls = []

        def fetch(url):
            """Return an item whose citation spoofs the FRASER host."""
            calls.append(url)
            return _item(citation="https://fraser.stlouisfed.org.evil.example/title/9")

        assert fedinprint.resolve_file("https://x/item", fetch) is None
        assert calls == ["https://x/item"]

    def test_resolve_no_link_none(self):
        """An item page with no file link resolves to ``None``."""
        assert fedinprint.resolve_file("https://x/item", _fetch_from()) is None

    def test_resolve_non_file_none(self):
        """An item whose link is an HTML article resolves to ``None``."""
        fetch = _fetch_from(
            item_pages={"item": _item(files_href="https://www.stlouisfed.org/ov/x")}
        )
        assert fedinprint.resolve_file("https://x/item", fetch) is None


class TestSafeResolve:
    """Tests for the cached, exception-swallowing single-item resolver."""

    def test_returns_resolved_document(self, monkeypatch):
        """A successful resolution is returned through the cache."""
        monkeypatch.setattr(
            fedinprint, "resolve_file", lambda url, fetch: "https://x/a.pdf"
        )
        monkeypatch.setattr(
            "openbb_federal_reserve.utils.cache.cached",
            lambda key, ttl, producer: producer(),
        )
        assert fedinprint._safe_resolve("item") == "https://x/a.pdf"

    def test_exception_returns_none(self, monkeypatch):
        """Any resolution error is swallowed to ``None``."""

        def _boom(url, fetch):
            raise RuntimeError("nope")

        monkeypatch.setattr(fedinprint, "resolve_file", _boom)
        monkeypatch.setattr(
            "openbb_federal_reserve.utils.cache.cached",
            lambda key, ttl, producer: producer(),
        )
        assert fedinprint._safe_resolve("item") is None


class TestResolveRecords:
    """Tests for the bounded-parallel, early-stopping resolution filter."""

    def test_drops_unresolved_and_rewrites_url(self, monkeypatch):
        """Non-resolving records drop; kept records carry the resolved URL."""
        resolved = {"a": "https://x/a.pdf", "c": "https://x/c.pdf"}
        monkeypatch.setattr(fedinprint, "_safe_resolve", resolved.get)
        records = [
            {"series": "S", "date": "2026-01", "title": "A", "url": "a"},
            {"series": "S", "date": "2025-12", "title": "B", "url": "b"},
            {"series": "S", "date": "2025-11", "title": "C", "url": "c"},
        ]
        out = fedinprint.resolve_records(records, 5)
        assert [(r["title"], r["url"]) for r in out] == [
            ("A", "https://x/a.pdf"),
            ("C", "https://x/c.pdf"),
        ]

    def test_stops_at_limit(self, monkeypatch):
        """Resolution halts once ``limit`` documents are collected."""
        monkeypatch.setattr(fedinprint, "_safe_resolve", lambda url: f"{url}.pdf")
        records = [
            {"series": "S", "date": "", "title": str(i), "url": str(i)}
            for i in range(30)
        ]
        out = fedinprint.resolve_records(records, 5, workers=4)
        assert len(out) == 5
        assert [r["title"] for r in out] == ["0", "1", "2", "3", "4"]

    def test_empty_records(self):
        """No records yields an empty page."""
        assert fedinprint.resolve_records([], 5) == []


class TestResolvedPage:
    """Tests for the district-agnostic resolved-page assembler."""

    _FACETS = {"wp": "Working Papers", "rev": "Review"}

    def _identity_resolver(self, monkeypatch):
        """Make resolve_records return its candidates with a ``.pdf`` URL suffix."""
        monkeypatch.setattr(
            fedinprint,
            "resolve_records",
            lambda cands, need: [{**c, "url": f"{c['url']}.pdf"} for c in cands][:need],
        )

    def test_known_series_searches_its_facet(self, monkeypatch):
        """A known slug searches only that series' facet."""
        captured = {}

        def _search(prov, fetch, series_facet=None, min_year="", start=0, limit=20):
            captured.update(facet=series_facet, min_year=min_year, start=start)
            return [{"series": "S", "date": "2026-01", "title": "A", "url": "a"}]

        monkeypatch.setattr(fedinprint, "search", _search)
        self._identity_resolver(monkeypatch)
        out = fedinprint.resolved_page("Prov", self._FACETS, "wp", "2024", 0, 5)
        assert captured["facet"] == "Working Papers"
        assert (captured["min_year"], captured["start"]) == ("2024", 0)
        assert out[0]["url"] == "a.pdf"

    def test_absent_series_uses_flagship(self, monkeypatch):
        """A ``None`` series falls back to the first (flagship) series."""
        captured = {}
        monkeypatch.setattr(
            fedinprint,
            "search",
            lambda prov, fetch, series_facet=None, **k: (
                captured.update(facet=series_facet) or []
            ),
        )
        self._identity_resolver(monkeypatch)
        fedinprint.resolved_page("Prov", self._FACETS, None, "", 0, 5)
        assert captured["facet"] == "Working Papers"

    def test_unknown_series_uses_flagship(self, monkeypatch):
        """An unknown slug also falls back to the flagship series."""
        captured = {}
        monkeypatch.setattr(
            fedinprint,
            "search",
            lambda prov, fetch, series_facet=None, **k: (
                captured.update(facet=series_facet) or []
            ),
        )
        self._identity_resolver(monkeypatch)
        fedinprint.resolved_page("Prov", self._FACETS, "bogus", "", 0, 5)
        assert captured["facet"] == "Working Papers"

    def test_empty_facets_returns_empty(self):
        """A provider with no document series yields an empty page."""
        assert fedinprint.resolved_page("Prov", {}, None, "", 0, 5) == []

    def test_start_offset_slices_resolved_page(self, monkeypatch):
        """The offset slices into the resolved, newest-first documents."""
        monkeypatch.setattr(
            fedinprint,
            "search",
            lambda *a, **k: [
                {"series": "S", "date": "", "title": str(i), "url": str(i)}
                for i in range(10)
            ],
        )
        self._identity_resolver(monkeypatch)
        out = fedinprint.resolved_page("Prov", self._FACETS, "wp", "", 2, 3)
        assert [r["title"] for r in out] == ["2", "3", "4"]


class TestSearch:
    """Tests for the fast paginated metadata search (no resolution in the list path)."""

    def test_returns_item_urls_sorted(self):
        """Content-type items are returned as item URLs, newest first."""
        page = _page(
            _block("fedlwp", "1", "Older", "A (2024-01)", "WP"),
            _block("fedlwp", "2", "Newer", "A (2024-06)", "WP"),
        )
        fetch = _fetch_from(search_pages={"start=0": page})
        out = fedinprint.search("Prov", fetch, series_facet="Working Papers", limit=5)
        assert [r["title"] for r in out] == ["Newer", "Older"]
        assert out[0]["url"] == "https://fedinprint.org/item/fedlwp/2"

    def test_offset_is_used(self):
        """A non-zero start offsets the first fetched page."""
        page = _page(_block("fedlwp", "9", "Deep", "A (2024-06)", "WP"))
        fetch = _fetch_from(search_pages={"start=10": page})
        out = fedinprint.search("Prov", fetch, start=10, limit=5)
        assert [r["title"] for r in out] == ["Deep"]

    def test_limit_caps_results(self):
        """The result count is capped at the limit."""
        page = _page(
            _block("fedlwp", "1", "A", "X (2024-06)", "WP"),
            _block("fedlwp", "2", "B", "X (2024-05)", "WP"),
        )
        fetch = _fetch_from(search_pages={"start=0": page})
        assert len(fedinprint.search("Prov", fetch, limit=1)) == 1

    def test_min_year_stops(self):
        """Records below the minimum year are dropped, newest-first."""
        page = _page(
            _block("fedlwp", "1", "New", "A (2024-06)", "WP"),
            _block("fedlwp", "2", "Old", "A (2018-01)", "WP"),
        )
        fetch = _fetch_from(search_pages={"start=0": page})
        out = fedinprint.search("Prov", fetch, min_year="2020", limit=10)
        assert [r["title"] for r in out] == ["New"]

    def test_dedupes_by_item_url(self):
        """Duplicate item URLs collapse to a single record."""
        page = _page(
            _block("fedliv", "1", "A", "X (2015-04)", "Inside the Vault"),
            _block("fedliv", "1", "A", "X (2015-04)", "Inside the Vault"),
        )
        fetch = _fetch_from(search_pages={"start=0": page})
        out = fedinprint.search("Prov", fetch, limit=10)
        assert len(out) == 1
        assert out[0]["url"] == "https://fedinprint.org/item/fedliv/1"

    def test_skips_content_typeless_blocks(self):
        """Web-only blocks without a content type are skipped."""
        page = _page(
            _block("l00001", "9", "Blog", "A (2026)", "Blog", content_type=""),
            _block("fedlwp", "1", "Doc", "A (2024-06)", "WP"),
        )
        fetch = _fetch_from(search_pages={"start=0": page})
        out = fedinprint.search("Prov", fetch, limit=10)
        assert [r["title"] for r in out] == ["Doc"]

    def test_empty_search_returns_empty(self):
        """A provider with no results yields an empty list."""
        assert fedinprint.search("Prov", _fetch_from(), limit=5) == []


class TestSeriesCounts:
    """Tests for parsing the series facet sidebar into document counts."""

    def test_parses_series_and_counts(self):
        """Series facets map to integer counts, keyed by clean label."""
        sidebar = (
            '<a data-facet-value="hasparentname_literal_array:Working Papers">x</a>'
            '<span class="text-muted">1,850&nbsp;items</span>'
            '<a data-facet-value="hasparentname_literal_array:On  the Economy">x</a>'
            '<span class="text-muted">626&nbsp;items</span>'
        )
        fetch = _fetch_from(search_pages={"provider_literal_array": sidebar})
        assert fedinprint.series_counts("Prov", fetch) == {
            "Working Papers": 1850,
            "On the Economy": 626,
        }


class _Resp:
    """A minimal scripted response for the session double."""

    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text

    def raise_for_status(self):
        """Raise for non-2xx that is not the retried 403."""
        if self.status_code >= 400 and self.status_code != 403:
            raise RuntimeError(str(self.status_code))


class _Session:
    """A session double that scripts responses in order."""

    def __init__(self, script):
        self.script = list(script)

    def get(self, url, timeout=None):
        """Return the next scripted response."""
        return self.script.pop(0)


class TestFetchText:
    """Tests for the per-thread session and text fetch."""

    def test_fetch_text_ok(self, monkeypatch):
        """A 200 returns the body without warming (Fed in Print is unwalled)."""
        from openbb_federal_reserve.utils import curl_session

        session = _Session([_Resp(200, "body")])
        monkeypatch.setattr(curl_session, "get_session", lambda key, warmup: session)
        assert fedinprint.fetch_text("https://fedinprint.org/item/x") == "body"

    def test_fetch_text_retries_once_on_403(self, monkeypatch):
        """A 403 resets the session and retries once."""
        from openbb_federal_reserve.utils import curl_session

        session = _Session([_Resp(403), _Resp(200, "ok")])
        monkeypatch.setattr(curl_session, "get_session", lambda key, warmup: session)
        resets = []
        monkeypatch.setattr(curl_session, "reset_session", resets.append)
        assert fedinprint.fetch_text("https://fedinprint.org/item/x") == "ok"
        assert len(resets) == 1


class TestDistrictApi:
    """Tests for the district-parameterised registry API."""

    def test_registry_exposes_districts(self):
        """The committed registry lists districts with a provider and series."""
        reg = fedinprint.load_registry()
        assert "boston" in fedinprint.districts()
        assert reg["boston"]["provider"] == "Federal Reserve Bank of Boston"
        assert fedinprint.provider("boston") == "Federal Reserve Bank of Boston"

    def test_series_choices_pair_label_with_slug(self):
        """Choices pair each series label with its slug for a district."""
        choices = fedinprint.series_choices("boston")
        slugs = [slug for slug, _ in fedinprint.load_registry()["boston"]["series"]]
        assert [c["value"] for c in choices] == slugs

    def test_search_publications_delegates_to_resolved_page(self, monkeypatch):
        """The district search forwards its provider, facet map, and paging."""
        captured = {}

        def _resolved(prov, facets, series, min_year, start, limit):
            captured.update(
                provider=prov, facets=facets, series=series, start=start, limit=limit
            )
            return [{"series": "x", "date": "", "title": "t", "url": "u"}]

        monkeypatch.setattr(fedinprint, "resolved_page", _resolved)
        slug, _facet = fedinprint.load_registry()["boston"]["series"][0]
        fedinprint.search_publications("boston", series=slug, start=5, limit=3)
        assert captured["provider"] == "Federal Reserve Bank of Boston"
        assert captured["facets"] == fedinprint._facets("boston")
        assert (captured["series"], captured["start"], captured["limit"]) == (
            slug,
            5,
            3,
        )

    def test_list_publications_derives_year_and_slug(self, monkeypatch):
        """The cached wrapper validates the slug and derives the start year."""
        from datetime import date

        captured = {}

        def _search(district, series, min_year, start, limit):
            captured.update(series=series, min_year=min_year)
            return [{"series": "x", "date": "", "title": "t", "url": "u"}]

        monkeypatch.setattr(fedinprint, "search_publications", _search)
        fedinprint.list_publications(
            "boston", series="bogus", start_date=date(2024, 5, 1)
        )
        assert captured["series"] is None
        assert captured["min_year"] == "2024"

    def test_list_series_merges_counts(self, monkeypatch):
        """list_series pairs each registry series with its live count."""
        monkeypatch.setattr(
            fedinprint,
            "series_counts",
            lambda prov, fetch: {"Working Papers": 513},
        )
        rows = fedinprint.list_series("boston")
        assert len(rows) == len(fedinprint.load_registry()["boston"]["series"])
        wp = next(r for r in rows if r["series"] == "working_papers")
        assert wp["count"] == 513


class TestRegistryGenerator:
    """Tests for classifying document series and writing the registry."""

    def test_slugify(self):
        """A facet name reduces to a lower-snake slug."""
        assert fedinprint._slugify("Working Paper Series, Macro") == (
            "working_paper_series_macro"
        )

    def test_is_document_true_when_item_resolves(self, monkeypatch):
        """A series is a document series when a recent item resolves to a file."""
        page = _page(_block("fedxwp", "1", "T", "A (2024)", "Working Papers"))
        monkeypatch.setattr(
            fedinprint,
            "fetch_text",
            _fetch_from(
                search_pages={"start=0": page},
                item_pages={"/1": _item(citation="https://x/a.pdf")},
            ),
        )
        assert fedinprint._is_document("Prov", "Working Papers") is True

    def test_is_document_false_when_no_file(self, monkeypatch):
        """A series is dropped when no recent item resolves to a file."""
        page = _page(_block("l00", "1", "Blog", "A (2024)", "Blog", content_type=""))
        monkeypatch.setattr(
            fedinprint, "fetch_text", _fetch_from(search_pages={"start=0": page})
        )
        assert fedinprint._is_document("Prov", "Blog") is False

    def test_is_document_false_on_resolve_error(self, monkeypatch):
        """A series is dropped when resolving its item raises."""
        page = _page(_block("fedxwp", "1", "T", "A (2024)", "Working Papers"))

        def fetch(url):
            if "fedinprint.org/search" in url:
                return page
            raise RuntimeError("boom")

        monkeypatch.setattr(fedinprint, "fetch_text", fetch)
        assert fedinprint._is_document("Prov", "Working Papers") is False

    def test_build_registry_dedups_slugs(self, monkeypatch):
        """Two facets with the same slug collapse to the first."""
        sidebar = (
            '<a data-facet-value="hasparentname_literal_array:Policy Hub">x</a>'
            '<span class="text-muted">10&nbsp;items</span>'
            '<a data-facet-value="hasparentname_literal_array:Policy Hub*">x</a>'
            '<span class="text-muted">5&nbsp;items</span>'
        )
        page = _page(_block("fedph", "1", "T", "A (2024)", "Policy Hub"))

        def fetch(url):
            if "provider_literal_array" in url and "hasparentname" not in url:
                return sidebar
            if "fedinprint.org/search" in url:
                return page
            return _item(citation="https://x/a.pdf")

        monkeypatch.setattr(fedinprint, "fetch_text", fetch)
        registry = fedinprint.build_registry({"x": "Prov"})
        assert registry["x"]["series"] == [["policy_hub", "Policy Hub"]]

    def test_build_and_write_registry(self, monkeypatch, tmp_path):
        """The registry keeps document series (deduped) and writes to the asset."""
        sidebar = (
            '<a data-facet-value="hasparentname_literal_array:Working Papers">x</a>'
            '<span class="text-muted">10&nbsp;items</span>'
            '<a data-facet-value="hasparentname_literal_array:Blog">x</a>'
            '<span class="text-muted">5&nbsp;items</span>'
        )
        wp_page = _page(_block("fedxwp", "1", "T", "A (2024)", "Working Papers"))
        blog_page = _page(_block("l00", "9", "B", "A (2024)", "Blog", content_type=""))

        def fetch(url):
            if "provider_literal_array" in url and "hasparentname" not in url:
                return sidebar
            if "Working+Papers" in url:
                return wp_page
            if "Blog" in url:
                return blog_page
            if "/item/" in url:
                return _item(citation="https://x/a.pdf")
            return "<html></html>"

        monkeypatch.setattr(fedinprint, "fetch_text", fetch)
        target = tmp_path / "districts.json"
        monkeypatch.setattr(fedinprint, "REGISTRY_PATH", target)
        fedinprint.load_registry.cache_clear()
        path = fedinprint.write_registry({"x": "Prov"})
        assert path == target
        import json

        payload = json.loads(target.read_text())
        assert payload["x"]["series"] == [["working_papers", "Working Papers"]]
        fedinprint.load_registry.cache_clear()
