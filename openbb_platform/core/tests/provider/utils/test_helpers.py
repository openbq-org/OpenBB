"""Test the provider helpers."""

import asyncio
import datetime as dt
from pathlib import Path
from typing import Any, cast

import pytest

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.utils.client import ClientSession
from openbb_core.provider.utils.helpers import (
    amake_request,
    amake_requests,
    check_item,
    filter_by_dates,
    get_querystring,
    get_requests_session,
    make_request,
    maybe_coroutine,
    run_async,
    to_snake_case,
)


class MockResponse:
    """Mock the response."""

    def __init__(self):
        """Initialize the mock response."""
        self.status_code = 200
        self.status = 200

    async def json(self):
        """Return the json response."""
        return {"test": "test"}


class MockSession:
    """Mock the ClientSession."""

    def __init__(self):
        """Initialize the mock session."""
        self.response = MockResponse()

    async def request(self, *args, **kwargs):
        """Mock the ClientSession.request method."""
        if kwargs.get("raise_for_status", False):
            raise Exception("Test")

        return self.response

    @staticmethod
    async def mock_callback(response, session):
        """Mock the response_callback."""
        assert response.status == 200
        return await response.json()


def test_get_querystring_exclude():
    """Test the get_querystring helper."""
    items = {
        "key1": "value1",
        "key2": "value2",
        "key3": None,
        "key4": ["value3", "value4"],
    }
    exclude = ["key2"]

    querystring = get_querystring(items, exclude)
    assert querystring == "key1=value1&key4=value3&key4=value4"


def test_get_querystring_no_exclude():
    """Test the get_querystring helper with no exclude list."""
    items = {
        "key1": "value1",
        "key2": "value2",
        "key3": None,
        "key4": ["value3", "value4"],
    }

    querystring = get_querystring(items, [])
    assert querystring == "key1=value1&key2=value2&key4=value3&key4=value4"


def test_make_request(monkeypatch):
    """Test the make_request helper."""

    def mock_get(*args, **kwargs):
        """Mock the requests.get method."""
        return MockResponse()

    client_session = get_requests_session()
    monkeypatch.setattr(client_session, "get", mock_get)

    response = make_request("http://mock.url", session=client_session)
    assert response.status_code == 200

    with pytest.raises(ValueError):
        make_request("http://mock.url", method="PUT")


def test_to_snake_case():
    """Test the to_snake_case helper."""
    assert to_snake_case("SomeRandomString") == "some_random_string"
    assert to_snake_case("someRandomString") == "some_random_string"
    assert to_snake_case("already_snake_case") == "already_snake_case"


@pytest.mark.asyncio
async def test_amake_request(monkeypatch):
    """Test the amake_request helper."""

    mock_callback = MockSession.mock_callback

    client_session = MockSession()
    monkeypatch.setattr(ClientSession, "request", client_session.request)

    response = await amake_request("http://mock.url", response_callback=mock_callback)
    assert response == {"test": "test"}

    with pytest.raises(Exception):
        await amake_request(
            "http://mock.url",
            response_callback=mock_callback,
            raise_for_status=True,
        )

    with pytest.raises(ValueError):
        await amake_request("http://mock.url", method=cast(Any, "PUT"))


@pytest.mark.asyncio
async def test_amake_requests(monkeypatch):
    """Test the amake_requests helper."""

    mock_callback = MockSession.mock_callback

    client_session = MockSession()
    monkeypatch.setattr(ClientSession, "request", client_session.request)

    multi_response = await amake_requests(
        ["http://mock.url", "http://mock.url"],
        response_callback=mock_callback,
    )
    assert multi_response == [{"test": "test"}, {"test": "test"}]

    with pytest.raises(ValueError):
        await amake_requests(
            ["http://mock.url", "http://mock.url"], method="PUT", raise_for_status=True
        )


def test_safe_fromtimestamp_negative_on_non_windows():
    import os

    from openbb_core.provider.utils.helpers import safe_fromtimestamp

    if os.name == "nt":
        pytest.skip("Windows-specific branch tested separately.")
    # Negative timestamps are well-defined on POSIX
    out = safe_fromtimestamp(-1)
    assert out.year < 1971


def test_safe_fromtimestamp_windows_negative_branch(monkeypatch):
    """Force the os.name=='nt' branch to test the timedelta fallback path."""

    from openbb_core.provider.utils import helpers

    monkeypatch.setattr(helpers, "os", type("FakeOs", (), {"name": "nt"}))
    out = helpers.safe_fromtimestamp(-3600, tz=dt.UTC)
    assert out.year == 1969


