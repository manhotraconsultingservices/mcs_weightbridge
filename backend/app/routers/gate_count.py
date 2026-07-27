"""Autonomous gate vehicle counting (truck / car / motorcycle / bus).

A separate, additive feature from ANPR and the gate register. The on-site
camera agent runs a lightweight vehicle-detection model on the frames it
already captures, classifies each vehicle, dedups it, and POSTs one event
(with snapshot) here. Direction = which physical camera fired (entry vs exit).

Purpose: an autonomous tally to reconcile against the gate passes the guard
creates manually — "camera counted N vehicles in, guard logged M passes".

Design / safety:
  * Distinct route prefix `/api/v1/vehicle-count` — never touches the existing
    `/api/v1/gate` register.
  * Ingest is agent-key authed (no JWT), mirroring `/gate/push-snapshot`, so the
    `vehicle_count` feature-module gate (which only runs on JWT/tenant-context
    requests) never blocks the agent. Report endpoints are JWT + module-gated.
  * Gated by the `vehicle_count` feature module (default OFF) → inert for every
    existing tenant until switched on. No existing behaviour changes.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
# Reuse the exact gate helpers so config + upload paths stay consistent.
from app.routers.gate import _uploads_base, _ctx_tenant_slug, _get_gate_cam_cfg

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/vehicle-count", tags=["Gate Vehicle Count"])

# Classes the edge model can emit reliably (COCO). A tipper/dumper reads as
# 'truck'. Unknown classes are rejected so junk never lands in the tally.
ALLOWED_CLASSES = {"truck", "car", "motorcycle", "bus", "bicycle", "auto"}


def _parse_dt(s: str | None) -> datetime | None:
    """Parse an ISO8601 / epoch string to an aware UTC datetime; None on failure."""
    if not s:
        return None
    try:
        s = s.strip()
        if s.isdigit():
            return datetime.fromtimestamp(int(s), tz=timezone.utc)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


async def _persist_event(
    wdb: AsyncSession, slug: str | None, position: str, vehicle_class: str,
    confidence: float, detected_at: str, camera_id: str, image: UploadFile | None,
) -> uuid.UUID:
    """Save the snapshot (if any) + insert the event row inside the given session."""
    cid_row = (await wdb.execute(text("SELECT id FROM companies LIMIT 1"))).fetchone()
    if not cid_row:
        raise HTTPException(500, "Company not configured")
    company_id = cid_row[0]

    eid = uuid.uuid4()
    snap_rel: str | None = None
    if image is not None:
        data = await image.read()
        if data:
            day = datetime.now(timezone.utc).strftime("%Y%m%d")
            parts = ["gate", "vehicle"] + ([slug] if slug else []) + [day]
            subdir = os.path.join(*parts)
            abs_dir = os.path.join(_uploads_base(), subdir)
            os.makedirs(abs_dir, exist_ok=True)
            with open(os.path.join(abs_dir, f"{eid}.jpg"), "wb") as f:
                f.write(data)
            snap_rel = "/".join(parts + [f"{eid}.jpg"])

    try:
        conf = round(float(confidence), 3)
    except (TypeError, ValueError):
        conf = 0.0

    await wdb.execute(text("""
        INSERT INTO gate_vehicle_events
          (id, company_id, position, vehicle_class, confidence, snapshot_path,
           source, camera_id, detected_at)
        VALUES
          (:id, :cid, :pos, :cls, :conf, :snap, 'edge_yolo', :cam,
           COALESCE(CAST(:det AS timestamptz), NOW()))
    """), {
        "id": str(eid), "cid": str(company_id), "pos": position, "cls": vehicle_class,
        "conf": conf, "snap": snap_rel, "cam": (camera_id or None),
        "det": _parse_dt(detected_at),
    })
    await wdb.commit()
    return eid


# ════════════════════════════════════════════════════════════════════════════
#  Ingest — agent-key auth (mirrors /gate/push-snapshot); never JWT-gated
# ════════════════════════════════════════════════════════════════════════════

@router.post("/event")
async def ingest_vehicle_event(
    position: str = Form(...),
    vehicle_class: str = Form(...),
    confidence: float = Form(0.0),
    detected_at: str = Form(""),
    camera_id: str = Form(""),
    image: UploadFile | None = File(None),
    tenant_slug: str = Form(""),
    x_gate_agent_key: str | None = Header(None, alias="X-Gate-Agent-Key"),
    x_agent_key: str | None = Header(None, alias="X-Agent-Key"),
    db: AsyncSession = Depends(get_db),
):
    """Called autonomously by the camera agent's vehicle-counter loop. One row
    per counted vehicle, with an optional snapshot. Same auth as push-snapshot."""
    from app.config import get_settings
    settings = get_settings()

    position = (position or "").strip().lower()
    vehicle_class = (vehicle_class or "").strip().lower()
    if position not in ("entry", "exit"):
        raise HTTPException(400, "position must be 'entry' or 'exit'")
    if vehicle_class not in ALLOWED_CLASSES:
        raise HTTPException(400, f"unknown vehicle_class '{vehicle_class}'")

    if settings.MULTI_TENANT and tenant_slug:
        from app.database import get_tenant_session
        _cm = await get_tenant_session(tenant_slug)
        async with _cm as wdb:
            cfg = await _get_gate_cam_cfg(wdb)
            if x_gate_agent_key:
                stored = cfg.get("agent_key", "")
                if not stored or x_gate_agent_key != stored:
                    raise HTTPException(403, "Invalid gate agent key")
            elif x_agent_key:
                from app.multitenancy.registry import tenant_registry
                if not await tenant_registry.validate_agent_key(tenant_slug, x_agent_key):
                    raise HTTPException(403, "Invalid agent key")
            else:
                raise HTTPException(400, "X-Gate-Agent-Key or X-Agent-Key header required")
            eid = await _persist_event(wdb, tenant_slug, position, vehicle_class,
                                       confidence, detected_at, camera_id, image)
    else:
        cfg = await _get_gate_cam_cfg(db)
        stored = cfg.get("agent_key", "")
        if not stored:
            raise HTTPException(403, "Agent key not configured. Go to Settings → Gate Cameras.")
        if x_gate_agent_key != stored:
            raise HTTPException(403, "Invalid agent key")
        eid = await _persist_event(db, None, position, vehicle_class,
                                   confidence, detected_at, camera_id, image)

    return {"ok": True, "id": str(eid), "position": position, "vehicle_class": vehicle_class}


# ════════════════════════════════════════════════════════════════════════════
#  Reports — JWT + module-gated (middleware enforces `vehicle_count`)
# ════════════════════════════════════════════════════════════════════════════

@router.get("/counts")
async def vehicle_counts(
    from_date: date | None = None,
    to_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Counts by class × direction + totals + reconciliation vs gate passes.

    Dates are the IST calendar day (detections are TIMESTAMPTZ; gate_passes.pass_date
    is already the IST day). Reconciliation compares total camera ENTRIES vs gate
    passes created in the same window (guard logs a pass per vehicle in)."""
    today = date.today()
    df = from_date or today
    dt = to_date or today
    cid = str(current_user.company_id)

    rows = (await db.execute(text("""
        SELECT position, vehicle_class, COUNT(*) AS n
        FROM gate_vehicle_events
        WHERE company_id = :cid
          AND CAST(detected_at AT TIME ZONE 'Asia/Kolkata' AS date) BETWEEN :df AND :dt
        GROUP BY position, vehicle_class
    """), {"cid": cid, "df": df, "dt": dt})).fetchall()

    by: dict[str, dict] = {}
    tot_entries = tot_exits = 0
    for r in rows:
        b = by.setdefault(r.vehicle_class, {"vehicle_class": r.vehicle_class, "entries": 0, "exits": 0})
        if r.position == "entry":
            b["entries"] += r.n
            tot_entries += r.n
        elif r.position == "exit":
            b["exits"] += r.n
            tot_exits += r.n

    gp = int((await db.execute(text("""
        SELECT COUNT(*) FROM gate_passes
        WHERE company_id = :cid AND pass_date BETWEEN :df AND :dt
    """), {"cid": cid, "df": df, "dt": dt})).scalar() or 0)

    by_class = sorted(by.values(), key=lambda x: (-(x["entries"] + x["exits"]), x["vehicle_class"]))
    return {
        "from_date": df.isoformat(),
        "to_date": dt.isoformat(),
        "by_class": by_class,
        "totals": {"entries": tot_entries, "exits": tot_exits},
        "gate_passes_created": gp,
        "reconciliation": {
            "camera_entries": tot_entries,
            "gate_passes": gp,
            "variance": tot_entries - gp,
        },
    }


