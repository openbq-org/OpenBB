from datetime import date
from math import exp

import pytest
from openbb_core.app.model.abstract.error import OpenBBError

from openbb_cftc.utils import fx_vol
from openbb_cftc.utils.fx_theory import garman_kohlhagen

AS_OF = date(2026, 7, 15)
SPOT = 1.10
PIP = 10_000.0


def _df_quote(years):
    return exp(-0.04 * years)


def _df_base(years):
    return exp(-0.02 * years)


def _forward(base, quote, n_base, n_quote, effective, leg1_base=True):
    return {
        "UPI FISN": f"NA/Fwd {base} {quote}",
        "Action type": "NEWT",
        "Effective Date": effective,
        "Notional amount-Leg 1": f"{n_base if leg1_base else n_quote}",
        "Notional currency-Leg 1": base if leg1_base else quote,
        "Notional amount-Leg 2": f"{n_quote if leg1_base else n_base}",
        "Notional currency-Leg 2": quote if leg1_base else base,
    }


def _option(fisn, strike, premium, premium_ccy, expiration, n_base, n_quote, base):
    legs = fisn.split()
    call_ccy = legs[3] if legs[2] == "Call" else legs[4]
    put_ccy = legs[4] if legs[2] == "Call" else legs[3]
    return {
        "UPI FISN": fisn,
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Execution Timestamp": f"{AS_OF.isoformat()}T10:00:00Z",
        "Strike Price": f"{strike}",
        "Strike price currency/currency pair": f"{legs[3]}/{legs[4]}",
        "Call currency": call_ccy,
        "Call amount": f"{n_base if call_ccy == base else n_quote}",
        "Put currency": put_ccy,
        "Put amount": f"{n_base if put_ccy == base else n_quote}",
        "Option Premium Amount": f"{premium}",
        "Option Premium Currency": premium_ccy,
        "Expiration Date": expiration,
        "Notional amount-Leg 1": f"{n_base}",
        "Notional currency-Leg 1": base,
        "Notional amount-Leg 2": f"{n_quote}",
        "Notional currency-Leg 2": ("USD" if base == "EUR" else "EUR"),
    }


def _priced_option(strike, tenor_days, vol, is_call, base="EUR", quote="USD"):
    fisn = f"NA/O Van {'Call' if is_call else 'Put'} {base} {quote}"
    years = tenor_days / 365.0
    per_unit = garman_kohlhagen(SPOT, strike, years, 0.04, 0.02, vol, is_call)
    notional = 10_000_000.0
    expiration = (AS_OF + __import__("datetime").timedelta(days=tenor_days)).isoformat()
    return _option(
        fisn,
        strike,
        per_unit * notional,
        quote,
        expiration,
        notional,
        notional * SPOT,
        base,
    )


def test_resolve_major_pair():
    assert fx_vol.resolve_major_pair("eurusd") == ("EUR", "USD", 10_000.0)
    assert fx_vol.resolve_major_pair("USDJPY")[2] == 100.0

    with pytest.raises(OpenBBError, match="Invalid pair"):
        fx_vol.resolve_major_pair("XAUUSD")


def test_fx_spot_from_shortest_dated_trades():
    non_newt = _forward("EUR", "USD", 1_000_000, 9_999_999, "2026-07-16")
    non_newt["Action type"] = "CORR"
    ndf = _forward("EUR", "USD", 1_000_000, 2_000_000, "2026-07-16")
    ndf["UPI FISN"] = "NA/Fwd NDF EUR USD"
    volvar = _forward("EUR", "USD", 1_000_000, 3_000_000, "2026-07-16")
    volvar["UPI FISN"] = "NA/Fwd VolVar EUR USD"
    records = [
        _forward("EUR", "USD", 1_000_000, 1_100_000, "2026-07-16"),
        _forward("EUR", "USD", 2_000_000, 2_204_000, "2026-07-17", leg1_base=False),
        _forward("EUR", "USD", 1_000_000, 1_200_000, "2026-09-01"),
        _forward("GBP", "USD", 1_000_000, 1_300_000, "2026-07-16"),
        {"UPI FISN": "NA/O Van Call EUR USD", "Action type": "NEWT"},
        non_newt,
        ndf,
        volvar,
    ]
    spot = fx_vol.fx_spot(records, "EUR", "USD", AS_OF)

    assert spot == pytest.approx(1.101, abs=1e-6)
    assert fx_vol.fx_spot([], "EUR", "USD", AS_OF) is None
    assert fx_vol.fx_spot([], "USD", "JPY", AS_OF) is None


