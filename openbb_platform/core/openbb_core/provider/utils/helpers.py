"""Provider helpers."""

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from functools import partial
from inspect import iscoroutinefunction
from typing import (
    TYPE_CHECKING,
    Literal,
    TypeVar,
    cast,
)

from anyio.from_thread import start_blocking_portal
from typing_extensions import ParamSpec

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.utils.client import (
    ClientResponse,
    ClientSession,
    get_user_agent,
)
from openbb_core.provider.utils.errors import UnauthorizedError

if TYPE_CHECKING:
    from requests import Response, Session

T = TypeVar("T")
P = ParamSpec("P")
D = TypeVar("D", bound="Data")


def check_item(item: str, allowed: list[str], threshold: float = 0.75) -> None:
    """Check if an item is in a list of allowed items and raise an error if not.

    Parameters
    ----------
    item : str
        The item to check.
    allowed : list[str]
        The list of allowed items.
    threshold : float, optional
        The similarity threshold for the error message, by default 0.75

    Raises
    ------
    ValueError
        If the item is not in the allowed list.
    """
    if item not in allowed:
        similarities = map(
            lambda c: (c, SequenceMatcher(None, item, c).ratio()), allowed
        )
        similar, score = max(similarities, key=lambda x: x[1])
        if score > threshold:
            raise ValueError(f"'{item}' is not available. Did you mean '{similar}'?")
        raise ValueError(f"'{item}' is not available.")


def get_querystring(items: dict, exclude: list[str]) -> str:
    """Turn a dictionary into a querystring, excluding the keys in the exclude list.

    Parameters
    ----------
    items: dict
        The dictionary to be turned into a querystring.

    exclude: list[str]
        The keys to be excluded from the querystring.

    Returns
    -------
    str
        The querystring.
    """
    for key in exclude:
        items.pop(key, None)

    query_items = []
    for key, value in items.items():
        if value is None:
            continue
        if isinstance(value, list):
            for item in value:
                query_items.append(f"{key}={item}")
        else:
            query_items.append(f"{key}={value}")

    querystring = "&".join(query_items)

    return f"{querystring}" if querystring else ""


def get_python_request_settings() -> dict:
    """
    Get the python settings from the system_settings.json file.

    They are read from the "http" key in the "python_settings" key in the system_settings.json file.

    The configuration applies to both the requests and aiohttp libraries.

    Available settings:
    - cafile: Path to a CA certificate file.
    - certfile: Path to a client certificate file.
    - keyfile: Path to a client key file.
    - password: Password for the client key file.  # aiohttp only
    - verify_ssl: Verify SSL certificates.
    - fingerprint: SSL fingerprint.  # aiohttp only
    - proxy: Proxy URL.
    - proxy_auth: Proxy authentication.  # aiohttp only
    - proxy_headers: Proxy headers.  # aiohttp only
    - timeout: Request timeout.
    - auth: Basic authentication.
    - headers: Request headers.
    - cookies: Dictionary of session cookies.

    Any additional keys supplied will be ignored.
    """
    from openbb_core.app.service.system_service import SystemService

    python_settings = SystemService().system_settings.python_settings.model_dump()
    http_settings = python_settings.get("http", {})
    allowed_keys = [
        "cafile",
        "certfile",
        "keyfile",
        "password",
        "verify_ssl",
        "fingerprint",
        "proxy",
        "proxy_auth",
        "proxy_headers",
        "timeout",
        "auth",
        "headers",
        "cookies",
    ]

    return {
        k: v for k, v in http_settings.items() if v is not None and k in allowed_keys
    }


