from datetime import UTC

from openbb_cftc.utils import store


def test_put_and_get_slice():
    store.put_slice("CFTC", "IR", "2026-07-15", etag="W/1", last_modified="Thu")
    cached = store.get_slice("CFTC", "IR", "2026-07-15")

    assert "payload" not in cached
    assert cached["etag"] == "W/1"
    assert cached["last_modified"] == "Thu"
    assert cached["fetched_at"]


def test_get_slice_missing_returns_none():
    assert store.get_slice("CFTC", "IR", "1999-01-01") is None


def test_put_slice_replaces_existing():
    store.put_slice("CFTC", "IR", "2026-07-15", etag="W/1")
    store.put_slice("CFTC", "IR", "2026-07-15", etag="W/2")
    cached = store.get_slice("CFTC", "IR", "2026-07-15")

    assert cached["etag"] == "W/2"


def test_shed_slice_payload_drops_only_the_payload():
    store._cache("blobs").set(
        ("CFTC", "IR", "2026-07-15"),
        {"payload": b"legacy", "etag": "W/1", "fetched_at": "2026-07-16T00:00:00"},
    )
    store.shed_slice_payload("CFTC", "IR", "2026-07-15")
    meta = store.get_slice("CFTC", "IR", "2026-07-15")

    assert meta == {"etag": "W/1", "fetched_at": "2026-07-16T00:00:00"}

    store.shed_slice_payload("CFTC", "IR", "2026-07-15")

    assert store.get_slice("CFTC", "IR", "2026-07-15") == meta
    assert store.shed_slice_payload("CFTC", "IR", "1999-01-01") is None


def test_cached_dates():
    store.put_slice("CFTC", "IR", "2026-07-14")
    store.put_slice("CFTC", "IR", "2026-07-15")
    store.put_slice("CFTC", "CR", "2026-07-15")

    assert store.cached_dates("CFTC", "IR") == {"2026-07-14", "2026-07-15"}
    assert store.cached_dates("CFTC", "CR") == {"2026-07-15"}
    assert store.cached_dates("SEC", "IR") == set()


def test_manifest_round_trip():
    store.put_manifest("CFTC", "IR", [{"fileName": "a.zip"}])
    cached = store.get_manifest("CFTC", "IR")

    assert cached["payload"] == [{"fileName": "a.zip"}]
    assert cached["fetched_at"]
    assert store.get_manifest("CFTC", "CR") is None


def test_put_manifest_replaces_existing():
    store.put_manifest("CFTC", "IR", [{"fileName": "old.zip"}])
    store.put_manifest("CFTC", "IR", [{"fileName": "new.zip"}])

    assert store.get_manifest("CFTC", "IR")["payload"] == [{"fileName": "new.zip"}]


def test_trade_record_round_trip():
    record = {
        "Dissemination Identifier": "A1",
        "UPI FISN": "NA/Swap OIS USD",
        "Fixed rate-Leg 1": "0.04",
    }
    store.write_search_records("IR", "2026-07-15", [record])

    assert store.get_trade_record("A1") == record
    assert store.get_trade_record("absent") is None


def test_trade_records_resolve_only_their_exact_identifier():
    first = {"Dissemination Identifier": "4391821108000000101"}
    second = {"Dissemination Identifier": "4391821108000000201"}
    store.write_slice_records("IR", "2026-07-15", [first, second])

    assert store.get_trade_record("4391821108000000101") == first
    assert store.get_trade_record("4391821108000000201") == second
    assert store.get_trade_record("4399999999000000101") is None
    assert store.get_trade_record(" 4391821108000000101 ") == first


def test_has_slice_records():
    assert store.has_slice_records("IR", "2026-07-15") is False

    store.write_slice_records("IR", "2026-07-15", [{"Dissemination Identifier": "A1"}])

    assert store.has_slice_records("IR", "2026-07-15") is True
    assert store.has_slice_records("IR", "2026-07-14") is False
    assert store.has_slice_records("CR", "2026-07-15") is False


