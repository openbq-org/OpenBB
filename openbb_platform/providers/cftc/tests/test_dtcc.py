import asyncio
from datetime import UTC

import pytest
from openbb_core.app.model.abstract.error import OpenBBError

from openbb_cftc.utils import dtcc, store

FIXTURE_URL = (
    "https://kgc0418-tdw-data-0.s3.amazonaws.com/cftc/eod/"
    "CFTC_CUMULATIVE_RATES_2026_07_15.zip"
)


class _FakeResponse:
    def __init__(self, status=200, body=b"", headers=None):
        self.status = status
        self.headers = headers or {}
        self._body = body

    async def read(self):
        return self._body

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")


def _patch_amake_request(monkeypatch, response, capture=None):

    async def _request(url, headers=None, response_callback=None, **kwargs):
        if capture is not None:
            capture.append((url, headers))

        return await response_callback(response, None)

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _request)


def test_download_file_returns_body_and_validators(monkeypatch):
    _patch_amake_request(
        monkeypatch, _FakeResponse(body=b"payload", headers={"ETag": "W/2"})
    )
    body, validators = asyncio.run(dtcc.download_file(FIXTURE_URL))

    assert body == b"payload"
    assert validators["etag"] == "W/2"


def test_download_file_sends_if_none_match_and_handles_304(monkeypatch):
    capture: list = []
    _patch_amake_request(monkeypatch, _FakeResponse(status=304), capture)
    body, validators = asyncio.run(dtcc.download_file(FIXTURE_URL, etag="W/1"))

    assert body is None
    assert validators == {"etag": "W/1"}
    assert capture[0][1] == {"If-None-Match": "W/1"}


def test_download_file_wraps_bad_status(monkeypatch):
    _patch_amake_request(monkeypatch, _FakeResponse(status=500))

    with pytest.raises(OpenBBError, match="Failed to download"):
        asyncio.run(dtcc.download_file(FIXTURE_URL))


def test_download_file_wraps_transport_errors(monkeypatch):

    async def _raise(*args, **kwargs):
        raise RuntimeError("connection reset")

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _raise)

    with pytest.raises(OpenBBError, match="Failed to download"):
        asyncio.run(dtcc.download_file(FIXTURE_URL))


@pytest.mark.parametrize(
    ("value", "expected"), [("rates", "IR"), ("RATES", "IR"), ("credits", "CR")]
)
def test_normalize_asset_class(value, expected):
    assert dtcc.normalize_asset_class(value) == expected


def test_normalize_rejects_unknown_values():
    with pytest.raises(OpenBBError, match="Invalid asset class"):
        dtcc.normalize_asset_class("weather")


def test_manifest_by_date_parses_and_skips(manifest):
    index = dtcc.manifest_by_date(
        manifest
        + [
            {"fileName": "GARBAGE.zip"},
            {"fileName": "CFTC_CUMULATIVE_RATES_YYYY_MM_DD.zip"},
            {},
        ]
    )

    assert list(index) == ["2026-07-15"]


def test_parse_slice_csv(slice_bytes):
    records = dtcc.parse_slice_csv(slice_bytes)

    assert len(records) == 3274
    assert records[0]["Asset Class"] == "IR"


def test_parse_slice_csv_rejects_bad_zip():
    with pytest.raises(OpenBBError, match="not a valid zip"):
        dtcc.parse_slice_csv(b"not a zip")


def test_parse_slice_csv_requires_a_csv_member():
    import io
    import zipfile

    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "no csv here")

    with pytest.raises(OpenBBError, match="no CSV member"):
        dtcc.parse_slice_csv(buffer.getvalue())


def test_get_manifest_returns_entries(monkeypatch, manifest):
    calls: list = []

    async def _request(url, **kwargs):
        calls.append(url)
        return manifest

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _request)
    result = asyncio.run(dtcc.get_manifest("rates"))

    assert result == manifest
    assert calls[0].endswith("/ppd/api/cumulative/CFTC/IR")


def test_get_manifest_wraps_failures(monkeypatch):

    async def _raise(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _raise)

    with pytest.raises(OpenBBError, match="Failed to fetch the PPD manifest"):
        asyncio.run(dtcc.get_manifest("rates"))


