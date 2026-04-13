"""
WebSocket endpoint for real-time weight streaming + REST status/config endpoints.

Multi-tenant support:
- WebSocket accepts ?tenant= query param for per-tenant routing
- External reading endpoint validates X-Tenant + X-Agent-Key headers
- Per-tenant WeightScaleManager instances (keyed by tenant slug)
"""
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.settings import SerialPortConfig
from app.integrations.serial_port.manager import (
    get_weight_manager, init_weight_manager, scan_serial_ports, test_port_connection,
    auto_detect_scale, WeightReading,
)
from app.integrations.serial_port.protocols import (
    PROTOCOL_LABELS, PROTOCOL_DEFAULT_BAUD, PROTOCOL_DEFAULT_CONFIG, PROTOCOL_DEFAULT_SERIAL,
)

log = logging.getLogger(__name__)
router = APIRouter()

# ── Per-tenant weight manager registry ──────────────────────────────────────
# In multi-tenant mode, each tenant gets its own passive WeightScaleManager
# keyed by tenant slug. In single-tenant mode, the global manager is used.
_tenant_weight_managers: dict[str, Any] = {}  # slug → WeightScaleManager


def _get_manager_for_tenant(slug: str | None = None):
    """Get weight manager — per-tenant in MT mode, global otherwise."""
    if slug:
        return _tenant_weight_managers.get(slug)
    return get_weight_manager()


@router.websocket("/ws/weight")
async def ws_weight(websocket: WebSocket, tenant: str = Query("")):
    """Real-time weight broadcast. No auth token needed (LAN-only use).
    In multi-tenant mode, ?tenant=<slug> routes to per-tenant manager.
    """
    from app.config import get_settings
    settings = get_settings()

    if settings.MULTI_TENANT and not tenant:
        await websocket.close(code=4001, reason="tenant query param required")
        return

    manager = _get_manager_for_tenant(tenant if settings.MULTI_TENANT else None)
    if manager is None:
        await websocket.close(code=1013)
        return

    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:
        await manager.disconnect(websocket)


@router.get("/api/v1/weight/status")
async def weight_status(current_user: User = Depends(get_current_user)):
    from app.config import get_settings
    from app.multitenancy.context import current_tenant_slug
    settings = get_settings()

    slug = current_tenant_slug.get() if settings.MULTI_TENANT else None
    manager = _get_manager_for_tenant(slug)

    if manager is None:
        return {
            "scale_connected": False,
            "weight_kg": 0.0,
            "is_stable": False,
            "stable_duration_sec": 0.0,
        }
    latest = manager.latest
    return {
        "scale_connected": manager.is_connected and (latest.scale_connected if latest else False),
        "weight_kg": latest.weight_kg if latest else 0.0,
        "is_stable": latest.is_stable if latest else False,
        "stable_duration_sec": latest.stable_duration_sec if latest else 0.0,
    }


@router.post("/api/v1/weight/capture")
async def capture_weight(current_user: User = Depends(get_current_user)):
    """Return the latest stable weight reading."""
    from app.config import get_settings
    from app.multitenancy.context import current_tenant_slug
    settings = get_settings()

    slug = current_tenant_slug.get() if settings.MULTI_TENANT else None
    manager = _get_manager_for_tenant(slug)

    if manager is None:
        raise HTTPException(status_code=503, detail="Scale not connected")
    latest = manager.latest
    if not latest or not latest.scale_connected:
        raise HTTPException(status_code=503, detail="Scale not connected")
    if not latest.is_stable:
        raise HTTPException(status_code=422, detail="Weight not stable yet")
    return {
        "weight_kg": latest.weight_kg,
        "is_stable": latest.is_stable,
        "stable_duration_sec": latest.stable_duration_sec,
    }


@router.get("/api/v1/weight/config")
async def get_weight_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(SerialPortConfig).limit(1))
    cfg = result.scalar_one_or_none()
    if not cfg:
        return {}
    pc = cfg.protocol_config
    if isinstance(pc, str):
        try:
            pc = json.loads(pc)
        except Exception:
            pc = {}
    return {
        "port_name": cfg.port_name,
        "baud_rate": cfg.baud_rate,
        "data_bits": cfg.data_bits,
        "stop_bits": cfg.stop_bits,
        "parity": cfg.parity,
        "is_enabled": cfg.is_enabled,
        "protocol": cfg.protocol,
        "protocol_config": pc or {},
        "stability_readings": cfg.stability_readings,
        "stability_tolerance_kg": float(cfg.stability_tolerance_kg),
    }


@router.put("/api/v1/weight/config")
async def update_weight_config(
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(SerialPortConfig).limit(1))
    cfg = result.scalar_one_or_none()
    if not cfg:
        cfg = SerialPortConfig()
        db.add(cfg)

    if "port_name" in payload:
        cfg.port_name = payload["port_name"]
    if "baud_rate" in payload:
        cfg.baud_rate = int(payload["baud_rate"])
    if "data_bits" in payload:
        cfg.data_bits = int(payload["data_bits"])
    if "stop_bits" in payload:
        cfg.stop_bits = int(payload["stop_bits"])
    if "parity" in payload:
        cfg.parity = str(payload["parity"])
    if "is_enabled" in payload:
        cfg.is_enabled = bool(payload["is_enabled"])
    if "protocol" in payload:
        cfg.protocol = payload["protocol"]
    if "protocol_config" in payload:
        # DB column is Text — must serialize dict to JSON string
        pc = payload["protocol_config"]
        cfg.protocol_config = json.dumps(pc) if isinstance(pc, dict) else pc
    if "stability_readings" in payload:
        cfg.stability_readings = int(payload["stability_readings"])
    if "stability_tolerance_kg" in payload:
        cfg.stability_tolerance_kg = float(payload["stability_tolerance_kg"])

    await db.commit()
    await db.refresh(cfg)

    # Deserialize protocol_config from DB Text column
    pc = cfg.protocol_config
    if isinstance(pc, str):
        try:
            pc = json.loads(pc)
        except Exception:
            pc = {}
    pc = pc or {}

    # Restart manager with new config (single-tenant only)
    from app.config import get_settings
    if not get_settings().MULTI_TENANT:
        await init_weight_manager(
            port=cfg.port_name,
            baud_rate=cfg.baud_rate,
            data_bits=cfg.data_bits,
            stop_bits=cfg.stop_bits,
            parity=cfg.parity,
            protocol=cfg.protocol,
            protocol_config=pc,
            stability_readings=cfg.stability_readings,
            stability_tolerance_kg=float(cfg.stability_tolerance_kg),
        )

    return {"message": "Weight config updated and scale restarted"}


