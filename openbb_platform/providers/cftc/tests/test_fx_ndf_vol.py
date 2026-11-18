import asyncio
from datetime import date, timedelta
from math import exp

import pytest
from openbb_core.app.model.abstract.error import OpenBBError

from openbb_cftc.models.fx_implied_vol import (
    CftcFxImpliedVolData,
    CftcFxImpliedVolFetcher,
    CftcFxImpliedVolQueryParams,
)
from openbb_cftc.utils import fx_vol
from openbb_cftc.utils.fx_theory import garman_kohlhagen

AS_OF = date(2026, 7, 17)
SPOT0 = 96.0
R_DOM = 0.10
R_FOR = 0.04


def _df_base(years):
    return exp(-R_FOR * years)


@pytest.mark.parametrize(
    ("pair", "expected"),
    [("USDBRL", True), ("usdinr", True), ("EURUSD", False), ("ZZZZZZ", False)],
)
def test_is_ndf_vol_pair(pair, expected):
    assert fx_vol.is_ndf_vol_pair(pair) is expected


def test_snap_moneyness_snaps_within_the_band_only():
    assert fx_vol._snap_moneyness(120.0) == 100
    assert fx_vol._snap_moneyness(-260.0) == -300
    assert fx_vol._snap_moneyness(2_000.0) is None


def test_grid_offset_and_strike_helpers_switch_on_moneyness():
    assert fx_vol._grid_offsets(True) == fx_vol._MONEYNESS_OFFSETS
    assert fx_vol._grid_offsets(False) == fx_vol._STRIKE_OFFSETS

    assert fx_vol._offset_strike(100, 1.10, 10_000.0, False) == pytest.approx(1.11)
    assert fx_vol._snap_strike(1.11, 1.10, 10_000.0, False) == 100

    assert fx_vol._offset_strike(200, 96.0, 10_000.0, True) == pytest.approx(97.92)
    assert fx_vol._snap_strike(97.92, 96.0, 10_000.0, True) == 200


def _ndf_fwd(days, notional=5_000_000.0):
    rate = SPOT0 * exp((R_DOM - R_FOR) * days / 365.0)
    return {
        "UPI FISN": "NA/Fwd NDF INR USD",
        "UPI Underlier Name": "INR USD",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Execution Timestamp": f"{AS_OF.isoformat()}T10:00:00Z",
        "Expiration Date": (AS_OF + timedelta(days=days)).isoformat(),
        "Notional amount-Leg 1": f"{notional:.0f}",
        "Notional currency-Leg 1": "USD",
        "Notional amount-Leg 2": f"{notional * rate:.0f}",
        "Notional currency-Leg 2": "INR",
    }


def test_ndf_forward_curve_spot_and_interpolation():
    spot, forward = fx_vol.ndf_forward_curve(
        [_ndf_fwd(7), _ndf_fwd(30), _ndf_fwd(90)], "USDINR", AS_OF
    )

    assert spot == pytest.approx(SPOT0 * exp(0.06 * 7 / 365.0), abs=1e-3)
    assert forward(1 / 365.0) == pytest.approx(SPOT0 * exp(0.06 * 7 / 365.0), abs=1e-3)
    assert forward(2.0) == pytest.approx(SPOT0 * exp(0.06 * 90 / 365.0), abs=1e-3)
    mid = forward(60 / 365.0)
    assert SPOT0 * exp(0.06 * 30 / 365.0) < mid < SPOT0 * exp(0.06 * 90 / 365.0)


def test_ndf_forward_curve_empty_and_short_end_fallback():
    assert fx_vol.ndf_forward_curve([], "USDINR", AS_OF) == (None, None)

    spot, _ = fx_vol.ndf_forward_curve([_ndf_fwd(14), _ndf_fwd(30)], "USDINR", AS_OF)
    assert spot == pytest.approx(SPOT0 * exp(0.06 * 14 / 365.0), abs=1e-3)


def test_implied_df_inverts_the_forward():
    spot, forward = fx_vol.ndf_forward_curve(
        [_ndf_fwd(7), _ndf_fwd(90)], "USDINR", AS_OF
    )
    df_quote = fx_vol.implied_df(_df_base, spot, forward)
    years = 90 / 365.0

    assert spot * _df_base(years) / df_quote(years) == pytest.approx(forward(years))


def _ndo(days, strike, vol, is_call_usd, notional=5_000_000.0):
    years = days / 365.0
    gk = garman_kohlhagen(SPOT0, strike, years, R_DOM, R_FOR, vol, is_call_usd)
    premium_usd = gk * notional / SPOT0
    label = "Call" if is_call_usd else "Put"
    record = {
        "UPI FISN": f"NA/O NDO {label} INR USD",
        "UPI Underlier Name": "INR USD",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Execution Timestamp": f"{AS_OF.isoformat()}T10:00:00Z",
        "Expiration Date": (AS_OF + timedelta(days=days)).isoformat(),
        "Strike Price": f"{strike}",
        "Strike price currency/currency pair": "USD/INR",
        "Option Premium Amount": f"{premium_usd:.4f}",
        "Option Premium Currency": "USD",
        "Notional amount-Leg 1": f"{notional:.0f}",
        "Notional currency-Leg 1": "USD",
        "Notional amount-Leg 2": f"{notional * strike:.0f}",
        "Notional currency-Leg 2": "INR",
    }
    usd_amount, inr_amount = f"{notional:.0f}", f"{notional * strike:.0f}"

    if is_call_usd:
        record.update(
            {
                "Call currency": "USD",
                "Call amount": usd_amount,
                "Put currency": "INR",
                "Put amount": inr_amount,
            }
        )
    else:
        record.update(
            {
                "Put currency": "USD",
                "Put amount": usd_amount,
                "Call currency": "INR",
                "Call amount": inr_amount,
            }
        )

    return record


