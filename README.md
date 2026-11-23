# US500 Market Agent

An always-on research agent for **Pepperstone US500**, the same feed as [your TradingView chart](https://www.tradingview.com/chart/M4XmmecI/?symbol=PEPPERSTONE%3AUS500).
It checks price **every second while the futures market is open**, runs your strategy, paper-trades every setup, and **learns from its mistakes**.

It never places real trades and never connects to a brokerage account. It only uses read-only price data.

**Live report:** [reports/live.md](reports/live.md) (refreshed every 15 minutes)  ·  **Nightly report:** [reports/daily-latest.md](reports/daily-latest.md)  ·  **Backtest:** [reports/backtest.md](reports/backtest.md)  ·  **Lessons learned:** [state/lessons.md](state/lessons.md)  ·  **Alerts:** [Issues tab](../../issues)

---

## What it does

**Every second (Sun 6pm – Fri 5pm ET):**
- Streams live US500 ticks and builds 1-minute and 5-minute candles
- Tracks 4H trend structure (higher highs / higher lows) and every unfilled **4H fair value gap**
- Detects your setup: price taps a 4H FVG in the trend direction, then a 5m candle closes through the last 5m swing (change of delivery)
- When a setup triggers, it opens a **GitHub issue** with entry, stop, target and its own win estimate. Turn on GitHub mobile notifications to get these on your phone.
- Paper-trades every signal and closes it the moment stop or target is hit

**Every night (5–6pm ET break):**
- Backtests your strategy on recent data: tunes target/stop on older data, then checks the result on newer data it has never seen
- Grades its daily up/down call and adjusts itself
- Writes the nightly report (plus a written brief if a Claude API key is added)

## How it learns from its mistakes

1. **Trade post-mortems.** Every losing paper trade is logged with the conditions it fired in: session, weekday, volatility, gap size, whether it went against the 24-hour move, and how extended the entry was. The agent keeps a win/loss scorecard for each condition. Live losses count 3x as much as backtest losses.
2. **It skips what keeps losing.** Every new setup gets a win estimate from that scorecard. If the estimate is below break-even, it marks the setup **SKIP**.
3. **It has to prove this works.** The agent keeps two paper ledgers: *every signal* and *only the signals it chose to take*. The skip filter only goes live for alerts once it has beaten "take everything" on unseen backtest data. Until then it alerts on every signal and keeps learning.
4. **Its daily bias call learns from wrong calls.** After each session it predicts up or down from a weighted vote of signals. When a call is wrong, the signals that misled it lose weight, 4x harder than a right call reinforces them. It also tracks the "always up" baseline, so you can see whether it's beating a coin flip.
5. **Written lessons (optional).** With a Claude API key, every loss gets a one-sentence lesson in [state/lessons.md](state/lessons.md). Past lessons are fed back in each time, so it builds on what it has already learned.

---

## Setup

It already runs on free, delayed ES futures data with zero setup. Steps 1–4 switch it to live Pepperstone ticks.

### 1. Pepperstone cTrader account
Open a free **Pepperstone cTrader demo account** (or use a live one; the agent only reads prices).

### 2. Register a cTrader Open API app
Go to **https://openapi.ctrader.com**, log in with your cTrader ID, and add an application. Use `http://localhost` as the redirect URI.
Approval can take a little while. When it's approved you'll have a **Client ID** and **Secret**.

### 3. Get an access token
Easiest: on your app's page, use the **Playground** option (if shown) and copy the access token and refresh token.
Or run the helper script on any computer with Python:
```bash
pip install ctrader-open-api
python scripts/get_ctrader_token.py
```
It requests **read-only** access, which is all the agent needs.

### 4. Add the secrets to this repo
**Settings → Secrets and variables → Actions → New repository secret**

| Secret | Required | What it is |
|---|---|---|
| `CTRADER_CLIENT_ID` | yes | From step 2 |
| `CTRADER_CLIENT_SECRET` | yes | From step 2 |
| `CTRADER_ACCESS_TOKEN` | yes | From step 3 |
| `CTRADER_REFRESH_TOKEN` | recommended | From step 3. Lets the agent renew the token itself |
| `CTRADER_ACCOUNT_ID` | no | Picked automatically if blank |
| `GH_PAT` | no | A GitHub fine-grained token with *Secrets: read & write* on this repo, so renewed cTrader tokens are saved automatically |
| `ANTHROPIC_API_KEY` | no | Turns on the written lessons and nightly brief |

Secrets stay private even though the repo is public.

### 5. Start it
**Actions** tab → enable workflows if asked → **Watchdog** → **Run workflow**. From then on the watchdog checks every 10 minutes and keeps the agent running whenever the market is open.

---

## Settings
Everything lives in [`config.yaml`](config.yaml): symbol, strategy rules, backtest grid, alert options. Edit it on GitHub; the next run picks it up.

## How it runs on GitHub
GitHub jobs can run for at most 6 hours, so the agent runs about 5h45m, saves everything, and queues its own next run. There's a gap of about a minute at each handoff. Public repos get unlimited free Actions minutes, so this costs nothing.

## Honest limits
- Fills are idealized: no spread or slippage, and the stop is assumed hit first when stop and target land in the same candle.
- A backtest edge can disappear live. That's why the agent keeps forward-testing and only trusts what holds up on unseen data.
- Research and paper trading only. Not financial advice.
