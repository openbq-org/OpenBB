"""Tests for the build-time security-type generator."""

import gzip
import io
import json
from urllib.error import HTTPError
from urllib.parse import urlparse

import pytest

from openbb_finra.utils import generate_securities as generator

AAPL = {
    "QueryKey": "AAPL",
    "Ticker": "AAPL",
    "Type": "ST",
    "OS01W": "Apple Inc",
    "Name": "Apple",
    "AC021": "Common Shares",
    "SecId": "0P000000GY",
    "PID": "0P000000GY",
    "Exch": "XNAS",
    "ListingMarket": "19",
    "CompositeExchangeID": "126",
    "Region": "USA",
    "DomicileCountry": "USA",
    "Currency": "USD",
    "TenforeInfo": ["AAPL", "19", "1", "126"],
}


class FakeClient:
    """Answer generator requests from a responder."""

    def __init__(self, respond):
        """Hold the responder and record calls."""
        self.respond = respond
        self.calls: list = []

    def request(self, url, params=None, payload=None):
        """Answer one request."""
        self.calls.append((url, params, payload))

        return self.respond(url, params, payload)

class TestHelpers:
    """The pure helpers shared with the runtime."""

    def test_latest_weeks(self):
        """The newest week of each tier is kept and unknown tiers ignored."""
        assert generator.latest_weeks(
            [
                ["2026-08-24", "T1"],
                ["2026-08-31", "T1"],
                ["2026-08-17", "T2"],
                ["2023-11-06", "NMS"],
                ["2026-08-17"],
            ]
        ) == {"T1": "2026-08-31", "T2": "2026-08-17"}

    def test_universe_payload(self):
        """The request filters every partition key."""
        payload = generator.universe_payload("2026-08-31", "T1", "OTC_W_SMBL")

        assert payload["fields"] == generator.UNIVERSE_FIELDS
        assert [item["fieldValue"] for item in payload["compareFilters"]] == [
            "2026-08-31",
            "T1",
            "OTC_W_SMBL",
        ]

    def test_merge_universe(self):
        """Symbols are upper-cased, blanks dropped, and the first sighting kept."""
        universe: dict = {}
        generator.merge_universe(
            universe,
            [
                {
                    "issueSymbolIdentifier": "aapl",
                    "issueName": "Apple",
                    "tierDescription": "NMS Tier 1",
                },
                {
                    "issueSymbolIdentifier": "AAPL",
                    "issueName": "Later",
                    "tierDescription": "NMS Tier 2",
                },
                {"issueSymbolIdentifier": None},
            ],
        )

        assert universe == {
            "AAPL": {"issue_name": "Apple", "tier": "NMS Tier 1", "product_type": None}
        }

    def test_classify(self):
        """A lookup record maps to the class fields in order."""
        assert dict(zip(generator.CLASS_FIELDS, generator.classify(AAPL))) == {
            "security_type": "ST",
            "name": "Apple Inc",
            "security_description": "Common Shares",
            "security_id": "0P000000GY",
            "performance_id": "0P000000GY",
            "exchange": "XNAS",
            "listing_market_id": "19",
            "composite_exchange_id": "126",
            "country": "USA",
            "domicile": "USA",
            "currency": "USD",
            "quote_symbol": "126.1.AAPL",
        }

    def test_classify_sparse_record(self):
        """Missing values are None and an incomplete Tenfore key gives no quote key."""
        values = generator.classify(
            {"Name": " X ", "AC021": "", "TenforeInfo": ["X", "", "1", "22"]}
        )

        assert values[1] == "X"
        assert values[2] is None
        assert values[-1] is None

    def test_lookup_form(self):
        """Preferred series move to a lower-case p, on the market when one is given."""
        assert generator.lookup_form("ACP$A") == "ACPpA"
        assert generator.lookup_form("BRK.B") == "BRK.B"
        assert generator.lookup_form("ACP$A", "126") == "126:ACPpA"

    @pytest.mark.parametrize(
        ("tier", "prefix"),
        [("NMS Tier 1", "126"), ("NMS Tier 2", "126"), ("OTC", "22"), (None, "126")],
    )
    def test_market_prefix(self, tier, prefix):
        """OTC equities are looked up on the OTC composite, NMS stocks on the US one."""
        assert generator.market_prefix(tier) == prefix

    def test_lookup_plan(self):
        """Symbols are grouped by the market they are looked up on."""
        universe = {"AAPL": {"tier": "NMS Tier 1"}, "TCEHY": {"tier": "OTC"}}

        assert generator.lookup_plan(universe, ["AAPL", "TCEHY", "NEW"]) == {
            "126": ["AAPL", "NEW"],
            "22": ["TCEHY"],
        }

    def test_read_lookup_on_a_market(self):
        """Records looked up on a market are matched by their prefixed key."""
        records = [{**AAPL, "QueryKey": "126:AAPL"}, {"QueryKey": "126:X"}]

        assert set(generator.read_lookup(records, ["AAPL", "X"], "126")) == {"AAPL"}

    def test_read_lookup_keeps_only_us_markets(self):
        """Without a market, records off the US composites are dropped."""
        records = [
            {**AAPL, "QueryKey": "AAPL"},
            {**AAPL, "QueryKey": "ISSC", "CompositeExchangeID": "52"},
        ]

        assert set(generator.read_lookup(records, ["AAPL", "ISSC"])) == {"AAPL"}

    def test_read_lookup(self):
        """Records map back to the FINRA symbols that were looked up."""
        records = [
            {**AAPL},
            {**AAPL, "QueryKey": "ACPpA", "Type": "ST"},
            {**AAPL, "QueryKey": "ZZZZ"},
            {"Type": "ST"},
        ]
        classes = generator.read_lookup(records, ["AAPL", "ACP$A"])

        assert set(classes) == {"AAPL", "ACP$A"}

    def test_batches(self, monkeypatch):
        """Symbols are split into lookup-sized batches."""
        monkeypatch.setattr(generator, "LOOKUP_BATCH", 2)

        assert generator.batches(["A", "B", "C"]) == [["A", "B"], ["C"]]


