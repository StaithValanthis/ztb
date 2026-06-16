"""Source-level regression locks for the 2026-06-16 real-fill root cause.

These assert the KNOWN bug patterns cannot silently return. They complement the
binding `ztb/real-fill-certified` gate (which catches reintroduction via "no real
fill") but fire at unit-CI time — faster, and they pin the exact defects so a
re-break reads as "you reintroduced bug X", not "the fix looks wrong".
"""

import re
from pathlib import Path

ZTB = Path(__file__).resolve().parent.parent / "ztb"


def test_get_executions_not_signed_over_sorted_params() -> None:
    """GET signature must be over the order SENT (insertion), not sorted().

    sign(sorted(params)) while send(insertion) made Bybit reject every execution
    query with "Error sign" -> 0 real fills (the root cause). Never reintroduce.
    """
    src = (ZTB / "execution" / "bybit_client.py").read_text()
    assert "sorted(params.items())" not in src, (
        "REGRESSION: get_executions signs sorted params but sends insertion order "
        "-> Bybit 'Error sign' -> 0 real fills. Sign the order actually sent."
    )


def test_demo_does_not_short_circuit_fill_polling() -> None:
    """DEMO must poll real fills, not short-circuit to synthetic (revert of d797575)."""
    src = (ZTB / "execution" / "executor.py").read_text()
    assert "Skipping fill polling in DEMO" not in src, (
        "REGRESSION: DEMO synthetic short-circuit reintroduced (d797575) "
        "-> 100% synthetic fills. DEMO must poll get_executions like LIVE."
    )


def test_fill_poll_window_long_enough_for_demo() -> None:
    """Real demo fills register ~6-8s; the poll window must comfortably exceed that."""
    src = (ZTB / "execution" / "models.py").read_text()
    m = re.search(r"poll_fill_max_attempts: int = (\d+)", src)
    n = re.search(r"poll_fill_interval: float = ([\d.]+)", src)
    assert m and n, "poll_fill config not found in models.py"
    window = int(m.group(1)) * float(n.group(1))
    assert window >= 20.0, (
        f"REGRESSION: fill-poll window {window}s too short; real demo fills land "
        f"~6-8s and the old 2.5s default missed them -> synthetic fallback."
    )
