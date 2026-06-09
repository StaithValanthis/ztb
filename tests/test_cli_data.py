from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner
from pandas import DataFrame

from ztb.cli import cli
from ztb.data.cache import write_cache
from ztb.data.schema import OHLCV_COLUMNS


def _make_df(n: int = 10) -> DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC", name="open_time")
    data = {col: np.random.randn(n) * 100 + 50000 for col in OHLCV_COLUMNS}
    data["volume"] = np.abs(data["volume"]) + 1
    data["turnover"] = np.abs(data["turnover"]) + 1
    df = DataFrame(data, index=idx)
    df.index.name = "open_time"
    for col in OHLCV_COLUMNS:
        df[col] = df[col].astype("float64")
    return df


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_data_show_with_cache(runner: CliRunner) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        df = _make_df(n=5)
        write_cache(df, "linear", "BTCUSDT", "60", base=base)
        with patch("ztb.cli.read_cache") as mock_read:
            mock_read.return_value = df
            result = runner.invoke(cli, ["data", "show", "BTCUSDT", "--timeframe", "60"])
            assert result.exit_code == 0
            assert "open" in result.output
            assert "Range:" in result.output


def test_data_show_tail(runner: CliRunner) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        df = _make_df(n=5)
        write_cache(df, "linear", "BTCUSDT", "60", base=base)
        with patch("ztb.cli.read_cache") as mock_read:
            mock_read.return_value = df
            result = runner.invoke(
                cli, ["data", "show", "BTCUSDT", "--timeframe", "60", "--tail", "3"]
            )
            assert result.exit_code == 0
            assert "Last 3 bars" in result.output


def test_data_verify_with_cache(runner: CliRunner) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        df = _make_df(n=10)
        write_cache(df, "linear", "BTCUSDT", "60", base=base)
        with patch("ztb.cli.read_cache") as mock_read:
            mock_read.return_value = df
            result = runner.invoke(
                cli,
                [
                    "data",
                    "verify",
                    "BTCUSDT",
                    "--timeframe",
                    "60",
                    "--category",
                    "linear",
                ],
            )
            assert result.exit_code == 0
            assert "Integrity report" in result.output


def test_data_verify_gaps_fails(runner: CliRunner) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        df = _make_df(n=5)
        extra_idx = pd.date_range(
            "2025-01-01 10:00", periods=3, freq="1h", tz="UTC", name="open_time"
        )
        extra_data = {col: np.random.randn(3) * 100 + 50000 for col in OHLCV_COLUMNS}
        extra_data["volume"] = np.abs(extra_data["volume"]) + 1
        extra_data["turnover"] = np.abs(extra_data["turnover"]) + 1
        extra = DataFrame(extra_data, index=extra_idx)
        extra.index.name = "open_time"
        for col in OHLCV_COLUMNS:
            extra[col] = extra[col].astype("float64")
        df = pd.concat([df, extra])
        df = df[~df.index.duplicated(keep="first")].sort_index()
        write_cache(df, "linear", "BTCUSDT", "60", base=base)
        with patch("ztb.cli.read_cache") as mock_read:
            mock_read.return_value = df
            result = runner.invoke(
                cli,
                [
                    "data",
                    "verify",
                    "BTCUSDT",
                    "--timeframe",
                    "60",
                    "--category",
                    "linear",
                ],
            )
            assert result.exit_code == 1


def test_data_fetch_success(runner: CliRunner) -> None:
    df = _make_df(n=5)
    with patch("ztb.cli.load") as mock_load:
        mock_load.return_value = df
        result = runner.invoke(
            cli,
            [
                "data",
                "fetch",
                "BTCUSDT",
                "--timeframe",
                "60",
                "--start",
                "2025-01-01",
                "--end",
                "2025-01-01T04:00:00",
            ],
        )
        assert result.exit_code == 0
        assert "Fetched 5 bars" in result.output


def test_data_fetch_error(runner: CliRunner) -> None:
    from ztb.data.errors import FetchError

    with patch("ztb.cli.load") as mock_load:
        mock_load.side_effect = FetchError("API error")
        result = runner.invoke(
            cli,
            [
                "data",
                "fetch",
                "INVALID",
                "--timeframe",
                "60",
            ],
        )
        assert result.exit_code == 1
        assert "Error:" in result.output


def test_data_instruments(runner: CliRunner) -> None:
    mock_client = MagicMock()
    mock_client.get_instruments_info.return_value = [
        {"symbol": "BTCUSDT", "status": "Trading"},
        {"symbol": "ETHUSDT", "status": "Trading"},
    ]
    with patch("ztb.cli.BybitPublicREST") as mock_cls:
        mock_cls.return_value = mock_client
        result = runner.invoke(cli, ["data", "instruments", "--category", "linear"])
        assert result.exit_code == 0
        assert "BTCUSDT" in result.output


def test_data_instruments_empty(runner: CliRunner) -> None:
    mock_client = MagicMock()
    mock_client.get_instruments_info.return_value = []
    with patch("ztb.cli.BybitPublicREST") as mock_cls:
        mock_cls.return_value = mock_client
        result = runner.invoke(cli, ["data", "instruments", "--category", "linear"])
        assert result.exit_code == 1


def test_data_instruments_error(runner: CliRunner) -> None:
    from ztb.data.errors import FetchError

    mock_client = MagicMock()
    mock_client.get_instruments_info.side_effect = FetchError("API error")
    with patch("ztb.cli.BybitPublicREST") as mock_cls:
        mock_cls.return_value = mock_client
        result = runner.invoke(cli, ["data", "instruments", "--category", "linear"])
        assert result.exit_code == 1
