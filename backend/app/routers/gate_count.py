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
import json
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
# `person` is opt-in per site (agent `classes` config) and is kept SEPARATE from
# the vehicle totals + the gate-pass reconciliation (see vehicle_counts).
ALLOWED_CLASSES = {"truck", "car", "motorcycle", "bus", "bicycle", "auto", "person"}
PERSON_CLASSES = {"person"}


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
        # Tenant-agnostic agent: ONE exe is deployed anywhere. Whether a tenant
        # actually gets vehicle counting is controlled centrally by the platform
        # admin's `vehicle_count` module toggle. The agent ingest is agent-key
        # (no JWT), so the middleware module-gate never runs for it — enforce the
        # module HERE so an installed agent on a non-subscribed tenant is inert.
        from app.multitenancy.middleware import _get_tenant_modules
        try:
            _mods = await _get_tenant_modules(tenant_slug)
        except Exception:
            _mods = {}
        if not _mods.get("vehicle_count", False):
            raise HTTPException(403, "vehicle_count is not enabled for this tenant (paid add-on — enable it in the Platform console)")
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
    tot_entries = tot_exits = 0            # VEHICLES only (person excluded)
    ppl_entries = ppl_exits = 0           # people, tracked separately
    for r in rows:
        b = by.setdefault(r.vehicle_class, {"vehicle_class": r.vehicle_class, "entries": 0, "exits": 0})
        is_person = r.vehicle_class in PERSON_CLASSES
        if r.position == "entry":
            b["entries"] += r.n
            if is_person:
                ppl_entries += r.n
            else:
                tot_entries += r.n
        elif r.position == "exit":
            b["exits"] += r.n
            if is_person:
                ppl_exits += r.n
            else:
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
        "totals": {"entries": tot_entries, "exits": tot_exits},   # vehicles only
        "people": {"entries": ppl_entries, "exits": ppl_exits},   # separate; 0 unless `person` is counted
        "gate_passes_created": gp,
        "reconciliation": {
            "camera_entries": tot_entries,                        # vehicles vs gate passes
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

# Snapshots are what fill the disk — thousands of JPEGs a day at ~150 KB each. The
# event ROWS are tiny and are what the count report reads, so they are kept far
# longer: deleting them would silently shorten how far back the report can look.
DEFAULT_SNAPSHOT_RETAIN_DAYS = 20
DEFAULT_ROW_RETAIN_DAYS = 365
RETENTION_SETTING_KEY = "vehicle_count"


async def _retention_days(db) -> tuple[int, int]:
    """(snapshot days, row days) — per-tenant override, else the defaults above."""
    snaps, rows = DEFAULT_SNAPSHOT_RETAIN_DAYS, DEFAULT_ROW_RETAIN_DAYS
    try:
        raw = (await db.execute(text("SELECT value FROM app_settings WHERE key = :k"),
                                {"k": RETENTION_SETTING_KEY})).scalar()
        cfg = json.loads(raw) if isinstance(raw, str) else (raw or {})
        if isinstance(cfg, dict):
            snaps = int(cfg.get("retain_days") or snaps)
            rows = int(cfg.get("retain_rows_days") or rows)
    except Exception:      # a malformed setting must not stop the purge
        pass
    # Never let a bad value delete today's captures.
    return max(1, snaps), max(1, rows)


async def purge_old_vehicle_events(factory, label: str = "default",
                                   retain_days: int | None = None,
                                   tenant_slug: str | None = None) -> None:
    """Delete snapshot day-dirs older than the snapshot retention, and event rows
    older than the (much longer) row retention. Both configurable per tenant via
    ``app_settings.vehicle_count``. Fully guarded — never raises."""
    snap_days, row_days = DEFAULT_SNAPSHOT_RETAIN_DAYS, DEFAULT_ROW_RETAIN_DAYS
    # 1) DB rows
    try:
        async with factory() as db:
            snap_days, row_days = await _retention_days(db)
            if retain_days is not None:        # explicit caller override wins
                snap_days = max(1, int(retain_days))
            await db.execute(
                text("DELETE FROM gate_vehicle_events WHERE detected_at < NOW() - make_interval(days => :d)"),
                {"d": row_days},
            )
            await db.commit()
    except Exception as e:  # pragma: no cover - best effort
        log.warning("purge_old_vehicle_events rows [%s] failed: %s", label, e)
    retain_days = snap_days
    # 2) snapshot day-dirs (uploads/gate/vehicle/[<slug>/]<YYYYMMDD>)
    try:
        import datetime as _dt, shutil
        from datetime import timezone as _tz
        slug = tenant_slug or (label if label and label != "default" else None)
        veh_base = os.path.join(_uploads_base(), "gate", "vehicle")
        root = os.path.join(veh_base, slug) if slug else veh_base
        if os.path.isdir(root):
            cutoff = _dt.datetime.now(_tz.utc).date() - _dt.timedelta(days=retain_days)
            for name in os.listdir(root):
                if len(name) == 8 and name.isdigit():
                    try:
                        d = _dt.datetime.strptime(name, "%Y%m%d").date()
                    except ValueError:
                        continue
                    if d < cutoff:
                        # Labelled frames were copied into gate/training when they
                        # were reviewed, so dropping the day folder cannot lose
                        # them — that copy is the whole point of the promotion.
                        shutil.rmtree(os.path.join(root, name), ignore_errors=True)
    except Exception as e:  # pragma: no cover - best effort
        log.warning("purge_old_vehicle_events files [%s] failed: %s", label, e)


# ════════════════════════════════════════════════════════════════════════════
#  Review & training set
#  The counter can only ever answer in the six words its model knows. Teaching it
#  the yard's own vocabulary — tractor, camper, tipper — needs examples from THIS
#  gate, so every corrected event is kept as one.
# ════════════════════════════════════════════════════════════════════════════

# The yard's own vocabulary — what a reviewer may label a frame, and the classes a
# retrained model will be taught. Deliberately WIDER than what the model can output
# today: COCO knows only car/truck/bus/motorcycle/bicycle/person, so tractor, camper,
# jcb, tanker and trailer can be LABELLED now and only DETECTED once there are enough
# examples to train on. Changing this list later invalidates labels already collected,
# so it is defined in one place rather than typed into a screen.
LABEL_CLASSES = [
    "truck", "tractor", "camper", "car", "jcb", "tanker", "trailer",
    "bus", "motorcycle", "bicycle", "person", "other",
]


@router.get("/label-classes")
async def label_classes(user: User = Depends(get_current_user)):
    """The categories a reviewer can assign, and which of them the CURRENT model can
    actually produce on its own — so the screen can show the difference honestly."""
    model_can_emit = sorted(set(ALLOWED_CLASSES))
    return {
        "classes": LABEL_CLASSES,
        "detectable_today": [c for c in LABEL_CLASSES if c in model_can_emit],
        "needs_training": [c for c in LABEL_CLASSES if c not in model_can_emit],
    }


def _training_dir(slug: str | None) -> str:
    parts = [_uploads_base(), "gate", "training"] + ([slug] if slug else [])
    return os.path.join(*parts)


@router.get("/review")
async def review_queue(
    limit: int = Query(40, ge=1, le=200),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    only_class: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Counted events that nobody has confirmed yet, newest first.

    Deliberately biased towards events that carry a snapshot — an event with no
    image teaches nothing and would only waste the reviewer's time.
    """
    where = ["company_id = :cid", "reviewed_class IS NULL",
             "snapshot_path IS NOT NULL", "snapshot_path <> ''"]
    params: dict = {"cid": str(user.company_id), "lim": limit}
    if date_from:
        where.append("detected_at >= :df")
        params["df"] = date_from
    if date_to:
        where.append("detected_at < (:dt::date + 1)")
        params["dt"] = date_to
    if only_class:
        where.append("vehicle_class = :cls")
        params["cls"] = only_class
    rows = (await db.execute(text(
        "SELECT id, position, vehicle_class, confidence, snapshot_path, detected_at "
        "FROM gate_vehicle_events WHERE " + " AND ".join(where) +
        " ORDER BY detected_at DESC LIMIT :lim"), params)).mappings().all()
    return {"items": [{
        "id": str(r["id"]), "position": r["position"],
        "model_class": r["vehicle_class"],
        "confidence": float(r["confidence"] or 0),
        "snapshot_url": f"/uploads/{r['snapshot_path']}",
        "detected_at": r["detected_at"],
    } for r in rows]}


@router.post("/events/{event_id}/label")
async def label_event(
    event_id: uuid.UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Confirm or correct one event's category, and keep the frame for training.

    The image is COPIED into the training folder rather than left where it is:
    snapshots are purged on a short clock, and a labelled frame is the one thing
    that must outlive it.
    """
    cls = str(payload.get("vehicle_class") or "").strip().lower()
    if not cls:
        raise HTTPException(400, "vehicle_class is required")
    if cls not in LABEL_CLASSES:
        raise HTTPException(
            400, f"'{cls}' is not one of the agreed categories: {', '.join(LABEL_CLASSES)}")

    row = (await db.execute(text(
        "SELECT snapshot_path FROM gate_vehicle_events "
        "WHERE id = :i AND company_id = :c"),
        {"i": str(event_id), "c": str(user.company_id)})).mappings().first()
    if not row:
        raise HTTPException(404, "Event not found")

    training_rel = None
    rel = (row["snapshot_path"] or "").lstrip("/")
    if rel:
        src = os.path.join(_uploads_base(), rel.replace("/", os.sep))
        if os.path.isfile(src):
            slug = _ctx_tenant_slug()
            dest_dir = os.path.join(_training_dir(slug), cls)
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, f"{event_id}.jpg")
            try:
                import shutil
                shutil.copy2(src, dest)
                parts = ["gate", "training"] + ([slug] if slug else []) + [cls, f"{event_id}.jpg"]
                training_rel = "/".join(parts)
            except OSError as e:
                log.warning("could not copy training frame %s: %s", src, e)

    await db.execute(text(
        "UPDATE gate_vehicle_events SET reviewed_class = :cls, reviewed_by = :u, "
        "reviewed_at = NOW(), training_path = COALESCE(:tp, training_path) "
        "WHERE id = :i AND company_id = :c"),
        {"cls": cls, "u": str(user.id), "tp": training_rel,
         "i": str(event_id), "c": str(user.company_id)})
    await db.commit()
    return {"ok": True, "id": str(event_id), "vehicle_class": cls,
            "kept_for_training": training_rel is not None}


@router.get("/training-set")
async def training_set_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """How much labelled material exists, per category — the number that decides
    whether a retraining run is worth doing yet."""
    rows = (await db.execute(text(
        "SELECT reviewed_class AS cls, count(*) AS n, "
        "count(*) FILTER (WHERE reviewed_class <> vehicle_class) AS corrected "
        "FROM gate_vehicle_events WHERE company_id = :c AND reviewed_class IS NOT NULL "
        "GROUP BY reviewed_class ORDER BY n DESC"),
        {"c": str(user.company_id)})).mappings().all()
    total = sum(r["n"] for r in rows)
    unreviewed = (await db.execute(text(
        "SELECT count(*) FROM gate_vehicle_events WHERE company_id = :c "
        "AND reviewed_class IS NULL AND snapshot_path IS NOT NULL"),
        {"c": str(user.company_id)})).scalar() or 0
    # A rough, honest bar: fine-tuning a detector needs a few hundred examples of
    # each category before it is worth the effort.
    TARGET = 200
    return {
        "classes": [{"vehicle_class": r["cls"], "labelled": r["n"],
                     "model_got_it_wrong": r["corrected"],
                     "short_of_target": max(0, TARGET - r["n"])} for r in rows],
        "total_labelled": total, "awaiting_review": unreviewed,
        "per_class_target": TARGET,
        "ready_to_train": bool(rows) and all(r["n"] >= TARGET for r in rows),
    }
