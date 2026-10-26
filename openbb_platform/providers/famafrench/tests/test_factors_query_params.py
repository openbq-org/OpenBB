"""Tests for Fama-French factor query parameters."""

import asyncio
from datetime import date

import pandas as pd
import pytest
from openbb_famafrench.models.factors import (
    FamaFrenchFactorsFetcher,
    FamaFrenchFactorsQueryParams,
)
from pydantic import ValidationError


def test_factors_query_params_defaults():
    """Default parameters should describe the US monthly three-factor dataset."""
    params = FamaFrenchFactorsQueryParams()

    assert params.region == "america"
    assert params.factor == "3_factors"
    assert params.frequency == "monthly"
    assert params.start_date is None
    assert params.end_date is None


def test_factors_query_params_accept_valid_regional_frequency():
    """A frequency available for the selected regional factor should validate."""
    params = FamaFrenchFactorsQueryParams(
        region="europe", factor="momentum", frequency="annual"
    )

    assert params.region == "europe"
    assert params.factor == "momentum"
    assert params.frequency == "annual"


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        (
            {"region": "antarctica"},
            "Invalid region: 'antarctica'",
        ),
        (
            {"factor": "profitability"},
            "Invalid factor:",
        ),
        (
            {"region": "europe", "factor": "st_reversal"},
            "Invalid factor: 'ST_Reversal'",
        ),
        (
            {"region": "europe", "factor": "momentum", "frequency": "weekly"},
            "Invalid frequency: 'weekly'",
        ),
    ],
)
def test_factors_query_params_reject_invalid_combinations(parameters, message):
    """Unsupported region, factor, and frequency combinations should fail."""
    with pytest.raises(ValidationError, match=message):
        FamaFrenchFactorsQueryParams(**parameters)


def test_factors_fetcher_transforms_query():
    """Fetcher query transformation should apply model defaults and validation."""
    params = FamaFrenchFactorsFetcher.transform_query({"factor": "momentum"})

    assert params == FamaFrenchFactorsQueryParams(factor="momentum")


def test_factors_fetcher_selects_dataset(monkeypatch):
    """Extraction should map query values to the correct library dataset."""
    expected = (("table",), ("metadata",))

    def get_portfolio_data(dataset, frequency):
        assert dataset == "Europe_Mom_Factor"
        assert frequency == "annual"
        return expected

    monkeypatch.setattr(
        "openbb_famafrench.utils.helpers.get_portfolio_data", get_portfolio_data
    )
    query = FamaFrenchFactorsQueryParams(
        region="europe", factor="momentum", frequency="annual"
    )

    result = asyncio.run(FamaFrenchFactorsFetcher.aextract_data(query, None))

    assert result == expected


def test_factors_fetcher_transforms_and_filters_data():
    """Transformation should filter dates and create aliased factor models."""
    table = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2023-01-01", "2023-02-01", "2023-03-01"]),
            "Mkt-RF": [0.01, 0.02, 0.03],
            "SMB": [0.001, 0.002, 0.003],
            "HML": [0.004, 0.005, 0.006],
            "RF": [0.0001, 0.0002, 0.0003],
        }
    ).set_index("Date")
    query = FamaFrenchFactorsQueryParams(
        start_date=date(2023, 2, 1), end_date=date(2023, 2, 28)
    )

    result = FamaFrenchFactorsFetcher.transform_data(
        query, ([table], [{"source": "fixture"}])
    )

    assert result.metadata == {"source": "fixture"}
    assert len(result.result) == 1
    assert result.result[0].date == date(2023, 2, 1)
    assert result.result[0].mkt_rf == pytest.approx(0.02)