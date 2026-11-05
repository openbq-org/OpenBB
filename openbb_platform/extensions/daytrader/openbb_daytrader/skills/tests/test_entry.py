"""trader-entry tests. Fixtures in tests/fixtures/trader-entry/:

TSLA-2026-10-19-5m.json  TSLA's Oct 19 2026 five-minute bars, cut from the reel's
                         TSLA-60d5m.json (Yahoo chart JSON v8, fetched 10:49:45 ET).
                         It ends with the in-progress 10:45 bar and Yahoo's live tick
                         at 10:49:45. meta trimmed to one day, like a range=1d answer.
DEMO-1m-synthetic.json   SYNTHETIC one-minute bars (not market data): a wick above the
                         range high, a close AT the high, a null bar, a live tick.
"""

import copy
import datetime
import gzip
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX, ROOT

entry = load("trader-entry", "entry")

EDIR = os.path.join(FIX, "trader-entry")
TSLA = os.path.join(EDIR, "TSLA-2026-10-19-5m.json")
DEMO = os.path.join(EDIR, "DEMO-1m-synthetic.json")
OPEN_TS = 1792416600       # 2026-10-19 09:30 EDT
DT = datetime.datetime


def ny(text):
    return entry.parse_now(text)


def doc(path=TSLA):
    with open(path) as fh:
        return json.load(fh)


def chart(d=None, sym="TSLA"):
    return entry.parse_chart(json.dumps(d if d is not None else doc()), sym)


def at(text, d=None, **kw):
    return entry.evaluate(chart(d), ny(text), **kw)


def shift_to(d, day, edt):
    """The same session moved to another date: 9:30 New York is 13:30 UTC in EDT, 14:30 in EST."""
    d = copy.deepcopy(d)
    r = d["chart"]["result"][0]
    new_open = int((DT.combine(day, datetime.time(13 if edt else 14, 30)) - DT(1970, 1, 1)).total_seconds())
    delta = new_open - OPEN_TS
    r["timestamp"] = [t + delta for t in r["timestamp"]]
    r["meta"]["regularMarketTime"] += delta
    r["meta"]["timezone"] = "EDT" if edt else "EST"
    return d


def no_breakout(d=None):
    """Every bar after the range stays under the 362.18 high."""
    d = copy.deepcopy(d if d is not None else doc())
    q = d["chart"]["result"][0]["indicators"]["quote"][0]
    for i in range(3, len(q["close"])):
        q["close"][i] = min(q["close"][i], 362.00)
        q["high"][i] = min(q["high"][i], 362.10)
        q["open"][i] = min(q["open"][i], 362.00)
    return d


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = entry.main(argv)
    return code, out.getvalue(), err.getvalue()


