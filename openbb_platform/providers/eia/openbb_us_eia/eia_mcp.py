"""EIA MCP server: a streamable-http subprocess, reverse-proxied through the
OpenBB API so the Workspace connects on the API's own host/port.
"""

import logging
from typing import Annotated, Any

from fastapi import Depends
from starlette.requests import Request

from openbb_us_eia.browsers import _user_key

_logger = logging.getLogger(__name__)

_MCP_HOST = "127.0.0.1"
_MCP_PATH = "/mcp"
_DEFAULT_MCP_PORT = 6923


def mcp_port() -> int:
    """Return the port the MCP subprocess listens on (``OPENBB_EIA_MCP_PORT``)."""
    import os

    try:
        return int(os.environ.get("OPENBB_EIA_MCP_PORT", str(_DEFAULT_MCP_PORT)))
    except ValueError:
        return _DEFAULT_MCP_PORT


def mcp_server_url() -> str:
    """Return the streamable-http URL the Workspace connects to."""
    return f"http://{_MCP_HOST}:{mcp_port()}{_MCP_PATH}"


def _port_open(host: str, port: int) -> bool:
    """Return True if something is already listening on host:port."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def _api_state_url(browser: str, user: str) -> str:
    """Return the main API process's URL for reading one browser's live state.

    The MCP tool runs in this module's own subprocess, which has no
    visibility into the main API process's in-memory browser state (that
    state lives only where ``eia_table``/``eia_view``/``eia_proxy`` run), so
    the tool calls back into the main process to read it there.
    """
    import os
    from urllib.parse import urlencode

    from openbb_core.app.service.system_service import SystemService

    host = os.environ.get("OPENBB_API_HOST", "127.0.0.1")
    port = os.environ.get("OPENBB_API_PORT", "6900")
    prefix = SystemService().system_settings.api_settings.prefix
    query = urlencode({"browser": browser, "user": user})
    return f"http://{host}:{port}{prefix}/eia/eia_mcp_state?{query}"


_mcp_process: Any = None


def ensure_mcp_subprocess() -> None:
    """Launch the MCP server in its own process (idempotent).

    The streamable-http session manager must own its event loop and lifespan;
    mounting it inside the OpenBB API — whose lifespan it cannot extend —
    does not survive a real deployment, so it never finishes starting.
    Running it as a subprocess gives it a clean uvicorn lifecycle. The
    port-in-use guard keeps this safe when the API runs multiple workers.
    """
    global _mcp_process  # noqa: PLW0603
    import atexit
    import os
    import subprocess
    import sys

    if _mcp_process is not None and _mcp_process.poll() is None:
        return
    port = mcp_port()
    if _port_open(_MCP_HOST, port):
        return
    try:
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
        _mcp_process = subprocess.Popen(  # noqa: S603
            [
                sys.executable,
                "-m",
                "openbb_us_eia.eia_mcp",
                "--host",
                _MCP_HOST,
                "--port",
                str(port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        atexit.register(stop_mcp_subprocess)
    except Exception:  # noqa: BLE001
        _mcp_process = None


def stop_mcp_subprocess() -> None:
    """Terminate the MCP subprocess if this process started it."""
    global _mcp_process  # noqa: PLW0603
    if _mcp_process is not None and _mcp_process.poll() is None:
        _mcp_process.terminate()
    _mcp_process = None


def _build_mcp_server() -> Any:
    """Build the FastMCP server and register the EIA data-browser tool."""
    from fastmcp import FastMCP

    mcp: Any = FastMCP(
        name="EIA Data Browsers",
        instructions=(
            "Tools for reading the exact table currently rendered on screen"
            " in one of the EIA data-browser widgets."
        ),
    )

    @mcp.tool
    async def get_current_browser_data(browser: str) -> list[dict]:
        """Return the exact table currently rendered on screen for one EIA data browser.

        Parameters
        ----------
        browser : str
            One of: electricity, coal, total_energy, steo, aeo,
            international, petroleum_imports, natural_gas_query, states, maps.

        Returns
        -------
        list[dict]
            One record per row, matching exactly what the browser's iframe is
            currently displaying.
        """
        import json

        import aiohttp
        from fastmcp.server.dependencies import get_http_headers

        headers = get_http_headers(include={"x-openbb-user"})
        user = _user_key(headers.get("x-openbb-user", ""))
        url = _api_state_url(browser, user)
        try:
            async with (
                aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as session,
                session.get(url) as response,
            ):
                if response.status != 200:
                    return []
                rows = json.loads(await response.read())
        except (aiohttp.ClientError, ValueError):
            _logger.exception("Failed to read live browser state from the API")
            return []
        return rows if isinstance(rows, list) else []

    @mcp.tool
    async def get_feed_articles(feed: str = "today_in_energy") -> list[dict]:
        """Return the articles currently listed in one EIA RSS feed.

        Parameters
        ----------
        feed : str
            One of: today_in_energy, whats_new, press_releases,
            congressional_testimony, presentations, gasoline_diesel,
            heating_oil_propane. Unknown values fall back to today_in_energy.

        Returns
        -------
        list[dict]
            One record per article, with ``title``, ``date``, ``author``,
            ``url`` and ``excerpt``. Pass a record's ``url`` to
            ``get_article_content`` to read the full article.
        """
        import aiohttp

        from openbb_us_eia.utils.rss import EIA_RSS_FEEDS, build_feed, fetch_feed

        if feed not in EIA_RSS_FEEDS:
            feed = "today_in_energy"
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            ) as session:
                parsed = await fetch_feed(session, EIA_RSS_FEEDS[feed]["url"])
        except aiohttp.ClientError:
            _logger.exception("Failed to fetch the EIA RSS feed")
            return []
        return [
            {key: item[key] for key in ("title", "date", "author", "url", "excerpt")}
            for item in build_feed(feed, parsed, 50)["items"]
        ]

    @mcp.tool
    async def get_article_content(url: str) -> str:
        """Return the readable text of one EIA article.

        Parameters
        ----------
        url : str
            The article's ``url`` from ``get_feed_articles``. Only eia.gov
            URLs are fetched.

        Returns
        -------
        str
            The article's prose, or an empty string if it could not be read.
        """
        from urllib.parse import urlsplit

        import aiohttp

        from openbb_us_eia.utils.rss import article_text

        host = (urlsplit(url).hostname or "").lower()
        if host != "eia.gov" and not host.endswith(".eia.gov"):
            return "Only eia.gov article URLs can be fetched."
        try:
            async with (
                aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as session,
                session.get(url) as response,
            ):
                if response.status != 200:
                    return ""
                html = await response.text()
        except (aiohttp.ClientError, UnicodeDecodeError):
            _logger.exception("Failed to fetch the EIA article")
            return ""
        return article_text(html)

    return mcp


def _serve(host: str, port: int) -> None:
    """Run the FastMCP streamable-http server — the subprocess entry point."""
    import uvicorn
    from starlette.middleware.cors import CORSMiddleware

    mcp = _build_mcp_server()
    app = mcp.http_app(path=_MCP_PATH, json_response=True, transport="streamable-http")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["mcp-session-id", "Mcp-Session-Id"],
    )
    _exit_when_orphaned()
    uvicorn.run(app, host=host, port=port, log_level="warning")


def _exit_when_orphaned() -> None:
    """Exit if the parent API process goes away.

    The launcher cannot fire ``atexit`` when uvicorn SIGKILLs its workers on
    a reload, which would otherwise leave this server running forever.
    Polling the parent pid lets the subprocess clean itself up so reloads
    never accumulate abandoned MCP servers.
    """
    import os
    import threading
    import time

    parent = os.getppid()

    def _watch() -> None:
        while True:
            time.sleep(2)
            if os.getppid() != parent:
                os._exit(0)

    threading.Thread(target=_watch, daemon=True).start()


_FORWARD_REQ_HEADERS = {
    "accept",
    "content-type",
    "mcp-session-id",
    "mcp-protocol-version",
    "x-openbb-user",
}
_DROP_RESP_HEADERS = {
    "content-length",
    "transfer-encoding",
    "connection",
    "content-encoding",
}


async def _await_ready(timeout: float = 10.0) -> bool:
    """Poll until the MCP subprocess is accepting connections."""
    import asyncio

    for _ in range(max(1, int(timeout / 0.2))):
        if _port_open(_MCP_HOST, mcp_port()):
            return True
        await asyncio.sleep(0.2)
    return False


async def _extract_mcp_request(request: Request) -> dict:
    """Pull plain values out of the request.

    The OpenBB router wraps endpoints as commands and deep-copies their
    kwargs; a starlette ``Request`` cannot be deep-copied (it recurses), so
    the proxy takes this plain dict via a dependency instead of the
    ``Request`` itself.
    """
    return {
        "method": request.method,
        "body": await request.body(),
        "headers": {
            k: v
            for k, v in request.headers.items()
            if k.lower() in _FORWARD_REQ_HEADERS
        },
        "query": dict(request.query_params),
    }


async def mcp_reverse_proxy(
    data: Annotated[dict, Depends(_extract_mcp_request)],
) -> Any:
    """Proxy an MCP request to the local subprocess, streaming the response.

    Lets the Workspace connect at the OpenBB API's own host/port — the
    subprocess is an internal detail — while the subprocess still owns the
    streamable-http lifecycle that an in-process mount could not start.

    The request arrives as a plain dict from ``_extract_mcp_request``: taking
    the ``Request`` directly would put it in the command wrapper's kwargs,
    which ``CommandRunner`` deep-copies, and deep-copying a ``Request``
    recurses until it raises ``RecursionError``.
    """
    import asyncio

    import aiohttp
    from starlette.responses import JSONResponse, StreamingResponse

    ensure_mcp_subprocess()
    if not await _await_ready():
        return JSONResponse({"error": "MCP server failed to start"}, status_code=503)

    session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=None)
    )
    try:
        upstream = await session.request(
            data["method"],
            mcp_server_url(),
            headers=data["headers"],
            data=data["body"] or None,
            params=data["query"],
        )
    except aiohttp.ClientError:
        _logger.exception("MCP proxy request failed")
        await session.close()
        return JSONResponse({"error": "MCP proxy error."}, status_code=502)

    out_headers = {
        k: v for k, v in upstream.headers.items() if k.lower() not in _DROP_RESP_HEADERS
    }
    out_headers["access-control-expose-headers"] = "mcp-session-id, Mcp-Session-Id"

    async def _stream() -> Any:
        try:
            async for chunk in upstream.content.iter_any():
                yield chunk
        except (TimeoutError, asyncio.CancelledError, aiohttp.ClientError):
            return
        finally:
            upstream.release()
            await session.close()

    return StreamingResponse(
        _stream(), status_code=upstream.status, headers=out_headers
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=_MCP_HOST)
    parser.add_argument("--port", type=int, default=mcp_port())
    args = parser.parse_args()
    _serve(args.host, args.port)
