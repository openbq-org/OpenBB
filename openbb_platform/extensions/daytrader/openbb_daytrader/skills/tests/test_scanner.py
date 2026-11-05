import datetime
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

scan = load("trader-scanner", "scan")

SDIR = os.path.join(FIX, "trader-scanner")
WALL = os.path.join(SDIR, "wall5m-2026-10-19.json.gz")       # 234 real 5-min charts, Oct 19 2026
DAILY = os.path.join(SDIR, "daily-spark-2026-10-19.json")    # 19 real daily charts as one spark answer
LIVE = os.path.join(SDIR, "spark-3mo-live-2026-10-20.json")  # a real 20-symbol spark answer
SYMDIR = os.path.join(SDIR, "symdir")                        # trimmed Nasdaq Trader files of Oct 19
SPARK5 = os.path.join(SDIR, "spark-5m-live-2026-10-20-1001.json")  # real, fetched 10:01:47 AM ET Oct 20
TSLA5 = os.path.join(SDIR, "TSLA-5m-live-2026-10-20-1001.json")    # real v8, fetched with it
DT = datetime.datetime
D = datetime.date


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = scan.main(argv)
    return code, out.getvalue(), err.getvalue()


def ts(et_text):
    """New York wall-clock text -> unix seconds (through the tool's own DST rule)."""
    utc = scan.eastern_to_utc(DT.strptime(et_text, "%Y-%m-%d %H:%M:%S" if et_text.count(":") == 2
                                          else "%Y-%m-%d %H:%M"))
    return int((utc - DT(1970, 1, 1)).total_seconds())


def bars_series(day, closes, highs=None, lows=None, start="09:30", extra=None):
    """A v8-like series of 5-min bars from `start` on `day` (YYYY-MM-DD)."""
    t0 = DT.strptime(day + " " + start, "%Y-%m-%d %H:%M")
    t = [ts((t0 + datetime.timedelta(minutes=5 * i)).strftime("%Y-%m-%d %H:%M")) for i in range(len(closes))]
    s = {"t": t, "c": list(closes), "h": list(highs or [c + 0.1 if c is not None else None for c in closes]),
         "l": list(lows or [c - 0.1 if c is not None else None for c in closes]), "o": None,
         "v": [1000] * len(closes), "meta": {}}
    for when, c in (extra or []):
        s["t"].append(ts(when))
        for k in ("c", "h", "l"):
            s[k].append(c)
        s["v"].append(10)
    return s


class Universe(unittest.TestCase):
    def setUp(self):
        texts = {}
        for f in scan.NASDAQ_FILES:
            with open(os.path.join(SYMDIR, f), encoding="utf-8") as fh:
                texts[f] = fh.read()
        self.kept, self.counts, self.created = scan.build_universe(texts)
        self.rows = {}
        for f in scan.NASDAQ_FILES:
            rows, _ = scan.parse_symdir(texts[f])
            for r in rows:
                self.rows[(r.get("Symbol") or r.get("ACT Symbol"))] = r

    def why(self, sym):
        return scan.classify(self.rows[sym])

    def test_the_kept_list(self):
        self.assertEqual([s for s, _ in self.kept],
                         ["A", "AACG", "AACI", "AAPL", "AME", "AMX", "ARLP", "BEP", "BF.B", "BRK.B", "IRS",
                          "KO", "OBAI", "ORGO", "PFBC", "PRT", "TSLA"])
        self.assertEqual(self.counts["rows"], 36)
        self.assertEqual(self.created, "2026-10-19 10:01")
        self.assertEqual(dict(self.kept)["TSLA"], "Tesla, Inc. - Common Stock")

    def test_one_case_per_rule(self):
        cases = {
            "ZAZZT": "test issue", "ZZZTX": "test issue",           # 1. test issues
            "AAAP": "ETF", "SPY": "ETF",                            # 1. ETFs
            "ABR$D": "not a plain ticker",                          # 2. $ preferred
            "AAC.U": "unit / warrant / right suffix",               # 2. .U unit
            "AAC.W": "unit / warrant / right suffix",               # 2. .W warrant
            "AACIW": "warrant",                                     # 3. warrants
            "HAVAR": "unit or right",                               # 3. SPAC rights "Rights that convert..."
            "ATMP": "note",                                         # 3. an ETN with the ETF flag at N
            "GJH": "coupon", "EAI": "coupon",                       # 3. a % coupon (bonds too)
            "CDZIP": "depositary",                                  # 3. depositary shares that carry a preferred
            "AACIU": "unit", "ARCIU": "unit",                       # 5. "- Units", "- Unit"
            "AACPR": "right", "GENVR": "right",                     # 5. rights, contingent value rights
            "BHK": "bond",                                          # 5. a bond fund with no share wording
            "CHTRP": "preferred",                                   # 5. preferred stock
            "AAPL": "keep", "AACI": "keep", "AACG": "keep",         # 4. common, ordinary, ADS
            "PFBC": "keep", "OBAI": "keep",                         # 4. "Preferred Bank", "Our Bond": common stock
            "AMX": "keep", "IRS": "keep",                           # 4. ADS "the right to receive", Global depositary
            "ARLP": "keep", "BEP": "keep", "PRT": "keep",           # 4. partnership and trust units
            "BRK.B": "keep", "BF.B": "keep",                        # 2. one class letter after a dot
            "AME": "keep", "ORGO": "keep",                          # 6. plain names
        }
        for sym, want in cases.items():
            self.assertEqual(self.why(sym), want, sym)

    def test_nextshares_rule(self):
        row = {"Symbol": "ZXYZ", "Security Name": "Some Fund - NextShares", "Test Issue": "N",
               "ETF": "N", "NextShares": "Y"}
        self.assertEqual(scan.classify(row), "NextShares")

    def test_not_a_symbol_file(self):
        with self.assertRaises(scan.ScanError):
            scan.parse_symdir("<html>maintenance</html>")


