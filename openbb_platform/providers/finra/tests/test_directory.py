"""Tests for the traded-security list."""

import asyncio
import gzip
import json
from urllib.parse import urlparse

import pytest

from openbb_finra.utils import directory, generate_securities


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


def _responder(response):
    """Answer FINRA Query API requests."""

    def respond(call):
        path = urlparse(call["url"]).path

        if path.startswith("/partitions/"):
            return response(200, _partitions())

        if path.endswith("/weeklySummary"):
            body, headers = _summary(call)
            return response(200, body, headers)

        return response(200, "{}")

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
    """The list joins the live universe to the bundled classes."""

    def test_rows(self, asset, fake_session, response):
        """Known symbols use the asset; new symbols are returned without classes."""
        session = fake_session(responder=_responder(response))
        rows = {row["symbol"]: row for row in asyncio.run(directory.list_securities())}

        assert list(rows) == ["AAPL", "ACHR.W", "NEWCO", "SPY"]
        assert rows["AAPL"]["security_type"] == "ST"
        assert rows["AAPL"]["tier"] == "NMS Tier 1"
        assert urlparse(rows["AAPL"]["url"]).query == "query=19:0P000000GY"
        assert rows["SPY"].get("security_type") is None
        assert rows["NEWCO"].get("security_type") is None
        assert rows["ACHR.W"].get("security_type") is None
        assert rows["ACHR.W"]["url"] is None

        assert not any(
            urlparse(call["url"]).path == "/getids.jsp" for call in session.calls
        )

    def test_bundled_classification_is_preserved(self, asset, monkeypatch):
        """A known symbol keeps its bundled classification."""

        async def _universe():
            return {"AAPL": {"tier": "T1"}}

        monkeypatch.setattr(directory, "load_universe", _universe)

        rows = asyncio.run(directory.list_securities())

        assert rows[0]["security_type"] == "ST"
        assert [row["symbol"] for row in rows] == ["AAPL"]