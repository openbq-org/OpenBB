"""Tests for the traded-security list."""

import asyncio
import gzip
import json
from urllib.parse import urlparse

import pytest
from openbb_core.app.model.abstract.error import OpenBBError

from openbb_finra.utils import directory, generate_securities

LOOKUP = {
    "Type": "FE",
    "CompositeExchangeID": "126",
    "OS01W": "State Street SPDR S&P 500 ETF",
    "SecId": "FEUSA00001",
    "PID": "0P00002D7X",
    "ListingMarket": "16",
}


def _partitions():
    """Return a partitions body with one week per tier."""
    return json.dumps(
        {
            "availablePartitions": [
                {"partitions": ["2026-08-31", "T1"]},
                {"partitions": ["2026-08-17", "OTCE"]},
            ]
        }
    )


def _summary(call):
    """Return the weekly summary rows of one tier and summary type."""
    tier = call["json"]["compareFilters"][1]["fieldValue"]
    summary_type = call["json"]["compareFilters"][2]["fieldValue"]
    rows = {
        ("T1", "ATS_W_SMBL"): [
            {
                "issueSymbolIdentifier": "AAPL",
                "tierDescription": "NMS Tier 1",
                "productTypeCode": "UTP",
            },
            {
                "issueSymbolIdentifier": "SPY",
                "tierDescription": "NMS Tier 1",
                "productTypeCode": "CTS",
            },
        ],
        ("T1", "OTC_W_SMBL"): [
            {
                "issueSymbolIdentifier": "SPY",
                "tierDescription": "NMS Tier 1",
                "productTypeCode": "CTS",
            },
        ],
        ("OTCE", "OTC_W_SMBL"): [
            {"issueSymbolIdentifier": "ACHR.W", "tierDescription": "OTC"},
            {"issueSymbolIdentifier": "NEWCO", "tierDescription": "OTC"},
        ],
    }.get((tier, summary_type), [])

    return json.dumps(rows), {"record-total": str(len(rows))}


@pytest.fixture
def asset(monkeypatch, tmp_path):
    """Install a small bundled asset."""
    path = tmp_path / "security_types.json.gz"
    classes = {
        "AAPL": [
            "ST",
            "Apple Inc",
            "Common Shares",
            "0P000000GY",
            "0P000000GY",
            "XNAS",
            "19",
            "126",
            "USA",
            "USA",
            "USD",
            "126.1.AAPL",
        ],
    }
    path.write_bytes(
        gzip.compress(
            json.dumps(
                {"securities": classes, "unresolved": ["ACHR.W"], "fields": []}
            ).encode()
        )
    )
    monkeypatch.setattr(generate_securities, "ASSET_PATH", path)

    return path


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    """Retry without pausing."""
    monkeypatch.setattr("openbb_finra.utils.constants.LOOKUP_THROTTLE_WAIT", 0)


def _responder(response, lookup_statuses=None, reject=()):
    """Answer the Query API and the Market Data Center."""
    statuses = list(lookup_statuses or [])

    def respond(call):
        url = call["url"]

        if urlparse(url).path.startswith("/partitions/"):
            return response(200, _partitions())

        if urlparse(url).path.endswith("/weeklySummary"):
            body, headers = _summary(call)

            return response(200, body, headers)

        if urlparse(url).path == "/finralogin.jsp":
            return response(200, "\n")

        if statuses:
            return response(statuses.pop(0), "")

        symbols = call["params"]["symbol"].split(",")

        if any(bad in symbol for symbol in symbols for bad in reject):
            return response(500, "error")

        return response(
            200,
            json.dumps({"Records": [{**LOOKUP, "QueryKey": s} for s in symbols]}),
        )

    return respond


class TestAsset:
    """The bundled asset is read, with a safe fallback."""

    def test_bundled_asset(self):
        """The shipped asset classifies the traded universe."""
        bundled = directory.read_asset()

        assert len(bundled["securities"]) > 10000
        assert bundled["fields"] == generate_securities.CLASS_FIELDS
        assert bundled["securities"]["AAPL"][0] == "ST"

    def test_missing_asset(self, monkeypatch, tmp_path):
        """A missing asset reads as empty."""
        monkeypatch.setattr(generate_securities, "ASSET_PATH", tmp_path / "none.gz")

        assert directory.read_asset() == {"securities": {}, "unresolved": []}


