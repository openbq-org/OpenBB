import datetime
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from _load import FIX, load

news = load("trader-news", "news")
DIR = os.path.join(FIX, "trader-news")
NOW = "2026-10-14T00:00:00+00:00"


def raw(name):
    with open(os.path.join(DIR, name), "rb") as fh:
        return fh.read()


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = news.main(args)
    return code, out.getvalue(), err.getvalue()


class Feeds(unittest.TestCase):
    def test_yahoo_rss(self):
        items = news.parse_rss(raw("yahoo-AAPL.xml"), "AAPL")
        self.assertEqual(len(items), 6)
        first = items[0]
        self.assertEqual(first["title"], "Apple may have a way to dominate the smart home space")
        self.assertEqual(first["time"], datetime.datetime(2026, 10, 13, 19, 46, 52,
                                                          tzinfo=datetime.timezone.utc))
        self.assertTrue(first["link"].startswith("https://finance.yahoo.com/"))
        self.assertTrue(first["id"].startswith("rss:"))

    def test_sec_atom_8k(self):
        items = news.parse_sec_atom(raw("sec-8-K-0000320193.xml"), "AAPL")
        self.assertEqual([i["form"] for i in items], ["8-K/A", "8-K", "8-K"])
        earn = items[1]
        self.assertEqual(earn["items"], ["2.02", "9.01"])
        self.assertTrue(earn["important"])
        self.assertEqual(earn["title"], "Apple Inc. filed a 8-K: earnings results")
        self.assertEqual(earn["id"], "sec:0000320193-26-000018")
        self.assertIn("000032019326000018", earn["link"])
        # 16:30:28 New York time is 20:30:28 UTC
        self.assertEqual(earn["time"].isoformat(), "2026-07-30T20:30:28+00:00")
        self.assertEqual(items[0]["title"], "Apple Inc. filed a 8-K/A: director or officer change")

    def test_times(self):
        self.assertEqual(news.parse_time("Tue, 13 Oct 2026 20:02:03 +0000").hour, 20)
        self.assertEqual(news.parse_time("2026-09-01T16:30:35-04:00").hour, 20)
        self.assertIsNone(news.parse_time("soon"))

    def test_yahoo_symbols(self):
        self.assertEqual(news.yahoo_symbol("BRK.B"), "BRK-B")


class Tagging(unittest.TestCase):
    def test_touches_and_tags(self):
        items = news.parse_rss(raw("yahoo-KO.xml"), "KO")
        watch = {"KO": "Coca-Cola", "CVX": "Chevron", "AAPL": "Apple"}
        news.tag(items, watch)
        by = {i["title"][:20]: i for i in items}
        chevron = by["Coca-Cola or Chevron"]
        self.assertEqual(chevron["touches"], ["CVX", "KO"])
        self.assertIn("capital", chevron["tags"])  # dividend
        self.assertEqual(by["Is Coca-Cola (KO) St"]["touches"], ["KO"])

    def test_earnings_filings_are_tagged(self):
        items = news.tag(news.parse_sec_atom(raw("sec-8-K-0000021344.xml"), "KO"), {"KO": None})
        self.assertEqual(items[0]["tags"][0], "earnings")
        self.assertFalse(items[1]["important"])  # 8.01 other events

    def test_dedupe_merges_the_same_story(self):
        a = news.parse_rss(raw("yahoo-AAPL.xml"), "AAPL")
        b = news.parse_rss(raw("yahoo-AAPL.xml"), "GOOGL")
        items = news.dedupe(news.tag(a + b, {"AAPL": None, "GOOGL": None}))
        self.assertEqual(len(items), 6)
        self.assertEqual(items[0]["touches"], ["AAPL", "GOOGL"])