class Time(unittest.TestCase):
    def test_dst_and_clock(self):
        self.assertEqual(scan.eastern_offset(DT(2026, 3, 8, 6, 59)), -5)
        self.assertEqual(scan.eastern_offset(DT(2026, 3, 8, 7, 0)), -4)
        self.assertEqual(scan.eastern_offset(DT(2026, 11, 1, 5, 59)), -4)
        self.assertEqual(scan.eastern_offset(DT(2026, 11, 1, 6, 0)), -5)
        self.assertEqual(scan.ts_to_eastern(1792416600), DT(2026, 10, 19, 9, 30))   # TSLA's first bar
        self.assertEqual(scan.ts_to_eastern(ts("2026-12-01 09:30")), DT(2026, 12, 1, 9, 30))
        self.assertEqual(scan.parse_now("2026-10-19 10:15"), DT(2026, 10, 19, 14, 15))
        self.assertEqual(scan.parse_now("2026-12-01 10:15"), DT(2026, 12, 1, 15, 15))
        self.assertEqual(scan.parse_now("2026-10-19T14:15:00Z"), DT(2026, 10, 19, 14, 15))
        self.assertEqual(scan.clock_label(DT(2026, 10, 19, 10, 15)), "10:15 AM")
        self.assertEqual(scan.clock_label(datetime.time(12, 5)), "12:05 PM")
        with self.assertRaises(scan.ScanError):
            scan.parse_now("tomorrow")
        with self.assertRaises(scan.ScanError):
            scan.parse_hhmm("25:00")


class Spark(unittest.TestCase):
    def test_a_real_spark_answer(self):
        with open(LIVE, encoding="utf-8") as fh:
            text = fh.read()
        wanted = {scan.to_yahoo(s): s for s in ["AAPL", "TSLA", "BRK.B", "ZZZZQX"]}
        data = scan.parse_spark(text, wanted)
        self.assertEqual(len(data), 19)            # 20 asked; Yahoo silently drops the made-up ZZZZQX
        self.assertNotIn("ZZZZQX", data)
        self.assertIn("BRK.B", data)               # BRK-B comes back as ours
        t = data["TSLA"]
        self.assertEqual(len(t["t"]), 65)
        self.assertIsNone(t["h"])                  # spark is closes only
        self.assertEqual(t["c"][-1], 368.06)
        self.assertEqual(t["meta"]["regularMarketVolume"], 38651173)
        self.assertEqual(data["AMC"]["meta"]["regularMarketPrice"], 2.98)
        closes = scan.daily_closes(t, scan.parse_now("2026-10-20 09:14"))
        self.assertEqual(closes[-1], (D(2026, 10, 19), 368.06))
        # the same answer read during Monday's session: Monday's bar is still in progress
        closes = scan.daily_closes(t, scan.parse_now("2026-10-19 12:00"))
        self.assertEqual(closes[-1][0], D(2026, 10, 16))

    def test_spark_errors(self):
        too_many = '{"spark":{"result":null,"error":{"code":"Bad Request",' \
                   '"description":"Number of symbols needs to be less than or equal to 20"}}}'
        with self.assertRaises(scan.ScanError) as cm:
            scan.parse_spark(too_many)
        self.assertIn("less than or equal to 20", str(cm.exception))
        self.assertEqual(scan.parse_spark('{"spark":{"result":[],"error":null}}'), {})
        with self.assertRaises(scan.ScanError):
            scan.parse_spark('{"chart":{}}')

    def test_urls(self):
        self.assertEqual(scan.spark_path(["BRK.B", "tsla"], "3mo", "1d"),
                         "/v7/finance/spark?symbols=BRK-B,TSLA&range=3mo&interval=1d")
        self.assertEqual(scan.chart_path("TSLA", "1d", "5m"), "/v8/finance/chart/TSLA?range=1d&interval=5m")