@pytest.mark.parametrize("response", [None, [], {"error": "nope"}])
def test_get_manifest_requires_entries(monkeypatch, response):

    async def _empty(*args, **kwargs):
        return response

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _empty)

    with pytest.raises(OpenBBError, match="No PPD manifest entries"):
        asyncio.run(dtcc.get_manifest("rates"))


def test_get_manifest_serves_a_fresh_cache_without_hitting_the_network(
    monkeypatch, manifest
):
    store.put_manifest("CFTC", "IR", manifest)

    async def _fail(*args, **kwargs):
        raise AssertionError("amake_request must not run for a fresh manifest cache")

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _fail)

    assert asyncio.run(dtcc.get_manifest("rates")) == manifest


def test_get_manifest_refetches_once_the_cache_is_stale(monkeypatch, manifest):
    store.put_manifest("CFTC", "IR", [{"fileName": "stale.zip"}])
    monkeypatch.setattr(dtcc, "MANIFEST_TTL_SECONDS", 0)
    calls: list = []

    async def _request(url, **kwargs):
        calls.append(url)
        return manifest

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _request)
    result = asyncio.run(dtcc.get_manifest("rates"))

    assert result == manifest
    assert len(calls) == 1
    assert store.get_manifest("CFTC", "IR")["payload"] == manifest


def test_get_manifest_falls_back_to_a_stale_cache_on_network_failure(monkeypatch):
    store.put_manifest("CFTC", "IR", [{"fileName": "stale.zip"}])
    monkeypatch.setattr(dtcc, "MANIFEST_TTL_SECONDS", 0)

    async def _raise(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _raise)

    assert asyncio.run(dtcc.get_manifest("rates")) == [{"fileName": "stale.zip"}]


@pytest.mark.parametrize("response", [None, [], {"error": "nope"}])
def test_get_manifest_falls_back_to_a_stale_cache_on_an_empty_response(
    monkeypatch, response
):
    store.put_manifest("CFTC", "IR", [{"fileName": "stale.zip"}])
    monkeypatch.setattr(dtcc, "MANIFEST_TTL_SECONDS", 0)

    async def _empty(*args, **kwargs):
        return response

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _empty)

    assert asyncio.run(dtcc.get_manifest("rates")) == [{"fileName": "stale.zip"}]


def test_get_available_dates(monkeypatch, manifest):

    async def _manifest(*args, **kwargs):
        return manifest

    monkeypatch.setattr(dtcc, "get_manifest", _manifest)

    assert asyncio.run(dtcc.get_available_dates("rates")) == ["2026-07-15"]


def test_get_slice_downloads_and_caches(monkeypatch, manifest, slice_bytes):
    calls: list = []

    async def _manifest(*args, **kwargs):
        return manifest

    async def _download(url, etag=None):
        calls.append(etag)
        return slice_bytes, {"etag": "W/1", "last_modified": "Thu"}

    monkeypatch.setattr(dtcc, "get_manifest", _manifest)
    monkeypatch.setattr(dtcc, "download_file", _download)

    records = asyncio.run(dtcc.get_slice("rates", "2026-07-15"))

    assert len(list(records)) == 3274
    assert calls == [None]
    assert store.get_slice("CFTC", "IR", "2026-07-15")["etag"] == "W/1"


def _todays_manifest():
    from datetime import datetime

    today = datetime.now(UTC).date()
    today_str = today.isoformat()
    name = f"CFTC_CUMULATIVE_RATES_{today.year}_{today.month:02d}_{today.day:02d}.zip"

    return today_str, [
        {
            "fileName": name,
            "fullFilePath": "https://kgc0418-tdw-data-0.s3.amazonaws.com/cftc/eod/"
            + name,
        }
    ]


def test_get_slice_revalidates_todays_still_open_date_with_etag(
    monkeypatch, slice_bytes
):
    today_str, today_manifest = _todays_manifest()
    dtcc._ingest_slice("IR", today_str, slice_bytes)
    store.put_slice("CFTC", "IR", today_str, etag="W/1")
    seen: list = []

    async def _manifest(*args, **kwargs):
        return today_manifest

    async def _not_modified(url, etag=None):
        seen.append(etag)
        return None, {"etag": etag}

    monkeypatch.setattr(dtcc, "get_manifest", _manifest)
    monkeypatch.setattr(dtcc, "download_file", _not_modified)

    records = asyncio.run(dtcc.get_slice("rates", today_str))

    assert len(list(records)) == 3274
    assert seen == ["W/1"]


