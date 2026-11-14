"""Unit tests for the statement_schema engine.

These tests drive the pure functions in
``openbb_sec.utils.statement_schema`` directly with small synthetic
inputs to exercise statement-type detection, schema lookups, and
row-level extraction.  A real BlackRock company-facts fixture is also
pushed end-to-end (annual, quarterly, and growth periods) to cover the
combinatorial extraction/imputation branches that only realistic data
reaches.  The imputation engine's own unit tests live in
``test_imputation.py``.

Tests only — no source under ``openbb_sec/`` is modified.
"""

# flake8: noqa: D101,D102,D103,D403

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from openbb_sec.utils.company_facts import resolve_company_facts
from openbb_sec.utils.statement_schema import StatementSchema
from openbb_sec.utils.statement_schema._detection import (
    _collapse_near_dates,
    _fiscal_position,
    _has_recent_data,
    _latest_annual_shares,
    annual_fiscal_years,
    detect_reporting_currency,
    detect_type,
    get_filing_dates,
    get_fiscal_meta,
    preliminary_view,
    prior_period_end,
)
from openbb_sec.utils.statement_schema._extraction import (
    _get_annual_values,
    _get_unit_data,
    _get_ytd9_values,
    compute_ref_filings,
    extract_row_values,
    rescaled_facts,
)
from openbb_sec.utils.statement_schema._types import (
    SUPERSEDED_SUFFIX,
    RowDef,
    RowResult,
    ScaledFacts,
    _tolerance,
)

_FIXTURE_DIR = Path(__file__).parent / "record"
_M = 1_000_000  # magnitudes must exceed the 1M tolerance cap to register


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _entry(
    end, start=None, *, form="10-K", filed=None, fy=None, fp="FY", val=1.0, accn=None
):
    """Build a single XBRL fact entry dict; filed defaults to 45 days after end."""
    if filed is None:
        try:
            filed = (datetime.strptime(end, "%Y-%m-%d") + timedelta(days=45)).strftime(
                "%Y-%m-%d"
            )
        except ValueError:
            filed = "2024-02-15"
    e = {"end": end, "val": val, "form": form, "filed": filed, "fp": fp}
    if accn is not None:
        e["accn"] = accn
    if start is not None:
        e["start"] = start
    if fy is not None:
        e["fy"] = fy
    elif end[:4].isdigit():
        e["fy"] = int(end[:4])
    else:
        e["fy"] = 0
    return e


_SHARES = "WeightedAverageNumberOfSharesOutstandingBasic"


def _cover(*counts):
    """Build dei cover-page share counts from (accession, filed, count) tuples."""
    return (
        "dei",
        "EntityCommonStockSharesOutstanding",
        "shares",
        [_entry(filed, filed=filed, val=val, accn=accn) for accn, filed, val in counts],
    )


def _facts(tags):
    """Build a facts dict: {ns: {tag: {units: {unit: [entries]}}}}.

    ``tags`` is an iterable of (ns, tag, unit, [entries]) tuples.
    """
    out: dict = {}
    for ns, tag, unit, entries in tags:
        out.setdefault(ns, {}).setdefault(tag, {"units": {}})
        out[ns][tag]["units"].setdefault(unit, []).extend(entries)
    return out


def _rd(
    tag,
    *,
    xbrl=(),
    unit="monetary",
    period_type="duration",
    parent=None,
    factor="+",
    balance="",
    sequence=1,
    label=None,
):
    """Build a RowDef with a tuple of {tag, namespace} xbrl entries."""
    return RowDef(
        tag=tag,
        label=label or tag.replace("_", " ").title(),
        description="",
        parent=parent,
        sequence=sequence,
        factor=factor,
        balance=balance,
        unit=unit,
        period_type=period_type,
        xbrl_tags=tuple({"tag": t, "namespace": ns} for t, ns in xbrl),
    )


# ---------------------------------------------------------------------------
# _types._tolerance
# ---------------------------------------------------------------------------


class TestTolerance:
    def test_floor(self):
        # Small magnitudes floor at 100k.
        assert _tolerance(1.0, 2.0) == 100_000

    def test_cap(self):
        # 0.1% of 10B = 10M, capped at 1M.
        assert _tolerance(10_000_000_000.0) == 1_000_000

    def test_scaled_between(self):
        # 0.1% of 500M = 500k, between floor and cap.
        assert _tolerance(500_000_000.0) == 500_000

    def test_ignores_none(self):
        assert _tolerance(None, None) == 100_000


# ---------------------------------------------------------------------------
# _detection
# ---------------------------------------------------------------------------


_DETECT_KW: dict[str, Any] = dict(
    insurance_is_signals=["PremiumsEarnedNet", "BenefitsLossesAndExpenses"],
    insurance_bs_signals=["LiabilityForFuturePolicyBenefits", "UnearnedPremiums"],
    financial_signals=["InterestIncomeExpenseNet", "NoninterestIncome"],
    min_financial_signals=2,
    industrial_signals=["CostOfGoodsAndServicesSold", "CostOfRevenue"],
    diversified_signals=["CostsAndExpenses", "OperatingIncomeLoss"],
)


class TestDetectType:
    def test_insurance_wins_when_total_exceeds_financial(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "PremiumsEarnedNet",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01")],
                ),
                (
                    "us-gaap",
                    "LiabilityForFuturePolicyBenefits",
                    "USD",
                    [_entry("2023-12-31")],
                ),
                ("us-gaap", "UnearnedPremiums", "USD", [_entry("2023-12-31")]),
                (
                    "us-gaap",
                    "InterestIncomeExpenseNet",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01")],
                ),
                (
                    "us-gaap",
                    "NoninterestIncome",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01")],
                ),
            ]
        )
        # ins_total = 3 (1 IS + 2 BS), fin_count = 2 -> insurance
        assert detect_type(facts, **_DETECT_KW) == "insurance"

    def test_financial_wins_when_count_exceeds_insurance_total(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "PremiumsEarnedNet",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01")],
                ),
                (
                    "us-gaap",
                    "LiabilityForFuturePolicyBenefits",
                    "USD",
                    [_entry("2023-12-31")],
                ),
                (
                    "us-gaap",
                    "InterestIncomeExpenseNet",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01")],
                ),
                (
                    "us-gaap",
                    "NoninterestIncome",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01")],
                ),
            ]
        )
        # ins_total = 2, fin_count = 2 -> not > so financial branch:
        # is_insurance and is_financial, ins_total(2) > fin_count(2) is False -> financial
        assert detect_type(facts, **_DETECT_KW) == "financial"

    def test_insurance_only(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "PremiumsEarnedNet",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01")],
                ),
                (
                    "us-gaap",
                    "LiabilityForFuturePolicyBenefits",
                    "USD",
                    [_entry("2023-12-31")],
                ),
            ]
        )
        assert detect_type(facts, **_DETECT_KW) == "insurance"

    def test_financial_only(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "InterestIncomeExpenseNet",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01")],
                ),
                (
                    "us-gaap",
                    "NoninterestIncome",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01")],
                ),
            ]
        )
        assert detect_type(facts, **_DETECT_KW) == "financial"

    def test_industrial_requires_recent_data(self):
        # COGS present and recent (within 5 years of an annual filing) -> industrial.
        facts = _facts(
            [
                (
                    "us-gaap",
                    "CostOfGoodsAndServicesSold",
                    "USD",
                    [_entry("2024-12-31", "2024-01-01", form="10-K")],
                ),
            ]
        )
        assert detect_type(facts, **_DETECT_KW) == "industrial"

    def test_stale_cogs_falls_through_to_diversified(self):
        # COGS only present in an ancient filing -> not "recent" -> diversified via CostsAndExpenses.
        facts = _facts(
            [
                (
                    "us-gaap",
                    "CostOfGoodsAndServicesSold",
                    "USD",
                    [_entry("2005-12-31", "2005-01-01", form="10-K")],
                ),
                (
                    "us-gaap",
                    "CostsAndExpenses",
                    "USD",
                    [_entry("2024-12-31", "2024-01-01")],
                ),
            ]
        )
        assert detect_type(facts, **_DETECT_KW) == "diversified"

    def test_default_industrial_when_no_signals(self):
        facts = _facts([("us-gaap", "SomeRandomTag", "USD", [_entry("2023-12-31")])])
        assert detect_type(facts, **_DETECT_KW) == "industrial"

    def test_non_dict_namespace_skipped(self):
        # detect_type iterates facts.values(); non-dict values are ignored.
        facts = {
            "weird": ["not", "a", "dict"],
            "us-gaap": {"CostsAndExpenses": {"units": {}}},
        }
        assert detect_type(facts, **_DETECT_KW) == "diversified"


class TestLatestAnnualShares:
    def test_null_revenue_value_skipped(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry("2023-12-31", "2023-01-01", val=None, accn="a1"),
                        _entry("2023-12-31", "2023-01-01", val=200.0, accn="a1"),
                    ],
                ),
                (
                    "us-gaap",
                    "PremiumsEarnedNet",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=50.0, accn="a1")],
                ),
            ]
        )
        revenue, shares = _latest_annual_shares(
            facts, ["Revenues"], {"insurance": ["PremiumsEarnedNet"]}
        )
        assert revenue == 200.0
        assert shares == {"insurance": 0.25}

    def test_zero_revenue_returns_no_shares(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=0.0, accn="a1")],
                )
            ]
        )
        assert _latest_annual_shares(
            facts, ["Revenues"], {"insurance": ["PremiumsEarnedNet"]}
        ) == (None, {"insurance": None})

    def test_non_dict_namespace_skipped_in_measure_lookup(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=100.0)],
                ),
                (
                    "us-gaap",
                    "InterestIncomeOperating",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=40.0)],
                ),
            ]
        )
        facts["weird"] = ["not", "a", "dict"]
        revenue, shares = _latest_annual_shares(
            facts, ["Revenues"], {"financial": ["InterestIncomeOperating"]}
        )
        assert revenue == 100.0
        assert shares == {"financial": 0.4}


class TestCollapseNearDates:
    def test_interim_near_fiscal_year_end_dropped(self):
        kept = _collapse_near_dates(
            {"2023-03-31", "2023-12-28"}, {"2023-12-31"}, Counter()
        )
        assert kept == {"2023-03-31"}

    def test_better_supported_interim_kept(self):
        weights = Counter({"2023-06-30": 1, "2023-07-02": 3})
        assert _collapse_near_dates({"2023-06-30", "2023-07-02"}, set(), weights) == {
            "2023-07-02"
        }

    def test_first_interim_kept_when_not_outweighed(self):
        weights = Counter({"2023-06-30": 3, "2023-07-02": 1})
        assert _collapse_near_dates({"2023-06-30", "2023-07-02"}, set(), weights) == {
            "2023-06-30"
        }


class TestMalformedDates:
    def test_filing_dates_skip_unparseable_end(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-02-30", "2022-03-01", filed="2023-05-01")],
                )
            ]
        )
        assert get_filing_dates(facts, "annual") == set()

    def test_annual_fiscal_years_skip_unparseable_end(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-02-30", "2022-03-01", filed="2023-05-01")],
                )
            ]
        )
        assert annual_fiscal_years(facts, set()) == {}


class TestFiscalPosition:
    _ENDS = ["2022-12-31", "2023-12-31"]
    _YEARS = {"2022-12-31": 2022, "2023-12-31": 2023}

    def test_date_before_grid_rolls_back(self):
        assert _fiscal_position("2020-06-30", self._ENDS, self._YEARS) == (2020, 2)

    def test_date_after_grid_rolls_forward(self):
        assert _fiscal_position("2025-06-30", self._ENDS, self._YEARS) == (2025, 2)


class TestPreliminaryView:
    def _facts(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry("2023-12-31", "2023-01-01", filed="2024-02-15"),
                        _entry(
                            "2023-12-31", "2023-01-01", form="8-K", filed="2024-01-25"
                        ),
                        _entry(
                            "2024-12-31", "2024-01-01", form="8-K", filed="2025-01-25"
                        ),
                    ],
                ),
                (
                    "us-gaap",
                    "Assets",
                    "USD",
                    [_entry("2023-12-31", filed="2024-02-15")],
                ),
                (
                    "dei",
                    "EntityCommonStockSharesOutstanding",
                    "shares",
                    [_entry("2024-01-31", form="10-K", filed="2024-02-15")],
                ),
            ]
        )
        facts["weird"] = ["not", "a", "dict"]
        return facts

    def test_reported_period_superseded_and_unreported_kept(self):
        facts = self._facts()
        view = preliminary_view(facts)
        forms = [e["form"] for e in view["us-gaap"]["Revenues"]["units"]["USD"]]
        assert forms == ["10-K", "8-K" + SUPERSEDED_SUFFIX, "8-K"]
        assert view["us-gaap"]["Assets"] is facts["us-gaap"]["Assets"]
        assert view["weird"] is facts["weird"]
        assert view["dei"] == facts["dei"]

    def test_pit_mode_keeps_entry_filed_before_regular_filing(self):
        view = preliminary_view(self._facts(), pit_mode=True)
        forms = [e["form"] for e in view["us-gaap"]["Revenues"]["units"]["USD"]]
        assert forms == ["10-K", "8-K", "8-K"]


