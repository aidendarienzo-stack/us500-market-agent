"""Talking to GitHub from inside the Actions run: commit results, open alert issues, chain runs."""
import json
import os
import subprocess
import threading
import urllib.request

from .util import ROOT, STATE, log, read_json, write_json

_push_lock = threading.Lock()


def _api(method, path, body=None):
    tok = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    if not tok or not repo:
        return None
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            txt = r.read().decode()
            return json.loads(txt) if txt else {}
    except Exception as e:
        log("GitHub API error:", method, path, e)
        return None


def create_issue(title, body):
    r = _api("POST", "/issues", {"title": title, "body": body})
    if r is None:
        log("ALERT (no GitHub token, printing instead):", title)
        return None
    return r.get("number")


def comment(number, body):
    if number:
        _api("POST", f"/issues/{number}/comments", {"body": body})


def close_issue(number):
    if number:
        _api("PATCH", f"/issues/{number}", {"state": "closed"})


def alert_once(key, title, body):
    """Open an issue for a problem, at most once per day per key."""
    import pandas as pd
    seen = read_json(STATE / "alerts_sent.json", {})
    today = str(pd.Timestamp.now(tz="UTC").date())
    if seen.get(key) == today:
        return
    seen[key] = today
    write_json(STATE / "alerts_sent.json", seen)
    create_issue(title, body)


def dispatch_self(workflow="agent.yml"):
    ref = os.getenv("GITHUB_REF_NAME", "main")
    r = _api("POST", f"/actions/workflows/{workflow}/dispatches", {"ref": ref})
    log("Queued next run" if r is not None else "Could not queue next run (watchdog will start it)")


def save_tokens(tok):
    """Store refreshed cTrader tokens as repo secrets. Needs the optional GH_PAT secret."""
    pat = os.getenv("GH_PAT")
    repo = os.getenv("GITHUB_REPOSITORY")
    if not pat or not repo:
        return False
    env = dict(os.environ, GH_TOKEN=pat)
    try:
        for name, key in (("CTRADER_ACCESS_TOKEN", "accessToken"), ("CTRADER_REFRESH_TOKEN", "refreshToken")):
            if tok.get(key):
                subprocess.run(["gh", "secret", "set", name, "--repo", repo, "--body", tok[key]],
                               env=env, check=True, capture_output=True)
        return True
    except Exception as e:
        log("Could not save refreshed tokens:", e)
        return False


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def commit_push(message, background=True):
    if os.getenv("AGENT_GIT_PUSH") != "1":
        return

    def work():
        if not _push_lock.acquire(blocking=False):
            return
        try:
            _git("config", "user.name", "market-agent[bot]")
            _git("config", "user.email", "market-agent@users.noreply.github.com")
            _git("add", "-A", "reports", "state", "data")
            if _git("diff", "--cached", "--quiet").returncode == 0:
                return
            _git("commit", "-m", message)
            for _ in range(3):
                _git("pull", "--rebase", "--autostash")
                if _git("push").returncode == 0:
                    return
            log("git push failed; will retry next cycle")
        finally:
            _push_lock.release()

    if background:
        threading.Thread(target=work, daemon=True).start()
    else:
        work()
