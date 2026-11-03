"""Tests for the SEC fetchers."""

import asyncio
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from openbb_core.app.service.user_service import UserService

from openbb_sec.models.adviser_documents import SecAdviserDocumentsFetcher
from openbb_sec.models.adviser_search import (
    SecAdviserFirmsFetcher,
    SecAdviserIndividualsFetcher,
)
from openbb_sec.models.balance_sheet import SecBalanceSheetFetcher
from openbb_sec.models.balance_sheet_growth import SecBalanceSheetGrowthFetcher
from openbb_sec.models.cash_flow import SecCashFlowStatementFetcher
from openbb_sec.models.cash_flow_growth import SecCashFlowStatementGrowthFetcher
from openbb_sec.models.cik_map import SecCikMapFetcher
from openbb_sec.models.company_filings import SecCompanyFilingsFetcher
from openbb_sec.models.compare_company_facts import SecCompareCompanyFactsFetcher
from openbb_sec.models.equity_ftd import SecEquityFtdFetcher
from openbb_sec.models.equity_search import SecEquitySearchFetcher
from openbb_sec.models.form_13FHR import SecForm13FHRFetcher
from openbb_sec.models.full_text_search import SecFullTextSearchFetcher
from openbb_sec.models.htm_file import SecHtmFileFetcher
from openbb_sec.models.income_statement import SecIncomeStatementFetcher
from openbb_sec.models.income_statement_growth import SecIncomeStatementGrowthFetcher
from openbb_sec.models.insider_trading import SecInsiderTradingFetcher
from openbb_sec.models.institutions_search import SecInstitutionsSearchFetcher
from openbb_sec.models.latest_financial_reports import SecLatestFinancialReportsFetcher
from openbb_sec.models.management_discussion_analysis import (
    SecManagementDiscussionAnalysisFetcher,
)
from openbb_sec.models.nport_disclosure import SecNportDisclosureFetcher
from openbb_sec.models.nport_fund_metrics import SecNportFundMetricsFetcher
from openbb_sec.models.rss_litigation import SecRssLitigationFetcher
from openbb_sec.models.schema_files import SecSchemaFilesFetcher
from openbb_sec.models.sec_as_filed_statements import SecAsFiledStatementsFetcher
from openbb_sec.models.sec_beneficial_ownership import SecBeneficialOwnershipFetcher
from openbb_sec.models.sec_company_overview import SecCompanyOverviewFetcher
from openbb_sec.models.sec_disclosures import SecDisclosuresFetcher
from openbb_sec.models.sec_executive_compensation import (
    SecExecutiveCompensationFetcher,
)
from openbb_sec.models.sec_filing import SecFilingFetcher
from openbb_sec.models.sec_legal_proceedings import SecLegalProceedingsFetcher
from openbb_sec.models.sec_pay_versus_performance import (
    SecPayVersusPerformanceFetcher,
)
from openbb_sec.models.sec_risk_factors import SecRiskFactorsFetcher
from openbb_sec.models.sec_segment_revenue import SecSegmentRevenueFetcher
from openbb_sec.models.sic_search import SecSicSearchFetcher
from openbb_sec.models.symbol_map import SecSymbolMapFetcher
from openbb_sec.utils.company_facts import resolve_company_facts

test_credentials = UserService().default_user_settings.credentials.model_dump()


@pytest.fixture(scope="module")
def vcr_config():
    """VCR configuration."""
    return {
        "filter_headers": [("User-Agent", None)],
        "filter_query_parameters": [
            None,
        ],
    }


