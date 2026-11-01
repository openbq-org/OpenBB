"""Unit tests for TEJ provider modules."""

from datetime import date

import pytest
from dotenv import load_dotenv

load_dotenv()

from openbb_core.app.service.user_service import UserService
from openbb_tej.models.balance_sheet import TEJBalanceSheetFetcher
from openbb_tej.models.cash_flow import TEJCashFlowStatementFetcher
from openbb_tej.models.equity_historical import TEJEquityHistoricalFetcher
from openbb_tej.models.income_statement import TEJIncomeStatementFetcher

test_credentials = UserService().default_user_settings.credentials.model_dump(
    mode="json"
)


@pytest.mark.record_http
def test_tej_equity_historical_fetcher(credentials=test_credentials):
    """Test TEJ equity historical fetcher."""
    params = {
        "symbol": "2330",
        "start_date": date(2024, 1, 1),
        "end_date": date(2024, 1, 31),
    }

    fetcher = TEJEquityHistoricalFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_tej_balance_sheet_fetcher(credentials=test_credentials):
    """Test TEJ balance sheet fetcher."""
    params = {
        "symbol": "2330",
        "start_date": date(2024, 1, 1),
        "end_date": date(2024, 12, 31),
    }

    fetcher = TEJBalanceSheetFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_tej_income_statement_fetcher(credentials=test_credentials):
    """Test TEJ income statement fetcher."""
    params = {
        "symbol": "2330",
        "start_date": date(2024, 1, 1),
        "end_date": date(2024, 12, 31),
    }

    fetcher = TEJIncomeStatementFetcher()
    result = fetcher.test(params, credentials)
    assert result is None


@pytest.mark.record_http
def test_tej_cash_flow_fetcher(credentials=test_credentials):
    """Test TEJ cash flow statement fetcher."""
    params = {
        "symbol": "2330",
        "start_date": date(2024, 1, 1),
        "end_date": date(2024, 12, 31),
    }

    fetcher = TEJCashFlowStatementFetcher()
    result = fetcher.test(params, credentials)
    assert result is None
