import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest
from openbb_core.app.model.abstract.error import OpenBBError

from openbb_cftc.utils import fixings, store


@pytest.mark.parametrize(
    ("underlier", "expected"),
    [
        ("USD-SOFR-COMPOUND", "SOFR"),
        ("USD-SOFR-OIS Compound", "SOFR"),
        ("USD-Federal Funds-H.15-OIS-COMPOUND", "EFFR"),
        ("CAD-CORRA-OIS-COMPOUND", "CORRA"),
        ("EUR-EuroSTR-OIS Compound", "ESTR"),
        ("GBP-SONIA-COMPOUND", "SONIA"),
        ("GBP-SONIA-OIS Compound", "SONIA"),
        ("JPY-TONA-OIS-COMPOUND", "TONA"),
        ("JPY-TONA Compounded Index", "TONA"),
        ("MXN-TIIE ON-OIS Compound", "TIIE"),
        ("MXN-TIIE-OIS-COMPOUND", "TIIE"),
        ("BRL-CDI", "CDI"),
        ("CHF-SARON-OIS-COMPOUND", "SARON"),
        ("CHF-SARON-OIS Compound", "SARON"),
        ("SGD-SORA-COMPOUND", "SORA"),
        ("SGD-SORA-OIS Compound", "SORA"),
        ("INR-MIBOR-OIS Compound", "MIBOR"),
        ("INR-MIBOR-OIS-COMPOUND", "MIBOR"),
        ("COP-IBR-OIS Compound", "IBR"),
        ("COP-IBR-OIS-COMPOUND", "IBR"),
        ("ZAR-ZARONIA-OIS Compound", "ZARONIA"),
        ("ZAR-ZARONIA-OIS-COMPOUND", "ZARONIA"),
        ("CLP-ICP", "ICP"),
        ("CL-CLICP-Bloomberg", "ICP"),
        ("THB-THOR-OIS Compound", "THOR"),
        ("THB-THOR-COMPOUND", "THOR"),
        ("ILS-SHIR-OIS Compound", "SHIR"),
        ("ILS-SHIR-OIS-COMPOUND", "SHIR"),
        ("NZD-NZIONA-OIS Compound", "NZIONA"),
        ("NZD-NZIONA-OIS-COMPOUND", "NZIONA"),
        ("AUD-AONIA-OIS Compound", "AONIA"),
        ("AUD-AONIA-OIS-COMPOUND", "AONIA"),
        ("CNY-CNREPOFIX=CFXS-Reuters", "FR007"),
        ("CNY-Fixing Repo Rate", "FR007"),
        ("PLN-WIBOR", "WIBOR"),
        ("HUF-BUBOR-Reuters", "BUBOR"),
        ("AUD-BBSW", "BBSW"),
        ("ZAR-JIBAR-SAFEX", "JIBAR"),
        ("HKD-HIBOR-HKAB", "HIBOR"),
        ("KRW-CD 91D", "KRWCD"),
        ("MYR-KLIBOR-BNM", "KLIBOR"),
        ("CZK-PRIBOR-PRBO", "PRIBOR"),
        ("EUR-EURIBOR-Reuters", "EURIBOR"),
        ("NZD-BBR-FRA", "BKBM"),
        ("NA/Swap OIS USD", "SOFR"),
        ("NA/Swap Fxd Flt EUR", "EURIBOR"),
        ("OTHER vs Basket", None),
        (None, None),
    ],
)
def test_index_for_underlier(underlier, expected):
    assert fixings.index_for_underlier(underlier) == expected


def test_compound_fixings_spans_gaps_and_compounds_daily():
    series = {
        date(2026, 7, 16): 0.036,
        date(2026, 7, 17): 0.036,
        date(2026, 7, 20): 0.0357,
    }
    accrued = fixings.compound_fixings(series, date(2026, 7, 16), date(2026, 7, 21))

    expected = (1 + 0.036 / 360) * (1 + 0.036 * 3 / 360) * (1 + 0.0357 / 360) - 1
    assert accrued == pytest.approx(expected)


def test_compound_fixings_uses_the_fixing_in_force_at_the_start():
    series = {date(2026, 7, 17): 0.036}

    accrued = fixings.compound_fixings(series, date(2026, 7, 18), date(2026, 7, 20))

    assert accrued == pytest.approx(0.036 * 2 / 360)


def test_compound_fixings_refuses_an_uncovered_window():
    series = {date(2026, 7, 17): 0.036}

    assert fixings.compound_fixings({}, date(2026, 7, 16), date(2026, 7, 21)) is None
    assert (
        fixings.compound_fixings(series, date(2026, 7, 15), date(2026, 7, 21)) is None
    )


