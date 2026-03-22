#!/bin/bash
# keycloak_user_create.sh - Create a Keycloak user with password
# Usage: ./setup/keycloak_user_create.sh <username> <password>

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

USERNAME="${1:-}"
PASSWORD="${2:-}"

if [ -z "$USERNAME" ] || [ -z "$PASSWORD" ]; then
    echo "Usage: $0 <username> <password>"
    echo ""
    echo "Example: $0 dev1 my-password"
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
log_info "Checking Keycloak at $KEYCLOAK_URL..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$KEYCLOAK_URL/health/ready" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" != "200" ]; then
    log_error "Keycloak is not reachable (HTTP $HTTP_CODE)"
    exit 1
fi
log_ok "Keycloak is up"

# Get admin token
log_info "Getting admin token..."
TOKEN_RESP=$(curl -s --max-time 10 \
    -d "grant_type=password&client_id=admin-cli&username=$KEYCLOAK_ADMIN&password=$KEYCLOAK_ADMIN_PASSWORD" \
    "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" 2>/dev/null)

ADMIN_TOKEN=$(echo "$TOKEN_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)

if [ -z "$ADMIN_TOKEN" ]; then
    log_error "Failed to get admin token. Check admin credentials."
    exit 1
fi
log_ok "Admin token obtained"

# Check user doesn't already exist
EXISTING=$(curl -s --max-time 10 \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/users?username=$USERNAME&exact=true" 2>/dev/null)

EXISTING_COUNT=$(echo "$EXISTING" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

if [ "$EXISTING_COUNT" != "0" ]; then
    log_error "User '$USERNAME' already exists in realm '$REALM'"
    exit 1
fi

# Create user
log_info "Creating user '$USERNAME' in realm '$REALM'..."
CREATE_RESP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
    -X POST \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$USERNAME\",\"enabled\":true,\"credentials\":[{\"type\":\"password\",\"value\":\"$PASSWORD\",\"temporary\":false}]}" \
    "$KEYCLOAK_URL/admin/realms/$REALM/users" 2>/dev/null)

if [ "$CREATE_RESP" = "201" ]; then
    log_ok "User '$USERNAME' created"
else
    log_error "Failed to create user (HTTP $CREATE_RESP)"
    exit 1
fi

# Test login + verify JWT contains preferred_username
log_info "Testing login..."
LOGIN_RESP=$(curl -s --max-time 10 \
    -d "grant_type=password&client_id=multi-agent-web&username=$USERNAME&password=$PASSWORD" \
    "$KEYCLOAK_URL/realms/$REALM/protocol/openid-connect/token" 2>/dev/null)

ACCESS_TOKEN=$(echo "$LOGIN_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)

if [ -z "$ACCESS_TOKEN" ]; then
    log_info "User created but login test failed (client 'multi-agent-web' may not be configured)"
else
    # Decode JWT and check preferred_username
    JWT_USERNAME=$(echo "$ACCESS_TOKEN" | cut -d. -f2 | python3 -c "
import sys,base64,json
b = sys.stdin.read().strip()
b += '=' * (-len(b) % 4)
payload = json.loads(base64.urlsafe_b64decode(b))
print(payload.get('preferred_username', ''))
" 2>/dev/null)

    if [ "$JWT_USERNAME" = "$USERNAME" ]; then
        log_ok "Login test passed — JWT contains preferred_username='$USERNAME'"
    else
        log_info "Login OK but JWT missing preferred_username (got: '$JWT_USERNAME')"
        log_info "Fixing: adding 'profile' scope to client..."

        # Get admin token
        FIX_TOKEN=$(curl -s --max-time 10 \
            -d "grant_type=password&client_id=admin-cli&username=$KEYCLOAK_ADMIN&password=$KEYCLOAK_ADMIN_PASSWORD" \
            "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" 2>/dev/null \
            | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)

        if [ -n "$FIX_TOKEN" ]; then
            # Get client UUID
            FIX_CLIENT=$(curl -s -H "Authorization: Bearer $FIX_TOKEN" \
                "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=multi-agent-web" 2>/dev/null \
                | python3 -c "import sys,json; c=json.load(sys.stdin); print(c[0]['id'] if c else '')" 2>/dev/null)

            # Check if profile scope exists, create if not
            PROFILE_ID=$(curl -s -H "Authorization: Bearer $FIX_TOKEN" \
                "$KEYCLOAK_URL/admin/realms/$REALM/client-scopes" 2>/dev/null \
                | python3 -c "import sys,json; [print(s['id']) for s in json.load(sys.stdin) if s['name']=='profile']" 2>/dev/null)

            if [ -z "$PROFILE_ID" ]; then
                curl -s -X POST -H "Authorization: Bearer $FIX_TOKEN" -H "Content-Type: application/json" \
                    "$KEYCLOAK_URL/admin/realms/$REALM/client-scopes" \
                    -d '{"name":"profile","protocol":"openid-connect","attributes":{"include.in.token.scope":"true"}}' >/dev/null 2>&1

                PROFILE_ID=$(curl -s -H "Authorization: Bearer $FIX_TOKEN" \
                    "$KEYCLOAK_URL/admin/realms/$REALM/client-scopes" 2>/dev/null \
                    | python3 -c "import sys,json; [print(s['id']) for s in json.load(sys.stdin) if s['name']=='profile']" 2>/dev/null)

                curl -s -X POST -H "Authorization: Bearer $FIX_TOKEN" -H "Content-Type: application/json" \
                    "$KEYCLOAK_URL/admin/realms/$REALM/client-scopes/$PROFILE_ID/protocol-mappers/models" \
                    -d '{"name":"preferred_username","protocol":"openid-connect","protocolMapper":"oidc-usermodel-attribute-mapper","config":{"user.attribute":"username","claim.name":"preferred_username","jsonType.label":"String","id.token.claim":"true","access.token.claim":"true","userinfo.token.claim":"true"}}' >/dev/null 2>&1
            fi

            if [ -n "$FIX_CLIENT" ] && [ -n "$PROFILE_ID" ]; then
                curl -s -X PUT -H "Authorization: Bearer $FIX_TOKEN" \
                    "$KEYCLOAK_URL/admin/realms/$REALM/clients/$FIX_CLIENT/default-client-scopes/$PROFILE_ID" >/dev/null 2>&1
                log_ok "Profile scope fixed — logout/login to get username in JWT"
            fi
        fi
    fi
fi

echo ""
log_ok "Done. User '$USERNAME' created in realm '$REALM'."
