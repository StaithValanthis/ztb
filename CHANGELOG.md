# Changelog

## v0.3.0 (2026-06-10)

- M2 engine core: `features/indicators.py` (SMA, EMA, RSI, ATR, crossover)
- Plugin framework: `strategies/base.py` (Strategy ABC), `strategies/registry.py` (auto-discovery)
- Reference strategy: `strategies/sma_cross.py` (long-or-flat SMA crossover)
- Engine: `engine/backtest.py` (cost model, IS/OOS split, credible-sample guard)
- Metrics: `engine/metrics.py` (net Sharpe/Sortino/maxDD/trades/PF/winrate/turnover)
- Portfolio: `engine/portfolio.py` (minimal single-symbol passthrough)
- CLI: `ztb list`, `ztb backtest <strategy> <symbol>`
- **Tests:** 213/213 pass, 94% coverage, no-lookahead proven (T-B2), cost exactness (T-B1/T-B3), short flips proven
- **Documentation:** `docs/engine.md` (cost model, signal-timing, metric formulas)
- **Measured evidence (sma_cross, 5000 bars, synthetic):** 316 trades, full return 0.0004 / Sharpe 0.950, IS return 0.0006 / Sharpe 2.041, OOS return -0.0002 / Sharpe -1.578, MaxDD -0.0007, WinRate 18.0%, ProfitFactor 1.152
- **PR:** [#4](https://github.com/StaithValanthis/ztb/pull/4)
- **Merge commit:** `be3b888` — two-key merge (CI green + V&R PASS on SHA `f2b9d60`)
- **Tag:** v0.3.0

## v0.2.0 (2026-06-09)

- M1 data layer: ztb/data/ module (errors, schema, timeframes, rate_limit, bybit_rest, pagination, fetch, cache, integrity, loader)
- CLI: ztb data fetch|show|verify|instruments
- Dependencies: httpx, pandas, pyarrow
- **Tests:** all green, ≥90% coverage, cold==warm determinism proven, delta-fetch spy-proven
- **Merge commit:** 651d284 — two-key merge (CI green + V&R PASS on SHA 1a8250b)
- **Tag:** v0.2.0

## v0.1.1 (2026-06-09)

- CI fix: exclude `@pytest.mark.network` from default test run (unblocks M1 data layer testing)
- **PR:** [#3](https://github.com/StaithValanthis/ztb/pull/3)
- **Merge commit:** `02035ac` — admin-merge (MD-authorized, V&R PASS on SHA `e51f8b9`)

## v0.1.0 (2026-06-09)

- M0 scaffold: typed package skeleton, frozen Config, CLI dispatcher, pyproject.toml + pre-commit + CI
- **Tests:** 20/20 pass, 98% coverage
- **Merge commit:** 9cd35d5 — two-key merge (CI green + V&R PASS on SHA a709d6c)
