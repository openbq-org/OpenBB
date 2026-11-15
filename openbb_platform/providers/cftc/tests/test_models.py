import asyncio
from datetime import UTC, date, timedelta

import pytest
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_cftc.models.cds_index_trades import (
    CftcCdsIndexTradesFetcher,
    CftcCdsIndexTradesQueryParams,
)
from openbb_cftc.models.cot import CftcCotFetcher, CftcCotQueryParams
from openbb_cftc.models.cot_search import CftcCotSearchFetcher, CftcCotSearchQueryParams
from openbb_cftc.models.fx_forward_points import (
    CftcFxForwardPointsData,
    CftcFxForwardPointsFetcher,
    CftcFxForwardPointsQueryParams,
)
from openbb_cftc.models.fx_implied_vol import (
    CftcFxImpliedVolData,
    CftcFxImpliedVolFetcher,
    CftcFxImpliedVolQueryParams,
)
from openbb_cftc.models.ois_curve import (
    CftcOisCurveData,
    CftcOisCurveFetcher,
    CftcOisCurveQueryParams,
)
from openbb_cftc.models.ois_curve_history import (
    CftcOisCurveHistoryFetcher,
    CftcOisCurveHistoryQueryParams,
)
from openbb_cftc.models.ois_forward_curve import (
    CftcOisForwardCurveData,
    CftcOisForwardCurveFetcher,
    CftcOisForwardCurveQueryParams,
)
from openbb_cftc.models.swap_trades import (
    CftcSwapTradesData,
    CftcSwapTradesFetcher,
    CftcSwapTradesQueryParams,
)

TRADE_DATE = date(2026, 7, 15)


@pytest.fixture(name="patch_source")
def patch_source_fixture(monkeypatch, slice_records, fx_records):

    async def _dates(asset_class):
        return ["2026-07-14", "2026-07-15"]

    async def _slice(asset_class, report_date, use_cache=True):
        return fx_records if asset_class == "forex" else slice_records

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_available_dates", _dates)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _slice)


@pytest.fixture(name="patch_search")
def patch_search_fixture(monkeypatch, chf_search_records):
    calls: list = []

    async def _search(asset_class, **kwargs):
        calls.append({"asset_class": asset_class, **kwargs})
        return chf_search_records

    monkeypatch.setattr("openbb_cftc.utils.search.search_trades", _search)

    return calls


@pytest.mark.parametrize(
    ("fetcher", "query_cls", "params"),
    [
        (CftcCdsIndexTradesFetcher, CftcCdsIndexTradesQueryParams, {}),
        (CftcCotFetcher, CftcCotQueryParams, {"code": "088691"}),
        (CftcCotSearchFetcher, CftcCotSearchQueryParams, {"query": "gold"}),
        (CftcSwapTradesFetcher, CftcSwapTradesQueryParams, {}),
        (CftcOisCurveFetcher, CftcOisCurveQueryParams, {}),
        (CftcOisCurveHistoryFetcher, CftcOisCurveHistoryQueryParams, {}),
        (CftcOisForwardCurveFetcher, CftcOisForwardCurveQueryParams, {}),
        (CftcFxForwardPointsFetcher, CftcFxForwardPointsQueryParams, {}),
        (CftcFxImpliedVolFetcher, CftcFxImpliedVolQueryParams, {}),
    ],
)
def test_transform_query(fetcher, query_cls, params):
    assert isinstance(fetcher.transform_query(params), query_cls)


@pytest.mark.parametrize(
    "model",
    [
        CftcOisCurveData,
        CftcOisForwardCurveData,
        CftcFxForwardPointsData,
        CftcFxImpliedVolData,
        CftcSwapTradesData,
    ],
)
def test_widget_config_survives_the_serialization_schema(model):
    schema = model.model_json_schema(mode="serialization")
    props = schema.get("properties", {})

    assert props, f"{model.__name__} exposes no serialization-schema properties"
    assert any("x-widget_config" in prop for prop in props.values()), (
        f"{model.__name__} lost its x-widget_config in the serialization schema"
    )


def test_cot_search_query_defaults_are_none():
    query = CftcCotSearchQueryParams()

    assert query.query is None
    assert query.code is None


def test_currency_and_pair_params_accept_any_case():
    assert CftcOisCurveQueryParams(currency="usd").currency == "USD"
    assert CftcOisCurveHistoryQueryParams(currency="chf").currency == "CHF"
    assert CftcFxForwardPointsQueryParams(pair="eurUSD").pair == "EURUSD"
    assert CftcSwapTradesQueryParams(asset_class="RATES").asset_class == "rates"


def test_swap_trades_data_normalizes_values():
    model = CftcSwapTradesData.model_validate(
        {
            "Dissemination Identifier": "4217413061000000101",
            "Notional amount-Leg 1": "79,501,573,807+",
            "Fixed rate-Leg 1": "0.04",
            "Product name": "",
            "Effective Date": "2026-07-17",
        }
    )

    assert model.notional_amount_leg_1 == 79501573807.0
    assert model.is_capped is True
    assert model.product_name is None
    assert model.effective_date == date(2026, 7, 17)


def test_swap_trades_data_passes_through_non_str():
    model = CftcSwapTradesData.model_validate(
        {"Notional amount-Leg 1": 100.0, "Asset Class": "IR", "Cleared": None}
    )

    assert model.notional_amount_leg_1 == 100.0
    assert model.asset_class == "IR"
    assert model.cleared is None
    assert model.is_capped is False


def test_swap_trades_data_passes_non_dict_payloads_through():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="valid dictionary"):
        CftcSwapTradesData.model_validate(["not", "a", "mapping"])


def test_swap_trades_data_drops_a_bare_cap_marker():
    model = CftcSwapTradesData.model_validate({"Notional amount-Leg 1": "+"})

    assert model.notional_amount_leg_1 is None
    assert model.is_capped is True


def test_swap_trades_data_qualifies_the_identifier_out_of_double_range():
    model = CftcSwapTradesData.model_validate(
        {"Dissemination Identifier": "4402189634000000101", "Asset Class": "IR"}
    )

    assert model.trade_key == "IR:4402189634000000101"
    assert not model.trade_key.isdigit()

    bare = model.trade_key.split(":", 1)[1]

    assert float(bare) != int(bare)


def test_swap_trades_data_qualifies_an_identifier_without_an_asset_class():
    model = CftcSwapTradesData.model_validate(
        {"Dissemination Identifier": "4402189634000000101"}
    )

    assert model.trade_key == "NA:4402189634000000101"


def test_swap_trades_data_has_no_trade_key_without_an_identifier():
    assert CftcSwapTradesData.model_validate({"Asset Class": "IR"}).trade_key is None


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("IR:4402189634000000101", "4402189634000000101"),
        ("FX:4402190022000000101", "4402190022000000101"),
        ("4402189634000000101", "4402189634000000101"),
        ("  4402189634000000101  ", "4402189634000000101"),
        (None, None),
    ],
)
def test_swap_valuation_accepts_a_qualified_trade_key(given, expected):
    from openbb_cftc.models.swap_valuation import CftcSwapValuationQueryParams

    query = CftcSwapValuationQueryParams(dissemination_identifier=given)

    assert query.dissemination_identifier == expected


def test_swap_trades_fetcher_filters(patch_source):
    records = asyncio.run(
        CftcSwapTradesFetcher.aextract_data(
            CftcSwapTradesQueryParams(
                date=TRADE_DATE,
                currency="USD",
                underlier="SOFR",
                upi_fisn="Swap OIS",
                action_type="NEWT",
            ),
            None,
        )
    )

    assert records
    assert all(r["Notional currency-Leg 1"] == "USD" for r in records)
    assert all("SOFR" in r["UPI Underlier Name"].upper() for r in records)


def test_swap_trades_fetcher_notional_bounds_and_limit(patch_source):
    records = asyncio.run(
        CftcSwapTradesFetcher.aextract_data(
            CftcSwapTradesQueryParams(
                date=TRADE_DATE, min_notional=1e7, max_notional=5e7, limit=5
            ),
            None,
        )
    )

    assert len(records) == 5


def _priceable(**overrides):
    record = {
        "Action type": "NEWT",
        "Event type": "TRAD",
        "UPI FISN": "NA/Swap OIS USD",
        "Notional currency-Leg 1": "USD",
        "Fixed rate-Leg 1": "0.04",
        "Effective Date": "2020-01-01",
        "Expiration Date": "2099-01-01",
    }
    record.update(overrides)

    return record


async def _passthrough_priceable(filtered, day_records, day, query):
    return filtered


def test_swap_trades_fetcher_skips_records_without_a_notional(monkeypatch):
    priced = _priceable(**{"Notional amount-Leg 1": "20,000,000"})
    unpriced = {**priced, "Notional amount-Leg 1": ""}

    async def _dates(*args, **kwargs):
        return ["2026-07-15"]

    async def _slice(*args, **kwargs):
        return [unpriced, priced]

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_available_dates", _dates)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _slice)
    monkeypatch.setattr(
        "openbb_cftc.models.swap_trades._keep_priceable", _passthrough_priceable
    )

    records = asyncio.run(
        CftcSwapTradesFetcher.aextract_data(
            CftcSwapTradesQueryParams(min_notional=1e6), None
        )
    )

    assert records == [{**priced, "trade_type": "spot"}]