def test_safe_fromtimestamp_windows_non_negative_uses_datetime_fromtimestamp(
    monkeypatch,
):

    from openbb_core.provider.utils import helpers

    monkeypatch.setattr(helpers, "os", type("FakeOs", (), {"name": "nt"}))
    out = helpers.safe_fromtimestamp(0, tz=dt.UTC)
    assert out == dt.datetime(1970, 1, 1, tzinfo=dt.UTC)


def test_check_item_suggests_similar():
    with pytest.raises(ValueError, match="Did you mean 'apple'"):
        check_item("appl", ["apple", "banana"])


def test_check_item_no_similar_message():
    with pytest.raises(ValueError, match="'zzz' is not available\\."):
        check_item("zzz", ["apple", "banana"], threshold=0.99)


def test_to_snake_case_collapses_double_underscores():
    from openbb_core.provider.utils.helpers import to_snake_case

    assert to_snake_case("SomeABCName") == "some_abc_name"


def test_to_snake_case_replaces_spaces():
    from openbb_core.provider.utils.helpers import to_snake_case

    assert "_" in to_snake_case("Hello World")


def test_combine_certificates_returns_cert_on_write_failure(tmp_path, monkeypatch):
    """If shutil.copyfileobj raises, the original cert path is returned with a warning."""
    import shutil
    import warnings as _warnings

    from openbb_core.provider.utils import helpers

    cert = tmp_path / "ca.pem"
    cert.write_text("CERT")
    bundle = tmp_path / "bundle.pem"
    bundle.write_text("BUNDLE")

    def boom(*_a, **_kw):
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copyfileobj", boom)
    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always")
        out = helpers.combine_certificates(str(cert), str(bundle))
    # On failure, function returns the original cert string
    assert out == str(cert)
    assert any("error occurred while handling" in str(w.message) for w in caught)


def test_combine_certificates_uses_certifi_when_no_bundle(tmp_path, monkeypatch):
    """When no bundle is given, certifi.where() is used."""
    from openbb_core.provider.utils import helpers

    cert = tmp_path / "ca.pem"
    cert.write_text("CERT")
    bundle = tmp_path / "ca-bundle.pem"
    bundle.write_text("DEFAULT-BUNDLE")
    import certifi

    monkeypatch.setattr(certifi, "where", lambda: str(bundle))
    out = helpers.combine_certificates(str(cert))
    from pathlib import Path

    out_path = Path(out)
    assert out_path.exists()
    assert "DEFAULT-BUNDLE" in out_path.read_text()
    out_path.unlink(missing_ok=True)


def test_get_async_requests_session_returns_provided_session():
    """A pre-existing ClientSession is returned as-is."""
    import asyncio

    from openbb_core.provider.utils.client import ClientSession
    from openbb_core.provider.utils.helpers import get_async_requests_session

    async def _run():
        s = ClientSession()
        try:
            out = await get_async_requests_session(session=s)
            assert out is s
        finally:
            await s.close()

    asyncio.run(_run())


def test_get_async_requests_session_proxy_upgrades_https_to_http(monkeypatch):
    """When env HTTP_PROXY==HTTPS_PROXY and starts with https:, it is rewritten."""
    import asyncio

    from openbb_core.provider.utils import helpers

    monkeypatch.setattr(helpers, "get_python_request_settings", lambda: {})
    monkeypatch.setenv("HTTP_PROXY", "https://shared:1")
    monkeypatch.setenv("HTTPS_PROXY", "https://shared:1")

    async def _run():
        s = await helpers.get_async_requests_session()
        try:
            assert not s.closed
        finally:
            await s.close()

    asyncio.run(_run())


def test_get_async_requests_session_with_basic_auth(monkeypatch):
    import asyncio

    from openbb_core.provider.utils import helpers

    monkeypatch.setattr(helpers, "get_python_request_settings", lambda: {})

    async def _run():
        s = await helpers.get_async_requests_session(auth=["user", "pass"])
        try:
            assert not s.closed
        finally:
            await s.close()

    asyncio.run(_run())


def test_get_async_requests_session_with_cookies_dict(monkeypatch):
    import asyncio

    from openbb_core.provider.utils import helpers

    monkeypatch.setattr(helpers, "get_python_request_settings", lambda: {})

    async def _run():
        s = await helpers.get_async_requests_session(cookies={"k": "v"})
        try:
            assert not s.closed
        finally:
            await s.close()

    asyncio.run(_run())


def test_get_async_requests_session_with_timeout_int(monkeypatch):
    import asyncio

    from openbb_core.provider.utils import helpers

    monkeypatch.setattr(helpers, "get_python_request_settings", lambda: {"timeout": 5})

    async def _run():
        s = await helpers.get_async_requests_session()
        try:
            assert not s.closed
        finally:
            await s.close()

    asyncio.run(_run())