class Network(unittest.TestCase):
    """429s and 5xx without the network."""

    def setUp(self):
        self.calls, self.sleeps = [], []
        self._get, self._sleep = scan.http_get, scan.SLEEP
        scan.SLEEP = self.sleeps.append
        with open(LIVE, encoding="utf-8") as fh:
            self.body = fh.read()

    def tearDown(self):
        scan.http_get, scan.SLEEP = self._get, self._sleep

    def answers(self, codes):
        codes = list(codes)

        def fake(url, timeout=20):
            self.calls.append(url.split("/v")[0])
            code = codes.pop(0) if codes else 200
            if code != 200:
                raise urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(b""))
            return self.body
        scan.http_get = fake

    def test_429_falls_back_then_waits_once(self):
        self.answers([429, 429, 200])
        text = scan.yahoo_get("/v7/finance/spark?symbols=TSLA&range=3mo&interval=1d")
        self.assertEqual(text, self.body)
        self.assertEqual(self.calls, ["https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com",
                                      "https://query2.finance.yahoo.com"])
        self.assertEqual(self.sleeps, [scan.BACKOFF])

    def test_5xx_goes_to_query1_without_waiting(self):
        self.answers([503, 200])
        scan.yahoo_get("/v8/finance/chart/TSLA?range=1d&interval=5m")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.sleeps, [])

    def test_429_for_good_is_reported_as_partial(self):
        self.answers([200] + [429] * 10)
        syms = ["AAPL", "TSLA", "NVDA", "BRK.B", "AMC", "ZZZZQX", "MSFT", "AMZN", "META", "GOOGL", "PLTR", "AMD",
                "INTC", "F", "BAC", "KO", "PLUG", "SOFI", "RIVN", "LCID"] + ["X%02d" % i for i in range(20)]
        data, failed = scan.fetch_spark(syms, "3mo", "1d", 0.3)
        self.assertEqual(len(data), 19)
        self.assertEqual(failed["ZZZZQX"], "no data from Yahoo")
        self.assertEqual(len(failed), 21)
        self.assertIn("HTTP 429", failed["X00"])
        self.assertEqual(self.sleeps, [0.3, scan.BACKOFF])  # a pause between batches, one backoff
        hits, counts, _ = scan.scan_daily(data, syms, scan.parse_now("2026-10-20 09:14"), 5, 1000000)
        self.assertEqual(counts["requested"], 40)
        self.assertEqual(counts["fetched"], 19)

    def test_a_404_is_final(self):
        self.answers([404])
        with self.assertRaises(scan.ScanError):
            scan.yahoo_get("/v8/finance/chart/NOPE?range=1d&interval=5m")
        self.assertEqual(len(self.calls), 1)


