from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from ztb import __version__
from ztb.cli import cli


def test_smoke_test_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["smoke-test", "--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "real demo" in result.output


def test_smoke_test_missing_keys() -> None:
    runner = CliRunner()
    with patch.dict(os.environ, {}, clear=True):
        result = runner.invoke(cli, ["smoke-test", "--symbol", "BTCUSDT"])
    assert result.exit_code == 1
    assert "ZTB_BYBIT_API_KEY" in result.output


def test_smoke_test_success(tmp_path: pytest.TempPathFactory) -> None:
    db_path = str(tmp_path / "smoke_test.db")
    runner = CliRunner()

    mock_client = MagicMock()
    mock_client.get_instrument_info.return_value = {
        "symbol": "BTCUSDT",
        "lotSizeFilter": {
            "qtyStep": "0.001",
            "minOrderQty": "0.001",
            "maxOrderQty": "1000",
        },
    }
    mock_client.place_order.return_value = {
        "orderId": "test-order-123",
        "price": "50000.0",
        "cumExecValue": "50.0",
        "cumExecFee": "0.025",
    }
    mock_client.get_executions.return_value = [
        {
            "execId": "test-exec-001",
            "execPrice": "50000.0",
            "execQty": "0.001",
            "execFee": "0.025",
            "realizedPnl": "0.0",
            "execTime": "2024-01-01T00:00:00Z",
        }
    ]

    mock_class = MagicMock()
    mock_class.round_to_step.return_value = 0.001

    with (
        patch.dict(os.environ, {"ZTB_BYBIT_API_KEY": "test-key",
                                "ZTB_BYBIT_API_SECRET": "test-secret"}),
        patch("ztb.execution.bybit_client.BybitClient", mock_class),
    ):
        mock_class.return_value = mock_client
        result = runner.invoke(cli, [
            "smoke-test",
            "--symbol", "BTCUSDT",
            "--qty", "0.001",
            "--db", db_path,
            "--timeout", "5",
            "--poll-interval", "1",
        ])

    assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"
    assert "SMOKE TEST PASSED" in result.output
    assert "test-exec-001" in result.output
    assert __version__ in result.output

    assert mock_client.place_order.call_count == 1
    call_kwargs = mock_client.place_order.call_args[1]
    assert call_kwargs["symbol"] == "BTCUSDT"
    assert call_kwargs["side"].value == "Buy"
    assert call_kwargs["qty"] == 0.001

    assert mock_client.get_executions.call_count == 1


def test_smoke_test_side_always_buy(tmp_path: pytest.TempPathFactory) -> None:
    db_path = str(tmp_path / "smoke_buy.db")
    runner = CliRunner()

    mock_client = MagicMock()
    mock_client.get_instrument_info.return_value = {
        "symbol": "BTCUSDT",
        "lotSizeFilter": {
            "qtyStep": "0.001",
            "minOrderQty": "0.001",
            "maxOrderQty": "1000",
        },
    }
    mock_client.place_order.return_value = {
        "orderId": "test-order-buy",
        "price": "50000.0",
        "cumExecValue": "50.0",
        "cumExecFee": "0.025",
    }
    mock_client.get_executions.return_value = [
        {
            "execId": "test-exec-buy-001",
            "execPrice": "50000.0",
            "execQty": "0.001",
            "execFee": "0.025",
            "realizedPnl": "0.0",
            "execTime": "2024-01-01T00:00:00Z",
        }
    ]

    mock_class = MagicMock()
    mock_class.round_to_step.return_value = 0.001

    with (
        patch.dict(os.environ, {"ZTB_BYBIT_API_KEY": "test-key",
                                "ZTB_BYBIT_API_SECRET": "test-secret"}),
        patch("ztb.execution.bybit_client.BybitClient", mock_class),
    ):
        mock_class.return_value = mock_client
        result = runner.invoke(cli, [
            "smoke-test",
            "--symbol", "BTCUSDT",
            "--qty", "0.001",
            "--db", db_path,
            "--timeout", "5",
        ])

    assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"
    assert "SMOKE TEST PASSED" in result.output
    call_kwargs = mock_client.place_order.call_args[1]
    assert call_kwargs["side"].value == "Buy"


def test_smoke_test_order_skipped(tmp_path: pytest.TempPathFactory) -> None:
    db_path = str(tmp_path / "smoke_skip.db")
    runner = CliRunner()

    mock_client = MagicMock()
    mock_client.get_instrument_info.return_value = {
        "symbol": "BTCUSDT",
        "lotSizeFilter": {
            "qtyStep": "0.001",
            "minOrderQty": "0.01",
            "maxOrderQty": "1000",
        },
    }
    mock_client.place_order.return_value = {
        "skipped": True,
        "reason": "Qty 0.001 below minOrderQty 0.01 for BTCUSDT",
    }

    mock_class = MagicMock()
    mock_class.round_to_step.return_value = 0.001

    with (
        patch.dict(os.environ, {"ZTB_BYBIT_API_KEY": "test-key",
                                "ZTB_BYBIT_API_SECRET": "test-secret"}),
        patch("ztb.execution.bybit_client.BybitClient", mock_class),
    ):
        mock_class.return_value = mock_client
        result = runner.invoke(cli, [
            "smoke-test",
            "--symbol", "BTCUSDT",
            "--qty", "0.001",
            "--db", db_path,
            "--timeout", "5",
        ])

    assert result.exit_code == 1
    assert "skipped" in result.output


def test_smoke_test_api_error(tmp_path: pytest.TempPathFactory) -> None:
    db_path = str(tmp_path / "smoke_err.db")
    runner = CliRunner()

    mock_client = MagicMock()
    mock_client.get_instrument_info.side_effect = Exception("API connection failed")

    mock_class = MagicMock()

    with (
        patch.dict(os.environ, {"ZTB_BYBIT_API_KEY": "test-key",
                                "ZTB_BYBIT_API_SECRET": "test-secret"}),
        patch("ztb.execution.bybit_client.BybitClient", mock_class),
    ):
        mock_class.return_value = mock_client
        result = runner.invoke(cli, [
            "smoke-test",
            "--symbol", "BTCUSDT",
            "--qty", "0.001",
            "--db", db_path,
            "--timeout", "5",
        ])

    assert result.exit_code == 1
    assert "Smoke test error" in result.output
    assert "API connection failed" in result.output


def test_smoke_test_zero_fills(tmp_path: pytest.TempPathFactory) -> None:
    db_path = str(tmp_path / "smoke_zero.db")
    runner = CliRunner()

    mock_client = MagicMock()
    mock_client.get_instrument_info.return_value = {
        "symbol": "BTCUSDT",
        "lotSizeFilter": {
            "qtyStep": "0.001",
            "minOrderQty": "0.001",
            "maxOrderQty": "1000",
        },
    }
    mock_client.place_order.return_value = {
        "orderId": "test-order-zero-fills",
        "price": "50000.0",
        "cumExecValue": "50.0",
        "cumExecFee": "0.025",
    }
    mock_client.get_executions.return_value = []

    mock_class = MagicMock()
    mock_class.round_to_step.return_value = 0.001

    with (
        patch.dict(os.environ, {"ZTB_BYBIT_API_KEY": "test-key",
                                "ZTB_BYBIT_API_SECRET": "test-secret"}),
        patch("ztb.execution.bybit_client.BybitClient", mock_class),
    ):
        mock_class.return_value = mock_client
        result = runner.invoke(cli, [
            "smoke-test",
            "--symbol", "BTCUSDT",
            "--qty", "0.001",
            "--db", db_path,
            "--timeout", "3",
            "--poll-interval", "0.5",
        ])

    assert result.exit_code == 1
    assert "no exec_fills row found" in result.output


def test_smoke_test_zero_commission_fails(tmp_path: pytest.TempPathFactory) -> None:
    db_path = str(tmp_path / "smoke_bad_fee.db")
    runner = CliRunner()

    mock_client = MagicMock()
    mock_client.get_instrument_info.return_value = {
        "symbol": "BTCUSDT",
        "lotSizeFilter": {
            "qtyStep": "0.001",
            "minOrderQty": "0.001",
            "maxOrderQty": "1000",
        },
    }
    mock_client.place_order.return_value = {
        "orderId": "test-order-bad-fee",
        "price": "50000.0",
        "cumExecValue": "50.0",
        "cumExecFee": "0.0",
    }
    mock_client.get_executions.return_value = [
        {
            "execId": "test-exec-bad-fee",
            "execPrice": "50000.0",
            "execQty": "0.001",
            "execFee": "0.0",
            "realizedPnl": "0.0",
            "execTime": "2024-01-01T00:00:00Z",
        }
    ]

    mock_class = MagicMock()
    mock_class.round_to_step.return_value = 0.001

    with (
        patch.dict(os.environ, {"ZTB_BYBIT_API_KEY": "test-key",
                                "ZTB_BYBIT_API_SECRET": "test-secret"}),
        patch("ztb.execution.bybit_client.BybitClient", mock_class),
    ):
        mock_class.return_value = mock_client
        result = runner.invoke(cli, [
            "smoke-test",
            "--symbol", "BTCUSDT",
            "--qty", "0.001",
            "--db", db_path,
            "--timeout", "5",
        ])

    assert result.exit_code == 1
    assert "zero commission" in result.output


def test_smoke_test_zero_price_fails(tmp_path: pytest.TempPathFactory) -> None:
    db_path = str(tmp_path / "smoke_bad_price.db")
    runner = CliRunner()

    mock_client = MagicMock()
    mock_client.get_instrument_info.return_value = {
        "symbol": "BTCUSDT",
        "lotSizeFilter": {
            "qtyStep": "0.001",
            "minOrderQty": "0.001",
            "maxOrderQty": "1000",
        },
    }
    mock_client.place_order.return_value = {
        "orderId": "test-order-bad-price",
        "price": "0.0",
        "cumExecValue": "0.0",
        "cumExecFee": "0.0",
    }
    mock_client.get_executions.return_value = [
        {
            "execId": "test-exec-bad-price",
            "execPrice": "0.0",
            "execQty": "0.001",
            "execFee": "0.025",
            "realizedPnl": "0.0",
            "execTime": "2024-01-01T00:00:00Z",
        }
    ]

    mock_class = MagicMock()
    mock_class.round_to_step.return_value = 0.001

    with (
        patch.dict(os.environ, {"ZTB_BYBIT_API_KEY": "test-key",
                                "ZTB_BYBIT_API_SECRET": "test-secret"}),
        patch("ztb.execution.bybit_client.BybitClient", mock_class),
    ):
        mock_class.return_value = mock_client
        result = runner.invoke(cli, [
            "smoke-test",
            "--symbol", "BTCUSDT",
            "--qty", "0.001",
            "--db", db_path,
            "--timeout", "5",
        ])

    assert result.exit_code == 1
    assert "zero price" in result.output


def test_smoke_test_poll_retries_until_fills(tmp_path: pytest.TempPathFactory) -> None:
    db_path = str(tmp_path / "smoke_poll.db")
    runner = CliRunner()

    mock_client = MagicMock()
    mock_client.get_instrument_info.return_value = {
        "symbol": "BTCUSDT",
        "lotSizeFilter": {
            "qtyStep": "0.001",
            "minOrderQty": "0.001",
            "maxOrderQty": "1000",
        },
    }
    mock_client.place_order.return_value = {
        "orderId": "test-order-poll",
        "price": "50000.0",
        "cumExecValue": "50.0",
        "cumExecFee": "0.025",
    }
    mock_client.get_executions.side_effect = [
        [],
        [],
        [
            {
                "execId": "test-exec-poll",
                "execPrice": "50000.0",
                "execQty": "0.001",
                "execFee": "0.025",
                "realizedPnl": "0.0",
                "execTime": "2024-01-01T00:00:00Z",
            }
        ],
    ]

    mock_class = MagicMock()
    mock_class.round_to_step.return_value = 0.001

    with (
        patch.dict(os.environ, {"ZTB_BYBIT_API_KEY": "test-key",
                                "ZTB_BYBIT_API_SECRET": "test-secret"}),
        patch("ztb.execution.bybit_client.BybitClient", mock_class),
    ):
        mock_class.return_value = mock_client
        result = runner.invoke(cli, [
            "smoke-test",
            "--symbol", "BTCUSDT",
            "--qty", "0.001",
            "--db", db_path,
            "--timeout", "10",
            "--poll-interval", "0.3",
        ])

    assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"
    assert "SMOKE TEST PASSED" in result.output
    assert mock_client.get_executions.call_count == 3


def test_smoke_test_poll_timeout_no_fills(tmp_path: pytest.TempPathFactory) -> None:
    db_path = str(tmp_path / "smoke_timeout.db")
    runner = CliRunner()

    mock_client = MagicMock()
    mock_client.get_instrument_info.return_value = {
        "symbol": "BTCUSDT",
        "lotSizeFilter": {
            "qtyStep": "0.001",
            "minOrderQty": "0.001",
            "maxOrderQty": "1000",
        },
    }
    mock_client.place_order.return_value = {
        "orderId": "test-order-timeout",
        "price": "50000.0",
        "cumExecValue": "50.0",
        "cumExecFee": "0.025",
    }
    mock_client.get_executions.return_value = []

    mock_class = MagicMock()
    mock_class.round_to_step.return_value = 0.001

    with (
        patch.dict(os.environ, {"ZTB_BYBIT_API_KEY": "test-key",
                                "ZTB_BYBIT_API_SECRET": "test-secret"}),
        patch("ztb.execution.bybit_client.BybitClient", mock_class),
    ):
        mock_class.return_value = mock_client
        result = runner.invoke(cli, [
            "smoke-test",
            "--symbol", "BTCUSDT",
            "--qty", "0.001",
            "--db", db_path,
            "--timeout", "1",
            "--poll-interval", "0.2",
        ])

    assert result.exit_code == 1
    assert "no exec_fills row found" in result.output


@pytest.mark.network
def test_smoke_test_network() -> None:
    """Live smoke test against Bybit demo. Requires ZTB_BYBIT_API_KEY and ZTB_BYBIT_API_SECRET."""
    runner = CliRunner()
    result = runner.invoke(cli, [
        "smoke-test",
        "--symbol", "BTCUSDT",
        "--qty", "0.001",
        "--timeout", "30",
    ])
    assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"
    assert "SMOKE TEST PASSED" in result.output