class TheReel(unittest.TestCase):
    def test_triggers_at_1015_on_the_1010_bar(self):
        r = at("2026-10-19 10:15")
        self.assertEqual(r["status"], "triggered")
        self.assertEqual(r["opening_range"]["high"], 362.18)
        self.assertEqual(r["opening_range"]["low"], 354.47)
        self.assertEqual(r["opening_range"]["bars"], 3)
        t = r["trigger"]
        self.assertEqual(t["time"], "10:15 AM")
        self.assertEqual(t["bar_start"], "10:10")
        self.assertEqual(t["bar_index"], 8)
        self.assertEqual(t["price"], 364.18)
        self.assertEqual(t["close"], 364.1759948730469)
        self.assertEqual(t["pct_over"], 0.55)
        self.assertEqual(r["level"], 362.18)
        self.assertEqual(r["prev_close"], 354.72)

    def test_at_1012_the_1010_bar_is_still_forming(self):
        r = at("2026-10-19 10:12")
        self.assertEqual(r["status"], "waiting")
        self.assertIsNone(r["trigger"])
        self.assertEqual(r["last"]["bar_start"], "10:05")
        self.assertEqual(r["last"]["close"], 361.68)
        self.assertEqual(r["forming"]["bar_start"], "10:10")
        self.assertIn("$0.50 under the range high $362.18", r["reason"])
        self.assertEqual(at("2026-10-19 10:14:59")["status"], "waiting")

    def test_before_the_open_and_while_the_range_forms(self):
        r = at("2026-10-19 09:20")
        self.assertEqual((r["status"], r["phase"]), ("waiting", "pre-open"))
        r = at("2026-10-19 09:44")
        self.assertEqual((r["status"], r["phase"]), ("waiting", "forming"))
        self.assertEqual(r["opening_range"]["bars"], 2)
        self.assertFalse(r["opening_range"]["complete"])
        r = at("2026-10-19 09:46")
        self.assertEqual((r["status"], r["phase"]), ("waiting", "open"))
        self.assertEqual(r["opening_range"]["bars"], 3)

    def test_the_live_tick_and_the_in_progress_bar_are_dropped(self):
        c = chart()
        self.assertEqual(c["bars"][-1]["t"], 1792421385)          # 10:49:45 is in the file
        r = entry.evaluate(c, entry.utc_of(c["data_time"]))     # read as of the file's own time
        self.assertEqual(r["now"], "2026-10-19 10:49:45")
        self.assertEqual(r["_bars"][-1]["slot"], 14)               # the 10:40 bar
        self.assertEqual(r["forming"]["bar_start"], "10:45")
        self.assertEqual(r["bars_closed"], 15)
        # 10:50: closed by the clock, but Yahoo's last trade (10:49:45) is before its close
        r = at("2026-10-19 10:50")
        self.assertEqual(r["_bars"][-1]["slot"], 14)
        self.assertIn("Yahoo's last trade is 10:49:45", r["lag_note"])
        # a minute later with no newer trade it counts; the 10:49:45 tick never becomes a bar
        r = at("2026-10-19 10:51")
        self.assertEqual(r["_bars"][-1]["slot"], 15)
        self.assertEqual(r["bars_closed"], 16)
        self.assertTrue(all(b["t"] % 300 == 0 for b in r["_bars"]))

    def test_after_the_close_it_stays_triggered_and_says_it_is_late(self):
        r = at("2026-10-19 16:05")
        self.assertEqual((r["status"], r["phase"]), ("triggered", "after-close"))
        self.assertEqual(r["trigger"]["time"], "10:15 AM")
        text = "\n".join(entry.describe(r))
        self.assertIn("minutes ago", text)
        self.assertNotIn("This is the moment", text)


