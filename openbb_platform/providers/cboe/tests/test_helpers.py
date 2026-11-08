"""Tests for openbb_cboe.utils.helpers."""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager, closing
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pandas import DataFrame

from openbb_cboe.utils import helpers


class FakeResponse:
    """Minimal stand-in for an aiohttp client response."""

    def __init__(self, content_type, payload):
        self.headers = {"Content-Type": content_type}
        self._payload = payload

    async def json(self):
        """Return the JSON payload."""
        return self._payload

    async def text(self):
        """Return the text payload."""
        return self._payload

    async def read(self):
        """Return the raw payload."""
        return self._payload


class FakeCachedSession:
    """Minimal stand-in for ``aiohttp_client_cache.session.CachedSession``."""

    def __init__(self, response):
        self._response = response
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

        return False

    async def get(self, url, **kwargs):
        """Return the canned response."""
        self.url = url
        return self._response

    async def close(self):
        """Record that the session was closed."""
        self.closed = True


@pytest.fixture
def cache_file(tmp_path):
    """Keep the response cache in a file of its own, and check nothing is left open."""
    with (
        patch.object(helpers, "cache_path", lambda: str(tmp_path / "cboe")),
        patch.object(helpers, "_swept", True),
    ):
        yield tmp_path

    assert helpers._cache_users == 0
    assert helpers._stores is None


