"""Unit tests for ``openbb_sec.utils.parse_13f``.

These exercise the parsing/helper functions directly with crafted synthetic XML
strings and mocked transport, covering branches the fetcher/VCR suites never
reach.  No real HTTP is performed.
"""

import asyncio
from unittest.mock import patch

import pytest
from openbb_core.app.model.abstract.error import OpenBBError

from openbb_sec.utils import parse_13f


def test_date_to_quarter_end():
    """A mid-quarter date snaps to the calendar quarter end."""
    assert parse_13f.date_to_quarter_end("2023-05-15") == "2023-06-30"
    assert parse_13f.date_to_quarter_end("2023-01-01") == "2023-03-31"
    assert parse_13f.date_to_quarter_end("2023-12-31") == "2023-12-31"


def test_get_13f_candidates_requires_input():
    """get_13f_candidates raises when neither symbol nor cik is given."""
    with pytest.raises(OpenBBError, match="Either symbol or cik"):
        asyncio.run(parse_13f.get_13f_candidates())


def test_get_13f_candidates_no_filings():
    """No 13F-HR filings raises a descriptive error (cik branch)."""

    class _Fetcher:
        async def fetch_data(self, params, creds):
            # Assert the cik branch populated params.
            assert params["cik"] == "1067983"
            assert params["form_type"] == "13F-HR"
            return []

    # The fetcher is imported inside the function from its defining module.
    with patch("openbb_sec.models.company_filings.SecCompanyFilingsFetcher", _Fetcher):
        with pytest.raises(OpenBBError, match="No 13F-HR filings"):
            asyncio.run(parse_13f.get_13f_candidates(cik="1067983"))


def test_get_13f_candidates_no_filings_symbol_branch():
    """The symbol branch populates params['symbol'] and raises on no filings."""

    class _Fetcher:
        async def fetch_data(self, params, creds):
            assert params["symbol"] == "AAPL"
            assert "cik" not in params
            return []

    with patch("openbb_sec.models.company_filings.SecCompanyFilingsFetcher", _Fetcher):
        with pytest.raises(OpenBBError, match="No 13F-HR filings found for AAPL"):
            asyncio.run(parse_13f.get_13f_candidates(symbol="AAPL"))


def test_get_13f_candidates_returns_filings():
    """Filings return as a report-date-indexed URL series; pre-2013 dropped."""
    from datetime import date
    from types import SimpleNamespace

    def _mk(report_date, url):
        return SimpleNamespace(
            model_dump=lambda rd=report_date, u=url: {
                "report_date": rd,
                "complete_submission_url": u,
            }
        )

    class _Fetcher:
        async def fetch_data(self, params, creds):
            return [
                _mk(date(2023, 9, 30), "https://sec.gov/new.txt"),
                _mk(date(2010, 3, 31), "https://sec.gov/old.txt"),
            ]

    with patch("openbb_sec.models.company_filings.SecCompanyFilingsFetcher", _Fetcher):
        out = asyncio.run(parse_13f.get_13f_candidates(symbol="BRK-A"))
    assert out.loc[date(2023, 9, 30)] == "https://sec.gov/new.txt"
    assert date(2010, 3, 31) not in out.index


