"""Device health monitoring — scale + camera heartbeat + Telegram alerting.

A standalone local watchdog agent (backend/agents/watchdog_agent.py) reads the
EXISTING scale/camera agents' /status endpoints, probes the cameras, and POSTs a
heartbeat here per device. The server stores per-device health, powers a
dashboard (GET /monitor/health), and a background loop (_device_health_loop in
main.py) fires a Telegram alert when a device stays down / silent past a
configurable threshold. No change to the scale or camera agents is required.
"""
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_tenant_session
from app.dependencies import get_current_user, require_role
from app.models.user import User
from app.config import get_settings

router = APIRouter(prefix="/api/v1/monitor", tags=["Device Health"])

CONFIG_KEY = "device_health"
DEFAULT_CONFIG = {"enabled": True, "down_threshold_min": 5, "stale_min": 3}


def _merge_cfg(raw: str | None) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if raw:
        try:
            v = json.loads(raw)
            if isinstance(v, dict):
                cfg.update(v)
        except Exception:
            pass
    # sanitise
    cfg["enabled"] = bool(cfg.get("enabled", True))
    cfg["down_threshold_min"] = max(1, int(cfg.get("down_threshold_min", 5)))
    cfg["stale_min"] = max(1, int(cfg.get("stale_min", 3)))
    return cfg


async def _load_config(db: AsyncSession) -> dict:
    row = (await db.execute(
        text("SELECT value FROM app_settings WHERE key = :k"), {"k": CONFIG_KEY}
    )).fetchone()
    return _merge_cfg(row[0] if row else None)


# ── Agent heartbeat ingest (agent-key auth, no JWT) ──────────────────────────
@router.post("/heartbeat")
async def heartbeat(payload: dict[str, Any]):
    """The watchdog agent pushes per-device health. Body:
        { tenant, agent_key, site, devices: [{key, type, label, ok, error}] }
    Auth mirrors the scale/gate agent push — agent_key is validated against the
    tenant registry; the request carries no JWT and sets no middleware context, so
    the tenant session is opened explicitly.
    """
    settings = get_settings()
    slug: str | None = None
    if settings.MULTI_TENANT:
        slug = (payload.get("tenant") or payload.get("tenant_slug") or "").strip().lower()
        agent_key = payload.get("agent_key")
        if not slug or not agent_key:
            raise HTTPException(400, "tenant and agent_key required in multi-tenant mode")
        from app.multitenancy.registry import tenant_registry
        if not await tenant_registry.validate_agent_key(slug, agent_key):
            raise HTTPException(403, "Invalid agent key for tenant")

    devices = payload.get("devices")
    if not isinstance(devices, list):
        raise HTTPException(400, "devices must be a list")
    site = (str(payload.get("site") or "").strip()[:80]) or None

    async with (await get_tenant_session(slug)) as db:
        co = (await db.execute(text("SELECT id FROM companies LIMIT 1"))).fetchone()
        if not co:
            raise HTTPException(400, "No company configured")
        cid = str(co[0])
        n = 0
        for d in devices:
            if not isinstance(d, dict):
                continue
            key = str(d.get("key") or "").strip()[:80]
            if not key:
                continue
            dtype = (str(d.get("type") or "camera").strip().lower())[:20]
            label = (str(d.get("label") or key).strip())[:120]
            ok = bool(d.get("ok"))
            err = (str(d.get("error") or "").strip() or None)
            if err:
                err = err[:300]
            await db.execute(text("""
                INSERT INTO device_health
                    (company_id, device_key, device_type, label, site, status,
                     last_seen_at, last_ok_at, last_error, alerted, updated_at)
                VALUES
                    (:cid, :key, :type, :label, :site, :status,
                     NOW(), NOW(), :err, FALSE, NOW())
                ON CONFLICT (company_id, device_key) DO UPDATE SET
                    device_type  = EXCLUDED.device_type,
                    label        = EXCLUDED.label,
                    site         = COALESCE(EXCLUDED.site, device_health.site),
                    status       = EXCLUDED.status,
                    last_seen_at = NOW(),
                    last_ok_at   = CASE WHEN :ok THEN NOW() ELSE device_health.last_ok_at END,
                    last_error   = :err,
                    updated_at   = NOW()
            """), {
                "cid": cid, "key": key, "type": dtype, "label": label, "site": site,
                "status": ("ok" if ok else "down"), "ok": ok, "err": err,
            })
            n += 1
        await db.commit()
        return {"ok": True, "count": n}


# ── Dashboard feed (JWT) ─────────────────────────────────────────────────────
@router.get("/health")
async def get_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Live status of every monitored device for the current company."""
    cfg = await _load_config(db)
    stale_secs = cfg["stale_min"] * 60
    rows = (await db.execute(text("""
        SELECT device_key, device_type, label, site, status, last_seen_at, last_ok_at, last_error,
               EXTRACT(EPOCH FROM (NOW() - last_seen_at)) AS age_secs
        FROM device_health
        WHERE company_id = :cid
        ORDER BY device_type, site, label
    """), {"cid": str(current_user.company_id)})).fetchall()

    devices = []
    for r in rows:
        age = float(r.age_secs) if r.age_secs is not None else None
        if age is None or age > stale_secs:
            eff = "stale"     # no heartbeat recently → watchdog/PC likely offline
        elif r.status == "down":
            eff = "offline"   # heartbeat fresh but the device itself is failing
        else:
            eff = "online"
        devices.append({
            "device_key": r.device_key,
            "device_type": r.device_type,
            "label": r.label,
            "site": r.site,
            "status": eff,
            "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
            "last_seen_age_secs": int(age) if age is not None else None,
            "last_ok_at": r.last_ok_at.isoformat() if r.last_ok_at else None,
            "last_error": r.last_error,
        })
    online = sum(1 for d in devices if d["status"] == "online")
    return {
        "devices": devices,
        "summary": {"total": len(devices), "online": online, "down": len(devices) - online},
        "config": cfg,
    }


# ── Config (admin) ───────────────────────────────────────────────────────────
@router.get("/config")
async def get_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await _load_config(db)


@router.put("/config")
async def put_config(
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    cfg = await _load_config(db)
    if "enabled" in payload:
        cfg["enabled"] = bool(payload["enabled"])
    if "down_threshold_min" in payload:
        cfg["down_threshold_min"] = max(1, int(payload["down_threshold_min"]))
    if "stale_min" in payload:
        cfg["stale_min"] = max(1, int(payload["stale_min"]))
    await db.execute(text("""
        INSERT INTO app_settings (key, value, updated_at) VALUES (:k, :v, NOW())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
    """), {"k": CONFIG_KEY, "v": json.dumps(cfg)})
    await db.commit()
    return cfg


# ── Remove a stale / decommissioned device from the dashboard (admin) ─────────
@router.delete("/devices/{device_key}")
async def delete_device(
    device_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Delete one device's health row for this company.

    Use to clear a device that no longer exists (e.g. a scale wrongly listed in a
    PC's watchdog config). IMPORTANT: first remove it from that PC's
    watchdog_agent.json + restart the watchdog — otherwise its next heartbeat
    (~30 s) re-creates the row here.
    """
    res = await db.execute(text("""
        DELETE FROM device_health
        WHERE company_id = :cid AND device_key = :k
    """), {"cid": str(current_user.company_id), "k": device_key})
    await db.commit()
    return {"ok": True, "deleted": res.rowcount or 0, "device_key": device_key}
