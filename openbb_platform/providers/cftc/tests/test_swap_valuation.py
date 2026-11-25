import asyncio
from datetime import UTC, date, timedelta
from math import exp

import pytest

from openbb_cftc.models.swap_valuation import (
    CftcSwapValuationData,
    CftcSwapValuationFetcher,
    CftcSwapValuationQueryParams,
)
from openbb_cftc.utils.swap import value_swap

DATE = date(2026, 7, 17)


def _flat_curve(rate):

    def factory(records, currency, trade_date, min_trades):
        return lambda years: exp(-rate * years)

    return factory


def test_value_swap_par_prices_to_zero(monkeypatch):
    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.rate_discount_factor", _flat_curve(0.04)
    )
    schedule, summary = value_swap([], "USD", DATE, 1826)

    assert len(schedule) == 5
    assert summary["par_rate"] > 0
    assert summary["npv"] == pytest.approx(0.0, abs=1e-6)
    assert summary["fixed_leg_pv"] == pytest.approx(summary["floating_leg_pv"])
    assert summary["dv01"] == pytest.approx(summary["annuity"] * 1e-4)
    assert sum(r["floating_pv"] for r in schedule) == pytest.approx(
        summary["floating_leg_pv"]
    )


def test_value_swap_off_market_is_signed_by_side(monkeypatch):
    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.rate_discount_factor", _flat_curve(0.04)
    )
    _, pay = value_swap([], "USD", DATE, 1826, fixed_rate=0.03, side="pay")
    _, receive = value_swap([], "USD", DATE, 1826, fixed_rate=0.03, side="receive")

    assert pay["npv"] > 0
    assert receive["npv"] == pytest.approx(-pay["npv"])


def test_value_swap_spread_prices_into_both_legs(monkeypatch):
    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.rate_discount_factor", _flat_curve(0.04)
    )
    _, plain = value_swap([], "USD", DATE, 1826)
    schedule, spread = value_swap([], "USD", DATE, 1826, spread=0.0025)

    assert spread["par_rate"] - plain["par_rate"] == pytest.approx(0.0025)
    assert spread["npv"] == pytest.approx(0.0, abs=1e-6)
    assert sum(r["floating_pv"] for r in schedule) == pytest.approx(
        spread["floating_leg_pv"]
    )
    assert all(
        r["floating_rate"] - r["forward_rate"] == pytest.approx(0.0025)
        for r in schedule
    )


def test_value_swap_forward_starting_telescopes_from_the_start(monkeypatch):
    from math import exp

    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.rate_discount_factor", _flat_curve(0.04)
    )
    schedule, summary = value_swap([], "USD", DATE, 1826, start_days=365)
    df_start = exp(-0.04 * 365 / 365.0)
    df_maturity = schedule[-1]["discount_factor"]

    assert schedule[0]["start_date"] == DATE + timedelta(days=365)
    assert summary["floating_leg_pv"] == pytest.approx(
        10_000_000.0 * (df_start - df_maturity)
    )
    assert summary["npv"] == pytest.approx(0.0, abs=1e-6)


def test_value_swap_aggregates_floating_periods_onto_coarser_fixed_rows(monkeypatch):
    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.rate_discount_factor", _flat_curve(0.04)
    )
    schedule, summary = value_swap(
        [],
        "USD",
        DATE,
        1826,
        fixed_frequency=("YEAR", 1),
        floating_frequency=("MNTH", 6),
    )

    assert len(schedule) == 5
    assert sum(r["floating_pv"] for r in schedule) == pytest.approx(
        summary["floating_leg_pv"]
    )
    assert summary["npv"] == pytest.approx(0.0, abs=1e-6)


def test_value_swap_leaves_a_fixed_row_bare_when_no_floating_period_fits_inside_it(
    monkeypatch,
):
    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.rate_discount_factor", _flat_curve(0.04)
    )
    schedule, summary = value_swap(
        [],
        "USD",
        DATE,
        365,
        fixed_frequency=("MNTH", 3),
        floating_frequency=("MNTH", 12),
    )

    assert len(schedule) == 4
    assert all("floating_pv" not in row for row in schedule)
    assert summary["floating_leg_pv"] > 0


def test_swap_valuation_transform_query():
    query = CftcSwapValuationFetcher.transform_query({"currency": "usd"})

    assert isinstance(query, CftcSwapValuationQueryParams)
    assert query.currency == "USD"


def test_swap_valuation_aextract_raises_without_a_priceable_print(monkeypatch):
    from openbb_core.provider.utils.errors import EmptyDataError

    async def _rates(report_date, currencies, use_cache=True):
        return [], "2026-07-17"

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)

    with pytest.raises(EmptyDataError, match="No priceable USD swap"):
        asyncio.run(
            CftcSwapValuationFetcher.aextract_data(
                CftcSwapValuationQueryParams(currency="USD"), None
            )
        )


def _future_trade(**overrides):
    trade = {
        "dissemination_identifier": "S1",
        "underlier": "USD-SOFR-COMPOUND",
        "effective_date": date(2099, 1, 1),
        "expiration_date": date(2100, 1, 1),
    }
    trade.update(overrides)

    return trade


def test_swap_valuation_aextract_anchors_the_rates_date(monkeypatch):
    seen: list = []

    async def _rates(report_date, currencies, use_cache=True):
        seen.append(currencies)
        return [], "2026-07-17"

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)
    monkeypatch.setattr(
        "openbb_cftc.utils.swap.select_swap_trade", lambda *a, **k: _future_trade()
    )

    asyncio.run(
        CftcSwapValuationFetcher.aextract_data(
            CftcSwapValuationQueryParams(currency="EUR", date=DATE), None
        )
    )
    asyncio.run(
        CftcSwapValuationFetcher.aextract_data(
            CftcSwapValuationQueryParams(currency="CNY"), None
        )
    )

    assert seen == [["EUR"], ["USD"]]


