from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np


@dataclass
class KillTrigger:
    source: str
    reason: str
    value: float
    threshold: float
    timestamp: str = ""


@dataclass
class LiveKillSwitch:
    max_account_dd: float = 0.25
    max_reconcile_drift: float = 0.01
    max_data_staleness_sec: float = 300.0
    heartbeat_timeout_sec: float = 60.0
    _tripped: bool = False
    _triggers: list[KillTrigger] = field(default_factory=list)
    _last_heartbeat: float = 0.0
    _hwm_equity: float = 0.0
    _current_equity: float = 0.0

    @property
    def is_tripped(self) -> bool:
        return self._tripped

    @property
    def triggers(self) -> list[KillTrigger]:
        return list(self._triggers)

    def _now(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _ts(self) -> float:
        return time.time()

    def check_account_dd(self, current_equity: float) -> bool:
        self._current_equity = current_equity
        if not np.isfinite(current_equity):
            self.trip(
                KillTrigger(
                    source="account_dd",
                    reason="non-finite value",
                    value=current_equity,
                    threshold=self.max_account_dd,
                    timestamp=self._now(),
                )
            )
            return True
        if current_equity > self._hwm_equity:
            self._hwm_equity = current_equity
        if self._hwm_equity <= 0:
            return False
        dd = (self._hwm_equity - current_equity) / self._hwm_equity
        if dd > self.max_account_dd:
            self.trip(
                KillTrigger(
                    source="account_dd",
                    reason=f"Drawdown {dd:.4f} exceeds limit {self.max_account_dd:.4f}",
                    value=dd,
                    threshold=self.max_account_dd,
                    timestamp=self._now(),
                )
            )
            return True
        return False

    def check_reconcile_drift(self, drift: float) -> bool:
        if abs(drift) > self.max_reconcile_drift:
            self.trip(
                KillTrigger(
                    source="reconcile_drift",
                    reason=f"Reconcile drift {drift:.6f} exceeds {self.max_reconcile_drift:.6f}",
                    value=drift,
                    threshold=self.max_reconcile_drift,
                    timestamp=self._now(),
                )
            )
            return True
        return False

    def check_data_staleness(self, last_bar_ts: str) -> bool:
        try:
            last_dt = datetime.fromisoformat(last_bar_ts.replace("Z", "+00:00"))
            age = (datetime.now(UTC) - last_dt).total_seconds()
        except (ValueError, TypeError):
            self.trip(
                KillTrigger(
                    source="data_staleness",
                    reason="Unparseable bar timestamp",
                    value=float("inf"),
                    threshold=self.max_data_staleness_sec,
                    timestamp=self._now(),
                )
            )
            return True
        if age > self.max_data_staleness_sec:
            self.trip(
                KillTrigger(
                    source="data_staleness",
                    reason=f"Data age {age:.1f}s exceeds limit {self.max_data_staleness_sec:.1f}s",
                    value=age,
                    threshold=self.max_data_staleness_sec,
                    timestamp=self._now(),
                )
            )
            return True
        return False

    def check_heartbeat(self) -> bool:
        age = self._ts() - self._last_heartbeat
        if self._last_heartbeat > 0 and age > self.heartbeat_timeout_sec:
            self.trip(
                KillTrigger(
                    source="heartbeat",
                    reason=f"Heartbeat age {age:.1f}s exceeds {self.heartbeat_timeout_sec:.1f}s",
                    value=age,
                    threshold=self.heartbeat_timeout_sec,
                    timestamp=self._now(),
                )
            )
            return True
        return False

    def manual_trip(self, reason: str = "Manual kill") -> None:
        self.trip(
            KillTrigger(
                source="manual",
                reason=reason,
                value=0.0,
                threshold=0.0,
                timestamp=self._now(),
            )
        )

    def trip(self, trigger: KillTrigger) -> None:
        self._tripped = True
        self._triggers.append(trigger)

    def reset(self) -> None:
        self._tripped = False
        self._triggers.clear()

    def heartbeat(self) -> None:
        self._last_heartbeat = self._ts()

    def to_store_dict(self, exec_run_id: str) -> dict[str, Any]:
        return {
            "exec_run_id": exec_run_id,
            "tripped": self._tripped,
            "triggers": [
                {
                    "source": t.source,
                    "reason": t.reason,
                    "value": t.value,
                    "threshold": t.threshold,
                    "timestamp": t.timestamp or self._now(),
                }
                for t in self._triggers
            ],
            "hwm_equity": self._hwm_equity,
            "current_equity": self._current_equity,
        }

    def get_triggers(self) -> list[KillTrigger]:
        return self._triggers

    def to_persistable_state(self) -> dict[str, Any]:
        return {
            "tripped": self._tripped,
            "hwm_equity": self._hwm_equity,
            "last_heartbeat": self._last_heartbeat,
        }

    def restore_from_state(self, state: dict[str, Any], current_equity: float = 0.0) -> None:
        self._tripped = state.get("tripped", False)
        self._hwm_equity = max(state.get("hwm_equity", 0.0), current_equity)
        self._last_heartbeat = state.get("last_heartbeat", 0.0)
