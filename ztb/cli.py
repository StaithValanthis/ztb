from __future__ import annotations

import sys

import click
from pandas import DataFrame

from ztb import __version__
from ztb.data.bybit_rest import BackoffStrategy, BybitPublicREST, TokenBucket
from ztb.data.cache import read_cache
from ztb.data.errors import CacheError, DataError, FetchError
from ztb.data.integrity import check_integrity
from ztb.data.loader import load
from ztb.data.timeframes import interval_to_ms
from ztb.engine.backtest import BacktestConfig, run_backtest
from ztb.engine.forwardtest import ForwardtestConfig, run_forwardtest
from ztb.engine.metrics import MetricsResult
from ztb.reporting.format import format_backtest_result, format_forwardtest_result
from ztb.reporting.scorecard import build_scorecard
from ztb.store.results import (
    connect,
    get_equity_curve,
    get_metrics,
    get_run,
    get_trades,
    list_runs,
    save_forward_run,
    save_run,
)
from ztb.strategies.registry import get as get_strategy
from ztb.strategies.registry import list_names


@click.group()
@click.version_option(version=__version__, prog_name="ztb")
def cli() -> None:
    pass


@cli.group()
def data() -> None:
    """Data management commands."""


@data.command()
@click.argument("symbol")
@click.option("--timeframe", default="60", help="Timeframe interval (1, 5, 15, 60, D, W, M)")
@click.option("--category", default="linear", help="Market category")
@click.option("--start", default=None, help="Start date (ISO format)")
@click.option("--end", default=None, help="End date (ISO format)")
def fetch(
    symbol: str,
    timeframe: str,
    category: str,
    start: str | None,
    end: str | None,
) -> None:
    """Download and cache OHLCV data for a symbol/timeframe range."""
    try:
        df = load(
            symbol=symbol,
            timeframe=timeframe,
            category=category,
            start=start,
            end=end,
        )
        click.echo(f"Fetched {len(df)} bars for {symbol} {timeframe} {category}")
    except DataError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@data.command()
@click.argument("symbol")
@click.option("--timeframe", default="60", help="Timeframe interval")
@click.option("--category", default="linear", help="Market category")
@click.option("--head", default=10, type=int, help="Number of rows to show")
@click.option("--tail", default=0, type=int, help="Number of rows from end")
def show(
    symbol: str,
    timeframe: str,
    category: str,
    head: int,
    tail: int,
) -> None:
    """Display cached data for a symbol."""
    try:
        df = read_cache(category=category, symbol=symbol, interval=timeframe)
        if df is None or df.empty:
            click.echo(f"No cached data for {symbol} {timeframe} {category}")
            sys.exit(1)

        if tail > 0:
            click.echo(f"Last {tail} bars for {symbol}:")
            click.echo(df.tail(tail).to_string())
        else:
            click.echo(f"First {head} bars for {symbol} (total {len(df)})")
            click.echo(df.head(head).to_string())
        click.echo(f"\nRange: {df.index[0]} to {df.index[-1]}")
        click.echo(f"Bars: {len(df)}")
    except CacheError as exc:
        click.echo(f"Cache error: {exc}", err=True)
        sys.exit(1)


@data.command()
@click.argument("symbol")
@click.option("--timeframe", default="60", help="Timeframe interval")
@click.option("--category", default="linear", help="Market category")
def verify(symbol: str, timeframe: str, category: str) -> None:
    """Full integrity check + freshness."""
    df = read_cache(category=category, symbol=symbol, interval=timeframe)
    if df is None or df.empty:
        click.echo(f"No cached data for {symbol} {timeframe} {category}")
        sys.exit(1)

    import pandas as pd

    interval_ms = interval_to_ms(timeframe)
    report = check_integrity(df, interval_ms, reference_ts=pd.Timestamp.now(tz="UTC"))

    click.echo(f"Integrity report for {symbol} {timeframe} {category}:")
    click.echo(f"  Bars:        {report.n_bars}")
    click.echo(f"  Has gaps:    {report.has_gaps} ({report.gap_count})")
    click.echo(f"  Has dupes:   {report.has_dupes} ({report.dupe_count})")
    click.echo(f"  Monotonic:   {report.is_monotonic}")
    click.echo(f"  Unique:      {report.is_unique}")
    click.echo(f"  Fresh:       {report.is_fresh}")
    if report.freshness_seconds is not None:
        click.echo(f"  Age (s):     {report.freshness_seconds:.1f}")
    if report.gap_ranges:
        for gs, ge in report.gap_ranges[:5]:
            click.echo(f"  Gap:         {gs} -> {ge}")

    if report.has_gaps or report.has_dupes or not report.is_monotonic:
        sys.exit(1)