@pytest.fixture
def server():
    """A local HTTP server that records the path of every request it is sent."""
    from aiohttp import web

    requests: list = []
    started = threading.Event()
    running: dict = {}

    async def handler(request):
        requests.append(request.path)
        await asyncio.sleep(0.02)

        return web.json_response({"path": request.path})

    async def serve():
        app = web.Application()
        app.router.add_get("/{tail:.*}", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        running["url"] = f"http://127.0.0.1:{runner.addresses[0][1]}"
        running["loop"] = asyncio.get_running_loop()
        running["stop"] = asyncio.Event()
        started.set()
        await running["stop"].wait()
        await runner.cleanup()

    thread = threading.Thread(target=lambda: asyncio.run(serve()), daemon=True)
    thread.start()
    assert started.wait(10)

    yield SimpleNamespace(url=running["url"], requests=requests)

    running["loop"].call_soon_threadsafe(running["stop"].set)
    thread.join(10)


def _on_a_thread(factory):
    """Run ``factory()`` on a thread, and an event loop, of its own."""
    outcome: dict = {}

    def target():
        try:
            outcome["result"] = asyncio.run(factory())
        except BaseException as error:  # noqa: BLE001
            outcome["error"] = error

    thread = threading.Thread(target=target, daemon=True)
    thread.start()

    return thread, outcome


class TestNewYorkClock:
    """Every session-date default is anchored to America/New_York."""

    def test_ny_now_is_eastern(self):
        """The clock is timezone-aware and offset like New York."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        now = helpers.ny_now()

        assert now.tzinfo is not None
        assert (
            now.utcoffset() == datetime.now(tz=ZoneInfo("America/New_York")).utcoffset()
        )

    def test_ny_today_is_the_session_date(self):
        """The date is the New York session date, not the machine's."""
        assert helpers.ny_today() == helpers.ny_now().date()


class TestResponseCallback:
    """Content-type dispatch in ``response_callback``."""

    def test_json(self):
        """A JSON content type deserializes the body."""
        response = FakeResponse("application/json", {"a": 1})

        assert asyncio.run(helpers.response_callback(response, None)) == {"a": 1}

    def test_text(self):
        """A text content type returns the decoded body."""
        response = FakeResponse("text/csv", "a,b\n1,2")

        assert asyncio.run(helpers.response_callback(response, None)) == "a,b\n1,2"

    def test_bytes(self):
        """Any other content type returns raw bytes."""
        response = FakeResponse("application/octet-stream", b"\x00\x01")

        assert asyncio.run(helpers.response_callback(response, None)) == b"\x00\x01"


class TestGetCboeData:
    """Cache and no-cache request paths."""

    def test_uses_cached_session(self):
        """With use_cache, the request goes through a session on the shared cache."""

        @asynccontextmanager
        async def shared_cache():
            yield "backend"

        session = FakeCachedSession(FakeResponse("application/json", {"ok": True}))

        with (
            patch.object(helpers, "amake_request") as mock_request,
            patch(
                "aiohttp_client_cache.session.CachedSession", return_value=session
            ) as cached_session,
            patch.object(helpers, "cache_backend", shared_cache),
        ):
            result = asyncio.run(helpers.get_cboe_data("https://cboe.test/a.json"))

        assert result == {"ok": True}
        assert session.closed is True
        cached_session.assert_called_once_with(cache="backend")
        mock_request.assert_not_called()

    def test_a_failed_request_raises_and_lets_go_of_the_cache(self):
        """The cache is released however the request ends."""
        released = []

        @asynccontextmanager
        async def shared_cache():
            try:
                yield "backend"
            finally:
                released.append(True)

        class BrokenSession(FakeCachedSession):
            async def get(self, url, **kwargs):
                raise TimeoutError("cboe is down")

        session = BrokenSession(FakeResponse("application/json", {}))

        with (
            patch("aiohttp_client_cache.session.CachedSession", return_value=session),
            patch.object(helpers, "cache_backend", shared_cache),
            pytest.raises(TimeoutError),
        ):
            asyncio.run(helpers.get_cboe_data("https://cboe.test/a.json"))

        assert released == [True]
        assert session.closed is True

    def test_bypasses_cache(self):
        """Without use_cache, the request goes straight through amake_request."""
        with (
            patch.object(
                helpers, "amake_request", new=AsyncMock(return_value={"ok": False})
            ) as mock_request,
            patch.object(helpers, "cache_backend") as shared_cache,
        ):
            result = asyncio.run(
                helpers.get_cboe_data("https://cboe.test/a.json", use_cache=False)
            )

        assert result == {"ok": False}
        mock_request.assert_awaited_once()
        shared_cache.assert_not_called()


class TestDirectories:
    """Directory parsing helpers."""

    def test_company_directory(self):
        """The company CSV is renamed and indexed by symbol."""
        csv = (
            b"Company Name, Stock Symbol, DPM Name, Post/Station\n"
            b"APPLE INC,AAPL,Market Maker,1\n"
        )

        with patch.object(helpers, "get_cboe_data", new=AsyncMock(return_value=csv)):
            directory = asyncio.run(helpers.get_company_directory())

        assert directory.index.tolist() == ["AAPL"]
        assert directory.loc["AAPL", "name"] == "APPLE INC"
        assert directory.loc["AAPL", "dpm_name"] == "Market Maker"

    def test_au_index_directory(self):
        """CXA definitions are mapped onto the global directory schema."""
        payload = {
            "data": [
                {
                    "symbol": "X2C",
                    "short_name": "CXA 200 Price Return Index",
                    "long_name": "Cboe Australia 200 Price Return Index",
                    "launch_date": "20171204",
                    "series": "CXA 200",
                }
            ]
        }

        with patch.object(
            helpers, "get_cboe_data", new=AsyncMock(return_value=payload)
        ):
            directory = asyncio.run(helpers.get_au_index_directory())

        assert directory.loc[0, "index_symbol"] == "X2C"
        assert directory.loc[0, "currency"] == "AUD"
        assert directory.loc[0, "source"] == "au_proprietary_index"

    def test_index_directory_merges_jurisdictions(self):
        """Morningstar rows are dropped, keys pruned, and CXA rows appended."""
        us_eu = [
            {
                "index_symbol": "BUK100P",
                "name": "Cboe UK 100",
                "source": "eu_proprietary_index",
                "mkt_data_delay": 15,
                "featured": True,
                "featured_order": 1,
                "display": True,
            },
            {
                "index_symbol": "MSTAR",
                "name": "Morningstar",
                "source": "morningstar",
                "featured": False,
                "featured_order": 2,
                "display": False,
            },
        ]
        au = DataFrame(
            [
                {
                    "index_symbol": "X2C",
                    "name": "CXA 200",
                    "currency": "AUD",
                    "source": "au_proprietary_index",
                }
            ]
        )

        catalog = DataFrame(
            [
                {
                    "index_symbol": "BUK100P",
                    "agent_classification": "CO",
                    "channel": "CGI",
                }
            ]
        )

        with (
            patch.object(helpers, "get_cboe_data", new=AsyncMock(return_value=us_eu)),
            patch.object(
                helpers, "get_au_index_directory", new=AsyncMock(return_value=au)
            ),
            patch.object(
                helpers, "get_global_indices_feed", new=AsyncMock(return_value=catalog)
            ),
        ):
            directory = asyncio.run(helpers.get_index_directory())

        assert directory["index_symbol"].tolist() == ["BUK100P", "X2C"]
        assert "featured" not in directory.columns
        assert "display" not in directory.columns
        assert directory.loc[1, "mkt_data_delay"] is None
        assert directory.loc[0, "channel"] == "CGI"
        assert directory.loc[1, "channel"] is None


class TestListFutures:
    """Futures root listing."""

    def test_drops_sort_order(self):
        """The presentation-only sort_order key is removed."""
        payload = {"data": [{"future_root": "VX", "sort_order": 1}]}

        with patch.object(
            helpers, "get_cboe_data", new=AsyncMock(return_value=payload)
        ):
            futures = asyncio.run(helpers.list_futures())

        assert futures == [{"future_root": "VX"}]


class TestSettlementPrices:
    """URL selection and parsing for settlement prices."""

    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            ({}, "https://www.cboe.com/us/futures/market_statistics/settlement/csv"),
            (
                {"options": True},
                "https://www.cboe.com/us/futures/market_statistics/settlement/csv?options=t",
            ),
            (
                {"settlement_date": date(2024, 6, 27)},
                "https://www.cboe.com/us/futures/market_statistics/settlement/csv?dt=2024-06-27",
            ),
            (
                {"settlement_date": date(2024, 6, 27), "options": True},
                "https://www.cboe.com/us/futures/market_statistics/settlement/csv?options=t&dt=2024-06-27",
            ),
            (
                {"archives": True},
                "https://cdn.cboe.com/resources/futures/archive/volume-and-price/CFE_FinalSettlement_Archive.csv",
            ),
            (
                {"final_settlement": True},
                "https://www.cboe.com/us/futures/market_statistics/final_settlement_prices/csv/",
            ),
        ],
    )
    def test_url_selection(self, kwargs, expected):
        """Each flag combination resolves to its documented endpoint."""
        csv = "Product,Symbol,Expiration Date,Price\nVX,VX/N4,2024-06-27,12.5\n"
        mock = AsyncMock(return_value=csv)

        with patch.object(helpers, "get_cboe_data", new=mock):
            data = asyncio.run(helpers.get_settlement_prices(**kwargs))

        assert mock.await_args.args[0] == expected
        assert data["expiration"].tolist() == ["2024-06-27"]
        assert data.columns.tolist()[:4] == ["product", "symbol", "expiration", "price"]

    def test_empty_response(self):
        """An empty CSV yields an empty frame."""
        with patch.object(
            helpers, "get_cboe_data", new=AsyncMock(return_value="Product,Price\n")
        ):
            data = asyncio.run(helpers.get_settlement_prices())

        assert data.empty

    def test_session_stamp_is_anchored_to_new_york(self):
        """The live settlement session is stamped with the New York date."""
        csv = "Product,Symbol,Expiration Date,Price\nVX,VX/N4,2026-07-01,12.5\n"

        with (
            patch.object(helpers, "get_cboe_data", new=AsyncMock(return_value=csv)),
            patch.object(helpers, "ny_today", return_value=date(2026, 7, 1)),
        ):
            data = asyncio.run(helpers.get_settlement_prices())

        assert data["settlement_date"].tolist() == ["2026-07-01"]


class TestChoices:
    """Widget dropdown choice builders."""

    def test_index_choices(self, index_directory):
        """Every index in the directory becomes a label/value pair."""
        with patch.object(
            helpers, "get_index_directory", new=AsyncMock(return_value=index_directory)
        ):
            choices = asyncio.run(helpers.get_index_choices())

        assert choices == [
            {"label": "BUK100P - Cboe UK 100", "value": "BUK100P"},
            {"label": "AAVE10RP - Cboe Apple 10 Index", "value": "AAVE10RP"},
            {"label": "X2C - CXA 200 Price Return Index", "value": "X2C"},
        ]

    def test_constituent_choices_intersect_supported_symbols(self, index_directory):
        """Only the European and CXA symbols the model accepts are offered."""
        with patch.object(
            helpers, "get_index_directory", new=AsyncMock(return_value=index_directory)
        ):
            choices = asyncio.run(helpers.get_eu_index_choices())

        assert choices == [
            {"label": "BUK100P - Cboe UK 100", "value": "BUK100P"},
            {"label": "X2C - CXA 200 Price Return Index", "value": "X2C"},
        ]

    def test_equity_choices_skip_missing_symbols(self, company_directory):
        """Rows with a non-string symbol are dropped."""
        directory = company_directory.copy()
        directory.loc[float("nan"), "name"] = "BROKEN ROW"

        with patch.object(
            helpers, "get_company_directory", new=AsyncMock(return_value=directory)
        ):
            choices = asyncio.run(helpers.get_equity_choices())

        assert [c["value"] for c in choices] == ["AAPL", "SPY"]
        assert choices[0]["label"] == "AAPL - APPLE INC"


