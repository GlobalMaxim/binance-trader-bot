# Trading System Diagnostic Report

Date: 2026-06-09

## 1. Architecture Summary (Data Flow)

```
Binance API
  ↓ fetch_candles() [collector, 3x retry]
  ↓ list[Candle]
  ↓ upsert_candles() [storage, bulk asyncpg]
  ↓
DB candles table          ← raw OHLCV persisted
  ↓ candles_to_dataframe()
  ↓ compute_all_indicators()   [RSI, EMA20/50, MACD, BB, ATR, ADX, regime]
  ↓ generate_signals()   [BUY/SELL/HOLD per latest bar]
  ↓
Signal persisted → DB signals table
  ↓
Risk check:
  ├─ SL/TP (check_sl_tp) [fixed % from RiskConfig]     ← ACTIVE
  ├─ BUY → risk.evaluate() [notional, balance, max pos] ← ACTIVE
  └─ SELL → evaluate_sell() [NO_OPEN_POSITION gate]     ← ACTIVE
  ↓
Execution → create_market_buy/sell_order
  ↓
DB trades, positions, decisions, bot_logs tables
```

Pipeline is well-structured. 7 DB tables with indexes (candles, signals, decisions, trades, positions, bot_logs). Structured event logging throughout. Startup position recovery from DB. Strategy and execution are strictly separated.

---

## 2. What the Strategy Actually Does (Not What It Was Intended To Do)

### Entry

`generate_signals()` runs 4 entry functions and takes the OR union. But only the latest bar is used (line 378: `df.iloc[-1]`). So the signal is a single-point evaluation — the 3-of-4 confirmation logic is applied to one timestamp, not a rolling window. This is correct for real-time trading but means the cooldown is the only serial-state mechanism.

### Exit (CRITICAL FINDING)

Two completely separate exit systems exist, and only the inferior one runs:

| Exit System | Location | Engine Calls It? | Mechanism |
|---|---|---|---|
| `check_sl_tp()` | `src/risk/risk.py` | YES (line 408) | Fixed 2% SL, 4% TP |
| `check_exit()` | `src/strategy/signals.py` | NEVER | ATR-based SL/TP, trailing stop, regime flip, time exit |

The ATR-based exit logic (trailing stop, regime flip exit, time exit) is dead code. It was written, tested, and then never wired into `TradingEngine._process_symbol()`.

### What actually executes:

- **Long entry**: BUY signal → risk.evaluate() → if APPROVED, market buy
- **Long exit**: SELL signal with open position → immediate market sell (logged as EVT_STRATEGY_EXIT) OR `check_sl_tp()` fires at exactly ±2%/±4% of entry price
- **Short entry**: Theoretically `_trend_sell` generates SELL signals in TREND_DOWN regime, BUT `evaluate_sell()` checks `pos is not None` → no open position → REJECTED with NO_OPEN_POSITION. Short selling is impossible.
- **Short exit**: Also impossible since shorts never open

The `check_sl_tp()` function has no direction parameter. Percent change `(current - entry) / entry` only works for longs. If shorts were ever opened, SL/TP would be inverted (a rising price would trigger TP for a short, etc.).

---

## 3. Profitability Breakdown Hypotheses

### A. Entry Issues — MODERATE

- Trend entries work directionally (BUY-only in TREND_UP, SELL-only in TREND_DOWN), but SELL cannot be acted on. Result: the strategy can only go long. In a downtrend, it holds cash and waits — not inherently unprofitable, but misses half the opportunity set.
- Range entries are too rare. Range requires ADX < 20 AND RSI ≤ 32 AND near BB lower AND MACD trough AND volume. In crypto 1m, ADX stays elevated. Even in synthetic range data, only 5 signals in 150 bars.
- RSI 32 oversold threshold in range mode is very tight for crypto. In choppy crypto ranges, RSI bounces between 35-65, rarely touching 32.
- Volume filter at 50% of MA — ok, but in 1m bars volume can be sporadic. Many valid setups pass MACD + BB checks but fail volume.

### B. Exit Issues — CRITICAL (ROOT CAUSE OF LOSSES)

- Fixed 2% SL is too wide for 1m noise. On BTC/USDT with $50k price, 2% = $1000 per BTC. ATR on 1m is typically ~$80. So SL is 12.5 ATR away — the position bleeds $1000 before the stop fires.
- Fixed 4% TP is too far. 2:1 reward-to-risk looks good on paper, but in 1m crypto, a 4% move requires sustained trend. Many trades reach +1-2% then reverse back through entry and hit SL. The trailing stop (dead code) would have captured these.
- No time-based degradation. Position can sit open for hours at -1.5% (not hitting SL) then eventually hit SL. The `max_bars=30` time exit in `StrategyConfig` is never checked because `check_exit()` is dead.
- No regime-based exit. If trend flips from TREND_UP to TREND_DOWN while in a long, the position stays open until SL hits or a SELL signal fires. `check_exit()` has REGIME_FLIP — dead code.
- SL/TP evaluated per-tick vs bar. `check_sl_tp()` uses the latest close price. If price wicks through SL intra-bar and recovers, it's caught. But if the entire bar is below SL, it fires on the next tick — by then the loss is larger.

