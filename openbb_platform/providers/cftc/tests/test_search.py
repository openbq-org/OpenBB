import asyncio
from datetime import UTC, date, timedelta

import pytest
from openbb_core.app.model.abstract.error import OpenBBError

from openbb_cftc.utils import search, store

END = date(2026, 7, 16)

_REAL_POST_SEARCH = search.post_search


class _FakeResponse:
    def __init__(self, body, status=200, raises=None):
        self.status = status
        self._body = body
        self._raises = raises

    async def json(self, content_type=None):
        return self._body

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    async def __aenter__(self):
        if self._raises:
            raise self._raises
        return self

    async def __aexit__(self, *args):
        return False


class _FakeSession:
    def __init__(self, response, capture):
        self._response = response
        self._capture = capture

    def post(self, url, json=None, headers=None):
        self._capture.append({"url": url, "json": json, "headers": headers})
        return self._response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _patch_post(monkeypatch, response):
    import aiohttp

    capture: list = []
    monkeypatch.setattr(
        aiohttp, "ClientSession", lambda *a, **k: _FakeSession(response, capture)
    )

    return capture


def _unblock(monkeypatch):
    monkeypatch.setattr("openbb_cftc.utils.search.post_search", _REAL_POST_SEARCH)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("rates", "RATES"), ("RATES", "RATES"), (" forex ", "FOREIGNEXCHANGE")],
)
def test_normalize_search_asset_class(value, expected):
    assert search.normalize_search_asset_class(value) == expected


def test_normalize_search_asset_class_rejects_unknown():
    with pytest.raises(OpenBBError, match="Invalid asset class"):
        search.normalize_search_asset_class("weather")


@pytest.mark.parametrize(
    ("end_of_day", "expected"),
    [(False, "2026-07-16T00:00:00.000Z"), (True, "2026-07-16T23:59:59.999Z")],
)
def test_format_search_datetime(end_of_day, expected):
    assert search.format_search_datetime(END, end_of_day=end_of_day) == expected


def test_build_search_payload_carries_every_field():
    payload = search.build_search_payload(
        "rates",
        currency="CHF",
        upi_short_name="NA/Swap OIS CHF",
        upi="QZH55DK310GD",
    )

    assert payload == {
        "jurisdiction": "CFTC",
        "assetClass": "RATES",
        "currency": "CHF",
        "minNotionalAmount": "0",
        "maxNotionalAmount": "999999999999",
        "displayType": "w",
        "disseminationDateTimeLow": None,
        "disseminationDateTimeHigh": None,
        "productId": None,
        "underlyingAsset": None,
        "upi": "QZH55DK310GD",
        "upiShortName": "NA/Swap OIS CHF",
        "name": None,
        "searchIndicator": "post",
    }
    assert isinstance(payload["minNotionalAmount"], str)
    assert isinstance(payload["maxNotionalAmount"], str)


def test_build_search_payload_commodities_nulls_the_upi_side():
    commodities = search.build_search_payload(
        "commodities",
        currency="USD",
        upi_short_name="NA/Swap OIS USD",
        upi="QZH55DK310GD",
        product_id="Commodity:Energy:Oil:Swap:Cash",
        underlying_asset="WTI",
    )
    rates = search.build_search_payload(
        "rates",
        product_id="Commodity:Energy:Oil:Swap:Cash",
        underlying_asset="WTI",
    )

    assert commodities["upi"] is None
    assert commodities["upiShortName"] is None
    assert commodities["currency"] is None
    assert commodities["productId"] == "Commodity:Energy:Oil:Swap:Cash"
    assert commodities["underlyingAsset"] == "WTI"

    assert rates["productId"] is None
    assert rates["underlyingAsset"] is None


