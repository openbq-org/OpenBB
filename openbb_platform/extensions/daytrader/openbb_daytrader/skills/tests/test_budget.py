import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, ROOT, FIX

size = load("trader-budget", "size")

CFG = os.path.join(ROOT, "trader-budget", "config.example.json")
PLAN = os.path.join(FIX, "trader-budget", "plan-tsla.json")
TARGETS = os.path.join(ROOT, "trader-budget", "targets.example.json")
TOP5 = os.path.join(FIX, "trader-budget", "berkshire-q2-2026-top5.json")
NOW = "2026-10-19 10:15"
TODAY = "2026-10-19"
REEL_V1 = {"AAPL": 1250, "AXP": 1119, "GOOGL": 823, "KO": 708, "BAC": 600}
PRICES = {"AAPL": 341.27, "AXP": 309.84, "GOOGL": 353.78, "KO": 90.11, "BAC": 53.96}
# the contract's v2 config, key for key
CONTRACT_CFG = {
    "budget": 5000, "cash_buffer_pct": 10, "max_position_pct": 75, "max_order_usd": 4000, "min_order_usd": 5,
    "max_loss_per_trade_usd": 50, "max_daily_loss_usd": 150, "max_trades_per_day": 3, "max_orders_per_day": 10,
    "min_reward_risk": 1.0, "require_stop": True,
    "no_entries_before": "09:45", "no_entries_after": "15:30", "flat_by": "15:55",
    "fractional": False, "broker": "alpaca", "paper": True, "blocked": [],
    "allow_options": False, "allow_margin": False, "allow_short": False, "pdt_guard": False,
    "sec_user_agent": "Your Name you@example.com",
}
# v1's rules, for the weights mode tests
V1 = {"budget": 5000, "cash_buffer_pct": 10, "max_position_pct": 25, "max_order_usd": 2000, "min_order_usd": 5,
      "fractional": True, "paper": True, "blocked": []}


def cfg(**over):
    with open(CFG) as fh:
        c = json.load(fh)
    c.update(over)
    return c


def v1(**over):
    c = dict(V1)
    c.update(over)
    return c


def plan(**over):
    with open(PLAN) as fh:
        p = json.load(fh)
    p.update(over)
    return p


def rows(path):
    with open(path) as fh:
        return size.parse_weights(json.load(fh))


def dollars(result):
    return {p["ticker"]: p["dollars"] for p in result["positions"]}


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = size.main(argv)
    return code, out.getvalue(), err.getvalue()


def prices_doc(price, quote_time="2026-10-19T14:52:13Z"):
    return {"as_of": quote_time, "source": "yahoo", "prices": {"TSLA": price},
            "detail": {"TSLA": {"prev_close": 354.72, "time": quote_time, "source": "yahoo"}}}


