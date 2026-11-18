"""Tests for the Minneapolis Fed regional models."""

from datetime import date
from unittest.mock import MagicMock

import pytest
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_federal_reserve.models.regional.minneapolis_business_conditions import (
    FederalReserveMinneapolisBusinessConditionsData,
    FederalReserveMinneapolisBusinessConditionsFetcher,
)
from openbb_federal_reserve.models.regional.minneapolis_claims import (
    FederalReserveMinneapolisClaimsData,
    FederalReserveMinneapolisClaimsFetcher,
)
from openbb_federal_reserve.models.regional.minneapolis_cpi import (
    FederalReserveMinneapolisCpiData,
    FederalReserveMinneapolisCpiFetcher,
)
from openbb_federal_reserve.models.regional.minneapolis_employment import (
    FederalReserveMinneapolisEmploymentData,
    FederalReserveMinneapolisEmploymentFetcher,
)
from openbb_federal_reserve.models.regional.minneapolis_gdp import (
    FederalReserveMinneapolisGdpData,
    FederalReserveMinneapolisGdpFetcher,
)
from openbb_federal_reserve.models.regional.minneapolis_job_openings import (
    FederalReserveMinneapolisJobOpeningsData,
    FederalReserveMinneapolisJobOpeningsFetcher,
    _state_url,
)
from openbb_federal_reserve.models.regional.minneapolis_labor_force import (
    FederalReserveMinneapolisLaborForceData,
    FederalReserveMinneapolisLaborForceFetcher,
)
from openbb_federal_reserve.models.regional.minneapolis_quits_rate import (
    FederalReserveMinneapolisQuitsRateData,
    FederalReserveMinneapolisQuitsRateFetcher,
)
from openbb_federal_reserve.models.regional.minneapolis_unemployment import (
    FederalReserveMinneapolisUnemploymentData,
    FederalReserveMinneapolisUnemploymentFetcher,
)

_PRICES = (
    "Date,Benefits,Input prices,Sales prices,Wages\n"
    "Apr 2026,13.0,50.0,30.0,32.0\n"
    "May 2026 (F),10.4,49.1,32.0,24.7\n"
)
_PERFORMANCE = (
    "month,Investment,Headcount,Hiring,Inventories,Profits,Sales\n"
    "Apr 2026,15.7,13.4,16.3,-6.2,-17.5,7.5\n"
    "May 2026 (F),10.7,10.0,6.1,-4.7,-1.1,20.3\n"
)
_EMPLOYMENT = (
    "Date,MN,MT,ND,SD,WI,US\n"
    "Apr 2026,102.3,108.9,101.9,106.9,101.3,105.8\n"
    "May 2026,,,,,,105.9\n"
)
_UNEMPLOYMENT = (
    "Date,MN,MT,ND,SD,WI,US\nApr 2026,4.5,3.5,2.4,2.2,3.5,4.3\nMay 2026,-,-,-,-,-,4.3\n"
)
_LABOR_FORCE = (
    "Date,MN,MT,ND,SD,WI,US\n"
    "Apr 2026,67.4,61.8,69.9,67.4,64.4,61.8\n"
    "May 2026,-,-,-,-,-,61.8\n"
)
_QUITS = (
    "Date,MN,MT,ND,SD,WI,US\n"
    "Nov 2025,1.73,2.63,2.27,2.10,2.10,1.93\n"
    "Dec 2025,1.93,2.77,2.50,2.67,2.23,1.97\n"
)
_GDP = (
    "Period,US,MN,MT,ND,SD,WI\n"
    "Q3 2025,117.6,111.5,125.5,107.7,114.7,109.6\n"
    "Q4 2025,117.7,112.1,125.9,108.7,115.5,109.7\n"
)
_CPI_U = (
    "Date,US,West North Central,Mountain\n"
    "Apr 2026,3.78,4.20,3.61\n"
    "May 2026,4.17,5.30,3.55\n"
)
_CPI_CORE = (
    "Date,US,West North Central,Mountain\n"
    "Apr 2026,2.74,3.67,2.67\n"
    "May 2026,2.82,4.32,2.29\n"
)
_CPI_U_GAP = (
    "Date,US,West North Central,Mountain\nApr 2026,3.78,4.20,3.61\nMay 2026,,,\n"
)
_CPI_CORE_GAP = (
    "Date,US,West North Central,Mountain\nApr 2026,2.74,3.67,2.67\nMay 2026,,,\n"
)
_INITIAL = "Date,MN\n2026-05-16,3302\n2026-05-23,3757\n"
_CONTINUED = "Date,MN\n2026-05-09,37765\n2026-05-16,36410\n"


