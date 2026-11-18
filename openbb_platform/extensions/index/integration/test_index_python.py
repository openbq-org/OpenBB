"""Test economy extension."""

import pytest
from openbb_core.app.model.obbject import OBBject


@pytest.fixture(scope="session")
def obb(pytestconfig):
    """Fixture to setup obb."""

    if pytestconfig.getoption("markexpr") != "not integration":
        import openbb

        return openbb.obb

    pytest.skip("Integration tests are not enabled.")


@pytest.mark.parametrize(
    "params",
    [
        ({"symbol": "dowjones", "provider": "fmp"}),
        ({"symbol": "BUK100P", "provider": "cboe"}),
        ({"symbol": "^TX60", "provider": "tmx", "use_cache": False}),
    ],
)
@pytest.mark.integration
def test_index_constituents(params, obb):
    """Test the index constituents endpoint."""
    result = obb.index.constituents(**params)
    assert result
    assert isinstance(result, OBBject)
    assert len(result.results) > 0


@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "interval": "1d",
                "provider": "cboe",
                "symbol": "AAVE100",
                "start_date": "2023-01-01",
                "end_date": "2023-06-06",
                "use_cache": False,
            }
        ),
        (
            {
                "interval": "1d",
                "provider": "fmp",
                "symbol": "^DJI",
                "start_date": "2024-01-01",
                "end_date": "2024-02-05",
            }
        ),
        (
            {
                "interval": "1h",
                "provider": "fmp",
                "symbol": "^DJI,^NDX",
                "start_date": None,
                "end_date": None,
            }
        ),
        (
            {
                "interval": "1d",
                "provider": "yfinance",
                "symbol": "DJI",
                "start_date": "2023-01-01",
                "end_date": "2023-06-06",
            }
        ),
        (
            {
                "provider": "intrinio",
                "start_date": "2023-01-01",
                "end_date": "2023-06-06",
                "symbol": "DJI",
                "limit": 100,
            }
        ),
    ],
)
@pytest.mark.integration
def test_index_price_historical(params, obb):
    """Test the index historical price endpoint."""
    result = obb.index.price.historical(**params)
    assert result
    assert isinstance(result, OBBject)
    assert len(result.results) > 0


@pytest.mark.parametrize(
    "params",
    [
        ({}),
        ({"provider": "cboe", "use_cache": False}),
        ({"provider": "fmp"}),
        ({"provider": "yfinance"}),
        ({"provider": "tmx", "use_cache": False}),
    ],
)
@pytest.mark.integration
def test_index_available(params, obb):
    """Test the index available endpoint."""
    result = obb.index.available(**params)
    assert result
    assert isinstance(result, OBBject)
    assert len(result.results) > 0


@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "query": "D",
                "is_symbol": True,
                "provider": "cboe",
                "use_cache": False,
            }
        ),
    ],
)
@pytest.mark.integration
def test_index_search(params, obb):
    """Test the index search endpoint."""
    result = obb.index.search(**params)
    assert result
    assert isinstance(result, OBBject)
    assert len(result.results) > 0


@pytest.mark.parametrize(
    "params",
    [
        ({"region": "us", "provider": "cboe"}),
        ({"provider": "tmx", "region": "ca", "use_cache": False}),
    ],
)
@pytest.mark.integration
def test_index_snapshots(params, obb):
    """Test the index snapshots endpoint."""
    result = obb.index.snapshots(**params)
    assert result
    assert isinstance(result, OBBject)
    assert len(result.results) > 0


@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "series_name": "pe_month",
                "start_date": None,
                "end_date": None,
                "provider": "multpl",
            }
        ),
    ],
)
@pytest.mark.integration
def test_index_sp500_multiples(params, obb):
    """Test the index sp500 multiples endpoint."""
    result = obb.index.sp500_multiples(**params)
    assert result
    assert isinstance(result, OBBject)
    assert len(result.results) > 0


@pytest.mark.parametrize(
    "params",
    [
        ({"symbol": "^TX60", "provider": "tmx"}),
    ],
)
@pytest.mark.integration
def test_index_sectors(params, obb):
    """Test the index sectors endpoint."""
    result = obb.index.sectors(**params)
    assert result
    assert isinstance(result, OBBject)
    assert len(result.results) > 0
