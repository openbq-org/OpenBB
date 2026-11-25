"""Ticker subscriptions over the Deribit websocket."""

WS_URL = "wss://www.deribit.com/ws/api/v2"
SUBSCRIBE_TIMEOUT = 15.0


async def _collect(websocket, wanted: set, received: dict, messages: set) -> None:
    """Read tickers off one subscription until every symbol has arrived."""
    import json

    from websockets import ConnectionClosed

    while True:
        try:
            frame = await websocket.recv()
        except ConnectionClosed:
            return

        payload = json.loads(frame)

        if payload.get("error"):
            messages.add(f"Deribit returned an error -> {payload['error']}")
            return

        ticker = (payload.get("params") or {}).get("data") or {}
        symbol = ticker.get("instrument_name")

        if not symbol or symbol in received:
            continue

        received[symbol] = ticker

        if wanted <= set(received):
            return


async def subscribe_tickers(symbols: list[str], messages: set) -> dict[str, dict]:
    """Return the ticker of every symbol on one subscription.

    Parameters
    ----------
    symbols : list[str]
        The instrument names to subscribe to.
    messages : set
        Collects what went wrong, for the caller to warn about.

    Returns
    -------
    dict[str, dict]
        The ticker of each symbol that published one.
    """
    import asyncio
    import json

    from websockets.asyncio.client import connect

    received: dict[str, dict] = {}
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "public/subscribe",
        "params": {"channels": [f"ticker.{symbol}.100ms" for symbol in symbols]},
    }

    try:
        async with connect(WS_URL) as websocket:
            await websocket.send(json.dumps(request))

            try:
                await asyncio.wait_for(
                    _collect(websocket, set(symbols), received, messages),
                    timeout=SUBSCRIBE_TIMEOUT,
                )
            except TimeoutError:
                missing = len(symbols) - len(received)
                messages.add(
                    f"Deribit did not publish {missing} of {len(symbols)} contracts"
                    " before the subscription timed out."
                )
    except Exception as error:  # noqa: BLE001
        messages.add(
            f"The Deribit subscription failed -> {error.__class__.__name__}: {error}"
        )

    return received