def _searched_print(day, **overrides):
    record = _priceable(
        **{
            "Unique Product Identifier": "QZXQ4R16245X",
            "Execution Timestamp": f"{day}T14:00:00Z",
            "Dissemination Timestamp": f"{day}T14:00:01Z",
        }
    )
    record.update(overrides)

    return record


def test_swap_trades_ticker_queries_the_search_api_across_the_window(monkeypatch):
    seen: list = []

    async def _search(asset_class, start_date, end_date, **kwargs):
        seen.append((asset_class, start_date, end_date, kwargs))
        return [
            _searched_print("2026-07-14", **{"Cleared": "Y"}),
            _searched_print("2026-07-15", **{"Cleared": "N"}),
        ]

    async def _forbidden_slice(*args, **kwargs):
        raise AssertionError("get_slice ran for a ticker-routed query")

    async def _rates(report_date, currencies, use_cache=True):
        return [], "2026-07-15"

    monkeypatch.setattr("openbb_cftc.utils.search.search_trades", _search)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _forbidden_slice)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)
    monkeypatch.setattr(
        "openbb_cftc.models.swap_trades._keep_priceable", _passthrough_priceable
    )

    records = asyncio.run(
        CftcSwapTradesFetcher.aextract_data(
            CftcSwapTradesQueryParams(
                ticker="qzxq4r16245x",
                currency="USD",
                cleared=True,
                start_date=date(2026, 7, 14),
                end_date=date(2026, 7, 15),
            ),
            None,
        )
    )

    assert [r["Cleared"] for r in records] == ["Y"]
    assert seen == [
        (
            "rates",
            date(2026, 7, 14),
            date(2026, 7, 15),
            {"currency": "USD", "upi": "QZXQ4R16245X", "use_cache": True},
        )
    ]


def test_swap_trades_ticker_without_dates_keeps_the_latest_disseminated_day(
    monkeypatch,
):
    async def _search(asset_class, start_date, end_date, **kwargs):
        return [
            _searched_print("2026-07-14"),
            _searched_print("2026-07-15"),
            _searched_print("2026-07-15"),
        ]

    async def _rates(report_date, currencies, use_cache=True):
        return [], "2026-07-15"

    monkeypatch.setattr("openbb_cftc.utils.search.search_trades", _search)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)
    monkeypatch.setattr(
        "openbb_cftc.models.swap_trades._keep_priceable", _passthrough_priceable
    )

    records = asyncio.run(
        CftcSwapTradesFetcher.aextract_data(
            CftcSwapTradesQueryParams(ticker="QZXQ4R16245X"), None
        )
    )

    assert len(records) == 2
    assert all(r["Dissemination Timestamp"].startswith("2026-07-15") for r in records)


def test_swap_trades_ticker_raises_when_the_search_matches_nothing(monkeypatch):
    async def _search(*args, **kwargs):
        return []

    monkeypatch.setattr("openbb_cftc.utils.search.search_trades", _search)

    with pytest.raises(EmptyDataError, match="No rates transactions matched"):
        asyncio.run(
            CftcSwapTradesFetcher.aextract_data(
                CftcSwapTradesQueryParams(ticker="QZXQ4R16245X"), None
            )
        )


def test_swap_trades_ticker_routes_forex_through_search(monkeypatch):
    seen: list = []

    async def _search(asset_class, start_date, end_date, **kwargs):
        seen.append((asset_class, kwargs.get("upi")))
        return [
            {
                "Action type": "NEWT",
                "UPI FISN": "NA/Fwd EUR USD",
                "Unique Product Identifier": "QZFWDAAAAAAA",
                "Dissemination Timestamp": "2026-07-15T10:00:00Z",
            }
        ]

    async def _forbidden_slice(*args, **kwargs):
        raise AssertionError("get_slice ran for a ticker-routed forex query")

    monkeypatch.setattr("openbb_cftc.utils.search.search_trades", _search)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _forbidden_slice)

    records = asyncio.run(
        CftcSwapTradesFetcher.aextract_data(
            CftcSwapTradesQueryParams(asset_class="forex", ticker="qzfwdaaaaaaa"),
            None,
        )
    )

    assert seen == [("forex", "QZFWDAAAAAAA")]
    assert [r["Unique Product Identifier"] for r in records] == ["QZFWDAAAAAAA"]


def test_apply_filters_drops_a_ticker_the_search_did_not_match_exactly():
    from openbb_cftc.models import swap_trades as st

    wanted = {
        "Action type": "NEWT",
        "UPI FISN": "NA/Fwd EUR USD",
        "Unique Product Identifier": "QZFWDAAAAAAA",
    }
    other = {**wanted, "Unique Product Identifier": "QZFWDBBBBBBB"}
    query = CftcSwapTradesQueryParams(asset_class="forex", ticker="qzfwdaaaaaaa")

    assert st._apply_filters([wanted, other], query) == [wanted]


def test_swap_trades_rejects_an_unpriceable_asset_class():
    from pydantic import ValidationError

    for asset_class in ("credits", "equities", "commodities"):
        with pytest.raises(ValidationError):
            CftcSwapTradesQueryParams(asset_class=asset_class)

    assert CftcSwapTradesQueryParams(asset_class="forex").asset_class == "forex"


def test_swap_trades_ticker_rejects_a_backwards_window():
    with pytest.raises(OpenBBError, match="ends before it starts"):
        asyncio.run(
            CftcSwapTradesFetcher.aextract_data(
                CftcSwapTradesQueryParams(
                    ticker="QZXQ4R16245X",
                    start_date=date(2026, 7, 15),
                    end_date=date(2026, 7, 14),
                ),
                None,
            )
        )


def test_swap_trades_ticker_route_applies_the_priceability_gate(monkeypatch):
    async def _search(asset_class, start_date, end_date, **kwargs):
        return [
            _searched_print("2026-07-15", **{"Notional amount-Leg 1": "20,000,000"})
        ]

    async def _rates(report_date, currencies, use_cache=True):
        return [], "2026-07-15"

    monkeypatch.setattr("openbb_cftc.utils.search.search_trades", _search)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_rates_slice_for", _rates)

    records = asyncio.run(
        CftcSwapTradesFetcher.aextract_data(
            CftcSwapTradesQueryParams(ticker="QZXQ4R16245X"), None
        )
    )

    assert records == []


def test_swap_trades_fetcher_cleared_filter(monkeypatch):
    records = [
        _priceable(**{"Cleared": "Y"}),
        _priceable(**{"Cleared": "I"}),
        _priceable(**{"Cleared": "N"}),
    ]

    async def _dates(*args, **kwargs):
        return ["2026-07-15"]

    async def _slice(*args, **kwargs):
        return records

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_available_dates", _dates)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _slice)
    monkeypatch.setattr(
        "openbb_cftc.models.swap_trades._keep_priceable", _passthrough_priceable
    )

    cleared = asyncio.run(
        CftcSwapTradesFetcher.aextract_data(
            CftcSwapTradesQueryParams(cleared=True), None
        )
    )
    assert [r["Cleared"] for r in cleared] == ["Y", "I"]

    bilateral = asyncio.run(
        CftcSwapTradesFetcher.aextract_data(
            CftcSwapTradesQueryParams(cleared=False), None
        )
    )
    assert [r["Cleared"] for r in bilateral] == ["N"]


def test_classify_rates_swap_rejects_a_non_trad_event():
    from openbb_cftc.models.swap_trades import _classify_rates_swap

    record = _priceable(**{"Event type": "COMP"})

    assert _classify_rates_swap(record, date(2026, 7, 20)) is None


def test_classify_rates_swap_rejects_an_unpriced_leg_with_no_second_currency():
    from openbb_cftc.models.swap_trades import _classify_rates_swap

    record = _priceable(**{"Fixed rate-Leg 1": "", "Fixed rate-Leg 2": ""})

    assert _classify_rates_swap(record, date(2026, 7, 20)) is None


def test_classify_rates_swap_splits_spot_from_forward():
    from openbb_cftc.models.swap_trades import _classify_rates_swap

    today = date(2026, 7, 20)
    spot = _priceable(**{"Effective Date": "2020-01-01"})
    forward = _priceable(**{"Effective Date": "2030-01-01"})

    assert _classify_rates_swap(spot, today) == "spot"
    assert _classify_rates_swap(forward, today) == "forward"


def test_classify_rates_swap_rejects_a_fixed_vs_float_swap_with_no_effective_date():
    from openbb_cftc.models.swap_trades import _classify_rates_swap

    record = _priceable(**{"Effective Date": ""})

    assert _classify_rates_swap(record, date(2026, 7, 20)) is None


def test_classify_rates_swap_identifies_basis_and_cross_currency():
    from openbb_cftc.models.swap_trades import _classify_rates_swap

    today = date(2026, 7, 20)
    basis = _priceable(
        **{
            "UPI FISN": "NA/Swap Flt Flt OIS USD",
            "Fixed rate-Leg 1": "",
            "Notional currency-Leg 2": "USD",
        }
    )
    cross_currency = _priceable(
        **{
            "UPI FISN": "NA/Swap Flt Flt EUR USD",
            "Notional currency-Leg 1": "EUR",
            "Fixed rate-Leg 1": "",
            "Notional currency-Leg 2": "USD",
        }
    )

    assert _classify_rates_swap(basis, today) == "basis"
    assert _classify_rates_swap(cross_currency, today) == "cross_currency"


