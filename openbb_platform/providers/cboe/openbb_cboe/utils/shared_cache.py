"""Response cache whose storage is reached through another event loop.

An aiosqlite connection, and the lock that guards it, only work on the event
loop that first used them. Cboe requests run on whichever loop their caller
has - core's ``run_async`` gives every synchronous call a thread and a loop of
its own - so the one connection they all share has to live on a loop of its
own, and each request reaches it from wherever it is running. These classes are
that reach: they implement the storage interface ``aiohttp_client_cache`` asks
of a custom backend and leave the work to a ``call`` function.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from aiohttp_client_cache import CacheBackend
from aiohttp_client_cache.backends import BaseCache

StoreCall = Callable[..., Awaitable[Any]]
"""``call(table, method, *args)`` runs a store's method where its connection is.

A method that yields, like ``keys``, comes back as the list of what it yielded.
"""


class SharedStore(BaseCache):
    """One table of the shared cache, usable from any event loop.

    Parameters
    ----------
    table : str
        The name of the backend's store this stands for, ``responses`` or
        ``redirects``.
    call : StoreCall
        Runs a method of that store where the connection is.
    """

    def __init__(self, table: str, call: StoreCall) -> None:
        super().__init__()
        self._table = table
        self._call = call

    async def contains(self, key: str) -> bool:
        """Check if a key is stored in the cache."""
        return await self._call(self._table, "contains", key)

    async def clear(self) -> None:
        """Delete all items from the cache."""
        await self._call(self._table, "clear")

    async def close(self) -> None:
        """Leave the connection open: other requests are still using it."""

    async def delete(self, key: str) -> None:
        """Delete an item from the cache."""
        await self._call(self._table, "delete", key)

    async def bulk_delete(self, keys: set) -> None:
        """Delete items from the cache."""
        await self._call(self._table, "bulk_delete", keys)

    async def keys(self) -> AsyncIterator[str]:  # type: ignore[override]
        """Yield all keys stored in the cache."""
        for key in await self._call(self._table, "keys"):
            yield key

    async def read(self, key: str) -> Any:
        """Read an item from the cache; ``None`` if it is missing."""
        return await self._call(self._table, "read", key)

    async def size(self) -> int:
        """Get the number of items in the cache."""
        return await self._call(self._table, "size")

    async def values(self) -> AsyncIterator[Any]:  # type: ignore[override]
        """Yield all values stored in the cache."""
        for value in await self._call(self._table, "values"):
            yield value

    async def write(self, key: str, item: Any) -> None:
        """Write an item to the cache."""
        await self._call(self._table, "write", key, item)


class SharedCache(CacheBackend):
    """A response cache that keeps what it stores through ``call``.

    Expiry, keys and redirects are decided here, on the caller's loop, as they
    are for any backend; only reading and writing leave it.

    Parameters
    ----------
    call : StoreCall
        Runs a store's method where the connection is.
    **kwargs
        The settings of ``aiohttp_client_cache.CacheBackend``.
    """

    def __init__(self, call: StoreCall, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.responses = SharedStore("responses", call)
        self.redirects = SharedStore("redirects", call)
