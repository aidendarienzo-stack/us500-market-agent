# US500 nightly report - session 2026-11-23

Close **7262.0** · 4H structure **bearish** · VIX 26.62 · Sector breadth 45% above 50-day

## Did the agent learn from its mistakes?

| Ledger (live paper trades) | Trades | Win rate | Total pts | Avg pts | Profit factor | Max DD |
|---|---|---|---|---|---|---|
| Every signal | 8 | 38% | -14.0 | -1.75 | 0.72 | 40.0 |
| Only signals the agent chose to take | 8 | 38% | -14.0 | -1.75 | 0.72 | 40.0 |

If the second row beats the first, skipping its past losing conditions is working.

**On unseen backtest data** (the filter learned only from older data):

| | Trades | Win rate | Total pts | Avg pts | Profit factor | Max DD |
|---|---|---|---|---|---|---|
| All signals | 14 | 64% | 50.0 | 3.57 | 2.25 | 16.0 |
| After skipping losing conditions | 6 | 67% | 24.0 | 4.00 | 2.50 | 16.0 |

Mistake filter is **OFF** for live alerts (it has not proven it helps yet, so every signal is alerted).

**Conditions that have lost the most** (backtest + live, live counts 3x):

| Condition | Win rate | Weighted trades |
|---|---|---|
| volatility = normal | 34% | 37.0 |
| session = Asia / overnight | 37% | 25.0 |
| weekday = Fri | 40% | 8.0 |
| entry_stretch = near level | 41% | 37.0 |
| weekday = Wed | 42% | 10.0 |
| vs_24h_move = against | 43% | 49.0 |

**Latest losing trades (post-mortems)**

- 2026-11-23 16:10 short @ 7259.0, -10.0 pts. Conditions: direction short, session Asia / overnight, weekday Mon, gap_size large, volatility normal, entry_stretch extended, vs_24h_move against
- 2026-11-23 16:05 short @ 7260.2, -10.0 pts. Conditions: direction short, session Asia / overnight, weekday Mon, gap_size large, volatility normal, entry_stretch extended, vs_24h_move against
- 2026-11-23 16:00 short @ 7256.5, -10.0 pts. Conditions: direction short, session New York cash session, weekday Mon, gap_size large, volatility normal, entry_stretch extended, vs_24h_move against
- 2026-11-23 15:05 short @ 7259.8, -10.0 pts. Conditions: direction short, session New York cash session, weekday Mon, gap_size large, volatility normal, entry_stretch extended, vs_24h_move against
- 2026-11-23 11:10 short @ 7260.2, -10.0 pts. Conditions: direction short, session New York cash session, weekday Mon, gap_size large, volatility high, entry_stretch near level, vs_24h_move against

## Daily bias model

- Next session call: **DOWN** (confidence 0.50)

| Signal | Today | Learned weight | Hit rate |
|---|---|---|---|
| trend_50 | -1.00 | +1.00 | - |
| trend_200 | +1.00 | +0.80 | - |
| momentum_20d | -1.00 | +0.50 | - |
| rsi | -0.18 | +0.00 | - |
| last_day | +1.00 | +0.00 | - |
| structure_4h | -1.00 | +1.00 | - |
| fvg_position | -0.50 | +0.50 | - |
| vix_change_5d | -0.81 | +0.50 | - |
| breadth | -0.09 | +0.50 | - |

## Strategy backtest

Best settings on older data: target **10**, stop **8**, 5m swing 3. On newer unseen data: 14 trades, 50.0 pts. **Edge holds on unseen data.**
Full grid: [backtest.md](../backtest.md)

[Open your TradingView chart](https://www.tradingview.com/chart/M4XmmecI/?symbol=PEPPERSTONE%3AUS500) · Research only, not financial advice.
