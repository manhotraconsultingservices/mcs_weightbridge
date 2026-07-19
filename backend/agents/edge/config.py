"""Edge agent configuration.

Anchored to the folder the program lives in (frozen-EXE safe, same rule as the
scale/tally agents) so a built .exe reads edge_config.json sitting next to it.
Everything client-specific comes from this JSON — the binary is client-agnostic.
"""
from __future__ import annotations

import copy
import json
import os
import socket
import sys
from pathlib import Path

if getattr(sys, "frozen", False) or "__compiled__" in globals():
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

CONFIG_FILE = BASE_DIR / "edge_config.json"
DEFAULT_DB_PATH = str(BASE_DIR / "weighbridge_edge.db")

# API port: deliberately clear of the other agents' ranges
#   scale 9002–9006 · camera 9003–9005 · tally 9010–9014.
# The edge API sits at 9007 and steps up to 9009 if busy (still below Tally).
DEFAULT_API_PORT = 9007
API_PORT_RANGE = 3

DEFAULT_CONFIG: dict = {
    "cloud_url": "https://weighbridgesetu.com",
    "tenant_slug": "",
    "agent_key": "",
    # Terminal tag (1–2 chars) used in offline-issued numbers, e.g. gate pass
    # GP/<date>/B1-007. One per weighbridge PC so two terminals never collide.
    "terminal_tag": "B1",
    "api_port": DEFAULT_API_PORT,
    "db_path": DEFAULT_DB_PATH,
    # Cloud sync loop cadence + local retention for the 04:05 conditional prune.
    "sync_interval_sec": 30,
    "retain_days": 7,
    # Optional — a SKIPPED prune (unsynced work pending at 04:00) alerts here.
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    # Extra browser origins allowed to call the edge API (LAN dev, etc.).
    # The tenant subdomain + apex are derived automatically from cloud_url.
    "allowed_origins": [],
    # How often (seconds) to pull master data from the cloud while online.
    "mirror_interval_sec": 300,
}


def default_terminal_id() -> str:
    return f"edge-{socket.gethostname()}"[:64]


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        raise SystemExit(
            f"Config not found: {CONFIG_FILE}\nRun: edge_agent --setup"
        )
    with open(CONFIG_FILE, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(data)
    if not cfg.get("db_path"):
        cfg["db_path"] = DEFAULT_DB_PATH
    return cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)


def allowed_origins(cfg: dict) -> set[str]:
    """Browser origins permitted to call the edge API (never a wildcard —
    this listens on the operator's PC and handles transactions)."""
    origins: set[str] = set()
    from urllib.parse import urlsplit

    cloud_url = str(cfg.get("cloud_url") or "").strip()
    slug = str(cfg.get("tenant_slug") or "").strip().lower()
    host = ""
    if cloud_url:
        parts = urlsplit(cloud_url if "//" in cloud_url else f"https://{cloud_url}")
        host = (parts.hostname or "").lower()

    base = host
    for prefix in ((f"{slug}." if slug else None), "www."):
        if prefix and base.startswith(prefix):
            base = base[len(prefix):]
            break
    if not base:
        base = "weighbridgesetu.com"
    origins.add(f"https://{base}")
    origins.add(f"https://www.{base}")
    if slug:
        origins.add(f"https://{slug}.{base}")
    origins.add("http://localhost:9000")   # local dev
    for extra in (cfg.get("allowed_origins") or []):
        extra = str(extra).strip().rstrip("/")
        if extra:
            origins.add(extra)
    return {o for o in origins if "://" in o}
