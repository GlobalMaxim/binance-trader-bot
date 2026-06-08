# Why This Trading System Loses Money

## Current State (post-refactor)

`check_exit()` is now wired in. ATR-based SL/TP/trailing/regime/time exits are active. Fixed 2%/4% stops are gone. This fixed the biggest structural flaw, but deep problems remain.

---

## Insight 1: Long-only in all regimes — strategy is blind in half the market

The strategy generates both BUY and SELL signals, but only BUY can open a position. SELL signals require `pos is not None` in `evaluate_sell()` — which always returns `REJECTED / NO_OPEN_POSITION` because short selling was never implemented.

Result: in TREND_DOWN regimes, the strategy computes indicators, generates SELL signals, writes them to the DB, risk-rejects every one, and does nothing. All that compute is wasted. The system can only profit when price goes up.

Crypto bear moves are violent (BTC drops 5-10% in hours). The system watches them go by, makes zero trades, and the equity curve flatlines. Over a full market cycle, it misses roughly half the directional opportunities.

**Expected**: multi-directional system capturing both up and down moves. **Actual**: long-only by accident of incomplete implementation.

---

## Insight 2: Regime detection arrives 28 bars late — entries hit near the move's end

ADX uses EWM smoothing with `min_periods=period*2=28`. On 1-minute candles, that's a 28-minute lag before ADX converges. `detect_regime()` also requires three-way AND alignment: `adx >= threshold & +DI > -DI & EMA_20 > EMA_50`.

During a real trend start: price rips upward, +DI crosses -DI within 5-10 bars, but ADX is still climbing from 12 toward 20. The three-way AND doesn't all light up until bar 20-28. By then, the move has largely run its course. The BUY signal fires near the local top.

The strategy then enters, the move stalls or reverses, and either the trailing stop or a TIME_EXIT closes it at a small loss. The system is structurally late — not because the entry logic is wrong, but because the regime classifier that gates which entry logic to use is too slow.

**Expected**: regime detected within 5-10 bars of transition. **Actual**: 20-28 bar lag, entry at exhaustion.

---

## Insight 3: SELL signals never open shorts — but they DO close longs at suboptimal times

When a SELL signal fires in `_handle_sell()`, the system checks: is there an open long position? If yes → market sell immediately. Exit reason is logged as the hardcoded string `"strategy_exit"`.

This conflates several distinct exit catalysts into one bucket:
- RSI overbought in TREND_DOWN (trend_sell)
- RSI overbought in RANGE (range_sell)
- MACD peak + near BB upper + volume spike

Some of these are valid exit signals. Others close a long that's still trending because the regime detection lagged (Insight 2) and the system temporarily misclassified the regime, generated a contradictory SELL, and exited early.

Without `exit_reason` on the positions table, there's no way to tell which SELLs were profitable exits and which were premature. The hardcoded `"strategy_exit"` tag makes all strategy-driven closes look identical.

**Expected**: exits differentiated by catalyst. **Actual**: all strategy exits tagged identically — indistinguishable.

---

## Insight 4: ATR-based SL at 1.5x on 1-minute crypto is eaten by noise

Current config: `sl_atr_mult=1.5`, `tp_atr_mult=3.0`. On BTC/USDT 1m, typical ATR is $80-150. That puts SL at $120-225 from entry — roughly 0.24-0.45% on a $50k BTC.

1-minute crypto bars routinely wick 0.3-0.5% in both directions within single bars. The low of the bar breaches the SL level, the position gets stopped out, and the price reverses back up on the next bar. This is the classic noise-exit pattern: SL too tight for the timeframe's natural volatility.

The trailing stop at `trail_activate_atr=2.0` (2x ATR to activate) and `trail_atr_mult=1.0` (1x ATR trail) means once price moves 2 ATR in profit, the trailing stop tightens to within 1 ATR of the high water mark. In practice: price moves +2.5%, trailing stop activates, a single 1 ATR pullback stops it out at +1.5%. The trade was right directionally but captured only 60% of the move.

The `TP at 3.0x ATR` is rarely hit because the trailing stop fires first.

**Expected**: SL wide enough to survive noise, exits capture the full move. **Actual**: noise stops + premature trailing exits chop winning trades short.

---

## Insight 5: Range entries are too rare to matter — strategy starves for signals

Range mode requires four stacked conditions on one bar: ADX < 20, RSI ≤ 32 (or ≥ 68 for sell), price within 0.25 BB width of band, MACD histogram at a trough/peak, AND volume ≥ 0.5× MA. Three of four must pass.

On 1-minute crypto:
- ADX stays elevated most of the time. True ranges (ADX < 20) are brief — maybe 5-10 bars per hour.
- RSI in crypto 1m oscillates between 35-65. It rarely touches 32 or 68. The 32/68 thresholds were designed for daily equity data where RSI extremes signal genuine exhaustion. On 1m crypto, RSI 32 is not "oversold" — it's a normal Tuesday.
- Volume filter at 0.5× MA is reasonable but becomes the tiebreaker that kills entries when RSI and BB barely qualify.

Net effect: range mode generates single-digit signals per day across all symbols. Most trading days, every signal comes from trend mode. The range/trend dual-mode architecture is effectively single-mode.

**Expected**: alternating trend-following and mean-reversion logic depending on conditions. **Actual**: trend mode only, range mode is dormant.

---

## Root Cause Summary

| Rank | Component | Problem | Effect |
|---|---|---|---|
| 1 | **Entry timing** | ADX 28-bar lag → regime detected too late | Buys near local tops, sells near local bottoms |
| 2 | **Direction coverage** | No short selling → half of signals wasted | Zero profit in downtrends |
| 3 | **Exit calibration** | SL at 1.5 ATR on 1m crypto → noise-exited | Winning trades stopped out early |
| 4 | **Exit attribution** | All strategy exits tagged `"strategy_exit"` | Can't measure which exit logic works |
| 5 | **Signal starvation** | Range thresholds too tight for crypto 1m | Range mode dormant, misses mean-reversion opportunities |

The system's core problem is not bad ideas — the dual-mode strategy, ATR-based exits, and risk gating are sound in principle. The problem is calibration mismatch: parameters tuned for daily equity data running on 1-minute crypto, and missing the short side entirely.