class TheReel(unittest.TestCase):
    """$5,000, 10% buffer, $50 max loss, TSLA risk 5.86 -> 8 shares, $2,913.44, max loss $46.88."""

    def test_config_example_is_the_contract(self):
        with open(CFG) as fh:
            self.assertEqual(json.load(fh), CONTRACT_CFG)

    def test_tsla_is_8_shares_bound_by_the_max_loss(self):
        s = size.size_trade(plan(), cfg(), today=TODAY)
        self.assertEqual(s["qty"], 8)
        self.assertEqual(s["bound_by"], "max loss")
        self.assertEqual(s["risk_per_share"], 5.86)
        self.assertEqual(s["cost"], 2913.44)
        self.assertEqual(s["max_loss"], 46.88)
        self.assertEqual(s["reward_risk"], 1.0)
        self.assertEqual(s["cash_buffer"], 500)
        self.assertEqual([(l["name"], l["shares"]) for l in s["limits"]],
                         [("max loss", 8), ("position cap", 10), ("max order", 10), ("cash", 12)])
        self.assertEqual([l["name"] for l in s["limits"] if l["binds"]], ["max loss"])
        self.assertIsNone(s["refusal"])

    def test_the_bracket_order(self):
        o = size.bracket_order(size.size_trade(plan(), cfg(), today=TODAY))
        why = o.pop("why")
        self.assertEqual(o, {
            "symbol": "TSLA", "side": "buy", "qty": "8", "type": "market", "time_in_force": "day",
            "order_class": "bracket", "take_profit_limit_price": "370.04", "stop_loss_stop_price": "358.32",
            "plan": {"entry": 364.18, "stop": 358.32, "target": 370.04, "risk_per_share": 5.86,
                     "max_loss": 46.88, "setup": "orb", "entry_time": "10:15 AM", "flat_by": "15:55"}})
        self.assertIn("bound by your $50 max loss", why)
        self.assertIn("$46.88", why)

    def test_the_fixture_orders_file_is_what_it_writes(self):
        with open(os.path.join(FIX, "trader-risk", "orders-tsla.json")) as fh:
            fixture = json.load(fh)["orders"][0]
        self.assertEqual(size.bracket_order(size.size_trade(plan(), cfg(), today=TODAY)), fixture)

    def test_a_limit_order(self):
        o = size.bracket_order(size.size_trade(plan(), cfg(), limit=364.18, today=TODAY))
        self.assertEqual((o["type"], o["limit_price"], o["qty"]), ("limit", "364.18", "8"))
        s = size.size_trade(plan(), cfg(), limit=364.00, today=TODAY)
        self.assertEqual((s["risk_per_share"], s["qty"], s["max_loss"]), (5.68, 8, 45.44))
        self.assertEqual(size.bracket_order(s)["limit_price"], "364.00")

    def test_cli_writes_one_bracket_order(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "trader", "orders.json")
            code, text, _ = run(["--plan", PLAN, "--config", CFG, "--portfolio", os.path.join(d, "none"),
                                 "--now", NOW, "--write", out])
            self.assertEqual(code, 0)
            self.assertIn("Size: 8 shares of TSLA = $2,913.44 at 364.18", text)
            self.assertIn("8 x 5.86 = $46.88", text)
            self.assertIn("<- binds", text)
            self.assertIn("not financial advice", text)
            with open(out) as fh:
                doc = json.load(fh)
            self.assertEqual(doc["status"], "proposed")
            self.assertIs(doc["paper"], True)
            self.assertEqual(doc["created_at"], "2026-10-19T14:15:00Z")
            self.assertEqual(len(doc["orders"]), 1)
            self.assertEqual(doc["orders"][0]["plan"]["max_loss"], 46.88)

    def test_cli_json_and_limit(self):
        code, text, _ = run(["--plan", PLAN, "--config", CFG, "--portfolio", "/nonexistent", "--now", NOW,
                             "--limit", "--json"])
        self.assertEqual(code, 0)
        out = json.loads(text)
        self.assertEqual(out["sizing"]["qty"], 8)
        self.assertEqual(out["orders"][0]["limit_price"], "364.18")