class Rules(unittest.TestCase):
    def test_volume_confirmation_moves_the_trigger(self):
        r = at("2026-10-19 10:49", min_volume_x=1)
        self.assertEqual(r["opening_range"]["avg_volume"], 1658945)
        t = r["trigger"]
        self.assertEqual((t["time"], t["bar_index"], t["price"]), ("10:35 AM", 12, 365.75))
        self.assertEqual(t["volume_x"], 7.98)
        r = at("2026-10-19 10:16", min_volume_x=1)
        self.assertEqual(r["status"], "waiting")
        self.assertIn("0.60x the range's volume, under your 1.00x", r["reason"])

    def test_level_setup(self):
        r = at("2026-10-19 10:30", setup="level", level=365.5)
        self.assertEqual(r["trigger"]["time"], "10:25 AM")
        self.assertEqual(r["trigger"]["bar_index"], 10)
        self.assertEqual(r["trigger"]["price"], 365.75)
        # a level under the open: the first eligible close is the 9:40 bar's, at 9:45 (no_entries_before)
        r = at("2026-10-19 10:30", setup="level", level=350)
        self.assertEqual((r["trigger"]["time"], r["trigger"]["bar_index"]), ("9:45 AM", 2))
        with self.assertRaises(entry.EntryError):
            at("2026-10-19 10:30", setup="level")

    def test_no_breakout_waits_then_expires_at_the_cutoff(self):
        d = no_breakout()
        r = at("2026-10-19 10:49", d)
        self.assertEqual(r["status"], "waiting")
        self.assertEqual(at("2026-10-19 15:29", d)["status"], "waiting")
        r = at("2026-10-19 15:30", d)
        self.assertEqual(r["status"], "expired")
        self.assertIn("by 15:30", r["reason"])
        self.assertEqual(at("2026-10-19 16:30", d)["phase"], "after-close")

    def test_the_bar_closing_at_the_cutoff_still_counts_when_yahoo_lags(self):
        d = no_breakout()
        r0 = d["chart"]["result"][0]
        keep = [i for i, t in enumerate(r0["timestamp"]) if t <= OPEN_TS + 14 * 300]   # live: up to the 10:40 bar
        r0["timestamp"] = [r0["timestamp"][i] for i in keep]
        q = r0["indicators"]["quote"][0]
        for k in q:
            q[k] = [q[k][i] for i in keep]
        r0["meta"]["regularMarketTime"] = OPEN_TS + 74 * 60 + 40                       # last trade 10:44:40
        cfg = {"no_entries_before": "09:45", "no_entries_after": "10:45"}
        r = at("2026-10-19 10:45:10", d, cfg=cfg)                           # the 10:40 bar closed by the clock only
        self.assertEqual(r["status"], "waiting")
        self.assertIn("Yahoo's last trade is 10:44:40", r["lag_note"])
        self.assertEqual(at("2026-10-19 10:46", d, cfg=cfg)["status"], "expired")

    def test_config_cutoff(self):
        cfg = {"no_entries_before": "09:45", "no_entries_after": "10:10"}
        r = at("2026-10-19 10:15", cfg=cfg)
        self.assertEqual(r["status"], "expired")
        cfg = {"no_entries_before": "10:20", "no_entries_after": "15:30"}
        r = at("2026-10-19 10:30", cfg=cfg)
        self.assertEqual(r["trigger"]["time"], "10:20 AM")       # the 10:15 bar, first to close at or after 10:20

    def test_bad_inputs(self):
        with self.assertRaises(entry.EntryError):
            at("2026-10-19 10:15", or_minutes=7)
        with self.assertRaises(entry.EntryError):
            at("2026-10-19 10:15", interval="15m")
        with self.assertRaises(entry.EntryError):
            entry.parse_now("tomorrow")
        with self.assertRaises(entry.EntryError):
            entry.parse_hhmm("25:00", "x")
        self.assertEqual(entry.parse_now("2026-10-19 10:15"), DT(2026, 10, 19, 14, 15))
        self.assertEqual(entry.parse_now("2026-10-19T14:15:00Z"), DT(2026, 10, 19, 14, 15))
        self.assertEqual(entry.parse_now("2026-10-19 10:15 ET"), DT(2026, 10, 19, 14, 15))

    def test_or_minutes_30(self):
        r = at("2026-10-19 10:49", or_minutes=30)
        self.assertEqual(r["opening_range"]["bars"], 6)
        self.assertEqual(r["opening_range"]["high"], 362.92)
        self.assertEqual(r["trigger"]["time"], "10:15 AM")


class OneMinute(unittest.TestCase):
    def c(self):
        return entry.parse_chart(json.dumps(doc(DEMO)), "DEMO")

    def test_wick_and_close_at_the_high_do_not_trigger(self):
        c = self.c()
        r = entry.evaluate(c, entry.utc_of(c["data_time"]), interval="1m")
        self.assertEqual(r["now"], "2026-10-19 10:06:30")
        self.assertEqual(r["opening_range"], {"high": 100.5, "low": 99.0, "minutes": 15, "bars": 15, "of": 15,
                                              "complete": True, "avg_volume": 10667})
        t = r["trigger"]
        self.assertEqual((t["time"], t["bar_start"], t["bar_index"], t["price"]), ("9:59 AM", "09:58", 28, 100.62))
        r = entry.evaluate(c, ny("2026-10-19 09:58:59"), interval="1m")
        self.assertEqual(r["status"], "waiting")
        self.assertEqual(r["forming"]["bar_start"], "09:58")
        self.assertEqual(r["last"]["close"], 100.5)             # the 9:57 bar closed AT the high

    def test_null_bar_tick_and_volume(self):
        c = self.c()
        r = entry.evaluate(c, entry.utc_of(c["data_time"]), interval="1m", min_volume_x=2)
        self.assertEqual((r["trigger"]["time"], r["trigger"]["bar_index"]), ("10:02 AM", 31))
        slots = [b["slot"] for b in r["_bars"]]
        self.assertNotIn(19, slots)                               # 9:49 came as nulls
        self.assertEqual(slots[-1], 35)                           # 10:06 still forming, 10:06:30 tick dropped
        self.assertEqual(r["forming"]["bar_start"], "10:06")

    def test_the_file_and_the_interval_must_agree(self):
        code, _, err = run(["check", "DEMO", "--offline", DEMO])
        self.assertEqual(code, 1)
        self.assertIn("1m bars, not 5m", err)