def test_classify_rates_swap_rejects_a_swaption():
    from openbb_cftc.models.swap_trades import _classify_rates_swap

    record = _priceable(
        **{
            "UPI FISN": "NA/O P Epn Fxd Flt USD",
            "Fixed rate-Leg 1": "",
            "Notional currency-Leg 2": "USD",
        }
    )

    assert _classify_rates_swap(record, date(2026, 7, 20)) is None


def test_swap_trades_trade_type_filter_narrows_the_table(monkeypatch):
    today = date(2026, 7, 20)
    spot = _priceable(**{"Effective Date": "2020-01-01"})
    forward = _priceable(**{"Effective Date": "2030-01-01"})
    basis = _priceable(
        **{
            "UPI FISN": "NA/Swap Flt Flt OIS USD",
            "Fixed rate-Leg 1": "",
            "Notional currency-Leg 2": "USD",
        }
    )
    cross_currency = _priceable(
        **{
            "UPI FISN": "NA/Swap Flt Flt EUR USD",
            "Notional currency-Leg 1": "EUR",
            "Fixed rate-Leg 1": "",
            "Notional currency-Leg 2": "USD",
        }
    )

    async def _dates(*args, **kwargs):
        return [today.isoformat()]

    async def _slice(*args, **kwargs):
        return [spot, forward, basis, cross_currency]

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_available_dates", _dates)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _slice)
    monkeypatch.setattr(
        "openbb_cftc.models.swap_trades._keep_priceable", _passthrough_priceable
    )

    records = asyncio.run(
        CftcSwapTradesFetcher.aextract_data(
            CftcSwapTradesQueryParams(end_date=today, trade_type="cross_currency"),
            None,
        )
    )

    assert len(records) == 1
    assert records[0]["trade_type"] == "cross_currency"
    assert records[0]["UPI FISN"] == "NA/Swap Flt Flt EUR USD"

    all_records = asyncio.run(
        CftcSwapTradesFetcher.aextract_data(
            CftcSwapTradesQueryParams(end_date=today), None
        )
    )

    assert {r["trade_type"] for r in all_records} == {
        "spot",
        "forward",
        "basis",
        "cross_currency",
    }


def test_swap_trades_action_type_filter_applies_outside_rates(monkeypatch):
    forex_newt = {"Action type": "NEWT", "UPI FISN": "NA/Fwd EUR USD"}
    forex_modi = {"Action type": "MODI", "UPI FISN": "NA/Fwd EUR USD"}

    async def _dates(*args, **kwargs):
        return ["2026-07-15"]

    async def _slice(*args, **kwargs):
        return [forex_newt, forex_modi]

    async def _keep(filtered, day_records, day, query):
        return filtered

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_available_dates", _dates)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _slice)
    monkeypatch.setattr("openbb_cftc.models.swap_trades._keep_priceable_forex", _keep)

    records = asyncio.run(
        CftcSwapTradesFetcher.aextract_data(
            CftcSwapTradesQueryParams(asset_class="forex", action_type="NEWT"), None
        )
    )

    assert records == [forex_newt]


def test_swap_trades_fetcher_defaults_to_the_latest_date(patch_source):
    assert asyncio.run(
        CftcSwapTradesFetcher.aextract_data(CftcSwapTradesQueryParams(), None)
    )


def test_swap_trades_fetcher_raises_when_nothing_matches(patch_source):
    with pytest.raises(EmptyDataError, match="No rates transactions matched"):
        asyncio.run(
            CftcSwapTradesFetcher.aextract_data(
                CftcSwapTradesQueryParams(end_date=TRADE_DATE, currency="ZWL"), None
            )
        )


def test_swap_trades_window_concatenates_days_and_limits(patch_source, monkeypatch):
    monkeypatch.setattr(
        "openbb_cftc.models.swap_trades._keep_priceable", _passthrough_priceable
    )
    single = asyncio.run(
        CftcSwapTradesFetcher.aextract_data(
            CftcSwapTradesQueryParams(start_date=TRADE_DATE, end_date=TRADE_DATE), None
        )
    )
    window = asyncio.run(
        CftcSwapTradesFetcher.aextract_data(
            CftcSwapTradesQueryParams(
                start_date=TRADE_DATE - timedelta(days=2), end_date=TRADE_DATE
            ),
            None,
        )
    )
    limited = asyncio.run(
        CftcSwapTradesFetcher.aextract_data(
            CftcSwapTradesQueryParams(
                start_date=TRADE_DATE - timedelta(days=2),
                end_date=TRADE_DATE,
                limit=5,
            ),
            None,
        )
    )

    assert len(window) == 3 * len(single)
    assert len(limited) == 5


def test_keep_priceable_drops_rows_the_valuation_cannot_price(
    slice_records, fx_records, monkeypatch
):
    from openbb_cftc.models import swap_trades as st
    from openbb_cftc.utils.swap import extract_spread_trade, parse_trade_record

    async def _fx(asset_class, report_date, use_cache=True):
        assert asset_class == "forex"
        return fx_records

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _fx)

    no_curve = _priceable(
        **{
            "UPI FISN": "NA/Swap Fxd Flt ZWL",
            "Notional currency-Leg 1": "ZWL",
            "Notional amount-Leg 1": "20,000,000",
        }
    )
    query = CftcSwapTradesQueryParams()
    filtered = st._apply_filters([*slice_records, no_curve], query)

    assert any(r["Notional currency-Leg 1"] == "ZWL" for r in filtered)

    kept = asyncio.run(st._keep_priceable(filtered, slice_records, "2026-07-15", query))

    assert kept
    assert all(r["Notional currency-Leg 1"] != "ZWL" for r in kept)

    today = date(2026, 7, 15)

    for row in kept:
        if row["trade_type"] in ("basis", "cross_currency"):
            assert extract_spread_trade(row, today) is not None
        elif row["trade_type"] == "inflation":
            from openbb_cftc.utils.swap import extract_inflation_trade

            assert extract_inflation_trade(row, today) is not None
        else:
            assert parse_trade_record(row, today) is not None


def test_keep_priceable_drops_forex_rows_the_valuation_cannot_price(monkeypatch):
    from openbb_cftc.models import swap_trades as st

    async def _slice(*args, **kwargs):
        return []

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _slice)

    query = CftcSwapTradesQueryParams(asset_class="forex")
    rows = [{"UPI FISN": "NA/Fwd EUR USD"}]

    assert asyncio.run(st._keep_priceable(rows, rows, "2026-07-15", query)) == []


def test_keep_priceable_forex_returns_nothing_without_a_rates_slice(monkeypatch):
    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_cftc.models import swap_trades as st

    async def _slice(*args, **kwargs):
        raise OpenBBError("no rates slice")

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _slice)

    query = CftcSwapTradesQueryParams(asset_class="forex")
    rows = [{"UPI FISN": "NA/Fwd EUR USD"}]

    assert asyncio.run(st._keep_priceable(rows, rows, "2026-07-15", query)) == []


def test_keep_priceable_drops_cross_currency_when_forex_is_unavailable(
    slice_records, monkeypatch
):
    from openbb_cftc.models import swap_trades as st

    fetches: list = []

    async def _broken(*args, **kwargs):
        fetches.append(args)
        raise OpenBBError("forex source unavailable")

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _broken)

    cross = [{"trade_type": "cross_currency", "UPI FISN": "NA/Swap Flt Flt EUR USD"}]
    kept = asyncio.run(
        st._keep_priceable(
            cross, slice_records, "2026-07-15", CftcSwapTradesQueryParams()
        )
    )

    assert len(fetches) == 1
    assert kept == []

    spot_query = CftcSwapTradesQueryParams(trade_type="spot", currency="USD")
    spot = st._apply_filters(slice_records, spot_query)
    assert spot

    kept_spot = asyncio.run(
        st._keep_priceable(spot, slice_records, "2026-07-15", spot_query)
    )

    assert kept_spot
    assert len(fetches) == 1


def test_curve_ok_persists_a_closed_day_verdict(slice_records, monkeypatch):
    from openbb_cftc.models import swap_trades as st
    from openbb_cftc.utils import fx_vol

    builds: list = []
    real_build = fx_vol.rate_discount_factor

    def _counted(*args, **kwargs):
        builds.append(1)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(fx_vol, "rate_discount_factor", _counted)

    assert st._curve_ok(slice_records, "USD", "2026-07-15", {}) is True
    assert builds == [1]
    assert st._curve_ok(slice_records, "USD", "2026-07-15", {}) is True
    assert builds == [1]

    memo: dict = {}
    assert st._curve_ok(slice_records, "ZWL", "2026-07-15", memo) is False
    assert st._curve_ok(slice_records, "ZWL", "2026-07-15", memo) is False


def test_curve_ok_does_not_persist_todays_verdict(slice_records):
    from datetime import datetime

    from openbb_cftc.models import swap_trades as st
    from openbb_cftc.utils import store

    today = datetime.now(UTC).date().isoformat()

    assert st._curve_ok(slice_records, "ZWL", today, {}) is False
    assert store.get_curve(f"priceable-curve:{today}:ZWL") is None