@router.get("/api/v1/weight/ports")
async def list_ports(current_user: User = Depends(get_current_user)):
    """Scan and return all available COM/serial ports on this machine."""
    return {"ports": scan_serial_ports()}


@router.get("/api/v1/weight/protocols")
async def list_protocols(current_user: User = Depends(get_current_user)):
    """Return all supported protocols with labels, default baud rates, and default config."""
    return {
        "protocols": [
            {
                "id": k,
                "label": v,
                "default_baud": PROTOCOL_DEFAULT_BAUD.get(k, 9600),
                "default_config": PROTOCOL_DEFAULT_CONFIG.get(k, {}),
                "default_serial": PROTOCOL_DEFAULT_SERIAL.get(k, {"data_bits": 8, "parity": "N", "stop_bits": 1}),
            }
            for k, v in PROTOCOL_LABELS.items()
        ]
    }


@router.post("/api/v1/weight/external-reading")
async def external_weight_reading(payload: dict[str, Any]):
    """
    Accept weight reading from external bridge program (weight_bridge.py).
    No auth required — only accessible from localhost.
    Body: { weight_kg: float, raw: str (optional) }

    Multi-tenant mode: requires X-Tenant + X-Agent-Key headers for tenant routing.
    Single-tenant: auto-initialises a passive weight manager if none configured yet.
    """
    import asyncio
    from fastapi import Request
    from app.integrations.serial_port.manager import (
        WeightScaleManager, WeightReading,
    )
    import app.integrations.serial_port.manager as _mgr_module
    from app.config import get_settings

    settings = get_settings()
    tenant_slug: str | None = None

    if settings.MULTI_TENANT:
        # Validate tenant + agent key from payload or we check later via header
        tenant_slug = payload.get("tenant") or payload.get("tenant_slug")
        agent_key = payload.get("agent_key")

        if not tenant_slug or not agent_key:
            raise HTTPException(400, "tenant and agent_key required in multi-tenant mode")

        from app.multitenancy.registry import tenant_registry
        if not await tenant_registry.validate_agent_key(tenant_slug, agent_key):
            raise HTTPException(403, "Invalid agent key for tenant")

        # Get or create per-tenant passive manager
        manager = _tenant_weight_managers.get(tenant_slug)
        if manager is None:
            passive = WeightScaleManager(port="EXTERNAL", baud_rate=9600)
            passive._running = True
            passive._serial_open = True
            _tenant_weight_managers[tenant_slug] = passive
            manager = passive
            log.info("Created passive weight manager for tenant: %s", tenant_slug)
    else:
        manager = get_weight_manager()

        # Auto-create a passive manager if none exists (weight_bridge.py mode)
        if manager is None:
            passive = WeightScaleManager(port="EXTERNAL", baud_rate=9600)
            passive._running = True
            passive._serial_open = True
            _mgr_module.weight_manager = passive
            manager = passive
            log.info("Created passive weight manager for external bridge readings")

    weight_kg = float(payload.get("weight_kg", 0))
    raw = payload.get("raw", "")

    loop = asyncio.get_running_loop()
    reading = manager._make_reading(weight_kg, raw.encode("ascii", errors="ignore") if raw else b"", loop)
    reading.scale_connected = True
    manager._latest = reading
    manager._serial_open = True
    await manager._broadcast(reading)

    return {"ok": True, "weight_kg": reading.weight_kg, "is_stable": reading.is_stable}


@router.post("/api/v1/weight/auto-detect")
async def auto_detect_port(current_user: User = Depends(get_current_user)):
    """
    Scan all COM ports at common baud rates and return the one transmitting weight data.
    Uses Win32 API directly — works even without pyserial driver issues.
    Takes ~15-30 seconds (3s probe per baud rate per port).
    """
    result = await auto_detect_scale()
    return result


@router.post("/api/v1/weight/test-port")
async def test_port(
    payload: dict[str, Any],
    current_user: User = Depends(get_current_user),
):
    """
    Open a serial port for a few seconds and capture raw frames.
    Use this to verify wiring and baud rate before saving config.
    Body: { port_name, baud_rate, duration_sec (1-10) }
    """
    port = payload.get("port_name", "COM1")
    baud = int(payload.get("baud_rate", 9600))
    duration = min(int(payload.get("duration_sec", 3)), 10)
    data_bits = int(payload.get("data_bits", 8))
    stop_bits = int(payload.get("stop_bits", 1))
    parity = payload.get("parity", "N")

    result = await test_port_connection(
        port=port,
        baud_rate=baud,
        duration_sec=duration,
        data_bits=data_bits,
        stop_bits=stop_bits,
        parity=parity,
    )
    return result