def get_requests_session(**kwargs) -> "Session":
    """Get a requests session object with the applied user settings or environment variables."""
    import requests

    # If a session is already provided, just return it.
    if "session" in kwargs and isinstance(kwargs.get("session"), requests.Session):
        return kwargs["session"]

    # We want to add a user agent to the request, so check if there are any headers
    # If there are headers, check if there is a user agent, if not add one.
    # Some requests seem to work only with a specific user agent, so we want to be able to override it.
    python_settings = get_python_request_settings()
    headers = kwargs.pop("headers", {})
    headers.update(python_settings.pop("headers", {}))

    if "User-Agent" not in headers:
        headers["User-Agent"] = get_user_agent()

    # Allow a custom session for caching, if desired
    _session: requests.Session = kwargs.pop("session", None) or requests.Session()
    _session.headers.update(headers)

    if python_settings.get("verify_ssl") is False:
        _session.verify = False
    else:
        ca_file = python_settings.get("cafile")
        requests_ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE")
        cert = ca_file or requests_ca_bundle
        if cert:
            bundle = requests_ca_bundle if requests_ca_bundle != cert else None
            _session.verify = combine_certificates(cert, bundle)

    if certfile := python_settings.get("certfile"):
        keyfile = python_settings.get("keyfile")
        _session.cert = (certfile, keyfile) if keyfile else certfile

    proxy = python_settings.get("proxy")
    http_proxy = os.environ.get("HTTP_PROXY", os.environ.get("HTTPS_PROXY"))
    https_proxy = os.environ.get("HTTPS_PROXY", os.environ.get("HTTP_PROXY"))

    if http_proxy is not None and http_proxy == https_proxy:
        https_proxy = None

    if http_proxy or https_proxy or proxy:
        proxies: dict = {}
        if http := http_proxy or https_proxy or proxy:
            proxies["http"] = http
        if https := https_proxy or http_proxy or proxy:
            proxies["https"] = https
        _session.proxies = proxies

    if cookies := python_settings.get("cookies"):
        _session.cookies = (
            cookies
            if isinstance(cookies, requests.cookies.RequestsCookieJar)  # type: ignore
            else requests.cookies.cookiejar_from_dict(cookies)  # type: ignore
        )

    if auth := python_settings.get("auth"):
        import requests.auth as _requests_auth

        _session.auth = (
            auth if isinstance(auth, (tuple, _requests_auth.AuthBase)) else tuple(auth)
        )

    if kwargs:
        for key, value in kwargs.items():
            try:
                if hasattr(_session, key):
                    if hasattr(getattr(_session, key, None), "update"):
                        getattr(_session, key, {}).update(value)
                    else:
                        setattr(_session, key, value)
            except AttributeError:
                continue

    _session.trust_env = False

    return _session


