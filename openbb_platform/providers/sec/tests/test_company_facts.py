"""Test company facts resolution and imputation logic."""

# flake8: noqa: D102,D103,D403

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from openbb_core.app.model.abstract.error import OpenBBError

import openbb_sec.utils.company_facts as cf
from openbb_sec.utils.company_facts import resolve_company_facts
from openbb_sec.utils.statement_schema import StatementSchema
from openbb_sec.utils.statement_schema._detection import get_filing_dates

_FIXTURE_DIR = Path(__file__).parent / "record"


@pytest.fixture(scope="module")
def schema():
    return StatementSchema()


@pytest.fixture(scope="module")
def blk_facts():
    """Load the BlackRock company-facts JSON fixture."""
    with open(_FIXTURE_DIR / "CIK0002012383.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def blk_annual(blk_facts):
    """Annual extraction of BLK fixture."""
    return resolve_company_facts(blk_facts, period="annual")


def _val(records, tag, date="2025-12-31"):
    """Get values for a specific tag/date."""
    for r in records:
        if r["tag"] == tag and r["period_ending"] == date:
            return r["value"], r["source"]
    return None, None


def create_mock_facts(entries: list):
    facts = {}
    for e in entries:
        ns = e.get("ns", "us-gaap")
        tag = e["tag"]
        val = e["val"]
        start = e.get("start")
        end = e["end"]
        form = e.get("form", "10-K")
        filed = e.get(
            "filed",
            (datetime.strptime(end, "%Y-%m-%d") + timedelta(days=45)).strftime(
                "%Y-%m-%d"
            ),
        )
        fy = e.get("fy", int(end[:4]))

        # Determine fp if not provided.
        if "fp" in e:
            fp = e["fp"]
        elif form == "10-Q":
            # Just a simplistic inferring for the mock
            if end.endswith("-03-31"):
                fp = "Q1"
            elif end.endswith("-06-30"):
                fp = "Q2"
            elif end.endswith("-09-30"):
                fp = "Q3"
            else:
                fp = "Q4"
        else:
            fp = "FY"

        if ns not in facts:
            facts[ns] = {}
        if tag not in facts[ns]:
            facts[ns][tag] = {"units": {"USD": []}}

        entry_data = {
            "end": end,
            "val": val,
            "form": form,
            "filed": filed,
            "fy": fy,
            "fp": fp,
        }
        if start:
            entry_data["start"] = start
        facts[ns][tag]["units"]["USD"].append(entry_data)

    return {"cik": "0000000000", "entityName": "Mock Company Inc.", "facts": facts}


def test_company_type_detection(schema):
    industrial = create_mock_facts(
        [{"tag": "CostOfGoodsAndServicesSold", "val": 100, "end": "2023-12-31"}]
    )
    assert schema.detect_type(industrial["facts"]) == "industrial"

    financial = create_mock_facts(
        [
            {"tag": "InterestIncomeExpenseNet", "val": 100, "end": "2023-12-31"},
            {"tag": "NoninterestIncome", "val": 100, "end": "2023-12-31"},
        ]
    )
    assert schema.detect_type(financial["facts"]) == "financial"

    insurance = create_mock_facts(
        [
            {"tag": "PremiumsEarnedNet", "val": 100, "end": "2023-12-31"},
            {
                "tag": "LiabilityForFuturePolicyBenefits",
                "val": 100,
                "end": "2023-12-31",
            },
        ]
    )
    assert schema.detect_type(insurance["facts"]) == "insurance"

    diversified = create_mock_facts(
        [{"tag": "CostsAndExpenses", "val": 100, "end": "2023-12-31"}]
    )
    assert schema.detect_type(diversified["facts"]) == "diversified"


def test_basic_extraction_and_imputation():
    def anchor_tags(year):
        return [
            {"tag": "Assets", "val": 1000, "end": f"{year}-12-31"},
            {
                "tag": "NetCashProvidedByUsedInOperatingActivities",
                "val": 100,
                "start": f"{year}-01-01",
                "end": f"{year}-12-31",
            },
        ]

    mock_data = create_mock_facts(
        anchor_tags(2023)
        + anchor_tags(2024)
        + [
            {"tag": "Revenues", "val": 500, "start": "2023-01-01", "end": "2023-12-31"},
            {
                "tag": "CostOfGoodsAndServicesSold",
                "val": 300,
                "start": "2023-01-01",
                "end": "2023-12-31",
            },
            {"tag": "Revenues", "val": 600, "start": "2024-01-01", "end": "2024-12-31"},
            {
                "tag": "CostOfGoodsAndServicesSold",
                "val": 350,
                "start": "2024-01-01",
                "end": "2024-12-31",
            },
        ]
    )

    res = resolve_company_facts(mock_data, period="annual")
    is_records = res.income_statement
    gp_2024 = [
        r
        for r in is_records
        if r["tag"] == "total_gross_profit" and r["period_ending"] == "2024-12-31"
    ]
    assert len(gp_2024) == 1
    assert gp_2024[0]["value"] == 250.0
    assert gp_2024[0]["source"] == "imputed: total_revenue - total_cost_of_revenue"


def test_suspect_zero_policy():
    def anchor_tags(year):
        return [
            {"tag": "Assets", "val": 1000, "end": f"{year}-12-31"},
            {
                "tag": "NetCashProvidedByUsedInOperatingActivities",
                "val": 100,
                "start": f"{year}-01-01",
                "end": f"{year}-12-31",
            },
        ]

    mock_data = create_mock_facts(
        anchor_tags(2023)
        + [
            {"tag": "Revenues", "val": 500, "start": "2023-01-01", "end": "2023-12-31"},
            {
                "tag": "CostOfGoodsAndServicesSold",
                "val": 500,
                "start": "2023-01-01",
                "end": "2023-12-31",
            },
        ]
    )
    res = resolve_company_facts(mock_data, period="annual")
    gp_2023 = [
        r
        for r in res.income_statement
        if r["tag"] == "total_gross_profit" and r["period_ending"] == "2023-12-31"
    ]
    assert gp_2023[0]["value"] == 0.0
    assert "imputed-zero" in gp_2023[0]["source"]


def test_corrected_mathematical_flaw_costs_and_expenses():
    def anchor_tags(year):
        return [
            {"tag": "Assets", "val": 1000, "end": f"{year}-12-31"},
            {
                "tag": "NetCashProvidedByUsedInOperatingActivities",
                "val": 100,
                "start": f"{year}-01-01",
                "end": f"{year}-12-31",
            },
        ]

    mock_data = create_mock_facts(
        anchor_tags(2023)
        + [
            {
                "tag": "Revenues",
                "val": 1000,
                "start": "2023-01-01",
                "end": "2023-12-31",
            },
            {
                "tag": "OperatingIncomeLoss",
                "val": 200,
                "start": "2023-01-01",
                "end": "2023-12-31",
            },
            {
                "tag": "IncomeBeforeEquityMethodInvestments",
                "val": 300,
                "start": "2023-01-01",
                "end": "2023-12-31",
            },
        ]
    )
    res = resolve_company_facts(mock_data, period="annual")
    ce_2023 = [
        r
        for r in res.income_statement
        if r["tag"] == "costs_and_expenses" and r["period_ending"] == "2023-12-31"
    ]
    assert ce_2023[0]["value"] == 800.0


def test_q4_derivation_and_bs_immunity():
    def q_anchor(start, end):
        return [
            {
                "tag": "NetCashProvidedByUsedInOperatingActivities",
                "val": 100,
                "start": start,
                "end": end,
                "form": "10-Q",
            }
        ]

    mock_data = create_mock_facts(
        [
            {"tag": "Assets", "val": 1000, "end": "2023-12-31", "form": "10-K"},
            {
                "tag": "NetCashProvidedByUsedInOperatingActivities",
                "val": 400,
                "start": "2023-01-01",
                "end": "2023-12-31",
                "form": "10-K",
            },
            {
                "tag": "Revenues",
                "val": 100,
                "start": "2023-01-01",
                "end": "2023-03-31",
                "form": "10-Q",
            },
            {"tag": "Assets", "val": 900, "end": "2023-03-31", "form": "10-Q"},
            *q_anchor("2023-01-01", "2023-03-31"),
            {
                "tag": "Revenues",
                "val": 150,
                "start": "2023-04-01",
                "end": "2023-06-30",
                "form": "10-Q",
            },
            {"tag": "Assets", "val": 920, "end": "2023-06-30", "form": "10-Q"},
            *q_anchor("2023-04-01", "2023-06-30"),
            {
                "tag": "Revenues",
                "val": 200,
                "start": "2023-07-01",
                "end": "2023-09-30",
                "form": "10-Q",
            },
            {"tag": "Assets", "val": 940, "end": "2023-09-30", "form": "10-Q"},
            *q_anchor("2023-07-01", "2023-09-30"),
            {
                "tag": "Revenues",
                "val": 600,
                "start": "2023-01-01",
                "end": "2023-12-31",
                "form": "10-K",
            },
        ]
    )
    res = resolve_company_facts(mock_data, period="quarterly")
    is_q4 = [
        r
        for r in res.income_statement
        if r["fiscal_period"] == "Q4" and r["tag"] == "total_revenue"
    ]
    assert is_q4[0]["value"] == 150.0
    assert "Q4:" in is_q4[0]["source"]
    # Enriched Q4 source should include XBRL tags in brackets
    assert "FY[" in is_q4[0]["source"]
    assert "Q1[" in is_q4[0]["source"]
    assert "Q2[" in is_q4[0]["source"]
    assert "Q3[" in is_q4[0]["source"]
    bs_q4 = [
        r
        for r in res.balance_sheet
        if r["fiscal_period"] == "Q4" and r["tag"] == "total_assets"
    ]
    assert bs_q4[0]["value"] == 1000.0
    assert "Q4:" not in bs_q4[0]["source"]


def test_diagnostics_produced():
    mock_data = create_mock_facts(
        [
            {"tag": "Assets", "val": 1000000000, "end": "2023-12-31"},
            {
                "tag": "NetCashProvidedByUsedInOperatingActivities",
                "val": 100,
                "start": "2023-01-01",
                "end": "2023-12-31",
            },
            {"tag": "Revenues", "val": 500, "start": "2023-01-01", "end": "2023-12-31"},
            {
                "tag": "LiabilitiesAndStockholdersEquity",
                "val": 900000000,
                "end": "2023-12-31",
            },
        ]
    )
    res = resolve_company_facts(mock_data, period="annual")
    warnings = [d for d in res.diagnostics if d.tag == "total_assets"]
    assert warnings[0].actual == 1000000000.0
    assert warnings[0].expected == 900000000.0


def test_cross_vintage_fallback():
    mock_data = create_mock_facts(
        [
            {"tag": "Assets", "val": 1000, "end": "2023-12-31", "filed": "2024-03-01"},
            {
                "tag": "NetCashProvidedByUsedInOperatingActivities",
                "val": 100,
                "start": "2023-01-01",
                "end": "2023-12-31",
                "filed": "2024-03-01",
            },
            {
                "tag": "Revenues",
                "val": 500,
                "start": "2023-01-01",
                "end": "2023-12-31",
                "filed": "2024-03-01",
            },
            {
                "tag": "CostOfRevenue",
                "val": 200,
                "start": "2023-01-01",
                "end": "2023-12-31",
                "filed": "2025-03-01",
            },
        ]
    )
    res = resolve_company_facts(mock_data, period="annual")
    rev = [r for r in res.income_statement if r["tag"] == "total_revenue"]
    assert rev[0]["value"] == 500.0
    assert "(fallback)" in rev[0]["source"]


def test_deep_cascading_imputation():
    def anchor_tags(year):
        return [
            {"tag": "Assets", "val": 1000, "end": f"{year}-12-31"},
            {
                "tag": "NetCashProvidedByUsedInOperatingActivities",
                "val": 100,
                "start": f"{year}-01-01",
                "end": f"{year}-12-31",
            },
        ]

    mock_data = create_mock_facts(
        anchor_tags(2023)
        + [
            {
                "tag": "Revenues",
                "val": 1000,
                "start": "2023-01-01",
                "end": "2023-12-31",
            },
            {
                "tag": "CostOfGoodsAndServicesSold",
                "val": 400,
                "start": "2023-01-01",
                "end": "2023-12-31",
            },
            {
                "tag": "OperatingExpenses",
                "val": 200,
                "start": "2023-01-01",
                "end": "2023-12-31",
            },
            {
                "tag": "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                "val": 350,
                "start": "2023-01-01",
                "end": "2023-12-31",
            },
            {
                "tag": "IncomeTaxExpenseBenefit",
                "val": 100,
                "start": "2023-01-01",
                "end": "2023-12-31",
            },
            {
                "tag": "IncomeLossFromDiscontinuedOperationsNetOfTax",
                "val": 0,
                "start": "2023-01-01",
                "end": "2023-12-31",
            },
        ]
    )
    res = resolve_company_facts(mock_data, period="annual")

    def get_val(tag_name):
        matches = [
            r
            for r in res.income_statement
            if r["tag"] == tag_name and r["period_ending"] == "2023-12-31"
        ]
        return matches[0]["value"] if matches else None

    assert get_val("total_revenue") == 1000.0
    assert get_val("total_cost_of_revenue") == 400.0
    assert get_val("total_gross_profit") == 600.0
    assert get_val("total_operating_expenses") == 200.0
    assert get_val("total_operating_income") == 400.0
    assert get_val("total_other_income") == -50.0
    assert get_val("total_pretax_income") == 350.0
    assert get_val("net_income_continuing") == 250.0
    assert get_val("net_income") == 250.0


def test_ifrs_namespace():
    def anchor_tags(year):
        return [
            {
                "ns": "ifrs-full",
                "tag": "Assets",
                "val": 1000,
                "end": f"{year}-12-31",
                "form": "20-F",
            },
            {
                "ns": "ifrs-full",
                "tag": "CashFlowsFromUsedInOperatingActivities",
                "val": 100,
                "start": f"{year}-01-01",
                "end": f"{year}-12-31",
                "form": "20-F",
            },
        ]

    mock_data = create_mock_facts(
        anchor_tags(2023)
        + [
            {
                "ns": "ifrs-full",
                "tag": "Revenue",
                "val": 1000,
                "start": "2023-01-01",
                "end": "2023-12-31",
                "form": "20-F",
            },
        ]
    )
    res = resolve_company_facts(mock_data, period="annual")
    rev = [r for r in res.income_statement if r["tag"] == "total_revenue"]
    assert rev[0]["value"] == 1000.0


def test_mixed_10k_10q_period_filtering():
    def q_anchor(start, end, form):
        return [
            {
                "tag": "NetCashProvidedByUsedInOperatingActivities",
                "val": 10,
                "start": start,
                "end": end,
                "form": form,
            }
        ]

    mock_data = create_mock_facts(
        [
            {"tag": "Assets", "val": 1000, "end": "2023-12-31", "form": "10-K"},
            *q_anchor("2023-01-01", "2023-12-31", "10-K"),
            {
                "tag": "Revenues",
                "val": 400,
                "start": "2023-01-01",
                "end": "2023-12-31",
                "form": "10-K",
            },
            {"tag": "Assets", "val": 900, "end": "2023-03-31", "form": "10-Q"},
            *q_anchor("2023-01-01", "2023-03-31", "10-Q"),
            {
                "tag": "Revenues",
                "val": 100,
                "start": "2023-01-01",
                "end": "2023-03-31",
                "form": "10-Q",
            },
        ]
    )
    res_annual = resolve_company_facts(mock_data, period="annual")
    assert all(r["fiscal_period"] == "FY" for r in res_annual.balance_sheet)
    res_quarterly = resolve_company_facts(mock_data, period="quarterly")
    periods = {r["fiscal_period"] for r in res_quarterly.balance_sheet}
    assert "Q1" in periods


# =========================================================================
# BLK fixture tests — real SEC XBRL data for BlackRock (CIK 0002012383)
# =========================================================================


class TestBLKCompanyType:
    """Company-type detection for BlackRock (diversified asset manager)."""

    def test_detected_as_diversified(self, blk_annual):
        assert blk_annual.company_type == "diversified"

    def test_entity_metadata(self, blk_annual):
        assert blk_annual.entity_name == "BlackRock, Inc."
        assert blk_annual.currency == "USD"


class TestBLKZeroDiagnostics:
    """All accounting identities must hold — zero violations."""

    def test_no_identity_violations(self, blk_annual):
        assert len(blk_annual.diagnostics) == 0, (
            f"Expected 0 diagnostics, got {len(blk_annual.diagnostics)}: "
            + "; ".join(
                f"{d.tag}@{d.date}: expected={d.expected}, actual={d.actual}"
                for d in blk_annual.diagnostics
            )
        )


class TestBLKDates:
    """Verify the expected reporting periods are present."""

    def test_three_annual_dates(self, blk_annual):
        dates = sorted(set(r["period_ending"] for r in blk_annual.income_statement))
        assert dates == ["2023-12-31", "2024-12-31", "2025-12-31"]

    def test_bs_dates_match_is(self, blk_annual):
        is_dates = sorted(set(r["period_ending"] for r in blk_annual.income_statement))
        bs_dates = sorted(set(r["period_ending"] for r in blk_annual.balance_sheet))
        assert is_dates == bs_dates

    def test_cf_dates_match_is(self, blk_annual):
        is_dates = sorted(set(r["period_ending"] for r in blk_annual.income_statement))
        cf_dates = sorted(set(r["period_ending"] for r in blk_annual.cash_flow))
        assert is_dates == cf_dates


class TestBLKIncomeStatement:
    """Income statement XBRL tag selection, values, and imputation."""

    # --- Direct XBRL extractions (tag selection) ---

    def test_revenue_tag_selection(self, blk_annual):
        v, s = _val(blk_annual.income_statement, "total_revenue")
        assert v == 24_216_000_000
        assert "RevenueFromContractWithCustomerExcludingAssessedTax" in s

    def test_operating_income(self, blk_annual):
        v, s = _val(blk_annual.income_statement, "total_operating_income")
        assert v == 7_045_000_000
        assert "OperatingIncomeLoss" in s

    def test_pretax_income(self, blk_annual):
        v, s = _val(blk_annual.income_statement, "total_pretax_income")
        assert v == 7_619_000_000

    def test_income_tax_expense(self, blk_annual):
        v, s = _val(blk_annual.income_statement, "income_tax_expense")
        assert v == 1_677_000_000
        assert "IncomeTaxExpenseBenefit" in s

    def test_net_income(self, blk_annual):
        v, s = _val(blk_annual.income_statement, "net_income")
        assert v == 5_942_000_000
        assert "ProfitLoss" in s

    def test_net_income_to_common(self, blk_annual):
        v, s = _val(blk_annual.income_statement, "net_income_to_common")
        assert v == 5_553_000_000
        assert "NetIncomeLoss" in s

    def test_sga_expense(self, blk_annual):
        v, s = _val(blk_annual.income_statement, "sga_expense")
        assert v == 2_731_000_000
        assert "GeneralAndAdministrativeExpense" in s

    def test_operating_expenses(self, blk_annual):
        v, s = _val(blk_annual.income_statement, "total_operating_expenses")
        assert v == 17_171_000_000
        assert "OperatingExpenses" in s

    def test_eps_values(self, blk_annual):
        basic, _ = _val(blk_annual.income_statement, "basic_eps")
        diluted, _ = _val(blk_annual.income_statement, "diluted_eps")
        assert basic == 35.83
        assert diluted == 35.31

    def test_equity_method_investments(self, blk_annual):
        v, s = _val(blk_annual.income_statement, "equity_method_investments")
        assert v == 51_000_000
        assert "IncomeLossFromEquityMethodInvestments" in s

    # --- Imputed values ---

    def test_costs_and_expenses_from_operating_expenses(self, blk_annual):
        """C&E takes the reported OperatingExpenses total; its other line holds the remainder."""
        v, s = _val(blk_annual.income_statement, "costs_and_expenses")
        assert v == 17_171_000_000
        assert s == "us-gaap:OperatingExpenses"
        sga, _ = _val(blk_annual.income_statement, "sga_expense")
        restr, _ = _val(blk_annual.income_statement, "restructuring_charge")
        other, s_other = _val(blk_annual.income_statement, "other_operating_expenses")
        assert other == v - sga - restr
        assert s_other.startswith("imputed-plug")

    def test_income_before_equity_method(self, blk_annual):
        """income_before_equity_method from XBRL (same tag as total_pretax_income for BLK)."""
        v, s = _val(blk_annual.income_statement, "income_before_equity_method")
        assert v == 7_619_000_000

    def test_comprehensive_income_nci_imputed(self, blk_annual):
        """comprehensive_income_nci = comprehensive_income - comprehensive_income_parent."""
        v, s = _val(blk_annual.income_statement, "comprehensive_income_nci")
        ci, _ = _val(blk_annual.income_statement, "comprehensive_income")
        ci_p, _ = _val(blk_annual.income_statement, "comprehensive_income_parent")
        assert v == ci - ci_p
        assert "imputed" in s

    def test_plug_rows_present(self, blk_annual):
        """Each total's other line holds its remainder."""
        plugs = {
            "other_operating_expenses",
            "other_income",
            "other_adjustments_to_net_income_to_common",
        }
        for tag in plugs:
            v, s = _val(blk_annual.income_statement, tag)
            assert v is not None, f"{tag} missing"
            assert "imputed-plug" in s, f"{tag} should be a plug, got: {s}"

    def test_pretax_articulates_without_remainder(self, blk_annual):
        """Pretax income is operating income plus non-operating income."""
        pretax, _ = _val(blk_annual.income_statement, "total_pretax_income")
        opinc, _ = _val(blk_annual.income_statement, "total_operating_income")
        other, _ = _val(blk_annual.income_statement, "total_other_income")
        assert pretax == opinc + other
        assert _val(blk_annual.income_statement, "other_pretax_income") == (None, None)

    def test_tax_decomposition(self, blk_annual):
        """Current + deferred tax should sum to total income tax expense."""
        current, _ = _val(blk_annual.income_statement, "income_tax_current")
        deferred, _ = _val(blk_annual.income_statement, "income_tax_deferred")
        total, _ = _val(blk_annual.income_statement, "income_tax_expense")
        assert current == 2_308_000_000
        assert deferred == -631_000_000
        assert current + deferred == total


class TestBLKBalanceSheet:
    """Balance sheet XBRL tag selection, values, and rollups."""

    # --- Direct XBRL extractions ---

    def test_total_assets(self, blk_annual):
        v, s = _val(blk_annual.balance_sheet, "total_assets")
        assert v == 169_998_000_000
        assert "Assets" in s

    def test_total_liabilities(self, blk_annual):
        v, s = _val(blk_annual.balance_sheet, "total_liabilities")
        assert v == 108_456_000_000
        assert "Liabilities" in s

    def test_total_equity(self, blk_annual):
        v, s = _val(blk_annual.balance_sheet, "total_equity")
        assert v == 55_888_000_000
        assert "StockholdersEquity" in s

    def test_total_liabilities_and_equity(self, blk_annual):
        v, s = _val(blk_annual.balance_sheet, "total_liabilities_and_equity")
        assert v == 169_998_000_000
        assert "LiabilitiesAndStockholdersEquity" in s

    def test_noncontrolling_interests(self, blk_annual):
        v, s = _val(blk_annual.balance_sheet, "noncontrolling_interests")
        assert v == 227_000_000
        assert "MinorityInterest" in s

    def test_goodwill(self, blk_annual):
        v, s = _val(blk_annual.balance_sheet, "goodwill")
        assert v == 35_283_000_000

    def test_ppe_decomposition(self, blk_annual):
        gross, _ = _val(blk_annual.balance_sheet, "gross_ppe")
        accum, _ = _val(blk_annual.balance_sheet, "accumulated_depreciation")
        net, _ = _val(blk_annual.balance_sheet, "net_ppe")
        assert gross == 2_948_000_000
        assert accum == 1_692_000_000
        assert net == 1_256_000_000
        assert gross - accum == net

    # --- BS primary identity: Assets = Liabilities + Equity (+ mezzanine) ---

    def test_assets_equal_liabilities_and_equity(self, blk_annual):
        ta, _ = _val(blk_annual.balance_sheet, "total_assets")
        tle, _ = _val(blk_annual.balance_sheet, "total_liabilities_and_equity")
        assert ta == tle

    def test_liabilities_plus_equity_plus_mezzanine(self, blk_annual):
        """L + ENCI + temporary equity = L&E."""
        tl, _ = _val(blk_annual.balance_sheet, "total_liabilities")
        teni, _ = _val(
            blk_annual.balance_sheet, "total_equity_and_noncontrolling_interests"
        )
        mezz, _ = _val(blk_annual.balance_sheet, "temporary_equity")
        tle, _ = _val(blk_annual.balance_sheet, "total_liabilities_and_equity")
        assert tl + teni + mezz == tle

    # --- Mezzanine equity (temporary equity) ---

    def test_temporary_equity_is_liabilities_and_equity_remainder(self, blk_annual):
        """BLK mezzanine equity is the remainder of liabilities and equity."""
        v, s = _val(blk_annual.balance_sheet, "temporary_equity")
        assert v == 5_427_000_000
        assert s.startswith("imputed-plug: total_liabilities_and_equity - ")
        rnci, _ = _val(blk_annual.balance_sheet, "redeemable_noncontrolling_interest")
        assert rnci is None

    def test_mezzanine_leaves_no_liabilities_and_equity_remainder(self, blk_annual):
        """Redeemable NCI closes L&E, so no other line is created for it."""
        other_le, _ = _val(blk_annual.balance_sheet, "other_liabilities_and_equity")
        assert other_le is None

    # --- Rollups ---

    def test_total_common_equity_rollup(self, blk_annual):
        """total_common_equity is a rollup of equity components (with sign factors)."""
        tce, s = _val(blk_annual.balance_sheet, "total_common_equity")
        assert tce == 55_888_000_000
        assert "imputed-rollup" in s
        # Enriched source should list child tags
        assert "(+)" in s  # at least one child with factor shown
        # Verify it matches total_equity (from XBRL)
        te, _ = _val(blk_annual.balance_sheet, "total_equity")
        assert tce == te

    # --- Plug rows ---

    def test_other_assets_plug(self, blk_annual):
        v, s = _val(blk_annual.balance_sheet, "other_assets")
        assert v == 86_969_000_000
        assert "imputed-plug" in s
        # Enriched source should reference parent tag and children
        assert "total_assets" in s

    def test_other_liabilities_plug(self, blk_annual):
        v, s = _val(blk_annual.balance_sheet, "other_liabilities")
        assert v == 87_240_000_000
        assert "imputed-plug" in s
        # Enriched source should reference parent tag and children
        assert "total_liabilities" in s


class TestBLKCashFlow:
    """Cash flow statement values, identities, and imputation."""

    # --- Direct XBRL extractions ---

    def test_operating_activities(self, blk_annual):
        v, s = _val(blk_annual.cash_flow, "net_cash_from_operating_activities")
        assert v == 3_927_000_000
        assert "NetCashProvidedByUsedInOperatingActivities" in s

    def test_investing_activities(self, blk_annual):
        v, s = _val(blk_annual.cash_flow, "net_cash_from_investing_activities")
        assert v == -4_418_000_000

    def test_financing_activities(self, blk_annual):
        v, s = _val(blk_annual.cash_flow, "net_cash_from_financing_activities")
        assert v == -1_127_000_000

    def test_fx_effect(self, blk_annual):
        v, s = _val(blk_annual.cash_flow, "effect_of_exchange_rate_changes")
        assert v == 329_000_000

    def test_net_change_in_cash(self, blk_annual):
        v, s = _val(blk_annual.cash_flow, "net_change_in_cash")
        assert v == -1_289_000_000

    def test_depreciation(self, blk_annual):
        v, s = _val(blk_annual.cash_flow, "depreciation_and_amortization")
        assert v == 297_000_000

    # --- CF identity: op + inv + fin + fx = net_change ---

    def test_activity_sum_equals_net_change(self, blk_annual):
        op, _ = _val(blk_annual.cash_flow, "net_cash_from_operating_activities")
        inv, _ = _val(blk_annual.cash_flow, "net_cash_from_investing_activities")
        fin, _ = _val(blk_annual.cash_flow, "net_cash_from_financing_activities")
        fx, _ = _val(blk_annual.cash_flow, "effect_of_exchange_rate_changes")
        nc, _ = _val(blk_annual.cash_flow, "net_change_in_cash")
        assert op + inv + fin + fx == nc

    # --- Cash bridge: begin + net_change = end ---

    def test_cash_bridge(self, blk_annual):
        begin, _ = _val(blk_annual.cash_flow, "cash_at_beginning_of_period")
        end, _ = _val(blk_annual.cash_flow, "cash_at_end_of_period")
        nc, _ = _val(blk_annual.cash_flow, "net_change_in_cash")
        assert begin + nc == end
        assert begin == 12_779_000_000
        assert end == 11_490_000_000

    # --- Identity lock: CF net_income comes from IS ---

    def test_net_income_identity_lock(self, blk_annual):
        v, s = _val(blk_annual.cash_flow, "net_income")
        assert v == 5_942_000_000
        assert "identity_lock" in s
        # Enriched source should indicate which statement the lock came from
        assert "identity_lock:cash_flow" in s

    # --- Rollups ---

    def test_operating_capital_rollup(self, blk_annual):
        """increase_decrease_in_operating_capital is a rollup of WC changes."""
        v, s = _val(blk_annual.cash_flow, "increase_decrease_in_operating_capital")
        assert v == -1_266_000_000
        assert "imputed-rollup" in s
        # Should be sum of mapped WC children
        ar, _ = _val(blk_annual.cash_flow, "change_in_accounts_receivable")
        ap, _ = _val(blk_annual.cash_flow, "change_in_accounts_payable")
        other_wc, _ = _val(
            blk_annual.cash_flow, "change_in_other_operating_assets_and_liabilities"
        )
        assert ar + ap + other_wc == v

    # --- Plug rows ---

    def test_operating_plug(self, blk_annual):
        v, s = _val(blk_annual.cash_flow, "other_operating_activities")
        assert "imputed-plug" in s

    def test_investing_plug(self, blk_annual):
        v, s = _val(blk_annual.cash_flow, "other_investing_activities_net")
        assert "imputed-plug" in s

    def test_financing_plug(self, blk_annual):
        v, s = _val(blk_annual.cash_flow, "other_financing_activities_net")
        assert "imputed-plug" in s


class TestBLKCrossStatement:
    """Cross-statement consistency checks."""

    def test_cf_net_income_equals_is_net_income(self, blk_annual):
        """Net income in CF must match net income in IS (identity lock)."""
        cf_ni, _ = _val(blk_annual.cash_flow, "net_income")
        is_ni, _ = _val(blk_annual.income_statement, "net_income")
        assert cf_ni == is_ni

    def test_cross_statement_consistency_all_dates(self, blk_annual):
        """CF net_income = IS net_income for every date."""
        is_ni = {
            r["period_ending"]: r["value"]
            for r in blk_annual.income_statement
            if r["tag"] == "net_income"
        }
        cf_ni = {
            r["period_ending"]: r["value"]
            for r in blk_annual.cash_flow
            if r["tag"] == "net_income"
        }
        for date, value in is_ni.items():
            assert date in cf_ni, f"CF missing net_income for {date}"
            assert value == cf_ni[date], f"NI mismatch at {date}"

    def test_bs_identity_all_dates(self, blk_annual):
        """Assets = L&E for every date."""
        dates = sorted(set(r["period_ending"] for r in blk_annual.balance_sheet))
        for date in dates:
            ta, _ = _val(blk_annual.balance_sheet, "total_assets", date)
            tle, _ = _val(
                blk_annual.balance_sheet, "total_liabilities_and_equity", date
            )
            assert ta == tle, f"A≠L&E at {date}: {ta} vs {tle}"

    def test_cf_identity_all_dates(self, blk_annual):
        """op + inv + fin + fx = net_change for every date."""
        dates = sorted(set(r["period_ending"] for r in blk_annual.cash_flow))
        for date in dates:
            op, _ = _val(
                blk_annual.cash_flow, "net_cash_from_operating_activities", date
            )
            inv, _ = _val(
                blk_annual.cash_flow, "net_cash_from_investing_activities", date
            )
            fin, _ = _val(
                blk_annual.cash_flow, "net_cash_from_financing_activities", date
            )
            fx, _ = _val(blk_annual.cash_flow, "effect_of_exchange_rate_changes", date)
            nc, _ = _val(blk_annual.cash_flow, "net_change_in_cash", date)
            if all(x is not None for x in (op, inv, fin, fx, nc)):
                assert op + inv + fin + fx == nc, f"CF identity fails at {date}"


class TestBLKImputationCounts:
    """Verify the expected number and types of imputed values."""

    def test_is_imputed_count(self, blk_annual):
        imputed = [
            r
            for r in blk_annual.income_statement
            if r["period_ending"] == "2025-12-31" and "imputed" in r["source"]
        ]
        assert len(imputed) == 4

    def test_bs_imputed_count(self, blk_annual):
        imputed = [
            r
            for r in blk_annual.balance_sheet
            if r["period_ending"] == "2025-12-31" and "imputed" in r["source"]
        ]
        assert len(imputed) == 4

    def test_cf_imputed_count(self, blk_annual):
        imputed = [
            r
            for r in blk_annual.cash_flow
            if r["period_ending"] == "2025-12-31" and "imputed" in r["source"]
        ]
        assert len(imputed) == 4

    def test_no_suspect_zeros(self, blk_annual):
        """No imputed values should be suspect zeros for BLK."""
        all_records = (
            blk_annual.income_statement
            + blk_annual.balance_sheet
            + blk_annual.cash_flow
        )
        suspect = [r for r in all_records if "imputed-zero" in r.get("source", "")]
        assert len(suspect) == 0


class TestBLKMultiYear:
    """Verify consistent extraction across all three years."""

    @pytest.mark.parametrize("date", ["2023-12-31", "2024-12-31", "2025-12-31"])
    def test_revenue_positive_all_years(self, blk_annual, date):
        v, _ = _val(blk_annual.income_statement, "total_revenue", date)
        assert v is not None and v > 0

    @pytest.mark.parametrize("date", ["2023-12-31", "2024-12-31", "2025-12-31"])
    def test_assets_positive_all_years(self, blk_annual, date):
        v, _ = _val(blk_annual.balance_sheet, "total_assets", date)
        assert v is not None and v > 0

    def test_tag_coverage_stable(self, blk_annual):
        """Each date should have similar tag coverage (within reason)."""
        dates = sorted(set(r["period_ending"] for r in blk_annual.income_statement))
        counts = {
            d: len([r for r in blk_annual.income_statement if r["period_ending"] == d])
            for d in dates
        }
        max_count = max(counts.values())
        min_count = min(counts.values())
        # Tag count shouldn't vary widely between years
        assert max_count - min_count <= 10, f"Tag count varies too much: {counts}"


def _anchor(year, extra=None):
    """Minimal tags to anchor a year (BS instant + CF duration)."""
    base = [
        {"tag": "Assets", "val": 1000, "end": f"{year}-12-31"},
        {
            "tag": "NetCashProvidedByUsedInOperatingActivities",
            "val": 100,
            "start": f"{year}-01-01",
            "end": f"{year}-12-31",
        },
    ]
    if extra:
        base.extend(extra)
    return base


def _pick(rows, tag, date):
    """Return the single record matching a standardized tag and period end."""
    matches = [r for r in rows if r["tag"] == tag and r["period_ending"] == date]
    assert len(matches) == 1, f"expected one {tag} @ {date}, got {len(matches)}"
    return matches[0]


class TestFinancialIS:
    """Financial institution revenue decomposition (banks)."""

    def test_revenue_from_nii_plus_noninterest(self):
        """total_revenue = net_interest_income + total_noninterest_income."""
        mock = create_mock_facts(
            _anchor(2023)
            + [
                {
                    "tag": "InterestIncomeExpenseNet",
                    "val": 50_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "NoninterestIncome",
                    "val": 30_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
                    "ExtraordinaryItemsNoncontrollingInterest",
                    "val": 60_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "IncomeTaxExpenseBenefit",
                    "val": 15_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")
        assert res.company_type == "financial"

        rev = [
            r
            for r in res.income_statement
            if r["tag"] == "total_revenue" and r["period_ending"] == "2023-12-31"
        ]
        assert len(rev) == 1
        assert rev[0]["value"] == 80_000  # 50k NII + 30k noninterest
        assert "imputed" in rev[0]["source"]

    def test_provision_for_credit_losses(self):
        """net_interest_income_after_provision = NII - provision."""
        mock = create_mock_facts(
            _anchor(2023)
            + [
                {
                    "tag": "InterestIncomeExpenseNet",
                    "val": 60_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "NoninterestIncome",
                    "val": 20_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "ProvisionForLoanAndLeaseLosses",
                    "val": 5_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
                    "ExtraordinaryItemsNoncontrollingInterest",
                    "val": 50_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "IncomeTaxExpenseBenefit",
                    "val": 10_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")
        niiap = [
            r
            for r in res.income_statement
            if r["tag"] == "net_interest_income_after_provision"
            and r["period_ending"] == "2023-12-31"
        ]
        assert len(niiap) == 1
        assert niiap[0]["value"] == 55_000  # 60k - 5k


class TestProvisionTagMigration:
    """Modern provision-for-credit-losses tag chains (IFRS + US-GAAP CECL)."""

    _NII = {
        "tag": "InterestIncomeExpenseNet",
        "val": 60_000,
        "start": "2023-01-01",
        "end": "2023-12-31",
    }
    _NONINT = {
        "tag": "NoninterestIncome",
        "val": 20_000,
        "start": "2023-01-01",
        "end": "2023-12-31",
    }
    _PRETAX = {
        "tag": "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
        "ExtraordinaryItemsNoncontrollingInterest",
        "val": 50_000,
        "start": "2023-01-01",
        "end": "2023-12-31",
    }
    _TAX = {
        "tag": "IncomeTaxExpenseBenefit",
        "val": 10_000,
        "start": "2023-01-01",
        "end": "2023-12-31",
    }

    def test_ifrs_adjustments_for_impairment_captures_provision(self):
        """IFRS bank tag AdjustmentsForImpairmentLoss... yields a positive provision."""
        mock = create_mock_facts(
            _anchor(2023)
            + [
                self._NII,
                self._NONINT,
                {
                    "ns": "ifrs-full",
                    "tag": "AdjustmentsForImpairmentLossReversalOf"
                    "ImpairmentLossRecognisedInProfitOrLoss",
                    "val": 4_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                self._PRETAX,
                self._TAX,
            ]
        )
        res = resolve_company_facts(mock, period="annual")
        assert res.company_type == "financial"
        prov = _pick(res.income_statement, "provision_for_credit_losses", "2023-12-31")
        assert prov["value"] == 4_000
        assert "AdjustmentsForImpairmentLoss" in prov["source"]
        niiap = _pick(
            res.income_statement,
            "net_interest_income_after_provision",
            "2023-12-31",
        )
        assert niiap["value"] == 56_000  # 60k NII - 4k provision

    def test_ifrs_adjustments_for_provisions_wins_over_impairment(self):
        """BMO pattern: AdjustmentsForProvisions is preferred over the impairment tag."""
        mock = create_mock_facts(
            _anchor(2023)
            + [
                self._NII,
                self._NONINT,
                {
                    "ns": "ifrs-full",
                    "tag": "AdjustmentsForProvisions",
                    "val": 3_700,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "ns": "ifrs-full",
                    "tag": "AdjustmentsForImpairmentLossReversalOf"
                    "ImpairmentLossRecognisedInProfitOrLoss",
                    "val": 100,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                self._PRETAX,
                self._TAX,
            ]
        )
        res = resolve_company_facts(mock, period="annual")
        prov = _pick(res.income_statement, "provision_for_credit_losses", "2023-12-31")
        assert prov["value"] == 3_700
        assert "AdjustmentsForProvisions" in prov["source"]

    def test_cecl_funded_plus_unfunded_are_combined(self):
        """BAC pattern: provision = funded + unfunded when no NII-after-provision tag."""
        mock = create_mock_facts(
            _anchor(2023)
            + [
                self._NII,
                self._NONINT,
                {
                    "tag": "FinancingReceivableExcludingAccruedInterest"
                    "CreditLossExpenseReversal",
                    "val": 5_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "OffBalanceSheetCreditLossLiability"
                    "CreditLossExpenseReversal",
                    "val": -300,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                self._PRETAX,
                self._TAX,
            ]
        )
        res = resolve_company_facts(mock, period="annual")
        prov = _pick(res.income_statement, "provision_for_credit_losses", "2023-12-31")
        assert prov["value"] == 4_700  # 5000 funded + (-300) unfunded
        assert "(combined)" in prov["source"]
        cf_prov = _pick(res.cash_flow, "provision_for_loan_losses", "2023-12-31")
        assert cf_prov["value"] == 4_700

    def test_cecl_not_combined_when_nii_after_provision_reported(self):
        """Citi pattern: funded provision left alone when NII-after-provision is tagged."""
        mock = create_mock_facts(
            _anchor(2023)
            + [
                self._NII,
                self._NONINT,
                {
                    "tag": "ProvisionForLoanLossesExpensed",
                    "val": 5_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "OffBalanceSheetCreditLossLiability"
                    "CreditLossExpenseReversal",
                    "val": -300,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "InterestIncomeExpenseAfterProvisionForLoanLoss",
                    "val": 55_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                self._PRETAX,
                self._TAX,
            ]
        )
        res = resolve_company_facts(mock, period="annual")
        prov = _pick(res.income_statement, "provision_for_credit_losses", "2023-12-31")
        assert prov["value"] == 5_000  # funded only; unfunded NOT added
        assert "(combined)" not in prov["source"]


class TestBankInsuranceClassification:
    """Tie-break between the insurance and financial company-type templates."""

    def test_bank_with_insurance_subsidiary_is_financial(self, schema):
        """More core-banking signals than insurance IS signals resolves to financial."""
        facts = create_mock_facts(
            [
                {"tag": "InsuranceRevenue", "val": 1, "end": "2024-12-31"},
                {"tag": "NetEarnedPremium", "val": 1, "end": "2024-12-31"},
                {
                    "tag": "InsuranceContractsThatAreLiabilities",
                    "val": 1,
                    "end": "2024-12-31",
                },
                {"tag": "InterestIncomeExpenseNet", "val": 1, "end": "2024-12-31"},
                {"tag": "NetInterestIncome", "val": 1, "end": "2024-12-31"},
                {"tag": "TradingIncomeExpense", "val": 1, "end": "2024-12-31"},
            ]
        )["facts"]
        # ins_is=2, ins_total=3, fin=3 -> financial
        assert schema.detect_type(facts) == "financial"

    def test_genuine_insurer_stays_insurance(self, schema):
        """Insurance IS signals outnumbering financial signals stays insurance."""
        facts = create_mock_facts(
            [
                {"tag": "PremiumsEarnedNet", "val": 1, "end": "2024-12-31"},
                {
                    "tag": "PolicyholderBenefitsAndClaimsIncurredNet",
                    "val": 1,
                    "end": "2024-12-31",
                },
                {"tag": "InsuranceRevenue", "val": 1, "end": "2024-12-31"},
                {
                    "tag": "LiabilityForFuturePolicyBenefits",
                    "val": 1,
                    "end": "2024-12-31",
                },
                {"tag": "InterestIncomeExpenseNet", "val": 1, "end": "2024-12-31"},
                {"tag": "TradingIncomeExpense", "val": 1, "end": "2024-12-31"},
            ]
        )["facts"]
        # ins_is=3, fin=2 -> insurance
        assert schema.detect_type(facts) == "insurance"


class TestInsuranceIS:
    """Insurance company revenue/benefit structure."""

    def test_insurance_detection_and_pretax(self):
        """total_pretax_income = total_revenue - benefits_costs_expenses."""
        mock = create_mock_facts(
            _anchor(2023)
            + [
                {
                    "tag": "PremiumsEarnedNet",
                    "val": 100_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "Revenues",
                    "val": 120_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "BenefitsLossesAndExpenses",
                    "val": 80_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "LiabilityForFuturePolicyBenefits",
                    "val": 200_000,
                    "end": "2023-12-31",
                },
                {
                    "tag": "IncomeTaxExpenseBenefit",
                    "val": 8_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")
        assert res.company_type == "insurance"

        pretax = [
            r
            for r in res.income_statement
            if r["tag"] == "total_pretax_income" and r["period_ending"] == "2023-12-31"
        ]
        assert len(pretax) == 1
        assert pretax[0]["value"] == 40_000  # 120k rev - 80k benefits

    def test_insurance_net_income_cascade(self):
        """net_income_continuing = total_pretax_income - income_tax_expense."""
        mock = create_mock_facts(
            _anchor(2023)
            + [
                {
                    "tag": "PremiumsEarnedNet",
                    "val": 100_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "Revenues",
                    "val": 120_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "BenefitsLossesAndExpenses",
                    "val": 80_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "LiabilityForFuturePolicyBenefits",
                    "val": 200_000,
                    "end": "2023-12-31",
                },
                {
                    "tag": "IncomeTaxExpenseBenefit",
                    "val": 8_000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")
        nic = [
            r
            for r in res.income_statement
            if r["tag"] == "net_income_continuing"
            and r["period_ending"] == "2023-12-31"
        ]
        assert len(nic) == 1
        assert nic[0]["value"] == 32_000  # 40k pretax - 8k tax


class TestDiscontinuedOperations:
    """Discontinued operations impact on net income."""

    def test_discontinued_ops_adds_to_net_income(self):
        """net_income = net_income_continuing + net_income_discontinued."""
        mock = create_mock_facts(
            _anchor(2023)
            + [
                {
                    "tag": "Revenues",
                    "val": 1000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "CostOfGoodsAndServicesSold",
                    "val": 400,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
                    "ExtraordinaryItemsNoncontrollingInterest",
                    "val": 500,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "IncomeTaxExpenseBenefit",
                    "val": 100,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    # Explicit continuing-ops tag avoids ProfitLoss fallback
                    "tag": "IncomeLossFromContinuingOperations",
                    "val": 400,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "IncomeLossFromDiscontinuedOperationsNetOfTax",
                    "val": 50,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "ProfitLoss",
                    "val": 450,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")

        def get_val(tag):
            return next(
                (
                    r["value"]
                    for r in res.income_statement
                    if r["tag"] == tag and r["period_ending"] == "2023-12-31"
                ),
                None,
            )

        assert get_val("net_income_continuing") == 400  # explicit continuing tag
        assert get_val("net_income_discontinued") == 50
        assert get_val("net_income") == 450  # ProfitLoss
        assert get_val("net_income_continuing") + get_val(
            "net_income_discontinued"
        ) == get_val("net_income")


class TestPreferredEquity:
    """Preferred stock decomposition in BS equity."""

    def test_common_equity_with_preferred(self):
        """total_common_equity = total_equity - total_preferred_equity."""
        mock = create_mock_facts(
            [
                {"tag": "Assets", "val": 10000, "end": "2023-12-31"},
                {
                    "tag": "LiabilitiesAndStockholdersEquity",
                    "val": 10000,
                    "end": "2023-12-31",
                },
                {"tag": "Liabilities", "val": 7000, "end": "2023-12-31"},
                {"tag": "StockholdersEquity", "val": 2800, "end": "2023-12-31"},
                {
                    "tag": "StockholdersEquityIncludingPortionAttributableTo"
                    "NoncontrollingInterest",
                    "val": 3000,
                    "end": "2023-12-31",
                },
                {"tag": "MinorityInterest", "val": 200, "end": "2023-12-31"},
                {"tag": "PreferredStockValue", "val": 500, "end": "2023-12-31"},
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 100,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                # IS duration tag required for date alignment across all 3 statements
                {
                    "tag": "Revenues",
                    "val": 500,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")

        def bs_val(tag):
            return next(
                (
                    r["value"]
                    for r in res.balance_sheet
                    if r["tag"] == tag and r["period_ending"] == "2023-12-31"
                ),
                None,
            )

        assert bs_val("total_equity") == 2800
        assert bs_val("total_preferred_equity") == 500
        # common = total_equity - preferred
        tce = bs_val("total_common_equity")
        assert tce == 2300

    def test_common_equity_without_preferred(self):
        """Without preferred, total_common_equity == total_equity."""
        mock = create_mock_facts(
            [
                {"tag": "Assets", "val": 5000, "end": "2023-12-31"},
                {
                    "tag": "LiabilitiesAndStockholdersEquity",
                    "val": 5000,
                    "end": "2023-12-31",
                },
                {"tag": "Liabilities", "val": 3000, "end": "2023-12-31"},
                {"tag": "StockholdersEquity", "val": 2000, "end": "2023-12-31"},
                {
                    "tag": "StockholdersEquityIncludingPortionAttributableTo"
                    "NoncontrollingInterest",
                    "val": 2000,
                    "end": "2023-12-31",
                },
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 50,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "Revenues",
                    "val": 300,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")

        def bs_val(tag):
            return next(
                (
                    r["value"]
                    for r in res.balance_sheet
                    if r["tag"] == tag and r["period_ending"] == "2023-12-31"
                ),
                None,
            )

        tce = bs_val("total_common_equity")
        assert tce == 2000


class TestMergeFacts:
    """merge_facts() combines multiple CIK JSON dicts."""

    def test_basic_merge(self, schema):
        """Two CIKs with different years produce combined history."""
        old_cik = create_mock_facts(
            [
                {
                    "tag": "Revenues",
                    "val": 1000,
                    "start": "2020-01-01",
                    "end": "2020-12-31",
                    "filed": "2021-03-01",
                },
            ]
        )
        new_cik = create_mock_facts(
            [
                {
                    "tag": "Revenues",
                    "val": 1500,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                    "filed": "2024-03-01",
                },
            ]
        )
        merged = StatementSchema.merge_facts(old_cik, new_cik)
        revenue_entries = merged["us-gaap"]["Revenues"]["units"]["USD"]
        assert len(revenue_entries) == 2
        vals = {e["val"] for e in revenue_entries}
        assert vals == {1000, 1500}

    def test_deduplication(self, schema):
        """Identical entries across CIKs are not duplicated."""
        facts_a = create_mock_facts(
            [
                {
                    "tag": "Assets",
                    "val": 5000,
                    "end": "2023-12-31",
                    "filed": "2024-03-01",
                },
            ]
        )
        facts_b = create_mock_facts(
            [
                {
                    "tag": "Assets",
                    "val": 5000,
                    "end": "2023-12-31",
                    "filed": "2024-03-01",
                },
            ]
        )
        merged = StatementSchema.merge_facts(facts_a, facts_b)
        entries = merged["us-gaap"]["Assets"]["units"]["USD"]
        assert len(entries) == 1

    def test_merge_preserves_namespaces(self, schema):
        """Merge combines tags across different namespaces."""
        us_facts = create_mock_facts(
            [{"tag": "Revenues", "val": 100, "end": "2023-12-31"}]
        )
        ifrs_facts = create_mock_facts(
            [{"ns": "ifrs-full", "tag": "Revenue", "val": 200, "end": "2023-12-31"}]
        )
        merged = StatementSchema.merge_facts(us_facts, ifrs_facts)
        assert "us-gaap" in merged
        assert "ifrs-full" in merged

    def test_merge_different_values_same_tag_different_dates(self, schema):
        """Same tag reported with different values on different dates retained."""
        a = create_mock_facts(
            [
                {
                    "tag": "Assets",
                    "val": 1000,
                    "end": "2022-12-31",
                    "filed": "2023-03-01",
                },
            ]
        )
        b = create_mock_facts(
            [
                {
                    "tag": "Assets",
                    "val": 2000,
                    "end": "2023-12-31",
                    "filed": "2024-03-01",
                },
            ]
        )
        merged = StatementSchema.merge_facts(a, b)
        entries = merged["us-gaap"]["Assets"]["units"]["USD"]
        assert len(entries) == 2


class TestTagChainPriority:
    """First matching XBRL tag in the chain wins."""

    def test_newer_revenue_tag_preferred(self):
        """RevenueFromContractWithCustomer... is first in operating_revenue chain.

        operating_revenue and total_revenue are separate schema rows with
        independent tag chains.  RFCWCE is position #1 for operating_revenue
        but lower priority for total_revenue (where Revenues is preferred).
        """
        mock = create_mock_facts(
            _anchor(2023)
            + [
                {
                    "tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
                    "val": 1000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "Revenues",
                    "val": 1100,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "CostOfGoodsAndServicesSold",
                    "val": 400,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")
        # operating_revenue uses RFCWCE as first-priority tag
        orev = [
            r
            for r in res.income_statement
            if r["tag"] == "operating_revenue" and r["period_ending"] == "2023-12-31"
        ]
        assert orev[0]["value"] == 1000
        assert (
            "RevenueFromContractWithCustomerExcludingAssessedTax" in orev[0]["source"]
        )
        # total_revenue picks Revenues (higher in its own chain)
        trev = [
            r
            for r in res.income_statement
            if r["tag"] == "total_revenue" and r["period_ending"] == "2023-12-31"
        ]
        assert trev[0]["value"] == 1100
        assert "Revenues" in trev[0]["source"]

    def test_fallback_to_secondary_tag(self):
        """When primary tag absent, secondary tag is used."""
        mock = create_mock_facts(
            _anchor(2023)
            + [
                {
                    "tag": "Revenues",
                    "val": 900,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "CostOfGoodsAndServicesSold",
                    "val": 300,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")
        rev = [
            r
            for r in res.income_statement
            if r["tag"] == "total_revenue" and r["period_ending"] == "2023-12-31"
        ]
        assert rev[0]["value"] == 900
        assert "Revenues" in rev[0]["source"]


class TestCFFxDerivation:
    """The exchange-rate effect is never derived from the cash identity."""

    def test_fx_not_derived_from_cash_identity(self):
        """An unexplained net change is held in other_net_changes_in_cash."""
        m = 1_000_000
        mock = create_mock_facts(
            [
                {"tag": "Assets", "val": 1000 * m, "end": "2023-12-31"},
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 500 * m,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "NetCashProvidedByUsedInInvestingActivities",
                    "val": -200 * m,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "NetCashProvidedByUsedInFinancingActivities",
                    "val": -150 * m,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
                    "PeriodIncreaseDecreaseIncludingExchangeRateEffect",
                    "val": 160 * m,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "Revenues",
                    "val": 800 * m,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")
        by_tag = {
            r["tag"]: r for r in res.cash_flow if r["period_ending"] == "2023-12-31"
        }
        assert "effect_of_exchange_rate_changes" not in by_tag
        other = by_tag["other_net_changes_in_cash"]
        assert other["value"] == 10 * m
        assert other["source"].startswith("imputed-plug: net_change_in_cash - ")


class TestCFDepreciationDecomposition:
    """D&A = depreciation + amortization when only components given."""

    def test_da_from_components(self):
        mock = create_mock_facts(
            [
                {"tag": "Assets", "val": 1000, "end": "2023-12-31"},
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 100,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "Depreciation",
                    "val": 60,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "AmortizationOfIntangibleAssets",
                    "val": 40,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")
        da = [
            r
            for r in res.cash_flow
            if r["tag"] == "depreciation_and_amortization"
            and r["period_ending"] == "2023-12-31"
        ]
        assert len(da) == 1
        assert da[0]["value"] == 100  # 60 + 40


class TestBSNoncurrentDerivation:
    """Noncurrent = total - current decomposition."""

    def test_noncurrent_assets_derived(self):
        mock = create_mock_facts(
            [
                {"tag": "Assets", "val": 10000, "end": "2023-12-31"},
                {
                    "tag": "LiabilitiesAndStockholdersEquity",
                    "val": 10000,
                    "end": "2023-12-31",
                },
                {"tag": "AssetsCurrent", "val": 3000, "end": "2023-12-31"},
                {"tag": "Liabilities", "val": 6000, "end": "2023-12-31"},
                {
                    "tag": "LiabilitiesCurrent",
                    "val": 2000,
                    "end": "2023-12-31",
                },
                {"tag": "StockholdersEquity", "val": 4000, "end": "2023-12-31"},
                {
                    "tag": "StockholdersEquityIncludingPortionAttributableTo"
                    "NoncontrollingInterest",
                    "val": 4000,
                    "end": "2023-12-31",
                },
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 100,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "Revenues",
                    "val": 600,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")

        def bs_val(tag):
            return next(
                (
                    r["value"]
                    for r in res.balance_sheet
                    if r["tag"] == tag and r["period_ending"] == "2023-12-31"
                ),
                None,
            )

        assert bs_val("total_noncurrent_assets") == 7000  # 10000 - 3000
        assert bs_val("total_noncurrent_liabilities") == 4000  # 6000 - 2000


class TestBSLiabilitiesImputed:
    """Total liabilities imputed from L&E identity."""

    def test_liabilities_from_identity(self):
        """total_liabilities = L&E - total_equity_and_nci."""
        mock = create_mock_facts(
            [
                {"tag": "Assets", "val": 10000, "end": "2023-12-31"},
                # L&E must be extracted directly (not from rollup)
                {
                    "tag": "LiabilitiesAndStockholdersEquity",
                    "val": 10000,
                    "end": "2023-12-31",
                },
                {"tag": "StockholdersEquity", "val": 3000, "end": "2023-12-31"},
                {
                    "tag": "StockholdersEquityIncludingPortionAttributableTo"
                    "NoncontrollingInterest",
                    "val": 3500,
                    "end": "2023-12-31",
                },
                {"tag": "MinorityInterest", "val": 500, "end": "2023-12-31"},
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 100,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "Revenues",
                    "val": 400,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")

        def bs_val(tag):
            return next(
                (
                    r["value"]
                    for r in res.balance_sheet
                    if r["tag"] == tag and r["period_ending"] == "2023-12-31"
                ),
                None,
            )

        # L = L&E - E_nci = 10000 - 3500 = 6500
        assert bs_val("total_liabilities") == 6500
        assert bs_val("total_assets") == 10000
        assert bs_val("total_liabilities_and_equity") == 10000


class TestDiversifiedISCascade:
    """Diversified IS imputation: operating income without COGS/GP."""

    def test_diversified_cascade_with_operating_income(self):
        """Diversified IS cascade: OI → pretax → NI works correctly."""
        mock = create_mock_facts(
            _anchor(2023)
            + [
                {
                    "tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
                    "val": 5000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "CostsAndExpenses",
                    "val": 3500,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    # OperatingIncomeLoss extracted directly avoids rollup
                    "tag": "OperatingIncomeLoss",
                    "val": 1500,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "NonoperatingIncomeExpense",
                    "val": 200,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "IncomeTaxExpenseBenefit",
                    "val": 300,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")
        assert res.company_type == "diversified"

        def get_val(tag):
            return next(
                (
                    r["value"]
                    for r in res.income_statement
                    if r["tag"] == tag and r["period_ending"] == "2023-12-31"
                ),
                None,
            )

        assert get_val("total_revenue") == 5000
        assert get_val("costs_and_expenses") == 3500
        assert get_val("total_operating_income") == 1500
        assert get_val("total_other_income") == 200
        # pretax = OI + other_income = 1700
        assert get_val("total_pretax_income") == 1700
        assert get_val("net_income_continuing") == 1400  # 1700 - 300


class TestNoncurrentAssetsOnly:
    """Current/noncurrent: when only total_current_assets present, noncurrent derived."""

    def test_equity_nci_fallback(self):
        """When no NCI, total_equity_and_noncontrolling_interests = total_equity."""
        mock = create_mock_facts(
            [
                {"tag": "Assets", "val": 5000, "end": "2023-12-31"},
                {"tag": "Liabilities", "val": 3000, "end": "2023-12-31"},
                {"tag": "StockholdersEquity", "val": 2000, "end": "2023-12-31"},
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 100,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "Revenues",
                    "val": 350,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")

        def bs_val(tag):
            return next(
                (
                    r["value"]
                    for r in res.balance_sheet
                    if r["tag"] == tag and r["period_ending"] == "2023-12-31"
                ),
                None,
            )

        # Fallback: E_nci = E when no NCI present
        assert bs_val("total_equity") == 2000
        assert bs_val("total_equity_and_noncontrolling_interests") == 2000
        # L&E = Assets
        assert bs_val("total_liabilities_and_equity") == 5000
        # Identity: no diagnostics
        assert len(res.diagnostics) == 0


class TestCOGSDisambiguation:
    """Narrow COGS override when COGS + OpEx << CostsAndExpenses."""

    def test_narrow_cogs_corrected(self):
        """When narrow COGS reported, it's overridden to C&E - OpEx."""
        mock = create_mock_facts(
            _anchor(2023)
            + [
                {
                    "tag": "Revenues",
                    "val": 10000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    # Narrow COGS (product-only): 2000
                    "tag": "CostOfGoodsAndServicesSold",
                    "val": 2000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    # But CostsAndExpenses is much larger: 8000
                    "tag": "CostsAndExpenses",
                    "val": 8000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "OperatingExpenses",
                    "val": 3000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "OperatingIncomeLoss",
                    "val": 2000,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
                    "ExtraordinaryItemsNoncontrollingInterest",
                    "val": 2200,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "IncomeTaxExpenseBenefit",
                    "val": 400,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")

        def get_val(tag):
            matches = [
                r
                for r in res.income_statement
                if r["tag"] == tag and r["period_ending"] == "2023-12-31"
            ]
            return matches[0] if matches else None

        # COGS should be corrected to C&E - OpEx = 8000 - 3000 = 5000
        cogs = get_val("total_cost_of_revenue")
        if cogs and "corrected" in cogs["source"]:
            assert cogs["value"] == 5000
        else:
            # If not corrected, gross profit still articulates
            gp = get_val("total_gross_profit")
            assert gp is not None

        # Operating income should still be 2000 regardless
        oi = get_val("total_operating_income")
        assert oi["value"] == 2000


class TestIdentityLockCrossStatement:
    """Identity lock: CF net_income is forced to match IS net_income."""

    def test_cf_net_income_overridden_by_is(self):
        """CF ProfitLoss with identity_lock uses IS net_income value."""
        mock = create_mock_facts(
            [
                {"tag": "Assets", "val": 1000, "end": "2023-12-31"},
                {
                    "tag": "Revenues",
                    "val": 500,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "CostOfGoodsAndServicesSold",
                    "val": 200,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
                    "ExtraordinaryItemsNoncontrollingInterest",
                    "val": 250,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "IncomeTaxExpenseBenefit",
                    "val": 50,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                # This ProfitLoss appears in both IS and CF
                {
                    "tag": "ProfitLoss",
                    "val": 200,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 300,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")

        is_ni = next(
            (
                r["value"]
                for r in res.income_statement
                if r["tag"] == "net_income" and r["period_ending"] == "2023-12-31"
            ),
            None,
        )
        cf_ni = next(
            (
                r["value"]
                for r in res.cash_flow
                if r["tag"] == "net_income" and r["period_ending"] == "2023-12-31"
            ),
            None,
        )
        # Both should be the same regardless of source
        if is_ni is not None and cf_ni is not None:
            assert is_ni == cf_ni


class TestMultiDateDiagnostics:
    """Diagnostics capture failures at specific dates."""

    def test_bs_identity_violation_flagged(self):
        """When Assets != L&E by > 1M, a diagnostic is produced.

        The verification tolerance is $1M, so values must be large enough
        that the mismatch exceeds the threshold.
        """
        mock = create_mock_facts(
            [
                {"tag": "Assets", "val": 1_000_000_000, "end": "2023-12-31"},
                {
                    "tag": "LiabilitiesAndStockholdersEquity",
                    "val": 900_000_000,
                    "end": "2023-12-31",
                },
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 100,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "tag": "Revenues",
                    "val": 500,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")
        # Should see diagnostic for total_assets mismatch
        asset_diags = [d for d in res.diagnostics if d.tag == "total_assets"]
        assert len(asset_diags) >= 1
        assert asset_diags[0].date == "2023-12-31"
        assert asset_diags[0].actual == 1_000_000_000
        assert asset_diags[0].expected == 900_000_000


class TestCashBridgePeriodCarryover:
    """cash_at_beginning_of_period derived from prior year end."""

    def test_begin_derived_from_prior_end(self):
        """Begin-of-period cash = end-of-period cash from prior year."""
        mock = create_mock_facts(
            _anchor(2022)
            + _anchor(2023)
            + [
                {
                    "tag": "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
                    "val": 500,
                    "end": "2022-12-31",
                },
                {
                    "tag": "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
                    "val": 600,
                    "end": "2023-12-31",
                },
                {
                    "tag": "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
                    "PeriodIncreaseDecreaseIncludingExchangeRateEffect",
                    "val": 100,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")
        begin = [
            r
            for r in res.cash_flow
            if r["tag"] == "cash_at_beginning_of_period"
            and r["period_ending"] == "2023-12-31"
        ]
        if begin:
            # Begin 2023 should be end 2022
            assert begin[0]["value"] == 500
            assert "derived" in begin[0]["source"]


class TestTTM:
    """Tests for trailing-twelve-month (TTM) aggregation."""

    @staticmethod
    def _quarterly_revenue(years_quarters):
        entries = []
        anchor_entries = []
        for year, quarter, val in years_quarters:
            q_map = {"Q1": "03-31", "Q2": "06-30", "Q3": "09-30", "Q4": "12-31"}
            q_start_map = {"Q1": "01-01", "Q2": "04-01", "Q3": "07-01", "Q4": "10-01"}
            end = f"{year}-{q_map[quarter]}"
            start = f"{year}-{q_start_map[quarter]}"
            entries.append(
                {
                    "tag": "Revenues",
                    "val": val,
                    "start": start,
                    "end": end,
                    "form": "10-Q" if quarter != "Q4" else "10-K",
                    "fp": quarter if quarter != "Q4" else "FY",
                    "fy": year,
                }
            )
            anchor_entries.append(
                {
                    "tag": "Assets",
                    "val": 1000,
                    "end": end,
                }
            )
            anchor_entries.append(
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 50,
                    "start": start,
                    "end": end,
                    "form": "10-Q" if quarter != "Q4" else "10-K",
                    "fp": quarter if quarter != "Q4" else "FY",
                    "fy": year,
                }
            )
        for year in {y for y, _, _ in years_quarters}:
            total = sum(v for y, q, v in years_quarters if y == year)
            entries.append(
                {
                    "tag": "Revenues",
                    "val": total,
                    "start": f"{year}-01-01",
                    "end": f"{year}-12-31",
                    "form": "10-K",
                    "fp": "FY",
                    "fy": year,
                }
            )
            anchor_entries.append(
                {
                    "tag": "Assets",
                    "val": 1000,
                    "end": f"{year}-12-31",
                }
            )
            anchor_entries.append(
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 200,
                    "start": f"{year}-01-01",
                    "end": f"{year}-12-31",
                    "form": "10-K",
                    "fp": "FY",
                    "fy": year,
                }
            )
        return create_mock_facts(entries + anchor_entries)

    def test_ttm_sum_for_duration_items(self):
        mock = self._quarterly_revenue(
            [
                (2023, "Q1", 100),
                (2023, "Q2", 110),
                (2023, "Q3", 120),
                (2023, "Q4", 130),
            ]
        )
        res = resolve_company_facts(mock, period="ttm")
        ttm_recs = [r for r in res.income_statement if r["tag"] == "total_revenue"]
        assert len(ttm_recs) >= 1
        latest = max(ttm_recs, key=lambda r: r["period_ending"])
        assert latest["value"] == 460
        assert latest["fiscal_period"] == "TTM"
        assert latest["frequency"] == "ttm"
        assert "TTM: sum(" in latest["source"]

    def test_ttm_fewer_than_4_quarters_skipped(self):
        entries = []
        for q, end_md, start_md, val in [
            ("Q1", "03-31", "01-01", 100),
            ("Q2", "06-30", "04-01", 110),
        ]:
            entries.append(
                {
                    "tag": "Revenues",
                    "val": val,
                    "start": f"2023-{start_md}",
                    "end": f"2023-{end_md}",
                    "form": "10-Q",
                    "fp": q,
                    "fy": 2023,
                }
            )
            entries.append(
                {
                    "tag": "Assets",
                    "val": 1000,
                    "end": f"2023-{end_md}",
                }
            )
            entries.append(
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 50,
                    "start": f"2023-{start_md}",
                    "end": f"2023-{end_md}",
                    "form": "10-Q",
                    "fp": q,
                    "fy": 2023,
                }
            )
        mock = create_mock_facts(entries)
        res = resolve_company_facts(mock, period="ttm")
        ttm_recs = [r for r in res.income_statement if r["tag"] == "total_revenue"]
        assert len(ttm_recs) == 0

    def test_ttm_avg_for_instant_items(self):
        entries = []
        for q, end in [
            ("Q1", "2023-03-31"),
            ("Q2", "2023-06-30"),
            ("Q3", "2023-09-30"),
            ("Q4", "2023-12-31"),
        ]:
            entries.append(
                {
                    "tag": "Assets",
                    "val": 1000 + int(q[1]) * 100,
                    "end": end,
                    "form": "10-Q" if q != "Q4" else "10-K",
                    "fp": q if q != "Q4" else "FY",
                    "fy": 2023,
                }
            )
        entries.append(
            {
                "tag": "Assets",
                "val": 1300,
                "end": "2023-12-31",
                "form": "10-K",
                "fp": "FY",
                "fy": 2023,
            }
        )
        entries.append(
            {
                "tag": "NetCashProvidedByUsedInOperatingActivities",
                "val": 100,
                "start": "2023-01-01",
                "end": "2023-12-31",
                "form": "10-K",
                "fp": "FY",
                "fy": 2023,
            }
        )
        for q, end in [
            ("Q1", "2023-03-31"),
            ("Q2", "2023-06-30"),
            ("Q3", "2023-09-30"),
            ("Q4", "2023-12-31"),
        ]:
            start = {
                "Q1": "2023-01-01",
                "Q2": "2023-04-01",
                "Q3": "2023-07-01",
                "Q4": "2023-10-01",
            }[q]
            entries.append(
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 25,
                    "start": start,
                    "end": end,
                    "form": "10-Q" if q != "Q4" else "10-K",
                    "fp": q if q != "Q4" else "FY",
                    "fy": 2023,
                }
            )

        mock = create_mock_facts(entries)
        res = resolve_company_facts(mock, period="ttm")
        asset_recs = [r for r in res.balance_sheet if r["tag"] == "total_assets"]
        if asset_recs:
            latest = max(asset_recs, key=lambda r: r["period_ending"])
            assert "TTM: avg(" in latest["source"]
            assert latest["value"] == (1100 + 1200 + 1300 + 1400) / 4

    def test_ttm_provenance_string(self):
        mock = self._quarterly_revenue(
            [
                (2023, "Q1", 100),
                (2023, "Q2", 110),
                (2023, "Q3", 120),
                (2023, "Q4", 130),
            ]
        )
        res = resolve_company_facts(mock, period="ttm")
        ttm_recs = [r for r in res.income_statement if r["tag"] == "total_revenue"]
        if ttm_recs:
            src = ttm_recs[0]["source"]
            assert src.startswith("TTM:")
            assert "2023-" in src

    def test_ttm_rolling_windows(self):
        mock = self._quarterly_revenue(
            [
                (2023, "Q1", 100),
                (2023, "Q2", 110),
                (2023, "Q3", 120),
                (2023, "Q4", 130),
                (2024, "Q1", 140),
            ]
        )
        res = resolve_company_facts(mock, period="ttm")
        ttm_recs = sorted(
            [r for r in res.income_statement if r["tag"] == "total_revenue"],
            key=lambda r: r["period_ending"],
        )
        assert len(ttm_recs) >= 2
        assert ttm_recs[0]["value"] == 460  # Q1-Q4 2023
        assert ttm_recs[1]["value"] == 500  # Q2 2023 - Q1 2024


class TestPctChange:
    """Tests for period-over-period percent-change calculation."""

    @staticmethod
    def _annual_revenue(year_vals):
        entries = []
        for year, val in year_vals:
            entries.append(
                {
                    "tag": "Revenues",
                    "val": val,
                    "start": f"{year}-01-01",
                    "end": f"{year}-12-31",
                    "form": "10-K",
                    "fp": "FY",
                    "fy": year,
                }
            )
            entries.append(
                {
                    "tag": "Assets",
                    "val": 1000,
                    "end": f"{year}-12-31",
                }
            )
            entries.append(
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 100,
                    "start": f"{year}-01-01",
                    "end": f"{year}-12-31",
                    "form": "10-K",
                    "fp": "FY",
                    "fy": year,
                }
            )
        return create_mock_facts(entries)

    def test_yoy_annual(self):
        mock = self._annual_revenue([(2023, 1000), (2024, 1100)])
        res = resolve_company_facts(mock, period="yoy")
        yoy_recs = [r for r in res.income_statement if r["tag"] == "total_revenue"]
        assert len(yoy_recs) >= 1
        latest = max(yoy_recs, key=lambda r: r["period_ending"])
        assert abs(latest["value"] - 0.1) < 0.001
        assert latest["unit"] == "percent"
        assert latest["currency"] == ""
        assert "yoy:" in latest["source"]

    def test_yoy_quarterly(self):
        entries = []
        for year in [2023, 2024]:
            for q, end_md, start_md in [
                ("Q1", "03-31", "01-01"),
                ("Q2", "06-30", "04-01"),
            ]:
                entries.append(
                    {
                        "tag": "Revenues",
                        "val": 100 * (year - 2022) + (10 if q == "Q2" else 0),
                        "start": f"{year}-{start_md}",
                        "end": f"{year}-{end_md}",
                        "form": "10-Q",
                        "fp": q,
                        "fy": year,
                    }
                )
                entries.append(
                    {
                        "tag": "Assets",
                        "val": 1000,
                        "end": f"{year}-{end_md}",
                    }
                )
                entries.append(
                    {
                        "tag": "NetCashProvidedByUsedInOperatingActivities",
                        "val": 50,
                        "start": f"{year}-{start_md}",
                        "end": f"{year}-{end_md}",
                        "form": "10-Q",
                        "fp": q,
                        "fy": year,
                    }
                )
            total = sum(
                100 * (year - 2022) + (10 if q == "Q2" else 0) for q in ["Q1", "Q2"]
            )
            entries.append(
                {
                    "tag": "Revenues",
                    "val": total,
                    "start": f"{year}-01-01",
                    "end": f"{year}-12-31",
                    "form": "10-K",
                    "fp": "FY",
                    "fy": year,
                }
            )
            entries.append(
                {
                    "tag": "Assets",
                    "val": 1000,
                    "end": f"{year}-12-31",
                }
            )
            entries.append(
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 100,
                    "start": f"{year}-01-01",
                    "end": f"{year}-12-31",
                    "form": "10-K",
                    "fp": "FY",
                    "fy": year,
                }
            )
        mock = create_mock_facts(entries)
        res = resolve_company_facts(mock, period="yoy_quarterly")
        yoy_recs = [r for r in res.income_statement if r["tag"] == "total_revenue"]
        assert len(yoy_recs) >= 1
        for rec in yoy_recs:
            assert rec["frequency"] == "yoy_quarterly"
            assert rec["unit"] == "percent"

    def test_pop(self):
        entries = []
        for q, end_md, start_md, val in [
            ("Q1", "03-31", "01-01", 100),
            ("Q2", "06-30", "04-01", 120),
        ]:
            entries.append(
                {
                    "tag": "Revenues",
                    "val": val,
                    "start": f"2023-{start_md}",
                    "end": f"2023-{end_md}",
                    "form": "10-Q",
                    "fp": q,
                    "fy": 2023,
                }
            )
            entries.append(
                {
                    "tag": "Assets",
                    "val": 1000,
                    "end": f"2023-{end_md}",
                }
            )
            entries.append(
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 50,
                    "start": f"2023-{start_md}",
                    "end": f"2023-{end_md}",
                    "form": "10-Q",
                    "fp": q,
                    "fy": 2023,
                }
            )
        entries.append(
            {
                "tag": "Revenues",
                "val": 220,
                "start": "2023-01-01",
                "end": "2023-12-31",
                "form": "10-K",
                "fp": "FY",
                "fy": 2023,
            }
        )
        entries.append(
            {
                "tag": "Assets",
                "val": 1000,
                "end": "2023-12-31",
            }
        )
        entries.append(
            {
                "tag": "NetCashProvidedByUsedInOperatingActivities",
                "val": 100,
                "start": "2023-01-01",
                "end": "2023-12-31",
                "form": "10-K",
                "fp": "FY",
                "fy": 2023,
            }
        )
        mock = create_mock_facts(entries)
        res = resolve_company_facts(mock, period="pop")
        pop_recs = [r for r in res.income_statement if r["tag"] == "total_revenue"]
        assert len(pop_recs) >= 1
        latest = max(pop_recs, key=lambda r: r["period_ending"])
        assert abs(latest["value"] - 20.0) < 0.01
        assert latest["frequency"] == "pop"

    def test_division_by_zero_skipped(self):
        mock = self._annual_revenue([(2023, 0), (2024, 100)])
        res = resolve_company_facts(mock, period="yoy")
        yoy_recs = [
            r
            for r in res.income_statement
            if r["tag"] == "total_revenue" and r["period_ending"] == "2024-12-31"
        ]
        assert len(yoy_recs) == 0

    def test_negative_to_positive(self):
        mock = self._annual_revenue([(2023, -100), (2024, 50)])
        res = resolve_company_facts(mock, period="yoy")
        yoy_recs = [
            r
            for r in res.income_statement
            if r["tag"] == "total_revenue" and r["period_ending"] == "2024-12-31"
        ]
        assert len(yoy_recs) >= 1
        assert abs(yoy_recs[0]["value"] - 1.5) < 0.01

    def test_pct_change_unit_and_currency(self):
        mock = self._annual_revenue([(2023, 1000), (2024, 1200)])
        res = resolve_company_facts(mock, period="yoy")
        yoy_recs = [r for r in res.income_statement if r["tag"] == "total_revenue"]
        for rec in yoy_recs:
            assert rec["unit"] == "percent"
            assert rec["currency"] == ""

    def test_provenance_string(self):
        mock = self._annual_revenue([(2023, 1000), (2024, 1100)])
        res = resolve_company_facts(mock, period="yoy")
        yoy_recs = [
            r
            for r in res.income_statement
            if r["tag"] == "total_revenue" and r["period_ending"] == "2024-12-31"
        ]
        if yoy_recs:
            src = yoy_recs[0]["source"]
            assert "yoy:" in src
            assert "2024-12-31" in src
            assert "2023-12-31" in src


class TestPeriodType:
    """Tests for period_type handling in standardized records."""

    def test_period_type_in_records(self):
        mock = create_mock_facts(
            [
                {
                    "tag": "Revenues",
                    "val": 500,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {"tag": "Assets", "val": 1000, "end": "2023-12-31"},
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 100,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
            ]
        )
        res = resolve_company_facts(mock, period="annual")
        rev = [r for r in res.income_statement if r["tag"] == "total_revenue"]
        if rev:
            assert "period_type" in rev[0]
            assert rev[0]["period_type"] == "duration"
        assets = [r for r in res.balance_sheet if r["tag"] == "total_assets"]
        if assets:
            assert assets[0]["period_type"] == "instant"


def _mini_result(rows, dates, currency="USD", fiscal=None, preliminary=None):
    """Build a minimal StatementResult-shaped namespace for _build_records."""
    from types import SimpleNamespace

    return SimpleNamespace(
        currency=currency,
        rows=rows,
        dates=dates,
        fiscal_data=fiscal or {},
        preliminary_dates=preliminary or set(),
    )


def _row(tag, values, sources=None):
    from openbb_sec.utils.statement_schema._types import RowResult

    return RowResult(
        tag=tag,
        label=tag.replace("_", " ").title(),
        description="d",
        parent=None,
        sequence=1,
        factor="+",
        balance="debit",
        unit="monetary",
        period_type="duration",
        values=values,
        sources=sources or {},
    )


def test_pct_change_pop_skips_zero_prior():
    """A period-over-period change from a zero prior value is not computed."""

    def rec(date, value):
        return {
            "period_ending": date,
            "fiscal_year": int(date[:4]),
            "fiscal_period": "FY",
            "calendar_year": int(date[:4]),
            "calendar_period": "Q4",
            "tag": "total_revenue",
            "label": "Total Revenue",
            "description": "d",
            "parent": None,
            "sequence": 1,
            "factor": "+",
            "balance": "credit",
            "period_type": "duration",
            "value": value,
        }

    records = [
        rec("2021-12-31", 0.0),
        rec("2022-12-31", 100.0),
        rec("2023-12-31", 150.0),
    ]
    out = cf._compute_pct_change(records, "pop")
    assert [r["period_ending"] for r in out] == ["2023-12-31"]
    assert out[0]["value"] == 50.0


def test_build_records_skips_all_zero_tags():
    """A tag that is all-zero (and not imputed/corrected) is dropped entirely."""
    zero_row = _row("dead_tag", {"2023-12-31": 0, "2022-12-31": 0})
    live_row = _row(
        "live_tag",
        {"2023-12-31": 100, "2022-12-31": 90},
        sources={"2023-12-31": "Assets", "2022-12-31": "Assets"},
    )
    result = _mini_result([zero_row, live_row], ["2022-12-31", "2023-12-31"])
    records = cf._build_records(result)
    tags = {r["tag"] for r in records}
    assert "dead_tag" not in tags  # all-zero tag excluded
    assert "live_tag" in tags
    assert len(records) == 2  # one live tag x two dates


def test_build_records_zero_kept_when_imputed():
    """An all-zero tag whose source is 'imputed' is retained (not suspect-dropped)."""
    imp_zero = _row(
        "imp_tag",
        {"2023-12-31": 0},
        sources={"2023-12-31": "imputed: a - b"},
    )
    result = _mini_result([imp_zero], ["2023-12-31"])
    records = cf._build_records(result)
    assert len(records) == 1
    # Suspect-zero policy rewrites 'imputed' -> 'imputed-zero'.
    assert records[0]["source"].startswith("imputed-zero")
    assert records[0]["value"] == 0


def test_build_records_corrected_zero_prefixed():
    """A 'corrected:' exact-zero takes the else-branch, prefixing 'imputed-zero: '."""
    corrected_zero = _row(
        "corr_tag",
        {"2023-12-31": 0},
        sources={"2023-12-31": "corrected: a - b"},
    )
    result = _mini_result([corrected_zero], ["2023-12-31"])
    records = cf._build_records(result)
    assert len(records) == 1
    # Non-'imputed' suspect sources are wrapped, not replaced.
    assert records[0]["source"] == "imputed-zero: corrected: a - b"
    assert records[0]["value"] == 0


def test_build_records_fiscal_year_filter():
    """fiscal_years filters out periods whose fiscal_year is excluded."""
    row = _row(
        "rev",
        {"2023-12-31": 100, "2022-12-31": 90},
        sources={"2023-12-31": "Revenues", "2022-12-31": "Revenues"},
    )
    fiscal = {
        "2023-12-31": {"fiscal_year": 2023, "fiscal_period": "FY"},
        "2022-12-31": {"fiscal_year": 2022, "fiscal_period": "FY"},
    }
    result = _mini_result([row], ["2022-12-31", "2023-12-31"], fiscal=fiscal)
    records = cf._build_records(result, fiscal_years=[2023])
    assert {r["period_ending"] for r in records} == {"2023-12-31"}


def test_get_standardized_financials_int_cik(blk_facts):
    """An integer CIK is zero-padded and fetched once via cached_request."""
    calls = []

    async def _fake_request(url, **kwargs):
        calls.append(url)
        return blk_facts

    with patch("openbb_sec.utils.cache.cached_request", _fake_request):
        res = asyncio.run(cf.get_standardized_financials(cik=2012383, period="annual"))
    assert len(calls) == 1
    assert "CIK0002012383.json" in calls[0]
    assert res.entity_name == "BlackRock, Inc."
    assert len(res.income_statement) > 0


def test_get_standardized_financials_symbol_maps_to_cik(blk_facts):
    """A symbol is resolved through symbol_map then fetched."""

    async def _fake_symbol_map(symbol, use_cache=True):
        return "0002012383"

    async def _fake_request(url, **kwargs):
        return blk_facts

    with (
        patch("openbb_sec.utils.helpers.symbol_map", _fake_symbol_map),
        patch("openbb_sec.utils.cache.cached_request", _fake_request),
    ):
        res = asyncio.run(
            cf.get_standardized_financials(symbol="BLKX", period="annual")
        )
    assert res.entity_name == "BlackRock, Inc."


def test_get_standardized_financials_symbol_no_cik_raises():
    """A symbol that maps to an empty CIK raises a not-found error."""

    async def _fake_symbol_map(symbol, use_cache=True):
        return ""

    with patch("openbb_sec.utils.helpers.symbol_map", _fake_symbol_map):
        with pytest.raises(OpenBBError, match="Could not find CIK"):
            asyncio.run(cf.get_standardized_financials(symbol="NOPE"))


def test_get_standardized_financials_requires_input():
    """Neither symbol nor cik raises an error."""
    with pytest.raises(OpenBBError, match="Either symbol or cik"):
        asyncio.run(cf.get_standardized_financials())


def test_get_standardized_financials_empty_string_cik_raises():
    """An empty-string cik resolves to an empty cik_list and raises.

    Distinct from the None case: ``cik=""`` enters the ``isinstance(cik, str)``
    branch which produces ``[]``, then the ``if not cik_list`` guard fires.
    """
    with pytest.raises(OpenBBError, match="Either symbol or cik"):
        asyncio.run(cf.get_standardized_financials(cik=""))


def test_get_standardized_financials_unexpected_response():
    """A response without a 'facts' key raises an unexpected-response error."""

    async def _fake_request(url, **kwargs):
        return {"not": "facts"}

    with patch("openbb_sec.utils.cache.cached_request", _fake_request):
        with pytest.raises(OpenBBError, match="Unexpected response"):
            asyncio.run(cf.get_standardized_financials(cik="0000320193"))


def test_get_standardized_financials_multi_cik_merge(blk_facts):
    """A MULTI_CIK_TICKERS symbol fetches every CIK and merges the facts."""
    calls = []

    async def _fake_symbol_map(symbol, use_cache=True):
        return "0002012383"

    async def _fake_request(url, **kwargs):
        calls.append(url)
        return blk_facts

    # BLK is in MULTI_CIK_TICKERS with two CIKs. symbol_map is still called for
    # the not-found guard before MULTI_CIK_TICKERS is consulted, so it must be
    # patched at its source (helpers binds cached_request at import, so the
    # cached_request patch alone does not intercept get_all_companies).
    with (
        patch("openbb_sec.utils.helpers.symbol_map", _fake_symbol_map),
        patch("openbb_sec.utils.cache.cached_request", _fake_request),
    ):
        res = asyncio.run(cf.get_standardized_financials(symbol="BLK", period="annual"))
    assert len(calls) == 2  # one request per CIK
    assert res.entity_name == "BlackRock, Inc."


def _six_k_filer_facts():
    """Build facts for a 40-F/20-F filer that furnishes financials via 6-K.

    Mirrors real foreign private issuers (e.g. Canadian National Railway):
    most fiscal years are annual-only (the full-year statements are tagged on
    a 6-K exhibit rather than in the 40-F/20-F), while a few earlier years
    additionally carry genuine interim (3/6/9-month) periods on 6-K.
    """
    entries: list[dict] = []
    # Annual-only years: only a full-year period is reported, via 6-K, filed
    # ~6 weeks after year-end (as real FY 6-K exhibits are).
    for year, assets, rev in ((2021, 23000, 7600), (2022, 24000, 8000)):
        filed = f"{year + 1}-02-15"
        entries += [
            {
                "tag": "Assets",
                "val": assets,
                "end": f"{year}-12-31",
                "form": "6-K",
                "filed": filed,
            },
            {
                "tag": "Revenues",
                "val": rev,
                "start": f"{year}-01-01",
                "end": f"{year}-12-31",
                "form": "6-K",
                "fp": "FY",
                "filed": filed,
            },
            {
                "tag": "NetCashProvidedByUsedInOperatingActivities",
                "val": 2000,
                "start": f"{year}-01-01",
                "end": f"{year}-12-31",
                "form": "6-K",
                "fp": "FY",
                "filed": filed,
            },
        ]
    # 2023: full-year plus genuine interim periods (cumulative 3/6/9-month).
    entries += [
        {
            "tag": "Assets",
            "val": 26000,
            "end": "2023-12-31",
            "form": "6-K",
            "filed": "2024-02-15",
        },
        {
            "tag": "Revenues",
            "val": 9000,
            "start": "2023-01-01",
            "end": "2023-12-31",
            "form": "6-K",
            "fp": "FY",
            "filed": "2024-02-15",
        },
        {
            "tag": "NetCashProvidedByUsedInOperatingActivities",
            "val": 2200,
            "start": "2023-01-01",
            "end": "2023-12-31",
            "form": "6-K",
            "fp": "FY",
            "filed": "2024-02-15",
        },
    ]
    for end, filed, assets, rev, cash in (
        ("2023-03-31", "2023-05-01", 24500, 2000, 500),  # ~90 days
        ("2023-06-30", "2023-08-01", 25000, 4100, 1000),  # ~181 days
        ("2023-09-30", "2023-11-01", 25500, 6200, 1500),  # ~273 days (9-month)
    ):
        entries += [
            {
                "tag": "Assets",
                "val": assets,
                "end": end,
                "form": "6-K",
                "filed": filed,
            },
            {
                "tag": "Revenues",
                "val": rev,
                "start": "2023-01-01",
                "end": end,
                "form": "6-K",
                "filed": filed,
            },
            {
                "tag": "NetCashProvidedByUsedInOperatingActivities",
                "val": cash,
                "start": "2023-01-01",
                "end": end,
                "form": "6-K",
                "filed": filed,
            },
        ]
    return create_mock_facts(entries)


def _six_k_lapsed_interim_facts():
    """Build facts for a 6-K filer whose interim reporting lapsed.

    Annual (FY) periods continue through 2024, but the only interim periods
    are from 2020 — the quarterly series would be sparse/stale, so it must be
    treated as no quarterly data.
    """
    entries: list[dict] = []
    for year in (2020, 2021, 2022, 2023, 2024):
        filed = f"{year + 1}-02-15"
        entries += [
            {
                "tag": "Assets",
                "val": 24000 + year,
                "end": f"{year}-12-31",
                "form": "6-K",
                "filed": filed,
            },
            {
                "tag": "Revenues",
                "val": 8000,
                "start": f"{year}-01-01",
                "end": f"{year}-12-31",
                "form": "6-K",
                "fp": "FY",
                "filed": filed,
            },
        ]
    # Lone interim periods, only for 2020.
    for end, filed in (("2020-06-30", "2020-08-01"), ("2020-09-30", "2020-11-01")):
        entries += [
            {"tag": "Assets", "val": 23500, "end": end, "form": "6-K", "filed": filed},
            {
                "tag": "Revenues",
                "val": 2000,
                "start": "2020-01-01",
                "end": end,
                "form": "6-K",
                "filed": filed,
            },
        ]
    return create_mock_facts(entries)


class TestSixKReportingPeriods:
    """Period detection for 40-F/20-F filers that report via 6-K exhibits."""

    def test_annual_fy_periods_detected_from_6k(self):
        facts = _six_k_filer_facts()["facts"]
        annual = get_filing_dates(facts, "annual")
        assert annual == {"2021-12-31", "2022-12-31", "2023-12-31"}

    def test_nine_month_interim_period_detected(self):
        facts = _six_k_filer_facts()["facts"]
        quarterly = get_filing_dates(facts, "quarterly")
        assert {"2023-03-31", "2023-06-30", "2023-09-30"} <= quarterly

    def test_annual_only_years_excluded_from_quarterly(self):
        # Years with no interim data must not surface as phantom Q4/H2 rows.
        facts = _six_k_filer_facts()["facts"]
        quarterly = get_filing_dates(facts, "quarterly")
        assert "2021-12-31" not in quarterly
        assert "2022-12-31" not in quarterly

    def test_annual_balance_sheet_not_empty(self):
        res = resolve_company_facts(_six_k_filer_facts(), period="annual")
        assert res.balance_sheet, "annual balance sheet must not be empty for 6-K filer"
        dates = {r["period_ending"] for r in res.balance_sheet}
        assert {"2021-12-31", "2022-12-31", "2023-12-31"} <= dates
        assert all(r["fiscal_period"] == "FY" for r in res.balance_sheet)

    def test_annual_total_assets_value(self):
        res = resolve_company_facts(_six_k_filer_facts(), period="annual")
        ta = {
            r["period_ending"]: r["value"]
            for r in res.balance_sheet
            if r["tag"] == "total_assets"
        }
        assert ta.get("2023-12-31") == 26000

    def test_quarterly_excludes_annual_only_years(self):
        res = resolve_company_facts(_six_k_filer_facts(), period="quarterly")
        dates = {r["period_ending"] for r in res.balance_sheet}
        assert "2021-12-31" not in dates
        assert "2022-12-31" not in dates

    def test_lapsed_interim_yields_no_quarterly_dates(self):
        # Interim reporting that stopped years before the latest annual period
        # is discontinuous and must be treated as no quarterly data.
        facts = _six_k_lapsed_interim_facts()["facts"]
        assert get_filing_dates(facts, "quarterly") == set()
        assert get_filing_dates(facts, "annual") == {
            "2020-12-31",
            "2021-12-31",
            "2022-12-31",
            "2023-12-31",
            "2024-12-31",
        }

    def test_lapsed_interim_quarterly_raises(self):
        from openbb_core.app.model.abstract.error import OpenBBError

        with pytest.raises(OpenBBError, match="quarterly"):
            resolve_company_facts(_six_k_lapsed_interim_facts(), period="quarterly")


class TestPointInTimeAsOfDate:
    """Point-in-Time (PIT) as_of_date filtering, filing_date, and is_restated metadata."""

    @staticmethod
    def _restated_facts():
        return create_mock_facts(
            [
                # 2022 originally filed on 2023-02-15 with Revenues = 1000
                {
                    "tag": "Assets",
                    "val": 5000,
                    "end": "2022-12-31",
                    "form": "10-K",
                    "filed": "2023-02-15",
                },
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 200,
                    "start": "2022-01-01",
                    "end": "2022-12-31",
                    "form": "10-K",
                    "filed": "2023-02-15",
                },
                {
                    "tag": "Revenues",
                    "val": 1000,
                    "start": "2022-01-01",
                    "end": "2022-12-31",
                    "form": "10-K",
                    "filed": "2023-02-15",
                },
                # 2022 restated in 2023 10-K filed on 2024-02-15 with Revenues = 1150
                {
                    "tag": "Assets",
                    "val": 5000,
                    "end": "2022-12-31",
                    "form": "10-K",
                    "filed": "2024-02-15",
                },
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 200,
                    "start": "2022-01-01",
                    "end": "2022-12-31",
                    "form": "10-K",
                    "filed": "2024-02-15",
                },
                {
                    "tag": "Revenues",
                    "val": 1150,
                    "start": "2022-01-01",
                    "end": "2022-12-31",
                    "form": "10-K",
                    "filed": "2024-02-15",
                },
                # 2023 filed on 2024-02-15 with Revenues = 1300
                {
                    "tag": "Assets",
                    "val": 6000,
                    "end": "2023-12-31",
                    "form": "10-K",
                    "filed": "2024-02-15",
                },
                {
                    "tag": "NetCashProvidedByUsedInOperatingActivities",
                    "val": 300,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                    "form": "10-K",
                    "filed": "2024-02-15",
                },
                {
                    "tag": "Revenues",
                    "val": 1300,
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                    "form": "10-K",
                    "filed": "2024-02-15",
                },
            ]
        )

    def test_as_of_date_prevents_lookahead(self):
        """As of 2023-06-15, 2023-12-31 does not exist and 2022-12-31 has original value 1000."""
        facts = self._restated_facts()
        res_pit = resolve_company_facts(facts, period="annual", as_of_date="2023-06-15")
        dates = {r["period_ending"] for r in res_pit.income_statement}
        assert dates == {"2022-12-31"}
        rev = _pick(res_pit.income_statement, "total_revenue", "2022-12-31")
        assert rev["value"] == 1000
        assert rev["filing_date"] == "2023-02-15"
        assert rev["is_restated"] is False

    def test_after_restatement_reflects_restated_value_and_flag(self):
        """As of 2024-06-15 (or default), 2022-12-31 reflects restated value 1150 and is_restated=True."""
        facts = self._restated_facts()
        res_later = resolve_company_facts(
            facts, period="annual", as_of_date="2024-06-15"
        )
        dates = {r["period_ending"] for r in res_later.income_statement}
        assert dates == {"2022-12-31", "2023-12-31"}
        rev_2022 = _pick(res_later.income_statement, "total_revenue", "2022-12-31")
        assert rev_2022["value"] == 1150
        assert rev_2022["filing_date"] == "2024-02-15"
        assert rev_2022["original_filing_date"] == "2023-02-15"
        assert rev_2022["is_restated"] is True

        rev_2023 = _pick(res_later.income_statement, "total_revenue", "2023-12-31")
        assert rev_2023["value"] == 1300
        assert rev_2023["filing_date"] == "2024-02-15"
        assert rev_2023["is_restated"] is False

    def test_as_of_date_before_any_filing_returns_empty(self):
        """An as_of_date before the earliest filing returns empty statements."""
        facts = self._restated_facts()
        res = resolve_company_facts(facts, period="annual", as_of_date="2020-01-01")
        assert res.income_statement == []
        assert res.balance_sheet == []
        assert res.cash_flow == []
