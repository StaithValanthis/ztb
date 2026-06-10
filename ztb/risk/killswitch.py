from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class KillSwitch:
    hwm: float = 0.0
    tripped: bool = False
    cooldown_remaining: int = 0
    trip_reason: str = ""
    account_killswitch_dd: float = 0.25
    cooldown_bars: int = 100

    def update(self, current_equity: float) -> None:
        self.hwm = max(self.hwm, current_equity)

    def check_trip(self, current_equity: float) -> bool:
        if self.hwm <= 0:
            self.hwm = current_equity
            return False
        drawdown = (self.hwm - current_equity) / self.hwm
        if drawdown >= self.account_killswitch_dd:
            self.tripped = True
            self.cooldown_remaining = self.cooldown_bars
            self.trip_reason = (
                f"drawdown {drawdown:.4f} >= killswitch_dd {self.account_killswitch_dd}"
            )
            return True
        return False

    def cooldown_tick(self) -> None:
        if self.tripped and self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1
            if self.cooldown_remaining <= 0:
                self.reset(current_equity=self.hwm)

    def reset(self, current_equity: float) -> None:
        self.hwm = current_equity
        self.tripped = False
        self.cooldown_remaining = 0
        self.trip_reason = ""

    def flatten_signal(self, current_position: float) -> float:
        return 0.0

    def is_tripped(self) -> bool:
        return self.tripped

    def to_dict(self) -> dict[str, Any]:
        return {
            "hwm": self.hwm,
            "tripped": self.tripped,
            "cooldown_remaining": self.cooldown_remaining,
            "trip_reason": self.trip_reason,
            "account_killswitch_dd": self.account_killswitch_dd,
            "cooldown_bars": self.cooldown_bars,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KillSwitch:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
