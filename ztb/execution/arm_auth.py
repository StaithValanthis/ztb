from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path


def load_arm_hash(path: str | Path | None = None) -> str | None:
    if path:
        p = Path(path)
    else:
        env_path = os.environ.get("ZTB_ARM_HASH_PATH")
        p = Path(env_path) if env_path else Path.home() / ".ztb" / "board-arm-hash"
    if not p.exists():
        return None
    try:
        return p.read_text().strip()
    except OSError:
        return None


def compute_arm_hash(token: str) -> str:
    return hmac.new(token.encode(), b"ztb-arm", hashlib.sha256).hexdigest()


def verify_board_token(token: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    computed = compute_arm_hash(token)
    return hmac.compare_digest(computed, stored_hash)
