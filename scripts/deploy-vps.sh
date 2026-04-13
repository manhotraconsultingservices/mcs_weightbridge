#!/bin/bash
# ============================================================================
# Weighbridge SaaS — Full VPS Deployment Script
# Target: Ubuntu 24.04 LTS (Hostinger KVM 2)
# Domain: weighbridgesetu.com (Cloudflare DNS)
# ============================================================================
set -e

# ── Configuration ────────────────────────────────────────────────────────────
REPO_URL="https://github.com/manhotraconsultingservices/mcs_weightbridge.git"
APP_DIR="/opt/weighbridge"
FRONTEND_DIR="/var/www/weighbridge"
PG_DATA="/data/pgdata"
PG_USER="weighbridge"
PG_PASS="weighbridge_prod_2026"
SECRET_KEY=$(openssl rand -hex 32)
SUPER_ADMIN_SECRET=$(openssl rand -hex 24)
PLATFORM_ADMIN_USER="platform_admin"
PLATFORM_ADMIN_PASSWORD="MCS@Admin2026"
DOMAIN="weighbridgesetu.com"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     Weighbridge SaaS — VPS Deployment                      ║"
echo "║     Domain: $DOMAIN                                        ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: System packages ─────────────────────────────────────────────────
echo "━━━ Step 1/10: Installing system packages ━━━"
apt update -qq
apt install -y -qq git curl wget nginx python3 python3-venv python3-pip \
    docker.io docker-compose-v2 ufw jq \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 \
    libffi-dev libcairo2 libpq-dev gcc python3-dev > /dev/null 2>&1

# Install Node.js 20 LTS (if not already installed or too old)
if ! command -v node &> /dev/null || [[ $(node -v | cut -d. -f1 | tr -d v) -lt 18 ]]; then
    echo "  Installing Node.js 20 LTS..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - > /dev/null 2>&1
    apt install -y -qq nodejs > /dev/null 2>&1
fi

systemctl enable docker nginx > /dev/null 2>&1
systemctl start docker
echo "  ✓ Packages installed (Python $(python3 --version | cut -d' ' -f2), Node $(node -v), Docker $(docker --version | cut -d' ' -f3 | tr -d ','))"

# ── Step 2: Firewall ────────────────────────────────────────────────────────
echo ""
echo "━━━ Step 2/10: Configuring firewall ━━━"
ufw allow 22/tcp > /dev/null 2>&1
ufw allow 80/tcp > /dev/null 2>&1
ufw allow 443/tcp > /dev/null 2>&1
echo "y" | ufw enable > /dev/null 2>&1 || true
echo "  ✓ Firewall configured (SSH + HTTP + HTTPS)"

# ── Step 3: Clone repository ────────────────────────────────────────────────
echo ""
echo "━━━ Step 3/10: Cloning repository ━━━"
if [ -d "$APP_DIR/.git" ]; then
    echo "  Repo exists, pulling latest..."
    cd "$APP_DIR"
    git pull origin main
else
    mkdir -p "$APP_DIR"
    git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"
echo "  ✓ Repository at $APP_DIR ($(git log --oneline -1))"

# ── Step 4: PostgreSQL via Docker ────────────────────────────────────────────
echo ""
echo "━━━ Step 4/10: Starting PostgreSQL ━━━"
mkdir -p "$PG_DATA"

# Update docker-compose with production password
cat > "$APP_DIR/docker-compose.override.yml" << YAML
services:
  db:
    environment:
      POSTGRES_PASSWORD: ${PG_PASS}
    volumes:
      - ${PG_DATA}:/var/lib/postgresql/data
YAML

chmod +x "$APP_DIR/docker/init-multi-db.sh" 2>/dev/null || true
cd "$APP_DIR"
docker compose up -d db
echo "  Waiting for PostgreSQL to be ready..."
for i in {1..30}; do
    if docker exec weighbridge_db pg_isready -U "$PG_USER" > /dev/null 2>&1; then
        echo "  ✓ PostgreSQL is ready"
        break
    fi
    sleep 1
done

# Ensure master database exists
docker exec weighbridge_db psql -U "$PG_USER" -tc "SELECT 1 FROM pg_database WHERE datname = 'weighbridge_master'" | grep -q 1 || \
    docker exec weighbridge_db psql -U "$PG_USER" -c "CREATE DATABASE weighbridge_master OWNER $PG_USER" 2>/dev/null || true