@pytest.mark.record_http
def test_sec_symbol_map_fetcher(credentials=test_credentials):
    """Test the SEC Symbol Map fetcher."""
    params = {"query": "0000909832", "use_cache": False}

    fetcher = SecSymbolMapFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_schema_files_fetcher(credentials=test_credentials):
    """Test the SEC Schema Files fetcher."""
    params = {}  # Lists all taxonomy families from the in-memory registry

    fetcher = SecSchemaFilesFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_nport_disclosure_fetcher(credentials=test_credentials):
    """Test the SEC NPORT Disclosure fetcher."""
    params = {"symbol": "DIA", "year": 2025, "quarter": 1, "use_cache": False}

    fetcher = SecNportDisclosureFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_nport_fund_metrics_fetcher(credentials=test_credentials):
    """Test the SEC NPORT Fund Metrics fetcher."""
    params = {"symbol": "XLK", "use_cache": False}

    fetcher = SecNportFundMetricsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_full_text_search_fetcher(credentials=test_credentials):
    """Test the SEC Full-Text Search fetcher."""
    params = {"query": "climate change", "form_type": "8-K", "limit": 10}

    fetcher = SecFullTextSearchFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_sic_search_fetcher(credentials=test_credentials):
    """Test the SEC SIC Search fetcher."""
    params = {"query": "oil", "use_cache": False}

    fetcher = SecSicSearchFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_equity_ftd_fetcher(credentials=test_credentials):
    """Test the SEC Equity FTD fetcher."""
    params = {"symbol": "AAPL", "limit": 1, "use_cache": False}

    fetcher = SecEquityFtdFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_equity_search_fetcher(credentials=test_credentials):
    """Test the SEC Equity Search fetcher."""
    params = {"query": "trust", "use_cache": False}

    fetcher = SecEquitySearchFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_company_filings_fetcher(credentials=test_credentials):
    """Test the SEC Company Filings fetcher."""
    params = {"symbol": "AAPL", "type": "10-K", "use_cache": False}

    fetcher = SecCompanyFilingsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_institutions_search_fetcher(credentials=test_credentials):
    """Test the SEC Institutions Search fetcher."""
    params = {"query": "Investment Trust", "use_cache": False}

    fetcher = SecInstitutionsSearchFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_adviser_firms_fetcher(credentials=test_credentials):
    """Test the SEC adviser firms fetcher."""
    params = {"query": "citadel", "limit": 20, "use_cache": False}

    query = SecAdviserFirmsFetcher.transform_query(params)
    data = asyncio.run(SecAdviserFirmsFetcher.aextract_data(query, credentials))
    result = SecAdviserFirmsFetcher.transform_data(query, data)

    assert len(result) == 10
    assert result[0].crd == "148826"
    assert "CITADEL SECURITIES LLC" not in {record.name for record in result}


@pytest.mark.record_http
def test_sec_adviser_individuals_fetcher(credentials=test_credentials):
    """Test the SEC adviser individuals fetcher."""
    params = {"query": "john smith", "limit": 2, "use_cache": False}

    fetcher = SecAdviserIndividualsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_adviser_documents_fetcher(credentials=test_credentials):
    """Test the SEC adviser documents fetcher."""
    params = {"crd": "148826", "use_cache": False}

    fetcher = SecAdviserDocumentsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_rss_litigation_fetcher(credentials=test_credentials):
    """Test the SEC RSS Litigation fetcher."""
    params = {"limit": 2}

    fetcher = SecRssLitigationFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_cik_map_fetcher(credentials=test_credentials):
    """Test the SEC CIK map fetcher."""
    params = {"symbol": "OXY", "use_cache": False}

    fetcher = SecCikMapFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_form_13FHR_fetcher(credentials=test_credentials):
    """Test the SEC Form 13FHR fetcher."""
    params = {"symbol": "NVDA", "use_cache": False}

    fetcher = SecForm13FHRFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_compare_company_facts_fetcher(credentials=test_credentials):
    """Test the SEC Compare Company Facts fetcher."""
    params = {
        "symbol": None,
        "fact": "PaymentsForRepurchaseOfCommonStock",
        "year": 2023,
        "calendar_period": None,
        "instantaneous": False,
        "use_cache": False,
    }

    fetcher = SecCompareCompanyFactsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_latest_financial_reports_fetcher(credentials=test_credentials):
    """Test the SEC Latest Financial Reports fetcher."""
    params = {
        "date": date(2024, 11, 5),
        "report_type": "10-K",
    }

    fetcher = SecLatestFinancialReportsFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_insider_trading_fetcher(credentials=test_credentials):
    """Test the SEC Insider Trading fetcher."""
    params = {
        "symbol": "AAPL",
        "start_date": date(2024, 6, 30),
        "end_date": date(2024, 9, 30),
        "use_cache": False,
    }

    fetcher = SecInsiderTradingFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_management_discussion_analysis_fetcher(credentials=test_credentials):
    """Test the SEC Management Discussion Analysis fetcher."""
    params = {
        "symbol": "AAPL",
        "calendar_year": 2024,
        "calendar_period": "Q2",
        "include_tables": True,
        "use_cache": False,
        "raw_html": False,
    }

    fetcher = SecManagementDiscussionAnalysisFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_filing_fetcher(credentials=test_credentials):
    """Test the SEC Filing fetcher."""
    params = {
        "url": "https://www.sec.gov/Archives/edgar/data/21344/000155278124000634/",
        "use_cache": False,
    }

    fetcher = SecFilingFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_htm_file_fetcher(credentials=test_credentials):
    """Test the SEC HTM File fetcher."""
    params = {
        "url": "https://www.sec.gov/Archives/edgar/data/1990353/000110465925015513/tm256977d7_ex99-1.htm",
        "use_cache": False,
    }

    fetcher = SecHtmFileFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


# ---------------------------------------------------------------------------
# Financial statement fetcher tests using BLK fixture (no HTTP)
# ---------------------------------------------------------------------------

_FIXTURE_DIR = Path(__file__).parent / "record"


@pytest.fixture(scope="module")
def blk_facts():
    """Load the BLK company-facts fixture (parsed once per module)."""
    with open(_FIXTURE_DIR / "CIK0002012383.json") as f:
        return json.load(f)


