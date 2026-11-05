import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from _load import FIX, load

facts = load("trader-analyst", "facts")
DIR = os.path.join(FIX, "trader-analyst")


def companyfacts(cik):
    with open(os.path.join(DIR, "companyfacts-CIK%s.json" % cik)) as fh:
        return json.load(fh)


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = facts.main(args)
    return code, out.getvalue(), err.getvalue()


class Apple(unittest.TestCase):
    def setUp(self):
        self.r = facts.analyse(companyfacts("0000320193"), quarters=8)

    def test_latest_quarter(self):
        q = self.r["rows"][0]
        self.assertEqual(q["end"], "2026-06-27")
        self.assertEqual(q["fiscal"], "Q3 2026")
        self.assertEqual(q["revenue"], 109417000000)
        self.assertEqual(q["net_income"], 29789000000)
        self.assertEqual(q["eps_diluted"], 2.02)
        self.assertEqual(q["revenue_yoy"], 16.4)    # vs 94,036 a year earlier
        self.assertEqual(q["eps_yoy"], 28.7)        # vs 1.57
        self.assertEqual(q["gross_margin"], 50.1)
        self.assertEqual(q["operating_margin"], 32.6)
        self.assertEqual(q["net_margin"], 27.2)
        self.assertFalse(q["derived"])

    def test_fiscal_labels_come_from_the_first_filing(self):
        labels = [r["fiscal"] for r in self.r["rows"][:6]]
        self.assertEqual(labels, ["Q3 2026", "Q2 2026", "Q1 2026", "Q4 2025", "Q3 2025", "Q2 2025"])

    def test_q4_is_derived_from_the_10k(self):
        q4 = next(r for r in self.r["rows"] if r["end"] == "2025-09-27")
        self.assertTrue(q4["derived"])
        # FY2025 416,161 minus Q1 124,300, Q2 95,359, Q3 94,036
        self.assertEqual(q4["revenue"], 102466000000)
        self.assertEqual(q4["revenue_yoy"], 7.9)

    def test_trailing_twelve_months(self):
        self.assertEqual(self.r["ttm"]["revenue"], 466823000000)
        self.assertEqual(self.r["ttm"]["net_income"], 128930000000)
        self.assertEqual(self.r["ttm"]["eps_diluted"], 8.71)

    def test_what_changed_in_words(self):
        lines = facts.changes(self.r)
        self.assertIn("revenue $109.42B (+16.4% vs a year earlier)", lines[0])
        self.assertIn("diluted EPS $2.02 (+28.7%)", lines[0])
        self.assertTrue(any(l.startswith("Gross margin 50.1% (+0.8 points") for l in lines))

    def test_restated_values_win_but_labels_stay(self):
        facts_ = [
            {"start": "2025-01-01", "end": "2025-03-31", "val": 100, "fy": 2025, "fp": "Q1",
             "form": "10-Q", "filed": "2025-05-01", "accn": "a"},
            {"start": "2025-01-01", "end": "2025-03-31", "val": 90, "fy": 2026, "fp": "Q1",
             "form": "10-Q", "filed": "2026-05-01", "accn": "b"},
            {"start": "2025-01-01", "end": "2025-03-31", "val": 1, "fy": 2025, "fp": "Q1",
             "form": "8-K", "filed": "2025-04-20", "accn": "c"},
        ]
        q = facts.quarterly(facts_)
        self.assertEqual(q["2025-03-31"]["value"], 90)
        self.assertEqual((q["2025-03-31"]["fy"], q["2025-03-31"]["fp"]), (2025, "Q1"))