class Daily(unittest.TestCase):
    # Hand-checked from the closes (see the numbers in the comments): through Fri Oct 16 2026.
    EXPECT = {
        "BLK": ["breakout_20d"],    # 1134.38 > 1120.78, the best close of the 20 before
        "CI": ["breakout_20d"],     # 302.30 > 298.81
        "XOM": ["breakout_20d"],    # 178.98 > 177.01
        "HD": ["breakout_20d"],     # 309.63 > 308.24
        "KO": ["breakout_20d"],     # 93.90 > 92.00 (a closing high; its intraday high was not taken out)
        "CCL": ["bull_flag"],       # up 18.4 % over the 10 sessions, last 5 closes in a 3.2 % range
        "RCL": ["bull_flag"],       # up 16.3 %, 2.6 % range
        "F": ["reclaim_ma20"],      # 12.31 under 12.41, then 12.43 over 12.37
        "JPM": ["reclaim_ma20"],    # 335.53 under 336.15, then 339.72 over 335.65
        "GE": ["reclaim_ma20"],     # 312.00 under 312.90, then 313.83 over 312.88
        "BAC": ["oversold"],        # RSI 24.0
        "PLUG": ["oversold"],       # RSI 21.0
        "MS": ["oversold"],         # RSI 25.5
        "RIVN": ["oversold"],       # RSI 22.7
        "PNC": ["oversold_bounce"],  # RSI 27.1 on Thursday, closed up Friday (214.94 -> 217.39), RSI 34.0
    }
    # The reel's refs/scan.py tags for the same charts (it used highs and lows): all reproduced.
    REEL = {"BLK": "breakout_20d", "CI": "breakout_20d", "XOM": "breakout_20d", "HD": "breakout_20d",
            "CCL": "bull_flag", "F": "reclaim_ma20", "JPM": "reclaim_ma20", "GE": "reclaim_ma20",
            "BAC": "oversold", "PLUG": "oversold", "MS": "oversold", "RIVN": "oversold"}

    def setUp(self):
        self.data, self.errors = scan.load_offline(DAILY)
        self.syms = sorted(self.data)

    def test_setups_before_the_open(self):
        self.assertEqual(len(self.syms), 19)
        hits, counts, last = scan.scan_daily(self.data, self.syms, scan.parse_now("2026-10-19 09:00"), 0, 0)
        self.assertEqual({h["symbol"]: h["setups"] for h in hits}, self.EXPECT)
        self.assertEqual(last, D(2026, 10, 16))
        self.assertEqual(counts, {"requested": 19, "fetched": 19, "illiquid": 0, "short": 0, "scanned": 19,
                                  "hits": 15})
        for sym, tag in self.REEL.items():
            self.assertIn(tag, self.EXPECT[sym], sym)
        blk = [h for h in hits if h["symbol"] == "BLK"][0]
        self.assertEqual((blk["price"], blk["rsi"], blk["close_date"]), (1134.38, 63.7, "2026-10-16"))

    def test_the_in_progress_bar_is_dropped(self):
        before = scan.scan_daily(self.data, self.syms, scan.parse_now("2026-10-19 09:00"), 0, 0)
        during = scan.scan_daily(self.data, self.syms, scan.parse_now("2026-10-19 10:50"), 0, 0)
        self.assertEqual(before, during)
        bars = scan.daily_closes(self.data["TSLA"], scan.parse_now("2026-10-19 15:59"))
        self.assertEqual(bars[-1], (D(2026, 10, 16), 354.7200012207031))
        bars = scan.daily_closes(self.data["TSLA"], scan.parse_now("2026-10-19 16:00"))
        self.assertEqual(bars[-1], (D(2026, 10, 19), 365.7950134277344))

    def test_half_day_bar_completes_at_one(self):
        s = {"t": [ts("2026-11-25 09:30"), ts("2026-11-27 09:30")], "c": [10.0, 11.0], "meta": {}}
        self.assertEqual(len(scan.daily_closes(s, scan.parse_now("2026-11-27 12:59"))), 1)
        self.assertEqual(len(scan.daily_closes(s, scan.parse_now("2026-11-27 13:00"))), 2)

    def test_liquidity_filter(self):
        # meta is Yahoo's as of 10:50 AM Monday, so the volume is the day's so far
        hits, counts, _ = scan.scan_daily(self.data, self.syms, scan.parse_now("2026-10-19 10:50"), 5, 1000000)
        self.assertEqual(sorted(h["symbol"] for h in hits), ["BAC", "CCL", "F", "JPM", "KO", "RIVN", "XOM"])
        self.assertEqual(counts["illiquid"], 8)     # PLUG under $5; BLK, CI, HD, RCL, GE, MS, PNC under 1M so far
        self.assertEqual(counts["scanned"], 11)

    def test_short_and_empty_charts(self):
        s = {"t": [ts("2026-10-%02d 09:30" % d) for d in range(1, 11)], "c": [10.0] * 10,
             "meta": {"regularMarketPrice": 10, "regularMarketVolume": 5000000}}
        hits, counts, last = scan.scan_daily({"X": s, "E": {"t": [], "c": [], "meta": {}}}, ["X", "E", "GONE"],
                                             scan.parse_now("2026-10-20 09:00"), 5, 1000000)
        self.assertEqual(hits, [])
        self.assertEqual((counts["fetched"], counts["short"], counts["illiquid"], counts["scanned"]), (2, 1, 1, 0))
        self.assertIsNone(last)

    def test_rsi_matches_the_reel_math(self):
        self.assertIsNone(scan.rsi([1.0] * 10))
        self.assertEqual(scan.rsi([float(x) for x in range(1, 40)]), 100.0)
        closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61,
                  46.28, 46.28]
        self.assertAlmostEqual(scan.rsi(closes), 70.46, places=1)  # Wilder's textbook example


