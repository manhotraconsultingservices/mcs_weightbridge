#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Weighbridge Docker + Multi-Tenant Setup Script (Linux)
# Sets up PostgreSQL in Docker, initializes master DB, and starts backend.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_DIR/backend"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   Weighbridge Docker Setup (Linux)            ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: Check Docker ────────────────────────────────────────────────────
echo -e "${YELLOW}[1/6] Checking Docker...${NC}"
if ! command -v docker &>/dev/null; then
    echo -e "${RED}Docker not found. Install Docker first:${NC}"
    echo "  curl -fsSL https://get.docker.com | sh"
    echo "  sudo usermod -aG docker \$USER"
    exit 1
fi

if ! docker info &>/dev/null; then
    echo -e "${RED}Docker daemon not running. Start it with:${NC}"
    echo "  sudo systemctl start docker"
    exit 1
fi

echo -e "${GREEN}  Docker OK: $(docker --version)${NC}"

# ── Step 2: Create data directory ────────────────────────────────────────────
echo -e "${YELLOW}[2/6] Setting up data directory...${NC}"
DATA_DIR="/data/pgdata"
if [ ! -d "$DATA_DIR" ]; then
    sudo mkdir -p "$DATA_DIR"
    sudo chown "$(id -u):$(id -g)" "$DATA_DIR"
    echo -e "${GREEN}  Created $DATA_DIR${NC}"
else
    echo -e "${GREEN}  $DATA_DIR already exists${NC}"
fi

# ── Step 3: Make init script executable ──────────────────────────────────────
echo -e "${YELLOW}[3/6] Preparing init scripts...${NC}"
chmod +x "$PROJECT_DIR/docker/init-multi-db.sh" 2>/dev/null || true
echo -e "${GREEN}  Init scripts ready${NC}"

# ── Step 4: Start PostgreSQL ────────────────────────────────────────────────
echo -e "${YELLOW}[4/6] Starting PostgreSQL container...${NC}"
cd "$PROJECT_DIR"

# Check if container already running
if docker ps --filter "name=weighbridge_db" --format '{{.Status}}' | grep -q "Up"; then
    echo -e "${GREEN}  PostgreSQL already running${NC}"
else
    docker compose up -d db
    echo -n "  Waiting for PostgreSQL to be ready"
    for i in $(seq 1 30); do
        if docker exec weighbridge_db pg_isready -U weighbridge &>/dev/null; then
            echo ""
            echo -e "${GREEN}  PostgreSQL is ready!${NC}"
            break
        fi
        echo -n "."
        sleep 1
    done
fi

# ── Step 5: Verify master database ──────────────────────────────────────────
echo -e "${YELLOW}[5/6] Verifying master database...${NC}"
MASTER_EXISTS=$(docker exec -e PGPASSWORD=weighbridge_dev_2024 weighbridge_db \
    psql -U weighbridge -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname = 'weighbridge_master'" 2>/dev/null || echo "")

if [ "$MASTER_EXISTS" = "1" ]; then
    echo -e "${GREEN}  weighbridge_master database exists${NC}"
else
    echo "  Creating weighbridge_master database..."
    docker exec -e PGPASSWORD=weighbridge_dev_2024 weighbridge_db \
        psql -U weighbridge -d postgres -c \
        "CREATE DATABASE weighbridge_master OWNER weighbridge"
    echo -e "${GREEN}  weighbridge_master created${NC}"
fi

# ── Step 6: Create .env if needed ────────────────────────────────────────────
echo -e "${YELLOW}[6/6] Checking backend configuration...${NC}"
ENV_FILE="$BACKEND_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" <<'ENVEOF'
DATABASE_URL=postgresql+asyncpg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge
DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge
SECRET_KEY=change-this-to-a-random-secret
MULTI_TENANT=true
MASTER_DATABASE_URL=postgresql+asyncpg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge_master
MASTER_DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge_master
SUPER_ADMIN_SECRET=change-this-to-a-strong-secret
ENVEOF
    echo -e "${GREEN}  Created $ENV_FILE (edit SUPER_ADMIN_SECRET!)${NC}"
else
    echo -e "${GREEN}  $ENV_FILE already exists${NC}"
fi

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Setup Complete!                             ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo "Next steps:"
echo "  1. Edit $ENV_FILE and set SUPER_ADMIN_SECRET"
echo "  2. Start backend:"
echo "     cd $BACKEND_DIR && uvicorn app.main:app --host 0.0.0.0 --port 9001"
echo "  3. Create your first tenant:"
echo "     export SUPER_ADMIN_SECRET='your-secret'"
echo "     $SCRIPT_DIR/manage-tenant.sh create --slug demo --name 'Demo Corp' --password Admin123 --company 'Demo Crushers'"
echo ""
