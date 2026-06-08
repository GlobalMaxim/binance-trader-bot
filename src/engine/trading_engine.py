import asyncio
import logging
import subprocess
from datetime import datetime, timezone

import asyncpg
import ccxt.async_support as ccxt
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.collector.ohlcv import fetch_candles
from src.config import Config
from src.engine.portfolio import PortfolioState
from src.execution.executor import OrderResult, execute_market_buy, execute_market_sell
from src.features.indicators import candles_to_dataframe, compute_all_indicators
from src.risk import risk
from src.risk.risk import RejectReason, RiskConfig, RiskDecision, SLTPTrigger, check_sl_tp, evaluate_sell, position_size
from src.storage.candle_repo import upsert_candles
from src.storage.decision_repo import DecisionRecord, save_decision
from src.storage.log_repo import (
    CAT_ENGINE,
    CAT_EXECUTION,
    CAT_RISK,
    CAT_STRATEGY,
    EVT_DECISION_APPROVED,
    EVT_ENGINE_STARTED,
    EVT_EXCHANGE_ERROR,
    EVT_ORDER_FILLED,
    EVT_POSITION_CLOSED,
    EVT_POSITION_OPENED,
    EVT_RISK_REJECTED,
    EVT_SIGNAL_GENERATED,
    EVT_SL_HIT,
    EVT_STRATEGY_EXIT,
    EVT_TICK_START,
    EVT_TP_HIT,
    EVT_UNEXPECTED_EXCEPTION,
    safe_write_log,
)
from src.storage.position_repo import close_position as db_close_position
from src.storage.position_repo import load_open_positions
from src.storage.position_repo import open_position as db_open_position
from src.storage.signal_repo import SignalRecord, insert_signal
from src.storage.trade_repo import save_trade
from src.strategy.signals import Signal, generate_signals

log = logging.getLogger(__name__)

_MIN_CANDLES = 60  # enough for all indicators (EMA-50 + MACD-26 + warmup)


def _get_strategy_version() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def _f(val: object) -> float | None:
    """NaN/None → None so asyncpg can write NULL."""
    if val is None:
        return None
    f = float(val)  # type: ignore[arg-type]
    return None if pd.isna(f) else f


def _signal_reason(df: pd.DataFrame, signal: Signal) -> str | None:
    if signal == Signal.HOLD:
        return None
    row = df.iloc[-1]
    rsi = float(row["rsi"])
    parts: list[str] = []
    if signal == Signal.BUY:
        if rsi < 25.0:
            parts.append("rsi_deep_oversold")
        else:
            parts.append("rsi_oversold")
            if float(row["ema_20"]) > float(row["ema_50"]):
                parts.append("ema_cross")
            if len(df) >= 2 and float(df["macd_hist"].iloc[-1]) > float(df["macd_hist"].iloc[-2]):
                parts.append("macd_turning")
    else:  # SELL
        if rsi > 75.0:
            parts.append("rsi_deep_overbought")
        else:
            parts.append("rsi_overbought")
            if float(row["ema_20"]) < float(row["ema_50"]):
                parts.append("ema_cross")
            if len(df) >= 2 and float(df["macd_hist"].iloc[-1]) < float(df["macd_hist"].iloc[-2]):
                parts.append("macd_turning")
    return "+".join(parts) if parts else None


