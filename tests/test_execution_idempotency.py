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


def test_make_order_link_id_not_run_id() -> None:
    """Prove the stable tuple does NOT include run_id (§0.7, fix #21)."""
    id1 = make_order_link_id("sma_cross", "BTCUSDT", "2026-01-01T00:00:00Z", "abc123")
    id2 = make_order_link_id("sma_cross", "BTCUSDT", "2026-01-01T00:00:00Z", "abc123")
    assert id1 == id2  # same inputs → same id, regardless of any run_id


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
    """Prove that replaying the same bar/intent produces the same orderLinkId."""
    intent = make_intent_hash(0.5, 0.0)
    id1 = make_order_link_id("strat", "SYM", "T1", intent)
    id2 = make_order_link_id("strat", "SYM", "T1", intent)
    assert id1 == id2
    # This simulates restart: same strategy, symbol, bar timestamp, signal → same id


def test_different_intent_different_id() -> None:
    """Prove distinct intents produce distinct orderLinkIds."""
    intent1 = make_intent_hash(0.5, 0.0)
    intent2 = make_intent_hash(-0.5, 0.5)
    id1 = make_order_link_id("strat", "SYM", "T1", intent1)
    id2 = make_order_link_id("strat", "SYM", "T1", intent2)
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


def test_idempotency_count_empty(ledger_conn: sqlite3.Connection) -> None:
    ledger = IdempotencyLedger(ledger_conn)
    assert ledger.count() == 0


def test_idempotency_count_nonempty(ledger_conn: sqlite3.Connection) -> None:
    ledger = IdempotencyLedger(ledger_conn)
    ledger.try_claim("link1", "order1")
    ledger.try_claim("link2", "order2")
    assert ledger.count() == 2


def test_clear_stale_removes_old_resolved(ledger_conn: sqlite3.Connection) -> None:
    from datetime import UTC, datetime, timedelta

    ledger = IdempotencyLedger(ledger_conn)
    ledger.try_claim("stale_placed", "oid1")
    ledger.resolve("stale_placed", "placed", "oid1")

    ledger.try_claim("stale_filled", "oid2")
    ledger.resolve("stale_filled", "filled", "oid2")

    ledger.try_claim("fresh_pending", "oid3")

    old_ts = (datetime.now(UTC) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger.conn.execute(
        "UPDATE idempotency SET created_at = ? WHERE order_link_id IN (?, ?)",
        (old_ts, "stale_placed", "stale_filled"),
    )
    ledger.conn.commit()

    deleted = ledger.clear_stale(ttl_hours=24)
    assert deleted == 2
    assert ledger.get("stale_placed") is None
    assert ledger.get("stale_filled") is None
    assert ledger.get("fresh_pending") is not None


def test_clear_stale_skips_recent_entries(ledger_conn: sqlite3.Connection) -> None:
    ledger = IdempotencyLedger(ledger_conn)
    ledger.try_claim("recent_placed", "oid1")
    ledger.resolve("recent_placed", "placed", "oid1")

    ledger.try_claim("recent_pending", "oid2")

    deleted = ledger.clear_stale(ttl_hours=24)
    assert deleted == 0
    assert ledger.get("recent_placed") is not None
    assert ledger.get("recent_pending") is not None


def test_clear_stale_idempotent(ledger_conn: sqlite3.Connection) -> None:
    from datetime import UTC, datetime, timedelta

    ledger = IdempotencyLedger(ledger_conn)
    ledger.try_claim("stale", "oid1")
    ledger.resolve("stale", "filled", "oid1")

    old_ts = (datetime.now(UTC) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger.conn.execute(
        "UPDATE idempotency SET created_at = ? WHERE order_link_id = ?", (old_ts, "stale")
    )
    ledger.conn.commit()

    deleted = ledger.clear_stale(ttl_hours=24)
    assert deleted == 1

    deleted2 = ledger.clear_stale(ttl_hours=24)
    assert deleted2 == 0


def test_clear_pending_removes_pending_entries(ledger_conn: sqlite3.Connection) -> None:
    ledger = IdempotencyLedger(ledger_conn)
    ledger.try_claim("pending1", "oid1")
    ledger.try_claim("pending2", "oid2")

    deleted = ledger.clear_pending()
    assert deleted == 2
    assert ledger.get("pending1") is None
    assert ledger.get("pending2") is None


def test_clear_pending_preserves_placed(ledger_conn: sqlite3.Connection) -> None:
    ledger = IdempotencyLedger(ledger_conn)
    ledger.try_claim("placed_link", "oid1")
    ledger.resolve("placed_link", "placed", "oid1")

    ledger.try_claim("pending_link", "oid2")

    deleted = ledger.clear_pending()
    assert deleted == 1
    assert ledger.get("placed_link") is not None
    assert ledger.get("pending_link") is None


def test_clear_pending_frees_link_for_reclaim(ledger_conn: sqlite3.Connection) -> None:
    ledger = IdempotencyLedger(ledger_conn)
    assert ledger.try_claim("orphan_link")
    assert not ledger.try_claim("orphan_link")

    ledger.clear_pending()
    assert ledger.try_claim("orphan_link")


def test_clear_pending_zero_on_empty(ledger_conn: sqlite3.Connection) -> None:
    ledger = IdempotencyLedger(ledger_conn)
    assert ledger.clear_pending() == 0


def test_clear_pending_with_max_age_preserves_recent(
    ledger_conn: sqlite3.Connection,
) -> None:
    ledger = IdempotencyLedger(ledger_conn)
    ledger.try_claim("recent", "oid1")
    ledger.try_claim("recent2", "oid2")

    deleted = ledger.clear_pending(max_age_seconds=3600)
    assert deleted == 0
    assert ledger.get("recent") is not None
    assert ledger.get("recent2") is not None


def test_clear_pending_with_max_age_removes_old(
    ledger_conn: sqlite3.Connection,
) -> None:
    from datetime import UTC, datetime, timedelta

    ledger = IdempotencyLedger(ledger_conn)
    ledger.try_claim("old_link", "oid1")
    ledger.try_claim("recent_link", "oid2")

    old_ts = (datetime.now(UTC) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger.conn.execute(
        "UPDATE idempotency SET created_at = ? WHERE order_link_id = ?",
        (old_ts, "old_link"),
    )
    ledger.conn.commit()

    deleted = ledger.clear_pending(max_age_seconds=3600)
    assert deleted == 1
    assert ledger.get("old_link") is None
    assert ledger.get("recent_link") is not None
