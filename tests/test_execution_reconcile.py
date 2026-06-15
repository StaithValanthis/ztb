from __future__ import annotations

from ztb.execution.models import AccountState, Position
from ztb.execution.reconcile import (
    compute_account_state,
    heal_drift,
    parse_fills,
    reconcile_account,
    reconcile_and_adopt,
)


def _make_position(size: float, avg_price: float = 50000.0) -> Position:
    return Position(
        symbol="BTCUSDT",
        size=size,
        avg_price=avg_price,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        timestamp="",
    )


def test_reconcile_matched() -> None:
    expected = AccountState(
        total_equity=100000.0,
        wallet_balance=100000.0,
        unrealized_pnl=0.0,
        positions={"BTCUSDT": _make_position(0.5)},
    )
    actual = AccountState(
        total_equity=100000.0,
        wallet_balance=100000.0,
        unrealized_pnl=0.0,
        positions={"BTCUSDT": _make_position(0.5)},
    )
    report = reconcile_account(expected, actual, "BTCUSDT")
    assert report.matched is True
    assert len(report.issues) == 0
    assert report.position_drift == 0.0


def test_reconcile_position_drift() -> None:
    expected = AccountState(
        total_equity=100000.0,
        wallet_balance=100000.0,
        unrealized_pnl=0.0,
        positions={"BTCUSDT": _make_position(0.5)},
    )
    actual = AccountState(
        total_equity=100000.0,
        wallet_balance=100000.0,
        unrealized_pnl=0.0,
        positions={"BTCUSDT": _make_position(0.4)},
    )
    report = reconcile_account(expected, actual, "BTCUSDT")
    assert report.matched is False
    assert len(report.issues) > 0
    assert abs(report.position_drift - (-0.1)) < 1e-8


def test_reconcile_expected_only() -> None:
    expected = AccountState(
        total_equity=100000.0,
        wallet_balance=100000.0,
        unrealized_pnl=0.0,
        positions={"BTCUSDT": _make_position(0.5)},
    )
    actual = AccountState(
        total_equity=100000.0,
        wallet_balance=100000.0,
        unrealized_pnl=0.0,
    )
    report = reconcile_account(expected, actual, "BTCUSDT")
    assert report.matched is False
    assert report.actual_position == 0.0
    assert report.expected_position == 0.5


def test_reconcile_actual_only() -> None:
    expected = AccountState(
        total_equity=100000.0,
        wallet_balance=100000.0,
        unrealized_pnl=0.0,
    )
    actual = AccountState(
        total_equity=100000.0,
        wallet_balance=100000.0,
        unrealized_pnl=0.0,
        positions={"BTCUSDT": _make_position(0.3)},
    )
    report = reconcile_account(expected, actual, "BTCUSDT")
    assert report.matched is False
    assert report.actual_position == 0.3
    assert report.expected_position == 0.0


def test_reconcile_no_positions() -> None:
    expected = AccountState(total_equity=100000.0, wallet_balance=100000.0, unrealized_pnl=0.0)
    actual = AccountState(total_equity=100000.0, wallet_balance=100000.0, unrealized_pnl=0.0)
    report = reconcile_account(expected, actual, "BTCUSDT")
    assert report.matched is True


def test_reconcile_reports_actual_available_balance() -> None:
    expected = AccountState(total_equity=100000.0, wallet_balance=100000.0, unrealized_pnl=0.0)
    actual = AccountState(
        total_equity=100000.0,
        wallet_balance=95000.0,
        available_balance=80000.0,
        unrealized_pnl=5000.0,
    )
    report = reconcile_account(expected, actual, "BTCUSDT")
    assert report.actual_wallet_balance == 95000.0
    assert report.actual_available_balance == 80000.0
    assert report.actual_equity == 100000.0


def test_compute_account_state_empty() -> None:
    state = compute_account_state([], {})
    assert state.total_equity == 0.0
    assert state.wallet_balance == 0.0
    assert state.positions == {}


