from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from ztb.store.retry import retry_on_lock


def _lock_error(msg: str = "database is locked") -> sqlite3.OperationalError:
    return sqlite3.OperationalError(msg)


def _other_error(msg: str = "no such table") -> sqlite3.OperationalError:
    return sqlite3.OperationalError(msg)


class TestRetryOnLockDecorator:
    def test_success_on_first_try(self) -> None:
        mock_fn = Mock(return_value="ok")
        decorated = retry_on_lock(max_retries=3)(mock_fn)
        result = decorated(Mock(spec=sqlite3.Connection))
        assert result == "ok"
        assert mock_fn.call_count == 1

    def test_retry_then_success(self) -> None:
        mock_fn = Mock(side_effect=[_lock_error(), "ok"])
        decorated = retry_on_lock(max_retries=3, base_delay=0.01)(mock_fn)
        result = decorated(Mock(spec=sqlite3.Connection))
        assert result == "ok"
        assert mock_fn.call_count == 2

    def test_retry_multiple_then_success(self) -> None:
        mock_fn = Mock(side_effect=[_lock_error(), _lock_error(), "ok"])
        decorated = retry_on_lock(max_retries=5, base_delay=0.01)(mock_fn)
        result = decorated(Mock(spec=sqlite3.Connection))
        assert result == "ok"
        assert mock_fn.call_count == 3

    def test_exhaust_retries_raises(self) -> None:
        mock_fn = Mock(side_effect=_lock_error("database is locked"))
        decorated = retry_on_lock(max_retries=3, base_delay=0.01)(mock_fn)
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            decorated(Mock(spec=sqlite3.Connection))
        assert mock_fn.call_count == 3

    def test_non_lock_error_passes_through_immediately(self) -> None:
        mock_fn = Mock(side_effect=_other_error("no such table: foo"))
        decorated = retry_on_lock(max_retries=3)(mock_fn)
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            decorated(Mock(spec=sqlite3.Connection))
        assert mock_fn.call_count == 1

    def test_max_one_retry_exhausted(self) -> None:
        mock_fn = Mock(side_effect=_lock_error())
        decorated = retry_on_lock(max_retries=1, base_delay=0.01)(mock_fn)
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            decorated(Mock(spec=sqlite3.Connection))
        assert mock_fn.call_count == 1

    def test_jitter_applied(self) -> None:
        with patch("random.uniform", return_value=0.1):
            mock_fn = Mock(side_effect=[_lock_error(), _lock_error(), "ok"])
            decorated = retry_on_lock(max_retries=5, base_delay=1.0, max_delay=30.0)(mock_fn)
            with patch("time.sleep") as mock_sleep:
                result = decorated(Mock(spec=sqlite3.Connection))
        assert result == "ok"
        assert mock_sleep.call_count == 2
        sleep_args = [c[0][0] for c in mock_sleep.call_args_list]
        assert sleep_args[0] == pytest.approx(1.1, rel=0.5)
        assert sleep_args[1] == pytest.approx(2.1, rel=0.5)

    def test_delay_capped_at_max_delay(self) -> None:
        with patch("random.uniform", return_value=0.0):
            mock_fn = Mock(side_effect=[_lock_error()] * 5 + ["ok"])
            decorated = retry_on_lock(max_retries=6, base_delay=1.0, max_delay=4.0)(mock_fn)
            with patch("time.sleep") as mock_sleep:
                result = decorated(Mock(spec=sqlite3.Connection))
        assert result == "ok"
        assert mock_fn.call_count == 6
        last_sleep = mock_sleep.call_args_list[4][0][0]
        assert last_sleep <= 4.0 + 1e-9