def test_fx_spot_triangulates_a_cross_through_usd():
    ndf = _forward("CAD", "EUR", 1_000_000, 1_540_000, "2026-07-16")
    ndf["UPI FISN"] = "NA/Fwd NDF CAD EUR"
    eur_usd = _forward("EUR", "USD", 1_000_000, 1_100_000, "2026-07-16")
    cad_usd = _forward("CAD", "USD", 1_400_000, 1_000_000, "2026-07-16")

    spot = fx_vol.fx_spot([ndf, eur_usd, cad_usd], "EUR", "CAD", AS_OF)
    assert spot == pytest.approx(1.10 * 1.40, abs=1e-6)

    assert fx_vol.fx_spot([eur_usd], "EUR", "CAD", AS_OF) is None


def test_fx_spot_leaves_out_prints_below_a_notional_floor():
    records = [
        _forward("EUR", "USD", 500, 600, "2026-07-16"),
        _forward("EUR", "USD", 1_000_000, 1_100_000, "2026-07-16"),
    ]

    assert fx_vol.fx_spot(records, "EUR", "USD", AS_OF) == pytest.approx(1.15)
    assert fx_vol.fx_spot(records, "EUR", "USD", AS_OF, 1_000.0) == pytest.approx(1.10)


def test_market_spot_reads_spot_dated_forwards_for_a_pair_without_a_curve():
    records = [
        _forward("EUR", "USD", 1_000_000, 1_100_000, "2026-07-16"),
        _forward("CAD", "USD", 1_400_000, 1_000_000, "2026-07-16"),
        _forward("EUR", "USD", 500, 900, "2026-07-16"),
    ]
    curve = fx_vol.pair_curve(records, "EURCAD", AS_OF)
    spot, forward = fx_vol.market_spot(curve, records, "EUR", "CAD", AS_OF)

    assert spot == pytest.approx(1.10 * 1.40, abs=1e-6)
    assert forward is None
    assert fx_vol.market_spot(curve, [], "EUR", "CAD", AS_OF) == (None, None)


def test_build_market_needs_a_spot_and_a_curve_for_each_leg(monkeypatch):
    records = [_forward("EUR", "USD", 1_000_000, 1_100_000, "2026-07-16")]
    curve = fx_vol.pair_curve(records, "EURGBP", AS_OF)
    flat = {"EUR": _df_base, "USD": _df_quote}

    assert fx_vol.build_market(curve, [], "EUR", "USD", AS_OF, flat.get) is None
    assert fx_vol.build_market(curve, records, "EUR", "USD", AS_OF, {}.get) is None

    market = fx_vol.build_market(curve, records, "EUR", "USD", AS_OF, flat.get)

    assert market["spot"] == pytest.approx(1.10)
    assert market["forward"](1.0) == pytest.approx(1.10 * exp(0.02))


def test_market_discount_is_forward_aware_and_builds_a_currency_once(monkeypatch):
    seen: list = []

    def _rate_df(records, currency, day, min_trades, forward_aware=False):
        seen.append((currency, min_trades, forward_aware))

        return _df_base

    monkeypatch.setattr(fx_vol, "rate_discount_factor", _rate_df)
    discount = fx_vol.market_discount([], AS_OF, 3)

    assert discount("USD") is discount("USD") is _df_base
    assert seen == [("USD", 3, True)]


def test_extract_and_price_recovers_known_vols():
    records = [
        _priced_option(1.06, 30, 0.08, False),
        _priced_option(1.15, 90, 0.10, True),
        _priced_option(1.02, 60, 0.12, False),
    ]
    options = fx_vol.extract_vanilla_options(records, "EUR", "USD", AS_OF, SPOT)
    priced = fx_vol.price_options(options, SPOT, _df_quote, _df_base)

    assert len(priced) == 3
    assert priced[0]["implied_vol"] == pytest.approx(0.08, abs=1e-4)
    assert priced[1]["implied_vol"] == pytest.approx(0.10, abs=1e-4)
    assert priced[2]["implied_vol"] == pytest.approx(0.12, abs=1e-4)
    assert priced[0]["strike"] < priced[1]["strike"]


