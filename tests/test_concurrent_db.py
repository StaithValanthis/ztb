from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from ztb.store.exec_io import ensure_exec_tables
from ztb.store.results import (
    _get_db_path_from_conn,
    _migration_lock,
    connect,
    execute_with_retry,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def _run_in_threads(
    target, n_threads: int, db_path: str, timeout: float = 10.0
) -> list[Exception | None]:
    """Run *target(db_path)* in *n_threads* concurrent threads and return
    any exceptions each thread raised (None = success)."""
    results: list[Exception | None] = [None] * n_threads
    lock = threading.Lock()

    def wrapper(i: int) -> None:
        try:
            target(db_path)
        except Exception as e:
            with lock:
                results[i] = e

    threads = [
        threading.Thread(target=wrapper, args=(i,), daemon=True)
        for i in range(n_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout)
    return results


# ── migration lock ───────────────────────────────────────────────────────────


def test_migration_lock_serialises_concurrent_access(tmp_path: Path) -> None:
    """Two processes (simulated via threads) that acquire the same
    migration lock will be serialised, not race."""
    db = tmp_path / "race.db"
    db.write_text("")  # ensure file exists
    lock_path = db.with_name(f".{db.name}.migrate.lock")

    inside: list[int] = []

    def acquire() -> None:
        with _migration_lock(db):
            inside.append(1)

    t1 = threading.Thread(target=acquire, daemon=True)
    t2 = threading.Thread(target=acquire, daemon=True)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert lock_path.exists()
    lock_path.unlink(missing_ok=True)


def test_migration_lock_timeout(tmp_path: Path) -> None:
    """A short timeout raises RuntimeError when lock is held."""
    db = tmp_path / "timeout.db"
    db.write_text("")
    errors: list[Exception] = []

    def holder() -> None:
        with _migration_lock(db):
            import time
            time.sleep(5)

    def contender() -> None:
        try:
            with _migration_lock(db, timeout=0.3):
                pass
        except RuntimeError as e:
            errors.append(e)

    t1 = threading.Thread(target=holder, daemon=True)
    t2 = threading.Thread(target=contender, daemon=True)

    t1.start()
    t2.start()
    t2.join(timeout=4)
    assert len(errors) == 1
    assert "timeout" in str(errors[0]).lower()


def test_migration_lock_covers_connect(tmp_path: Path) -> None:
    """connect() acquires the migration lock so concurrent calls are
    serialised and both succeed."""
    db = str(tmp_path / "concurrent_connect.db")

    def do_connect(p: str) -> None:
        c = connect(p)
        c.close()

    errs = _run_in_threads(do_connect, 4, db, timeout=15.0)
    failures = [(i, e) for i, e in enumerate(errs) if e is not None]
    assert not failures, f"concurrent connect failures: {failures}"


def test_migration_lock_covers_exec_tables(tmp_path: Path) -> None:
    """ensure_exec_tables is safe when called concurrently from
    separate connections."""
    db = str(tmp_path / "concurrent_exec.db")

    def do_ensure(p: str) -> None:
        c = connect(p)
        ensure_exec_tables(c)
        c.close()

    errs = _run_in_threads(do_ensure, 4, db, timeout=15.0)
    failures = [(i, e) for i, e in enumerate(errs) if e is not None]
    assert not failures, f"concurrent ensure_exec_tables failures: {failures}"


def test_migration_lock_idempotent_calls(tmp_path: Path) -> None:
    """Calling connect() twice on the same db file is always safe."""
    db = str(tmp_path / "idemp.db")
    c1 = connect(db)
    c1.close()
    c2 = connect(db)
    c2.close()


# ── execute_with_retry ───────────────────────────────────────────────────────


def test_execute_with_retry_simple(tmp_path: Path) -> None:
    """Happy path — succeeds on first attempt."""
    db = str(tmp_path / "simple.db")
    conn = connect(db)
    cur = execute_with_retry(conn, "SELECT 1 AS x")
    assert cur.fetchone()["x"] == 1
    conn.close()


def test_execute_with_retry_with_params(tmp_path: Path) -> None:
    """Params are forwarded correctly."""
    db = str(tmp_path / "params.db")
    conn = connect(db)
    cur = execute_with_retry(
        conn, "SELECT ? AS x, ? AS y", ("hello", 42)
    )
    row = cur.fetchone()
    assert row["x"] == "hello"
    assert row["y"] == 42
    conn.close()


def test_execute_with_retry_passes_non_locked_errors(tmp_path: Path) -> None:
    """Non-locked OperationalErrors (e.g. syntax error) are NOT retried."""
    db = str(tmp_path / "syntax.db")
    conn = connect(db)
    with pytest.raises(sqlite3.OperationalError):
        execute_with_retry(conn, "SELECT syntax error")
    conn.close()


# ── _get_db_path_from_conn ──────────────────────────────────────────────────


def test_get_db_path_from_conn(tmp_path: Path) -> None:
    """Extracts the real file path from an open connection."""
    db = str(tmp_path / "some_nested" / "path.db")
    conn = connect(db)
    p = _get_db_path_from_conn(conn)
    assert p.name == "path.db"
    assert p.suffix == ".db"
    conn.close()
