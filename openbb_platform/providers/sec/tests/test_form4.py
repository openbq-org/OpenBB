"""Unit tests for ``openbb_sec.utils.form4``.

These exercise the parsing/helper functions directly with crafted synthetic dict
structures and mocked transport, covering branches the fetcher/VCR suites never
reach.  No real HTTP is performed: any function that fetches has its transport
patched at the import site.
"""

import asyncio
from unittest.mock import patch

import pytest
from openbb_core.app.model.abstract.error import OpenBBError

from openbb_sec.utils import form4


def test_clean_xml():
    """clean_xml strips backslashes and '/s/ ' and escapes bare ampersands."""
    out = form4.clean_xml(r"A & B /s/ John \Doe &amp; Co &lt;x&gt;")
    assert "\\" not in out
    assert "/s/ " not in out
    assert "A &amp; B" in out  # bare & escaped
    assert "&amp;amp;" not in out  # existing entity left intact


def _form4_full_data():
    """A Form 4 dict exercising owner-list, footnotes, and both tables."""
    return {
        "periodOfReport": "2023-05-01",
        "documentType": "4",
        "issuer": {
            "issuerName": "ACME",
            "issuerCik": "0000123",
            "issuerTradingSymbol": "acm",
        },
        "reportingOwner": [
            {
                "reportingOwnerId": {"rptOwnerName": "Jane", "rptOwnerCik": "111"},
                "reportingOwnerRelationship": {"isDirector": "1"},
            },
            {"reportingOwnerId": {"rptOwnerName": "Bob", "rptOwnerCik": "222"}},
        ],
        "ownerSignature": [{"signatureDate": "2023-05-02"}],
        "footnotes": {"footnote": {"@id": "F1", "#text": "note one"}},
        "nonDerivativeTable": {
            "nonDerivativeTransaction": [
                {
                    "securityTitle": {"value": "Common"},
                    "transactionDate": {"value": "2023-05-01"},
                    "transactionCoding": {
                        "transactionCode": "P",
                        "transactionFormType": "4",
                    },
                    "transactionAmounts": {
                        "transactionShares": {
                            "value": "100",
                            "footnoteId": {"@id": "F1"},
                        },
                        "transactionPricePerShare": {"value": "10"},
                        "transactionAcquiredDisposedCode": {"value": "A"},
                    },
                    "postTransactionAmounts": {
                        "sharesOwnedFollowingTransaction": {"value": "500"}
                    },
                    "ownershipNature": {
                        "directOrIndirectOwnership": {
                            "value": "D",
                            "footnoteId": [{"@id": "F1"}],
                        }
                    },
                }
            ]
        },
        "derivativeTable": {
            "derivativeTransaction": {
                "securityTitle": {"value": "Option"},
                "conversionOrExercisePrice": {"value": "5"},
                "transactionCoding": {"transactionCode": "M"},
                "transactionAmounts": {
                    "transactionShares": {"value": "10"},
                    "transactionTotalValue": {"value": "50"},
                },
                "underlyingSecurity": {
                    "underlyingSecurityTitle": {"value": "Common"},
                    "underlyingSecurityShares": {"value": "10"},
                },
            }
        },
    }


def test_parse_form_4_data_full():
    """parse_form_4_data handles list owners, footnotes, and both tables."""
    rows = asyncio.run(form4.parse_form_4_data(_form4_full_data()))
    assert len(rows) == 2
    non_deriv = rows[0]
    assert non_deriv["owner"] == "Jane;Bob"
    assert non_deriv["owner_cik"] == "111;222"
    assert non_deriv["symbol"] == "ACM"  # upper-cased
    assert non_deriv["isDirector"] == "1"  # owner_relationship merged
    assert non_deriv["filing_date"] == "2023-05-02"  # signature date wins
    assert non_deriv["transaction_type"] == "P"
    assert non_deriv["footnote"] == "note one"
    assert non_deriv["securityTitle"] == "Common"
    assert non_deriv["sharesOwnedFollowingTransaction"] == "500"
    deriv = rows[1]
    assert deriv["securityTitle"] == "Option"
    assert deriv["transaction_type"] == "M"
    # transactionValue popped onto transactionTotalValue when present.
    assert deriv["transactionTotalValue"] == "50"
    assert deriv["underlyingSecurityShares"] == "10"