def _mock_get_standardized(blk_facts):
    async def _inner(
        symbol=None,
        cik=None,
        fiscal_years=None,
        period="both",
        *,
        use_cache=True,
        pit_mode=False,
        include_preliminary=False,
        as_of_date=None,
    ):
        return resolve_company_facts(
            blk_facts,
            period=period,
            include_preliminary=include_preliminary,
            pit_mode=pit_mode,
            as_of_date=as_of_date,
        )

    return _inner


def test_sec_income_statement_fetcher(blk_facts, credentials=test_credentials):
    """Test the SEC Income Statement fetcher."""
    params = {"symbol": "BLK", "period": "annual", "use_cache": False}
    fetcher = SecIncomeStatementFetcher()
    with patch(
        "openbb_sec.utils.company_facts.get_standardized_financials",
        new=_mock_get_standardized(blk_facts),
    ):
        result = fetcher.test(params, credentials)
    assert result is None


def test_sec_balance_sheet_fetcher(blk_facts, credentials=test_credentials):
    """Test the SEC Balance Sheet fetcher."""
    params = {"symbol": "BLK", "period": "annual", "use_cache": False}
    fetcher = SecBalanceSheetFetcher()
    with patch(
        "openbb_sec.utils.company_facts.get_standardized_financials",
        new=_mock_get_standardized(blk_facts),
    ):
        result = fetcher.test(params, credentials)
    assert result is None


def test_sec_cash_flow_fetcher(blk_facts, credentials=test_credentials):
    """Test the SEC Cash Flow Statement fetcher."""
    params = {"symbol": "BLK", "period": "annual", "use_cache": False}
    fetcher = SecCashFlowStatementFetcher()
    with patch(
        "openbb_sec.utils.company_facts.get_standardized_financials",
        new=_mock_get_standardized(blk_facts),
    ):
        result = fetcher.test(params, credentials)
    assert result is None


def test_sec_income_statement_growth_fetcher(blk_facts, credentials=test_credentials):
    """Test the SEC Income Statement Growth fetcher."""
    params = {"symbol": "BLK", "period": "annual", "use_cache": False}
    fetcher = SecIncomeStatementGrowthFetcher()
    with patch(
        "openbb_sec.utils.company_facts.get_standardized_financials",
        new=_mock_get_standardized(blk_facts),
    ):
        result = fetcher.test(params, credentials)
    assert result is None


def test_sec_balance_sheet_growth_fetcher(blk_facts, credentials=test_credentials):
    """Test the SEC Balance Sheet Growth fetcher."""
    params = {"symbol": "BLK", "period": "annual", "use_cache": False}
    fetcher = SecBalanceSheetGrowthFetcher()
    with patch(
        "openbb_sec.utils.company_facts.get_standardized_financials",
        new=_mock_get_standardized(blk_facts),
    ):
        result = fetcher.test(params, credentials)
    assert result is None


def test_sec_cash_flow_growth_fetcher(blk_facts, credentials=test_credentials):
    """Test the SEC Cash Flow Statement Growth fetcher."""
    params = {"symbol": "BLK", "period": "annual", "use_cache": False}
    fetcher = SecCashFlowStatementGrowthFetcher()
    with patch(
        "openbb_sec.utils.company_facts.get_standardized_financials",
        new=_mock_get_standardized(blk_facts),
    ):
        result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_sec_filing_section_fetchers(credentials=test_credentials):
    """Test the filing-section fetchers against one shared 10-K filing.

    All section fetchers resolve to the same filing, which is parsed once
    (memoized by URL), so the shared cassette records the filing a single time.
    """
    params = {
        "symbol": "WDFC",
        "calendar_year": 2024,
        "calendar_period": "Q3",
        "use_cache": False,
    }

    assert SecDisclosuresFetcher().test(params, credentials) is None
    assert SecRiskFactorsFetcher().test(params, credentials) is None
    assert SecCompanyOverviewFetcher().test(params, credentials) is None
    assert SecSegmentRevenueFetcher().test(params, credentials) is None
    assert SecLegalProceedingsFetcher().test(params, credentials) is None
    assert (
        SecAsFiledStatementsFetcher().test(
            {**params, "statement_type": "balance"}, credentials
        )
        is None
    )


@pytest.mark.record_http
def test_sec_proxy_statement_fetchers(credentials=test_credentials):
    """Test the DEF 14A-based fetchers against one shared proxy statement.

    All proxy fetchers resolve to the same DEF 14A, downloaded once (cached by
    URL), so the shared cassette records the filing a single time.
    """
    params = {"symbol": "CAT", "calendar_year": 2024, "use_cache": False}

    assert SecBeneficialOwnershipFetcher().test(params, credentials) is None
    assert SecExecutiveCompensationFetcher().test(params, credentials) is None
    assert SecPayVersusPerformanceFetcher().test(params, credentials) is None