def test_compound_fixings_at_basis_252_applies_once_per_business_day():
    series = {
        date(2026, 6, 18): 0.00052531,
        date(2026, 6, 19): 0.00052531,
        date(2026, 6, 22): 0.00052531,
    }
    accrued = fixings.compound_fixings(
        series, date(2026, 6, 18), date(2026, 6, 23), 252.0
    )

    expected = (1.00052531) ** 3 - 1
    assert accrued == pytest.approx(expected)


def test_compound_fixings_at_basis_252_refuses_an_uncovered_window():
    assert (
        fixings.compound_fixings({}, date(2026, 6, 18), date(2026, 6, 23), 252.0)
        is None
    )


def test_get_fixings_fetches_parses_and_caches(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    calls: list = []

    async def _request(url, **kwargs):
        calls.append(url)
        return {
            "refRates": [
                {"effectiveDate": "2026-07-16", "type": "SOFR", "percentRate": 3.62},
                {"effectiveDate": "2026-07-17", "type": "SOFR", "percentRate": 3.59},
            ]
        }

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _request)

    series = asyncio.run(
        fixings.get_fixings("SOFR", date(2026, 7, 16), date(2026, 7, 19))
    )

    assert series == {date(2026, 7, 16): 0.0362, date(2026, 7, 17): 0.0359}
    assert len(calls) == 1
    assert "secured/sofr" in calls[0]
    assert f"startDate={fixings.FULL_HISTORY_START}" in calls[0]

    again = asyncio.run(
        fixings.get_fixings("SOFR", date(2026, 7, 16), date(2026, 7, 19))
    )

    assert again == series
    assert len(calls) == 1
    store.reset()


def test_get_fixings_serves_a_different_window_of_the_same_index_from_cache(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    calls: list = []

    async def _request(url, **kwargs):
        calls.append(url)
        return {
            "refRates": [
                {"effectiveDate": "2019-01-02", "type": "SOFR", "percentRate": 2.4},
                {"effectiveDate": "2026-07-16", "type": "SOFR", "percentRate": 3.62},
            ]
        }

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _request)

    asyncio.run(fixings.get_fixings("SOFR", date(2026, 7, 16), date(2026, 7, 16)))
    assert len(calls) == 1

    older = asyncio.run(fixings.get_fixings("SOFR", date(2019, 1, 2), date(2019, 1, 2)))

    assert older == {date(2019, 1, 2): 0.024}
    assert len(calls) == 1
    store.reset()


def test_get_fixings_without_cache_always_fetches(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    calls: list = []

    async def _request(url, **kwargs):
        calls.append(url)
        return {"refRates": []}

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _request)

    for _ in range(2):
        series = asyncio.run(
            fixings.get_fixings(
                "SOFR", date(2026, 7, 16), date(2026, 7, 17), use_cache=False
            )
        )

    assert series == {}
    assert len(calls) == 2
    store.reset()


def test_get_fixings_serves_cached_history_through_a_source_outage(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)

    async def _request(url, **kwargs):
        return {
            "refRates": [
                {
                    "effectiveDate": yesterday.isoformat(),
                    "type": "SOFR",
                    "percentRate": 3.62,
                }
            ]
        }

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _request)
    first = asyncio.run(fixings.get_fixings("SOFR", yesterday, today))
    assert first == {yesterday: 0.0362}

    key = "fixings-SOFR"
    monkeypatch.setattr(store, "SEARCH_INTRADAY_TTL_SECONDS", -1)
    store.put_search_days(key, {today.isoformat(): []})

    async def _boom(url, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _boom)
    stale = asyncio.run(fixings.get_fixings("SOFR", yesterday, today))

    assert stale == {yesterday: 0.0362}
    store.reset()


def test_get_fixings_wraps_transport_and_shape_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))

    async def _boom(url, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _boom)

    with pytest.raises(OpenBBError, match="Failed to fetch SOFR fixings"):
        asyncio.run(
            fixings.get_fixings(
                "SOFR", date(2026, 7, 16), date(2026, 7, 17), use_cache=False
            )
        )

    async def _shape(url, **kwargs):
        return ["not-a-dict"]

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _shape)

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "SOFR", date(2026, 7, 16), date(2026, 7, 17), use_cache=False
            )
        )