def test_swap_valuation_aextract_uses_a_cached_trade_record_without_scanning(
    monkeypatch,
):
    from openbb_cftc.utils import store

    pln_print = {
        "Dissemination Identifier": "PLN1",
        "UPI FISN": "NA/Swap Fxd Flt PLN",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Notional currency-Leg 1": "PLN",
        "Fixed rate-Leg 1": "0.05",
        "Effective Date": (DATE + timedelta(days=2)).isoformat(),
        "Expiration Date": (DATE + timedelta(days=2 + 1826)).isoformat(),
        "Notional amount-Leg 1": "20000000",
        "Cleared": "Y",
        "Execution Timestamp": "2026-07-16T10:00:00Z",
    }
    store.write_search_records("IR", "2026-07-15", [pln_print])

    async def _forbidden(*args, **kwargs):
        raise AssertionError("get_latest_viable_slice ran despite a cache hit")

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_latest_viable_slice", _forbidden)

    seen_anchor: list = []

    async def _rates(report_date, currencies, use_cache=True):
        seen_anchor.append(currencies)
        return [], "2026-07-17"

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)

    trade, _, _, _, currency, trade_date_str = asyncio.run(
        CftcSwapValuationFetcher.aextract_data(
            CftcSwapValuationQueryParams(
                currency="USD", dissemination_identifier="PLN1"
            ),
            None,
        )
    )

    assert currency == "PLN"
    assert trade["dissemination_identifier"] == "PLN1"
    assert trade_date_str == "2026-07-16"
    assert seen_anchor == [["USD"]]


def test_swap_valuation_aextract_finds_a_trade_by_id_off_its_own_record(monkeypatch):
    pln_print = {
        "Dissemination Identifier": "PLN1",
        "UPI FISN": "NA/Swap Fxd Flt PLN",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Notional currency-Leg 1": "PLN",
        "Fixed rate-Leg 1": "0.05",
        "Effective Date": (DATE + timedelta(days=2)).isoformat(),
        "Expiration Date": (DATE + timedelta(days=2 + 1826)).isoformat(),
        "Notional amount-Leg 1": "20000000",
        "Cleared": "Y",
    }

    async def _dates(asset_class):
        return ["2026-07-15", "2026-07-16", "2026-07-17"]

    async def _slice(asset_class, report_date, use_cache=True):
        return [pln_print] if report_date == "2026-07-16" else []

    seen_anchor: list = []

    async def _rates(report_date, currencies, use_cache=True):
        seen_anchor.append(currencies)
        return [], "2026-07-17"

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_available_dates", _dates)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _slice)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)

    trade, _, _, _, currency, trade_date_str = asyncio.run(
        CftcSwapValuationFetcher.aextract_data(
            CftcSwapValuationQueryParams(
                currency="USD", dissemination_identifier="PLN1"
            ),
            None,
        )
    )

    assert currency == "PLN"
    assert trade["dissemination_identifier"] == "PLN1"
    assert trade_date_str == "2026-07-16"
    assert seen_anchor == [["USD"]]


def test_swap_valuation_aextract_scans_slices_for_the_exact_identifier(monkeypatch):
    usd_print = {
        "Dissemination Identifier": "4391821108000000101",
        "UPI FISN": "NA/Swap OIS USD",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Notional currency-Leg 1": "USD",
        "Fixed rate-Leg 1": "0.04",
        "Effective Date": (DATE + timedelta(days=2)).isoformat(),
        "Expiration Date": (DATE + timedelta(days=2 + 1826)).isoformat(),
        "Notional amount-Leg 1": "17000000",
        "Cleared": "I",
    }

    async def _dates(asset_class):
        return ["2026-07-16", "2026-07-17"]

    async def _slice(asset_class, report_date, use_cache=True):
        return [usd_print] if report_date == "2026-07-17" else []

    async def _rates(report_date, currencies, use_cache=True):
        return [], "2026-07-17"

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_available_dates", _dates)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _slice)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)

    trade, _, _, _, currency, _ = asyncio.run(
        CftcSwapValuationFetcher.aextract_data(
            CftcSwapValuationQueryParams(
                currency="USD", dissemination_identifier="4391821108000000101"
            ),
            None,
        )
    )

    assert currency == "USD"
    assert trade["dissemination_identifier"] == "4391821108000000101"


def test_swap_valuation_aextract_falls_back_to_search_when_not_yet_in_any_slice(
    monkeypatch,
):
    from datetime import datetime

    today = datetime.now(UTC).date()
    fresh_print = {
        "Dissemination Identifier": "FRESH1",
        "UPI FISN": "NA/Swap OIS USD",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Execution Timestamp": f"{today.isoformat()}T14:00:00Z",
        "Notional currency-Leg 1": "USD",
        "Fixed rate-Leg 1": "0.04",
        "Effective Date": (today + timedelta(days=2)).isoformat(),
        "Expiration Date": (today + timedelta(days=2 + 1826)).isoformat(),
        "Notional amount-Leg 1": "10000000",
        "Cleared": "Y",
    }

    async def _no_usable_slice(*args, **kwargs):
        from openbb_core.app.model.abstract.error import OpenBBError

        raise OpenBBError(
            f"No rates file in the 10 days to {today.isoformat()} held usable"
            " data for this query. Widen the filters, or pass an explicit date."
        )

    seen_search_window: list = []

    async def _search(asset_class, start_date, end_date, use_cache=True):
        seen_search_window.append((start_date, end_date))
        return [fresh_print]

    seen_anchor: list = []

    async def _rates(report_date, currencies, use_cache=True):
        seen_anchor.append(currencies)
        return [], today.isoformat()

    monkeypatch.setattr(
        "openbb_cftc.utils.dtcc.get_latest_viable_slice", _no_usable_slice
    )
    monkeypatch.setattr("openbb_cftc.utils.search.search_trades", _search)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)

    trade, _, _, _, currency, trade_date_str = asyncio.run(
        CftcSwapValuationFetcher.aextract_data(
            CftcSwapValuationQueryParams(
                currency="USD", dissemination_identifier="FRESH1"
            ),
            None,
        )
    )

    assert currency == "USD"
    assert trade["dissemination_identifier"] == "FRESH1"
    assert trade_date_str == today.isoformat()
    assert seen_search_window == [(today, today)]