echo "  ✓ weighbridge_master database ensured"

# ── Step 5: Backend setup ────────────────────────────────────────────────────
echo ""
echo "━━━ Step 5/10: Setting up Python backend ━━━"
cd "$APP_DIR/backend"

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q 2>&1 | tail -1
deactivate

# Create production .env
cat > "$APP_DIR/backend/.env" << ENV
DATABASE_URL=postgresql+asyncpg://${PG_USER}:${PG_PASS}@localhost:5432/weighbridge
DATABASE_URL_SYNC=postgresql+psycopg://${PG_USER}:${PG_PASS}@localhost:5432/weighbridge
SECRET_KEY=${SECRET_KEY}
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
MULTI_TENANT=true
MASTER_DATABASE_URL=postgresql+asyncpg://${PG_USER}:${PG_PASS}@localhost:5432/weighbridge_master
MASTER_DATABASE_URL_SYNC=postgresql+psycopg://${PG_USER}:${PG_PASS}@localhost:5432/weighbridge_master
SUPER_ADMIN_SECRET=${SUPER_ADMIN_SECRET}
PLATFORM_ADMIN_USER=${PLATFORM_ADMIN_USER}
PLATFORM_ADMIN_PASSWORD=${PLATFORM_ADMIN_PASSWORD}
TENANT_DB_PREFIX=wb_
TENANT_POOL_SIZE=3
TENANT_MAX_OVERFLOW=5
ENV

echo "  ✓ Backend configured (venv + .env)"

# ── Step 6: Backend systemd service ──────────────────────────────────────────
echo ""
echo "━━━ Step 6/10: Creating systemd service ━━━"
cat > /etc/systemd/system/weighbridge.service << 'SVC'
[Unit]
Description=Weighbridge Backend (FastAPI)
After=docker.service network.target
Requires=docker.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/weighbridge/backend
ExecStart=/opt/weighbridge/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 9001 --workers 2 --log-level info
Restart=always
RestartSec=5
Environment=PATH=/opt/weighbridge/backend/venv/bin:/usr/bin:/usr/local/bin

[Install]
WantedBy=multi-user.target
SVC

systemctl daemon-reload
systemctl enable weighbridge > /dev/null 2>&1
systemctl restart weighbridge

# Wait for backend to be ready
echo "  Waiting for backend to start..."
for i in {1..30}; do
    if curl -s http://localhost:9001/api/v1/health > /dev/null 2>&1; then
        echo "  ✓ Backend is running"
        break
    fi
    sleep 2
done

