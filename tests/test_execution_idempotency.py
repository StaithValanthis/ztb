from __future__ import annotations

import sqlite3

import pytest

from ztb.execution.idempotency import (
    IdempotencyLedger,
    make_intent_hash,
    make_order_link_id,
)


def test_make_order_link_id_stable() -> None:
    id1 = make_order_link_id("sma_cross", "BTCUSDT", "2026-01-01T00:00:00Z", "abc123")
    id2 = make_order_link_id("sma_cross", "BTCUSDT", "2026-01-01T00:00:00Z", "abc123")
    assert id1 == id2
    assert len(id1) == 40


def test_make_order_link_id_different_bar() -> None:
    id1 = make_order_link_id("sma_cross", "BTCUSDT", "2026-01-01T00:00:00Z", "abc123")
    id2 = make_order_link_id("sma_cross", "BTCUSDT", "2026-01-02T00:00:00Z", "abc123")
    assert id1 != id2


def test_make_order_link_id_different_strategy() -> None:
    id1 = make_order_link_id("strat_a", "BTCUSDT", "2026-01-01T00:00:00Z", "abc123")
    id2 = make_order_link_id("strat_b", "BTCUSDT", "2026-01-01T00:00:00Z", "abc123")
    assert id1 != id2


def test_make_order_link_id_different_run() -> None:
    """Prove different exec_run_id produces a different orderLinkId (§ZTB-2021)."""
    id1 = make_order_link_id("sma_cross", "BTCUSDT", "2026-01-01T00:00:00Z", "abc123", "exec_run_1")
    id2 = make_order_link_id("sma_cross", "BTCUSDT", "2026-01-01T00:00:00Z", "abc123", "exec_run_2")
    assert id1 != id2


def test_make_order_link_id_same_run_stable() -> None:
    """Prove same inputs + same exec_run_id → same output (within-run dedup)."""
    id1 = make_order_link_id("sma_cross", "BTCUSDT", "2026-01-01T00:00:00Z", "abc123", "exec_r1")
    id2 = make_order_link_id("sma_cross", "BTCUSDT", "2026-01-01T00:00:00Z", "abc123", "exec_r1")
    assert id1 == id2


def test_make_order_link_id_cross_run_collision() -> None:
    """Prove same inputs + different exec_run_id → different output (cross-run collision eliminated)."""
    intent = "abc123"
    id_run_a = make_order_link_id("strat", "SYM", "T1", intent, "run_a")
    id_run_b = make_order_link_id("strat", "SYM", "T1", intent, "run_b")
    assert id_run_a != id_run_b


def test_make_intent_hash_stable() -> None:
    h1 = make_intent_hash(0.5, 0.0)
    h2 = make_intent_hash(0.5, 0.0)
    assert h1 == h2
    assert len(h1) == 16


def test_make_intent_hash_different() -> None:
    h1 = make_intent_hash(0.5, 0.0)
    h2 = make_intent_hash(0.0, 0.5)
    assert h1 != h2


@pytest.fixture
def ledger_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    yield conn
    conn.close()


def test_idempotency_try_claim(ledger_conn: sqlite3.Connection) -> None:
    ledger = IdempotencyLedger(ledger_conn)
    ok = ledger.try_claim("link1", "order1")
    assert ok is True


def test_idempotency_double_claim_rejected(ledger_conn: sqlite3.Connection) -> None:
    ledger = IdempotencyLedger(ledger_conn)
    assert ledger.try_claim("link1", "order1") is True
    assert ledger.try_claim("link1", "order2") is False


def test_idempotency_lookup_order(ledger_conn: sqlite3.Connection) -> None:
    ledger = IdempotencyLedger(ledger_conn)
    ledger.try_claim("link1", "order1")
    ledger.resolve("link1", "placed", "order1")
    oid = ledger.lookup_order("link1")
    assert oid == "order1"


def test_idempotency_lookup_pending_returns_none(ledger_conn: sqlite3.Connection) -> None:
    ledger = IdempotencyLedger(ledger_conn)
    ledger.try_claim("link1", "order1")
    assert ledger.lookup_order("link1") is None


def test_idempotency_lookup_missing(ledger_conn: sqlite3.Connection) -> None:
    ledger = IdempotencyLedger(ledger_conn)
    assert ledger.lookup_order("nonexistent") is None


def test_idempotency_get(ledger_conn: sqlite3.Connection) -> None:
    ledger = IdempotencyLedger(ledger_conn)
    ledger.try_claim("link1", "order1")
    entry = ledger.get("link1")
    assert entry is not None
    assert entry["order_link_id"] == "link1"
    assert entry["order_id"] == "order1"
    assert entry["status"] == "pending"


def test_idempotency_resolve(ledger_conn: sqlite3.Connection) -> None:
    ledger = IdempotencyLedger(ledger_conn)
    ledger.try_claim("link1", "order1")
    ledger.resolve("link1", "filled", "order1")
    entry = ledger.get("link1")
    assert entry is not None
    assert entry["status"] == "filled"


def test_replay_same_intent_same_id() -> None:
    """Prove that replaying the same bar/intent/exec_run_id produces the same orderLinkId."""
    intent = make_intent_hash(0.5, 0.0)
    id1 = make_order_link_id("strat", "SYM", "T1", intent, "exec_r1")
    id2 = make_order_link_id("strat", "SYM", "T1", intent, "exec_r1")
    assert id1 == id2


def test_different_intent_different_id() -> None:
    """Prove distinct intents produce distinct orderLinkIds."""
    intent1 = make_intent_hash(0.5, 0.0)
    intent2 = make_intent_hash(-0.5, 0.5)
    id1 = make_order_link_id("strat", "SYM", "T1", intent1, "exec_r1")
    id2 = make_order_link_id("strat", "SYM", "T1", intent2, "exec_r1")
    assert id1 != id2


def test_idempotency_get_missing(ledger_conn: sqlite3.Connection) -> None:
    ledger = IdempotencyLedger(ledger_conn)
    entry = ledger.get("nonexistent_link")
    assert entry is None


def test_idempotency_lookup_order_wrong_status(ledger_conn: sqlite3.Connection) -> None:
    ledger = IdempotencyLedger(ledger_conn)
    ledger.try_claim("link1", "order1")
    oid = ledger.lookup_order("link1")
    assert oid is None
