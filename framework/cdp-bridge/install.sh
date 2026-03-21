#!/bin/bash
# =============================================================================
# CDP Bridge — macOS Installer
# =============================================================================
#
# WHAT THIS SCRIPT DOES:
#   1. Prompts for the Chrome extension ID (shown after loading the extension)
#   2. Creates the native messaging host manifest with the correct paths
#   3. Installs the manifest in Chrome's NativeMessagingHosts directory
#   4. Makes the Node.js host script executable
#
# PREREQUISITES:
#   - Node.js installed (node command available)
#   - Chrome installed
#   - Extension loaded in Chrome (to get the extension ID)
#
# USAGE:
#   ./install.sh
#   ./install.sh <extension-id>    # Skip the prompt
#
# UNINSTALL:
#   ./install.sh --uninstall
#
# =============================================================================

set -euo pipefail

# --- Paths ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NATIVE_HOST_DIR="$SCRIPT_DIR/native-host"
HOST_SCRIPT="$NATIVE_HOST_DIR/cdp-bridge-host.js"
TEMPLATE="$NATIVE_HOST_DIR/com.cdpbridge.host.json.template"
MANIFEST_NAME="com.cdpbridge.host.json"

# Chrome native messaging hosts directory (macOS)
CHROME_NM_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
# Also support Chromium and Chrome Canary
CHROMIUM_NM_DIR="$HOME/Library/Application Support/Chromium/NativeMessagingHosts"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}ℹ${NC}  $1"; }
ok()    { echo -e "${GREEN}✓${NC}  $1"; }
warn()  { echo -e "${YELLOW}⚠${NC}  $1"; }
err()   { echo -e "${RED}✗${NC}  $1"; }

# =============================================================================
# UNINSTALL
# =============================================================================

if [[ "${1:-}" == "--uninstall" ]]; then
    echo ""
    echo "═══════════════════════════════════════════"
    echo "  CDP Bridge — Uninstall"
    echo "═══════════════════════════════════════════"
    echo ""

    for dir in "$CHROME_NM_DIR" "$CHROMIUM_NM_DIR"; do
        manifest="$dir/$MANIFEST_NAME"
        if [[ -f "$manifest" ]]; then
            rm "$manifest"
            ok "Removed: $manifest"
        fi
    done

    ok "Uninstall complete. You can also remove the extension from chrome://extensions."
    exit 0
fi

# =============================================================================
# INSTALL
# =============================================================================

echo ""
echo "═══════════════════════════════════════════"
echo "  CDP Bridge — macOS Installer"
echo "═══════════════════════════════════════════"
echo ""

# --- Step 0: Check prerequisites ---

if ! command -v node &>/dev/null; then
    err "Node.js not found. Install it: brew install node"
    exit 1
fi
ok "Node.js found: $(node --version)"

if [[ ! -f "$HOST_SCRIPT" ]]; then
    err "Host script not found: $HOST_SCRIPT"
    exit 1
fi
ok "Host script found: $HOST_SCRIPT"

# --- Step 1: Get Extension ID ---

echo ""
info "You need the Chrome extension ID."
info "To find it:"
info "  1. Open chrome://extensions in Chrome"
info "  2. Enable 'Developer mode' (top right toggle)"
info "  3. Click 'Load unpacked' and select: $SCRIPT_DIR/extension"
info "  4. Copy the 'ID' shown under 'CDP Bridge'"
echo ""

EXTENSION_ID="${1:-}"
if [[ -z "$EXTENSION_ID" ]]; then
    read -p "  Paste the extension ID here: " EXTENSION_ID
fi

# Validate: extension IDs are 32 lowercase letters
if [[ ! "$EXTENSION_ID" =~ ^[a-z]{32}$ ]]; then
    warn "Extension ID doesn't look standard (expected 32 lowercase letters)."
    warn "Got: '$EXTENSION_ID'"
    read -p "  Continue anyway? [y/N] " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        exit 1
    fi
fi

ok "Extension ID: $EXTENSION_ID"

# --- Step 2: Create the launcher script ---
# Native messaging requires an executable, so we create a wrapper script
# that uses the correct Node.js path.

LAUNCHER="$NATIVE_HOST_DIR/cdp-bridge-launcher.sh"
NODE_PATH="$(which node)"

cat > "$LAUNCHER" << EOF
#!/bin/bash
# Auto-generated launcher for CDP Bridge Native Messaging Host
# Chrome calls this script; it starts the Node.js host.
exec "$NODE_PATH" "$HOST_SCRIPT"
EOF

chmod +x "$LAUNCHER"
ok "Created launcher: $LAUNCHER"

# --- Step 3: Generate the manifest ---

MANIFEST_CONTENT=$(cat "$TEMPLATE" \
    | sed "s|__NATIVE_HOST_PATH__|$LAUNCHER|g" \
    | sed "s|__EXTENSION_ID__|$EXTENSION_ID|g")

# --- Step 4: Install the manifest ---

mkdir -p "$CHROME_NM_DIR"
echo "$MANIFEST_CONTENT" > "$CHROME_NM_DIR/$MANIFEST_NAME"
ok "Installed manifest: $CHROME_NM_DIR/$MANIFEST_NAME"

# Also install for Chromium if the directory exists
if [[ -d "$(dirname "$CHROMIUM_NM_DIR")" ]]; then
    mkdir -p "$CHROMIUM_NM_DIR"
    echo "$MANIFEST_CONTENT" > "$CHROMIUM_NM_DIR/$MANIFEST_NAME"
    ok "Also installed for Chromium"
fi

# --- Step 5: Verify ---

echo ""
echo "═══════════════════════════════════════════"
echo "  Installation Complete!"
echo "═══════════════════════════════════════════"
echo ""
info "Manifest installed at:"
info "  $CHROME_NM_DIR/$MANIFEST_NAME"
echo ""
info "Next steps:"
info "  1. Restart Chrome (or reload the extension)"
info "  2. The native host should auto-start"
info "  3. Test with: curl http://localhost:9222/json"
echo ""
info "If port 9222 is busy (old --remote-debugging-port):"
info "  Kill Chrome with debug port first, then restart normally."
info "  The extension replaces the need for --remote-debugging-port."
echo ""
info "To test the Python client:"
info "  python3 chrome-bridge.py status"
info "  python3 chrome-bridge.py tab https://www.google.com"
info "  python3 chrome-bridge.py screenshot test.png"
echo ""
ok "Done!"