def test_fixing_basis_is_the_index_convention():
    assert fixings.fixing_basis("CORRA") == 365.0
    assert fixings.fixing_basis("SONIA") == 365.0
    assert fixings.fixing_basis("TONA") == 365.0
    assert fixings.fixing_basis("SOFR") == 360.0
    assert fixings.fixing_basis("ESTR") == 360.0
    assert fixings.fixing_basis("TIIE") == 360.0
    assert fixings.fixing_basis("CDI") == 252.0
    assert fixings.fixing_basis("SARON") == 360.0
    assert fixings.fixing_basis("SORA") == 365.0
    assert fixings.fixing_basis("MIBOR") == 365.0
    assert fixings.fixing_basis("IBR") == 360.0
    assert fixings.fixing_basis("ZARONIA") == 365.0
    assert fixings.fixing_basis("ICP") == 360.0
    assert fixings.fixing_basis("THOR") == 365.0
    assert fixings.fixing_basis("SHIR") == 365.0
    assert fixings.fixing_basis("NZIONA") == 365.0
    assert fixings.fixing_basis("AONIA") == 365.0
    assert fixings.fixing_basis(None) == 360.0


def test_get_fixings_parses_the_boc_valet_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))

    async def _request(url, **kwargs):
        assert "bankofcanada.ca/valet" in url
        return {
            "observations": [
                {"d": "2026-07-20", "AVG.INTWO": {"v": "2.36"}},
                {"d": "2026-07-21", "AVG.INTWO": {"v": "2.35"}},
                {"d": "2026-07-22"},
            ]
        }

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _request)
    series = asyncio.run(
        fixings.get_fixings(
            "CORRA", date(2026, 7, 20), date(2026, 7, 22), use_cache=False
        )
    )

    assert series == {date(2026, 7, 20): 0.0236, date(2026, 7, 21): 0.0235}


class _EcbResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _EcbSession:
    def __init__(self, body, seen):
        self._body = body
        self._seen = seen

    def get(self, url, **kwargs):
        self._seen.append(url)
        return _EcbResponse(self._body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _patch_ecb(monkeypatch, body):
    import aiohttp

    seen: list = []
    monkeypatch.setattr(
        aiohttp, "ClientSession", lambda *a, **k: _EcbSession(body, seen)
    )

    return seen


def test_get_fixings_parses_the_ecb_csv_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    seen = _patch_ecb(
        monkeypatch,
        "KEY,FREQ,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
        "EST.B.EU000A2X2A25.WT,B,2026-07-15,2.184,A\n"
        "EST.B.EU000A2X2A25.WT,B,2026-07-16,2.186,A\n",
    )
    series = asyncio.run(
        fixings.get_fixings(
            "ESTR", date(2026, 7, 15), date(2026, 7, 16), use_cache=False
        )
    )

    assert series == {
        date(2026, 7, 15): pytest.approx(0.02184),
        date(2026, 7, 16): pytest.approx(0.02186),
    }
    assert "data-api.ecb.europa.eu" in seen[0]


def test_get_fixings_rejects_malformed_boc_and_ecb_payloads(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))

    async def _bad(url, **kwargs):
        return {"nope": True}

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _bad)

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "CORRA", date(2026, 7, 15), date(2026, 7, 16), use_cache=False
            )
        )

    _patch_ecb(monkeypatch, "<html>error</html>")

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "ESTR", date(2026, 7, 15), date(2026, 7, 16), use_cache=False
            )
        )


def test_get_fixings_parses_the_boe_csv_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    seen = _patch_ecb(
        monkeypatch,
        "DATE,IUDSOIA\n15 Jul 2026,3.7308\n16 Jul 2026,3.7308\n17 Jul 2026,\n",
    )
    series = asyncio.run(
        fixings.get_fixings(
            "SONIA", date(2026, 7, 15), date(2026, 7, 16), use_cache=False
        )
    )

    assert series == {
        date(2026, 7, 15): pytest.approx(0.037308),
        date(2026, 7, 16): pytest.approx(0.037308),
    }
    assert "Datefrom=01/Jan/2000" in seen[0] and "SeriesCodes=IUDSOIA" in seen[0]


def test_get_fixings_rejects_a_malformed_boe_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    _patch_ecb(monkeypatch, "<html>maintenance</html>")

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "SONIA", date(2026, 7, 15), date(2026, 7, 16), use_cache=False
            )
        )