def test_swap_valuation_aextract_raises_when_search_also_finds_nothing(monkeypatch):
    from openbb_core.app.model.abstract.error import OpenBBError

    async def _no_slice(*args, **kwargs):
        raise OpenBBError(
            "No rates file in the 10 days to 2026-07-17 held usable data for this"
            " query. Widen the filters, or pass an explicit date."
        )

    async def _empty_search(asset_class, start_date, end_date, use_cache=True):
        return []

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_latest_viable_slice", _no_slice)
    monkeypatch.setattr("openbb_cftc.utils.search.search_trades", _empty_search)

    from openbb_core.provider.utils.errors import EmptyDataError

    with pytest.raises(EmptyDataError, match="'GHOST1' was not found"):
        asyncio.run(
            CftcSwapValuationFetcher.aextract_data(
                CftcSwapValuationQueryParams(
                    currency="USD", dissemination_identifier="GHOST1"
                ),
                None,
            )
        )


def _print(identifier="P1", rate=0.03, start=2, tenor=1826, notional="10000000"):
    effective = DATE + timedelta(days=start)

    return {
        "Dissemination Identifier": identifier,
        "UPI FISN": "NA/Swap OIS USD",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Notional currency-Leg 1": "USD",
        "Fixed rate-Leg 1": f"{rate}",
        "Effective Date": effective.isoformat(),
        "Expiration Date": (effective + timedelta(days=tenor)).isoformat(),
        "Notional amount-Leg 1": notional,
        "Cleared": "Y",
    }


def test_swap_valuation_transform_prices_the_selected_print(monkeypatch):
    from openbb_cftc.utils.swap import select_swap_trade

    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.rate_discount_factor", _flat_curve(0.04)
    )
    records = [_print(rate=0.03)]
    trade = select_swap_trade(records, "USD", DATE)
    result = CftcSwapValuationFetcher.transform_data(
        CftcSwapValuationQueryParams(currency="USD"),
        (trade, records, DATE.isoformat(), {}, "USD", DATE.isoformat()),
    )

    assert all(isinstance(r, CftcSwapValuationData) for r in result.result)
    assert len(result.result) == 5
    assert result.metadata["dissemination_identifier"] == "P1"
    assert result.metadata["fixed_rate"] == pytest.approx(3.0)
    assert result.metadata["notional"] == pytest.approx(10_000_000.0)
    assert result.metadata["npv"] > 0
    assert result.metadata["dv01"] > 0
    assert result.result[0].fixed_rate == pytest.approx(3.0)
    assert all(r.notional == pytest.approx(10_000_000.0) for r in result.result)


def test_swap_valuation_transform_selects_by_identifier(monkeypatch):
    from openbb_cftc.utils.swap import select_swap_trade

    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.rate_discount_factor", _flat_curve(0.04)
    )
    records = [
        _print("big", notional="9000000000"),
        _print("small", rate=0.045, notional="5000000"),
    ]
    trade = select_swap_trade(records, "USD", DATE, dissemination_identifier="small")
    result = CftcSwapValuationFetcher.transform_data(
        CftcSwapValuationQueryParams(currency="USD", dissemination_identifier="small"),
        (trade, records, DATE.isoformat(), {}, "USD", DATE.isoformat()),
    )

    assert result.metadata["dissemination_identifier"] == "small"
    assert result.metadata["fixed_rate"] == pytest.approx(4.5)
    assert result.metadata["npv"] < 0


def test_swap_valuation_names_the_winning_side_of_a_seasoned_print(monkeypatch):
    from openbb_cftc.utils.swap import select_swap_trade

    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.rate_discount_factor", _flat_curve(0.04)
    )
    seasoned = _print(rate=0.03, start=-400)
    trade = select_swap_trade([seasoned], "USD", DATE)
    result = CftcSwapValuationFetcher.transform_data(
        CftcSwapValuationQueryParams(currency="USD"),
        (trade, [], DATE.isoformat(), {}, "USD", DATE.isoformat()),
    )
    m = result.metadata

    assert m["winning_side"] == "pay"
    assert m["npv"] > 0
    assert m["accrued_carry"] is None and "fixings" in m["carry_note"]
    assert result.result[0].start_date == DATE
    assert result.result[-1].payment_date.isoformat() == m["expiration_date"]


def test_swap_valuation_aextract_fetches_the_trade_day_slice(monkeypatch):
    fetched: list = []

    async def _rates(report_date, currencies, use_cache=True):
        return [{"day": "today"}], "2026-07-17"

    async def _slice(asset_class, report_date, use_cache=True):
        fetched.append(report_date)
        return [{"day": "then"}]

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _slice)
    monkeypatch.setattr(
        "openbb_cftc.utils.swap.select_swap_trade", lambda *a, **k: _future_trade()
    )

    trade, rates, rates_date, fixings, currency, trade_date_str = asyncio.run(
        CftcSwapValuationFetcher.aextract_data(
            CftcSwapValuationQueryParams(
                currency="USD", trade_date=DATE - timedelta(days=270)
            ),
            None,
        )
    )

    assert fetched == [(DATE - timedelta(days=270)).isoformat()]
    assert trade == _future_trade()
    assert rates == [{"day": "today"}]
    assert rates_date == "2026-07-17"
    assert fixings == {}
    assert currency == "USD"
    assert trade_date_str == (DATE - timedelta(days=270)).isoformat()