class Orb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.errors = scan.load_offline(WALL)
        cls.syms = sorted(set(cls.data) | set(cls.errors))

    def scan_at(self, now, min_price=0, syms=None, or_minutes=15):
        day, cutoff = scan.orb_window(scan.parse_now(now), None, or_minutes, datetime.time(15, 30))
        return scan.scan_orb(self.data, syms or self.syms, day, cutoff, or_minutes, min_price, 0)

    def test_the_reel_scan_at_1015(self):
        hits, counts, failed = self.scan_at("2026-10-19 10:15")
        self.assertEqual(len(self.syms), 234)
        self.assertEqual(counts["scanned"], 231)          # usable charts
        self.assertEqual(len(hits), 42)
        self.assertEqual(self.errors, {"SQ": "no data for SQ: No data found, symbol may be delisted"})
        self.assertEqual(counts["unusable"], 2)            # WBD (no bars), PARA (missing bars)
        tsla = [h for h in hits if h["symbol"] == "TSLA"][0]
        self.assertEqual(tsla, {"symbol": "TSLA", "setups": ["orb"], "price": 364.18, "at": "10:15 AM",
                                "bar_start": "10:10", "bar_index": 8, "or_high": 362.18, "or_low": 354.47,
                                "pct_over": 0.55})
        self.assertEqual(hits[0]["symbol"], "AMC")         # sorted by time, then symbol
        self.assertEqual([h["at"] for h in hits], sorted([h["at"] for h in hits], key=lambda x: scan.parse_hhmm(
            x[:-3]).hour % 12 * 60 + int(x[-5:-3])))
        self.assertEqual(sum(1 for h in hits if h["at"] == "10:15 AM"), 11)
        lly = [h for h in hits if h["symbol"] == "LLY"][0]
        self.assertEqual((lly["price"], lly["or_high"], lly["pct_over"]), (1255.0, 1254.99, 0.0))

    def test_price_floor(self):
        hits, counts, _ = self.scan_at("2026-10-19 10:15", min_price=5)
        self.assertEqual(len(hits), 41)                    # AMC at $2.97 drops out
        self.assertEqual(counts["illiquid"], 9)
        self.assertNotIn("AMC", [h["symbol"] for h in hits])

    def test_in_progress_bar_and_no_breakout_yet(self):
        hits, _, _ = self.scan_at("2026-10-19 10:14", syms=["TSLA"])
        self.assertEqual(hits, [])                         # the 10:10 bar is not done until 10:15
        hits, _, _ = self.scan_at("2026-10-19 10:15", syms=["TSLA"])
        self.assertEqual(hits[0]["at"], "10:15 AM")

    def test_the_live_tick_is_dropped(self):
        s = self.data["TSLA"]
        self.assertEqual(scan.ts_to_eastern(s["t"][-1]), DT(2026, 10, 19, 10, 58, 7))   # off the grid
        bars = scan.session_bars(s, D(2026, 10, 19), DT(2026, 10, 19, 10, 59))
        self.assertEqual(len(bars), 17)                    # 9:30 to 10:50; 10:55 in progress, the tick dropped
        self.assertTrue(scan.usable(bars, D(2026, 10, 19), DT(2026, 10, 19, 10, 59), 3))
        hits, _, _ = self.scan_at("2026-10-19 11:00", syms=["TSLA"])
        self.assertEqual(hits[0]["price"], 364.18)         # still the first close above the range

    def test_stage_one_is_a_necessary_condition(self):
        day, cut = D(2026, 10, 19), DT(2026, 10, 19, 10, 15)
        for sym, s in self.data.items():
            bars = scan.session_bars(s, day, cut)
            if scan.usable(bars, day, cut, 3) and scan.orb_hit(bars, 3):
                self.assertTrue(scan.orb_candidate(bars, 3), sym)

    def test_confirm_uses_the_v8_highs(self):
        spark_like = {k: dict(v, h=None, l=None) for k, v in self.data.items()}  # closes only, like spark
        asked = []

        def confirm(sym):
            asked.append(sym)
            return self.data[sym]
        hits, counts, failed = scan.scan_orb(spark_like, self.syms, D(2026, 10, 19), DT(2026, 10, 19, 10, 15), 15,
                                             0, 0, confirm)
        self.assertEqual(len(hits), 42)
        self.assertEqual(counts["candidates"], len(asked))
        self.assertLess(len(asked), 231)                   # stage 1 skipped most charts

        def broken(sym):
            raise scan.ScanError("Yahoo answered HTTP 429 for /v8/finance/chart/%s" % sym)
        hits, counts, failed = scan.scan_orb(spark_like, ["TSLA", "KO"], D(2026, 10, 19),
                                             DT(2026, 10, 19, 10, 15), 15, 0, 0, broken)
        self.assertEqual(hits, [])
        self.assertIn("429", failed["TSLA"])

    def test_a_missing_bar_makes_a_chart_unusable(self):
        s = bars_series("2026-10-20", [10, 10.2, 10.1, None, 10.5, 10.6, 10.7, 10.8, 10.9])
        bars = scan.session_bars(s, D(2026, 10, 20), DT(2026, 10, 20, 10, 15))
        self.assertFalse(scan.usable(bars, D(2026, 10, 20), DT(2026, 10, 20, 10, 15), 3))

    def test_winter_time_half_day_and_a_30_minute_range(self):
        # Fri Nov 27 2026: standard time (UTC-5) and a 1:00 PM close
        closes = [100, 101, 100.5, 100.8, 101.2, 100.9, 101.5] + [101.0] * 40
        s = bars_series("2026-11-27", closes, highs=[c + 0.2 for c in closes])
        hits, counts, _ = scan.scan_orb({"X": s}, ["X"], D(2026, 11, 27), DT(2026, 11, 27, 12, 0), 30, 0, 0)
        self.assertEqual(counts["scanned"], 1)
        self.assertEqual(hits[0]["at"], "10:05 AM")         # range 9:30 to 10:00 (high 101.4), 10:00 bar 101.5
        self.assertEqual(hits[0]["or_high"], 101.4)
        bars = scan.session_bars(s, D(2026, 11, 27), DT(2026, 11, 27, 12, 59))
        self.assertEqual(scan.ts_to_eastern(s["t"][0]), DT(2026, 11, 27, 9, 30))
        self.assertEqual(len(bars), 41)                    # 9:30 to 12:50 done at 12:59; bars after 1:00 dropped
        with self.assertRaises(scan.ScanError) as cm:
            scan.orb_window(scan.parse_now("2026-11-27 13:10"), None, 15, datetime.time(15, 30))
        self.assertIn("closed at 1:00 PM", str(cm.exception))

    def test_window_messages(self):
        until = datetime.time(15, 30)

        def msg(now, at=None, until=until):
            with self.assertRaises(scan.ScanError) as cm:
                scan.orb_window(scan.parse_now(now), at, 15, until)
            return str(cm.exception)
        self.assertIn("weekend", msg("2026-10-17 10:15"))
        self.assertIn("Thanksgiving", msg("2026-11-26 10:15"))
        self.assertIn("Run orb again after 9:50 AM", msg("2026-10-19 09:40"))
        self.assertIn("Run orb again after 9:50 AM", msg("2026-10-19 09:47"))
        self.assertIn("expired", msg("2026-10-19 15:45"))
        self.assertIn("expired", msg("2026-10-19 11:30", until=datetime.time(11, 0)))
        self.assertIn("closed at 4:00 PM", msg("2026-10-19 16:30"))
        self.assertIn("later than now", msg("2026-10-19 10:00", at=datetime.time(10, 15)))
        self.assertIn("after the 4:00 PM close", msg("2026-10-19 17:00", at=datetime.time(16, 30)))
        self.assertEqual(scan.orb_window(scan.parse_now("2026-10-19 16:30"), datetime.time(10, 15), 15, until),
                         (D(2026, 10, 19), DT(2026, 10, 19, 10, 15)))
        self.assertEqual(scan.orb_window(scan.parse_now("2026-10-19 09:50"), None, 15, until)[1],
                         DT(2026, 10, 19, 9, 50))
        with self.assertRaises(scan.ScanError):
            scan.orb_window(scan.parse_now("2026-10-19 10:15"), None, 7, until)


