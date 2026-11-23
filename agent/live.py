"""The always-on loop: checks US500 every second while the futures market is open."""
import time
from collections import deque

import pandas as pd

from . import ai, daily, github_ops, hours, mistakes
from .analysis import atr
from .strategy import build_context, scan, signal_features
from .util import DATA, ET, REPORTS, STATE, fmt_et, log, now_utc, read_json, write_json, write_text

M5 = pd.Timedelta(minutes=5)


class Engine:
    def __init__(self, cfg, feed_name):
        self.cfg = cfg
        self.feed_name = feed_name
        self.s = cfg["strategy"]
        self.m5 = pd.DataFrame()
        self.cur1 = self.cur5 = None
        self.start_bucket = None
        self.minutes = []
        self.state = {}
        self.signals = []
        self.events = deque(maxlen=60)
        self.price = self.last_tick = None
        self.seen = set(read_json(STATE / "seen_signals.json", []))
        self.paper = read_json(STATE / "paper_trades.json", {"open": [], "closed": []})
        self.mm = mistakes.load()
        self.params = self._params()
        self.tapped = set()
        self.watch_key = None
        self.stale_warned = False
        self.atr = None

    def _params(self):
        p = read_json(STATE / "strategy_params.json", None)
        if p and p.get("edge"):
            return {"target": p["target"], "stop": p["stop"], "swing_5m": p["swing_5m"],
                    "filter": bool(p.get("use_mistake_filter")), "source": f"nightly backtest {p['date']}"}
        return {"target": self.s["default_target"], "stop": self.s["default_stop"], "swing_5m": self.s["swing_5m"],
                "filter": bool(p and p.get("use_mistake_filter")), "source": "your defaults (no proven edge yet)"}

    def event(self, text):
        self.events.appendleft((now_utc(), text))
        log(text)

    # ------------------------------------------------------------------ data
    def load_history(self, feed, days=60):
        self.m5 = feed.history("5m", days)
        log(f"Loaded {len(self.m5)} five-minute bars of history")
        self.rescan(initial=True)

    def on_price(self, ts, price):
        ts = pd.Timestamp(ts).tz_convert("UTC")
        self.price, self.last_tick = float(price), ts
        b1 = ts.floor("1min").tz_convert(ET)
        b5 = ts.floor("5min").tz_convert(ET)
        if self.start_bucket is None:
            self.start_bucket = b5
        self.cur1 = self._roll(self.cur1, b1, price, self.minutes.append)
        self.cur5 = self._roll(self.cur5, b5, price, self._close_5m)
        self._intrabar(price)
        self._update_paper(ts, price)

    def heartbeat(self, now):
        """Close the 5m candle on time even if the next tick has not arrived yet."""
        if self.cur5 is not None and now - pd.Timedelta(seconds=2) >= self.cur5["t"] + M5:
            bar, self.cur5 = self.cur5, None
            self._close_5m(bar)

    @staticmethod
    def _roll(cur, bucket, px, on_close):
        if cur is None or cur["t"] != bucket:
            if cur is not None:
                on_close(cur)
            return {"t": bucket, "open": px, "high": px, "low": px, "close": px, "volume": 1}
        cur["high"] = max(cur["high"], px)
        cur["low"] = min(cur["low"], px)
        cur["close"] = px
        cur["volume"] += 1
        return cur

    def _close_5m(self, bar):
        if bar["t"] == self.start_bucket:
            return  # the agent started mid-candle; this candle is incomplete
        if not self.m5.empty and bar["t"] <= self.m5.index[-1]:
            return
        row = pd.DataFrame([{k: bar[k] for k in ("open", "high", "low", "close", "volume")}], index=[bar["t"]])
        self.m5 = pd.concat([self.m5, row]) if not self.m5.empty else row
        self.m5 = self.m5[self.m5.index >= self.m5.index[-1] - pd.Timedelta(days=70)]
        self.rescan()

    # ------------------------------------------------------------------ strategy
    def rescan(self, initial=False):
        if self.m5.empty:
            return
        fvgs, sw4 = build_context(self.m5, self.s)
        self.signals, self.state = scan(self.m5, fvgs, sw4, self.params["swing_5m"], self.s["arm_bars"])
        self.atr = atr(self.m5)
        cutoff = self.m5.index[-1] - pd.Timedelta(minutes=10)
        for sg in self.signals:
            key = sg["time"].isoformat()
            if key in self.seen:
                continue
            self.seen.add(key)
            if not initial and sg["time"] >= cutoff:
                self._on_signal(sg)

    def _on_signal(self, sg):
        tgt, stp = self.params["target"], self.params["stop"]
        feats = signal_features(self.m5, sg, self.atr)
        take, prob, be, reasons = mistakes.assess(self.mm, feats, tgt, stp)
        if not self.params["filter"]:
            take_note = "Mistake filter is off until it proves itself, so this alert is sent either way."
            taken = True
        else:
            take_note = "Agent decision: **TAKE**" if take else "Agent decision: **SKIP** (conditions keep losing)"
            taken = take
        d = sg["dir"]
        side = "LONG" if d == 1 else "SHORT"
        e = sg["price"]
        trade = {"id": sg["time"].isoformat(), "entry_time": str(sg["time"]), "dir": d, "entry": e,
                 "stop": e - d * stp, "target": e + d * tgt, "features": feats, "taken": taken,
                 "assessment": {"win_prob": prob, "breakeven": be, "take": take, "reasons": reasons}}
        self.event(f"{side} signal @ {e:.1f} ({'taken' if taken else 'skipped'})")
        if self.cfg["live"]["alert_on_signals"] and (taken or not self.params["filter"]):
            body = [f"**{side} US500 @ {e:.1f}**  ·  stop {trade['stop']:.1f}  ·  target {trade['target']:.1f}", "",
                    f"- 4H structure: {self.state['structure_4h']}",
                    f"- Tapped 4H FVG: {sg['zone'][0]:.1f} – {sg['zone'][1]:.1f}",
                    f"- 5m change of delivery through {sg['level']:.1f}",
                    f"- Conditions: {', '.join(f'{k} {v}' for k, v in feats.items())}",
                    f"- Agent's win estimate: {prob:.0%} vs break-even {be:.0%}" if prob is not None else
                    "- Agent's win estimate: not enough history yet",
                    *[f"  - {r}" for r in reasons], "", take_note, "",
                    f"Settings: {self.params['source']}. [Open chart]({self.cfg['tradingview_chart']})", "",
                    "_Paper trade for research only - not financial advice._"]
            trade["issue"] = github_ops.create_issue(f"{side} US500 @ {e:.1f} — {fmt_et(sg['time'])}", "\n".join(body))
        self.paper["open"].append(trade)

    def _update_paper(self, ts, price):
        still = []
        for t in self.paper["open"]:
            d = t["dir"]
            res = None
            if (d == 1 and price <= t["stop"]) or (d == -1 and price >= t["stop"]):
                res = -abs(t["entry"] - t["stop"])
            elif (d == 1 and price >= t["target"]) or (d == -1 and price <= t["target"]):
                res = abs(t["target"] - t["entry"])
            elif ts - pd.Timestamp(t["entry_time"]) > M5 * self.s["max_hold_bars"]:
                res = d * (price - t["entry"])
            if res is None:
                still.append(t)
                continue
            t.update(exit_time=str(ts), exit=price, pnl=round(res, 2))
            self._learn(t)
            self.paper["closed"].append(t)
        self.paper["open"] = still

    def _learn(self, t):
        """The learning-from-mistakes step for a finished live paper trade."""
        won = t["pnl"] > 0
        mistakes.record_live(self.mm, t["features"], won)
        msg = f"Paper trade closed {t['pnl']:+.1f} pts ({'win' if won else 'LOSS'})"
        if not won:
            ctx = {"structure_4h": self.state.get("structure_4h"), "session": hours.session_name(t["exit_time"])}
            t["lesson"] = ai.post_mortem({k: t[k] for k in ("entry_time", "exit_time", "dir", "entry", "exit", "pnl")},
                                         t["features"], t["assessment"], ctx)
            mistakes.add_post_mortem(self.mm, t, t["features"], t["assessment"])
            msg += " - logged as a mistake to learn from"
        mistakes.save(self.mm)
        self.event(msg)
        if t.get("issue"):
            body = f"Closed **{t['pnl']:+.1f} pts** at {t['exit']:.1f} ({'target' if won else 'stop/timeout'})."
            if t.get("lesson"):
                body += f"\n\nLesson: {t['lesson']}"
            github_ops.comment(t["issue"], body)
            github_ops.close_issue(t["issue"])

    def _intrabar(self, price):
        st = self.state
        for g in st.get("active_fvgs", []):
            key = (g["dir"], round(g["bottom"], 1), round(g["top"], 1))
            if g["bottom"] <= price <= g["top"] and key not in self.tapped:
                self.tapped.add(key)
                self.event(f"Price tapped {g['dir']}ish 4H FVG {g['bottom']:.1f}–{g['top']:.1f}")
                if self.cfg["live"]["alert_on_taps"]:
                    github_ops.create_issue(f"US500 tapped 4H FVG {g['bottom']:.1f}–{g['top']:.1f}",
                                            f"Price {price:.1f}. Watching for a 5m change of delivery.")
        sh, sl = st.get("last_swing_high"), st.get("last_swing_low")
        if st.get("structure_4h") == "bullish" and st.get("armed_long") and sh and price > sh["price"]:
            k = ("L", sh["price"])
            if self.watch_key != k:
                self.watch_key = k
                self.event(f"Watch: price above 5m swing high {sh['price']:.1f}; long triggers if this 5m candle closes above it")
        if st.get("structure_4h") == "bearish" and st.get("armed_short") and sl and price < sl["price"]:
            k = ("S", sl["price"])
            if self.watch_key != k:
                self.watch_key = k
                self.event(f"Watch: price below 5m swing low {sl['price']:.1f}; short triggers if this 5m candle closes below it")

    # ------------------------------------------------------------------ output
    def flush(self):
        if self.minutes:
            df = pd.DataFrame(self.minutes).rename(columns={"t": "time"})
            df["time"] = pd.to_datetime(df["time"]).dt.tz_convert("UTC")
            for month, part in df.groupby(df["time"].dt.strftime("%Y-%m")):
                p = DATA / "bars_1m" / f"{month}.csv"
                p.parent.mkdir(parents=True, exist_ok=True)
                part.to_csv(p, mode="a", header=not p.exists(), index=False)
            self.minutes = []
        write_json(STATE / "seen_signals.json", sorted(self.seen)[-1000:])
        self.paper["closed"] = self.paper["closed"][-2000:]
        write_json(STATE / "paper_trades.json", self.paper)
        mistakes.save(self.mm)

    def report(self, now):
        st = self.state
        px = self.price
        L = [f"# US500 live — {fmt_et(now)}", "",
             f"**Price {px:.1f}**" if px else "**Waiting for first price**",
             f" · {hours.session_name(now)} · feed: {self.feed_name}"
             + (f" · last tick {fmt_et(self.last_tick)}" if self.last_tick is not None else ""), "",
             f"4H structure: **{st.get('structure_4h', '?')}** · settings: target {self.params['target']}, "
             f"stop {self.params['stop']} ({self.params['source']}) · mistake filter "
             f"{'ON' if self.params['filter'] else 'OFF'}", ""]
        for side in ("long", "short"):
            a = st.get(f"armed_{side}")
            if a:
                L.append(f"- **{side.upper()} setup armed** since {fmt_et(a['since'])} after tapping FVG "
                         f"{a['zone'][0]:.1f}–{a['zone'][1]:.1f}")
        sh, sl = st.get("last_swing_high"), st.get("last_swing_low")
        if sh:
            L.append(f"- Last 5m swing high {sh['price']:.1f} · swing low {sl['price']:.1f}" if sl else
                     f"- Last 5m swing high {sh['price']:.1f}")
        gaps = st.get("active_fvgs", [])
        if px and gaps:
            above = sorted([g for g in gaps if g["bottom"] > px], key=lambda g: g["bottom"])[:4]
            below = sorted([g for g in gaps if g["top"] < px], key=lambda g: -g["top"])[:4]
            inside = [g for g in gaps if g["bottom"] <= px <= g["top"]]
            L += ["", "## Unfilled 4H fair value gaps", "", "| Where | Type | Zone | Distance |", "|---|---|---|---|"]
            for lab, grp in (("inside", inside), ("above", above), ("below", below)):
                for g in grp:
                    dist = 0 if lab == "inside" else (g["bottom"] - px if lab == "above" else px - g["top"])
                    L.append(f"| {lab} | {g['dir']} | {g['bottom']:.1f} – {g['top']:.1f} | {dist:.1f} pts |")
        today = [s for s in self.signals if s["time"] >= now - pd.Timedelta(hours=24)]
        L += ["", "## Signals in the last 24 hours", ""]
        L += [f"- {fmt_et(s['time'])}: {'LONG' if s['dir'] == 1 else 'SHORT'} @ {s['price']:.1f}" for s in today] or ["- none"]
        if self.paper["open"]:
            L += ["", "## Open paper trades", ""]
            L += [f"- {'LONG' if t['dir'] == 1 else 'SHORT'} @ {t['entry']:.1f}, stop {t['stop']:.1f}, target {t['target']:.1f}"
                  f" ({'taken' if t['taken'] else 'skipped by agent'})" for t in self.paper["open"]]
        closed = self.paper["closed"]
        if closed:
            from .strategy import metrics
            a, b = metrics(closed), metrics([t for t in closed if t.get("taken")])
            L += ["", "## Forward test (live paper trades)", "",
                  f"- Every signal: {a['trades']} trades, {a['total_pts']:+.1f} pts, win rate {a['win_rate']:.0%}",
                  f"- Signals the agent chose to take: {b['trades']} trades, {b['total_pts']:+.1f} pts"
                  + (f", win rate {b['win_rate']:.0%}" if b["trades"] else "")]
        L += ["", "## Recent events", ""]
        L += [f"- {fmt_et(t)} — {e}" for t, e in list(self.events)[:15]] or ["- none"]
        L += ["", f"[Nightly report](daily-latest.md) · [Backtest](backtest.md) · [Lessons](../state/lessons.md) · "
                  f"[TradingView chart]({self.cfg['tradingview_chart']})", "",
              "_Research and paper trading only. Not financial advice._"]
        write_text(REPORTS / "live.md", "\n".join(L) + "\n")