def test_swap_valuation_reports_realized_carry_from_fixings(monkeypatch):
    from openbb_cftc.utils.swap import select_swap_trade

    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.rate_discount_factor", _flat_curve(0.04)
    )
    seasoned = _print(rate=0.03, start=-400)
    trade = select_swap_trade([seasoned], "USD", DATE)
    fixings = {DATE - timedelta(days=400): 0.039}
    result = CftcSwapValuationFetcher.transform_data(
        CftcSwapValuationQueryParams(currency="USD"),
        (trade, [], DATE.isoformat(), fixings, "USD", DATE.isoformat()),
    )
    m = result.metadata

    assert m["floating_accrued"] > m["fixed_accrued"] > 0
    assert m["accrued_carry"] == pytest.approx(
        m["floating_accrued"] - m["fixed_accrued"]
    )
    assert m["winning_side"] == "pay"


def test_swap_valuation_aextract_fetches_fixings_for_a_seasoned_print(monkeypatch):
    windows: list = []

    async def _rates(report_date, currencies, use_cache=True):
        return [], "2026-07-17"

    async def _fixings(index, start_date, end_date, use_cache=True):
        windows.append((index, start_date, end_date))
        return {start_date: 0.039}

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)
    monkeypatch.setattr("openbb_cftc.utils.fixings.get_fixings", _fixings)
    monkeypatch.setattr(
        "openbb_cftc.utils.swap.select_swap_trade",
        lambda *a, **k: _future_trade(
            effective_date=date(2025, 10, 23), expiration_date=date(2030, 10, 23)
        ),
    )

    _, _, _, fixings, _, _ = asyncio.run(
        CftcSwapValuationFetcher.aextract_data(
            CftcSwapValuationQueryParams(currency="USD"), None
        )
    )

    assert windows == [("SOFR", date(2025, 10, 23), date(2026, 7, 17))]
    assert fixings == {date(2025, 10, 23): 0.039}


def test_swap_valuation_flags_fixings_that_do_not_cover_the_span(monkeypatch):
    from openbb_cftc.utils.swap import select_swap_trade

    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.rate_discount_factor", _flat_curve(0.04)
    )
    seasoned = _print(rate=0.03, start=-400)
    trade = select_swap_trade([seasoned], "USD", DATE)
    late = {DATE - timedelta(days=10): 0.039}
    result = CftcSwapValuationFetcher.transform_data(
        CftcSwapValuationQueryParams(currency="USD"),
        (trade, [], DATE.isoformat(), late, "USD", DATE.isoformat()),
    )
    m = result.metadata

    assert m["accrued_carry"] is None
    assert "do not cover" in m["carry_note"]


def test_realized_carry_is_zero_before_the_trade_accrues(monkeypatch):
    from openbb_cftc.utils.swap import extract_swap_trades, realized_carry

    trade = extract_swap_trades([_print(start=30)], "USD", DATE)[0]
    carry = realized_carry(trade, {DATE: 0.039}, DATE, 360.0, 365)

    assert carry == {
        "floating_settled": 0.0,
        "fixed_settled": 0.0,
        "floating_accrued": 0.0,
        "fixed_accrued": 0.0,
    }


def test_realized_carry_accrues_the_brl_fixed_leg_on_real_business_days():
    from openbb_cftc.utils.br_calendar import brl_business_days_between
    from openbb_cftc.utils.swap import extract_swap_trades, realized_carry

    effective = date(2028, 1, 3)
    expiration = date(2028, 7, 3)
    valuation_date = expiration
    record = {
        "Dissemination Identifier": "brl1",
        "UPI FISN": "NA/Swap OIS BRL",
        "UPI Underlier Name": "BRL-CDI",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Notional currency-Leg 1": "BRL",
        "Fixed rate-Leg 1": "0.1459",
        "Effective Date": effective.isoformat(),
        "Expiration Date": expiration.isoformat(),
        "Notional amount-Leg 1": "420000000",
        "Cleared": "Y",
        "Fixed rate day count convention-leg 1": "A018",
        "Floating rate day count convention-leg 2": "A018",
    }
    trade = extract_swap_trades([record], "BRL", effective)[0]

    real_bdays = brl_business_days_between(effective, expiration)
    fixings = {effective: 0.0006}
    carry = realized_carry(trade, fixings, valuation_date, 360.0, 365)

    expected_fixed = 420_000_000.0 * 0.1459 * (real_bdays / 252.0)

    assert carry["fixed_settled"] == pytest.approx(expected_fixed)
    assert carry["fixed_accrued"] == 0.0
    wrong_fixed = 420_000_000.0 * 0.1459 * ((expiration - effective).days / 252.0)
    assert carry["fixed_accrued"] < wrong_fixed * 0.8


def _cross_currency_print(identifier="XC1", spread_leg1="-0.0003"):
    effective = DATE + timedelta(days=2)

    return {
        "Dissemination Identifier": identifier,
        "UPI FISN": "NA/Swap Flt Flt EUR USD",
        "UPI Underlier Name": "EUR-EuroSTR-OIS Compound vs USD-SOFR-OIS Compound",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Notional currency-Leg 1": "EUR",
        "Notional currency-Leg 2": "USD",
        "Notional amount-Leg 1": "150000000",
        "Notional amount-Leg 2": "170550000",
        "Spread-Leg 1": spread_leg1,
        "Spread-Leg 2": "",
        "Effective Date": effective.isoformat(),
        "Expiration Date": (effective + timedelta(days=180)).isoformat(),
        "Floating rate day count convention-leg 1": "A004",
        "Floating rate payment frequency period-Leg 1": "MNTH",
        "Floating rate payment frequency period multiplier-Leg 1": "3",
        "Cleared": "N",
    }