class _BojResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _BojSession:
    def __init__(self, seen):
        self._seen = seen

    def post(self, url, data=None):
        self._seen.append(("POST", url, dict(data or {})))

        if (data or {}).get("cgi") == "$nme_r000_en":
            return _BojResponse("...DLform_DD...")

        return _BojResponse('<a href="/ssi/html/nme_R031.123.20260101.01.csv">csv</a>')

    def get(self, url):
        self._seen.append(("GET", url, None))

        return _BojResponse(
            "Series code,FM01'STRDCLUCON\n\n"
            'Name of time-series,"Call Rate"\n'
            "2026/07/15,0.981\n"
            "2026/07/16,NA\n"
            "2026/07/17,\n"
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _patch_boj(monkeypatch):
    import aiohttp

    seen: list = []
    monkeypatch.setattr(aiohttp, "ClientSession", lambda *a, **k: _BojSession(seen))

    return seen


def test_get_fixings_parses_the_boj_two_step_csv_flow(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    seen = _patch_boj(monkeypatch)

    series = asyncio.run(
        fixings.get_fixings(
            "TONA", date(2026, 7, 15), date(2026, 7, 17), use_cache=False
        )
    )

    assert series == {date(2026, 7, 15): pytest.approx(0.00981)}
    assert seen[0][0] == "POST" and seen[0][2]["cgi"] == "$nme_r000_en"
    assert seen[0][2]["lstCode"] == "FM01'STRDCLUCON"
    assert seen[0][2]["obj_name"] == "FM01"
    assert seen[1][0] == "POST" and seen[1][2]["cgi"] == "$nme_r030_en"
    assert seen[2][0] == "GET" and seen[2][1].endswith("nme_R031.123.20260101.01.csv")


def test_get_fixings_rejects_a_malformed_boj_search_step(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))

    import aiohttp

    class _BadSearchSession(_BojSession):
        def post(self, url, data=None):
            self._seen.append(("POST", url, dict(data or {})))

            return _BojResponse("<html>no form here</html>")

    monkeypatch.setattr(aiohttp, "ClientSession", lambda *a, **k: _BadSearchSession([]))

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "TONA", date(2026, 7, 15), date(2026, 7, 16), use_cache=False
            )
        )


def test_get_fixings_rejects_a_malformed_boj_download_step(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))

    import aiohttp

    class _BadDownloadSession(_BojSession):
        def post(self, url, data=None):
            self._seen.append(("POST", url, dict(data or {})))

            if (data or {}).get("cgi") == "$nme_r000_en":
                return _BojResponse("...DLform_DD...")

            return _BojResponse("<html>no csv link</html>")

    monkeypatch.setattr(
        aiohttp, "ClientSession", lambda *a, **k: _BadDownloadSession([])
    )

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "TONA", date(2026, 7, 15), date(2026, 7, 16), use_cache=False
            )
        )


class _BanxicoSession:
    def __init__(self, body, seen):
        self._body = body
        self._seen = seen

    def post(self, url, data=None):
        self._seen.append((url, dict(data or {})))
        return _BojResponse(self._body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _patch_banxico(monkeypatch, body):
    import aiohttp

    seen: list = []
    monkeypatch.setattr(
        aiohttp, "ClientSession", lambda *a, **k: _BanxicoSession(body, seen)
    )

    return seen


def test_get_fixings_parses_the_banxico_csv_export(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    seen = _patch_banxico(
        monkeypatch,
        '"Title","Overnight TIIE Funding Rate, Volume-weighted median."\n'
        '"Date","SF331451"\n'
        "07/15/2026,6.5000\n"
        "07/16/2026,6.4900\n",
    )

    series = asyncio.run(
        fixings.get_fixings(
            "TIIE", date(2026, 7, 15), date(2026, 7, 16), use_cache=False
        )
    )

    assert series == {
        date(2026, 7, 15): pytest.approx(0.065),
        date(2026, 7, 16): pytest.approx(0.0649),
    }
    assert seen[0][1]["series"] == "SF331451"
    this_year = str(datetime.now(UTC).date().year)
    assert seen[0][1]["anoInicial"] == "2000" and seen[0][1]["anoFinal"] == this_year


def test_get_fixings_rejects_a_malformed_banxico_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    _patch_banxico(monkeypatch, "<html>maintenance</html>")

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "TIIE", date(2026, 7, 15), date(2026, 7, 16), use_cache=False
            )
        )


def test_get_fixings_parses_the_bcb_sgs_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))

    async def _request(url, **kwargs):
        assert "api.bcb.gov.br/dados/serie/bcdata.sgs.12" in url
        return [
            {"data": "18/06/2026", "valor": "0.052531"},
            {"data": "19/06/2026", "valor": "0.052531"},
        ]

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _request)
    series = asyncio.run(
        fixings.get_fixings(
            "CDI", date(2026, 6, 18), date(2026, 6, 19), use_cache=False
        )
    )

    assert series == {
        date(2026, 6, 18): pytest.approx(0.00052531),
        date(2026, 6, 19): pytest.approx(0.00052531),
    }


def test_get_fixings_rejects_a_malformed_bcb_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))

    async def _bad(url, **kwargs):
        return {"nope": True}

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _bad)

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "CDI", date(2026, 6, 18), date(2026, 6, 19), use_cache=False
            )
        )


