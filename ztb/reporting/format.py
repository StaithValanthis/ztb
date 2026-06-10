from __future__ import annotations

from ztb.engine.backtest import BacktestResult
from ztb.engine.forwardtest import ForwardtestResult

OOS_SHARPE_FLOOR: float = 0.5
MAX_DD_LIMIT: float = -0.25
MIN_TRADES: int = 30


def pass_fail(
    value: float | None, threshold: float, higher_is_better: bool = True
) -> tuple[bool, str]:
    if value is None:
        return (False, "FAIL: no data")
    if higher_is_better:
        return (True, "PASS") if value >= threshold else (False, f"FAIL: {value} < {threshold}")
    return (True, "PASS") if value <= threshold else (False, f"FAIL: {value} > {threshold}")


def fmt_metric(v: float | None, decimals: int = 4) -> str:
    if v is None:
        return "N/A"
    return f"{v:.{decimals}f}"


def fmt_pct(v: float | None, decimals: int = 2) -> str:
    if v is None:
        return "N/A"
    return f"{v * 100:.{decimals}f}%"


def format_backtest_result(result: BacktestResult) -> str:
    lines: list[str] = []
    sep = "=" * 60
    lines.append(sep)
    lines.append(f"Backtest: {result.strategy_name} on {result.symbol} [{result.timeframe}]")
    lines.append(sep)
    header = (
        f"  {'Scope':12s} {'Return':>10s} {'Sharpe':>10s} "
        f"{'MaxDD':>10s} {'Trades':>8s} {'Win%':>8s} {'PF':>8s}"
    )
    lines.append(header)
    lines.append(f"  {'-' * 66}")
    for label, m in [("FULL", result.full), ("IS", result.is_), ("OOS", result.oos)]:
        credible = "\u2713" if m.credible else "\u2717"
        lines.append(
            f"  {label:12s} {fmt_metric(m.total_return, 4):>10s} "
            f"{fmt_metric(m.sharpe, 3):>10s} {fmt_metric(m.max_drawdown, 4):>10s} "
            f"{str(m.num_trades):>8s} {fmt_metric(m.win_rate, 3):>8s} "
            f"{fmt_metric(m.profit_factor, 3):>8s}  {credible}"
        )
    if not result.full.credible:
        lines.append(f"\n  Not credible: {result.full.reason}")
    if not result.oos.credible:
        lines.append(f"\n  OOS not credible: {result.oos.reason}")
    lines.append(sep)
    return "\n".join(lines)


def format_forwardtest_result(result: ForwardtestResult) -> str:
    lines: list[str] = []
    sep = "=" * 60
    lines.append(sep)
    lines.append(f"Forward Test: {result.strategy_name} on {result.symbol} [{result.timeframe}]")
    lines.append(sep)
    lines.append(f"  Warmup bars: {result.warmup_bars}  Total bars: {result.total_bars}")
    lines.append("")
    header = (
        f"  {'Scope':12s} {'Return':>10s} {'Sharpe':>10s} "
        f"{'MaxDD':>10s} {'Trades':>8s} {'Win%':>8s} {'PF':>8s}"
    )
    lines.append(header)
    lines.append(f"  {'-' * 66}")
    m = result.metrics
    credible = "\u2713" if m.credible else "\u2717"
    lines.append(
        f"  {'FORWARD':12s} {fmt_metric(m.total_return, 4):>10s} "
        f"{fmt_metric(m.sharpe, 3):>10s} {fmt_metric(m.max_drawdown, 4):>10s} "
        f"{str(m.num_trades):>8s} {fmt_metric(m.win_rate, 3):>8s} "
        f"{fmt_metric(m.profit_factor, 3):>8s}  {credible}"
    )
    if not m.credible:
        lines.append(f"\n  Not credible: {m.reason}")
    lines.append(sep)
    return "\n".join(lines)