async def get_async_requests_session(**kwargs) -> ClientSession:
    """Get an aiohttp session object with the applied user settings or environment variables."""
    import aiohttp  # noqa
    import atexit
    import ssl

    # If a session is already provided, just return it.
    if "session" in kwargs and isinstance(kwargs.get("session"), ClientSession):
        return kwargs["session"]
    # Handle SSL settings and proxies
    # We will accommodate the Requests environment variable for the CA bundle and HTTP Proxies, if provided.
    # The settings file will take precedence over the environment variables.
    python_settings = get_python_request_settings()
    _ = kwargs.pop("raise_for_status", None)

    # "password" is only valid as input to ssl.load_cert_chain, below; aiohttp
    # accepts neither it nor "proxy_headers" as a ClientSession constructor
    # kwarg, so both must be kept out of the generic settings merge/pass-through
    # further down or ClientSession(**conn_kwargs) raises a TypeError.
    password = python_settings.pop("password", None)
    python_settings.pop("proxy_headers", None)

    proxy = python_settings.get("proxy")
    http_proxy = os.environ.get("HTTP_PROXY", os.environ.get("HTTPS_PROXY"))
    https_proxy = os.environ.get("HTTPS_PROXY", os.environ.get("HTTP_PROXY"))

    # aiohttp will attempt to upgrade the proxy to https.
    if not proxy and http_proxy is not None and http_proxy == https_proxy:
        python_settings["proxy"] = http_proxy.replace("https:", "http:")

    # If a proxy is provided, or verify_ssl is False, we don't need to handle the certificate and create SSL context.
    # This takes priority over the cafile.
    if python_settings.get("proxy") or python_settings.get("verify_ssl") is False:
        python_settings["verify_ssl"] = None
        python_settings["ssl"] = False
    elif (
        python_settings.get("certfile")
        or python_settings.get("cafile")
        or os.environ.get("REQUESTS_CA_BUNDLE")
    ):
        ca = python_settings.get("cafile") or os.environ.get("REQUESTS_CA_BUNDLE")
        cert = python_settings.get("certfile")
        key = python_settings.get("keyfile")
        ssl_context = ssl.create_default_context()

        if ca:
            ssl_context.load_verify_locations(cafile=ca)

        if cert:
            ssl_context.load_cert_chain(
                certfile=cert,
                keyfile=key,
                password=password,
            )

        python_settings["ssl"] = ssl_context

    ssl_kwargs = {
        k: v
        for k, v in python_settings.items()
        if k in ["ssl", "verify_ssl", "fingerprint"] and v is not None
    }

    # Merge the updated python_settings dict with the kwargs.
    if python_settings:
        kwargs.update(
            {k: v for k, v in python_settings.items() if not k.endswith("file")}
        )

    # SSL settings get passed to the TCPConnector used by the session.
    connector = kwargs.pop("connector", None) or (
        aiohttp.TCPConnector(ttl_dns_cache=300, **ssl_kwargs) if ssl_kwargs else None
    )

    conn_kwargs = {"connector": connector} if connector else {}

    # Add basic auth for proxies, if provided.
    p_auth = kwargs.pop("proxy_auth", [])
    if p_auth:
        conn_kwargs["proxy_auth"] = aiohttp.BasicAuth(
            *p_auth if isinstance(p_auth, (list, tuple)) else p_auth
        )
    # Add basic auth for server, if provided.
    s_auth = kwargs.pop("auth", [])
    if s_auth:
        conn_kwargs["auth"] = aiohttp.BasicAuth(
            *s_auth if isinstance(s_auth, (list, tuple)) else s_auth
        )
    # Add cookies to the session, if provided.
    _cookies = kwargs.pop("cookies", None)
    if _cookies:
        if isinstance(_cookies, dict):
            conn_kwargs["cookies"] = _cookies
        elif isinstance(_cookies, aiohttp.CookieJar):
            conn_kwargs["cookie_jar"] = _cookies

    # Pass any remaining kwargs to the session
    for k, v in kwargs.items():
        if v is None:
            continue
        if k == "timeout":
            conn_kwargs["timeout"] = (
                v
                if isinstance(v, aiohttp.ClientTimeout)
                else aiohttp.ClientTimeout(total=v)
            )
        elif k not in ("ssl", "verify_ssl", "fingerprint") and k in python_settings:
            conn_kwargs[k] = v

    _session: ClientSession = ClientSession(**conn_kwargs)

    def at_exit(session):
        """Close the session at exit if it was orphaned."""
        if not session.closed:
            run_async(session.close)

    # Register the session to close at exit
    atexit.register(at_exit, _session)

    return _session