class Calendar(unittest.TestCase):
    def test_dst_both_sides(self):
        for day, edt in ((datetime.date(2026, 12, 7), False), (datetime.date(2026, 11, 2), False),
                         (datetime.date(2026, 10, 30), True), (datetime.date(2026, 3, 9), True)):
            d = shift_to(doc(), day, edt)
            r = entry.evaluate(chart(d), ny("%s 10:15" % day))
            self.assertEqual(r["status"], "triggered", day)
            self.assertEqual(r["trigger"]["time"], "10:15 AM", day)
            self.assertEqual(r["trigger"]["bar_index"], 8, day)
            self.assertEqual(entry.evaluate(chart(d), ny("%s 10:12" % day))["status"], "waiting", day)
        # Dec 7 at 10:15 New York is 15:15 UTC
        self.assertEqual(ny("2026-12-07 10:15"), DT(2026, 12, 7, 15, 15))

    def test_half_day_moves_the_cutoff_up(self):
        d = shift_to(no_breakout(), datetime.date(2026, 11, 27), False)
        r = entry.evaluate(chart(d), ny("2026-11-27 12:29"))
        self.assertEqual(r["status"], "waiting")
        self.assertEqual((r["closes"], r["no_entries_after"]), ("13:00", "12:30"))
        r = entry.evaluate(chart(d), ny("2026-11-27 12:30"))
        self.assertEqual(r["status"], "expired")
        self.assertIn("early close", r["reason"])
        r = entry.evaluate(chart(shift_to(doc(), datetime.date(2026, 11, 27), False)), ny("2026-11-27 10:15"))
        self.assertEqual(r["trigger"]["time"], "10:15 AM")
        self.assertIn("Early close today", "\n".join(entry.describe(r)))
        # a cutoff already before the early close stays put
        cfg = {"no_entries_before": "09:45", "no_entries_after": "12:00"}
        self.assertEqual(entry.evaluate(chart(d), ny("2026-11-27 11:00"), cfg=cfg)["no_entries_after"], "12:00")

    def test_weekend_holiday_and_empty_data(self):
        r = at("2026-10-17 10:30")
        self.assertEqual((r["status"], r["phase"]), ("no-data", "closed"))
        self.assertEqual(r["next_open"], "2026-10-19 09:30")
        r = at("2026-11-26 10:30")
        self.assertIn("Thanksgiving", r["reason"])
        empty = copy.deepcopy(doc())
        res = empty["chart"]["result"][0]
        del res["timestamp"]
        res["indicators"] = {"quote": [{}]}
        r = at("2026-10-19 10:15", empty)
        self.assertEqual((r["status"], r["phase"]), ("no-data", "open"))
        r = at("2026-10-20 10:15")                                # Yahoo sent yesterday's bars only
        self.assertEqual(r["status"], "no-data")
        self.assertFalse(at("2028-03-01 10:30")["calendar_known"])

    def test_yahoo_errors(self):
        bad = json.dumps({"chart": {"result": None, "error": {"code": "Not Found",
                                                              "description": "No data found, symbol may be delisted"}}})
        with self.assertRaises(entry.EntryError) as cm:
            entry.parse_chart(bad, "ZZZZ")
        self.assertIn("No data found", str(cm.exception))
        with self.assertRaises(entry.EntryError):
            entry.parse_chart("<html>", "TSLA")


