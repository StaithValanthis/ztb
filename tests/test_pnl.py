from __future__ import annotations

import pytest

from ztb.engine.pnl import PnLCalculator, PnLSnapshot
from ztb.engine.portfolio import single_symbol_portfolio

# ---------------------------------------------------------------------------
# PnLSnapshot
# ---------------------------------------------------------------------------


def test_pnl_snapshot_dataclass_fields() -> None:
    snap = PnLSnapshot(
        position=1.0,
        avg_entry_price=50000.0,
        realized_pnl=1000.0,
        total_commission=25.0,
        total_slippage=25.0,
        initial_cash=100_000.0,
    )
    assert snap.position == 1.0
    assert snap.avg_entry_price == 50000.0
    assert snap.realized_pnl == 1000.0
    assert snap.total_commission == 25.0
    assert snap.total_slippage == 25.0
    assert snap.initial_cash == 100_000.0


# ---------------------------------------------------------------------------
# PnLCalculator — position tracking (I1)
# I1: pnl.position == sum(delta)
# ---------------------------------------------------------------------------


def test_invariant_1_position_is_sum_of_deltas() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(1.0, 100.0)
    pnl.apply_fill(0.5, 101.0)
    pnl.apply_fill(-0.3, 102.0)
    assert pnl.position == pytest.approx(1.2)


def test_position_starts_zero() -> None:
    pnl = PnLCalculator()
    assert pnl.position == 0.0


def test_buy_one_unit() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(1.0, 100.0)
    assert pnl.position == 1.0
    assert pnl.avg_entry_price == 100.0


def test_sell_one_unit_no_position() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(-1.0, 100.0)
    assert pnl.position == -1.0
    assert pnl.avg_entry_price == 100.0


# ---------------------------------------------------------------------------
# PnLCalculator — avg_entry_price
# ---------------------------------------------------------------------------


def test_avg_entry_price_add_to_long() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(1.0, 100.0)
    pnl.apply_fill(1.0, 110.0)
    expected = (100.0 * 1.0 + 110.0 * 1.0) / 2.0
    assert pnl.avg_entry_price == pytest.approx(expected)
    assert pnl.position == 2.0


def test_avg_entry_price_add_to_short() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(-1.0, 100.0)
    pnl.apply_fill(-1.0, 110.0)
    expected = (100.0 * 1.0 + 110.0 * 1.0) / 2.0
    assert pnl.avg_entry_price == pytest.approx(expected)
    assert pnl.position == -2.0


def test_avg_entry_price_partial_close_long() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(2.0, 100.0)
    pnl.apply_fill(-1.0, 110.0)
    assert pnl.avg_entry_price == pytest.approx(100.0)
    assert pnl.position == 1.0


def test_avg_entry_price_close_all_long() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(2.0, 100.0)
    pnl.apply_fill(-2.0, 110.0)
    assert pnl.avg_entry_price == 0.0
    assert pnl.position == 0.0


def test_avg_entry_price_flip_long_to_short() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(1.0, 100.0)
    pnl.apply_fill(-2.0, 110.0)
    assert pnl.avg_entry_price == pytest.approx(110.0)
    assert pnl.position == -1.0


def test_avg_entry_price_flip_short_to_long() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(-1.0, 100.0)
    pnl.apply_fill(2.0, 90.0)
    assert pnl.avg_entry_price == pytest.approx(90.0)
    assert pnl.position == 1.0


def test_avg_entry_price_zero_delta() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(1.0, 100.0)
    pnl.apply_fill(0.0, 200.0)
    assert pnl.avg_entry_price == pytest.approx(100.0)
    assert pnl.position == 1.0


def test_avg_entry_price_buy_from_zero() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(0.0, 100.0)
    assert pnl.avg_entry_price == 0.0
    assert pnl.position == 0.0


# ---------------------------------------------------------------------------
# PnLCalculator — realized_pnl (I2)
# I2: realized_pnl == sum(liquidation_pnls) - sum(costs)
# ---------------------------------------------------------------------------


def test_invariant_2_realized_pnl_includes_costs() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(2.0, 100.0, commission=5.0, slippage=3.0)
    pnl.apply_fill(-1.0, 110.0, commission=2.5, slippage=1.5)
    expected_liquidation = (110.0 - 100.0) * 1.0
    expected_costs = 5.0 + 3.0 + 2.5 + 1.5
    assert pnl.realized_pnl == pytest.approx(expected_liquidation - expected_costs)


