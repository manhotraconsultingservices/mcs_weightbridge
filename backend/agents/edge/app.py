"""Edge agent FastAPI app — the local mini-backend for offline operation.

Security posture (same as the scale agent's status server): binds 127.0.0.1
ONLY and restricts CORS to the tenant's own origin. The browser reaching it is
therefore on this PC, served from this tenant's site. Operator identity +
offline unlock harden this further in a later step (auth across an outage).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agents.edge import routes
from agents.edge.config import allowed_origins
from agents.edge.db import init_db

EDGE_VERSION = "0.1.0"


def create_app(cfg: dict) -> FastAPI:
    routes.set_terminal_tag(cfg.get("terminal_tag", "B1"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_db(cfg["db_path"])
        yield

    app = FastAPI(title="Weighbridge Edge Agent", version=EDGE_VERSION, lifespan=lifespan)

    origins = sorted(allowed_origins(cfg))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,          # never "*": this handles transactions
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["content-type", "authorization"],
        max_age=600,
    )

    @app.get("/api/v1/health")
    async def health():
        return {
            "service": "weighbridge_edge",
            "status": "running",
            "edge_version": EDGE_VERSION,
            "tenant_slug": cfg.get("tenant_slug"),
            "mode": "offline-capable",
        }

    app.include_router(routes.router)
    return app


def main() -> None:  # pragma: no cover - runtime entrypoint
    import uvicorn
    from agents.edge.config import load_config, DEFAULT_API_PORT, API_PORT_RANGE

    cfg = load_config()
    app = create_app(cfg)
    base = int(cfg.get("api_port", DEFAULT_API_PORT))
    # 127.0.0.1 only — the edge API is never exposed to the LAN.
    for port in range(base, base + API_PORT_RANGE):
        try:
            uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
            return
        except OSError:
            continue
    raise SystemExit(f"edge API: ports {base}-{base + API_PORT_RANGE - 1} all busy")


if __name__ == "__main__":  # pragma: no cover
    main()