def test_get_slice_skips_revalidation_for_a_closed_cached_date(
    monkeypatch, slice_bytes
):
    dtcc._ingest_slice("IR", "2026-07-15", slice_bytes)
    store.put_slice("CFTC", "IR", "2026-07-15", etag="W/1")

    async def _forbidden_manifest(*args, **kwargs):
        raise AssertionError("get_manifest reached despite a closed, cached date")

    async def _forbidden_download(*args, **kwargs):
        raise AssertionError("download_file reached despite a closed, cached date")

    monkeypatch.setattr(dtcc, "get_manifest", _forbidden_manifest)
    monkeypatch.setattr(dtcc, "download_file", _forbidden_download)

    rows = list(asyncio.run(dtcc.get_slice("rates", "2026-07-15")))
    target = rows[0]["Dissemination Identifier"]

    assert len(rows) == 3274
    assert store.get_trade_record(target) == rows[0]


def test_get_slice_without_cache_skips_the_store(monkeypatch, manifest, slice_bytes):

    async def _manifest(*args, **kwargs):
        return manifest

    async def _download(url, etag=None):
        return slice_bytes, {}

    monkeypatch.setattr(dtcc, "get_manifest", _manifest)
    monkeypatch.setattr(dtcc, "download_file", _download)

    records = asyncio.run(dtcc.get_slice("rates", "2026-07-15", use_cache=False))

    assert len(list(records)) == 3274
    assert store.get_slice("CFTC", "IR", "2026-07-15") is None


def test_get_slice_indexes_records_by_identifier_on_a_cold_fetch(
    monkeypatch, manifest, slice_bytes
):

    async def _manifest(*args, **kwargs):
        return manifest

    async def _download(url, etag=None):
        return slice_bytes, {"etag": "W/1"}

    monkeypatch.setattr(dtcc, "get_manifest", _manifest)
    monkeypatch.setattr(dtcc, "download_file", _download)

    rows = list(asyncio.run(dtcc.get_slice("rates", "2026-07-15")))
    target = rows[0]["Dissemination Identifier"]

    assert store.get_trade_record(target) == rows[0]


def test_get_slice_indexes_records_on_a_304_revalidation(monkeypatch, slice_bytes):
    today_str, today_manifest = _todays_manifest()
    dtcc._ingest_slice("IR", today_str, slice_bytes)
    store.put_slice("CFTC", "IR", today_str, etag="W/1")

    async def _manifest(*args, **kwargs):
        return today_manifest

    async def _not_modified(url, etag=None):
        return None, {"etag": etag}

    monkeypatch.setattr(dtcc, "get_manifest", _manifest)
    monkeypatch.setattr(dtcc, "download_file", _not_modified)

    rows = list(asyncio.run(dtcc.get_slice("rates", today_str)))
    target = rows[0]["Dissemination Identifier"]

    assert store.get_trade_record(target) == rows[0]


def test_get_slice_indexes_records_without_cache(monkeypatch, manifest, slice_bytes):

    async def _manifest(*args, **kwargs):
        return manifest

    async def _download(url, etag=None):
        return slice_bytes, {}

    monkeypatch.setattr(dtcc, "get_manifest", _manifest)
    monkeypatch.setattr(dtcc, "download_file", _download)

    rows = list(asyncio.run(dtcc.get_slice("rates", "2026-07-15", use_cache=False)))
    target = rows[0]["Dissemination Identifier"]

    assert store.get_trade_record(target) == rows[0]


def test_get_slice_raises_when_download_returns_nothing_uncached(monkeypatch, manifest):

    async def _manifest(*args, **kwargs):
        return manifest

    async def _no_payload(url, etag=None):
        return None, {"etag": None}

    monkeypatch.setattr(dtcc, "get_manifest", _manifest)
    monkeypatch.setattr(dtcc, "download_file", _no_payload)

    with pytest.raises(OpenBBError, match="No payload returned"):
        asyncio.run(dtcc.get_slice("rates", "2026-07-15"))


