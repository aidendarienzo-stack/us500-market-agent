"""Nightly routine, run during the 17:00-18:00 ET break (and after Friday's close).

1. Backtest the strategy, tune it on old data, check it on newer unseen data.
2. Retrain the mistakes model on the backtest trades and test whether skipping
   "losing conditions" actually helps on the unseen data.
3. Grade yesterday's bias call, learn from it, make tomorrow's call.
4. Optional Claude brief. Write the daily report.
"""
import glob

import pandas as pd

from . import ai, learning, mistakes
from .analysis import H4, atr, structure, swings, to_4h, resample
from .strategy import build_context, metrics, scan, signal_features, simulate
from .util import DATA, ET, REPORTS, STATE, log, now_utc, read_json, write_json, write_text


def stored_5m():
    files = sorted(glob.glob(str(DATA / "bars_1m" / "*.csv")))
    if not files:
        return pd.DataFrame()
    parts = []
    for f in files:
        try:
            parts.append(pd.read_csv(f, parse_dates=["time"]).set_index("time"))
        except Exception:
            pass
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    if "volume" not in df:
        df["volume"] = df.get("ticks", 0)
    return resample(df[["open", "high", "low", "close", "volume"]], "5min")


def merged_5m(feed, days):
    fetched = feed.history("5m", days)
    own = stored_5m()
    if own.empty:
        return fetched
    if fetched.empty:
        return own
    df = fetched.combine_first(own)
    return df[df.index >= now_utc() - pd.Timedelta(days=days)].sort_index()


def run_backtest(m5, cfg):
    s, b = cfg["strategy"], cfg["backtest"]
    fvgs, sw4 = build_context(m5, s)
    a = atr(m5)
    split = m5.index[int(len(m5) * b["in_sample_frac"])]
    rows, cache = [], {}
    for n5 in b["swing_5m"]:
        sigs, _ = scan(m5, fvgs, sw4, n5, s["arm_bars"])
        cache[n5] = sigs
        for tg in b["targets"]:
            for sp in b["stops"]:
                tr = simulate(m5, sigs, tg, sp, s["max_hold_bars"])
                ins = [t for t in tr if t["entry_time"] < split]
                oos = [t for t in tr if t["entry_time"] >= split]
                rows.append({"swing_5m": n5, "target": tg, "stop": sp, "all": metrics(tr),
                             "in_sample": metrics(ins), "out_of_sample": metrics(oos)})
    eligible = [r for r in rows if r["in_sample"]["trades"] >= b["min_trades"]] or rows
    best = max(eligible, key=lambda r: r["in_sample"]["total_pts"])
    oos = best["out_of_sample"]
    edge = bool(oos["trades"] >= 5 and (oos["avg_pts"] or 0) > 0)

    # --- learning from mistakes, validated honestly: learn on in-sample, judge on out-of-sample
    sigs = cache[best["swing_5m"]]
    trades = simulate(m5, sigs, best["target"], best["stop"], s["max_hold_bars"])
    feats = {id(t["signal"]): signal_features(m5, t["signal"], a) for t in trades}
    mm = mistakes._empty()
    mistakes.train_backtest(mm, [(feats[id(t["signal"])], t["pnl"] > 0) for t in trades if t["entry_time"] < split])

    def allow(sig):
        take, *_ = mistakes.assess(mm, signal_features(m5, sig, a), best["target"], best["stop"])
        return take

    oos_sigs = [x for x in sigs if x["time"] >= split]
    filtered = simulate(m5, oos_sigs, best["target"], best["stop"], s["max_hold_bars"], allow=allow)
    unfiltered = simulate(m5, oos_sigs, best["target"], best["stop"], s["max_hold_bars"])
    filter_test = {"unfiltered": metrics(unfiltered), "filtered": metrics(filtered)}
    filter_helps = bool(filter_test["filtered"]["trades"] >= 3 and
                        filter_test["filtered"]["total_pts"] > filter_test["unfiltered"]["total_pts"])

    # the live mistakes model learns from the whole backtest
    all_feats = [(feats[id(t["signal"])], t["pnl"] > 0) for t in trades]
    return {"date": str(pd.Timestamp.now(tz=ET).date()), "bars": len(m5),
            "start": str(m5.index[0]), "end": str(m5.index[-1]), "split": str(split),
            "rows": rows, "best": best, "edge": edge, "filter_test": filter_test, "filter_helps": filter_helps,
            "_trades_features": all_feats}


