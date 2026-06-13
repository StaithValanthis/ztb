from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ztb.execution.models import AccountState, Fill, OrderSide, Position


@dataclass
class ReconcileReport:
    matched: bool = True
    position_drift: float = 0.0
    pnl_drift: float = 0.0
    orphan_order_ids: list[str] = field(default_factory=list)
    missing_fills: list[Fill] = field(default_factory=list)
    unexpected_fills: list[dict[str, Any]] = field(default_factory=list)
    expected_position: float = 0.0
    actual_position: float = 0.0
    actual_avg_price: float = 0.0
    expected_pnl: float = 0.0
    actual_pnl: float = 0.0
    issues: list[str] = field(default_factory=list)
    reconciled: bool = False
    irreconcilable: bool = False


def reconcile_and_adopt(
    expected: AccountState,
    actual: AccountState,
    symbol: str,
    tolerance: float = 1e-8,
) -> ReconcileReport:
    report = reconcile_account(expected, actual, symbol, tolerance)
    if not report.matched and abs(report.position_drift) > tolerance * 100:
        report.irreconcilable = True
        report.issues.append("DRIFT EXCEEDS ADOPT THRESHOLD — manual intervention required")
    elif not report.matched:
        report.reconciled = True
    return report


def heal_drift(report: ReconcileReport) -> float:
    return report.actual_position - report.expected_position


def reconcile_account(
    expected: AccountState,
    actual: AccountState,
    symbol: str,
    tolerance: float = 1e-8,
) -> ReconcileReport:
    report = ReconcileReport()
    exp_pos = expected.positions.get(symbol)
    act_pos = actual.positions.get(symbol)

    if exp_pos is not None and act_pos is not None:
        report.expected_position = exp_pos.size
        report.actual_position = act_pos.size
        report.actual_avg_price = act_pos.avg_price
        report.position_drift = act_pos.size - exp_pos.size
    elif exp_pos is not None:
        report.expected_position = exp_pos.size
        report.actual_position = 0.0
        report.position_drift = -exp_pos.size
    elif act_pos is not None:
        report.expected_position = 0.0
        report.actual_position = act_pos.size
        report.actual_avg_price = act_pos.avg_price
        report.position_drift = act_pos.size

    if abs(report.position_drift) > tolerance:
        report.issues.append(
            f"Position drift: expected={report.expected_position:.6f} "
            f"actual={report.actual_position:.6f}"
        )
    report.actual_pnl = actual.unrealized_pnl
    report.matched = len(report.issues) == 0
    return report


def compute_account_state(
    positions_raw: list[dict[str, Any]],
    wallet_raw: dict[str, Any],
) -> AccountState:
    positions: dict[str, Position] = {}
    for p in positions_raw:
        sym = p.get("symbol", "")
        pos_size = float(p.get("size", 0.0))
        if abs(pos_size) < 1e-12:
            continue
        positions[sym] = Position(
            symbol=sym,
            size=pos_size,
            avg_price=float(p.get("avgPrice", 0.0)),
            unrealized_pnl=float(p.get("unrealisedPnl", 0.0)),
            realized_pnl=float(p.get("cumRealisedPnl", 0.0)),
            timestamp=p.get("updatedTime", ""),
        )

    total_equity = 0.0
    wallet_balance = 0.0
    unrealized_pnl = 0.0
    if wallet_raw:
        for account_info in wallet_raw.get("list", []):
            for coin_entry in account_info.get("coin", []):
                if coin_entry.get("coin", "") in ("USDT", "USDC"):
                    total_equity += float(coin_entry.get("equity", 0.0))
                    wallet_balance += float(coin_entry.get("walletBalance", 0.0))
                    unrealized_pnl += float(coin_entry.get("unrealisedPnl", 0.0))

    return AccountState(
        total_equity=total_equity,
        wallet_balance=wallet_balance,
        unrealized_pnl=unrealized_pnl,
        positions=positions,
        timestamp="",
    )


def parse_fills(fills_raw: list[dict[str, Any]]) -> list[Fill]:
    fills: list[Fill] = []
    for f in fills_raw:
        fills.append(
            Fill(
                exec_id=f.get("execId", ""),
                order_id=f.get("orderId", ""),
                symbol=f.get("symbol", ""),
                side=OrderSide(f.get("side", "Buy").capitalize()),
                price=float(f.get("execPrice", 0.0)),
                qty=float(f.get("execQty", 0.0)),
                commission=float(f.get("execFee", 0.0)),
                realized_pnl=float(f.get("execRealisedPnl", 0.0)),
                timestamp=f.get("execTime", ""),
            )
        )
    return fills