class Network(unittest.TestCase):
    """Yahoo is never called: _open_url and _sleep are swapped for fakes."""

    def setUp(self):
        self.calls, self.sleeps = [], []
        self._open, self._sleep = entry._open_url, entry._sleep
        entry._sleep = lambda s: self.sleeps.append(s)
        with open(TSLA) as fh:
            self.body = fh.read()

    def tearDown(self):
        entry._open_url, entry._sleep = self._open, self._sleep

    def answers(self, *codes):
        seq = list(codes)

        def fake(url, timeout=20):
            self.calls.append(url)
            code = seq.pop(0)
            if code == 200:
                return self.body
            raise urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(b'{"chart":{"result":null,'
                                                                           b'"error":{"description":"No data found"}}}'))
        entry._open_url = fake

    def test_url_and_429_retry_once_after_a_pause(self):
        self.answers(429, 200)
        c = entry.get_chart("TSLA", "5m", datetime.date(2026, 10, 19), today=datetime.date(2026, 10, 19))
        self.assertEqual(len(c["bars"]), 17)
        self.assertEqual(self.calls, ["https://query2.finance.yahoo.com/v8/finance/chart/TSLA?range=1d&interval=5m"] * 2)
        self.assertEqual(self.sleeps, [entry.BACKOFF])

    def test_429_twice_falls_back_to_query1(self):
        self.answers(429, 429, 200)
        entry.get_chart("TSLA", "5m", datetime.date(2026, 10, 19), today=datetime.date(2026, 10, 19))
        self.assertEqual([u.split("/")[2] for u in self.calls],
                         ["query2.finance.yahoo.com", "query2.finance.yahoo.com", "query1.finance.yahoo.com"])

    def test_5xx_falls_back_without_waiting(self):
        self.answers(503, 200)
        entry.get_chart("TSLA", "5m", datetime.date(2026, 10, 19), today=datetime.date(2026, 10, 19))
        self.assertEqual(self.sleeps, [])
        self.assertIn("query1", self.calls[1])

    def test_still_busy_is_one_plain_error(self):
        self.answers(429, 429, 429, 429)
        code, out, err = run(["check", "TSLA", "--now", "2026-10-19 10:15"])
        self.assertEqual(code, 1)
        self.assertIn("HTTP 429", err)
        self.assertNotIn("Traceback", err)

    def test_unknown_ticker_404(self):
        self.answers(404)
        with self.assertRaises(entry.EntryError) as cm:
            entry.get_chart("ZZZZ", "5m", datetime.date(2026, 10, 19), today=datetime.date(2026, 10, 19))
        self.assertIn("No data found", str(cm.exception))

    def test_ranges_for_past_sessions(self):
        today = datetime.date(2026, 10, 20)
        self.assertEqual(entry.chart_range(today, today, "5m"), "1d")
        self.assertEqual(entry.chart_range(datetime.date(2026, 10, 19), today, "5m"), "5d")
        self.assertEqual(entry.chart_range(datetime.date(2026, 10, 1), today, "5m"), "1mo")
        self.assertEqual(entry.chart_range(datetime.date(2026, 8, 31), today, "5m"), "60d")
        with self.assertRaises(entry.EntryError):
            entry.chart_range(datetime.date(2026, 10, 1), today, "1m")
        self.assertIn("/chart/BRK-B?", entry.chart_path("brk.b", "1d", "5m"))