def context(cfg):
    out = {"vix": None, "vix_closes": None, "breadth": None, "sectors": {}}
    try:
        import yfinance as yf
        v = yf.Ticker(cfg["context"]["vix"]).history(period="3mo", interval="1d")["Close"].dropna()
        if len(v):
            out["vix"] = round(float(v.iloc[-1]), 2)
            out["vix_closes"] = [float(x) for x in v.iloc[-10:]]
        above = 0; total = 0
        for t in cfg["context"]["sectors"]:
            c = yf.Ticker(t).history(period="6mo", interval="1d")["Close"].dropna()
            if len(c) < 50:
                continue
            total += 1
            above += int(c.iloc[-1] > c.rolling(50).mean().iloc[-1])
            out["sectors"][t] = round(float(c.iloc[-1] / c.iloc[-2] - 1) * 100, 2)
        out["breadth"] = above / total if total else None
    except Exception as e:
        log("Context data unavailable:", e)
    return out


def _fmt(v, nd=1, pct=False):
    if v is None:
        return "-"
    return f"{v:.0%}" if pct else f"{v:.{nd}f}"


def _mrow(name, m):
    return (f"| {name} | {m['trades']} | {_fmt(m['win_rate'], pct=True)} | {_fmt(m['total_pts'])} | "
            f"{_fmt(m['avg_pts'], 2)} | {_fmt(m['profit_factor'], 2)} | {_fmt(m['max_dd_pts'])} |")


