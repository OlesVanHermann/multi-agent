#!/bin/bash
# keycloak_passwd_modify.sh - Change a Keycloak user's password
# Usage: ./framework/keycloak_passwd_modify.sh <username> <new-password>
#
# Uses Keycloak Admin REST API to:
# 1. Get admin token
# 2. Find user by username
# 3. Reset password
# 4. Test login with new credentials

set -e

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ── Args ──

USERNAME="${1:-}"
NEW_PASSWORD="${2:-}"

if [ -z "$USERNAME" ] || [ -z "$NEW_PASSWORD" ]; then
    echo "Usage: $0 <username> <new-password>"
    echo ""
    echo "Example: $0 octave my-new-password"
    exit 1
fi

KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8080}"
KEYCLOAK_ADMIN="${KEYCLOAK_ADMIN:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
REALM="${KEYCLOAK_REALM:-multi-agent}"

# ── Check Keycloak is up ──

log_info "Checking Keycloak at $KEYCLOAK_URL..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$KEYCLOAK_URL/health/ready" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" != "200" ]; then
    log_error "Keycloak is not reachable (HTTP $HTTP_CODE)"
    log_info "Start it with: ./framework/install_keycloak.sh"
    exit 1
fi
log_ok "Keycloak is up"

# ── Get admin token ──

log_info "Getting admin token..."
TOKEN_RESP=$(curl -s --max-time 10 \
    -d "grant_type=password&client_id=admin-cli&username=$KEYCLOAK_ADMIN&password=$KEYCLOAK_ADMIN_PASSWORD" \
    "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" 2>/dev/null)

ADMIN_TOKEN=$(echo "$TOKEN_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)

if [ -z "$ADMIN_TOKEN" ]; then
    log_error "Failed to get admin token. Check admin credentials."
    echo "$TOKEN_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error_description', d))" 2>/dev/null || echo "$TOKEN_RESP"
    exit 1
fi
log_ok "Admin token obtained"

# ── Find user by username ──

log_info "Looking up user '$USERNAME' in realm '$REALM'..."
USERS_RESP=$(curl -s --max-time 10 \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/users?username=$USERNAME&exact=true" 2>/dev/null)

USER_ID=$(echo "$USERS_RESP" | python3 -c "
import sys, json
users = json.load(sys.stdin)
if isinstance(users, list) and len(users) > 0:
    print(users[0]['id'])
else:
    print('')
" 2>/dev/null)

if [ -z "$USER_ID" ]; then
    log_error "User '$USERNAME' not found in realm '$REALM'"
    log_info "Available users:"
    echo "$USERS_RESP" | python3 -c "
import sys, json
users = json.load(sys.stdin)
if isinstance(users, list):
    for u in users:
        print(f'  - {u.get(\"username\", \"?\")} (id: {u.get(\"id\", \"?\")})')
else:
    print(f'  Error: {users}')
" 2>/dev/null || echo "  (parse error)"
    exit 1
fi
log_ok "Found user: $USERNAME (id: $USER_ID)"

# ── Reset password ──

log_info "Resetting password for '$USERNAME'..."
RESET_RESP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
    -X PUT \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"type\":\"password\",\"value\":\"$NEW_PASSWORD\",\"temporary\":false}" \
    "$KEYCLOAK_URL/admin/realms/$REALM/users/$USER_ID/reset-password" 2>/dev/null)

if [ "$RESET_RESP" = "204" ]; then
    log_ok "Password updated successfully"
else
    log_error "Failed to reset password (HTTP $RESET_RESP)"
    exit 1
fi

# ── Test login ──

log_info "Testing login with new credentials..."
LOGIN_RESP=$(curl -s --max-time 10 \
    -d "grant_type=password&client_id=multi-agent-web&username=$USERNAME&password=$NEW_PASSWORD" \
    "$KEYCLOAK_URL/realms/$REALM/protocol/openid-connect/token" 2>/dev/null)

if echo "$LOGIN_RESP" | grep -q "access_token"; then
    log_ok "Login test passed — '$USERNAME' can authenticate with new password"
else
    ERROR_DESC=$(echo "$LOGIN_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error_description','unknown'))" 2>/dev/null)
    log_warn "Login test failed: $ERROR_DESC"
    log_info "The password was updated but the login test failed."
    log_info "This may happen if the client 'multi-agent-web' is not configured in realm '$REALM'."
fi

echo ""
log_ok "Done. User '$USERNAME' password changed in realm '$REALM'."
