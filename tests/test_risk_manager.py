from __future__ import annotations

import numpy as np

from ztb.risk.killswitch import KillSwitch
from ztb.risk.manager import RiskManager
from ztb.risk.models import RiskConfig, RiskDecisionAction


def test_evaluate_no_positions_proceeds() -> None:
    mgr = RiskManager()
    mgr.update_portfolio_equity(100_000.0)
    decision = mgr.evaluate(
        portfolio_state={"cash": 100_000.0, "position": 0.0},
        proposed_positions={},
        prices={},
        current_equity=100_000.0,
    )
    assert decision.action == RiskDecisionAction.proceed
    assert decision.max_notional > 0


def test_evaluate_killswitch_halt() -> None:
    ks = KillSwitch(account_killswitch_dd=0.25, cooldown_bars=100)
    mgr = RiskManager(kill_switch=ks)
    mgr.update_portfolio_equity(100.0)
    decision = mgr.evaluate(
        portfolio_state={"cash": 100.0, "position": 1.0},
        proposed_positions={"BTC": 1.0},
        prices={"BTC": 10.0},
        current_equity=70.0,
    )
    assert decision.action == RiskDecisionAction.halt
    assert decision.max_pos_size == 0.0


def test_evaluate_leverage_exceeded() -> None:
    config = RiskConfig(max_leverage=2.0)
    mgr = RiskManager(config=config)
    mgr.update_portfolio_equity(100_000.0)
    decision = mgr.evaluate(
        portfolio_state={"cash": 100_000.0, "position": 0.0},
        proposed_positions={"BTC": 10.0},
        prices={"BTC": 50000.0},
        current_equity=100_000.0,
    )
    notional = 10.0 * 50000.0
    leverage = notional / 100_000.0
    assert leverage > 2.0
    assert decision.action == RiskDecisionAction.reduce
    assert "leverage" in decision.reason


def test_evaluate_leverage_within_limit_proceeds() -> None:
    config = RiskConfig(max_leverage=3.0)
    mgr = RiskManager(config=config)
    mgr.update_portfolio_equity(100_000.0)
    decision = mgr.evaluate(
        portfolio_state={"cash": 100_000.0, "position": 0.0},
        proposed_positions={"BTC": 1.0},
        prices={"BTC": 50000.0},
        current_equity=100_000.0,
    )
    assert decision.action == RiskDecisionAction.proceed


def test_evaluate_position_pct_exceeded() -> None:
    config = RiskConfig(max_leverage=10.0, max_position_pct=0.50)
    mgr = RiskManager(config=config)
    mgr.update_portfolio_equity(100_000.0)
    decision = mgr.evaluate(
        portfolio_state={"cash": 100_000.0, "position": 0.0},
        proposed_positions={"BTC": 10.0},
        prices={"BTC": 50000.0},
        current_equity=100_000.0,
    )
    assert decision.action == RiskDecisionAction.reduce
    assert "position" in decision.reason


def test_evaluate_position_pct_sets_correct_max_notional() -> None:
    config = RiskConfig(max_leverage=10.0, max_position_pct=0.50)
    mgr = RiskManager(config=config)
    mgr.update_portfolio_equity(100_000.0)
    decision = mgr.evaluate(
        portfolio_state={"cash": 100_000.0, "position": 0.0},
        proposed_positions={"BTC": 10.0},
        prices={"BTC": 50000.0},
        current_equity=100_000.0,
    )
    assert decision.action == RiskDecisionAction.reduce
    assert decision.max_notional == 100_000.0 * 10.0  # equity * max_leverage


def test_evaluate_heat_exceeded() -> None:
    config = RiskConfig(max_heat=0.3)
    mgr = RiskManager(config=config)
    cov = np.array([[0.25, 0.24], [0.24, 0.25]])
    mgr.set_covariance(cov)
    mgr.update_portfolio_equity(100_000.0)
    decision = mgr.evaluate(
        portfolio_state={"cash": 100_000.0, "position": 0.0},
        proposed_positions={"BTC": 1.0, "ETH": 1.0},
        prices={"BTC": 50000.0, "ETH": 3000.0},
        current_equity=100_000.0,
    )
    assert decision.action == RiskDecisionAction.reduce
    assert "heat" in decision.reason or "exceeds" in decision.reason


def test_evaluate_dd_budget_scalar() -> None:
    config = RiskConfig(max_portfolio_dd=0.25, max_leverage=10.0, max_position_pct=0.95)
    mgr = RiskManager(config=config)
    mgr.kill_switch.update(100_000.0)
    decision = mgr.evaluate(
        portfolio_state={"cash": 90_000.0, "position": 0.0},
        proposed_positions={"BTC": 1.0},
        prices={"BTC": 50000.0},
        current_equity=90_000.0,
    )
    assert decision.action == RiskDecisionAction.proceed
    assert "dd_budget_scalar" in decision.reason or decision.reason == ""