class Check(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "state", "news.json")
        self.base = ["--offline", DIR, "--state", self.state, "--now", NOW,
                     "--portfolio", os.path.join(self.tmp.name, "none.json"),
                     "--watchlist", os.path.join(self.tmp.name, "none.json"),
                     "--plan", os.path.join(self.tmp.name, "none.json")]

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_items_once_newest_first(self):
        code, out, err = run(["--tickers", "AAPL", "KO", "--hours", "24", "--json"] + self.base)
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        times = [i["time"] for i in data["items"]]
        self.assertEqual(times, sorted(times, reverse=True))
        self.assertEqual(len(data["items"]), 10)  # 6 Apple + 4 Coca-Cola headlines, filings are older
        code, out, _ = run(["--tickers", "AAPL", "KO", "--hours", "24"] + self.base)
        self.assertEqual(code, 1)
        self.assertIn("Nothing new.", out)

    def test_filings_show_in_a_wider_window(self):
        code, out, err = run(["--tickers", "AAPL", "--hours", "2400"] + self.base)
        self.assertEqual(code, 0, err)
        self.assertIn("! 2026-07-30 16:30 ET  AAPL", out)  # 20:30 UTC, New York time
        self.assertIn("earnings results", out)
        self.assertIn("Not financial advice", out)
        self.assertNotIn(chr(0x2014), out)

    def test_tickers_from_watchlist_and_plan(self):
        wl = os.path.join(self.tmp.name, "watchlist.json")
        with open(wl, "w") as fh:
            json.dump({"created_by": "trader-scanner", "hits": [{"symbol": "KO", "setups": ["orb"]}]}, fh)
        plan = os.path.join(self.tmp.name, "plan.json")
        with open(plan, "w") as fh:
            json.dump({"created_by": "trader-exit", "symbol": "AAPL"}, fh)
        self.assertEqual(sorted(news.watch_from_files("/nonexistent.json", wl, plan)), ["AAPL", "KO"])
        args = list(self.base)
        args[args.index("--watchlist") + 1] = wl
        code, out, err = run(["--json", "--dry-run", "--hours", "24"] + args)
        self.assertEqual(code, 0, err)
        tickers = {t for i in json.loads(out)["items"] for t in i["touches"]}
        self.assertEqual(tickers, {"KO"})
        self.assertFalse(os.path.exists(self.state))

    def test_no_tickers_is_an_error(self):
        code, _, err = run(self.base)
        self.assertEqual(code, 2)
        self.assertIn("no tickers", err)

    def test_sec_needs_a_user_agent(self):
        old = os.environ.pop("SEC_USER_AGENT", None)
        try:
            self.assertIsNone(news.sec_user_agent(None, "/nonexistent.json"))
            self.assertIsNone(news.sec_user_agent("Your Name you@example.com"))
            self.assertEqual(news.sec_user_agent("Ada ada@example.org"), "Ada ada@example.org")
            with self.assertRaises(news.NewsError):
                news.Fetcher(None).get("https://www.sec.gov/x", "x", sec=True)
        finally:
            if old is not None:
                os.environ["SEC_USER_AGENT"] = old

    def test_the_reel_tsla_morning(self):
        # The reel's real feed: Yahoo Finance headlines for TSLA, Monday Oct 19 2026, checked at 10:15 AM ET
        code, out, err = run(["--tickers", "TSLA", "--hours", "6", "--no-sec", "--no-moves",
                              "--now", "2026-10-19T10:15:00-04:00"] + self.base[:4])
        self.assertEqual(code, 0, err)
        self.assertIn("2026-10-19 08:04 ET  TSLA", out)
        self.assertNotIn("10:32 ET", out)  # published after the pinned 10:15 clock
        self.assertIn("Tesla-SpaceX Merger Mania Strikes Wall Street Ahead of Earnings", out)
        merger = [l for l in out.splitlines() if "Merger Mania" in l]
        tags = out.splitlines()[out.splitlines().index(merger[0]) + 1]
        self.assertIn("earnings", tags)
        self.assertIn("deal", tags)
        self.assertIn("Checked 2026-10-19 10:15 ET", out)
        self.assertEqual(len([l for l in out.splitlines() if l.startswith("  2026-10-19")]), 16)  # 18 in the feed, 2 after 10:15
        # the price line, from the chart fetched at 10:52
        code, out, err = run(["--tickers", "TSLA", "--hours", "6", "--no-sec", "--dry-run",
                              "--now", "2026-10-19T10:52:00-04:00"] + self.base[:4])
        self.assertRegex(out, r"TSLA\s+366\.4[78] \+3\.31% vs yesterday's close 354\.72 at 10:52 ET  MOVING")

    def test_moves(self):
        m = news.parse_chart(raw("chart-TSLA.json"), "TSLA")
        self.assertEqual(m["prev_close"], 354.72)
        self.assertEqual(m["pct"], 3.31)
        self.assertEqual(news.to_eastern(m["time"]).strftime("%H:%M"), "10:52")
        quiet = dict(m, pct=1.2)
        self.assertNotIn("MOVING", news.render_moves([quiet])[0])
        self.assertIn("MOVING", news.render_moves([quiet], move_pct=1.0)[0])
        with self.assertRaises(news.NewsError):
            news.parse_chart(b'{"chart": {"result": null}}', "ZZZZ")
        # no chart file offline: no move line, no error note
        code, out, _ = run(["--tickers", "KO", "--hours", "24", "--dry-run"] + self.base)
        self.assertNotIn("vs yesterday's close", out)
        self.assertNotIn("note:", out)

    def test_new_york_time_follows_daylight_saving(self):
        utc = datetime.datetime(2026, 1, 15, 15, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(news.to_eastern(utc).hour, 10)  # EST, UTC-5
        utc = datetime.datetime(2026, 10, 19, 14, 15, tzinfo=datetime.timezone.utc)
        self.assertEqual(news.to_eastern(utc).hour, 10)  # EDT, UTC-4
        utc = datetime.datetime(2026, 11, 1, 6, 30)       # 1:30 EST, just after the switch back
        self.assertEqual(news.to_eastern(utc).hour, 1)

    def test_day_trading_tags(self):
        items = [{"id": "x", "source": "Yahoo Finance", "kind": "headline", "ticker": "TSLA",
                  "title": "Trading halted in XYZ after FDA approval; futures rise before CPI",
                  "summary": "", "link": "", "time": None}]
        tags = news.tag(items, {"TSLA": None})[0]["tags"]
        for t in ("halt", "regulatory", "macro"):
            self.assertIn(t, tags)

    def test_state_forgets_after_30_days(self):
        state = {"seen": {"old": "2026-08-01T00:00:00+00:00"}}
        now = news.parse_time(NOW)
        news.remember([], state, now)
        self.assertNotIn("old", state["seen"])
        self.assertEqual(state["last_check"], now.isoformat())


if __name__ == "__main__":
    unittest.main()