def _hiring(state: str) -> str:
    """Build a per-state hiring/job-opening CSV with one trailing blank month."""
    return (
        f"Date,{state} Job Opening Rate,{state} Hiring Rate\n"
        f"Jan 2026,5.0,4.3\n"
        f"Feb 2026,,\n"
    )


def _hiring_partial(state: str) -> str:
    """Build a per-state CSV whose trailing month has only the hiring rate."""
    return (
        f"Date,{state} Job Opening Rate,{state} Hiring Rate\n"
        f"Jan 2026,5.0,4.3\n"
        f"Feb 2026,,4.1\n"
    )


def _text_response(text: str) -> MagicMock:
    """Build a make_request response with the given text body."""
    response = MagicMock()
    response.text = text
    response.raise_for_status = MagicMock()
    return response


def _by_url(mapping: dict[str, str]):
    """Return a make_request stub dispatching on a substring of the URL."""

    def _request(url, *args, **kwargs):
        for needle, body in mapping.items():
            if needle in url:
                return _text_response(body)
        raise AssertionError(f"unexpected url {url}")

    return _request


class TestBusinessConditions:
    """Tests for the Business Conditions Survey fetcher."""

    def test_merges_prices_and_performance(self, monkeypatch):
        """The two CSVs merge on date, the flash suffix strips, and dates filter."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            _by_url(
                {
                    "business_conditions_prices": _PRICES,
                    "business_conditions_performance": _PERFORMANCE,
                }
            ),
        )
        query = FederalReserveMinneapolisBusinessConditionsFetcher.transform_query(
            {"start_date": "2026-05-01", "end_date": "2026-05-31"}
        )
        rows = FederalReserveMinneapolisBusinessConditionsFetcher.extract_data(
            query, None
        )
        result = FederalReserveMinneapolisBusinessConditionsFetcher.transform_data(
            query, rows
        )
        assert all(
            isinstance(r, FederalReserveMinneapolisBusinessConditionsData)
            for r in result
        )
        assert len(result) == 1
        assert result[0].date == date(2026, 5, 1)
        assert result[0].benefits == 10.4
        assert result[0].sales == 20.3
        assert result[0].is_flash is True

    def test_flags_flash_and_final_rows(self, monkeypatch):
        """The flash ``(F)`` month is flagged while the final month is not."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            _by_url(
                {
                    "business_conditions_prices": _PRICES,
                    "business_conditions_performance": _PERFORMANCE,
                }
            ),
        )
        query = FederalReserveMinneapolisBusinessConditionsFetcher.transform_query({})
        rows = FederalReserveMinneapolisBusinessConditionsFetcher.extract_data(
            query, None
        )
        result = FederalReserveMinneapolisBusinessConditionsFetcher.transform_data(
            query, rows
        )
        flags = {r.date: r.is_flash for r in result}
        assert flags[date(2026, 4, 1)] is False
        assert flags[date(2026, 5, 1)] is True

    def test_prices_period_column_named_month(self, monkeypatch):
        """The prices CSV parses when its period column is ``month``, not ``Date``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            _by_url(
                {
                    "business_conditions_prices": _PRICES.replace("Date,", "month,"),
                    "business_conditions_performance": _PERFORMANCE,
                }
            ),
        )
        query = FederalReserveMinneapolisBusinessConditionsFetcher.transform_query({})
        rows = FederalReserveMinneapolisBusinessConditionsFetcher.extract_data(
            query, None
        )
        result = FederalReserveMinneapolisBusinessConditionsFetcher.transform_data(
            query, rows
        )
        assert [(r.date, r.wages, r.sales, r.is_flash) for r in result] == [
            (date(2026, 4, 1), 32.0, 7.5, False),
            (date(2026, 5, 1), 24.7, 20.3, True),
        ]

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            _by_url(
                {
                    "business_conditions_prices": "",
                    "business_conditions_performance": _PERFORMANCE,
                }
            ),
        )
        query = FederalReserveMinneapolisBusinessConditionsFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveMinneapolisBusinessConditionsFetcher.extract_data(query, None)


class TestRegionalEmployment:
    """Tests for the regional employment fetcher."""

    def test_pivots_wide_and_filters_dates(self, monkeypatch):
        """The CSV stays wide with one column per geography and the date filter applies."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response(_EMPLOYMENT),
        )
        query = FederalReserveMinneapolisEmploymentFetcher.transform_query(
            {"start_date": "2026-04-01", "end_date": "2026-04-30"}
        )
        rows = FederalReserveMinneapolisEmploymentFetcher.extract_data(query, None)
        result = FederalReserveMinneapolisEmploymentFetcher.transform_data(query, rows)
        assert all(
            isinstance(r, FederalReserveMinneapolisEmploymentData) for r in result
        )
        assert len(result) == 1
        row = result[0].model_dump()
        assert result[0].date == date(2026, 4, 1)
        assert {"MN", "MT", "ND", "SD", "WI", "US"}.issubset(row)
        assert row["MN"] == 102.3
        assert row["US"] == 105.8

    def test_keeps_populated_drops_all_none(self, monkeypatch):
        """The blank month keeps only its populated US column."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response(_EMPLOYMENT),
        )
        query = FederalReserveMinneapolisEmploymentFetcher.transform_query(
            {"start_date": "2026-05-01"}
        )
        rows = FederalReserveMinneapolisEmploymentFetcher.extract_data(query, None)
        result = FederalReserveMinneapolisEmploymentFetcher.transform_data(query, rows)
        assert len(result) == 1
        row = result[0].model_dump()
        assert row["US"] == 105.9
        assert row["MN"] is None

    def test_all_none_raises(self, monkeypatch):
        """When every kept row is all-``None`` the transform raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response("Date,MN,MT,ND,SD,WI,US\nMay 2026,,,,,,\n"),
        )
        query = FederalReserveMinneapolisEmploymentFetcher.transform_query({})
        rows = FederalReserveMinneapolisEmploymentFetcher.extract_data(query, None)
        with pytest.raises(EmptyDataError):
            FederalReserveMinneapolisEmploymentFetcher.transform_data(query, rows)

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response(""),
        )
        query = FederalReserveMinneapolisEmploymentFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveMinneapolisEmploymentFetcher.extract_data(query, None)


