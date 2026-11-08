"""Tests for openbb_cboe.utils.shared_cache."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from openbb_cboe.utils.shared_cache import SharedCache, SharedStore


async def _gather(iterable):
    """Collect everything an async iterable yields."""
    return [item async for item in iterable]


class TestSharedStore:
    """A store hands every operation to ``call``, whichever loop it is used on."""

    @pytest.mark.parametrize(
        ("method", "args", "returned"),
        [
            ("contains", ("key",), True),
            ("read", ("key",), "item"),
            ("size", (), 7),
            ("write", ("key", "item"), None),
            ("delete", ("key",), None),
            ("bulk_delete", ({"key"},), None),
            ("clear", (), None),
        ],
    )
    def test_an_operation_is_run_where_the_connection_is(self, method, args, returned):
        """The table, the method and its arguments go over, and the result comes back."""
        call = AsyncMock(return_value=returned)
        store = SharedStore("responses", call)

        result = asyncio.run(getattr(store, method)(*args))

        assert result == returned
        call.assert_awaited_once_with("responses", method, *args)

    @pytest.mark.parametrize("method", ["keys", "values"])
    def test_what_is_yielded_is_yielded_here(self, method):
        """Keys and values arrive gathered, and are yielded on the caller's loop."""
        call = AsyncMock(return_value=["a", "b"])
        store = SharedStore("redirects", call)

        assert asyncio.run(_gather(getattr(store, method)())) == ["a", "b"]
        call.assert_awaited_once_with("redirects", method)

    def test_closing_leaves_the_connection_to_the_cache(self):
        """Other requests are still using the connection, so a session may not close it."""
        call = AsyncMock()

        asyncio.run(SharedStore("responses", call).close())

        call.assert_not_awaited()

    def test_pop_reads_then_deletes(self):
        """The base class's ``pop`` works through the same two operations."""
        call = AsyncMock(side_effect=lambda table, method, *args: "item")

        assert asyncio.run(SharedStore("responses", call).pop("key")) == "item"
        assert [step.args[1] for step in call.await_args_list] == ["read", "delete"]

    def test_an_error_where_the_connection_is_reaches_the_caller(self):
        """A failed read is the failure of the request that made it."""
        call = AsyncMock(side_effect=OSError("disk"))

        with pytest.raises(OSError):
            asyncio.run(SharedStore("responses", call).read("key"))


class TestSharedCache:
    """The backend decides expiry and keys itself, and stores through ``call``."""

    def test_its_tables_are_the_responses_and_the_redirects(self):
        """Each table of the backend is a store of the same name."""
        call = AsyncMock()
        cache = SharedCache(call)

        asyncio.run(cache.responses.write("key", "item"))
        asyncio.run(cache.redirects.write("alias", "key"))

        assert [step.args[:2] for step in call.await_args_list] == [
            ("responses", "write"),
            ("redirects", "write"),
        ]

    def test_it_keeps_the_settings_it_is_given(self):
        """Expiry is applied on the caller's loop, from the backend's own settings."""
        cache = SharedCache(
            AsyncMock(),
            expire_after=60,
            urls_expire_after={"*/book/*": 5},
            autoclose=False,
        )

        assert cache.expire_after == 60
        assert cache.urls_expire_after == {"*/book/*": 5}
        assert cache.autoclose is False

    def test_closing_it_does_not_close_the_shared_connection(self):
        """Closing the backend is not closing the connection other requests use."""
        call = AsyncMock()

        asyncio.run(SharedCache(call).close())

        call.assert_not_awaited()