def _fx_spot_print(base="USD", quote="EUR", rate=0.874, as_of=None):
    effective = as_of or DATE

    return {
        "UPI FISN": f"NA/Fwd {base} {quote}",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Notional currency-Leg 1": base,
        "Notional currency-Leg 2": quote,
        "Notional amount-Leg 1": "100000000",
        "Notional amount-Leg 2": f"{rate * 100_000_000:.2f}",
        "Effective Date": effective.isoformat(),
        "Expiration Date": (effective + timedelta(days=2)).isoformat(),
    }


def test_swap_valuation_aextract_dispatches_a_cross_currency_trade_by_id(monkeypatch):
    from openbb_cftc.utils import store

    store.write_search_records("IR", "2026-07-15", [_cross_currency_print()])

    async def _rates(report_date, currencies, use_cache=True):
        return [
            _cross_currency_print(),
            _cross_currency_print("XC2", "-0.0004"),
        ], "2026-07-17"

    async def _forex_slice(asset_class, report_date, use_cache=True):
        assert asset_class == "forex"
        return [_fx_spot_print(as_of=date(2026, 7, 17))]

    async def _forbidden_fixings(*args, **kwargs):
        raise AssertionError("get_fixings ran for a spread trade")

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _forex_slice)
    monkeypatch.setattr("openbb_cftc.utils.fixings.get_fixings", _forbidden_fixings)

    trade, rates, rates_date, fixings, currency, trade_date_str = asyncio.run(
        CftcSwapValuationFetcher.aextract_data(
            CftcSwapValuationQueryParams(
                currency="GBP", dissemination_identifier="XC1"
            ),
            None,
        )
    )

    assert currency == "EUR"
    assert trade["traded_spread"] == pytest.approx(-0.0003)
    assert trade["trade_type"] == "cross_currency"
    assert fixings == {"spot": pytest.approx(0.874)}


def test_swap_valuation_aextract_raises_for_an_unpriced_spread_trade(monkeypatch):
    from openbb_core.provider.utils.errors import EmptyDataError

    from openbb_cftc.utils import store

    unpriced = _cross_currency_print(spread_leg1="0")
    unpriced["Spread-Leg 2"] = "0"
    store.write_search_records("IR", "2026-07-15", [unpriced])

    async def _rates(report_date, currencies, use_cache=True):
        return [], "2026-07-17"

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)

    with pytest.raises(EmptyDataError, match="has no priceable"):
        asyncio.run(
            CftcSwapValuationFetcher.aextract_data(
                CftcSwapValuationQueryParams(
                    currency="EUR", dissemination_identifier="XC1"
                ),
                None,
            )
        )


def test_swap_valuation_transform_prices_a_cross_currency_trade(monkeypatch):
    from openbb_cftc.utils.swap import extract_spread_trade

    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.rate_discount_factor", _flat_curve(0.03)
    )
    record = _cross_currency_print("XC1", "-0.0003")
    trade = extract_spread_trade(record, DATE)
    assert trade is not None
    fixings = {"spot": 0.88}
    result = CftcSwapValuationFetcher.transform_data(
        CftcSwapValuationQueryParams(currency="EUR"),
        (trade, [record], DATE.isoformat(), fixings, "EUR", DATE.isoformat()),
    )
    m = result.metadata

    assert m["dissemination_identifier"] == "XC1"
    assert m["trade_type"] == "cross_currency"
    assert m["underlier"] == "EUR-EuroSTR-OIS Compound vs USD-SOFR-OIS Compound"
    assert m["other_currency"] == "USD"
    assert m["spot"] == 0.88
    assert "exchange_pv" in m
    assert "reference_trade_count" not in m
    assert m["fixed_rate"] == pytest.approx(-0.03)
    assert "is_vanilla_par" not in m
    assert m["accrued_carry"] == 0.0
    assert sum(r.fixed_pv for r in result.result) == pytest.approx(m["fixed_leg_pv"])


def _seasoned_cross_currency_print(identifier="XC1", spread_leg1="-0.0003"):
    effective = DATE - timedelta(days=270)

    return {
        "Dissemination Identifier": identifier,
        "UPI FISN": "NA/Swap Flt Flt EUR USD",
        "UPI Underlier Name": "EUR-EuroSTR-OIS Compound vs USD-SOFR-OIS Compound",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Notional currency-Leg 1": "EUR",
        "Notional currency-Leg 2": "USD",
        "Notional amount-Leg 1": "150000000",
        "Notional amount-Leg 2": "170550000",
        "Spread-Leg 1": spread_leg1,
        "Spread-Leg 2": "",
        "Effective Date": effective.isoformat(),
        "Expiration Date": (effective + timedelta(days=1095)).isoformat(),
        "Floating rate day count convention-leg 1": "A004",
        "Floating rate day count convention-leg 2": "A004",
        "Floating rate payment frequency period-Leg 1": "MNTH",
        "Floating rate payment frequency period multiplier-Leg 1": "3",
        "Floating rate payment frequency period-Leg 2": "MNTH",
        "Floating rate payment frequency period multiplier-Leg 2": "3",
        "Cleared": "N",
    }


def test_swap_valuation_aextract_fetches_both_legs_fixings_for_a_seasoned_spread_trade(
    monkeypatch,
):
    from openbb_cftc.utils import store

    store.write_search_records("IR", "2026-07-15", [_seasoned_cross_currency_print()])

    async def _rates(report_date, currencies, use_cache=True):
        return [
            _seasoned_cross_currency_print(),
            _seasoned_cross_currency_print("XC2", "-0.0004"),
        ], DATE.isoformat()

    windows: list = []

    async def _fixings(index, start_date, end_date, use_cache=True):
        windows.append((index, start_date, end_date))
        return {start_date: 0.02}

    async def _forex_slice(asset_class, report_date, use_cache=True):
        assert asset_class == "forex"
        return [_fx_spot_print(as_of=DATE)]

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _forex_slice)
    monkeypatch.setattr("openbb_cftc.utils.fixings.get_fixings", _fixings)

    trade, _, _, fixings, currency, _ = asyncio.run(
        CftcSwapValuationFetcher.aextract_data(
            CftcSwapValuationQueryParams(
                currency="GBP", dissemination_identifier="XC1"
            ),
            None,
        )
    )

    assert currency == "EUR"
    assert {index for index, _, _ in windows} == {"ESTR", "SOFR"}
    assert set(fixings.keys()) == {"spread", "other", "spot"}
    assert fixings["spread"] and fixings["other"]
    assert fixings["spot"] == pytest.approx(0.874)