class PlanRules(unittest.TestCase):
    def test_zero_shares_is_a_plain_refusal(self):
        s = size.size_trade(plan(stop=300.0), cfg(), today=TODAY)
        self.assertEqual(s["qty"], 0)
        self.assertIn("more than your $50 max loss per trade", s["refusal"])
        self.assertIsNone(size.bracket_order(s))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "plan.json")
            with open(p, "w") as fh:
                json.dump(plan(stop=300.0), fh)
            out = os.path.join(d, "orders.json")
            code, text, _ = run(["--plan", p, "--config", CFG, "--portfolio", os.path.join(d, "none"),
                                 "--now", NOW, "--write", out])
            self.assertEqual(code, 1)
            self.assertIn("No order:", text)
            self.assertFalse(os.path.exists(out))

    def test_each_limit_can_bind(self):
        self.assertEqual(size.size_trade(plan(), cfg(max_order_usd=1000), today=TODAY)["bound_by"], "max order")
        s = size.size_trade(plan(), cfg(max_position_pct=20), today=TODAY)
        self.assertEqual((s["qty"], s["bound_by"]), (2, "position cap"))
        s = size.size_trade(plan(), cfg(), cash=1200, today=TODAY)
        self.assertEqual((s["qty"], s["bound_by"], s["cash_available"]), (1, "cash", 700))
        s = size.size_trade(plan(), cfg(max_loss_per_trade_usd=100), today=TODAY)
        self.assertEqual((s["qty"], s["bound_by"]), (10, "position cap"))

    def test_a_fresh_higher_price_means_a_bigger_risk(self):
        s = size.size_trade(plan(), cfg(min_reward_risk=0), price=366.475, today=TODAY)
        self.assertEqual((s["entry"], s["entry_from"], s["risk_per_share"]), (366.48, "price", 8.16))
        self.assertEqual((s["qty"], s["max_loss"], s["reward_risk"]), (6, 48.96, 0.44))
        self.assertIsNone(s["refusal"])
        s = size.size_trade(plan(), cfg(), price=366.475, today=TODAY)
        self.assertIn("reward:risk 0.44 (target 370.04, entry 366.48, stop 358.32) is under your minimum 1",
                      s["refusal"])
        self.assertIsNone(size.bracket_order(s))
        lower = size.size_trade(plan(), cfg(), price=363.00, today=TODAY)
        self.assertEqual((lower["entry"], lower["qty"]), (364.18, 8))

    def test_prices_file_is_used_only_when_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            pp = os.path.join(d, "prices.json")
            with open(pp, "w") as fh:
                json.dump(prices_doc(366.475), fh)
            base = ["--plan", PLAN, "--config", CFG, "--portfolio", os.path.join(d, "none"), "--prices", pp, "--json"]
            code, text, _ = run(base + ["--now", "2026-10-19 10:55"])
            out = json.loads(text)
            self.assertEqual((code, out["sizing"]["qty"], out["orders"]), (1, 6, []))
            self.assertIn("above the plan's entry", out["notes"][0])
            out = json.loads(run(base + ["--now", "2026-10-19 11:30"])[1])
            self.assertEqual(out["sizing"]["qty"], 8)
            self.assertIn("not used", out["notes"][0])

    def test_the_portfolio_cash_caps_the_size(self):
        with tempfile.TemporaryDirectory() as d:
            pf = os.path.join(d, "portfolio.json")
            with open(pf, "w") as fh:
                json.dump({"cash": 1200, "positions": []}, fh)
            out = json.loads(run(["--plan", PLAN, "--config", CFG, "--portfolio", pf, "--now", NOW, "--json"])[1])
            self.assertEqual((out["sizing"]["qty"], out["sizing"]["bound_by"]), (1, "cash"))

    def test_bad_plans(self):
        for p, word in ((plan(stop=365.0), "not below the entry"),
                        (plan(target=360.0), "already happened"),
                        (plan(target=None), "positive target"),
                        (plan(side="sell"), "long (buy) day trades only"),
                        (plan(symbol=""), "no symbol")):
            with self.assertRaises(size.SizeError) as e:
                size.size_trade(p, cfg(), today=TODAY)
            self.assertIn(word, str(e.exception))
        with self.assertRaises(size.SizeError) as e:
            size.size_trade(plan(), cfg(), price=371.00, today=TODAY)
        self.assertIn("already happened", str(e.exception))
        with self.assertRaises(size.SizeError) as e:
            size.size_trade(plan(), cfg(blocked=["tsla"]), today=TODAY)
        self.assertIn("blocked list", str(e.exception))
        with self.assertRaises(size.SizeError) as e:
            size.size_trade(plan(), cfg(), today="2026-10-20")
        self.assertIn("make a new plan", str(e.exception))

    def test_under_the_minimum_order(self):
        cheap = plan(symbol="ABC", entry=4.0, stop=3.0, target=5.0)
        s = size.size_trade(cheap, cfg(max_loss_per_trade_usd=1), today=TODAY)
        self.assertEqual(s["qty"], 1)
        self.assertIn("under your $5 minimum order", s["refusal"])
        self.assertIsNone(size.bracket_order(s))

    def test_missing_plan_and_weights_only_flags(self):
        code, _, err = run(["--plan", "/nonexistent/plan.json", "--config", CFG, "--now", NOW])
        self.assertEqual(code, 1)
        self.assertIn("no plan", err)
        code, _, err = run(["--plan", PLAN, "--config", CFG, "--now", NOW, "--top", "2"])
        self.assertEqual(code, 1)
        self.assertIn("--weights", err)
        code, _, err = run(["--plan", PLAN, "--config", CFG, "--now", "tomorrow"])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)