@data.command()
@click.option("--category", default="linear", help="Market category")
def instruments(category: str) -> None:
    """List available instruments for a category."""
    limiter = TokenBucket(capacity=10, refill_rate=10, refill_interval=1.0)
    backoff = BackoffStrategy()
    client = BybitPublicREST(rate_limiter=limiter, backoff=backoff)

    try:
        from ztb.data.fetch import fetch_instruments

        items = fetch_instruments(client, category)
        if not items:
            click.echo(f"No instruments found for {category}")
            sys.exit(1)
        for item in items:
            name = item.get("symbol", item.get("name", "?"))
            status = item.get("status", "?")
            click.echo(f"{name:20s} {status}")
        click.echo(f"\nTotal: {len(items)} instruments")
    except FetchError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("strategy_name")
@click.argument("symbol")
@click.option("--timeframe", default="60", help="Timeframe interval (1, 5, 15, 60, D, W, M)")
@click.option("--category", default="linear", help="Market category")
@click.option("--start", default=None, help="Start date (ISO format)")
@click.option("--end", default=None, help="End date (ISO format)")
@click.option("--cash", default=100000.0, type=float, help="Initial cash")
@click.option("--commission", default=0.0005, type=float, help="Commission rate")
@click.option("--slippage", default=0.0005, type=float, help="Slippage rate")
@click.option("--risk-enabled", is_flag=True, help="Enable risk management")
@click.option("--persist", is_flag=True, help="Save result to the store")
@click.option("--db", default=None, help="Path to result database")
def backtest(
    strategy_name: str,
    symbol: str,
    timeframe: str,
    category: str,
    start: str | None,
    end: str | None,
    cash: float,
    commission: float,
    slippage: float,
    risk_enabled: bool,
    persist: bool,
    db: str | None,
) -> None:
    """Run a backtest for a strategy on a symbol."""
    try:
        strat_cls = get_strategy(strategy_name)
    except KeyError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    try:
        df = load(symbol=symbol, timeframe=timeframe, category=category, start=start, end=end)
    except DataError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    strategy = strat_cls()
    strategy.symbols = [symbol]
    strategy.timeframe = timeframe

    cfg = BacktestConfig(
        initial_cash=cash,
        commission=commission,
        slippage=slippage,
        risk_enabled=risk_enabled,
    )

    result = run_backtest(strategy, df, cfg)

    click.echo(format_backtest_result(result))

    if persist:
        conn = connect(db)
        run_id = save_run(conn, result)
        conn.close()
        click.echo(f"Saved to store: run_id={run_id}")


@cli.command()
@click.argument("strategy_name")
@click.argument("symbol")
@click.option("--timeframe", default="60", help="Timeframe interval (1, 5, 15, 60, D, W, M)")
@click.option("--category", default="linear", help="Market category")
@click.option("--start", default=None, help="Start date (ISO format)")
@click.option("--end", default=None, help="End date (ISO format)")
@click.option("--cash", default=100000.0, type=float, help="Initial cash")
@click.option("--commission", default=0.0005, type=float, help="Commission rate")
@click.option("--slippage", default=0.0005, type=float, help="Slippage rate")
@click.option("--warmup", default=100, type=int, help="Warmup bars before forward test begins")
@click.option("--no-risk", is_flag=True, help="Disable risk management (default: ON)")
@click.option(
    "--baseline-run-id", default=None, help="Run ID for baseline metrics (decay computation)"
)
@click.option("--persist", is_flag=True, help="Save result to the store")
@click.option("--db", default=None, help="Path to result database")
def forwardtest(
    strategy_name: str,
    symbol: str,
    timeframe: str,
    category: str,
    start: str | None,
    end: str | None,
    cash: float,
    commission: float,
    slippage: float,
    warmup: int,
    no_risk: bool,
    baseline_run_id: str | None,
    persist: bool,
    db: str | None,
) -> None:
    """Run a forward test for a strategy on a symbol."""
    try:
        strat_cls = get_strategy(strategy_name)
    except KeyError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    try:
        df = load(symbol=symbol, timeframe=timeframe, category=category, start=start, end=end)
    except DataError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    strategy = strat_cls()
    strategy.symbols = [symbol]
    strategy.timeframe = timeframe

    cfg = ForwardtestConfig(
        initial_cash=cash,
        commission=commission,
        slippage=slippage,
        warmup_bars=warmup,
        risk_enabled=not no_risk,
    )

    need_store = persist or baseline_run_id is not None
    conn = connect(db) if need_store else None

    baseline_metrics: MetricsResult | None = None
    if baseline_run_id is not None:
        run_info = get_run(conn, baseline_run_id) if conn else None
        if run_info is None:
            if conn:
                conn.close()
            click.echo(f"Baseline run not found: {baseline_run_id}", err=True)
            sys.exit(1)
        metrics_rows = get_metrics(conn, baseline_run_id) if conn else []
        full_metrics = next((r for r in metrics_rows if r["scope"] == "full"), None)
        if full_metrics is None:
            if conn:
                conn.close()
            click.echo(f"No 'full' metrics for baseline run {baseline_run_id}", err=True)
            sys.exit(1)
        baseline_metrics = MetricsResult(
            total_return=full_metrics["total_return"],
            sharpe=full_metrics["sharpe"],
            sortino=full_metrics["sortino"],
            max_drawdown=full_metrics["max_drawdown"],
            max_drawdown_duration=full_metrics["max_drawdown_duration"],
            num_trades=full_metrics["num_trades"],
            profit_factor=full_metrics["profit_factor"],
            win_rate=full_metrics["win_rate"],
            turnover=full_metrics["turnover"],
            exposure_time=full_metrics["exposure_time"],
            sufficient_sample=bool(full_metrics["sufficient_sample"]),
            reason=full_metrics["reason"],
        )

    result = run_forwardtest(
        strategy,
        df,
        cfg,
        baseline_metrics=baseline_metrics,
        baseline_run_id=baseline_run_id,
    )

    click.echo(format_forwardtest_result(result))

    if persist:
        assert conn is not None
        run_id = save_forward_run(conn, result)
        click.echo(f"Saved to store: run_id={run_id}")
    if conn is not None:
        conn.close()