class TestRetryOnLockApplied:
    def test_ensure_exec_tables_retries(self) -> None:
        from ztb.store.exec_io import ensure_exec_tables

        call_count: list[int] = [0]

        def _side_effect(*_a: object, **_kw: object) -> Mock:
            call_count[0] += 1
            if call_count[0] == 1:
                raise _lock_error()
            return Mock()

        conn = Mock(spec=sqlite3.Connection)
        conn.execute.side_effect = _side_effect
        conn.executescript = Mock()
        with patch("time.sleep"):
            ensure_exec_tables(conn)
        assert call_count[0] >= 2

    def test_create_exec_run_retries(self) -> None:
        from ztb.store.exec_io import create_exec_run

        call_count: list[int] = [0]

        def _side_effect(*_a: object, **_kw: object) -> Mock:
            call_count[0] += 1
            if call_count[0] == 1:
                raise _lock_error()
            return Mock()

        conn = Mock(spec=sqlite3.Connection)
        conn.execute.side_effect = _side_effect
        with patch("time.sleep"):
            create_exec_run(conn, "r1", "rid", "strat", "BTCUSDT", "60")
        assert call_count[0] >= 2

    def test_save_exec_order_retries(self) -> None:
        from ztb.store.exec_io import save_exec_order

        call_count: list[int] = [0]

        def _side_effect(*_a: object, **_kw: object) -> Mock:
            call_count[0] += 1
            if call_count[0] == 1:
                raise _lock_error()
            return Mock()

        conn = Mock(spec=sqlite3.Connection)
        conn.execute.side_effect = _side_effect
        order = {
            "order_link_id": "ol1",
            "exec_run_id": "r1",
            "symbol": "BTCUSDT",
            "side": "Buy",
            "order_type": "Market",
        }
        with patch("time.sleep"):
            save_exec_order(conn, order)
        assert call_count[0] >= 2

    def test_save_validation_run_retries(self) -> None:
        from ztb.validation.store import save_validation_run

        call_count: list[int] = [0]

        def _side_effect(*_a: object, **_kw: object) -> Mock:
            call_count[0] += 1
            if call_count[0] == 1:
                raise _lock_error()
            return Mock()

        conn = Mock(spec=sqlite3.Connection)
        conn.execute.side_effect = _side_effect
        wf_result = Mock()
        wf_result.aggregate = Mock()
        wf_result.aggregate.sharpe = 1.5
        wf_result.n_windows_total = 10
        wf_result.n_windows_credible = 8
        wf_result.stability = 0.9
        wf_result.per_window = []
        with patch("time.sleep"):
            save_validation_run(conn, "strat", "BTCUSDT", "60", True, wf_result, 0.0, True, True)
        assert call_count[0] >= 2

    def test_idempotency_try_claim_retries(self) -> None:
        from ztb.execution.idempotency import IdempotencyLedger

        call_count: list[int] = [0]

        def _side_effect(*_a: object, **_kw: object) -> Mock:
            call_count[0] += 1
            if call_count[0] == 1:
                raise _lock_error()
            return Mock()

        conn = Mock(spec=sqlite3.Connection)
        conn.execute.side_effect = _side_effect
        ledger = IdempotencyLedger(conn)
        with patch("time.sleep"):
            ledger.try_claim("link1")
        assert call_count[0] >= 2

    def test_save_risk_decisions_retries(self) -> None:
        from ztb.store.results import save_risk_decisions

        call_count: list[int] = [0]

        def _side_effect(*_a: object, **_kw: object) -> Mock:
            call_count[0] += 1
            if call_count[0] == 1:
                raise _lock_error()
            return Mock()

        conn = Mock(spec=sqlite3.Connection)
        conn.execute.side_effect = _side_effect
        decision = {"action": "cool_off", "reason": "test"}
        with patch("time.sleep"):
            save_risk_decisions(conn, "run1", [decision])
        assert call_count[0] >= 2

    def test_non_lock_error_not_retried_on_write(self) -> None:
        from ztb.store.exec_io import create_exec_run

        conn = Mock(spec=sqlite3.Connection)
        conn.execute.side_effect = _other_error("no such table: exec_runs")
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            create_exec_run(conn, "r1", "rid", "strat", "BTCUSDT", "60")
        assert conn.execute.call_count == 1


class TestBusyTimeout:
    def test_busy_timeout_changed_to_30000(self, tmp_path: Path) -> None:
        from ztb.store.results import connect as store_connect

        db = str(tmp_path / "test_busy_timeout.db")
        conn = store_connect(db)
        try:
            row = conn.execute("PRAGMA busy_timeout").fetchone()
            assert row is not None
            assert row[0] == 30000
        finally:
            conn.close()
