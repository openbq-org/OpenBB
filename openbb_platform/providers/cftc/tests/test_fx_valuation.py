from datetime import date, timedelta

import pytest

from openbb_cftc.utils import fx_valuation as fv

DAY = date(2026, 7, 24)


def _forward(**overrides) -> dict:
    record = {
        "Dissemination Identifier": "4402190022000000101",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Asset Class": "FX",
        "UPI FISN": "NA/Fwd NDF KRW USD",
        "UPI Underlier Name": "KRW USD",
        "Notional amount-Leg 1": "1,458,000,000",
        "Notional amount-Leg 2": "1,000,000",
        "Notional currency-Leg 1": "KRW",
        "Notional currency-Leg 2": "USD",
        "Exchange rate": "1,458.00",
        "Exchange rate basis": "KRW/USD",
        "Effective Date": "2026-07-27",
        "Expiration Date": "2026-08-31",
        "Cleared": "N",
        "Package indicator": "FALSE",
        "Non-standardized term indicator": "FALSE",
    }
    record.update(overrides)

    return record


def _option(**overrides) -> dict:
    record = _forward(
        **{
            "UPI FISN": "NA/O Van Put EUR USD",
            "UPI Underlier Name": "EUR USD",
            "Notional currency-Leg 1": "EUR",
            "Notional currency-Leg 2": "USD",
            "Notional amount-Leg 1": "1,000,000",
            "Notional amount-Leg 2": "1,140,000",
            "Strike Price": "1.1425",
            "Strike price currency/currency pair": "EUR/USD",
            "Option Premium Amount": "20,000",
            "Option Premium Currency": "USD",
            "Call currency": "",
            "Put currency": "EUR",
            "Exchange rate": "1.1425",
            "Exchange rate basis": "EUR/USD",
        }
    )
    record.update(overrides)

    return record


@pytest.mark.parametrize(
    ("value", "notation", "expected"),
    [
        ("99999.9999999999999", "1", True),
        ("9.9999999999", "3", True),
        ("99999", "4", True),
        ("9.9999999999", "1", False),
        ("1.25", "1", False),
        ("", "1", False),
        (None, "3", False),
        ("99999", None, False),
    ],
)
def test_is_not_provided_matches_each_notation_sentinel(value, notation, expected):
    assert fv.is_not_provided(value, notation) is expected


@pytest.mark.parametrize(
    ("indicator", "expected"),
    [("TRUE", True), ("true", True), ("FALSE", False), ("", False)],
)
def test_is_package_leg(indicator, expected):
    assert fv.is_package_leg({"Package indicator": indicator}) is expected


@pytest.mark.parametrize(
    ("indicator", "expected"),
    [("TRUE", False), ("true", False), ("FALSE", True), ("", True)],
)
def test_is_standard_terms(indicator, expected):
    assert fv.is_standard_terms({"Non-standardized term indicator": indicator}) is (
        expected
    )


@pytest.mark.parametrize(
    ("action", "event", "expected"),
    [
        ("NEWT", "TRAD", True),
        ("TERM", "ETRM", False),
        ("NEWT", "ETRM", False),
        ("", "", False),
    ],
)
def test_is_live_print(action, event, expected):
    record = {"Action type": action, "Event type": event}

    assert fv.is_live_print(record) is expected


@pytest.mark.parametrize(
    ("basis", "expected"),
    [
        ("USD/KRW", 1458.0),
        ("KRW/USD", 1.0 / 1458.0),
        ("EUR/JPY", None),
        ("", None),
        (None, None),
    ],
)
def test_oriented_rate_reads_the_stated_basis(basis, expected):
    result = fv.oriented_rate(1458.0, basis, "USD", "KRW")

    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_oriented_rate_rejects_a_zero_value():
    assert fv.oriented_rate(0.0, "USD/KRW", "USD", "KRW") is None


@pytest.mark.parametrize(
    ("rate", "spot", "expected"),
    [
        (1458.0, 1460.0, 1458.0),
        (1.0 / 1458.0, 1460.0, 1458.0),
        (0.0, 1460.0, 0.0),
        (1458.0, 0.0, 1458.0),
    ],
)
def test_orient_to_spot_picks_the_side_the_market_supports(rate, spot, expected):
    assert fv.orient_to_spot(rate, spot) == pytest.approx(expected)


def test_exchange_rate_prefers_the_stated_rate():
    assert fv.exchange_rate(_forward(), "USD", "KRW") == pytest.approx(1.0 / 1458.0)


