"""Barrier relay trigger service (H3-D).

Fires an HTTP request to a configured relay endpoint when ANPR detects
a registered vehicle entry or exit. Non-blocking — any failure is logged
but never propagates to the caller.

Supported relay types for v1:
  http  — GET/POST to a URL (covers ESP8266/ESP32 boards, smart plugs, webhook relays)

Future: serial (USB relay boards), mqtt — not built in v1 to keep this simple.

Config key: 'barrier_config' in app_settings.
"""
import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "enabled": False,
    "trigger_entry": True,       # open on vehicle entry
    "trigger_exit": True,        # open on vehicle exit
    "trigger_unknown": False,    # open for unknown/unregistered plates
    "relay_type": "http",
    "http_url": "",              # e.g. http://192.168.1.100/relay/1
    "http_method": "GET",        # GET or POST
    "http_open_param": "?state=on&duration=5",   # appended to URL
    "http_auth_user": "",
    "http_auth_pass": "",
    "open_duration_sec": 5,
    "timeout_sec": 3,
}


async def _load_config(db) -> dict:
    """Load barrier config from app_settings, merge with defaults."""
    try:
        from sqlalchemy import text
        row = (await db.execute(
            text("SELECT value FROM app_settings WHERE key = 'barrier_config' LIMIT 1")
        )).fetchone()
        if row:
            stored = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
            return {**DEFAULT_CONFIG, **stored}
    except Exception:
        pass
    return dict(DEFAULT_CONFIG)


async def trigger_barrier(
    db,
    direction: str,
    vehicle_no: str,
    gate_pass_no: Optional[str] = None,
) -> None:
    """Called from ANPR handler as a BackgroundTask. Never raises."""
    try:
        cfg = await _load_config(db)
        if not cfg.get("enabled"):
            return
        if direction == "entry" and not cfg.get("trigger_entry"):
            return
        if direction == "exit" and not cfg.get("trigger_exit"):
            return

        url: str = cfg.get("http_url", "").strip()
        if not url:
            logger.warning("barrier_trigger: enabled but http_url is empty")
            return

        # Build full URL
        param = cfg.get("http_open_param", "").strip()
        full_url = url + param

        auth = None
        if cfg.get("http_auth_user"):
            auth = (cfg["http_auth_user"], cfg.get("http_auth_pass", ""))

        method = cfg.get("http_method", "GET").upper()
        timeout = float(cfg.get("timeout_sec", 3))

        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "POST":
                resp = await client.post(full_url, auth=auth)
            else:
                resp = await client.get(full_url, auth=auth)

        logger.info(
            "barrier_trigger: %s %s → HTTP %s (vehicle=%s gp=%s)",
            direction, full_url, resp.status_code, vehicle_no, gate_pass_no,
        )
    except Exception as exc:
        logger.warning("barrier_trigger: failed for %s %s — %s", direction, vehicle_no, exc)