class TradingEngine:
    def __init__(
        self,
        cfg: Config,
        exchange: ccxt.binance,
        portfolio: PortfolioState,
        pool: asyncpg.Pool,
        session_factory: async_sessionmaker[AsyncSession],
        risk_config: RiskConfig | None = None,
    ) -> None:
        self.cfg = cfg
        self.exchange = exchange
        self.portfolio = portfolio
        self.pool = pool
        self.session_factory = session_factory
        self.risk_config = risk_config or RiskConfig()
        self._strategy_version = _get_strategy_version()

    # ── DB log wrapper ────────────────────────────────────────────────────

    async def _log(
        self,
        *,
        level: str,
        category: str,
        event: str,
        symbol: str | None = None,
        message: str,
        data: dict | None = None,
        trade_id: int | None = None,
        decision_id: int | None = None,
    ) -> None:
        await safe_write_log(
            self.session_factory,
            level=level,
            category=category,
            event=event,
            symbol=symbol,
            message=message,
            data=data,
            trade_id=trade_id,
            decision_id=decision_id,
        )

    # ── Shared persistence helpers ────────────────────────────────────────

    async def _make_decision(
        self,
        signal_id: int | None,
        decision: str,
        reject_reason: str | None,
        proposed_qty: float,
    ) -> int:
        """Persist a decision row pre-filled with the current portfolio snapshot."""
        return await save_decision(
            self.session_factory,
            DecisionRecord(
                signal_id=signal_id,
                decision=decision,
                reject_reason=reject_reason,
                proposed_qty=proposed_qty,
                capital_pct=self.risk_config.capital_pct,
                min_notional=self.risk_config.min_notional,
                available_balance=self.portfolio.balance,
                open_positions=len(self.portfolio.positions),
            ),
        )

    async def _execute_order(
        self,
        side: str,
        symbol: str,
        qty: float,
        decision_id: int,
        fallback_price: float,
    ) -> tuple[OrderResult, float, datetime]:
        """Execute a market order. Logs EVT_EXCHANGE_ERROR and re-raises on failure.
        Returns (result, fill_price, filled_at).
        """
        execute = execute_market_buy if side == "buy" else execute_market_sell
        try:
            result = await execute(self.exchange, symbol, qty)
        except Exception as exc:
            await self._log(
                level="ERROR",
                category=CAT_EXECUTION,
                event=EVT_EXCHANGE_ERROR,
                symbol=symbol,
                message=f"exchange error on {side.upper()}  {symbol}: {exc}",
                data={"error": type(exc).__name__, "endpoint": f"createMarket{side.capitalize()}Order"},
                decision_id=decision_id,
            )
            raise
        fill_price = result.fill_price or fallback_price
        filled_at = result.filled_at or datetime.now(timezone.utc)
        return result, fill_price, filled_at

    async def _save_fill(
        self,
        result: OrderResult,
        symbol: str,
        side: str,
        fill_price: float,
        decision_id: int,
    ) -> int:
        """Persist trade row and log EVT_ORDER_FILLED. Returns trade_id."""
        trade_id = await save_trade(
            self.session_factory,
            symbol=symbol,
            side=side,
            fill_price=fill_price,
            quantity=result.quantity,
            status=result.status,
            exchange=result.exchange,
            order_id=result.order_id,
            cost=result.cost,
            fee=result.fee,
            filled_at=result.filled_at,
            decision_id=decision_id,
        )
        await self._log(
            level="INFO",
            category=CAT_EXECUTION,
            event=EVT_ORDER_FILLED,
            symbol=symbol,
            message=f"{side.upper()} filled: {result.quantity} {symbol} @ {fill_price:.4f}",
            data={"side": side, "quantity": result.quantity, "fill_price": fill_price,
                  "cost": result.cost, "order_id": result.order_id},
            trade_id=trade_id,
            decision_id=decision_id,
        )
        return trade_id

    async def _finalize_open(
        self,
        symbol: str,
        trade_id: int,
        qty: float,
        fill_price: float,
        opened_at: datetime,
        decision_id: int,
    ) -> int:
        """Write position to DB, log EVT_POSITION_OPENED, update portfolio. Returns position_id."""
        position_id = await db_open_position(
            self.session_factory,
            symbol=symbol,
            buy_trade_id=trade_id,
            quantity=qty,
            entry_price=fill_price,
            opened_at=opened_at,
        )
        await self._log(
            level="INFO",
            category=CAT_ENGINE,
            event=EVT_POSITION_OPENED,
            symbol=symbol,
            message=f"position opened  {symbol}  qty={qty}  entry={fill_price:.4f}",
            data={"symbol": symbol, "quantity": qty, "entry_price": fill_price},
            trade_id=trade_id,
            decision_id=decision_id,
        )
        self.portfolio.open_position(symbol, qty, fill_price, db_id=position_id)
        return position_id

    async def _finalize_close(
        self,
        symbol: str,
        trade_id: int,
        fill_price: float,
        closed_at: datetime,
        exit_reason: str,
        decision_id: int,
        entry_price: float,
    ) -> tuple[float, int]:
        """Close position in portfolio + DB, log EVT_POSITION_CLOSED. Returns (pnl, position_id)."""
        pnl, position_id = self.portfolio.close_position(symbol, fill_price)
        await db_close_position(
            self.session_factory,
            position_id=position_id,
            sell_trade_id=trade_id,
            exit_price=fill_price,
            realized_pnl=pnl,
            closed_at=closed_at,
        )
        await self._log(
            level="INFO",
            category=CAT_ENGINE,
            event=EVT_POSITION_CLOSED,
            symbol=symbol,
            message=f"position closed ({exit_reason})  {symbol}  pnl={pnl:+.4f}  exit={fill_price:.4f}",
            data={"symbol": symbol, "realized_pnl": pnl, "entry_price": entry_price,
                  "exit_price": fill_price, "exit_reason": exit_reason},
            trade_id=trade_id,
            decision_id=decision_id,
        )
        return pnl, position_id

    # ── Main loop ─────────────────────────────────────────────────────────

    async def run(self) -> None:
        await self._recover_positions()
        log.info(
            "TradingEngine started  symbols=%s  timeframe=%s  balance=%.2f USDT  open_positions=%d",
            self.cfg.symbols, self.cfg.timeframe,
            self.portfolio.balance, len(self.portfolio.positions),
        )
        await self._log(
            level="INFO",
            category=CAT_ENGINE,
            event=EVT_ENGINE_STARTED,
            message=(
                f"TradingEngine started  symbols={self.cfg.symbols}"
                f"  timeframe={self.cfg.timeframe}"
                f"  balance={self.portfolio.balance:.2f}"
                f"  open_positions={len(self.portfolio.positions)}"
            ),
            data={
                "symbols": self.cfg.symbols,
                "timeframe": self.cfg.timeframe,
                "balance": self.portfolio.balance,
                "open_positions": list(self.portfolio.positions.keys()),
            },
        )
        while True:
            await self._tick()
            await asyncio.sleep(self.cfg.poll_interval)

    async def _recover_positions(self) -> None:
        rows = await load_open_positions(self.session_factory)
        for row in rows:
            self.portfolio.restore_position(
                symbol=row.symbol,
                quantity=row.quantity,
                entry_price=row.entry_price,
                db_id=row.position_id,
            )
            log.info(
                "recovered position  %s  qty=%.6f  entry=%.4f  db_id=%d",
                row.symbol, row.quantity, row.entry_price, row.position_id,
            )

    async def _tick(self) -> None:
        await self._log(
            level="INFO",
            category=CAT_ENGINE,
            event=EVT_TICK_START,
            message=f"tick  balance={self.portfolio.balance:.2f}  open={list(self.portfolio.positions)}",
            data={
                "balance": self.portfolio.balance,
                "open_positions": list(self.portfolio.positions.keys()),
                "symbols": self.cfg.symbols,
            },
        )
        for symbol in self.cfg.symbols:
            try:
                await self._process_symbol(symbol)
            except Exception as exc:
                log.error("tick error  %s: %s", symbol, exc)
                await self._log(
                    level="ERROR",
                    category=CAT_ENGINE,
                    event=EVT_UNEXPECTED_EXCEPTION,
                    symbol=symbol,
                    message=f"unexpected exception  {symbol}: {exc}",
                    data={"error": type(exc).__name__, "detail": str(exc)},
                )

    # ── Per-symbol pipeline ───────────────────────────────────────────────

    async def _process_symbol(self, symbol: str) -> None:
        # 1. Fetch + persist candles
        candles = await fetch_candles(
            self.exchange, symbol, self.cfg.timeframe, self.cfg.fetch_limit
        )
        if len(candles) < _MIN_CANDLES:
            log.warning("not enough candles for %s (%d), skipping", symbol, len(candles))
            return
        await upsert_candles(self.pool, candles)

        # 2. Indicators + signal
        df = candles_to_dataframe(candles)
        df = compute_all_indicators(df)
        signal = Signal(generate_signals(df).iloc[-1])
        row = df.iloc[-1]
        current_price = float(row["close"])
        reason = _signal_reason(df, signal)

        # 3. Persist signal
        signal_id = await insert_signal(
            self.session_factory,
            SignalRecord(
                symbol=symbol,
                timeframe=self.cfg.timeframe,
                ts=df.index[-1].to_pydatetime(),
                signal=signal.value,
                rsi=_f(row.get("rsi")),
                ema_fast=_f(row.get("ema_20")),
                ema_slow=_f(row.get("ema_50")),
                macd=_f(row.get("macd")),
                macd_signal=_f(row.get("macd_signal")),
                macd_hist=_f(row.get("macd_hist")),
                bb_upper=_f(row.get("bb_upper")),
                bb_middle=_f(row.get("bb_middle")),
                bb_lower=_f(row.get("bb_lower")),
                close_price=current_price,
                strategy_version=self._strategy_version,
                reason=reason,
            ),
        )

        # 4. SL/TP — RiskManager is the only component that closes without a SELL signal
        if self.portfolio.has_position(symbol):
            trigger = check_sl_tp(
                self.portfolio.positions[symbol].entry_price, current_price, self.risk_config
            )
            if trigger is not None:
                await self._handle_risk_exit(symbol, current_price, trigger)
                return  # skip strategy for this tick

        upnl = self.portfolio.unrealized_pnl(symbol, current_price)
        log.info(
            "signal=%-4s  %s  price=%.4f  balance=%.2f  upnl=%.4f",
            signal, symbol, current_price, self.portfolio.balance, upnl,
        )

        # 5. Strategy dispatch
        if signal == Signal.BUY:
            await self._log(
                level="INFO", category=CAT_STRATEGY, event=EVT_SIGNAL_GENERATED, symbol=symbol,
                message=f"BUY signal  {symbol}  price={current_price:.4f}  reason={reason}",
                data={"signal": "BUY", "rsi": _f(row.get("rsi")), "close_price": current_price, "reason": reason},
            )
            await self._handle_buy(symbol, current_price, signal_id)
        elif signal == Signal.SELL:
            await self._log(
                level="INFO", category=CAT_STRATEGY, event=EVT_SIGNAL_GENERATED, symbol=symbol,
                message=f"SELL signal  {symbol}  price={current_price:.4f}  reason={reason}",
                data={"signal": "SELL", "rsi": _f(row.get("rsi")), "close_price": current_price, "reason": reason},
            )
            await self._handle_sell(symbol, current_price, signal_id)
        else:
            # HOLD: persist NO_ACTION for full signal coverage; no trade executed
            await self._make_decision(
                signal_id, RiskDecision.NO_ACTION.value, RejectReason.HOLD_SIGNAL.value, 0.0
            )

    # ── Forced exit (SL / TP) ─────────────────────────────────────────────

    async def _handle_risk_exit(
        self, symbol: str, current_price: float, trigger: SLTPTrigger
    ) -> None:
        pos = self.portfolio.positions[symbol]
        entry_price = pos.entry_price  # capture before close_position pops it
        change_pct = (current_price - entry_price) / entry_price
        evt = EVT_SL_HIT if trigger == SLTPTrigger.SL_HIT else EVT_TP_HIT

        decision_id = await self._make_decision(
            None, RiskDecision.APPROVED.value, trigger.value, pos.quantity
        )
        log.warning(
            "%s forced exit  %s  entry=%.4f  current=%.4f  chg=%.2f%%  decision_id=%d",
            trigger.value, symbol, entry_price, current_price, change_pct * 100, decision_id,
        )
        await self._log(
            level="WARNING" if trigger == SLTPTrigger.SL_HIT else "INFO",
            category=CAT_RISK, event=evt, symbol=symbol,
            message=f"{trigger.value}  {symbol}  entry={entry_price:.4f}  current={current_price:.4f}  chg={change_pct:+.2%}",
            data={"trigger": trigger.value, "entry_price": entry_price,
                  "current_price": current_price, "change_pct": round(change_pct, 6)},
            decision_id=decision_id,
        )

        result, fill_price, closed_at = await self._execute_order(
            "sell", symbol, pos.quantity, decision_id, current_price
        )
        trade_id = await self._save_fill(result, symbol, "sell", fill_price, decision_id)
        pnl, position_id = await self._finalize_close(
            symbol, trade_id, fill_price, closed_at, trigger.value, decision_id, entry_price
        )
        log.info(
            "%s executed  %s  qty=%.6f  fill=%.4f  pnl=%+.4f  position_id=%d  balance=%.2f",
            trigger.value, symbol, result.quantity, fill_price, pnl, position_id, self.portfolio.balance,
        )

    # ── Strategy-driven entry ─────────────────────────────────────────────

    async def _handle_buy(self, symbol: str, price: float, signal_id: int) -> None:
        proposed_qty = position_size(price, self.portfolio.balance, self.risk_config.capital_pct)
        decision_enum, approved_qty, reject_reason = risk.evaluate(
            symbol=symbol,
            price=price,
            capital=self.portfolio.balance,
            available_balance=self.portfolio.balance,
            positions={s: [p] for s, p in self.portfolio.positions.items()},
            config=self.risk_config,
        )
        decision_id = await self._make_decision(
            signal_id, decision_enum.value,
            reject_reason.value if reject_reason else None,
            proposed_qty,
        )

        if decision_enum == RiskDecision.REJECTED:
            log.warning("BUY rejected  %s  reason=%s  decision_id=%d", symbol, reject_reason, decision_id)
            await self._log(
                level="WARNING", category=CAT_RISK, event=EVT_RISK_REJECTED, symbol=symbol,
                message=f"BUY rejected  {symbol}  reason={reject_reason}",
                data={"reason": reject_reason.value if reject_reason else None,
                      "available": self.portfolio.balance, "required": proposed_qty * price},
                decision_id=decision_id,
            )
            return

        log.info("BUY approved  %s  qty=%.6f  price=%.4f  decision_id=%d", symbol, approved_qty, price, decision_id)
        await self._log(
            level="INFO", category=CAT_RISK, event=EVT_DECISION_APPROVED, symbol=symbol,
            message=f"BUY approved  {symbol}  qty={approved_qty:.6f}  price={price:.4f}",
            data={"side": "buy", "quantity": approved_qty, "price": price},
            decision_id=decision_id,
        )

        result, fill_price, opened_at = await self._execute_order(
            "buy", symbol, approved_qty, decision_id, price
        )
        trade_id = await self._save_fill(result, symbol, "buy", fill_price, decision_id)
        position_id = await self._finalize_open(
            symbol, trade_id, result.quantity, fill_price, opened_at, decision_id
        )
        log.info(
            "BUY executed  %s  qty=%.6f  fill=%.4f  position_id=%d  balance=%.2f",
            symbol, result.quantity, fill_price, position_id, self.portfolio.balance,
        )

    # ── Strategy-driven exit ──────────────────────────────────────────────

    async def _handle_sell(self, symbol: str, price: float, signal_id: int) -> None:
        pos = self.portfolio.positions.get(symbol)
        proposed_qty = pos.quantity if pos else 0.0

        sell_decision, sell_reject = evaluate_sell(pos is not None)
        decision_id = await self._make_decision(
            signal_id, sell_decision.value,
            sell_reject.value if sell_reject else None,
            proposed_qty,
        )

        if sell_decision == RiskDecision.REJECTED:
            log.warning("SELL rejected  %s  reason=%s  decision_id=%d", symbol, sell_reject, decision_id)
            await self._log(
                level="WARNING", category=CAT_RISK, event=EVT_RISK_REJECTED, symbol=symbol,
                message=f"SELL rejected  {symbol}  reason={sell_reject}",
                data={"reason": sell_reject.value if sell_reject else None},
                decision_id=decision_id,
            )
            return

        entry_price = pos.entry_price  # type: ignore[union-attr]  # guaranteed non-None: APPROVED only if pos exists
        log.info("SELL approved  %s  qty=%.6f  price=%.4f", symbol, pos.quantity, price)
        await self._log(
            level="INFO", category=CAT_RISK, event=EVT_DECISION_APPROVED, symbol=symbol,
            message=f"SELL approved  {symbol}  qty={pos.quantity:.6f}  price={price:.4f}",
            data={"side": "sell", "quantity": pos.quantity, "price": price},
            decision_id=decision_id,
        )

        result, fill_price, closed_at = await self._execute_order(
            "sell", symbol, pos.quantity, decision_id, price
        )
        trade_id = await self._save_fill(result, symbol, "sell", fill_price, decision_id)
        pnl, position_id = await self._finalize_close(
            symbol, trade_id, fill_price, closed_at, EVT_STRATEGY_EXIT, decision_id, entry_price
        )
        log.info(
            "SELL executed  %s  qty=%.6f  fill=%.4f  pnl=%+.4f  position_id=%d  balance=%.2f",
            symbol, result.quantity, fill_price, pnl, position_id, self.portfolio.balance,
        )
