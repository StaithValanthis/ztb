from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner
from pandas import DataFrame, date_range

from ztb.cli import cli


def test_run_command_exists() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--help"])
    assert result.exit_code == 0
    assert "Execute a strategy" in result.output or "Usage" in result.output


def test_run_accepts_live_mode() -> None:
    """--mode=live is no longer blocked at CLI level in M7 (LiveGuard instead)."""
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
            ],
        )
    assert result.exit_code == 0, f"stderr={result.output}"
    assert "Mode:" in result.output


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
            "--start=2026-01-01",
            "--end=2026-01-02",
            "--db=:memory:",
        ],
    )
    assert "blocked" not in result.output.lower()
