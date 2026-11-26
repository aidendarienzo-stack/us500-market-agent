# US500 nightly report - session 2026-11-26

Close **7234.5** · 4H structure **range** · VIX 26.80 · Sector breadth 64% above 50-day

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
| After skipping losing conditions | 6 | 83% | 42.0 | 7.00 | 6.25 | 8.0 |

Mistake filter is **ON** for live alerts (it improved results on unseen data).

**Conditions that have lost the most** (backtest + live, live counts 3x):

| Condition | Win rate | Weighted trades |
|---|---|---|
| volatility = low | 10% | 39.0 |
| session = Asia / overnight | 14% | 60.0 |
| direction = long | 18% | 57.0 |
| weekday = Tue | 21% | 31.0 |
| weekday = Wed | 21% | 26.0 |
| vs_24h_move = against | 23% | 87.0 |

**Latest losing trades (post-mortems)**

- 2026-11-25 03:40 long @ 7164.5, -8.0 pts. Conditions: direction long, session London / pre-market, weekday Wed, gap_size large, volatility normal, entry_stretch extended, vs_24h_move against
- 2026-11-25 01:35 long @ 7160.8, -8.0 pts. Conditions: direction long, session Asia / overnight, weekday Wed, gap_size large, volatility low, entry_stretch near level, vs_24h_move against
- 2026-11-25 01:30 long @ 7163.2, -8.0 pts. Conditions: direction long, session Asia / overnight, weekday Wed, gap_size large, volatility low, entry_stretch extended, vs_24h_move against
- 2026-11-25 01:20 long @ 7169.0, -8.0 pts. Conditions: direction long, session Asia / overnight, weekday Wed, gap_size large, volatility low, entry_stretch extended, vs_24h_move against
- 2026-11-25 01:25 long @ 7169.5, -8.0 pts. Conditions: direction long, session Asia / overnight, weekday Wed, gap_size large, volatility low, entry_stretch extended, vs_24h_move against

## Daily bias model

- Call for the session after 2026-11-25: **DOWN** → actual +46.0 pts → **WRONG**
- Next session call: **DOWN** (confidence 0.07)
- Track record: 67% correct over 3 calls (last 30: 67%); 'always up' would have scored 33%

| Signal | Today | Learned weight | Hit rate |
|---|---|---|---|
| trend_50 | -1.00 | +0.97 | 67% of 3 |
| trend_200 | +1.00 | +0.82 | 33% of 3 |
| momentum_20d | -1.00 | +0.47 | 67% of 3 |
| rsi | -0.18 | -0.01 | 67% of 3 |
| last_day | +0.54 | -0.03 | 33% of 3 |
| structure_4h | +0.00 | +1.06 | 100% of 2 |
| fvg_position | +0.00 | +0.50 | 50% of 2 |
| vix_change_5d | +0.29 | +0.47 | 67% of 3 |
| breadth | +0.27 | +0.51 | 67% of 3 |

## Strategy backtest

Best settings on older data: target **10**, stop **8**, 5m swing 3. On newer unseen data: 14 trades, 32.0 pts. **Edge holds on unseen data.**
Full grid: [backtest.md](../backtest.md)

[Open your TradingView chart](https://www.tradingview.com/chart/M4XmmecI/?symbol=PEPPERSTONE%3AUS500) · Research only, not financial advice.