def test_spot_ok_requires_forex_prints(fx_records):
    from openbb_cftc.models import swap_trades as st
    from openbb_cftc.utils import store

    assert st._spot_ok(None, "EUR", "USD", "2026-07-15", {}) is False
    assert store.get_curve("priceable-spot:2026-07-15:EUR/USD") is None

    assert st._spot_ok(fx_records, "EUR", "USD", "2026-07-15", {}) is True
    assert st._spot_ok(None, "EUR", "USD", "2026-07-15", {}) is True

    memo: dict = {}
    assert st._spot_ok(fx_records, "ZWL", "USD", "2026-07-15", memo) is False
    assert st._spot_ok(fx_records, "ZWL", "USD", "2026-07-15", memo) is False


def test_spot_ok_does_not_persist_todays_verdict(fx_records):
    from datetime import datetime

    from openbb_cftc.models import swap_trades as st
    from openbb_cftc.utils import store

    today = datetime.now(UTC).date().isoformat()

    assert st._spot_ok(fx_records, "ZWL", "USD", today, {}) is False
    assert store.get_curve(f"priceable-spot:{today}:ZWL/USD") is None


def test_priceable_rejects_a_spot_print_missing_terms():
    from openbb_cftc.models import swap_trades as st

    record = {
        "trade_type": "spot",
        "UPI FISN": "NA/Swap OIS USD",
        "Notional currency-Leg 1": "USD",
    }

    assert st._priceable(record, [], "2026-07-15", date(2026, 7, 25), None, {}) is False


def test_priceable_rejects_a_spread_print_without_priceable_legs():
    from openbb_cftc.models import swap_trades as st

    record = {"trade_type": "basis", "UPI FISN": "NA/Swap Flt Flt OIS USD"}

    assert st._priceable(record, [], "2026-07-15", date(2026, 7, 25), None, {}) is False


def test_priceable_rejects_a_basis_print_without_same_day_references(
    slice_records, monkeypatch
):
    from openbb_cftc.models import swap_trades as st
    from openbb_cftc.utils import swap

    monkeypatch.setattr(
        swap,
        "extract_spread_trade",
        lambda record, day, min_notional=0.0: {
            "currency": "USD",
            "other_currency": None,
            "underlier": "NO SUCH INDEX",
            "trade_type": "basis",
            "spread_leg": 1,
        },
    )

    record = {"trade_type": "basis"}

    assert (
        st._priceable(record, slice_records, "2026-07-15", date(2026, 7, 15), None, {})
        is False
    )


def test_priceable_gates_a_cross_currency_print_on_curves_and_spot(
    slice_records, fx_records, monkeypatch
):
    from openbb_cftc.models import swap_trades as st
    from openbb_cftc.utils import swap

    trade = {
        "currency": "USD",
        "other_currency": "EUR",
        "underlier": "EUR USD",
        "trade_type": "cross_currency",
        "spread_leg": 1,
    }
    monkeypatch.setattr(
        swap, "extract_spread_trade", lambda record, day, min_notional=0.0: trade
    )

    record = {"trade_type": "cross_currency"}

    assert (
        st._priceable(
            record, slice_records, "2026-07-15", date(2026, 7, 15), fx_records, {}
        )
        is True
    )

    trade["other_currency"] = "ZWL"

    assert (
        st._priceable(
            record, slice_records, "2026-07-15", date(2026, 7, 15), fx_records, {}
        )
        is False
    )


def test_swap_trades_window_skips_an_unpublished_day(monkeypatch, slice_records):
    from openbb_cftc.models.swap_trades import _apply_filters

    async def _slice(asset_class, report_date, use_cache=True):
        if report_date == "2026-07-14":
            raise EmptyDataError("No PPD file published.")
        return slice_records

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _slice)
    query = CftcSwapTradesQueryParams(
        start_date=TRADE_DATE - timedelta(days=1), end_date=TRADE_DATE
    )
    records = asyncio.run(CftcSwapTradesFetcher.aextract_data(query, None))

    assert len(records) == len(_apply_filters(slice_records, query))


def test_swap_trades_rejects_an_inverted_window(patch_source):
    with pytest.raises(OpenBBError, match="ends before it starts"):
        asyncio.run(
            CftcSwapTradesFetcher.aextract_data(
                CftcSwapTradesQueryParams(
                    start_date=TRADE_DATE, end_date=TRADE_DATE - timedelta(days=3)
                ),
                None,
            )
        )


def test_swap_trades_transform_data(patch_source, slice_records):
    result = CftcSwapTradesFetcher.transform_data(
        CftcSwapTradesQueryParams(), slice_records[:3]
    )

    assert len(result) == 3
    assert all(isinstance(r, CftcSwapTradesData) for r in result)


def test_ois_curve_fetcher_usd(patch_source):
    query = CftcOisCurveQueryParams(date=TRADE_DATE, source="slice", min_trades=5)
    data = asyncio.run(CftcOisCurveFetcher.aextract_data(query, None))
    result = CftcOisCurveFetcher.transform_data(query, data)

    assert result.metadata["source"] == "slice"
    assert result.metadata["benchmark"] == "SOFR"
    assert result.metadata["central_bank"] == "Federal Reserve"
    assert result.metadata["curve_date"] == "2026-07-15"
    assert result.metadata["lookback_days"] is None
    assert all(isinstance(n, CftcOisCurveData) for n in result.result)

    ten_year = next(n for n in result.result if n.tenor == "10Y")
    assert ten_year.currency == "USD"
    assert ten_year.benchmark == "SOFR"
    assert ten_year.index == "10Y"
    assert ten_year.curve_type == "par"
    assert ten_year.rate == pytest.approx(4.13782, abs=5e-5)
    assert ten_year.discount_factor == pytest.approx(0.6616279, abs=5e-7)

    assert all(n.as_of_date == TRADE_DATE for n in result.result)
    assert all(n.staleness_days == 0 for n in result.result)


def test_ois_curve_slice_walks_back_to_a_priceable_day(monkeypatch, slice_records):
    from openbb_cftc.utils.constants import SOFR_OIS_FISN

    forward_only = [
        {
            "UPI FISN": SOFR_OIS_FISN,
            "Action type": "NEWT",
            "Event type": "TRAD",
            "Notional currency-Leg 1": "USD",
            "Fixed rate-Leg 1": "0.04",
            "Effective Date": "2026-08-19",
            "Expiration Date": "2027-08-19",
            "Notional amount-Leg 1": "50,000,000",
        }
    ]

    async def _dates(asset_class):
        return ["2026-07-16", "2026-07-17", "2026-07-18", "2026-07-19"]

    async def _slice(asset_class, report_date, use_cache=True):
        if report_date == "2026-07-19":
            return forward_only
        if report_date == "2026-07-18":
            return []
        return slice_records

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_available_dates", _dates)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _slice)

    query = CftcOisCurveQueryParams(
        source="slice", date=date(2026, 7, 19), lookback_days=7, min_trades=5
    )
    data = asyncio.run(CftcOisCurveFetcher.aextract_data(query, None))
    result = CftcOisCurveFetcher.transform_data(query, data)

    assert data[1] == "2026-07-17"
    assert result.metadata["curve_date"] == "2026-07-17"
    assert result.result


def test_ois_curve_slice_raises_when_nothing_priceable_in_window(monkeypatch):
    from openbb_core.app.model.abstract.error import OpenBBError

    async def _dates(asset_class):
        return ["2026-07-17", "2026-07-18", "2026-07-19"]

    async def _slice(asset_class, report_date, use_cache=True):
        return []

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_available_dates", _dates)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _slice)

    query = CftcOisCurveQueryParams(source="slice", lookback_days=3)

    with pytest.raises(OpenBBError, match="held usable data"):
        asyncio.run(CftcOisCurveFetcher.aextract_data(query, None))


def test_ois_curve_type_selects_the_variant_in_rate(patch_source):
    common = {"date": TRADE_DATE, "source": "slice", "min_trades": 5}

    def curve(curve_type):
        query = CftcOisCurveQueryParams(**common, curve_type=curve_type)
        data = asyncio.run(CftcOisCurveFetcher.aextract_data(query, None))
        result = CftcOisCurveFetcher.transform_data(query, data)
        return {n.tenor: n for n in result.result}, result.metadata

    par, par_meta = curve("par")
    zero, _ = curve("zero")

    assert par_meta["curve_type"] == "par"
    assert all(n.curve_type == "par" for n in par.values())
    assert par["10Y"].rate == pytest.approx(4.13782, abs=5e-5)

    assert zero["10Y"].curve_type == "zero"
    assert zero["10Y"].rate > par["10Y"].rate

    assert not hasattr(par["10Y"], "par_rate")
    assert set(par["10Y"].model_dump()) == set(zero["10Y"].model_dump())


