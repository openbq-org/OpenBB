"""IBKR connection helper using ib_insync."""

import asyncio
import threading
from typing import Any, Callable


def run_in_new_loop(func: Callable, *args: Any, **kwargs: Any) -> Any:
    """Run a blocking ib_insync call in a new thread with its own event loop.

    OpenBB uses asyncio internally, and so does ib_insync. Running both in the
    same event loop causes a conflict, so we isolate the IBKR call in a thread.
    """
    result: list = []
    error: list = []

    def target() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result.append(func(*args, **kwargs))
        except Exception as e:  # pylint: disable=broad-except
            error.append(e)
        finally:
            loop.close()

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()

    if error:
        raise error[0]
    return result[0]


def fetch_historical_bars(
    symbol: str,
    end_date_str: str,
    duration_str: str,
    bar_size: str,
    what_to_show: str,
    use_rth: bool,
    host: str,
    port: int,
    client_id: int,
) -> list[dict]:
    """Fetch historical bar data from IBKR TWS/Gateway."""
    from ib_insync import IB, Stock  # pylint: disable=import-outside-toplevel

    def _fetch() -> list[dict]:
        ib = IB()
        ib.connect(host, port, clientId=client_id)
        try:
            contract = Stock(symbol.upper(), "SMART", "USD")
            bars = ib.reqHistoricalData(
                contract,
                endDateTime=end_date_str,
                durationStr=duration_str,
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=use_rth,
                formatDate=1,
            )
        finally:
            ib.disconnect()

        return [
            {
                "date": bar.date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "bar_count": bar.barCount,
                "average": bar.average,
            }
            for bar in bars
        ]

    return run_in_new_loop(_fetch)