def test_map_search_record_decodes_and_renames():
    mapped = search.map_search_record(
        {
            "uniqueProductIdentifierShortName": "NA%2FSwap%20OIS%20CHF",
            "uniqueProductIdentifierUnderlierName": "CHF-SARON-OIS%20Compound",
            "uniqueProductIdentifier": "QZJCR16V3FG5",
            "disseminationIdentifier": "3731277599000001601",
            "actionType": "NEWT",
            "eventType": "TRAD",
            "effectiveDate": "2028-03-15",
            "expirationDate": "2029-03-15",
            "fixedRateLeg1": "0.0033",
            "fixedRateLeg2": "",
            "notionalAmountLeg1": "79,326,002+",
            "notionalAmountLeg2": 79326002,
            "notionalCurrencyLeg1": "CHF",
            "notionalCurrencyLeg2": "CHF",
            "disseminationTimestamp": "2026-06-17T14:57:40Z",
            "cleared": "I",
            "platformIdentifier": "TWSF",
            "packageIndicator": False,
        }
    )

    assert mapped["UPI FISN"] == "NA/Swap OIS CHF"
    assert mapped["Cleared"] == "I"
    assert mapped["UPI Underlier Name"] == "CHF-SARON-OIS Compound"
    assert mapped["Unique Product Identifier"] == "QZJCR16V3FG5"
    assert mapped["Dissemination Identifier"] == "3731277599000001601"
    assert mapped["Action type"] == "NEWT"
    assert mapped["Event type"] == "TRAD"
    assert mapped["Effective Date"] == "2028-03-15"
    assert mapped["Expiration Date"] == "2029-03-15"
    assert mapped["Fixed rate-Leg 1"] == "0.0033"
    assert mapped["Notional amount-Leg 1"] == "79,326,002+"
    assert mapped["Notional amount-Leg 2"] == 79326002
    assert mapped["Notional currency-Leg 1"] == "CHF"
    assert mapped["Dissemination Timestamp"] == "2026-06-17T14:57:40Z"
    assert mapped["Platform identifier"] == "TWSF"
    assert mapped["Package indicator"] is False

    from openbb_cftc.utils.constants import SLICE_HEADERS

    assert set(mapped) <= set(SLICE_HEADERS) | set(search.SEARCH_ALIASES.values())


def test_map_search_record_carries_the_full_disseminated_column_set():
    mapped = search.map_search_record(
        {
            "executionTimestamp": "2026-07-24T20:45:34Z",
            "eventTimestamp": "2026-07-24T20:45:34Z",
            "originalDisseminationIdentifier": "1718697525",
            "fixedRatePaymentFrequencyPeriodLeg1": "YEAR",
            "fixedRatePaymentFrequencyPeriodMultiplierLeg1": "1",
            "floatingRateDaycountConventionLeg2": "A004",
            "fixedRateDaycountConventionleg1": "A004",
            "otherPaymentAmount": "631228.00000",
            "otherPaymentType": "UFRO",
            "otherPaymentCurrency": "USD",
            "packageTransactionPrice": "-1,311,809",
            "packageTransactionPriceNotation": "1",
            "spreadLeg1": "-0.0002625",
            "callAmountLeg1": "190476",
            "callCurrencyLeg1": "USD",
            "putAmountLeg1": "2000000",
            "putCurrencyLeg1": "NOK",
            "callAmountLeg2": "999",
            "putAmountLeg2": "999",
            "settlementLocationLeg1": "US",
            "settlementLocationLeg2": "GB",
            "strikePriceCurrencyOrCurrencypair": "USD/NOK",
            "exchangeRate": "10.5",
            "exchangeRateBasis": "USD/NOK",
            "optionType": "PUTO",
            "firstExerciseDate": "2026-07-24",
        }
    )

    assert mapped["Execution Timestamp"] == "2026-07-24T20:45:34Z"
    assert mapped["Event timestamp"] == "2026-07-24T20:45:34Z"
    assert mapped["Original Dissemination Identifier"] == "1718697525"
    assert mapped["Fixed rate payment frequency period-Leg 1"] == "YEAR"
    assert mapped["Fixed rate payment frequency period multiplier-Leg 1"] == "1"
    assert mapped["Floating rate day count convention-leg 2"] == "A004"
    assert mapped["Fixed rate day count convention-leg 1"] == "A004"
    assert mapped["Other payment amount"] == "631228.00000"
    assert mapped["Other payment type"] == "UFRO"
    assert mapped["Other payment currency"] == "USD"
    assert mapped["Package transaction price"] == "-1,311,809"
    assert mapped["Package transaction price notation"] == "1"
    assert mapped["Spread-Leg 1"] == "-0.0002625"
    assert mapped["Call amount"] == "190476"
    assert mapped["Call currency"] == "USD"
    assert mapped["Put amount"] == "2000000"
    assert mapped["Put currency"] == "NOK"
    assert mapped["Settlement location"] == "US"
    assert mapped["Strike price currency/currency pair"] == "USD/NOK"
    assert mapped["Exchange rate"] == "10.5"
    assert mapped["Exchange rate basis"] == "USD/NOK"
    assert mapped["Option Type"] == "PUTO"
    assert mapped["First exercise date"] == "2026-07-24"
    assert "callAmountLeg2" not in mapped
    assert "putAmountLeg2" not in mapped
    assert "settlementLocationLeg2" not in mapped