def test_get_slice_rejects_an_unpublished_date(monkeypatch, manifest):

    async def _manifest(*args, **kwargs):
        return manifest

    monkeypatch.setattr(dtcc, "get_manifest", _manifest)

    with pytest.raises(OpenBBError, match="No PPD file published"):
        asyncio.run(dtcc.get_slice("rates", "1999-01-01"))


def _patch_dates_and_slices(monkeypatch, dates, by_date):

    async def _dates(*args, **kwargs):
        return dates

    async def _slice(asset_class, report_date, use_cache=True):
        return by_date.get(report_date, [])

    monkeypatch.setattr(dtcc, "get_available_dates", _dates)
    monkeypatch.setattr(dtcc, "get_slice", _slice)


def test_get_latest_viable_slice_walks_back_past_an_empty_day(monkeypatch):
    seen: list = []
    _patch_dates_and_slices(
        monkeypatch,
        ["2026-07-15", "2026-07-16", "2026-07-17"],
        {"2026-07-15": [{"row": 1}], "2026-07-16": [], "2026-07-17": []},
    )

    def _is_viable(records, report_date):
        seen.append(report_date)
        return bool(records)

    records, report_date = asyncio.run(
        dtcc.get_latest_viable_slice("rates", _is_viable)
    )

    assert records == [{"row": 1}]
    assert report_date == "2026-07-15"
    assert [d.isoformat() for d in seen] == ["2026-07-17", "2026-07-16", "2026-07-15"]


def test_get_latest_viable_slice_raises_without_published_files(monkeypatch):
    _patch_dates_and_slices(monkeypatch, [], {})

    with pytest.raises(OpenBBError, match="No PPD rates files are currently"):
        asyncio.run(dtcc.get_latest_viable_slice("rates", lambda records, date: True))


def test_get_latest_viable_slice_raises_when_no_day_is_viable(monkeypatch):
    _patch_dates_and_slices(monkeypatch, ["2026-07-15", "2026-07-16"], {})

    with pytest.raises(OpenBBError, match="held usable data for this query"):
        asyncio.run(dtcc.get_latest_viable_slice("rates", lambda records, date: False))


def test_get_rates_slice_for_walks_back_to_a_day_with_the_currency_ois(monkeypatch):
    _patch_dates_and_slices(
        monkeypatch,
        ["2026-07-16", "2026-07-17"],
        {
            "2026-07-17": [{"UPI FISN": "NA/Swap OIS EUR"}],
            "2026-07-16": [{"UPI FISN": "NA/Swap OIS USD"}],
        },
    )
    records, rates_date = asyncio.run(dtcc.get_rates_slice_for("2026-07-17", ["USD"]))

    assert rates_date == "2026-07-16"
    assert records == [{"UPI FISN": "NA/Swap OIS USD"}]


def test_get_rates_slice_for_raises_without_the_currency_ois(monkeypatch):
    _patch_dates_and_slices(
        monkeypatch,
        ["2026-07-16", "2026-07-17"],
        {"2026-07-17": [{"UPI FISN": "NA/Swap OIS EUR"}]},
    )

    with pytest.raises(OpenBBError, match="priced USD"):
        asyncio.run(dtcc.get_rates_slice_for("2026-07-17", ["USD"]))


def test_get_rates_slice_for_appends_todays_realtime_prints(monkeypatch):
    from datetime import datetime, timedelta

    today = datetime.now(UTC).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    _patch_dates_and_slices(
        monkeypatch,
        ["2026-01-01", yesterday],
        {yesterday: [{"UPI FISN": "NA/Swap OIS USD", "src": "slice"}]},
    )
    captured: dict = {}

    async def _search(asset_class, **kwargs):
        captured.update(kwargs)
        return [{"UPI FISN": "NA/Swap OIS USD", "src": "realtime"}]

    monkeypatch.setattr("openbb_cftc.utils.search.search_trades", _search)
    records, rates_date = asyncio.run(
        dtcc.get_rates_slice_for(today.isoformat(), ["USD"])
    )

    assert rates_date == yesterday
    assert {r["src"] for r in records} == {"slice", "realtime"}
    assert captured["currency"] == "USD"
    assert captured["upi_short_name"] == "NA/Swap OIS USD"
    assert captured["start_date"] == today
    assert captured["end_date"] == today


