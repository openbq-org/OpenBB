"""Unit tests for the IMF port info and volume models."""

# ruff: noqa: I001

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from openbb_core.app.model.abstract.error import OpenBBError

from openbb_imf.models.port_info import (
    ImfPortInfoData,
    ImfPortInfoFetcher,
    ImfPortInfoQueryParams,
)
from openbb_imf.models.port_volume import (
    ImfPortVolumeData,
    ImfPortVolumeFetcher,
    ImfPortVolumeQueryParams,
)


class _FakeResponse:
    """Pretend aiohttp ``ClientResponse`` returning a fixed payload/status."""

    def __init__(self, payload: Any, status: int = 200, reason: str = ""):
        self.status = status
        self.reason = reason
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self) -> Any:
        return self._payload


class _AwaitableContext:
    """Wrap a CM so ``await session.get(url)`` works."""

    def __init__(self, ctx):
        self._ctx = ctx

    def __await__(self):
        async def _do():
            return self._ctx

        return _do().__await__()


class _FakeSession:
    """aiohttp session double that returns successive responses by call order."""

    def __init__(
        self, payloads: list[dict[str, Any]], statuses: list[int] | None = None
    ):
        self._payloads = list(payloads)
        self._statuses = list(statuses) if statuses else [200] * len(self._payloads)
        self.urls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get(self, url: str):
        self.urls.append(url)
        payload = self._payloads.pop(0) if self._payloads else {}
        status = self._statuses.pop(0) if self._statuses else 200
        return _AwaitableContext(_FakeResponse(payload, status=status))


def _patch_session(
    payloads: list[dict[str, Any]],
    statuses: list[int] | None = None,
):
    """Build a patcher for ``get_async_requests_session`` using ``_FakeSession``."""
    fake = _FakeSession(payloads, statuses=statuses)

    class _Factory:
        async def __aenter__(self_):
            return fake

        async def __aexit__(self_, *args):
            return False

    async def _factory(*args, **kwargs):
        return _Factory()

    patcher = patch(
        "openbb_core.provider.utils.helpers.get_async_requests_session",
        side_effect=_factory,
    )
    return patcher, fake


def _port_attrs(
    portid: str = "port1",
    portname: str = "Sample",
    iso: str = "USA",
    continent: str = "North America",
    vessel_count_total: int = 100,
) -> dict[str, Any]:
    """Return a minimal port-attributes dict consumable by ``ImfPortInfoData``."""
    return {
        "portid": portid,
        "portname": portname,
        "fullname": portname,
        "ISO3": iso,
        "countrynoaccents": "United States",
        "continent": continent,
        "lat": 0.0,
        "lon": 0.0,
        "vessel_count_total": vessel_count_total,
        "vessel_count_tanker": 10,
        "vessel_count_container": 20,
        "vessel_count_general_cargo": 5,
        "vessel_count_dry_bulk": 15,
        "vessel_count_RoRo": 2,
        "share_country_maritime_import": 5.0,
        "share_country_maritime_export": 7.0,
    }


def _patch_port_helpers(
    monkeypatch: pytest.MonkeyPatch,
    port_id_choices: list[dict[str, str]] | None = None,
    port_ids_by_country: str | None = None,
) -> None:
    """Stub the port-watch helpers to keep ``port_volume`` validators offline."""
    if port_id_choices is None:
        port_id_choices = [{"label": "Honolulu - HI", "value": "port1114"}]
    monkeypatch.setattr(
        "openbb_imf.models.port_volume.get_port_id_choices",
        lambda: port_id_choices,
    )

    def _by_country(code: str) -> str:
        return port_ids_by_country if port_ids_by_country is not None else ""

    monkeypatch.setattr(
        "openbb_imf.models.port_volume.get_port_ids_by_country",
        _by_country,
    )