def test_evaluate_accumulates_decisions() -> None:
    mgr = RiskManager()
    mgr.update_portfolio_equity(100_000.0)
    mgr.evaluate(
        portfolio_state={"cash": 100_000.0, "position": 0.0},
        proposed_positions={"BTC": 1.0},
        prices={"BTC": 50000.0},
        current_equity=100_000.0,
    )
    assert len(mgr.decisions) == 1
    mgr.evaluate(
        portfolio_state={"cash": 100_000.0, "position": 0.0},
        proposed_positions={"BTC": 1.0},
        prices={"BTC": 50000.0},
        current_equity=100_000.0,
    )
    assert len(mgr.decisions) == 2


def test_evaluate_heat_not_computed_for_single_asset() -> None:
    config = RiskConfig(max_heat=0.3)
    mgr = RiskManager(config=config)
    cov = np.array([[0.25]])
    mgr.set_covariance(cov)
    mgr.update_portfolio_equity(100_000.0)
    decision = mgr.evaluate(
        portfolio_state={"cash": 100_000.0, "position": 0.0},
        proposed_positions={"BTC": 1.0},
        prices={"BTC": 50000.0},
        current_equity=100_000.0,
    )
    assert decision.action == RiskDecisionAction.proceed


def test_cooldown_tick_delegates() -> None:
    mgr = RiskManager()
    mgr.kill_switch.tripped = True
    mgr.kill_switch.cooldown_remaining = 5
    mgr.cooldown_tick()
    assert mgr.kill_switch.cooldown_remaining == 4


def test_reset_kill_switch() -> None:
    mgr = RiskManager()
    mgr.kill_switch.tripped = True
    mgr.kill_switch.trip_reason = "test"
    mgr.reset_kill_switch(current_equity=50_000.0)
    assert mgr.kill_switch.tripped is False
    assert mgr.kill_switch.hwm == 50_000.0


def test_evaluate_pipeline_order_killswitch_first() -> None:
    ks = KillSwitch(account_killswitch_dd=0.25)
    mgr = RiskManager(kill_switch=ks)
    mgr.update_portfolio_equity(100.0)
    decision = mgr.evaluate(
        portfolio_state={"cash": 70.0, "position": 1.0},
        proposed_positions={"BTC": 100.0},
        prices={"BTC": 1.0},
        current_equity=70.0,
    )
    assert decision.action == RiskDecisionAction.halt


def test_set_returns_and_set_covariance() -> None:
    import numpy as np
    from pandas import DataFrame

    mgr = RiskManager()
    df = DataFrame({"A": [0.01, -0.01, 0.02]})
    mgr.set_returns(df)
    cov = np.array([[0.04]])
    mgr.set_covariance(cov)
    assert mgr._returns_df is not None
    assert mgr._cov is not None


def test_compute_current_dd_when_hwm_zero() -> None:
    mgr = RiskManager()
    mgr.kill_switch.hwm = 0.0
    dd = mgr._compute_current_dd(100.0)
    assert dd == 1.0


def test_compute_current_dd_returns_1_when_hwm_nan() -> None:
    mgr = RiskManager()
    mgr.kill_switch.hwm = np.nan
    dd = mgr._compute_current_dd(100.0)
    assert dd == 1.0


def test_compute_current_dd_returns_1_when_hwm_inf() -> None:
    mgr = RiskManager()
    mgr.kill_switch.hwm = np.inf
    dd = mgr._compute_current_dd(100.0)
    assert dd == 1.0


def test_evaluate_heat_computed_for_multi_asset() -> None:
    import numpy as np

    config = RiskConfig(max_heat=10.0, max_leverage=10.0, max_position_pct=0.95)
    mgr = RiskManager(config=config)
    cov = np.array([[0.04, 0.01], [0.01, 0.09]])
    mgr.set_covariance(cov)
    mgr.update_portfolio_equity(100_000.0)
    decision = mgr.evaluate(
        portfolio_state={"cash": 100_000.0, "position": 0.0},
        proposed_positions={"BTC": 1.0, "ETH": 10.0},
        prices={"BTC": 50000.0, "ETH": 3000.0},
        current_equity=100_000.0,
    )
    assert decision.action == RiskDecisionAction.proceed
    assert decision.current_heat is not None


def test_config_from_to_dict() -> None:
    cfg = RiskConfig()
    d = cfg.to_dict()
    assert d["max_portfolio_dd"] == 0.25
    assert d["max_leverage"] == 3.0
    cfg2 = RiskConfig.from_dict(d)
    assert cfg2.max_portfolio_dd == 0.25
    assert cfg2.max_leverage == 3.0


def test_config_from_dict_partial() -> None:
    cfg = RiskConfig.from_dict({"max_portfolio_dd": 0.15})
    assert cfg.max_portfolio_dd == 0.15
    assert cfg.max_leverage == 3.0


def test_evaluate_hwm_in_decision() -> None:
    mgr = RiskManager()
    mgr.update_portfolio_equity(100_000.0)
    mgr.update_portfolio_equity(110_000.0)
    decision = mgr.evaluate(
        portfolio_state={"cash": 110_000.0, "position": 0.0},
        proposed_positions={"BTC": 1.0},
        prices={"BTC": 50000.0},
        current_equity=110_000.0,
    )
    assert decision.hwm == 110_000.0