def live_provider(d, lag_until=None, calls=None):
    """Bars the way Yahoo serves them at `now`: closed bars final, the in-progress bar
    showing a spike to 363.00 (above the high, then it closes under), plus a live tick.
    lag_until: before this UTC time Yahoo's last trade lags 30 seconds behind."""
    base = chart(d)

    def provider(now):
        if calls is not None:
            calls.append(now)
        nts = entry.ts_of(now)
        lagging = lag_until is not None and now < lag_until
        data_ts = nts - 30 if lagging else nts
        bars = []
        for b in base["bars"]:
            if b["t"] % 300 or b["t"] > data_ts:
                continue
            b = dict(b)
            if b["t"] + 300 > data_ts:
                b["c"], b["h"] = 363.00, max(b["h"], 363.00)
            bars.append(b)
        if data_ts % 300:
            bars.append({"t": data_ts, "o": 363.0, "h": 363.0, "l": 363.0, "c": 363.0, "v": 0})
        return {"symbol": "TSLA", "meta": {}, "bars": bars, "prev_close": 354.72, "data_time": data_ts}
    return provider


class Watch(unittest.TestCase):
    OPTS = {"setup": "orb", "or_minutes": 15, "interval": "5m", "level": None, "min_volume_x": None, "cfg": None}

    def loop(self, provider, start, **kw):
        clock = entry.SimClock(ny(start))
        lines, fired = [], []
        code, res = entry.watch_loop(provider, clock.now, clock.sleep, lines.append, dict(self.OPTS),
                                     on_trigger=lambda r, now: fired.append((r, now)), **kw)
        return code, res, lines, fired, clock

    def test_fires_on_the_first_closed_bar_not_the_spike_in_progress(self):
        calls = []
        code, res, lines, fired, clock = self.loop(live_provider(doc(), calls=calls), "2026-10-19 10:07", every=60)
        self.assertEqual(code, 0)
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0][0]["trigger"]["time"], "10:15 AM")
        self.assertEqual(fired[0][0]["trigger"]["price"], 364.18)
        # it looked at 10:07 (10:05 bar spiking to 363 in progress) and at 10:10:02 (that bar closed 361.68)
        self.assertEqual([entry.to_eastern(c).strftime("%H:%M:%S") for c in calls], ["10:07:00", "10:10:02", "10:15:02"])
        text = "\n".join(lines)
        self.assertIn("10:05 bar  closed $361.68  $0.50 under $362.18", text)
        self.assertIn("10:10 bar  closed $364.18  TRIGGERED", text)
        self.assertEqual(text.count("TRIGGERED"), 1)

    def test_waits_for_yahoo_to_catch_up(self):
        lag = ny("2026-10-19 10:15:30")
        calls = []
        code, res, lines, fired, clock = self.loop(live_provider(doc(), lag_until=lag, calls=calls),
                                                   "2026-10-19 10:12", every=30)
        self.assertEqual(code, 0)
        times = [entry.to_eastern(c).strftime("%H:%M:%S") for c in calls]
        self.assertEqual(times, ["10:12:00", "10:15:02", "10:15:32"])   # 10:15:02: Yahoo still at 10:14:32
        self.assertEqual(fired[0][0]["trigger"]["time"], "10:15 AM")

    def test_from_before_the_open_prints_the_range_bar_by_bar(self):
        code, res, lines, fired, clock = self.loop(live_provider(doc()), "2026-10-19 09:00", every=30)
        self.assertEqual(code, 0)
        text = "\n".join(lines)
        self.assertIn("not open yet", lines[0])
        self.assertIn(" 9:40 bar  closed $360.39  opening range set: high $362.18, low $354.47", text)
        self.assertEqual(sum(1 for x in lines if " bar  closed " in x), 9)    # 9:30 ... 10:10, one line each

    def test_a_computer_that_dozes_off_catches_up_when_it_wakes(self):
        class Dozing(entry.SimClock):
            naps = 0

            def sleep(self, seconds):
                entry.SimClock.sleep(self, seconds)
                self.naps += 1
                if self.naps == 3:                      # the laptop sleeps for 17 minutes mid-wait
                    self.t += datetime.timedelta(minutes=17)
        clock = Dozing(ny("2026-10-19 09:46"))
        calls, lines = [], []
        code, res = entry.watch_loop(live_provider(doc(), calls=calls), clock.now, clock.sleep, lines.append,
                                     dict(self.OPTS), every=30)
        self.assertEqual(code, 0)
        times = [entry.to_eastern(c).strftime("%H:%M:%S") for c in calls]
        self.assertEqual(times[:2], ["09:46:00", "10:04:30"])   # straight after waking, not a long sleep later
        text = "\n".join(lines)
        for start in (" 9:45", " 9:50", " 9:55", "10:00"):
            self.assertIn(start + " bar  closed", text)          # the bars it slept through, one line each
        self.assertEqual(res["trigger"]["time"], "10:15 AM")

    def test_expires_and_until(self):
        code, res, lines, fired, clock = self.loop(live_provider(no_breakout()), "2026-10-19 15:00", every=300)
        self.assertEqual(code, 1)
        self.assertEqual(res["status"], "expired")
        self.assertEqual(fired, [])
        self.assertEqual(entry.to_eastern(clock.now()).strftime("%H:%M"), "15:30")
        until = DT(2026, 10, 19, 11, 0)
        code, res, lines, fired, clock = self.loop(live_provider(no_breakout()), "2026-10-19 10:30", every=300,
                                                   until=until)
        self.assertEqual(code, 1)
        self.assertIn("--until 11:00", lines[-1])

    def test_closed_day_and_repeated_errors(self):
        code, _, lines, _, _ = self.loop(live_provider(doc()), "2026-10-17 10:00")
        self.assertEqual(code, 1)
        self.assertIn("weekend", lines[0])

        def broken(now):
            raise entry.EntryError("Yahoo did not answer")
        code, _, lines, _, _ = self.loop(broken, "2026-10-19 10:00", every=30)
        self.assertEqual(code, 1)
        self.assertIn("Stopping after 5 failed reads", lines[-1])