class TestAuConstituents:
    """CXA daily constituent files."""

    def test_parses_constituent_block(self):
        """The constituent block is located and the footer rows dropped."""
        csv = (
            "Net Change,Close,Index Symbol\n"
            "-0.008,1690.87,X2C\n"
            ",,\n"
            "Constituent Name,Closing Price,SEDOL Code,ISIN Code,Symbol,Weight,GICS\n"
            "BHP Group Ltd,42.5,5974437,AU000000BHP4,BHP,0.11176,15104020\n"
            "Dividends,,,,,,\n"
        )

        with patch.object(helpers, "get_cboe_data", new=AsyncMock(return_value=csv)):
            rows = asyncio.run(helpers.get_au_index_constituents("X2C"))

        assert len(rows) == 1
        assert rows[0]["Symbol"] == "BHP"
        assert rows[0]["Weight"] == "0.11176"

    def test_decodes_bytes_and_selects_session(self):
        """A bytes body is decoded and 'sod' reads the PREDICT file."""
        csv = (
            b"Close\n1690.87\n,,\nConstituent Name,Symbol,Weight\nBHP Group Ltd,BHP,1\n"
        )
        mock = AsyncMock(return_value=csv)

        with patch.object(helpers, "get_cboe_data", new=mock):
            rows = asyncio.run(helpers.get_au_index_constituents("X2C", session="sod"))

        assert rows[0]["Symbol"] == "BHP"
        assert mock.await_args.args[0].endswith("PREDICT_X2C.csv")

    def test_missing_block_raises(self):
        """A file with no constituent header raises."""
        from openbb_core.provider.utils.errors import EmptyDataError

        with (
            patch.object(
                helpers, "get_cboe_data", new=AsyncMock(return_value="Close\n1690.87\n")
            ),
            pytest.raises(EmptyDataError, match="No constituent data"),
        ):
            asyncio.run(helpers.get_au_index_constituents("X2C"))


class TestIndexHistoryFiles:
    """The published per-symbol daily history files."""

    def test_ohlc_series(self):
        """A volatility index file is parsed as OHLC."""
        csv = "DATE,OPEN,HIGH,LOW,CLOSE\n01/02/1990,17.24,17.24,17.24,17.24\n"

        with patch.object(helpers, "get_cboe_data", new=AsyncMock(return_value=csv)):
            rows = asyncio.run(helpers.get_index_history("^VIX"))

        assert rows == [
            {
                "date": "01/02/1990",
                "open": "17.24",
                "high": "17.24",
                "low": "17.24",
                "close": "17.24",
            }
        ]

    def test_close_only_series_is_renamed(self):
        """A symbol-named price column is renamed to 'close'."""
        csv = b"DATE,SPX\n01/02/1975,70.23\n"

        with patch.object(helpers, "get_cboe_data", new=AsyncMock(return_value=csv)):
            rows = asyncio.run(helpers.get_index_history("SPX"))

        assert rows == [{"date": "01/02/1975", "close": "70.23"}]

    def test_skips_blank_rows(self):
        """Trailing blank rows are dropped."""
        csv = "DATE,SPX\n01/02/1975,70.23\n,\n"

        with patch.object(helpers, "get_cboe_data", new=AsyncMock(return_value=csv)):
            rows = asyncio.run(helpers.get_index_history("SPX"))

        assert len(rows) == 1

    def test_unpublished_symbol_raises(self):
        """A non-CSV body raises."""
        from openbb_core.provider.utils.errors import EmptyDataError

        with (
            patch.object(
                helpers, "get_cboe_data", new=AsyncMock(return_value="<html>404</html>")
            ),
            pytest.raises(EmptyDataError, match="No published history"),
        ):
            asyncio.run(helpers.get_index_history("NOPE"))

    def test_header_only_raises(self):
        """A file with a header and no rows raises."""
        from openbb_core.provider.utils.errors import EmptyDataError

        with (
            patch.object(
                helpers, "get_cboe_data", new=AsyncMock(return_value="DATE,SPX\n")
            ),
            pytest.raises(EmptyDataError, match="No published history"),
        ):
            asyncio.run(helpers.get_index_history("SPX"))


class TestGlobalIndicesFeed:
    """The Global Indices definition feed catalog."""

    def test_parses_channels(self):
        """Symbol, classification, and channel are retained."""
        csv = (
            "Symbol,Description,Agent Classification,Channel,Time and Date of Capture\n"
            ".MSDXUTPU,Morningstar Developed,MS,MSTAR,2026-07-24 15:38:06 CDT\n"
            "BXM,Cboe S&P 500 BuyWrite,CO,CGI,2026-07-24 15:38:06 CDT\n"
        )

        with patch.object(helpers, "get_cboe_data", new=AsyncMock(return_value=csv)):
            catalog = asyncio.run(helpers.get_global_indices_feed())

        assert catalog.columns.tolist() == [
            "index_symbol",
            "agent_classification",
            "channel",
        ]
        assert catalog["channel"].tolist() == ["MSTAR", "CGI"]

    def test_decodes_bytes(self):
        """A bytes body is decoded before parsing."""
        csv = (
            b"Symbol,Description,Agent Classification,Channel\n"
            b"BXM,Cboe S&P 500 BuyWrite,CO,CGI\n"
        )

        with patch.object(helpers, "get_cboe_data", new=AsyncMock(return_value=csv)):
            catalog = asyncio.run(helpers.get_global_indices_feed())

        assert catalog["index_symbol"].tolist() == ["BXM"]