def test_post_search_returns_the_trade_list(monkeypatch):
    _unblock(monkeypatch)
    capture = _patch_post(
        monkeypatch, _FakeResponse({"tradeList": [{"a": 1}], "errorList": None})
    )
    rows = asyncio.run(search.post_search({"searchIndicator": "post"}))

    assert rows == [{"a": 1}]
    assert capture[0]["url"].endswith("/ppd/api/search/webdisplay")
    assert capture[0]["json"] == {"searchIndicator": "post"}
    assert capture[0]["headers"]["Content-Type"] == "application/json"


def test_post_search_raises_on_errors_returned_with_http_200(monkeypatch):
    _unblock(monkeypatch)
    _patch_post(
        monkeypatch,
        _FakeResponse(
            {
                "tradeList": None,
                "errorList": [
                    {
                        "errorCode": 1009,
                        "errorMessage": "Dissemination Date Time format is not correct.",
                    }
                ],
            }
        ),
    )

    with pytest.raises(OpenBBError, match="Dissemination Date Time format"):
        asyncio.run(search.post_search({}))


def test_post_search_error_without_a_message(monkeypatch):
    _unblock(monkeypatch)
    _patch_post(monkeypatch, _FakeResponse({"errorList": [{"errorCode": 9}]}))

    with pytest.raises(OpenBBError, match="errorCode"):
        asyncio.run(search.post_search({}))


def test_post_search_null_trade_list_is_empty(monkeypatch):
    _unblock(monkeypatch)
    _patch_post(monkeypatch, _FakeResponse({"tradeList": None, "errorList": None}))

    assert asyncio.run(search.post_search({})) == []


def test_post_search_wraps_transport_failures(monkeypatch):
    _unblock(monkeypatch)
    _patch_post(monkeypatch, _FakeResponse({}, raises=RuntimeError("connection reset")))

    with pytest.raises(OpenBBError, match="Failed to query the PPD search endpoint"):
        asyncio.run(search.post_search({}))


def test_post_search_rejects_a_non_object_body(monkeypatch):
    _unblock(monkeypatch)
    _patch_post(monkeypatch, _FakeResponse(["nope"]))

    with pytest.raises(OpenBBError, match="Unexpected PPD search response"):
        asyncio.run(search.post_search({}))


def test_search_window_returns_rows_below_the_cap(monkeypatch):
    windows: list = []

    async def _post(payload):
        windows.append(
            (payload["disseminationDateTimeLow"], payload["disseminationDateTimeHigh"])
        )
        return [{"row": 1}]

    monkeypatch.setattr(search, "post_search", _post)
    rows = asyncio.run(search.search_window({}, date(2026, 7, 1), END))

    assert rows == [{"row": 1}]
    assert windows == [("2026-07-01T00:00:00.000Z", "2026-07-16T23:59:59.999Z")]