class TestHasRecentData:
    def test_true_for_recent_annual(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "CostOfRevenue",
                    "USD",
                    [_entry("2024-12-31", "2024-01-01", form="10-K")],
                )
            ]
        )
        assert _has_recent_data(facts, "CostOfRevenue") is True

    def test_false_for_old(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "CostOfRevenue",
                    "USD",
                    [_entry("2005-12-31", "2005-01-01", form="10-K")],
                )
            ]
        )
        assert _has_recent_data(facts, "CostOfRevenue") is False

    def test_false_for_non_annual_form(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "CostOfRevenue",
                    "USD",
                    [_entry("2024-09-30", "2024-07-01", form="10-Q")],
                )
            ]
        )
        assert _has_recent_data(facts, "CostOfRevenue") is False

    def test_missing_tag(self):
        facts = _facts([("us-gaap", "Other", "USD", [_entry("2024-12-31")])])
        assert _has_recent_data(facts, "CostOfRevenue") is False


class TestGetFilingDates:
    def test_annual_basic(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Assets",
                    "USD",
                    [_entry(f"{y}-12-31") for y in (2022, 2023)],
                ),
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry(f"{y}-12-31", f"{y}-01-01") for y in (2022, 2023)],
                ),
            ]
        )
        assert get_filing_dates(facts, "annual") == {"2022-12-31", "2023-12-31"}

    def test_bad_dates_skipped(self):
        # start==end and unparseable dates are ignored, leaving no annual dates.
        facts = _facts(
            [
                ("us-gaap", "Revenues", "USD", [_entry("2023-12-31", "2023-12-31")]),
                ("us-gaap", "Other", "USD", [_entry("bad", "worse")]),
            ]
        )
        assert get_filing_dates(facts, "annual") == set()

    def test_quarterly_merges_annual_and_drops_orphan_quarter(self):
        # A quarter end with no instant Assets anchor and earlier than others gets dropped.
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Assets",
                    "USD",
                    [
                        _entry("2023-03-31", form="10-Q"),
                        _entry("2023-06-30", form="10-Q"),
                        _entry("2023-12-31", form="10-K"),
                    ],
                ),
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry("2023-03-31", "2023-01-01", form="10-Q"),
                        _entry("2023-06-30", "2023-04-01", form="10-Q"),
                        _entry("2023-12-31", "2023-01-01", form="10-K"),
                    ],
                ),
            ]
        )
        dates = get_filing_dates(facts, "quarterly")
        assert "2023-03-31" in dates
        assert "2023-12-31" in dates  # annual merged in

    def test_canonical_month_filter_keeps_offcycle_without_neighbor(self):
        # >3 annual dates, dominant 12-31, plus an isolated 06-30 far from any canonical.
        rev = [
            _entry(f"{y}-12-31", f"{y}-01-01") for y in (2020, 2021, 2022, 2023, 2024)
        ]
        assets = [_entry(f"{y}-12-31") for y in (2020, 2021, 2022, 2023, 2024)]
        rev.append(_entry("2016-06-30", "2015-07-01"))
        assets.append(_entry("2016-06-30"))
        facts = _facts(
            [
                ("us-gaap", "Assets", "USD", assets),
                ("us-gaap", "Revenues", "USD", rev),
            ]
        )
        dates = get_filing_dates(facts, "annual")
        assert "2016-06-30" in dates
        assert "2024-12-31" in dates

    def test_canonical_month_filter_drops_near_duplicate(self):
        # Two canonical dates within 10 days: the non-exact one is discarded.
        rev = [_entry(f"{y}-12-31", f"{y}-01-01") for y in (2021, 2022, 2023, 2024)]
        assets = [_entry(f"{y}-12-31") for y in (2021, 2022, 2023, 2024)]
        # Near-duplicate 52-week fiscal end a few days before a calendar 12-31.
        rev.append(_entry("2024-12-28", "2024-01-01"))
        assets.append(_entry("2024-12-28"))
        facts = _facts(
            [
                ("us-gaap", "Assets", "USD", assets),
                ("us-gaap", "Revenues", "USD", rev),
            ]
        )
        dates = get_filing_dates(facts, "annual")
        # The exact 12-31 wins over the 12-28 near-duplicate.
        assert "2024-12-31" in dates
        assert "2024-12-28" not in dates

    def test_include_preliminary_adds_8k(self):
        facts = _facts(
            [
                ("us-gaap", "Assets", "USD", [_entry("2024-12-31")]),
                ("us-gaap", "Revenues", "USD", [_entry("2024-12-31", "2024-01-01")]),
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2025-12-31", "2025-01-01", form="8-K")],
                ),
            ]
        )
        with_prelim = get_filing_dates(facts, "annual", include_preliminary=True)
        assert "2025-12-31" in with_prelim
        without = get_filing_dates(facts, "annual")
        assert "2025-12-31" not in without


class TestGetFiscalMeta:
    def test_annual_descending_year_correction(self):
        # Two annual dates where the earlier filing erroneously claims a >= fy;
        # get_fiscal_meta forces the earlier to be next_fy - 1.
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Assets",
                    "USD",
                    [_entry("2022-12-31"), _entry("2023-12-31")],
                ),
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry("2022-12-31", "2022-01-01", fy=2023, fp="FY"),
                        _entry("2023-12-31", "2023-01-01", fy=2023, fp="FY"),
                    ],
                ),
            ]
        )
        dates = get_filing_dates(facts, "annual")
        meta = get_fiscal_meta(facts, "annual", dates)
        assert meta["2023-12-31"]["fiscal_year"] == 2023
        assert meta["2022-12-31"]["fiscal_year"] == 2022  # corrected down

    def test_annual_fallback_year_from_date(self):
        # No fy/fp metadata at all -> falls back to int(date[:4]).
        facts = _facts(
            [
                ("us-gaap", "Assets", "USD", [_entry("2023-12-31", fy=None, fp="")]),
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", fp="")],
                ),
            ]
        )
        dates = {"2023-12-31"}
        meta = get_fiscal_meta(facts, "annual", dates)
        assert meta["2023-12-31"] == {"fiscal_year": 2023, "fiscal_period": "FY"}

    def test_quarterly_period_from_10q(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Assets",
                    "USD",
                    [
                        _entry("2023-09-30", form="10-Q", fy=2023, fp="Q3"),
                        _entry("2023-12-31", form="10-K", fy=2023, fp="FY"),
                    ],
                ),
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry(
                            "2023-09-30", "2023-07-01", form="10-Q", fy=2023, fp="Q3"
                        ),
                        _entry(
                            "2023-12-31", "2023-01-01", form="10-K", fy=2023, fp="FY"
                        ),
                    ],
                ),
            ]
        )
        dates = get_filing_dates(facts, "quarterly")
        meta = get_fiscal_meta(facts, "quarterly", dates)
        assert meta["2023-09-30"]["fiscal_period"] == "Q3"
        # Annual date present in quarterly extraction becomes Q4.
        assert meta["2023-12-31"]["fiscal_period"] == "Q4"


class TestDetectCurrency:
    def test_picks_most_common(self):
        facts = _facts(
            [
                ("us-gaap", "A", "EUR", [_entry("2023-12-31")]),
                ("us-gaap", "B", "EUR", [_entry("2023-12-31")]),
                ("us-gaap", "C", "USD", [_entry("2023-12-31")]),
            ]
        )
        assert detect_reporting_currency(facts) == "EUR"

    def test_skips_shares_and_ratios(self):
        facts = _facts(
            [
                ("us-gaap", "Shares", "shares", [_entry("2023-12-31")]),
                ("us-gaap", "Ratio", "pure", [_entry("2023-12-31")]),
                ("us-gaap", "PerShare", "USD/shares", [_entry("2023-12-31")]),
            ]
        )
        # Only currency-looking 3-letter upper keys count; none here -> USD default.
        assert detect_reporting_currency(facts) == "USD"

    def test_empty_defaults_usd(self):
        assert detect_reporting_currency({}) == "USD"


class TestPriorPeriodEnd:
    @pytest.mark.parametrize(
        "date,expected",
        [
            ("2023-03-31", "2022-12-31"),
            ("2023-06-30", "2023-03-31"),
            ("2023-09-30", "2023-06-30"),
            ("2023-12-31", "2023-09-30"),
            ("2023-01-31", "2022-10-31"),
            ("2023-04-30", "2023-01-31"),
        ],
    )
    def test_known_months(self, date, expected):
        assert prior_period_end(date) == expected

    def test_unmapped_month_returns_none(self):
        assert prior_period_end("2023-05-31") is None

    def test_bad_date_returns_none(self):
        assert prior_period_end("garbage") is None


# ---------------------------------------------------------------------------
# _extraction
# ---------------------------------------------------------------------------


class TestGetUnitData:
    def test_shares_key(self):
        td = {"units": {"shares": [{"val": 1}], "USD": [{"val": 2}]}}
        assert _get_unit_data(td, "shares") == [{"val": 1}]

    def test_per_share_exact(self):
        td = {"units": {"USD/shares": [{"val": 1.5}]}}
        assert _get_unit_data(td, "per_share", "USD") == [{"val": 1.5}]

    def test_per_share_prefix_fallback(self):
        td = {"units": {"USD/foo": [{"val": 9}]}}
        assert _get_unit_data(td, "per_share", "USD") == [{"val": 9}]

    def test_monetary_currency_match(self):
        td = {"units": {"EUR": [{"val": 3}]}}
        assert _get_unit_data(td, "monetary", "EUR") == [{"val": 3}]

    def test_falls_back_to_first_unit(self):
        td = {"units": {"GBP": [{"val": 7}]}}
        # Requesting USD monetary but only GBP present -> first unit returned.
        assert _get_unit_data(td, "monetary", "USD") == [{"val": 7}]

    def test_no_units_returns_none(self):
        assert _get_unit_data({"units": {}}, "monetary") is None


class TestGetAnnualValues:
    def test_instant_returns_empty(self):
        row = _rd("x", period_type="instant", xbrl=[("Assets", "us-gaap")])
        assert _get_annual_values({}, row) == {}

    def test_picks_earliest_filed(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry(
                            "2023-12-31", "2023-01-01", filed="2024-02-01", val=500.0
                        ),
                        _entry(
                            "2023-12-31", "2023-01-01", filed="2025-02-01", val=510.0
                        ),
                    ],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        res = _get_annual_values(facts, row)
        assert res["2023-12-31"][1] == 500.0  # earliest filing wins
        assert res["2023-12-31"][2] == "us-gaap:Revenues"

    def test_tag_chain_priority(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "RevA",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=100.0)],
                ),
                (
                    "us-gaap",
                    "RevB",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=200.0)],
                ),
            ]
        )
        row = _rd("total_revenue", xbrl=[("RevA", "us-gaap"), ("RevB", "us-gaap")])
        res = _get_annual_values(facts, row)
        assert res["2023-12-31"][1] == 100.0  # first tag in chain

    def test_duration_window_filter(self):
        # A 200-day duration is not annual (300-400) -> excluded.
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-07-01", "2022-12-01", val=9.0)],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        assert _get_annual_values(facts, row) == {}

    def test_reference_map_selects_mapped_filing(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry(
                            "2023-12-31", "2023-01-01", filed="2024-02-01", val=500.0
                        ),
                        _entry(
                            "2023-12-31", "2023-01-01", filed="2025-02-01", val=510.0
                        ),
                    ],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        res = _get_annual_values(facts, row, ref_filed_map={"2023-12-31": "2025-02-01"})
        assert res["2023-12-31"] == ("2023-01-01", 510.0, "us-gaap:Revenues")

    def test_reference_map_falls_back_to_latest_earlier_filing(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry(
                            "2023-12-31", "2023-01-01", filed="2024-02-01", val=500.0
                        ),
                        _entry(
                            "2023-12-31", "2023-01-01", filed="2024-05-01", val=505.0
                        ),
                    ],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        res = _get_annual_values(facts, row, ref_filed_map={"2023-12-31": "2025-02-01"})
        assert res["2023-12-31"] == (
            "2023-01-01",
            505.0,
            "us-gaap:Revenues(fallback)",
        )

    def test_reference_map_falls_back_to_earliest_later_filing(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry(
                            "2023-12-31", "2023-01-01", filed="2025-02-01", val=510.0
                        ),
                        _entry(
                            "2023-12-31", "2023-01-01", filed="2025-05-01", val=515.0
                        ),
                    ],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        res = _get_annual_values(facts, row, ref_filed_map={"2023-12-31": "2024-02-01"})
        assert res["2023-12-31"][1:] == (510.0, "us-gaap:Revenues(fallback)")

    def test_reference_map_skips_unmapped_period(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=500.0)],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        assert _get_annual_values(facts, row, ref_filed_map={}) == {}


class TestGetYtd9Values:
    def test_instant_empty(self):
        row = _rd("x", period_type="instant", xbrl=[("A", "us-gaap")])
        assert _get_ytd9_values({}, row) == {}

    def test_q4_from_fy_minus_ytd9(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry(
                            "2023-12-31", "2023-01-01", filed="2024-02-01", val=1000.0
                        ),
                        _entry(
                            "2023-09-30", "2023-01-01", filed="2024-02-01", val=700.0
                        ),
                    ],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        res = _get_ytd9_values(facts, row)
        assert res["2023-12-31"] == 300.0  # 1000 - 700

    def test_missing_ytd_returns_empty(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=1000.0)],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        assert _get_ytd9_values(facts, row) == {}