# Verify health
HEALTH=$(curl -s http://localhost:9001/api/v1/health 2>/dev/null)
echo "  Health: $(echo $HEALTH | jq -r '.status' 2>/dev/null || echo 'checking...')"

# ── Step 7: Frontend build ───────────────────────────────────────────────────
echo ""
echo "━━━ Step 7/10: Building frontend ━━━"
cd "$APP_DIR/frontend"
npm ci --quiet 2>&1 | tail -1
npm run build 2>&1 | tail -3

mkdir -p "$FRONTEND_DIR"
rm -rf "$FRONTEND_DIR"/*
cp -r dist/* "$FRONTEND_DIR/"
echo "  ✓ Frontend built and deployed to $FRONTEND_DIR"

# ── Step 8: Nginx configuration ──────────────────────────────────────────────
echo ""
echo "━━━ Step 8/10: Configuring Nginx ━━━"
cat > /etc/nginx/sites-available/weighbridge << 'NGINX'
server {
    listen 80;
    server_name weighbridgesetu.com *.weighbridgesetu.com;

    # Cloudflare real IP
    set_real_ip_from 173.245.48.0/20;
    set_real_ip_from 103.21.244.0/22;
    set_real_ip_from 103.22.200.0/22;
    set_real_ip_from 103.31.4.0/22;
    set_real_ip_from 141.101.64.0/18;
    set_real_ip_from 108.162.192.0/18;
    set_real_ip_from 190.93.240.0/20;
    set_real_ip_from 188.114.96.0/20;
    set_real_ip_from 197.234.240.0/22;
    set_real_ip_from 198.41.128.0/17;
    set_real_ip_from 162.158.0.0/15;
    set_real_ip_from 104.16.0.0/13;
    set_real_ip_from 104.24.0.0/14;
    set_real_ip_from 172.64.0.0/13;
    set_real_ip_from 131.0.72.0/22;
    real_ip_header CF-Connecting-IP;

    client_max_body_size 20M;

    # API reverse proxy
    location /api/ {
        proxy_pass http://127.0.0.1:9001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    # WebSocket
    location /ws/ {
        proxy_pass http://127.0.0.1:9001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400s;
    }

    # Uploaded files
    location /uploads/ {
        proxy_pass http://127.0.0.1:9001;
        proxy_set_header Host $host;
    }

    # React SPA
    location / {
        root /var/www/weighbridge;
        try_files $uri $uri/ /index.html;

        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff2?)$ {
            expires 30d;
            add_header Cache-Control "public, immutable";
        }
    }
}
NGINX

ln -sf /etc/nginx/sites-available/weighbridge /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t 2>&1 && systemctl reload nginx
echo "  ✓ Nginx configured for $DOMAIN + wildcard subdomains"

# ── Step 9: Create uploads directory ─────────────────────────────────────────
echo ""
echo "━━━ Step 9/10: Creating uploads directory ━━━"
mkdir -p "$APP_DIR/backend/uploads/camera"
mkdir -p "$APP_DIR/backend/uploads/wallpaper"
mkdir -p "$APP_DIR/backend/uploads/compliance"
echo "  ✓ Upload directories created"

# ── Step 10: Verify ──────────────────────────────────────────────────────────
echo ""
echo "━━━ Step 10/10: Verification ━━━"
echo ""

# Check services
echo "  Docker:      $(docker ps --filter name=weighbridge_db --format '{{.Status}}' 2>/dev/null || echo 'NOT RUNNING')"
echo "  Backend:     $(systemctl is-active weighbridge 2>/dev/null)"
echo "  Nginx:       $(systemctl is-active nginx 2>/dev/null)"

# Health check
HEALTH=$(curl -s http://localhost:9001/api/v1/health 2>/dev/null)
echo "  Health:      $(echo $HEALTH | jq -r '.status' 2>/dev/null || echo 'ERROR')"
echo "  Multi-tenant: $(echo $HEALTH | jq -r '.multi_tenant' 2>/dev/null || echo 'unknown')"

# Frontend check
if [ -f "$FRONTEND_DIR/index.html" ]; then
    echo "  Frontend:    deployed ($(du -sh $FRONTEND_DIR | cut -f1))"
else
    echo "  Frontend:    NOT FOUND"
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅ Deployment Complete!                                    ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║                                                            ║"
echo "║  Platform Admin:                                           ║"
echo "║    URL:      https://$DOMAIN/platform                ║"
echo "║    Username: $PLATFORM_ADMIN_USER                    ║"
echo "║    Password: $PLATFORM_ADMIN_PASSWORD                      ║"
echo "║                                                            ║"
echo "║  Super Admin Secret: ${SUPER_ADMIN_SECRET:0:20}...         ║"
echo "║  Secret Key: ${SECRET_KEY:0:20}...                         ║"
echo "║  DB Password: $PG_PASS                                    ║"
echo "║                                                            ║"
echo "║  Next Steps:                                               ║"
echo "║    1. Configure Cloudflare DNS:                            ║"
echo "║       A record @ → 187.127.139.92 (proxied)               ║"
echo "║       A record * → 187.127.139.92 (proxied)               ║"
echo "║    2. Set Cloudflare SSL to 'Flexible'                     ║"
echo "║    3. Login at https://$DOMAIN/platform        ║"
echo "║    4. Onboard your first tenant                            ║"
echo "║                                                            ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "  Credentials saved to: /opt/weighbridge/CREDENTIALS.txt"

# Save credentials
cat > /opt/weighbridge/CREDENTIALS.txt << CREDS
Weighbridge SaaS — Production Credentials
==========================================
Generated: $(date)

Platform Admin Portal: https://$DOMAIN/platform
  Username: $PLATFORM_ADMIN_USER
  Password: $PLATFORM_ADMIN_PASSWORD

Backend .env secrets:
  SECRET_KEY=$SECRET_KEY
  SUPER_ADMIN_SECRET=$SUPER_ADMIN_SECRET
  DB_PASSWORD=$PG_PASS

PostgreSQL:
  Host: localhost:5432
  User: $PG_USER
  Password: $PG_PASS
  Master DB: weighbridge_master
CREDS
chmod 600 /opt/weighbridge/CREDENTIALS.txt
