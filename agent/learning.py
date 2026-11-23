"""Daily bias model that learns from its wrong calls.

After each session close the agent predicts whether the next session closes up or down,
using a weighted vote of signals. When the next session is done it grades itself:
 - wrong call  -> every signal that pointed the wrong way loses weight, the right ones gain
 - right call  -> a small reinforcement
It also tracks the "always up" baseline so you can see if it is actually beating a coin flip.
"""
import numpy as np
import pandas as pd

from .analysis import rsi, sma
from .util import STATE, clip, read_json, write_json

MODEL = STATE / "bias_model.json"
JOURNAL = STATE / "bias_journal.json"

DEFAULT_WEIGHTS = {
    "trend_50": 1.0, "trend_200": 0.8, "momentum_20d": 0.5, "rsi": 0.0, "last_day": 0.0,
    "structure_4h": 1.0, "fvg_position": 0.5, "vix_change_5d": 0.5, "breadth": 0.5,
}


def daily_signals(d1, struct4, ctx, gaps, price):
    c = d1["close"]
    s = {}
    if len(c) >= 50:
        s["trend_50"] = 1.0 if c.iloc[-1] > sma(c, 50).iloc[-1] else -1.0
    if len(c) >= 200:
        s["trend_200"] = 1.0 if sma(c, 50).iloc[-1] > sma(c, 200).iloc[-1] else -1.0
    if len(c) >= 21:
        s["momentum_20d"] = clip((c.iloc[-1] / c.iloc[-21] - 1) / 0.05)
    if len(c) >= 15:
        s["rsi"] = clip((rsi(c).iloc[-1] - 50) / 50)
    if len(c) >= 2:
        s["last_day"] = clip((c.iloc[-1] / c.iloc[-2] - 1) / 0.01)
    s["structure_4h"] = {"bullish": 1.0, "bearish": -1.0}.get(struct4, 0.0)
    pos = 0.0
    for g in gaps or []:
        if g["bottom"] <= price <= g["top"]:
            pos = 0.5 if g["dir"] == "bull" else -0.5
    s["fvg_position"] = pos
    vix = ctx.get("vix_closes")
    if vix is not None and len(vix) >= 6:
        s["vix_change_5d"] = -clip((vix[-1] / vix[-6] - 1) / 0.2)
    if ctx.get("breadth") is not None:
        s["breadth"] = clip((ctx["breadth"] - 0.5) * 2)
    return {k: round(float(v), 3) for k, v in s.items()}


def load():
    m = read_json(MODEL, None) or {}
    m.setdefault("weights", dict(DEFAULT_WEIGHTS))
    for k, v in DEFAULT_WEIGHTS.items():
        m["weights"].setdefault(k, v)
    m.setdefault("resolved", 0); m.setdefault("correct", 0); m.setdefault("baseline_correct", 0)
    m.setdefault("recent", []); m.setdefault("signal_stats", {}); m.setdefault("mistakes", [])
    return m, read_json(JOURNAL, [])


def save(model, journal):
    model["mistakes"] = model["mistakes"][-100:]
    write_json(MODEL, model)
    write_json(JOURNAL, journal[-1000:])


def score(signals, weights):
    den = sum(abs(weights.get(k, 0.0)) for k in signals) or 1.0
    return sum(weights.get(k, 0.0) * v for k, v in signals.items()) / den


def resolve(journal, model, d1_completed, lr):
    """Grade any open predictions whose session has now closed. Returns the graded ones."""
    graded = []
    dates = np.array([str(d.date()) for d in d1_completed.index])
    for p in journal:
        if p.get("outcome") is not None:
            continue
        later = np.where(dates > p["base_date"])[0]
        if len(later) == 0:
            continue
        j = later[0]
        close = float(d1_completed["close"].iloc[j])
        y = 1 if close > p["base_close"] else -1
        ok = p["prediction"] == y
        p.update(outcome=y, outcome_date=dates[j], outcome_close=close,
                 outcome_change=round(close - p["base_close"], 2), correct=ok)
        model["resolved"] += 1
        model["correct"] += int(ok)
        model["baseline_correct"] += int(y == 1)
        model["recent"] = (model["recent"] + [int(ok)])[-30:]
        misled = []
        step = lr if not ok else lr * 0.25   # mistakes teach 4x harder than wins
        for k, s in p["signals"].items():
            w = model["weights"].get(k, 0.0)
            model["weights"][k] = round(clip(w + step * y * s, -2.0, 2.0), 4)
            st = model["signal_stats"].setdefault(k, {"n": 0, "hits": 0})
            if s != 0:
                st["n"] += 1
                st["hits"] += int(np.sign(s) == y)
                if np.sign(s) != y and abs(w) > 0:
                    misled.append(k)
        if not ok:
            model["mistakes"].append({"date": dates[j], "predicted": "up" if p["prediction"] == 1 else "down",
                                      "actual_change": p["outcome_change"], "misleading_signals": misled})
        graded.append(p)
    return graded


def predict(journal, model, base_date, base_close, signals):
    for p in journal:
        if p["base_date"] == base_date:
            return p
    sc = score(signals, model["weights"])
    p = {"base_date": base_date, "base_close": float(base_close), "made_at": str(pd.Timestamp.now(tz="UTC")),
         "signals": signals, "score": round(sc, 3), "prediction": 1 if sc > 0 else -1,
         "confidence": round(abs(sc), 3), "outcome": None}
    journal.append(p)
    return p


def scoreboard(model):
    n = model["resolved"]
    if n == 0:
        return {"resolved": 0}
    return {"resolved": n, "accuracy": round(model["correct"] / n, 3),
            "always_up_baseline": round(model["baseline_correct"] / n, 3),
            "last_30": round(sum(model["recent"]) / len(model["recent"]), 3) if model["recent"] else None}