def test_no_realized_pnl_on_entry() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(1.0, 100.0)
    assert pnl.realized_pnl == 0.0


def test_realized_pnl_long_full_close() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(1.0, 100.0)
    pnl.apply_fill(-1.0, 110.0)
    assert pnl.realized_pnl == pytest.approx(10.0)


def test_realized_pnl_long_partial_close() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(2.0, 100.0)
    pnl.apply_fill(-1.0, 110.0)
    assert pnl.realized_pnl == pytest.approx(10.0)
    assert pnl.position == 1.0


def test_realized_pnl_flip_long_to_short() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(1.0, 100.0)
    pnl.apply_fill(-2.0, 110.0)
    realized_on_close = (110.0 - 100.0) * 1.0
    assert pnl.realized_pnl == pytest.approx(realized_on_close)
    assert pnl.position == -1.0


def test_realized_pnl_short_full_close() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(-1.0, 100.0)
    pnl.apply_fill(1.0, 90.0)
    assert pnl.realized_pnl == pytest.approx(10.0)


def test_realized_pnl_short_partial_close() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(-2.0, 100.0)
    pnl.apply_fill(1.0, 90.0)
    assert pnl.realized_pnl == pytest.approx(10.0)


def test_realized_pnl_flip_short_to_long() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(-1.0, 100.0)
    pnl.apply_fill(2.0, 90.0)
    realized_on_close = (100.0 - 90.0) * 1.0
    assert pnl.realized_pnl == pytest.approx(realized_on_close)
    assert pnl.position == 1.0


def test_realized_pnl_with_commission_and_slippage() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(2.0, 100.0, commission=10.0, slippage=5.0)
    pnl.apply_fill(-2.0, 110.0, commission=10.0, slippage=5.0)
    expected = (110.0 - 100.0) * 2.0 - 10.0 - 5.0 - 10.0 - 5.0
    assert pnl.realized_pnl == pytest.approx(expected)


# ---------------------------------------------------------------------------
# PnLCalculator — unrealized_pnl (I4)
# I4: unrealized_pnl == 0 when position == 0
# ---------------------------------------------------------------------------


def test_invariant_4_zero_unrealized_when_no_position() -> None:
    pnl = PnLCalculator()
    assert pnl.unrealized_pnl(99999.0) == 0.0
    pnl.apply_fill(2.0, 100.0)
    pnl.apply_fill(-2.0, 110.0)
    assert pnl.unrealized_pnl(99999.0) == 0.0


def test_unrealized_pnl_long() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(1.0, 100.0)
    assert pnl.unrealized_pnl(110.0) == 10.0
    assert pnl.unrealized_pnl(90.0) == -10.0


def test_unrealized_pnl_short() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(-1.0, 100.0)
    assert pnl.unrealized_pnl(90.0) == 10.0
    assert pnl.unrealized_pnl(110.0) == -10.0


def test_unrealized_pnl_zero_avg_price() -> None:
    pnl = PnLCalculator()
    assert pnl.unrealized_pnl(100.0) == 0.0


# ---------------------------------------------------------------------------
# PnLCalculator — equity (I3)
# I3: equity(close) == initial_cash + realized_pnl + unrealized_pnl(close)
# ---------------------------------------------------------------------------


def test_invariant_3_equity_identity() -> None:
    pnl = PnLCalculator(initial_cash=200_000.0)
    pnl.apply_fill(1.5, 100.0, commission=3.0, slippage=1.0)
    eq = pnl.equity(110.0)
    assert eq == pytest.approx(200_000.0 + pnl.realized_pnl + pnl.unrealized_pnl(110.0))


def test_equity_starts_at_initial_cash() -> None:
    pnl = PnLCalculator(initial_cash=50_000.0)
    assert pnl.equity(100.0) == 50_000.0


# ---------------------------------------------------------------------------
# PnLCalculator — snapshot (I5, I6)
# I5: snapshot.initial_cash == initial_cash (immutable)
# I6: total_commission + total_slippage == total costs
# ---------------------------------------------------------------------------


def test_invariant_5_initial_cash_immutable() -> None:
    pnl = PnLCalculator(initial_cash=99_000.0)
    snap = pnl.snapshot
    assert snap.initial_cash == 99_000.0
    pnl.apply_fill(1.0, 100.0)
    snap2 = pnl.snapshot
    assert snap2.initial_cash == 99_000.0