def test_parse_form_4_data_holding_and_single_owner():
    """nonDerivativeHolding (no transaction) and a single dict owner are handled."""
    data = {
        "periodOfReport": "2023-08-01",
        "documentType": "4",
        "issuer": {
            "issuerName": "BETA",
            "issuerCik": "0000999",
            "issuerTradingSymbol": "BET",
        },
        "reportingOwner": {
            "reportingOwnerId": {"rptOwnerName": "Solo", "rptOwnerCik": "333"},
            "reportingOwnerRelationship": {"isOfficer": "1", "officerTitle": "CEO"},
        },
        "ownerSignature": {"signatureDate": "2023-08-02"},
        "nonDerivativeTable": {
            "nonDerivativeHolding": {
                "securityTitle": {"value": "Common"},
                "postTransactionAmounts": {
                    "sharesOwnedFollowingTransaction": {"value": "1000"}
                },
                "ownershipNature": {"directOrIndirectOwnership": {"value": "I"}},
            }
        },
    }
    rows = asyncio.run(form4.parse_form_4_data(data))
    assert len(rows) == 1
    assert rows[0]["owner"] == "Solo"
    assert rows[0]["owner_cik"] == "333"
    assert rows[0]["officerTitle"] == "CEO"
    assert rows[0]["filing_date"] == "2023-08-02"
    assert rows[0]["sharesOwnedFollowingTransaction"] == "1000"


def test_parse_form_4_data_derivative_security_key():
    """A 'derivativeSecurity' key (not derivativeTable) is parsed."""
    data = {
        "periodOfReport": "2023-09-01",
        "documentType": "4",
        "issuer": {
            "issuerName": "GAMMA",
            "issuerCik": "0000777",
            "issuerTradingSymbol": "GAM",
        },
        "reportingOwner": {
            "reportingOwnerId": {"rptOwnerName": "Dee", "rptOwnerCik": "444"}
        },
        "derivativeSecurity": [
            {
                "securityTitle": {"value": "Warrant"},
                "conversionOrExercisePrice": {"value": "12"},
                "exerciseDate": {"value": "2024-01-01"},
            }
        ],
    }
    rows = asyncio.run(form4.parse_form_4_data(data))
    assert len(rows) == 1
    assert rows[0]["securityTitle"] == "Warrant"
    assert rows[0]["conversionOrExercisePrice"] == "12"
    # documentType used because no transactionCoding present.
    assert rows[0]["form"] == "4"


def test_parse_form_4_data_str_skip_outer_footnote_list_and_deriv_value():
    """String list entries are skipped; an outer footnoteId list joins notes.

    Both the non-derivative and derivative transaction lists carry a stray string
    entry (skipped via ``continue``). The security title carries a *list* of
    footnoteId references at the outer value level, joined by '; '. The
    derivative transaction supplies ``transactionValue``, which is popped onto
    ``transactionTotalValue``.
    """
    data = {
        "periodOfReport": "2023-05-01",
        "documentType": "4",
        "issuer": {
            "issuerName": "ACME",
            "issuerCik": "0000123",
            "issuerTradingSymbol": "acm",
        },
        "reportingOwner": {
            "reportingOwnerId": {"rptOwnerName": "Jane", "rptOwnerCik": "111"}
        },
        "ownerSignature": {"signatureDate": "2023-05-02"},
        "footnotes": {
            "footnote": [
                {"@id": "F1", "#text": "note one"},
                {"@id": "F2", "#text": "note two"},
            ]
        },
        "nonDerivativeTable": {
            "nonDerivativeTransaction": [
                "JUNK STRING ENTRY",
                {
                    "securityTitle": {
                        "value": "Common",
                        "footnoteId": [{"@id": "F1"}, {"@id": "F2"}],
                    },
                    "transactionCoding": {
                        "transactionCode": "P",
                        "transactionFormType": "4",
                    },
                    "transactionAmounts": {
                        "transactionShares": {"value": "100"},
                        "transactionAcquiredDisposedCode": {"value": "A"},
                    },
                },
            ]
        },
        "derivativeTable": {
            "derivativeTransaction": [
                "DERIV JUNK STRING",
                {
                    "securityTitle": {"value": "Option"},
                    "transactionCoding": {"transactionCode": "M"},
                    "transactionAmounts": {
                        "transactionShares": {"value": "10"},
                        "transactionValue": {"value": "50"},
                    },
                },
            ]
        },
    }
    rows = asyncio.run(form4.parse_form_4_data(data))
    assert len(rows) == 2  # one non-deriv + one deriv (strings skipped)
    non_deriv = rows[0]
    assert non_deriv["securityTitle"] == "Common"
    assert non_deriv["footnote"] == "note one; note two"  # outer list joined
    deriv = rows[1]
    assert deriv["securityTitle"] == "Option"
    # transactionValue popped -> transactionTotalValue; original key removed.
    assert deriv["transactionTotalValue"] == "50"
    assert "transactionValue" not in deriv