def test_search_window_bisects_a_truncated_window(monkeypatch):
    windows: list = []

    async def _post(payload):
        low = payload["disseminationDateTimeLow"][:10]
        high = payload["disseminationDateTimeHigh"][:10]
        windows.append((low, high))

        if (low, high) == ("2026-07-01", "2026-07-16"):
            return [{"n": i} for i in range(search.SEARCH_ROW_CAP)]

        return [{"n": low}]

    monkeypatch.setattr(search, "post_search", _post)
    rows = asyncio.run(search.search_window({}, date(2026, 7, 1), END))

    assert rows == [{"n": "2026-07-01"}, {"n": "2026-07-09"}]
    assert windows == [
        ("2026-07-01", "2026-07-16"),
        ("2026-07-01", "2026-07-08"),
        ("2026-07-09", "2026-07-16"),
    ]


def test_search_window_bisects_down_to_adjacent_days(monkeypatch):
    windows: list = []

    async def _post(payload):
        low = payload["disseminationDateTimeLow"][:10]
        high = payload["disseminationDateTimeHigh"][:10]
        windows.append((low, high))

        if low != high:
            return [{"n": i} for i in range(search.SEARCH_ROW_CAP)]

        return [{"n": low}]

    monkeypatch.setattr(search, "post_search", _post)
    rows = asyncio.run(search.search_window({}, date(2026, 7, 15), END))

    assert rows == [{"n": "2026-07-15"}, {"n": "2026-07-16"}]
    assert windows == [
        ("2026-07-15", "2026-07-16"),
        ("2026-07-15", "2026-07-15"),
        ("2026-07-16", "2026-07-16"),
    ]


def test_search_window_splits_a_capped_day_by_notional(monkeypatch):
    seen: list = []

    async def _post(payload):
        lo, hi = payload["minNotionalAmount"], payload["maxNotionalAmount"]

        if (lo, hi) == ("0", "1000000000000"):
            return [{"n": i} for i in range(search.SEARCH_ROW_CAP)]

        seen.append((int(lo), int(hi)))

        return [{"band": lo}]

    monkeypatch.setattr(search, "post_search", _post)
    payload = {"minNotionalAmount": "0", "maxNotionalAmount": "1000000000000"}
    rows = asyncio.run(search.search_window(payload, END, END))

    assert len(rows) == len(seen)
    assert min(lo for lo, _ in seen) == 0
    assert max(hi for _, hi in seen) == 1_000_000_000_000


def test_search_window_notional_split_defaults_the_range(monkeypatch):
    seen: list = []

    async def _post(payload):
        if "minNotionalAmount" not in payload:
            return [{"n": i} for i in range(search.SEARCH_ROW_CAP)]

        seen.append(
            (int(payload["minNotionalAmount"]), int(payload["maxNotionalAmount"]))
        )

        return [{"band": payload["minNotionalAmount"]}]

    monkeypatch.setattr(search, "post_search", _post)
    rows = asyncio.run(search.search_window({}, END, END))

    assert len(rows) == len(seen)
    assert min(lo for lo, _ in seen) == 0
    assert max(hi for _, hi in seen) == int(search.SEARCH_MAX_NOTIONAL)


def test_search_window_refuses_a_single_notional_value(monkeypatch):

    async def _post(payload):
        return [{"n": i} for i in range(search.SEARCH_ROW_CAP)]

    monkeypatch.setattr(search, "post_search", _post)
    payload = {"minNotionalAmount": "5", "maxNotionalAmount": "5"}

    with pytest.raises(OpenBBError, match="cannot be narrowed further by notional"):
        asyncio.run(search.search_window(payload, END, END))


