"""Aiden's US500 strategy: 4H trend structure + change of delivery near 4H fair value gaps.

Long:  4H structure bullish (HH + HL) -> price taps an unfilled bullish 4H FVG ->
       a 5m candle closes above the most recent 5m swing high (change of delivery).
Short: mirror image.
Entry at the close of the trigger candle, fixed point stop and target.
"""
import numpy as np
import pandas as pd

from .analysis import H4, M5, atr, classify, find_fvgs, swings, to_4h
from . import hours


def build_context(m5, scfg):
    h4 = to_4h(m5)
    fvgs = find_fvgs(h4, H4, scfg["fvg_min_points"])
    sw4 = swings(h4, scfg["swing_4h"], H4)
    return fvgs, sw4


def scan(m5, fvgs, sw4, n5, arm_bars, max_gap_age_days=20):
    """Walk 5m bars in order (no look-ahead) and return trigger signals + the final live state."""
    if m5 is None or m5.empty:
        return [], {"structure_4h": "unknown", "active_fvgs": [], "armed_long": None, "armed_short": None,
                    "last_swing_high": None, "last_swing_low": None}
    sw5 = swings(m5, n5, M5)
    idx = m5.index
    h = m5["high"].to_numpy(float)
    l = m5["low"].to_numpy(float)
    c = m5["close"].to_numpy(float)
    gi = si4 = si5 = 0
    active, hs4, ls4 = [], [], []
    last_sh = last_sl = None
    arm_long = arm_short = None
    signals = []
    st = "unknown"
    max_age = pd.Timedelta(days=max_gap_age_days)
    window = pd.Timedelta(hours=1)

    for i in range(len(idx)):
        t = idx[i]
        while gi < len(fvgs) and fvgs[gi]["created"] <= t:
            active.append(dict(fvgs[gi]))
            gi += 1
        while si4 < len(sw4) and sw4[si4]["confirmed"] <= t:
            s = sw4[si4]
            (hs4 if s["kind"] == "H" else ls4).append(s["price"])
            si4 += 1
        while si5 < len(sw5) and sw5[si5]["confirmed"] <= t:
            s = sw5[si5]
            if s["kind"] == "H":
                last_sh = s
            else:
                last_sl = s
            si5 += 1
        st = classify(hs4[-2:], ls4[-2:])

        keep = []
        for g in active:
            if t - g["created"] > max_age:
                continue
            if g["dir"] == "bull":
                if l[i] <= g["top"] and c[i] >= g["bottom"]:
                    arm_long = {"i": i, "time": t, "zone": g}
                if c[i] < g["bottom"]:
                    continue  # closed through the gap: invalid
            else:
                if h[i] >= g["bottom"] and c[i] <= g["top"]:
                    arm_short = {"i": i, "time": t, "zone": g}
                if c[i] > g["top"]:
                    continue
            keep.append(g)
        active = keep

        if arm_long and i - arm_long["i"] > arm_bars:
            arm_long = None
        if arm_short and i - arm_short["i"] > arm_bars:
            arm_short = None

        if (st == "bullish" and arm_long and last_sh is not None
                and last_sh["bar"] >= arm_long["time"] - window and c[i] > last_sh["price"]):
            z = arm_long["zone"]
            signals.append({"time": t + M5, "i": i, "dir": 1, "price": float(c[i]),
                            "level": last_sh["price"], "zone": [z["bottom"], z["top"]]})
            arm_long = None
        if (st == "bearish" and arm_short and last_sl is not None
                and last_sl["bar"] >= arm_short["time"] - window and c[i] < last_sl["price"]):
            z = arm_short["zone"]
            signals.append({"time": t + M5, "i": i, "dir": -1, "price": float(c[i]),
                            "level": last_sl["price"], "zone": [z["bottom"], z["top"]]})
            arm_short = None

    state = {
        "structure_4h": st,
        "active_fvgs": active,
        "armed_long": arm_long and {"since": arm_long["time"], "zone": [arm_long["zone"]["bottom"], arm_long["zone"]["top"]]},
        "armed_short": arm_short and {"since": arm_short["time"], "zone": [arm_short["zone"]["bottom"], arm_short["zone"]["top"]]},
        "last_swing_high": last_sh,
        "last_swing_low": last_sl,
    }
    return signals, state