async def amake_request(
    url: str,
    method: Literal["GET", "POST"] = "GET",
    timeout: int | None = None,
    response_callback: (
        Callable[[ClientResponse, ClientSession], Awaitable[dict | list[dict]]] | None
    ) = None,
    **kwargs,
) -> dict | list[dict]:
    """
    Abstract helper to make requests from a url with potential headers and params.

    Parameters
    ----------
    url : str
        Url to make the request to
    method : str, optional
        HTTP method to use.  Can be "GET" or "POST", by default "GET"
    timeout : int, optional
        Timeout in seconds for the whole request. The `request_timeout` preference wins when
        `preferences` is passed; without a timeout, the `timeout` python setting, else 10.
    response_callback : Callable[[ClientResponse, ClientSession], Awaitable[Union[dict, list[dict]]]], optional
        Async callback with response and session as arguments that returns the json, by default None
    session : ClientSession, optional
        Custom session to use for requests, by default None


    Returns
    -------
    Union[dict, list[dict]]
        Response json
    """
    if method.upper() not in ["GET", "POST"]:
        raise ValueError("Method must be GET or POST")

    preferences = kwargs.pop("preferences", None) or {}
    if "request_timeout" in preferences:
        timeout = preferences["request_timeout"] or timeout
    if timeout is None:
        timeout = get_python_request_settings().get("timeout") or 10
    kwargs["timeout"] = timeout

    response_callback = response_callback or (
        lambda r, _: asyncio.ensure_future(r.json())
    )

    with_session = kwargs.pop("with_session", "session" in kwargs)
    session = kwargs.pop("session", await get_async_requests_session(**kwargs))

    try:
        response = await session.request(method, url, **kwargs)
        return await response_callback(response, session)
    finally:
        if not with_session:
            await session.close()


async def amake_requests(
    urls: str | list[str],
    response_callback: (
        Callable[[ClientResponse, ClientSession], Awaitable[dict | list[dict]]] | None
    ) = None,
    **kwargs,
):
    """Make multiple requests asynchronously.

    Parameters
    ----------
    urls : Union[str, list[str]]
        list of urls to make requests to
    method : Literal["GET", "POST"], optional
        HTTP method to use.  Can be "GET" or "POST", by default "GET"
    timeout : int, optional
        Timeout in seconds for each request, resolved as in `amake_request`.
    response_callback : Callable[[ClientResponse, ClientSession], Awaitable[Union[dict, list[dict]]]], optional
        Async callback with response and session as arguments that returns the json, by default None
    session : ClientSession, optional
        Custom session to use for requests, by default None

    Returns
    -------
    Union[dict, list[dict]]
        Response json
    """
    session = kwargs.pop("session", await get_async_requests_session(**kwargs))
    ret_exceptions = kwargs.pop("return_exceptions", False)
    kwargs["response_callback"] = response_callback
    urls = urls if isinstance(urls, list) else [urls]

    try:
        results: list = []
        exceptions: list = []

        for result in await asyncio.gather(
            *[amake_request(url, session=session, **kwargs) for url in urls],
            return_exceptions=True,
        ):
            is_exception = isinstance(result, Exception)

            if is_exception and (
                isinstance(result, UnauthorizedError)
                or kwargs.get("raise_for_status", False)
            ):
                assert isinstance(result, BaseException)  # noqa: S101
                raise result

            if is_exception and ret_exceptions:
                results.append(result)  # type: ignore[arg-type]
                continue

            if is_exception:
                exceptions.append(result)  # type: ignore[arg-type]
                continue

            if not result:
                continue

            if not isinstance(result, Exception):
                results.extend(result if isinstance(result, list) else [result])  # type: ignore[list-item]

        if exceptions and not results and not ret_exceptions:
            raise exceptions[0]

        return results

    finally:
        await session.close()


def combine_certificates(cert: str, bundle: str | None = None) -> str:
    """Combine a certificate and a bundle into a single certificate file. Use the default bundle if none is provided."""
    import atexit  # noqa
    import certifi
    import shutil
    from pathlib import Path
    from warnings import warn

    if not Path(cert).exists():
        raise FileNotFoundError(f"Certificate file '{cert}' not found")

    if cert.split(".", maxsplit=1)[0].endswith("_combined"):
        return cert

    combined_cert = cert.split(".", maxsplit=1)[0] + "_combined." + cert.split(".")[1]

    if Path(combined_cert).exists():
        return combined_cert

    if not bundle:
        bundle = certifi.where()

    try:
        with open(combined_cert, "wb") as combined_cert_file:
            # Write the default CA bundle to the combined certificate file
            with open(bundle, "rb") as bundle_file:
                shutil.copyfileobj(bundle_file, combined_cert_file)

            # Write the custom CA certificate to the combined certificate file
            with open(cert, "rb") as cert_file:
                shutil.copyfileobj(cert_file, combined_cert_file)

        # Register the combined certificate file for deletion.
        atexit.register(Path(combined_cert).unlink, missing_ok=True)

        return combined_cert
    except Exception as e:
        warn(
            f"An error occurred while handling the certificates file -> {e.__class__.__name__}: {e}"
        )
        return cert


