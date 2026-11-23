"""Price feeds.

CTraderFeed  - Pepperstone cTrader Open API: live US500 ticks (same feed as PEPPERSTONE:US500 on TradingView)
YahooFeed    - free fallback (ES futures, delayed ~10 min) used until cTrader secrets are set

Both expose: start(), stop(), latest() -> (utc_timestamp, price) | None,
history(tf, days) -> OHLCV DataFrame indexed in US/Eastern, with only completed bars.
"""
import os
import threading
import time

import pandas as pd

from .util import ET, log, now_utc

TF_LEN = {"1m": pd.Timedelta(minutes=1), "5m": pd.Timedelta(minutes=5),
          "1h": pd.Timedelta(hours=1), "1d": pd.Timedelta(days=1)}


def _finish(df, tf):
    if df is None or df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    if tf != "1d":
        df = df[df.index + TF_LEN[tf] <= now_utc()]  # drop the bar still forming
    return df


# ----------------------------------------------------------------------------- Yahoo
class YahooFeed:
    name = "Yahoo Finance (delayed fallback)"

    def __init__(self, cfg):
        self.symbol = cfg["symbol"]["yahoo_fallback"]
        self._last = None
        self._fetched = 0.0
        self.fatal = None

    def start(self):
        log(f"Using fallback feed {self.symbol}. Add the cTrader secrets for live Pepperstone US500 ticks.")

    def stop(self):
        pass

    def _yf(self):
        import yfinance as yf
        return yf

    def history(self, tf, days):
        yf = self._yf()
        period = {"1m": "7d", "5m": f"{min(days, 59)}d", "1h": f"{min(days, 729)}d", "1d": f"{days}d"}[tf]
        try:
            df = yf.Ticker(self.symbol).history(period=period, interval=tf, auto_adjust=False)
        except Exception as e:
            log("Yahoo history error", e)
            return _finish(None, tf)
        if df is None or df.empty:
            return _finish(None, tf)
        df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert(ET)
        return _finish(df, tf)

    def latest(self):
        if time.monotonic() - self._fetched > 15:
            self._fetched = time.monotonic()
            try:
                df = self._yf().Ticker(self.symbol).history(period="1d", interval="1m")
                if df is not None and not df.empty:
                    ts = df.index[-1]
                    ts = (ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")) + pd.Timedelta(minutes=1)
                    self._last = (min(ts, now_utc()), float(df["Close"].iloc[-1]))
            except Exception as e:
                log("Yahoo quote error", e)
        return self._last

    def drain(self):
        q = self.latest()
        if q is None or q == getattr(self, "_drained", None):
            return []
        self._drained = q
        return [q]


# ----------------------------------------------------------------------------- cTrader
class CTraderFeed:
    name = "Pepperstone cTrader (live ticks)"

    def __init__(self, cfg):
        self.cfg = cfg
        self.client_id = os.environ["CTRADER_CLIENT_ID"]
        self.client_secret = os.environ["CTRADER_CLIENT_SECRET"]
        self.access_token = os.environ["CTRADER_ACCESS_TOKEN"]
        self.refresh_token = os.getenv("CTRADER_REFRESH_TOKEN", "")
        self.account_id = int(os.getenv("CTRADER_ACCOUNT_ID") or 0)
        self.symbol_name = cfg["symbol"]["ctrader_name"]
        self.env = cfg["symbol"].get("ctrader_env", "demo")
        self.side = cfg["symbol"].get("price_side", "bid")
        self.symbol_id = None
        self.bid = self.ask = None
        self.tick_time = None
        self.fatal = None
        self.token_refreshed = False
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._buf = []

    # ---- lifecycle
    def start(self):
        from ctrader_open_api import Client, EndPoints, TcpProtocol
        from twisted.internet import reactor, task
        self._reactor = reactor
        host = EndPoints.PROTOBUF_LIVE_HOST if self.env == "live" else EndPoints.PROTOBUF_DEMO_HOST
        self.client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.client.setConnectedCallback(self._on_connected)
        self.client.setDisconnectedCallback(lambda c, reason: log("cTrader disconnected:", reason))
        self.client.setMessageReceivedCallback(self._on_message)

        def boot():
            self.client.startService()
            task.LoopingCall(self._heartbeat).start(10, now=False)

        reactor.callWhenRunning(boot)
        threading.Thread(target=reactor.run, kwargs={"installSignalHandlers": False}, daemon=True).start()
        if not self._ready.wait(90):
            raise RuntimeError(self.fatal or "Timed out connecting to cTrader")
        if self.fatal:
            raise RuntimeError(self.fatal)
        log(f"cTrader connected: {self.symbol_name} (symbolId {self.symbol_id}, account {self.account_id})")

    def stop(self):
        try:
            self._reactor.callFromThread(self._reactor.stop)
        except Exception:
            pass

    # ---- protocol helpers (run in the reactor thread)
    def _send(self, req, timeout=20):
        from ctrader_open_api import Protobuf
        d = self.client.send(req, responseTimeoutInSeconds=timeout)
        d.addCallback(lambda msg: Protobuf.extract(msg))
        return d

    def _heartbeat(self):
        from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoHeartbeatEvent
        try:
            self.client.send(ProtoHeartbeatEvent()).addErrback(lambda f: None)
        except Exception:
            pass

    def _fail(self, why):
        self.fatal = why
        log("cTrader error:", why)
        self._ready.set()

    def _check(self, res):
        if type(res).__name__ == "ProtoOAErrorRes":
            raise RuntimeError(f"{res.errorCode}: {getattr(res, 'description', '')}")
        return res

    def _on_connected(self, client):
        from ctrader_open_api.messages.OpenApiMessages_pb2 import (
            ProtoOAAccountAuthReq, ProtoOAApplicationAuthReq, ProtoOAGetAccountListByAccessTokenReq,
            ProtoOASubscribeSpotsReq, ProtoOASymbolsListReq)

        def app_auth():
            r = ProtoOAApplicationAuthReq(); r.clientId = self.client_id; r.clientSecret = self.client_secret
            return self._send(r)

        def pick_account(_):
            if self.account_id:
                return None
            r = ProtoOAGetAccountListByAccessTokenReq(); r.accessToken = self.access_token
            return self._send(r).addCallback(self._check).addCallback(self._choose_account)

        def acct_auth(_):
            r = ProtoOAAccountAuthReq(); r.ctidTraderAccountId = self.account_id; r.accessToken = self.access_token
            return self._send(r)

        def symbols(_):
            r = ProtoOASymbolsListReq(); r.ctidTraderAccountId = self.account_id
            return self._send(r, timeout=30)

        def subscribe(res):
            self._check(res)
            want = self.symbol_name.lower()
            syms = list(res.symbol)
            match = [s for s in syms if s.symbolName.lower() == want] or \
                    [s for s in syms if want in s.symbolName.lower()]
            if not match:
                raise RuntimeError(f"Symbol {self.symbol_name} not found on this account")
            self.symbol_id = match[0].symbolId
            r = ProtoOASubscribeSpotsReq(); r.ctidTraderAccountId = self.account_id; r.symbolId.append(self.symbol_id)
            return self._send(r)

        d = app_auth()
        d.addCallback(self._check).addCallback(pick_account).addCallback(acct_auth)
        d.addCallback(self._check).addCallback(symbols).addCallback(subscribe)
        d.addCallback(self._check).addCallback(lambda _: self._ready.set())
        d.addErrback(lambda f: self._fail(str(f.value)))

    def _choose_account(self, res):
        accts = list(res.ctidTraderAccount)
        want_live = self.env == "live"
        pick = [a for a in accts if bool(a.isLive) == want_live] or accts
        if not pick:
            raise RuntimeError("No cTrader accounts on this token")
        self.account_id = int(pick[0].ctidTraderAccountId)

    def _on_message(self, client, message):
        from ctrader_open_api import Protobuf
        from ctrader_open_api.messages.OpenApiMessages_pb2 import (
            ProtoOAAccountsTokenInvalidatedEvent, ProtoOASpotEvent)
        pt = message.payloadType
        if pt == ProtoOASpotEvent().payloadType:
            ev = Protobuf.extract(message)
            if ev.symbolId != self.symbol_id:
                return
            with self._lock:
                if ev.HasField("bid"):
                    self.bid = ev.bid / 100000.0
                if ev.HasField("ask"):
                    self.ask = ev.ask / 100000.0
                self.tick_time = now_utc()
                px = self._px()
                if px is not None:
                    self._buf.append((self.tick_time, px))
        elif pt == ProtoOAAccountsTokenInvalidatedEvent().payloadType:
            self.fatal = "cTrader access token was invalidated"

    # ---- public API (called from the main thread)
    def _px(self):
        if self.side == "ask" and self.ask is not None:
            return self.ask
        if self.side == "mid" and self.ask is not None and self.bid is not None:
            return (self.bid + self.ask) / 2
        return self.bid if self.bid is not None else self.ask

    def latest(self):
        with self._lock:
            if self.tick_time is None:
                return None
            px = self._px()
            return (self.tick_time, px) if px is not None else None

    def drain(self):
        with self._lock:
            out, self._buf = self._buf, []
        return out

    def history(self, tf, days):
        from twisted.internet.threads import blockingCallFromThread
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq
        from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod
        period = {"1m": "M1", "5m": "M5", "1h": "H1", "1d": "D1"}[tf]
        chunk = {"1m": 3, "5m": 7, "1h": 60, "1d": 365}[tf]
        end = now_utc()
        start = end - pd.Timedelta(days=days)
        rows = []
        cur_end = end
        while cur_end > start:
            cur_start = max(start, cur_end - pd.Timedelta(days=chunk))

            def req(a=cur_start, b=cur_end):
                r = ProtoOAGetTrendbarsReq()
                r.ctidTraderAccountId = self.account_id
                r.symbolId = self.symbol_id
                r.period = ProtoOATrendbarPeriod.Value(period)
                r.fromTimestamp = int(a.timestamp() * 1000)
                r.toTimestamp = int(b.timestamp() * 1000)
                return self._send(r, timeout=60)

            try:
                res = self._check(blockingCallFromThread(self._reactor, req))
                for b in res.trendbar:
                    lo = b.low
                    rows.append((pd.Timestamp(b.utcTimestampInMinutes * 60, unit="s", tz="UTC"),
                                 (lo + b.deltaOpen) / 1e5, (lo + b.deltaHigh) / 1e5, lo / 1e5,
                                 (lo + b.deltaClose) / 1e5, b.volume))
            except Exception as e:
                log(f"cTrader history error ({tf} {cur_start:%Y-%m-%d}):", e)
            cur_end = cur_start
            time.sleep(0.3)  # stay under the historical-data rate limit
        if not rows:
            return _finish(None, tf)
        df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"]).set_index("time")
        df.index = df.index.tz_convert(ET)
        return _finish(df, tf)


def refresh_ctrader_token():
    """Exchange the refresh token for a new access token. Returns dict or None."""
    try:
        from ctrader_open_api import Auth
        auth = Auth(os.environ["CTRADER_CLIENT_ID"], os.environ["CTRADER_CLIENT_SECRET"], "http://localhost")
        res = auth.refreshToken(os.environ["CTRADER_REFRESH_TOKEN"])
        if res and res.get("accessToken"):
            return res
        log("Token refresh failed:", res)
    except Exception as e:
        log("Token refresh error:", e)
    return None


def make_feed(cfg):
    have = all(os.getenv(k) for k in ("CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET", "CTRADER_ACCESS_TOKEN"))
    if not have:
        f = YahooFeed(cfg); f.start(); return f
    feed = CTraderFeed(cfg)
    try:
        feed.start()
        return feed
    except Exception as e:
        log("cTrader start failed:", e)
        from . import github_ops
        feed.stop()
        f = YahooFeed(cfg)
        f.restart_requested = False
        if os.getenv("CTRADER_REFRESH_TOKEN"):
            tok = refresh_ctrader_token()
            if tok and github_ops.save_tokens(tok):
                # A Twisted reactor can't restart in the same process, so start a fresh run
                # that picks up the new token from the repo secrets.
                log("Token refreshed and saved; restarting with the live feed.")
                f.restart_requested = True
                return f
        github_ops.alert_once("ctrader-feed-down", "cTrader feed could not connect",
                              f"The agent fell back to delayed Yahoo data for this run.\n\nError: `{e}`\n\n"
                              "If your token expired, follow **Step 3** in the README to get a new one.")
        f.start()
        return f
