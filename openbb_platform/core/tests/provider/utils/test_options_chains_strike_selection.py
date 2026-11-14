"""Regression tests for option strike selection across different expirations."""

from datetime import date

import pytest

from openbb_core.provider.standard_models.options_chains import OptionsChainsData


@pytest.fixture
def chain_with_different_strikes():
    """Build a chain whose expirations offer different strike prices."""
    rows = []
    for expiration, strikes in (
        (date(2030, 1, 15), (90.0, 100.0, 110.0)),
        (date(2030, 2, 15), (95.0, 105.0)),
    ):
        for strike in strikes:
            for option_type in ("call", "put"):
                intrinsic = (
                    max(100.0 - strike, 0.0)
                    if option_type == "call"
                    else max(strike - 100.0, 0.0)
                )
                bid = intrinsic + (4.0 if strike == 100.0 else 1.0)
                rows.append(
                    {
                        "contract_symbol": (
                            f"FAKE{expiration:%y%m%d}{option_type[0]}{strike}"
                        ),
                        "underlying_symbol": "FAKE",
                        "underlying_price": 100.0,
                        "eod_date": date(2030, 1, 1),
                        "expiration": expiration,
                        "strike": strike,
                        "option_type": option_type,
                        "bid": bid,
                        "ask": bid + 0.1,
                    }
                )
    return OptionsChainsData(**{key: [row[key] for row in rows] for key in rows[0]})


@pytest.mark.requires_pandas
@pytest.mark.parametrize("expiration", ["2030-01-15", 14])
def test_otm_strikes_use_selected_expiration(chain_with_different_strikes, expiration):
    """A target near another expiration's strike must use the selected chain."""
    result = chain_with_different_strikes._get_nearest_otm_strikes(
        date=expiration, moneyness=5.2
    )

    assert result == {"call": 110.0, "put": 90.0}


@pytest.mark.requires_pandas
@pytest.mark.parametrize("expiration", ["2030-02-15", 45])
def test_otm_strikes_ignore_other_expirations_at_the_money(
    chain_with_different_strikes, expiration
):
    """An ATM strike from January must not be selected for February."""
    result = chain_with_different_strikes._get_nearest_otm_strikes(
        date=expiration, moneyness=1.0
    )

    assert result == {"call": 105.0, "put": 95.0}


@pytest.mark.requires_pandas
def test_otm_strikes_without_expiration_use_full_chain(chain_with_different_strikes):
    """Without an expiration filter, all listed strikes remain available."""
    result = chain_with_different_strikes._get_nearest_otm_strikes(moneyness=5.2)

    assert result == {"call": 105.0, "put": 95.0}


@pytest.mark.requires_pandas
@pytest.mark.parametrize("moneyness,expected_cost", [(5.2, 2.2), (-5.2, -2.0)])
def test_strangle_cost_uses_selected_expiration_strikes(
    chain_with_different_strikes, moneyness, expected_cost
):
    """Both long and short strangles must price the intended expiration's legs."""
    result = chain_with_different_strikes.strangle(days=14, moneyness=moneyness).iloc[
        :, 0
    ]

    assert result["Expiration"] == "2030-01-15"
    assert result["Strike 1"] == 110.0
    assert result["Strike 2"] == 90.0
    assert result["Cost"] == pytest.approx(expected_cost)