@cli.command()
@click.argument("strategy_name")
@click.argument("symbol")
@click.option("--timeframe", default="60", help="Timeframe interval (1, 5, 15, 60, D, W, M)")
@click.option("--category", default="linear", help="Market category")
@click.option("--start", default=None, help="Start date (ISO format)")
@click.option("--end", default=None, help="End date (ISO format)")
@click.option("--cash", default=100000.0, type=float, help="Initial cash")
@click.option("--commission", default=0.0005, type=float, help="Commission rate")
@click.option("--slippage", default=0.0005, type=float, help="Slippage rate")
@click.option("--walk-forward-windows", default=4, type=int, help="Number of walk-forward windows")
@click.option("--train-ratio", default=0.7, type=float, help="Training ratio per window")
@click.option("--db", default=None, help="Path to result database")
@click.option("--persist", is_flag=True, help="Save result to the store")
def validate(
    strategy_name: str,
    symbol: str,
    timeframe: str,
    category: str,
    start: str | None,
    end: str | None,
    cash: float,
    commission: float,
    slippage: float,
    walk_forward_windows: int,
    train_ratio: float,
    db: str | None,
    persist: bool,
) -> None:
    """Run OOS validation gate for a strategy on a symbol."""

    try:
        strat_cls = get_strategy(strategy_name)
    except KeyError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)

    try:
        df = load(symbol=symbol, timeframe=timeframe, category=category, start=start, end=end)
    except DataError as exc:
        click.echo(f"Error loading data: {exc}", err=True)
        sys.exit(2)

    strategy = strat_cls()
    strategy.symbols = [symbol]
    strategy.timeframe = timeframe

    from ztb.validation.lookahead import run_lookahead_tripwire

    def _data_factory() -> DataFrame:
        return df[["open", "high", "low", "close", "volume"]].copy()

    click.echo("Running look-ahead tripwire...")
    lookahead_result = run_lookahead_tripwire(strategy, _data_factory)
    if not lookahead_result.passed:
        click.echo("VALIDATE FAIL: look-ahead detected")
        for d in lookahead_result.details:
            click.echo(f"  {d}")
        sys.exit(1)

    click.echo(f"Look-ahead: PASS  ({lookahead_result.bars_checked} bars checked)")

    from ztb.validation.walk_forward import WalkForwardConfig, run_walk_forward

    wf_config = WalkForwardConfig(
        n_windows=walk_forward_windows,
        train_ratio=train_ratio,
        initial_cash=cash,
        commission=commission,
        slippage=slippage,
    )
    click.echo(f"Running walk-forward ({walk_forward_windows} windows)...")
    wf_result = run_walk_forward(strategy, df, wf_config)
    agg = wf_result.aggregate

    total_windows = wf_result.n_windows_total
    cred_windows = wf_result.n_windows_credible
    stab = wf_result.stability
    stab_str = f"{stab:.4f}" if stab is not None else "N/A"
    click.echo(
        f"Walk-forward: {total_windows} windows, "
        f"{cred_windows} credible (min_trades={wf_config.min_trades})"
    )
    click.echo(f"Stability: {stab_str}")

    from ztb.validation.deflated_sharpe import compute_deflated_sharpe

    oos_sharpe = agg.sharpe if agg.sharpe is not None else 0.0
    n_obs = agg.exposure_time if agg.exposure_time else 0
    n_trials = len(strategy.params) if hasattr(strategy, "params") and strategy.params else 1

    dsr_result = compute_deflated_sharpe(
        sharpe=oos_sharpe,
        n_observations=int(n_obs),
        n_trials=n_trials,
    )

    from ztb.validation.scoring import evaluate_acceptance_criteria

    scorecard = evaluate_acceptance_criteria(wf_result, dsr_result, lookahead_result)

    click.echo("")
    click.echo(f"{'':>20} {'Sharpe':>10} {'DSR':>10} {'MaxDD':>10} {'WinRate':>8} {'Trades':>8}")
    click.echo(f"{'':->66}")
    for idx, w in enumerate(wf_result.per_window):
        ws = f"{w.sharpe:.3f}" if w.sharpe is not None else "N/A"
        wdd = f"{w.max_drawdown:.3f}" if w.max_drawdown is not None else "N/A"
        wwr = f"{w.win_rate:.3f}" if w.win_rate is not None else "N/A"
        flag = "  (!)" if not w.sufficient_sample else ""
        click.echo(
            f"  Window {idx + 1:<5}     {ws:>10} {'—':>10} {wdd:>10}"
            f" {wwr:>8} {str(w.num_trades):>8}{flag}"
        )
    click.echo(f"{'':->66}")
    agg_sharpe = f"{agg.sharpe:.3f}" if agg.sharpe is not None else "N/A"
    agg_dd = f"{agg.max_drawdown:.3f}" if agg.max_drawdown is not None else "N/A"
    agg_wr = f"{agg.win_rate:.3f}" if agg.win_rate is not None else "N/A"
    dsr_val = f"{dsr_result.dsr:.3f}" if dsr_result.dsr is not None else "N/A"
    click.echo(
        f"  Aggregate (med) {agg_sharpe:>10} {dsr_val:>10} {agg_dd:>10}"
        f" {agg_wr:>8} {str(agg.num_trades):>8}"
    )
    click.echo("")

    for c in scorecard["criteria"]:
        status = "PASS" if c["pass"] else "FAIL"
        val_str = f"{c['value']:.3f}" if isinstance(c["value"], float) else str(c["value"])
        click.echo(
            f"  Criterion {c['id']}: {c['name']:<35s} "
            f"{val_str:>10s} {c['threshold']:>10s}  {status}"
        )

    click.echo("")
    passed = scorecard["pass"]
    n_pass = sum(1 for c in scorecard["criteria"] if c["pass"])
    n_total = len(scorecard["criteria"])
    result_str = "PASS" if passed else "FAIL"
    click.echo(f"RESULT: {result_str} ({n_pass}/{n_total}) — exit code {scorecard['exit_code']}")

    if persist and passed:
        from ztb.store.results import connect as store_connect
        from ztb.validation.store import save_validation_run

        conn = store_connect(db)
        run_id = save_validation_run(
            conn,
            strategy=strategy_name,
            symbol=symbol,
            timeframe=timeframe,
            overall_pass=passed,
            wf_result=wf_result,
            dsr=dsr_result.dsr,
            dsr_significant=dsr_result.is_significant,
            lookahead_pass=lookahead_result.passed,
        )
        conn.close()
        click.echo(f"Saved to store: run_id={run_id}")

    sys.exit(scorecard["exit_code"])


