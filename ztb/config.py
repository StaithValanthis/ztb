from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Config:
    mode: str = "demo"
    secrets: dict[str, str] = field(default_factory=dict, repr=False)

    @classmethod
    def from_env(cls) -> Config:
        secrets: dict[str, str] = {}
        for key in ("ZTB_BYBIT_API_KEY", "ZTB_BYBIT_API_SECRET", "ZTB_BYBIT_PASSPHRASE"):
            val = os.environ.get(key)
            if val is not None:
                secrets[key] = val
        return cls(mode="demo", secrets=secrets)
