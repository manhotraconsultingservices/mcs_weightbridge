#!/bin/bash
# ════════════════════════════════════════════════════════════════════════════
#  CI/CD deploy script — called by .github/workflows/deploy.yml over SSH
#
#  What it does:
#   1. Pulls latest main into /opt/weighbridge
#   2. Decides what's changed (frontend / backend / both / nothing material)
#   3. Re-installs dependencies + rebuilds only what's affected
#   4. Restarts the FastAPI systemd unit if backend changed
#   5. Replaces nginx docroot if frontend changed
#   6. Reloads nginx (cheap, always)
#   7. Hits /api/v1/health to verify the backend is up — exits non-zero if not
#   8. Appends a one-line summary to /var/log/weighbridge-deploy.log
#
#  Designed to be idempotent and safe to re-run. Concurrency is enforced by
#  the workflow's `concurrency: deploy-vps` group, but a flock guard is also
#  in place here so manual reruns can't collide with a CI run in flight.
#
#  Usage (CI):     ssh root@vps "bash /opt/weighbridge/scripts/ci-deploy.sh"
#  Usage (manual): cd /opt/weighbridge && bash scripts/ci-deploy.sh
#
#  Environment overrides (optional):
#    APP_DIR        default /opt/weighbridge
#    FRONTEND_DIR   default /var/www/weighbridge
#    SERVICE        default weighbridge (systemd unit name)
#    HEALTH_URL     default http://127.0.0.1:9001/api/v1/health
#    LOG_FILE       default /var/log/weighbridge-deploy.log
# ════════════════════════════════════════════════════════════════════════════
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/weighbridge}"
FRONTEND_DIR="${FRONTEND_DIR:-/var/www/weighbridge}"
SERVICE="${SERVICE:-weighbridge}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:9001/api/v1/health}"
LOG_FILE="${LOG_FILE:-/var/log/weighbridge-deploy.log}"
LOCK_FILE="/var/lock/weighbridge-deploy.lock"
# Marker recording the commit we last actually BUILT + promoted to nginx.
# Change detection compares the new HEAD against this, NOT against git's
# pre-pull HEAD — so a manual `git pull` on the VPS (which leaves the script's
# own reset a no-op) can never trick us into skipping a rebuild. If the marker
# is missing (first run after this change, or a fresh box) we rebuild both
# sides unconditionally, which is the safe default.
DEPLOY_MARKER="${DEPLOY_MARKER:-$APP_DIR/.last_deployed_sha}"
# Set FORCE_BUILD=1 in the environment to rebuild both sides regardless.
FORCE_BUILD="${FORCE_BUILD:-0}"

# ── Concurrency guard — block parallel deploys ─────────────────────────────
exec 9>"$LOCK_FILE"
flock -n 9 || { echo "❌ Another deploy is already running. Aborting."; exit 1; }

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
log() { echo "[$(ts)] $*" | tee -a "$LOG_FILE" >&2; }

START_TS=$(ts)
log "━━━ CI/CD deploy started"

cd "$APP_DIR"

# Capture commit hashes for logging + summary
BEFORE=$(git rev-parse HEAD 2>/dev/null || echo "none")
log "  Git HEAD before pull: $BEFORE"

# Hard reset to remote main — this discards any local commits on the VPS.
# That's intentional: the VPS is a deploy target, not a dev environment.
git fetch --quiet origin main
git reset --hard --quiet origin/main
AFTER=$(git rev-parse HEAD)
log "  Git HEAD after pull:  $AFTER"

# What did we LAST successfully build + promote? (not the pre-pull HEAD)
LAST_DEPLOYED=$(cat "$DEPLOY_MARKER" 2>/dev/null || echo "none")
log "  Last deployed commit: $LAST_DEPLOYED"

if [ "$FORCE_BUILD" != "1" ] && [ "$LAST_DEPLOYED" = "$AFTER" ]; then
    log "  Already deployed $AFTER — nothing to do. Still running nginx -t for sanity."
    nginx -t > /dev/null 2>&1 && systemctl reload nginx
    log "✅ No-op deploy complete in $(($(date +%s) - $(date -d "$START_TS" +%s)))s"
    exit 0
fi

# ── Decide what changed (vs last DEPLOYED commit, not pre-pull HEAD) ─────────
# git diff returns one filename per line. Use grep -c to count, not -E so the
# empty regex case can't false-positive.
if [ "$FORCE_BUILD" = "1" ] || [ "$LAST_DEPLOYED" = "none" ]; then
    log "  $([ "$FORCE_BUILD" = "1" ] && echo "FORCE_BUILD set" || echo "No deploy marker") — rebuilding both sides"
    FRONTEND_CHANGED=1
    BACKEND_CHANGED=1
    REQ_CHANGED=1