class LiveFiveMinute(unittest.TestCase):
    """A real spark 5-minute answer and TSLA's v8 chart, fetched at 10:01:47 AM ET on Tue Oct 20 2026."""

    def setUp(self):
        with open(SPARK5, encoding="utf-8") as fh:
            self.spark = scan.parse_spark(fh.read())
        with open(TSLA5, encoding="utf-8") as fh:
            self.v8 = scan.parse_chart(fh.read(), "TSLA")
        self.now = scan.parse_now("2026-10-20T14:01:48Z")

    def test_in_progress_bar_and_live_tick_are_dropped(self):
        self.assertEqual(len(self.spark), 20)
        self.assertIn("BRK.B", self.spark)
        t = self.spark["TSLA"]
        self.assertEqual(len(t["t"]), 8)                   # 9:30 ... 10:00 (in progress) + the 10:01:47 tick
        self.assertEqual(scan.ts_to_eastern(t["t"][-1]), DT(2026, 10, 20, 10, 1, 47))
        day, cut = scan.orb_window(self.now, None, 15, datetime.time(15, 30))
        self.assertEqual(cut, DT(2026, 10, 20, 10, 1))
        bars = scan.session_bars(t, day, cut)
        self.assertEqual([b["start"].strftime("%H:%M") for b in bars], ["09:30", "09:35", "09:40", "09:45",
                                                                         "09:50", "09:55"])
        self.assertEqual(len(scan.session_bars(self.v8, day, cut)), 6)

    def test_tsla_broke_its_range_at_ten(self):
        day, cut = scan.orb_window(self.now, None, 15, datetime.time(15, 30))
        hits, counts, failed = scan.scan_orb(self.spark, ["TSLA", "AMC"], day, cut, 15, 5, 0, lambda s: self.v8)
        # range 9:30 to 9:45: high 370.49 (the 9:30 bar), low 363.64; the 9:55 bar closed 370.585
        self.assertEqual(hits, [{"symbol": "TSLA", "setups": ["orb"], "price": 370.58, "at": "10:00 AM",
                                 "bar_start": "09:55", "bar_index": 5, "or_high": 370.49, "or_low": 363.64,
                                 "pct_over": 0.03}])
        self.assertEqual(counts["illiquid"], 1)            # AMC under the $5 floor

    def test_stage_two_cap_takes_the_most_traded(self):
        data, _ = scan.load_offline(WALL)
        spark_like = {k: dict(v, h=None, l=None) for k, v in data.items()}
        asked = []

        def confirm(sym):
            asked.append(sym)
            return data[sym]
        day, cut = D(2026, 10, 19), DT(2026, 10, 19, 10, 15)
        hits, counts, _ = scan.scan_orb(spark_like, sorted(data), day, cut, 15, 0, 0, confirm, max_confirm=10)
        self.assertEqual((counts["confirmed"], counts["unconfirmed"]), (10, counts["candidates"] - 10))
        self.assertIn("TSLA", asked)                       # the most dollars traded by 10:15
        self.assertLessEqual(len(hits), 10)
        hits_all, _, _ = scan.scan_orb(spark_like, sorted(data), day, cut, 15, 0, 0, confirm, max_confirm=0)
        self.assertEqual(len(hits_all), 42)
        for h in hits:
            self.assertIn(h, hits_all)


