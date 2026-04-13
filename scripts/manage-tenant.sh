#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Weighbridge Multi-Tenant Management Script (Linux/macOS)
# Usage:
#   ./manage-tenant.sh create  --slug acme --name "Acme Corp" --password Admin123 --company "Acme Crushers"
#   ./manage-tenant.sh list
#   ./manage-tenant.sh backup  --slug acme
#   ./manage-tenant.sh backup-all
#   ./manage-tenant.sh status
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# Configuration (override via environment variables)
API_URL="${API_URL:-http://localhost:9001}"
SUPER_ADMIN_SECRET="${SUPER_ADMIN_SECRET:-}"
PG_CONTAINER="${PG_CONTAINER:-weighbridge_db}"
PG_USER="${PG_USER:-weighbridge}"
PG_PASSWORD="${PG_PASSWORD:-weighbridge_dev_2024}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║   Weighbridge Multi-Tenant Manager (Linux)   ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"
    echo ""
}

usage() {
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  create      Create a new tenant"
    echo "  list        List all tenants"
    echo "  backup      Backup a specific tenant"
    echo "  backup-all  Backup all active tenants"
    echo "  status      Show system status"
    echo ""
    echo "Create options:"
    echo "  --slug <slug>         Tenant slug (lowercase, 3-31 chars)"
    echo "  --name <name>         Display name"
    echo "  --password <pw>       Admin password"
    echo "  --company <name>      Company name"
    echo "  --admin-user <user>   Admin username (default: admin)"
    echo ""
    echo "Backup options:"
    echo "  --slug <slug>         Tenant slug to backup"
    echo ""
    echo "Environment variables:"
    echo "  API_URL              Backend API URL (default: http://localhost:9001)"
    echo "  SUPER_ADMIN_SECRET   Super admin secret for API auth"
    echo "  PG_CONTAINER         Docker container name (default: weighbridge_db)"
    exit 1
}

check_prereqs() {
    if [ -z "$SUPER_ADMIN_SECRET" ]; then
        echo -e "${RED}Error: SUPER_ADMIN_SECRET environment variable is required${NC}"
        echo "Set it with: export SUPER_ADMIN_SECRET='your-secret-here'"
        exit 1
    fi
}

api_call() {
    local method="$1"
    local endpoint="$2"
    local data="${3:-}"

    local args=(-s -w "\n%{http_code}" -H "X-Super-Admin: $SUPER_ADMIN_SECRET" -H "Content-Type: application/json")

    if [ "$method" = "POST" ] && [ -n "$data" ]; then
        args+=(-X POST -d "$data")
    elif [ "$method" = "GET" ]; then
        args+=(-X GET)
    fi

    local response
    response=$(curl "${args[@]}" "${API_URL}${endpoint}")
    local http_code
    http_code=$(echo "$response" | tail -n1)
    local body
    body=$(echo "$response" | sed '$d')

    if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 300 ]; then
        echo "$body"
        return 0
    else
        echo -e "${RED}API Error (HTTP $http_code): $body${NC}" >&2
        return 1
    fi
}

cmd_create() {
    local slug="" name="" password="" company="" admin_user="admin"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --slug)      slug="$2"; shift 2 ;;
            --name)      name="$2"; shift 2 ;;
            --password)  password="$2"; shift 2 ;;
            --company)   company="$2"; shift 2 ;;
            --admin-user) admin_user="$2"; shift 2 ;;
            *) echo "Unknown option: $1"; usage ;;
        esac
    done

    if [ -z "$slug" ] || [ -z "$name" ] || [ -z "$password" ] || [ -z "$company" ]; then
        echo -e "${RED}Error: --slug, --name, --password, and --company are required${NC}"
        usage
    fi

    echo -e "${YELLOW}Creating tenant: ${slug}${NC}"
    local payload
    payload=$(cat <<EOF
{
    "slug": "$slug",
    "display_name": "$name",
    "admin_username": "$admin_user",
    "admin_password": "$password",
    "company_name": "$company"
}
EOF
)

    local result
    if result=$(api_call POST "/api/v1/admin/tenants" "$payload"); then
        echo -e "${GREEN}Tenant created successfully!${NC}"
        echo "$result" | python3 -m json.tool 2>/dev/null || echo "$result"
        echo ""
        echo -e "${CYAN}Login with:${NC}"
        echo "  Tenant slug: $slug"
        echo "  Username:    $admin_user"
        echo "  Password:    (as provided)"
    fi
}