def test_ois_curve_fetcher_honors_log_cubic_interpolation(patch_source):
    common = {"date": TRADE_DATE, "source": "slice", "min_trades": 5}
    linear = CftcOisCurveFetcher.transform_data(
        CftcOisCurveQueryParams(**common),
        asyncio.run(
            CftcOisCurveFetcher.aextract_data(CftcOisCurveQueryParams(**common), None)
        ),
    )
    cubic_query = CftcOisCurveQueryParams(**common, interpolation="log_cubic")
    cubic = CftcOisCurveFetcher.transform_data(
        cubic_query,
        asyncio.run(CftcOisCurveFetcher.aextract_data(cubic_query, None)),
    )
    linear_by = {n.tenor: n for n in linear.result}
    cubic_by = {n.tenor: n for n in cubic.result}

    assert cubic_query.interpolation == "log_cubic"
    assert {n.tenor: n.rate for n in cubic.result} == {
        n.tenor: n.rate for n in linear.result
    }
    assert cubic_by["1Y"].discount_factor == pytest.approx(
        linear_by["1Y"].discount_factor, abs=1e-12
    )
    assert cubic_by["10Y"].discount_factor == pytest.approx(
        linear_by["10Y"].discount_factor, abs=5e-4
    )
    assert all(
        n.discount_factor is None or 0.0 < n.discount_factor <= 1.0
        for n in cubic.result
    )


def test_tenor_to_years_maps_labels_and_rejects_unknown():
    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_cftc.utils.constants import tenor_to_years

    assert tenor_to_years("1Y") == pytest.approx(1.0)
    assert tenor_to_years("6m") == pytest.approx(182 / 365)
    assert tenor_to_years("3M") == pytest.approx(91 / 365)

    with pytest.raises(OpenBBError, match="Invalid tenor"):
        tenor_to_years("7M")


def test_ois_curve_observed_index_is_the_maturity_date(patch_source):
    observed = CftcOisCurveQueryParams(
        date=TRADE_DATE, source="slice", granularity="observed", min_trades=1
    )
    obs_result = CftcOisCurveFetcher.transform_data(
        observed, asyncio.run(CftcOisCurveFetcher.aextract_data(observed, None))
    )
    assert all(n.index == n.maturity_date.isoformat() for n in obs_result.result)

    benchmark = CftcOisCurveQueryParams(date=TRADE_DATE, source="slice", min_trades=5)
    bench_result = CftcOisCurveFetcher.transform_data(
        benchmark, asyncio.run(CftcOisCurveFetcher.aextract_data(benchmark, None))
    )
    assert all(n.index == n.tenor for n in bench_result.result)


def test_ois_curve_cleared_filter_drops_uncleared(patch_source):
    common = {"date": TRADE_DATE, "source": "slice", "min_trades": 5}
    everything = CftcOisCurveFetcher.transform_data(
        CftcOisCurveQueryParams(**common),
        asyncio.run(
            CftcOisCurveFetcher.aextract_data(CftcOisCurveQueryParams(**common), None)
        ),
    )
    cleared_query = CftcOisCurveQueryParams(**common, cleared=True)
    cleared = CftcOisCurveFetcher.transform_data(
        cleared_query,
        asyncio.run(CftcOisCurveFetcher.aextract_data(cleared_query, None)),
    )

    assert everything.metadata["cleared_only"] is False
    assert cleared.metadata["cleared_only"] is True
    assert cleared.metadata["trades"] < everything.metadata["trades"]


def test_ois_curve_fetcher_search_is_the_default(patch_search):
    query = CftcOisCurveQueryParams(
        currency="CHF", date=date(2026, 7, 16), min_trades=1
    )
    data = asyncio.run(CftcOisCurveFetcher.aextract_data(query, None))
    result = CftcOisCurveFetcher.transform_data(query, data)

    assert query.source == "search"
    assert result.metadata["source"] == "search"
    assert result.metadata["lookback_days"] == 7
    assert result.metadata["benchmark"] == "SARON"
    assert result.metadata["curve_date"] == "2026-07-16"
    assert result.metadata["freshest_node"] == "2026-07-16"
    assert result.metadata["stalest_node"] < result.metadata["freshest_node"]

    assert {n.staleness_days for n in result.result} != {0}
    assert min(n.rate for n in result.result) < 0


def test_ois_curve_search_window_is_the_lookback(patch_search):
    query = CftcOisCurveQueryParams(
        currency="CHF", date=date(2026, 7, 16), lookback_days=30
    )
    asyncio.run(CftcOisCurveFetcher.aextract_data(query, None))

    assert patch_search[0]["start_date"] == date(2026, 6, 17)
    assert patch_search[0]["end_date"] == date(2026, 7, 16)
    assert patch_search[0]["currency"] == "CHF"
    assert patch_search[0]["upi_short_name"] == "NA/Swap OIS CHF"
    assert patch_search[0]["asset_class"] == "rates"


def test_ois_curve_search_defaults_the_window_to_today(patch_search):
    from datetime import datetime

    asyncio.run(
        CftcOisCurveFetcher.aextract_data(CftcOisCurveQueryParams(currency="CHF"), None)
    )

    assert patch_search[0]["end_date"] == datetime.now(UTC).date()


def test_ois_curve_search_caps_staleness(patch_search):
    base = CftcOisCurveQueryParams(currency="CHF")
    full = CftcOisCurveFetcher.transform_data(
        base, asyncio.run(CftcOisCurveFetcher.aextract_data(base, None))
    )
    capped_query = CftcOisCurveQueryParams(currency="CHF", max_staleness_days=0)
    capped = CftcOisCurveFetcher.transform_data(
        capped_query,
        asyncio.run(CftcOisCurveFetcher.aextract_data(capped_query, None)),
    )

    assert capped.result
    assert all(n.staleness_days == 0 for n in capped.result)
    assert len(capped.result) < len(full.result)


@pytest.mark.parametrize(
    ("currency", "index"),
    [
        ("EUR", "ESTR"),
        ("GBP", "SONIA"),
        ("JPY", "TONA"),
        ("CAD", "CORRA"),
        ("CHF", "SARON"),
        ("MXN", "TIIE"),
        ("SGD", "SORA"),
        ("INR", "MIBOR"),
        ("COP", "IBR"),
        ("ZAR", "ZARONIA"),
        ("CLP", "ICP"),
    ],
)
def test_ois_curve_every_central_bank(patch_source, currency, index):
    query = CftcOisCurveQueryParams(date=TRADE_DATE, currency=currency, source="slice")
    data = asyncio.run(CftcOisCurveFetcher.aextract_data(query, None))
    result = CftcOisCurveFetcher.transform_data(query, data)

    assert result.metadata["benchmark"] == index
    assert result.result

    factors = [
        n.discount_factor for n in result.result if n.discount_factor is not None
    ]
    assert all(a > b for a, b in zip(factors, factors[1:]))
    assert all(n.benchmark == index for n in result.result)


def test_ois_currency_literal_matches_the_index_registry():
    from typing import get_args

    from openbb_cftc.utils.constants import (
        FIXED_FLOAT_CURVE_SPECS,
        OIS_INDICES,
        day_count_basis,
    )

    registry = set(OIS_INDICES)
    fixed_float = set(FIXED_FLOAT_CURVE_SPECS)
    thin = {"AUD", "NZD"}
    offered_by_class = {
        CftcOisCurveQueryParams: (registry - thin) | fixed_float,
        CftcOisForwardCurveQueryParams: registry - thin,
        CftcOisCurveHistoryQueryParams: registry | fixed_float,
    }
    for query_cls, expected in offered_by_class.items():
        offered = set(get_args(query_cls.model_fields["currency"].annotation))
        assert offered == expected, query_cls.__name__

    for currency in ("THB", "ILS", "BRL", "AUD", "NZD"):
        entry = OIS_INDICES[currency]
        assert entry["index"] and entry["central_bank"]
        assert day_count_basis(entry["day_count"], "A004") in (360.0, 365.0)


def test_ois_curve_slice_defaults_to_the_latest_published_date(patch_source):
    _, report_date, anchor = asyncio.run(
        CftcOisCurveFetcher.aextract_data(CftcOisCurveQueryParams(source="slice"), None)
    )

    assert report_date == "2026-07-15"
    assert anchor is None


@pytest.mark.parametrize("lookback", [0, 366])
def test_ois_curve_rejects_a_lookback_outside_the_horizon(lookback):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CftcOisCurveQueryParams(lookback_days=lookback)


def test_ois_curve_accepts_a_full_horizon_lookback():
    assert CftcOisCurveQueryParams(lookback_days=365).lookback_days == 365


def test_ois_curve_history_pivot(patch_source):
    query = CftcOisCurveHistoryQueryParams(
        start_date=date(2026, 7, 14), end_date=TRADE_DATE, min_trades=5
    )
    nodes = asyncio.run(CftcOisCurveHistoryFetcher.aextract_data(query, None))
    result = CftcOisCurveHistoryFetcher.transform_data(query, nodes)

    assert result.metadata["pivot"] is True
    assert result.metadata["index"] == "SOFR"
    assert len(result.result) == 2
    assert result.result[0].tenor_10y == pytest.approx(0.041378, abs=5e-7)
    assert result.result[0].tenor is None


def test_ois_curve_history_flat_and_tenor_filter(patch_source):
    query = CftcOisCurveHistoryQueryParams(
        start_date=date(2026, 7, 14),
        end_date=TRADE_DATE,
        tenor="2y, 10Y",
        pivot=False,
        measure="zero_rate",
        min_trades=5,
    )
    nodes = asyncio.run(CftcOisCurveHistoryFetcher.aextract_data(query, None))
    result = CftcOisCurveHistoryFetcher.transform_data(query, nodes)

    assert {r.tenor for r in result.result} == {"2Y", "10Y"}
    assert all(r.value is not None for r in result.result)
    assert result.metadata["measure"] == "zero_rate"