def test_exchange_rate_falls_back_to_leg_notionals():
    record = _forward(**{"Exchange rate": "", "Exchange rate basis": ""})

    assert fv.exchange_rate(record, "USD", "KRW") == pytest.approx(1458.0)


def test_pair_for_resolves_in_the_keys_convention():
    assert fv.pair_for(_forward()) == ("USD", "KRW", "USDKRW")


@pytest.mark.parametrize("underlier", ["KRW", "KRW USD EUR", "", "ZZZ YYY"])
def test_pair_for_returns_none_for_unusable_legs(underlier):
    assert fv.pair_for({"UPI Underlier Name": underlier}) is None


@pytest.mark.parametrize(
    ("fisn", "expected"),
    [
        ("NA/Fwd NDF KRW USD", "forward"),
        ("NA/Fwd EUR USD", "forward"),
        ("NA/Swaps CHF EUR", None),
        ("NA/FX Fwd Nstd INR USD", None),
        ("NA/O Van Put EUR USD", "option"),
        ("NA/O NDO Call INR USD", "option"),
        ("NA/O Dig Put EUR USD", None),
        ("NA/O", None),
        ("", None),
    ],
)
def test_classify_fx_trade(fisn, expected):
    assert fv.classify_fx_trade({"UPI FISN": fisn}) == expected


@pytest.mark.parametrize(
    ("fisn", "expected"),
    [
        ("NA/O Van Put EUR USD", "NA/O Van "),
        ("NA/O NDO Call INR USD", "NA/O NDO "),
        ("NA/O Dig Put EUR USD", None),
        ("NA/Fwd EUR USD", None),
        ("NA/O", None),
    ],
)
def test_option_family(fisn, expected):
    assert fv.option_family({"UPI FISN": fisn}) == expected


def test_extract_fx_trade_reads_a_forward():
    trade = fv.extract_fx_trade(_forward(), DAY)

    assert trade["trade_type"] == "fx_forward"
    assert trade["pair"] == "USDKRW"
    assert trade["base"] == "USD"
    assert trade["quote"] == "KRW"
    assert trade["currency"] == "KRW"
    assert trade["notional"] == pytest.approx(1_000_000.0)
    assert trade["days"] == 38
    assert trade["product"] == "Non-Deliverable Forward"
    assert trade["cleared"] == "N"


def test_extract_fx_trade_reads_an_option():
    trade = fv.extract_fx_trade(_option(), DAY)

    assert trade["trade_type"] == "fx_option"
    assert trade["strike"] == pytest.approx(1.1425)
    assert trade["premium"] == pytest.approx(20_000.0)
    assert trade["premium_currency"] == "USD"
    assert trade["is_call"] is False
    assert trade["option_family"] == "NA/O Van "


def test_extract_fx_trade_falls_back_to_the_exchange_rate_for_a_strike():
    trade = fv.extract_fx_trade(_option(**{"Strike Price": ""}), DAY)

    assert trade["strike"] == pytest.approx(1.1425)


@pytest.mark.parametrize(
    "overrides",
    [
        {"Action type": "TERM", "Event type": "ETRM"},
        {"Package indicator": "TRUE"},
        {"Non-standardized term indicator": "TRUE"},
        {"UPI FISN": "NA/O Dig Put EUR USD"},
        {"UPI Underlier Name": "ZZZ YYY"},
        {"Expiration Date": ""},
        {"Expiration Date": "2026-07-01"},
        {"Notional amount-Leg 2": "0", "Notional currency-Leg 2": "USD"},
        {"Exchange rate": "", "Exchange rate basis": "", "Notional amount-Leg 1": ""},
    ],
)
def test_extract_fx_trade_rejects_unpriceable_prints(overrides):
    assert fv.extract_fx_trade(_forward(**overrides), DAY) is None


def test_extract_fx_trade_honours_the_notional_floor():
    assert fv.extract_fx_trade(_forward(), DAY, min_notional=5_000_000.0) is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"Option Premium Amount": ""},
        {"Option Premium Currency": "JPY"},
        {"Call currency": "", "Put currency": ""},
        {
            "Strike Price": "",
            "Exchange rate": "",
            "Exchange rate basis": "",
            "Notional amount-Leg 2": "",
        },
    ],
)
def test_extract_fx_trade_rejects_unpriceable_options(overrides):
    assert fv.extract_fx_trade(_option(**overrides), DAY) is None


