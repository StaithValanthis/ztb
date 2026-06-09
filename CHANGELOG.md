# Changelog

## v0.1.1 (2026-06-09)

- CI fix: exclude `@pytest.mark.network` from default test run (unblocks M1 data layer testing)
- **PR:** [#3](https://github.com/StaithValanthis/ztb/pull/3)
- **Merge commit:** `02035ac` — admin-merge (MD-authorized, V&R PASS on SHA `e51f8b9`)

## v0.2.0 (2026-06-09)

- M1 data layer: ztb/data/ module (errors, schema, timeframes, rate_limit, bybit_rest, pagination, fetch, cache, integrity, loader)
- CLI: ztb data fetch|show|verify|instruments
- Dependencies: httpx, pandas, pyarrow
- **Tests:** all green, ≥90% coverage, cold==warm determinism proven, delta-fetch spy-proven
- **Merge commit:** 651d284 — two-key merge (CI green + V&R PASS on SHA 1a8250b)
- **Tag:** v0.2.0

## v0.1.0 (2026-06-09)

- M0 scaffold: typed package skeleton, frozen Config, CLI dispatcher, pyproject.toml + pre-commit + CI
- **Tests:** 20/20 pass, 98% coverage
- **Merge commit:** 9cd35d5 — two-key merge (CI green + V&R PASS on SHA a709d6c)