def make_request(
    url: str, method: str = "GET", timeout: int = 10, **kwargs
) -> "Response":
    """Abstract helper to make requests from a url with potential headers and params.

    Parameters
    ----------
    url : str
        Url to make the request to
    method : str, optional
        HTTP method to use.  Can be "GET" or "POST", by default "GET"
    timeout : int, optional
        Timeout in seconds, by default 10.  Can be overwritten by user setting, request_timeout

    Returns
    -------
    Response
        Request response object

    Raises
    ------
    ValueError
        If invalid method is passed
    """
    # We want to add a user agent to the request, so check if there are any headers
    # If there are headers, check if there is a user agent, if not add one.
    # Some requests seem to work only with a specific user agent, so we want to be able to override it.
    python_settings = get_python_request_settings()
    headers = kwargs.pop("headers", {})
    headers.update(python_settings.pop("headers", {}))
    preferences = kwargs.pop("preferences", None)

    if preferences and "request_timeout" in preferences:
        timeout = preferences["request_timeout"] or timeout
    elif "timeout" in python_settings:
        timeout = python_settings["timeout"]

    if "User-Agent" not in headers:
        headers["User-Agent"] = get_user_agent()

    # Allow a custom session for caching, if desired
    _session = kwargs.pop("session", get_requests_session(**kwargs))

    if method.upper() == "GET":
        return _session.get(
            url,
            headers=headers,
            timeout=timeout,
            **kwargs,
        )
    if method.upper() == "POST":
        return _session.post(
            url,
            headers=headers,
            timeout=timeout,
            **kwargs,
        )
    raise ValueError("Method must be GET or POST")


def to_snake_case(string: str) -> str:
    """Convert a string to snake case."""
    import re

    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", string)
    return (
        re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1)
        .lower()
        .replace(" ", "_")
        .replace("__", "_")
    )


async def maybe_coroutine(
    func: Callable[P, T | Awaitable[T]], /, *args: P.args, **kwargs: P.kwargs
) -> T:
    """Check if a function is a coroutine and run it accordingly."""
    if not iscoroutinefunction(func):
        return cast(T, func(*args, **kwargs))

    return await func(*args, **kwargs)


def run_async(
    func: Callable[P, Awaitable[T]], /, *args: P.args, **kwargs: P.kwargs
) -> T:
    """Run a coroutine function in a blocking context."""
    if not iscoroutinefunction(func):
        return cast(T, func(*args, **kwargs))

    with start_blocking_portal() as portal:
        try:
            return portal.call(partial(func, *args, **kwargs))
        finally:
            portal.call(portal.stop)


def filter_by_dates(
    data: list[D], start_date: date | None = None, end_date: date | None = None
) -> list[D]:
    """Filter data by dates."""
    if start_date is None and end_date is None:
        return data

    def _filter(d: D) -> bool:
        _date = getattr(d, "date", None)
        dt = _date.date() if _date and isinstance(_date, datetime) else _date
        if dt:
            if start_date and end_date:
                return start_date <= dt <= end_date
            if start_date:
                return dt >= start_date
            if end_date:
                return dt <= end_date
            return True  # pragma: no cover
        return False

    return list(filter(_filter, data))


def safe_fromtimestamp(timestamp: float | int, tz: timezone | None = None) -> datetime:
    """datetime.fromtimestamp alternative which supports negative timestamps on Windows platform."""
    if os.name == "nt" and timestamp < 0:
        return datetime(1970, 1, 1, tzinfo=tz) + timedelta(seconds=timestamp)
    return datetime.fromtimestamp(timestamp, tz)