class TestRegionalUnemployment:
    """Tests for the regional unemployment fetcher."""

    def test_keeps_populated_drops_dash_rows(self, monkeypatch):
        """The populated ``US`` month survives while the ``-`` columns are dropped."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response(_UNEMPLOYMENT),
        )
        query = FederalReserveMinneapolisUnemploymentFetcher.transform_query(
            {"start_date": "2026-05-01"}
        )
        rows = FederalReserveMinneapolisUnemploymentFetcher.extract_data(query, None)
        result = FederalReserveMinneapolisUnemploymentFetcher.transform_data(
            query, rows
        )
        assert all(
            isinstance(r, FederalReserveMinneapolisUnemploymentData) for r in result
        )
        assert len(result) == 1
        row = result[0].model_dump()
        assert result[0].date == date(2026, 5, 1)
        assert row["US"] == 4.3
        assert row["MN"] is None

    def test_all_none_raises(self, monkeypatch):
        """When every kept row is all-``None`` the transform raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response(
                "Date,MN,MT,ND,SD,WI,US\nMay 2026,-,-,-,-,-,-\n"
            ),
        )
        query = FederalReserveMinneapolisUnemploymentFetcher.transform_query({})
        rows = FederalReserveMinneapolisUnemploymentFetcher.extract_data(query, None)
        with pytest.raises(EmptyDataError):
            FederalReserveMinneapolisUnemploymentFetcher.transform_data(query, rows)

    def test_parses_value(self, monkeypatch):
        """A present value parses through the end_date filter."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response(_UNEMPLOYMENT),
        )
        query = FederalReserveMinneapolisUnemploymentFetcher.transform_query(
            {"end_date": "2026-04-30"}
        )
        rows = FederalReserveMinneapolisUnemploymentFetcher.extract_data(query, None)
        result = FederalReserveMinneapolisUnemploymentFetcher.transform_data(
            query, rows
        )
        assert len(result) == 1
        assert result[0].model_dump()["MN"] == 4.5

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response(""),
        )
        query = FederalReserveMinneapolisUnemploymentFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveMinneapolisUnemploymentFetcher.extract_data(query, None)


class TestLaborForceParticipation:
    """Tests for the labor force participation fetcher."""

    def test_parses_and_filters(self, monkeypatch):
        """The participation columns parse and the date filter applies."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response(_LABOR_FORCE),
        )
        query = FederalReserveMinneapolisLaborForceFetcher.transform_query(
            {"start_date": "2026-04-01", "end_date": "2026-04-30"}
        )
        rows = FederalReserveMinneapolisLaborForceFetcher.extract_data(query, None)
        result = FederalReserveMinneapolisLaborForceFetcher.transform_data(query, rows)
        assert all(
            isinstance(r, FederalReserveMinneapolisLaborForceData) for r in result
        )
        assert len(result) == 1
        assert result[0].model_dump()["MN"] == 67.4

    def test_keeps_populated_drops_dash_rows(self, monkeypatch):
        """The populated ``US`` month survives while the ``-`` columns are dropped."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response(_LABOR_FORCE),
        )
        query = FederalReserveMinneapolisLaborForceFetcher.transform_query(
            {"start_date": "2026-05-01"}
        )
        rows = FederalReserveMinneapolisLaborForceFetcher.extract_data(query, None)
        result = FederalReserveMinneapolisLaborForceFetcher.transform_data(query, rows)
        assert len(result) == 1
        row = result[0].model_dump()
        assert row["US"] == 61.8
        assert row["MN"] is None

    def test_all_none_raises(self, monkeypatch):
        """When every kept row is all-``None`` the transform raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response(
                "Date,MN,MT,ND,SD,WI,US\nMay 2026,-,-,-,-,-,-\n"
            ),
        )
        query = FederalReserveMinneapolisLaborForceFetcher.transform_query({})
        rows = FederalReserveMinneapolisLaborForceFetcher.extract_data(query, None)
        with pytest.raises(EmptyDataError):
            FederalReserveMinneapolisLaborForceFetcher.transform_data(query, rows)

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response(""),
        )
        query = FederalReserveMinneapolisLaborForceFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveMinneapolisLaborForceFetcher.extract_data(query, None)