@cli.command()
@click.argument("strategy_name")
@click.argument("symbol")
@click.option("--timeframe", default="60", help="Timeframe interval (1, 5, 15, 60, D, W, M)")
@click.option("--category", default="linear", help="Market category")
@click.option("--start", default=None, help="Start date (ISO format)")
@click.option("--end", default=None, help="End date (ISO format)")
@click.option("--mode", default="demo", help="Execution mode (demo/live)")
@click.option("--cash", default=100000.0, type=float, help="Initial cash")
@click.option("--dry-run", is_flag=True, help="Simulate without placing orders")
@click.option("--once", is_flag=True, help="Process only the last bar")
@click.option("--loop", is_flag=True, help="Run in polling loop after processing history")
@click.option("--poll-interval", default=60.0, type=float, help="Seconds between polls")
@click.option("--lookback-bars", default=0, type=int, help="Minimum historical bars to load")
@click.option("--no-risk", is_flag=True, help="Disable risk management (default: ON)")
@click.option("--asset-precision", default=8, type=int, help="Decimal places for qty rounding")
@click.option("--db", default=None, help="Path to result database")
@click.option("--preflight", is_flag=True, help="Run preflight checks before execution")
@click.option("--expected-tag", default=None, help="Expected git tag for pinning")
@click.option("--expected-version", default=None, help="Expected installed version")
@click.option(
    "--loop-flush-interval",
    default=1,
    type=int,
    help="Flush bars_processed to DB every N bars (0=disabled)",
)
def run(
    strategy_name: str,
    symbol: str,
    timeframe: str,
    category: str,
    start: str | None,
    end: str | None,
    mode: str,
    cash: float,
    dry_run: bool,
    once: bool,
    loop: bool,
    poll_interval: float,
    lookback_bars: int,
    no_risk: bool,
    asset_precision: int,
    db: str | None,
    preflight: bool,
    expected_tag: str | None,
    expected_version: str | None,
    loop_flush_interval: int,
) -> None:
    """Execute a strategy on live/demo data."""
    from ztb.execution.executor import Executor
    from ztb.execution.killswitch import LiveKillSwitch
    from ztb.execution.models import ExecRunConfig
    from ztb.execution.models import Mode as ExecMode

    if preflight:
        click.echo("Running preflight checks...")
        from ztb.ops.preflight import run_preflight

        report = run_preflight(
            expected_tag=expected_tag,
            expected_version=expected_version or __version__,
            strategy_name=strategy_name,
            check_secrets_enabled=True,
        )
        for item in report.items:
            status = "\u2713" if item.passed else "\u2717"
            click.echo(f"  {status} {item.name}: {item.detail}")
        if not report.passed:
            click.echo("Preflight FAILED — aborting.", err=True)
            sys.exit(1)
        click.echo("Preflight PASSED.\n")

    try:
        strat_cls = get_strategy(strategy_name)
    except KeyError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    exec_mode = ExecMode(mode)

    strategy = strat_cls()
    strategy.symbols = [symbol]
    strategy.timeframe = timeframe

    config = ExecRunConfig(
        mode=exec_mode,
        dry_run=dry_run,
        once=once,
        loop=loop,
        poll_interval_seconds=poll_interval,
        lookback_bars=lookback_bars,
        initial_cash=cash,
        risk_enabled=not no_risk,
        asset_precision=asset_precision,
        loop_flush_interval=loop_flush_interval,
    )

    killswitch = LiveKillSwitch() if exec_mode == ExecMode.LIVE and not dry_run else None

    if not dry_run:
        import os

        from ztb.execution.bybit_client import BybitClient, ClientConfig

        api_key = os.environ.get("ZTB_BYBIT_API_KEY", "")
        api_secret = os.environ.get("ZTB_BYBIT_API_SECRET", "")
        if not api_key or not api_secret:
            click.echo("Error: ZTB_BYBIT_API_KEY and ZTB_BYBIT_API_SECRET must be set", err=True)
            sys.exit(1)
        client_cfg = ClientConfig(api_key=api_key, api_secret=api_secret, mode=exec_mode)
        client = BybitClient(client_cfg)
    else:
        client = None

    executor = Executor(strategy, config=config, killswitch=killswitch, client=client)

    try:
        result = executor.run(
            symbol=symbol,
            timeframe=timeframe,
            category=category,
            start=start,
            end=end,
            db_path=db,
        )
    except Exception as exc:
        click.echo(f"Execution error: {exc}", err=True)
        sys.exit(1)

    click.echo(f"Execution run: {result.exec_run_id}")
    click.echo(f"  Strategy:    {result.strategy_name}")
    click.echo(f"  Symbol:      {result.symbol}")
    click.echo(f"  Mode:        {result.mode.value}")
    click.echo(f"  Bars:        {result.bars_processed}")
    click.echo(f"  Position:    {result.current_position:.6f}")
    click.echo(f"  Realized PnL: {result.realized_pnl:.4f}")
    click.echo(f"  Status:      {result.status}")
    if dry_run:
        click.echo("(dry-run — no orders placed)")


