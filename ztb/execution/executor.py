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
from ztb.strategies.base import RiskProfile, ScaleOutTier
from ztb.utils.balance import extract_available_balance

logger = logging.getLogger(__name__)


def _safe_float(val: str | float | None, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


_PROFILE_DEFAULTS: dict[str, Any] = {
    "sl_pct": 0.02,
    "tp_pct": 0.03,
    "leverage": 1.0,
    "trail_pct": 0.0,
    "activation_pct": 0.0,
    "trail_atr_mult": 0.0,
    "scale_outs": (),
}
# RiskProfile field -> ExecRunConfig attr (leverage reuses the max_leverage sizing cap).
_CONFIG_FIELD: dict[str, str] = {"leverage": "max_leverage"}


def _resolve_profile_field(strategy: Any, config: Any, field: str) -> Any:
    """Effective per-strategy trade-management value.

    Precedence:
      1) strategy.get_risk_profile().<field>  (non-None wins)
      2) strategy.params[field]               (ONLY sl_pct/tp_pct; PR#199 back-compat)
      3) config.<mapped attr>                 (present & not None; explicit 0.0 disable wins)
      4) _PROFILE_DEFAULTS[field]             (hard default)

    None (not declared) falls through; 0.0 (explicit disable) is returned as-is.
    The config value is authoritative even at 0.0 because the CLI passes
    sl_pct/tp_pct=0.0 (not None) when the flag is omitted.
    """
    get = getattr(strategy, "get_risk_profile", None)
    prof = get() if callable(get) else getattr(strategy, "risk_profile", None)
    if isinstance(prof, RiskProfile):
        val = getattr(prof, field, None)
        if val is not None:
            return val
    if field in ("sl_pct", "tp_pct"):
        params = getattr(strategy, "params", None)
        if isinstance(params, dict) and params.get(field) is not None:
            return params[field]
    cfg_attr = _CONFIG_FIELD.get(field, field)
    cval = getattr(config, cfg_attr, None)
    if cval is not None:
        return cval
    return _PROFILE_DEFAULTS[field]


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
        self._active_sl_tp: dict[str, dict[str, Any]] = {}
        self._applied_leverage: dict[str, float] = {}
        self._dll_day: str | None = None
        self._dll_day_start_realized: float = 0.0

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
            for sym in list(self._active_sl_tp.keys()):
                self._clear_sl_tp(sym, side=OrderSide.BUY, position_size=0.0)

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

    def _resolve_sizing_leverage(self) -> float:
        """Leverage for LOCAL margin sizing caps. Always returns a value:
        per-strategy declared > config.max_leverage > hard default."""
        return float(_resolve_profile_field(self.strategy, self.config, "leverage"))

    def _resolve_exchange_leverage(self) -> float | None:
        """Leverage to SET on the exchange. Only when the strategy EXPLICITLY
        declares risk_profile.leverage (None => leave the account default)."""
        get = getattr(self.strategy, "get_risk_profile", None)
        prof = get() if callable(get) else getattr(self.strategy, "risk_profile", None)
        lev = prof.leverage if isinstance(prof, RiskProfile) else None
        if isinstance(lev, (int, float)) and not isinstance(lev, bool) and lev > 0:
            return float(lev)
        return None

    def _resolve_limit_price(self, side: OrderSide, ref_price: float, symbol: str) -> float:
        """On-tick limit price offset from the reference price; BUY rests below
        market, SELL rests above (both aim to post as a maker)."""
        off = self.config.limit_offset_pct
        raw = ref_price * (1.0 - off) if side == OrderSide.BUY else ref_price * (1.0 + off)
        if self.client is not None:
            try:
                tick = self.client.get_tick_size(symbol)
                if tick > 0:
                    step_fn = (
                        self.client.ceil_to_step
                        if side == OrderSide.SELL
                        else self.client.round_to_step
                    )
                    return float(step_fn(raw, tick))
            except Exception:  # pragma: no cover - best-effort tick lookup
                pass
        return float(raw)

    def _merge_fills(
        self, a: list[dict[str, Any]], b: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for f in list(a) + list(b):
            fid = str(f.get("fill_id", ""))
            key = fid or (
                f"{f.get('order_id', '')}:{f.get('price', '')}:"
                f"{f.get('qty', '')}:{f.get('filled_at', '')}"
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(f)
        return out

    def _round_qty_down(self, symbol: str, qty: float) -> float:
        if qty <= 0.0 or self.client is None:
            return max(0.0, qty)
        try:
            step = self.client.get_qty_step(symbol)
        except Exception:  # pragma: no cover - best-effort step lookup
            step = 0.0
        if step > 0:
            # add a negligible fraction of a step so float repr (e.g. 0.6/0.001
            # = 599.999...) cannot floor away a whole step from the remainder.
            return float(self.client.round_to_step(qty + step * 1e-6, step))
        return qty

    def _execute_limit_lifecycle(
        self,
        symbol: str,
        side: OrderSide,
        qty: float,
        order_id: str,
        order_link_id: str,
    ) -> dict[str, Any]:
        """Authoritative limit-entry lifecycle. Give the resting maker a brief
        chance to fill, then CANCEL FIRST so no later fill can race a fallback,
        re-read the actual fills, fill only the UNFILLED remainder with a market
        order (if enabled), and NEVER synthesize a fill. Returns the real fills
        plus the order id/link/type to attribute downstream.

        v1 limitation (limit orders are OFF by default — order_type defaults to
        market): the shared restart/lost-response recovery paths (the top-of-bar
        synthetic restore and the M1 _reconcile_pending_order block) assume
        market-fill-at-close semantics. If the process crashes mid-bar while a
        limit is resting, on restart those paths may mis-attribute the entry at
        close_price rather than the fill price (the next bar re-reconciles
        against the exchange). Making them fully limit-aware requires reworking
        that shared idempotency code; tracked separately. Normal (non-restart)
        operation is correct and fully covered by tests."""
        assert self.client is not None
        assert self._idempotency is not None
        executed_order_type = "Limit"
        pre = self._poll_fills(order_id=order_id, order_link_id=order_link_id)
        try:
            self.client.cancel_order(symbol=symbol, order_id=order_id, order_link_id=order_link_id)
        except Exception as exc:  # best-effort cleanup — must never abort the bar
            logger.debug("limit cancel for %s returned: %s", order_id, exc)
        post = self._poll_fills(order_id=order_id, order_link_id=order_link_id)
        real_fills = self._merge_fills(pre, post)
        filled_qty = sum(float(f["qty"]) for f in real_fills)
        # Only a FULLY filled limit is restorable as 'placed' on restart (the
        # restore path books the full delta). A partial or unfilled limit is
        # resolved terminally so a restart reconciles against the exchange
        # (via _reconcile_pending_order) instead of synth-restoring a wrong qty.
        if filled_qty >= qty - 1e-9:
            self._idempotency.resolve(order_link_id, "placed", order_id)
        else:
            self._idempotency.resolve(order_link_id, "cancelled")
        out_order_id, out_link = order_id, order_link_id
        remainder = self._round_qty_down(symbol, qty - filled_qty)
        if remainder > 0.0 and self.config.limit_fallback_market:
            fb_link = f"{order_link_id}-mkt"
            if not self._idempotency.try_claim(fb_link):
                # already placed in a prior (crashed) run for this bar — do not
                # double-fire the fallback on restart.
                logger.info("limit fallback %s already claimed — skipping", fb_link)
            else:
                logger.info(
                    "limit %s filled %.8f/%.8f — market fallback %s for %.8f",
                    order_link_id,
                    filled_qty,
                    qty,
                    fb_link,
                    remainder,
                )
                try:
                    fb_result = self.client.place_order(
                        symbol=symbol,
                        side=side,
                        qty=remainder,
                        order_type=OrderType.MARKET,
                        order_link_id=fb_link,
                        reduce_only=False,
                    )
                    if not fb_result.get("skipped"):
                        fb_id = str(fb_result.get("orderId", ""))
                        if fb_id:
                            self._idempotency.resolve(fb_link, "placed", fb_id)
                            fb_fills = self._poll_fills(order_id=fb_id, order_link_id=fb_link)
                            real_fills = self._merge_fills(real_fills, fb_fills)
                            out_order_id, out_link = fb_id, fb_link
                            executed_order_type = "Limit+Market" if filled_qty > 0 else "Market"
                    else:
                        self._idempotency.resolve(fb_link, "skipped")
                except Exception as exc:  # never abort the bar on a fallback error
                    self._idempotency.resolve(fb_link, "failed")
                    self._save_error("FallbackOrderError", f"limit fallback failed: {exc}")
        return {
            "real_fills": real_fills,
            "order_id": out_order_id,
            "order_link_id": out_link,
            "executed_order_type": executed_order_type,
        }

    def _apply_leverage(self, symbol: str) -> None:
        """Set per-strategy leverage on the exchange once, when flat before the
        first entry. Idempotent; no-op in dry_run or when not declared."""
        if self.client is None or self.config.dry_run:
            return
        lev = self._resolve_exchange_leverage()
        if lev is None or lev <= 0:
            return
        if self._applied_leverage.get(symbol) == lev:
            return
        try:
            self.client.set_leverage(symbol, buy_leverage=lev, sell_leverage=lev)
            self._applied_leverage[symbol] = lev
            logger.info("Applied leverage %sx for %s", lev, symbol)
        except Exception:
            logger.warning("set_leverage failed for %s — continuing", symbol)

    def _daily_loss_breached(self, bar_ts: str) -> bool:
        """Account-level daily realized-loss circuit breaker. Blocks NEW entries
        (existing positions / exits unaffected) once today's realized PnL drops to
        -limit * initial_cash. Resets at the UTC day boundary. Disabled at <= 0."""
        limit = getattr(self.config, "daily_loss_limit_pct", 0.0)
        if not limit or limit <= 0.0:
            return False
        day = str(bar_ts)[:10]
        if self._dll_day != day:
            self._dll_day = day
            self._dll_day_start_realized = self._pnl.realized_pnl
        daily_realized = self._pnl.realized_pnl - self._dll_day_start_realized
        return daily_realized <= -(limit * self.config.initial_cash)

    def _seed_scale_outs(
        self,
        symbol: str,
        entry_qty: float,
        avg_entry: float,
        bar_ts: str,
        scale_outs: tuple[ScaleOutTier, ...],
    ) -> None:
        """Seed per-tier scale-out state at entry (absolute trigger prices)."""
        from ztb.execution.idempotency import make_intent_hash

        is_long = entry_qty > 0
        state = self._active_sl_tp.setdefault(symbol, {})
        state["entry_qty"] = entry_qty
        state["avg_entry"] = avg_entry
        state["entry_bar_ts"] = str(bar_ts)
        state["intent_hash"] = make_intent_hash(entry_qty, avg_entry)
        state["fired_frac"] = 0.0
        state["scale_tiers"] = [
            {
                "tier_index": i,
                "close_frac": float(t.close_frac),
                "fired": False,
                "at_price": avg_entry * (1.0 + t.at_pct)
                if is_long
                else avg_entry * (1.0 - t.at_pct),
            }
            for i, t in enumerate(scale_outs)
        ]

    def _check_scale_outs(self, symbol: str, close_price: float) -> None:
        """Fire any crossed scale-out tiers: a reduce_only partial close of
        ``close_frac`` of the ORIGINAL entry size, then re-assert SL on the
        remainder. Idempotent per tier (fired flag + deterministic link_id)."""
        if self.client is None or self.config.dry_run or self.state is None:
            return
        state = self._active_sl_tp.get(symbol)
        if not state or not state.get("scale_tiers"):
            return
        entry_qty = float(state.get("entry_qty", 0.0))
        avg_entry = float(state.get("avg_entry", 0.0))
        if abs(entry_qty) < 1e-12 or avg_entry <= 0.0:
            return
        is_long = entry_qty > 0
        try:
            step = self.client.get_qty_step(symbol)
        except Exception:
            step = 0.0
        try:
            min_qty = self.client.get_min_order_qty(symbol)
        except Exception:
            min_qty = 0.0
        fired_any = False
        for tier in state["scale_tiers"]:
            if tier.get("fired"):
                continue
            at_price = float(tier["at_price"])
            crossed = (close_price >= at_price) if is_long else (close_price <= at_price)
            if not crossed:
                continue
            scale_qty = abs(entry_qty) * float(tier["close_frac"])
            if isinstance(step, (int, float)) and step > 0:
                scale_qty = round_to_step(scale_qty, step)
            if scale_qty <= 0.0 or (min_qty > 0 and scale_qty < min_qty):
                logger.info(
                    "scale-out tier %s qty %s below min — skip", tier["tier_index"], scale_qty
                )
                continue
            close_side = OrderSide.SELL if is_long else OrderSide.BUY
            from ztb.execution.idempotency import make_sl_tp_order_link_id

            link_id = make_sl_tp_order_link_id(
                self.state.strategy_name,
                symbol,
                str(state.get("entry_bar_ts", "")),
                str(state.get("intent_hash", "")),
                f"scaleout{tier['tier_index']}",
            )
            if self._idempotency is not None and not self._idempotency.try_claim(link_id):
                tier["fired"] = True  # already placed in a prior run
                state["fired_frac"] = min(
                    1.0, float(state.get("fired_frac", 0.0)) + float(tier["close_frac"])
                )
                continue
            try:
                self.client.place_order(
                    symbol,
                    close_side,
                    scale_qty,
                    order_type=OrderType.MARKET,
                    order_link_id=link_id,
                    reduce_only=True,
                )
                fill_delta = -scale_qty if is_long else scale_qty
                comm = scale_qty * close_price * self.config.commission
                slip = scale_qty * close_price * self.config.slippage
                self._pnl.apply_fill(fill_delta, close_price, commission=comm, slippage=slip)
                self._sync_pnl_state()
                tier["fired"] = True
                state["fired_frac"] = min(
                    1.0, float(state.get("fired_frac", 0.0)) + scale_qty / abs(entry_qty)
                )
                if self._idempotency is not None:
                    self._idempotency.resolve(link_id, "placed")
                fired_any = True
                logger.info(
                    "scale-out tier %s: closed %s %s at %s",
                    tier["tier_index"],
                    scale_qty,
                    symbol,
                    close_price,
                )
            except Exception:
                logger.warning(
                    "scale-out tier %s failed for %s — continuing", tier["tier_index"], symbol
                )
        if fired_any:
            remaining = self._pnl.position
            if abs(remaining) > 1e-12:
                preserved = {
                    k: state[k]
                    for k in (
                        "scale_tiers",
                        "entry_qty",
                        "avg_entry",
                        "fired_frac",
                        "entry_bar_ts",
                        "intent_hash",
                    )
                    if k in state
                }
                pos_side = OrderSide.BUY if remaining > 0 else OrderSide.SELL
                sl_pct = _resolve_profile_field(self.strategy, self.config, "sl_pct")
                self._apply_sl_tp(symbol, pos_side, remaining, avg_entry, sl_pct, 0.0)
                self._active_sl_tp.setdefault(symbol, {}).update(preserved)
            else:
                # fully scaled out — clear state so a stale fired_frac=1.0 can never
                # zero every future target_qty and freeze the symbol flat.
                self._active_sl_tp.pop(symbol, None)
                self._signal_initialized = False

    def _compute_atr(self, data: Any, period: int = 14) -> float:
        """ATR(period) last value from the bar window for ATR-based trailing.
        Returns 0.0 (disable ATR trailing) on insufficient/invalid data."""
        try:
            from ztb.features.indicators import atr as _atr

            if data is None or len(data) < period + 1:
                return 0.0
            series = _atr(data["high"], data["low"], data["close"], period)
            val = float(series.iloc[-1])
            return val if val > 0.0 and not pd.isna(val) else 0.0
        except Exception:
            return 0.0

    def _apply_sl_tp(
        self,
        symbol: str,
        side: OrderSide,
        position_size: float,
        avg_entry: float,
        sl_pct: float,
        tp_pct: float,
        trail_pct: float = 0.0,
        activation_pct: float = 0.0,
        trail_atr_mult: float = 0.0,
        atr: float = 0.0,
    ) -> bool:
        if self.client is None or self.config.dry_run:
            return False
        if sl_pct <= 0.0 and tp_pct <= 0.0 and trail_pct <= 0.0 and trail_atr_mult <= 0.0:
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
        trailing_stop_dist: float = 0.0
        if trail_pct > 0.0:
            trailing_stop_dist = avg_entry * trail_pct
        elif trail_atr_mult > 0.0 and atr > 0.0:
            trailing_stop_dist = atr * trail_atr_mult
        active_price: float = 0.0
        if trailing_stop_dist > 0.0 and activation_pct > 0.0:
            active_price = (
                avg_entry * (1.0 + activation_pct)
                if is_long
                else avg_entry * (1.0 - activation_pct)
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
                trailing_stop=trailing_stop_dist,
                active_price=active_price,
            )
            sl_link_id: str | None = None
            tp_link_id: str | None = None
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
            self._active_sl_tp[symbol] = {
                "sl_price": sl_price,
                "tp_price": tp_price,
                "trailing_stop": trailing_stop_dist,
                "sl_link_id": sl_link_id,
                "tp_link_id": tp_link_id,
            }
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
        entry = self._active_sl_tp.pop(symbol, {})
        if self._idempotency is not None and self.state is not None:
            sl_link_id = entry.get("sl_link_id")
            tp_link_id = entry.get("tp_link_id")
            if sl_link_id or tp_link_id:
                with contextlib.suppress(Exception):
                    for lid in [sl_link_id, tp_link_id]:
                        if lid:
                            self._idempotency.conn.execute(
                                "DELETE FROM idempotency WHERE order_link_id = ?", (lid,)
                            )
                    self._idempotency.conn.commit()
            else:
                with contextlib.suppress(Exception):
                    self._idempotency.conn.execute(
                        "DELETE FROM idempotency WHERE order_link_id LIKE ?",
                        (f"%:{symbol}:%",),
                    )
                    self._idempotency.conn.commit()
        return True

    def _cleanup_orphan_sl_tp(self) -> None:
        if self.client is None or self.config.dry_run:
            return
        try:
            active_stops = self.client.get_active_trading_stops()
        except Exception:
            logger.warning("orphan-cleanup: get_active_trading_stops failed — skipping")
            return
        for pos in active_stops:
            sym = pos.get("symbol", "")
            if not sym or sym in self._active_sl_tp:
                continue
            try:
                self.client.set_trading_stop(
                    symbol=sym,
                    side=OrderSide.BUY,
                    position_size=0.01,
                    stop_loss=0.0,
                    take_profit=0.0,
                )
                logger.info("orphan-cleanup: cleared stale SL/TP for %s", sym)
            except Exception:
                logger.warning("orphan-cleanup: failed to clear %s — continuing", sym)
            self._active_sl_tp.pop(sym, None)

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

    def _fetch_and_record_sltp_fills(self, symbol: str) -> list[dict[str, Any]]:
        if self.client is None or self.config.dry_run:
            return []
        assert self.state is not None
        recorded: list[dict[str, Any]] = []
        try:
            orders = self.client.get_order_history(symbol=symbol, limit=50)
            sltp_orders = [
                o
                for o in orders
                if o.get("stopOrderType") in ("StopLoss", "TakeProfit")
                and o.get("orderStatus") in ("Filled", "PartiallyFilled")
            ]
            for order in sltp_orders:
                order_id = order.get("orderId", "")
                order_link_id = order.get("orderLinkId", "")
                if not order_id:
                    continue
                raw_fills = self.client.get_executions(symbol=symbol, order_id=order_id)
                from ztb.execution.reconcile import parse_fills as _parse_fills

                parsed = list(_parse_fills(raw_fills))
                for fill in parsed:
                    fill_row = {
                        "fill_id": fill.exec_id,
                        "order_link_id": order_link_id,
                        "exec_run_id": self.state.exec_run_id,
                        "order_id": fill.order_id,
                        "symbol": fill.symbol,
                        "side": fill.side.value,
                        "price": fill.price,
                        "qty": fill.qty,
                        "commission": fill.commission,
                        "realized_pnl": 0.0,
                        "filled_at": fill.timestamp,
                        "sufficient_sample": 1,
                        "code_version": __version__,
                    }
                    from ztb.store.exec_io import save_exec_fill

                    save_exec_fill(self._store_conn, fill_row)
                    recorded.append(fill_row)
            if recorded:
                logger.info("Recorded %d SL/TP fill(s) for %s", len(recorded), symbol)
        except Exception:
            logger.warning("Failed to fetch/record SL/TP fills for %s", symbol)
        return recorded

    def modify_tp_sl(
        self,
        symbol: str,
        sl_price: float | None = None,
        tp_price: float | None = None,
        trailing_stop: float | None = None,
        activation_price: float | None = None,
    ) -> bool:
        """Modify SL/TP levels on an open position by absolute price.

        Args:
            symbol: Trading pair (e.g. "BTCUSDT").
            sl_price: New stop-loss price. None leaves current unchanged.
            tp_price: New take-profit price. None leaves current unchanged.
            trailing_stop: New trailing stop distance. None leaves current.
            activation_price: New activation price for trailing stop. None leaves current.

        Returns:
            True if the trading-stop API call succeeded.
        """
        if self.client is None or self.config.dry_run:
            return False
        assert self.state is not None
        state = self._active_sl_tp.get(symbol, {})
        side = OrderSide.BUY if self._pnl.position > 0 else OrderSide.SELL
        pos_size = abs(self._pnl.position)
        if pos_size < 1e-12 and symbol not in self._active_sl_tp:
            logger.warning("modify_tp_sl: no position for %s — skipping", symbol)
            return False
        current_sl = state.get("sl_price", 0.0)
        current_tp = state.get("tp_price", 0.0)
        current_ts = state.get("trailing_stop", 0.0)
        current_ap = state.get("activation_price", 0.0)
        effective_sl = sl_price if sl_price is not None else current_sl
        effective_tp = tp_price if tp_price is not None else current_tp
        effective_ts = trailing_stop if trailing_stop is not None else current_ts
        effective_ap = activation_price if activation_price is not None else current_ap
        try:
            self.client.set_trading_stop(
                symbol=symbol,
                side=side,
                position_size=max(pos_size, 0.01),
                stop_loss=effective_sl,
                take_profit=effective_tp,
                trailing_stop=effective_ts,
                active_price=effective_ap,
            )
            self._active_sl_tp[symbol] = {
                "sl_price": effective_sl,
                "tp_price": effective_tp,
                "trailing_stop": effective_ts,
                "activation_price": effective_ap,
            }
            return True
        except Exception:
            logger.warning("modify_tp_sl failed for %s — continuing", symbol)
            return False

    def modify_tp_sl_by_pct(
        self,
        symbol: str,
        sl_pct: float | None = None,
        tp_pct: float | None = None,
    ) -> bool:
        """Modify SL/TP on an open position by percentage of avg entry price.

        Args:
            symbol: Trading pair.
            sl_pct: New stop-loss as fraction of entry (e.g. 0.02 = 2%).
                    Pass 0.0 to clear SL.
            tp_pct: New take-profit as fraction of entry.
                    Pass 0.0 to clear TP.

        Returns:
            True if the trading-stop API call succeeded.
        """
        avg_entry = self._pnl.avg_entry_price
        if avg_entry <= 0.0:
            logger.warning("modify_tp_sl_by_pct: no avg_entry for %s — skipping", symbol)
            return False
        is_long = self._pnl.position > 0
        sl_price: float | None = 0.0
        tp_price: float | None = 0.0
        if sl_pct is not None and sl_pct > 0.0:
            sl_price = avg_entry * (1.0 - sl_pct) if is_long else avg_entry * (1.0 + sl_pct)
        elif sl_pct is not None:
            sl_price = 0.0
        else:
            sl_price = None
        if tp_pct is not None and tp_pct > 0.0:
            tp_price = avg_entry * (1.0 + tp_pct) if is_long else avg_entry * (1.0 - tp_pct)
        elif tp_pct is not None:
            tp_price = 0.0
        else:
            tp_price = None
        return self.modify_tp_sl(symbol, sl_price=sl_price, tp_price=tp_price)

    def cancel_tp_sl(self, symbol: str) -> bool:
        """Cancel both stop-loss and take-profit on an open position.

        Args:
            symbol: Trading pair.

        Returns:
            True if cancellation succeeded.
        """
        return self._clear_sl_tp(symbol)

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

        self._check_scale_outs(symbol, close_price)

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
                equity, available_balance * self._resolve_sizing_leverage()
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

        scale_state = self._active_sl_tp.get(symbol)
        if (
            scale_state
            and scale_state.get("scale_tiers")
            and float(scale_state.get("fired_frac", 0.0)) > 0.0
            and abs(current_position) > 1e-12
            and target_qty * float(scale_state.get("entry_qty", 0.0)) > 0
        ):
            target_qty *= 1.0 - float(scale_state["fired_frac"])

        if self._daily_loss_breached(bar_ts):
            if target_qty * current_position < 0:
                target_qty = 0.0  # block flip into new opposite exposure (close to flat)
            elif abs(target_qty) > abs(current_position):
                target_qty = current_position  # block same-direction adds (hold)

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

            self._fetch_and_record_sltp_fills(symbol)

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
                self._fetch_and_record_sltp_fills(symbol)
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
                max_notional = available_balance * self._resolve_sizing_leverage()
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

            if not reduce_only and abs(current_position) < 1e-8:
                self._apply_leverage(symbol)
            use_limit = (
                self.config.order_type == OrderType.LIMIT
                and not reduce_only
                and not flip
                and abs(current_position) < 1e-8
            )
            executed_order_type = "Limit" if use_limit else "Market"
            limit_price = (
                self._resolve_limit_price(side, close_price, symbol) if use_limit else None
            )
            try:
                order_result = self.client.place_order(
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    order_type=OrderType.LIMIT if use_limit else OrderType.MARKET,
                    price=limit_price,
                    order_link_id=order_link_id,
                    reduce_only=reduce_only,
                )
            except ClientError as exc:
                if "OrderLinkedID is duplicate" in str(exc):
                    matched = self._reconcile_pending_order(symbol, order_link_id)
                    if matched:
                        if use_limit:
                            # A limit order may be resting (unfilled) or filled at
                            # the limit price — never book the full qty at close, and
                            # only resolve 'placed' when something actually filled.
                            booked = float(matched.get("cumExecQty") or 0.0)
                            avgp = float(matched.get("avgPrice") or 0.0) or close_price
                            if booked > 0:
                                self._idempotency.resolve(
                                    order_link_id, "placed", matched["orderId"]
                                )
                                signed = booked if delta > 0 else -booked
                                comm_cost = booked * avgp * self.config.commission
                                self._pnl.apply_fill(
                                    signed, avgp, commission=comm_cost, slippage=0.0
                                )
                            else:
                                self._idempotency.resolve(order_link_id, "cancelled")
                        else:
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
            if use_limit:
                lifecycle = self._execute_limit_lifecycle(
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    order_id=order_id,
                    order_link_id=order_link_id,
                )
                real_fills: list[dict[str, Any]] = lifecycle["real_fills"]
                order_id = lifecycle["order_id"]
                order_link_id = lifecycle["order_link_id"]
                executed_order_type = lifecycle["executed_order_type"]
                if not real_fills:
                    # The limit (and any market fallback) took NO position. Never
                    # synthesize a fill — that would book a phantom. Mark the signal
                    # acted-upon so we do not re-fire an unfillable entry every bar.
                    result["order_unfilled"] = True
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
                    self._last_executed_signal = target_signal
                    self._signal_initialized = True
                    return result
            else:
                self._idempotency.resolve(order_link_id, "placed", order_id)
                # Real fill pipeline: poll for fills from exchange
                real_fills = self._poll_fills(order_id=order_id, order_link_id=order_link_id)
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
                        "order_type": executed_order_type,
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
            elif not use_limit:
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
                        "order_type": executed_order_type,
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
            sl_pct = _resolve_profile_field(self.strategy, self.config, "sl_pct")
            tp_pct = _resolve_profile_field(self.strategy, self.config, "tp_pct")
            trail_pct = _resolve_profile_field(self.strategy, self.config, "trail_pct")
            activation_pct = _resolve_profile_field(self.strategy, self.config, "activation_pct")
            trail_atr_mult = _resolve_profile_field(self.strategy, self.config, "trail_atr_mult")
            atr_val = self._compute_atr(data) if trail_atr_mult > 0.0 else 0.0
            scale_outs = _resolve_profile_field(self.strategy, self.config, "scale_outs")
            if scale_outs:
                tp_pct = 0.0  # tiered exits + SL replace the single TP
            self._apply_sl_tp(
                symbol,
                pos_side,
                pos_size,
                avg_entry,
                sl_pct,
                tp_pct,
                trail_pct=trail_pct,
                activation_pct=activation_pct,
                trail_atr_mult=trail_atr_mult,
                atr=atr_val,
            )
            if scale_outs and (flip or abs(current_position) < 1e-8):
                self._seed_scale_outs(symbol, pos_size, avg_entry, bar_ts, scale_outs)

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
            self._cleanup_orphan_sl_tp()

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