cmd_list() {
    echo -e "${YELLOW}Listing all tenants...${NC}"
    local result
    if result=$(api_call GET "/api/v1/admin/tenants"); then
        echo "$result" | python3 -m json.tool 2>/dev/null || echo "$result"
    fi
}

cmd_backup() {
    local slug=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --slug) slug="$2"; shift 2 ;;
            *) echo "Unknown option: $1"; usage ;;
        esac
    done

    if [ -z "$slug" ]; then
        echo -e "${RED}Error: --slug is required${NC}"
        usage
    fi

    echo -e "${YELLOW}Backing up tenant: ${slug}${NC}"
    mkdir -p "$BACKUP_DIR"

    local timestamp
    timestamp=$(date +%Y%m%d_%H%M%S)
    local filename="tenant_${slug}_${timestamp}.sql"
    local filepath="${BACKUP_DIR}/${filename}"

    docker exec -e PGPASSWORD="$PG_PASSWORD" "$PG_CONTAINER" \
        pg_dump -U "$PG_USER" -d "wb_${slug}" --no-owner --no-acl \
        > "$filepath"

    local size
    size=$(du -h "$filepath" | cut -f1)
    echo -e "${GREEN}Backup created: ${filepath} (${size})${NC}"
}

cmd_backup_all() {
    echo -e "${YELLOW}Backing up all tenants...${NC}"
    mkdir -p "$BACKUP_DIR"

    # Get list of tenant databases
    local dbs
    dbs=$(docker exec -e PGPASSWORD="$PG_PASSWORD" "$PG_CONTAINER" \
        psql -U "$PG_USER" -d postgres -tAc \
        "SELECT datname FROM pg_database WHERE datname LIKE 'wb_%' ORDER BY datname")

    if [ -z "$dbs" ]; then
        echo -e "${YELLOW}No tenant databases found.${NC}"
        return
    fi

    local timestamp
    timestamp=$(date +%Y%m%d_%H%M%S)
    local count=0

    while IFS= read -r db; do
        local slug="${db#wb_}"
        local filename="tenant_${slug}_${timestamp}.sql"
        local filepath="${BACKUP_DIR}/${filename}"

        echo -n "  Backing up ${slug}... "
        docker exec -e PGPASSWORD="$PG_PASSWORD" "$PG_CONTAINER" \
            pg_dump -U "$PG_USER" -d "$db" --no-owner --no-acl \
            > "$filepath"
        local size
        size=$(du -h "$filepath" | cut -f1)
        echo -e "${GREEN}OK (${size})${NC}"
        count=$((count + 1))
    done <<< "$dbs"

    echo -e "${GREEN}Backed up ${count} tenant(s) to ${BACKUP_DIR}/${NC}"
}

cmd_status() {
    echo -e "${YELLOW}System Status${NC}"
    echo "─────────────────────────────────────"

    # Docker
    if docker ps --filter "name=$PG_CONTAINER" --format '{{.Status}}' | grep -q "Up"; then
        echo -e "  PostgreSQL: ${GREEN}Running${NC}"
    else
        echo -e "  PostgreSQL: ${RED}Stopped${NC}"
    fi

    # Backend health
    local health
    if health=$(curl -s --max-time 5 "${API_URL}/api/v1/health" 2>/dev/null); then
        local status
        status=$(echo "$health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null)
        local mt
        mt=$(echo "$health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('multi_tenant',False))" 2>/dev/null)
        echo -e "  Backend:    ${GREEN}${status}${NC}"
        echo -e "  Multi-tenant: ${CYAN}${mt}${NC}"
    else
        echo -e "  Backend:    ${RED}Unreachable${NC}"
    fi

    # Count tenant databases
    local count
    count=$(docker exec -e PGPASSWORD="$PG_PASSWORD" "$PG_CONTAINER" \
        psql -U "$PG_USER" -d postgres -tAc \
        "SELECT COUNT(*) FROM pg_database WHERE datname LIKE 'wb_%'" 2>/dev/null || echo "?")
    echo -e "  Tenant DBs: ${CYAN}${count}${NC}"
    echo ""
}

# ── Main ─────────────────────────────────────────────────────────────────────
print_header

if [ $# -eq 0 ]; then
    usage
fi

COMMAND="$1"
shift

case "$COMMAND" in
    create)
        check_prereqs
        cmd_create "$@"
        ;;
    list)
        check_prereqs
        cmd_list
        ;;
    backup)
        cmd_backup "$@"
        ;;
    backup-all)
        cmd_backup_all
        ;;
    status)
        cmd_status
        ;;
    *)
        echo -e "${RED}Unknown command: ${COMMAND}${NC}"
        usage
        ;;
esac
