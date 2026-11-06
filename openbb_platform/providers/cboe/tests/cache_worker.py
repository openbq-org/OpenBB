"""One OS process making cached requests, for the tests that share a cache file.

Run as ``cache_worker.py URL CACHE_FILE ROUNDS REQUESTS_PER_ROUND THREADS``. Each
thread runs bursts of concurrent requests on an event loop of its own, over a few
dozen URLs the other processes ask for too, and the last line printed is a JSON
summary of how many succeeded and what the failures were.
"""

import asyncio
import collections
import json
import logging
import sys
import threading
import traceback
from pathlib import Path

from openbb_cboe.utils import helpers

URL, CACHE_FILE, ROUNDS, PER_ROUND, THREADS = sys.argv[1:6]
URLS = 40
# Requests in flight per event loop. A test server can only queue so many
# connections at once (128 on macOS); this keeps the workers' total under it, so
# what the test measures is the cache and not the server's accept queue.
IN_FLIGHT = 2

logging.disable(logging.CRITICAL)
helpers.cache_path = lambda: CACHE_FILE
succeeded = 0
failures: collections.Counter = collections.Counter()


async def request(number, turn):
    """Request one URL, recording how it went."""
    global succeeded  # noqa: PLW0603

    try:
        async with turn:
            await asyncio.wait_for(
                helpers.get_cboe_data(f"{URL}/{number % URLS}.json"), timeout=30
            )

        succeeded += 1
    except Exception as error:  # noqa: BLE001
        frames = traceback.extract_tb(error.__traceback__)[-4:]
        where = " <- ".join(
            f"{Path(frame.filename).name}:{frame.lineno} {frame.name}"
            for frame in reversed(frames)
        )
        failures[f"{type(error).__name__}: {error} (at {where})"] += 1


def work(thread):
    """Run the bursts of one thread, each on a new event loop."""

    async def burst(first):
        turn = asyncio.Semaphore(IN_FLIGHT)

        await asyncio.gather(*(request(first + n, turn) for n in range(int(PER_ROUND))))

    for round_number in range(int(ROUNDS)):
        asyncio.run(burst(round_number * int(PER_ROUND) + thread * 7))


threads = [threading.Thread(target=work, args=(n,)) for n in range(int(THREADS))]

for thread in threads:
    thread.start()

for thread in threads:
    thread.join()

sys.stdout.write(json.dumps({"succeeded": succeeded, "failures": failures}) + "\n")