def test_parse_form_4_data_outer_single_footnote():
    """A single-dict footnoteId on a direct child resolves via the else-branch."""
    data = {
        "periodOfReport": "2023-05-01",
        "documentType": "4",
        "issuer": {
            "issuerName": "ACME",
            "issuerCik": "0000123",
            "issuerTradingSymbol": "acm",
        },
        "reportingOwner": {
            "reportingOwnerId": {"rptOwnerName": "Jane", "rptOwnerCik": "111"}
        },
        "ownerSignature": {"signatureDate": "2023-05-02"},
        "footnotes": {"footnote": {"@id": "F9", "#text": "single note"}},
        "nonDerivativeTable": {
            "nonDerivativeTransaction": [
                {
                    "securityTitle": {"value": "Common", "footnoteId": {"@id": "F9"}},
                    "transactionCoding": {"transactionCode": "P"},
                    "transactionAmounts": {
                        "transactionShares": {"value": "100"},
                        "transactionAcquiredDisposedCode": {"value": "A"},
                    },
                }
            ]
        },
    }
    rows = asyncio.run(form4.parse_form_4_data(data))
    assert len(rows) == 1
    assert rows[0]["securityTitle"] == "Common"
    assert rows[0]["footnote"] == "single note"  # F9 resolved from the map


def test_download_data_with_cache_roundtrip():
    """download_data caches parsed filings and serves the second call from cache.

    aget_cached/aset_cached are imported locally inside download_data from
    openbb_sec.utils.cache, so they are patched there. The first pass finds every
    URL uncached, fetches/parses/stores them; the second pass reads them all back.
    """
    import openbb_sec.utils.cache as cache_mod

    parsed = {
        "documentType": "4",
        "issuer": {"issuerName": "ACME", "issuerTradingSymbol": "ACM"},
        "reportingOwner": {
            "reportingOwnerId": {"rptOwnerName": "Jane", "rptOwnerCik": "111"}
        },
        "ownerSignature": {"signatureDate": "2023-05-02"},
        "nonDerivativeTable": {
            "nonDerivativeTransaction": {
                "securityTitle": {"value": "Common"},
                "transactionCoding": {"transactionCode": "P"},
                "transactionAmounts": {
                    "transactionShares": {"value": "100"},
                    "transactionAcquiredDisposedCode": {"value": "A"},
                },
            }
        },
    }

    store: dict = {}

    async def _aget(key):
        return store.get(key)

    async def _aset(key, val):
        store[key] = val

    async def _fake_get_data(url):
        return parsed

    urls = ["http://sec.gov/a.xml", "http://sec.gov/b.xml"]

    with (
        patch.object(cache_mod, "aget_cached", _aget),
        patch.object(cache_mod, "aset_cached", _aset),
        patch.object(form4, "get_form_4_data", _fake_get_data),
    ):
        first = asyncio.run(form4.download_data(urls, use_cache=True))
        # Both filings now cached under their 'form4 <url>' keys.
        assert store["form4 http://sec.gov/a.xml"]
        second = asyncio.run(form4.download_data(urls, use_cache=True))

    assert len(first) == 2
    assert len(second) == 2  # served entirely from cache
    assert second[0]["owner_name"] == "Jane"


def test_download_data_cache_mass_warning():
    """A large URL set logs the long-download notice via the cache path.

    Enough URLs push the estimated time past the warning threshold, exercising
    the logger branch. asyncio.sleep is neutralised so the chunked gather loop
    returns immediately.
    """
    import openbb_sec.utils.cache as cache_mod

    parsed = {
        "documentType": "4",
        "issuer": {"issuerName": "ACME", "issuerTradingSymbol": "ACM"},
        "reportingOwner": {
            "reportingOwnerId": {"rptOwnerName": "Jane", "rptOwnerCik": "111"}
        },
        "ownerSignature": {"signatureDate": "2023-05-02"},
        "nonDerivativeTable": {
            "nonDerivativeTransaction": {
                "securityTitle": {"value": "Common"},
                "transactionCoding": {"transactionCode": "P"},
                "transactionAmounts": {
                    "transactionShares": {"value": "100"},
                    "transactionAcquiredDisposedCode": {"value": "A"},
                },
            }
        },
    }
    store: dict = {}

    async def _aget(key):
        return store.get(key)

    async def _aset(key, val):
        store[key] = val

    async def _fake_get_data(url):
        return parsed

    async def _no_sleep(*_a, **_k):
        return None

    # 40 URLs -> estimate 40/7*1.8 > 10s -> long-download notice branch.
    urls = [f"http://sec.gov/{i}.xml" for i in range(40)]

    with (
        patch.object(cache_mod, "aget_cached", _aget),
        patch.object(cache_mod, "aset_cached", _aset),
        patch.object(form4, "get_form_4_data", _fake_get_data),
        patch("asyncio.sleep", _no_sleep),
    ):
        out = asyncio.run(form4.download_data(urls, use_cache=True))

    assert len(out) == 40
    assert len(store) == 40  # every filing cached