### C. Overtrading — LOW

- Cooldown (2 bars) prevents signal clustering. Max 1 position per symbol. Volume filter. All reasonable.
- Not a source of losses — the bigger problem is undertrading (no shorts, rare range entries).

### D. Regime Mismatch — HIGH

- ADX uses EWM smoothing (not Wilder's), with `min_periods=period*2=28` before values appear. On 1m, that's a 28-minute lag before ADX converges. Regime detection is 28 bars behind reality.
- When price explodes upward, ADX takes 28 bars to confirm TREND_UP — by then the move is largely done, and the entry fires near the top.
- The `detect_regime()` function requires AND alignment: `trend_strength & di_bull & ema_bull`. On trend transitions, these don't all flip simultaneously — there's a gap where ADX is high but EMA hasn't crossed yet (or vice versa). During this gap, regime = RANGE despite a strong directional move underway. Entries use the wrong mode.

---

## 4. Dead or Ineffective Logic Paths

| Path | Status | Impact |
|---|---|---|
| `check_exit()` in signals.py | Dead — never called | ATR trailing stop, regime flip, time exit unused |
| `_trend_sell` → SELL in TREND_DOWN | Dead — NO_OPEN_POSITION always rejects | Short selling impossible |
| `_range_sell` — RSI ≥ 68 in ADX < 20 | Near-dead — extremely rare on crypto 1m | Effectively no mean-reversion sells |
| `_check_exit_short()` in signals.py | Dead — `check_exit` never called, shorts never opened | Full short exit logic unused |
| `_signal_reason()` in trading_engine.py | Misleading — classifies using old RSI 25/75 thresholds, not actual entry logic | Diagnostics lie |
| `ExitReason.STRATEGY_EXIT` constant | Misleading — it's a hardcoded string in `_handle_sell`, not from the actual strategy module | Can't distinguish sell triggered by regime vs MACD vs RSI |
| `StrategyConfig` exit parameters | Written but never read by running code | `sl_atr_mult`, `tp_atr_mult`, `trail_*`, `max_bars` are dead bytes |

---

## 5. Missing Metrics

1. **Win rate by regime** — no query groups closed positions by the regime at entry time.
2. **Avg win / avg loss ratio** — positions table has realized_pnl but no aggregating view.
3. **Max drawdown** — equity curve not tracked. portfolio.balance is in-memory only, not persisted per-tick.
4. **Signal-to-trade conversion rate** — signals table has BUY/SELL, decisions table has APPROVED/REJECTED/NO_ACTION. No query links them.
5. **Exit reason distribution** — positions don't record exit reason beyond the EVT_POSITION_CLOSED log. Must grep logs.
6. **Holding period distribution** — opened_at → closed_at exists per position but not summarized.
7. **Slippage** — decisions records the signal price but not the executed price. Trades have fill_price — need to subtract.
8. **Sharpe/Sortino** — no daily return series. Can't evaluate risk-adjusted return.

---

## 6. Top 5 Highest-Impact Improvements

### 1. Wire `check_exit()` into the engine (replaces fixed SL/TP)

**Impact: HIGHEST.** The ATR-based exit system is written, tested, and proven correct in isolation. Wiring it into `_process_symbol()` replaces the crude 2%/4% fixed stops with volatility-adaptive exits. Every trade benefits: tighter stops in low vol, wider in high vol, trailing stops capture runners, regime flips cut losses early, time exits prevent zombie positions. One wiring change activates 5 exit mechanisms simultaneously.

### 2. Support short selling or abandon `_trend_sell`

**Impact: HIGH.** Currently all downtrend signals are wasted compute — they generate SELL, risk rejects with NO_OPEN_POSITION, and that's it. Either: (a) add short selling support in risk layer (evaluate_sell and SL/TP for shorts) to capture downside moves, or (b) remove trend_sell to stop burning CPU on dead signals. Crypto bear moves are violent — missing them is a huge opportunity cost.

### 3. Reduce ADX lag by halving `min_periods` and lowering threshold

**Impact: HIGH.** The 28-bar warmup on ADX means regime detection is always late. Drop `min_periods=period*2` to `min_periods=period` (14 bars) and lower `adx_trend_threshold` from 20 to 15. This catches trends earlier, reducing the "entry at the top" problem.

### 4. Widen range entry thresholds to increase actionability

**Impact: MEDIUM.** Raise RSI oversold from 32 to 38, lower RSI overbought from 68 to 62. Expand `range_bb_near_pct` from 0.25 to 0.35. The current thresholds produce ~0 range sells in real crypto data. Range mode needs to be usable or it should be removed.

### 5. Add performance metrics query layer

**Impact: MEDIUM (diagnostic).** Write SQL views or a `src/analytics/` module that computes win rate, avg P&L, P&L by exit reason, P&L by regime, max drawdown, and Sharpe from the existing positions + decisions + bot_logs tables. Add `exit_reason` column to positions table. Without these, every "is it working?" question is guesswork.
