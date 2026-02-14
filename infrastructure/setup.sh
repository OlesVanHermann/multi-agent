#!/bin/bash
set -e

# ===========================================
# Multi-Agent System - Setup
# ===========================================

echo "Multi-Agent System - Setup"
echo "=========================="
echo ""

cd "$(dirname "$0")"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

ok() { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
err() { echo -e "${RED}✗${NC} $1"; }

# 1. Check dependencies
echo "Checking dependencies..."

if ! command -v docker &> /dev/null; then
    err "Docker not found. Install Docker Desktop: https://docker.com/products/docker-desktop"
    exit 1
fi
ok "Docker"

if ! command -v python3 &> /dev/null; then
    err "Python3 not found"
    exit 1
fi
ok "Python3"

# Check/install Python packages
echo ""
echo "Checking Python packages..."
python3 -c "import redis" 2>/dev/null || {
    warn "Installing redis Python package..."
    pip3 install redis --quiet
}
ok "Redis Python package"

# 2. Setup mode
echo ""
echo "Setup mode:"
echo "  1) Standalone (Redis only, local development)"
echo "  2) Full (Redis + Dashboard + Bridge for multi-VM)"
echo ""
read -p "Choose [1]: " mode
mode=${mode:-1}

if [[ "$mode" == "2" ]]; then
    # Full setup with .env.mac
    if [[ ! -f .env.mac ]]; then
        echo ""
        echo "Creating .env.mac for multi-VM setup..."

        read -p "Remote VM IP address: " vm_host
        read -p "Remote VM SSH user [ubuntu]: " vm_user
        vm_user=${vm_user:-ubuntu}
        read -p "SSH key path [~/.ssh/id_rsa]: " ssh_key
        ssh_key=${ssh_key:-~/.ssh/id_rsa}

        cat > .env.mac << EOF
VM_HOST=$vm_host
VM_USER=$vm_user
VM_SSH_PORT=22
SSH_KEY_PATH=$ssh_key
EOF
        ok "Created .env.mac"
    else
        ok ".env.mac exists"
    fi

    # Build all images
    echo ""
    echo "Building Docker images (Redis + Dashboard + Bridge)..."
    docker compose -f docker-compose.yml build
    ok "Docker images built"

    START_CMD="./multi-agent.sh start full"
else
    # Standalone - just Redis
    ok "Standalone mode - no extra config needed"
    START_CMD="./multi-agent.sh start standalone"
fi

# 3. Create directories
echo ""
mkdir -p ../sessions ../logs ../pool-requests/{pending,assigned,done,specs,tests,knowledge,state}
ok "Directories created"

# 4. Make scripts executable
chmod +x multi-agent.sh
chmod +x ../scripts/*.sh 2>/dev/null || true
ok "Scripts executable"

# 5. Initialize NEXT_ID if needed
[[ ! -f ../pool-requests/NEXT_ID ]] && echo "1" > ../pool-requests/NEXT_ID
ok "Pool requests initialized"

echo ""
echo "========================================="
echo -e "${GREEN}✅ Setup complete!${NC}"
echo ""
echo "Next steps:"
echo ""
echo "1. Start infrastructure:"
echo "   cd infrastructure"
echo "   $START_CMD"
echo ""
echo "2. Configure your project with the Architect:"
echo "   cd .."
echo "   claude"
echo "   > Lis prompts/000-architect.md"
echo ""
echo "3. Launch agents:"
echo "   ./scripts/start-agents.sh"
echo ""
if [[ "$mode" == "2" ]]; then
echo "4. Dashboard: http://127.0.0.1:8080"
echo ""
fi
echo "========================================="
