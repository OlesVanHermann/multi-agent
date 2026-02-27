#!/bin/bash
# install_keycloak.sh - Install Docker + Keycloak on Mac or Ubuntu
# Usage: ./framework/install_keycloak.sh
#
# Detects OS, installs Docker if missing, starts Keycloak container
# with realm auto-import from web/keycloak/realm-multi-agent.json

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REALM_FILE="$BASE_DIR/web/keycloak/realm-multi-agent.json"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ── Detect OS ──

detect_os() {
    case "$(uname -s)" in
        Darwin) echo "mac" ;;
        Linux)  echo "linux" ;;
        *)      echo "unknown" ;;
    esac
}

OS=$(detect_os)
log_info "Detected OS: $OS"

# ── Install Docker ──

install_docker_mac() {
    if command -v docker &>/dev/null; then
        log_ok "Docker already installed"
        return
    fi

    if ! command -v brew &>/dev/null; then
        log_error "Homebrew not found. Install it first: https://brew.sh"
        exit 1
    fi

    log_info "Installing Docker via Homebrew..."
    brew install docker colima

    log_info "Starting Colima (Docker runtime for Mac)..."
    colima start --memory 4 --cpu 2
    log_ok "Docker ready via Colima"
}

install_docker_linux() {
    if command -v docker &>/dev/null; then
        log_ok "Docker already installed"
    else
        log_info "Installing Docker..."
        sudo apt-get update -qq
        sudo apt-get install -y -qq docker.io docker-compose-plugin
        sudo systemctl enable docker
        sudo systemctl start docker
        sudo usermod -aG docker "$USER"
        log_ok "Docker installed"
        log_warn "You may need to log out and back in for docker group to take effect"
    fi

    # Ensure Docker daemon is running
    if ! docker info &>/dev/null 2>&1; then
        if sudo docker info &>/dev/null 2>&1; then
            log_warn "Docker requires sudo — using sudo for this session"
            log_warn "Fix: sudo usermod -aG docker \$USER && logout/login"
        else
            log_info "Starting Docker daemon..."
            sudo systemctl start docker
        fi
    fi
}

# ── Install Docker based on OS ──

case "$OS" in
    mac)   install_docker_mac ;;
    linux) install_docker_linux ;;
    *)     log_error "Unsupported OS: $(uname -s)"; exit 1 ;;
esac

# Resolve docker command (with or without sudo)
DOCKER="docker"
if ! docker info &>/dev/null 2>&1; then
    if sudo docker info &>/dev/null 2>&1; then
        DOCKER="sudo docker"
    else
        log_error "Docker is not running. Start it manually."
        exit 1
    fi
fi

log_ok "Docker is running"

# ── Start Keycloak ──

if $DOCKER ps --format '{{.Names}}' 2>/dev/null | grep -q '^ma-keycloak$'; then
    log_ok "Keycloak container already running"
else
    # Stop and remove old container if exists (stopped)
    $DOCKER rm -f ma-keycloak 2>/dev/null || true

    REALM_MOUNT=""
    if [ -f "$REALM_FILE" ]; then
        REALM_MOUNT="-v $REALM_FILE:/opt/keycloak/data/import/realm-multi-agent.json:ro"
        log_info "Realm file found: $REALM_FILE"
    else
        log_warn "No realm file at $REALM_FILE — Keycloak will start without auto-import"
    fi

    log_info "Starting Keycloak container..."
    $DOCKER run -d --name ma-keycloak \
        -p 127.0.0.1:8080:8080 \
        -e KEYCLOAK_ADMIN=admin \
        -e KEYCLOAK_ADMIN_PASSWORD=admin \
        -e KC_HEALTH_ENABLED=true \
        $REALM_MOUNT \
        -v ma-keycloak-data:/opt/keycloak/data \
        --restart unless-stopped \
        quay.io/keycloak/keycloak:23.0 start-dev --import-realm

    log_ok "Keycloak container started"
fi

# ── Health check ──

log_info "Waiting for Keycloak to be ready..."
MAX_WAIT=120
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "http://localhost:8080/health/ready" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        log_ok "Keycloak is ready! (${ELAPSED}s)"
        break
    fi
    sleep 3
    ELAPSED=$((ELAPSED + 3))
    if [ $((ELAPSED % 15)) -eq 0 ]; then
        log_info "  Still waiting... (${ELAPSED}s, HTTP $HTTP_CODE)"
    fi
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
    log_error "Keycloak did not become ready within ${MAX_WAIT}s"
    log_info "Check logs: $DOCKER logs ma-keycloak"
    exit 1
fi

# ── Summary ──

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}   KEYCLOAK INSTALLED AND READY${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Admin console: http://localhost:8080/admin"
echo "  Admin user:    admin / admin"
echo "  Health check:  http://localhost:8080/health/ready"
echo ""
echo "  Change password:"
echo "    ./framework/change_passwd_keycloak.sh <username> <new-password>"
echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