def test_ois_curve_history_tenor_filter_in_pivot_mode(patch_source):
    query = CftcOisCurveHistoryQueryParams(
        start_date=date(2026, 7, 14), end_date=TRADE_DATE, tenor="10Y", min_trades=5
    )
    nodes = asyncio.run(CftcOisCurveHistoryFetcher.aextract_data(query, None))
    result = CftcOisCurveHistoryFetcher.transform_data(query, nodes)

    assert result.result[0].tenor_10y is not None
    assert result.result[0].tenor_2y is None


def test_ois_curve_history_other_currency(patch_source):
    query = CftcOisCurveHistoryQueryParams(
        currency="EUR", start_date=date(2026, 7, 14), end_date=TRADE_DATE
    )
    nodes = asyncio.run(CftcOisCurveHistoryFetcher.aextract_data(query, None))
    result = CftcOisCurveHistoryFetcher.transform_data(query, nodes)

    assert result.metadata["index"] == "ESTR"
    assert result.result


def test_ois_curve_history_defaults_the_window(patch_source):
    nodes = asyncio.run(
        CftcOisCurveHistoryFetcher.aextract_data(
            CftcOisCurveHistoryQueryParams(min_trades=5), None
        )
    )

    assert {n["date"] for n in nodes} == {date(2026, 7, 14), date(2026, 7, 15)}


def test_ois_curve_history_unmatched_tenor_raises(patch_source):
    query = CftcOisCurveHistoryQueryParams(
        start_date=date(2026, 7, 14), end_date=TRADE_DATE, tenor="99Y", min_trades=5
    )
    nodes = asyncio.run(CftcOisCurveHistoryFetcher.aextract_data(query, None))

    with pytest.raises(EmptyDataError, match="No curve nodes matched"):
        CftcOisCurveHistoryFetcher.transform_data(query, nodes)


def test_ois_curve_history_skips_dates_without_a_curve(monkeypatch, slice_records):

    async def _dates(*args, **kwargs):
        return ["2026-07-14", "2026-07-15"]

    async def _slice(asset_class, report_date, use_cache=True):
        return slice_records if report_date == "2026-07-15" else []

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_available_dates", _dates)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _slice)

    nodes = asyncio.run(
        CftcOisCurveHistoryFetcher.aextract_data(
            CftcOisCurveHistoryQueryParams(
                start_date=date(2026, 7, 14), end_date=TRADE_DATE, min_trades=5
            ),
            None,
        )
    )

    assert {n["date"] for n in nodes} == {date(2026, 7, 15)}


def test_ois_curve_history_raises_without_any_curve(monkeypatch):

    async def _dates(*args, **kwargs):
        return ["2026-07-15"]

    async def _slice(*args, **kwargs):
        return []

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_available_dates", _dates)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _slice)

    with pytest.raises(EmptyDataError, match="could be built"):
        asyncio.run(
            CftcOisCurveHistoryFetcher.aextract_data(
                CftcOisCurveHistoryQueryParams(), None
            )
        )


def test_ois_curve_history_raises_without_published_files(monkeypatch):

    async def _none(*args, **kwargs):
        return []

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_available_dates", _none)

    with pytest.raises(EmptyDataError, match="No PPD interest-rate files"):
        asyncio.run(
            CftcOisCurveHistoryFetcher.aextract_data(
                CftcOisCurveHistoryQueryParams(), None
            )
        )


def test_ois_curve_history_raises_when_window_has_no_files(monkeypatch):

    async def _dates(*args, **kwargs):
        return ["2026-07-15"]

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_available_dates", _dates)

    with pytest.raises(EmptyDataError, match="No PPD files were published"):
        asyncio.run(
            CftcOisCurveHistoryFetcher.aextract_data(
                CftcOisCurveHistoryQueryParams(
                    start_date=date(2020, 1, 1), end_date=date(2020, 2, 1)
                ),
                None,
            )
        )


def test_ois_forward_curve_slice_prices_a_strip(patch_source):
    query = CftcOisForwardCurveQueryParams(
        source="slice", forward_tenor="1Y", forward_step="1Y", min_trades=5
    )
    data = asyncio.run(CftcOisForwardCurveFetcher.aextract_data(query, None))
    result = CftcOisForwardCurveFetcher.transform_data(query, data)

    assert data[1] == "2026-07-15"
    assert result.metadata["index"] == "SOFR"
    assert result.metadata["forward_tenor"] == "1Y"
    assert all(isinstance(r, CftcOisForwardCurveData) for r in result.result)
    assert all(r.forward_rate is not None for r in result.result)

    starts = [round(r.start_years, 6) for r in result.result]
    assert starts == sorted(starts)
    assert starts[0] == 0.0

    five_year = next(r for r in result.result if r.start_years == pytest.approx(5.0))
    assert 3.0 < five_year.forward_rate < 5.0


def test_ois_forward_curve_observed_method(patch_source, monkeypatch):

    def _grid(
        records,
        fisn,
        currency,
        curve_date,
        *,
        forward_tenor_days,
        step_years,
        count,
        min_trades,
        spot_rate,
    ):
        assert spot_rate > 0.0
        return [
            {
                "tenor_years": 0.0,
                "tenor_days": 0,
                "forward_rate": 0.04,
                "forward_extrapolated": False,
                "num_trades": 7,
            },
            {
                "tenor_years": 0.25,
                "tenor_days": 91,
                "forward_rate": 0.041,
                "forward_extrapolated": False,
                "num_trades": 7,
            },
        ]

    monkeypatch.setattr("openbb_cftc.utils.policy.observed_forward_grid", _grid)
    query = CftcOisForwardCurveQueryParams(
        source="slice", method="observed", forward_tenor="1Y", forward_step="3M"
    )
    data = asyncio.run(CftcOisForwardCurveFetcher.aextract_data(query, None))
    result = CftcOisForwardCurveFetcher.transform_data(query, data)

    assert result.metadata["method"] == "observed"
    assert [round(r.start_years, 2) for r in result.result] == [0.0, 0.25]
    assert result.result[0].forward_rate == pytest.approx(4.0)


def test_ois_forward_curve_slice_walks_back_over_an_empty_weekend(
    monkeypatch, slice_records
):

    async def _dates(asset_class):
        return ["2026-07-16", "2026-07-17", "2026-07-18", "2026-07-19"]

    async def _slice(asset_class, report_date, use_cache=True):
        return [] if report_date in ("2026-07-18", "2026-07-19") else slice_records

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_available_dates", _dates)
    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _slice)

    query = CftcOisForwardCurveQueryParams(
        source="slice", date=date(2026, 7, 19), forward_step="1Y", min_trades=5
    )
    data = asyncio.run(CftcOisForwardCurveFetcher.aextract_data(query, None))
    result = CftcOisForwardCurveFetcher.transform_data(query, data)

    assert data[1] == "2026-07-17"
    assert result.result[0].date == date(2026, 7, 17)


def test_ois_forward_curve_forward_tenor_accepts_labels(patch_source):
    query = CftcOisForwardCurveQueryParams(
        source="slice", date=TRADE_DATE, forward_tenor="6m", forward_step="6m"
    )
    assert query.forward_tenor == "6M"
    assert query.forward_step == "6M"

    result = CftcOisForwardCurveFetcher.transform_data(
        query, asyncio.run(CftcOisForwardCurveFetcher.aextract_data(query, None))
    )
    assert result.metadata["forward_tenor"] == "6M"
    assert all("6M @" in r.tenor for r in result.result)


def test_ois_forward_curve_count_caps_the_strip(patch_source):
    query = CftcOisForwardCurveQueryParams(
        source="slice",
        date=TRADE_DATE,
        forward_step="1Y",
        forward_count=3,
        min_trades=5,
    )
    data = asyncio.run(CftcOisForwardCurveFetcher.aextract_data(query, None))
    result = CftcOisForwardCurveFetcher.transform_data(query, data)

    assert len(result.result) == 3
    assert [round(r.start_years, 6) for r in result.result] == [0.0, 1.0, 2.0]


def test_ois_forward_curve_search_defaults_report_date_none(patch_search):
    query = CftcOisForwardCurveQueryParams(
        currency="chf", source="search", forward_tenor="1Y", forward_step="1Y"
    )
    data = asyncio.run(CftcOisForwardCurveFetcher.aextract_data(query, None))
    result = CftcOisForwardCurveFetcher.transform_data(query, data)

    assert data[1] is None
    assert result.metadata["index"] == "SARON"
    assert result.result


def test_ois_forward_curve_flags_an_extrapolated_tail(patch_source):
    query = CftcOisForwardCurveQueryParams(
        source="slice",
        date=TRADE_DATE,
        forward_tenor="5Y",
        forward_step="1Y",
        min_trades=3,
    )
    data = asyncio.run(CftcOisForwardCurveFetcher.aextract_data(query, None))
    result = CftcOisForwardCurveFetcher.transform_data(query, data)

    assert all(r.forward_rate is not None for r in result.result)
    assert result.result[0].extrapolated is False
    assert result.result[-1].extrapolated is True