class TestClient:
    """The standard-library client returns status, body, and headers."""

    class _Response(io.BytesIO):
        status = 200
        headers = {"Record-Total": "3"}

    def test_get_and_post(self):
        """Parameters are encoded and JSON bodies posted."""
        seen = []
        client = generator.Client()

        def _open(request, timeout):
            seen.append((request.full_url, request.data, request.get_method()))

            return self._Response(b"[1]")

        client.opener.open = _open

        assert client.request("https://x/y", {"a": "1"}) == (
            200,
            "[1]",
            {"record-total": "3"},
        )
        assert client.request("https://x/y", payload={"b": 2})[0] == 200
        assert seen == [
            ("https://x/y?a=1", None, "GET"),
            ("https://x/y", b'{"b": 2}', "POST"),
        ]

    def test_http_error(self):
        """An HTTP error returns its status and body."""
        client = generator.Client()

        def _open(request, timeout):
            raise HTTPError(request.full_url, 500, "error", {}, io.BytesIO(b"boom"))

        client.opener.open = _open

        assert client.request("https://x/y") == (500, "boom", {})


def _universe_responder(partitions_status=200):
    """Answer the weekly partitions and summaries."""

    def respond(url, params, payload):
        if urlparse(url).path.startswith("/partitions/"):
            body = {"availablePartitions": [{"partitions": ["2026-08-31", "T1"]}]}

            return partitions_status, json.dumps(body), {}

        if payload["compareFilters"][2]["fieldValue"] == "ATS_W_SMBL":
            if payload["offset"] == 0:
                return (
                    200,
                    json.dumps([{"issueSymbolIdentifier": "AAPL"}]),
                    {"record-total": "2"},
                )

            return (
                200,
                json.dumps([{"issueSymbolIdentifier": "ACP$A"}]),
                {"record-total": "2"},
            )

        return 204, "", {}

    return respond


class TestFetchUniverse:
    """The traded universe is read from the latest week of each tier."""

    def test_pages_and_types(self):
        """Every page of every summary type is read."""
        client = FakeClient(_universe_responder())
        weeks, universe = generator.fetch_universe(client)

        assert weeks == {"T1": "2026-08-31"}
        assert set(universe) == {"AAPL", "ACP$A"}
        assert len(client.calls) == 4

    def test_empty_page_ends_the_type(self):
        """A page with no rows ends that summary type."""

        def respond(url, params, payload):
            if urlparse(url).path.startswith("/partitions/"):
                return (
                    200,
                    json.dumps({"availablePartitions": [{"partitions": ["w", "T1"]}]}),
                    {},
                )

            return 200, "[]", {"record-total": "5"}

        weeks, universe = generator.fetch_universe(FakeClient(respond))

        assert universe == {}

    def test_partitions_refused(self):
        """A refused partitions request raises."""
        with pytest.raises(RuntimeError, match="partitions with HTTP 500"):
            generator.fetch_universe(FakeClient(_universe_responder(500)))

    def test_summary_refused(self):
        """A refused summary request raises."""

        def respond(url, params, payload):
            if urlparse(url).path.startswith("/partitions/"):
                return (
                    200,
                    json.dumps({"availablePartitions": [{"partitions": ["w", "T1"]}]}),
                    {},
                )

            return 400, "{}", {}

        with pytest.raises(RuntimeError, match="T1 weekly summary with HTTP 400"):
            generator.fetch_universe(FakeClient(respond))

class TestBuild:
    """The asset holds the classes, the unresolved symbols, and the weeks."""

    def test_build(self):
        """Known classes are kept, new symbols are unresolved, nothing is looked up."""
        known = {
            "AAPL": generator.classify(AAPL),
            "GONE": generator.classify(AAPL),
        }
        
        client = FakeClient(_universe_responder())
        asset = generator.build(client, known)
        
        assert asset["weeks"] == {"T1": "2026-08-31"}
        assert asset["securities"] == {"AAPL": known["AAPL"]}
        assert asset["unresolved"] == ["ACP$A"]
        assert asset["fields"] == generator.CLASS_FIELDS
        assert not any(urlparse(call[0]).path == "/getids.jsp" for call in client.calls)

    def test_read_classes(self, monkeypatch, tmp_path):
        """The classes of the existing asset are read, and none when it is missing."""
        target = tmp_path / "security_types.json.gz"
        monkeypatch.setattr(generator, "ASSET_PATH", target)

        assert generator.read_classes() == {}

        target.write_bytes(
            gzip.compress(json.dumps({"securities": {"A": ["ST"]}}).encode())
        )

        assert generator.read_classes() == {"A": ["ST"]}

    def test_main_writes_the_asset(self, monkeypatch, tmp_path, capsys):
        """The asset is written gzipped and summarized."""
        target = tmp_path / "assets" / "security_types.json.gz"
        monkeypatch.setattr(generator, "ASSET_PATH", target)
        monkeypatch.setattr(
            generator,
            "build",
            lambda client, known: {
                "weeks": {},
                "fields": [],
                "securities": {"A": []},
                "unresolved": [],
            },
        )

        assert generator.main() == 0
        assert json.loads(gzip.decompress(target.read_bytes()))["securities"] == {
            "A": []
        }
        assert "1 classified, 0 unresolved" in capsys.readouterr().err
