from __future__ import annotations

import sys

import click

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
            credible=bool(full_metrics["credible"]),
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
def validate() -> None:
    click.echo("validate: not yet implemented")


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
@click.option("--no-risk", is_flag=True, help="Disable risk management (default: ON)")
@click.option("--asset-precision", default=8, type=int, help="Decimal places for qty rounding")
@click.option("--db", default=None, help="Path to result database")
@click.option("--preflight", is_flag=True, help="Run preflight checks before execution")
@click.option("--expected-tag", default=None, help="Expected git tag for pinning")
@click.option("--expected-version", default=None, help="Expected installed version")
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
    no_risk: bool,
    asset_precision: int,
    db: str | None,
    preflight: bool,
    expected_tag: str | None,
    expected_version: str | None,
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
        initial_cash=cash,
        risk_enabled=not no_risk,
        asset_precision=asset_precision,
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
            cred = "✓" if m["credible"] else "✗"
            ret = f"{m['total_return']:.4f}" if m["total_return"] is not None else "N/A"
            shr = f"{m['sharpe']:.3f}" if m["sharpe"] is not None else "N/A"
            dd = f"{m['max_drawdown']:.4f}" if m["max_drawdown"] is not None else "N/A"
            wr = f"{m['win_rate']:.3f}" if m["win_rate"] is not None else "N/A"
            pf = f"{m['profit_factor']:.3f}" if m["profit_factor"] is not None else "N/A"
            click.echo(
                f"  {m['scope'].upper():12s} {ret:>10s} {shr:>10s} "
                f"{dd:>10s} {str(m['num_trades']):>8s} {wr:>8s} {pf:>8s}  {cred}"
            )

        if scorecard:
            trades = get_trades(conn, run_id)
            equity = get_equity_curve(conn, run_id)
            sc = build_scorecard(run_info, metrics, trades, equity)
            click.echo(f"\nScorecard: credible={sc.get('credible')}")
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


def main() -> None:
    sys.exit(cli(auto_envvar_prefix="ZTB"))


if __name__ == "__main__":
    main()