def test_get_rates_slice_for_survives_a_search_outage(monkeypatch):
    from datetime import datetime, timedelta

    today = datetime.now(UTC).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    _patch_dates_and_slices(
        monkeypatch,
        ["2026-01-01", yesterday],
        {yesterday: [{"UPI FISN": "NA/Swap OIS USD", "src": "slice"}]},
    )

    async def _broken_search(asset_class, **kwargs):
        raise OpenBBError("search endpoint down")

    monkeypatch.setattr("openbb_cftc.utils.search.search_trades", _broken_search)
    records, rates_date = asyncio.run(
        dtcc.get_rates_slice_for(today.isoformat(), ["USD"])
    )

    assert rates_date == yesterday
    assert [r["src"] for r in records] == ["slice"]


def test_get_slice_reuses_the_shard_for_a_closed_final_date(
    monkeypatch, manifest, slice_bytes
):
    downloads: list = []
    writes: list = []
    real_write = store.write_slice_records

    async def _manifest(*args, **kwargs):
        return manifest

    async def _download(url, etag=None):
        downloads.append(etag)
        return slice_bytes, {"etag": "W/1", "last_modified": "Thu"}

    def _counted_write(asset, report_date, records):
        writes.append(1)
        return real_write(asset, report_date, records)

    monkeypatch.setattr(dtcc, "get_manifest", _manifest)
    monkeypatch.setattr(dtcc, "download_file", _download)
    monkeypatch.setattr(store, "write_slice_records", _counted_write)

    first = list(asyncio.run(dtcc.get_slice("rates", "2026-07-15")))
    second = list(asyncio.run(dtcc.get_slice("rates", "2026-07-15")))
    target = first[0]["Dissemination Identifier"]

    assert first == second
    assert downloads == [None]
    assert writes == [1]
    assert store.has_slice_records("IR", "2026-07-15") is True
    assert store.get_trade_record(target) == first[0]


def test_get_slice_returns_a_reiterable_view(monkeypatch, slice_bytes):
    dtcc._ingest_slice("IR", "2026-07-15", slice_bytes)
    store.put_slice("CFTC", "IR", "2026-07-15", etag="W/1")

    records = asyncio.run(dtcc.get_slice("rates", "2026-07-15"))

    assert len(list(records)) == 3274
    assert len(list(records)) == 3274


def test_get_slice_sheds_a_legacy_payload(monkeypatch, slice_bytes):
    dtcc._ingest_slice("IR", "2026-07-15", slice_bytes)
    store._cache("blobs").set(
        ("CFTC", "IR", "2026-07-15"),
        {
            "payload": slice_bytes,
            "etag": "W/1",
            "last_modified": "Thu",
            "fetched_at": "2026-07-20T00:00:00+00:00",
        },
    )

    records = asyncio.run(dtcc.get_slice("rates", "2026-07-15"))
    meta = store.get_slice("CFTC", "IR", "2026-07-15")

    assert len(list(records)) == 3274
    assert "payload" not in meta
    assert meta["etag"] == "W/1"


def test_ingest_slice_writes_the_shard_and_returns_a_view(monkeypatch):
    monkeypatch.setattr(
        dtcc,
        "iter_slice_csv",
        lambda payload: iter([{"Dissemination Identifier": payload.decode()}]),
    )

    view = dtcc._ingest_slice("IR", "2026-07-15", b"one")

    assert list(view) == [{"Dissemination Identifier": "one"}]
    assert list(view) == [{"Dissemination Identifier": "one"}]
    assert store.get_trade_record("one") is not None


def test_ingest_slice_overwrites_an_existing_shard(monkeypatch):
    monkeypatch.setattr(
        dtcc,
        "iter_slice_csv",
        lambda payload: iter([{"Dissemination Identifier": payload.decode()}]),
    )

    dtcc._ingest_slice("IR", "2026-07-15", b"one")
    records = dtcc._ingest_slice("IR", "2026-07-15", b"two")

    assert list(records) == [{"Dissemination Identifier": "two"}]
    assert store.get_trade_record("one") is None
    assert store.get_trade_record("two") is not None


