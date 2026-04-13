import asyncio
import logging
import socket
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.routers import (
    auth, company, products, parties, vehicles, tokens,
    weight, invoices, quotations, payments, dashboard, reports,
    usb_guard, private_invoices, notifications, audit, backup, import_data,
    tally, app_settings, license, compliance, cameras, inventory,
)
from app.middleware.license_guard import LicenseGuardMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.services.license import validate_license, LicenseError

logger = logging.getLogger(__name__)


# ── Background license re-checker (runs every 6 hours) ─────────────────────

async def _license_recheck_loop(app: FastAPI):
    """Periodically re-validate license to catch mid-day expiration.
    Runs in a supervised wrapper — crashes restart after 60 s.
    """
    while True:
        await asyncio.sleep(6 * 3600)  # 6 hours
        try:
            # validate_license() is synchronous — run in thread with timeout
            loop = asyncio.get_event_loop()
            lic = await asyncio.wait_for(
                loop.run_in_executor(None, validate_license),
                timeout=30.0,
            )
            app.state.license_valid = True
            app.state.license_error = None
            logger.info("License re-check OK: %s, %d days remaining", lic.serial, lic.days_remaining)
        except asyncio.TimeoutError:
            logger.error("License re-check timed out after 30 s — keeping current state")
        except LicenseError as e:
            app.state.license_valid = False
            app.state.license_error = str(e)
            logger.critical("License re-check FAILED: %s", e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("License re-check unexpected error: %s", e)


async def _supervised(name: str, coro, restart_delay: int = 60):
    """Wrap a background coroutine so it auto-restarts if it raises unexpectedly."""
    while True:
        try:
            await coro
            return  # coroutine exited cleanly — don't restart
        except asyncio.CancelledError:
            logger.info("Background task '%s' cancelled", name)
            raise
        except Exception as exc:
            logger.error(
                "Background task '%s' crashed: %s — restarting in %d s",
                name, exc, restart_delay,
            )
            await asyncio.sleep(restart_delay)



# ── Inventory daily Telegram report (runs every minute, fires at configured time) ─

_last_inv_report_date = None   # module-level; prevents double-send within same minute


async def _inventory_daily_report_loop():
    """Send inventory Telegram report once per day at configured time (default 20:00)."""
    global _last_inv_report_date
    from datetime import date as _date_cls

    while True:
        await asyncio.sleep(60)   # check every minute
        try:
            from app.database import async_session
            from sqlalchemy import text as _sql

            async with async_session() as db:
                rows = (await db.execute(_sql(
                    "SELECT key, value FROM app_settings WHERE key IN ("
                    " 'inventory.telegram_bot_token',"
                    " 'inventory.telegram_chat_id',"
                    " 'inventory.telegram_report_time',"
                    " 'inventory.telegram_enabled'"
                    ")"
                ))).fetchall()
                cfg = {r[0]: r[1] for r in rows}

                if cfg.get("inventory.telegram_enabled") != "true":
                    continue

                report_time = cfg.get("inventory.telegram_report_time", "20:00")
                try:
                    hh, mm = map(int, report_time.split(":"))
                except Exception:
                    hh, mm = 20, 0

                import datetime as _dt
                now = _dt.datetime.now()
                if now.hour != hh or now.minute != mm:
                    continue

                today = _date_cls.today()
                if _last_inv_report_date == today:
                    continue   # already sent today
                _last_inv_report_date = today

                # Fetch items
                items_rows = (await db.execute(_sql(
                    "SELECT name, unit, current_stock, min_stock_level "
                    "FROM inventory_items WHERE is_active = TRUE ORDER BY category, name"
                ))).fetchall()
                items = [
                    {
                        "name": r[0], "unit": r[1],
                        "current_stock": float(r[2]),
                        "min_stock_level": float(r[3]),
                        "stock_status": (
                            "out" if float(r[2]) <= 0
                            else ("low" if float(r[2]) <= float(r[3]) else "ok")
                        ),
                    }
                    for r in items_rows
                ]

                today_str = today.isoformat()
                today_issues = (await db.execute(_sql(
                    "SELECT COUNT(*) FROM inventory_transactions "
                    "WHERE transaction_type='issue' AND DATE(created_at)=:d"
                ), {"d": today_str})).scalar() or 0
                today_receipts = (await db.execute(_sql(
                    "SELECT COUNT(DISTINCT reference_id) FROM inventory_transactions "
                    "WHERE transaction_type='receipt' AND DATE(created_at)=:d "
                    "AND reference_id IS NOT NULL"
                ), {"d": today_str})).scalar() or 0

                company_name = (await db.execute(_sql(
                    "SELECT name FROM companies LIMIT 1"
                ))).scalar() or "WeighBridge Pro"

                token = cfg.get("inventory.telegram_bot_token", "")
                chat  = cfg.get("inventory.telegram_chat_id", "")
                if not token or not chat:
                    continue

                from app.integrations.notifications.telegram import (
                    send_telegram_message, build_daily_report
                )
                report_date = today.strftime("%d %b %Y")
                msg = build_daily_report(
                    items, int(today_issues), int(today_receipts),
                    company_name, report_date
                )
                await send_telegram_message(token, chat, msg)
                logger.info("Inventory daily Telegram report sent to chat_id=%s", chat)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Inventory daily report error: %s", exc)


# ── AMC auto-expiry background task (multi-tenant only) ──────────────────────

_last_amc_check_date = None

async def _amc_expiry_check_loop():
    """Daily check: auto-set tenants to readonly when AMC expires."""
    global _last_amc_check_date
    from datetime import date as _date_cls

    while True:
        await asyncio.sleep(60)  # check every minute
        try:
            from app.config import get_settings as _gs
            if not _gs().MULTI_TENANT:
                continue

            today = _date_cls.today()
            if _last_amc_check_date == today:
                continue

            # Only run at midnight-ish (0:00-0:05)
            import datetime as _dt
            now = _dt.datetime.now()
            if now.hour != 0 or now.minute > 5:
                continue

            _last_amc_check_date = today

            from app.multitenancy.master_db import get_master_session_factory
            from sqlalchemy import text as _sql
            factory = get_master_session_factory()
            async with factory() as db:
                # Find active tenants whose AMC has expired
                result = await db.execute(_sql("""
                    UPDATE tenants SET status = 'readonly', updated_at = NOW()
                    WHERE status = 'active'
                      AND amc_expiry_date IS NOT NULL
                      AND amc_expiry_date < :today
                    RETURNING slug, amc_expiry_date
                """), {"today": today})
                expired = result.fetchall()
                await db.commit()

                for row in expired:
                    logger.warning("AMC EXPIRED: tenant '%s' set to readonly (expired %s)", row[0], row[1])
                    # Invalidate status cache
                    from app.multitenancy.middleware import invalidate_tenant_status_cache
                    invalidate_tenant_status_cache(row[0])

                if expired:
                    logger.info("AMC check: %d tenant(s) moved to readonly", len(expired))

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("AMC expiry check error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── License validation ──────────────────────────────────────────────────
    try:
        lic = validate_license()
        app.state.license_valid = True
        app.state.license_error = None
        logger.info("License valid: %s, serial=%s, expires=%s (%d days)",
                     lic.customer, lic.serial, lic.expires, lic.days_remaining)
    except LicenseError as e:
        app.state.license_valid = False
        app.state.license_error = str(e)
        logger.critical("LICENSE ERROR: %s", e)

    # Start background tasks inside supervised wrappers — auto-restart on crash
    recheck_task = asyncio.create_task(
        _supervised("license-recheck", _license_recheck_loop(app), restart_delay=300)
    )
    daily_inv_task = asyncio.create_task(
        _supervised("inventory-telegram", _inventory_daily_report_loop(), restart_delay=120)
    )
    amc_task = asyncio.create_task(
        _supervised("amc-expiry-check", _amc_expiry_check_loop(), restart_delay=300)
    )

    # ── Startup ─────────────────────────────────────────────────────────────
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.database import async_session
    from app.models.settings import SerialPortConfig
    from sqlalchemy import select, text as _text
    from app.config import get_settings as _get_settings
    _settings = _get_settings()

    # ── Ensure runtime tables exist ──────────────────────────────────────────
    from app.ddl import get_runtime_ddl, get_column_migrations, get_supplier_ddl, get_supplier_master_ddl
    runtime_ddl = get_runtime_ddl()
    column_migrations = get_column_migrations()
    supplier_ddl_sql = get_supplier_ddl()
    supplier_master_ddl_sql = get_supplier_master_ddl()

    # ── Helper to run all DDL on a single database ────────────────────────────
    async def _apply_all_ddl(session_factory, label: str = "default"):
        """Execute runtime DDL + column migrations + extra tables on one DB."""
        try:
            async with session_factory() as db:
                for ddl in runtime_ddl:
                    await db.execute(_text(ddl))
                await db.commit()
        except Exception as e:
            logger.warning("Could not create runtime tables [%s]: %s", label, e)

        try:
            async with session_factory() as db:
                await db.execute(_text(supplier_ddl_sql))
                await db.commit()
        except Exception as e:
            logger.warning("Could not create inventory_item_suppliers [%s]: %s", label, e)

        try:
            async with session_factory() as db:
                await db.execute(_text(supplier_master_ddl_sql))
                await db.commit()
        except Exception as e:
            logger.warning("Could not create inventory_suppliers [%s]: %s", label, e)

        try:
            async with session_factory() as db:
                await db.execute(_text(
                    "ALTER TABLE inventory_item_suppliers ADD COLUMN IF NOT EXISTS master_supplier_id UUID REFERENCES inventory_suppliers(id)"
                ))
                await db.commit()
        except Exception as e:
            logger.warning("Could not add master_supplier_id column [%s]: %s", label, e)

        try:
            async with session_factory() as db:
                for migration in column_migrations:
                    await db.execute(_text(migration))
                await db.commit()
        except Exception as e:
            logger.warning("Could not run column migrations [%s]: %s", label, e)

    # ── Apply DDL: multi-tenant iterates all tenant DBs, single-tenant uses default
    if _settings.MULTI_TENANT:
        # Initialize master database first
        from app.multitenancy.master_db import init_master_db
        await init_master_db()
        logger.info("Multi-tenant mode: master DB initialized")

        # Run DDL on all active tenant databases
        from app.multitenancy.registry import tenant_registry
        _tenants = await tenant_registry.list_active_tenants()
        for _t in _tenants:
            try:
                _t_factory = await tenant_registry.get_session_factory(_t.slug)
                await _apply_all_ddl(_t_factory, label=_t.slug)
                logger.info("DDL migrations OK for tenant: %s", _t.slug)
            except Exception as e:
                logger.error("DDL migration FAILED for tenant %s: %s", _t.slug, e)

        # Skip serial port init in multi-tenant mode (agents handle weight per-tenant)
        logger.info("Multi-tenant: serial port init skipped (use agent per client)")
    else:
        # Single-tenant: apply to default database
        await _apply_all_ddl(async_session, label="default")

        # ── Weight scale (single-tenant only) ────────────────────────────────
        try:
            async with async_session() as db:
                result = await db.execute(select(SerialPortConfig).limit(1))
                cfg = result.scalar_one_or_none()
                if cfg and cfg.is_enabled:
                    import json
                    protocol_config = {}
                    if cfg.protocol_config:
                        try:
                            protocol_config = json.loads(cfg.protocol_config)
                        except Exception:
                            pass
                    from app.integrations.serial_port.manager import init_weight_manager
                    await init_weight_manager(
                        port=cfg.port_name,
                        baud_rate=cfg.baud_rate,
                        data_bits=cfg.data_bits,
                        stop_bits=cfg.stop_bits,
                        parity=cfg.parity,
                        protocol=cfg.protocol,
                        protocol_config=protocol_config,
                        stability_readings=cfg.stability_readings,
                        stability_tolerance_kg=float(cfg.stability_tolerance_kg),
                    )
        except Exception as e:
            logger.warning("Could not start weight manager: %s", e)

        # ── Seed notification templates + ensure default recipients ──────────
        try:
            from app.integrations.notifications.service import seed_default_templates
            from app.models.company import Company as _Company
            from app.models.notification import NotificationRecipient as _NR
            import json as _json
            async with async_session() as db:
                co = (await db.execute(select(_Company).limit(1))).scalar_one_or_none()
                if co:
                    await seed_default_templates(db, co.id)

                    # Ensure default named recipients exist (idempotent by contact)
                    default_recipients = [
                        {"name": "Ankush",  "channel": "telegram", "contact": "6613370540"},
                        {"name": "RM",      "channel": "telegram", "contact": "11003601151496"},
                        {"name": "A",       "channel": "telegram", "contact": "1988828526"},
                        {"name": "Ankush",  "channel": "email",    "contact": "ankushmanhotra@gmail.com"},
                        {"name": "Rishu",   "channel": "email",    "contact": "rishumanhotra@gmail.com"},
                    ]
                    existing_contacts = {
                        (r.channel, r.contact)
                        for r in (await db.execute(
                            select(_NR.channel, _NR.contact).where(_NR.company_id == co.id)
                        )).all()
                    }
                    for rec in default_recipients:
                        key = (rec["channel"], rec["contact"])
                        if key not in existing_contacts:
                            db.add(_NR(
                                company_id=co.id,
                                name=rec["name"],
                                channel=rec["channel"],
                                contact=rec["contact"],
                                event_types=_json.dumps(["*"]),
                                is_active=True,
                            ))
                    await db.commit()
                    logger.info("Notification templates seeded; default recipients ensured.")
        except Exception as e:
            logger.warning("Could not seed notification templates/recipients: %s", e)

    yield

    # Shutdown
    recheck_task.cancel()
    daily_inv_task.cancel()
    from app.integrations.serial_port.manager import get_weight_manager
    mgr = get_weight_manager()
    if mgr:
        await mgr.stop()

    # Dispose multi-tenant engines
    if _settings.MULTI_TENANT:
        from app.multitenancy.registry import tenant_registry
        await tenant_registry.dispose_all()
        from app.multitenancy.master_db import dispose_master
        await dispose_master()


app = FastAPI(
    title="Weighbridge Invoice Software",
    description="Stone Crusher Weighbridge Management System with GST & Tally Integration",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Middleware (order matters: outermost first) ──────────────────────────────

# Security headers on all responses
app.add_middleware(SecurityHeadersMiddleware)

# Tenant middleware (must be before auth dependencies resolve)
from app.config import get_settings as _gs
if _gs().MULTI_TENANT:
    from app.multitenancy.middleware import TenantMiddleware
    app.add_middleware(TenantMiddleware)

# License enforcement (blocks API when license invalid)
app.add_middleware(LicenseGuardMiddleware)

# CORS — locked down to known origins
_cors_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:9000",
    "http://127.0.0.1:9000",
]
try:
    _local_ip = socket.gethostbyname(socket.gethostname())
    _cors_origins.append(f"http://{_local_ip}:3000")
    _cors_origins.append(f"http://{_local_ip}:9000")
except Exception:
    pass

# Allow override via CORS_ORIGINS env var (comma-separated)
import os
_env_origins = os.getenv("CORS_ORIGINS")
if _env_origins:
    _cors_origins = [o.strip() for o in _env_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-Super-Admin", "X-Tenant", "X-Agent-Key"],
)

# ── API Routers ───────────────────────────────────────────────────────────────
# Tenant management (multi-tenant only)
if _gs().MULTI_TENANT:
    from app.multitenancy.router import router as _tenant_router, public_router as _tenant_public_router
    app.include_router(_tenant_router, prefix="/api/v1/admin", tags=["Tenant Management"])
    app.include_router(_tenant_public_router, prefix="/api/v1", tags=["Tenant Public"])
    from app.multitenancy.platform_router import router as _platform_router
    app.include_router(_platform_router, prefix="/api/v1/platform", tags=["Platform Admin"])

app.include_router(license.router)  # No auth, must be accessible always
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(company.router, prefix="/api/v1/company", tags=["Company"])
app.include_router(products.router, prefix="/api/v1", tags=["Products"])
app.include_router(parties.router, prefix="/api/v1/parties", tags=["Parties"])
app.include_router(vehicles.router, prefix="/api/v1", tags=["Vehicles & Transport"])
app.include_router(tokens.router)
app.include_router(weight.router)
app.include_router(invoices.router)
app.include_router(quotations.router)
app.include_router(payments.router)
app.include_router(dashboard.router)
app.include_router(reports.router)
app.include_router(usb_guard.router)
app.include_router(private_invoices.router)
app.include_router(notifications.router)
app.include_router(audit.router)
app.include_router(backup.router)
app.include_router(import_data.router)
app.include_router(tally.router)
app.include_router(app_settings.router)
app.include_router(compliance.router)
app.include_router(cameras.router)
app.include_router(cameras.router_tokens)
app.include_router(inventory.router)


@app.get("/api/v1/health")
async def health_check(request: Request):
    """Real health check — used by watchdog and monitoring.
    Returns 200 for healthy/degraded, 503 for unhealthy.
    No authentication required so the watchdog can poll without a token.
    """
    import shutil as _shutil
    import datetime as _datetime

    checks: dict = {}
    overall = "healthy"

    # ── 1. Database ────────────────────────────────────────────────────────────
    try:
        from app.database import async_session
        from sqlalchemy import text as _t
        async with async_session() as _db:
            await asyncio.wait_for(_db.execute(_t("SELECT 1")), timeout=5.0)
        checks["database"] = {"status": "ok"}
    except asyncio.TimeoutError:
        checks["database"] = {"status": "timeout", "detail": "Query took > 5 s"}
        overall = "unhealthy"
    except Exception as exc:
        checks["database"] = {"status": "error", "detail": str(exc)}
        overall = "unhealthy"

    # ── 2. License ─────────────────────────────────────────────────────────────
    lic_valid = getattr(request.app.state, "license_valid", True)
    lic_error = getattr(request.app.state, "license_error", None)
    checks["license"] = {
        "status": "valid" if lic_valid else "expired",
        "detail": lic_error,
    }
    if not lic_valid:
        overall = "degraded"

    # ── 3. Weight scale ────────────────────────────────────────────────────────
    try:
        from app.integrations.serial_port.manager import get_weight_manager
        _mgr = get_weight_manager()
        checks["weight_scale"] = {
            "status": "connected" if (_mgr and getattr(_mgr, "_running", False)) else "disconnected"
        }
    except Exception:
        checks["weight_scale"] = {"status": "unknown"}

    # ── 4. Disk space ──────────────────────────────────────────────────────────
    try:
        _usage = _shutil.disk_usage(os.path.abspath(__file__))
        _free_pct = (_usage.free / _usage.total) * 100
        checks["disk"] = {
            "free_pct": round(_free_pct, 1),
            "free_gb": round(_usage.free / (1024 ** 3), 1),
            "status": "ok" if _free_pct > 10 else "critical",
        }
        if _free_pct < 10:
            overall = "degraded"
            logger.warning("Disk critically low: %.1f%% free", _free_pct)
    except Exception:
        checks["disk"] = {"status": "unknown"}

    from fastapi.responses import JSONResponse as _JR
    status_code = 503 if overall == "unhealthy" else 200
    return _JR({
        "status": overall,
        "app": "Weighbridge Invoice Software",
        "multi_tenant": _gs().MULTI_TENANT,
        "timestamp": _datetime.datetime.utcnow().isoformat() + "Z",
        "checks": checks,
    }, status_code=status_code)


# ── Frontend static file serving ─────────────────────────────────────────────
# In the compiled release the React build (frontend/dist/) sits next to the
# .exe.  In dev the dist/ folder may not exist — serving is silently skipped
# so the Vite dev server on port 9000 continues to work unchanged.

import sys as _sys
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse as _FileResponse


def _resolve_frontend_dist() -> str | None:
    """Return the path to frontend/dist/ if it exists, else None."""
    if getattr(_sys, "frozen", False):
        # PyInstaller: look for frontend/dist/ next to weighbridge.exe
        base = os.path.dirname(_sys.executable)
    else:
        # Source: project root is 3 levels up from backend/app/main.py
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    dist = os.path.join(base, "frontend", "dist")
    return dist if os.path.isdir(dist) else None


_frontend_dist = _resolve_frontend_dist()

# ── Uploads directory (wallpaper, etc.) ──────────────────────────────────────
_uploads_base = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "uploads",
)
os.makedirs(os.path.join(_uploads_base, "wallpaper"), exist_ok=True)
os.makedirs(os.path.join(_uploads_base, "camera"), exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_uploads_base), name="uploads")

if _frontend_dist:
    _assets = os.path.join(_frontend_dist, "assets")
    if os.path.isdir(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="fe_assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _serve_spa(full_path: str):
        """Catch-all: serve index.html for every non-API path (SPA routing)."""
        return _FileResponse(os.path.join(_frontend_dist, "index.html"))
