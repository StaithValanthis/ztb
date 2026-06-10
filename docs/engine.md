# ztb Engine Documentation

## Overview

The ztb engine is a deterministic, cost-realistic Python backtesting core for Bybit markets. It processes historical OHLCV data through a strategy plugin and produces net-of-cost performance metrics across in-sample (IS) and out-of-sample (OOS) periods.

## Architecture

### Signal Timing / No-Lookahead Convention

The engine — not the strategy — owns the 1-bar signal shift:

```
Bar t close → strategy.generate_signals() → target[t] → engine shift → position[t+1]
```

- A target computed from bar *t*'s close executes at bar *t+1*.
- **Strategies must never shift** their output. Any `shift()` call in a strategy plugin is forbidden.
- The warmup period (first `strategy.warmup` bars) is enforced flat by the engine. Strategies must emit `0` during warmup or raise `StrategyError`.

### Cost Model

Cost at bar *t* = `(commission + slippage) × |pos_t − pos_{t-1}|`

- Turnover-based: charged on every unit of position change (open, flip, close).
- Short flips (`+1 → −1`) are charged on the full 2-unit turnover.
- All reported metrics are **net of costs**.
- Default rates: 0.05% commission, 0.05% slippage.

#### Commission
Charged as `abs(delta) × price × commission_rate` on each trade.

#### Slippage
Charged as `abs(delta) × price × slippage_rate` on each trade.

### IS/OOS Split

Chronological split at fraction `config.is_fraction` (default 0.7). The first 70% of bars are IS, the remaining 30% are OOS. If the split point would result in fewer than `min_bars` IS bars, a 50/50 split is used instead.

Full, IS, and OOS metrics are all reported independently.

### Credible-Sample Guard

A backtest result is marked `credible=False` with a reason when:
- Number of trades on the evaluated segment is below `min_trades` (default 30).
- Fewer than 2 equity curve points exist.
- Returns cannot be computed.

The engine returns real numbers or marks results as non-credible — it never fabricates metrics.

## Modules

### `engine/backtest.py`

Entry point: `run_backtest(strategy, data, config?) → BacktestResult`

Validates signal contract (length, index, warmup, NaN, range), applies the 1-bar shift, runs the portfolio simulation, and computes metrics for full/IS/OOS segments.

### `engine/metrics.py`

Computes performance metrics from an equity curve and trade list. All metrics are net of costs (`pnl` field includes costs).

- **total_return**: `equity[-1] / equity[0] - 1`
- **sharpe**: `mean(returns) / std(returns) × √(periods_per_year)`. Zero when std=0.
- **sortino**: `mean(returns) / std(downside_returns) × √(periods_per_year)`. Zero when downside_std=0.
- **max_drawdown**: Maximum peak-to-trough decline as a fraction.
- **max_drawdown_duration**: Longest consecutive periods in drawdown.
- **num_trades**: Total trade events.
- **profit_factor**: Gross profit / gross loss.
- **win_rate**: Winning trades / total trades.
- **turnover**: Sum of absolute trade sizes.
- **exposure_time**: Number of return periods.

### `engine/portfolio.py`

Single-symbol portfolio simulation. Tracks cash, position, equity curve, and per-trade realized PnL (net of costs). Supports entry, exit, and flip (long↔short) trades.

Periods per year:
| Timeframe | PPY |
|-----------|-----|
| 1m | 365×24×60 = 525,600 |
| 5m | 365×24×12 = 105,120 |
| 15m | 365×24×4 = 35,040 |
| 1h | 365×24 = 8,760 |
| 1d | 365 |
| 1w | 52 |
| 1M | 12 |

## `strategies/` — Plugin Framework

### `Strategy` ABC

```python
class Strategy(ABC):
    name: str
    symbols: list[str]
    timeframe: str
    params: dict[str, float | int | str]
    warmup: int

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        ...
```

Contract:
- Returns target position in **[-1, 1]**: -1 = fully short, 0 = flat, +1 = fully long.
- Warmup-flat: must emit `0` across warmup window.
- No-NaN: returned series contains no NaN values.
- **Engine owns the shift** — strategies never shift.

### Registry

Auto-discovers Strategy subclasses via `pkgutil`. Provides:
- `get(name) → type[Strategy]` — raises `KeyError` on unknown name.
- `all() → list[type[Strategy]]` — all discovered classes.
- `list_names() → list[str]` — sorted names.
- Duplicate names raise `ValueError`.

## `features/` — Indicator Library

Pure vectorized indicators. No-lookahead: results for a sub-range depend only on data up to that point (proven by truncate-at-k invariance tests).

| Function | Description |
|----------|-------------|
| `sma(series, period)` | Simple moving average |
| `ema(series, period)` | Exponential moving average |
| `rsi(series, period=14)` | Relative Strength Index |
| `atr(high, low, close, period=14)` | Average True Range |
| `crossover(s1, s2)` | Crossover detection (1 when s1 crosses below s2) |

## CLI Usage

```bash
# List available strategies
ztb list
ztb list --verbose

# Run backtest
ztb backtest sma_cross BTCUSDT --timeframe 60 --cash 100000 --commission 0.0005 --slippage 0.0005
```

## Determinism

Identical inputs (same data, same strategy, same config) produce byte-identical `BacktestResult` outputs. Cached data is cold==warm.