def test_ingest_slice_parses_in_memory_without_a_records_dir(monkeypatch):
    import io
    import zipfile

    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("slice.csv", "Dissemination Identifier\nA1\n")

    monkeypatch.setattr(store, "_records_dir", lambda: None)
    records = dtcc._ingest_slice("IR", "2026-07-15", buffer.getvalue())

    assert records == [{"Dissemination Identifier": "A1"}]


def test_get_slice_serves_the_cached_copy_when_the_download_fails(
    monkeypatch, slice_bytes
):
    today_str, today_manifest = _todays_manifest()
    dtcc._ingest_slice("IR", today_str, slice_bytes)
    store.put_slice("CFTC", "IR", today_str, etag="W/1")

    async def _manifest(*args, **kwargs):
        return today_manifest

    async def _broken(url, etag=None):
        raise OpenBBError(f"Failed to download {url} -> timeout")

    monkeypatch.setattr(dtcc, "get_manifest", _manifest)
    monkeypatch.setattr(dtcc, "download_file", _broken)

    records = asyncio.run(dtcc.get_slice("rates", today_str))

    assert len(list(records)) == 3274


def test_get_slice_still_raises_a_download_failure_on_a_cold_cache(monkeypatch):
    today_str, today_manifest = _todays_manifest()

    async def _manifest(*args, **kwargs):
        return today_manifest

    async def _broken(url, etag=None):
        raise OpenBBError(f"Failed to download {url} -> timeout")

    monkeypatch.setattr(dtcc, "get_manifest", _manifest)
    monkeypatch.setattr(dtcc, "download_file", _broken)

    with pytest.raises(OpenBBError, match="Failed to download"):
        asyncio.run(dtcc.get_slice("rates", today_str))


def test_get_rates_slice_for_past_date_skips_the_realtime_append(monkeypatch):
    _patch_dates_and_slices(
        monkeypatch,
        ["2026-07-16", "2026-07-17"],
        {"2026-07-17": [{"UPI FISN": "NA/Swap OIS USD"}]},
    )

    def _fail(*args, **kwargs):
        raise AssertionError("real-time search must not run for a past date")

    monkeypatch.setattr("openbb_cftc.utils.search.search_trades", _fail)
    records, rates_date = asyncio.run(dtcc.get_rates_slice_for("2026-07-17", ["USD"]))

    assert rates_date == "2026-07-17"
    assert records == [{"UPI FISN": "NA/Swap OIS USD"}]


def test_get_rates_slice_for_todays_published_file_needs_no_append(monkeypatch):
    from datetime import datetime

    today = datetime.now(UTC).date().isoformat()
    _patch_dates_and_slices(
        monkeypatch, ["2026-01-01", today], {today: [{"UPI FISN": "NA/Swap OIS USD"}]}
    )

    def _fail(*args, **kwargs):
        raise AssertionError("no append when the slice is already today")

    monkeypatch.setattr("openbb_cftc.utils.search.search_trades", _fail)
    records, rates_date = asyncio.run(dtcc.get_rates_slice_for(today, ["USD"]))

    assert rates_date == today


def test_get_rates_slice_for_empty_currencies_skips_the_append(monkeypatch):
    from datetime import datetime, timedelta

    today = datetime.now(UTC).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    _patch_dates_and_slices(
        monkeypatch,
        ["2026-01-01", yesterday],
        {yesterday: [{"UPI FISN": "NA/Swap OIS USD"}]},
    )

    def _fail(*args, **kwargs):
        raise AssertionError("no search when no currency is required")

    monkeypatch.setattr("openbb_cftc.utils.search.search_trades", _fail)
    records, rates_date = asyncio.run(dtcc.get_rates_slice_for(today.isoformat(), []))

    assert rates_date == yesterday
    assert records == [{"UPI FISN": "NA/Swap OIS USD"}]


def test_get_latest_viable_slice_bounds_its_lookback(monkeypatch):
    tried: list = []
    dates = [f"2026-06-{day:02d}" for day in range(1, 29)]
    _patch_dates_and_slices(monkeypatch, dates, {})

    def _is_viable(records, report_date):
        tried.append(report_date)
        return False

    with pytest.raises(OpenBBError):
        asyncio.run(
            dtcc.get_latest_viable_slice(
                "rates", _is_viable, max_lookback=dtcc.MAX_LOOKBACK_DAYS
            )
        )

    assert len(tried) == dtcc.MAX_LOOKBACK_DAYS