class TestQuitsRate:
    """Tests for the quits rate fetcher."""

    def test_parses_and_filters(self, monkeypatch):
        """The quits columns parse and the date filters apply."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response(_QUITS),
        )
        query = FederalReserveMinneapolisQuitsRateFetcher.transform_query(
            {"start_date": "2025-12-01", "end_date": "2025-12-31"}
        )
        rows = FederalReserveMinneapolisQuitsRateFetcher.extract_data(query, None)
        result = FederalReserveMinneapolisQuitsRateFetcher.transform_data(query, rows)
        assert all(
            isinstance(r, FederalReserveMinneapolisQuitsRateData) for r in result
        )
        assert len(result) == 1
        row = result[0].model_dump()
        assert result[0].date == date(2025, 12, 1)
        assert row["MN"] == 1.93
        assert row["MT"] == 2.77

    def test_all_none_raises(self, monkeypatch):
        """When every kept row is all-``None`` the transform raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response("Date,MN,MT,ND,SD,WI,US\nMay 2026,,,,,,\n"),
        )
        query = FederalReserveMinneapolisQuitsRateFetcher.transform_query({})
        rows = FederalReserveMinneapolisQuitsRateFetcher.extract_data(query, None)
        with pytest.raises(EmptyDataError):
            FederalReserveMinneapolisQuitsRateFetcher.transform_data(query, rows)

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response(""),
        )
        query = FederalReserveMinneapolisQuitsRateFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveMinneapolisQuitsRateFetcher.extract_data(query, None)