def test_ois_forward_curve_raises_on_empty_strip(patch_source, monkeypatch):
    from openbb_core.app.model.abstract.error import OpenBBError

    monkeypatch.setattr(
        "openbb_cftc.utils.curve.forward_curve_grid", lambda *a, **k: []
    )
    query = CftcOisForwardCurveQueryParams(source="slice", date=TRADE_DATE)
    data = asyncio.run(CftcOisForwardCurveFetcher.aextract_data(query, None))

    with pytest.raises(OpenBBError, match="forward curve could be built"):
        CftcOisForwardCurveFetcher.transform_data(query, data)


def test_fx_forward_points_fetcher_slice(patch_source):
    query = CftcFxForwardPointsQueryParams(
        pair="USDJPY", date=TRADE_DATE, source="slice"
    )
    data = asyncio.run(CftcFxForwardPointsFetcher.aextract_data(query, None))
    result = CftcFxForwardPointsFetcher.transform_data(query, data)

    assert result.metadata["source"] == "slice"
    assert result.metadata["pair"] == "USDJPY"
    assert result.metadata["spot_rate"] > 100
    assert result.metadata["curve_date"] == "2026-07-15"
    assert result.metadata["lookback_days"] is None
    assert all(isinstance(p, CftcFxForwardPointsData) for p in result.result)
    assert all(p.staleness_days == 0 for p in result.result)

    series = [p.forward_points for p in result.result]
    assert all(a >= b for a, b in zip(series, series[1:]))


def test_fx_forward_points_slice_defaults_to_the_latest_published_date(patch_source):
    _, _, report_date, _ = asyncio.run(
        CftcFxForwardPointsFetcher.aextract_data(
            CftcFxForwardPointsQueryParams(source="slice"), None
        )
    )

    assert report_date == "2026-07-15"


def test_fx_forward_points_search_queries_both_fisns(monkeypatch, fx_records):
    from datetime import (
        date as dateType,
        timedelta,
    )

    calls: list = []

    async def _search(asset_class, **kwargs):
        calls.append(kwargs)
        return [
            {**r, "Dissemination Timestamp": "2026-07-15T10:00:00Z"} for r in fx_records
        ]

    monkeypatch.setattr("openbb_cftc.utils.search.search_trades", _search)

    query = CftcFxForwardPointsQueryParams(pair="USDJPY", date=dateType(2026, 7, 15))
    data = asyncio.run(CftcFxForwardPointsFetcher.aextract_data(query, None))
    result = CftcFxForwardPointsFetcher.transform_data(query, data)

    assert [c["upi_short_name"] for c in calls] == [
        "NA/Fwd JPY USD",
        "NA/Swaps JPY USD",
    ]
    assert all(c.get("currency") is None for c in calls)
    assert calls[0]["start_date"] == dateType(2026, 7, 15) - timedelta(days=29)

    assert result.metadata["source"] == "search"
    assert result.metadata["lookback_days"] == 30
    assert result.metadata["freshest_tenor"] == "2026-07-15"

    series = [p.forward_points for p in result.result]
    assert all(a >= b for a, b in zip(series, series[1:]))
    assert series[-1] < 0


def _infl_row(**overrides):
    record = {
        "Dissemination Identifier": "INF1",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "UPI FISN": "NA/Swap Infl Idx GBP",
        "UPI Underlier Name": "UK-RPI",
        "Notional currency-Leg 1": "GBP",
        "Fixed rate-Leg 1": "0.03",
        "Effective Date": "2020-01-01",
        "Expiration Date": "2036-07-15",
        "Notional amount-Leg 1": "10,000,000",
        "trade_type": "inflation",
    }
    record.update(overrides)

    return record


def test_priceable_drops_a_seasoned_inflation_print_without_its_index(
    slice_records, monkeypatch
):
    from openbb_cftc.models import swap_trades as st

    monkeypatch.setattr(st, "_curve_ok", lambda *a, **k: True)
    monkeypatch.setattr(
        "openbb_cftc.utils.inflation.build_breakeven_curve",
        lambda *a, **k: [(9.0, 0.03)],
    )

    row = _infl_row()
    today = date(2026, 7, 15)

    assert st._priceable(row, slice_records, "2026-07-15", today, None, {}, {}) is False
    assert (
        st._priceable(
            row,
            slice_records,
            "2026-07-15",
            today,
            None,
            {},
            {"UKRPI": {date(2019, 11, 1): 100.0, date(2026, 5, 1): 120.0}},
        )
        is True
    )


def test_priceable_keeps_an_unstarted_inflation_print_without_any_index(
    slice_records, monkeypatch
):
    from openbb_cftc.models import swap_trades as st

    monkeypatch.setattr(st, "_curve_ok", lambda *a, **k: True)
    monkeypatch.setattr(
        "openbb_cftc.utils.inflation.build_breakeven_curve",
        lambda *a, **k: [(9.0, 0.03)],
    )

    row = _infl_row(**{"Effective Date": "2026-08-01"})

    assert (
        st._priceable(row, slice_records, "2026-07-15", date(2026, 7, 15), None, {}, {})
        is True
    )


def test_priceable_drops_an_inflation_print_that_will_not_extract(slice_records):
    from openbb_cftc.models import swap_trades as st

    unpriceable = _infl_row(**{"Notional amount-Leg 1": ""})

    assert (
        st._priceable(
            unpriceable, slice_records, "2026-07-15", date(2026, 7, 15), None, {}, {}
        )
        is False
    )


def test_priceable_drops_an_inflation_print_without_a_rate_curve(
    slice_records, monkeypatch
):
    from openbb_cftc.models import swap_trades as st

    monkeypatch.setattr(st, "_curve_ok", lambda *a, **k: False)

    assert (
        st._priceable(
            _infl_row(), slice_records, "2026-07-15", date(2026, 7, 15), None, {}, {}
        )
        is False
    )


def test_priceable_drops_an_inflation_print_with_no_breakeven_curve(
    slice_records, monkeypatch
):
    from openbb_cftc.models import swap_trades as st

    monkeypatch.setattr(st, "_curve_ok", lambda *a, **k: True)
    monkeypatch.setattr(
        "openbb_cftc.utils.inflation.build_breakeven_curve", lambda *a, **k: []
    )

    assert (
        st._priceable(
            _infl_row(), slice_records, "2026-07-15", date(2026, 7, 15), None, {}, {}
        )
        is False
    )


def test_inflation_levels_fetches_each_index_once_and_survives_an_outage(monkeypatch):
    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_cftc.models import swap_trades as st

    calls: list = []

    async def _index(index, use_cache=True):
        calls.append(index)

        if index == "USCPI":
            raise OpenBBError("publisher down")

        return {date(2026, 1, 1): 100.0}

    monkeypatch.setattr("openbb_cftc.utils.inflation.get_inflation_index", _index)

    rows = [
        _infl_row(),
        _infl_row(),
        _infl_row(**{"UPI Underlier Name": "USA-CPI-U"}),
        {"trade_type": "spot", "UPI Underlier Name": "USD-SOFR-COMPOUND"},
    ]
    levels = asyncio.run(st._inflation_levels(rows, True))

    assert sorted(calls) == ["UKRPI", "USCPI"]
    assert sorted(levels) == ["UKRPI"]


def test_ois_curve_overnight_anchor(patch_source, monkeypatch):
    seen: list = []

    async def _fixings(index, start_date, end_date, use_cache=True):
        seen.append((index, start_date, end_date))

        return {date(2026, 7, 14): 0.0435}

    monkeypatch.setattr("openbb_cftc.utils.fixings.get_fixings", _fixings)
    query = CftcOisCurveQueryParams(
        date=TRADE_DATE, source="slice", min_trades=5, overnight_anchor=True
    )
    data = asyncio.run(CftcOisCurveFetcher.aextract_data(query, None))
    result = CftcOisCurveFetcher.transform_data(query, data)
    first = result.result[0]

    assert seen[0][0] == "SOFR"
    assert first.tenor == "1D"
    assert first.num_trades == 0
    assert first.as_of_date == date(2026, 7, 14)
    assert first.staleness_days == 1
    assert first.rate == pytest.approx(4.35)
    assert result.metadata["overnight_anchor"] == {
        "date": "2026-07-14",
        "rate": pytest.approx(4.35),
    }


def test_ois_curve_overnight_anchor_search_source(patch_search, monkeypatch):

    async def _fixings(index, start_date, end_date, use_cache=True):
        return {end_date: 0.011}

    monkeypatch.setattr("openbb_cftc.utils.fixings.get_fixings", _fixings)
    query = CftcOisCurveQueryParams(currency="CHF", min_trades=1, overnight_anchor=True)
    data = asyncio.run(CftcOisCurveFetcher.aextract_data(query, None))
    result = CftcOisCurveFetcher.transform_data(query, data)

    assert result.result[0].tenor == "1D"
    assert result.metadata["overnight_anchor"]["rate"] == pytest.approx(1.1)