class TestExtractRowValues:
    def test_annual_simple(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=500.0)],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        vals, srcs = extract_row_values(facts, row, "annual", "USD")
        assert vals["2023-12-31"] == 500.0
        assert srcs["2023-12-31"] == "us-gaap:Revenues"

    def test_instant_balance_sheet(self):
        facts = _facts(
            [("us-gaap", "Assets", "USD", [_entry("2023-12-31", val=999.0)])]
        )
        row = _rd("total_assets", period_type="instant", xbrl=[("Assets", "us-gaap")])
        vals, _ = extract_row_values(facts, row, "annual", "USD")
        assert vals["2023-12-31"] == 999.0

    def test_cross_target_identity_lock(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "ProfitLoss",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=42.0)],
                )
            ]
        )
        row = _rd("net_income", xbrl=[("ProfitLoss", "us-gaap")])
        vals, srcs = extract_row_values(
            facts,
            row,
            "annual",
            "USD",
            cross_targets={"2023-12-31": 42.0},
            statement="cash_flow",
        )
        assert vals["2023-12-31"] == 42.0
        assert "identity_lock:cash_flow" in srcs["2023-12-31"]

    def test_identity_locked_quarter_keeps_its_concept_for_ytd(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "A",
                    "USD",
                    [
                        _entry("2023-03-31", "2023-01-01", form="10-Q", val=100.0),
                        _entry("2023-06-30", "2023-01-01", form="10-Q", val=200.0),
                    ],
                ),
                (
                    "us-gaap",
                    "B",
                    "USD",
                    [
                        _entry("2023-03-31", "2023-01-01", form="10-Q", val=205.0),
                        _entry("2023-06-30", "2023-04-01", form="10-Q", val=207.0),
                    ],
                ),
            ]
        )
        row = _rd(
            "depreciation_and_amortization",
            xbrl=[("A", "us-gaap"), ("B", "us-gaap")],
        )
        vals, srcs = extract_row_values(
            facts,
            row,
            "quarterly",
            "USD",
            cross_targets={"2023-03-31": 100.0},
            statement="cash_flow",
        )
        assert vals["2023-06-30"] == 100.0
        assert srcs["2023-06-30"] == "ytd_derived(us-gaap:A)"

    def test_share_count_scale_restated_before_extraction(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    _SHARES,
                    "shares",
                    [
                        _entry(
                            "2017-12-31",
                            "2017-01-01",
                            filed="2019-02-21",
                            val=351.9,
                            accn="x",
                        ),
                    ],
                ),
                _cover(("x", "2019-02-21", 350_000_000), ("y", "2018-05-01", 352 * _M)),
            ]
        )
        row = _rd(
            "weighted_ave_basic_shares_os", unit="shares", xbrl=[(_SHARES, "us-gaap")]
        )
        vals, srcs = extract_row_values(
            rescaled_facts(facts),
            row,
            "annual",
            "USD",
            ref_filed_map={"2017-12-31": "2019-02-21"},
        )
        assert vals["2017-12-31"] == 351_900_000
        assert isinstance(vals["2017-12-31"], int)
        assert srcs["2017-12-31"] == f"us-gaap:{_SHARES}"

    def test_ref_filed_fallback_when_exact_missing(self):
        # ref_filed_map points to a date not in the filings -> fallback path.
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", filed="2024-02-01", val=500.0)],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        vals, srcs = extract_row_values(
            facts, row, "annual", "USD", ref_filed_map={"2023-12-31": "2099-01-01"}
        )
        assert vals["2023-12-31"] == 500.0
        assert "(fallback)" in srcs["2023-12-31"]

    def test_quarterly_q4_derivation_from_fy_minus_quarters(self):
        # Three 10-Q quarters + FY -> Q4 = FY - sum(Q1..Q3).
        entries = [
            _entry("2023-03-31", "2023-01-01", form="10-Q", val=100.0),
            _entry("2023-06-30", "2023-04-01", form="10-Q", val=150.0),
            _entry("2023-09-30", "2023-07-01", form="10-Q", val=200.0),
            _entry("2023-12-31", "2023-01-01", form="10-K", val=600.0),
        ]
        facts = _facts([("us-gaap", "Revenues", "USD", entries)])
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        vals, srcs = extract_row_values(facts, row, "quarterly", "USD")
        assert vals["2023-12-31"] == 150.0  # 600 - (100+150+200)
        assert "Q4:" in srcs["2023-12-31"]

    def test_quarterly_q4_uses_annual_reference_map(self):
        entries = [
            _entry("2023-03-31", "2023-01-01", form="10-Q", val=100.0),
            _entry("2023-06-30", "2023-04-01", form="10-Q", val=150.0),
            _entry("2023-09-30", "2023-07-01", form="10-Q", val=200.0),
            _entry("2023-12-31", "2023-01-01", filed="2024-02-15", val=600.0),
            _entry("2023-12-31", "2023-01-01", filed="2025-02-15", val=660.0),
        ]
        facts = _facts([("us-gaap", "Revenues", "USD", entries)])
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        vals, srcs = extract_row_values(
            facts,
            row,
            "quarterly",
            "USD",
            annual_ref_map={"2023-12-31": "2025-02-15"},
        )
        assert vals["2023-12-31"] == 210.0  # 660 - (100+150+200)
        assert srcs["2023-12-31"].startswith("Q4: FY[us-gaap:Revenues]")

    def test_quarterly_h2_derivation_single_interim(self):
        # Semi-annual reporter: FY + one H1 interim -> H2 = FY - H1.
        entries = [
            _entry("2023-06-30", "2023-01-01", form="6-K", val=400.0),
            _entry("2023-12-31", "2023-01-01", form="10-K", val=900.0),
        ]
        facts = _facts([("us-gaap", "Revenues", "USD", entries)])
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        vals, srcs = extract_row_values(facts, row, "quarterly", "USD")
        assert vals["2023-12-31"] == 500.0  # 900 - 400
        assert "H2:" in srcs["2023-12-31"]

    def test_shares_unit_has_no_q4_derivation(self):
        entries = [_entry("2023-12-31", "2023-01-01", form="10-K", val=1_000.0)]
        facts = _facts([("us-gaap", "WAS", "shares", entries)])
        row = _rd(
            "weighted_average_shares_outstanding",
            unit="shares",
            xbrl=[("WAS", "us-gaap")],
        )
        vals, srcs = extract_row_values(facts, row, "quarterly", "USD")
        assert "2023-12-31" not in vals
        assert "2023-12-31" not in srcs

    def test_missing_tag_returns_empty(self):
        row = _rd("total_revenue", xbrl=[("Nope", "us-gaap")])
        vals, srcs = extract_row_values({}, row, "annual", "USD")
        assert vals == {} and srcs == {}

    def test_quarterly_ignores_annual_form_interim_monetary_facts(self):
        entries = [
            _entry("2023-03-31", "2023-01-01", form="10-K", val=100.0),
            _entry("2023-12-31", "2023-01-01", form="10-K", val=600.0),
        ]
        facts = _facts([("us-gaap", "Revenues", "USD", entries)])
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        vals, _ = extract_row_values(facts, row, "quarterly", "USD")
        assert "2023-03-31" not in vals

    def test_quarterly_keeps_annual_form_interim_share_facts(self):
        entries = [_entry("2023-12-31", "2023-10-01", form="10-K", val=7.0)]
        facts = _facts([("us-gaap", "WAS", "shares", entries)])
        row = _rd("shares", unit="shares", xbrl=[("WAS", "us-gaap")])
        vals, _ = extract_row_values(facts, row, "quarterly", "USD")
        assert vals["2023-12-31"] == 7.0

    def test_quarterly_q4_from_quarters_concept(self):
        quarters = [
            _entry("2023-03-31", "2023-01-01", form="10-Q", val=200.0),
            _entry("2023-06-30", "2023-04-01", form="10-Q", val=250.0),
            _entry("2023-09-30", "2023-07-01", form="10-Q", val=300.0),
            _entry("2023-12-31", "2023-01-01", form="10-K", val=1000.0),
        ]
        subset = [_entry("2023-12-31", "2023-01-01", form="10-K", val=700.0)]
        facts = _facts(
            [
                ("us-gaap", "Revenues", "USD", quarters),
                (
                    "us-gaap",
                    "RevenueFromContractWithCustomerExcludingAssessedTax",
                    "USD",
                    subset,
                ),
            ]
        )
        row = _rd(
            "operating_revenue",
            xbrl=[
                ("RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap"),
                ("Revenues", "us-gaap"),
            ],
        )
        vals, srcs = extract_row_values(facts, row, "quarterly", "USD")
        assert vals["2023-12-31"] == 250.0
        assert srcs["2023-12-31"].startswith("Q4: FY[us-gaap:Revenues]")

    def test_quarterly_q4_from_annual_concept_without_quarters_concept(self):
        entries = [
            _entry("2023-03-31", "2023-01-01", form="10-Q", val=200.0),
            _entry("2023-06-30", "2023-04-01", form="10-Q", val=250.0),
            _entry("2023-09-30", "2023-07-01", form="10-Q", val=300.0),
        ]
        subset = [_entry("2023-12-31", "2023-01-01", form="10-K", val=700.0)]
        facts = _facts(
            [
                ("us-gaap", "Revenues", "USD", entries),
                (
                    "us-gaap",
                    "RevenueFromContractWithCustomerExcludingAssessedTax",
                    "USD",
                    subset,
                ),
            ]
        )
        row = _rd(
            "operating_revenue",
            xbrl=[
                ("RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap"),
                ("Revenues", "us-gaap"),
            ],
        )
        vals, srcs = extract_row_values(facts, row, "quarterly", "USD")
        assert vals["2023-12-31"] == -50.0
        assert srcs["2023-12-31"].startswith(
            "Q4: FY[us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax]"
        )

    def test_instant_row_skips_duration_facts(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Assets",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=5.0)],
                )
            ]
        )
        row = _rd("total_assets", period_type="instant", xbrl=[("Assets", "us-gaap")])
        assert extract_row_values(facts, row, "annual", "USD") == ({}, {})

    def test_negative_net_position_skipped_in_asset_row(self):
        net = "DeferredTaxAssetsLiabilitiesNetNoncurrent"
        facts = _facts(
            [
                (
                    "us-gaap",
                    net,
                    "USD",
                    [_entry("2022-12-31", val=40.0), _entry("2023-12-31", val=-50.0)],
                )
            ]
        )
        row = _rd(
            "noncurrent_deferred_tax_assets",
            period_type="instant",
            balance="debit",
            xbrl=[(net, "us-gaap")],
        )
        vals, _ = extract_row_values(facts, row, "annual", "USD")
        assert vals == {"2022-12-31": 40.0}