@cli.command()
@click.option("--exec-run-id", default=None, help="Execution run ID to reconcile")
@click.option("--db", default=None, help="Path to result database")
def reconcile(exec_run_id: str | None, db: str | None) -> None:
    """Reconcile a previous execution run state against the exchange."""
    from ztb.execution.bybit_client import BybitClient, ClientConfig
    from ztb.execution.models import Mode as ExecMode
    from ztb.execution.reconcile import compute_account_state
    from ztb.store.exec_io import get_exec_run
    from ztb.store.results import connect

    conn = connect(db)
    from ztb.store.exec_io import ensure_exec_tables

    ensure_exec_tables(conn)

    if exec_run_id:
        run_info = get_exec_run(conn, exec_run_id)
        if run_info is None:
            click.echo(f"Execution run not found: {exec_run_id}", err=True)
            conn.close()
            sys.exit(1)
        click.echo(f"Reconciling run: {exec_run_id}")
        click.echo(f"  Strategy: {run_info['strategy_name']}")
        click.echo(f"  Symbol:   {run_info['symbol']}")
        click.echo(f"  Mode:     {run_info['mode']}")
        click.echo(f"  Status:   {run_info['status']}")
    else:
        click.echo("No exec-run-id provided. Reconciling current account state only.")

    try:
        cfg = ClientConfig(mode=ExecMode.DEMO)
        client = BybitClient(cfg)
        positions_raw = client.get_positions()
        wallet_raw = client.get_wallet_balance()
        client.close()
    except Exception as exc:
        click.echo(f"Failed to fetch account state: {exc}", err=True)
        conn.close()
        sys.exit(1)

    actual = compute_account_state(positions_raw, wallet_raw)
    click.echo("\nCurrent account state:")
    click.echo(f"  Total equity:   {actual.total_equity:.4f}")
    click.echo(f"  Wallet balance: {actual.wallet_balance:.4f}")
    click.echo(f"  Unrealized PnL: {actual.unrealized_pnl:.4f}")
    for sym, pos in actual.positions.items():
        click.echo(f"  Position {sym}: {pos.size:.6f} @ {pos.avg_price:.4f}")
    conn.close()


