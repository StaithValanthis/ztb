# Frozen Contract: `flag_floor_bounce_long` strategy plugin

**Issue:** ZTB-3893
**Parent:** ZTB-3872
**SPEC:** `memory/skills/spec-flag-floor-bounce-long.md`
**V&R co-sign:** PASS — ZTB-3886 (SPEC co-sign). Build authorized.
**Build owner:** Strategy Engineer
**Branch:** `strat/flag_floor_bounce_long`
**Worktree:** `~/ztb-wt/strat/flag_floor_bounce_long`

---

## 1. Scope — plugin only, no engine edits

One new file: `ztb/strategies/flag_floor_bounce_long.py`. NO changes to:
- `ztb/engine/`, `ztb/execution/`, `ztb/data/`, `ztb/store/`, `ztb/risk/`
- `ztb/strategies/base.py` (ABC unchanged)
- `ztb/strategies/registry.py`
- `ztb/strategies/__init__.py`
- `ztb/features/indicators.py`
- `pyproject.toml`, `.github/`, CI config
- Any test outside `tests/test_flag_floor_bounce_long.py`

---

## 2. Strategy interface (Strategy ABC contract)

| Field | Value |
|-------|-------|
| `name` | `"flag_floor_bounce_long"` |
| `symbols` | `["BTCUSDT"]` |
| `timeframe` | `"60"` |
| `warmup` | `200` |
| `params` | See parameter table below |
| `risk_profile` | `RiskProfile()` — no SL/TP managed by strategy (falls through to ExecRunConfig). Exits handled in signal logic. |
| `generate_signals` | Returns `pd.Series` in {0, +1} (long-only; -1 never fires), index-matched to input `df`; warmup bars flat at 0.0; no NaN |

### Parameter table

| param | type | default | range | purpose |
|-------|------|---------|-------|---------|
| `flag_floor_level` | float | 63644.0 | Dynamic | Flag floor support level, set at deploy time |
| `flag_floor_lower_pct` | float | 0.98 | [0.97, 0.995] | Lower boundary of floor zone as fraction of flag floor |
| `flag_floor_upper_pct` | float | 1.02 | [1.005, 1.03] | Upper boundary of floor zone as fraction of flag floor |
| `flag_ceiling_level` | float | 67276.0 | Dynamic | Profit ceiling level, set at deploy time |
| `rsi_period` | int | 14 | [7, 21] | RSI lookback period |
| `rsi_oversold_threshold` | float | 30.0 | [20, 40] | RSI(14) level considered oversold at support |
| `vol_sma_period` | int | 20 | [10, 50] | Volume SMA period for confirmation |
| `vol_confirmation_mult` | float | 1.5 | [1.2, 2.5] | Min volume spike multiple vs SMA(20) |
| `bullish_body_ratio` | float | 0.6 | [0.5, 0.8] | Min fraction of bar range in upper half (rejection body) |
| `atr_period` | int | 14 | [7, 28] | ATR lookback for exits |
| `target_atr_mult` | float | 3.0 | [2.0, 5.0] | Profit target in 1h ATR multiples |
| `trail_atr_mult` | float | 1.5 | [1.0, 2.5] | Trailing stop in 1h ATR multiples |
| `stop_atr_mult` | float | 2.0 | [1.5, 3.0] | Hard stop below entry in 1h ATR multiples |
| `max_hold_bars` | int | 24 | [12, 48] | Max 1h bars to hold (24 bars = 24h) |

---

## 3. Signal logic

### 3.1 No look-ahead

The engine owns the 1-bar shift (`signal.shift(1)` inside `_step_impl`). The strategy operates on ALL bars and must NOT shift, peek at `df.iloc[i+1]`, reference `df["close"].shift(-1)`, or use any future bar. All indicators compute on full columns (vectorized), but signals are only emitted for bars where all data is available (`warmup` ensures indicator windows are stable).

### 3.2 Required data columns

