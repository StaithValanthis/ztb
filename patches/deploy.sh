#!/usr/bin/env bash
set -euo pipefail

# Deploy Paperclip server patches for ZTB-1261
# Requires sudo or ubuntu user to write to npm-installed files
#
# Usage:
#   sudo ./deploy.sh
#   # OR (run as ubuntu)
#   su ubuntu -c ./deploy.sh

PATCH_DIR="$(cd "$(dirname "$0")" && pwd)"

# Target paths (npm global install under /home/ubuntu)
OPENCODE_PARSE="/home/ubuntu/.npm-global/lib/node_modules/paperclipai/node_modules/@paperclipai/adapter-opencode-local/dist/server/parse.js"
OPENCODE_EXECUTE="/home/ubuntu/.npm-global/lib/node_modules/paperclipai/node_modules/@paperclipai/adapter-opencode-local/dist/server/execute.js"
RECOVERY_SERVICE="/home/ubuntu/.npm-global/lib/node_modules/paperclipai/node_modules/@paperclipai/server/dist/services/recovery/service.js"
HEARTBEAT="/home/ubuntu/.npm-global/lib/node_modules/paperclipai/node_modules/@paperclipai/server/dist/services/heartbeat.js"

# Backup originals
echo "=== Backing up originals ==="
cp "$OPENCODE_PARSE" "${OPENCODE_PARSE}.bak-ztb1261"
cp "$OPENCODE_EXECUTE" "${OPENCODE_EXECUTE}.bak-ztb1261"
cp "$RECOVERY_SERVICE" "${RECOVERY_SERVICE}.bak-ztb1261"
cp "$HEARTBEAT" "${HEARTBEAT}.bak-ztb1261"

# Apply patches
echo "=== Applying opencode parse.js ==="
cp "$PATCH_DIR/../patches/adapter-opencode-local/parse.js" "$OPENCODE_PARSE"

echo "=== Applying opencode execute.js ==="
cp "$PATCH_DIR/../patches/adapter-opencode-local/execute.js" "$OPENCODE_EXECUTE"

echo "=== Applying recovery service.js ==="
cp "$PATCH_DIR/../patches/server/recovery-service.js" "$RECOVERY_SERVICE"

echo "=== Applying heartbeat.js ==="
cd "$(dirname "$HEARTBEAT")"
patch -p0 < "$PATCH_DIR/../patches/server/heartbeat.patch"

echo "=== Verifying ==="
# Check that key functions exist in the patched files
grep -q "isOpenCodeTransientUpstreamError" "$OPENCODE_PARSE" && echo "  [OK] isOpenCodeTransientUpstreamError in parse.js"
grep -q "opencode_transient_upstream" "$OPENCODE_EXECUTE" && echo "  [OK] opencode_transient_upstream in execute.js"
grep -q "opencode_transient_upstream" "$RECOVERY_SERVICE" && echo "  [OK] opencode_transient_upstream in recovery service"
grep -q "opencode_transient_upstream" "$HEARTBEAT" && echo "  [OK] opencode_transient_upstream in heartbeat"

echo ""
echo "=== Done ==="
echo "Backups saved with .bak-ztb1261 suffix"
echo ""
echo "Patches applied but require Paperclip server restart to take effect."
echo "Restart the server:"
echo "  sudo systemctl restart paperclip"
echo "  # OR (if running via subreaper)"
echo "  kill -HUP <paperclip-pid>"