class Cli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.t = os.path.join(self.d, "trader")
        self.wl = os.path.join(self.t, "watchlist.json")

    def tearDown(self):
        shutil.rmtree(self.d)

    def read(self, path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_universe_daily_orb_end_to_end(self):
        uni = os.path.join(self.t, "universe.txt")
        code, text, _ = run(["universe", "--offline", SYMDIR, "--out", uni])
        self.assertEqual(code, 0)
        self.assertIn("Kept 17 US-listed", text)
        with open(uni, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        self.assertEqual(len(lines), 17)
        self.assertIn("BRK.B|Berkshire Hathaway Inc. New Common Stock", lines)

        # daily over that universe with the fixture charts: only KO and TSLA are in both, so partial
        code, text, _ = run(["daily", "--universe", uni, "--offline", DAILY, "--now", "2026-10-19 09:00",
                             "--out", self.wl, "--min-volume", "0"])
        self.assertEqual(code, 0)
        self.assertIn("Fetched 2 of 17 charts (15 failed or had no data)", text)
        doc = self.read(self.wl)
        self.assertEqual((doc["mode"], doc["universe"], doc["scanned"], doc["failed"]), ("daily", 17, 2, 15))
        self.assertEqual(doc["hits"], [{"symbol": "KO", "setups": ["breakout_20d"], "price": 93.9,
                                        "close_date": "2026-10-16", "rsi": 75.3, "volume": 3680307}])
        self.assertEqual(doc["as_of"], "2026-10-16 close")

        # the reel's 10:15 scan
        code, text, _ = run(["orb", "--offline", WALL, "--now", "2026-10-19 10:15", "--min-price", "0",
                             "--out", self.wl])
        self.assertEqual(code, 0)
        self.assertIn("42 of 231 charts closed above their opening-range high by 10:15 AM", text)
        self.assertIn("10:15 AM  TSLA      $364.18  range 354.47 to 362.18  +0.55% over", text)
        self.assertIn("not a list of stocks to buy", text)
        doc = self.read(self.wl)
        self.assertEqual({k: doc[k] for k in ("created_by", "created_at", "mode", "as_of", "universe", "scanned",
                                              "source")},
                         {"created_by": "trader-scanner", "created_at": "2026-10-19T14:15:00Z", "mode": "orb",
                          "as_of": "2026-10-19 10:15 ET", "universe": 234, "scanned": 231, "source": "yahoo"})
        self.assertEqual(len(doc["hits"]), 42)
        self.assertIn({"symbol": "TSLA", "setups": ["orb"], "price": 364.18, "at": "10:15 AM", "bar_start": "10:10",
                       "bar_index": 8, "or_high": 362.18, "or_low": 354.47, "pct_over": 0.55}, doc["hits"])

        # the hits read back as a watchlist, with --at instead of --now
        code, text, _ = run(["orb", "--offline", WALL, "--at", "10:15", "--watchlist", self.wl, "--min-price", "0",
                             "--json", "--no-write"])
        self.assertEqual(code, 0)
        out = json.loads(text)
        self.assertEqual((out["universe"], out["scanned"], len(out["hits"])), (42, 42, 42))

    def test_partial_stage_two_is_said(self):
        """The networked path with a fake Yahoo that answers from the Oct 19 bundle."""
        bundle = json.loads(scan._read_maybe_gz(WALL))
        calls = []

        def get(path):
            calls.append(path)
            if path.startswith("/v7/finance/spark"):
                res = []
                for y in path.split("symbols=")[1].split("&")[0].split(","):
                    r = ((bundle.get(y.replace("-", ".")) or {}).get("chart") or {}).get("result")
                    if r:
                        closes = r[0]["indicators"]["quote"][0].get("close", [])
                        res.append({"symbol": y, "response": [dict(r[0], indicators={"quote": [{"close": closes}]})]})
                return json.dumps({"spark": {"result": res, "error": None}})
            return json.dumps(bundle[path.split("/chart/")[1].split("?")[0].replace("-", ".")])
        old_get, old_sleep, real_now = scan.yahoo_get, scan.SLEEP, scan.parse_now
        scan.yahoo_get, scan.SLEEP = get, (lambda s: None)
        scan.parse_now = lambda text: real_now(text or "2026-10-19 10:20")  # the machine clock, pinned
        uni = os.path.join(self.d, "u.txt")
        with open(uni, "w") as fh:
            fh.write("\n".join(sorted(bundle)) + "\n")
        try:
            code, text, _ = run(["orb", "--universe", uni, "--now", "2026-10-19 10:15", "--min-price", "0",
                                 "--max-confirm", "10", "--no-write"])
        finally:
            scan.yahoo_get, scan.SLEEP, scan.parse_now = old_get, old_sleep, real_now
        self.assertEqual(code, 0)
        self.assertIn("231 usable; 95 candidates, 10 confirmed", text)
        self.assertIn("PARTIAL: 85 more candidates were not checked", text)
        self.assertIn("5 of the 10 checked charts closed above their opening-range high by 10:15 AM", text)
        self.assertEqual(sum(1 for c in calls if c.startswith("/v8/")), 10)
        self.assertEqual(sum(1 for c in calls if c.startswith("/v7/")), 12)   # 234 symbols, 20 a request
        self.assertTrue(all("range=1d&interval=5m" in c for c in calls))

    def test_plain_messages_and_exit_codes(self):
        code, _, err = run(["orb", "--offline", WALL, "--now", "2026-10-17 10:15", "--out", self.wl])
        self.assertEqual(code, 1)
        self.assertIn("No session on Sat 2026-10-17 (weekend)", err)
        self.assertNotIn("Traceback", err)
        self.assertFalse(os.path.exists(self.wl))
        code, _, err = run(["orb", "--offline", WALL, "--now", "2026-10-19 09:44", "--out", self.wl])
        self.assertIn("after 9:50 AM", err)
        cfg = os.path.join(self.t, "config.json")
        os.makedirs(self.t)
        with open(cfg, "w") as fh:
            json.dump({"no_entries_after": "10:00"}, fh)
        code, _, err = run(["orb", "--offline", WALL, "--now", "2026-10-19 10:15", "--config", cfg])
        self.assertEqual(code, 1)
        self.assertIn("expired", err)
        code, _, err = run(["orb", "--offline", WALL])
        self.assertIn("--at HH:MM", err)
        code, text, _ = run(["orb", "--offline", WALL, "--now", "2026-10-19 10:10", "--symbols", "TSLA",
                             "--out", self.wl])
        self.assertEqual(code, 1)                          # no breakout yet, but the empty list is written
        self.assertIn("No chart closed above its opening-range high by 10:10 AM", text)
        self.assertEqual(self.read(self.wl)["hits"], [])
        code, _, err = run(["daily", "--universe", os.path.join(self.d, "nope.txt")])
        self.assertEqual(code, 1)
        self.assertIn("scan.py universe", err)
        code, _, err = run(["daily", "--offline", os.path.join(self.d, "nothing-here")])
        self.assertIn("no offline file", err)
        empty = os.path.join(self.d, "empty.json")
        with open(empty, "w") as fh:
            fh.write("{}")
        code, _, err = run(["daily", "--offline", empty])
        self.assertEqual(code, 1)
        self.assertIn("no symbols to scan", err)

    def test_offline_folder_of_v8_files(self):
        folder = os.path.join(self.d, "charts")
        os.makedirs(folder)
        data, _ = scan.load_offline(WALL)
        bundle = json.loads(scan._read_maybe_gz(WALL))
        for sym in ("TSLA", "AAPL", "KO", "SQ"):
            with open(os.path.join(folder, sym + ".json"), "w") as fh:
                json.dump(bundle[sym], fh)
        code, text, _ = run(["orb", "--offline", folder, "--now", "2026-10-19 10:15", "--no-write", "--json"])
        out = json.loads(text)
        self.assertEqual((out["universe"], out["scanned"], out["failed"]), (4, 3, 1))
        self.assertEqual([h["symbol"] for h in out["hits"]], ["AAPL", "TSLA"])
        self.assertEqual(code, 0)

    def test_symbol_lists(self):
        txt = os.path.join(self.d, "list.txt")
        with open(txt, "w") as fh:
            fh.write("# my list\nTSLA|Tesla, Inc. - Common Stock\nko\n\nTSLA\n")
        self.assertEqual(scan.symbols_from_file(txt), ["TSLA", "KO", "TSLA"])
        js = os.path.join(self.d, "wl.json")
        with open(js, "w") as fh:
            json.dump({"hits": [{"symbol": "tsla"}, {"symbol": "KO"}]}, fh)
        self.assertEqual(scan.symbols_from_file(js), ["TSLA", "KO"])
        code, text, _ = run(["daily", "--offline", DAILY, "--watchlist", txt, "--now", "2026-10-19 09:00",
                             "--json", "--no-write", "--min-volume", "0"])
        out = json.loads(text)
        self.assertEqual((out["universe"], out["scanned"]), (2, 2))
        code, text, _ = run(["daily", "--offline", DAILY, "--limit", "3", "--now", "2026-10-19 09:00", "--json",
                             "--no-write", "--min-volume", "0"])
        self.assertEqual(json.loads(text)["universe"], 3)

    def test_daily_json(self):
        code, text, _ = run(["daily", "--offline", DAILY, "--now", "2026-10-19 09:00", "--json", "--no-write",
                             "--min-volume", "0", "--min-price", "0"])
        self.assertEqual(code, 0)
        out = json.loads(text)
        self.assertEqual(len(out["hits"]), 15)
        self.assertEqual(out["note"], "A scan is a list of charts that match a rule, not a list of stocks to buy.")


if __name__ == "__main__":
    unittest.main()