def test_get_fixings_parses_the_snb_data_portal_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))

    async def _request(url, **kwargs):
        assert "data.snb.ch/api/cube/zirepo" in url
        return {
            "timeseries": [
                {
                    "header": [{"dimItem": "Overnight (SARON), close of trading"}],
                    "metadata": {"key": "EPB@SNB.zirepo{H0}"},
                    "values": [
                        {"date": "2026-07-15", "value": -0.043818},
                        {"date": "2026-07-16", "value": -0.04},
                    ],
                },
                {
                    "header": [{"dimItem": "SARON 1M Compound Rate"}],
                    "metadata": {"key": "EPB@SNB.zirepo{H6}"},
                    "values": [{"date": "2026-07-15", "value": -0.0387}],
                },
            ]
        }

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _request)
    series = asyncio.run(
        fixings.get_fixings(
            "SARON", date(2026, 7, 15), date(2026, 7, 16), use_cache=False
        )
    )

    assert series == {
        date(2026, 7, 15): pytest.approx(-0.00043818),
        date(2026, 7, 16): pytest.approx(-0.0004),
    }


def test_get_fixings_rejects_a_malformed_snb_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))

    async def _no_timeseries(url, **kwargs):
        return {"nope": True}

    monkeypatch.setattr(
        "openbb_core.provider.utils.helpers.amake_request", _no_timeseries
    )

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "SARON", date(2026, 7, 15), date(2026, 7, 16), use_cache=False
            )
        )

    async def _no_h0(url, **kwargs):
        return {
            "timeseries": [
                {
                    "header": [{"dimItem": "other"}],
                    "metadata": {"key": "{H6}"},
                    "values": [],
                }
            ]
        }

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _no_h0)

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "SARON", date(2026, 7, 17), date(2026, 7, 18), use_cache=False
            )
        )


class _MasResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _MasSession:
    def __init__(self, token_page, result_page, seen):
        self._token_page = token_page
        self._result_page = result_page
        self._seen = seen

    def get(self, url):
        self._seen.append(("GET", url, None))
        return _MasResponse(self._token_page)

    def post(self, url, data=None):
        self._seen.append(("POST", url, dict(data or {})))
        return _MasResponse(self._result_page)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _patch_mas(monkeypatch, token_page, result_page):
    import aiohttp

    seen: list = []
    monkeypatch.setattr(
        aiohttp,
        "ClientSession",
        lambda *a, **k: _MasSession(token_page, result_page, seen),
    )

    return seen


# noqa: S105
_MAS_TOKEN_PAGE = (
    '<input id="__VIEWSTATE" value="vs123" />'  # noqa: S105
    '<input id="__VIEWSTATEGENERATOR" value="gen1" />'
    '<input id="__EVENTVALIDATION" value="ev123" />'
)

_MAS_RESULT_PAGE = """
<table>
<thead><tr><th colspan="3">SORA VALUE DATE</th><th>SORA PUBLICATION DATE</th><th>SORA</th></tr></thead>
<tbody>
<tr><td>2026</td><td>Jul</td><td>15</td><td class="msbData">16 Jul 2026</td><td class="msbData">1.0910</td></tr>
<tr><td>&nbsp;</td><td>&nbsp;</td><td>16</td><td class="msbData">17 Jul 2026</td><td class="msbData">1.1200</td></tr>
<tr><td>&nbsp;</td><td>&nbsp;</td><td>17</td><td class="msbData">&nbsp;</td><td class="msbData">&nbsp;</td></tr>
</tbody>
</table>
"""


def test_get_fixings_parses_the_mas_two_step_postback_flow(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    seen = _patch_mas(monkeypatch, _MAS_TOKEN_PAGE, _MAS_RESULT_PAGE)

    series = asyncio.run(
        fixings.get_fixings(
            "SORA", date(2026, 7, 15), date(2026, 7, 16), use_cache=False
        )
    )

    assert series == {
        date(2026, 7, 15): pytest.approx(0.01091),
        date(2026, 7, 16): pytest.approx(0.0112),
    }
    assert seen[0][0] == "GET"
    assert seen[1][0] == "POST"
    assert seen[1][2]["__VIEWSTATE"] == "vs123"
    assert seen[1][2]["ctl00$ContentPlaceHolder1$ColumnsCheckBoxList$13"] == "on"


def test_get_fixings_rejects_a_malformed_mas_token_page(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    _patch_mas(monkeypatch, "<html>no tokens here</html>", _MAS_RESULT_PAGE)

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "SORA", date(2026, 7, 15), date(2026, 7, 16), use_cache=False
            )
        )


def test_get_fixings_rejects_a_malformed_mas_result_page(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    _patch_mas(monkeypatch, _MAS_TOKEN_PAGE, "<html>invalid period</html>")

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "SORA", date(2026, 7, 15), date(2026, 7, 16), use_cache=False
            )
        )


