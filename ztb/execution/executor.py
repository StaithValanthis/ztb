from __future__ import annotations

import contextlib
import logging
import signal
import sqlite3
import time as time_module
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from pandas import DataFrame

from ztb import __version__
from ztb.data.loader import load as load_data
from ztb.data.timeframes import interval_to_ms
from ztb.engine.pnl import PnLCalculator
from ztb.execution.bybit_client import BybitClient, ceil_to_step, round_to_step
from ztb.execution.errors import (
    ClientError,
    ExecutionError,
    PollingError,
)
from ztb.execution.idempotency import IdempotencyLedger, make_intent_hash, make_order_link_id
from ztb.execution.killswitch import LiveKillSwitch
from ztb.execution.models import (
    AccountState,
    ExecRunConfig,
    ExecRunState,
    Mode,
    OrderSide,
    OrderType,
    Position,
)
from ztb.execution.reconcile import ReconcileReport, reconcile_account
from ztb.risk.manager import RiskManager
from ztb.risk.models import RiskConfig, RiskDecision, RiskDecisionAction
from ztb.store.results import connect as store_connect
from ztb.utils.balance import extract_available_balance

logger = logging.getLogger(__name__)


def _safe_float(val: str | float | None, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


class Executor:
    def __init__(
        self,
        strategy: Any,
        config: ExecRunConfig | None = None,
        client: BybitClient | None = None,
        risk_config: RiskConfig | None = None,
        killswitch: LiveKillSwitch | None = None,
    ) -> None:
        self.strategy = strategy
        self.config = config or ExecRunConfig()
        self.client = client
        self.risk_config = risk_config
        self.state: ExecRunState | None = None
        self.risk_mgr: RiskManager | None = None
        self._store_conn: Any = None
        self._idempotency: IdempotencyLedger | None = None
        self._run_id: str = ""
        self._exec_run_id: str = ""
        self._killswitch = killswitch
        self._original_sigterm: Any = None
        self._sigterm_stop: bool = False
        self._last_executed_signal: float = 0.0
        self._signal_initialized: bool = False
        self._active_sl_tp: dict[str, dict[str, float | None]] = {}

    def _init_run(self) -> None:
        now = datetime.now(UTC)
        ts = now.strftime("%Y%m%dT%H%M%S")
        symbol = self.strategy.symbols[0] if self.strategy.symbols else ""
        self._run_id = f"{self.strategy.name}_{symbol}_{ts}"
        self._exec_run_id = f"exec_{self._run_id}"
        self.state = ExecRunState(
            strategy_name=self.strategy.name,
            symbol=symbol,
            timeframe=self.strategy.timeframe,
            mode=self.config.mode,
            run_id=self._run_id,
            exec_run_id=self._exec_run_id,
        )
        self.risk_mgr = RiskManager(config=self.risk_config) if self.config.risk_enabled else None
        self._pnl: PnLCalculator = PnLCalculator(initial_cash=self.config.initial_cash)

    def _setup_sigterm(self) -> None:
        def _handler(signum: int, _frame: Any) -> None:
            self._sigterm_stop = True
            if self._killswitch and not self._killswitch.is_tripped:
                self._killswitch.manual_trip("SIGTERM received — flattening positions")
            if self.state and self.client and self.config and not self.config.dry_run:
                try:
                    pos_size = self.state.current_position
                    if abs(pos_size) > 1e-12:
                        side = OrderSide.SELL if pos_size > 0 else OrderSide.BUY
                        self.client.place_order(
                            symbol=self.state.symbol,
                            side=side,
                            qty=abs(pos_size),
                            order_type=OrderType.MARKET,
                            reduce_only=True,
                        )
                except Exception:
                    pass

        self._original_sigterm = signal.signal(signal.SIGTERM, _handler)

    def _restore_sigterm(self) -> None:
        if self._original_sigterm is not None:
            signal.signal(signal.SIGTERM, self._original_sigterm)

    def _init_store(self, db_path: str | None = None) -> None:
        self._store_conn = store_connect(db_path)
        from ztb.store.exec_io import create_exec_run, ensure_exec_tables

        ensure_exec_tables(self._store_conn)
        assert self.state is not None
        create_exec_run(
            self._store_conn,
            self.state.exec_run_id,
            self.state.run_id,
            self.state.strategy_name,
            self.state.symbol,
            self.state.timeframe,
            mode=self.config.mode.value,
            started_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        self._idempotency = IdempotencyLedger(self._store_conn)

    def _restore_last_bar_ts(self) -> None:
        assert self.state is not None
        from ztb.store.exec_io import get_last_bar_ts

        last_ts = get_last_bar_ts(
            self._store_conn,
            self.state.strategy_name,
            self.state.symbol,
            self.state.timeframe,
        )
        if last_ts:
            self.state.last_bar_ts = last_ts
            logger.info(
                "Restored last_bar_ts=%s for %s %s %s",
                last_ts,
                self.state.strategy_name,
                self.state.symbol,
                self.state.timeframe,
            )

    def _apply_sl_tp(
        self,
        symbol: str,
        side: OrderSide,
        position_size: float,
        avg_entry: float,
        sl_pct: float,
        tp_pct: float,
    ) -> bool:
        if self.client is None or self.config.dry_run:
            return False
        if sl_pct <= 0.0 and tp_pct <= 0.0:
            return False
        if abs(position_size) < 1e-12 or avg_entry <= 0.0:
            return False
        assert self.state is not None
        is_long = position_size > 0
        sl_price: float = 0.0
        tp_price: float = 0.0
        if sl_pct > 0.0:
            sl_price = avg_entry * (1.0 - sl_pct) if is_long else avg_entry * (1.0 + sl_pct)
        if tp_pct > 0.0:
            tp_price = avg_entry * (1.0 + tp_pct) if is_long else avg_entry * (1.0 - tp_pct)
        if sl_price > 0.0 and is_long and sl_price >= avg_entry:
            raise ValueError(
                f"SL price {sl_price} must be below entry {avg_entry} for long position"
            )
        if sl_price > 0.0 and not is_long and sl_price <= avg_entry:
            raise ValueError(
                f"SL price {sl_price} must be above entry {avg_entry} for short position"
            )
        if tp_price > 0.0 and is_long and tp_price <= avg_entry:
            raise ValueError(
                f"TP price {tp_price} must be above entry {avg_entry} for long position"
            )
        if tp_price > 0.0 and not is_long and tp_price >= avg_entry:
            raise ValueError(
                f"TP price {tp_price} must be below entry {avg_entry} for short position"
            )
        try:
            self.client.set_trading_stop(
                symbol=symbol,
                side=side,
                position_size=abs(position_size),
                stop_loss=sl_price,
                take_profit=tp_price,
                sl_trigger_by="LastPrice",
                tp_trigger_by="LastPrice",
            )
            self._active_sl_tp[symbol] = {"sl_price": sl_price, "tp_price": tp_price}
            if self.state.last_bar_ts and self._idempotency is not None:
                from ztb.execution.idempotency import make_intent_hash, make_sl_tp_order_link_id

                intent_hash = make_intent_hash(position_size, avg_entry)
                sl_link_id = make_sl_tp_order_link_id(
                    self.state.strategy_name, symbol, self.state.last_bar_ts, intent_hash, "sl"
                )
                self._idempotency.try_claim(sl_link_id)
                self._idempotency.resolve(sl_link_id, "placed")
                if tp_price > 0.0:
                    tp_link_id = make_sl_tp_order_link_id(
                        self.state.strategy_name, symbol, self.state.last_bar_ts, intent_hash, "tp"
                    )
                    self._idempotency.try_claim(tp_link_id)
                    self._idempotency.resolve(tp_link_id, "placed")
            return True
        except Exception:
            logger.warning("set_trading_stop failed for %s — continuing", symbol)
            return False

    def _clear_sl_tp(
        self, symbol: str, side: OrderSide = OrderSide.BUY, position_size: float = 0.0
    ) -> bool:
        if self.client is None or self.config.dry_run:
            return False
        if symbol not in self._active_sl_tp:
            return False
        try:
            self.client.set_trading_stop(
                symbol=symbol,
                side=side,
                position_size=abs(position_size) if abs(position_size) > 1e-12 else 0.01,
                stop_loss=0.0,
                take_profit=0.0,
            )
        except Exception:
            logger.warning("clear_sl_tp failed for %s — continuing", symbol)
        self._active_sl_tp.pop(symbol, None)
        if self._idempotency is not None and self.state is not None:
            with contextlib.suppress(Exception):
                self._idempotency.conn.execute(
                    "DELETE FROM idempotency WHERE order_link_id LIKE ?",
                    (f"%:{symbol}:%",),
                )
                self._idempotency.conn.commit()
        return True

    def _save_position_snapshot(self) -> None:
        from ztb.store.exec_io import save_position_snapshot

        assert self.state is not None
        price = self.state.avg_entry_price
        save_position_snapshot(
            self._store_conn,
            {
                "exec_run_id": self.state.exec_run_id,
                "symbol": self.state.symbol,
                "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "position": self.state.current_position,
                "avg_price": price,
                "unrealized_pnl": 0.0,
                "sufficient_sample": 1,
                "code_version": __version__,
            },
        )

    def _sync_pnl_state(self) -> None:
        assert self.state is not None
        self.state.current_position = self._pnl.position
        self.state.avg_entry_price = self._pnl.avg_entry_price
        self.state.realized_pnl = self._pnl.realized_pnl
        self.state.total_commission = self._pnl.total_commission
        self.state.total_slippage = self._pnl.total_slippage

    def _save_pnl(self, realized: float, unrealized: float, equity: float, bar_ts: str) -> None:
        from ztb.store.exec_io import save_pnl_entry

        assert self.state is not None
        save_pnl_entry(
            self._store_conn,
            {
                "exec_run_id": self.state.exec_run_id,
                "timestamp": bar_ts,
                "symbol": self.state.symbol,
                "realized_pnl": realized,
                "unrealized_pnl": unrealized,
                "total_equity": equity,
                "sufficient_sample": 1,
                "code_version": __version__,
            },
        )

    def _check_killswitch(self) -> bool:
        if self._killswitch is None:
            return False
        tripped = self._killswitch.is_tripped
        if tripped and self._store_conn is not None:
            assert self.state is not None
            persist = self._killswitch.to_persistable_state()
            from ztb.store.exec_io import save_killswitch_state

            with contextlib.suppress(sqlite3.OperationalError):
                save_killswitch_state(
                    self._store_conn,
                    self.state.exec_run_id,
                    persist["tripped"],
                    persist["hwm_equity"],
                    persist["last_heartbeat"],
                )
        return bool(tripped)

    def _save_kill_events(self) -> None:
        if self._killswitch is None or self._store_conn is None:
            return
        assert self.state is not None
        for t in self._killswitch.get_triggers():
            from ztb.store.exec_io import save_kill_event

            save_kill_event(
                self._store_conn,
                {
                    "exec_run_id": self.state.exec_run_id,
                    "source": t.source,
                    "reason": t.reason,
                    "value": t.value,
                    "threshold": t.threshold,
                    "timestamp": t.timestamp or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            )

    def _save_error(self, error_type: str, message: str) -> None:
        from ztb.store.exec_io import save_exec_error

        assert self.state is not None
        save_exec_error(
            self._store_conn,
            {
                "exec_run_id": self.state.exec_run_id,
                "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "error_type": error_type,
                "message": message,
            },
        )

    def _compute_target_position(self, data: DataFrame) -> float:
        warmup = getattr(self.strategy, "warmup", 0)
        if len(data) <= warmup:
            logger.warning(
                "Strategy '%s' not called: data length (%d) <= warmup (%d). "
                "Returning 0.0 — ensure _ensure_warmup is providing enough bars.",
                self.strategy.name,
                len(data),
                warmup,
            )
            return 0.0
        signals = self.strategy.generate_signals(data)
        return float(signals.iloc[-1])

    def _apply_risk(
        self,
        target_signal: float,
        current_position: float,
        price: float,
        equity: float,
        bar_ts: str,
    ) -> tuple[float, RiskDecision | None]:
        if self.risk_mgr is None:
            return target_signal, None
        assert self.state is not None
        sym = self.state.symbol
        target_qty = target_signal * equity / price if price > 0 else 0.0
        proposed = {sym: target_qty}
        prices = {sym: price}
        portfolio_state: dict[str, Any] = {
            "cash": equity - current_position * price,
            "positions": {sym: current_position},
        }
        self.risk_mgr.update_portfolio_equity(equity)
        decision = self.risk_mgr.evaluate(
            portfolio_state=portfolio_state,
            proposed_positions=proposed,
            prices=prices,
            current_equity=equity,
            timestamp=bar_ts,
        )
        if decision.action == RiskDecisionAction.halt:
            return 0.0, decision
        if decision.action == RiskDecisionAction.reduce:
            if decision.max_pos_size > 0:
                pos_notional = decision.max_pos_size * price
                scale = (
                    pos_notional / abs(target_signal * equity)
                    if abs(target_signal * equity) > 0
                    else 0.0
                )
            else:
                sig_val = abs(target_signal) * equity
                scale = decision.max_notional / sig_val if sig_val > 0 else 0.0
            return target_signal * min(scale, 1.0), decision
        return target_signal, decision

    def _reconcile(
        self, expected_position: float, close_price: float, bar_ts: str
    ) -> ReconcileReport:
        assert self.state is not None
        expected_upnl = self._pnl.unrealized_pnl(close_price)
        equity = self._pnl.equity(close_price)
        expected = AccountState(
            total_equity=equity,
            wallet_balance=equity - expected_position * close_price,
            unrealized_pnl=expected_upnl,
            positions={
                self.state.symbol: Position(
                    symbol=self.state.symbol,
                    size=expected_position,
                    avg_price=self._pnl.avg_entry_price,
                    unrealized_pnl=expected_upnl,
                    realized_pnl=self._pnl.realized_pnl,
                    timestamp=bar_ts,
                )
            },
            timestamp=bar_ts,
        )
        if self.config.dry_run or self.client is None:
            return reconcile_account(expected, expected, self.state.symbol)
        try:
            actual_positions_raw = self.client.get_positions(self.state.symbol)
            wallet_raw = self.client.get_wallet_balance(coin="USDT")
            from ztb.execution.reconcile import compute_account_state

            actual = compute_account_state(
                actual_positions_raw,
                wallet_raw,
            )
            return reconcile_account(expected, actual, self.state.symbol)
        except Exception:
            return reconcile_account(expected, expected, self.state.symbol)

    def _reconcile_pending_order(self, symbol: str, order_link_id: str) -> dict[str, Any] | None:
        if self.client is None:
            return None
        try:
            orders = self.client.get_order_history(symbol=symbol, limit=50)
            for order in orders:
                if order.get("orderLinkId") == order_link_id:
                    return order
            open_orders = self.client.get_open_orders(symbol=symbol)
            for order in open_orders:
                if order.get("orderLinkId") == order_link_id:
                    return order
        except Exception:
            logger.warning("reconcile_pending_order: query failed for %s", order_link_id)
        return None

    def _poll_fills(
        self,
        order_id: str,
        order_link_id: str,
    ) -> list[dict[str, Any]]:
        assert self.state is not None
        assert self.client is not None
        max_attempts = self.config.poll_fill_max_attempts
        interval = self.config.poll_fill_interval

        for attempt in range(1, max_attempts + 1):
            if self._sigterm_stop:
                logger.warning("SIGTERM received — aborting fill polling for %s", order_link_id)
                break
            try:
                from ztb.execution.reconcile import parse_fills as _parse_fills

                raw_fills = self.client.get_executions(symbol=self.state.symbol, order_id=order_id)
                parsed = list(_parse_fills(raw_fills))
                if parsed:
                    logger.info(
                        "Polled fills for %s on attempt %d/%d: %d fill(s)",
                        order_link_id,
                        attempt,
                        max_attempts,
                        len(parsed),
                    )
                    return [
                        {
                            "fill_id": f.exec_id,
                            "order_link_id": order_link_id,
                            "exec_run_id": self.state.exec_run_id,
                            "order_id": f.order_id,
                            "symbol": f.symbol,
                            "side": f.side.value,
                            "price": f.price,
                            "qty": f.qty,
                            "commission": f.commission,
                            "realized_pnl": f.realized_pnl,
                            "filled_at": f.timestamp,
                            "sufficient_sample": 1,
                            "code_version": __version__,
                        }
                        for f in parsed
                    ]
                if attempt < max_attempts:
                    logger.debug(
                        "No fills yet for %s (attempt %d/%d), retrying in %.1fs",
                        order_link_id,
                        attempt,
                        max_attempts,
                        interval,
                    )
                    time_module.sleep(interval)
                    if self._sigterm_stop:
                        logger.warning(
                            "SIGTERM received — aborting fill polling for %s",
                            order_link_id,
                        )
                        break
            except Exception:
                logger.warning(
                    "Poll fills attempt %d/%d failed for order %s",
                    attempt,
                    max_attempts,
                    order_id,
                )
                if attempt < max_attempts:
                    time_module.sleep(interval)
                    if self._sigterm_stop:
                        logger.warning(
                            "SIGTERM received — aborting fill polling for %s",
                            order_link_id,
                        )
                        break

        logger.warning(
            "Fill polling exhausted for %s after %d attempts — returning empty",
            order_link_id,
            max_attempts,
        )
        return []

    def step(
        self,
        data: DataFrame,
    ) -> dict[str, Any]:
        assert self.state is not None
        assert self._store_conn is not None
        assert self._idempotency is not None

        if self._check_killswitch():
            for sym in list(self._active_sl_tp.keys()):
                self._clear_sl_tp(sym, side=OrderSide.BUY, position_size=0.0)
            return {
                "killswitch_tripped": True,
                "bar_ts": str(data.index[-1] if len(data) > 0 else ""),
            }

        try:
            return self._step_impl(data)
        except ClientError as exc:
            error_msg = f"step ClientError: {exc}"
            assert self.state is not None
            if "ab not enough" in str(exc):
                logger.warning(
                    "Insufficient balance for %s: %s — skipped bar",
                    self.state.symbol,
                    exc,
                )
            self.state.errors.append(error_msg)
            from ztb.store.exec_io import save_exec_error

            save_exec_error(
                self._store_conn,
                {
                    "exec_run_id": self.state.exec_run_id,
                    "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "error_type": type(exc).__name__,
                    "message": error_msg,
                },
            )
            return {
                "bar_ts": str(data.index[-1] if len(data) > 0 else ""),
                "client_error": True,
                "error": error_msg,
            }
        except Exception as exc:
            error_msg = f"step error: {exc}"
            assert self.state is not None
            self.state.errors.append(error_msg)
            from ztb.store.exec_io import save_exec_error

            save_exec_error(
                self._store_conn,
                {
                    "exec_run_id": self.state.exec_run_id,
                    "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "error_type": type(exc).__name__,
                    "message": error_msg,
                },
            )
            raise

    def _step_impl(
        self,
        data: DataFrame,
    ) -> dict[str, Any]:
        assert self.state is not None
        assert self._store_conn is not None
        assert self._idempotency is not None

        symbol = self.state.symbol
        bar_ts = str(data.index[-1])
        close_price = float(data["close"].iloc[-1])

        target_signal = self._compute_target_position(data)
        current_position = self._pnl.position

        equity = self._pnl.equity(close_price)
        available_balance = 0.0

        if not self.config.dry_run and self.client is not None:
            try:
                wallet = self.client.get_wallet_balance(coin="USDT")
                from ztb.execution.reconcile import compute_account_state

                actual = compute_account_state([], wallet)
                equity = actual.total_equity if actual.total_equity > 0 else equity
                available_balance = actual.available_balance
                if available_balance == 0.0:
                    available_balance = actual.total_available_balance
            except Exception:
                error_msg = f"Wallet fetch failed for {symbol}"
                logger.warning(error_msg)
                self._save_error("WalletFetchError", error_msg)
                self.state.errors.append(error_msg)
                wallet_error_result: dict[str, Any] = {
                    "bar_ts": bar_ts,
                    "close_price": close_price,
                    "signal": target_signal,
                    "current_position": current_position,
                    "target_position": 0.0,
                    "delta": 0.0,
                    "order_placed": False,
                    "order": None,
                    "risk_decision": None,
                    "fills": [],
                    "wallet_fetch_failed": True,
                }
                self.state.bars_processed += 1
                self.state.last_bar_ts = bar_ts
                self._sync_pnl_state()
                unrealized_pnl = self._pnl.unrealized_pnl(close_price)
                self._save_position_snapshot()
                self._save_pnl(
                    self._pnl.realized_pnl, unrealized_pnl, self._pnl.equity(close_price), bar_ts
                )
                return wallet_error_result

            if self.config.mode == Mode.DEMO:
                equity = min(equity, self.config.initial_cash)

        # --- reconcile exchange position (before delta computation) ---
        if not self.config.dry_run and self.client is not None:
            try:
                actual_positions_raw = self.client.get_positions(symbol)
                for p in actual_positions_raw:
                    if p.get("symbol") == symbol:
                        actual_position = float(p.get("size", 0.0))
                        actual_avg_price = float(p.get("avgPrice", 0.0))
                        if abs(actual_position - current_position) > 1e-8:
                            self._pnl.adopt_state(
                                position=actual_position,
                                avg_entry_price=actual_avg_price,
                            )
                            current_position = self._pnl.position
                            self._sync_pnl_state()
                            self._signal_initialized = False
                            logger.info(
                                "Adopted exchange position %.4f for %s (PnL had %.4f)",
                                actual_position,
                                symbol,
                                current_position,
                            )
                        break
            except Exception:
                logger.warning("Position reconciliation failed for %s", symbol, exc_info=True)

        if self._killswitch is not None:
            self._killswitch.check_account_dd(equity)
            if self._killswitch.check_data_staleness(bar_ts):
                self._save_kill_events()

        target_signal, risk_decision = self._apply_risk(
            target_signal, current_position, close_price, equity, bar_ts
        )

        if risk_decision is not None and risk_decision.action == RiskDecisionAction.halt:
            target_signal = 0.0

        asset_precision = self.config.asset_precision
        if not self.config.dry_run and self.client is not None and available_balance > 0:
            target_notional = target_signal * min(
                equity, available_balance * self.config.max_leverage
            )
            target_qty = (
                round(target_notional / close_price, asset_precision) if close_price > 0 else 0.0
            )
        else:
            target_qty = (
                round(target_signal * equity / close_price, asset_precision)
                if close_price > 0
                else 0.0
            )

        # Align target_qty to instrument step size (round away from zero)
        # to avoid flooring small wallets to zero when step > precision
        instrument_qty_step = 0.0
        if not self.config.dry_run and self.client is not None:
            try:
                instrument_qty_step = self.client.get_qty_step(symbol)
            except Exception:
                logger.warning(
                    "Failed to fetch qty_step for %s, skipping step alignment",
                    symbol,
                )
        if isinstance(instrument_qty_step, (int, float)) and instrument_qty_step > 0:
            target_qty = ceil_to_step(target_qty, instrument_qty_step)

        delta = target_qty - current_position

        result: dict[str, Any] = {
            "bar_ts": bar_ts,
            "close_price": close_price,
            "signal": target_signal,
            "current_position": current_position,
            "target_position": target_qty,
            "delta": delta,
            "order_placed": False,
            "order": None,
            "risk_decision": risk_decision,
            "fills": [],
        }

        if self.config.dry_run:
            if abs(delta) > 1e-12:
                commission_cost = abs(delta) * close_price * self.config.commission
                slippage_cost = abs(delta) * close_price * self.config.slippage
                self._pnl.apply_fill(
                    delta, close_price, commission=commission_cost, slippage=slippage_cost
                )
            self._sync_pnl_state()
            self.state.bars_processed += 1
            self.state.last_bar_ts = bar_ts
            unrealized_pnl = self._pnl.unrealized_pnl(close_price)
            self._save_position_snapshot()
            self._save_pnl(
                self._pnl.realized_pnl, unrealized_pnl, self._pnl.equity(close_price), bar_ts
            )
            self._last_executed_signal = target_signal
            self._signal_initialized = True
            return result

        signal_changed = (
            not self._signal_initialized or abs(target_signal - self._last_executed_signal) > 1e-6
        )

        if signal_changed:
            self._signal_initialized = True

        if abs(delta) > 1e-12:
            intent_hash = make_intent_hash(target_qty, current_position)
            order_link_id = make_order_link_id(
                self.state.strategy_name, symbol, bar_ts, intent_hash
            )

            claimed = self._idempotency.try_claim(order_link_id)
            if not claimed:
                existing = self._idempotency.get(order_link_id)
                if existing and existing.get("order_id"):
                    comm_cost = abs(delta) * close_price * self.config.commission
                    slip_cost = abs(delta) * close_price * self.config.slippage
                    self._pnl.apply_fill(
                        delta, close_price, commission=comm_cost, slippage=slip_cost
                    )
                    self._sync_pnl_state()
                    result["order_placed"] = True
                    result["order"] = {"order_id": existing["order_id"], "restored": True}
                    self.state.bars_processed += 1
                    self.state.last_bar_ts = bar_ts
                    unrealized_pnl = self._pnl.unrealized_pnl(close_price)
                    self._save_position_snapshot()
                    self._save_pnl(
                        self._pnl.realized_pnl,
                        unrealized_pnl,
                        self._pnl.equity(close_price),
                        bar_ts,
                    )
                    return result

                # M1: reconcile lost response before resubmit
                matched = self._reconcile_pending_order(symbol, order_link_id)
                if matched:
                    self._idempotency.resolve(order_link_id, "placed", matched["orderId"])
                    comm_cost = abs(delta) * close_price * self.config.commission
                    slip_cost = abs(delta) * close_price * self.config.slippage
                    self._pnl.apply_fill(
                        delta, close_price, commission=comm_cost, slippage=slip_cost
                    )
                    self._sync_pnl_state()
                    result["order_placed"] = True
                    result["order"] = {"order_id": matched["orderId"], "restored": True}
                    self.state.bars_processed += 1
                    self.state.last_bar_ts = bar_ts
                    unrealized_pnl = self._pnl.unrealized_pnl(close_price)
                    self._save_position_snapshot()
                    self._save_pnl(
                        self._pnl.realized_pnl,
                        unrealized_pnl,
                        self._pnl.equity(close_price),
                        bar_ts,
                    )
                    return result

                # order never reached Bybit — resolve as failed, retry with nonced link_id
                self._idempotency.resolve(order_link_id, "failed")
                nonce = str(time_module.time_ns())
                fresh_link_id = make_order_link_id(
                    self.state.strategy_name, symbol, bar_ts, intent_hash, nonce=nonce
                )
                claimed = self._idempotency.try_claim(fresh_link_id)
                if not claimed:
                    logger.warning(
                        "M1: fresh try_claim failed after "
                        "resolving stale pending %s — skipping bar",
                        order_link_id,
                    )
                    self.state.bars_processed += 1
                    self.state.last_bar_ts = bar_ts
                    self._sync_pnl_state()
                    unrealized_pnl = self._pnl.unrealized_pnl(close_price)
                    self._save_position_snapshot()
                    self._save_pnl(
                        self._pnl.realized_pnl,
                        unrealized_pnl,
                        self._pnl.equity(close_price),
                        bar_ts,
                    )
                    return result
                order_link_id = fresh_link_id

            if self.client is None:
                raise ExecutionError("No BybitClient configured for live trading")

            reconcile_report = self._reconcile(current_position, close_price, bar_ts)

            if self._killswitch is not None:
                self._killswitch.check_reconcile_drift(reconcile_report.position_drift)
                if self._killswitch.is_tripped:
                    for sym in list(self._active_sl_tp.keys()):
                        self._clear_sl_tp(sym, side=OrderSide.BUY, position_size=0.0)
                    self._save_kill_events()
                    result["killswitch_tripped"] = True
                    self.state.bars_processed += 1
                    self.state.last_bar_ts = bar_ts
                    return result

            side = OrderSide.BUY if delta > 0 else OrderSide.SELL
            qty = round(abs(delta), asset_precision)

            # Align order qty to instrument step size so it passes
            # _validate_qty without being floored to zero or silently adjusted
            if isinstance(instrument_qty_step, (int, float)) and instrument_qty_step > 0:
                if delta > 0:
                    qty = ceil_to_step(qty, instrument_qty_step)
                else:
                    qty = round_to_step(qty, instrument_qty_step)

            flip = (
                delta < 0 and current_position > 0 and abs(delta) > current_position + 1e-12
            ) or (delta > 0 and current_position < 0 and abs(delta) > abs(current_position) + 1e-12)
            reduce_only = not flip and (
                (delta < 0 and current_position > 0) or (delta > 0 and current_position < 0)
            )

            if (
                reduce_only
                and not self.config.dry_run
                and self.client is not None
                and abs(reconcile_report.actual_position) < 1e-8
            ):
                logger.warning(
                    "Reduce-only skipped — exchange position is zero for %s "
                    "(PnL position=%s, actual=%s). Adopting zero position.",
                    symbol,
                    current_position,
                    reconcile_report.actual_position,
                )
                # adopt_state without realized_pnl --- PnL from the external close
                # (SL/TP, manual close) is NOT preserved in PnLCalculator.
                # Acceptable because equity is refreshed from exchange wallet
                # balance each bar via LiveExecutor._reconcile.
                self._pnl.adopt_state(position=0.0, avg_entry_price=0.0)
                self._sync_pnl_state()
                result["order_skipped"] = True
                result["skip_reason"] = (
                    f"Reduce-only skipped — exchange position is zero "
                    f"(PnL had {current_position}, actual "
                    f"{reconcile_report.actual_position})"
                )
                self._save_error("OrderSkipped", result["skip_reason"])
                self.state.errors.append(result["skip_reason"])
                self.state.bars_processed += 1
                self.state.last_bar_ts = bar_ts
                unrealized_pnl = self._pnl.unrealized_pnl(close_price)
                equity = self._pnl.equity(close_price)
                self._save_position_snapshot()
                self._save_pnl(
                    self._pnl.realized_pnl,
                    unrealized_pnl,
                    self._pnl.equity(close_price),
                    bar_ts,
                )
                self._signal_initialized = True
                return result

            if not reduce_only and available_balance > 0 and close_price > 0:
                max_notional = available_balance * self.config.max_leverage
                max_qty = round(max_notional / close_price, asset_precision)
                if isinstance(instrument_qty_step, (int, float)) and instrument_qty_step > 0:
                    max_qty = round_to_step(max_qty, instrument_qty_step)
                require_margin_qty = max(0.0, qty - abs(current_position)) if flip else qty
                if require_margin_qty > max_qty + 1e-12:
                    capped_qty = round(qty - require_margin_qty + max_qty, asset_precision)
                    # Align capped qty to step size (toward zero / floor) to
                    # avoid exceeding the balance limit after step-rounding
                    if isinstance(instrument_qty_step, (int, float)) and instrument_qty_step > 0:
                        capped_qty = round_to_step(capped_qty, instrument_qty_step)
                    self.state.errors.append(
                        f"Qty capped by available balance: {qty} -> {capped_qty} "
                        f"(available_balance={available_balance:.2f}, "
                        f"max_notional={max_notional:.2f})"
                    )
                    qty = capped_qty
                    if qty < 1e-12:
                        result["order_skipped"] = True
                        result["skip_reason"] = (
                            f"Qty capped to {max_qty} by balance limit, below minimum"
                        )
                        self._save_error("OrderSkipped", result["skip_reason"])
                        self.state.errors.append(result["skip_reason"])
                        self.state.bars_processed += 1
                        self.state.last_bar_ts = bar_ts
                        self._sync_pnl_state()
                        unrealized_pnl = self._pnl.unrealized_pnl(close_price)
                        equity = self._pnl.equity(close_price)
                        self._save_position_snapshot()
                        self._save_pnl(
                            self._pnl.realized_pnl,
                            unrealized_pnl,
                            self._pnl.equity(close_price),
                            bar_ts,
                        )
                        self._signal_initialized = True
                        return result

            positions_close = abs(delta) > 1e-12 and abs(target_qty) < 1e-12
            if flip or positions_close:
                clear_side = OrderSide.BUY if current_position > 0 else OrderSide.SELL
                self._clear_sl_tp(symbol, side=clear_side, position_size=abs(current_position))

            try:
                order_result = self.client.place_order(
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    order_type=OrderType.MARKET,
                    order_link_id=order_link_id,
                    reduce_only=reduce_only,
                )
            except ClientError as exc:
                if "OrderLinkedID is duplicate" in str(exc):
                    matched = self._reconcile_pending_order(symbol, order_link_id)
                    if matched:
                        self._idempotency.resolve(order_link_id, "placed", matched["orderId"])
                        comm_cost = abs(delta) * close_price * self.config.commission
                        slip_cost = abs(delta) * close_price * self.config.slippage
                        self._pnl.apply_fill(
                            delta, close_price, commission=comm_cost, slippage=slip_cost
                        )
                        self._sync_pnl_state()
                        result["order_placed"] = True
                        result["order"] = {"order_id": matched["orderId"], "restored": True}
                        self.state.bars_processed += 1
                        self.state.last_bar_ts = bar_ts
                        unrealized_pnl = self._pnl.unrealized_pnl(close_price)
                        self._save_position_snapshot()
                        self._save_pnl(
                            self._pnl.realized_pnl,
                            unrealized_pnl,
                            self._pnl.equity(close_price),
                            bar_ts,
                        )
                        self._last_executed_signal = target_signal
                        return result
                    self._idempotency.resolve(order_link_id, "failed")
                    logger.warning(
                        "Duplicate OrderLinkedID %s — order not found on exchange, skipping bar",
                        order_link_id,
                    )
                    self.state.bars_processed += 1
                    self.state.last_bar_ts = bar_ts
                    self._sync_pnl_state()
                    unrealized_pnl = self._pnl.unrealized_pnl(close_price)
                    self._save_position_snapshot()
                    self._save_pnl(
                        self._pnl.realized_pnl,
                        unrealized_pnl,
                        self._pnl.equity(close_price),
                        bar_ts,
                    )
                    return result
                raise

            if order_result.get("skipped"):
                result["order_skipped"] = True
                result["skip_reason"] = str(order_result.get("reason", ""))
                self._save_error("OrderSkipped", result["skip_reason"])
                self.state.errors.append(f"Order skipped: {result['skip_reason']}")
                self.state.bars_processed += 1
                self.state.last_bar_ts = bar_ts
                self._sync_pnl_state()
                unrealized_pnl = self._pnl.unrealized_pnl(close_price)
                equity = self._pnl.equity(close_price)
                self._save_position_snapshot()
                self._save_pnl(
                    self._pnl.realized_pnl,
                    unrealized_pnl,
                    self._pnl.equity(close_price),
                    bar_ts,
                )
                return result

            order_id = order_result.get("orderId", "")
            self._idempotency.resolve(order_link_id, "placed", order_id)

            # Real fill pipeline: poll for fills from exchange
            real_fills: list[dict[str, Any]] = self._poll_fills(
                order_id=order_id, order_link_id=order_link_id
            )
            if not real_fills:
                self._save_error("FillFetchError", f"No fills after polling for order {order_id}")

            if real_fills:
                total_fill_qty = sum(f["qty"] for f in real_fills)
                total_fill_commission = sum(f["commission"] for f in real_fills)
                avg_fill_price = (
                    sum(f["price"] * f["qty"] for f in real_fills) / total_fill_qty
                    if total_fill_qty > 0
                    else close_price
                )
                self._pnl.apply_fill(
                    total_fill_qty if delta > 0 else -total_fill_qty,
                    avg_fill_price,
                    commission=total_fill_commission,
                    slippage=0.0,
                )
                self._sync_pnl_state()
                result["real_fills"] = real_fills
                cum_exec_qty = total_fill_qty
                cum_exec_value = sum(f["price"] * f["qty"] for f in real_fills)
                cum_exec_fee = total_fill_commission
                from ztb.store.exec_io import save_exec_order

                save_exec_order(
                    self._store_conn,
                    {
                        "order_link_id": order_link_id,
                        "exec_run_id": self.state.exec_run_id,
                        "order_id": order_id,
                        "symbol": symbol,
                        "side": side.value,
                        "order_type": "Market",
                        "price": avg_fill_price,
                        "qty": total_fill_qty,
                        "status": "Filled",
                        "created_at": bar_ts,
                        "cum_exec_qty": cum_exec_qty,
                        "cum_exec_value": cum_exec_value,
                        "cum_exec_fee": cum_exec_fee,
                        "sufficient_sample": 1,
                        "code_version": __version__,
                    },
                )
                for fill in real_fills:
                    from ztb.store.exec_io import save_exec_fill

                    save_exec_fill(self._store_conn, fill)
            else:
                commission_cost = qty * close_price * self.config.commission
                slippage_cost = qty * close_price * self.config.slippage
                self._pnl.apply_fill(
                    delta, close_price, commission=commission_cost, slippage=slippage_cost
                )
                self._sync_pnl_state()
                from ztb.store.exec_io import save_exec_order

                save_exec_order(
                    self._store_conn,
                    {
                        "order_link_id": order_link_id,
                        "exec_run_id": self.state.exec_run_id,
                        "order_id": order_id,
                        "symbol": symbol,
                        "side": side.value,
                        "order_type": "Market",
                        "price": close_price,
                        "qty": qty,
                        "status": "Filled",
                        "created_at": bar_ts,
                        "cum_exec_qty": qty,
                        "cum_exec_value": qty * close_price,
                        "cum_exec_fee": commission_cost,
                        "sufficient_sample": 1,
                        "code_version": __version__,
                    },
                )
                from ztb.store.exec_io import save_exec_fill

                save_exec_fill(
                    self._store_conn,
                    {
                        "fill_id": f"synthetic-{order_link_id}",
                        "order_link_id": order_link_id,
                        "exec_run_id": self.state.exec_run_id,
                        "order_id": order_id,
                        "symbol": symbol,
                        "side": side.value,
                        "price": close_price,
                        "qty": qty,
                        "commission": commission_cost,
                        "realized_pnl": 0.0,
                        "filled_at": bar_ts,
                        "sufficient_sample": 1,
                        "code_version": __version__,
                    },
                )

            result["order_placed"] = True
            result["order"] = {"order_id": order_id, "order_link_id": order_link_id}

            pos_side = OrderSide.BUY if self._pnl.position > 0 else OrderSide.SELL
            pos_size = self._pnl.position
            avg_entry = self._pnl.avg_entry_price
            self._clear_sl_tp(symbol, side=pos_side, position_size=abs(pos_size))
            self._apply_sl_tp(
                symbol,
                pos_side,
                pos_size,
                avg_entry,
                self.config.sl_pct,
                self.config.tp_pct,
            )

            self._reconcile(target_qty, close_price, bar_ts)
            self._last_executed_signal = target_signal
        elif signal_changed:
            self._last_executed_signal = target_signal

        self.state.bars_processed += 1
        self.state.last_bar_ts = bar_ts
        self._sync_pnl_state()
        unrealized_pnl = self._pnl.unrealized_pnl(close_price)
        equity = self._pnl.equity(close_price)
        self._save_position_snapshot()
        self._save_pnl(self._pnl.realized_pnl, unrealized_pnl, equity, bar_ts)
        return result

    def _ensure_warmup(
        self,
        data: DataFrame,
        warmup: int,
        symbol: str,
        timeframe: str,
        category: str,
        start: str | None,
    ) -> DataFrame:
        if len(data) >= warmup:
            return data
        current_start = pd.Timestamp(start) if start else data.index[0]
        interval_ms = interval_to_ms(timeframe)
        needed_bars = warmup - len(data) + 100
        extended_start = current_start - timedelta(milliseconds=interval_ms * needed_bars)
        extended = load_data(
            symbol=symbol,
            timeframe=timeframe,
            category=category,
            start=extended_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end=current_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        if extended is None or extended.empty:
            raise ExecutionError(
                f"Cannot fetch enough historical data for {symbol} {timeframe}: "
                f"need {warmup} bars for warmup, exchange returned empty data"
            )
        combined = pd.concat([extended, data])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined = combined.sort_index()
        if len(combined) < warmup:
            raise ExecutionError(
                f"Exchange cannot provide enough historical data for {symbol} {timeframe}: "
                f"got {len(combined)} bars, need {warmup} for warmup"
            )
        return combined

    def _fetch_new_bars(
        self,
        data: DataFrame,
        symbol: str,
        timeframe: str,
        category: str,
    ) -> DataFrame:
        last_ts = data.index[-1]
        new_data = load_data(
            symbol=symbol,
            timeframe=timeframe,
            category=category,
            start=last_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end=pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        if new_data is None or new_data.empty:
            return data
        combined = pd.concat([data, new_data[new_data.index > last_ts]])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined = combined.sort_index()
        return combined  # type: ignore[no-any-return]

    def run(
        self,
        symbol: str,
        timeframe: str = "60",
        category: str = "linear",
        start: str | None = None,
        end: str | None = None,
        db_path: str | None = None,
    ) -> ExecRunState:
        self._init_run()
        self._init_store(db_path)
        self._restore_last_bar_ts()

        if self._idempotency is not None:
            self._idempotency.clear_stale(ttl_hours=24)
            self._idempotency.clear_pending(max_age_seconds=3600)

        if (
            self._killswitch is not None
            and self._store_conn is not None
            and self.config.mode == Mode.LIVE
            and not self.config.dry_run
        ):
            from ztb.store.exec_io import load_killswitch_state, save_killswitch_state

            assert self.state is not None
            state = load_killswitch_state(self._store_conn, self.state.exec_run_id)
            if state is not None:
                equity = self._pnl.equity(0)
                self._killswitch.restore_from_state(state, current_equity=equity)
            else:
                persist = self._killswitch.to_persistable_state()
                save_killswitch_state(
                    self._store_conn,
                    self.state.exec_run_id,
                    persist["tripped"],
                    persist["hwm_equity"],
                    persist["last_heartbeat"],
                )

        if self._killswitch is not None:
            self._killswitch.heartbeat()

        if self.client is not None and not self.config.dry_run and self.config.mode == Mode.LIVE:
            try:
                active_stops = self.client.get_active_trading_stops()
                for pos in active_stops:
                    sym = pos.get("symbol", "")
                    if sym:
                        if sym not in self._active_sl_tp:
                            logger.warning(
                                "Startup: %s has active SL/TP on exchange "
                                "(stopLoss=%s, takeProfit=%s) — not tracked locally",
                                sym,
                                pos.get("stopLoss", ""),
                                pos.get("takeProfit", ""),
                            )
                        self._active_sl_tp[sym] = {
                            "sl_price": _safe_float(pos.get("stopLoss", "0")),
                            "tp_price": _safe_float(pos.get("takeProfit", "0")),
                        }
            except Exception:
                logger.warning("Startup active-trading-stops query failed — continuing")

        self._setup_sigterm()

        if self.config.mode == Mode.DEMO and not self.config.dry_run and self.client is not None:
            try:
                wallet_raw = self.client.get_wallet_balance(coin="USDT")
                wallet_balance = extract_available_balance(wallet_raw, coin="USDT")
                if wallet_balance >= self.config.initial_cash * 0.10:
                    logger.info(
                        "Demo wallet already funded: available=%.2f USDT "
                        "(>=10%% of initial_cash=%.2f) — skipping top-up",
                        wallet_balance,
                        self.config.initial_cash,
                    )
                else:
                    top_up_result = self.client.top_up_demo_account(
                        "USDT", str(self.config.initial_cash)
                    )
                    if not top_up_result.success:
                        self._save_error("DemoAccountTopUpError", top_up_result.message)
                    elif top_up_result.credited_amount < self.config.initial_cash * 0.01:
                        logger.warning(
                            "Demo account top-up may be insufficient: "
                            "credited=%s %s (requested=%s)",
                            top_up_result.credited_amount,
                            top_up_result.coin,
                            top_up_result.requested_amount,
                        )
            except Exception as exc:
                self._save_error("DemoAccountTopUpError", str(exc))

        data = load_data(
            symbol=symbol,
            timeframe=timeframe,
            category=category,
            start=start,
            end=end,
        )

        if data is None or data.empty:
            raise ExecutionError(f"No data loaded for {symbol} {timeframe}")

        assert self.state is not None
        warmup = max(getattr(self.strategy, "warmup", 0), self.config.warmup_bars)

        effective_lookback = (
            self.config.lookback_bars
            if self.config.lookback_bars and self.config.lookback_bars > 0
            else max(warmup * 2, 200)
        )
        if len(data) < effective_lookback:
            data = self._ensure_warmup(data, effective_lookback, symbol, timeframe, category, start)

        if len(data) < warmup:
            data = self._ensure_warmup(data, warmup, symbol, timeframe, category, start)

        start_idx = warmup
        if self.state.last_bar_ts:
            try:
                cursor_pos: int = data.index.get_loc(self.state.last_bar_ts)  # type: ignore[assignment]
                if cursor_pos >= warmup:
                    start_idx = cursor_pos + 1
                else:
                    logger.warning(
                        "Cursor %s before warmup (pos=%d, warmup=%d) — no skip",
                        self.state.last_bar_ts,
                        cursor_pos,
                        warmup,
                    )
            except KeyError:
                logger.warning("Cursor %s not in data — no skip", self.state.last_bar_ts)

        if not self.config.dry_run and self.client is not None and len(data) > warmup:
            try:
                warmup_data = data.iloc[: warmup + 1] if len(data) > warmup + 1 else data
                close_price = float(warmup_data["close"].iloc[-1])
                bar_ts = str(warmup_data.index[-1])
                report = self._reconcile(0.0, close_price, bar_ts)
                if abs(report.actual_position) > 1e-8:
                    actual_avg = (
                        report.actual_avg_price
                        if abs(report.actual_avg_price) > 1e-8
                        else close_price
                    )
                    # adopt_state without realized_pnl --- the exchange
                    # position endpoint does not expose the cumulative
                    # realized PnL at startup in a single call.  Equity
                    # is refreshed from wallet balance each bar, so the
                    # missing realized_pnl is reconciled naturally.
                    self._pnl.adopt_state(
                        position=report.actual_position,
                        avg_entry_price=actual_avg,
                    )
                self._sync_pnl_state()
            except Exception:
                pass

        if self.config.once:
            if len(data) <= warmup:
                raise ExecutionError(f"Data length {len(data)} <= warmup {warmup}, cannot run")
            result = self.step(data)
            if result.get("killswitch_tripped"):
                self._save_kill_events()
        else:
            for i in range(start_idx, len(data)):
                if self._check_killswitch():
                    self._save_kill_events()
                    break
                chunk = data.iloc[: i + 1]
                result = self.step(chunk)
                if result.get("killswitch_tripped"):
                    self._save_kill_events()
                    break
                if self._killswitch is not None:
                    self._killswitch.heartbeat()
                    if self._store_conn is not None:
                        assert self.state is not None
                        persist = self._killswitch.to_persistable_state()
                        from ztb.store.exec_io import save_killswitch_state

                        with contextlib.suppress(sqlite3.OperationalError):
                            save_killswitch_state(
                                self._store_conn,
                                self.state.exec_run_id,
                                persist["tripped"],
                                persist["hwm_equity"],
                                persist["last_heartbeat"],
                            )

        if self.config.loop and not self.config.once:
            try:
                self._run_polling_loop(data, symbol, timeframe, category)
            except PollingError as e:
                self._save_error("PollingError", str(e))
                self.state.errors.append(str(e))
            except sqlite3.OperationalError as e:
                self.state.errors.append(f"Fatal DB error in polling loop: {e}")

        from ztb.store.exec_io import update_exec_run_status

        self.state.status = "completed"
        update_exec_run_status(
            self._store_conn,
            self.state.exec_run_id,
            self.state.status,
            self.state.bars_processed,
            self.state.last_bar_ts,
        )

        self._restore_sigterm()

        if self._store_conn:
            self._store_conn.close()

        return self.state

    def _flush_bars_processed(self) -> None:
        from ztb.store.exec_io import update_exec_run_status

        assert self.state is not None
        with contextlib.suppress(sqlite3.OperationalError):
            update_exec_run_status(
                self._store_conn,
                self.state.exec_run_id,
                self.state.status,
                self.state.bars_processed,
                self.state.last_bar_ts,
            )

    def _run_polling_loop(
        self,
        data: DataFrame,
        symbol: str,
        timeframe: str,
        category: str,
    ) -> None:
        poll_interval: float = self.config.poll_interval_seconds or 60.0
        if poll_interval <= 0:
            interval_ms = interval_to_ms(timeframe)
            poll_interval = interval_ms / 1000.0 / 3.0

        assert self.state is not None

        consecutive_errors = 0
        max_errors = 3

        while not self._sigterm_stop:
            try:
                if self._check_killswitch():
                    self.state.errors.append("Killswitch tripped — stopping polling loop")
                    with contextlib.suppress(sqlite3.OperationalError):
                        self._save_error(
                            "KillswitchTripped",
                            "Killswitch tripped during polling loop",
                        )
                    break

                time_module.sleep(poll_interval)
                if self._check_killswitch():
                    self.state.errors.append(
                        "Killswitch tripped during sleep — stopping polling loop"
                    )
                    with contextlib.suppress(sqlite3.OperationalError):
                        self._save_error(
                            "KillswitchTripped",
                            "Killswitch tripped after sleep",
                        )
                    break
                old_len = len(data)
                data = self._fetch_new_bars(data, symbol, timeframe, category)
                new_len = len(data)

                if new_len > old_len:
                    for i in range(old_len, new_len):
                        chunk = data.iloc[: i + 1]
                        result = self.step(chunk)
                        if result.get("killswitch_tripped"):
                            break
                        if result.get("client_error"):
                            continue
                        if (
                            self.config.loop_flush_interval > 0
                            and self.state.bars_processed > 0
                            and self.state.bars_processed % self.config.loop_flush_interval == 0
                        ):
                            self._flush_bars_processed()
                else:
                    result = self.step(data)
                    if result.get("client_error"):
                        continue
                    if (
                        self.config.loop_flush_interval > 0
                        and self.state.bars_processed > 0
                        and self.state.bars_processed % self.config.loop_flush_interval == 0
                    ):
                        self._flush_bars_processed()
                consecutive_errors = 0
            except ClientError:
                continue
            except sqlite3.OperationalError as exc:
                consecutive_errors += 1
                err_msg = f"Polling loop DB error ({consecutive_errors}/{max_errors}): {exc}"
                self.state.errors.append(err_msg)
                if consecutive_errors >= max_errors:
                    self.state.errors.append("Max polling errors reached — stopping")
                    raise PollingError(err_msg) from exc
            except Exception as exc:
                consecutive_errors += 1
                err_msg = f"Polling loop error ({consecutive_errors}/{max_errors}): {exc}"
                self.state.errors.append(err_msg)
                with contextlib.suppress(sqlite3.OperationalError):
                    self._save_error("PollingError", str(exc))
                if consecutive_errors >= max_errors:
                    self.state.errors.append("Max polling errors reached — stopping")
                    raise PollingError(err_msg) from exc