class TestRescaledFacts:
    def test_filing_scaled_in_full(self):
        entries = [
            _entry(f"{y}-12-31", f"{y}-01-01", filed=filed, val=val, accn=accn)
            for y in range(2001, 2011)
            for accn, filed, val in (
                ("bad", "2012-02-01", y),
                ("b", "2012-03-01", y * _M),
                ("c", "2013-03-01", y * _M),
            )
        ]
        entries.append(
            _entry("2011-12-31", "2011-01-01", filed="2012-02-01", val=2.5, accn="bad")
        )
        facts = _facts([("us-gaap", "Revenues", "USD", entries)])
        out = rescaled_facts(facts)["us-gaap"]["Revenues"]["units"]["USD"]
        vals = {(e["end"], e["accn"]): e["val"] for e in out}
        assert vals[("2001-12-31", "bad")] == 2001 * _M
        assert vals[("2011-12-31", "bad")] == 2_500_000
        assert isinstance(vals[("2011-12-31", "bad")], int)
        assert vals[("2001-12-31", "b")] == 2001 * _M
        assert facts["us-gaap"]["Revenues"]["units"]["USD"][0]["val"] == 2001

    @pytest.mark.parametrize(
        ("val", "covers", "expected"),
        [
            (
                351.9,
                (("x", "2019-02-21", 350 * _M), ("y", "2018-05-01", 352 * _M)),
                351_900_000,
            ),
            (
                116_238_493,
                (("x", "2019-02-21", 116_238), ("y", "2018-05-01", 116_000)),
                116_238.493,
            ),
            (
                351.9,
                (("x", "2019-02-21", 350_000 * _M), ("y", "2018-05-01", 352 * _M)),
                351.9,
            ),
            (351.9, (("x", "2019-02-21", 350 * _M),), 351.9),
        ],
    )
    def test_share_count_restated_to_cover_page(self, val, covers, expected):
        facts = _facts(
            [
                (
                    "us-gaap",
                    _SHARES,
                    "shares",
                    [
                        _entry(
                            "2017-12-31",
                            "2017-01-01",
                            filed="2019-02-21",
                            val=val,
                            accn="x",
                        )
                    ],
                ),
                _cover(*covers),
            ]
        )
        value = rescaled_facts(facts)["us-gaap"][_SHARES]["units"]["shares"][0]["val"]
        assert value == expected
        assert type(value) is type(expected)

    def test_disputed_value_takes_concept_scale(self):
        entries = [
            _entry("2020-12-31", "2020-01-01", filed="2021-02-23", val=-26.3, accn="a"),
            _entry(
                "2020-12-31", "2020-01-01", filed="2023-02-24", val=26_300_000, accn="b"
            ),
            _entry(
                "2023-12-31", "2023-01-01", filed="2024-02-22", val=71_700_000, accn="c"
            ),
            _entry(
                "2020-06-30",
                "2020-04-01",
                form="10-Q",
                filed="2020-08-10",
                val=11_900_000,
                accn="d",
            ),
        ]
        facts = _facts([("us-gaap", "AssetImpairmentCharges", "USD", entries)])
        out = rescaled_facts(facts)["us-gaap"]["AssetImpairmentCharges"]["units"]["USD"]
        assert [e["val"] for e in out] == [
            -26_300_000,
            26_300_000,
            71_700_000,
            11_900_000,
        ]

    def test_disputed_value_consistent_with_own_filing_kept(self):
        def quarter(year, filed, val, accn):
            return _entry(
                f"{year}-10-31",
                f"{year}-08-01",
                form="10-Q",
                filed=filed,
                val=val,
                accn=accn,
            )

        entries = [
            quarter(2023, "2023-12-07", 241_490_000, "a"),
            quarter(2022, "2023-12-07", 228_544_000, "a"),
            quarter(2023, "2024-12-05", 241_490, "b"),
            *(quarter(y, f"{y}-12-05", 266_556, f"n{y}") for y in (2024, 2025, 2026)),
        ]
        facts = _facts([("us-gaap", "Revenues", "USD", entries)])
        out = rescaled_facts(facts)["us-gaap"]["Revenues"]["units"]["USD"]
        assert [e["val"] for e in out[:3]] == [241_490_000, 228_544_000, 241_490]

    @pytest.mark.parametrize(
        ("entries", "expected"),
        [
            (
                [
                    _entry("2020-12-31", "2020-01-01", filed="2021-02-01", val=5),
                    _entry("2020-12-31", "2020-01-01", filed="2022-02-01", val=5 * _M),
                    _entry("2019-12-31", "2019-01-01", filed="2020-02-01", val=150_000),
                ],
                [5, 5 * _M, 150_000],
            ),
            (
                [
                    _entry("2019-12-31", "2019-10-01", filed="2020-01-31", val=395),
                    _entry(
                        "2019-12-31", "2019-10-01", filed="2021-02-01", val=395 * _M
                    ),
                    _entry("2018-12-31", "2018-10-01", form="8-K", val=100),
                ],
                [395, 395 * _M, 100],
            ),
        ],
    )
    def test_dispute_without_fitting_scale_unchanged(self, entries, expected):
        facts = _facts([("us-gaap", "Revenues", "USD", entries)])
        out = rescaled_facts(facts)
        assert isinstance(out, ScaledFacts)
        assert out["us-gaap"] is facts["us-gaap"]
        assert [e["val"] for e in out["us-gaap"]["Revenues"]["units"]["USD"]] == (
            expected
        )

    def test_schema_restates_facts_once(self):
        facts = _facts(
            [("us-gaap", "Revenues", "USD", [_entry("2023-12-31", "2023-01-01")])]
        )
        scaled = StatementSchema._preliminary_facts(facts, False, False)
        assert isinstance(scaled, ScaledFacts)
        assert StatementSchema._preliminary_facts(scaled, False, False) is scaled


class TestComputeRefFilings:
    def test_quarterly_ignores_annual_form_interim_monetary_facts(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry(
                            "2023-03-31", "2023-01-01", form="10-Q", filed="2023-05-01"
                        ),
                        _entry(
                            "2023-03-31", "2023-01-01", form="10-K", filed="2024-02-01"
                        ),
                    ],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        ref = compute_ref_filings(facts, [row], "quarterly", "USD")
        assert ref == {"2023-03-31": "2023-05-01"}

    def test_instant_row_ignores_duration_facts(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Assets",
                    "USD",
                    [
                        _entry("2023-12-31", filed="2024-02-01"),
                        _entry("2023-12-31", "2023-01-01", filed="2024-06-01"),
                    ],
                )
            ]
        )
        row = _rd("total_assets", period_type="instant", xbrl=[("Assets", "us-gaap")])
        ref = compute_ref_filings(facts, [row], "annual", "USD")
        assert ref == {"2023-12-31": "2024-02-01"}

    def test_prefers_latest_filed_normal_mode(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry("2023-12-31", "2023-01-01", filed="2024-02-01", val=1.0),
                        _entry("2023-12-31", "2023-01-01", filed="2024-05-01", val=1.0),
                    ],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        ref = compute_ref_filings(facts, [row], "annual", "USD")
        assert ref["2023-12-31"] == "2024-05-01"  # latest

    def test_pit_mode_prefers_earliest(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry("2023-12-31", "2023-01-01", filed="2024-02-01", val=1.0),
                        _entry("2023-12-31", "2023-01-01", filed="2024-05-01", val=1.0),
                    ],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        ref = compute_ref_filings(facts, [row], "annual", "USD", pit_mode=True)
        assert ref["2023-12-31"] == "2024-02-01"  # earliest

    def test_stale_filing_gap_excluded(self):
        # filed > 450 days after period end is dropped in non-pit mode.
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", filed="2026-01-01", val=1.0)],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        assert compute_ref_filings(facts, [row], "annual", "USD") == {}


# ---------------------------------------------------------------------------
# End-to-end on the real BlackRock fixture (annual, quarterly, growth).
# These exercise the combinatorial extraction/imputation branches that
# only realistic XBRL data reaches.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def blk_facts():
    with open(_FIXTURE_DIR / "CIK0002012383.json") as f:
        return json.load(f)


class TestBLKEndToEnd:
    def test_annual_pipeline(self, blk_facts):
        res = resolve_company_facts(blk_facts, period="annual")
        assert res.company_type == "diversified"
        assert res.currency == "USD"
        assert len(res.diagnostics) == 0
        # Core identity holds on the latest year.
        ta = next(
            r["value"]
            for r in res.balance_sheet
            if r["tag"] == "total_assets" and r["period_ending"] == "2025-12-31"
        )
        tle = next(
            r["value"]
            for r in res.balance_sheet
            if r["tag"] == "total_liabilities_and_equity"
            and r["period_ending"] == "2025-12-31"
        )
        assert ta == tle

    def test_quarterly_pipeline_runs_and_aligns(self, blk_facts):
        res = resolve_company_facts(blk_facts, period="quarterly")
        # Quarterly extraction exercises YTD/Q4 derivation at the shared reference vintage.
        assert res.income_statement
        # All three statements share the same set of period-ending dates.
        is_dates = {r["period_ending"] for r in res.income_statement}
        bs_dates = {r["period_ending"] for r in res.balance_sheet}
        cf_dates = {r["period_ending"] for r in res.cash_flow}
        assert is_dates == bs_dates == cf_dates

    def test_pit_mode_quarterly(self, blk_facts):
        # pit_mode resolves every period at its earliest filing.
        res = resolve_company_facts(blk_facts, period="quarterly", pit_mode=True)
        assert res.income_statement

    def test_quarterly_skip_imputation_has_no_diagnostics(self, blk_facts):
        results = StatementSchema().extract_all(
            blk_facts, frequency="quarterly", skip_imputation=True
        )
        assert all(not r.diagnostics for r in results.values())

    def test_both_periods(self, blk_facts):
        res = resolve_company_facts(blk_facts, period="both")
        freqs = {r["frequency"] for r in res.income_statement}
        assert "annual" in freqs and "quarterly" in freqs

    def test_yoy_growth(self, blk_facts):
        res = resolve_company_facts(blk_facts, period="yoy")
        assert res.income_statement
        assert all(r["unit"] == "percent" for r in res.income_statement)

    def test_ttm(self, blk_facts):
        res = resolve_company_facts(blk_facts, period="ttm")
        assert all(r["fiscal_period"] == "TTM" for r in res.income_statement)

    def test_fiscal_year_filter(self, blk_facts):
        res = resolve_company_facts(blk_facts, period="annual", fiscal_years=[2025])
        years = {r["fiscal_year"] for r in res.income_statement}
        assert years == {2025}


class TestSchemaObject:
    """Direct StatementSchema accessor coverage."""

    @pytest.fixture(scope="class")
    @staticmethod
    def schema():
        return StatementSchema()

    def test_version_and_generated(self, schema):
        assert schema.version == "2.0"
        assert schema.generated == "2026-03-17"

    def test_get_row_and_chain(self, schema):
        row = schema.get_row("total_assets", "balance_sheet", "industrial")
        assert row is not None
        assert row.tag == "total_assets"
        chain = schema.get_tag_chain("total_assets", "balance_sheet", "industrial")
        assert isinstance(chain, tuple) and len(chain) > 0

    @staticmethod
    def _names(schema, tag, statement, company_type):
        return [
            f"{x['namespace']}:{x['tag']}"
            for x in schema.get_tag_chain(tag, statement, company_type)
        ]

    @pytest.mark.parametrize(
        "company_type", ["industrial", "financial", "diversified", "insurance"]
    )
    def test_chain_scope(self, schema, company_type):
        revenue = self._names(schema, "total_revenue", "income_statement", company_type)
        assert revenue.index("us-gaap:Revenues") < revenue.index(
            "us-gaap:SalesRevenueNet"
        )
        for statement in ("income_statement", "cash_flow"):
            assert "us-gaap:OtherDepreciationAndAmortization" not in self._names(
                schema, "depreciation_and_amortization", statement, company_type
            )
        sbc = self._names(schema, "stock_based_compensation", "cash_flow", company_type)
        assert "us-gaap:StockIssuedDuringPeriodValueShareBasedCompensation" not in sbc
        assert self._names(
            schema, "temporary_equity", "balance_sheet", company_type
        ) == [
            "us-gaap:TemporaryEquityCarryingAmountIncludingPortionAttributableToNoncontrollingInterests",
            "us-gaap:TemporaryEquityCarryingAmount",
        ]
        rnci = self._names(
            schema, "redeemable_noncontrolling_interest", "balance_sheet", company_type
        )
        assert rnci[-1] == (
            "us-gaap:TemporaryEquityCarryingAmountAttributableToNoncontrollingInterest"
        )
        interest = self._names(
            schema, "total_interest_income", "income_statement", company_type
        )
        assert "us-gaap:InterestIncomeExpenseNet" not in interest
        assert "ifrs-full:InterestRevenueExpense" not in interest
        if company_type == "financial":
            assert not {
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
                "ifrs-full:RevenueFromContractsWithCustomers",
            } & set(revenue)
        if company_type == "insurance":
            investment = self._names(
                schema,
                "investment_securities_interest_income",
                "income_statement",
                company_type,
            )
            assert investment[0] == "us-gaap:NetInvestmentIncome"
            row = schema.get_row(
                "total_interest_income", "income_statement", company_type
            )
            assert row.parent == "investment_securities_interest_income"

    def test_get_row_missing_returns_none(self, schema):
        assert schema.get_row("does_not_exist", "balance_sheet", "industrial") is None
        assert (
            schema.get_tag_chain("does_not_exist", "balance_sheet", "industrial") == ()
        )

    def test_get_period_type(self, schema):
        assert (
            schema.get_period_type("total_assets", "balance_sheet", "industrial")
            == "instant"
        )
        assert schema.get_period_type("nope", "balance_sheet", "industrial") is None

    def test_extract_all_raises_for_annual_only_filer_on_quarterly(self, schema):
        # A 20-F (annual-only) filer with no interim data -> OpenBBError for quarterly.
        from openbb_core.app.model.abstract.error import OpenBBError

        facts_json = {
            "entityName": "Annual Only Inc.",
            "cik": "0000000001",
            "facts": _facts(
                [
                    ("ifrs-full", "Assets", "EUR", [_entry("2023-12-31", form="20-F")]),
                    (
                        "ifrs-full",
                        "Revenue",
                        "EUR",
                        [_entry("2023-12-31", "2023-01-01", form="20-F")],
                    ),
                ]
            ),
        }
        with pytest.raises(OpenBBError):
            schema.extract_all(facts_json, frequency="quarterly")

    def test_merge_facts_combines_units(self, schema):
        a = {
            "facts": _facts(
                [("us-gaap", "Assets", "USD", [_entry("2022-12-31", val=1.0)])]
            )
        }
        b = {
            "facts": _facts(
                [("us-gaap", "Assets", "USD", [_entry("2023-12-31", val=2.0)])]
            )
        }
        merged = schema.merge_facts(a, b)
        assert len(merged["us-gaap"]["Assets"]["units"]["USD"]) == 2


# ---------------------------------------------------------------------------
# _detection.py
# ---------------------------------------------------------------------------


class TestGetFilingDatesSemiAnnual:
    def test_semi_annual_150_to_200_day_window(self):
        # A 6-K with a ~182-day (H1) duration must register via the
        # 150<=days<=200 quarterly branch (line 127-130).
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenue",
                    "USD",
                    [_entry("2023-06-30", "2023-01-01", form="6-K")],
                ),
            ]
        )
        dates = get_filing_dates(facts, "quarterly")
        assert "2023-06-30" in dates

    def test_preliminary_quarterly_candidate_added(self):
        # 8-K with a ~90 day duration only registers as a preliminary
        # quarterly candidate when include_preliminary=True (line 131-136).
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenue",
                    "USD",
                    [_entry("2023-09-30", "2023-07-01", form="8-K")],
                ),
            ]
        )
        with_prelim = get_filing_dates(facts, "quarterly", include_preliminary=True)
        assert "2023-09-30" in with_prelim
        # Without the flag the 8-K quarter is ignored.
        assert "2023-09-30" not in get_filing_dates(facts, "quarterly")


