#!/bin/bash
# install_redis.sh - Install Docker + Redis on Mac or Ubuntu
# Usage: ./setup/install_redis.sh

set -e

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
    colima start --memory 2 --cpu 2
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

    if ! docker info &>/dev/null 2>&1; then
        if sudo docker info &>/dev/null 2>&1; then
            log_warn "Docker requires sudo — using sudo for this session"
        else
            log_info "Starting Docker daemon..."
            sudo systemctl start docker
        fi
    fi
}

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

# ── Start Redis ──

if $DOCKER ps --format '{{.Names}}' 2>/dev/null | grep -q '^ma-redis$'; then
    log_ok "Redis container already running"
else
    $DOCKER rm -f ma-redis 2>/dev/null || true

    log_info "Starting Redis container..."
    $DOCKER run -d --name ma-redis \
        -p 127.0.0.1:6379:6379 \
        -v ma-redis-data:/data \
        --restart unless-stopped \
        redis:7-alpine \
        redis-server --appendonly yes

    log_ok "Redis container started"
fi

# ── Health check ──

log_info "Waiting for Redis to be ready..."
MAX_WAIT=30
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
    if $DOCKER exec ma-redis redis-cli ping 2>/dev/null | grep -q PONG; then
        log_ok "Redis is ready! (${ELAPSED}s)"
        break
    fi
    sleep 1
    ELAPSED=$((ELAPSED + 1))
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
    log_error "Redis did not become ready within ${MAX_WAIT}s"
    log_info "Check logs: $DOCKER logs ma-redis"
    exit 1
fi

# ── Summary ──

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}   REDIS INSTALLED AND READY${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Host:    127.0.0.1:6379"
echo "  Volume:  ma-redis-data (persistent)"
echo ""
echo "  Test:    redis-cli ping"
echo "  Logs:    docker logs ma-redis"
echo "  Stop:    docker stop ma-redis"
echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
