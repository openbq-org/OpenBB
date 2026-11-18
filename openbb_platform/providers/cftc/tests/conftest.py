from datetime import date
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_DATE = date(2026, 7, 15)
FIXTURE_NAME = "CFTC_CUMULATIVE_RATES_2026_07_15.zip"
FX_FIXTURE_NAME = "CFTC_CUMULATIVE_FOREX_2026_07_15.zip"
CREDITS_FIXTURE_NAME = "CFTC_CUMULATIVE_CREDITS_2026_07_15.zip"
SEARCH_FIXTURE_NAME = "CFTC_SEARCH_RATES_CHF_2026_06_17_2026_07_16.json.gz"
SEARCH_FIXTURE_END = date(2026, 7, 16)


def scrub_string(key):

    def before_record_response(response):
        response["headers"][key] = "MOCK_VALUE"
        return response

    return before_record_response


@pytest.fixture(scope="module")
def vcr_config():
    return {
        "filter_headers": [("User-Agent", None)],
        "filter_query_parameters": [
            ("$$app_token", "MOCK_APP_TOKEN"),
            ("$limit", "MOCK_LIMIT"),
            ("$order", "MOCK_ORDER"),
            ("$where", "MOCK_WHERE"),
        ],
        "before_record_response": [
            scrub_string("Etag"),
            scrub_string("X-Socrata-RequestId"),
            scrub_string("X-Socrata-Region"),
        ],
    }


@pytest.fixture(name="slice_bytes", scope="session")
def slice_bytes_fixture() -> bytes:
    return (FIXTURES / FIXTURE_NAME).read_bytes()


@pytest.fixture(name="slice_records", scope="session")
def slice_records_fixture(slice_bytes) -> list[dict]:
    from openbb_cftc.utils.dtcc import parse_slice_csv

    return parse_slice_csv(slice_bytes)


@pytest.fixture(name="fx_records", scope="session")
def fx_records_fixture() -> list[dict]:
    from openbb_cftc.utils.dtcc import parse_slice_csv

    return parse_slice_csv((FIXTURES / FX_FIXTURE_NAME).read_bytes())


@pytest.fixture(name="credits_bytes", scope="session")
def credits_bytes_fixture() -> bytes:
    return (FIXTURES / CREDITS_FIXTURE_NAME).read_bytes()


@pytest.fixture(name="credits_records", scope="session")
def credits_records_fixture(credits_bytes) -> list[dict]:
    from openbb_cftc.utils.dtcc import parse_slice_csv

    return parse_slice_csv(credits_bytes)


@pytest.fixture(name="chf_search_records", scope="session")
def chf_search_records_fixture() -> list[dict]:
    import gzip
    import json

    with gzip.open(FIXTURES / SEARCH_FIXTURE_NAME, "rt", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    if request.node.get_closest_marker("cassette"):
        return

    async def _blocked(*args, **kwargs):
        raise AssertionError("post_search reached the network in a unit test")

    monkeypatch.setattr("openbb_cftc.utils.search.post_search", _blocked)


@pytest.fixture(name="manifest")
def manifest_fixture() -> list[dict]:
    return [
        {
            "sliceId": 34074363,
            "fileName": FIXTURE_NAME,
            "startTs": "2026-07-16T00:15:09Z",
            "endTs": "2026-07-16T00:15:42Z",
            "rowCount": 0,
            "dissemDTM": "2026-07-16T00:00:00Z",
            "fullFilePath": (
                "https://kgc0418-tdw-data-0.s3.amazonaws.com/cftc/eod/" + FIXTURE_NAME
            ),
        }
    ]


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    from openbb_cftc.utils import helpers, store

    monkeypatch.setattr(store, "_cache_dir", lambda: str(tmp_path))
    store.close()
    helpers.reset_cot_choices()
    yield
    store.close()
    helpers.reset_cot_choices()
