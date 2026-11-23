"""Price-action building blocks: bars, swings, trend structure, fair value gaps, indicators."""
import numpy as np
import pandas as pd

from .util import ET

M5 = pd.Timedelta(minutes=5)
H1 = pd.Timedelta(hours=1)
H4 = pd.Timedelta(hours=4)
AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def resample(df, rule, offset=None):
    """Resample OHLC bars. Done in UTC to avoid daylight-saving edge cases."""
    if df is None or df.empty:
        return pd.DataFrame(columns=list(AGG))
    u = df.tz_convert("UTC")
    kw = {"offset": offset} if offset else {}
    out = u.resample(rule, **kw).agg(AGG).dropna(subset=["close"])
    return out.tz_convert(ET)


def to_4h(m5):
    # 4H candles starting 18:00 ET (session open), like a futures-session chart
    return resample(m5, "4h", offset="3h")


def swings(df, n, bar_len):
    """Fractal swing highs/lows. Each swing records when it became known (confirmed)."""
    if df is None or len(df) < 2 * n + 1:
        return []
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    idx = df.index
    out = []
    for i in range(n, len(df) - n):
        wh = h[i - n:i + n + 1]
        wl = l[i - n:i + n + 1]
        if h[i] == wh.max() and np.count_nonzero(wh == h[i]) == 1:
            out.append({"kind": "H", "price": float(h[i]), "bar": idx[i], "confirmed": idx[i + n] + bar_len})
        if l[i] == wl.min() and np.count_nonzero(wl == l[i]) == 1:
            out.append({"kind": "L", "price": float(l[i]), "bar": idx[i], "confirmed": idx[i + n] + bar_len})
    out.sort(key=lambda s: s["confirmed"])
    return out


def classify(highs, lows):
    if len(highs) < 2 or len(lows) < 2:
        return "unknown"
    hh = highs[-1] > highs[-2]
    hl = lows[-1] > lows[-2]
    if hh and hl:
        return "bullish"
    if not hh and not hl:
        return "bearish"
    return "range"


def structure(sw, asof=None):
    hs, ls = [], []
    for s in sw:
        if asof is not None and s["confirmed"] > asof:
            break
        (hs if s["kind"] == "H" else ls).append(s["price"])
    return classify(hs[-2:], ls[-2:])


def find_fvgs(df, bar_len, min_size=0.0):
    """Three-candle fair value gaps. 'created' = close time of the third candle."""
    out = []
    if df is None or len(df) < 3:
        return out
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    idx = df.index
    for i in range(2, len(df)):
        if l[i] > h[i - 2] and l[i] - h[i - 2] >= min_size:
            out.append({"dir": "bull", "bottom": float(h[i - 2]), "top": float(l[i]),
                        "bar": idx[i], "created": idx[i] + bar_len})
        elif h[i] < l[i - 2] and l[i - 2] - h[i] >= min_size:
            out.append({"dir": "bear", "bottom": float(h[i]), "top": float(l[i - 2]),
                        "bar": idx[i], "created": idx[i] + bar_len})
    out.sort(key=lambda g: g["created"])
    return out


def sma(s, n):
    return s.rolling(n).mean()


def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()