def test_price_options_skips_in_the_money_options():
    itm_call = _priced_option(1.02, 30, 0.09, True)
    itm_put = _priced_option(1.20, 30, 0.09, False)
    options = fx_vol.extract_vanilla_options(
        [itm_call, itm_put], "EUR", "USD", AS_OF, SPOT
    )

    assert len(options) == 2
    assert fx_vol.price_options(options, SPOT, _df_quote, _df_base) == []


def test_extract_flips_call_put_when_the_quote_leads_and_inverts_strike():
    quote_led = _option(
        "NA/O Van Put JPY USD",
        0.0065,
        1000.0,
        "USD",
        "2026-08-14",
        10_000_000,
        1_500_000,
        "USD",
    )
    options = fx_vol.extract_vanilla_options([quote_led], "USD", "JPY", AS_OF, 154.0)

    assert len(options) == 1
    assert options[0]["is_call"] is True
    assert options[0]["strike"] == pytest.approx(1.0 / 0.0065, abs=1e-6)


def test_extract_keeps_a_strike_already_in_the_pair_convention():
    mislabeled = _option(
        "NA/O Van Put EUR USD",
        1.14,
        15_000.0,
        "USD",
        "2026-08-14",
        10_000_000,
        11_400_000,
        "EUR",
    )
    mislabeled["Strike price currency/currency pair"] = "USD/EUR"
    options = fx_vol.extract_vanilla_options([mislabeled], "EUR", "USD", AS_OF, SPOT)

    assert len(options) == 1
    assert options[0]["strike"] == pytest.approx(1.14, abs=1e-9)


def test_extract_normalizes_a_base_currency_premium():
    fisn = "NA/O Van Call EUR USD"
    quote_prem = _option(
        fisn, 1.10, 15_000.0, "USD", "2026-08-14", 10_000_000, 11_000_000, "EUR"
    )
    base_prem = _option(
        fisn, 1.10, 15_000.0 / SPOT, "EUR", "2026-08-14", 10_000_000, 11_000_000, "EUR"
    )

    a = fx_vol.extract_vanilla_options([quote_prem], "EUR", "USD", AS_OF, SPOT)[0]
    b = fx_vol.extract_vanilla_options([base_prem], "EUR", "USD", AS_OF, SPOT)[0]

    assert a["premium"] == pytest.approx(b["premium"], abs=1e-9)


def test_extract_skips_unusable_options():
    good = _priced_option(1.10, 30, 0.08, True)
    rows = [
        {**good, "Strike Price": ""},
        {**good, "Option Premium Currency": "CHF"},
        {**good, "Expiration Date": AS_OF.isoformat()},
        {**good, "Action type": "CORR"},
        {**good, "Event type": "COMP"},
        {**good, "Execution Timestamp": "2026-07-10T10:00:00Z"},
        {**good, "UPI FISN": "NA/Fwd EUR USD"},
        {**good, "UPI FISN": "NA/O Van Call GBP JPY"},
        {**good, "Call currency": "CHF", "Put currency": "CHF"},
    ]

    assert fx_vol.extract_vanilla_options(rows, "EUR", "USD", AS_OF, SPOT) == []


def test_price_options_drops_an_unpriceable_premium():
    too_rich = {"tenor_days": 30, "strike": 1.20, "premium": 2.0, "is_call": True}

    assert fx_vol.price_options([too_rich], SPOT, _df_quote, _df_base) == []


def _priced(tenor_days, vol, offset_pips):
    return {
        "tenor_days": tenor_days,
        "implied_vol": vol,
        "strike": SPOT + offset_pips / PIP,
    }


