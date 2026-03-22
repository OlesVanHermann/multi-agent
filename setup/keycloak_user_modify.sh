#!/bin/bash
# keycloak_user_modify.sh - Modify a Keycloak user (password, enable/disable, email, name)
# Usage: ./setup/keycloak_user_modify.sh <username> [options]
#
# Options:
#   --password <new_password>    Change password
#   --enable                     Enable user
#   --disable                    Disable user
#   --email <email>              Set email
#   --first-name <name>          Set first name
#   --last-name <name>           Set last name

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

USERNAME="${1:-}"

if [ -z "$USERNAME" ] || [ "${USERNAME:0:2}" = "--" ]; then
    echo "Usage: $0 <username> [options]"
    echo ""
    echo "Options:"
    echo "  --password <new_password>    Change password"
    echo "  --enable                     Enable user"
    echo "  --disable                    Disable user"
    echo "  --email <email>              Set email"
    echo "  --first-name <name>          Set first name"
    echo "  --last-name <name>           Set last name"
    echo ""
    echo "Examples:"
    echo "  $0 dev1 --password newpass123"
    echo "  $0 dev1 --disable"
    echo "  $0 dev1 --enable --email dev1@example.com --first-name John"
    exit 1
fi
shift

# Parse options
NEW_PASSWORD=""
SET_ENABLED=""
NEW_EMAIL=""
NEW_FIRST_NAME=""
NEW_LAST_NAME=""

while [ $# -gt 0 ]; do
    case "$1" in
        --password)
            NEW_PASSWORD="$2"; shift 2 ;;
        --enable)
            SET_ENABLED="true"; shift ;;
        --disable)
            SET_ENABLED="false"; shift ;;
        --email)
            NEW_EMAIL="$2"; shift 2 ;;
        --first-name)
            NEW_FIRST_NAME="$2"; shift 2 ;;
        --last-name)
            NEW_LAST_NAME="$2"; shift 2 ;;
        *)
            log_error "Unknown option: $1"
            exit 1 ;;
    esac
done

if [ -z "$NEW_PASSWORD" ] && [ -z "$SET_ENABLED" ] && [ -z "$NEW_EMAIL" ] && [ -z "$NEW_FIRST_NAME" ] && [ -z "$NEW_LAST_NAME" ]; then
    log_error "No modification specified. Use --password, --enable, --disable, --email, --first-name, or --last-name."
    exit 1
fi

# Load secrets
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SCRIPT_DIR/secrets.cfg" ] && source "$SCRIPT_DIR/secrets.cfg"
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
    log_error "Failed to get admin token. Check admin credentials."
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

# Change password
if [ -n "$NEW_PASSWORD" ]; then
    log_info "Changing password..."
    PASS_RESP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
        -X PUT \
        -H "Authorization: Bearer $ADMIN_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"type\":\"password\",\"value\":\"$NEW_PASSWORD\",\"temporary\":false}" \
        "$KEYCLOAK_URL/admin/realms/$REALM/users/$USER_ID/reset-password" 2>/dev/null)

    if [ "$PASS_RESP" = "204" ]; then
        log_ok "Password changed"
    else
        log_error "Failed to change password (HTTP $PASS_RESP)"
        exit 1
    fi
fi

# Update user attributes (enabled, email, names)
if [ -n "$SET_ENABLED" ] || [ -n "$NEW_EMAIL" ] || [ -n "$NEW_FIRST_NAME" ] || [ -n "$NEW_LAST_NAME" ]; then
    log_info "Updating user attributes..."

    UPDATE_JSON=$(echo "$USERS_RESP" | python3 -c "
import sys, json
users = json.load(sys.stdin)
user = users[0]
patch = {}
" 2>/dev/null)

    # Build JSON patch
    PATCH_FIELDS=""
    [ -n "$SET_ENABLED" ] && PATCH_FIELDS="${PATCH_FIELDS}\"enabled\":$SET_ENABLED,"
    [ -n "$NEW_EMAIL" ] && PATCH_FIELDS="${PATCH_FIELDS}\"email\":\"$NEW_EMAIL\","
    [ -n "$NEW_FIRST_NAME" ] && PATCH_FIELDS="${PATCH_FIELDS}\"firstName\":\"$NEW_FIRST_NAME\","
    [ -n "$NEW_LAST_NAME" ] && PATCH_FIELDS="${PATCH_FIELDS}\"lastName\":\"$NEW_LAST_NAME\","

    # Remove trailing comma
    PATCH_FIELDS="${PATCH_FIELDS%,}"

    UPDATE_RESP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
        -X PUT \
        -H "Authorization: Bearer $ADMIN_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"username\":\"$USERNAME\",$PATCH_FIELDS}" \
        "$KEYCLOAK_URL/admin/realms/$REALM/users/$USER_ID" 2>/dev/null)

    if [ "$UPDATE_RESP" = "204" ]; then
        [ -n "$SET_ENABLED" ] && log_ok "User ${SET_ENABLED} = true → enabled / false → disabled: $SET_ENABLED"
        [ -n "$NEW_EMAIL" ] && log_ok "Email set to: $NEW_EMAIL"
        [ -n "$NEW_FIRST_NAME" ] && log_ok "First name set to: $NEW_FIRST_NAME"
        [ -n "$NEW_LAST_NAME" ] && log_ok "Last name set to: $NEW_LAST_NAME"
    else
        log_error "Failed to update user (HTTP $UPDATE_RESP)"
        exit 1
    fi
fi

echo ""
log_ok "Done. User '$USERNAME' modified in realm '$REALM'."