@router.get("/events")
async def vehicle_events(
    from_date: date | None = None,
    to_date: date | None = None,
    position: str | None = None,
    vehicle_class: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Paginated event log with snapshot URLs (for the report table)."""
    today = date.today()
    df = from_date or today
    dt = to_date or today
    cid = str(current_user.company_id)

    where = ["company_id = :cid",
             "CAST(detected_at AT TIME ZONE 'Asia/Kolkata' AS date) BETWEEN :df AND :dt"]
    params: dict = {"cid": cid, "df": df, "dt": dt}
    if position in ("entry", "exit"):
        where.append("position = :pos")
        params["pos"] = position
    if vehicle_class:
        where.append("vehicle_class = :cls")
        params["cls"] = vehicle_class.strip().lower()
    wsql = " AND ".join(where)

    total = int((await db.execute(
        text(f"SELECT COUNT(*) FROM gate_vehicle_events WHERE {wsql}"), params
    )).scalar() or 0)

    params2 = {**params, "limit": page_size, "offset": (page - 1) * page_size}
    rows = (await db.execute(text(f"""
        SELECT id, position, vehicle_class, confidence, snapshot_path, camera_id, detected_at
        FROM gate_vehicle_events
        WHERE {wsql}
        ORDER BY detected_at DESC
        OFFSET :offset LIMIT :limit
    """), params2)).fetchall()

    items = [{
        "id": str(r.id),
        "position": r.position,
        "vehicle_class": r.vehicle_class,
        "confidence": float(r.confidence) if r.confidence is not None else None,
        "snapshot_url": (f"/uploads/{r.snapshot_path}" if r.snapshot_path else None),
        "camera_id": r.camera_id,
        "detected_at": r.detected_at.isoformat() if r.detected_at else None,
    } for r in rows]

    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "from_date": df.isoformat(), "to_date": dt.isoformat()}


# ════════════════════════════════════════════════════════════════════════════
#  Retention — called once/day from the digest loop (wired in a later phase)
# ════════════════════════════════════════════════════════════════════════════

async def purge_old_vehicle_events(factory, label: str = "default", retain_days: int = 30) -> None:
    """Delete event rows (and best-effort their snapshot day-dirs) older than
    `retain_days`. The permanent tally lives in the aggregated report; short local
    retention keeps snapshots off the VPS disk. Guarded — never raises."""
    try:
        async with factory() as db:
            await db.execute(
                text("DELETE FROM gate_vehicle_events WHERE detected_at < NOW() - make_interval(days => :d)"),
                {"d": retain_days},
            )
            await db.commit()
    except Exception as e:  # pragma: no cover - best effort
        log.warning("purge_old_vehicle_events [%s] failed: %s", label, e)
