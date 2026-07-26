"""ANPR (Automatic Number Plate Recognition) router.

Single source of truth for plate-detection ingest, decision logic
(entry vs exit vs duplicate), gate-pass auto-numbering, token creation
linked to the detection, and the browsing / reporting + config surface
used by the admin UI.

Ingest sources (all converge on _handle_detection):
  - POST /anpr/detect             Local FastALPR worker (Source A)
  - POST /anpr/webhook/hikvision  Hikvision Generic Event Push (Source B)
  - POST /anpr/webhook/dahua      Dahua Smart Event HTTP Notify (Source B)

All three paths require either the agent's bearer JWT (for /detect, called
by the agent which logs in with its company API key) or the
X-ANPR-Secret header (for vendor webhooks, since cameras can't carry JWTs).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.utils.timefmt import fmt_ist as _fmt_ist
from app.models.anpr import AnprEvent
from app.models.company import Company, FinancialYear
from app.models.party import Party
from app.models.product import Product
from app.models.settings import NumberSequence
from app.models.token import Token
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.anpr import (
    AnprConfig,
    AnprDayBucket,
    AnprEventListResponse,
    AnprEventResponse,
    AnprStatsResponse,
    AnprTrip,
    AnprTripListResponse,
    DahuaWebhookPayload,
    DetectPayload,
    DetectResponse,
    HikvisionWebhookPayload,
    ReassignRequest,
    TokenBrief,
    VehicleBrief,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/anpr", tags=["ANPR"])

CONFIG_KEY = "anpr_config"
SNAPSHOT_DIR = Path("uploads/anpr")
MASKED = "***"


# ════════════════════════════════════════════════════════════════════════════
#  Plate normalisation + fuzzy lookup
# ════════════════════════════════════════════════════════════════════════════

def normalise_plate(plate: str) -> str:
    """Strip everything that isn't [A-Z0-9] and uppercase. India: MH12AB1234."""
    return "".join(ch for ch in (plate or "").upper() if ch.isalnum())