def signal_features(m5, sig, atr_series=None):
    """Describe the conditions a signal fired in. Used to learn which conditions lose."""
    i = sig["i"]
    c = m5["close"].to_numpy(float)
    a = atr_series if atr_series is not None else atr(m5)
    a_i = float(a.iloc[i]) if i < len(a) else float("nan")
    lo = max(0, i - 2000)
    med = float(np.nanmedian(a.iloc[lo:i + 1])) if i >= 1 else a_i
    zone_h = sig["zone"][1] - sig["zone"][0]
    t = sig["time"]
    f = {"direction": "long" if sig["dir"] == 1 else "short",
         "session": hours.session_name(t - M5),
         "weekday": pd.Timestamp(t).tz_convert("America/New_York").strftime("%a")}
    if a_i == a_i and a_i > 0:
        r = zone_h / a_i
        f["gap_size"] = "small" if r < 1 else ("medium" if r < 3 else "large")
        v = a_i / med if med and med == med else 1.0
        f["volatility"] = "low" if v < 0.75 else ("high" if v > 1.4 else "normal")
        stretch = (sig["price"] - sig["level"]) * sig["dir"] / a_i
        f["entry_stretch"] = "near level" if stretch < 0.5 else "extended"
    if i >= 288:
        move = (c[i] - c[i - 288]) * sig["dir"]
        f["vs_24h_move"] = "with" if move > 0 else "against"
    return f


def simulate(m5, signals, target, stop, max_hold, allow=None):
    """Turn signals into trades. One position at a time; if stop and target hit in the
    same 5m bar we assume the stop (conservative). `allow(sig)` can veto a signal."""
    h = m5["high"].to_numpy(float)
    l = m5["low"].to_numpy(float)
    c = m5["close"].to_numpy(float)
    trades = []
    busy_until = -1
    for s in signals:
        i = s["i"]
        if i <= busy_until:
            continue
        if allow is not None and not allow(s):
            continue
        d, e = s["dir"], s["price"]
        stop_px, tgt_px = e - d * stop, e + d * target
        end = min(i + 1 + max_hold, len(c))
        pnl, j = None, i
        for j in range(i + 1, end):
            if d == 1:
                if l[j] <= stop_px:
                    pnl = -float(stop); break
                if h[j] >= tgt_px:
                    pnl = float(target); break
            else:
                if h[j] >= stop_px:
                    pnl = -float(stop); break
                if l[j] <= tgt_px:
                    pnl = float(target); break
        if pnl is None:
            if end == len(c):
                continue  # still open at end of data
            j = end - 1
            pnl = float(d * (c[j] - e))
        trades.append({"signal": s, "entry_time": s["time"], "exit_time": m5.index[j], "dir": d,
                       "entry": e, "pnl": round(pnl, 2)})
        busy_until = j
    return trades


def metrics(trades):
    n = len(trades)
    if n == 0:
        return {"trades": 0, "win_rate": None, "total_pts": 0.0, "avg_pts": None, "profit_factor": None, "max_dd_pts": 0.0}
    p = np.array([t["pnl"] for t in trades], float)
    gw, gl = p[p > 0].sum(), -p[p < 0].sum()
    eq = np.cumsum(p)
    peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
    return {"trades": n, "win_rate": round(float((p > 0).mean()), 3), "total_pts": round(float(p.sum()), 1),
            "avg_pts": round(float(p.mean()), 2), "profit_factor": round(float(gw / gl), 2) if gl > 0 else None,
            "max_dd_pts": round(float((peak - eq).max()), 1)}