class Filings(unittest.TestCase):
    def test_latest_10q_and_earnings_press_release(self):
        with open(os.path.join(DIR, "submissions-CIK0000320193.json")) as fh:
            sub = json.load(fh)
        f = facts.latest_filings(sub, "0000320193", facts.Fetcher(offline=DIR))
        self.assertEqual(f["report"]["form"], "10-Q")
        self.assertEqual(f["report"]["period"], "2026-06-27")
        self.assertTrue(f["report"]["url"].endswith("/000032019326000020/aapl-20260627.htm"))
        e = f["earnings_8k"]
        self.assertEqual(e["filed"], "2026-07-30")
        self.assertEqual(e["exhibit"], "https://www.sec.gov/Archives/edgar/data/320193/"
                                       "000032019326000018/a8-kex991q3202606272026.htm")

    def test_exhibit_names_seen_on_edgar(self):
        pick = facts.exhibit_name
        self.assertEqual(pick(["axp-20260724.htm", "q226exhibit991.htm", "q226exhibit992.htm",
                               "R1.htm"], "axp-20260724.htm"), "q226exhibit991.htm")
        self.assertEqual(pick(["goog-20260722.htm", "googexhibit991q22026.htm"],
                              "goog-20260722.htm"), "googexhibit991q22026.htm")
        self.assertEqual(pick(["a2026q2earningsreleaseex-9.htm", "ko-20260728.htm"],
                              "ko-20260728.htm"), "a2026q2earningsreleaseex-9.htm")
        self.assertEqual(pick(["bac-06302026ex993.htm", "bac-06302026ex991.htm"]),
                         "bac-06302026ex991.htm")
        self.assertIsNone(pick(["only-8k.htm"], "only-8k.htm"))


class LaggingData(unittest.TestCase):
    def test_says_when_sec_facts_trail_a_filed_10q(self):
        code, out, err = run(["KO", "--offline", DIR])
        self.assertEqual(code, 0, err)
        self.assertIn("COCA COLA CO (KO)", out)
        self.assertIn("NOTE: SEC's XBRL facts stop at 2026-04-03, but a 10-Q for the period "
                      "ending 2026-07-03 was filed 2026-07-29", out)

    def test_one_offs_are_flagged(self):
        result = {"rows": [
            {"end": "2026-06-30", "derived": False, "revenue": 100.0, "net_income": 90.0,
             "operating_income": 30.0, "eps_diluted": 1.0, "revenue_yoy": 10.0,
             "net_income_yoy": 200.0, "eps_yoy": 200.0, "gross_margin": None,
             "operating_margin": 30.0, "net_margin": 90.0}]}
        self.assertTrue(any("above operating income" in l for l in facts.changes(result)))


class Cli(unittest.TestCase):
    def test_metrics_file_for_the_screener(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "trader", "metrics.json")
            code, out, err = run(["AAPL", "KO", "--offline", DIR, "--metrics", path])
            self.assertEqual(code, 0, err)
            with open(path) as fh:
                data = json.load(fh)
        rows = {r["ticker"]: r for r in data["companies"]}
        self.assertEqual(sorted(rows), ["AAPL", "KO"])
        self.assertEqual(rows["AAPL"]["eps_ttm"], 8.71)
        self.assertEqual(rows["AAPL"]["revenue_growth_yoy"], 16.4)
        self.assertEqual(rows["KO"]["period_end"], "2026-04-03")
        self.assertIn("wrote", out)
        self.assertNotIn(chr(0x2014), out)

    def test_unknown_ticker_and_no_user_agent(self):
        code, _, err = run(["ZZZZ", "--offline", DIR])
        self.assertEqual(code, 2)
        self.assertIn("no SEC CIK for ZZZZ", err)
        old = os.environ.pop("SEC_USER_AGENT", None)
        try:
            code, _, err = run(["AAPL", "--config", "/nonexistent.json"])
            self.assertEqual(code, 2)
            self.assertIn("User-Agent", err)
            self.assertIsNone(facts.user_agent("Your Name you@example.com"))
        finally:
            if old is not None:
                os.environ["SEC_USER_AGENT"] = old

    def test_json_output(self):
        code, out, err = run(["AAPL", "--offline", DIR, "--json", "--quarters", "4"])
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(len(data[0]["result"]["rows"]), 4)
        self.assertEqual(data[0]["result"]["concepts"]["revenue"],
                         ["RevenueFromContractWithCustomerExcludingAssessedTax"])


if __name__ == "__main__":
    unittest.main()