def test_get_fixings_parses_the_fbil_graph_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))

    async def _request(url, **kwargs):
        assert "fbil.org.in/wasdm/ovnmibor/fetchgraphdata/12M" in url
        return {
            "productName": "Overnight MIBOR",
            "benchMarkTrend": [
                {"publishDate": "2026-07-15", "rate": 5.27},
                {"publishDate": "2026-07-14", "rate": 5.27},
                {"publishDate": "2026-05-01", "rate": 5.23},
            ],
        }

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _request)
    series = asyncio.run(
        fixings.get_fixings(
            "MIBOR", date(2026, 7, 14), date(2026, 7, 15), use_cache=False
        )
    )

    assert series == {
        date(2026, 7, 14): pytest.approx(0.0527),
        date(2026, 7, 15): pytest.approx(0.0527),
    }


def test_get_fixings_rejects_a_malformed_fbil_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))

    async def _bad(url, **kwargs):
        return {"nope": True}

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _bad)

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "MIBOR", date(2026, 7, 14), date(2026, 7, 15), use_cache=False
            )
        )


def test_get_fixings_parses_the_banrep_epoch_millis_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))

    async def _request(url, **kwargs):
        assert "idSerie=241" in url
        return [
            {
                "id": 241,
                "unidad": "Tasa nominal, base 360",
                "data": [
                    [1783919200000, 11.192],
                    [1784005600000, 11.185],
                    [1784092000000, 11.183],
                ],
            }
        ]

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _request)
    series = asyncio.run(
        fixings.get_fixings(
            "IBR", date(2026, 7, 14), date(2026, 7, 15), use_cache=False
        )
    )

    assert series == {
        date(2026, 7, 14): pytest.approx(0.11185),
        date(2026, 7, 15): pytest.approx(0.11183),
    }


def test_get_fixings_rejects_a_malformed_banrep_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))

    async def _not_a_list(url, **kwargs):
        return {"nope": True}

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _not_a_list)

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "IBR", date(2026, 7, 14), date(2026, 7, 15), use_cache=False
            )
        )

    async def _no_data(url, **kwargs):
        return [{"id": 241, "unidad": "Tasa nominal, base 360"}]

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _no_data)

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "IBR", date(2026, 7, 14), date(2026, 7, 15), use_cache=False
            )
        )


def test_get_fixings_parses_the_sarb_ratereform_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    seen = _patch_ecb(
        monkeypatch,
        '{"rate_type":"ZARONIA","rates":['
        '{"date":"2026-07-14T00:00:00Z","rate":6.852},'
        '{"date":"2026-07-15T00:00:00Z","rate":6.853}'
        "]}",
    )

    series = asyncio.run(
        fixings.get_fixings(
            "ZARONIA", date(2026, 7, 14), date(2026, 7, 15), use_cache=False
        )
    )

    assert series == {
        date(2026, 7, 14): pytest.approx(0.06852),
        date(2026, 7, 15): pytest.approx(0.06853),
    }
    assert "resbank.co.za/bin/sarb/ratereform" in seen[0]
    assert "rate_type=ZARONIA" in seen[0]


def test_get_fixings_rejects_a_malformed_sarb_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    _patch_ecb(monkeypatch, "not json at all")

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "ZARONIA", date(2026, 7, 14), date(2026, 7, 15), use_cache=False
            )
        )

    _patch_ecb(monkeypatch, '{"rate_type":"ZARONIA"}')

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "ZARONIA", date(2026, 7, 16), date(2026, 7, 17), use_cache=False
            )
        )


class _BcchReadResponse:
    def raise_for_status(self):
        return None

    async def read(self):
        return b"fake-xls-bytes"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _BcchSession:
    def __init__(self, seen):
        self._seen = seen

    def get(self, url):
        self._seen.append(url)
        return _BcchReadResponse()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _patch_bcch_session(monkeypatch):
    import aiohttp

    seen: list = []
    monkeypatch.setattr(aiohttp, "ClientSession", lambda *a, **k: _BcchSession(seen))

    return seen


class _FakeSheet:
    def __init__(self, rows):
        self._rows = rows

    @property
    def nrows(self):
        return len(self._rows)

    def cell_type(self, row, col):
        return self._rows[row][0] if col == 0 else 2

    def cell_value(self, row, col):
        return self._rows[row][1] if col == 0 else self._rows[row][2]


class _FakeBook:
    def __init__(self, sheets):
        self.datemode = 0
        self._sheets = sheets

    def sheet_by_name(self, name):
        return self._sheets[name]