def test_vol_surface_snaps_traded_options_to_the_strike_grid():
    priced = [
        _priced(90, 0.05, 10),
        _priced(90, 0.06, -510),
        _priced(90, 0.065, 520),
        _priced(90, 0.20, -500),
        _priced(30, 0.045, -10),
        _priced(30, 0.05, 110),
        _priced(90, 0.06, 5000),
        _priced(5000, 0.05, 0),
    ]
    rows = {r["strike_offset"]: r for r in fx_vol.vol_surface(priced, SPOT, PIP)}

    assert {-500.0, 0.0, 100.0, 500.0} == set(rows)
    assert rows[0.0]["vol_3m"] == pytest.approx(0.05)
    assert rows[-500.0]["vol_3m"] == pytest.approx(0.06)
    assert rows[500.0]["vol_3m"] == pytest.approx(0.065)
    assert rows[0.0]["vol_1m"] == pytest.approx(0.045)
    assert rows[100.0]["vol_1m"] == pytest.approx(0.05)
    assert rows[-500.0]["strike"] == pytest.approx(SPOT - 0.05)
    assert all(r["vol_2y"] is None for r in rows.values())


def _priced_at(tenor_days, vol, strike):
    return {"tenor_days": tenor_days, "implied_vol": vol, "strike": strike}


def test_theoretical_surface_fits_a_smooth_sabr_smile():
    forward = SPOT * _df_base(90 / 365.0) / _df_quote(90 / 365.0)
    priced = [
        _priced_at(90, vol, strike)
        for strike, vol in (
            (1.03, 0.11),
            (1.06, 0.09),
            (1.09, 0.075),
            (forward, 0.07),
            (1.12, 0.068),
            (1.15, 0.072),
            (1.18, 0.08),
        )
    ]
    rows, fits = fx_vol.theoretical_surface(priced, SPOT, _df_quote, _df_base, PIP)

    assert "3M" in fits and fits["3M"]["rho"] < 0
    by_offset = {r["strike_offset"]: r for r in rows}
    assert by_offset[0.0]["strike"] == pytest.approx(SPOT)
    assert by_offset[0.0]["vol_3m"] == pytest.approx(0.07, abs=0.02)
    assert by_offset[-250.0]["vol_3m"] > by_offset[250.0]["vol_3m"]
    assert any(r["num_options"] > 0 for r in rows)


def test_theoretical_surface_skips_a_one_sided_expiry():
    priced = [
        _priced_at(90, 0.08, 1.05),
        _priced_at(90, 0.09, 1.02),
        _priced_at(90, 0.10, 0.99),
        _priced_at(90, 0.11, 0.96),
    ]
    rows, fits = fx_vol.theoretical_surface(priced, SPOT, _df_quote, _df_base, PIP)

    assert fits == {}
    assert all(r["num_options"] == 0 for r in rows)


def test_ois_discount_factor_reads_the_curve(slice_records):
    from math import log

    df = fx_vol.ois_discount_factor(
        slice_records, "USD", date(2026, 7, 15), min_trades=5
    )

    assert df(1.0) < 1.0
    assert df(2.0) < df(1.0)
    assert 0.03 < -log(df(1.0)) / 1.0 < 0.05


def _ois_slice_record(currency, effective, expiration, rate):
    return {
        "UPI FISN": f"NA/Swap OIS {currency}",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Notional currency-Leg 1": currency,
        "Fixed rate-Leg 1": str(rate),
        "Notional amount-Leg 1": "1,000,000",
        "Effective Date": effective,
        "Expiration Date": expiration,
        "Event timestamp": "2026-07-20T15:00:00Z",
    }


def test_forward_fill_extends_short_end_from_slice_forwards():
    trade_date = date(2026, 7, 20)
    spot = [(0.25, 0.990)]
    records = [
        _ois_slice_record("NZD", "2026-08-25", "2026-10-19", 0.036),
        _ois_slice_record("NZD", "2026-10-29", "2026-12-10", 0.0288),
        _ois_slice_record("NZD", "2026-12-10", "2027-02-11", 0.0310),
        _ois_slice_record("NZD", "2027-02-11", "2027-03-18", -50.0),
    ]
    enriched = fx_vol._forward_fill(
        list(spot), records, "NA/Swap OIS NZD", "NZD", trade_date
    )

    assert (0.25, 0.990) in enriched
    assert len(enriched) == 3
    assert all(df > 0 for _, df in enriched)
    assert enriched == sorted(enriched)


def test_forward_fill_without_forwards_returns_the_spot_nodes():
    trade_date = date(2026, 7, 20)
    spot = [(0.25, 0.990), (1.0, 0.96)]

    assert (
        fx_vol._forward_fill(list(spot), [], "NA/Swap OIS NZD", "NZD", trade_date)
        == spot
    )