def test_invariant_6_costs_equals_commission_plus_slippage() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(2.0, 100.0, commission=10.0, slippage=5.0)
    pnl.apply_fill(-1.0, 110.0, commission=5.0, slippage=2.5)
    snap = pnl.snapshot
    assert snap.total_commission == pytest.approx(15.0)
    assert snap.total_slippage == pytest.approx(7.5)
    assert snap.total_commission + snap.total_slippage == pytest.approx(22.5)


def test_snapshot_reflects_current_state() -> None:
    pnl = PnLCalculator(initial_cash=100_000.0)
    pnl.apply_fill(2.0, 50.0, commission=2.0, slippage=1.0)
    snap = pnl.snapshot
    assert snap.position == 2.0
    assert snap.avg_entry_price == 50.0
    assert snap.realized_pnl == -3.0
    assert snap.total_commission == 2.0
    assert snap.total_slippage == 1.0
    assert snap.initial_cash == 100_000.0


def test_snapshot_frozen() -> None:
    snap = PnLCalculator().snapshot
    with pytest.raises(AttributeError):
        snap.position = 5.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PnLCalculator — cost tracking edge cases
# ---------------------------------------------------------------------------


def test_zero_costs_on_entry() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(1.0, 100.0)
    assert pnl.total_commission == 0.0
    assert pnl.total_slippage == 0.0
    assert pnl.realized_pnl == 0.0


def test_costs_on_close_only() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(2.0, 100.0, commission=0.0, slippage=0.0)
    pnl.apply_fill(-1.0, 110.0, commission=5.0, slippage=3.0)
    assert pnl.total_commission == 5.0
    assert pnl.total_slippage == 3.0


# ---------------------------------------------------------------------------
# Cross-check: executor equity == engine portfolio equity
# ---------------------------------------------------------------------------


def test_pnl_calculator_matches_backtest_equity() -> None:
    import pandas as pd
    from pandas import Series as PdSeries

    idx = pd.date_range("2020-01-01", periods=10, freq="h", tz="UTC")
    signals = PdSeries([0.0, 0.5, 1.0, 1.0, 1.0, 0.5, 0.0, -0.3, -0.3, 0.0], index=idx)
    close_prices = PdSeries(
        [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0],
        index=idx,
    )

    commission = 0.001
    slippage = 0.0005
    initial_cash = 100_000.0

    pnl = PnLCalculator(initial_cash=initial_cash)
    pnl_equities: list[float] = []
    for i in range(len(signals)):
        price = float(close_prices.iloc[i])
        target_frac = float(signals.iloc[i])
        current_equity = pnl.equity(price)
        target_qty = target_frac * current_equity / price if price > 0 else 0.0
        delta = target_qty - pnl.position
        if abs(delta) > 1e-12:
            comm_cost = abs(delta) * price * commission
            slip_cost = abs(delta) * price * slippage
            pnl.apply_fill(delta, price, commission=comm_cost, slippage=slip_cost)
        pnl_equities.append(pnl.equity(price))

    engine_state = single_symbol_portfolio(
        signals=signals,
        close=close_prices,
        initial_cash=initial_cash,
        commission=commission,
        slippage=slippage,
    )

    for i in range(len(signals)):
        assert pnl_equities[i] == pytest.approx(engine_state.equity[i], abs=1e-9)


def test_pnl_calculator_matches_backtest_equity_short() -> None:
    import pandas as pd
    from pandas import Series as PdSeries

    idx = pd.date_range("2020-01-01", periods=10, freq="h", tz="UTC")
    signals = PdSeries([0.0, -0.5, -1.0, -0.5, 0.0, 0.3, 0.0, -0.3, 0.0, 0.0], index=idx)
    close_prices = PdSeries(
        [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0],
        index=idx,
    )

    initial_cash = 100_000.0

    pnl = PnLCalculator(initial_cash=initial_cash)
    pnl_equities: list[float] = []
    for i in range(len(signals)):
        price = float(close_prices.iloc[i])
        target_frac = float(signals.iloc[i])
        current_equity = pnl.equity(price)
        target_qty = target_frac * current_equity / price if price > 0 else 0.0
        delta = target_qty - pnl.position
        if abs(delta) > 1e-12:
            pnl.apply_fill(delta, price, commission=0.0, slippage=0.0)
        pnl_equities.append(pnl.equity(price))

    engine_state = single_symbol_portfolio(
        signals=signals,
        close=close_prices,
        initial_cash=initial_cash,
        commission=0.0,
        slippage=0.0,
    )

    for i in range(len(signals)):
        assert pnl_equities[i] == pytest.approx(engine_state.equity[i], abs=1e-9)


