"""Tests for the HTTP transport."""

import asyncio
import json
from urllib.parse import urlparse

import pytest
from openbb_core.app.model.abstract.error import OpenBBError

from openbb_finra.utils import client


def _run(coroutine):
    """Run a coroutine to completion."""
    return asyncio.run(coroutine)


def _trace_body(rows, total=None, status="success"):
    """Return a TRACE envelope carrying the rows."""
    return json.dumps(
        {
            "status": status,
            "returnBody": {
                "headers": {
                    "Record-Total": [str(len(rows) if total is None else total)]
                },
                "data": json.dumps(rows),
            },
        }
    )


class TestOpenSession:
    """The real session factory applies the core request settings."""

    def test_opens_a_core_session(self, real_open_session):
        """A core client session is returned and can be closed."""
        from openbb_core.provider.utils.client import ClientSession

        async def run():
            session = await real_open_session()

            try:
                return isinstance(session, ClientSession)
            finally:
                await session.close()

        assert _run(run())


class TestDecode:
    """Bodies decode to JSON when they are JSON."""

    def test_empty(self):
        """A blank body is None."""
        assert client._decode("  ") is None

    def test_json(self):
        """JSON decodes."""
        assert client._decode('{"a": 1}') == {"a": 1}

    def test_text(self):
        """Anything else is kept as text."""
        assert client._decode("<html>") == "<html>"


class TestCollectPages:
    """Paged datasets are read completely, including short pages."""

    @staticmethod
    def _fetcher(total, cap=None, calls=None, empty_at=None):
        rows = [{"n": index} for index in range(total)]

        async def fetch(offset, limit):
            if calls is not None:
                calls.append((offset, limit))

            if empty_at is not None and offset >= empty_at:
                return [], total

            size = min(limit, cap) if cap else limit

            return rows[offset : offset + size], total

        return fetch

    def test_single_page(self):
        """A dataset within one page is read with one request."""
        calls: list = []
        rows = _run(client.collect_pages(self._fetcher(3, calls=calls), 10))

        assert [row["n"] for row in rows] == [0, 1, 2]
        assert calls == [(0, 10)]

    def test_empty(self):
        """An empty dataset returns no rows."""
        assert _run(client.collect_pages(self._fetcher(0), 10)) == []

    def test_many_pages(self):
        """Every page is read, in offset order."""
        rows = _run(client.collect_pages(self._fetcher(25), 10, concurrency=3))

        assert [row["n"] for row in rows] == list(range(25))

    def test_short_pages_are_filled(self):
        """A page cut short by a payload cap is completed with more requests."""
        calls: list = []
        rows = _run(client.collect_pages(self._fetcher(25, cap=7, calls=calls), 10))

        assert [row["n"] for row in rows] == list(range(25))
        assert (7, 3) in calls
        assert (17, 3) in calls

    def test_max_rows(self):
        """Reading stops at the row cap."""
        rows = _run(client.collect_pages(self._fetcher(25), 10, max_rows=12))

        assert [row["n"] for row in rows] == list(range(12))

    def test_max_rows_within_first_page(self):
        """A cap below one page is read with one request."""
        calls: list = []
        rows = _run(
            client.collect_pages(self._fetcher(25, calls=calls), 10, max_rows=4)
        )

        assert [row["n"] for row in rows] == [0, 1, 2, 3]
        assert calls == [(0, 4)]

    def test_page_that_runs_dry(self):
        """A page that comes back empty ends that block."""
        rows = _run(client.collect_pages(self._fetcher(25, empty_at=10), 10))

        assert [row["n"] for row in rows] == list(range(10))


