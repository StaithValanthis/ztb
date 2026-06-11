from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from ztb import __version__
from ztb.execution.live_guard import LiveGuard


@dataclass
class PreflightItem:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class PreflightReport:
    passed: bool = False
    items: list[PreflightItem] = field(default_factory=list)


def _check_tag(expected_tag: str | None = None) -> PreflightItem:
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--exact-match"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return PreflightItem(
                name="tag", passed=False, detail="Not on an exact tag — detached or dirty HEAD"
            )
        current_tag = result.stdout.strip()
        if expected_tag and current_tag != expected_tag:
            return PreflightItem(
                name="tag",
                passed=False,
                detail=f"Expected tag {expected_tag}, currently on {current_tag}",
            )
        return PreflightItem(name="tag", passed=True, detail=f"On tag {current_tag}")
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return PreflightItem(name="tag", passed=False, detail=f"Tag check failed: {exc}")


def _check_version(expected: str | None = None) -> PreflightItem:
    ver = expected or __version__
    from importlib.metadata import version as pkg_version

    try:
        installed = pkg_version("ztb")
        if installed != ver:
            return PreflightItem(
                name="version",
                passed=False,
                detail=f"Installed ztb {installed} != expected {ver}",
            )
        return PreflightItem(name="version", passed=True, detail=f"ztb {ver}")
    except Exception as exc:
        return PreflightItem(name="version", passed=False, detail=f"Version check error: {exc}")


def _check_live_guard() -> PreflightItem:
    armed = LiveGuard.is_armed()
    return PreflightItem(
        name="live_guard",
        passed=True,
        detail=f"LiveGuard {'ARMED' if armed else 'DISARMED'}",
    )


def _check_risk_config() -> PreflightItem:
    try:
        from pathlib import Path

        path = Path.cwd() / "risk-thresholds.json"
        if not path.exists():
            return PreflightItem(
                name="risk_config", passed=False, detail=f"risk-thresholds.json not found at {path}"
            )
        import json

        data = json.loads(path.read_text())
        thresholds = data.get("account", {})
        dd = thresholds.get("kill_switch_dd_pct", 25)
        return PreflightItem(
            name="risk_config", passed=True, detail=f"risk-thresholds.json found, KS DD={dd}%"
        )
    except Exception as exc:
        return PreflightItem(name="risk_config", passed=False, detail=f"Risk config error: {exc}")


def _check_strategy_ready(strategy_name: str | None = None) -> PreflightItem:
    if strategy_name is None:
        return PreflightItem(name="strategy", passed=True, detail="No strategy specified (skip)")
    try:
        from ztb.strategies.registry import get as get_strategy

        cls = get_strategy(strategy_name)
        inst = cls()
        return PreflightItem(
            name="strategy",
            passed=True,
            detail=f"Strategy {strategy_name} loaded (warmup={inst.warmup})",
        )
    except KeyError as exc:
        return PreflightItem(name="strategy", passed=False, detail=f"Strategy not found: {exc}")
    except Exception as exc:
        return PreflightItem(name="strategy", passed=False, detail=f"Strategy load error: {exc}")


def _check_secrets() -> PreflightItem:
    import os

    api_key = os.environ.get("ZTB_BYBIT_API_KEY", "")
    api_secret = os.environ.get("ZTB_BYBIT_API_SECRET", "")
    if api_key and api_secret:
        masked_key = api_key[:4] + "****" + api_key[-4:] if len(api_key) > 8 else "****"
        return PreflightItem(
            name="secrets", passed=True, detail=f"API key set ({masked_key}), secret set"
        )
    if api_key and not api_secret:
        return PreflightItem(name="secrets", passed=False, detail="API key set but secret missing")
    if not api_key and api_secret:
        return PreflightItem(name="secrets", passed=False, detail="Secret set but API key missing")
    return PreflightItem(name="secrets", passed=False, detail="No API credentials found")


def run_preflight(
    expected_tag: str | None = None,
    expected_version: str | None = None,
    strategy_name: str | None = None,
    check_secrets_enabled: bool = False,
) -> PreflightReport:
    items: list[PreflightItem] = [
        _check_tag(expected_tag),
        _check_version(expected_version),
        _check_live_guard(),
        _check_risk_config(),
        _check_strategy_ready(strategy_name),
    ]
    if check_secrets_enabled:
        items.append(_check_secrets())
    passed = all(i.passed for i in items)
    return PreflightReport(passed=passed, items=items)
