"""Edge → cloud HTTP transport.

Two calls to the cloud, both agent-key authed (``{tenant, agent_key}`` in the
body — never a user JWT, so they bypass the tenant middleware's module gate):

  * ``fetch_masters``  — pull the masters snapshot for the local mirror.
  * ``make_push``      — build the ``PushFn`` the replay engine drains intents
                         through (one intent per POST to /offline/replay-one).

The apex→subdomain routing bug that bit the scale agent is reused here: the apex
weighbridgesetu.com 301-redirects to www, and a 301 turns a POST into a GET that
drops the body, so a reading/intent silently never lands. Route to the tenant's
own subdomain, which does not redirect.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from agents.edge.replay import PushResult

log = logging.getLogger("edge.cloud")

PRODUCT_DOMAIN = "weighbridgesetu.com"


def push_base(cfg: dict[str, Any]) -> str:
    """Base URL for cloud calls; routes the apex/www host to <slug>.<domain>."""
    base = (cfg.get("cloud_url") or "").rstrip("/")
    if base and "://" not in base:
        base = "https://" + base
    slug = cfg.get("tenant_slug") or ""
    try:
        parts = urlparse(base)
        host = (parts.hostname or "").lower()
    except Exception:
        return base
    if slug and host in (PRODUCT_DOMAIN, f"www.{PRODUCT_DOMAIN}"):
        return f"{parts.scheme or 'https'}://{slug}.{PRODUCT_DOMAIN}"
    return base


def _auth(cfg: dict[str, Any]) -> dict[str, Any]:
    return {"tenant": cfg.get("tenant_slug"), "agent_key": cfg.get("agent_key")}


async def fetch_masters(cfg: dict[str, Any], *, timeout: float = 30.0) -> dict[str, Any]:
    """Pull the full masters snapshot. Raises on any non-2xx / network error
    (the caller treats that as 'offline' and skips the mirror this cycle)."""
    url = push_base(cfg).rstrip("/") + "/api/v1/offline/masters"
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=_auth(cfg))
    r.raise_for_status()
    return r.json()


def make_push(cfg: dict[str, Any], *, timeout: float = 20.0):
    """Return an async ``push(intent) -> PushResult`` for ``replay.replay``."""
    url = push_base(cfg).rstrip("/") + "/api/v1/offline/replay-one"

    async def push(intent: dict[str, Any]) -> PushResult:
        body = {
            **_auth(cfg),
            "op_type": intent.get("op_type"),
            "entity_id": intent.get("entity_id"),
            "payload": intent.get("payload") or {},
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(url, json=body)
        except httpx.RequestError as e:                 # DNS/connect/read timeout → transient
            return PushResult(status=None, error=f"{type(e).__name__}: {e}")

        data: Any = None
        try:
            data = r.json()
        except Exception:
            pass

        if 200 <= r.status_code < 300:
            assigned = data.get("assigned") if isinstance(data, dict) else None
            return PushResult(status=r.status_code, body=assigned or data)

        detail = data.get("detail") if isinstance(data, dict) else None
        return PushResult(status=r.status_code, error=detail or f"HTTP {r.status_code}")

    return push