def test_pnl_calculator_matches_backtest_final_position() -> None:
    import pandas as pd
    from pandas import Series as PdSeries

    initial_cash = 100_000.0
    idx = pd.date_range("2020-01-01", periods=10, freq="h", tz="UTC")
    signals = PdSeries([0.0, 0.5, 1.0, 1.0, 0.5, 0.0, -0.3, -0.3, 0.0, 0.0], index=idx)
    close_prices = PdSeries(
        [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0],
        index=idx,
    )

    pnl = PnLCalculator(initial_cash=initial_cash)
    for i in range(len(signals)):
        price = float(close_prices.iloc[i])
        target_frac = float(signals.iloc[i])
        current_equity = pnl.equity(price)
        target_qty = target_frac * current_equity / price if price > 0 else 0.0
        delta = target_qty - pnl.position
        if abs(delta) > 1e-12:
            pnl.apply_fill(delta, price)

    engine_state = single_symbol_portfolio(
        signals=signals,
        close=close_prices,
        initial_cash=initial_cash,
        commission=0.0,
        slippage=0.0,
    )
    assert pnl.position == pytest.approx(engine_state.position, abs=1e-9)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_large_number_of_fills() -> None:
    pnl = PnLCalculator(initial_cash=1_000_000.0)
    price = 100.0
    for _ in range(1000):
        pnl.apply_fill(0.1, price, commission=0.01, slippage=0.005)
    assert pnl.position == pytest.approx(100.0)
    assert pnl.total_commission == pytest.approx(10.0)
    assert pnl.total_slippage == pytest.approx(5.0)


@pytest.mark.parametrize("initial_cash", [0.0, 1.0, 100_000.0, 1_000_000.0])
def test_various_initial_cash(initial_cash: float) -> None:
    pnl = PnLCalculator(initial_cash=initial_cash)
    assert pnl.equity(100.0) == initial_cash
    assert pnl.snapshot.initial_cash == initial_cash


def test_negative_prices() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(1.0, -50.0)
    assert pnl.avg_entry_price == -50.0
    assert pnl.equity(-50.0) == pytest.approx(100_000.0)
    assert pnl.unrealized_pnl(-40.0) == pytest.approx(10.0)


def test_fractional_deltas() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(0.123456, 100.0)
    assert pnl.position == pytest.approx(0.123456)
    pnl.apply_fill(-0.054321, 101.0)
    assert pnl.position == pytest.approx(0.069135)


# ---------------------------------------------------------------------------
# PnLCalculator — adopt_state (exchange state adoption)
# ---------------------------------------------------------------------------


def test_adopt_state_sets_position_and_avg_price() -> None:
    pnl = PnLCalculator(initial_cash=100_000.0)
    pnl.adopt_state(position=1.5, avg_entry_price=30000.0)
    assert pnl.position == 1.5
    assert pnl.avg_entry_price == 30000.0
    assert pnl.realized_pnl == 0.0
    assert pnl.total_commission == 0.0
    assert pnl.total_slippage == 0.0


def test_adopt_state_with_realized_pnl() -> None:
    pnl = PnLCalculator(initial_cash=100_000.0)
    pnl.adopt_state(position=-0.5, avg_entry_price=40000.0, realized_pnl=250.0)
    assert pnl.position == -0.5
    assert pnl.avg_entry_price == 40000.0
    assert pnl.realized_pnl == 250.0


def test_adopt_state_preserves_equity_identity() -> None:
    pnl = PnLCalculator(initial_cash=100_000.0)
    pnl.adopt_state(position=2.0, avg_entry_price=50000.0)
    eq = pnl.equity(51000.0)
    expected_eq = 100_000.0 + 0.0 + (51000.0 - 50000.0) * 2.0
    assert eq == pytest.approx(expected_eq)


# ---------------------------------------------------------------------------


def test_consecutive_closes_and_reopens() -> None:
    pnl = PnLCalculator()
    pnl.apply_fill(1.0, 100.0)
    pnl.apply_fill(-1.0, 110.0)
    assert pnl.position == 0.0
    assert pnl.avg_entry_price == 0.0
    pnl.apply_fill(1.0, 105.0)
    assert pnl.position == 1.0
    assert pnl.avg_entry_price == 105.0
    assert pnl.realized_pnl == pytest.approx(10.0)