class TestList:
    """The list joins the live universe to the bundled and live classes."""

    def test_rows(self, asset, fake_session, response):
        """Known symbols use the asset, new ones are looked up, unresolved stay bare."""
        session = fake_session(responder=_responder(response))
        rows = {row["symbol"]: row for row in asyncio.run(directory.list_securities())}

        assert list(rows) == ["AAPL", "ACHR.W", "NEWCO", "SPY"]
        assert rows["AAPL"]["security_type"] == "ST"
        assert rows["AAPL"]["tier"] == "NMS Tier 1"
        assert urlparse(rows["AAPL"]["url"]).query == "query=19:0P000000GY"
        assert rows["SPY"]["security_type"] == "FE"
        assert rows["ACHR.W"].get("security_type") is None
        assert rows["ACHR.W"]["url"] is None

        lookups = [
            call
            for call in session.calls
            if urlparse(call["url"]).path == "/getids.jsp"
        ]

        assert [call["params"] for call in lookups] == [
            {"symbol": "22:NEWCO", "cb": "finraLookup"},
            {"symbol": "126:SPY", "cb": "finraLookup"},
        ]

    def test_nothing_to_look_up(self, asset, monkeypatch):
        """When the asset knows every symbol no lookup session is opened."""

        async def _universe():
            return {"AAPL": {"tier": "T1"}}

        monkeypatch.setattr(directory, "load_universe", _universe)

        rows = asyncio.run(directory.list_securities())

        assert [row["symbol"] for row in rows] == ["AAPL"]


class TestLookups:
    """Live lookups retry throttling and isolate rejected symbols."""

    @staticmethod
    def _classify(fake_session, response, symbols, **kwargs):
        session = fake_session(responder=_responder(response, **kwargs))
        universe = {symbol: {"tier": "NMS Tier 1"} for symbol in symbols}

        return asyncio.run(directory.classify_symbols(universe)), session

    def test_rejected_symbol_is_isolated(self, fake_session, response):
        """A symbol that fails its batch is dropped and the rest classified."""
        classes, _ = self._classify(
            fake_session, response, ["AAA", "BAD", "CCC"], reject=("BAD",)
        )

        assert set(classes) == {"AAA", "CCC"}

    def test_throttled_then_served(self, fake_session, response):
        """A throttled batch is retried after a fresh login."""
        classes, session = self._classify(
            fake_session, response, ["AAA"], lookup_statuses=[429]
        )
        logins = [
            call
            for call in session.calls
            if urlparse(call["url"]).path == "/finralogin.jsp"
        ]

        assert set(classes) == {"AAA"}
        assert len(logins) == 2

    def test_always_throttled(self, fake_session, response):
        """A batch throttled on every attempt raises."""
        with pytest.raises(OpenBBError, match="kept throttling"):
            self._classify(fake_session, response, ["AAA"], lookup_statuses=[429] * 10)

    def test_preferred_series(self, fake_session, response):
        """Preferred series are looked up in the Market Data Center form."""
        classes, session = self._classify(fake_session, response, ["ACP$A"])

        assert set(classes) == {"ACP$A"}
        assert session.calls[1]["params"] == {
            "symbol": "126:ACPpA",
            "cb": "finraLookup",
        }

    def test_fallback_keeps_only_us_markets(self, fake_session, response):
        """A symbol missed on its market is kept from any market only if it is US."""

        def respond(call):
            if urlparse(call["url"]).path == "/finralogin.jsp":
                return response(200, "\n")

            if ":" in call["params"]["symbol"]:
                return response(200, json.dumps({"Records": []}))

            records = [
                {**LOOKUP, "QueryKey": "WARR", "CompositeExchangeID": "126"},
                {**LOOKUP, "QueryKey": "ISSC", "CompositeExchangeID": "52"},
            ]

            return response(200, json.dumps({"Records": records}))

        fake_session(responder=respond)
        classes = asyncio.run(
            directory.classify_symbols(
                {"ISSC": {"tier": "NMS Tier 2"}, "WARR": {"tier": "NMS Tier 2"}}
            )
        )

        assert set(classes) == {"WARR"}