def _market(spot: float = 1460.0) -> dict:
    return {
        "spot": spot,
        "forward": lambda years: spot * (1.0 + 0.01 * years),
        "df_base": lambda years: 0.98**years,
        "df_quote": lambda years: 0.97**years,
    }


def test_value_fx_forward_marks_against_the_curve():
    trade = fv.extract_fx_trade(_forward(), DAY)
    trade["traded_rate"] = 1458.0
    valued = fv.value_fx_forward(trade, _market())

    assert valued["years"] == pytest.approx(38.0 / 365.0)
    assert valued["market_rate"] > 1460.0
    assert valued["npv"] > 0.0
    assert valued["spot"] == 1460.0


def test_value_fx_option_marks_against_the_premium():
    trade = fv.extract_fx_trade(_option(), DAY)
    valued = fv.value_fx_option(trade, _market(spot=1.14), vol=0.09)

    assert valued["implied_vol"] == 0.09
    assert valued["premium"] == pytest.approx(20_000.0)
    assert valued["npv"] == pytest.approx(valued["mark"] - valued["premium"])


def test_value_fx_option_converts_a_base_currency_premium():
    trade = fv.extract_fx_trade(_option(**{"Option Premium Currency": "EUR"}), DAY)
    valued = fv.value_fx_option(trade, _market(spot=1.14), vol=0.09)

    assert valued["premium"] == pytest.approx(20_000.0 * 1.14)


def _observations(days_list):
    return [{"days": d, "rate": 1460.0} for d in days_list]


def _patch_market(monkeypatch, nodes, spot=1460.0, base_ok=True, quote_ok=True):
    from openbb_core.provider.utils.errors import EmptyDataError

    monkeypatch.setattr(
        "openbb_cftc.utils.fx.extract_fx_observations",
        lambda *a, **k: _observations(nodes),
    )
    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.ndf_forward_curve",
        lambda *a, **k: (spot, (lambda years: spot * (1.0 + 0.01 * years))),
    )

    def _rate_df(records, currency, day, min_trades):
        if currency == "USD" and not base_ok:
            raise EmptyDataError("no base curve")

        if currency == "KRW" and not quote_ok:
            raise EmptyDataError("no quote curve")

        return lambda years: 0.98**years

    monkeypatch.setattr("openbb_cftc.utils.fx_vol.rate_discount_factor", _rate_df)
    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.implied_df",
        lambda df_base, spot_, forward: lambda years: 0.97**years,
    )


def test_fx_market_builds_from_the_base_curve(monkeypatch):
    _patch_market(monkeypatch, [7, 38, 90])
    trade = fv.extract_fx_trade(_forward(), DAY)
    market = fv.fx_market([], [], trade, DAY)

    assert market["spot"] == 1460.0
    assert market["df_quote"](1.0) == pytest.approx(0.97)


def test_fx_market_falls_back_to_the_quote_curve(monkeypatch):
    _patch_market(monkeypatch, [7, 38, 90], base_ok=False)
    trade = fv.extract_fx_trade(_forward(), DAY)
    market = fv.fx_market([], [], trade, DAY)

    assert market["df_base"](1.0) == pytest.approx(0.98 * 1.01 / 1.0, rel=0.05)


def test_fx_market_needs_both_curves(monkeypatch):
    _patch_market(monkeypatch, [7, 38, 90], base_ok=False, quote_ok=False)
    trade = fv.extract_fx_trade(_forward(), DAY)

    assert fv.fx_market([], [], trade, DAY) is None


def test_fx_market_requires_enough_nodes(monkeypatch):
    _patch_market(monkeypatch, [38])
    trade = fv.extract_fx_trade(_forward(), DAY)

    assert fv.fx_market([], [], trade, DAY) is None


def test_fx_market_recovers_a_missing_spot_through_cip(monkeypatch):
    _patch_market(monkeypatch, [7, 38, 90])
    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.ndf_forward_curve", lambda *a, **k: (None, None)
    )
    trade = fv.extract_fx_trade(_forward(), DAY)
    market = fv.fx_market([], [], trade, DAY)

    assert market["spot"] == pytest.approx(1460.0)
    assert market["forward"](1.0) == pytest.approx(1460.0)