class TestIndexDocuments:
    """The bundled index documents catalog."""

    def test_full_catalog(self):
        """With no symbol the whole catalog is returned."""
        catalog = asyncio.run(helpers.get_index_documents())

        assert catalog
        assert {"category", "title", "url"} <= set(catalog[0])
        assert any(d["category"] == "Methodology" for d in catalog)

    def test_symbol_scopes_constituents(self):
        """Symbol-scoped documents include that symbol's constituents file."""
        with patch.object(
            helpers, "amake_request", new=AsyncMock(side_effect=OSError("404"))
        ):
            docs = asyncio.run(helpers.get_index_documents("SPBFA"))

        titles = [d["title"] for d in docs]

        assert "SPBFA Constituents" in titles
        assert "BXMU Constituents" not in titles

    def test_factsheet_prepended_when_published(self):
        """A published factsheet is prepended to the symbol's documents."""
        with patch.object(helpers, "amake_request", new=AsyncMock(return_value=200)):
            docs = asyncio.run(helpers.get_index_documents("^BXM"))

        assert docs[0]["category"] == "Factsheet"
        assert docs[0]["url"].endswith("CboeGlobalIndices_BXM-Index.pdf")

    def test_factsheet_omitted_when_absent(self):
        """No factsheet is added when Cboe does not publish one."""
        with patch.object(
            helpers, "amake_request", new=AsyncMock(side_effect=OSError("403"))
        ):
            docs = asyncio.run(helpers.get_index_documents("VIX"))

        assert not [d for d in docs if d["title"].endswith("Index Factsheet")]

    def test_status_callback(self):
        """The probe callback passes 200 through and raises otherwise."""
        ok = type("R", (), {"status": 200, "url": "u"})()
        bad = type("R", (), {"status": 403, "url": "u"})()

        assert asyncio.run(helpers._status_callback(ok, None)) == 200

        with pytest.raises(OSError, match="403"):
            asyncio.run(helpers._status_callback(bad, None))


class TestIndexDocumentViewer:
    """Cover the document choices and the PDF download behind the viewer."""

    CATALOG = [
        {
            "category": "Governance",
            "title": "Cboe Index Policies & Practices",
            "url": "https://cdn.cboe.com/a.pdf",
        },
        {"category": "Methodology", "title": "No Link", "url": ""},
    ]

    def test_choices_label_each_document(self):
        """Each catalogued document becomes a labelled choice."""
        with patch.object(
            helpers, "get_index_documents", AsyncMock(return_value=self.CATALOG)
        ):
            choices = asyncio.run(helpers.get_document_choices("BXM"))

        assert choices == [
            {
                "label": "Governance - Cboe Index Policies & Practices",
                "value": "https://cdn.cboe.com/a.pdf",
                "extraInfo": {"description": "Cboe Index Policies & Practices"},
            }
        ]

    def test_choices_pass_the_symbol_through(self):
        """The symbol scopes the catalog the choices are built from."""
        catalog = AsyncMock(return_value=[])

        with patch.object(helpers, "get_index_documents", catalog):
            asyncio.run(helpers.get_document_choices("BXM"))

        catalog.assert_awaited_once_with("BXM")

    def test_document_urls_are_validated(self):
        """Only https URLs on a Cboe document host pass."""
        assert helpers.is_cboe_document_url("https://cdn.cboe.com/a.pdf") is True
        assert helpers.is_cboe_document_url("http://cdn.cboe.com/a.pdf") is False
        assert helpers.is_cboe_document_url("https://evil.example/a.pdf") is False
        assert (
            helpers.is_cboe_document_url("https://cdn.cboe.com.evil.example/a.pdf")
            is False
        )
        assert (
            helpers.is_cboe_document_url("https://evil.example/cdn.cboe.com") is False
        )
        assert helpers.is_cboe_document_url(42) is False

    def test_download_refuses_foreign_hosts(self):
        """A URL off the allowlist is refused before any request is made."""
        with pytest.raises(OSError, match="Refusing"):
            asyncio.run(helpers.download_index_document("https://evil.example/a.pdf"))

    def test_download_is_base64(self):
        """The PDF body is read through the callback and base64-encoded."""

        class Response:
            """A stand-in carrying a PDF body."""

            async def read(self):
                """Return the raw body."""
                return b"%PDF-1.4 body"

        async def request(url, **kwargs):
            """Invoke the response callback the helper supplies."""
            return await kwargs["response_callback"](Response(), None)

        with patch(
            "openbb_core.provider.utils.helpers.amake_request", side_effect=request
        ):
            encoded = asyncio.run(
                helpers.download_index_document("https://cdn.cboe.com/a.pdf")
            )

        assert encoded == "JVBERi0xLjQgYm9keQ=="

    def test_open_returns_the_viewer_payload(self):
        """A successful download carries the data format and filename."""
        with patch.object(
            helpers, "download_index_document", AsyncMock(return_value="QUJD")
        ):
            payload = asyncio.run(
                helpers.open_index_document("https://cdn.cboe.com/BXM.pdf")
            )

        assert payload == {
            "content": "QUJD",
            "data_format": {"data_type": "pdf", "filename": "BXM.pdf"},
        }

    def test_open_falls_back_to_a_generic_filename(self):
        """A URL ending in a separator still names the document."""
        with patch.object(
            helpers, "download_index_document", AsyncMock(return_value="QUJD")
        ):
            payload = asyncio.run(helpers.open_index_document("https://cdn.cboe.com/"))

        assert payload["data_format"]["filename"] == "document.pdf"

    def test_open_reports_a_failure(self):
        """A failed download is surfaced as an error payload."""
        with patch.object(
            helpers,
            "download_index_document",
            AsyncMock(side_effect=OSError("404")),
        ):
            payload = asyncio.run(
                helpers.open_index_document("https://cdn.cboe.com/a.pdf")
            )

        assert payload["error_type"] == "download_error"
        assert "404" in payload["content"]


async def _empty():
    """Yield no keys at all."""
    for key in ():
        yield key


async def _keys(count):
    """Yield as many keys as the cache is said to hold."""
    for index in range(count):
        yield f"key{index}"


class _Cursor:
    """Stand in for the cursor of an aiosqlite statement."""

    def __init__(self, row):
        self._row = row

    async def fetchone(self):
        """Return the one row there is."""
        return self._row

    async def close(self):
        """Close the cursor."""


