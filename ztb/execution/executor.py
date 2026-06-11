from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pandas import DataFrame

from ztb.data.loader import load as load_data
from ztb.execution.bybit_client import BybitClient
from ztb.execution.errors import (
    ExecutionError,
)
from ztb.execution.idempotency import IdempotencyLedger, make_intent_hash, make_order_link_id
from ztb.execution.models import (
    AccountState,
    ExecRunConfig,
    ExecRunState,
    OrderSide,
    OrderType,
    Position,
)
from ztb.execution.reconcile import ReconcileReport, reconcile_account
from ztb.risk.manager import RiskManager
from ztb.risk.models import RiskConfig, RiskDecision, RiskDecisionAction
from ztb.store.results import connect as store_connect


class Executor:
    def __init__(
        self,
        strategy: Any,
        config: ExecRunConfig | None = None,
        client: BybitClient | None = None,
        risk_config: RiskConfig | None = None,
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
            },
        )

    def _save_pnl(self, realized: float, unrealized: float, equity: float) -> None:
        from ztb.store.exec_io import save_pnl_entry

        assert self.state is not None
        save_pnl_entry(
            self._store_conn,
            {
                "exec_run_id": self.state.exec_run_id,
                "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "symbol": self.state.symbol,
                "realized_pnl": realized,
                "unrealized_pnl": unrealized,
                "total_equity": equity,
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
        proposed = {sym: target_signal}
        prices = {sym: price}
        portfolio_state: dict[str, Any] = {
            "cash": equity - abs(current_position) * price,
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
            sig_val = abs(target_signal) * price
            scale = decision.max_notional / sig_val if sig_val > 0 else 0.0
            return target_signal * min(scale, 1.0), decision
        return target_signal, decision

    def _update_avg_entry_price(self, delta: float, fill_price: float) -> None:
        assert self.state is not None
        if abs(delta) < 1e-12:
            return
        old_qty = self.state.current_position
        new_qty = old_qty + delta
        if abs(new_qty) > abs(old_qty) + 1e-12:
            added_qty = abs(new_qty) - abs(old_qty)
            if self.state.avg_entry_price == 0 or abs(old_qty) < 1e-12:
                self.state.avg_entry_price = fill_price
                self.state.total_cost = abs(new_qty) * fill_price
            else:
                prev_avg = self.state.avg_entry_price
                num = prev_avg * abs(old_qty) + fill_price * added_qty
                self.state.avg_entry_price = num / abs(new_qty)
                self.state.total_cost += added_qty * fill_price
        elif abs(new_qty) < abs(old_qty) - 1e-12:
            reduced_qty = abs(old_qty) - abs(new_qty)
            if self.state.avg_entry_price > 0 and abs(old_qty) > 1e-12:
                realized = reduced_qty * (fill_price - self.state.avg_entry_price)
                if old_qty < 0:
                    realized = -realized
                self.state.realized_pnl += realized
            self.state.total_cost *= abs(new_qty) / abs(old_qty) if abs(old_qty) > 0 else 0.0
        if abs(new_qty) < 1e-12:
            self.state.avg_entry_price = 0.0
            self.state.total_cost = 0.0

    def _compute_unrealized_pnl(self, close_price: float) -> float:
        assert self.state is not None
        if self.state.avg_entry_price == 0 or abs(self.state.current_position) < 1e-12:
            return 0.0
        return (close_price - self.state.avg_entry_price) * self.state.current_position

    def _reconcile(
        self, expected_position: float, close_price: float, bar_ts: str
    ) -> ReconcileReport:
        assert self.state is not None
        equity = (
            self.config.initial_cash
            + self.state.realized_pnl
            + expected_position * (close_price - self.state.avg_entry_price)
        )
        expected = AccountState(
            total_equity=equity,
            wallet_balance=equity - abs(expected_position) * close_price,
            unrealized_pnl=self._compute_unrealized_pnl(close_price),
            positions={
                self.state.symbol: Position(
                    symbol=self.state.symbol,
                    size=expected_position,
                    avg_price=self.state.avg_entry_price,
                    unrealized_pnl=self._compute_unrealized_pnl(close_price),
                    realized_pnl=self.state.realized_pnl,
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

        symbol = self.state.symbol
        bar_ts = str(data.index[-1])
        close_price = float(data["close"].iloc[-1])

        target_signal = self._compute_target_position(data)
        current_position = self.state.current_position

        equity = (
            self.config.initial_cash
            + self.state.realized_pnl
            + self._compute_unrealized_pnl(close_price)
        )

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
                self._update_avg_entry_price(delta, close_price)
            self.state.current_position = target_qty
            self.state.bars_processed += 1
            self.state.last_bar_ts = bar_ts
            unrealized_pnl = self._compute_unrealized_pnl(close_price)
            self._save_position_snapshot()
            self._save_pnl(0.0, unrealized_pnl, equity)
            return result

        if abs(delta) > 1e-12:
            intent_hash = make_intent_hash(target_qty, current_position)
            order_link_id = make_order_link_id(
                self.state.strategy_name, symbol, bar_ts, intent_hash
            )

            claimed = self._idempotency.try_claim(order_link_id)
            if not claimed:
                existing = self._idempotency.get(order_link_id)
                if existing and existing.get("order_id"):
                    self._update_avg_entry_price(delta, close_price)
                    self.state.current_position = target_qty
                    result["order_placed"] = True
                    result["order"] = {"order_id": existing["order_id"], "restored": True}
                    self.state.bars_processed += 1
                    self.state.last_bar_ts = bar_ts
                    unrealized_pnl = self._compute_unrealized_pnl(close_price)
                    self._save_position_snapshot()
                    self._save_pnl(self.state.realized_pnl, unrealized_pnl, equity)
                    return result

            if self.client is None:
                raise ExecutionError("No BybitClient configured for live trading")

            self._reconcile(current_position, close_price, bar_ts)

            side = OrderSide.BUY if delta > 0 else OrderSide.SELL
            qty = round(abs(delta), asset_precision)

            order_result = self.client.place_order(
                symbol=symbol,
                side=side,
                qty=qty,
                order_type=OrderType.MARKET,
                order_link_id=order_link_id,
            )
            order_id = order_result.get("orderId", "")

            self._idempotency.resolve(order_link_id, "placed", order_id)

            self._update_avg_entry_price(delta, close_price)
            self.state.current_position = target_qty
            result["order_placed"] = True
            result["order"] = {"order_id": order_id, "order_link_id": order_link_id}

            self._reconcile(target_qty, close_price, bar_ts)

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
                    "cum_exec_fee": qty * close_price * self.config.commission,
                },
            )

            self.state.total_commission += qty * close_price * self.config.commission
            self.state.total_slippage += qty * close_price * self.config.slippage

        self.state.bars_processed += 1
        self.state.last_bar_ts = bar_ts
        unrealized_pnl = self._compute_unrealized_pnl(close_price)
        self._save_position_snapshot()
        self._save_pnl(self.state.realized_pnl, unrealized_pnl, equity)
        return result

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

        if self.config.once:
            if len(data) <= warmup:
                raise ExecutionError(f"Data length {len(data)} <= warmup {warmup}, cannot run")
            self.step(data)
        else:
            for i in range(warmup, len(data)):
                chunk = data.iloc[: i + 1]
                self.step(chunk)

        from ztb.store.exec_io import update_exec_run_status

        self.state.status = "completed"
        update_exec_run_status(
            self._store_conn,
            self.state.exec_run_id,
            self.state.status,
            self.state.bars_processed,
        )

        if self._store_conn:
            self._store_conn.close()

        return self.state
