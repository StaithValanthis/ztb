# Go-Live Runbook

## Preflight Checklist (Gate)

1. **Tag pinning** — ensure `ztb` is running a released tag (not `main`):
   ```
   git describe --tags --exact-match
   ```
2. **Version match** — confirm installed version matches tag:
   ```
   python -c "from ztb import __version__; print(__version__)"
   ```
3. **LiveGuard** — set `ZTB_LIVE_ARMED=1` only after Board approval.
4. **Risk thresholds** — verify `risk-thresholds.json` is current (V&R-owned).
5. **Secrets** — confirm `ZTB_BYBIT_API_KEY` and `ZTB_BYBIT_API_SECRET` are set.
6. **Strategy readiness** — run `ztb backtest --risk-enabled` and verify scorecard.
7. **Demo proof** — run a sustained DEMO execution (`ztb run --mode=demo`) with zero unexpected errors.

## Arming Sequence

```bash
# 1. Run preflight
ztb run --preflight --expected-tag v1.0.0

# 2. Start demo run to verify connectivity
ztb run sma_cross BTCUSDT --mode=demo --dry-run

# 3. Board meeting — explicit arm vote
export ZTB_LIVE_ARMED=1

# 4. Live run (disarmed by default; MUST be armed first)
ztb run sma_cross BTCUSDT --preflight
```

## Monitoring

- Health via `ztb dashboard` live page.
- Killswitch events appear in the store `kill_events` table.
- Discord alerts via `send_live_alert()` (configure `ZTB_DISCORD_WEBHOOK_URL`).

## Disarm

```bash
unset ZTB_LIVE_ARMED
# or
export ZTB_LIVE_ARMED=0
```