def test_swap_valuation_transform_computes_real_realized_carry_for_a_seasoned_spread_trade(
    monkeypatch,
):
    from openbb_cftc.utils.swap import extract_spread_trade

    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.rate_discount_factor", _flat_curve(0.03)
    )
    comparables = [
        _seasoned_cross_currency_print("XC1", "-0.0003"),
        _seasoned_cross_currency_print("XC2", "-0.0005"),
        _seasoned_cross_currency_print("XC3", "-0.0007"),
    ]
    trade = extract_spread_trade(comparables[0], DATE)
    assert trade is not None
    fixings = {
        "spread": {trade["effective_date"]: 0.02},
        "other": {trade["effective_date"]: 0.04},
        "spot": 0.88,
    }
    result = CftcSwapValuationFetcher.transform_data(
        CftcSwapValuationQueryParams(currency="EUR"),
        (trade, comparables, DATE.isoformat(), fixings, "EUR", DATE.isoformat()),
    )
    m = result.metadata

    assert m["accrued_carry"] is not None
    assert m["spread_leg_accrued"] > 0
    assert m["other_leg_accrued"] > 0
    assert "carry_note" not in m


def test_swap_valuation_flags_a_seasoned_spread_trade_missing_either_legs_fixings(
    monkeypatch,
):
    from openbb_cftc.utils.swap import extract_spread_trade

    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.rate_discount_factor", _flat_curve(0.03)
    )
    comparables = [
        _seasoned_cross_currency_print("XC1", "-0.0003"),
        _seasoned_cross_currency_print("XC2", "-0.0005"),
        _seasoned_cross_currency_print("XC3", "-0.0007"),
    ]
    trade = extract_spread_trade(comparables[0], DATE)
    assert trade is not None
    result = CftcSwapValuationFetcher.transform_data(
        CftcSwapValuationQueryParams(currency="EUR"),
        (trade, comparables, DATE.isoformat(), {"spot": 0.88}, "EUR", DATE.isoformat()),
    )
    m = result.metadata

    assert m["accrued_carry"] is None
    assert "not available" in m["carry_note"]


def test_swap_valuation_flags_a_seasoned_spread_trade_with_incomplete_fixings(
    monkeypatch,
):
    from openbb_cftc.utils.swap import extract_spread_trade

    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.rate_discount_factor", _flat_curve(0.03)
    )
    comparables = [
        _seasoned_cross_currency_print("XC1", "-0.0003"),
        _seasoned_cross_currency_print("XC2", "-0.0005"),
        _seasoned_cross_currency_print("XC3", "-0.0007"),
    ]
    trade = extract_spread_trade(comparables[0], DATE)
    assert trade is not None
    late = DATE - timedelta(days=10)
    fixings = {"spread": {late: 0.02}, "other": {late: 0.04}, "spot": 0.88}
    result = CftcSwapValuationFetcher.transform_data(
        CftcSwapValuationQueryParams(currency="EUR"),
        (trade, comparables, DATE.isoformat(), fixings, "EUR", DATE.isoformat()),
    )
    m = result.metadata

    assert m["accrued_carry"] is None
    assert "do not cover" in m["carry_note"]


def test_swap_valuation_aextract_skips_an_unrecognized_index_for_a_spread_trade(
    monkeypatch,
):
    from openbb_cftc.utils import store

    tenor_basis = {
        "Dissemination Identifier": "TB1",
        "UPI FISN": "NA/Swap Flt Flt EUR",
        "UPI Underlier Name": "OTHER vs EUR-EuroSTR-OIS Compound",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Notional currency-Leg 1": "EUR",
        "Notional currency-Leg 2": "EUR",
        "Notional amount-Leg 1": "100000000",
        "Notional amount-Leg 2": "100000000",
        "Spread-Leg 1": "0.0003",
        "Spread-Leg 2": "",
        "Effective Date": (DATE - timedelta(days=270)).isoformat(),
        "Expiration Date": (DATE + timedelta(days=825)).isoformat(),
        "Cleared": "Y",
    }
    store.write_search_records("IR", "2026-07-15", [tenor_basis])

    async def _rates(report_date, currencies, use_cache=True):
        return [tenor_basis], DATE.isoformat()

    windows: list = []

    async def _fixings(index, start_date, end_date, use_cache=True):
        windows.append(index)
        return {start_date: 0.02}

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)
    monkeypatch.setattr("openbb_cftc.utils.fixings.get_fixings", _fixings)

    trade, _, _, fixings, _, _ = asyncio.run(
        CftcSwapValuationFetcher.aextract_data(
            CftcSwapValuationQueryParams(
                currency="EUR", dissemination_identifier="TB1"
            ),
            None,
        )
    )

    assert trade["spread_index"] is None
    assert windows == ["ESTR"]
    assert fixings == {"spread": {}, "other": {DATE - timedelta(days=270): 0.02}}