class TestImfPortInfoFetcher:
    """Tests for ``ImfPortInfoFetcher``."""

    def test_transform_query_defaults(self):
        """Defaults: no continent, country, or port_code applied."""
        q = ImfPortInfoFetcher.transform_query({})
        assert isinstance(q, ImfPortInfoQueryParams)
        assert q.country is None
        assert q.continent is None

    @pytest.mark.asyncio
    async def test_aextract_data_non_200_raises(self):
        """Non-200 first-page response raises ``OpenBBError`` (covers lines 238-240, 268-269)."""
        patcher, _ = _patch_session([{}], statuses=[500])
        q = ImfPortInfoFetcher.transform_query({})
        with patcher:
            with pytest.raises(OpenBBError):
                await ImfPortInfoFetcher.aextract_data(q, None)

    @pytest.mark.asyncio
    async def test_aextract_data_country_pushes_where_clause(self):
        """A ``country`` query sends ``where=ISO3='X'`` to the ArcGIS server."""
        page = {"features": [{"attributes": _port_attrs("p1", "A", iso="USA")}]}
        patcher, fake = _patch_session([page])
        q = ImfPortInfoFetcher.transform_query({"country": "USA"})
        with patcher:
            await ImfPortInfoFetcher.aextract_data(q, None)
        assert "where=ISO3%3D%27USA%27" in fake.urls[0]

    @pytest.mark.asyncio
    async def test_aextract_data_continent_pushes_where_clause(self):
        """A ``continent`` query maps to the label and sends ``where=continent='X'``."""
        page = {"features": [{"attributes": _port_attrs("p1", "A")}]}
        patcher, fake = _patch_session([page])
        q = ImfPortInfoFetcher.transform_query({"continent": "north_america"})
        with patcher:
            await ImfPortInfoFetcher.aextract_data(q, None)
        assert "where=continent%3D%27North+America%27" in fake.urls[0]

    @pytest.mark.asyncio
    async def test_aextract_data_default_uses_1_eq_1(self):
        """No filter falls back to the ``where=1=1`` catch-all."""
        page = {"features": [{"attributes": _port_attrs("p1", "A")}]}
        patcher, fake = _patch_session([page])
        q = ImfPortInfoFetcher.transform_query({})
        with patcher:
            await ImfPortInfoFetcher.aextract_data(q, None)
        assert "where=1%3D1" in fake.urls[0]

    @pytest.mark.asyncio
    async def test_aextract_data_limit_is_passed_to_server(self):
        """``limit`` is forwarded as ``resultRecordCount``."""
        page = {"features": [{"attributes": _port_attrs("p1", "A")}]}
        patcher, fake = _patch_session([page])
        q = ImfPortInfoFetcher.transform_query({"limit": 5})
        with patcher:
            await ImfPortInfoFetcher.aextract_data(q, None)
        assert "resultRecordCount=5" in fake.urls[0]

    @pytest.mark.asyncio
    async def test_aextract_data_handles_pagination(self):
        """``exceededTransferLimit`` triggers a second page fetch with offset."""
        page1 = {
            "features": [{"attributes": _port_attrs("p1", "A")}],
            "exceededTransferLimit": True,
        }
        page2 = {"features": [{"attributes": _port_attrs("p2", "B")}]}
        patcher, fake = _patch_session([page1, page2])
        q = ImfPortInfoFetcher.transform_query({})
        with patcher:
            out = await ImfPortInfoFetcher.aextract_data(q, None)
        assert len(out) == 2
        assert "resultOffset=1" in fake.urls[1]

    @pytest.mark.asyncio
    async def test_aextract_data_limit_short_circuits_pagination(self):
        """Once ``limit`` rows are accumulated paging stops and the list is truncated."""
        page1 = {
            "features": [
                {"attributes": _port_attrs("p1", "A")},
                {"attributes": _port_attrs("p2", "B")},
            ],
            "exceededTransferLimit": True,
        }
        patcher, fake = _patch_session([page1])
        q = ImfPortInfoFetcher.transform_query({"limit": 2})
        with patcher:
            out = await ImfPortInfoFetcher.aextract_data(q, None)
        assert len(fake.urls) == 1
        assert len(out) == 2

    @pytest.mark.asyncio
    async def test_aextract_data_pagination_non_200_raises(self):
        """A subsequent paginated request that fails raises ``OpenBBError``."""
        page1 = {
            "features": [{"attributes": _port_attrs("p1", "A")}],
            "exceededTransferLimit": True,
        }
        patcher, _ = _patch_session([page1, {}], statuses=[200, 500])
        q = ImfPortInfoFetcher.transform_query({})
        with patcher:
            with pytest.raises(OpenBBError):
                await ImfPortInfoFetcher.aextract_data(q, None)

    def test_transform_data_straight_maps_attributes(self):
        """``transform_data`` is a 1:1 mapping; the server already filtered/sorted/limited."""
        rows = [
            {"attributes": _port_attrs("p1", "A", iso="USA", vessel_count_total=300)},
            {"attributes": _port_attrs("p2", "B", iso="USA", vessel_count_total=200)},
        ]
        q = ImfPortInfoFetcher.transform_query({"country": "USA"})
        out = ImfPortInfoFetcher.transform_data(q, rows)
        assert [r.port_name for r in out] == ["A", "B"]
        assert all(isinstance(r, ImfPortInfoData) for r in out)