class TestGetFilingDatesCanonicalEdges:
    def test_feb29_anchor_value_error_fallback(self):
        # Dominant month/day is 02-29; for non-leap anchor years datetime()
        # raises ValueError and the min(day, 28) fallback path runs (168-169).
        rev = [
            _entry("2020-02-29", "2019-03-01"),
            _entry("2024-02-29", "2023-03-01"),
            _entry("2016-02-29", "2015-03-01"),
            _entry("2028-02-29", "2027-03-01"),
        ]
        assets = [
            _entry("2020-02-29"),
            _entry("2024-02-29"),
            _entry("2016-02-29"),
            _entry("2028-02-29"),
        ]
        facts = _facts(
            [
                ("us-gaap", "Assets", "USD", assets),
                ("us-gaap", "Revenues", "USD", rev),
            ]
        )
        dates = get_filing_dates(facts, "annual")
        # All four leap-day ends survive the canonical filter.
        assert "2024-02-29" in dates
        assert "2020-02-29" in dates

    def test_earlier_near_duplicate_dropped_when_later_is_exact(self):
        # Equal support within 10 days: the dominant anchor date is kept.
        rev = [_entry(f"{y}-12-31", f"{y}-01-01") for y in (2021, 2022, 2023, 2024)]
        assets = [_entry(f"{y}-12-31") for y in (2021, 2022, 2023, 2024)]
        # A 52-week fiscal end a few days AFTER a calendar 12-31.
        rev.append(_entry("2025-01-03", "2024-01-05"))
        assets.append(_entry("2025-01-03"))
        facts = _facts(
            [
                ("us-gaap", "Assets", "USD", assets),
                ("us-gaap", "Revenues", "USD", rev),
            ]
        )
        dates = get_filing_dates(facts, "annual")
        assert "2024-12-31" in dates

    def test_later_near_duplicate_dropped_when_earlier_is_exact(self):
        # Equal support within 10 days: the dominant anchor date is kept.
        rev = [_entry(f"{y}-12-31", f"{y}-01-01") for y in (2020, 2021, 2022, 2023)]
        assets = [_entry(f"{y}-12-31") for y in (2020, 2021, 2022, 2023)]
        rev.append(_entry("2024-01-02", "2023-01-04"))
        assets.append(_entry("2024-01-02"))
        facts = _facts(
            [
                ("us-gaap", "Assets", "USD", assets),
                ("us-gaap", "Revenues", "USD", rev),
            ]
        )
        dates = get_filing_dates(facts, "annual")
        assert "2023-12-31" in dates
        assert "2024-01-02" not in dates

    def test_near_duplicate_cluster_keeps_best_supported_date(self):
        # 2023-09-30 carries more annual facts than the 09-24 anchor and 09-25 strays.
        ends = ("2020-09-24", "2021-09-24", "2022-09-24")
        rev = [_entry(e, f"{int(e[:4]) - 1}-09-25") for e in ends]
        ni = [_entry(e, f"{int(e[:4]) - 1}-09-25") for e in ends]
        assets = [_entry(e) for e in ends]
        rev += [
            _entry("2023-09-24", "2022-09-25"),
            _entry("2023-09-25", "2022-09-26"),
            _entry("2023-09-30", "2022-10-01"),
        ]
        ni.append(_entry("2023-09-30", "2022-10-01"))
        cogs = [_entry("2023-09-30", "2022-10-01")]
        assets.append(_entry("2023-09-30"))
        facts = _facts(
            [
                ("us-gaap", "Assets", "USD", assets),
                ("us-gaap", "Revenues", "USD", rev),
                ("us-gaap", "NetIncomeLoss", "USD", ni),
                ("us-gaap", "CostOfRevenue", "USD", cogs),
            ]
        )
        dates = get_filing_dates(facts, "annual")
        assert "2023-09-30" in dates
        assert "2023-09-24" not in dates
        assert "2023-09-25" not in dates


class TestGetFiscalMetaEdges:
    def test_annual_entry_without_filed_skipped(self):
        # An annual entry that has no `filed` is skipped (line 266-267);
        # metadata then falls back to int(date[:4]).
        facts = _facts(
            [
                ("us-gaap", "Assets", "USD", [_entry("2023-12-31", filed="")]),
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", filed="")],
                ),
            ]
        )
        meta = get_fiscal_meta(facts, "annual", {"2023-12-31"})
        assert meta["2023-12-31"] == {"fiscal_year": 2023, "fiscal_period": "FY"}

    def test_quarterly_entry_missing_fy_fp_skipped(self):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-09-30", "2023-07-01", form="10-Q", fy=None, fp="")],
                ),
            ]
        )
        meta = get_fiscal_meta(facts, "quarterly", {"2023-09-30"})
        assert meta["2023-09-30"] == {"fiscal_year": 2023, "fiscal_period": "Q3"}

    def test_semi_annual_metadata_used_for_quarter(self):
        # A 6-K H1 interim supplies fiscal metadata via the SEMI_ANNUAL
        # branch (279-283) and is read back through best_semi (328-333).
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry(
                            "2023-06-30",
                            "2023-01-01",
                            form="6-K",
                            fy=2023,
                            fp="H1",
                        )
                    ],
                ),
            ]
        )
        meta = get_fiscal_meta(facts, "quarterly", {"2023-06-30"})
        assert meta["2023-06-30"] == {"fiscal_year": 2023, "fiscal_period": "H1"}

    def test_preliminary_with_fy_fp_metadata(self):
        # An 8-K carrying explicit fy/fp populates best_preliminary via the
        # first preliminary branch (285-290) and is read back (335-340).
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry(
                            "2023-09-30",
                            "2023-07-01",
                            form="8-K",
                            fy=2023,
                            fp="Q3",
                        )
                    ],
                ),
            ]
        )
        meta = get_fiscal_meta(facts, "quarterly", {"2023-09-30"})
        assert meta["2023-09-30"] == {"fiscal_year": 2023, "fiscal_period": "Q3"}

    def test_semi_annual_half_year_classified_as_h1(self):
        # A 6-K half-year (~181-day) interim is classified as H1 from its
        # duration alone; the unreliable fy/fp fields are not required.
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry(
                            "2023-06-30",
                            "2023-01-01",
                            form="6-K",
                            fy=None,
                            fp="",
                        )
                    ],
                ),
            ]
        )
        meta = get_fiscal_meta(facts, "quarterly", {"2023-06-30"})
        assert meta["2023-06-30"] == {"fiscal_year": 2023, "fiscal_period": "H1"}

    def test_preliminary_without_fy_fp_derives_calendar_quarter(self):
        # An 8-K with no fy/fp derives a calendar quarter from the end
        # month (line 291-298): 2023-09-30 -> Q3.
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry(
                            "2023-09-30",
                            "2023-07-01",
                            form="8-K",
                            fy=None,
                            fp="",
                        )
                    ],
                ),
            ]
        )
        meta = get_fiscal_meta(facts, "quarterly", {"2023-09-30"})
        assert meta["2023-09-30"] == {"fiscal_year": 2023, "fiscal_period": "Q3"}

    def test_semi_annual_only_annual_date_becomes_h2(self):
        # No 10-Q data, only 6-K interims: an annual date in a quarterly
        # extraction is labelled H2 when non-annual dates do NOT outnumber
        # annual dates (line 312-314).
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Assets",
                    "USD",
                    [
                        _entry("2023-06-30", form="6-K", fy=2023, fp="H1"),
                        _entry("2023-12-31", form="10-K", fy=2023, fp="FY"),
                    ],
                ),
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry(
                            "2023-06-30",
                            "2023-01-01",
                            form="6-K",
                            fy=2023,
                            fp="H1",
                        ),
                        _entry(
                            "2023-12-31",
                            "2023-01-01",
                            form="10-K",
                            fy=2023,
                            fp="FY",
                        ),
                    ],
                ),
            ]
        )
        dates = {"2023-06-30", "2023-12-31"}
        meta = get_fiscal_meta(facts, "quarterly", dates)
        # 1 non-annual (H1) is not > 1 annual -> H2.
        assert meta["2023-12-31"]["fiscal_period"] == "H2"

    def test_quarterly_fiscal_year_from_annual_filing(self):
        # An annual date marked Q4 whose fiscal_year disagrees with the
        # preceding interim's fiscal_year is realigned (line 366-370).
        # Fiscal year ends 2024-01-31; the Q3 interim (2023-10-31) carries
        # fy=2024, the FY end (2024-01-31) is mis-stamped fy=2023.
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Assets",
                    "USD",
                    [
                        _entry("2023-10-31", form="10-Q", fy=2024, fp="Q3"),
                        _entry("2024-01-31", form="10-K", fy=2023, fp="FY"),
                    ],
                ),
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry(
                            "2023-10-31",
                            "2023-08-01",
                            form="10-Q",
                            fy=2024,
                            fp="Q3",
                        ),
                        _entry(
                            "2024-01-31",
                            "2023-02-01",
                            form="10-K",
                            fy=2023,
                            fp="FY",
                        ),
                    ],
                ),
            ]
        )
        dates = get_filing_dates(facts, "quarterly")
        meta = get_fiscal_meta(facts, "quarterly", dates)
        assert meta["2024-01-31"]["fiscal_year"] == 2023
        assert meta["2024-01-31"]["fiscal_period"] in ("Q4", "H2")


class TestDetectCurrencyTie:
    def test_max_picks_a_currency_on_tie(self):
        # Equal counts of two currencies -> max() still returns one of them
        # (deterministic, exercises the non-empty return at line 398).
        facts = _facts(
            [
                ("us-gaap", "A", "USD", [_entry("2023-12-31")]),
                ("us-gaap", "B", "JPY", [_entry("2023-12-31")]),
            ]
        )
        assert detect_reporting_currency(facts) in {"USD", "JPY"}


# ---------------------------------------------------------------------------
# _extraction.py
# ---------------------------------------------------------------------------


class TestGetAnnualValuesEdges:
    def test_missing_tag_appends_empty_candidate(self):
        # A tag absent from facts hits the `if not tag_data` continue (72-73);
        # the second (present) tag still resolves.
        facts = _facts(
            [
                (
                    "us-gaap",
                    "RevB",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=200.0)],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("RevA", "us-gaap"), ("RevB", "us-gaap")])
        res = _get_annual_values(facts, row)
        assert res["2023-12-31"][1] == 200.0

    def test_tag_present_but_no_matching_unit(self):
        # Tag exists but only under a non-monetary unit -> _get_unit_data
        # falls back to first unit; here we force an empty units dict so the
        # `if not unit_data` branch (line 71-73) runs.
        facts = {"us-gaap": {"RevA": {"units": {}}}}
        row = _rd("total_revenue", xbrl=[("RevA", "us-gaap")])
        assert _get_annual_values(facts, row) == {}

    def test_unparseable_dates_skipped(self):
        # A non-date end/start raises in strptime -> entry skipped (96-97).
        facts = _facts(
            [("us-gaap", "Revenues", "USD", [_entry("bad-date", "worse", val=5.0)])]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        assert _get_annual_values(facts, row) == {}

    def test_none_value_skipped(self):
        # An annual-window entry whose val is None is skipped (line 104-105).
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=None)],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        assert _get_annual_values(facts, row) == {}

    def test_date_present_only_in_skipped_candidate(self):
        # all_dates collects a date, but every filing for it was filtered so
        # ref_filed stays None -> the `if ref_filed is None: continue` at
        # line 136-137 runs. Achieved by a val=None entry on a lone tag.
        facts = {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "end": "2023-12-31",
                                "start": "2023-01-01",
                                "val": 10.0,
                                "form": "10-K",
                                "filed": "2024-02-15",
                            }
                        ]
                    }
                }
            }
        }
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        # Sanity: this one resolves.
        assert _get_annual_values(facts, row)["2023-12-31"][1] == 10.0


class TestGetYtd9ValuesEdges:
    def test_missing_tag_continue(self):
        # First tag missing -> `if not tag_data: continue` (168-169); second
        # tag supplies both the annual and the 9-month YTD entries.
        facts = _facts(
            [
                (
                    "us-gaap",
                    "RevB",
                    "USD",
                    [
                        _entry("2023-12-31", "2023-01-01", val=1000.0),
                        _entry("2023-09-30", "2023-01-01", val=700.0),
                    ],
                ),
            ]
        )
        row = _rd("total_revenue", xbrl=[("RevA", "us-gaap"), ("RevB", "us-gaap")])
        res = _get_ytd9_values(facts, row)
        assert res["2023-12-31"] == 300.0

    def test_empty_units_continue(self):
        # Tag present but units empty -> `if not unit_data: continue` (173-174).
        facts = {"us-gaap": {"Rev": {"units": {}}}}
        row = _rd("total_revenue", xbrl=[("Rev", "us-gaap")])
        assert _get_ytd9_values(facts, row) == {}

    def test_zero_length_duration_skipped(self):
        # start == end inside the YTD loop -> skipped (line 180-181); leaves
        # no annual entries so result is empty.
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-12-31", "2023-12-31", val=1000.0)],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        assert _get_ytd9_values(facts, row) == {}

    def test_unparseable_and_none_value_skipped(self):
        # Bad date (188-189) and None val (193-194) inside the YTD loop.
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry("bad", "worse", val=10.0),
                        _entry("2023-12-31", "2023-01-01", val=None),
                    ],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        assert _get_ytd9_values(facts, row) == {}

    def test_no_ytd_match_continue(self):
        # Annual present and a 9-month YTD present but the YTD end does NOT
        # fall strictly inside any (fy_start, fy_end) window, so ytd_end_match
        # stays None -> `if not ytd_end_match: continue` (229-230). The YTD
        # belongs to a different fiscal year than the only annual.
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry("2023-12-31", "2023-01-01", val=1000.0),
                        # 9-mo YTD ending in a LATER year -> outside 2023 window.
                        _entry("2024-09-30", "2024-01-01", val=700.0),
                    ],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        assert _get_ytd9_values(facts, row) == {}

    def test_no_common_filing_uses_latest_each(self):
        # FY and YTD filed on different dates (no common filing) -> the else
        # branch picks latest of each (line 241-243).
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry(
                            "2023-12-31",
                            "2023-01-01",
                            filed="2024-02-10",
                            val=1000.0,
                        ),
                        _entry(
                            "2023-09-30",
                            "2023-01-01",
                            filed="2023-11-05",
                            val=700.0,
                        ),
                    ],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        res = _get_ytd9_values(facts, row)
        assert res["2023-12-31"] == 300.0