@cli.command()
@click.argument("tag")
@click.option("--dry-run", is_flag=True, help="Validate without checking out")
def rollback(tag: str, dry_run: bool) -> None:
    """Roll back to a previously released tag."""
    import subprocess

    click.echo(f"Rollback requested: {tag}")

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/tags/{tag}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            click.echo(f"Error: tag {tag} not found.", err=True)
            sys.exit(1)

        target_sha = result.stdout.strip()
        click.echo(f"  Tag {tag} resolves to {target_sha[:12]}")

        if dry_run:
            click.echo("  (dry-run — no checkout performed)")
            return

        subprocess.run(
            ["git", "checkout", f"tags/{tag}"],
            check=True,
            timeout=30,
        )
        click.echo(f"  Checked out {tag}. Restart ztb run to use this version.")
    except subprocess.TimeoutExpired:
        click.echo("Error: git operation timed out.", err=True)
        sys.exit(1)
    except subprocess.CalledProcessError:
        click.echo(f"Error: failed to check out {tag}.", err=True)
        sys.exit(1)


@cli.command()
@click.option("--run-id", default=None, help="Specific run ID to report")
@click.option("--db", default=None, help="Path to result database")
@click.option("--limit", default=10, type=int, help="Number of recent runs to show")
@click.option("--scorecard", is_flag=True, help="Show scorecard for the run")
def report(
    run_id: str | None,
    db: str | None,
    limit: int,
    scorecard: bool,
) -> None:
    """Show backtest results from the store."""
    conn = connect(db)

    if run_id:
        run_info = get_run(conn, run_id)
        if run_info is None:
            click.echo(f"Run not found: {run_id}", err=True)
            sys.exit(1)

        sn = run_info["strategy_name"]
        click.echo(f"Run: {sn} / {run_info['symbol']} [{run_info['timeframe']}]")
        click.echo(f"Run ID: {run_info['run_id']}")
        click.echo(f"Created: {run_info['created_at']}")
        click.echo(f"Parameters: {run_info['parameters']}")
        click.echo()

        metrics = get_metrics(conn, run_id)
        header = (
            f"  {'Scope':12s} {'Return':>10s} {'Sharpe':>10s} "
            f"{'MaxDD':>10s} {'Trades':>8s} {'Win%':>8s} {'PF':>8s}"
        )
        click.echo(header)
        click.echo(f"  {'-' * 66}")
        for m in metrics:
            suff = "✓" if m["sufficient_sample"] else "✗"
            ret = f"{m['total_return']:.4f}" if m["total_return"] is not None else "N/A"
            shr = f"{m['sharpe']:.3f}" if m["sharpe"] is not None else "N/A"
            dd = f"{m['max_drawdown']:.4f}" if m["max_drawdown"] is not None else "N/A"
            wr = f"{m['win_rate']:.3f}" if m["win_rate"] is not None else "N/A"
            pf = f"{m['profit_factor']:.3f}" if m["profit_factor"] is not None else "N/A"
            click.echo(
                f"  {m['scope'].upper():12s} {ret:>10s} {shr:>10s} "
                f"{dd:>10s} {str(m['num_trades']):>8s} {wr:>8s} {pf:>8s}  {suff}"
            )

        if scorecard:
            trades = get_trades(conn, run_id)
            equity = get_equity_curve(conn, run_id)
            sc = build_scorecard(run_info, metrics, trades, equity)
            click.echo(f"\nScorecard: sufficient_sample={sc.get('sufficient_sample')}")
            for scope_name, m in sc.get("metrics", {}).items():
                click.echo(
                    f"  {scope_name}: Sharpe={m.get('sharpe', 'N/A')} "
                    f"DD={m.get('max_drawdown', 'N/A')} "
                    f"Trades={m.get('num_trades', 0)}"
                )
    else:
        runs = list_runs(conn)
        if not runs:
            click.echo("No runs found. Run `ztb backtest --persist` first.")
            sys.exit(1)

        click.echo(f"Recent runs (last {limit}):")
        click.echo()
        for r in runs:
            rtype = r.get("run_type", "backtest")
            click.echo(
                f"  {r['run_id'][:12]}  {r['strategy_name']:12s} {r['symbol']:10s} "
                f"{r['timeframe']:6s} {rtype:9s} {r['created_at']}"
            )

    conn.close()