def test_search_window_refuses_a_band_that_still_caps(monkeypatch):

    async def _post(payload):
        return [{"n": i} for i in range(search.SEARCH_ROW_CAP)]

    monkeypatch.setattr(search, "post_search", _post)
    payload = {"minNotionalAmount": "0", "maxNotionalAmount": "1000000000000"}

    with pytest.raises(OpenBBError, match="narrow the date or notional range"):
        asyncio.run(search.search_window(payload, END, END))


def test_notional_band_edges():
    edges = search._notional_band_edges(0, 1_000_000_000_000)

    assert edges[0] == 0
    assert edges[-1] == 1_000_000_000_000
    assert all(a < b for a, b in zip(edges, edges[1:]))
    assert search._notional_band_edges(5, 5) == []
    assert search._notional_band_edges(10, 3) == []


def test_search_trades_rejects_an_inverted_window():
    with pytest.raises(OpenBBError, match="ends before it starts"):
        asyncio.run(
            search.search_trades("rates", start_date=END, end_date=date(2026, 1, 1))
        )


def test_search_trades_clamps_the_window_to_the_one_year_horizon(monkeypatch):
    from datetime import datetime

    today = datetime.now(UTC).date()
    horizon = today - timedelta(days=search.SEARCH_MAX_RETENTION_DAYS - 1)
    lows: list = []

    async def _post(payload):
        lows.append(payload["disseminationDateTimeLow"][:10])
        return []

    monkeypatch.setattr(search, "post_search", _post)
    asyncio.run(
        search.search_trades(
            "rates",
            start_date=today - timedelta(days=500),
            end_date=today - timedelta(days=1),
        )
    )

    assert lows
    assert min(lows) == horizon.isoformat()


def test_search_trades_rejects_a_window_wholly_before_the_horizon():
    from datetime import datetime

    today = datetime.now(UTC).date()

    with pytest.raises(OpenBBError, match="predates the .* horizon"):
        asyncio.run(
            search.search_trades(
                "rates",
                start_date=today - timedelta(days=500),
                end_date=today - timedelta(days=400),
            )
        )


def test_chunk_windows_splits_a_long_span():
    start, end = date(2025, 1, 1), date(2025, 10, 1)
    chunks = search._chunk_windows(start, end, search.SEARCH_MAX_RANGE_DAYS)

    assert len(chunks) > 1
    assert chunks[0][0] == start
    assert chunks[-1][1] == end
    assert all((high - low).days < search.SEARCH_MAX_RANGE_DAYS for low, high in chunks)
    assert all(
        nxt[0] == cur[1] + timedelta(days=1) for cur, nxt in zip(chunks, chunks[1:])
    )


def test_chunk_windows_returns_one_window_within_the_limit():
    start, end = date(2025, 1, 1), date(2025, 3, 1)

    assert search._chunk_windows(start, end, search.SEARCH_MAX_RANGE_DAYS) == [
        (start, end)
    ]


def test_contiguous_runs_groups_days_into_gapless_runs():
    days = [date(2025, 3, 1), date(2025, 3, 2), date(2025, 3, 5), date(2025, 3, 6)]

    assert search._contiguous_runs(days) == [
        (date(2025, 3, 1), date(2025, 3, 2)),
        (date(2025, 3, 5), date(2025, 3, 6)),
    ]


def test_contiguous_runs_handles_a_single_day():
    assert search._contiguous_runs([date(2025, 3, 1)]) == [
        (date(2025, 3, 1), date(2025, 3, 1))
    ]


def test_search_trades_chains_sub_windows_over_180_days(monkeypatch):
    from datetime import datetime

    today = datetime.now(UTC).date()
    end = today - timedelta(days=1)
    start = end - timedelta(days=250)
    calls: list = []

    async def _post(payload):
        low = payload["disseminationDateTimeLow"][:10]
        high = payload["disseminationDateTimeHigh"][:10]
        calls.append((low, high))
        return [
            {
                "disseminationTimestamp": f"{low}T10:00:00Z",
                "disseminationIdentifier": low,
            }
        ]

    monkeypatch.setattr(search, "post_search", _post)
    rows = asyncio.run(search.search_trades("rates", start_date=start, end_date=end))

    expected = [
        (low.isoformat(), high.isoformat())
        for low, high in search._chunk_windows(start, end, search.SEARCH_MAX_RANGE_DAYS)
    ]

    assert len(expected) > 1
    assert sorted(calls) == sorted(expected)
    assert len(rows) == len(expected)


