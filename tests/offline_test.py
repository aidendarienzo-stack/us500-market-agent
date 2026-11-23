"""End-to-end test on synthetic prices (no network). Run: python -m tests.offline_test"""
import os
import shutil
import tempfile

import numpy as np
import pandas as pd

from agent import util


def synth(days=90, seed=7):
    rng = np.random.default_rng(seed)
    end = pd.Timestamp.now(tz="UTC").floor("5min")
    idx = pd.date_range(end - pd.Timedelta(days=days), end, freq="5min", tz="UTC")
    drift = np.sin(np.arange(len(idx)) / 900) * 0.6
    steps = rng.normal(drift, 2.2, len(idx))
    close = 6500 + np.cumsum(steps)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) + rng.gamma(1.5, 1.2, len(idx))
    low = np.minimum(open_, close) - rng.gamma(1.5, 1.2, len(idx))
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 100}, index=idx)
    return df.tz_convert(util.ET)


class FakeFeed:
    name = "synthetic test feed"
    fatal = None

    def __init__(self):
        self.m5 = synth()
        self.buf = []

    def start(self): pass
    def stop(self): pass

    def history(self, tf, days):
        df = self.m5[self.m5.index >= self.m5.index[-1] - pd.Timedelta(days=days)]
        if tf == "1d":
            from agent.analysis import resample
            d = resample(self.m5, "1D")
            ext = pd.DataFrame({"open": 6000.0, "high": 6010.0, "low": 5990.0, "close": np.linspace(6000, 6480, 300),
                                "volume": 1}, index=pd.date_range(d.index[0] - pd.Timedelta(days=300), periods=300, freq="D", tz=util.ET))
            return pd.concat([ext, d])
        return df

    def latest(self):
        return None

    def drain(self):
        return []


def main():
    tmp = tempfile.mkdtemp()
    util.STATE, util.REPORTS, util.DATA = (util.pathlib.Path(tmp) / p for p in ("state", "reports", "data"))
    import agent.ai, agent.daily, agent.learning, agent.live, agent.mistakes
    for mod in (agent.daily, agent.live):
        mod.STATE, mod.REPORTS, mod.DATA = util.STATE, util.REPORTS, util.DATA
    agent.learning.MODEL = util.STATE / "bias_model.json"
    agent.learning.JOURNAL = util.STATE / "bias_journal.json"
    agent.mistakes.PATH = util.STATE / "mistakes_model.json"
    agent.ai.LESSONS = util.STATE / "lessons.md"
    import agent.github_ops
    agent.github_ops.STATE = util.STATE
    os.environ.pop("AGENT_GIT_PUSH", None)

    cfg = util.load_config()
    feed = FakeFeed()

    # nightly routine: backtest + mistakes model + bias learning
    rep = agent.daily.run_daily(cfg, feed, force=True)
    assert rep and "learn from its mistakes" in rep, "daily report missing"
    print(open(util.REPORTS / "backtest.md").read()[:1500])

    # second night: grade yesterday's call
    j = agent.learning.load()[1]
    assert len(j) == 1

    # live engine: replay the last day tick-by-tick
    eng = agent.live.Engine(cfg, feed.name)
    hist = feed.m5.iloc[:-48]
    eng.m5 = hist.copy()
    eng.rescan(initial=True)
    sigs_before = len(eng.seen)
    rng = np.random.default_rng(1)
    for t, row in feed.m5.iloc[-48:].iterrows():
        tu = t.tz_convert("UTC")
        for k, px in enumerate([row.open, row.high, row.low, row.close]):
            eng.on_price(tu + pd.Timedelta(seconds=10 + k * 70), float(px))
    eng.heartbeat(pd.Timestamp.now(tz="UTC") + pd.Timedelta(minutes=10))
    eng.flush()
    eng.report(pd.Timestamp.now(tz="UTC"))
    live = open(util.REPORTS / "live.md").read()
    print(live[:2500])
    print("signals seen:", sigs_before, "->", len(eng.seen))
    print("paper open/closed:", len(eng.paper["open"]), len(eng.paper["closed"]))
    print("post-mortems:", len(eng.mm.get("post_mortems", [])))
    print("worst conditions:", agent.mistakes.worst_conditions(eng.mm)[:3])
    assert os.path.exists(util.DATA / "bars_1m")

    # forced signal -> loss -> post-mortem -> live learning; then a win
    last_t = eng.m5.index[-1]
    px = float(eng.m5["close"].iloc[-1])
    n_live_before = eng.mm["live"].get("__all__", {}).get("n", 0)
    for k, outcome in enumerate((-1, 1)):
        sig = {"time": last_t + pd.Timedelta(minutes=5 * (k + 1)), "i": len(eng.m5) - 1, "dir": 1, "price": px,
               "level": px - 1, "zone": [px - 6, px - 2]}
        eng._on_signal(sig)
        assert len(eng.paper["open"]) == 1
        hit = px - 11 if outcome < 0 else px + 13
        eng._update_paper(sig["time"].tz_convert("UTC") + pd.Timedelta(minutes=1), hit)
        assert len(eng.paper["open"]) == 0
    assert len(eng.paper["closed"]) == 2 and eng.paper["closed"][0]["pnl"] < 0 < eng.paper["closed"][1]["pnl"]
    assert len(eng.mm["post_mortems"]) == 1, "loss was not logged as a mistake"
    assert eng.mm["live"]["__all__"]["n"] == n_live_before + 2
    eng.flush()
    assert agent.mistakes.load()["live"]["__all__"]["n"] == n_live_before + 2
    print("paper trades:", [(t["pnl"], t["taken"]) for t in eng.paper["closed"]])
    print("post-mortem:", eng.mm["post_mortems"][-1]["conditions"])
    shutil.rmtree(tmp)
    print("\nOFFLINE TEST PASSED")


if __name__ == "__main__":
    main()
