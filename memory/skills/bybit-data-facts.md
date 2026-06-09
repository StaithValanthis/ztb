# Bybit data facts
- **Type:** fact
- **When to use:** building/checking the data layer, the cost model, or any Bybit API call.

## Fact
- **Taker fee ≈ 0.055% per side** (linear USDT perps); maker ≈ 0.02%. Re-verify the live rate before relying on it in a release.
- **Public market data (no auth, mainnet host):**
  - kline: `GET https://api.bybit.com/v5/market/kline` (`category=linear|spot`, `symbol`, `interval`, `limit`≤1000)
  - funding history: `GET https://api.bybit.com/v5/market/funding/history` (`category=linear`, `symbol`) — funding settles every **8h**
  - instruments: `/v5/market/instruments-info`; server time: `/v5/market/time`
- **Demo trading (signed orders):** `https://api-demo.bybit.com`. Public data still uses the mainnet host above.
- Rate-limited: honor HTTP **429** + `Retry-After`. Keep all metrics **net** of fees + slippage.

- **Last-verified:** 2026-06-09 (kline endpoint confirmed returning data live)
- **Source:** docs/playbook/01-MASTER-PLAN.md (M1); Bybit v5 public REST.