class Cli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.d)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.d)

    def test_check_write_is_the_contract_shape(self):
        code, text, _ = run(["check", "TSLA", "--offline", TSLA, "--now", "2026-10-19 10:15", "--write"])
        self.assertEqual(code, 0)
        self.assertIn("TRIGGERED 10:15 AM at $364.18", text)
        self.assertIn("/trader-exit", text)
        with open(os.path.join("trader", "entry.json")) as fh:
            e = json.load(fh)
        want = {"created_by": "trader-entry", "symbol": "TSLA", "setup": "orb", "side": "buy", "date": "2026-10-19",
                "status": "triggered", "time": "10:15 AM", "bar_start": "10:10", "bar_index": 8, "price": 364.18,
                "level": 362.18, "interval": "5m", "opening_range": {"high": 362.18, "low": 354.47, "minutes": 15},
                "source": "yahoo", "checked_at": "2026-10-19T14:15:00Z"}
        for k, v in want.items():
            self.assertEqual(e[k], v, k)

    def test_check_waiting_json_and_exit_codes(self):
        code, text, _ = run(["check", "TSLA", "--offline", TSLA, "--now", "2026-10-19 10:12", "--json"])
        self.assertEqual(code, 1)
        r = json.loads(text)
        self.assertEqual(r["status"], "waiting")
        self.assertNotIn("_bars", r)
        code, text, _ = run(["check", "TSLA", "--offline", TSLA, "--now", "2026-10-19 10:12", "--write", "e.json"])
        with open("e.json") as fh:
            self.assertEqual(json.load(fh)["status"], "waiting")
        self.assertIn("still forming", text)

    def test_offline_gz_folder_and_mismatch(self):
        os.mkdir("charts")
        with open(TSLA, "rb") as src, gzip.open(os.path.join("charts", "TSLA.json.gz"), "wb") as dst:
            dst.write(src.read())
        code, text, _ = run(["check", "tsla", "--offline", "charts", "--now", "2026-10-19 10:15"])
        self.assertEqual(code, 0)
        code, _, err = run(["check", "NVDA", "--offline", TSLA])
        self.assertEqual(code, 1)
        self.assertIn("holds TSLA, not NVDA", err)

    def test_longs_only_and_flag_errors(self):
        code, _, err = run(["check", "TSLA", "--offline", TSLA, "--side", "short"])
        self.assertEqual(code, 1)
        self.assertIn("v2 plans longs only", err)
        code, _, err = run(["check", "TSLA", "--offline", TSLA, "--level", "300"])
        self.assertIn("--level is for --setup level", err)
        code, _, err = run(["check", "TSLA", "--offline", TSLA, "--setup", "level"])
        self.assertIn("needs --level", err)

    def test_config_is_read(self):
        os.mkdir("trader")
        with open(os.path.join("trader", "config.json"), "w") as fh:
            json.dump({"no_entries_after": "10:10"}, fh)
        code, text, _ = run(["check", "TSLA", "--offline", TSLA, "--now", "2026-10-19 10:15"])
        self.assertEqual(code, 1)
        self.assertIn("EXPIRED", text)
        with open(os.path.join("trader", "config.json"), "w") as fh:
            fh.write("{nope")
        code, _, err = run(["check", "TSLA", "--offline", TSLA])
        self.assertIn("not valid JSON", err)

    def test_watch_replays_the_file_and_writes_the_entry(self):
        code, text, _ = run(["watch", "TSLA", "--offline", TSLA, "--now", "2026-10-19 09:50", "--every", "30"])
        self.assertEqual(code, 0)
        self.assertIn("10:10 bar  closed $364.18  TRIGGERED", text)
        with open(os.path.join("trader", "entry.json")) as fh:
            self.assertEqual(json.load(fh)["bar_index"], 8)
        code, text, _ = run(["watch", "TSLA", "--offline", TSLA, "--now", "2026-10-19 09:50", "--until", "10:00",
                             "--out", "x.json"])
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists("x.json"))

    def test_watchlist(self):
        os.mkdir("charts")
        shutil.copy(TSLA, os.path.join("charts", "TSLA.json"))
        shutil.copy(DEMO, os.path.join("charts", "DEMO.json"))
        os.mkdir("trader")
        with open(os.path.join("trader", "watchlist.json"), "w") as fh:
            json.dump({"created_by": "trader-scanner", "hits": [
                {"symbol": "TSLA", "setups": ["orb"], "or_high": 362.18, "or_low": 354.47},
                {"symbol": "ZZZZ", "setups": ["orb"]}, {"symbol": "DEMO", "setups": ["orb"]}]}, fh)
        code, text, _ = run(["watchlist", "--offline", "charts", "--now", "2026-10-19 10:15"])
        self.assertEqual(code, 0)
        rows = text.splitlines()
        self.assertTrue(rows[1].startswith("TSLA    triggered  10:15 AM  $364.18   $362.18"), rows[1])
        self.assertIn("ZZZZ    error: no offline file", rows[2])
        self.assertIn("DEMO    error: DEMO has 1m bars", rows[3])
        self.assertIn("1 of 3 triggered", text)
        code, text, _ = run(["watchlist", "--offline", "charts", "--now", "2026-10-19 10:12", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(text)[0]["result"]["status"], "waiting")
        code, _, err = run(["watchlist", "--watchlist", "missing.json"])
        self.assertIn("run /trader-scanner first", err)


class SkillDoc(unittest.TestCase):
    def test_skill_md(self):
        with open(os.path.join(ROOT, "trader-entry", "SKILL.md"), encoding="utf-8") as fh:
            text = fh.read()
        with open(os.path.join(ROOT, "trader-risk", "SKILL.md"), encoding="utf-8") as fh:
            risk = fh.read()
        self.assertTrue(text.startswith("---\nname: trader-entry\n"))
        self.assertGreater(len(text.splitlines()), 60)
        self.assertEqual(text[text.index("## Safety"):], risk[risk.index("## Safety"):])
        low = " ".join(text.lower().split())
        for must in ("bar by bar", "can lag", "day trading loses most people money", "/trader-exit", "longs only", "in the background", "/loop", "nothing was placed", "10:15 am", "$364.18", "bar 8"):
            self.assertIn(must, low)
        for never in ("\u2014", "tick " + "by tick", "real " + "time", "pro" + "fit"):
            self.assertNotIn(never, low)


if __name__ == "__main__":
    unittest.main()