def run_daily(cfg, feed, force=False):
    now = now_utc()
    d1 = feed.history("1d", 900)
    completed = d1[d1.index <= now - pd.Timedelta(hours=12)] if not d1.empty else d1
    if completed.empty:
        log("No daily bars yet; skipping nightly routine")
        return None
    key = str(completed.index[-1].date())
    done = read_json(STATE / "daily_done.json", {})
    if done.get("key") == key and not force:
        return None
    log(f"Nightly routine for session {key}")

    m5 = merged_5m(feed, cfg["backtest"]["days"])
    if m5.empty or len(m5) < 500:
        log("Not enough 5m history for the nightly routine")
        return None

    # 1-2. backtest + mistakes model
    bt = run_backtest(m5, cfg)
    pairs = bt.pop("_trades_features")
    mm = mistakes.load()
    mistakes.train_backtest(mm, pairs)
    mistakes.save(mm)
    best = bt["best"]
    write_json(STATE / "strategy_params.json", {"date": bt["date"], "edge": bt["edge"], "target": best["target"],
                                                "stop": best["stop"], "swing_5m": best["swing_5m"],
                                                "use_mistake_filter": bt["filter_helps"]})
    hist = read_json(STATE / "backtest_history.json", [])
    hist.append({"date": bt["date"], "best": {k: best[k] for k in ("swing_5m", "target", "stop")},
                 "in_sample": best["in_sample"], "out_of_sample": best["out_of_sample"],
                 "edge": bt["edge"], "filter_test": bt["filter_test"]})
    write_json(STATE / "backtest_history.json", hist[-365:])

    # 3. daily bias learning
    s = cfg["strategy"]
    fvgs, sw4 = build_context(m5, s)
    _, st = scan(m5, fvgs, sw4, s["swing_5m"], s["arm_bars"])
    ctx = context(cfg)
    price = float(completed["close"].iloc[-1])
    sig = learning.daily_signals(completed, st["structure_4h"], ctx, st["active_fvgs"], price)
    model, journal = learning.load()
    graded = learning.resolve(journal, model, completed, cfg["learning"]["rate"])
    pred = learning.predict(journal, model, key, price, sig)
    learning.save(model, journal)
    board = learning.scoreboard(model)

    paper = read_json(STATE / "paper_trades.json", {"open": [], "closed": []})
    paper_all = metrics([t for t in paper["closed"]])
    paper_taken = metrics([t for t in paper["closed"] if t.get("taken")])

    snapshot = {"session": key, "close": price, "structure_4h": st["structure_4h"], "context": ctx,
                "graded_bias_calls": graded, "next_call": pred, "bias_scoreboard": board,
                "weights": model["weights"], "recent_bias_mistakes": model["mistakes"][-5:],
                "backtest_best": best, "backtest_has_edge": bt["edge"], "mistake_filter_test": bt["filter_test"],
                "paper_all_signals": paper_all, "paper_agent_taken": paper_taken,
                "worst_conditions": mistakes.worst_conditions(mm),
                "todays_losses": [p for p in mm.get("post_mortems", []) if str(p["entry_time"])[:10] == key]}
    brief = ai.daily_brief(snapshot)
    if graded and ai.enabled():
        wrong = [g for g in graded if not g["correct"]]
        if wrong:
            g = wrong[-1]
            lesson = ai._ask(ai.SYSTEM, f"The agent's daily bias call was wrong: {g}. Current weights: {model['weights']}. "
                                        f"Lessons so far:\n{ai.recent_lessons()}\nIn ONE sentence (max 35 words), what should the agent learn?",
                             max_tokens=120)
            if lesson:
                ai.add_lesson(lesson)

    report = build_report(key, price, st, ctx, pred, graded, board, model, bt, mm, paper_all, paper_taken, brief, cfg)
    write_text(REPORTS / "daily" / f"{key}.md", report)
    write_text(REPORTS / "daily-latest.md", report)
    write_text(REPORTS / "backtest.md", backtest_report(bt))
    write_json(STATE / "daily_done.json", {"key": key, "ran_at": str(now)})
    log("Nightly routine done")
    return report