def test_search_trades_fetches_only_the_missing_runs(monkeypatch):
    from datetime import datetime

    today = datetime.now(UTC).date()
    days = [today - timedelta(days=6 - offset) for offset in range(5)]
    calls: list = []

    async def _post(payload):
        calls.append(
            (
                payload["disseminationDateTimeLow"][:10],
                payload["disseminationDateTimeHigh"][:10],
            )
        )
        return []

    monkeypatch.setattr(search, "post_search", _post)
    key = search._cache_key(search.build_search_payload("rates", currency="CHF"))
    store.put_search_days(key, {days[2].isoformat(): []})

    asyncio.run(
        search.search_trades(
            "rates", currency="CHF", start_date=days[0], end_date=days[4]
        )
    )

    assert sorted(calls) == [
        (days[0].isoformat(), days[1].isoformat()),
        (days[3].isoformat(), days[4].isoformat()),
    ]


def test_search_trades_dedupes_a_straggler_across_chunks(monkeypatch):
    from datetime import datetime

    today = datetime.now(UTC).date()
    end = today - timedelta(days=1)
    start = end - timedelta(days=200)
    straggler = start + timedelta(days=185)

    async def _post(payload):
        return [
            {
                "disseminationTimestamp": f"{straggler.isoformat()}T10:00:00Z",
                "disseminationIdentifier": "dup",
            }
        ]

    monkeypatch.setattr(search, "post_search", _post)
    rows = asyncio.run(search.search_trades("rates", start_date=start, end_date=end))

    assert [r["Dissemination Identifier"] for r in rows] == ["dup"]


def test_search_trades_maps_and_orders_by_day(monkeypatch):

    async def _post(payload):
        return [
            {
                "uniqueProductIdentifierShortName": "NA%2FSwap%20OIS%20CHF",
                "disseminationTimestamp": "2026-07-15T10:00:00Z",
            },
            {
                "uniqueProductIdentifierShortName": "NA%2FSwap%20OIS%20CHF",
                "disseminationTimestamp": "2026-07-14T10:00:00Z",
            },
        ]

    monkeypatch.setattr(search, "post_search", _post)
    rows = asyncio.run(
        search.search_trades(
            "rates", start_date=date(2026, 7, 14), end_date=date(2026, 7, 15)
        )
    )

    assert [r["Dissemination Timestamp"][:10] for r in rows] == [
        "2026-07-14",
        "2026-07-15",
    ]
    assert all(r["UPI FISN"] == "NA/Swap OIS CHF" for r in rows)


def test_search_trades_indexes_records_by_identifier(monkeypatch):

    async def _post(payload):
        return [
            {
                "disseminationIdentifier": "S1",
                "uniqueProductIdentifierShortName": "NA%2FSwap%20OIS%20CHF",
                "disseminationTimestamp": "2026-07-15T10:00:00Z",
            }
        ]

    monkeypatch.setattr(search, "post_search", _post)
    rows = asyncio.run(
        search.search_trades(
            "rates", start_date=date(2026, 7, 15), end_date=date(2026, 7, 15)
        )
    )

    assert store.get_trade_record("S1") == rows[0]


