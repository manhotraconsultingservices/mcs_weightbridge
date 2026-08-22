"""ANPR Pydantic schemas — request + response models for /api/v1/anpr/*.

Three shapes of payload feed into the ingest pipeline:
  1. DetectPayload — what the local FastALPR worker posts
  2. HikvisionWebhookPayload — vendor format from Hikvision Generic Event Push
  3. DahuaWebhookPayload    — vendor format from Dahua Smart Event HTTP Notify

Webhook adapters normalise to DetectPayload before reaching _handle_detection().
"""
import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


# ── Source A: local FastALPR ingest ───────────────────────────────────────────


class OcrAlternate(BaseModel):
    plate: str
    confidence: float


class DetectPayload(BaseModel):
    """Body POSTed by the camera agent's ANPR worker."""
    plate_raw: str
    plate_normalized: str | None = None     # if missing, server normalises
    confidence: float = Field(ge=0.0, le=1.0)
    camera_id: str = "front"
    source: str = "local_fastalpr"
    detected_at: datetime | None = None     # if missing, server stamps NOW()
    snapshot_b64: str | None = None          # optional inline JPEG payload
    ocr_alternates: list[OcrAlternate] | None = None


class DetectResponse(BaseModel):
    event_id: uuid.UUID
    direction: str                          # entry | exit | unmatched | duplicate
    token_id: uuid.UUID | None = None
    gate_pass_no: str | None = None
    action_taken: str                       # human-readable for agent logs


# ── Source B: vendor webhooks ─────────────────────────────────────────────────


class HikvisionPlateInfo(BaseModel):
    """Subset of Hikvision Generic Event Push payload that we care about."""
    licensePlate: str | None = None
    confidence: float | None = None
    captureTime: str | None = None          # ISO-ish, varies by firmware


class HikvisionWebhookPayload(BaseModel):
    """Top-level wrapper Hikvision posts. Fields beyond what we use are ignored."""
    eventType: str | None = None
    channelID: int | None = None
    dateTime: str | None = None
    ANPR: HikvisionPlateInfo | None = None
    # Some firmware nests under "Plates" instead — accept extras.
    model_config = {"extra": "allow"}


class DahuaWebhookPayload(BaseModel):
    """Dahua Smart Event HTTP push. Slightly different shape."""
    Code: str | None = None                 # 'TrafficJunction' typically
    Action: str | None = None
    Data: dict[str, Any] | None = None      # contains plate, confidence, time
    model_config = {"extra": "allow"}


# ── Listing + browsing ────────────────────────────────────────────────────────


class VehicleBrief(BaseModel):
    id: uuid.UUID
    registration_no: str
    model_config = {"from_attributes": True}


class TokenBrief(BaseModel):
    id: uuid.UUID
    token_no: int | None = None
    token_date: date
    status: str
    vehicle_no: str
    gate_pass_no: str | None = None
    party_name: str | None = None
    product_name: str | None = None
    model_config = {"from_attributes": True}


class AnprEventResponse(BaseModel):
    id: uuid.UUID
    plate_raw: str
    plate_normalized: str
    direction: str
    confidence: Decimal | None = None
    source: str
    camera_id: str
    snapshot_path: str | None = None
    detected_at: datetime
    needs_review: bool
    reviewed_at: datetime | None = None
    notes: str | None = None
    vehicle: VehicleBrief | None = None
    token: TokenBrief | None = None
    ocr_alternates: list[OcrAlternate] | None = None
    model_config = {"from_attributes": True}


class AnprEventListResponse(BaseModel):
    items: list[AnprEventResponse]
    total: int
    page: int
    page_size: int


# ── Stats + dashboard ─────────────────────────────────────────────────────────


class AnprDayBucket(BaseModel):
    date: date
    entries: int
    exits: int


class AnprStatsResponse(BaseModel):
    entries: int
    exits: int
    unmatched: int
    unique_vehicles: int
    currently_inside: int                   # open tokens with no anpr_exit_at
    avg_dwell_minutes: float
    by_day: list[AnprDayBucket]


# ── Review queue ──────────────────────────────────────────────────────────────


class ReassignRequest(BaseModel):
    """When the operator corrects a misread / unknown plate."""
    vehicle_id: uuid.UUID | None = None     # link to existing vehicle
    plate_corrected: str | None = None      # update the normalized plate
    register_new_vehicle: bool = False      # auto-create Vehicle from plate
    notes: str | None = None


# ── Config (admin) ────────────────────────────────────────────────────────────


class AnprConfig(BaseModel):
    """ANPR feature configuration stored under app_settings.anpr_config."""
    enabled: bool = False
    engine: str = "local_fastalpr"          # local_fastalpr | hikvision_webhook | dahua_webhook
    gate_camera_id: str = "front"           # which camera in app_settings.camera_config
    cooldown_sec: int = 8                   # min gap between detections of same plate
    min_confidence: float = 0.55
    fuzzy_match: bool = True                # 1-char Levenshtein against vehicle master
    auto_create_token: bool = True
    notify_owner: bool = True               # Telegram on entry/exit
    notify_unknown_plate: bool = True
    daily_summary: bool = True              # Telegram daily list of trips at owner_digest time
    webhook_secret: str | None = None       # required for Hikvision/Dahua webhook auth


# ── Daily trip report — one row per vehicle visit ────────────────────────────


class AnprTrip(BaseModel):
    """One vehicle visit (entry + exit pair where available).

    Sourced from tokens with anpr_entry_at OR anpr_exit_at populated, joined
    with the linked invoice for billing info.
    """
    token_id: uuid.UUID
    token_no: int | None = None
    token_date: date
    vehicle_no: str
    gate_pass_no: str | None = None
    entry_time: datetime | None = None
    exit_time: datetime | None = None
    dwell_minutes: int | None = None           # null if still inside
    party_name: str | None = None
    product_name: str | None = None
    net_weight_mt: Decimal | None = None       # converted from kg at API boundary
    invoice_id: uuid.UUID | None = None
    invoice_no: str | None = None
    invoice_status: str | None = None          # draft | final | cancelled
    payment_status: str | None = None          # unpaid | partial | paid
    grand_total: Decimal | None = None
    status: str                                # token status
    source: str                                # token source (anpr / manual / kiosk)


class AnprTripListResponse(BaseModel):
    items: list[AnprTrip]
    total: int
    page: int
    page_size: int
    # Roll-up totals for the date range
    entries: int
    exits: int
    currently_inside: int
    total_tonnage_mt: Decimal          # material DISPATCHED (sale tokens)
    received_tonnage_mt: Decimal = Decimal("0")   # material RECEIVED (purchase tokens)
    total_revenue: Decimal             # SALE invoices only — purchases are not revenue
    purchase_value: Decimal = Decimal("0")        # purchase bills against these trips
    avg_dwell_minutes: float