def test_fx_market_cip_fallback_prices_off_both_curves(monkeypatch):
    monkeypatch.setattr(
        "openbb_cftc.utils.fx.extract_fx_observations",
        lambda *a, **k: [{"days": 2, "rate": 1460.0}, {"days": 5, "rate": 1461.0}],
    )

    def _rate_df(records, currency, day, min_trades):
        if currency == "USD":
            return lambda years: 0.96**years

        return lambda years: 0.99**years

    monkeypatch.setattr("openbb_cftc.utils.fx_vol.rate_discount_factor", _rate_df)
    trade = fv.extract_fx_trade(_forward(), DAY)
    market = fv.fx_market([], [], trade, DAY)

    assert market["spot"] == pytest.approx(1460.5)
    assert market["forward"](1.0) == pytest.approx(1460.5 * 0.96 / 0.99)
    assert market["forward"](2.0) < market["forward"](1.0)
    assert market["df_base"](1.0) == pytest.approx(0.96)
    assert market["df_quote"](1.0) == pytest.approx(0.99)


def test_fx_market_cip_fallback_needs_both_curves(monkeypatch):
    from openbb_core.provider.utils.errors import EmptyDataError

    monkeypatch.setattr(
        "openbb_cftc.utils.fx.extract_fx_observations",
        lambda *a, **k: [{"days": 2, "rate": 1460.0}],
    )

    def _usd_only(records, currency, day, min_trades):
        if currency == "USD":
            return lambda years: 0.96**years

        raise EmptyDataError("no quote curve")

    monkeypatch.setattr("openbb_cftc.utils.fx_vol.rate_discount_factor", _usd_only)
    trade = fv.extract_fx_trade(_forward(), DAY)

    assert fv.fx_market([], [], trade, DAY) is None


def test_fx_market_cip_fallback_needs_a_near_print(monkeypatch):
    monkeypatch.setattr(
        "openbb_cftc.utils.fx.extract_fx_observations",
        lambda *a, **k: [{"days": 38, "rate": 1460.0}],
    )
    trade = fv.extract_fx_trade(_forward(), DAY)

    assert fv.fx_market([], [], trade, DAY) is None


def test_fx_market_cip_fallback_rejects_a_nonpositive_spot(monkeypatch):
    monkeypatch.setattr(
        "openbb_cftc.utils.fx.extract_fx_observations",
        lambda *a, **k: [{"days": 2, "rate": 0.0}],
    )
    trade = fv.extract_fx_trade(_forward(), DAY)

    assert fv.fx_market([], [], trade, DAY) is None


def test_fx_market_uses_the_same_curve_as_the_vol_surface(monkeypatch):
    seen = {}

    def _curve(records, pair, as_of, **kwargs):
        seen["ids"] = [r.get("Dissemination Identifier") for r in records]
        return 1460.0, lambda years: 1460.0

    monkeypatch.setattr(
        "openbb_cftc.utils.fx.extract_fx_observations",
        lambda *a, **k: _observations([7, 38, 90]),
    )
    monkeypatch.setattr("openbb_cftc.utils.fx_vol.ndf_forward_curve", _curve)
    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.rate_discount_factor",
        lambda *a, **k: lambda years: 0.98**years,
    )
    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.implied_df", lambda *a, **k: lambda years: 0.97
    )
    own = _forward()
    peer = _forward(**{"Dissemination Identifier": "4402190022000000201"})
    leg = _forward(
        **{
            "Dissemination Identifier": "4402190022000000202",
            "Package indicator": "TRUE",
        }
    )
    trade = fv.extract_fx_trade(own, DAY)
    fv.fx_market([own, peer, leg], [], trade, DAY)

    assert seen["ids"] == [
        own["Dissemination Identifier"],
        "4402190022000000201",
        "4402190022000000202",
    ]


def test_fx_market_builds_the_curve_once_per_pair_and_day(monkeypatch):
    _patch_market(monkeypatch, [7, 38, 90])
    calls: list = []

    def _curve(records, pair, as_of, **kwargs):
        calls.append(as_of)
        return 1460.0, lambda years: 1460.0

    monkeypatch.setattr("openbb_cftc.utils.fx_vol.ndf_forward_curve", _curve)
    first = _forward()
    second = _forward(**{"Dissemination Identifier": "4402190022000000201"})
    memo: dict = {}

    for record in (first, second):
        fv.fx_market(
            [first, second], [], fv.extract_fx_trade(record, DAY), DAY, memo=memo
        )

    assert calls == [DAY]

    later = DAY + timedelta(days=1)
    fv.fx_market(
        [first, second], [], fv.extract_fx_trade(first, later), later, memo=memo
    )

    assert calls == [DAY, later]