def test_get_complete_submission_uses_amake_request(monkeypatch):
    """get_complete_submission calls the rate-limited request with the callback."""
    captured = {}

    async def _amake(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return "FILING TEXT"

    monkeypatch.setattr("openbb_sec.utils.ratelimit.sec_amake_request", _amake)
    out = asyncio.run(parse_13f.get_complete_submission("https://sec.gov/x.txt"))
    assert out == "FILING TEXT"
    assert captured["url"] == "https://sec.gov/x.txt"
    assert (
        captured["kwargs"]["response_callback"]
        is parse_13f.complete_submission_callback
    )


def test_complete_submission_callback_status():
    """complete_submission_callback returns text on 200, raises otherwise."""

    class _Ok:
        status = 200

        async def text(self):
            return "BODY"

    class _Bad:
        status = 503

        async def text(self):
            return ""

    assert asyncio.run(parse_13f.complete_submission_callback(_Ok(), None)) == "BODY"
    with pytest.raises(OpenBBError, match="status code 503"):
        asyncio.run(parse_13f.complete_submission_callback(_Bad(), None))


_HEADER_XML = (
    "<edgarSubmission>"
    "<headerData><submissionType>13F-HR</submissionType>"
    "<filerInfo><periodOfReport>03-31-2023</periodOfReport></filerInfo>"
    "</headerData></edgarSubmission>"
)


def test_parse_header_and_submission_type():
    """parse_header extracts headerData; submission type & period read from it."""
    header = parse_13f.parse_header(_HEADER_XML)
    assert header["submissionType"] == "13F-HR"
    assert parse_13f.get_submission_type(_HEADER_XML) == "13F-HR"
    assert parse_13f.get_period_ending(_HEADER_XML) == "03-31-2023"


def test_get_submission_type_text_fallback():
    """When submissionType is absent, the '#text' value is returned."""
    # headerData with a text body + attribute parses to {'@a':..,'#text':..}.
    xml = '<edgarSubmission><headerData a="x">MYFORM</headerData></edgarSubmission>'
    assert parse_13f.get_submission_type(xml) == "MYFORM"


def test_parse_header_namespaced_falls_back_to_type():
    """A namespaced <headerData> trips the KeyError fallback, which then reads
    the <type> element instead."""
    filing_str = (
        '<?xml version="1.0"?>'
        '<edgarSubmission xmlns:ns1="http://www.sec.gov/edgar/x">'
        "<ns1:headerData><a>1</a></ns1:headerData>"
        "<type><submissionType>13F-HR</submissionType></type>"
        "</edgarSubmission>"
    )
    header = parse_13f.parse_header(filing_str)
    assert header == {"submissionType": "13F-HR"}


def test_parse_header_empty_header_raises():
    """An empty <headerData> parses to a falsy dict and raises."""
    xml = "<edgarSubmission><headerData></headerData></edgarSubmission>"
    with pytest.raises(OpenBBError, match="Failed to parse the form header"):
        parse_13f.parse_header(xml)


def test_get_period_ending_raises_without_filer_info():
    """A header lacking filerInfo raises a period-of-report error."""
    xml = "<edgarSubmission><headerData><submissionType>4</submissionType></headerData></edgarSubmission>"
    with pytest.raises(OpenBBError, match="period of report"):
        parse_13f.get_period_ending(xml)


_INFO_TABLE_XML = """<?xml version="1.0"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
<headerData>
 <submissionType>13F-HR</submissionType>
 <filerInfo><periodOfReport>03-31-2023</periodOfReport></filerInfo>
</headerData>
<formData>
<informationTable>
 <infoTable>
  <nameOfIssuer>ACME CORP</nameOfIssuer>
  <titleOfClass>COM</titleOfClass>
  <cusip>000000000</cusip>
  <value>1000</value>
  <shrsOrPrnAmt><sshPrnamt>500</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  <putCall>Put</putCall>
  <investmentDiscretion>SOLE</investmentDiscretion>
  <votingAuthority><Sole>500</Sole><Shared>0</Shared><None>0</None></votingAuthority>
 </infoTable>
 <infoTable>
  <nameOfIssuer>ACME CORP</nameOfIssuer>
  <titleOfClass>COM</titleOfClass>
  <cusip>000000000</cusip>
  <value>2000</value>
  <shrsOrPrnAmt><sshPrnamt>1000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  <investmentDiscretion>SOLE</investmentDiscretion>
  <votingAuthority><Sole>1000</Sole><Shared>0</Shared><None>0</None></votingAuthority>
 </infoTable>
</informationTable>
</formData>
</edgarSubmission>"""


def test_parse_13f_hr_aggregates_and_weights():
    """parse_13f_hr unpacks nested objects, aggregates by CUSIP, and weights."""
    records = asyncio.run(parse_13f.parse_13f_hr(_INFO_TABLE_XML))
    assert len(records) == 2
    # Sorted by weight descending; the 2000-value (no put/call) row is first.
    assert records[0]["value"] == 2000
    assert records[0]["principal_amount"] == 1000
    assert records[0]["security_type"] == "SH"
    assert records[0]["putCall"] is None  # "--" replaced with None
    assert records[0]["voting_authority_sole"] == 1000
    assert str(records[0]["period_ending"]) == "2023-03-31"
    assert round(sum(r["weight"] for r in records), 6) == 1.0
    # The put option row carries its putCall value.
    put_row = next(r for r in records if r["value"] == 1000)
    assert put_row["putCall"] == "Put"


def test_parse_13f_hr_url_fetches_submission():
    """A https filing argument is downloaded via get_complete_submission."""

    async def _fake_get(url):
        return _INFO_TABLE_XML

    with patch.object(parse_13f, "get_complete_submission", _fake_get):
        records = asyncio.run(
            parse_13f.parse_13f_hr("https://sec.gov/filing.txt", use_cache=False)
        )
    assert len(records) == 2


def test_parse_13f_hr_url_cache_hit(monkeypatch):
    """A cached parse is returned without downloading the filing."""

    async def _aget(key):
        return [{"value": 1}]

    async def _boom(url):
        raise AssertionError("should not download on a cache hit")

    monkeypatch.setattr("openbb_sec.utils.cache.aget_cached", _aget)
    monkeypatch.setattr(parse_13f, "get_complete_submission", _boom)
    records = asyncio.run(parse_13f.parse_13f_hr("https://sec.gov/x.txt"))
    assert records == [{"value": 1}]


def test_parse_13f_hr_url_cache_write(monkeypatch):
    """A freshly parsed URL filing is written to the cache."""
    saved: dict = {}

    async def _aget(key):
        return None

    async def _aset(key, value, expire=None):
        saved["key"] = key
        saved["value"] = value

    async def _fake_get(url):
        return _INFO_TABLE_XML

    monkeypatch.setattr("openbb_sec.utils.cache.aget_cached", _aget)
    monkeypatch.setattr("openbb_sec.utils.cache.aset_cached", _aset)
    monkeypatch.setattr(parse_13f, "get_complete_submission", _fake_get)
    records = asyncio.run(parse_13f.parse_13f_hr("https://sec.gov/x.txt"))
    assert len(records) == 2
    assert saved["key"] == "GET https://sec.gov/x.txt ::13f-parsed"
    assert saved["value"] == records


def test_parse_13f_hr_period_regex_fallback():
    """A period tag the fast regex misses falls back to header parsing."""
    xml = (
        '<?xml version="1.0"?>\n<edgarSubmission>\n'
        "<headerData><filerInfo>"
        "<periodOfReport >03-31-2023</periodOfReport>"
        "</filerInfo></headerData>\n"
        "<informationTable><infoTable>"
        "<nameOfIssuer>X CORP</nameOfIssuer><titleOfClass>COM</titleOfClass>"
        "<cusip>000000000</cusip><value>10</value>"
        "<shrsOrPrnAmt><sshPrnamt>5</sshPrnamt><sshPrnamtType>SH</sshPrnamtType>"
        "</shrsOrPrnAmt><investmentDiscretion>SOLE</investmentDiscretion>"
        "<votingAuthority><Sole>5</Sole></votingAuthority>"
        "</infoTable></informationTable>\n</edgarSubmission>"
    )
    records = asyncio.run(parse_13f.parse_13f_hr(xml))
    assert str(records[0]["period_ending"]) == "2023-03-31"


def test_parse_13f_hr_single_info_table():
    """A single infoTable (dict, not list) is wrapped and parsed."""
    single = """<?xml version="1.0"?>
<edgarSubmission>
<headerData><filerInfo><periodOfReport>06-30-2023</periodOfReport></filerInfo></headerData>
<informationTable>
 <infoTable>
  <nameOfIssuer>SOLO CORP</nameOfIssuer>
  <titleOfClass>COM</titleOfClass>
  <cusip>111111111</cusip>
  <value>4242</value>
  <shrsOrPrnAmt><sshPrnamt>42</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  <investmentDiscretion>SOLE</investmentDiscretion>
  <votingAuthority><Sole>42</Sole></votingAuthority>
 </infoTable>
</informationTable>
</edgarSubmission>"""
    records = asyncio.run(parse_13f.parse_13f_hr(single))
    assert len(records) == 1
    assert records[0]["value"] == 4242
    assert records[0]["weight"] == 1.0


def test_parse_13f_hr_zero_value_filing_weights_zero():
    """A filing whose only row is the zero-value placeholder weights it 0.0."""
    xml = """<?xml version="1.0"?>
<edgarSubmission>
<headerData><filerInfo><periodOfReport>03-31-2026</periodOfReport></filerInfo></headerData>
<informationTable>
 <infoTable>
  <nameOfIssuer>NA</nameOfIssuer>
  <titleOfClass>COM</titleOfClass>
  <cusip>000000000</cusip>
  <value>0</value>
  <shrsOrPrnAmt><sshPrnamt>0</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  <investmentDiscretion>SOLE</investmentDiscretion>
  <votingAuthority><Sole>0</Sole><Shared>0</Shared><None>0</None></votingAuthority>
 </infoTable>
</informationTable>
</edgarSubmission>"""
    records = asyncio.run(parse_13f.parse_13f_hr(xml))
    assert len(records) == 1
    assert records[0]["value"] == 0
    assert records[0]["weight"] == 0.0


@pytest.mark.parametrize("prefix", ["", "ns1", "n1"])
def test_parse_13f_hr_sgml_submission_keeps_ampersands(prefix):
    """Entities in an SGML-wrapped complete submission decode to ``&``."""
    p = f"{prefix}:" if prefix else ""
    xmlns = f"xmlns:{prefix}" if prefix else "xmlns"
    filing = (
        "<SEC-DOCUMENT>0000000000-26-000001.txt : 20260515\n<SEC-HEADER>\n</SEC-HEADER>\n"
        "<DOCUMENT>\n<TYPE>13F-HR\n<TEXT>\n<XML>\n"
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<edgarSubmission><headerData><filerInfo>"
        "<periodOfReport>03-31-2026</periodOfReport>"
        "</filerInfo></headerData></edgarSubmission>\n</XML>\n</TEXT>\n</DOCUMENT>\n"
        "<DOCUMENT>\n<TYPE>INFORMATION TABLE\n<TEXT>\n<XML>\n"
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<{p}informationTable {xmlns}="http://www.sec.gov/edgar/x">'
        f"<{p}infoTable><{p}nameOfIssuer>BABCOCK &amp; WILCOX</{p}nameOfIssuer>"
        f"<{p}titleOfClass>S&amp;P500 EQL WGT</{p}titleOfClass>"
        f"<{p}cusip>05614L209</{p}cusip><{p}value>100</{p}value>"
        f"<{p}shrsOrPrnAmt><{p}sshPrnamt>10</{p}sshPrnamt>"
        f"<{p}sshPrnamtType>SH</{p}sshPrnamtType></{p}shrsOrPrnAmt>"
        f"<{p}investmentDiscretion>SOLE</{p}investmentDiscretion>"
        f"<{p}votingAuthority><{p}Sole>10</{p}Sole></{p}votingAuthority></{p}infoTable>"
        f"</{p}informationTable>\n</XML>\n</TEXT>\n</DOCUMENT>\n</SEC-DOCUMENT>\n"
    )
    records = asyncio.run(parse_13f.parse_13f_hr(filing))
    assert records[0]["nameOfIssuer"] == "BABCOCK & WILCOX"
    assert records[0]["titleOfClass"] == "S&P500 EQL WGT"


def test_parse_13f_hr_non_numeric_share_and_voting_values():
    """Non-numeric share/voting values trigger the ``except ValueError`` branches.

    A non-numeric ``sshPrnamt`` makes ``int(...)`` raise inside the shrsOrPrnAmt
    unpack, so no ``principal_amount`` / ``security_type`` columns are produced;
    likewise a non-numeric ``Sole`` skips the voting-authority columns. The row
    still parses with its integer ``value``.
    """
    xml = """<?xml version="1.0"?>
<edgarSubmission>
<headerData><filerInfo><periodOfReport>03-31-2023</periodOfReport></filerInfo></headerData>
<informationTable>
 <infoTable>
  <nameOfIssuer>X CORP</nameOfIssuer>
  <titleOfClass>COM</titleOfClass>
  <cusip>000000000</cusip>
  <value>10</value>
  <shrsOrPrnAmt><sshPrnamt>NOTANUMBER</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  <investmentDiscretion>SOLE</investmentDiscretion>
  <votingAuthority><Sole>BAD</Sole><Shared>0</Shared><None>0</None></votingAuthority>
 </infoTable>
</informationTable>
</edgarSubmission>"""
    records = asyncio.run(parse_13f.parse_13f_hr(xml))
    assert len(records) == 1
    assert records[0]["value"] == 10
    # The ValueError branches leave these derived columns out entirely.
    assert "principal_amount" not in records[0]
    assert "voting_authority_sole" not in records[0]


def test_parse_13f_hr_empty_info_table_raises():
    """An <infoTable> with no children yields parsed_xml=None and raises."""
    xml = """<?xml version="1.0"?>
<edgarSubmission>
<headerData><filerInfo><periodOfReport>03-31-2023</periodOfReport></filerInfo></headerData>
<informationTable><infoTable></infoTable></informationTable>
</edgarSubmission>"""
    with pytest.raises(
        OpenBBError, match="Failed to parse the 13F-HR information table"
    ):
        asyncio.run(parse_13f.parse_13f_hr(xml))


def test_parse_13f_hr_table_fallback_indexes_as_list():
    """When no <informationTable> element is present the parser falls back to the
    last <table>. That fallback must remain a *list* so ``info_table[0]`` selects
    the element; previously it assigned a bare ``Tag`` and ``Tag[0]`` raised
    ``KeyError: 0`` before the downstream lookup ran. With the fix, execution
    reaches the ``["informationTable"]`` lookup, which raises ``KeyError`` on the
    key name (not ``0``) for this minimal input."""
    filing = "<edgarSubmission><table><row>1</row></table></edgarSubmission>"
    with pytest.raises(KeyError, match="informationTable"):
        asyncio.run(parse_13f.parse_13f_hr(filing))


def test_parse_13f_hr_preserves_ampersand_in_issuer_name():
    """Ensure issuer names containing character entities (such as &amp; in S&P500)
    survive SGML-wrapped complete submission files without having the ampersand stripped."""
    filing = """<SEC-DOCUMENT>
COMPANY CONFORMED NAME: AT&T INC.
<DOCUMENT>
<TYPE>INFORMATION TABLE
<TEXT>
<XML>
<edgarSubmission>
<headerData><filerInfo><periodOfReport>03-31-2023</periodOfReport></filerInfo></headerData>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
 <infoTable>
  <nameOfIssuer>S&amp;P500 EQL WGT</nameOfIssuer>
  <titleOfClass>COM</titleOfClass>
  <cusip>78462F103</cusip>
  <value>1000</value>
  <shrsOrPrnAmt><sshPrnamt>100</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  <investmentDiscretion>SOLE</investmentDiscretion>
 </infoTable>
</informationTable>
</edgarSubmission>
</XML>
</TEXT>
</DOCUMENT>
</SEC-DOCUMENT>"""
    records = asyncio.run(parse_13f.parse_13f_hr(filing))
    assert len(records) == 1
    assert records[0]["nameOfIssuer"] == "S&P500 EQL WGT"