def test_write_slice_records_replaces_the_shard():
    store.write_slice_records(
        "IR", "2026-07-15", [{"Dissemination Identifier": "A1", "n": "1"}]
    )
    store.write_slice_records(
        "IR", "2026-07-15", [{"Dissemination Identifier": "A1", "n": "2"}]
    )

    assert store.get_trade_record("A1") == {
        "Dissemination Identifier": "A1",
        "n": "2",
    }


def test_write_slice_records_accepts_an_empty_day():
    store.write_slice_records("IR", "2026-07-12", [])

    assert store.has_slice_records("IR", "2026-07-12") is True
    assert store.get_trade_record("anything") is None


def test_write_search_records_merges_by_identifier():
    store.write_search_records(
        "IR", "2026-07-15", [{"Dissemination Identifier": "A1", "n": 1}]
    )
    store.write_search_records(
        "IR",
        "2026-07-15",
        [
            {"Dissemination Identifier": "A1", "n": 2},
            {"Dissemination Identifier": "B2", "n": 3},
        ],
    )

    assert store.get_trade_record("A1") == {"Dissemination Identifier": "A1", "n": "2"}
    assert store.get_trade_record("B2") == {"Dissemination Identifier": "B2", "n": "3"}


def test_write_search_records_skips_records_without_an_identifier():
    store.write_search_records(
        "IR", "2026-07-15", [{"UPI FISN": "NA/Swap OIS USD"}, {}]
    )

    assert store.get_trade_record("") is None


def test_write_search_records_no_ops_on_empty_input():
    assert store.write_search_records("IR", "2026-07-15", []) is None
    assert (
        store.write_search_records("IR", "", [{"Dissemination Identifier": "A1"}])
        is None
    )


def test_get_trade_record_prefers_the_newest_shard_and_skips_corrupt_files():
    import os

    store.write_slice_records(
        "IR", "2026-07-14", [{"Dissemination Identifier": "A1", "n": "old"}]
    )
    store.write_search_records(
        "IR", "2026-07-15", [{"Dissemination Identifier": "A1", "n": "new"}]
    )

    directory = store._records_dir()
    with open(os.path.join(directory, "CFTC_IR_slice_2026-07-16.parquet"), "wb") as fh:
        fh.write(b"not parquet")

    assert store.get_trade_record("A1") == {
        "Dissemination Identifier": "A1",
        "n": "new",
    }


def test_curve_round_trip():
    store.put_curve("key", "2026-07-15", [{"tenor": "10Y", "par_rate": 0.041}])

    assert store.get_curve("key") == [{"tenor": "10Y", "par_rate": 0.041}]
    assert store.get_curve("absent") is None


def test_search_days_round_trip():
    store.put_search_days(
        "sig",
        {"2026-07-15": [{"UPI FISN": "NA/Swap OIS CHF"}], "2026-07-11": []},
    )
    cached = store.get_search_days("sig", ["2026-07-15", "2026-07-11", "2026-07-01"])

    assert cached["2026-07-15"] == [{"UPI FISN": "NA/Swap OIS CHF"}]
    assert cached["2026-07-11"] == []
    assert "2026-07-01" not in cached


def test_response_round_trip_and_ttl(monkeypatch):
    store.put_response("https://example/query", [{"n": 1}])

    assert store.get_response("https://example/query") == [{"n": 1}]
    assert store.get_response("https://example/other") is None

    monkeypatch.setattr(store, "RESPONSE_TTL_SECONDS", -1)
    store.put_response("https://example/query", [{"n": 2}])

    assert store.get_response("https://example/query") is None


def test_search_todays_partition_serves_within_its_ttl():
    from datetime import datetime

    today = datetime.now(UTC).date().isoformat()
    store.put_search_days("sig", {today: [{"n": 1}]})

    assert store.get_search_days("sig", [today]) == {today: [{"n": 1}]}


def test_search_todays_partition_expires_while_a_closed_day_persists(monkeypatch):
    from datetime import datetime

    today = datetime.now(UTC).date().isoformat()
    monkeypatch.setattr(store, "SEARCH_INTRADAY_TTL_SECONDS", -1)
    store.put_search_days("sig", {today: [{"n": 1}], "2026-07-15": [{"n": 2}]})

    cached = store.get_search_days("sig", [today, "2026-07-15"])

    assert today not in cached
    assert cached["2026-07-15"] == [{"n": 2}]


