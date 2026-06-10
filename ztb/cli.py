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
    )

    result = run_backtest(strategy, df, cfg)

    def _fmt(v: float | None, decimals: int = 4) -> str:
        if v is None:
            return "N/A"
        return f"{v:.{decimals}f}"

    click.echo(f"\n{'=' * 60}")
    click.echo(f"Backtest: {strategy_name} on {symbol} [{timeframe}]")
    click.echo(f"{'=' * 60}")
    click.echo(
        f"  {'Scope':12s} {'Return':>10s} {'Sharpe':>10s} "
        f"{'MaxDD':>10s} {'Trades':>8s} {'Win%':>8s}"
    )
    click.echo(f"  {'-' * 58}")
    for label, m in [("FULL", result.full), ("IS", result.is_), ("OOS", result.oos)]:
        credible = "✓" if m.credible else "✗"
        click.echo(
            f"  {label:12s} {_fmt(m.total_return, 4):>10s} "
            f"{_fmt(m.sharpe, 3):>10s} {_fmt(m.max_drawdown, 4):>10s} "
            f"{str(m.num_trades):>8s} {_fmt(m.win_rate, 3):>8s}  {credible}"
        )
    if not result.full.credible:
        click.echo(f"\n  Not credible: {result.full.reason}")
    if not result.oos.credible:
        click.echo(f"\n  OOS not credible: {result.oos.reason}")
    click.echo(f"{'=' * 60}\n")


@cli.command()
def forwardtest() -> None:
    click.echo("forwardtest: not yet implemented")


@cli.command()
def validate() -> None:
    click.echo("validate: not yet implemented")


@cli.command()
def run() -> None:
    click.echo("run: not yet implemented")


@cli.command()
def report() -> None:
    click.echo("report: not yet implemented")


@cli.command()
def dashboard() -> None:
    click.echo("dashboard: not yet implemented")


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