class TestImfPortVolumeQueryParams:
    """Tests for ``ImfPortVolumeQueryParams`` validators."""

    def test_validate_port_code_all_returns_all(self, monkeypatch):
        """``port_code='all'`` is returned verbatim (covers line 92)."""
        _patch_port_helpers(monkeypatch)
        q = ImfPortVolumeQueryParams(port_code="all")
        assert q.port_code == "all"

    def test_validate_port_code_country_code_expands(self, monkeypatch):
        """An ISO3 country code expands via ``get_port_ids_by_country`` (covers 95-98)."""
        _patch_port_helpers(
            monkeypatch,
            port_id_choices=[
                {"label": "Honolulu - HI", "value": "port1"},
                {"label": "San Diego - CA", "value": "port2"},
            ],
            port_ids_by_country="port1,port2",
        )
        q = ImfPortVolumeQueryParams(port_code="USA")
        assert q.port_code == "port1,port2"

    def test_validate_port_code_label_match_picks_value(self, monkeypatch):
        """Matching by label appends the value (covers 109-113)."""
        _patch_port_helpers(
            monkeypatch,
            port_id_choices=[{"label": "Honolulu - HI", "value": "port1"}],
        )
        q = ImfPortVolumeQueryParams(port_code="Honolulu - HI")
        assert q.port_code == "port1"

    def test_validate_port_code_snake_match_picks_value(self, monkeypatch):
        """A snake-cased port name resolves to its port code."""
        _patch_port_helpers(
            monkeypatch,
            port_id_choices=[
                {"label": "Rotterdam", "value": "port1114"},
                {"label": "Singapore", "value": "port1201"},
            ],
        )
        q = ImfPortVolumeQueryParams(port_code="rotterdam,singapore")
        assert q.port_code == "port1114,port1201"

    def test_validate_port_code_first_part_match(self, monkeypatch):
        """First-segment match falls through to the final elif (covers 125-134)."""
        _patch_port_helpers(
            monkeypatch,
            port_id_choices=[{"label": "Honolulu - HI", "value": "port1"}],
        )
        q = ImfPortVolumeQueryParams(port_code="honolulu")
        assert q.port_code == "port1"

    def test_validate_port_code_unknown_raises(self, monkeypatch):
        """A completely unknown name raises ``ValueError`` (covers 136-138)."""
        _patch_port_helpers(
            monkeypatch,
            port_id_choices=[{"label": "Honolulu - HI", "value": "port1"}],
        )
        with pytest.raises(ValueError):
            ImfPortVolumeQueryParams(port_code="atlantis")

    def test_validate_port_code_empty_list_raises(self, monkeypatch):
        """An empty list after processing raises ``ValueError`` (covers line 141)."""
        _patch_port_helpers(
            monkeypatch,
            port_id_choices=[{"label": "Honolulu - HI", "value": "port1"}],
            port_ids_by_country="",
        )
        with pytest.raises(ValueError):
            ImfPortVolumeQueryParams(port_code="USA")

    def test_validate_model_rejects_pre_2019(self, monkeypatch):
        """``start_date`` before 2019-01-01 raises ``OpenBBError`` (covers lines 152-156)."""
        _patch_port_helpers(monkeypatch)
        with pytest.raises(OpenBBError):
            ImfPortVolumeQueryParams(port_code="port1114", start_date=date(2018, 1, 1))

    def test_validate_model_defaults_port_code(self, monkeypatch):
        """No port_code or country falls back to ``port1114`` (covers line 158)."""
        _patch_port_helpers(monkeypatch)
        q = ImfPortVolumeQueryParams()
        assert q.port_code == "port1114"


