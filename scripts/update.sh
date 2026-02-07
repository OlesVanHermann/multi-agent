#!/bin/bash
# update.sh — Update framework scripts from GitHub
# Usage: ./scripts/update.sh

set -euo pipefail

REPO="https://raw.githubusercontent.com/OlesVanHermann/multi-agent/main"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Updating scripts from GitHub..."
curl -sf -o "$SCRIPT_DIR/sync-to-git.sh" "$REPO/scripts/sync-to-git.sh"
curl -sf -o "$SCRIPT_DIR/update.sh" "$REPO/scripts/update.sh"
chmod +x "$SCRIPT_DIR/sync-to-git.sh" "$SCRIPT_DIR/update.sh"

echo "Done. md5:"
md5sum "$SCRIPT_DIR/sync-to-git.sh"
md5sum "$SCRIPT_DIR/update.sh"