def _basis_print(identifier="B1", spread_leg1="-0.0002625"):
    effective = DATE + timedelta(days=2)

    return {
        "Dissemination Identifier": identifier,
        "UPI FISN": "NA/Swap Flt Flt USD",
        "UPI Underlier Name": "USD-Federal Funds-OIS Compound vs USD-SOFR-OIS Compound",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Notional currency-Leg 1": "USD",
        "Notional currency-Leg 2": "USD",
        "Notional amount-Leg 1": "500000000",
        "Notional amount-Leg 2": "500000000",
        "Spread-Leg 1": spread_leg1,
        "Spread-Leg 2": "",
        "Effective Date": effective.isoformat(),
        "Expiration Date": (effective + timedelta(days=365)).isoformat(),
        "Floating rate day count convention-leg 1": "A004",
        "Floating rate payment frequency period-Leg 1": "MNTH",
        "Floating rate payment frequency period multiplier-Leg 1": "3",
        "Cleared": "I",
    }


def test_swap_valuation_transform_prices_a_basis_trade(monkeypatch):
    from openbb_cftc.utils.swap import extract_spread_trade

    monkeypatch.setattr(
        "openbb_cftc.utils.fx_vol.rate_discount_factor", _flat_curve(0.04)
    )
    comparables = [
        _basis_print("B1", "-0.0002625"),
        _basis_print("B2", "-0.0004"),
        _basis_print("B3", "-0.0005"),
    ]
    trade = extract_spread_trade(comparables[0], DATE)
    assert trade is not None
    result = CftcSwapValuationFetcher.transform_data(
        CftcSwapValuationQueryParams(currency="USD"),
        (trade, comparables, DATE.isoformat(), {}, "USD", DATE.isoformat()),
    )
    m = result.metadata

    assert m["dissemination_identifier"] == "B1"
    assert m["trade_type"] == "basis"
    assert m["reference_trade_count"] == 3
    assert "other_currency" not in m
    assert "exchange_pv" not in m
    assert m["fixed_rate"] == pytest.approx(-0.02625)
    assert m["par_rate"] == pytest.approx(-0.04)
    assert sum(r.fixed_pv for r in result.result) == pytest.approx(m["fixed_leg_pv"])


def test_swap_valuation_aextract_raises_when_no_spot_can_be_established(monkeypatch):
    from openbb_core.provider.utils.errors import EmptyDataError

    from openbb_cftc.utils import store

    store.write_search_records("IR", "2026-07-15", [_cross_currency_print()])

    async def _rates(report_date, currencies, use_cache=True):
        return [_cross_currency_print()], "2026-07-17"

    async def _empty_forex(asset_class, report_date, use_cache=True):
        return []

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _empty_forex)

    with pytest.raises(EmptyDataError, match="spot could be"):
        asyncio.run(
            CftcSwapValuationFetcher.aextract_data(
                CftcSwapValuationQueryParams(
                    currency="EUR", dissemination_identifier="XC1"
                ),
                None,
            )
        )


def test_economics_metadata_folds_an_upfront_into_the_net():
    from openbb_cftc.models.swap_valuation import _economics_metadata

    trade = {
        "other_payments": [
            {"type": "UFRO", "amount": 1000.0, "currency": "USD"},
            {"type": "UFRO", "amount": 50.0, "currency": "EUR"},
            {"type": "PEXH", "amount": 5.0, "currency": "USD"},
        ],
        "package_indicator": True,
        "package_price": {"amount": -2000.0, "currency": "USD"},
    }
    metadata = {
        "currency": "USD",
        "npv": 900.0,
        "settled_carry": 60.0,
        "accrued_carry": 40.0,
    }
    _economics_metadata(trade, CftcSwapValuationQueryParams(side="pay"), metadata)

    assert metadata["upfront_amount"] == 1000.0
    assert metadata["entry_cost"] == 1000.0
    assert metadata["net_pnl"] == 0.0
    assert metadata["winning_side"] == "flat"
    assert metadata["package_indicator"] is True
    assert metadata["package_price"] == -2000.0
    assert metadata["package_price_currency"] == "USD"
    assert "other_payment_note" in metadata
    assert len(metadata["other_payments"]) == 3


def test_economics_metadata_signs_the_entry_cost_against_a_negative_npv():
    from openbb_cftc.models.swap_valuation import _economics_metadata

    trade = {"other_payments": [{"type": "UFRO", "amount": 500.0, "currency": "USD"}]}
    metadata = {"currency": "USD", "npv": -400.0, "realized_carry": None}
    _economics_metadata(trade, CftcSwapValuationQueryParams(side="receive"), metadata)

    assert metadata["entry_cost"] == -500.0
    assert metadata["net_pnl"] == 100.0
    assert metadata["winning_side"] == "receive"
    assert "other_payment_note" not in metadata


def test_economics_metadata_without_payments_tracks_npv_and_carry():
    from openbb_cftc.models.swap_valuation import _economics_metadata

    metadata = {
        "currency": "USD",
        "npv": -10.0,
        "settled_carry": 1.0,
        "accrued_carry": 3.0,
    }
    _economics_metadata({}, CftcSwapValuationQueryParams(side="pay"), metadata)

    assert "upfront_amount" not in metadata
    assert "other_payments" not in metadata
    assert "package_indicator" not in metadata
    assert metadata["net_pnl"] == -6.0
    assert metadata["winning_side"] == "receive"


def _inflation_slice(slice_records):
    return [
        r
        for r in slice_records
        if (r.get("UPI FISN") or "").strip()
        in ("NA/Swap Infl Idx GBP", "NA/Swap OIS GBP")
    ]