class TestQueryApiSession:
    """The Query API pages, totals, and errors are handled."""

    @staticmethod
    def _query(fake_session, response, method="page"):
        fake_session(responder=lambda call: response)

        async def run():
            async with client.query_api_session() as api:
                if method == "partitions":
                    return await api.partitions("otcMarket", "weeklySummary")

                return await api.page("otcMarket", "weeklySummary", {}, 0, 10)

        return _run(run())

    def test_no_content(self, fake_session, response):
        """HTTP 204 is an empty result."""
        assert self._query(fake_session, response(204)) == ([], 0)

    def test_rows_and_total(self, fake_session, response):
        """The record-total header gives the total."""
        response = response(200, '[{"a": 1}]', {"record-total": "42"})

        assert self._query(fake_session, response) == ([{"a": 1}], 42)

    def test_rows_without_total(self, fake_session, response):
        """Without the header the page size is the total."""
        assert self._query(fake_session, response(200, '[{"a": 1}]')) == (
            [{"a": 1}],
            1,
        )

    def test_error_message(self, fake_session, response):
        """The FINRA error message is raised."""
        response = response(400, '{"message": "Sorting is not allowed"}')

        with pytest.raises(OpenBBError, match="HTTP 400: Sorting is not allowed"):
            self._query(fake_session, response)

    def test_error_text(self, fake_session, response):
        """A non-JSON error body is raised as text."""
        with pytest.raises(OpenBBError, match="HTTP 503: unavailable"):
            self._query(fake_session, response(503, "unavailable"))

    def test_unexpected_body(self, fake_session, response):
        """A body that is not a list is rejected."""
        with pytest.raises(OpenBBError, match="unexpected weeklySummary"):
            self._query(fake_session, response(200, '{"a": 1}'))

    def test_partitions(self, fake_session, response):
        """Partitions are returned as lists of key values."""
        body = json.dumps(
            {
                "availablePartitions": [
                    {"partitions": ["2026-08-31", "T1"]},
                    {"partitions": None},
                ]
            }
        )
        result = self._query(fake_session, response(200, body), "partitions")

        assert result == [["2026-08-31", "T1"], []]

    def test_partitions_error(self, fake_session, response):
        """A failed partitions request raises."""
        with pytest.raises(OpenBBError, match="partitions with HTTP 500"):
            self._query(fake_session, response(500, "error"), "partitions")

    def test_session_is_closed(self, fake_session, response):
        """The session closes when the block exits."""
        session = fake_session(responder=lambda call: response(204))

        async def run():
            async with client.query_api_session() as api:
                await api.query("otcMarket", "weeklySummary", {})

        _run(run())

        assert session.closed
        assert session.calls[0]["json"] == {"offset": 0, "limit": 5000}


class TestTraceSession:
    """The TRACE envelope, token, retries, and errors are handled."""

    @staticmethod
    def _page(fake_session, response, responses, cookies=None):
        answers = iter(responses)

        def responder(call):
            if call["method"] == "GET":
                return response(400, '{"status": "failure"}')

            return next(answers)

        session = fake_session(responder=responder, cookies=cookies)

        async def run():
            async with client.trace_session() as trace:
                return await trace.page("corporateAndAgencySecurities", {}, 0, 5)

        return _run(run()), session

    def test_rows_and_total(self, fake_session, response):
        """Rows come from the encoded data string."""
        result, session = self._page(
            fake_session, response, [response(200, _trace_body([{"cusip": "X"}], 9))]
        )

        assert result == ([{"cusip": "X"}], 9)
        assert session.closed

    def test_null_data(self, fake_session, response):
        """A null data block is an empty page."""
        body = json.dumps({"status": "success", "returnBody": {"data": None}})
        result, _ = self._page(fake_session, response, [response(200, body)])

        assert result == ([], 0)

    def test_data_list(self, fake_session, response):
        """A data block that is already a list is used as is."""
        body = json.dumps({"status": "success", "returnBody": {"data": [{"a": 1}]}})
        result, _ = self._page(fake_session, response, [response(200, body)])

        assert result == ([{"a": 1}], 1)

    def test_http_error(self, fake_session, response):
        """A non-200 answer raises."""
        with pytest.raises(OpenBBError, match="HTTP 403"):
            self._page(fake_session, response, [response(403, "Invalid CORS request")])

    def test_login_page(self, fake_session, response):
        """A login page served with HTTP 200 raises."""
        with pytest.raises(OpenBBError, match="HTTP 200"):
            self._page(fake_session, response, [response(200, "<html>Login</html>")])

    def test_failure_status(self, fake_session, response):
        """A failure envelope raises its message."""
        body = json.dumps({"status": "failure", "statusMessage": "Bad Request."})

        with pytest.raises(OpenBBError, match="Bad Request"):
            self._page(fake_session, response, [response(200, body)])

    def test_retries_gateway_errors(self, fake_session, response, monkeypatch):
        """A gateway error is retried."""
        monkeypatch.setattr("openbb_finra.utils.constants.TRACE_BACKOFF", 0)
        gateway = response(502, "<html>Bad gateway</html>")
        result, _ = self._page(
            fake_session, response, [gateway, response(200, _trace_body([{"a": 1}]))]
        )

        assert result == ([{"a": 1}], 1)
        assert gateway.released

    def test_gives_up_after_retries(self, fake_session, response, monkeypatch):
        """Gateway errors on every attempt raise."""
        monkeypatch.setattr("openbb_finra.utils.constants.TRACE_BACKOFF", 0)

        with pytest.raises(OpenBBError, match="HTTP 524"):
            self._page(fake_session, response, [response(524, "timeout")] * 3)

    def test_missing_token(self, fake_session, response):
        """Without the XSRF cookie the session cannot open."""
        with pytest.raises(OpenBBError, match="XSRF"):
            self._page(fake_session, response, [], cookies={"XSRF-TOKEN": ""})

    def test_query_pages(self, fake_session, response):
        """A query collects every page."""

        def responder(call):
            if call["method"] == "GET":
                return response(400, "{}")

            offset = call["json"]["offset"]

            return response(200, _trace_body([{"n": offset}], 2))

        fake_session(responder=responder)

        async def run():
            async with client.trace_session() as trace:
                return await trace.query("x", {}, max_rows=None)

        assert _run(run()) == [{"n": 0}, {"n": 1}]