def test_compute_account_state_with_positions() -> None:
    positions_raw = [
        {
            "symbol": "BTCUSDT",
            "size": "0.5",
            "avgPrice": "50000.0",
            "unrealisedPnl": "100.0",
            "cumRealisedPnl": "50.0",
            "updatedTime": "",
        }
    ]
    wallet_raw = {
        "list": [
            {
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "100000.0",
                        "walletBalance": "99900.0",
                        "unrealisedPnl": "100.0",
                    }
                ]
            }
        ]
    }
    state = compute_account_state(positions_raw, wallet_raw)
    assert "BTCUSDT" in state.positions
    assert state.positions["BTCUSDT"].size == 0.5
    assert state.positions["BTCUSDT"].avg_price == 50000.0
    assert state.total_equity == 100000.0
    assert state.wallet_balance == 99900.0


def test_compute_account_state_extracts_available_balance() -> None:
    wallet_raw = {
        "list": [
            {
                "totalAvailableBalance": "80000.0",
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "100000.0",
                        "walletBalance": "95000.0",
                        "unrealisedPnl": "5000.0",
                    }
                ]
            }
        ]
    }
    state = compute_account_state([], wallet_raw)
    assert state.available_balance == 80000.0
    assert state.wallet_balance == 95000.0
    assert state.total_equity == 100000.0
    assert state.unrealized_pnl == 5000.0


def test_compute_account_state_available_balance_defaults_zero() -> None:
    state = compute_account_state([], {})
    assert state.available_balance == 0.0


def test_compute_account_state_zero_position_skipped() -> None:
    positions_raw = [
        {
            "symbol": "BTCUSDT",
            "size": "0.0",
            "avgPrice": "0.0",
            "unrealisedPnl": "0.0",
            "cumRealisedPnl": "0.0",
            "updatedTime": "",
        }
    ]
    state = compute_account_state(positions_raw, {})
    assert "BTCUSDT" not in state.positions


def test_parse_fills() -> None:
    fills_raw = [
        {
            "execId": "exec1",
            "orderId": "ord1",
            "symbol": "BTCUSDT",
            "side": "Buy",
            "execPrice": "50000.0",
            "execQty": "0.1",
            "execFee": "2.5",
            "execRealisedPnl": "0.0",
            "execTime": "2026-01-01T00:00:00Z",
        }
    ]
    fills = parse_fills(fills_raw)
    assert len(fills) == 1
    assert fills[0].exec_id == "exec1"
    assert fills[0].price == 50000.0
    assert fills[0].qty == 0.1
    assert fills[0].commission == 2.5


def _make_state(pos_size: float = 0.0, avg_price: float = 0.0) -> AccountState:
    return AccountState(
        total_equity=100000.0,
        wallet_balance=100000.0,
        unrealized_pnl=0.0,
        positions={
            "BTCUSDT": Position(
                symbol="BTCUSDT",
                size=pos_size,
                avg_price=avg_price,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
                timestamp="2026-06-11T00:00:00Z",
            )
        },
        timestamp="2026-06-11T00:00:00Z",
    )


def test_reconcile_and_adopt_matched() -> None:
    exp = _make_state(pos_size=1.0, avg_price=50000.0)
    act = _make_state(pos_size=1.0, avg_price=50000.0)
    report = reconcile_and_adopt(exp, act, "BTCUSDT")
    assert report.matched
    assert not report.irreconcilable
    assert report.reconciled is False


def test_reconcile_and_adopt_small_drift() -> None:
    exp = _make_state(pos_size=1.0, avg_price=50000.0)
    act = _make_state(pos_size=1.00001, avg_price=50000.0)
    report = reconcile_and_adopt(exp, act, "BTCUSDT", tolerance=1e-6)
    assert not report.matched
    assert not report.irreconcilable
    assert report.reconciled


def test_reconcile_and_adopt_large_drift() -> None:
    exp = _make_state(pos_size=1.0, avg_price=50000.0)
    act = _make_state(pos_size=1.5, avg_price=50000.0)
    report = reconcile_and_adopt(exp, act, "BTCUSDT")
    assert not report.matched
    assert report.irreconcilable


def test_heal_drift() -> None:
    exp = _make_state(pos_size=1.0, avg_price=50000.0)
    act = _make_state(pos_size=1.5, avg_price=50000.0)
    report = reconcile_account(exp, act, "BTCUSDT")
    drift = heal_drift(report)
    assert drift == 0.5


def test_heal_drift_zero() -> None:
    exp = _make_state(pos_size=1.0, avg_price=50000.0)
    act = _make_state(pos_size=1.0, avg_price=50000.0)
    report = reconcile_account(exp, act, "BTCUSDT")
    drift = heal_drift(report)
    assert drift == 0.0
