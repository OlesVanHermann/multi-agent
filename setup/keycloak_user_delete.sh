#!/bin/bash
# keycloak_user_delete.sh - Delete a Keycloak user
# Usage: ./setup/keycloak_user_delete.sh <username>

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

USERNAME="${1:-}"

if [ -z "$USERNAME" ]; then
    echo "Usage: $0 <username>"
    echo ""
    echo "Example: $0 dev1"
    exit 1
fi

# Load .env if not already set
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SCRIPT_DIR/../scripts/.env" ] && source "$SCRIPT_DIR/../scripts/.env"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8080}"
KEYCLOAK_ADMIN="${KEYCLOAK_ADMIN:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
REALM="${KEYCLOAK_REALM:-multi-agent}"

# Check Keycloak
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$KEYCLOAK_URL/health/ready" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" != "200" ]; then
    log_error "Keycloak is not reachable (HTTP $HTTP_CODE)"
    exit 1
fi

# Get admin token
TOKEN_RESP=$(curl -s --max-time 10 \
    -d "grant_type=password&client_id=admin-cli&username=$KEYCLOAK_ADMIN&password=$KEYCLOAK_ADMIN_PASSWORD" \
    "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" 2>/dev/null)

ADMIN_TOKEN=$(echo "$TOKEN_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)

if [ -z "$ADMIN_TOKEN" ]; then
    log_error "Failed to get admin token"
    exit 1
fi

# Find user
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
    exit 1
fi
log_ok "Found user: $USERNAME (id: $USER_ID)"

# Delete user
log_info "Deleting user '$USERNAME'..."
DELETE_RESP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
    -X DELETE \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/users/$USER_ID" 2>/dev/null)

if [ "$DELETE_RESP" = "204" ]; then
    log_ok "User '$USERNAME' deleted from realm '$REALM'."
else
    log_error "Failed to delete user (HTTP $DELETE_RESP)"
    exit 1
fi
