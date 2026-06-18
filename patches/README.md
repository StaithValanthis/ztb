# Board-owned file patches (ZTB-3866)

These patches MUST be applied by Board operations (ubuntu user with write access
to /home/ubuntu/ztb-ops/).

## Change 4 — validation-referee.js

Location: /home/ubuntu/ztb-ops/validation-referee.js

1. Add constant after MIN_NET_PNL (line 43):
   ```
   const MIN_CODE_VERSION = env.REFEREE_MIN_CODE_VERSION || '1.1.53';
   ```

2. Scope filledOrders query (line 113):
   Change `WHERE status='Filled'` → `WHERE status='Filled' AND code_version >= '${MIN_CODE_VERSION}'`

3. Scope realFills query (line 116):
   Change `WHERE fill_id NOT LIKE 'synthetic%'` → `WHERE fill_id NOT LIKE 'synthetic%' AND code_version >= '${MIN_CODE_VERSION}'`

4. Scope feedFills query (line 117):
   Change `WHERE commission > 0 AND fill_id NOT LIKE 'synthetic%'` → `WHERE commission > 0 AND fill_id NOT LIKE 'synthetic%' AND code_version >= '${MIN_CODE_VERSION}'`

5. Add MIN_CODE_VERSION to output standard (line 135):
   Add `MIN_CODE_VERSION` to the `standard` object.

## Change 5 — conformance/test_validation_conformance.py

Location: /home/ubuntu/ztb-ops/conformance/test_validation_conformance.py

In `test_demo_fills_are_real_not_synthetic` (line 179):

1. Add after the `import os` (line 183):
   ```python
   min_code_version = os.environ.get("ZTB_MIN_CODE_VERSION", "1.1.53")
   ```

2. Scope filled orders query (line 190):
   Change:
   ```python
   filled = con.execute("SELECT COUNT(*) FROM exec_orders WHERE status='Filled'").fetchone()[0]
   ```
   To:
   ```python
   filled = con.execute("SELECT COUNT(*) FROM exec_orders WHERE status='Filled' AND code_version >= ?", (min_code_version,)).fetchone()[0]
   ```

3. Scope fills query (line 193):
   Change:
   ```python
   fills = con.execute("SELECT COUNT(*) FROM exec_fills WHERE fill_id NOT LIKE 'synthetic%'").fetchone()[0]
   ```
   To:
   ```python
   fills = con.execute("SELECT COUNT(*) FROM exec_fills WHERE fill_id NOT LIKE 'synthetic%' AND code_version >= ?", (min_code_version,)).fetchone()[0]
   ```