def test_extract_and_price_ndo_options():
    records = [_ndo(30, 98.0, 0.10, True), _ndo(90, 94.0, 0.09, False)]
    spot, forward = fx_vol.ndf_forward_curve(
        [_ndf_fwd(7), _ndf_fwd(90)], "USDINR", AS_OF
    )
    options = fx_vol.extract_vanilla_options(
        records, "USD", "INR", AS_OF, spot, "NA/O NDO "
    )
    priced = fx_vol.price_options(
        options, spot, fx_vol.implied_df(_df_base, spot, forward), _df_base
    )

    assert len(options) == 2
    assert fx_vol.has_vanilla_options(records, "USD", "INR", "NA/O NDO ")
    assert not fx_vol.has_vanilla_options(records, "USD", "INR")
    assert all(0.05 < p["implied_vol"] < 0.15 for p in priced)


def _priced_at(tenor_days, vol, strike):
    return {"tenor_days": tenor_days, "implied_vol": vol, "strike": strike}


def test_vol_surface_moneyness_grid():
    spot = 96.0
    priced = [
        _priced_at(90, 0.06, spot),
        _priced_at(90, 0.07, spot * 1.02),
        _priced_at(90, 0.075, spot * 0.98),
    ]
    rows = {
        r["strike_offset"]: r
        for r in fx_vol.vol_surface(priced, spot, 10_000.0, moneyness=True)
    }

    assert set(rows) == {-200.0, 0.0, 200.0}
    assert rows[200.0]["strike"] == pytest.approx(spot * 1.02, abs=1e-2)
    assert rows[0.0]["vol_3m"] == pytest.approx(0.06)


def test_theoretical_surface_moneyness_grid():
    spot, forward = fx_vol.ndf_forward_curve([_ndf_fwd(90)], "USDINR", AS_OF)
    df_quote = fx_vol.implied_df(_df_base, spot, forward)
    fwd = spot * _df_base(90 / 365.0) / df_quote(90 / 365.0)
    priced = [
        _priced_at(90, vol, strike)
        for strike, vol in (
            (fwd * 0.96, 0.11),
            (fwd * 0.98, 0.095),
            (fwd, 0.09),
            (fwd * 1.02, 0.093),
            (fwd * 1.04, 0.10),
        )
    ]
    rows, fits = fx_vol.theoretical_surface(
        priced, spot, df_quote, _df_base, 10_000.0, moneyness=True
    )

    assert "3M" in fits
    offsets = {r["strike_offset"] for r in rows}
    assert offsets == {float(o) for o in fx_vol._MONEYNESS_OFFSETS}


def _ndf_forex():
    forex = [_ndf_fwd(days) for days in (4, 15, 30, 60, 90, 180)]

    for days in (30, 90):
        for strike in (92.0, 94.0, 95.0):
            forex.append(_ndo(days, strike, 0.10, is_call_usd=False))
        for strike in (98.0, 100.0, 102.0):
            forex.append(_ndo(days, strike, 0.10, is_call_usd=True))

    return forex


@pytest.fixture(name="flat_usd_ois")
def flat_usd_ois_fixture(monkeypatch):
    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.rate_discount_factor",
        lambda records, currency, trade_date, min_trades, forward_aware=False: _df_base,
    )


def test_fx_implied_vol_ndf_empirical(flat_usd_ois):
    query = CftcFxImpliedVolQueryParams(pair="USDINR", basis="empirical")
    result = CftcFxImpliedVolFetcher.transform_data(
        query, (_ndf_forex(), [], AS_OF.isoformat(), AS_OF.isoformat())
    )

    assert result.metadata["pair"] == "USDINR"
    assert result.metadata["options_priced"] > 0
    assert all(isinstance(r, CftcFxImpliedVolData) for r in result.result)
    grid = {float(o) for o in fx_vol._MONEYNESS_OFFSETS}
    assert all(r.strike_offset in grid for r in result.result)


def test_fx_implied_vol_ndf_theoretical(flat_usd_ois):
    query = CftcFxImpliedVolQueryParams(pair="USDINR", basis="theoretical")
    result = CftcFxImpliedVolFetcher.transform_data(
        query, (_ndf_forex(), [], AS_OF.isoformat(), AS_OF.isoformat())
    )

    assert result.metadata["sabr_fits"]
    assert len(result.result) == len(fx_vol._MONEYNESS_OFFSETS)


def test_fx_implied_vol_transform_query():
    assert isinstance(
        CftcFxImpliedVolFetcher.transform_query({"pair": "USDINR"}),
        CftcFxImpliedVolQueryParams,
    )


def test_fx_implied_vol_ndf_raises_without_spot():
    query = CftcFxImpliedVolQueryParams(pair="USDINR")

    with pytest.raises(OpenBBError, match="No spot could be established"):
        CftcFxImpliedVolFetcher.transform_data(
            query, ([], [], AS_OF.isoformat(), AS_OF.isoformat())
        )


def test_fx_implied_vol_ndf_aextract(monkeypatch):
    forex = _ndf_forex()
    seen_currencies = []

    async def _dates(asset_class):
        return ["2026-07-16", "2026-07-17"]

    async def _slice(asset_class, report_date, use_cache=True):
        return forex

    async def _rates(report_date, currencies, use_cache=True):
        seen_currencies.append(currencies)
        return [], report_date

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_available_dates", _dates)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _slice)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)

    query = CftcFxImpliedVolQueryParams(pair="USDINR")
    forex_out, rates, report_date, rates_date = asyncio.run(
        CftcFxImpliedVolFetcher.aextract_data(query, None)
    )

    assert report_date == "2026-07-17"
    assert seen_currencies == [["USD"]]