def run(cfg, max_seconds):
    from .feeds import make_feed
    feed = make_feed(cfg)
    if getattr(feed, "restart_requested", False):
        github_ops.dispatch_self()
        return
    eng = Engine(cfg, feed.name)
    eng.load_history(feed)
    every = cfg["live"]["report_every_minutes"] * 60
    stale = cfg["live"]["stale_after_seconds"]
    t0 = time.monotonic()
    last_report = 0.0
    reason = "time limit"
    try:
        while True:
            loop_start = time.monotonic()
            if loop_start - t0 > max_seconds:
                break
            now = now_utc()
            if getattr(feed, "fatal", None):
                reason = f"feed error: {feed.fatal}"
                break
            if not hours.is_open(now):
                try:
                    daily.run_daily(cfg, feed)
                    eng.params = eng._params()
                    eng.mm = mistakes.load()
                except Exception as e:
                    log("Nightly routine failed:", e)
                eng.flush(); eng.report(now)
                github_ops.commit_push(f"agent: {now:%Y-%m-%d %H:%M} UTC", background=False)
                last_report = time.monotonic()
                if hours.minutes_until_open(now) > 75:
                    reason = "market closed"
                    break
                time.sleep(30)
                continue
            for ts, px in feed.drain():   # every tick since the last second
                eng.on_price(ts, px)
            q = feed.latest()
            if q:
                if (now - q[0]).total_seconds() > stale and not eng.stale_warned:
                    eng.stale_warned = True
                    eng.event(f"No new price for {stale}s (quiet market, holiday, or feed problem)")
                elif (now - q[0]).total_seconds() <= stale:
                    eng.stale_warned = False
            eng.heartbeat(now)
            if time.monotonic() - last_report >= every:
                eng.flush(); eng.report(now)
                github_ops.commit_push(f"live: {now:%Y-%m-%d %H:%M} UTC")
                last_report = time.monotonic()
            time.sleep(max(0.0, 1.0 - (time.monotonic() - loop_start)))
    finally:
        log("Stopping:", reason)
        eng.flush(); eng.report(now_utc())
        github_ops.commit_push(f"agent stop ({reason})", background=False)
        if reason == "time limit" or reason.startswith("feed error"):
            github_ops.dispatch_self()
        feed.stop()