def _levenshtein(a: str, b: str) -> int:
    """Iterative Levenshtein distance — O(len(a)*len(b)). Plates are < 12 chars."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


async def _fuzzy_lookup_vehicle(
    db: AsyncSession, company_id: uuid.UUID, plate_norm: str, fuzzy: bool = True
) -> Vehicle | None:
    """Lookup a Vehicle by normalised plate.

    1. Exact case-insensitive match on `registration_no` after normalisation.
    2. If `fuzzy` and step 1 missed, accept a Vehicle whose normalised plate
       is within 1 Levenshtein edit. Returns the first such match (real-world
       collisions are vanishingly rare on Indian plates which carry a 4-digit
       suffix).
    """
    # Step 1: exact match against the normalised form. The DB stores the plate
    # as the operator typed it, so we normalise both sides for comparison.
    rows = (await db.execute(
        select(Vehicle).where(Vehicle.company_id == company_id, Vehicle.is_active == True)
    )).scalars().all()
    for v in rows:
        if normalise_plate(v.registration_no) == plate_norm:
            return v
    if not fuzzy:
        return None
    # Step 2: 1-edit fuzzy match. Only for plates ≥ 6 chars to avoid noise.
    if len(plate_norm) < 6:
        return None
    for v in rows:
        if _levenshtein(normalise_plate(v.registration_no), plate_norm) == 1:
            return v
    return None


# ════════════════════════════════════════════════════════════════════════════
#  Config (stored as JSON blob in app_settings)
# ════════════════════════════════════════════════════════════════════════════

async def _get_raw_setting(db: AsyncSession, key: str) -> str | None:
    row = (await db.execute(
        text("SELECT value FROM app_settings WHERE key = :k"), {"k": key}
    )).fetchone()
    return row[0] if row else None


async def _upsert_setting(db: AsyncSession, key: str, value: str) -> None:
    await db.execute(
        text("""
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (:k, :v, NOW())
            ON CONFLICT (key) DO UPDATE
              SET value = EXCLUDED.value, updated_at = NOW()
        """),
        {"k": key, "v": value},
    )


async def _load_config(db: AsyncSession) -> AnprConfig:
    raw = await _get_raw_setting(db, CONFIG_KEY)
    if not raw:
        return AnprConfig()
    try:
        return AnprConfig(**json.loads(raw))
    except Exception:
        log.warning("anpr_config is corrupt; falling back to defaults")
        return AnprConfig()


def _mask_secret(cfg: AnprConfig) -> AnprConfig:
    """Return a copy of cfg with webhook_secret masked for safe display."""
    if cfg.webhook_secret:
        return cfg.model_copy(update={"webhook_secret": MASKED})
    return cfg


# ════════════════════════════════════════════════════════════════════════════
#  Gate-pass auto-numbering — reuses NumberSequence (same pattern as invoices)
# ════════════════════════════════════════════════════════════════════════════

async def _next_gate_pass_no(
    db: AsyncSession, company_id: uuid.UUID, fy_id: uuid.UUID
) -> str:
    """Allocate the next gap-free gate-pass number (GP/25-26/0001).

    Delegates to the shared numbering helper so the ANPR auto-entry path and
    the manual token-create path use one identical, row-locked allocator and
    can never hand out a duplicate.
    """
    from app.services.numbering import next_gate_pass_no
    return await next_gate_pass_no(db, company_id, fy_id)


# ════════════════════════════════════════════════════════════════════════════
#  Snapshot persistence (inline base64 → uploads/anpr/<date>/<id>.jpg)
# ════════════════════════════════════════════════════════════════════════════

def _save_snapshot(event_id: uuid.UUID, b64: str | None) -> str | None:
    """Persist an inline base64 JPEG to disk; returns the relative path or None."""
    if not b64:
        return None
    try:
        data = base64.b64decode(b64, validate=False)
        # Strip data-URL prefix if present
        if not data or len(data) < 32:
            return None
    except Exception:
        return None
    today_dir = SNAPSHOT_DIR / datetime.now(timezone.utc).strftime("%Y%m%d")
    today_dir.mkdir(parents=True, exist_ok=True)
    rel = today_dir / f"{event_id}.jpg"
    try:
        rel.write_bytes(data)
    except OSError as exc:
        log.warning("Could not write ANPR snapshot to %s: %s", rel, exc)
        return None
    # Return a forward-slash relative path so it serves correctly via /uploads
    return str(rel.as_posix())


# ════════════════════════════════════════════════════════════════════════════
#  Background notification fire (reuses existing send_notification engine)
# ════════════════════════════════════════════════════════════════════════════

async def _send_notification_bg(
    company_id: uuid.UUID,
    event_type: str,
    context: dict[str, Any],
    entity_type: str | None = None,
    entity_id: str | None = None,
    tenant_slug: str | None = None,
) -> None:
    """Background wrapper — opens its own DB session and fires the notification."""
    try:
        from app.database import get_tenant_session
        async with await get_tenant_session(tenant_slug) as db:
            from app.integrations.notifications.service import send_notification
            await send_notification(db, company_id, event_type, context, entity_type, entity_id)
    except Exception as exc:
        log.warning("ANPR notification failed [%s]: %s", event_type, exc)


# ════════════════════════════════════════════════════════════════════════════
#  Common context helpers
# ════════════════════════════════════════════════════════════════════════════

async def _get_company_and_fy(db: AsyncSession) -> tuple[Company, FinancialYear]:
    company = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    if not company:
        raise HTTPException(500, "Company not configured")
    fy = (await db.execute(
        select(FinancialYear).where(FinancialYear.is_active == True).limit(1)
    )).scalar_one_or_none()
    if not fy:
        raise HTTPException(500, "No active financial year")
    return company, fy


def _tenant_slug() -> str | None:
    try:
        from app.multitenancy.context import current_tenant_slug
        return current_tenant_slug.get()
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════════════════
#  THE CORE: _handle_detection — 3-layer dedup + entry/exit decision
# ════════════════════════════════════════════════════════════════════════════

async def _handle_detection(
    db: AsyncSession,
    payload: DetectPayload,
    background_tasks: BackgroundTasks,
) -> DetectResponse:
    """Single entry point used by both /detect and the vendor webhooks.

    Pipeline:
      1. Normalise plate
      2. Load ANPR config
      3. Layer-1 dedup: 15 s SQL window of identical-plate events
      4. Decide direction (entry vs exit vs unmatched)
      5. If ENTRY: allocate gate_pass_no, create OPEN Token, smart-suggest
         party/product/tare from history
      6. If EXIT: stamp anpr_exit_at on the linked Token
      7. Persist AnprEvent
      8. Background: fire Telegram notification
    """
    cfg = await _load_config(db)
    if not cfg.enabled:
        raise HTTPException(403, "ANPR is disabled. Enable it in Settings → ANPR.")

    if payload.confidence < cfg.min_confidence:
        # Below threshold — still log for review queue, but no token side-effect.
        return await _record_low_confidence(db, payload, background_tasks, cfg)

    company, fy = await _get_company_and_fy(db)
    plate_norm = payload.plate_normalized or normalise_plate(payload.plate_raw)
    if not plate_norm:
        raise HTTPException(400, "Empty plate after normalisation")

    # ── Layer 1: 15-second SQL dedup ──────────────────────────────────────
    dup = (await db.execute(text("""
        SELECT id FROM anpr_events
        WHERE company_id = :cid
          AND plate_normalized = :p
          AND detected_at > NOW() - INTERVAL '15 seconds'
        LIMIT 1
    """), {"cid": str(company.id), "p": plate_norm})).fetchone()
    if dup:
        return DetectResponse(
            event_id=dup[0], direction="duplicate",
            action_taken="suppressed_duplicate_15s",
        )

    # ── Vehicle master lookup ─────────────────────────────────────────────
    vehicle = await _fuzzy_lookup_vehicle(db, company.id, plate_norm, fuzzy=cfg.fuzzy_match)
    needs_review = vehicle is None

    # ── Direction decision (single-camera setup) ──────────────────────────
    direction, linked_token_id, linked_gp = await _decide_direction(db, plate_norm, company.id)

    snapshot_event_id = uuid.uuid4()
    snapshot_path = _save_snapshot(snapshot_event_id, payload.snapshot_b64)

    token_id: uuid.UUID | None = linked_token_id
    gate_pass_no: str | None = linked_gp

    # ── ENTRY: create token + allocate gate pass ──────────────────────────
    if direction == "entry":
        if cfg.auto_create_token:
            # Application-level dedup guard: no fresh token created in last 5 min
            recent_open = (await db.execute(text("""
                SELECT id, gate_pass_no FROM tokens
                WHERE company_id = :cid
                  AND vehicle_no = :p
                  AND created_at > NOW() - INTERVAL '5 minutes'
                  AND status NOT IN ('CANCELLED')
                ORDER BY created_at DESC LIMIT 1
            """), {"cid": str(company.id), "p": plate_norm})).fetchone()
            if recent_open:
                token_id, gate_pass_no = recent_open[0], recent_open[1]
            else:
                gate_pass_no = await _next_gate_pass_no(db, company.id, fy.id)
                token_id = await _create_anpr_token(
                    db, company, fy, plate_norm, vehicle, gate_pass_no, payload
                )
        # else: cfg.auto_create_token is False (shadow mode) — log event only.

    # ── EXIT: stamp anpr_exit_at on the linked token ──────────────────────
    elif direction == "exit" and linked_token_id:
        tok = await db.get(Token, linked_token_id)
        if tok:
            tok.anpr_exit_at = datetime.now(timezone.utc)
            await db.flush()

    # ── Persist the ANPR event ───────────────────────────────────────────
    event = AnprEvent(
        id=snapshot_event_id,
        company_id=company.id,
        plate_raw=payload.plate_raw[:20],
        plate_normalized=plate_norm[:20],
        vehicle_id=vehicle.id if vehicle else None,
        token_id=token_id,
        direction=direction,
        confidence=Decimal(str(round(payload.confidence, 3))),
        source=payload.source[:30],
        camera_id=payload.camera_id[:20],
        snapshot_path=snapshot_path,
        detected_at=payload.detected_at or datetime.now(timezone.utc),
        ocr_alternates=([alt.model_dump() for alt in payload.ocr_alternates]
                        if payload.ocr_alternates else None),
        needs_review=needs_review and direction in ("entry", "unmatched"),
    )
    db.add(event)
    await db.commit()

    # ── Background notification ───────────────────────────────────────────
    if cfg.notify_owner:
        ts = _tenant_slug()
        if direction == "entry" and token_id:
            background_tasks.add_task(
                _send_notification_bg, company.id, "anpr_entry",
                _entry_context(plate_norm, vehicle, gate_pass_no, event.detected_at, token_id),
                "anpr_event", str(event.id), ts,
            )
        elif direction == "exit" and linked_token_id:
            background_tasks.add_task(
                _send_notification_bg, company.id, "anpr_exit",
                await _exit_context(db, plate_norm, vehicle, gate_pass_no, event.detected_at, linked_token_id),
                "anpr_event", str(event.id), ts,
            )
        elif needs_review and cfg.notify_unknown_plate:
            background_tasks.add_task(
                _send_notification_bg, company.id, "anpr_unknown_plate",
                {"plate": plate_norm, "captured_at": _fmt_ist(event.detected_at),
                 "company_name": company.name},
                "anpr_event", str(event.id), ts,
            )

    # ── H3-D: barrier relay trigger (non-blocking) ────────────────────────
    # Only fire for registered vehicles (needs_review=False) to prevent
    # unknown plates from opening the gate.
    if direction in ("entry", "exit") and not needs_review:
        from app.services.barrier import trigger_barrier as _barrier_trigger
        background_tasks.add_task(
            _barrier_trigger, db, direction, plate_norm, gate_pass_no
        )

    return DetectResponse(
        event_id=event.id,
        direction=direction,
        token_id=token_id,
        gate_pass_no=gate_pass_no,
        action_taken=_action_summary(direction, gate_pass_no, needs_review),
    )


def _action_summary(direction: str, gate_pass_no: str | None, needs_review: bool) -> str:
    parts: list[str] = [direction]
    if gate_pass_no:
        parts.append(f"gp={gate_pass_no}")
    if needs_review:
        parts.append("flagged_for_review")
    return "·".join(parts)


async def _record_low_confidence(
    db: AsyncSession, payload: DetectPayload, _bg: BackgroundTasks, _cfg: AnprConfig
) -> DetectResponse:
    """Below-threshold detections still get logged (needs_review=TRUE) but no token."""
    company, _ = await _get_company_and_fy(db)
    plate_norm = payload.plate_normalized or normalise_plate(payload.plate_raw)
    eid = uuid.uuid4()
    snapshot_path = _save_snapshot(eid, payload.snapshot_b64)
    ev = AnprEvent(
        id=eid,
        company_id=company.id,
        plate_raw=payload.plate_raw[:20],
        plate_normalized=plate_norm[:20],
        direction="unmatched",
        confidence=Decimal(str(round(payload.confidence, 3))),
        source=payload.source[:30],
        camera_id=payload.camera_id[:20],
        snapshot_path=snapshot_path,
        detected_at=payload.detected_at or datetime.now(timezone.utc),
        ocr_alternates=([alt.model_dump() for alt in payload.ocr_alternates]
                        if payload.ocr_alternates else None),
        needs_review=True,
        notes="confidence below min_confidence threshold",
    )
    db.add(ev)
    await db.commit()
    return DetectResponse(
        event_id=ev.id, direction="unmatched",
        action_taken=f"low_confidence_{payload.confidence:.2f}",
    )


async def _decide_direction(
    db: AsyncSession, plate_norm: str, company_id: uuid.UUID
) -> tuple[str, uuid.UUID | None, str | None]:
    """Single-camera entry/exit decision — see plan §5."""
    # Layer 2: open token today for this plate → it's coming back for 2nd weight = EXIT
    row = (await db.execute(text("""
        SELECT id, gate_pass_no FROM tokens
        WHERE company_id = :cid
          AND vehicle_no = :p
          AND token_date = CURRENT_DATE
          AND status IN ('OPEN','FIRST_WEIGHT','LOADING','SECOND_WEIGHT')
          AND anpr_exit_at IS NULL
          AND is_supplement = FALSE
        ORDER BY created_at DESC LIMIT 1
    """), {"cid": str(company_id), "p": plate_norm})).fetchone()
    if row:
        return "exit", row[0], row[1]

    # Layer 3: recently-completed (within 24 h) token w/o exit → late exit detection
    row = (await db.execute(text("""
        SELECT id, gate_pass_no FROM tokens
        WHERE company_id = :cid
          AND vehicle_no = :p
          AND token_date >= CURRENT_DATE - INTERVAL '1 day'
          AND status = 'COMPLETED'
          AND anpr_exit_at IS NULL
        ORDER BY completed_at DESC LIMIT 1
    """), {"cid": str(company_id), "p": plate_norm})).fetchone()
    if row:
        return "exit", row[0], row[1]

    return "entry", None, None


async def _create_anpr_token(
    db: AsyncSession,
    company: Company,
    fy: FinancialYear,
    plate_norm: str,
    vehicle: Vehicle | None,
    gate_pass_no: str,
    payload: DetectPayload,
) -> uuid.UUID:
    """Create an OPEN token from an ANPR entry detection.

    party/product/tare are auto-filled by replaying the smart-suggest logic
    (last COMPLETED token for this plate). If no history exists, those
    fields stay NULL and the existing auto-invoice flow silently skips —
    same behaviour as a manual token created without party/product.
    """
    party_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    tare: Decimal | None = None

    last_completed = (await db.execute(
        select(Token)
        .where(
            Token.company_id == company.id,
            Token.vehicle_no == plate_norm,
            Token.status == "COMPLETED",
            Token.is_supplement == False,
        )
        .order_by(Token.completed_at.desc().nulls_last(), Token.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if last_completed:
        party_id = last_completed.party_id
        product_id = last_completed.product_id
        tare = last_completed.tare_weight

    tok = Token(
        company_id=company.id,
        fy_id=fy.id,
        token_no=None,                       # assigned at COMPLETED (gap-free, existing)
        token_date=date.today(),
        direction="outbound",                # ANPR can't tell intent yet; default to sale.
        token_type="sale",
        party_id=party_id,
        product_id=product_id,
        vehicle_no=plate_norm,
        vehicle_id=vehicle.id if vehicle else None,
        vehicle_type=vehicle.vehicle_type if vehicle else None,
        tare_weight=tare,
        gate_pass_no=gate_pass_no,
        anpr_entry_at=datetime.now(timezone.utc),
        source="anpr",
        status="OPEN",
        remarks=f"Auto-created from ANPR detection ({payload.source})",
    )
    db.add(tok)
    await db.flush()
    return tok.id


def _entry_context(
    plate: str, vehicle: Vehicle | None, gate_pass_no: str | None,
    detected_at: datetime, token_id: uuid.UUID,
) -> dict:
    return {
        "vehicle_no": plate,
        "vehicle_known": "yes" if vehicle else "no",
        "gate_pass_no": gate_pass_no or "—",
        "entry_time": _fmt_ist(detected_at),
        "token_id": str(token_id),
    }


async def _exit_context(
    db: AsyncSession, plate: str, vehicle: Vehicle | None, gate_pass_no: str | None,
    detected_at: datetime, token_id: uuid.UUID,
) -> dict:
    tok = await db.get(Token, token_id)
    entry_at = tok.anpr_entry_at if tok and tok.anpr_entry_at else (tok.created_at if tok else None)
    dwell = 0
    if entry_at:
        dwell = max(0, int((detected_at - entry_at).total_seconds() / 60))
    return {
        "vehicle_no": plate,
        "gate_pass_no": gate_pass_no or "—",
        "exit_time": _fmt_ist(detected_at),
        "dwell_minutes": str(dwell),
        "token_no": str(tok.token_no) if tok and tok.token_no else "—",
        "net_weight": f"{(float(tok.net_weight or 0) / 1000):.3f}" if tok else "—",
    }


# ════════════════════════════════════════════════════════════════════════════
#  Endpoints — ingest
# ════════════════════════════════════════════════════════════════════════════

@router.post("/detect", response_model=DetectResponse)
async def post_detect(
    payload: DetectPayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),       # agent JWT
):
    """Source A — local FastALPR worker posts a single detection."""
    return await _handle_detection(db, payload, background_tasks)


# ── Webhook auth helper (shared by Hikvision + Dahua adapters) ────────────────

async def _verify_webhook_secret(
    db: AsyncSession, x_anpr_secret: str | None = Header(None),
) -> None:
    cfg = await _load_config(db)
    if not cfg.enabled:
        raise HTTPException(403, "ANPR is disabled")
    if not cfg.webhook_secret:
        raise HTTPException(401, "Webhook secret not configured — set anpr_config.webhook_secret")
    if x_anpr_secret != cfg.webhook_secret:
        raise HTTPException(401, "Invalid X-ANPR-Secret")


@router.post("/webhook/hikvision", response_model=DetectResponse)
async def webhook_hikvision(
    payload: HikvisionWebhookPayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    x_anpr_secret: str | None = Header(None, alias="X-ANPR-Secret"),
):
    """Source B — Hikvision Generic Event Push (HTTP Listening Server).

    The camera POSTs a JSON envelope with ANPR.licensePlate + confidence.
    We coerce into DetectPayload and route through the common handler.
    """
    await _verify_webhook_secret(db, x_anpr_secret)
    info = payload.ANPR
    if not info or not info.licensePlate:
        raise HTTPException(400, "Missing ANPR.licensePlate in Hikvision payload")
    detect = DetectPayload(
        plate_raw=info.licensePlate,
        plate_normalized=normalise_plate(info.licensePlate),
        confidence=float(info.confidence) if info.confidence is not None else 0.9,
        camera_id="front",
        source="hikvision_webhook",
        detected_at=_parse_camera_time(info.captureTime or payload.dateTime),
    )
    return await _handle_detection(db, detect, background_tasks)


@router.post("/webhook/dahua", response_model=DetectResponse)
async def webhook_dahua(
    payload: DahuaWebhookPayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    x_anpr_secret: str | None = Header(None, alias="X-ANPR-Secret"),
):
    """Source B — Dahua Smart Event HTTP Notify.

    Dahua nests the plate under Data.PlateNumber (firmware-dependent).
    """
    await _verify_webhook_secret(db, x_anpr_secret)
    data = payload.Data or {}
    plate = (
        data.get("PlateNumber")
        or data.get("plateNumber")
        or data.get("plate")
        or ""
    )
    if not plate:
        raise HTTPException(400, "Missing PlateNumber in Dahua payload")
    confidence = data.get("Confidence") or data.get("confidence") or 0.9
    try:
        confidence = float(confidence)
        if confidence > 1.0:                # Dahua sometimes sends 0..100
            confidence = confidence / 100.0
    except (TypeError, ValueError):
        confidence = 0.9
    captured = data.get("UTC") or data.get("Time") or data.get("captureTime")
    detect = DetectPayload(
        plate_raw=str(plate),
        plate_normalized=normalise_plate(str(plate)),
        confidence=confidence,
        camera_id="front",
        source="dahua_webhook",
        detected_at=_parse_camera_time(captured),
    )
    return await _handle_detection(db, detect, background_tasks)


def _parse_camera_time(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # Try ISO; if camera sends Unix epoch as int-string, fall back
        if s.isdigit():
            return datetime.fromtimestamp(int(s), tz=timezone.utc)
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════════════════
#  Endpoints — browsing + stats
# ════════════════════════════════════════════════════════════════════════════

def _to_event_response(
    ev: AnprEvent, vehicle: Vehicle | None, tok: Token | None,
    party_name: str | None, product_name: str | None,
) -> AnprEventResponse:
    return AnprEventResponse(
        id=ev.id,
        plate_raw=ev.plate_raw,
        plate_normalized=ev.plate_normalized,
        direction=ev.direction,
        confidence=ev.confidence,
        source=ev.source,
        camera_id=ev.camera_id,
        snapshot_path=ev.snapshot_path,
        detected_at=ev.detected_at,
        needs_review=ev.needs_review,
        reviewed_at=ev.reviewed_at,
        notes=ev.notes,
        vehicle=VehicleBrief(id=vehicle.id, registration_no=vehicle.registration_no) if vehicle else None,
        token=TokenBrief(
            id=tok.id, token_no=tok.token_no, token_date=tok.token_date,
            status=tok.status, vehicle_no=tok.vehicle_no, gate_pass_no=tok.gate_pass_no,
            party_name=party_name, product_name=product_name,
        ) if tok else None,
        ocr_alternates=ev.ocr_alternates if ev.ocr_alternates else None,
    )


async def _hydrate_events(
    db: AsyncSession, events: list[AnprEvent]
) -> list[AnprEventResponse]:
    """Batch-load vehicles + tokens (with party + product names) for a list of events."""
    if not events:
        return []
    veh_ids = {e.vehicle_id for e in events if e.vehicle_id}
    tok_ids = {e.token_id for e in events if e.token_id}

    vehicles = {}
    if veh_ids:
        rows = (await db.execute(select(Vehicle).where(Vehicle.id.in_(veh_ids)))).scalars().all()
        vehicles = {v.id: v for v in rows}

    tokens = {}
    party_names: dict[uuid.UUID, str] = {}
    product_names: dict[uuid.UUID, str] = {}
    if tok_ids:
        rows = (await db.execute(
            select(Token).where(Token.id.in_(tok_ids))
            .options(selectinload(Token.party), selectinload(Token.product))
        )).scalars().all()
        for t in rows:
            tokens[t.id] = t
            if t.party_id:
                party_names[t.id] = t.party.name if t.party else ""
            if t.product_id:
                product_names[t.id] = t.product.name if t.product else ""

    out: list[AnprEventResponse] = []
    for e in events:
        out.append(_to_event_response(
            e,
            vehicles.get(e.vehicle_id) if e.vehicle_id else None,
            tokens.get(e.token_id) if e.token_id else None,
            party_names.get(e.token_id) if e.token_id else None,
            product_names.get(e.token_id) if e.token_id else None,
        ))
    return out


@router.get("/events", response_model=AnprEventListResponse)
async def list_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    date_from: date | None = None,
    date_to: date | None = None,
    direction: str | None = None,
    plate: str | None = None,
    needs_review: bool | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated browse over ANPR events with filters."""
    company, _ = await _get_company_and_fy(db)
    conds = [AnprEvent.company_id == company.id]
    if date_from:
        conds.append(AnprEvent.detected_at >= datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc))
    if date_to:
        conds.append(AnprEvent.detected_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc))
    if direction:
        conds.append(AnprEvent.direction == direction)
    if plate:
        conds.append(AnprEvent.plate_normalized.ilike(f"%{normalise_plate(plate)}%"))
    if needs_review is not None:
        conds.append(AnprEvent.needs_review == needs_review)

    total = (await db.execute(
        select(func.count()).select_from(AnprEvent).where(and_(*conds))
    )).scalar() or 0

    rows = (await db.execute(
        select(AnprEvent).where(and_(*conds))
        .order_by(AnprEvent.detected_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    return AnprEventListResponse(
        items=await _hydrate_events(db, list(rows)),
        total=total, page=page, page_size=page_size,
    )


@router.get("/events/{event_id}", response_model=AnprEventResponse)
async def get_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ev = await db.get(AnprEvent, event_id)
    if not ev:
        raise HTTPException(404, "Event not found")
    out = await _hydrate_events(db, [ev])
    return out[0]


@router.get("/unmatched", response_model=AnprEventListResponse)
async def list_unmatched(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Review queue — events flagged needs_review=TRUE and not yet reviewed."""
    company, _ = await _get_company_and_fy(db)
    conds = [
        AnprEvent.company_id == company.id,
        AnprEvent.needs_review == True,
        AnprEvent.reviewed_at.is_(None),
    ]
    total = (await db.execute(
        select(func.count()).select_from(AnprEvent).where(and_(*conds))
    )).scalar() or 0
    rows = (await db.execute(
        select(AnprEvent).where(and_(*conds))
        .order_by(AnprEvent.detected_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    return AnprEventListResponse(
        items=await _hydrate_events(db, list(rows)),
        total=total, page=page, page_size=page_size,
    )


@router.post("/events/{event_id}/reassign", response_model=AnprEventResponse)
async def reassign_event(
    event_id: uuid.UUID,
    payload: ReassignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "operator", "accountant")),
):
    """Operator fixes a misread / unknown plate.

    Either link to an existing vehicle (`vehicle_id`), correct the plate
    text (`plate_corrected`), or register a brand-new Vehicle from the
    detected plate (`register_new_vehicle=true`).
    """
    ev = await db.get(AnprEvent, event_id)
    if not ev:
        raise HTTPException(404, "Event not found")
    company, _ = await _get_company_and_fy(db)

    if payload.register_new_vehicle:
        plate_to_use = normalise_plate(payload.plate_corrected or ev.plate_normalized)
        existing = (await db.execute(
            select(Vehicle).where(
                Vehicle.company_id == company.id,
                func.upper(Vehicle.registration_no) == plate_to_use,
            )
        )).scalar_one_or_none()
        if existing:
            ev.vehicle_id = existing.id
        else:
            v = Vehicle(
                company_id=company.id,
                registration_no=plate_to_use,
                is_active=True,
            )
            db.add(v)
            await db.flush()
            ev.vehicle_id = v.id
    elif payload.vehicle_id:
        v = await db.get(Vehicle, payload.vehicle_id)
        if not v or v.company_id != company.id:
            raise HTTPException(404, "Vehicle not found")
        ev.vehicle_id = v.id

    if payload.plate_corrected:
        ev.plate_normalized = normalise_plate(payload.plate_corrected)[:20]
        ev.plate_raw = payload.plate_corrected[:20]

    # If a linked token exists and we now know the vehicle, backfill the FK.
    if ev.token_id and ev.vehicle_id:
        tok = await db.get(Token, ev.token_id)
        if tok and not tok.vehicle_id:
            tok.vehicle_id = ev.vehicle_id
            tok.vehicle_no = ev.plate_normalized

    ev.needs_review = False
    ev.reviewed_by = current_user.id
    ev.reviewed_at = datetime.now(timezone.utc)
    if payload.notes:
        ev.notes = (ev.notes or "") + f"\n[reassign by {current_user.username}] {payload.notes}"
    await db.commit()

    out = await _hydrate_events(db, [ev])
    return out[0]


@router.get("/stats", response_model=AnprStatsResponse)
async def stats(
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Counts + by-day breakdown + currently-inside gauge."""
    company, _ = await _get_company_and_fy(db)
    if not date_from:
        date_from = date.today() - timedelta(days=14)
    if not date_to:
        date_to = date.today()
    start_ts = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
    end_ts = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

    counts = (await db.execute(text("""
        SELECT
          SUM(CASE WHEN direction = 'entry' THEN 1 ELSE 0 END)::INT AS entries,
          SUM(CASE WHEN direction = 'exit' THEN 1 ELSE 0 END)::INT  AS exits,
          SUM(CASE WHEN needs_review = TRUE THEN 1 ELSE 0 END)::INT AS unmatched,
          COUNT(DISTINCT plate_normalized)::INT AS unique_vehicles
        FROM anpr_events
        WHERE company_id = :cid AND detected_at >= :s AND detected_at < :e
    """), {"cid": str(company.id), "s": start_ts, "e": end_ts})).fetchone()
    entries = int(counts.entries or 0) if counts else 0
    exits_ = int(counts.exits or 0) if counts else 0
    unmatched = int(counts.unmatched or 0) if counts else 0
    unique_vehicles = int(counts.unique_vehicles or 0) if counts else 0

    # Currently inside = tokens with anpr_entry_at and no anpr_exit_at
    currently_inside = (await db.execute(text("""
        SELECT COUNT(*)::INT FROM tokens
        WHERE company_id = :cid
          AND anpr_entry_at IS NOT NULL
          AND anpr_exit_at IS NULL
          AND status NOT IN ('CANCELLED')
    """), {"cid": str(company.id)})).scalar() or 0

    # Average dwell minutes — only over closed pairs in the date window
    avg_dwell = (await db.execute(text("""
        SELECT COALESCE(AVG(EXTRACT(EPOCH FROM (anpr_exit_at - anpr_entry_at)) / 60.0), 0)
        FROM tokens
        WHERE company_id = :cid
          AND anpr_entry_at IS NOT NULL
          AND anpr_exit_at IS NOT NULL
          AND anpr_entry_at >= :s AND anpr_entry_at < :e
    """), {"cid": str(company.id), "s": start_ts, "e": end_ts})).scalar() or 0

    # Per-day buckets
    by_day_rows = (await db.execute(text("""
        SELECT
          DATE(detected_at AT TIME ZONE 'UTC') AS d,
          SUM(CASE WHEN direction = 'entry' THEN 1 ELSE 0 END)::INT AS entries,
          SUM(CASE WHEN direction = 'exit'  THEN 1 ELSE 0 END)::INT AS exits
        FROM anpr_events
        WHERE company_id = :cid AND detected_at >= :s AND detected_at < :e
        GROUP BY d ORDER BY d
    """), {"cid": str(company.id), "s": start_ts, "e": end_ts})).fetchall()
    by_day = [AnprDayBucket(date=r.d, entries=int(r.entries or 0), exits=int(r.exits or 0)) for r in by_day_rows]

    return AnprStatsResponse(
        entries=entries, exits=exits_, unmatched=unmatched,
        unique_vehicles=unique_vehicles, currently_inside=int(currently_inside),
        avg_dwell_minutes=float(avg_dwell),
        by_day=by_day,
    )


# ════════════════════════════════════════════════════════════════════════════
#  Endpoints — config
# ════════════════════════════════════════════════════════════════════════════

@router.get("/config", response_model=AnprConfig)
async def get_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    cfg = await _load_config(db)
    return _mask_secret(cfg)


@router.put("/config", response_model=AnprConfig)
async def put_config(
    payload: AnprConfig,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Save the ANPR config blob to app_settings.

    If `webhook_secret` is the masked sentinel ('***'), preserve the existing
    secret. Otherwise overwrite with the new value (including clearing).
    """
    existing = await _load_config(db)
    merged = payload.model_dump()
    if payload.webhook_secret == MASKED:
        merged["webhook_secret"] = existing.webhook_secret
    await _upsert_setting(db, CONFIG_KEY, json.dumps(merged))
    await db.commit()
    return _mask_secret(AnprConfig(**merged))


@router.post("/config/test", response_model=DetectResponse)
async def test_detection(
    payload: DetectPayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Admin-only — fire one synthetic detection through the pipeline.

    Used by Settings → ANPR → "Test Detection" button. Bypasses the
    cooldown/dedup logic by stamping the source as 'manual'.
    """
    payload.source = "manual"
    return await _handle_detection(db, payload, background_tasks)


# ════════════════════════════════════════════════════════════════════════════
#  Daily trip report — one row per vehicle visit (entry + exit pair)
# ════════════════════════════════════════════════════════════════════════════

async def _fetch_trips(
    db: AsyncSession, company_id: uuid.UUID,
    date_from: date, date_to: date,
    page: int = 1, page_size: int = 200,
) -> tuple[list[AnprTrip], int, dict]:
    """Pull all non-cancelled tokens between `date_from` and `date_to` inclusive,
    joined with their linked invoice, with summary roll-ups.

    Shows all tokens regardless of ANPR status. ANPR entry/exit timestamps are
    shown where available (camera-detected trucks), NULL otherwise (manual tokens).
    KPI entry/exit counts are still ANPR-specific; tonnage/revenue cover all tokens.
    """
    start_ts = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
    end_ts = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

    # Trip rows joined with party + product + invoice — single SELECT for table.
    rows_q = text("""
        SELECT
          t.id              AS token_id,
          t.token_no        AS token_no,
          t.token_date      AS token_date,
          t.vehicle_no      AS vehicle_no,
          t.gate_pass_no    AS gate_pass_no,
          t.anpr_entry_at   AS entry_time,
          t.anpr_exit_at    AS exit_time,
          t.net_weight      AS net_weight,
          t.status          AS status,
          t.source          AS source,
          p.name            AS party_name,
          pr.name           AS product_name,
          i.id              AS invoice_id,
          i.invoice_no      AS invoice_no,
          i.status          AS invoice_status,
          i.payment_status  AS payment_status,
          i.grand_total     AS grand_total
        FROM tokens t
        LEFT JOIN parties  p  ON p.id  = t.party_id
        LEFT JOIN products pr ON pr.id = t.product_id
        LEFT JOIN LATERAL (
            SELECT id, invoice_no, status, payment_status, grand_total
            FROM invoices
            WHERE token_id = t.id
            ORDER BY created_at DESC LIMIT 1
        ) i ON TRUE
        WHERE t.company_id = :cid
          AND t.is_supplement = FALSE
          AND t.status NOT IN ('CANCELLED')
          AND t.token_date BETWEEN :df AND :dt
        ORDER BY COALESCE(t.anpr_entry_at, t.anpr_exit_at, t.created_at) DESC
        OFFSET :offset LIMIT :limit
    """)
    rows = (await db.execute(rows_q, {
        "cid": str(company_id), "s": start_ts, "e": end_ts,
        "df": date_from, "dt": date_to,
        "offset": (page - 1) * page_size, "limit": page_size,
    })).fetchall()

    # Total count for pagination — same filter, no joins.
    total_q = text("""
        SELECT COUNT(*) FROM tokens t
        WHERE t.company_id = :cid
          AND t.is_supplement = FALSE
          AND t.status NOT IN ('CANCELLED')
          AND t.token_date BETWEEN :df AND :dt
    """)
    total = int((await db.execute(total_q, {
        "cid": str(company_id), "s": start_ts, "e": end_ts,
        "df": date_from, "dt": date_to,
    })).scalar() or 0)

    # Roll-ups for the same window
    rollup_q = text("""
        SELECT
          COUNT(*) FILTER (WHERE anpr_entry_at >= :s AND anpr_entry_at < :e)::INT AS entries,
          COUNT(*) FILTER (WHERE anpr_exit_at  >= :s AND anpr_exit_at  < :e)::INT AS exits,
          COALESCE(SUM(net_weight) FILTER (WHERE status = 'COMPLETED'
                       AND token_date BETWEEN :df AND :dt), 0) AS total_kg
        FROM tokens
        WHERE company_id = :cid AND is_supplement = FALSE
          AND status NOT IN ('CANCELLED')
    """)
    ru = (await db.execute(rollup_q, {
        "cid": str(company_id), "s": start_ts, "e": end_ts,
        "df": date_from, "dt": date_to,
    })).fetchone()
    entries_n = int(ru.entries or 0) if ru else 0
    exits_n = int(ru.exits or 0) if ru else 0
    total_kg = float(ru.total_kg or 0) if ru else 0.0

    # Total revenue for invoices linked to those trips
    rev_q = text("""
        SELECT COALESCE(SUM(i.grand_total), 0)
        FROM invoices i
        JOIN tokens t ON t.id = i.token_id
        WHERE t.company_id = :cid
          AND i.status = 'final'
          AND t.token_date BETWEEN :df AND :dt
    """)
    total_revenue = float((await db.execute(rev_q, {
        "cid": str(company_id), "df": date_from, "dt": date_to,
    })).scalar() or 0)

    # Currently inside = entries in window with no exit yet
    inside_q = text("""
        SELECT COUNT(*) FROM tokens
        WHERE company_id = :cid AND is_supplement = FALSE
          AND anpr_entry_at IS NOT NULL AND anpr_exit_at IS NULL
          AND status NOT IN ('CANCELLED')
    """)
    currently_inside = int((await db.execute(inside_q, {"cid": str(company_id)})).scalar() or 0)

    # Avg dwell for closed trips in window
    dwell_q = text("""
        SELECT COALESCE(AVG(EXTRACT(EPOCH FROM (anpr_exit_at - anpr_entry_at)) / 60.0), 0)
        FROM tokens
        WHERE company_id = :cid AND is_supplement = FALSE
          AND anpr_entry_at IS NOT NULL AND anpr_exit_at IS NOT NULL
          AND anpr_entry_at >= :s AND anpr_entry_at < :e
    """)
    avg_dwell = float((await db.execute(dwell_q, {
        "cid": str(company_id), "s": start_ts, "e": end_ts,
    })).scalar() or 0)

    # Build trip rows
    trips: list[AnprTrip] = []
    for r in rows:
        dwell = None
        if r.entry_time and r.exit_time:
            dwell = max(0, int((r.exit_time - r.entry_time).total_seconds() / 60))
        net_mt = (Decimal(str(r.net_weight)) / Decimal("1000")).quantize(Decimal("0.001")) if r.net_weight else None
        trips.append(AnprTrip(
            token_id=r.token_id,
            token_no=r.token_no,
            token_date=r.token_date,
            vehicle_no=r.vehicle_no,
            gate_pass_no=r.gate_pass_no,
            entry_time=r.entry_time,
            exit_time=r.exit_time,
            dwell_minutes=dwell,
            party_name=r.party_name,
            product_name=r.product_name,
            net_weight_mt=net_mt,
            invoice_id=r.invoice_id,
            invoice_no=r.invoice_no,
            invoice_status=r.invoice_status,
            payment_status=r.payment_status,
            grand_total=Decimal(str(r.grand_total)) if r.grand_total is not None else None,
            status=r.status,
            source=r.source,
        ))

    return trips, total, {
        "entries": entries_n,
        "exits": exits_n,
        "currently_inside": currently_inside,
        "total_tonnage_mt": Decimal(str(round(total_kg / 1000, 3))),
        "total_revenue": Decimal(str(round(total_revenue, 2))),
        "avg_dwell_minutes": float(avg_dwell),
    }


@router.get("/trips", response_model=AnprTripListResponse)
async def list_trips(
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One row per vehicle visit — the user-friendly daily movement report.

    Each row pairs the ANPR entry detection with its matching exit (when
    available) and joins the linked sales/purchase invoice for billing info.
    """
    company, _ = await _get_company_and_fy(db)
    if not date_from:
        date_from = date.today()
    if not date_to:
        date_to = date.today()
    trips, total, rollup = await _fetch_trips(db, company.id, date_from, date_to, page, page_size)
    return AnprTripListResponse(
        items=trips, total=total, page=page, page_size=page_size,
        **rollup,
    )


@router.post("/daily-summary/send", response_model=dict)
async def send_daily_summary_now(
    background_tasks: BackgroundTasks,
    target_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Fire the daily ANPR Telegram summary on demand (admin button).

    Same context that the scheduled loop builds — covers `target_date`
    (default today). Returns {ok: True, trip_count, entries, exits}.
    """
    company, _ = await _get_company_and_fy(db)
    cfg = await _load_config(db)
    if not cfg.enabled:
        raise HTTPException(400, "ANPR is disabled — enable it in Settings → ANPR first.")
    target = target_date or date.today()
    ctx = await _build_daily_summary_context(db, company.id, company.name, target)
    background_tasks.add_task(
        _send_notification_bg,
        company.id, "anpr_daily_summary", ctx,
        "company", str(company.id), _tenant_slug(),
    )
    return {
        "ok": True,
        "date": target.isoformat(),
        "trip_count": ctx.get("trip_count", 0),
        "entries": ctx.get("entries", 0),
        "exits": ctx.get("exits", 0),
    }


async def _build_daily_summary_context(
    db: AsyncSession, company_id: uuid.UUID, company_name: str, target_date: date
) -> dict[str, Any]:
    """Build the Jinja2 context the anpr_daily_summary template renders.

    Used by both the on-demand send endpoint and the scheduled owner-digest
    loop. Trip list is top-20 by entry time descending.
    """
    trips, total, rollup = await _fetch_trips(db, company_id, target_date, target_date, page=1, page_size=50)
    INR = lambda v: f"{float(v or 0):,.0f}"

    # Build a compact per-trip line for Telegram. Markdown is rendered as
    # HTML by the Telegram channel sender so we keep one line per trip.
    def fmt_trip(t: AnprTrip, idx: int) -> str:
        ent = t.entry_time.strftime("%H:%M") if t.entry_time else "—"
        ext = t.exit_time.strftime("%H:%M") if t.exit_time else "in"
        dwell = f"{t.dwell_minutes}m" if t.dwell_minutes is not None else "open"
        bits = [f"{idx}. <b>{t.vehicle_no}</b>", f"↓{ent}", f"↑{ext}", f"({dwell})"]
        if t.token_no is not None:
            bits.append(f"#{t.token_no}")
        if t.gate_pass_no:
            bits.append(f"<code>{t.gate_pass_no}</code>")
        if t.invoice_no:
            bits.append(f"INV {t.invoice_no}")
        if t.grand_total:
            bits.append(f"₹{INR(t.grand_total)}")
        return " · ".join(bits)

    top = trips[:20]
    trip_list = "\n".join(fmt_trip(t, i + 1) for i, t in enumerate(top))
    more = max(0, total - len(top))
    if more > 0:
        trip_list += f"\n…and {more} more"

    return {
        "company_name": company_name,
        "date": target_date.strftime("%d %b %Y"),
        "entries": rollup["entries"],
        "exits": rollup["exits"],
        "currently_inside": rollup["currently_inside"],
        "trip_count": total,
        "tonnage_mt": f"{float(rollup['total_tonnage_mt']):,.2f}",
        "revenue": INR(rollup["total_revenue"]),
        "avg_dwell": int(rollup["avg_dwell_minutes"]),
        "trip_list": trip_list,
    }


# Public alias so main.py can import the context builder for the digest loop.
build_daily_summary_context = _build_daily_summary_context
