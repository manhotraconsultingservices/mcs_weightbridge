"""Edge agent FastAPI app — the local mini-backend for offline operation.

Security posture (same as the scale agent's status server): binds 127.0.0.1
ONLY and restricts CORS to the tenant's own origin. The browser reaching it is
therefore on this PC, served from this tenant's site. Operator identity +
offline unlock harden this further in a later step (auth across an outage).
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agents.edge import routes, sync
from agents.edge.config import allowed_origins
from agents.edge.db import init_db

EDGE_VERSION = "0.1.0"

log = logging.getLogger("edge.app")


def create_app(cfg: dict) -> FastAPI:
    routes.set_terminal_tag(cfg.get("terminal_tag", "B1"))
    sync_interval = float(cfg.get("sync_interval_sec", 30))
    # Only run the cloud sync loop when we know which tenant to sync to.
    sync_enabled = bool(cfg.get("cloud_url") and cfg.get("tenant_slug") and cfg.get("agent_key"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_db(cfg["db_path"])
        stop = asyncio.Event()
        task = None
        if sync_enabled:
            task = asyncio.create_task(sync.run_loop(cfg, stop, interval=sync_interval))
        else:
            log.warning("edge sync loop NOT started — cloud_url/tenant_slug/agent_key missing")
        try:
            yield
        finally:
            stop.set()
            if task is not None:
                try:
                    await asyncio.wait_for(task, timeout=5)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    task.cancel()

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
            "sync_enabled": sync_enabled,
        }

    @app.get("/api/v1/sync/status")
    async def sync_status():
        """Spool depth by status — powers the operator's 'N pending to sync' pill."""
        counts = await sync.pending_summary()
        pending = sum(v for k, v in counts.items() if k != "done")
        return {"spool": counts, "pending": pending,
                "needs_review": counts.get("needs_review", 0),
                "needs_auth": counts.get("needs_auth", 0)}

    @app.post("/api/v1/sync/now")
    async def sync_now():
        """Force one mirror+replay cycle (used by a manual 'Sync now' action)."""
        if not sync_enabled:
            return {"online": False, "error": "sync not configured"}
        return await sync.sync_once(cfg)

    app.include_router(routes.router)
    return app


SERVICE_NAME = "WeighbridgeEdgeAgent"
RESTART_TASK = "WeighbridgeEdgeRestart"
PRUNE_TASK = "WeighbridgeEdgePrune"


def _serve(cfg: dict) -> None:  # pragma: no cover - runtime entrypoint
    import uvicorn
    from agents.edge.config import DEFAULT_API_PORT, API_PORT_RANGE
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


async def _test(cfg: dict) -> int:  # pragma: no cover
    """--test: init the DB, then probe cloud reachability (masters pull)."""
    from agents.edge.db import init_db
    from agents.edge import cloud
    print(f"[edge] db_path      : {cfg.get('db_path')}")
    print(f"[edge] cloud_url    : {cfg.get('cloud_url')}  (tenant {cfg.get('tenant_slug')})")
    await init_db(cfg["db_path"])
    print("[edge] SQLite schema : OK")
    if not (cfg.get("cloud_url") and cfg.get("tenant_slug") and cfg.get("agent_key")):
        print("[edge] cloud sync   : NOT configured (cloud_url/tenant_slug/agent_key missing)")
        return 1
    try:
        snap = await cloud.fetch_masters(cfg)
        n = snap.get("row_count", 0)
        print(f"[edge] cloud masters : OK — {n} master rows available to mirror")
        return 0
    except Exception as e:
        print(f"[edge] cloud masters : FAILED — {type(e).__name__}: {e}")
        return 1


def _install(cfg: dict) -> None:  # pragma: no cover
    """Register the NSSM service + the 04:00 restart and 04:05 prune tasks.

    Runs from .py SOURCE (python -m agents.edge.app), which sidesteps the
    Smart App Control per-file-reputation block that kills unsigned PyInstaller
    EXEs — the reliable path for these hand-installed agents.
    """
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    nssm = shutil.which("nssm")
    if not nssm:
        print("NSSM not found. Download from https://nssm.cc and add it to PATH.")
        raise SystemExit(1)
    py = str(Path(sys.executable).resolve())
    backend_dir = str(Path(__file__).resolve().parents[2])   # …/backend

    subprocess.run([nssm, "install", SERVICE_NAME, py, "-m", "agents.edge.app"], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppDirectory", backend_dir], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppStdout", str(Path(backend_dir) / "agents" / "logs" / "edge_stdout.log")], check=False)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppStderr", str(Path(backend_dir) / "agents" / "logs" / "edge_stderr.log")], check=False)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppRotateFiles", "1"], check=False)
    subprocess.run([nssm, "set", SERVICE_NAME, "Start", "SERVICE_AUTO_START"], check=False)

    # Daily 04:00 restart (clears leaks / wedged sockets — a known-good baseline).
    subprocess.run(["schtasks", "/create", "/f", "/tn", RESTART_TASK, "/sc", "daily",
                    "/st", "04:00", "/ru", "SYSTEM",
                    "/tr", f'"{nssm}" restart {SERVICE_NAME}'], check=False)
    # Daily 04:05 conditional prune (skips entirely if anything is unsynced).
    subprocess.run(["schtasks", "/create", "/f", "/tn", PRUNE_TASK, "/sc", "daily",
                    "/st", "04:05", "/ru", "SYSTEM",
                    "/tr", f'"{py}" -m agents.edge.prune'], check=False)

    print(f"Installed service '{SERVICE_NAME}' + tasks '{RESTART_TASK}' (04:00) / '{PRUNE_TASK}' (04:05).")
    print(f"Start:  nssm start {SERVICE_NAME}")
    print(f"Status: nssm status {SERVICE_NAME}")


def _uninstall() -> None:  # pragma: no cover
    import shutil
    import subprocess
    nssm = shutil.which("nssm")
    if nssm:
        subprocess.run([nssm, "stop", SERVICE_NAME], check=False)
        subprocess.run([nssm, "remove", SERVICE_NAME, "confirm"], check=False)
    subprocess.run(["schtasks", "/delete", "/f", "/tn", RESTART_TASK], check=False)
    subprocess.run(["schtasks", "/delete", "/f", "/tn", PRUNE_TASK], check=False)
    print(f"Removed '{SERVICE_NAME}' + its scheduled tasks.")


def main() -> None:  # pragma: no cover - runtime entrypoint
    import argparse
    from agents.edge.config import load_config

    p = argparse.ArgumentParser(description="Weighbridge offline edge agent")
    p.add_argument("--test", action="store_true", help="Check DB + cloud reachability and exit")
    p.add_argument("--install", action="store_true", help="Install NSSM service + 04:00 restart/prune tasks")
    p.add_argument("--uninstall", action="store_true", help="Remove the service + tasks")
    args = p.parse_args()

    if args.uninstall:
        _uninstall(); return
    cfg = load_config()
    if args.install:
        _install(cfg); return
    if args.test:
        import asyncio
        raise SystemExit(asyncio.run(_test(cfg)))
    _serve(cfg)


if __name__ == "__main__":  # pragma: no cover
    main()
