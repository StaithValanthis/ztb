from __future__ import annotations

import logging
import signal
import time as time_module
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from pandas import DataFrame

from ztb import __version__
from ztb.data.loader import load as load_data
from ztb.data.timeframes import interval_to_ms
from ztb.engine.pnl import PnLCalculator
from ztb.execution.bybit_client import BybitClient
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

logger = logging.getLogger(__name__)


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

    def step(
        self,
        data: DataFrame,
    ) -> dict[str, Any]:
        assert self.state is not None
        assert self._store_conn is not None
        assert self._idempotency is not None

        if self._check_killswitch():
            return {
                "killswitch_tripped": True,
                "bar_ts": str(data.index[-1] if len(data) > 0 else ""),
            }

        try:
            return self._step_impl(data)
        except ClientError as exc:
            error_msg = f"step ClientError: {exc}"
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
        total_available_balance = 0.0

        if not self.config.dry_run and self.client is not None:
            try:
                wallet = self.client.get_wallet_balance(coin="USDT")
                from ztb.execution.reconcile import compute_account_state

                actual = compute_account_state([], wallet)
                if actual.total_equity > 0:
                    equity = actual.total_equity
                total_available_balance = actual.total_available_balance
            except Exception:
                pass

            if self.config.mode == Mode.DEMO:
                equity = min(equity, self.config.initial_cash)

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
        target_qty = (
            round(target_signal * equity / close_price, asset_precision) if close_price > 0 else 0.0
        )
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
            self._last_executed_signal = target_signal
            self._signal_initialized = True

        if abs(delta) > 1e-12 and signal_changed:
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

            if self.client is None:
                raise ExecutionError("No BybitClient configured for live trading")

            reconcile_report = self._reconcile(current_position, close_price, bar_ts)

            if self._killswitch is not None:
                self._killswitch.check_reconcile_drift(reconcile_report.position_drift)
                if self._killswitch.is_tripped:
                    self._save_kill_events()
                    result["killswitch_tripped"] = True
                    self.state.bars_processed += 1
                    self.state.last_bar_ts = bar_ts
                    return result

            side = OrderSide.BUY if delta > 0 else OrderSide.SELL
            qty = round(abs(delta), asset_precision)

            reduce_only = (delta < 0 and current_position > 0) or (
                delta > 0 and current_position < 0
            )

            if not reduce_only and total_available_balance > 0 and close_price > 0:
                max_notional = total_available_balance * self.config.max_leverage
                max_qty = round(max_notional / close_price, asset_precision)
                if qty > max_qty + 1e-12:
                    self.state.errors.append(
                        f"Qty capped by total available balance: {qty} -> {max_qty} "
                        f"(total_available={total_available_balance:.2f}, "
                        f"max_notional={max_notional:.2f})"
                    )
                    qty = max_qty
                    if qty < 1e-12:
                        result["order_skipped"] = True
                        result["skip_reason"] = (
                            f"Qty capped to {max_qty} by balance limit, below minimum"
                        )
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
                        self._last_executed_signal = target_signal
                        self._signal_initialized = True
                        return result

            order_result = self.client.place_order(
                symbol=symbol,
                side=side,
                qty=qty,
                order_type=OrderType.MARKET,
                order_link_id=order_link_id,
                reduce_only=reduce_only,
            )
            if order_result.get("skipped"):
                result["order_skipped"] = True
                result["skip_reason"] = order_result.get("reason", "")
                self.state.errors.append(f"Order skipped: {order_result.get('reason', '')}")
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

            # Real fill pipeline: fetch actual fills from exchange
            real_fills: list[dict[str, Any]] = []
            from ztb.execution.reconcile import parse_fills as _parse_fills

            try:
                raw_fills = self.client.get_executions(order_id=order_id)
                for f in _parse_fills(raw_fills):
                    real_fills.append(
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
                    )
            except Exception:
                logger.warning(
                    "Failed to fetch fills for order %s, falling back to synthetic fill",
                    order_id,
                )
                self._save_error("FillFetchError", f"Failed to fetch fills for order {order_id}")
                real_fills = []

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

            result["order_placed"] = True
            result["order"] = {"order_id": order_id, "order_link_id": order_link_id}

            self._reconcile(target_qty, close_price, bar_ts)

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
            end=None,
        )
        if extended is None or extended.empty:
            raise ExecutionError(
                f"Cannot fetch enough historical data for {symbol} {timeframe}: "
                f"need {warmup} bars for warmup, exchange returned empty data"
            )
        if len(extended) < warmup:
            raise ExecutionError(
                f"Exchange cannot provide enough historical data for {symbol} {timeframe}: "
                f"got {len(extended)} bars, need {warmup} for warmup"
            )
        return extended

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
            end=None,
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
        self._setup_sigterm()

        if self.config.mode == Mode.DEMO and not self.config.dry_run and self.client is not None:
            try:
                self.client.top_up_demo_account("USDT", str(self.config.initial_cash))
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
            for i in range(warmup, len(data)):
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

        from ztb.store.exec_io import update_exec_run_status

        self.state.status = "completed"
        update_exec_run_status(
            self._store_conn,
            self.state.exec_run_id,
            self.state.status,
            self.state.bars_processed,
        )

        self._restore_sigterm()

        if self._store_conn:
            self._store_conn.close()

        return self.state

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
            if self._check_killswitch():
                self.state.errors.append("Killswitch tripped — stopping polling loop")
                self._save_error("KillswitchTripped", "Killswitch tripped during polling loop")
                break

            try:
                time_module.sleep(poll_interval)
                data = self._fetch_new_bars(data, symbol, timeframe, category)
                result = self.step(data)
                if result.get("client_error"):
                    continue
                consecutive_errors = 0
            except ClientError:
                continue
            except Exception as exc:
                consecutive_errors += 1
                err_msg = f"Polling loop error ({consecutive_errors}/{max_errors}): {exc}"
                self.state.errors.append(err_msg)
                self._save_error("PollingError", str(exc))
                if consecutive_errors >= max_errors:
                    self.state.errors.append("Max polling errors reached — stopping")
                    raise PollingError(err_msg) from exc