class _Database:
    """Stand in for the aiosqlite connection: it reports a size and logs what it is told."""

    def __init__(self, size=0, page_size=1, unused_pages=0):
        self.size = size
        self.page_size = page_size
        self.unused_pages = unused_pages
        self.statements: list = []

    async def execute(self, statement):
        """Record the statement and answer the pragmas the cache asks."""
        self.statements.append(statement)
        answers = {
            "PRAGMA page_count": (self.size // self.page_size,),
            "PRAGMA page_size": (self.page_size,),
            "PRAGMA freelist_count": (self.unused_pages,),
            "PRAGMA journal_mode=WAL": ("wal",),
        }

        return _Cursor(answers.get(statement, (0, -1, -1)))


def _stores(database, held=0, keys=_empty, bulk_delete=None):
    """Stand in for the SQLite stores of the cache, on a fake database."""

    @asynccontextmanager
    async def get_connection(commit=False):
        yield database

    return SimpleNamespace(
        close=AsyncMock(),
        delete_expired_responses=AsyncMock(),
        responses=SimpleNamespace(
            size=AsyncMock(return_value=held),
            keys=keys,
            bulk_delete=bulk_delete or AsyncMock(),
            get_connection=get_connection,
        ),
    )


class TestResponseCache:
    """The on-disk cache is bounded by age and by size."""

    def test_each_endpoint_keeps_for_as_long_as_it_stays_good(self):
        """A quote feed must not be held for as long as a directory."""
        from aiohttp_client_cache.cache_control import get_url_expiration

        expiry = {
            "https://ww2.cboe.com/json/bats_eu/book/BUK100P": 60,
            "https://ww2.cboe.com/education/tools/trade-optimizer"
            "/trade-optimizer-data/?symbol=SPY": 600,
            "https://cdn.cboe.com/api/global/us_indices/definitions"
            "/GlobalIndices.csv": 900,
            "https://cdn.cboe.com/api/global/us_indices/daily_prices"
            "/VIX_History.csv": 3600 * 6,
            "https://www.cboe.com/us/options/symboldir"
            "/equity_index_options/?download=csv": 3600 * 24,
        }

        for url, seconds in expiry.items():
            assert get_url_expiration(url, helpers.CACHE_TTL) == seconds, url

    def test_an_expired_response_is_deleted_not_just_ignored(self):
        """An expiry alone leaves the row behind and the file grows forever."""
        backend = _stores(_Database())

        asyncio.run(helpers._sweep(backend))

        backend.delete_expired_responses.assert_awaited_once()

    def test_a_file_over_the_limit_drops_its_oldest(self):
        """What the sweep leaves over the limit is trimmed by the overshoot."""
        database = _Database(size=1000, unused_pages=1)
        dropped: list = []

        async def bulk_delete(keys):
            dropped.append(len(keys))
            database.size = 100

        backend = _stores(
            database, held=10, keys=lambda: _keys(10), bulk_delete=bulk_delete
        )

        with patch.object(helpers, "CACHE_MAX_BYTES", 500):
            asyncio.run(helpers._sweep(backend))

        assert dropped == [5]

    def test_a_sweep_with_nothing_left_to_drop_stops(self):
        """An oversized file whose entries are already gone is not re-trimmed."""
        backend = _stores(_Database(size=1000), held=0)

        with patch.object(helpers, "CACHE_MAX_BYTES", 500):
            asyncio.run(helpers._sweep(backend))

        backend.responses.bulk_delete.assert_not_awaited()

    def test_a_file_under_the_limit_is_left_alone(self):
        """Nothing is dropped from a file that already fits."""
        backend = _stores(_Database(size=100), held=10, keys=lambda: _keys(10))

        with patch.object(helpers, "CACHE_MAX_BYTES", 500):
            asyncio.run(helpers._sweep(backend))

        backend.responses.bulk_delete.assert_not_awaited()

    def test_the_size_is_the_pages_the_file_holds(self):
        """The size comes from SQLite, which counts pages still waiting in the log."""
        database = _Database(size=8192, page_size=4096)

        assert asyncio.run(helpers._size(_stores(database))) == 8192
        assert database.statements == ["PRAGMA page_count", "PRAGMA page_size"]

    def test_a_vacuum_checkpoints_the_log(self):
        """Vacuumed pages only reach the disk, and free its space, once checkpointed."""
        database = _Database(unused_pages=3)

        asyncio.run(helpers._vacuum(_stores(database)))

        assert database.statements == [
            "PRAGMA freelist_count",
            "VACUUM",
            "PRAGMA wal_checkpoint(TRUNCATE)",
        ]

    def test_a_vacuum_with_nothing_to_give_back_does_not_run(self):
        """Every process sweeps as it starts, and a vacuum rewrites the whole file."""
        database = _Database(unused_pages=0)

        asyncio.run(helpers._vacuum(_stores(database)))

        assert database.statements == ["PRAGMA freelist_count"]


class TestCacheLifecycle:
    """One connection for every request, opened by the first and closed by the last."""

    @staticmethod
    def _stores(built):
        """Stand in for the SQLite stores, recording each one that is opened."""

        def new_backend():
            stores = _stores(_Database())
            built.append(stores)

            return stores

        return patch.object(helpers, "_new_backend", new_backend)

    @staticmethod
    async def _use_the_cache():
        async with helpers.cache_backend():
            pass

    def test_requests_on_other_loops_share_one_connection(self, cache_file):
        """A request on another loop is served by the connection already open."""
        built: list = []
        holding, release = threading.Event(), threading.Event()

        async def hold():
            async with helpers.cache_backend():
                holding.set()

                while not release.is_set():
                    await asyncio.sleep(0.005)

        with self._stores(built):
            holder, outcome = _on_a_thread(hold)

            try:
                assert holding.wait(10)
                asyncio.run(self._use_the_cache())

                assert len(built) == 1
                built[0].close.assert_not_awaited()
            finally:
                release.set()
                holder.join(10)

        assert "error" not in outcome
        built[0].close.assert_awaited_once()

    def test_the_last_request_to_finish_closes_it(self, cache_file):
        """Nothing stays open while nothing is running, and a closed one is not reused."""
        built: list = []

        with self._stores(built):
            asyncio.run(self._use_the_cache())
            asyncio.run(self._use_the_cache())

        assert len(built) == 2
        assert all(stores.close.await_count == 1 for stores in built)

    def test_a_request_that_fails_still_lets_go(self, cache_file):
        """An error in the request must not leave the connection open for ever."""
        built: list = []

        async def fails():
            async with helpers.cache_backend():
                raise ValueError("the request failed")

        with self._stores(built), pytest.raises(ValueError):
            asyncio.run(fails())

        built[0].close.assert_awaited_once()

    def test_a_cancelled_request_still_lets_go(self, cache_file):
        """Cancelling the request must not leave the connection open for ever."""
        built: list = []

        async def scenario():
            inside = asyncio.Event()

            async def hold():
                async with helpers.cache_backend():
                    inside.set()
                    await asyncio.sleep(30)

            task = asyncio.create_task(hold())
            await asyncio.wait_for(inside.wait(), timeout=10)
            task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await task

        with self._stores(built):
            asyncio.run(scenario())

        built[0].close.assert_awaited_once()

    def test_a_close_is_not_lost_when_the_request_is_cancelled_again(self, cache_file):
        """Ending the loop on a request that is closing must not leave the cache open.

        ``asyncio.run`` cancels what is left when its main coroutine returns. A close
        handed to a task that had not yet begun was lost with it, and the
        connection, and its thread, stayed open.
        """
        built: list = []

        async def scenario():
            inside = asyncio.Event()

            async def hold():
                async with helpers.cache_backend():
                    inside.set()
                    await asyncio.sleep(30)

            task = asyncio.create_task(hold())
            await asyncio.wait_for(inside.wait(), timeout=10)
            task.cancel()
            # Returns at once: the request has not yet reached its close.

        with self._stores(built):
            asyncio.run(scenario())

            deadline = time.monotonic() + 10

            while helpers._stores is not None and time.monotonic() < deadline:
                time.sleep(0.01)

        assert helpers._stores is None
        built[0].close.assert_awaited_once()

    def test_the_file_is_swept_once_and_before_anything_opens_it(self, cache_file):
        """The sweep vacuums the file, so no request may be in it while it runs."""
        order: list = []

        async def sweep():
            order.append("sweep")

        def new_backend():
            order.append("open")

            return _stores(_Database())

        with (
            patch.object(helpers, "_swept", False),
            patch.object(helpers, "_sweep_file", sweep),
            patch.object(helpers, "_new_backend", new_backend),
        ):
            asyncio.run(self._use_the_cache())
            asyncio.run(self._use_the_cache())

        assert order == ["sweep", "open", "open"]

    def test_a_failed_sweep_is_not_retried_and_does_not_stop_requests(self, cache_file):
        """A sweep that fails is logged, and the requests carry on."""
        built: list = []
        sweep = AsyncMock(side_effect=Exception("unreadable"))

        with (
            patch.object(helpers, "_swept", False),
            patch.object(helpers, "_sweep", sweep),
            self._stores(built),
        ):
            asyncio.run(self._use_the_cache())
            asyncio.run(self._use_the_cache())

        sweep.assert_awaited_once()
        assert len(built) == 3  # the sweep's own connection, then one per use

    def test_the_sweep_connection_is_closed_whatever_the_sweep_does(self, cache_file):
        """A sweep that raises, or a close that raises, is logged and goes no further."""
        backend = SimpleNamespace(close=AsyncMock(side_effect=Exception("locked")))

        with (
            patch.object(helpers, "_new_backend", return_value=backend),
            patch.object(
                helpers, "_sweep", new=AsyncMock(side_effect=Exception("boom"))
            ),
        ):
            asyncio.run(helpers._sweep_file())

        backend.close.assert_awaited_once()

    def test_a_close_that_fails_is_logged_not_raised(self, cache_file):
        """A close error must not surface as the request's failure."""
        stores = _stores(_Database())
        stores.close = AsyncMock(side_effect=Exception("locked"))

        with patch.object(helpers, "_new_backend", return_value=stores):
            asyncio.run(self._use_the_cache())

        stores.close.assert_awaited_once()


class TestCacheLoop:
    """The connection lives on one loop of its own, whichever loop asks."""

    def test_stores_are_reached_on_the_cache_thread(self):
        """Every operation runs on the one thread the connection belongs to."""
        threads: list = []

        async def read(key):
            threads.append(threading.current_thread().name)

            return f"value of {key}"

        stores = SimpleNamespace(responses=SimpleNamespace(read=read))

        async def ask(key):
            return await helpers._store_call("responses", "read", key)

        with patch.object(helpers, "_stores", stores):
            first = asyncio.run(ask("a"))
            thread, outcome = _on_a_thread(lambda: ask("b"))
            thread.join(10)

        assert first == "value of a"
        assert outcome == {"result": "value of b"}
        assert threads == ["cboe-cache", "cboe-cache"]

    def test_what_a_store_yields_comes_back_as_a_list(self):
        """Keys and values cannot be iterated from another loop, so are gathered."""

        async def keys():
            for key in ("a", "b"):
                yield key

        stores = SimpleNamespace(redirects=SimpleNamespace(keys=keys))

        with patch.object(helpers, "_stores", stores):
            keys_found = asyncio.run(helpers._store_call("redirects", "keys"))

        assert keys_found == ["a", "b"]

    def test_an_error_in_a_store_reaches_the_caller(self):
        """A failure on the cache loop is the failure of the request that asked."""
        stores = SimpleNamespace(
            responses=SimpleNamespace(read=AsyncMock(side_effect=OSError("disk")))
        )

        with patch.object(helpers, "_stores", stores), pytest.raises(OSError):
            asyncio.run(helpers._store_call("responses", "read", "a"))

    def test_the_connection_does_one_thing_at_a_time(self):
        """No read may be open while another request's write starts.

        The connection is held for reading by a read that is still open, and
        asking to write then is refused at once, not waited out, if another
        process is writing.
        """
        running = 0
        most_at_once = 0

        async def read(key):
            nonlocal running, most_at_once

            running += 1
            most_at_once = max(most_at_once, running)
            await asyncio.sleep(0.002)
            running -= 1

            return key

        stores = SimpleNamespace(
            responses=SimpleNamespace(read=read, write=read),
            redirects=SimpleNamespace(read=read),
        )

        async def burst():
            return await asyncio.gather(
                *(
                    helpers._store_call(table, method, str(n))
                    for n in range(10)
                    for table, method in (
                        ("responses", "read"),
                        ("responses", "write"),
                        ("redirects", "read"),
                    )
                )
            )

        with (
            patch.object(helpers, "_stores", stores),
            patch.object(helpers, "_swept", True),
        ):
            workers = [_on_a_thread(burst) for _ in range(4)]

            for worker, _ in workers:
                worker.join(30)

        assert all("error" not in outcome for _, outcome in workers)
        assert most_at_once == 1

    def test_a_forked_child_forgets_the_parents_loop(self):
        """The loop's thread does not survive a fork, so the child must not wait on it."""
        stores = SimpleNamespace(close=AsyncMock())
        inherited: list = []

        with (
            patch.object(helpers, "_cache_lock", threading.Lock()),
            patch.object(helpers, "_cache_loop", "parents loop"),
            patch.object(helpers, "_cache_guard", "parents guard"),
            patch.object(helpers, "_cache_users", 3),
            patch.object(helpers, "_stores", stores),
            patch.object(helpers, "_inherited", inherited),
        ):
            helpers._forget_cache_loop()

            assert helpers._cache_loop is None
            assert helpers._cache_guard is None
            assert helpers._cache_users == 0
            assert helpers._stores is None

        # Kept, not closed: closing it in the child could undo the parent's work.
        assert inherited == [stores]
        stores.close.assert_not_called()

    def test_a_forked_child_is_set_to_forget_the_loop(self):
        """Where processes fork, a child is told to start over when it is born."""
        register = MagicMock()

        with patch.object(helpers, "os", SimpleNamespace(register_at_fork=register)):
            helpers._forget_after_fork()

        register.assert_called_once_with(after_in_child=helpers._forget_cache_loop)

    def test_a_platform_that_cannot_fork_has_nothing_to_set(self):
        """Windows has no ``os.register_at_fork``, and has no forked children either."""
        with patch.object(helpers, "os", SimpleNamespace()):
            helpers._forget_after_fork()

    @pytest.mark.skipif(not hasattr(os, "fork"), reason="needs os.fork")
    def test_a_forked_child_can_make_a_cached_request(self, cache_file, server):
        """A forked server worker must not hang waiting on the parent's cache loop."""
        import signal

        url = f"{server.url}/forked.json"
        asyncio.run(helpers.get_cboe_data(f"{server.url}/before-the-fork.json"))
        pid = os.fork()

        if pid == 0:  # pragma: no cover - runs in the child
            signal.alarm(20)
            code = 1

            try:
                result = asyncio.run(helpers.get_cboe_data(url))
                code = 0 if result == {"path": "/forked.json"} else 2
            finally:
                os._exit(code)

        _, status = os.waitpid(pid, 0)

        assert os.waitstatus_to_exitcode(status) == 0
        assert asyncio.run(helpers.get_cboe_data(url)) == {"path": "/forked.json"}


class TestSharedAcrossEventLoops:
    """Callers on separate threads, each with a loop of its own, share one cache.

    Core's ``run_async`` gives every synchronous call a thread and a loop of its
    own. The cache used to hand them all one backend, whose lock and connection
    belong to one loop: some callers failed with ``Lock is bound to a different
    event loop`` or ``threads can only be started once``, others waited for ever.
    """

    def test_a_repeated_request_is_served_from_the_file(self, cache_file, server):
        """The second request never reaches the server."""
        url = f"{server.url}/a.json"

        assert asyncio.run(helpers.get_cboe_data(url)) == {"path": "/a.json"}
        assert asyncio.run(helpers.get_cboe_data(url)) == {"path": "/a.json"}
        assert server.requests == ["/a.json"]

    def test_threads_with_their_own_loops_share_one_cache(self, cache_file, server):
        """Concurrent callers all succeed, and what one fetched the others reuse."""
        threads, rounds, per_loop = 4, 4, 3
        # What is under test is that callers succeed, not how fast, so the limit is
        # for a caller that is stuck. A runner with a slow disk is not one.
        patience = 60

        def wave(label):
            barrier = threading.Barrier(threads)

            async def burst():
                barrier.wait(patience)

                return await asyncio.wait_for(
                    asyncio.gather(
                        *(
                            helpers.get_cboe_data(f"{server.url}/{label}/{n}.json")
                            for n in range(per_loop)
                        )
                    ),
                    timeout=patience,
                )

            workers = [_on_a_thread(burst) for _ in range(threads)]

            for worker, _ in workers:
                worker.join(patience * 2)

            return [outcome for _, outcome in workers]

        for round_number in range(rounds):
            label = f"round{round_number}"
            expected = [{"path": f"/{label}/{n}.json"} for n in range(per_loop)]

            for outcomes in (wave(label), wave(label)):
                assert outcomes == [{"result": expected}] * threads, outcomes

            # Four callers asked for each URL at once, so each was fetched at
            # least once; the second wave found every one of them on disk.
            fetched = [
                path for path in server.requests if path.startswith(f"/{label}/")
            ]
            assert set(fetched) == {path["path"] for path in expected}
            assert len(fetched) <= threads * per_loop

        settled = len(server.requests)
        wave("round0")

        assert len(server.requests) == settled

    def test_an_unreadable_row_does_not_stop_requests(self, cache_file, server, caplog):
        """A file the sweep cannot get through is logged, and still serves requests."""

        async def leave_an_unreadable_row():
            backend = helpers._new_backend()
            await backend.responses.write("unreadable", {"not": "a response"})
            await backend.close()

        asyncio.run(leave_an_unreadable_row())

        with patch.object(helpers, "_swept", False):
            result = asyncio.run(helpers.get_cboe_data(f"{server.url}/a.json"))

        assert result == {"path": "/a.json"}
        assert "Sweeping the Cboe response cache failed" in caplog.text


class TestAcrossProcesses:
    """Separate processes share the cache file without locking each other out.

    Each process has a connection of its own. One whose read was still open when
    another request began to write held the file for reading while it asked to
    write, and SQLite refuses that at once when another process is writing:
    several percent of the requests failed with ``database is locked``.
    """

    def test_processes_sharing_the_file_all_succeed(self, tmp_path, server):
        """Many processes, each with several threads, on one file."""
        processes, threads, rounds, per_round = 12, 4, 12, 8
        worker = Path(__file__).with_name("cache_worker.py")
        environment = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(filter(None, sys.path)),
        }
        command = [
            sys.executable,
            "-W",
            "ignore",
            str(worker),
            server.url,
            str(tmp_path / "shared"),
            str(rounds),
            str(per_round),
            str(threads),
        ]
        started = [
            subprocess.Popen(  # noqa: S603
                command,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(processes)
        ]
        summaries = []

        for process in started:
            stdout, stderr = process.communicate(timeout=120)
            assert process.returncode == 0, stderr
            summaries.append(json.loads(stdout.splitlines()[-1]))

        assert [summary["failures"] for summary in summaries] == [{}] * processes
        assert {summary["succeeded"] for summary in summaries} == {
            threads * rounds * per_round
        }


class TestWriteAheadLogging:
    """Readers and a writer, in one process or in several, do not block each other.

    The cache file is shared by every process that uses Cboe data, and in
    SQLite's default mode a process holding it - to write, or to read - stops
    the others from doing the opposite for as long as it does. One that holds it
    for longer than SQLite will wait fails the request with ``database is
    locked``.
    """

    @staticmethod
    def _journal_mode(tmp_path):
        with closing(sqlite3.connect(tmp_path / "cboe.sqlite")) as database:
            return database.execute("PRAGMA journal_mode").fetchone()[0]

    @staticmethod
    def _held_by_another_process(tmp_path, statements):
        """Hold the cache file the way another process in the middle of work would."""
        database = sqlite3.connect(
            tmp_path / "cboe.sqlite", isolation_level=None, check_same_thread=False
        )

        for statement in statements:
            database.execute(statement).fetchone()

        return database

    def test_the_cache_file_is_put_in_wal_mode(self, cache_file, server):
        """The mode is set on the file, so every process that opens it has it."""
        asyncio.run(helpers.get_cboe_data(f"{server.url}/a.json"))

        assert self._journal_mode(cache_file) == "wal"

    def test_a_hit_is_served_while_another_process_writes(self, cache_file, server):
        """A reader does not wait for a writer, however long it takes."""
        url = f"{server.url}/a.json"
        asyncio.run(helpers.get_cboe_data(url))
        writer = self._held_by_another_process(cache_file, ["BEGIN EXCLUSIVE"])

        async def hit():
            return await asyncio.wait_for(helpers.get_cboe_data(url), timeout=3)

        try:
            assert asyncio.run(hit()) == {"path": "/a.json"}
        finally:
            writer.execute("ROLLBACK")
            writer.close()

        assert server.requests == ["/a.json"]

    def test_a_miss_is_served_while_another_process_reads(self, cache_file, server):
        """A writer does not wait for a reader to finish."""
        asyncio.run(helpers.get_cboe_data(f"{server.url}/a.json"))
        reader = self._held_by_another_process(
            cache_file, ["BEGIN", "SELECT key FROM responses"]
        )

        async def miss():
            return await asyncio.wait_for(
                helpers.get_cboe_data(f"{server.url}/b.json"), timeout=3
            )

        try:
            assert asyncio.run(miss()) == {"path": "/b.json"}
        finally:
            reader.execute("ROLLBACK")
            reader.close()

    def test_each_statement_is_committed_as_it_runs(self, cache_file):
        """The connection must not hold a transaction open between statements."""

        async def isolation_level():
            stores = helpers._new_backend()

            try:
                async with stores.responses.get_connection() as connection:
                    return connection.isolation_level
            finally:
                await stores.close()

        assert asyncio.run(isolation_level()) is None

    def test_a_commit_does_not_wait_for_the_disk(self, cache_file):
        """A commit that waits for the disk holds the write lock for as long as it takes."""
        normal = 1

        async def synchronous():
            stores = helpers._new_backend()

            try:
                async with stores.responses.get_connection() as connection:
                    return await helpers._pragma(connection, "PRAGMA synchronous")
            finally:
                await stores.close()

        assert asyncio.run(synchronous()) == (normal,)

    def test_a_write_cancelled_before_its_commit_leaves_no_lock(self, cache_file):
        """Another process can write at once, whatever became of the write.

        A write is an ``INSERT`` and then, after the event loop has had a turn, a
        ``COMMIT``. Cancelled in between, it used to leave the write lock held.
        """

        async def scenario():
            stores = helpers._new_backend()

            try:
                reached = asyncio.Event()

                async def commit_never_arrives(connection):
                    reached.set()
                    await asyncio.sleep(30)

                with patch("aiosqlite.Connection.commit", commit_never_arrives):
                    write = asyncio.create_task(stores.responses.write("key", "item"))
                    await asyncio.wait_for(reached.wait(), timeout=10)
                    write.cancel()

                    with pytest.raises(asyncio.CancelledError):
                        await write

                with closing(
                    sqlite3.connect(cache_file / "cboe.sqlite", timeout=0)
                ) as another_process:
                    another_process.execute("BEGIN IMMEDIATE")
                    another_process.execute("ROLLBACK")
            finally:
                await stores.close()

        asyncio.run(scenario())

    def test_a_file_that_cannot_be_switched_still_works(self, caplog):
        """A file that stays in its default mode is a slower cache, not a failure."""

        @asynccontextmanager
        async def get_connection(commit=False):
            raise sqlite3.OperationalError("database is locked")
            yield

        stores = SimpleNamespace(
            responses=SimpleNamespace(get_connection=get_connection)
        )

        asyncio.run(helpers._use_wal(stores))

        assert "Could not put the Cboe response cache in WAL mode" in caplog.text

    def test_a_file_that_stays_in_another_mode_is_said_so(self, caplog):
        """A file system that cannot keep the shared memory answers with its old mode."""
        database = _Database()

        async def execute(statement):
            return _Cursor(("delete",))

        database.execute = execute

        asyncio.run(helpers._use_wal(_stores(database)))

        assert "staying in" in caplog.text

    def test_a_sweep_of_a_wal_file_trims_to_the_limit_and_no_further(
        self, cache_file, server
    ):
        """The file on disk lags a vacuum, so the sweep must not size it by that.

        After the first ``VACUUM`` the new, smaller file waits in the log, and the
        file on disk is still its old size. A sweep that believed it went on
        dropping responses that were never in the way.
        """
        asyncio.run(helpers.get_cboe_data(f"{server.url}/seed.json"))
        stored = cache_file / "cboe.sqlite"

        with closing(sqlite3.connect(stored)) as database:
            row = database.execute("SELECT value FROM responses").fetchone()[0]
            database.executemany(
                "INSERT OR REPLACE INTO responses VALUES (?, ?)",
                ((f"filler{number}", row) for number in range(400)),
            )
            database.commit()

        assert self._journal_mode(cache_file) == "wal"
        limit = stored.stat().st_size // 2

        with patch.object(helpers, "CACHE_MAX_BYTES", limit):
            asyncio.run(helpers._sweep_file())

        assert limit // 2 < stored.stat().st_size <= limit
