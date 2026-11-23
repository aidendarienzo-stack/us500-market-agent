"""Learning from mistakes.

Every trade (backtested and live paper) is stored with the conditions it fired in.
For each condition (e.g. session = "Asia / overnight", vs_24h_move = "against") the agent keeps
a win/loss tally. A new signal gets an estimated win probability from those tallies; if the
conditions it fires in have kept losing, the agent skips it.

Live paper trades count 3x as much as backtested trades, because they are the agent's own
real-time mistakes. Everything here is plain statistics - nothing is hidden.
"""
import math

from .util import STATE, read_json, write_json

PATH = STATE / "mistakes_model.json"
LIVE_WEIGHT = 3.0
PRIOR = 4.0          # pseudo-trades pulling each condition toward the overall win rate
MIN_EVIDENCE = 6.0   # need this much weighted history on a condition before it can veto
MARGIN = 0.03        # required edge over break-even win rate


def _empty():
    return {"backtest": {}, "live": {}, "post_mortems": []}


def load():
    m = read_json(PATH, None)
    return m if m else _empty()


def save(m):
    m["post_mortems"] = m.get("post_mortems", [])[-300:]
    write_json(PATH, m)


def _add(table, features, won, weight=1.0):
    tot = table.setdefault("__all__", {"w": 0.0, "n": 0.0})
    tot["n"] += weight
    tot["w"] += weight if won else 0.0
    for k, v in features.items():
        cell = table.setdefault(f"{k}={v}", {"w": 0.0, "n": 0.0})
        cell["n"] += weight
        cell["w"] += weight if won else 0.0


def train_backtest(m, trades_with_features):
    """Replace the backtest part of the model with tonight's backtest trades."""
    table = {}
    for feats, won in trades_with_features:
        _add(table, feats, won)
    m["backtest"] = table


def record_live(m, features, won):
    _add(m["live"], features, won)


def _merged(m):
    out = {}
    for src, wt in (("backtest", 1.0), ("live", LIVE_WEIGHT)):
        for k, cell in m.get(src, {}).items():
            o = out.setdefault(k, {"w": 0.0, "n": 0.0})
            o["w"] += cell["w"] * (wt if src == "live" else 1.0)
            o["n"] += cell["n"] * (wt if src == "live" else 1.0)
    return out


def assess(m, features, target, stop):
    """Return (take: bool, win_prob, breakeven, reasons)."""
    t = _merged(m)
    breakeven = stop / (stop + target)
    allc = t.get("__all__", {"w": 0.0, "n": 0.0})
    if allc["n"] < MIN_EVIDENCE:
        return True, None, breakeven, ["not enough history yet - taking every signal"]
    base = (allc["w"] + 1) / (allc["n"] + 2)
    logit = lambda p: math.log(p / (1 - p))
    score = logit(base)
    reasons = []
    for k, v in features.items():
        cell = t.get(f"{k}={v}")
        if not cell or cell["n"] < 1:
            continue
        p = (cell["w"] + PRIOR * base) / (cell["n"] + PRIOR)
        score += logit(p) - logit(base)
        if cell["n"] >= MIN_EVIDENCE:
            reasons.append((p - base, f"{k} = {v}: won {cell['w']:.0f} of {cell['n']:.0f} weighted trades ({p:.0%})"))
    prob = 1 / (1 + math.exp(-score))
    reasons.sort(key=lambda r: r[0])
    take = prob >= breakeven + MARGIN
    text = [r[1] for r in (reasons[:3] if not take else reasons[-3:][::-1])]
    return take, round(prob, 3), round(breakeven, 3), text


def worst_conditions(m, top=6):
    t = _merged(m)
    allc = t.get("__all__")
    if not allc or allc["n"] < MIN_EVIDENCE:
        return []
    base = (allc["w"] + 1) / (allc["n"] + 2)
    rows = []
    for k, cell in t.items():
        if k == "__all__" or cell["n"] < MIN_EVIDENCE:
            continue
        p = (cell["w"] + PRIOR * base) / (cell["n"] + PRIOR)
        rows.append({"condition": k.replace("=", " = "), "win_rate": round(p, 3), "weighted_trades": round(cell["n"], 1)})
    rows.sort(key=lambda r: r["win_rate"])
    return rows[:top]


def add_post_mortem(m, trade, features, assessment):
    m.setdefault("post_mortems", []).append({
        "entry_time": trade["entry_time"], "direction": "long" if trade["dir"] == 1 else "short",
        "entry": trade["entry"], "pnl": trade["pnl"], "conditions": features,
        "agent_estimate": assessment, "lesson": trade.get("lesson"),
    })