else
    CHANGES=$(git diff --name-only "$LAST_DEPLOYED" "$AFTER" || echo "")
    FRONTEND_CHANGED=$(echo "$CHANGES" | grep -c '^frontend/' || true)
    BACKEND_CHANGED=$(echo "$CHANGES" | grep -c '^backend/' || true)
    REQ_CHANGED=$(echo "$CHANGES" | grep -c '^backend/requirements.txt$' || true)
fi
log "  Frontend changed: $FRONTEND_CHANGED file(s)"
log "  Backend changed:  $BACKEND_CHANGED file(s)"

# ── Backend update ──────────────────────────────────────────────────────────
if [ "$BACKEND_CHANGED" -gt 0 ]; then
    log "→ Updating backend"
    cd "$APP_DIR/backend"
    if [ ! -d venv ]; then
        log "  No venv found — creating one"
        python3 -m venv venv
    fi
    # Re-install deps only if requirements.txt changed (saves ~10s on most deploys)
    if [ "${REQ_CHANGED:-1}" -gt 0 ]; then
        log "  pip install -r requirements.txt"
        ./venv/bin/pip install -q --upgrade pip
        ./venv/bin/pip install -q -r requirements.txt
    else
        log "  requirements.txt unchanged — skipping pip install"
    fi
    log "  Restarting systemd service '$SERVICE'"
    systemctl restart "$SERVICE"
    # Brief settle so health check below is meaningful
    sleep 3
else
    log "→ Backend unchanged — service untouched"
fi

# ── Frontend update ─────────────────────────────────────────────────────────
if [ "$FRONTEND_CHANGED" -gt 0 ]; then
    log "→ Updating frontend"
    cd "$APP_DIR/frontend"
    log "  npm ci  (clean install matching package-lock.json)"
    npm ci --silent --no-audit --no-fund
    log "  npm run build"
    npm run build 2>&1 | tail -5 | tee -a "$LOG_FILE"
    if [ ! -f dist/index.html ]; then
        log "❌ Build did not produce dist/index.html — aborting deploy"
        exit 1
    fi
    log "  Promoting dist/ to $FRONTEND_DIR"
    mkdir -p "$FRONTEND_DIR"
    # Use rsync so partial writes don't leave a broken root.
    # Falls back to cp if rsync isn't available.
    if command -v rsync > /dev/null; then
        rsync -a --delete dist/ "$FRONTEND_DIR/"
    else
        rm -rf "$FRONTEND_DIR"/*
        cp -r dist/* "$FRONTEND_DIR/"
    fi
    SIZE=$(du -sh "$FRONTEND_DIR" 2>/dev/null | cut -f1)
    log "  Frontend deployed (size: $SIZE)"
else
    log "→ Frontend unchanged — nginx docroot untouched"
fi

# ── Nginx reload (cheap, always — picks up any cert renewal too) ────────────
log "→ Reloading nginx"
nginx -t > /dev/null 2>&1 && systemctl reload nginx
log "  nginx: $(systemctl is-active nginx)"

# ── Health check ────────────────────────────────────────────────────────────
log "→ Health check ($HEALTH_URL)"
HEALTH_CODE=$(curl --max-time 10 -s -o /tmp/health.out -w "%{http_code}" "$HEALTH_URL" || echo "000")
# 200 = healthy, 503 = degraded-but-up (e.g. weight scale offline). Both OK.
case "$HEALTH_CODE" in
    200|503)
        log "  ✅ Backend responded $HEALTH_CODE"
        ;;
    *)
        log "  ❌ Backend health check returned $HEALTH_CODE — see /tmp/health.out"
        log "  Service status: $(systemctl is-active $SERVICE)"
        log "  Last 20 service log lines:"
        journalctl -u "$SERVICE" -n 20 --no-pager 2>&1 | tail -20 | tee -a "$LOG_FILE"
        exit 1
        ;;
esac

# ── Record what we deployed ─────────────────────────────────────────────────
# Only written after the health check passed, so a failed deploy never advances
# the marker — the next run will retry the rebuild.
echo "$AFTER" > "$DEPLOY_MARKER"

# ── Summary ─────────────────────────────────────────────────────────────────
DURATION=$(( $(date +%s) - $(date -d "$START_TS" +%s) ))
LAST_MSG=$(git log -1 --pretty=format:'%h %s' "$AFTER")
log "✅ Deploy complete in ${DURATION}s — at $LAST_MSG"
echo "DEPLOY_OK ${BEFORE:0:8}->${AFTER:0:8} ${DURATION}s frontend=$FRONTEND_CHANGED backend=$BACKEND_CHANGED" \
    | tee -a "$LOG_FILE"