class TestMarketDataSession:
    """The Market Data Center session, lookups, and errors are handled."""

    @staticmethod
    def _call(fake_session, response, answer, method, *args):
        def responder(call):
            if urlparse(call["url"]).path == "/finralogin.jsp":
                return response(200, "\n")

            return answer

        session = fake_session(responder=responder)

        async def run():
            async with client.market_data_session() as market_data:
                return await getattr(market_data, method)(*args)

        return _run(run()), session

    def test_search(self, fake_session, response):
        """Search records are returned."""
        answer = response(200, '{"result": [{"OS001": "AAPL"}], "id": "1"}')
        result, session = self._call(
            fake_session, response, answer, "search", "AAPL", "ST"
        )

        assert result == [{"OS001": "AAPL"}]
        assert session.calls[1]["params"] == {
            "condition": "ST",
            "kw": "AAPL",
            "id": "1",
        }
        assert session.closed

    def test_search_without_hits(self, fake_session, response):
        """No hits is an empty list."""
        result, _ = self._call(
            fake_session, response, response(200, '{"id": "1"}'), "search", "ZZZ", "ST"
        )

        assert result == []

    def test_search_error(self, fake_session, response):
        """A search error message is raised."""
        body = (
            '{"result": [], "errorMessage": "The parameter [kw] is not allowed empty."}'
        )

        with pytest.raises(OpenBBError, match="not allowed empty"):
            self._call(fake_session, response, response(200, body), "search", " ", "ST")

    def test_search_unreadable(self, fake_session, response):
        """A search body that is not JSON raises."""
        with pytest.raises(OpenBBError, match="no search data"):
            self._call(
                fake_session, response, response(200, "<html>"), "search", "A", "ST"
            )

    def test_invalid_session(self, fake_session, response):
        """A rejected session raises."""
        body = '{"status": {"errorCode": "-1", "errorMsg": "Invalid session"}, "data": null}'

        with pytest.raises(OpenBBError, match="rejected the session"):
            self._call(fake_session, response, response(200, body), "search", "A", "ST")

    def test_lookup(self, fake_session, response):
        """Lookup records are returned."""
        body = '{"errorCode": "0", "Records": [{"Ticker": "AAPL"}]}'
        result, session = self._call(
            fake_session, response, response(200, body), "lookup", ["AAPL", "MSFT"]
        )

        assert result == [{"Ticker": "AAPL"}]
        assert session.calls[1]["params"] == {"symbol": "AAPL,MSFT"}

    def test_lookup_unreadable(self, fake_session, response):
        """A lookup body that is not JSON raises."""
        with pytest.raises(OpenBBError, match="not readable"):
            self._call(
                fake_session, response, response(200, "finraLookup("), "lookup", ["A"]
            )

    def test_static_data(self, fake_session, response):
        """Static data rows are returned, skipping anything that is not a row."""
        body = '{"status": {"errorMsg": "Succeed"}, "data": [{"secId": "X"}, "junk"]}'
        result, _ = self._call(
            fake_session, response, response(200, body), "static_data", ["X"]
        )

        assert result == [{"secId": "X"}]

    def test_static_data_empty(self, fake_session, response):
        """A session-less empty body gives no rows."""
        result, _ = self._call(
            fake_session, response, response(200, "\n{}"), "static_data", ["X"]
        )

        assert result == []

    def test_http_error(self, fake_session, response):
        """A non-200 answer raises."""
        with pytest.raises(OpenBBError, match="HTTP 503"):
            self._call(
                fake_session, response, response(503, "unavailable"), "lookup", ["A"]
            )

    def test_throttled(self, fake_session, response):
        """A rate refusal raises the throttle error."""
        with pytest.raises(client.MarketDataThrottledError, match="throttled"):
            self._call(
                fake_session,
                response,
                response(429, "Just a moment..."),
                "lookup",
                ["A"],
            )
