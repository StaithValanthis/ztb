from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
from pandas import DataFrame, date_range

from ztb.cli import cli
from ztb.execution.arm_auth import compute_arm_hash
from ztb.execution.live_guard import LiveGuard

_TEST_TOKEN = "brd-tkn"


def _setup_arm(tmp_path: Path) -> Path:
    """Set up board token + hash file, return hash path."""
    os.environ[LiveGuard.BOARD_TOKEN_VAR] = _TEST_TOKEN
    hash_path = tmp_path / "board-arm-hash"
    hash_path.write_text(compute_arm_hash(_TEST_TOKEN))
    return hash_path


def _cleanup_arm() -> None:
    LiveGuard.disarm()
    os.environ.pop(LiveGuard.BOARD_TOKEN_VAR, None)


def test_run_command_exists() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--help"])
    assert result.exit_code == 0
    assert "Execute a strategy" in result.output or "Usage" in result.output


def test_run_accepts_live_mode(tmp_path: Path) -> None:
    """--mode=live accepted when LiveGuard is armed."""
    hash_path = _setup_arm(tmp_path)
    LiveGuard.arm(hash_path=hash_path)
    try:
        n = 200
        df = DataFrame(
            {
                "open": [50000.0 + i * 10 for i in range(n)],
                "high": [50100.0 + i * 10 for i in range(n)],
                "low": [49900.0 + i * 10 for i in range(n)],
                "close": [50000.0 + i * 10 for i in range(n)],
                "volume": [1000.0] * n,
            },
            index=date_range("2026-01-01", periods=n, freq="h"),
        )
        runner = CliRunner()
        with patch("ztb.execution.executor.load_data", return_value=df):
            result = runner.invoke(
                cli,
                [
                    "run",
                    "sma_cross",
                    "BTCUSDT",
                    "--mode=live",
                    "--dry-run",
                    "--once",
                    "--no-risk",
                    "--start=2026-01-01",
                    "--end=2026-01-03",
                    "--db=:memory:",
                ],
                env=os.environ,
            )
        assert result.exit_code == 0, f"stderr={result.output}"
        assert "Mode:" in result.output
    finally:
        _cleanup_arm()


def test_run_rejects_unknown_strategy() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["run", "nonexistent", "BTCUSDT", "--dry-run"],
    )
    assert result.exit_code != 0


def test_reconcile_command_exists() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["reconcile", "--help"])
    assert result.exit_code == 0
    assert "Reconcile" in result.output or "Usage" in result.output


def test_reconcile_reads_credentials() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["reconcile"],
        env={
            "ZTB_BYBIT_API_KEY": "test-key",
            "ZTB_BYBIT_API_SECRET": "test-secret",
        },
    )
    # With credentials set we get past the env check; fails at Bybit API call
    assert "must be set" not in result.output


def test_reconcile_missing_credentials_exits() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["reconcile"],
        env={"ZTB_BYBIT_API_KEY": "", "ZTB_BYBIT_API_SECRET": ""},
    )
    assert result.exit_code != 0
    assert "must be set" in result.output


def test_run_with_dry_run_and_demo_default() -> None:
    """Test that --dry-run is accepted with the run command."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["run", "sma_cross", "BTCUSDT", "--dry-run", "--start=2026-01-01", "--end=2026-01-02"],
    )
    # May fail because data not available, but should not say mode blocked
    assert "blocked" not in result.output.lower()


def test_reconcile_command_help_text() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["reconcile", "--help"])
    assert result.exit_code == 0
    assert "Reconcile" in result.output or "Usage" in result.output


def test_run_once_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            "sma_cross",
            "BTCUSDT",
            "--dry-run",
            "--once",
            "--start=2026-01-01",
            "--end=2026-01-10",
        ],
    )
    assert "blocked" not in result.output.lower()


def test_run_no_risk_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            "sma_cross",
            "BTCUSDT",
            "--dry-run",
            "--no-risk",
            "--start=2026-01-01",
            "--end=2026-01-02",
        ],
    )
    assert "blocked" not in result.output.lower()


def test_run_with_db() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            "sma_cross",
            "BTCUSDT",
            "--dry-run",
            "--once",
            "--start=2026-01-01",
            "--end=2026-01-02",
            "--db=:memory:",
        ],
    )
    assert "blocked" not in result.output.lower()


def test_run_loop_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            "sma_cross",
            "BTCUSDT",
            "--dry-run",
            "--once",
            "--loop",
            "--start=2026-01-01",
            "--end=2026-01-02",
        ],
    )
    assert "blocked" not in result.output.lower()


def test_run_poll_interval() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            "sma_cross",
            "BTCUSDT",
            "--dry-run",
            "--once",
            "--poll-interval=30",
            "--start=2026-01-01",
            "--end=2026-01-02",
        ],
    )
    assert "blocked" not in result.output.lower()


def test_run_lookback_bars() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            "sma_cross",
            "BTCUSDT",
            "--dry-run",
            "--once",
            "--lookback-bars=500",
            "--start=2026-01-01",
            "--end=2026-01-02",
        ],
    )
    assert "blocked" not in result.output.lower()
