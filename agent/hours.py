"""US500 / S&P futures trading hours (US Eastern time).

Open Sunday 18:00 ET -> Friday 17:00 ET, with a daily break 17:00-18:00 ET Mon-Thu.
Holidays are not modeled; on a holiday the feed simply goes quiet.
"""
import datetime as dt

import pandas as pd

from .util import ET

OPEN = dt.time(18, 0)
CLOSE = dt.time(17, 0)


def is_open(ts):
    t = pd.Timestamp(ts).tz_convert(ET)
    wd, tm = t.weekday(), t.time()  # Mon=0 ... Sun=6
    if wd == 5:
        return False
    if wd == 6:
        return tm >= OPEN
    if wd == 4:
        return tm < CLOSE
    return not (CLOSE <= tm < OPEN)


def minutes_until_open(ts, limit=4 * 24 * 60):
    t = pd.Timestamp(ts).tz_convert("UTC").floor("min")
    if is_open(t):
        return 0
    # coarse 15-minute steps, then refine
    m = 0
    while m < limit and not is_open(t + pd.Timedelta(minutes=m + 15)):
        m += 15
    while m < limit and not is_open(t + pd.Timedelta(minutes=m)):
        m += 1
    return m


def session_name(ts):
    t = pd.Timestamp(ts).tz_convert(ET)
    h = t.hour + t.minute / 60
    if not is_open(ts):
        return "closed"
    if 9.5 <= h < 16:
        return "New York cash session"
    if 3 <= h < 9.5:
        return "London / pre-market"
    return "Asia / overnight"