def test_get_form_4_data_traffic_limit():
    """A 'Traffic Limit' body raises an OpenBBError before parsing."""

    async def _fake_request(url, **kwargs):
        return b"You have hit the SEC Traffic Limit page."

    with patch("openbb_core.provider.utils.helpers.amake_request", _fake_request):
        with pytest.raises(OpenBBError, match="traffic limit"):
            asyncio.run(form4.get_form_4_data("http://sec.gov/f.xml"))


def test_get_form_4_data_parse_error_warns():
    """Unparseable XML returns an empty dict and emits a warning."""

    async def _fake_request(url, **kwargs):
        # Not valid XML once cleaned -> xmltodict.parse raises -> warn + {}.
        return b"<<<not xml>>>"

    with patch("openbb_core.provider.utils.helpers.amake_request", _fake_request):
        with pytest.warns(Warning):
            out = asyncio.run(form4.get_form_4_data("http://sec.gov/bad.xml"))
    assert out == {}


def test_get_form_4_data_ok():
    """A valid ownershipDocument XML is parsed to the inner dict."""
    xml = (
        b"<?xml version='1.0'?><ownershipDocument>"
        b"<documentType>4</documentType>"
        b"<issuer><issuerName>ACME</issuerName></issuer>"
        b"</ownershipDocument>"
    )

    async def _fake_request(url, **kwargs):
        return xml

    with patch("openbb_core.provider.utils.helpers.amake_request", _fake_request):
        out = asyncio.run(form4.get_form_4_data("http://sec.gov/ok.xml"))
    assert out["documentType"] == "4"
    assert out["issuer"]["issuerName"] == "ACME"


def test_download_data_no_cache():
    """download_data fetches, parses, renames via field_map, and sorts by date."""
    parsed = {
        "documentType": "4",
        "issuer": {"issuerName": "ACME", "issuerTradingSymbol": "ACM"},
        "reportingOwner": {
            "reportingOwnerId": {"rptOwnerName": "Jane", "rptOwnerCik": "111"}
        },
        "ownerSignature": {"signatureDate": "2023-05-02"},
        "nonDerivativeTable": {
            "nonDerivativeTransaction": {
                "securityTitle": {"value": "Common"},
                "transactionCoding": {"transactionCode": "P"},
                "transactionAmounts": {
                    "transactionShares": {"value": "100"},
                    "transactionAcquiredDisposedCode": {"value": "A"},
                },
            }
        },
    }

    async def _fake_get_data(url):
        return parsed

    # use_cache=False avoids the disk-cache gather entirely.
    with patch.object(form4, "get_form_4_data", _fake_get_data):
        out = asyncio.run(
            form4.download_data(["http://sec.gov/a.xml"], use_cache=False)
        )
    assert len(out) == 1
    # field_map renames: owner->owner_name, issuer->company_name, etc.
    assert out[0]["owner_name"] == "Jane"
    assert out[0]["company_name"] == "ACME"
    assert out[0]["transaction_type"] == "P"
    assert out[0]["filing_url"] == "http://sec.gov/a.xml"


def test_get_form_4_no_data_raises():
    """get_form_4 raises when downloading yields nothing."""

    async def _urls(symbol, start_date, end_date, use_cache):
        return ["http://sec.gov/a.xml"]

    async def _download(urls, use_cache):
        return []

    with (
        patch.object(form4, "get_form_4_urls", _urls),
        patch.object(form4, "download_data", _download),
    ):
        with pytest.raises(OpenBBError, match="No Form 4 data"):
            asyncio.run(form4.get_form_4("ACME"))


def test_get_form_4_limit_applied():
    """get_form_4 truncates URLs to the limit and returns downloaded rows."""
    seen = {}

    async def _urls(symbol, start_date, end_date, use_cache):
        return ["u1", "u2", "u3"]

    async def _download(urls, use_cache):
        seen["urls"] = list(urls)
        return [{"filing_date": "2023-01-01", "owner_name": "X"}]

    with (
        patch.object(form4, "get_form_4_urls", _urls),
        patch.object(form4, "download_data", _download),
    ):
        out = asyncio.run(form4.get_form_4("ACME", limit=2))
    assert seen["urls"] == ["u1", "u2"]
    assert out[0]["owner_name"] == "X"


def test_get_form_4_timeout_wrapped():
    """An asyncio.TimeoutError is re-raised as an OpenBBError."""

    async def _urls(symbol, start_date, end_date, use_cache):
        raise TimeoutError

    with patch.object(form4, "get_form_4_urls", _urls):
        with pytest.raises(OpenBBError, match="timeout error"):
            asyncio.run(form4.get_form_4("ACME"))
