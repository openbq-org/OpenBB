"""Tests for the FFIEC List of Banks in Peer Group (CDR router) model."""

import pytest
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_federal_reserve.models.list_of_banks_peer_group import (
    FederalReserveListOfBanksPeerGroupData,
    FederalReserveListOfBanksPeerGroupFetcher,
    FederalReserveListOfBanksPeerGroupQueryParams,
)

from .ffiec_cassettes import replay

_CYCLES = [
    {"reportingcycleid": "151", "enddateformatted": "03/31/2026"},
    {"reportingcycleid": "150", "enddateformatted": "12/31/2025"},
]

_ROSTER = [
    {
        "rssd_id": "233031",
        "fdic_cert": "12368",
        "charter_class": "SM",
        "name": "REGIONS BANK",
        "city": "BIRMINGHAM",
        "state": "AL",
        "state_name": "ALABAMA",
        "offices": 1221,
        "average_assets": 157731000,
        "net_income": 573000,
        "latitude": 33.5155,
        "longitude": -86.821,
    },
    {
        "rssd_id": "63069",
        "fdic_cert": "17281",
        "charter_class": "N",
        "name": "CITY NATIONAL BANK",
        "city": "LOS ANGELES",
        "state": "CA",
        "state_name": "CALIFORNIA",
        "offices": 65,
        "average_assets": 100278265,
        "net_income": 183570,
        "latitude": 34.0536,
        "longitude": -118.256,
    },
]


def _patch(monkeypatch, cycles=None, roster=None):
    """Point the cycle and roster fetches at in-memory fixtures."""
    monkeypatch.setattr(
        "openbb_federal_reserve.utils.ubpr_report.report_cycles",
        lambda: list(_CYCLES) if cycles is None else cycles,
    )
    monkeypatch.setattr(
        "openbb_federal_reserve.utils.ubpr_report.fetch_list_of_banks",
        lambda peer_group, cycle_id: list(_ROSTER) if roster is None else roster,
    )


class TestPeerGroupOptions:
    """Tests for the peer-group dropdown options on the query params."""

    def test_options_expanded_with_name_values(self):
        """The dropdown options expand to ``name -- description`` keyed by name."""
        extra = FederalReserveListOfBanksPeerGroupQueryParams.__json_schema_extra__
        options = extra["peer_group"]["x-widget_config"]["options"]
        assert len(options) == 187
        option = next(o for o in options if o["value"] == "ALCOM")
        assert option["label"] == "ALCOM -- All Insured Commercial Banks in Alabama"


class TestTransformQuery:
    """Tests for ``transform_query``."""

    def test_defaults(self):
        """The peer group defaults to '1' and date defaults to None."""
        query = FederalReserveListOfBanksPeerGroupFetcher.transform_query({})
        assert query.peer_group == "1"
        assert query.date is None

    def test_blank_peer_group_raises(self):
        """A blank peer group raises ``OpenBBError``."""
        with pytest.raises(OpenBBError):
            FederalReserveListOfBanksPeerGroupFetcher.transform_query(
                {"peer_group": "  "}
            )


class TestExtractData:
    """Tests for ``extract_data``."""

    def test_returns_roster(self, monkeypatch):
        """The roster rows pass through from the router client."""
        _patch(monkeypatch)
        query = FederalReserveListOfBanksPeerGroupFetcher.transform_query(
            {"peer_group": "1"}
        )
        rows = FederalReserveListOfBanksPeerGroupFetcher.extract_data(query, None)
        assert len(rows) == 2

    def test_selects_requested_date(self, monkeypatch):
        """A requested end date resolves to its reporting cycle id."""
        captured = {}

        def _fetch(peer_group, cycle_id):
            """Record the cycle id used for the roster fetch."""
            captured["cycle_id"] = cycle_id
            return list(_ROSTER)

        _patch(monkeypatch)
        monkeypatch.setattr(
            "openbb_federal_reserve.utils.ubpr_report.fetch_list_of_banks", _fetch
        )
        query = FederalReserveListOfBanksPeerGroupFetcher.transform_query(
            {"peer_group": "1", "date": "12/31/2025"}
        )
        FederalReserveListOfBanksPeerGroupFetcher.extract_data(query, None)
        assert captured["cycle_id"] == "150"

    def test_empty_cycles_raises(self, monkeypatch):
        """An empty cycle list raises ``EmptyDataError``."""
        _patch(monkeypatch, cycles=[])
        query = FederalReserveListOfBanksPeerGroupFetcher.transform_query(
            {"peer_group": "1"}
        )
        with pytest.raises(EmptyDataError):
            FederalReserveListOfBanksPeerGroupFetcher.extract_data(query, None)

    def test_empty_roster_raises(self, monkeypatch):
        """An empty roster raises ``EmptyDataError``."""
        _patch(monkeypatch, roster=[])
        query = FederalReserveListOfBanksPeerGroupFetcher.transform_query(
            {"peer_group": "999"}
        )
        with pytest.raises(EmptyDataError):
            FederalReserveListOfBanksPeerGroupFetcher.extract_data(query, None)