class WeightsMode(unittest.TestCase):
    """v1's split, kept behind --weights / --targets: $5,000, 10% cash, 25% cap."""

    def check_reel(self, r):
        self.assertEqual(dollars(r), REEL_V1)
        self.assertEqual(r["cash_buffer"], 500)
        self.assertEqual(r["invested"], 4500)
        self.assertEqual(r["idle"], 0)
        self.assertEqual(r["cap"], 1250)
        self.assertEqual([p["ticker"] for p in r["positions"] if p["capped"]], ["AAPL"])

    def test_from_the_raw_weights(self):
        self.check_reel(size.size(rows(TOP5), v1()))

    def test_from_the_renormalised_weights_file(self):
        self.check_reel(size.size(rows(TARGETS), v1()))

    def test_from_inline_weights(self):
        w = size.parse_weights(size.weights_from_arg("AAPL=22.04,AXP=17.14,GOOGL=12.62,KO=10.86,BAC=9.20"))
        self.check_reel(size.size(w, v1()))

    def test_renormalised_weights(self):
        r = size.size(rows(TOP5), v1())
        shown = {p["ticker"]: round(p["weight"], 1) for p in r["positions"]}
        self.assertEqual(shown, {"AAPL": 30.7, "AXP": 23.9, "GOOGL": 17.6, "KO": 15.1, "BAC": 12.8})

    def test_one_decimal_weights_stay_within_a_dollar(self):
        w = size.parse_weights({"AAPL": 30.7, "AXP": 23.9, "GOOGL": 17.6, "KO": 15.1, "BAC": 12.8})
        r = size.size(w, v1())
        self.assertEqual(r["invested"], 4500)
        self.assertEqual(dollars(r)["AAPL"], 1250)
        for t, v in dollars(r).items():
            self.assertLessEqual(abs(v - REEL_V1[t]), 1.0, t)

    def test_orders_are_place_stock_order_shaped(self):
        r = size.size(rows(TOP5), v1())
        orders = size.orders_from(r, "a 13F")
        self.assertEqual(orders[0], {"symbol": "AAPL", "side": "buy", "notional": "1250", "type": "market",
                                     "time_in_force": "day", "why": orders[0]["why"]})
        self.assertIn("capped at 25%", orders[0]["why"])
        for o in orders:
            self.assertIsInstance(o["notional"], str)
            self.assertNotIn("qty", o)
        self.assertEqual([o["notional"] for o in orders], ["1250", "1119", "823", "708", "600"])

    def test_cents_mode_keeps_the_total(self):
        r = size.size(rows(TOP5), v1(), cents=True)
        d = dollars(r)
        self.assertEqual(d["AAPL"], 1250)
        self.assertAlmostEqual(sum(d.values()), 4500, places=2)
        self.assertAlmostEqual(d["AXP"], 1118.13, places=2)
        self.assertEqual(size.orders_from(r)[1]["notional"], "1118.13")

    def test_cap_redistributes_until_nobody_is_over(self):
        w = size.parse_weights({"A": 60, "B": 30, "C": 10})
        r = size.size(w, {"budget": 1000, "cash_buffer_pct": 0, "max_position_pct": 40, "min_order_usd": 1})
        self.assertEqual(dollars(r), {"A": 400, "B": 400, "C": 200})
        self.assertEqual(sorted(p["ticker"] for p in r["positions"] if p["capped"]), ["A", "B"])

    def test_everything_capped_leaves_money_idle(self):
        w = size.parse_weights({"AAPL": 50, "KO": 50})
        r = size.size(w, v1())
        self.assertEqual(dollars(r), {"AAPL": 1250, "KO": 1250})
        self.assertEqual(r["idle"], 2000)
        self.assertIn("every stock is at its cap", size.report(r, size.orders_from(r)))

    def test_slices_under_the_minimum_are_dropped_and_shared_out(self):
        w = size.parse_weights({"A": 90, "B": 7, "C": 3})
        r = size.size(w, {"budget": 100, "cash_buffer_pct": 10, "max_position_pct": 100, "min_order_usd": 5})
        self.assertNotIn("C", dollars(r))
        self.assertEqual(sum(dollars(r).values()), 90)
        self.assertTrue(all(v >= 5 for v in dollars(r).values()))
        self.assertEqual(r["dropped"][0]["ticker"], "C")

    def test_blocked_tickers_are_dropped_first(self):
        r = size.size(rows(TOP5), v1(blocked=["ko"]))
        self.assertNotIn("KO", dollars(r))
        self.assertEqual(r["invested"], 4500)
        self.assertIn("blocked", r["dropped"][0]["reason"])

    def test_top_n(self):
        r = size.size(rows(TOP5), v1(max_position_pct=100), top=2)
        self.assertEqual(sorted(dollars(r)), ["AAPL", "AXP"])

    def test_whole_shares_need_prices(self):
        with self.assertRaises(size.SizeError):
            size.size(rows(TOP5), v1(fractional=False))
        with self.assertRaises(size.SizeError):
            size.size(rows(TOP5), cfg())          # the v2 example config is whole shares

    def test_whole_shares_with_prices(self):
        r = size.size(rows(TOP5), v1(fractional=False), prices=PRICES)
        self.assertTrue(r["whole_shares"])
        for p in r["positions"]:
            self.assertEqual(p["shares"], int(p["shares"]))
            self.assertAlmostEqual(p["dollars"], p["shares"] * PRICES[p["ticker"]], places=2)
            self.assertLessEqual(p["dollars"], 1250)
        self.assertAlmostEqual(r["invested"] + r["idle"], 4500, places=2)
        self.assertLess(r["idle"], min(PRICES.values()) * 2)
        orders = size.orders_from(r)
        self.assertTrue(all("qty" in o and "notional" not in o for o in orders))

    def test_no_budget_and_duplicates_are_errors(self):
        with self.assertRaises(size.SizeError):
            size.size(rows(TOP5), {"cash_buffer_pct": 10})
        with self.assertRaises(size.SizeError):
            size.size([{"ticker": "KO", "name": "", "weight": 1}, {"ticker": "KO", "name": "", "weight": 2}], v1())

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            c = os.path.join(d, "config.json")
            with open(c, "w") as fh:
                json.dump(v1(), fh)
            out = os.path.join(d, "trader", "orders.json")
            code, text, _ = run(["--targets", TARGETS, "--config", c, "--write", out])
            self.assertEqual(code, 0)
            self.assertIn("left idle", text)
            self.assertIn("require_stop", text)
            with open(out) as fh:
                doc = json.load(fh)
            self.assertEqual([o["symbol"] for o in doc["orders"]], ["AAPL", "AXP", "GOOGL", "KO", "BAC"])
            code, text, _ = run(["--targets", TARGETS, "--config", c, "--json"])
            self.assertEqual(json.loads(text)["result"]["idle"], 0)
            code, _, err = run(["--targets", "/nonexistent/targets.json", "--config", c])
            self.assertEqual(code, 1)
            self.assertIn("no weights file", err)


if __name__ == "__main__":
    unittest.main()
