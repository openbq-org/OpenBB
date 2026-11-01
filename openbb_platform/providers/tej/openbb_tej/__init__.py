
"""TEJ Provider Models."""

from openbb_core.provider.abstract.provider import Provider
from openbb_tej.models.equity_historical import TEJEquityHistoricalFetcher
from openbb_tej.models.income_statement import TEJIncomeStatementFetcher
from openbb_tej.models.balance_sheet import TEJBalanceSheetFetcher
from openbb_tej.models.cash_flow import TEJCashFlowStatementFetcher

tej_provider = Provider(
    name="tej",
    website="https://www.tej.com.tw",
    description="Taiwan Economic Journal (TEJ) Data Provider",
    credentials=["api_key"],
    fetcher_dict={
        "EquityHistorical": TEJEquityHistoricalFetcher,
        "IncomeStatement": TEJIncomeStatementFetcher,
        "BalanceSheet": TEJBalanceSheetFetcher,
        "CashFlowStatement": TEJCashFlowStatementFetcher,
    },
)
