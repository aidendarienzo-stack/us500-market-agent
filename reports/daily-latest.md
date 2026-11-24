# US500 nightly report - session 2026-11-24

Close **7212.2** · 4H structure **range** · VIX 26.36 · Sector breadth 55% above 50-day

## Did the agent learn from its mistakes?

| Ledger (live paper trades) | Trades | Win rate | Total pts | Avg pts | Profit factor | Max DD |
|---|---|---|---|---|---|---|
| Every signal | 8 | 38% | -14.0 | -1.75 | 0.72 | 40.0 |
| Only signals the agent chose to take | 8 | 38% | -14.0 | -1.75 | 0.72 | 40.0 |

If the second row beats the first, skipping its past losing conditions is working.

**On unseen backtest data** (the filter learned only from older data):

| | Trades | Win rate | Total pts | Avg pts | Profit factor | Max DD |
|---|---|---|---|---|---|---|
| All signals | 12 | 58% | 30.0 | 2.50 | 1.75 | 16.0 |
| After skipping losing conditions | 9 | 56% | 18.0 | 2.00 | 1.56 | 16.0 |

Mistake filter is **OFF** for live alerts (it has not proven it helps yet, so every signal is alerted).

**Conditions that have lost the most** (backtest + live, live counts 3x):

| Condition | Win rate | Weighted trades |
|---|---|---|
| volatility = normal | 34% | 37.0 |
| session = Asia / overnight | 36% | 26.0 |
| weekday = Fri | 41% | 8.0 |
| weekday = Wed | 42% | 10.0 |
| vs_24h_move = against | 42% | 50.0 |
| weekday = Mon | 42% | 38.0 |

**Latest losing trades (post-mortems)**

- 2026-11-23 16:10 short @ 7259.0, -10.0 pts. Conditions: direction short, session Asia / overnight, weekday Mon, gap_size large, volatility normal, entry_stretch extended, vs_24h_move against
- 2026-11-23 16:05 short @ 7260.2, -10.0 pts. Conditions: direction short, session Asia / overnight, weekday Mon, gap_size large, volatility normal, entry_stretch extended, vs_24h_move against
- 2026-11-23 16:00 short @ 7256.5, -10.0 pts. Conditions: direction short, session New York cash session, weekday Mon, gap_size large, volatility normal, entry_stretch extended, vs_24h_move against
- 2026-11-23 15:05 short @ 7259.8, -10.0 pts. Conditions: direction short, session New York cash session, weekday Mon, gap_size large, volatility normal, entry_stretch extended, vs_24h_move against
- 2026-11-23 11:10 short @ 7260.2, -10.0 pts. Conditions: direction short, session New York cash session, weekday Mon, gap_size large, volatility high, entry_stretch near level, vs_24h_move against

## Daily bias model

- Call for the session after 2026-11-23: **DOWN** → actual -49.8 pts → **correct**
- Next session call: **DOWN** (confidence 0.11)
- Track record: 100% correct over 1 calls (last 30: 100%); 'always up' would have scored 0%

| Signal | Today | Learned weight | Hit rate |
|---|---|---|---|
| trend_50 | -1.00 | +1.01 | 100% of 1 |
| trend_200 | +1.00 | +0.79 | 0% of 1 |
| momentum_20d | -1.00 | +0.51 | 100% of 1 |
| rsi | -0.21 | +0.00 | 100% of 1 |
| last_day | -0.58 | -0.01 | 0% of 1 |
| structure_4h | +0.00 | +1.01 | 100% of 1 |
| fvg_position | +0.50 | +0.51 | 100% of 1 |
| vix_change_5d | -0.18 | +0.51 | 100% of 1 |
| breadth | +0.09 | +0.50 | 100% of 1 |

## Strategy backtest

Best settings on older data: target **10**, stop **8**, 5m swing 3. On newer unseen data: 12 trades, 30.0 pts. **Edge holds on unseen data.**
Full grid: [backtest.md](../backtest.md)

[Open your TradingView chart](https://www.tradingview.com/chart/M4XmmecI/?symbol=PEPPERSTONE%3AUS500) · Research only, not financial advice.