The strategy reads: `open`, `high`, `low`, `close`, `volume`. Single timeframe (1h).

### 3.3 Precondition — Flag floor proximity

`close >= flag_floor_lower_pct * flag_floor_level AND close <= flag_floor_upper_pct * flag_floor_level`

The flag floor level is a **parameter**, not computed dynamically. This avoids lookahead (no peak/trough detection on future data). The level must be set at deploy time based on confirmed structural support.

### 3.4 Entry LONG (+1)

ALL of the following must be true:
1. Precondition — price is in the flag floor zone
2. `RSI(rsi_period) < rsi_oversold_threshold` — market is locally oversold at support
3. `volume > vol_confirmation_mult * SMA(volume, vol_sma_period)` — current bar has above-average volume
4. `(close - low) / (high - low) >= bullish_body_ratio` — bullish rejection body (buying pressure at support)
5. `low < low_of_previous_bar` — new local low was tested (final flush before bounce)

### 3.5 Exit logic (embedded in signal, state-machine loop)

The strategy tracks position state within `generate_signals` using a row-by-row loop (same pattern as `ztb/strategies/vol_expansion_60m.py`). The signal flattens to 0 when ANY exit condition is met:

- **Profit target (take profit):** `high >= entry_price + target_atr_mult * ATR(atr_period)`
- **Trailing stop:** Track `highest_since_entry`. When `low <= highest_since_entry - trail_atr_mult * ATR(atr_period)`, flatten.
- **Hard stop:** `low < entry_price - stop_atr_mult * ATR(atr_period)`
- **Time stop:** If bars since entry >= `max_hold_bars`, flatten.
- **Flag ceiling:** `close > flag_ceiling_level` — full bounce captured.

### 3.6 No NaN

`generate_signals` must return a value in {0, +1} for EVERY bar (including warmup). Use `.fillna(0.0)` on the final signal series. The backtest engine enforces this and will fail on NaN.

### 3.7 Warmup

Bars `0:warmup` MUST be 0.0. The warmup of 200 ensures all indicator windows (RSI(14), SMA(20), ATR(14)) are stable before any signal.

### 3.8 Cost assumption (unchanged from SPEC)

| Assumption | Value |
|------------|-------|
| Taker fee | 0.055% |
| Slippage (each side) | 1.5 bps |
| Cost model | per-trade, both sides |

---

## 4. Required indicators (from `ztb.features.indicators`)

- `sma(series, period)` — for volume SMA
- `rsi(series, period)` — for RSI oversold detection
- `atr(high, low, close, period)` — for ATR-based exits

All indicators exist in `ztb.features.indicators`.

---

## 5. Required pytest cases

Write in `tests/test_flag_floor_bounce_long.py`. All tests must use the `flag_floor_bounce_long` strategy from the registry OR instantiate directly.

| ID | Test | What it asserts |
|----|------|-----------------|
| FB-1 | `test_registered` | `get("flag_floor_bounce_long")` returns the class; `name`, `symbols`, `timeframe`, `warmup`, `params` match contract |
| FB-2 | `test_warmup_flat` | Bars `0:warmup` (200) are all 0.0 on trending data |
| FB-3 | `test_no_nan` | Full signal series on 500+ bars contains no NaN |
| FB-4 | `test_signal_range` | All non-warmup signals are in {0, +1}; no signal < 0 |
| FB-5 | `test_entry_at_flag_floor` | When price is at flag floor zone with RSI oversold + volume spike + bullish body + new low, signal goes +1 |
| FB-6 | `test_no_entry_outside_floor_zone` | No entry when price is outside the flag floor zone (above upper boundary) |
| FB-7 | `test_no_entry_without_oversold_rsi` | No entry when RSI is above oversold threshold |
| FB-8 | `test_no_entry_without_volume_surge` | No entry when volume is below confirmation threshold |
| FB-9 | `test_no_entry_without_bullish_body` | No entry when bar has weak bullish body (< threshold) |
| FB-10 | `test_no_entry_without_new_low` | No entry when low >= previous bar low |
| FB-11 | `test_profit_target_exit` | When price reaches `target_atr_mult * ATR`, signal flattens to 0 |
| FB-12 | `test_hard_stop_exit` | When price breaches `stop_atr_mult * ATR` below entry, signal flattens to 0 |
| FB-13 | `test_time_stop_exit` | After `max_hold_bars` bars, signal flattens to 0 |
| FB-14 | `test_flag_ceiling_exit` | When close exceeds `flag_ceiling_level`, signal flattens to 0 |
| FB-15 | `test_trailing_stop_exit` | When price retraces `trail_atr_mult * ATR` from highest high, signal flattens to 0 |
| FB-16 | `test_backtest_returns_result` | `run_backtest("flag_floor_bounce_long", df)` returns `BacktestResult` with no errors |
| FB-17 | `test_walkforward_runs` | `run_walk_forward` runs without error on synthetic data with flag-like structure |