def build_report(key, price, st, ctx, pred, graded, board, model, bt, mm, paper_all, paper_taken, brief, cfg):
    L = [f"# US500 nightly report - session {key}", "",
         f"Close **{price:.1f}** · 4H structure **{st['structure_4h']}** · VIX {_fmt(ctx.get('vix'), 2)} · "
         f"Sector breadth {_fmt(ctx.get('breadth'), pct=True)} above 50-day", ""]
    if brief:
        L += ["## Analyst brief", "", brief, ""]

    L += ["## Did the agent learn from its mistakes?", "",
          "| Ledger (live paper trades) | Trades | Win rate | Total pts | Avg pts | Profit factor | Max DD |",
          "|---|---|---|---|---|---|---|",
          _mrow("Every signal", paper_all), _mrow("Only signals the agent chose to take", paper_taken), "",
          "If the second row beats the first, skipping its past losing conditions is working.", "",
          "**On unseen backtest data** (the filter learned only from older data):", "",
          "| | Trades | Win rate | Total pts | Avg pts | Profit factor | Max DD |", "|---|---|---|---|---|---|---|",
          _mrow("All signals", bt["filter_test"]["unfiltered"]), _mrow("After skipping losing conditions", bt["filter_test"]["filtered"]), "",
          f"Mistake filter is **{'ON' if bt['filter_helps'] else 'OFF'}** for live alerts "
          f"({'it improved results on unseen data' if bt['filter_helps'] else 'it has not proven it helps yet, so every signal is alerted'}).", ""]
    worst = mistakes.worst_conditions(mm)
    if worst:
        L += ["**Conditions that have lost the most** (backtest + live, live counts 3x):", "",
              "| Condition | Win rate | Weighted trades |", "|---|---|---|"]
        L += [f"| {w['condition']} | {w['win_rate']:.0%} | {w['weighted_trades']} |" for w in worst]
        L += [""]
    pms = mm.get("post_mortems", [])[-5:]
    if pms:
        L += ["**Latest losing trades (post-mortems)**", ""]
        for p in reversed(pms):
            L.append(f"- {str(p['entry_time'])[:16]} {p['direction']} @ {p['entry']:.1f}, {p['pnl']:+.1f} pts. "
                     f"Conditions: {', '.join(f'{k} {v}' for k, v in p['conditions'].items())}"
                     + (f". Lesson: {p['lesson']}" if p.get("lesson") else ""))
        L += [""]

    L += ["## Daily bias model", ""]
    for g in graded:
        L.append(f"- Call for the session after {g['base_date']}: **{'UP' if g['prediction'] == 1 else 'DOWN'}** → "
                 f"actual {g['outcome_change']:+.1f} pts → **{'correct' if g['correct'] else 'WRONG'}**")
    L.append(f"- Next session call: **{'UP' if pred['prediction'] == 1 else 'DOWN'}** (confidence {pred['confidence']:.2f})")
    if board.get("resolved"):
        L.append(f"- Track record: {board['accuracy']:.0%} correct over {board['resolved']} calls "
                 f"(last 30: {_fmt(board.get('last_30'), pct=True)}); 'always up' would have scored {board['always_up_baseline']:.0%}")
    L += ["", "| Signal | Today | Learned weight | Hit rate |", "|---|---|---|---|"]
    for k, v in pred["signals"].items():
        stt = model["signal_stats"].get(k, {"n": 0, "hits": 0})
        hr = f"{stt['hits'] / stt['n']:.0%} of {stt['n']}" if stt["n"] else "-"
        L.append(f"| {k} | {v:+.2f} | {model['weights'].get(k, 0):+.2f} | {hr} |")
    L += ["", "## Strategy backtest", "",
          f"Best settings on older data: target **{bt['best']['target']}**, stop **{bt['best']['stop']}**, 5m swing {bt['best']['swing_5m']}. "
          f"On newer unseen data: {bt['best']['out_of_sample']['trades']} trades, {_fmt(bt['best']['out_of_sample']['total_pts'])} pts. "
          f"{'**Edge holds on unseen data.**' if bt['edge'] else '**No proven edge on unseen data yet** - alerts use your default 12/10.'}",
          "Full grid: [backtest.md](../backtest.md)", "",
          f"[Open your TradingView chart]({cfg['tradingview_chart']}) · Research only, not financial advice."]
    return "\n".join(L) + "\n"


def backtest_report(bt):
    L = [f"# Strategy backtest - {bt['date']}", "",
         f"Data: {bt['bars']} five-minute bars, {bt['start'][:16]} → {bt['end'][:16]}. "
         f"Tuned on bars before {bt['split'][:16]}, tested on bars after.", "",
         "| 5m swing | Target | Stop | In-sample trades | In-sample pts | Unseen trades | Unseen win rate | Unseen pts | Unseen PF |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(bt["rows"], key=lambda r: -r["in_sample"]["total_pts"]):
        i, o = r["in_sample"], r["out_of_sample"]
        mark = " ⭐" if r is bt["best"] else ""
        L.append(f"| {r['swing_5m']} | {r['target']} | {r['stop']}{mark} | {i['trades']} | {_fmt(i['total_pts'])} | "
                 f"{o['trades']} | {_fmt(o['win_rate'], pct=True)} | {_fmt(o['total_pts'])} | {_fmt(o['profit_factor'], 2)} |")
    L += ["", "Stop is assumed hit first whenever stop and target fall in the same 5m bar, so results lean conservative. "
              "No spread or slippage is modeled."]
    return "\n".join(L) + "\n"
