#!/usr/bin/env python3
"""ztb-ci-strategy-validate.py — CI gate that ACTUALLY runs `ztb validate`.

The firm's prior edge gate (`ztb/vr-pass`) was an ATTESTATION: a V&R agent (or human)
posted PASS — nothing machine-checked that a strategy truly cleared the walk-forward
OOS bar. This closes that hole: for every strategy plugin a PR adds/changes under
`ztb/strategies/`, run the real `ztb validate <name> BTCUSDT` and FAIL the build unless
it passes (cost-aware OOS Sharpe, Deflated Sharpe, >=30 trades/window, look-ahead). It
is run by free CI compute ($0 LLM), on the PR's exact code, so it is ungameable.

Non-strategy PRs (no changed plugin) pass trivially. sma_cross / base / registry /
__init__ are excluded (sma_cross is the reference fixture, not a tradeable edge).

Usage: python3 scripts/ztb-ci-strategy-validate.py
       [--base origin/main] [--symbol BTCUSDT] [--days 540]
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import subprocess
import sys
from datetime import UTC, datetime, timedelta

EXCLUDE = {"__init__", "base", "registry", "sma_cross"}


def sh(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def changed_strategy_files(base: str) -> list[str]:
    # diff the PR head against the merge-base with the target branch
    _, mb = sh(["git", "merge-base", base, "HEAD"])
    mb = mb.strip() or base
    code, out = sh(["git", "diff", "--name-only", "--diff-filter=AM", f"{mb}...HEAD"])
    if code != 0:  # fallback: diff against base directly
        _, out = sh(["git", "diff", "--name-only", "--diff-filter=AM", base])
    files = []
    for f in out.splitlines():
        f = f.strip()
        if f.startswith("ztb/strategies/") and f.endswith(".py"):
            stem = f.rsplit("/", 1)[-1][:-3]
            if stem not in EXCLUDE:
                files.append(stem)
    return sorted(set(files))


def strategies_in_module(stem: str) -> list[tuple[str, str]]:
    """Return (name, timeframe) for each concrete Strategy defined in the module."""
    from ztb.strategies.base import Strategy

    mod = importlib.import_module(f"ztb.strategies.{stem}")
    out = []
    for _, obj in inspect.getmembers(mod, inspect.isclass):
        if obj is Strategy or not issubclass(obj, Strategy) or inspect.isabstract(obj):
            continue
        if obj.__module__ != mod.__name__:  # defined here, not imported
            continue
        name = getattr(obj, "name", None)
        if name:
            out.append((str(name), str(getattr(obj, "timeframe", "60") or "60")))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--days", type=int, default=540)
    ap.add_argument("--end", default=None)  # ISO; default "now" (passed in by CI for determinism)
    args = ap.parse_args()

    stems = changed_strategy_files(args.base)
    if not stems:
        print("strategy-validate: no strategy plugin added/changed — PASS (n/a).")
        return 0

    end = args.end or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_dt = datetime.strptime(end, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    start = (end_dt - timedelta(days=args.days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    failures = []
    for stem in stems:
        try:
            strategies = strategies_in_module(stem)
        except Exception as exc:  # import error == broken plugin == fail
            print(f"strategy-validate: FAIL — cannot import ztb.strategies.{stem}: {exc}")
            failures.append(stem)
            continue
        if not strategies:
            print(f"strategy-validate: {stem}.py defines no concrete Strategy — skipping.")
            continue
        for name, tf in strategies:
            print(f"\n=== strategy-validate: {name} ({args.symbol} tf={tf}) {start}..{end} ===")
            code, out = sh(
                [
                    "ztb",
                    "validate",
                    name,
                    args.symbol,
                    "--timeframe",
                    tf,
                    "--start",
                    start,
                    "--end",
                    end,
                    "--persist",
                ]
            )
            print(out[-3000:])
            if code == 0:
                print(f"strategy-validate: {name} PASS")
            else:
                print(f"strategy-validate: {name} FAIL (exit {code})")
                failures.append(name)

    if failures:
        print(f"\nstrategy-validate: BLOCKED — these did NOT pass ztb validate: {failures}")
        print("A strategy plugin cannot merge until it clears the walk-forward OOS edge gate.")
        return 1
    print("\nstrategy-validate: all changed strategies PASS the validation gate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