---

## 6. Acceptance criteria (from SPEC, carried forward)

| # | Criterion | Threshold | Notes |
|---|-----------|-----------|-------|
| 1 | IS Sharpe (cost-aware) | >= 0.8 | Long-only counter-trend, taker + slippage |
| 2 | IS max DD | <= 20% | Tight stop + trailing stop contain adverse moves |
| 3 | IS win rate | >= 40% | Per-trade, cost-inclusive |
| 4 | OOS Sharpe (cost-aware) | >= 0.5 | 50/50 time split, same costs |
| 5 | OOS vs IS Sharpe decay | <= 50% | |
| 6 | RSI + volume + body-ratio gates are additive | Sharpe with gates > without | Compare vs unfiltered floor-touch-only variant (no RSI, volume, or body-shape requirements); >= 0.2 Sharpe improvement |
| 7 | No lookahead | Post-warmup only | Engine-enforced |
| 8 | No NaN on full OOS span | Every bar in {-1, 0} | Engine-enforced |
| 9 | Min trades (IS + OOS) | >= 40 | Flag floor touches in 6y BTC data |

**Walk-forward requirement:** >= 3 of 4 windows meet ALL per-window thresholds (OOS Sharpe >= 0.5, OOS DSR >= 0.95, min 40 trades per window).

**Historical level assignment:** Each walk-forward window must use that window's known structural support level (e.g., $3K in 2019, $16K in 2022, $64K in 2026). This is context-aware parameterization, not optimization. The `flag_floor_level` parameter must be documented per window in the test or a data note.

---

## 7. Builder self-audit checklist (mandatory before hand-up)

- [ ] **Test assertions match contract** — every assert cross-checked against this frozen contract
- [ ] **Only in-scope files changed** — only `ztb/strategies/flag_floor_bounce_long.py` + `tests/test_flag_floor_bounce_long.py`
- [ ] **Branch is based on current `main`** — `git fetch origin main && git rebase origin/main`, no conflicts
- [ ] **CI is green from worktree** — `pytest tests/test_flag_floor_bounce_long.py -q` passes; full `pytest tests/ -q` also green; `ruff check .`; `ruff format --check .`; `mypy ztb/` clean
- [ ] **No look-ahead** — signal operates on data known at each bar; no `iloc[i+1]`, no `shift(-1)`, no future close
- [ ] **Equity invariant** — equity = `initial_cash + realized_pnl + unrealized_pnl` (verified via backtest engine)
- [ ] **Fees + slippage applied** — backtest uses cost-aware `run_backtest` (default commission/slippage)
- [ ] **Executor uses shared accounting** — not applicable (plugin only, no executor edits)
- [ ] **Conventional commits** — commit messages follow `type(scope): description [ZTB-3893]`
- [ ] **All work committed + pushed** — branch fully pushed to remote
- [ ] **`__version__` unchanged** — plugin-only, no version bump needed. Merging does not change the trading code path, so no version bump or real-fill cert required.
