"""Tests for the financial statement transforms."""

import pytest

from openbb_tmx.utils.financials import to_snake_case, transform_reports

REPORTS = [
    {
        "reportPeriod": "A",
        "reportYear": 2025,
        "reportQuarter": 4,
        "periodEndDate": "2025-12-31",
        "currency": "CAD",
        "IncomeStatement": {"TotalRevenue": 100, "BasicEPS": 1.5},
        "BalanceSheet": {"TotalAssets": 900},
        "CashFlow": {"OperatingCashFlow": 50},
    },
    {
        "reportPeriod": "Q",
        "reportYear": 2026,
        "reportQuarter": 1,
        "periodEndDate": "2026-03-31",
        "currency": "CAD",
        "IncomeStatement": {"TotalRevenue": 30},
        "BalanceSheet": {},
        "CashFlow": {"OperatingCashFlow": 10},
    },
]


class TestSnakeCase:
    """Key conversion."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("TotalRevenue", "total_revenue"),
            ("BasicEPS", "basic_eps"),
            ("EBITDA", "ebitda"),
            ("PurchaseOfPPE", "purchase_of_ppe"),
            (
                "NetIncomeFromContinuingOperations",
                "net_income_from_continuing_operations",
            ),
        ],
    )
    def test_converts_keys(self, raw, expected):
        assert to_snake_case(raw) == expected


class TestTransformReports:
    """Flattening reports into statement rows."""

    def test_income_rows_are_newest_first(self):
        rows = transform_reports(REPORTS, "income")
        assert [r["period_ending"] for r in rows] == ["2026-03-31", "2025-12-31"]

    def test_annual_and_quarterly_periods(self):
        rows = transform_reports(REPORTS, "income")
        assert rows[0]["fiscal_period"] == "Q1"
        assert rows[1]["fiscal_period"] == "annual"

    def test_line_items_are_snake_cased(self):
        rows = transform_reports(REPORTS, "income")
        assert rows[1]["total_revenue"] == 100
        assert rows[1]["basic_eps"] == 1.5

    def test_empty_statement_is_skipped(self):
        rows = transform_reports(REPORTS, "balance")
        assert len(rows) == 1
        assert rows[0]["total_assets"] == 900

    def test_currency_is_carried(self):
        assert transform_reports(REPORTS, "cash")[0]["reported_currency"] == "CAD"

    def test_missing_period_end_is_skipped(self):
        assert transform_reports([{"IncomeStatement": {"A": 1}}], "income") == []

    def test_query_accepts_as_of_date(self):
        from datetime import date

        from openbb_tmx.models.income_statement import TmxIncomeStatementFetcher

        q = TmxIncomeStatementFetcher.transform_query(
            {"symbol": "RY", "as_of_date": "2025-12-31"}
        )
        assert q.as_of_date == date(2025, 12, 31)