def test_get_fixings_parses_the_bcch_xls_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    import xlrd

    seen = _patch_bcch_session(monkeypatch)
    before_window = xlrd.xldate.xldate_from_date_tuple((1990, 1, 1), 0)
    first = xlrd.xldate.xldate_from_date_tuple((2026, 7, 14), 0)
    second = xlrd.xldate.xldate_from_date_tuple((2026, 7, 15), 0)
    placeholder = xlrd.xldate.xldate_from_date_tuple((2026, 7, 16), 0)
    sheet = _FakeSheet(
        [
            (xlrd.XL_CELL_TEXT, "Fecha", None),
            (xlrd.XL_CELL_DATE, before_window, 4.5),
            (xlrd.XL_CELL_DATE, first, 4.5),
            (xlrd.XL_CELL_DATE, second, 4.5),
            (xlrd.XL_CELL_DATE, placeholder, "-"),
        ]
    )
    book = _FakeBook({fixings.BCCH_TIB_SHEET: sheet})
    monkeypatch.setattr(xlrd, "open_workbook", lambda file_contents: book)

    series = asyncio.run(
        fixings.get_fixings(
            "ICP", date(2026, 7, 14), date(2026, 7, 16), use_cache=False
        )
    )

    assert series == {
        date(2026, 7, 14): pytest.approx(0.045),
        date(2026, 7, 15): pytest.approx(0.045),
    }
    assert seen == [fixings.BCCH_TIB_URL]


def test_get_fixings_rejects_a_malformed_bcch_workbook(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    import xlrd

    _patch_bcch_session(monkeypatch)

    def _boom(file_contents):
        raise ValueError("not a valid workbook")

    monkeypatch.setattr(xlrd, "open_workbook", _boom)

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "ICP", date(2026, 7, 14), date(2026, 7, 15), use_cache=False
            )
        )


def test_get_fixings_parses_the_thaibma_csv_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    seen = _patch_ecb(
        monkeypatch,
        '"As of","Code","Tenor","Rate","Days Count"\n'
        '"2026-07-14","THOR","O/N","0.99148","1"\n'
        '"2026-07-14","THORA","1M","0.9925","30"\n'
        '"2026-07-15","THOR","O/N","0.99288","1"\n',
    )

    series = asyncio.run(
        fixings.get_fixings(
            "THOR", date(2026, 7, 14), date(2026, 7, 15), use_cache=False
        )
    )

    assert series == {
        date(2026, 7, 14): pytest.approx(0.0099148),
        date(2026, 7, 15): pytest.approx(0.0099288),
    }
    assert "thaibma.or.th/api/thor/download-all" in seen[0]


def test_get_fixings_rejects_a_malformed_thaibma_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    _patch_ecb(monkeypatch, "<html>maintenance</html>")

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "THOR", date(2026, 7, 14), date(2026, 7, 15), use_cache=False
            )
        )


def _boi_sdmx_payload(pairs):
    return {
        "data": {
            "dataSets": [
                {
                    "observations": {
                        f"0:0:0:{i}": [rate, 0, 0, 0, 0, 0, 0, 0]
                        for i, (_, rate) in enumerate(pairs)
                    }
                }
            ],
            "structure": {
                "dimensions": {
                    "observation": [
                        {"id": "SERIES_CODE", "values": [{"id": "MNT_SHIR_D"}]},
                        {"id": "FREQ", "values": [{"id": "D"}]},
                        {"id": "IR_FV_TYPE", "values": [{"id": "RIB_SHIR"}]},
                        {
                            "id": "TIME_PERIOD",
                            "values": [{"id": day} for day, _ in pairs],
                        },
                    ]
                }
            },
        }
    }


def test_get_fixings_parses_the_boi_sdmx_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    calls: list = []

    async def _request(url, **kwargs):
        calls.append(url)
        return _boi_sdmx_payload(
            [
                ("2026-07-14", "3.5"),
                ("2026-07-15", "3.5"),
                ("2026-07-16", None),
            ]
        )

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _request)
    series = asyncio.run(
        fixings.get_fixings(
            "SHIR", date(2026, 7, 14), date(2026, 7, 16), use_cache=False
        )
    )

    assert series == {
        date(2026, 7, 14): pytest.approx(0.035),
        date(2026, 7, 15): pytest.approx(0.035),
    }
    assert "SERIES_CODE]=MNT_SHIR_D" in calls[0]
    today = datetime.now(UTC).date().isoformat()
    assert (
        f"startPeriod={fixings.FULL_HISTORY_START}" in calls[0]
        and f"endPeriod={today}" in calls[0]
    )


def test_get_fixings_rejects_a_malformed_boi_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))

    async def _shape(url, **kwargs):
        return ["not-a-dict"]

    monkeypatch.setattr("openbb_core.provider.utils.helpers.amake_request", _shape)

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "SHIR", date(2026, 7, 14), date(2026, 7, 15), use_cache=False
            )
        )

    async def _missing_structure(url, **kwargs):
        return {"data": {"dataSets": [{"observations": {}}], "structure": {}}}

    monkeypatch.setattr(
        "openbb_core.provider.utils.helpers.amake_request", _missing_structure
    )

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "SHIR", date(2026, 7, 16), date(2026, 7, 17), use_cache=False
            )
        )


