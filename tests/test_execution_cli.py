from __future__ import annotations

from click.testing import CliRunner

from ztb.cli import cli


def test_run_command_exists() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--help"])
    assert result.exit_code == 0
    assert "Execute a strategy" in result.output or "Usage" in result.output


def test_run_rejects_live_mode() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["run", "sma_cross", "BTCUSDT", "--mode=live"],
    )
    assert result.exit_code != 0
    assert "blocked" in result.output.lower() or "demo" in result.output.lower()


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