class TestExtractRowValuesEdges:
    def test_missing_tag_quarterly_appends_empty_ytd_candidate(self):
        # Quarterly duration row with collect_ytd True: a missing first tag
        # appends empty entries to BOTH tag_candidates and ytd_tag_candidates
        # (line 278-284 / 289-294 region).
        facts = _facts(
            [
                (
                    "us-gaap",
                    "RevB",
                    "USD",
                    [_entry("2023-03-31", "2023-01-01", form="10-Q", val=100.0)],
                ),
            ]
        )
        row = _rd("total_revenue", xbrl=[("RevA", "us-gaap"), ("RevB", "us-gaap")])
        vals, _ = extract_row_values(facts, row, "quarterly", "USD")
        assert vals.get("2023-03-31") == 100.0

    def test_empty_units_quarterly_appends_empty_ytd_candidate(self):
        # Tag present but empty units, quarterly + collect_ytd -> the
        # `if not unit_data` branch appends empty ytd candidate (289-294).
        facts = {
            "us-gaap": {
                "RevA": {"units": {}},
                "RevB": {
                    "units": {
                        "USD": [
                            _entry("2023-03-31", "2023-01-01", form="10-Q", val=100.0)
                        ]
                    }
                },
            }
        }
        row = _rd("total_revenue", xbrl=[("RevA", "us-gaap"), ("RevB", "us-gaap")])
        vals, _ = extract_row_values(facts, row, "quarterly", "USD")
        assert vals.get("2023-03-31") == 100.0

    def test_entry_without_end_skipped(self):
        # An entry with no `end` is skipped (line 308-309).
        facts = {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2023-01-01",
                                "val": 5.0,
                                "form": "10-K",
                                "filed": "2024-02-15",
                            }
                        ]
                    }
                }
            }
        }
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        assert extract_row_values(facts, row, "annual", "USD") == ({}, {})

    def test_unparseable_duration_skipped_annual(self):
        # Bad date in duration branch -> strptime raises -> skipped (323-324).
        facts = _facts(
            [("us-gaap", "Revenues", "USD", [_entry("bad", "worse", val=5.0)])]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        assert extract_row_values(facts, row, "annual", "USD") == ({}, {})

    def test_semi_annual_h1_window_quarterly(self):
        # 6-K H1 (~181 days) in quarterly mode registers via the
        # SEMI_ANNUAL_FORMS window branch (line 329-331).
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-06-30", "2023-01-01", form="6-K", val=400.0)],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        vals, _ = extract_row_values(facts, row, "quarterly", "USD")
        assert vals.get("2023-06-30") == 400.0

    def test_semi_annual_nine_month_extracted(self):
        # A 6-K with a ~273-day (9-month) duration falls in the SEMI_ANNUAL
        # window (240..310) and is extracted as a cumulative interim value.
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-09-30", "2023-01-01", form="6-K", val=700.0)],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        vals, _ = extract_row_values(facts, row, "quarterly", "USD")
        assert vals.get("2023-09-30") == 700.0

    def test_none_value_skipped_after_window(self):
        # A within-window annual entry whose val is None is skipped (348-349).
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=None)],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        assert extract_row_values(facts, row, "annual", "USD") == ({}, {})

    def test_quarterly_ytd_derivation_fills_missing_quarter(self):
        # Q1 + Q2 standalone present, Q3 only as a 9-month YTD -> Q3 derived
        # as ytd - prev_cum (line 467-543 YTD reconstruction path), and the
        # ref-resolution `ref is None`/fallback branches (471-493) execute.
        entries = [
            # FY anchor (needed for fy_boundaries).
            _entry("2023-12-31", "2023-01-01", form="10-K", val=1000.0),
            # Standalone quarters from 10-Q vintage.
            _entry("2023-03-31", "2023-01-01", form="10-Q", val=200.0),
            _entry("2023-06-30", "2023-04-01", form="10-Q", val=250.0),
            # 9-month YTD (Jan..Sep) -> 273 days, in the 136..310 YTD band.
            _entry("2023-09-30", "2023-01-01", form="10-Q", val=750.0),
        ]
        facts = _facts([("us-gaap", "Revenues", "USD", entries)])
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        vals, srcs = extract_row_values(facts, row, "quarterly", "USD")
        # Q3 derived = 750 (YTD9) - (200 + 250) = 300.
        assert vals.get("2023-09-30") == 300.0
        assert "ytd_derived" in srcs.get("2023-09-30", "")

    def test_quarterly_first_ytd_past_first_quarter_is_no_quarter(self):
        entries = [
            _entry("2023-12-31", "2023-01-01", form="10-K", val=1000.0),
            _entry("2023-06-30", "2023-01-01", form="10-Q", val=500.0),
        ]
        facts = _facts([("us-gaap", "Revenues", "USD", entries)])
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        vals, _ = extract_row_values(facts, row, "quarterly", "USD")
        assert vals == {}

    @pytest.mark.parametrize(
        ("first", "expected_q3"),
        [
            (_entry("2023-06-30", "2023-01-01", form="10-Q", val=500.0), 250.0),
            (_entry("2023-03-31", "2023-01-01", form="10-Q", val=200.0), None),
            (None, None),
        ],
    )
    def test_quarterly_ytd_quarter_needs_preceding_quarter(self, first, expected_q3):
        entries = [
            _entry("2023-12-31", "2023-01-01", form="10-K", val=1000.0),
            _entry("2023-09-30", "2023-01-01", form="10-Q", val=750.0),
            *([first] if first else []),
        ]
        facts = _facts([("us-gaap", "Revenues", "USD", entries)])
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        vals, srcs = extract_row_values(facts, row, "quarterly", "USD")
        assert "2023-06-30" not in vals
        assert vals.get("2023-09-30") == expected_q3
        assert vals["2023-12-31"] == 250.0
        assert srcs["2023-12-31"] == (
            "Q4: FY[us-gaap:Revenues] \u2212 9M[us-gaap:Revenues]"
        )

    @pytest.mark.parametrize(("goodwill_fy", "expected"), [(164.0, 0.0), (None, None)])
    def test_q4_from_nine_months_on_one_concept(self, goodwill_fy, expected):
        goodwill = [
            _entry("2025-09-30", "2025-01-01", form="10-Q", val=164.0),
            _entry("2025-09-30", "2025-07-01", form="10-Q", val=164.0),
        ]
        if goodwill_fy is not None:
            goodwill.append(_entry("2025-12-31", "2025-01-01", val=goodwill_fy))
        facts = _facts(
            [
                (
                    "us-gaap",
                    "AssetImpairmentCharges",
                    "USD",
                    [_entry("2025-12-31", "2025-01-01", val=26.0)],
                ),
                ("us-gaap", "GoodwillImpairmentLoss", "USD", goodwill),
            ]
        )
        row = _rd(
            "impairment_expense",
            xbrl=[
                ("AssetImpairmentCharges", "us-gaap"),
                ("GoodwillImpairmentLoss", "us-gaap"),
            ],
        )
        vals, srcs = extract_row_values(facts, row, "quarterly", "USD")
        assert vals.get("2025-12-31") == expected
        if expected is not None:
            assert srcs["2025-12-31"] == (
                "Q4: FY[us-gaap:GoodwillImpairmentLoss] \u2212 "
                "9M[us-gaap:GoodwillImpairmentLoss]"
            )

    def test_quarterly_ytd_with_shifted_start_uses_prior_quarters(self):
        entries = [
            _entry("2023-12-31", "2023-01-01", form="10-K", val=1220.0),
            _entry("2023-03-31", "2023-01-01", form="10-Q", val=305.0),
            _entry("2023-06-30", "2023-01-03", form="10-Q", val=610.0),
            _entry("2023-09-30", "2023-01-01", form="10-Q", val=915.0),
        ]
        facts = _facts([("us-gaap", "Revenues", "USD", entries)])
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        vals, srcs = extract_row_values(facts, row, "quarterly", "USD")
        assert vals["2023-06-30"] == 305.0
        assert vals["2023-09-30"] == 305.0
        assert vals["2023-12-31"] == 305.0
        assert srcs["2023-09-30"] == "ytd_derived(us-gaap:Revenues)"

    def test_quarterly_ytd_with_ref_filed_map_fallback(self):
        # Same YTD reconstruction but driving the ref_filed_map branch where
        # the requested ref is absent for the YTD date -> the
        # `before/min(ytd_fdata)` fallback (line 492-494) runs.
        entries = [
            _entry(
                "2023-12-31", "2023-01-01", form="10-K", filed="2024-02-15", val=1000.0
            ),
            _entry(
                "2023-03-31", "2023-01-01", form="10-Q", filed="2023-05-01", val=200.0
            ),
            _entry(
                "2023-06-30", "2023-04-01", form="10-Q", filed="2023-08-01", val=250.0
            ),
            _entry(
                "2023-09-30", "2023-01-01", form="10-Q", filed="2023-11-01", val=750.0
            ),
        ]
        facts = _facts([("us-gaap", "Revenues", "USD", entries)])
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        # ref_filed_map points the YTD date at a filing that does not exist.
        ref_map = {
            "2023-03-31": "2023-05-01",
            "2023-06-30": "2023-08-01",
            "2023-09-30": "2099-01-01",
            "2023-12-31": "2024-02-15",
        }
        vals, srcs = extract_row_values(
            facts, row, "quarterly", "USD", ref_filed_map=ref_map
        )
        assert vals.get("2023-09-30") == 300.0

    def test_quarterly_ytd_ref_map_missing_date_skips_resolution(self):
        # ref_filed_map omits the YTD date entirely -> `ref = map.get(date)`
        # is None and the YTD candidate's `if ref is None: continue` (480-481)
        # runs, so no ytd_derived value is produced for that date.
        entries = [
            _entry(
                "2023-12-31", "2023-01-01", form="10-K", filed="2024-02-15", val=1000.0
            ),
            _entry(
                "2023-03-31", "2023-01-01", form="10-Q", filed="2023-05-01", val=200.0
            ),
            _entry(
                "2023-06-30", "2023-04-01", form="10-Q", filed="2023-08-01", val=250.0
            ),
            _entry(
                "2023-09-30", "2023-01-01", form="10-Q", filed="2023-11-01", val=750.0
            ),
        ]
        facts = _facts([("us-gaap", "Revenues", "USD", entries)])
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        # Deliberately leave 2023-09-30 (the YTD date) out of the map.
        ref_map = {
            "2023-03-31": "2023-05-01",
            "2023-06-30": "2023-08-01",
            "2023-12-31": "2024-02-15",
        }
        vals, srcs = extract_row_values(
            facts, row, "quarterly", "USD", ref_filed_map=ref_map
        )
        # Q3 was not resolved via the YTD path (its ref was None).
        assert "ytd_derived" not in srcs.get("2023-09-30", "")