def test_fx_market_memo_builds_the_pair_subset_and_curves_once(monkeypatch):
    _patch_market(monkeypatch, [7, 38, 90])
    subset_calls: list = []
    df_calls: list = []
    real_subset = fv.pair_records

    def _counted_subset(records, base, quote):
        subset_calls.append((base, quote))
        return real_subset(records, base, quote)

    def _counted_df(records, currency, day, min_trades):
        df_calls.append(currency)
        return lambda years: 0.98**years

    monkeypatch.setattr(fv, "pair_records", _counted_subset)
    monkeypatch.setattr("openbb_cftc.utils.fx_vol.rate_discount_factor", _counted_df)
    trade = fv.extract_fx_trade(_forward(), DAY)
    memo: dict = {}
    first = fv.fx_market([], [], trade, DAY, memo=memo)
    second = fv.fx_market([], [], trade, DAY, memo=memo)

    assert first["spot"] == second["spot"]
    assert len(subset_calls) == 1
    assert len(df_calls) == 1


def _patch_vol(monkeypatch, priced):
    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.extract_vanilla_options", lambda *a, **k: [{}]
    )
    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.price_options", lambda *a, **k: priced
    )


def test_option_vol_takes_the_nearest_tenor(monkeypatch):
    _patch_vol(
        monkeypatch,
        [
            {"tenor_days": 38, "implied_vol": 0.10},
            {"tenor_days": 38, "implied_vol": 0.12},
            {"tenor_days": 400, "implied_vol": 0.30},
        ],
    )
    trade = fv.extract_fx_trade(_option(), DAY)

    assert fv.option_vol([], trade, _market(1.14), DAY) == pytest.approx(0.11)


def test_option_vol_returns_none_without_priced_peers(monkeypatch):
    _patch_vol(monkeypatch, [])
    trade = fv.extract_fx_trade(_option(), DAY)

    assert fv.option_vol([], trade, _market(1.14), DAY) is None


def test_option_vol_returns_none_without_a_family():
    trade = fv.extract_fx_trade(_option(), DAY)
    trade["option_family"] = None

    assert fv.option_vol([], trade, _market(1.14), DAY) is None


def test_option_vol_prices_a_family_once_per_market(monkeypatch):
    calls: list = []

    def _price(*args, **kwargs):
        calls.append(args)
        return [{"tenor_days": 38, "implied_vol": 0.10}]

    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.extract_vanilla_options", lambda *a, **k: [{}]
    )
    monkeypatch.setattr("openbb_cftc.utils.fx_vol.price_options", _price)
    trade = fv.extract_fx_trade(_option(), DAY)
    market = {**_market(1.14), "key": "fx-market:EURUSD:2026-07-24:1"}
    memo: dict = {}

    for _ in range(3):
        assert fv.option_vol([], trade, market, DAY, memo) == pytest.approx(0.10)

    assert len(calls) == 1


def test_value_fx_trade_prices_a_forward(monkeypatch):
    _patch_market(monkeypatch, [7, 38, 90])
    valued = fv.value_fx_trade(_forward(), [], [], DAY)

    assert valued["trade_type"] == "fx_forward"
    assert valued["traded_rate"] == pytest.approx(1458.0)
    assert "npv" in valued


def test_value_fx_trade_prices_an_option(monkeypatch):
    _patch_market(monkeypatch, [7, 38, 90], spot=1.14)
    _patch_vol(monkeypatch, [{"tenor_days": 38, "implied_vol": 0.09}])
    valued = fv.value_fx_trade(_option(), [], [], DAY)

    assert valued["trade_type"] == "fx_option"
    assert valued["implied_vol"] == pytest.approx(0.09)


def test_value_fx_trade_returns_none_without_a_vol(monkeypatch):
    _patch_market(monkeypatch, [7, 38, 90], spot=1.14)
    _patch_vol(monkeypatch, [])

    assert fv.value_fx_trade(_option(), [], [], DAY) is None


def test_value_fx_trade_returns_none_for_an_unpriceable_print():
    assert fv.value_fx_trade(_forward(**{"Action type": "TERM"}), [], [], DAY) is None


def test_value_fx_trade_returns_none_without_a_market(monkeypatch):
    _patch_market(monkeypatch, [38])

    assert fv.value_fx_trade(_forward(), [], [], DAY) is None


def test_value_fx_trade_gates_a_rate_beyond_the_carry_bound(monkeypatch):
    _patch_market(monkeypatch, [7, 38, 90], spot=1460.0)
    record = _forward(**{"Exchange rate": "2,900.00", "Exchange rate basis": "USD/KRW"})

    assert fv.value_fx_trade(record, [], [], DAY) is None