class TestImfPortVolumeFetcher:
    """Tests for ``ImfPortVolumeFetcher``."""

    def test_transform_query_rejects_pre_2019(self, monkeypatch):
        """Pre-2019 ``start_date`` at the fetcher entry raises (covers lines 369-376)."""
        _patch_port_helpers(monkeypatch)
        with pytest.raises(OpenBBError):
            ImfPortVolumeFetcher.transform_query({"start_date": date(2018, 1, 1)})

    def test_transform_query_country_to_port_code(self, monkeypatch):
        """A ``country`` is converted into a comma-joined port list (covers 378-385)."""
        _patch_port_helpers(monkeypatch, port_ids_by_country="port1114")
        q = ImfPortVolumeFetcher.transform_query({"country": "USA"})
        assert "port1114" in q.port_code

    @pytest.mark.asyncio
    async def test_aextract_no_port_codes_raises(self, monkeypatch):
        """Empty resolved port list raises ``OpenBBError`` (covers line 408)."""
        _patch_port_helpers(monkeypatch)
        q = ImfPortVolumeFetcher.transform_query({"port_code": "port1114"})
        object.__setattr__(q, "port_code", None)
        object.__setattr__(q, "country", None)
        with pytest.raises(OpenBBError):
            await ImfPortVolumeFetcher.aextract_data(q, None)

    @pytest.mark.asyncio
    async def test_aextract_per_port_helper_failure(self, monkeypatch):
        """A per-port helper exception bubbles up via ``OpenBBError`` (covers 420-433)."""
        _patch_port_helpers(monkeypatch)
        q = ImfPortVolumeFetcher.transform_query({"port_code": "port1114"})
        with patch(
            "openbb_imf.utils.port_watch_helpers.get_daily_port_activity_data",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            with pytest.raises(OpenBBError):
                await ImfPortVolumeFetcher.aextract_data(q, None)

    @pytest.mark.asyncio
    async def test_aextract_empty_output_raises(self, monkeypatch):
        """An empty aggregated output raises ``OpenBBError`` (covers lines 435-440)."""
        _patch_port_helpers(monkeypatch)
        q = ImfPortVolumeFetcher.transform_query({"port_code": "port1114"})
        with patch(
            "openbb_imf.utils.port_watch_helpers.get_daily_port_activity_data",
            new=AsyncMock(return_value=[]),
        ):
            with pytest.raises(OpenBBError):
                await ImfPortVolumeFetcher.aextract_data(q, None)

    @pytest.mark.asyncio
    async def test_aextract_aggregates_results(self, monkeypatch):
        """Per-port results are appended to the shared output list."""
        _patch_port_helpers(monkeypatch)
        q = ImfPortVolumeFetcher.transform_query({"port_code": "port1114"})
        with patch(
            "openbb_imf.utils.port_watch_helpers.get_daily_port_activity_data",
            new=AsyncMock(return_value=[{"portid": "port1114", "date": "2024-01-01"}]),
        ):
            out = await ImfPortVolumeFetcher.aextract_data(q, None)
        assert out and out[0]["portid"] == "port1114"

    def test_transform_data_validates_rows(self, monkeypatch):
        """Rows pass through ``ImfPortVolumeData`` with the correct alias map."""
        _patch_port_helpers(monkeypatch)
        q = ImfPortVolumeFetcher.transform_query({"port_code": "port1114"})
        rows = [
            {
                "date": "2024-01-01",
                "portid": "port1114",
                "portname": "Honolulu",
                "ISO3": "USA",
                "portcalls": 5,
                "portcalls_tanker": 1,
                "portcalls_container": 2,
                "portcalls_general_cargo": 1,
                "portcalls_dry_bulk": 1,
                "portcalls_roro": 0,
                "import": 100.0,
                "import_cargo": 70.0,
                "import_tanker": 30.0,
                "import_container": 40.0,
                "import_general_cargo": 10.0,
                "import_dry_bulk": 15.0,
                "import_roro": 5.0,
                "export": 50.0,
                "export_cargo": 30.0,
                "export_tanker": 20.0,
                "export_container": 15.0,
                "export_general_cargo": 5.0,
                "export_dry_bulk": 8.0,
                "export_roro": 2.0,
            }
        ]
        out = ImfPortVolumeFetcher.transform_data(q, rows)
        assert isinstance(out[0], ImfPortVolumeData)
        assert out[0].port_code == "port1114"
        assert out[0].imports == 100.0