class TestComputeRefFilingsEdges:
    def test_missing_tag_continue(self):
        # A row tag absent from facts -> `if not tag_data: continue` (614).
        # Provided indirectly: row chains two tags, first missing.
        facts = _facts(
            [
                (
                    "us-gaap",
                    "RevB",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", filed="2024-02-01")],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("RevA", "us-gaap"), ("RevB", "us-gaap")])
        ref = compute_ref_filings(facts, [row], "annual", "USD")
        assert ref["2023-12-31"] == "2024-02-01"

    def test_empty_units_continue(self):
        # Tag present but empty units -> `if not unit_data: continue` (619-620).
        facts = {
            "us-gaap": {
                "RevA": {"units": {}},
                "RevB": {
                    "units": {
                        "USD": [_entry("2023-12-31", "2023-01-01", filed="2024-02-01")]
                    }
                },
            }
        }
        row = _rd("total_revenue", xbrl=[("RevA", "us-gaap"), ("RevB", "us-gaap")])
        ref = compute_ref_filings(facts, [row], "annual", "USD")
        assert ref["2023-12-31"] == "2024-02-01"

    def test_entry_without_end_skipped(self):
        # Entry lacking `end` -> skipped at line 630-631.
        facts = {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2023-01-01",
                                "val": 1.0,
                                "form": "10-K",
                                "filed": "2024-02-01",
                            }
                        ]
                    }
                }
            }
        }
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        assert compute_ref_filings(facts, [row], "annual", "USD") == {}

    def test_unparseable_duration_skipped(self):
        # Bad date in duration branch -> strptime raises -> skipped (644-645).
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("bad", "worse", filed="2024-02-01")],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        assert compute_ref_filings(facts, [row], "annual", "USD") == {}

    def test_semi_annual_h1_window_quarterly(self):
        # 6-K H1 (~181 days) accepted via SEMI_ANNUAL window (line 650-652).
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry(
                            "2023-06-30", "2023-01-01", form="6-K", filed="2023-08-01"
                        )
                    ],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        ref = compute_ref_filings(facts, [row], "quarterly", "USD")
        assert ref["2023-06-30"] == "2023-08-01"

    def test_semi_annual_nine_month_produces_ref(self):
        # A 6-K with a ~273-day (9-month) duration falls in the SEMI_ANNUAL
        # window (240..310) and contributes a reference filing.
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry(
                            "2023-09-30", "2023-01-01", form="6-K", filed="2023-11-01"
                        )
                    ],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        assert compute_ref_filings(facts, [row], "quarterly", "USD") == {
            "2023-09-30": "2023-11-01"
        }

    def test_out_of_window_quarterly_duration_skipped(self):
        # A 10-Q-vintage duration of ~273 days is neither 60..135 (quarter)
        # nor a semi-annual form -> rejected by `elif not 60<=days<=135`
        # (line 653-654) leaving no ref.
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry(
                            "2023-09-30", "2023-01-01", form="10-Q", filed="2023-11-01"
                        )
                    ],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        assert compute_ref_filings(facts, [row], "quarterly", "USD") == {}

    def test_entry_without_filed_skipped(self):
        # An entry with no `filed` -> skipped (line 658-659).
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", filed="")],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        assert compute_ref_filings(facts, [row], "annual", "USD") == {}

    def test_unparseable_filed_gap_skipped(self):
        # A non-pit-mode entry whose `filed` is unparseable raises in the gap
        # computation -> skipped (line 667-668).
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", filed="not-a-date")],
                )
            ]
        )
        row = _rd("total_revenue", xbrl=[("Revenues", "us-gaap")])
        assert compute_ref_filings(facts, [row], "annual", "USD") == {}


# ---------------------------------------------------------------------------
# _schema.py -- drive StatementSchema.extract() directly.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def schema():
    return StatementSchema()


def test_combine_unfunded_provision_skips_none_add(schema):
    row = RowResult(
        tag="provision_for_credit_losses",
        label="Provision for credit losses",
        description="",
        parent=None,
        sequence=1,
        factor="+",
        balance="debit",
        unit="monetary",
        period_type="duration",
        values={"2024-12-31": 100.0},
        sources={
            "2024-12-31": "us-gaap:FinancingReceivableExcludingAccruedInterestCreditLossExpenseReversal"
        },
    )
    with patch(
        "openbb_sec.utils.statement_schema._schema.extract_row_values",
        return_value=({}, {}),
    ):
        schema._combine_unfunded_provision(
            [row],
            "income_statement",
            "financial",
            {"us-gaap": {}},
            "annual",
            "USD",
            {},
        )
    assert row.values["2024-12-31"] == 100.0


class TestSchemaExtractDefaults:
    def test_extract_infers_type_dates_and_ref_map(self, schema):
        # Calling extract() with company_type / filing_dates / ref_filed_map
        # all None drives the inference branches (line 229-235, 246-254).
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", form="10-K", val=500.0 * _M)],
                ),
                (
                    "us-gaap",
                    "CostsAndExpenses",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", form="10-K", val=300.0 * _M)],
                ),
            ]
        )
        res = schema.extract({"facts": facts}, "income_statement", frequency="annual")
        assert res.statement == "income_statement"
        assert res.currency == "USD"
        assert "2023-12-31" in res.dates

    def test_extract_quarterly_computes_annual_ref_map(self, schema):
        # Quarterly extract() with no maps computes the annual reference map for Q4.
        entries = [
            _entry("2023-03-31", "2023-01-01", form="10-Q", val=100.0 * _M),
            _entry("2023-06-30", "2023-04-01", form="10-Q", val=150.0 * _M),
            _entry("2023-09-30", "2023-07-01", form="10-Q", val=200.0 * _M),
            _entry("2023-12-31", "2023-01-01", form="10-K", val=600.0 * _M),
        ]
        facts = _facts(
            [
                ("us-gaap", "Revenues", "USD", entries),
                (
                    "us-gaap",
                    "Assets",
                    "USD",
                    [
                        _entry("2023-03-31", form="10-Q"),
                        _entry("2023-06-30", form="10-Q"),
                        _entry("2023-09-30", form="10-Q"),
                        _entry("2023-12-31", form="10-K"),
                    ],
                ),
            ]
        )
        res = schema.extract(
            {"facts": facts}, "income_statement", frequency="quarterly"
        )
        rev = next(r for r in res.rows if r.tag == "total_revenue")
        assert rev.values["2023-12-31"] == 150.0 * _M
        assert rev.sources["2023-12-31"].startswith("Q4: FY[us-gaap:Revenues]")

    def test_extract_include_preliminary_marks_dates(self, schema):
        # include_preliminary populates _preliminary_dates and tags sources
        # with the "preliminary:" prefix (line 237-240, 431-438).
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [
                        _entry(
                            "2024-12-31",
                            "2024-01-01",
                            form="10-K",
                            filed="2025-02-15",
                            val=500.0 * _M,
                        ),
                        _entry(
                            "2025-12-31",
                            "2025-01-01",
                            form="8-K",
                            filed="2026-01-30",
                            val=600.0 * _M,
                        ),
                    ],
                ),
                (
                    "us-gaap",
                    "CostsAndExpenses",
                    "USD",
                    [
                        _entry(
                            "2024-12-31",
                            "2024-01-01",
                            form="10-K",
                            filed="2025-02-15",
                            val=300.0 * _M,
                        ),
                        _entry(
                            "2025-12-31",
                            "2025-01-01",
                            form="8-K",
                            filed="2026-01-30",
                            val=350.0 * _M,
                        ),
                    ],
                ),
            ]
        )
        res = schema.extract(
            {"facts": facts},
            "income_statement",
            frequency="annual",
            include_preliminary=True,
        )
        # The 8-K-only 2025 date is preliminary.
        assert "2025-12-31" in res.preliminary_dates
        rev = next(r for r in res.rows if r.tag == "total_revenue")
        assert rev.sources["2025-12-31"].startswith("preliminary:")


class TestSchemaExtractCashFlow:
    def _cf_facts(self, *, nc_val, eop_vals):
        """Build cash-flow facts: 3 activities + fx + net_change + EOP cash.

        ``eop_vals`` maps end-date -> EOP cash instant value.
        """
        op = "NetCashProvidedByUsedInOperatingActivities"
        inv = "NetCashProvidedByUsedInInvestingActivities"
        fin = "NetCashProvidedByUsedInFinancingActivities"
        fx = "EffectOfExchangeRateOnCashAndCashEquivalents"
        ncd = "CashAndCashEquivalentsPeriodIncreaseDecrease"
        eop = "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
        tags = []
        for d in eop_vals:
            y = d[:4]
            start = f"{y}-01-01"
            tags.extend(
                [
                    (
                        "us-gaap",
                        op,
                        "USD",
                        [_entry(d, start, form="10-K", val=500.0 * _M)],
                    ),
                    (
                        "us-gaap",
                        inv,
                        "USD",
                        [_entry(d, start, form="10-K", val=-200.0 * _M)],
                    ),
                    (
                        "us-gaap",
                        fin,
                        "USD",
                        [_entry(d, start, form="10-K", val=-150.0 * _M)],
                    ),
                    (
                        "us-gaap",
                        fx,
                        "USD",
                        [_entry(d, start, form="10-K", val=50.0 * _M)],
                    ),
                    (
                        "us-gaap",
                        ncd,
                        "USD",
                        [_entry(d, start, form="10-K", val=nc_val)],
                    ),
                    ("us-gaap", eop, "USD", [_entry(d, form="10-K", val=eop_vals[d])]),
                    # Assets instant anchors the annual date resolution.
                    ("us-gaap", "Assets", "USD", [_entry(d, form="10-K")]),
                ]
            )
        return _facts(tags)

    def test_eop_standalone_backfill_and_bop_derivation(self, schema):
        # Two consecutive years with EOP cash instants: the second year's BOP
        # is derived from the prior year's EOP (line 347-358) and the EOP
        # standalone backfill (line 336-345) populates eop from facts.
        facts = self._cf_facts(
            nc_val=200.0 * _M,
            eop_vals={"2022-12-31": 1000.0 * _M, "2023-12-31": 1200.0 * _M},
        )
        res = schema.extract({"facts": facts}, "cash_flow", frequency="annual")
        bop = next(
            (r for r in res.rows if r.tag == "cash_at_beginning_of_period"), None
        )
        assert bop is not None
        # BOP(2023) derived from EOP(2022) = 1000M.
        assert bop.values.get("2023-12-31") == 1000.0 * _M
        assert "derived: cash_at_end_of_period" in bop.sources["2023-12-31"]

    def test_identity_enforced_on_bop_when_derived(self, schema):
        # EOP - net_change != BOP(derived): because BOP source contains
        # "derived:", BOP is rewritten to EOP - net_change (line 382-387).
        # Year 1 EOP=1000, Year 2 EOP=1500, net_change=200 -> derived BOP
        # (1000) violates 1000 + 200 != 1500 -> enforced to 1500-200=1300.
        facts = self._cf_facts(
            nc_val=200.0 * _M,
            eop_vals={"2022-12-31": 1000.0 * _M, "2023-12-31": 1500.0 * _M},
        )
        res = schema.extract({"facts": facts}, "cash_flow", frequency="annual")
        bop = next(r for r in res.rows if r.tag == "cash_at_beginning_of_period")
        assert bop.values["2023-12-31"] == 1300.0 * _M
        assert "identity-enforced" in bop.sources["2023-12-31"]

    def test_net_change_corrected_when_activities_explain_cash_change(self, schema):
        facts = self._cf_facts(
            nc_val=999.0 * _M,
            eop_vals={"2022-12-31": 1000.0 * _M, "2023-12-31": 1200.0 * _M},
        )
        res = schema.extract({"facts": facts}, "cash_flow", frequency="annual")
        nc = next(r for r in res.rows if r.tag == "net_change_in_cash")
        assert nc.values["2023-12-31"] == 200.0 * _M
        assert nc.sources["2023-12-31"] == (
            "corrected: cash_at_end_of_period - cash_at_beginning_of_period"
        )
        other = next(
            (r for r in res.rows if r.tag == "other_net_changes_in_cash"), None
        )
        assert other is None or "2023-12-31" not in other.values
        bop = next(r for r in res.rows if r.tag == "cash_at_beginning_of_period")
        assert bop.values["2023-12-31"] == 1000.0 * _M


class TestSchemaExtractBalanceSheetAnchor:
    def _facts(self, *, with_le):
        tags = [
            (
                "us-gaap",
                "Revenues",
                "USD",
                [
                    _entry(
                        "2022-12-31", "2022-01-01", filed="2023-02-15", val=900.0 * _M
                    )
                ],
            ),
            (
                "us-gaap",
                "Assets",
                "USD",
                [
                    _entry("2022-12-31", filed="2023-02-15", val=300.0 * _M),
                    _entry("2022-12-31", filed="2024-02-15", val=300.0 * _M),
                ],
            ),
            (
                "us-gaap",
                "Liabilities",
                "USD",
                [_entry("2022-12-31", filed="2023-02-15", val=200.0 * _M)],
            ),
            (
                "us-gaap",
                "StockholdersEquity",
                "USD",
                [
                    _entry("2022-12-31", filed="2023-02-15", val=100.0 * _M),
                    _entry("2022-12-31", filed="2024-02-15", val=90.0 * _M),
                ],
            ),
        ]
        if with_le:
            tags.append(
                (
                    "us-gaap",
                    "LiabilitiesAndStockholdersEquity",
                    "USD",
                    [_entry("2022-12-31", filed="2023-02-15", val=300.0 * _M)],
                )
            )
        return _facts(tags)

    def _row(self, res, tag):
        return next(r for r in res.rows if r.tag == tag)

    def test_liabilities_and_equity_filing_is_reference(self, schema):
        res = schema.extract(
            {"facts": self._facts(with_le=True)},
            "balance_sheet",
            frequency="annual",
            company_type="industrial",
        )
        te = self._row(res, "total_equity")
        assert te.values["2022-12-31"] == 100.0 * _M
        assert te.sources["2022-12-31"] == "us-gaap:StockholdersEquity"
        assert self._row(res, "total_liabilities").sources["2022-12-31"] == (
            "us-gaap:Liabilities"
        )

    def test_anchor_overrides_supplied_reference_map(self, schema):
        res = schema.extract(
            {"facts": self._facts(with_le=True)},
            "balance_sheet",
            frequency="annual",
            company_type="industrial",
            ref_filed_map={"2022-12-31": "2024-02-15"},
        )
        assert self._row(res, "total_equity").values["2022-12-31"] == 100.0 * _M

    def test_total_assets_filing_is_reference_without_liabilities_and_equity(
        self, schema
    ):
        res = schema.extract(
            {"facts": self._facts(with_le=False)},
            "balance_sheet",
            frequency="annual",
            company_type="industrial",
        )
        te = self._row(res, "total_equity")
        assert te.values["2022-12-31"] == 90.0 * _M
        assert te.sources["2022-12-31"] == "us-gaap:StockholdersEquity"
        assert self._row(res, "total_liabilities").sources["2022-12-31"] == (
            "us-gaap:Liabilities(fallback)"
        )


