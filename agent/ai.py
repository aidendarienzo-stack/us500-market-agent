"""Optional Claude layer: written post-mortems on losing trades and a nightly market brief.

Only runs if the ANTHROPIC_API_KEY secret is set. Lessons accumulate in state/lessons.md and
are fed back into every future brief and post-mortem, so the agent builds on what it learned.
"""
import json
import os

import pandas as pd

from .util import STATE, log

LESSONS = STATE / "lessons.md"
DEFAULT_MODEL = "claude-sonnet-5-5"


def enabled():
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _ask(system, prompt, max_tokens=700):
    if not enabled():
        return None
    try:
        import anthropic
        client = anthropic.Anthropic()
        msg = client.messages.create(model=os.getenv("CLAUDE_MODEL") or DEFAULT_MODEL, max_tokens=max_tokens,
                                     system=system, messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    except Exception as e:
        log("Claude call failed:", e)
        return None


def recent_lessons(n=40):
    if not LESSONS.exists():
        return ""
    lines = [l for l in LESSONS.read_text().splitlines() if l.startswith("- ")]
    return "\n".join(lines[-n:])


def add_lesson(text):
    LESSONS.parent.mkdir(parents=True, exist_ok=True)
    if not LESSONS.exists():
        LESSONS.write_text("# Lessons the agent has learned from its mistakes\n\n")
    stamp = pd.Timestamp.now(tz="America/New_York").strftime("%Y-%m-%d")
    with open(LESSONS, "a") as f:
        f.write(f"- {stamp}: {text.strip()}\n")


SYSTEM = ("You are the analyst inside an automated US500 (S&P 500 CFD) research agent. The trader uses "
          "4H trend structure and a 5m change of delivery near 4H fair value gaps, targeting 10-15 points "
          "with stops of about 10. You write in plain, direct English. You never give financial advice; you "
          "analyze what the data shows and what the agent got wrong.")


def post_mortem(trade, features, assessment, context):
    """One-sentence lesson for a losing paper trade."""
    prompt = (f"A paper trade just lost. Trade: {json.dumps(trade, default=str)}\n"
              f"Conditions when it fired: {json.dumps(features)}\n"
              f"The agent's own estimate before entry: {json.dumps(assessment, default=str)}\n"
              f"Market context: {json.dumps(context, default=str)}\n\n"
              f"Lessons already learned:\n{recent_lessons() or '(none yet)'}\n\n"
              "In ONE sentence (max 35 words), state the most likely reason this setup failed and a concrete, "
              "testable rule to avoid it. Do not repeat an existing lesson; if it is the same, say "
              "'Repeat of: <lesson>' and add any new detail.")
    out = _ask(SYSTEM, prompt, max_tokens=120)
    if out:
        add_lesson(out)
    return out


def daily_brief(snapshot):
    prompt = (f"Today's data from the agent:\n{json.dumps(snapshot, default=str)[:12000]}\n\n"
              f"Lessons learned so far:\n{recent_lessons() or '(none yet)'}\n\n"
              "Write the nightly brief in markdown with these sections:\n"
              "### What happened\n### What the agent got wrong and why\n### What to watch next session\n"
              "Keep it under 250 words. Reference actual levels and numbers from the data.")
    return _ask(SYSTEM, prompt, max_tokens=700)