class TestRegionalGdp:
    """Tests for the regional GDP fetcher."""

    def test_parses_quarter_labels(self, monkeypatch):
        """The ``Qn YYYY`` labels parse to quarter-start dates and filters apply."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response(_GDP),
        )
        query = FederalReserveMinneapolisGdpFetcher.transform_query(
            {"start_date": "2025-10-01"}
        )
        rows = FederalReserveMinneapolisGdpFetcher.extract_data(query, None)
        result = FederalReserveMinneapolisGdpFetcher.transform_data(query, rows)
        assert all(isinstance(r, FederalReserveMinneapolisGdpData) for r in result)
        assert len(result) == 1
        assert result[0].date == date(2025, 10, 1)
        assert result[0].model_dump()["US"] == 117.7

    def test_all_geographies_and_end_date(self, monkeypatch):
        """Every geography returns as its own column and end_date applies."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response(_GDP),
        )
        query = FederalReserveMinneapolisGdpFetcher.transform_query(
            {"end_date": "2025-09-30"}
        )
        rows = FederalReserveMinneapolisGdpFetcher.extract_data(query, None)
        result = FederalReserveMinneapolisGdpFetcher.transform_data(query, rows)
        assert len(result) == 1
        row = result[0].model_dump()
        assert result[0].date == date(2025, 7, 1)
        assert {"US", "MN", "MT", "ND", "SD", "WI"}.issubset(row)
        assert row["US"] == 117.6

    def test_all_none_raises(self, monkeypatch):
        """When every kept row is all-``None`` the transform raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response("Period,US,MN,MT,ND,SD,WI\nQ4 2025,,,,,,\n"),
        )
        query = FederalReserveMinneapolisGdpFetcher.transform_query({})
        rows = FederalReserveMinneapolisGdpFetcher.extract_data(query, None)
        with pytest.raises(EmptyDataError):
            FederalReserveMinneapolisGdpFetcher.transform_data(query, rows)

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response(""),
        )
        query = FederalReserveMinneapolisGdpFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveMinneapolisGdpFetcher.extract_data(query, None)


class TestRegionalCpi:
    """Tests for the regional CPI fetcher."""

    def test_pivots_measures_and_geographies(self, monkeypatch):
        """Both measures pivot to one column per measure and geography."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            _by_url({"CPI_U_less_food_energy": _CPI_CORE, "CPI_U": _CPI_U}),
        )
        query = FederalReserveMinneapolisCpiFetcher.transform_query(
            {"start_date": "2026-05-01"}
        )
        rows = FederalReserveMinneapolisCpiFetcher.extract_data(query, None)
        result = FederalReserveMinneapolisCpiFetcher.transform_data(query, rows)
        assert all(isinstance(r, FederalReserveMinneapolisCpiData) for r in result)
        assert len(result) == 1
        row = result[0].model_dump()
        assert result[0].date == date(2026, 5, 1)
        assert row["CPI-U West North Central"] == 5.30
        assert row["Core West North Central"] == 4.32
        assert row["CPI-U US"] == 4.17
        assert row["Core Mountain"] == 2.29

    def test_both_measures_and_end_date(self, monkeypatch):
        """Both measures and every geography return, end_date applies."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            _by_url({"CPI_U_less_food_energy": _CPI_CORE, "CPI_U": _CPI_U}),
        )
        query = FederalReserveMinneapolisCpiFetcher.transform_query(
            {"end_date": "2026-04-30"}
        )
        rows = FederalReserveMinneapolisCpiFetcher.extract_data(query, None)
        result = FederalReserveMinneapolisCpiFetcher.transform_data(query, rows)
        assert len(result) == 1
        row = result[0].model_dump()
        assert result[0].date == date(2026, 4, 1)
        for measure in ("CPI-U", "Core"):
            for geography in ("US", "West North Central", "Mountain"):
                assert f"{measure} {geography}" in row

    def test_keeps_populated_drops_blank_month(self, monkeypatch):
        """The populated month survives while the all-blank month is dropped."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            _by_url({"CPI_U_less_food_energy": _CPI_CORE_GAP, "CPI_U": _CPI_U_GAP}),
        )
        query = FederalReserveMinneapolisCpiFetcher.transform_query({})
        rows = FederalReserveMinneapolisCpiFetcher.extract_data(query, None)
        result = FederalReserveMinneapolisCpiFetcher.transform_data(query, rows)
        assert {r.date for r in result} == {date(2026, 4, 1)}

    def test_all_none_raises(self, monkeypatch):
        """When every kept row is all-``None`` the transform raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            _by_url({"CPI_U_less_food_energy": _CPI_CORE_GAP, "CPI_U": _CPI_U_GAP}),
        )
        query = FederalReserveMinneapolisCpiFetcher.transform_query(
            {"start_date": "2026-05-01"}
        )
        rows = FederalReserveMinneapolisCpiFetcher.extract_data(query, None)
        with pytest.raises(EmptyDataError):
            FederalReserveMinneapolisCpiFetcher.transform_data(query, rows)

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            _by_url({"CPI_U_less_food_energy": _CPI_CORE, "CPI_U": ""}),
        )
        query = FederalReserveMinneapolisCpiFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveMinneapolisCpiFetcher.extract_data(query, None)


class TestUnemploymentClaims:
    """Tests for the unemployment claims fetcher."""

    def test_merges_initial_and_continued(self, monkeypatch):
        """The two weekly series merge on date and integer values cast cleanly."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            _by_url({"mn_initial": _INITIAL, "mn_continued": _CONTINUED}),
        )
        query = FederalReserveMinneapolisClaimsFetcher.transform_query(
            {"start_date": "2026-05-16", "end_date": "2026-05-16"}
        )
        rows = FederalReserveMinneapolisClaimsFetcher.extract_data(query, None)
        result = FederalReserveMinneapolisClaimsFetcher.transform_data(query, rows)
        assert all(isinstance(r, FederalReserveMinneapolisClaimsData) for r in result)
        assert len(result) == 1
        assert result[0].date == date(2026, 5, 16)
        assert result[0].initial_claims == 3302
        assert result[0].continued_claims == 36410

    def test_outer_join_leaves_gaps(self, monkeypatch):
        """A week present in only one series leaves the other as ``None``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            _by_url({"mn_initial": _INITIAL, "mn_continued": _CONTINUED}),
        )
        query = FederalReserveMinneapolisClaimsFetcher.transform_query(
            {"start_date": "2026-05-23"}
        )
        rows = FederalReserveMinneapolisClaimsFetcher.extract_data(query, None)
        result = FederalReserveMinneapolisClaimsFetcher.transform_data(query, rows)
        assert len(result) == 1
        assert result[0].initial_claims == 3757
        assert result[0].continued_claims is None

    def test_empty_raises(self, monkeypatch):
        """An empty response raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            _by_url({"mn_initial": "", "mn_continued": _CONTINUED}),
        )
        query = FederalReserveMinneapolisClaimsFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveMinneapolisClaimsFetcher.extract_data(query, None)


