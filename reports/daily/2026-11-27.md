# US500 nightly report - session 2026-11-27

Close **7308.2** · 4H structure **range** · VIX 23.81 · Sector breadth 64% above 50-day

## Did the agent learn from its mistakes?

| Ledger (live paper trades) | Trades | Win rate | Total pts | Avg pts | Profit factor | Max DD |
|---|---|---|---|---|---|---|
| Every signal | 20 | 15% | -110.0 | -5.50 | 0.25 | 136.0 |
| Only signals the agent chose to take | 20 | 15% | -110.0 | -5.50 | 0.25 | 136.0 |

If the second row beats the first, skipping its past losing conditions is working.

**On unseen backtest data** (the filter learned only from older data):

| | Trades | Win rate | Total pts | Avg pts | Profit factor | Max DD |
|---|---|---|---|---|---|---|
| All signals | 14 | 57% | 32.0 | 2.29 | 1.67 | 24.0 |
| After skipping losing conditions | 7 | 71% | 34.0 | 4.86 | 3.12 | 16.0 |

Mistake filter is **ON** for live alerts (it improved results on unseen data).

**Conditions that have lost the most** (backtest + live, live counts 3x):

| Condition | Win rate | Weighted trades |
|---|---|---|
| volatility = low | 10% | 39.0 |
| session = Asia / overnight | 15% | 58.0 |
| direction = long | 18% | 53.0 |
| weekday = Tue | 21% | 31.0 |
| weekday = Wed | 22% | 24.0 |
| vs_24h_move = against | 24% | 84.0 |

**Latest losing trades (post-mortems)**

- 2026-11-25 03:40 long @ 7164.5, -8.0 pts. Conditions: direction long, session London / pre-market, weekday Wed, gap_size large, volatility normal, entry_stretch extended, vs_24h_move against
- 2026-11-25 01:35 long @ 7160.8, -8.0 pts. Conditions: direction long, session Asia / overnight, weekday Wed, gap_size large, volatility low, entry_stretch near level, vs_24h_move against
- 2026-11-25 01:30 long @ 7163.2, -8.0 pts. Conditions: direction long, session Asia / overnight, weekday Wed, gap_size large, volatility low, entry_stretch extended, vs_24h_move against
- 2026-11-25 01:20 long @ 7169.0, -8.0 pts. Conditions: direction long, session Asia / overnight, weekday Wed, gap_size large, volatility low, entry_stretch extended, vs_24h_move against
- 2026-11-25 01:25 long @ 7169.5, -8.0 pts. Conditions: direction long, session Asia / overnight, weekday Wed, gap_size large, volatility low, entry_stretch extended, vs_24h_move against

## Daily bias model

- Call for the session after 2026-11-26: **DOWN** → actual +73.8 pts → **WRONG**
- Next session call: **DOWN** (confidence 0.02)
- Track record: 50% correct over 4 calls (last 30: 50%); 'always up' would have scored 50%

| Signal | Today | Learned weight | Hit rate |
|---|---|---|---|
| trend_50 | -1.00 | +0.93 | 50% of 4 |
| trend_200 | +1.00 | +0.88 | 50% of 4 |
| momentum_20d | -1.00 | +0.42 | 50% of 4 |
| rsi | -0.12 | -0.02 | 50% of 4 |
| last_day | +1.00 | +0.00 | 50% of 4 |
| structure_4h | +0.00 | +1.06 | 100% of 2 |
| fvg_position | -0.50 | +0.50 | 50% of 2 |
| vix_change_5d | +1.00 | +0.49 | 75% of 4 |
| breadth | +0.27 | +0.53 | 75% of 4 |

## Strategy backtest

Best settings on older data: target **10**, stop **8**, 5m swing 3. On newer unseen data: 14 trades, 32.0 pts. **Edge holds on unseen data.**
Full grid: [backtest.md](../backtest.md)

[Open your TradingView chart](https://www.tradingview.com/chart/M4XmmecI/?symbol=PEPPERSTONE%3AUS500) · Research only, not financial advice.
