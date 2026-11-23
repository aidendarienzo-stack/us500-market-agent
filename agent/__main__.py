"""Command line:
  python -m agent live [--max-minutes 345]   run the every-second loop
  python -m agent daily                      run the nightly learning routine now
  python -m agent check                      exit 0 if the agent should be running now (used by the watchdog)
"""
import argparse
import sys

from .util import load_config, log, now_utc


def main():
    ap = argparse.ArgumentParser(prog="agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    lv = sub.add_parser("live")
    lv.add_argument("--max-minutes", type=float, default=345)
    sub.add_parser("daily")
    sub.add_parser("check")
    a = ap.parse_args()

    if a.cmd == "check":
        from . import hours
        now = now_utc()
        should = hours.is_open(now) or hours.minutes_until_open(now) <= 60
        print("run" if should else "idle")
        sys.exit(0 if should else 1)

    cfg = load_config()
    if a.cmd == "live":
        from .live import run
        run(cfg, a.max_minutes * 60)
    elif a.cmd == "daily":
        from . import github_ops
        from .daily import run_daily
        from .feeds import make_feed
        feed = make_feed(cfg)
        try:
            run_daily(cfg, feed, force=True)
            github_ops.commit_push("nightly routine (manual)", background=False)
        finally:
            feed.stop()
    log("done")


if __name__ == "__main__":
    main()