def test_ois_curve_anchor_unavailable_on_a_fixings_outage(patch_source, monkeypatch):

    async def _broken(index, start_date, end_date, use_cache=True):
        raise OpenBBError("source down")

    monkeypatch.setattr("openbb_cftc.utils.fixings.get_fixings", _broken)
    query = CftcOisCurveQueryParams(
        date=TRADE_DATE, source="slice", min_trades=5, overnight_anchor=True
    )
    data = asyncio.run(CftcOisCurveFetcher.aextract_data(query, None))
    result = CftcOisCurveFetcher.transform_data(query, data)

    assert all(n.tenor != "1D" for n in result.result)
    assert result.metadata["overnight_anchor"] == "unavailable"


def test_ois_curve_anchor_metadata_defaults_off(patch_source):
    query = CftcOisCurveQueryParams(date=TRADE_DATE, source="slice", min_trades=5)
    data = asyncio.run(CftcOisCurveFetcher.aextract_data(query, None))
    result = CftcOisCurveFetcher.transform_data(query, data)

    assert result.metadata["overnight_anchor"] is False


def test_latest_fixing_skips_days_after_the_cutoff(monkeypatch):
    from openbb_cftc.models.ois_curve import _latest_fixing

    async def _fixings(index, start_date, end_date, use_cache=True):
        return {date(2026, 8, 1): 0.05}

    monkeypatch.setattr("openbb_cftc.utils.fixings.get_fixings", _fixings)

    assert asyncio.run(_latest_fixing("USD", date(2026, 7, 15), True)) is None


def test_keep_priceable_forex_injects_the_cfets_curve_for_cny(monkeypatch):
    from openbb_cftc.models.swap_trades import (
        CftcSwapTradesQueryParams,
        _keep_priceable_forex,
    )

    marker = {"UPI FISN": "NA/Swap Fxd Flt CNY", "synthetic": "1"}
    captured: list = []

    async def _rates(asset_class, report_date, use_cache=True):
        return [{"UPI FISN": "NA/Swap OIS USD"}]

    async def _cny(day, use_cache=True):
        return [marker]

    def _value(record, fx_records, rates_records, curve_date, **kwargs):
        captured.append(list(rates_records))

        return {"npv": 1.0}

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _rates)
    monkeypatch.setattr("openbb_cftc.utils.cfets.cny_curve_records", _cny)
    monkeypatch.setattr("openbb_cftc.utils.fx_valuation.value_fx_trade", _value)
    filtered = [{"UPI FISN": "NA/Fwd NDF CNY USD", "UPI Underlier Name": "CNY USD"}]
    query = CftcSwapTradesQueryParams(asset_class="forex")
    kept = asyncio.run(_keep_priceable_forex(filtered, [], "2026-07-24", query))

    assert kept == filtered
    assert marker in captured[0]


def test_keep_priceable_forex_skips_cfets_without_cny(monkeypatch):
    from openbb_cftc.models.swap_trades import (
        CftcSwapTradesQueryParams,
        _keep_priceable_forex,
    )

    async def _rates(asset_class, report_date, use_cache=True):
        return [{"UPI FISN": "NA/Swap OIS USD"}]

    def _forbidden(*args, **kwargs):
        raise AssertionError("no CFETS fetch for a CNY-free day")

    def _value(record, fx_records, rates_records, curve_date, **kwargs):
        return {"npv": 1.0}

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _rates)
    monkeypatch.setattr("openbb_cftc.utils.cfets.cny_curve_records", _forbidden)
    monkeypatch.setattr("openbb_cftc.utils.fx_valuation.value_fx_trade", _value)
    filtered = [{"UPI FISN": "NA/Fwd EUR USD", "UPI Underlier Name": "EUR USD"}]
    query = CftcSwapTradesQueryParams(asset_class="forex")
    kept = asyncio.run(_keep_priceable_forex(filtered, [], "2026-07-24", query))

    assert kept == filtered


def test_swap_summary_fx_injects_the_cfets_curve_for_cny(monkeypatch):
    from openbb_cftc.models.swap_summary import (
        CftcSwapSummaryQueryParams,
        _fx_metadata,
    )

    marker = {"UPI FISN": "NA/Swap Fxd Flt CNY", "synthetic": "1"}
    captured: list = []

    async def _slice(asset_class, report_date, use_cache=True):
        return [{"UPI FISN": "NA/Swap OIS USD"}]

    async def _cny(day, use_cache=True):
        return [marker]

    def _value(record, fx_records, rates_records, curve_date, **kwargs):
        captured.append(list(rates_records))

        return {"npv": 1.0}

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_slice", _slice)
    monkeypatch.setattr("openbb_cftc.utils.cfets.cny_curve_records", _cny)
    monkeypatch.setattr("openbb_cftc.utils.fx_valuation.value_fx_trade", _value)
    record = {
        "UPI FISN": "NA/Fwd NDF CNY USD",
        "UPI Underlier Name": "CNY USD",
        "Dissemination Timestamp": "2026-07-24T12:00:00Z",
    }
    query = CftcSwapSummaryQueryParams(dissemination_identifier="4400000000000000101")
    valued = asyncio.run(_fx_metadata(query, record))

    assert valued["npv"] == 1.0
    assert valued["trade_date"] == "2026-07-24"
    assert marker in captured[0]


def _patch_cfets_bulletin(monkeypatch):
    from tests.test_cfets import BULLETIN

    async def _bulletin(search_date, use_cache=True):
        return BULLETIN

    monkeypatch.setattr("openbb_cftc.utils.cfets.fetch_irs_bulletin", _bulletin)


def test_ois_curve_cny_slice_builds_from_the_cfets_backstop(patch_source, monkeypatch):
    _patch_cfets_bulletin(monkeypatch)
    query = CftcOisCurveQueryParams(
        currency="CNY", source="slice", date=TRADE_DATE, min_trades=1
    )
    data = asyncio.run(CftcOisCurveFetcher.aextract_data(query, None))
    result = CftcOisCurveFetcher.transform_data(query, data)
    tenors = {row.tenor for row in result.result}

    assert result.metadata["benchmark"] == "FR007"
    assert result.metadata["central_bank"] == "People's Bank of China"
    assert result.metadata["curve_date"] == "2026-07-15"
    assert {"1M", "1Y", "5Y"} <= tenors
    assert all(row.currency == "CNY" for row in result.result)

    factors = [
        row.discount_factor for row in result.result if row.discount_factor is not None
    ]
    assert all(a > b for a, b in zip(factors, factors[1:]))


def test_ois_curve_cny_slice_without_the_backstop_uses_the_tape(
    patch_source, monkeypatch
):

    async def _empty(day, use_cache=True):
        return []

    monkeypatch.setattr("openbb_cftc.utils.cfets.cny_curve_records", _empty)
    query = CftcOisCurveQueryParams(
        currency="CNY", source="slice", date=TRADE_DATE, min_trades=1
    )
    data = asyncio.run(CftcOisCurveFetcher.aextract_data(query, None))
    result = CftcOisCurveFetcher.transform_data(query, data)

    assert len(result.result) > 0
    assert all(row.currency == "CNY" for row in result.result)


def test_ois_curve_cny_slice_rejects_an_empty_window(patch_source, monkeypatch):
    from openbb_core.app.model.abstract.error import OpenBBError as CoreError

    async def _dates(asset_class):
        return ["2026-07-14", "2026-07-15"]

    monkeypatch.setattr("openbb_cftc.utils.dtcc.get_available_dates", _dates)
    query = CftcOisCurveQueryParams(
        currency="CNY", source="slice", date=date(2020, 1, 1)
    )

    with pytest.raises(CoreError, match="No PPD rates files"):
        asyncio.run(CftcOisCurveFetcher.aextract_data(query, None))


def test_ois_curve_cny_search_source(patch_search, monkeypatch):
    _patch_cfets_bulletin(monkeypatch)
    query = CftcOisCurveQueryParams(currency="CNY", min_trades=1)
    data = asyncio.run(CftcOisCurveFetcher.aextract_data(query, None))
    result = CftcOisCurveFetcher.transform_data(query, data)

    assert result.metadata["benchmark"] == "FR007"
    assert len(result.result) >= 9


def test_ois_curve_cny_overnight_anchor_uses_shibor(patch_source, monkeypatch):
    _patch_cfets_bulletin(monkeypatch)
    seen: list = []

    async def _fixings(index, start_date, end_date, use_cache=True):
        seen.append(index)

        return {date(2026, 7, 14): 0.0142}

    monkeypatch.setattr("openbb_cftc.utils.fixings.get_fixings", _fixings)
    query = CftcOisCurveQueryParams(
        currency="CNY",
        source="slice",
        date=TRADE_DATE,
        min_trades=1,
        overnight_anchor=True,
    )
    data = asyncio.run(CftcOisCurveFetcher.aextract_data(query, None))
    result = CftcOisCurveFetcher.transform_data(query, data)

    assert seen == ["SHIBOR"]
    assert result.result[0].tenor == "1D"
    assert result.result[0].rate == pytest.approx(1.42)


def test_ois_curve_history_cny(patch_source, monkeypatch):
    _patch_cfets_bulletin(monkeypatch)
    query = CftcOisCurveHistoryQueryParams(
        currency="CNY",
        start_date=date(2026, 7, 14),
        end_date=TRADE_DATE,
        min_trades=1,
    )
    data = asyncio.run(CftcOisCurveHistoryFetcher.aextract_data(query, None))
    result = CftcOisCurveHistoryFetcher.transform_data(query, data)

    assert result.metadata["index"] == "FR007"
    assert len(result.result) > 0
