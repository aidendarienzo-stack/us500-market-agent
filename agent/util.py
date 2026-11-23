import json
import pathlib

import pandas as pd
import yaml

ET = "America/New_York"
ROOT = pathlib.Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
REPORTS = ROOT / "reports"
DATA = ROOT / "data"


def load_config(path=None):
    p = pathlib.Path(path) if path else ROOT / "config.yaml"
    with open(p) as f:
        return yaml.safe_load(f)


def read_json(path, default):
    p = pathlib.Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def write_json(path, obj):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str))
    tmp.replace(p)


def write_text(path, text):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def now_utc():
    return pd.Timestamp.now(tz="UTC")


def et(ts):
    return pd.Timestamp(ts).tz_convert(ET)


def fmt_et(ts):
    return et(ts).strftime("%a %b %d %H:%M:%S ET")


def log(*args):
    print(f"[{pd.Timestamp.now(tz=ET):%Y-%m-%d %H:%M:%S}]", *args, flush=True)


def clip(x, lo=-1.0, hi=1.0):
    try:
        x = float(x)
    except Exception:
        return 0.0
    if x != x:  # NaN
        return 0.0
    return max(lo, min(hi, x))