class TestTransformData:
    """Tests for ``transform_data``."""

    def test_validates_roster(self, monkeypatch):
        """Each row validates into the data model with typed fields."""
        _patch(monkeypatch)
        query = FederalReserveListOfBanksPeerGroupFetcher.transform_query(
            {"peer_group": "1"}
        )
        rows = FederalReserveListOfBanksPeerGroupFetcher.extract_data(query, None)
        result = FederalReserveListOfBanksPeerGroupFetcher.transform_data(query, rows)
        assert all(
            isinstance(r, FederalReserveListOfBanksPeerGroupData) for r in result
        )
        first = result[0].model_dump()
        assert first["name"] == "REGIONS BANK"
        assert first["average_assets"] == 157731000 * 1000
        assert first["net_income"] == 573000 * 1000
        assert first["offices"] == 1221

    def test_scales_and_sorts_by_average_assets(self, monkeypatch):
        """Dollar amounts scale to U.S. dollars and rows sort by assets desc."""
        roster = [
            {"name": "SMALL", "average_assets": 100, "net_income": 5},
            {"name": "LARGE", "average_assets": 900, "net_income": 50},
            {"name": "NONE", "average_assets": None, "net_income": None},
        ]
        _patch(monkeypatch, roster=roster)
        query = FederalReserveListOfBanksPeerGroupFetcher.transform_query(
            {"peer_group": "1"}
        )
        rows = FederalReserveListOfBanksPeerGroupFetcher.extract_data(query, None)
        result = FederalReserveListOfBanksPeerGroupFetcher.transform_data(query, rows)
        assert [r.name for r in result] == ["LARGE", "SMALL", "NONE"]
        assert result[0].average_assets == 900 * 1000
        assert result[0].net_income == 50 * 1000
        assert result[-1].average_assets is None
        assert result[-1].net_income is None

    def test_fractional_thousands_round_to_whole_dollars(self, monkeypatch):
        """FFIEC reports some amounts in fractional thousands; the fields are int."""
        roster = [{"name": "A", "average_assets": 1234.5678, "net_income": -0.5}]
        _patch(monkeypatch, roster=roster)
        query = FederalReserveListOfBanksPeerGroupFetcher.transform_query(
            {"peer_group": "1"}
        )
        rows = FederalReserveListOfBanksPeerGroupFetcher.extract_data(query, None)
        result = FederalReserveListOfBanksPeerGroupFetcher.transform_data(query, rows)
        assert (result[0].average_assets, result[0].net_income) == (1234568, -500)


class TestCassetteIntegration:
    """Run the full fetcher against a recorded FFIEC router cassette."""

    def test_real_roster_parses_from_cassette(self):
        """The full pipeline parses the real captured peer-group roster.

        Replays the recorded ``PeriodsEndDateList`` and ``LlistOfBanks`` router
        responses and runs ``transform_query`` -> ``extract_data`` ->
        ``transform_data`` so the actual parse executes on real captured data.
        """
        with replay("list_of_banks_peer_group"):
            query = FederalReserveListOfBanksPeerGroupFetcher.transform_query({})
            rows = FederalReserveListOfBanksPeerGroupFetcher.extract_data(query, None)
            result = FederalReserveListOfBanksPeerGroupFetcher.transform_data(
                query, rows
            )

        assert query.peer_group == "1"
        assert result
        assert all(
            isinstance(r, FederalReserveListOfBanksPeerGroupData) for r in result
        )

        names = {r.name for r in result}
        assert "JPMORGAN CHASE BANK, NATIONAL ASSOCIATION" in names
        assert "REGIONS BANK" in names

        top = result[0]
        assert top.name == "JPMORGAN CHASE BANK, NATIONAL ASSOCIATION"
        assert top.rssd_id == "852218"
        assert top.fdic_cert == "628"
        assert top.charter_class == "N"
        assert top.city == "COLUMBUS"
        assert top.state == "OH"
        assert top.state_name == "OHIO"
        assert top.offices == 5114
        assert top.average_assets == 3920682000 * 1000
        assert top.net_income == 13974000 * 1000
        assert top.latitude == pytest.approx(40.1405)
        assert top.longitude == pytest.approx(-82.986)

        assets = [r.average_assets for r in result if r.average_assets is not None]
        assert len(assets) > 1
        assert assets == sorted(assets, reverse=True)
        assert all(isinstance(a, int) for a in assets)
