# Bybit data facts
- **Type:** fact
- **When to use:** building/checking the data layer, the cost model, or any Bybit API call.

## Fact
- **Taker fee ≈ 0.055% per side** (linear USDT perps); maker ≈ 0.02%. Re-verify the live rate before relying on it in a release.
- **Public market data (no auth, mainnet host):** kline `GET https://api.bybit.com/v5/market/kline` (`category=linear|spot`, `symbol`, `interval`, `limit`≤1000); funding `GET https://api.bybit.com/v5/market/funding/history` (settles every 8h); instruments `/v5/market/instruments-info`; time `/v5/market/time`.
- **Demo trading (signed orders):** `https://api-demo.bybit.com`. Public data uses the mainnet host above. Honor HTTP 429 + Retry-After. Metrics always net of fees + slippage.

- **Last-verified:** 2026-06-09 — **Source:** docs/playbook M1; Bybit v5 public REST.