class TestJobOpeningsHiring:
    """Tests for the job openings and hiring fetcher."""

    def test_state_url(self):
        """The per-state URL helper lower-cases the state code."""
        assert _state_url("MN").endswith("/hiring_job_mn.csv")

    def test_merges_states_into_columns(self, monkeypatch):
        """The per-state CSVs merge into one column per state metric on date."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            _by_url(
                {
                    "hiring_job_mn": _hiring("MN"),
                    "hiring_job_mt": _hiring("MT"),
                    "hiring_job_nd": _hiring("ND"),
                    "hiring_job_sd": _hiring("SD"),
                    "hiring_job_wi": _hiring("WI"),
                }
            ),
        )
        query = FederalReserveMinneapolisJobOpeningsFetcher.transform_query(
            {"start_date": "2026-01-01", "end_date": "2026-01-31"}
        )
        rows = FederalReserveMinneapolisJobOpeningsFetcher.extract_data(query, None)
        result = FederalReserveMinneapolisJobOpeningsFetcher.transform_data(query, rows)
        assert all(
            isinstance(r, FederalReserveMinneapolisJobOpeningsData) for r in result
        )
        assert len(result) == 1
        row = result[0].model_dump()
        assert result[0].date == date(2026, 1, 1)
        assert row["MN Job Opening Rate"] == 5.0
        assert row["MN Hiring Rate"] == 4.3
        assert row["WI Job Opening Rate"] == 5.0

    def test_skips_blank_state_and_keeps_partial_row(self, monkeypatch):
        """A blank state response is skipped and a partially-populated month is kept."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            _by_url(
                {
                    "hiring_job_mn": _hiring_partial("MN"),
                    "hiring_job_mt": "",
                    "hiring_job_nd": "",
                    "hiring_job_sd": "",
                    "hiring_job_wi": "",
                }
            ),
        )
        query = FederalReserveMinneapolisJobOpeningsFetcher.transform_query(
            {"start_date": "2026-02-01"}
        )
        rows = FederalReserveMinneapolisJobOpeningsFetcher.extract_data(query, None)
        result = FederalReserveMinneapolisJobOpeningsFetcher.transform_data(query, rows)
        assert len(result) == 1
        row = result[0].model_dump()
        assert row["MN Job Opening Rate"] is None
        assert row["MN Hiring Rate"] == 4.1

    def test_skips_missing_metric_column(self, monkeypatch):
        """A state CSV missing one metric column contributes only the present one."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            _by_url(
                {
                    "hiring_job_mn": "Date,MN Job Opening Rate\nJan 2026,5.0\n",
                    "hiring_job_mt": "",
                    "hiring_job_nd": "",
                    "hiring_job_sd": "",
                    "hiring_job_wi": "",
                }
            ),
        )
        query = FederalReserveMinneapolisJobOpeningsFetcher.transform_query({})
        rows = FederalReserveMinneapolisJobOpeningsFetcher.extract_data(query, None)
        result = FederalReserveMinneapolisJobOpeningsFetcher.transform_data(query, rows)
        assert len(result) == 1
        row = result[0].model_dump()
        assert row["MN Job Opening Rate"] == 5.0
        assert "MN Hiring Rate" not in row

    def test_all_none_row_dropped_and_raises(self, monkeypatch):
        """A month with both rates blank is dropped, raising when none remain."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            _by_url(
                {
                    "hiring_job_mn": _hiring("MN"),
                    "hiring_job_mt": "",
                    "hiring_job_nd": "",
                    "hiring_job_sd": "",
                    "hiring_job_wi": "",
                }
            ),
        )
        query = FederalReserveMinneapolisJobOpeningsFetcher.transform_query(
            {"start_date": "2026-02-01"}
        )
        rows = FederalReserveMinneapolisJobOpeningsFetcher.extract_data(query, None)
        with pytest.raises(EmptyDataError):
            FederalReserveMinneapolisJobOpeningsFetcher.transform_data(query, rows)

    def test_empty_raises(self, monkeypatch):
        """When every state response is empty the fetcher raises ``EmptyDataError``."""
        monkeypatch.setattr(
            "openbb_core.provider.utils.helpers.make_request",
            lambda *a, **k: _text_response(""),
        )
        query = FederalReserveMinneapolisJobOpeningsFetcher.transform_query({})
        with pytest.raises(EmptyDataError):
            FederalReserveMinneapolisJobOpeningsFetcher.extract_data(query, None)