class TestSchemaExtractChainSubsets:
    def _facts(self, broad, narrow):
        return _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=900.0 * _M)],
                ),
                (
                    "us-gaap",
                    "ResearchAndDevelopmentExpense",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=broad)],
                ),
                (
                    "us-gaap",
                    "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=narrow)],
                ),
            ]
        )

    def _rd_row(self, schema, facts):
        res = schema.extract(
            {"facts": facts},
            "income_statement",
            frequency="annual",
            company_type="industrial",
        )
        return next(r for r in res.rows if r.tag == "rd_expense")

    def test_larger_narrower_concept_replaces_partial_broader_value(self, schema):
        rd = self._rd_row(schema, self._facts(100.0 * _M, 150.0 * _M))
        assert rd.values["2023-12-31"] == 150.0 * _M
        assert rd.sources["2023-12-31"] == (
            "us-gaap:ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"
        )

    def test_smaller_narrower_concept_keeps_broader_value(self, schema):
        rd = self._rd_row(schema, self._facts(120.0 * _M, 110.0 * _M))
        assert rd.values["2023-12-31"] == 120.0 * _M
        assert rd.sources["2023-12-31"] == "us-gaap:ResearchAndDevelopmentExpense"

    @pytest.mark.parametrize(
        ("revenues", "sales", "expected", "source"),
        [
            (0.0, 950.0 * _M, 950.0 * _M, "us-gaap:SalesRevenueNet"),
            (1000.0 * _M, 950.0 * _M, 1000.0 * _M, "us-gaap:Revenues"),
        ],
    )
    def test_revenue_subset(self, schema, revenues, sales, expected, source):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "Revenues",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=revenues)],
                ),
                (
                    "us-gaap",
                    "SalesRevenueNet",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=sales)],
                ),
            ]
        )
        res = schema.extract(
            {"facts": facts},
            "income_statement",
            frequency="annual",
            company_type="industrial",
        )
        row = next(r for r in res.rows if r.tag == "total_revenue")
        assert row.values["2023-12-31"] == expected
        assert row.sources["2023-12-31"] == source

    @pytest.mark.parametrize(
        ("goods", "cost", "expected", "source"),
        [
            (33 * _M, 40199 * _M, 40199 * _M, "us-gaap:CostOfRevenue"),
            (900 * _M, 800 * _M, 900 * _M, "us-gaap:CostOfGoodsAndServicesSold"),
        ],
    )
    def test_cost_of_revenue_subset(self, schema, goods, cost, expected, source):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "CostOfGoodsAndServicesSold",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=goods)],
                ),
                (
                    "us-gaap",
                    "CostOfRevenue",
                    "USD",
                    [_entry("2023-12-31", "2023-01-01", val=cost)],
                ),
            ]
        )
        res = schema.extract(
            {"facts": facts},
            "income_statement",
            frequency="annual",
            company_type="industrial",
        )
        row = next(r for r in res.rows if r.tag == "total_cost_of_revenue")
        assert row.values["2023-12-31"] == expected
        assert row.sources["2023-12-31"] == source

    def test_nonnegative_concept_reads_as_magnitude(self, schema):
        entries = [
            _entry("2023-03-31", "2023-01-01", form="10-Q", val=-100.0 * _M),
            _entry("2023-06-30", "2023-04-01", form="10-Q", val=-110.0 * _M),
            _entry("2023-06-30", "2023-01-01", form="10-Q", val=-210.0 * _M),
            _entry("2023-09-30", "2023-07-01", form="10-Q", val=-120.0 * _M),
            _entry("2023-12-31", "2023-01-01", form="10-K", val=-450.0 * _M),
        ]
        facts = _facts(
            [
                ("us-gaap", "ResearchAndDevelopmentExpense", "USD", entries),
                (
                    "us-gaap",
                    "Assets",
                    "USD",
                    [
                        _entry("2023-03-31", form="10-Q"),
                        _entry("2023-06-30", form="10-Q"),
                        _entry("2023-09-30", form="10-Q"),
                        _entry("2023-12-31", form="10-K"),
                    ],
                ),
            ]
        )
        quarterly = schema.extract(
            {"facts": facts}, "income_statement", frequency="quarterly"
        )
        rd = next(r for r in quarterly.rows if r.tag == "rd_expense")
        assert [rd.values[d] for d in sorted(rd.values)] == [
            100.0 * _M,
            110.0 * _M,
            120.0 * _M,
            120.0 * _M,
        ]
        annual = schema.extract(
            {"facts": facts}, "income_statement", frequency="annual"
        )
        rd = next(r for r in annual.rows if r.tag == "rd_expense")
        assert rd.values["2023-12-31"] == 450.0 * _M

    def test_net_position_depreciation_negative_not_taken(self, schema):
        facts = _facts(
            [
                (
                    "us-gaap",
                    "DepreciationDepletionAndAmortization",
                    "USD",
                    [
                        _entry(
                            "2022-12-31",
                            "2022-01-01",
                            filed="2023-02-15",
                            val=-500.0 * _M,
                        ),
                        _entry(
                            "2022-12-31",
                            "2022-01-01",
                            filed="2024-06-15",
                            val=500.0 * _M,
                        ),
                        _entry("2023-03-31", "2023-01-01", form="10-Q", val=100.0 * _M),
                        _entry(
                            "2023-06-30", "2023-01-01", form="10-Q", val=-210.0 * _M
                        ),
                    ],
                ),
            ]
        )
        annual = schema.extract(
            {"facts": facts}, "income_statement", frequency="annual"
        )
        da = next(r for r in annual.rows if r.tag == "depreciation_and_amortization")
        assert da.values["2022-12-31"] == 500.0 * _M
        quarterly = schema.extract(
            {"facts": facts}, "income_statement", frequency="quarterly"
        )
        da = next(r for r in quarterly.rows if r.tag == "depreciation_and_amortization")
        assert da.values["2023-03-31"] == 100.0 * _M
        assert "2023-06-30" not in da.values

    def test_eop_stale_filing_recovered_via_instant_fallback(self, schema):
        # The EOP tag's only filing is stale (filed > 450 days after the
        # period end) so compute_ref_filings excludes it from the shared ref
        # map; the instant fallback in extract_row_values still recovers the
        # value via min(filings). Exercises the cash_flow EOP/BOP wiring with
        # a ref map driven by a separate (non-stale) operating-activity tag.
        op = "NetCashProvidedByUsedInOperatingActivities"
        eop = "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
        facts = _facts(
            [
                # Operating activity (non-stale) anchors both years' ref map.
                (
                    "us-gaap",
                    op,
                    "USD",
                    [
                        _entry(
                            "2022-12-31",
                            "2022-01-01",
                            form="10-K",
                            filed="2023-02-15",
                            val=400.0 * _M,
                        ),
                        _entry(
                            "2023-12-31",
                            "2023-01-01",
                            form="10-K",
                            filed="2024-02-15",
                            val=500.0 * _M,
                        ),
                    ],
                ),
                # EOP cash for 2023 filed > 450 days late -> dropped from the
                # shared ref map but recoverable standalone.
                (
                    "us-gaap",
                    eop,
                    "USD",
                    [
                        _entry(
                            "2023-12-31",
                            form="10-K",
                            filed="2025-06-01",
                            val=1200.0 * _M,
                        )
                    ],
                ),
                (
                    "us-gaap",
                    "Assets",
                    "USD",
                    [
                        _entry("2022-12-31", form="10-K", filed="2023-02-15"),
                        _entry("2023-12-31", form="10-K", filed="2024-02-15"),
                    ],
                ),
            ]
        )
        res = schema.extract({"facts": facts}, "cash_flow", frequency="annual")
        eop_row = next((r for r in res.rows if r.tag == "cash_at_end_of_period"), None)
        # The stale 2023 EOP was backfilled via the standalone extraction.
        assert eop_row is not None
        assert eop_row.values.get("2023-12-31") == 1200.0 * _M

    def test_eop_standalone_backfill_when_date_absent_from_ref_map(self, schema):
        # A date present in ``filing_dates`` but absent from the supplied
        # ``ref_filed_map`` is skipped by the main per-row extraction (ref_filed
        # resolves to None), so the standalone EOP backfill (lines 342-345)
        # recovers the value straight from the instant fact.
        eop = "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
        facts = _facts(
            [
                (
                    "us-gaap",
                    eop,
                    "USD",
                    [_entry("2023-12-31", form="10-K", val=1200.0 * _M)],
                )
            ]
        )
        res = schema.extract(
            {"facts": facts},
            "cash_flow",
            frequency="annual",
            filing_dates={"2023-12-31"},
            ref_filed_map={},
        )
        eop_row = next(r for r in res.rows if r.tag == "cash_at_end_of_period")
        assert eop_row.values["2023-12-31"] == 1200.0 * _M
        assert "CashCashEquivalents" in eop_row.sources["2023-12-31"]


class TestSchemaQuarterlyFiscalYearEnd:
    def test_fiscal_year_end_kept_when_income_statement_lacks_it(self, schema):
        m = 1_000_000
        quarters = ("2023-03-31", "2023-06-30", "2023-09-30")
        instants = ("2022-12-31", *quarters, "2023-12-31")
        facts_json = {
            "entityName": "Shifted Quarter Inc.",
            "facts": _facts(
                [
                    (
                        "us-gaap",
                        "Assets",
                        "USD",
                        [
                            _entry(d, form="10-K" if d.endswith("12-31") else "10-Q")
                            for d in instants
                        ],
                    ),
                    (
                        "us-gaap",
                        "CashAndCashEquivalentsAtCarryingValue",
                        "USD",
                        [
                            _entry(
                                d,
                                form="10-K" if d.endswith("12-31") else "10-Q",
                                val=10.0 * m,
                            )
                            for d in instants
                        ],
                    ),
                    (
                        "us-gaap",
                        "Revenues",
                        "USD",
                        [
                            _entry("2022-12-31", "2022-01-01", val=800.0 * m),
                            _entry("2023-12-31", "2023-01-01", val=1000.0 * m),
                            _entry(
                                "2023-03-31",
                                "2023-01-01",
                                form="10-Q",
                                fp="Q1",
                                val=200.0 * m,
                            ),
                            _entry(
                                "2023-04-01",
                                "2023-01-02",
                                form="10-Q",
                                fp="Q1",
                                filed="2024-05-10",
                                val=200.0 * m,
                            ),
                            _entry(
                                "2023-06-30",
                                "2023-04-01",
                                form="10-Q",
                                fp="Q2",
                                val=250.0 * m,
                            ),
                            _entry(
                                "2023-09-30",
                                "2023-07-01",
                                form="10-Q",
                                fp="Q3",
                                val=300.0 * m,
                            ),
                        ],
                    ),
                ]
            ),
        }
        results = schema.extract_all(facts_json, frequency="quarterly")
        income = results["income_statement"]
        assert "2023-12-31" in income.dates
        revenue = next(r for r in income.rows if r.tag == "total_revenue")
        assert revenue.values["2023-12-31"] == 250.0 * m


class TestSchemaExtractAllErrors:
    def test_quarterly_no_dates_generic_error(self, schema):
        # A plain 10-K filer (not 20-F/40-F) with no interim data yields no
        # quarterly filing dates and is not "annual-only" by form, so
        # extract_all raises the generic no-quarterly OpenBBError (line 493).
        from openbb_core.app.model.abstract.error import OpenBBError

        facts_json = {
            "entityName": "Domestic Annual Inc.",
            "facts": _facts(
                [
                    ("us-gaap", "Assets", "USD", [_entry("2023-12-31", form="10-K")]),
                    (
                        "us-gaap",
                        "Revenues",
                        "USD",
                        [_entry("2023-12-31", "2023-01-01", form="10-K")],
                    ),
                ]
            ),
        }
        with pytest.raises(OpenBBError, match="No quarterly filing dates"):
            schema.extract_all(facts_json, frequency="quarterly")


class TestSchemaMergeFactsMetadata:
    def test_merge_carries_label_and_description(self, schema):
        # merge_facts copies label/description from the first source that has
        # them (line 617-621).
        a = {
            "facts": {
                "us-gaap": {
                    "Assets": {
                        "label": "Total Assets",
                        "description": "Sum of assets.",
                        "units": {"USD": [_entry("2022-12-31", val=1.0)]},
                    }
                }
            }
        }
        b = {
            "facts": {
                "us-gaap": {
                    "Assets": {
                        "label": "Ignored",
                        "units": {"USD": [_entry("2023-12-31", val=2.0)]},
                    }
                }
            }
        }
        merged = schema.merge_facts(a, b)
        assert merged["us-gaap"]["Assets"]["label"] == "Total Assets"
        assert merged["us-gaap"]["Assets"]["description"] == "Sum of assets."
        assert len(merged["us-gaap"]["Assets"]["units"]["USD"]) == 2