def test_search_days_are_partitioned_by_key():
    store.put_search_days("chf", {"2026-07-15": [{"n": 1}]})
    store.put_search_days("eur", {"2026-07-15": [{"n": 2}]})

    assert store.get_search_days("chf", ["2026-07-15"]) == {"2026-07-15": [{"n": 1}]}
    assert store.get_search_days("eur", ["2026-07-15"]) == {"2026-07-15": [{"n": 2}]}


def test_put_search_days_replaces_a_day():
    store.put_search_days("sig", {"2026-07-15": [{"n": 1}]})
    store.put_search_days("sig", {"2026-07-15": [{"n": 2}]})

    assert store.get_search_days("sig", ["2026-07-15"]) == {"2026-07-15": [{"n": 2}]}


def test_search_days_no_ops_on_empty_input():
    assert store.get_search_days("sig", []) == {}
    assert store.put_search_days("sig", {}) is None


def test_reset_and_compact():
    store.put_slice("CFTC", "IR", "2026-07-15", b"payload")
    store.put_curve("key", "2026-07-15", [1])
    store.put_search_days("sig", {"2026-07-15": [{"n": 1}]})
    store.put_manifest("CFTC", "IR", [{"fileName": "a.zip"}])
    store.write_search_records("IR", "2026-07-15", [{"Dissemination Identifier": "A1"}])
    store.reset()

    assert store.get_slice("CFTC", "IR", "2026-07-15") is None
    assert store.get_curve("key") is None
    assert store.get_search_days("sig", ["2026-07-15"]) == {}
    assert store.get_manifest("CFTC", "IR") is None
    assert store.get_trade_record("A1") is None

    store.compact()


def test_operations_degrade_quietly_without_a_cache_dir(monkeypatch):
    monkeypatch.setattr(store, "_cache_dir", lambda: None)

    assert store.get_slice("CFTC", "IR", "2026-07-15") is None
    assert store.cached_dates("CFTC", "IR") == set()
    assert store.get_curve("key") is None
    assert store.get_search_days("sig", ["2026-07-15"]) == {}
    assert store.get_manifest("CFTC", "IR") is None
    assert store.get_trade_record("A1") is None
    assert store.get_response("https://example/query") is None
    assert store.put_slice("CFTC", "IR", "2026-07-15") is None
    assert store.shed_slice_payload("CFTC", "IR", "2026-07-15") is None
    assert store.slice_records("IR", "2026-07-15") is None
    assert store.put_curve("key", "2026-07-15", [1]) is None
    assert store.put_search_days("sig", {"2026-07-15": [{"n": 1}]}) is None
    assert store.put_manifest("CFTC", "IR", [{"fileName": "a.zip"}]) is None
    assert store.put_response("https://example/query", [{"n": 1}]) is None
    assert store.get_document("k") is None
    assert store.put_document("k", {"a": 1}) is None
    assert store.has_slice_records("IR", "2026-07-15") is False
    assert (
        store.write_slice_records(
            "IR", "2026-07-15", [{"Dissemination Identifier": "A1"}]
        )
        is None
    )
    assert (
        store.write_search_records(
            "IR", "2026-07-15", [{"Dissemination Identifier": "A1"}]
        )
        is None
    )
    assert store.reset() is None
    assert store.compact() is None


def test_cache_open_failure_degrades_quietly(monkeypatch):
    import diskcache

    def _raise(*args, **kwargs):
        raise diskcache.Timeout("locked")

    monkeypatch.setattr(diskcache, "Cache", _raise)
    store.close()

    assert store._cache("blobs") is None
    assert store.get_slice("CFTC", "IR", "2026-07-15") is None


def test_close_clears_open_handles():
    store.put_curve("key", "2026-07-15", [1])
    assert store._CACHES

    store.close()

    assert not store._CACHES