def _rbnz_workbook_bytes(series=None):
    import io

    import openpyxl

    series = series or fixings.RBNZ_NZIONA_SERIES
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append([None, "Cash rate"])
    sheet.append([None, "Overnight interbank cash rate"])
    sheet.append(["Notes", None])
    sheet.append(["Unit", "%pa"])
    sheet.append(["Series Id", series])
    sheet.append([datetime(2026, 7, 14), 2.73])
    sheet.append([datetime(2026, 7, 15), None])
    sheet.append([datetime(2026, 7, 16), 2.75])

    buffer = io.BytesIO()
    workbook.save(buffer)

    return buffer.getvalue()


def _patch_rbnz_curl(monkeypatch, stdout=b"", stderr=b"", returncode=0):
    calls: list = []

    class _FakeProcess:
        def __init__(self):
            self.returncode = returncode

        async def communicate(self):
            return stdout, stderr

    async def _fake_exec(*args, **kwargs):
        calls.append(args)
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    return calls


def test_get_fixings_parses_the_rbnz_b2_workbook_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    calls = _patch_rbnz_curl(monkeypatch, stdout=_rbnz_workbook_bytes())

    series = asyncio.run(
        fixings.get_fixings(
            "NZIONA", date(2026, 7, 14), date(2026, 7, 16), use_cache=False
        )
    )

    assert series == {
        date(2026, 7, 14): pytest.approx(0.0273),
        date(2026, 7, 16): pytest.approx(0.0275),
    }
    assert calls[0][0] == "curl"
    assert fixings.RBNZ_B2_URL in calls[0]


def test_get_fixings_rejects_a_failed_rbnz_curl_fetch(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    _patch_rbnz_curl(
        monkeypatch,
        stderr=b"curl: (22) The requested URL returned error: 403",
        returncode=22,
    )

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "NZIONA", date(2026, 7, 14), date(2026, 7, 15), use_cache=False
            )
        )


def test_get_fixings_rejects_a_malformed_rbnz_workbook(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    _patch_rbnz_curl(monkeypatch, stdout=b"not a real xlsx file")

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "NZIONA", date(2026, 7, 14), date(2026, 7, 15), use_cache=False
            )
        )

    _patch_rbnz_curl(
        monkeypatch, stdout=_rbnz_workbook_bytes(series="INM.SOME.OTHER.SERIES")
    )

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "NZIONA", date(2026, 7, 16), date(2026, 7, 17), use_cache=False
            )
        )


def _rba_workbook_bytes(series=None):
    import io

    import openpyxl

    series = series or fixings.RBA_AONIA_SERIES
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    for _ in range(10):
        sheet.append([None, None])
    sheet.append(["Series ID", series])
    sheet.append([datetime(2026, 7, 13), 4.35])
    sheet.append([datetime(2026, 7, 14), 4.35])
    sheet.append([datetime(2026, 7, 15), ""])

    buffer = io.BytesIO()
    workbook.save(buffer)

    return buffer.getvalue()


class _RbaReadResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    async def read(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _RbaSession:
    def __init__(self, body, seen):
        self._body = body
        self._seen = seen

    def get(self, url, **kwargs):
        self._seen.append((url, kwargs))
        return _RbaReadResponse(self._body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _patch_rba_session(monkeypatch, body):
    import aiohttp

    seen: list = []
    monkeypatch.setattr(
        aiohttp, "ClientSession", lambda *a, **k: _RbaSession(body, seen)
    )

    return seen


def test_get_fixings_parses_the_rba_f01d_workbook_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    seen = _patch_rba_session(monkeypatch, _rba_workbook_bytes())

    series = asyncio.run(
        fixings.get_fixings(
            "AONIA", date(2026, 7, 13), date(2026, 7, 15), use_cache=False
        )
    )

    assert series == {
        date(2026, 7, 13): pytest.approx(0.0435),
        date(2026, 7, 14): pytest.approx(0.0435),
    }
    assert seen == [(fixings.RBA_F01D_URL, {})]


def test_get_fixings_rejects_a_malformed_rba_workbook(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBB_CACHE_DIRECTORY", str(tmp_path))
    _patch_rba_session(monkeypatch, b"not a real xlsx file")

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "AONIA", date(2026, 7, 13), date(2026, 7, 14), use_cache=False
            )
        )

    _patch_rba_session(monkeypatch, _rba_workbook_bytes(series="FIRMMSOMEOTHERSERIES"))

    with pytest.raises(OpenBBError, match="Unexpected fixings response"):
        asyncio.run(
            fixings.get_fixings(
                "AONIA", date(2026, 7, 16), date(2026, 7, 17), use_cache=False
            )
        )