def test_swap_valuation_aextract_routes_an_inflation_print(monkeypatch, slice_records):
    from openbb_cftc.utils import store

    infl = next(
        r
        for r in slice_records
        if (r.get("UPI FISN") or "").strip() == "NA/Swap Infl Idx GBP"
    )
    store.write_search_records("IR", "2026-07-15", [infl])
    levels = {}
    level = 100.0
    for year in (2024, 2025, 2026):
        for month in range(1, 13):
            levels[date(year, month, 1)] = level
            level *= 1.0025

    async def _rates(report_date, currencies, use_cache=True):
        return _inflation_slice(slice_records), "2026-07-15"

    async def _index(index, use_cache=True):
        assert index == "UKRPI"
        return levels

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)
    monkeypatch.setattr("openbb_cftc.utils.inflation.get_inflation_index", _index)

    query = CftcSwapValuationQueryParams(
        currency="GBP",
        dissemination_identifier=infl["Dissemination Identifier"],
    )
    data = asyncio.run(CftcSwapValuationFetcher.aextract_data(query, None))
    trade, _, _, fixings, currency, _ = data

    assert trade["trade_type"] == "inflation"
    assert currency == "GBP"
    assert fixings["levels"] is levels

    result = CftcSwapValuationFetcher.transform_data(query, data)
    meta = result.metadata

    assert meta["trade_type"] == "inflation"
    assert meta["inflation_index"] == "UKRPI"
    assert meta["underlier"] == "UK-RPI"
    assert meta["realized_ratio"] is not None
    assert meta["projected_ratio"] > 1.0
    assert meta["index_ratio"] == pytest.approx(
        meta["realized_ratio"] * meta["projected_ratio"], rel=1e-6
    )
    assert meta["reference_trade_count"] == 1
    assert meta["accrued_carry"] is None
    assert result.result[0].index_ratio is not None
    assert result.result[0].realized_ratio is not None
    assert result.result[0].projected_ratio is not None


def test_swap_valuation_inflation_survives_an_index_outage(monkeypatch, slice_records):
    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_cftc.utils import store

    infl = next(
        r
        for r in slice_records
        if (r.get("UPI FISN") or "").strip() == "NA/Swap Infl Idx GBP"
    )
    store.write_search_records("IR", "2026-07-15", [infl])

    async def _rates(report_date, currencies, use_cache=True):
        return _inflation_slice(slice_records), "2026-07-15"

    async def _broken(index, use_cache=True):
        raise OpenBBError("publisher down")

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)
    monkeypatch.setattr("openbb_cftc.utils.inflation.get_inflation_index", _broken)

    query = CftcSwapValuationQueryParams(
        currency="GBP",
        dissemination_identifier=infl["Dissemination Identifier"],
    )
    data = asyncio.run(CftcSwapValuationFetcher.aextract_data(query, None))

    assert data[3]["levels"] == {}


def test_swap_valuation_rejects_an_unpriceable_inflation_print(
    monkeypatch, slice_records
):
    from openbb_core.provider.utils.errors import EmptyDataError

    from openbb_cftc.utils import store

    infl = next(
        r
        for r in slice_records
        if (r.get("UPI FISN") or "").strip() == "NA/Swap Infl Idx GBP"
    )
    store.write_search_records("IR", "2026-07-15", [infl])

    async def _rates(report_date, currencies, use_cache=True):
        return _inflation_slice(slice_records), "2026-07-15"

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)

    query = CftcSwapValuationQueryParams(
        currency="GBP",
        dissemination_identifier=infl["Dissemination Identifier"],
        min_notional=1e12,
    )

    with pytest.raises(EmptyDataError, match="zero-coupon inflation terms"):
        asyncio.run(CftcSwapValuationFetcher.aextract_data(query, None))


def _no_inflation(slice_records):
    return [
        r
        for r in slice_records
        if (r.get("UPI FISN") or "").strip() != "NA/Swap Infl Idx GBP"
    ]


def test_swap_valuation_walks_back_to_a_day_that_has_breakevens(
    monkeypatch, slice_records
):
    from openbb_cftc.utils import store

    infl = next(
        r
        for r in slice_records
        if (r.get("UPI FISN") or "").strip() == "NA/Swap Infl Idx GBP"
    )
    store.write_search_records("IR", "2026-07-15", [infl])
    seen: list = []

    async def _rates(report_date, currencies, use_cache=True):
        return _no_inflation(slice_records), "2026-07-17"

    async def _viable(asset_class, is_viable, use_cache=True, end_date=None):
        seen.append(end_date)
        return slice_records, "2026-07-15"

    async def _index(index, use_cache=True):
        return {}

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_latest_viable_slice", _viable)
    monkeypatch.setattr("openbb_cftc.utils.inflation.get_inflation_index", _index)

    query = CftcSwapValuationQueryParams(
        currency="GBP",
        dissemination_identifier=infl["Dissemination Identifier"],
    )
    data = asyncio.run(CftcSwapValuationFetcher.aextract_data(query, None))
    fixings = data[3]

    assert seen == ["2026-07-17"]
    assert fixings["breakeven_date"] == "2026-07-15"
    assert fixings["breakeven_records"] is slice_records


def test_swap_valuation_survives_a_failed_breakeven_walk_back(
    monkeypatch, slice_records
):
    from openbb_core.app.model.abstract.error import OpenBBError
    from openbb_core.provider.utils.errors import EmptyDataError

    from openbb_cftc.utils import store

    infl = next(
        r
        for r in slice_records
        if (r.get("UPI FISN") or "").strip() == "NA/Swap Infl Idx GBP"
    )
    store.write_search_records("IR", "2026-07-15", [infl])

    async def _rates(report_date, currencies, use_cache=True):
        return _no_inflation(slice_records), "2026-07-17"

    async def _no_viable(*args, **kwargs):
        raise OpenBBError("no day held usable data")

    async def _index(index, use_cache=True):
        return {}

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_latest_viable_slice", _no_viable)
    monkeypatch.setattr("openbb_cftc.utils.inflation.get_inflation_index", _index)

    query = CftcSwapValuationQueryParams(
        currency="GBP",
        dissemination_identifier=infl["Dissemination Identifier"],
    )
    data = asyncio.run(CftcSwapValuationFetcher.aextract_data(query, None))

    assert "breakeven_records" not in data[3]

    with pytest.raises(EmptyDataError, match="inflation prints were disseminated"):
        CftcSwapValuationFetcher.transform_data(query, data)