def test_cache_dir_returns_none_when_not_writable(monkeypatch):
    import os

    monkeypatch.undo()

    def _raise(*args, **kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(os, "makedirs", _raise)

    assert store._cache_dir() is None


def test_cache_dir_path(monkeypatch, tmp_path):
    monkeypatch.undo()
    monkeypatch.setattr(
        "openbb_core.app.utils.get_user_cache_directory", lambda: str(tmp_path)
    )
    path = store._cache_dir()

    assert path is not None
    assert path.endswith(os_join("cftc", "dtcc"))


def os_join(*parts: str) -> str:
    import os

    return os.path.join(*parts)


def test_records_dir_degrades_when_not_writable(monkeypatch):
    import os

    real_makedirs = os.makedirs

    def _raise(path, exist_ok=False):
        if str(path).endswith("record_shards"):
            raise OSError("read-only")
        return real_makedirs(path, exist_ok=exist_ok)

    monkeypatch.setattr(os, "makedirs", _raise)

    assert store._records_dir() is None
    assert store.get_trade_record("A1") is None
    assert store.has_slice_records("IR", "2026-07-15") is False


def test_shard_write_failures_degrade_quietly(monkeypatch):
    def _raise(path, rows):
        raise OSError("disk full")

    monkeypatch.setattr(store, "_write_shard", _raise)
    monkeypatch.setattr(store, "_stream_shard", _raise)

    record = {"Dissemination Identifier": "A1"}

    assert store.write_slice_records("IR", "2026-07-15", [record]) is None
    assert store.write_search_records("IR", "2026-07-15", [record]) is None
    assert store.get_trade_record("A1") is None


def test_stream_shard_batches_row_groups(tmp_path):
    import pyarrow.parquet as pq

    path = str(tmp_path / "batched.parquet")
    rows = (
        {"Dissemination Identifier": str(n), "Notional amount-Leg 1": None}
        for n in range(store.RECORD_ROW_GROUP_SIZE * 2 + 1)
    )
    store._stream_shard(path, rows)
    table = pq.read_table(path)

    assert table.num_rows == store.RECORD_ROW_GROUP_SIZE * 2 + 1
    assert pq.read_metadata(path).num_row_groups == 3
    assert table.column("Notional amount-Leg 1").to_pylist()[0] == ""


def test_stream_shard_removes_the_tmp_file_on_failure(tmp_path):
    import os

    import pytest

    path = str(tmp_path / "failed.parquet")

    def _rows():
        for n in range(store.RECORD_ROW_GROUP_SIZE + 1):
            yield {"Dissemination Identifier": str(n)}
        raise OSError("source went away")

    with pytest.raises(OSError, match="source went away"):
        store._stream_shard(path, _rows())

    assert not os.path.exists(path)
    assert not [name for name in os.listdir(tmp_path) if name.startswith("failed")]


def test_slice_records_streams_and_reiterates():
    rows = [
        {"Dissemination Identifier": "A1", "n": "1"},
        {"Dissemination Identifier": "A2", "n": "2"},
    ]
    store.write_slice_records("IR", "2026-07-15", iter(rows))
    view = store.slice_records("IR", "2026-07-15")

    assert list(view) == rows
    assert list(view) == rows
    assert store.slice_records("IR", "1999-01-01") is None


def test_record_chain_reiterates_every_source():
    chain = store.RecordChain([{"n": 1}], [{"n": 2}, {"n": 3}])

    assert [row["n"] for row in chain] == [1, 2, 3]
    assert [row["n"] for row in chain] == [1, 2, 3]


def test_write_search_records_recovers_from_a_corrupt_shard():
    import os

    directory = store._records_dir()

    with open(
        os.path.join(directory, "CFTC_IR_search_2026-07-15.parquet"), "wb"
    ) as handle:
        handle.write(b"junk")

    store.write_search_records("IR", "2026-07-15", [{"Dissemination Identifier": "A1"}])

    assert store.get_trade_record("A1") == {"Dissemination Identifier": "A1"}


def test_document_round_trip():
    assert store.get_document("absent") is None

    store.put_document("k", {"2026-01-01": 100.0})

    assert store.get_document("k") == {"2026-01-01": 100.0}

    store.put_document("k", {"2026-02-01": 101.0})

    assert store.get_document("k") == {"2026-02-01": 101.0}