@cli.command()
@click.option("--db", default=None, help="Path to result database")
def dashboard(db: str | None) -> None:
    """Launch the Streamlit dashboard app."""
    import subprocess
    import sys

    db_arg = f"--db={db}" if db else ""
    app_path = str(__import__("ztb.dashboard.app", fromlist=[""]).__file__)

    cmd = ["streamlit", "run", app_path]
    if db:
        cmd.extend(["--", db_arg])

    click.echo("Launching ztb dashboard...")
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        click.echo(
            "Streamlit not found. Install it with: pip install streamlit",
            err=True,
        )
        sys.exit(1)
    except subprocess.CalledProcessError:
        click.echo("Dashboard exited with an error.", err=True)
        sys.exit(1)


@cli.command(name="list")
@click.option("--verbose", is_flag=True, help="Show detailed strategy info")
def _list(verbose: bool) -> None:
    """List available strategies."""
    try:
        names = list_names()
    except Exception as exc:
        click.echo(f"Error listing strategies: {exc}", err=True)
        sys.exit(1)

    if not names:
        click.echo("No strategies found.")
        return

    click.echo("Available strategies:")
    for name in names:
        if verbose:
            cls = get_strategy(name)
            inst = cls()
            click.echo(f"  {name}")
            click.echo(f"    params:    {inst.params}")
            click.echo(f"    timeframe: {inst.timeframe}")
            click.echo(f"    warmup:    {inst.warmup}")
        else:
            click.echo(f"  {name}")


