"""HTTP transport for the FINRA data services."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from openbb_core.app.model.abstract.error import OpenBBError

PageFetcher = Callable[[int, int], Awaitable[tuple[list[dict], int]]]


async def open_session() -> Any:
    """Return a new HTTP session that applies the user's request settings.

    Returns
    -------
    ClientSession
        An open session; the caller closes it.
    """
    from openbb_core.provider.utils.helpers import get_async_requests_session

    return await get_async_requests_session()


def _decode(text: str) -> Any:
    """Return the JSON document in a response body, or the text when it is not JSON."""
    import json

    if not text.strip():
        return None

    try:
        return json.loads(text)
    except ValueError:
        return text


async def collect_pages(
    fetch_page: PageFetcher,
    page_limit: int,
    concurrency: int = 1,
    max_rows: int | None = None,
) -> list[dict]:
    """Return every row of a paged dataset.

    Parameters
    ----------
    fetch_page : Callable[[int, int], Awaitable[tuple[list[dict], int]]]
        Returns the rows at an offset, up to a limit, and the dataset's row total.
    page_limit : int
        The most rows the service returns for one request.
    concurrency : int
        The most pages requested at once.
    max_rows : int | None
        Stop after this many rows. All rows when None.

    Returns
    -------
    list[dict]
        The rows, in offset order.
    """
    import asyncio

    first_limit = min(page_limit, max_rows) if max_rows else page_limit
    rows, total = await fetch_page(0, first_limit)
    wanted = min(total, max_rows) if max_rows else total

    if not rows or len(rows) >= wanted:
        return rows[:wanted] if wanted else rows

    semaphore = asyncio.Semaphore(max(concurrency, 1))

    async def fill(offset: int, expected: int) -> list[dict]:
        block: list[dict] = []

        async with semaphore:
            while len(block) < expected:
                page, _ = await fetch_page(
                    offset + len(block), min(page_limit, expected - len(block))
                )

                if not page:
                    break

                block.extend(page)

        return block

    first_end = min(page_limit, wanted)
    tasks = [fill(len(rows), first_end - len(rows))] + [
        fill(offset, min(page_limit, wanted - offset))
        for offset in range(page_limit, wanted, page_limit)
    ]

    for block in await asyncio.gather(*tasks):
        rows.extend(block)

    return rows


class QueryApiSession:
    """A session on the public FINRA Query API."""

    def __init__(self, session: Any) -> None:
        """Hold the HTTP session the requests are made on."""
        self.session = session

    async def page(
        self, group: str, dataset: str, payload: dict, offset: int, limit: int
    ) -> tuple[list[dict], int]:
        """Return one page of a dataset and the dataset's row total.

        Parameters
        ----------
        group : str
            The dataset group, such as otcMarket.
        dataset : str
            The dataset name, such as weeklySummary.
        payload : dict
            The request body, without the paging keys.
        offset : int
            The first row to return.
        limit : int
            The most rows to return.

        Returns
        -------
        tuple[list[dict], int]
            The rows, and the total number of rows the query matches.

        Raises
        ------
        OpenBBError
            If FINRA rejects the request.
        """
        from openbb_finra.utils.constants import (
            QUERY_API_HEADERS,
            QUERY_API_URL,
            REQUEST_TIMEOUT,
        )

        response = await self.session.post(
            f"{QUERY_API_URL}/data/group/{group}/name/{dataset}",
            json={**payload, "offset": offset, "limit": limit},
            headers=dict(QUERY_API_HEADERS),
            timeout=REQUEST_TIMEOUT,
        )

        if response.status == 204:
            return [], 0

        body = _decode(await response.text())

        if response.status != 200:
            message = body.get("message") if isinstance(body, dict) else body
            raise OpenBBError(
                f"FINRA answered {group}/{dataset} with HTTP {response.status}: {message}"
            )

        if not isinstance(body, list):
            raise OpenBBError(f"FINRA returned an unexpected {dataset} response.")

        total = response.headers.get("record-total")

        return body, int(total) if total else len(body)

    async def query(
        self,
        group: str,
        dataset: str,
        payload: dict,
        max_rows: int | None = None,
    ) -> list[dict]:
        """Return every row a query matches.

        Parameters
        ----------
        group : str
            The dataset group, such as otcMarket.
        dataset : str
            The dataset name, such as weeklySummary.
        payload : dict
            The request body, without the paging keys.
        max_rows : int | None
            Stop after this many rows. All rows when None.

        Returns
        -------
        list[dict]
            The matching rows.
        """
        from openbb_finra.utils.constants import QUERY_API_PAGE_LIMIT

        async def fetch_page(offset: int, limit: int) -> tuple[list[dict], int]:
            return await self.page(group, dataset, payload, offset, limit)

        return await collect_pages(
            fetch_page, QUERY_API_PAGE_LIMIT, concurrency=4, max_rows=max_rows
        )

    async def partitions(self, group: str, dataset: str) -> list[list[str]]:
        """Return the partition values a dataset holds.

        Parameters
        ----------
        group : str
            The dataset group, such as otcMarket.
        dataset : str
            The dataset name, such as weeklySummary.

        Returns
        -------
        list[list[str]]
            One list of partition-key values per partition.

        Raises
        ------
        OpenBBError
            If FINRA rejects the request.
        """
        from openbb_finra.utils.constants import (
            QUERY_API_HEADERS,
            QUERY_API_URL,
            REQUEST_TIMEOUT,
        )

        response = await self.session.get(
            f"{QUERY_API_URL}/partitions/group/{group}/name/{dataset}",
            headers=dict(QUERY_API_HEADERS),
            timeout=REQUEST_TIMEOUT,
        )
        body = _decode(await response.text())

        if response.status != 200 or not isinstance(body, dict):
            raise OpenBBError(
                f"FINRA answered the {dataset} partitions with HTTP {response.status}."
            )

        return [
            list(item.get("partitions") or [])
            for item in body.get("availablePartitions") or []
        ]


@asynccontextmanager
async def query_api_session() -> AsyncGenerator[QueryApiSession, None]:
    """Open a session on the public FINRA Query API.

    Yields
    ------
    QueryApiSession
        The session; it is closed on exit.
    """
    session = await open_session()

    try:
        yield QueryApiSession(session)
    finally:
        await session.close()


class TraceSession:
    """A session on the public TRACE data service, holding its XSRF token."""

    def __init__(self, session: Any, token: str) -> None:
        """Hold the HTTP session and the token the service checks."""
        self.session = session
        self.token = token

    async def page(
        self, dataset: str, payload: dict, offset: int, limit: int
    ) -> tuple[list[dict], int]:
        """Return one page of a TRACE dataset and the dataset's row total.

        Parameters
        ----------
        dataset : str
            The dataset name, such as CorporateAndAgencySecurities.
        payload : dict
            The request body, without the paging keys.
        offset : int
            The first row to return.
        limit : int
            The most rows to return.

        Returns
        -------
        tuple[list[dict], int]
            The rows, and the total number of rows the query matches.

        Raises
        ------
        OpenBBError
            If the service rejects the request.
        """
        import asyncio
        import json

        from openbb_finra.utils.constants import (
            REQUEST_TIMEOUT,
            TRACE_ATTEMPTS,
            TRACE_BACKOFF,
            TRACE_ORIGIN,
            TRACE_REFERER,
            TRACE_RETRY_CODES,
            TRACE_URL,
            USER_AGENT,
        )

        attempt = 0

        while True:
            response = await self.session.post(
                f"{TRACE_URL}/{dataset}",
                json={**payload, "offset": offset, "limit": limit},
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json",
                    "Origin": TRACE_ORIGIN,
                    "Referer": TRACE_REFERER,
                    "X-XSRF-TOKEN": self.token,
                },
                timeout=REQUEST_TIMEOUT * 2,
            )

            if (
                response.status not in TRACE_RETRY_CODES
                or attempt + 1 == TRACE_ATTEMPTS
            ):
                break

            response.release()
            await asyncio.sleep(TRACE_BACKOFF * 2**attempt)
            attempt += 1

        body = _decode(await response.text())

        if response.status != 200 or not isinstance(body, dict):
            raise OpenBBError(
                f"FINRA TRACE answered {dataset} with HTTP {response.status}."
            )

        if body.get("status") != "success":
            raise OpenBBError(
                f"FINRA TRACE rejected the {dataset} request: "
                f"{body.get('statusMessage') or body.get('status')}"
            )

        returned = body.get("returnBody") or {}
        data = returned.get("data")
        rows = json.loads(data) if isinstance(data, str) and data.strip() else data
        totals = (returned.get("headers") or {}).get("Record-Total") or []
        rows = rows if isinstance(rows, list) else []

        return rows, int(totals[0]) if totals else len(rows)

    async def query(
        self, dataset: str, payload: dict, max_rows: int | None = None
    ) -> list[dict]:
        """Return every row a TRACE query matches.

        Parameters
        ----------
        dataset : str
            The dataset name, such as CorporateAndAgencySecurities.
        payload : dict
            The request body, without the paging keys.
        max_rows : int | None
            Stop after this many rows. All rows when None.

        Returns
        -------
        list[dict]
            The matching rows.
        """
        from openbb_finra.utils.constants import TRACE_CONCURRENCY, TRACE_PAGE_LIMIT

        async def fetch_page(offset: int, limit: int) -> tuple[list[dict], int]:
            return await self.page(dataset, payload, offset, limit)

        return await collect_pages(
            fetch_page,
            TRACE_PAGE_LIMIT,
            concurrency=TRACE_CONCURRENCY,
            max_rows=max_rows,
        )


async def _trace_token(session: Any) -> str:
    """Return the XSRF token the TRACE service issues on a first request.

    Raises
    ------
    OpenBBError
        If the service does not issue the token.
    """
    from openbb_finra.utils.constants import REQUEST_TIMEOUT, TRACE_URL, USER_AGENT

    response = await session.get(
        f"{TRACE_URL}/CorporateAndAgencySecurities",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    response.release()

    for cookie in session.cookie_jar:
        if cookie.key == "XSRF-TOKEN" and cookie.value:
            return cookie.value

    raise OpenBBError("FINRA TRACE did not issue the XSRF token its service requires.")


@asynccontextmanager
async def trace_session() -> AsyncGenerator[TraceSession, None]:
    """Open a session on the public TRACE data service.

    Yields
    ------
    TraceSession
        The session, holding its XSRF token; it is closed on exit.
    """
    session = await open_session()

    try:
        yield TraceSession(session, await _trace_token(session))
    finally:
        await session.close()


class MarketDataThrottledError(Exception):
    """The Market Data Center refused a request for its rate."""


class MarketDataRejectedError(OpenBBError):
    """The Market Data Center failed a request."""


class MarketDataSession:
    """A session on the FINRA Market Data Center."""

    def __init__(self, session: Any) -> None:
        """Hold the HTTP session the requests are made on."""
        self.session = session

    async def _get(self, path: str, params: dict) -> str:
        """Return the body of one Market Data Center request.

        Raises
        ------
        MarketDataThrottledError
            If the service refused the request for its rate.
        MarketDataRejectedError
            If the service does not answer with HTTP 200.
        """
        from openbb_finra.utils.constants import (
            MARKET_DATA_URL,
            REQUEST_TIMEOUT,
            USER_AGENT,
        )

        response = await self.session.get(
            f"{MARKET_DATA_URL}/{path}",
            params=params,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
            timeout=REQUEST_TIMEOUT,
        )
        text = await response.text()

        if response.status == 429:
            raise MarketDataThrottledError(
                f"The FINRA Market Data Center throttled {path}."
            )

        if response.status != 200:
            raise MarketDataRejectedError(
                f"The FINRA Market Data Center answered {path} with HTTP "
                f"{response.status}."
            )

        return text

    async def seed(self) -> None:
        """Open the Market Data Center session the data requests are made in."""
        await self._get("finralogin.jsp", {})

    @staticmethod
    def _check_session(body: Any) -> None:
        """Raise when the Market Data Center rejected the session.

        Raises
        ------
        OpenBBError
            If the response reports an invalid session.
        """
        status = body.get("status") if isinstance(body, dict) else None

        if isinstance(status, dict) and status.get("errorMsg") == "Invalid session":
            raise OpenBBError("The FINRA Market Data Center rejected the session.")

    async def search(self, query: str, condition: str) -> list[dict]:
        """Return the securities matching a keyword.

        Parameters
        ----------
        query : str
            The symbol, name, CUSIP, or ISIN to look for.
        condition : str
            The comma-separated security types to include.

        Returns
        -------
        list[dict]
            The raw search records.

        Raises
        ------
        OpenBBError
            If the service answers with an error.
        """
        from openbb_finra.utils.helpers import clean

        body = _decode(
            await self._get("acb.jsp", {"condition": condition, "kw": query, "id": "1"})
        )

        if not isinstance(body, dict):
            raise OpenBBError("The FINRA Market Data Center returned no search data.")

        self._check_session(body)
        error = clean(body.get("errorMessage"))

        if error and not body.get("result"):
            raise OpenBBError(
                f"The FINRA security search for {query!r} failed: {error}"
            )

        return list(body.get("result") or [])

    async def lookup(self, symbols: list[str]) -> list[dict]:
        """Return the listing the Market Data Center resolves for each symbol.

        Parameters
        ----------
        symbols : list[str]
            Tickers, CUSIPs, or Morningstar ids, at most 100.

        Returns
        -------
        list[dict]
            One raw lookup record per resolved symbol.

        Raises
        ------
        OpenBBError
            If the session was rejected or the response is not readable.
        """
        body = _decode(await self._get("getids.jsp", {"symbol": ",".join(symbols)}))

        if not isinstance(body, dict):
            raise OpenBBError("The FINRA security lookup was not readable.")

        self._check_session(body)

        return list(body.get("Records") or [])

    async def static_data(self, security_ids: list[str]) -> list[dict]:
        """Return the static data the Market Data Center holds for securities.

        Parameters
        ----------
        security_ids : list[str]
            The Morningstar security ids.

        Returns
        -------
        list[dict]
            One raw static-data row per security, in no particular order.
        """
        body = _decode(
            await self._get("getStaticData.jsp", {"secId": ",".join(security_ids)})
        )
        self._check_session(body)
        rows = body.get("data") if isinstance(body, dict) else None

        return [row for row in rows or [] if isinstance(row, dict)]


@asynccontextmanager
async def market_data_session() -> AsyncGenerator[MarketDataSession, None]:
    """Open a seeded session on the FINRA Market Data Center.

    Yields
    ------
    MarketDataSession
        The session; it is closed on exit.
    """
    session = await open_session()

    try:
        market_data = MarketDataSession(session)
        await market_data.seed()
        yield market_data
    finally:
        await session.close()