def test_search_trades_caches_closed_days_and_todays_within_its_ttl(monkeypatch):
    from datetime import datetime

    from openbb_cftc.utils import store

    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    calls: list = []

    async def _post(payload):
        calls.append(
            (
                payload["disseminationDateTimeLow"][:10],
                payload["disseminationDateTimeHigh"][:10],
            )
        )
        return [
            {
                "disseminationTimestamp": f"{yesterday.isoformat()}T10:00:00Z",
                "d": "old",
            },
            {"disseminationTimestamp": f"{today.isoformat()}T10:00:00Z", "d": "new"},
        ]

    monkeypatch.setattr(search, "post_search", _post)

    first = asyncio.run(
        search.search_trades("rates", start_date=yesterday, end_date=today)
    )
    second = asyncio.run(
        search.search_trades("rates", start_date=yesterday, end_date=today)
    )

    assert len(first) == 2
    assert len(second) == 2

    assert calls == [(yesterday.isoformat(), today.isoformat())]

    key = search._cache_key(search.build_search_payload("rates"))
    monkeypatch.setattr(store, "SEARCH_INTRADAY_TTL_SECONDS", -1)
    store.put_search_days(key, {today.isoformat(): []})

    third = asyncio.run(
        search.search_trades("rates", start_date=yesterday, end_date=today)
    )

    assert len(third) == 2
    assert calls == [
        (yesterday.isoformat(), today.isoformat()),
        (today.isoformat(), today.isoformat()),
    ]


def test_search_trades_serves_a_fully_closed_window_from_cache(monkeypatch):
    calls: list = []

    async def _post(payload):
        calls.append(payload)
        return [{"disseminationTimestamp": "2026-07-15T10:00:00Z", "d": "x"}]

    monkeypatch.setattr(search, "post_search", _post)

    for _ in range(3):
        rows = asyncio.run(
            search.search_trades(
                "rates",
                start_date=date(2026, 7, 15),
                end_date=date(2026, 7, 15),
            )
        )
        assert len(rows) == 1

    assert len(calls) == 1


def test_search_trades_without_cache_always_queries(monkeypatch):
    calls: list = []

    async def _post(payload):
        calls.append(payload)
        return [{"disseminationTimestamp": "2026-07-15T10:00:00Z"}]

    monkeypatch.setattr(search, "post_search", _post)

    for _ in range(2):
        asyncio.run(
            search.search_trades(
                "rates",
                start_date=date(2026, 7, 15),
                end_date=date(2026, 7, 15),
                use_cache=False,
            )
        )

    assert len(calls) == 2
    assert store.get_search_days(search._cache_key(calls[0]), ["2026-07-15"]) == {}


def test_search_trades_caches_a_day_that_returned_nothing(monkeypatch):
    calls: list = []

    async def _post(payload):
        calls.append(payload)
        return []

    monkeypatch.setattr(search, "post_search", _post)

    for _ in range(2):
        rows = asyncio.run(
            search.search_trades(
                "rates",
                start_date=date(2026, 7, 11),
                end_date=date(2026, 7, 11),
            )
        )
        assert rows == []

    assert len(calls) == 1


def test_search_trades_ignores_rows_dated_outside_the_window(monkeypatch):

    async def _post(payload):
        return [
            {
                "disseminationTimestamp": "2026-07-15T10:00:00Z",
                "disseminationIdentifier": "in",
            },
            {
                "disseminationTimestamp": "2020-01-01T10:00:00Z",
                "disseminationIdentifier": "out",
            },
        ]

    monkeypatch.setattr(search, "post_search", _post)
    rows = asyncio.run(
        search.search_trades(
            "rates", start_date=date(2026, 7, 15), end_date=date(2026, 7, 15)
        )
    )

    assert [r["Dissemination Identifier"] for r in rows] == ["in"]


def test_cache_key_ignores_the_window_but_not_the_filters():
    base = search.build_search_payload("rates", currency="CHF")
    windowed = dict(base)
    windowed["disseminationDateTimeLow"] = "2026-07-01T00:00:00.000Z"
    windowed["disseminationDateTimeHigh"] = "2026-07-16T23:59:00.000Z"
    other = search.build_search_payload("rates", currency="EUR")

    assert search._cache_key(base) == search._cache_key(windowed)
    assert search._cache_key(base) != search._cache_key(other)