@cli.command(name="smoke-test")
@click.option("--symbol", default="BTCUSDT", help="Trading pair")
@click.option("--qty", default=0.001, type=float, help="Quantity to trade")
@click.option("--category", default="linear", help="Market category")
@click.option("--db", default=None, help="Path to results.db (default: ZTB_STORE_PATH)")
@click.option("--timeout", default=30, type=int, help="Seconds to wait for fills")
@click.option("--poll-interval", default=2.0, type=float, help="Seconds between poll retries")
def smoke_test(
    symbol: str,
    qty: float,
    category: str,
    db: str | None,
    timeout: int,
    poll_interval: float,
) -> None:
    """Place ONE real demo MARKET BUY order and assert exec_fills row exists.

    End-to-end smoke test that validates the full execution pipeline:
    BybitClient auth, order placement, fill retrieval, and store persistence.
    Asserts: real fee > 0, correct price scale, code_version stamped,
    FK consistency between order and fills. DEMO mode only.
    """
    import os
    import time as _time
    from datetime import UTC, datetime
    from pathlib import Path
    from typing import Any

    from ztb.execution.bybit_client import BybitClient, ClientConfig
    from ztb.execution.models import Mode, OrderSide, OrderType
    from ztb.store.exec_io import (
        create_exec_run,
        ensure_exec_tables,
        get_exec_fills,
        save_exec_fill,
        save_exec_order,
    )
    from ztb.store.results import connect as db_connect

    click.echo(f"ztb smoke-test: {symbol} MARKET BUY via Bybit DEMO")

    api_key = os.environ.get("ZTB_BYBIT_API_KEY", "")
    api_secret = os.environ.get("ZTB_BYBIT_API_SECRET", "")
    if not api_key or not api_secret:
        click.echo("Error: ZTB_BYBIT_API_KEY and ZTB_BYBIT_API_SECRET must be set", err=True)
        sys.exit(1)

    cfg = ClientConfig(api_key=api_key, api_secret=api_secret, mode=Mode.DEMO)
    client = BybitClient(cfg)

    default_path = os.environ.get("ZTB_STORE_PATH", str(Path.home() / ".ztb" / "results.db"))
    db_path: str = db or default_path
    store_dir = os.path.dirname(db_path)
    if store_dir:
        os.makedirs(store_dir, exist_ok=True)

    conn = db_connect(db_path)
    try:
        ensure_exec_tables(conn)
        click.echo(f"  DB:     {db_path}")

        info = client.get_instrument_info(symbol, category)
        ls = info.get("lotSizeFilter", {})
        qty_step = float(ls.get("qtyStep", "0.001"))
        min_qty = float(ls.get("minOrderQty", "0.001"))
        qty = max(qty, min_qty)
        qty = BybitClient.round_to_step(qty, qty_step)
        click.echo(f"  Qty:    {qty} (step={qty_step}, min={min_qty})")

        run_id = f"smoke-{int(_time.time() * 1000)}"
        order_link_id = f"smoke-{run_id}-{int(_time.time() * 1000)}"

        order_result = client.place_order(
            symbol=symbol,
            side=OrderSide.BUY,
            qty=qty,
            order_type=OrderType.MARKET,
            order_link_id=order_link_id,
            category=category,
        )

        if order_result.get("skipped"):
            click.echo(f"  Order skipped: {order_result.get('reason', 'unknown')}", err=True)
            sys.exit(1)

        order_id = order_result.get("orderId", "")
        click.echo(f"  Order:  {order_id}")
        click.echo(f"  LinkID: {order_link_id}")

        deadline = _time.time() + timeout
        fills_raw: list[dict[str, Any]] = []
        while _time.time() < deadline:
            fills_raw = client.get_executions(symbol=symbol, category=category, order_id=order_id)
            if fills_raw:
                break
            remaining = max(0, int(deadline - _time.time()))
            click.echo(f"  Poll: {len(fills_raw)} fills, {remaining}s remaining...")
            _time.sleep(poll_interval)

        click.echo(f"  Fills:  {len(fills_raw)} raw execution(s)")

        exec_run_id = f"st-{int(_time.time() * 1000)}"
        now_str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        create_exec_run(
            conn,
            exec_run_id=exec_run_id,
            run_id=run_id,
            strategy_name="smoke_test",
            symbol=symbol,
            timeframe="1m",
            mode="demo",
            started_at=now_str,
        )

        order_dict = {
            "order_link_id": order_link_id,
            "exec_run_id": exec_run_id,
            "order_id": order_id,
            "symbol": symbol,
            "side": "Buy",
            "order_type": "Market",
            "price": float(order_result.get("price", 0)),
            "qty": qty,
            "status": "Filled",
            "created_at": now_str,
            "cum_exec_qty": qty,
            "cum_exec_value": float(order_result.get("cumExecValue", 0)),
            "cum_exec_fee": float(order_result.get("cumExecFee", 0)),
            "sufficient_sample": 1,
            "code_version": __version__,
        }
        save_exec_order(conn, order_dict)

        for fill_raw in fills_raw:
            exec_price = float(fill_raw.get("execPrice", 0))
            exec_qty = float(fill_raw.get("execQty", 0))
            commission = float(fill_raw.get("execFee", 0))
            fill_dict = {
                "fill_id": fill_raw.get("execId", f"fill-{order_id}-{int(_time.time() * 1000)}"),
                "order_link_id": order_link_id,
                "exec_run_id": exec_run_id,
                "order_id": order_id,
                "symbol": symbol,
                "side": "Buy",
                "price": exec_price,
                "qty": exec_qty,
                "commission": commission,
                "realized_pnl": float(fill_raw.get("realizedPnl", 0)),
                "filled_at": fill_raw.get("execTime", now_str),
                "sufficient_sample": 1,
                "code_version": __version__,
            }
            save_exec_fill(conn, fill_dict)

        stored_fills = get_exec_fills(conn, exec_run_id)
        click.echo(f"  Stored: {len(stored_fills)} fill(s) in exec_fills")

        errors: list[str] = []
        if len(stored_fills) == 0:
            errors.append("no exec_fills row found after order placement")

        for f in stored_fills:
            if f.get("order_link_id") != order_link_id:
                fid = f["fill_id"]
                errors.append(f"FK mismatch fill={fid}: link={f.get('order_link_id')}")
            if f.get("commission", 0) <= 0:
                errors.append(f"zero commission fill={f['fill_id']}: {f.get('commission')}")
            if f.get("price", 0) <= 0:
                errors.append(f"zero price fill={f['fill_id']}: {f.get('price')}")
            if f.get("code_version") != __version__:
                cv = f.get("code_version")
                errors.append(f"code_ver mismatch fill={f['fill_id']}: {cv} != {__version__}")

        if errors:
            for e in errors:
                click.echo(f"  FAIL: {e}", err=True)
            sys.exit(1)

        click.echo("")
        click.echo("SMOKE TEST PASSED")
        click.echo(f"  exec_run_id: {exec_run_id}")
        click.echo(f"  fills:       {len(stored_fills)}")
        for f in stored_fills:
            click.echo(
                f"    fill {str(f['fill_id'])[:20]}  "
                f"qty={f['qty']:.6f} price={f['price']:.1f} "
                f"fee={f['commission']:.8f} ver={f['code_version']}"
            )

    except Exception as exc:
        click.echo(f"Smoke test error: {exc}", err=True)
        sys.exit(1)
    finally:
        conn.close()
        client.close()


def main() -> None:
    sys.exit(cli(auto_envvar_prefix="ZTB"))


if __name__ == "__main__":
    main()