def test_amake_requests_raises_first_exception_when_no_results(monkeypatch):
    """When all results are exceptions and no results collected, the first is raised."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from openbb_core.provider.utils import helpers

    fake_session = MagicMock()
    fake_session.close = AsyncMock()
    monkeypatch.setattr(
        helpers, "get_async_requests_session", AsyncMock(return_value=fake_session)
    )

    async def _gather(*_args, **_kw):
        return [RuntimeError("first"), RuntimeError("second")]

    monkeypatch.setattr(asyncio, "gather", _gather)

    async def _run():
        with pytest.raises(RuntimeError, match="first"):
            await helpers.amake_requests(["http://a", "http://b"])

    asyncio.run(_run())


def test_amake_requests_returns_exceptions_when_ret_exceptions(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from openbb_core.provider.utils import helpers

    fake_session = MagicMock()
    fake_session.close = AsyncMock()
    monkeypatch.setattr(
        helpers, "get_async_requests_session", AsyncMock(return_value=fake_session)
    )

    err = RuntimeError("boom")

    async def _gather(*_args, **_kw):
        return [err, {"ok": True}]

    monkeypatch.setattr(asyncio, "gather", _gather)

    async def _run():
        out = await helpers.amake_requests(
            ["http://a", "http://b"], return_exceptions=True
        )
        assert err in out
        assert {"ok": True} in out

    asyncio.run(_run())


def test_get_async_requests_session_ssl_context_with_cert(tmp_path, monkeypatch):
    """Lines 263-279: ca/cert path builds ssl_context."""
    import asyncio

    # Build self-signed cert+key for test
    import subprocess

    from openbb_core.provider.utils import helpers as H

    cert = tmp_path / "c.pem"
    key = tmp_path / "k.pem"
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=t",
        ],
        check=True,
        capture_output=True,
    )

    async def _go():
        s = await H.get_async_requests_session(
            cafile=str(cert), certfile=str(cert), keyfile=str(key)
        )
        await s.close()

    asyncio.run(_go())


def test_get_async_requests_session_password_and_proxy_headers_do_not_crash(
    monkeypatch,
):
    """python_settings.http.password/proxy_headers must never reach
    ClientSession(**conn_kwargs) directly; aiohttp accepts neither as a
    constructor kwarg.
    """
    import asyncio

    from openbb_core.provider.utils import helpers as H

    monkeypatch.setattr(
        H,
        "get_python_request_settings",
        lambda: {"password": "secret", "proxy_headers": {"X-Foo": "bar"}},
    )

    async def _go():
        s = await H.get_async_requests_session()
        await s.close()

    asyncio.run(_go())


def test_get_async_requests_session_ssl_password_still_used(tmp_path, monkeypatch):
    """The password setting must still reach ssl_context.load_cert_chain."""
    import asyncio
    import subprocess

    from openbb_core.provider.utils import helpers as H

    cert = tmp_path / "c.pem"
    key = tmp_path / "k.pem"
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=t",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "openssl",
            "rsa",
            "-in",
            str(key),
            "-out",
            str(key),
            "-aes256",
            "-passout",
            "pass:correct-horse",
        ],
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(
        H,
        "get_python_request_settings",
        lambda: {
            "certfile": str(cert),
            "keyfile": str(key),
            "password": "wrong-password",
        },
    )

    async def _go():
        await H.get_async_requests_session()

    with pytest.raises(Exception, match="PEM"):
        asyncio.run(_go())


def test_get_async_requests_session_with_basic_auth_and_cookies():
    """Lines 303, 317-318: proxy_auth/auth/dict cookies."""
    import asyncio

    from openbb_core.provider.utils import helpers as H

    async def _go():
        s = await H.get_async_requests_session(
            proxy_auth=("u", "p"),
            auth=("a", "b"),
            cookies={"k": "v"},
        )
        await s.close()

    asyncio.run(_go())


def test_get_requests_session_verify_false_and_auth_and_cookies(monkeypatch):
    from openbb_core.provider.utils import helpers

    monkeypatch.setattr(
        helpers,
        "get_python_request_settings",
        lambda: {
            "verify_ssl": False,
            "cookies": {"k": "v"},
            "auth": ["u", "p"],
        },
    )
    sess = helpers.get_requests_session()
    assert sess.verify is False
    assert sess.cookies.get("k") == "v"
    assert sess.auth == ("u", "p")


def test_get_requests_session_combine_certs_and_cert_tuple(monkeypatch, tmp_path):
    from openbb_core.provider.utils import helpers

    cert = tmp_path / "ca.pem"
    key = tmp_path / "key.pem"
    cert.write_text("CERT")
    key.write_text("KEY")
    monkeypatch.setattr(
        helpers,
        "get_python_request_settings",
        lambda: {"cafile": str(cert), "certfile": str(cert), "keyfile": str(key)},
    )
    monkeypatch.setattr(helpers, "combine_certificates", lambda *_a, **_k: "combined")
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    sess = helpers.get_requests_session()
    assert sess.verify == "combined"
    assert sess.cert == (str(cert), str(key))


def test_get_requests_session_proxies_and_kwargs_update(monkeypatch):
    from openbb_core.provider.utils import helpers

    monkeypatch.setattr(helpers, "get_python_request_settings", lambda: {"headers": {}})
    monkeypatch.setenv("HTTP_PROXY", "http://same")
    monkeypatch.setenv("HTTPS_PROXY", "http://same")
    sess = helpers.get_requests_session(params={"a": 1})
    assert sess.proxies["http"] == "http://same"
    assert sess.proxies["https"] == "http://same"
    assert cast(dict, sess.params)["a"] == 1


def test_get_requests_session_kwargs_attribute_error_branch(monkeypatch):
    from openbb_core.provider.utils import helpers

    class _Bad:
        headers = {}
        trust_env = True
        proxies = {}
        verify = True
        cert = None
        cookies = {}
        auth = None

        @property
        def ro(self):
            return 1

    monkeypatch.setattr(helpers, "get_python_request_settings", lambda: {})
    monkeypatch.setattr("requests.Session", _Bad)
    sess = helpers.get_requests_session(ro=2)
    assert sess.trust_env is False


def test_get_async_requests_session_ssl_context_from_settings(monkeypatch, tmp_path):
    import asyncio
    import subprocess

    from openbb_core.provider.utils import helpers as H

    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=test",
        ],
        check=True,
        capture_output=True,
    )

    monkeypatch.setattr(
        H,
        "get_python_request_settings",
        lambda: {"cafile": str(cert), "certfile": str(cert), "keyfile": str(key)},
    )

    async def _go():
        s = await H.get_async_requests_session()
        await s.close()

    asyncio.run(_go())


def test_get_async_requests_session_cookiejar_branch(monkeypatch):
    import asyncio

    import aiohttp

    from openbb_core.provider.utils import helpers as H

    monkeypatch.setattr(H, "get_python_request_settings", lambda: {})

    async def _go():
        jar = aiohttp.CookieJar()
        jar.update_cookies({"k": "v"})
        s = await H.get_async_requests_session(cookies=jar)
        await s.close()

    asyncio.run(_go())


def test_get_async_requests_session_atexit_closes_orphan(monkeypatch):
    import asyncio

    from openbb_core.provider.utils import helpers as H

    monkeypatch.setattr(H, "get_python_request_settings", lambda: {})
    captured = {}

    def _register(fn, session):
        captured["fn"] = fn
        captured["session"] = session

    monkeypatch.setattr("atexit.register", _register)
    called = {"closed": 0}
    monkeypatch.setattr(
        H, "run_async", lambda fn: called.__setitem__("closed", called["closed"] + 1)
    )

    async def _go():
        s = await H.get_async_requests_session()
        captured["fn"](s)
        await s.close()

    asyncio.run(_go())
    assert called["closed"] >= 1


@pytest.mark.asyncio
async def test_amake_requests_skips_falsey_results(monkeypatch):
    async def _gather(*_args, **_kwargs):
        return [None, {}, [], {"ok": True}]

    class _S:
        async def close(self):
            return None

    from openbb_core.provider.utils import helpers

    async def _session_factory(**_k):
        return _S()

    monkeypatch.setattr(asyncio, "gather", _gather)
    monkeypatch.setattr(helpers, "get_async_requests_session", _session_factory)
    out = await helpers.amake_requests(["a", "b"])
    assert out == [{"ok": True}]


def test_combine_certificates_file_not_found():
    from openbb_core.provider.utils.helpers import combine_certificates

    with pytest.raises(FileNotFoundError):
        combine_certificates("/no/such/cert.pem")


def test_combine_certificates_returns_same_for_combined_suffix(tmp_path):
    from openbb_core.provider.utils.helpers import combine_certificates

    cert = tmp_path / "ca_combined.pem"
    cert.write_text("CERT")
    assert combine_certificates(str(cert)) == str(cert)


def test_combine_certificates_returns_existing_combined_file(tmp_path):
    from openbb_core.provider.utils.helpers import combine_certificates

    cert = tmp_path / "ca.pem"
    cert.write_text("CERT")
    combined = tmp_path / "ca_combined.pem"
    combined.write_text("COMBINED")
    assert combine_certificates(str(cert)) == str(combined)


def test_combine_certificates_cleanup_tolerates_missing_file(tmp_path, monkeypatch):
    """The registered atexit cleanup must not raise if the file is already gone."""
    import atexit

    import certifi

    from openbb_core.provider.utils import helpers

    cert = tmp_path / "ca.pem"
    cert.write_text("CERT")
    bundle = tmp_path / "ca-bundle.pem"
    bundle.write_text("BUNDLE")
    monkeypatch.setattr(certifi, "where", lambda: str(bundle))

    registered: list = []
    monkeypatch.setattr(
        atexit, "register", lambda func, *a, **kw: registered.append((func, a, kw))
    )

    out = Path(helpers.combine_certificates(str(cert)))
    assert out.exists()
    assert registered

    # Something else removes it first - the cleanup must still be a no-op.
    out.unlink()
    for func, args, kwargs in registered:
        func(*args, **kwargs)


def test_make_request_timeout_from_preferences(monkeypatch):
    captured = {}

    class _S:
        def get(self, *_a, **kwargs):
            captured["timeout"] = kwargs["timeout"]
            return MockResponse()

        def post(self, *_a, **_k):
            return MockResponse()

    monkeypatch.setattr(
        "openbb_core.provider.utils.helpers.get_python_request_settings", lambda: {}
    )
    monkeypatch.setattr(
        "openbb_core.provider.utils.helpers.get_requests_session", lambda **_k: _S()
    )
    make_request("http://mock.url", preferences={"request_timeout": 2})
    assert captured["timeout"] == 2


def test_make_request_timeout_from_python_settings(monkeypatch):
    captured = {}

    class _S:
        def get(self, *_a, **kwargs):
            captured["timeout"] = kwargs["timeout"]
            return MockResponse()

        def post(self, *_a, **_k):
            return MockResponse()

    monkeypatch.setattr(
        "openbb_core.provider.utils.helpers.get_python_request_settings",
        lambda: {"timeout": 3, "headers": {}},
    )
    monkeypatch.setattr(
        "openbb_core.provider.utils.helpers.get_requests_session", lambda **_k: _S()
    )
    make_request("http://mock.url")
    assert captured["timeout"] == 3


def test_make_request_post_branch(monkeypatch):
    called = {"post": 0}

    class _S:
        def get(self, *_a, **_k):
            return MockResponse()

        def post(self, *_a, **_k):
            called["post"] += 1
            return MockResponse()

    monkeypatch.setattr(
        "openbb_core.provider.utils.helpers.get_python_request_settings", lambda: {}
    )
    monkeypatch.setattr(
        "openbb_core.provider.utils.helpers.get_requests_session", lambda **_k: _S()
    )
    resp = make_request("http://mock.url", method="POST")
    assert resp.status_code == 200
    assert called["post"] == 1


@pytest.mark.asyncio
async def test_maybe_coroutine_both_paths():
    def _sync(x):
        return x + 1

    async def _async(x):
        return x + 2

    assert await maybe_coroutine(_sync, 1) == 2
    assert await maybe_coroutine(_async, 1) == 3


def test_run_async_sync_path():
    assert run_async(lambda x: x + 1, 2) == 3


def test_run_async_async_path():
    async def _coro(x):
        return x + 1

    assert run_async(_coro, 2) == 3


class _Item(Data):
    def __init__(self, dt):
        super().__init__(date=dt)


def test_filter_by_dates_no_bounds_returns_input():
    data = [_Item(dt.date(2024, 1, 1))]
    assert filter_by_dates(data) == data


def test_filter_by_dates_start_and_end():
    data = [_Item(dt.date(2024, 1, 1)), _Item(dt.date(2024, 2, 1))]
    out = filter_by_dates(
        data, start_date=dt.date(2024, 1, 15), end_date=dt.date(2024, 2, 2)
    )
    assert len(out) == 1


def test_filter_by_dates_only_start():
    data = [_Item(dt.date(2024, 1, 1)), _Item(dt.datetime(2024, 2, 1))]
    out = filter_by_dates(data, start_date=dt.date(2024, 2, 1))
    assert len(out) == 1


def test_filter_by_dates_only_end_and_missing_date():
    class _NoDate(Data):
        pass

    data = [_Item(dt.date(2024, 3, 1)), _NoDate()]
    out = filter_by_dates(data, end_date=dt.date(2024, 2, 1))
    assert out == []
