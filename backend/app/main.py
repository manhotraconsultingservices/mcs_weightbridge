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

    # ── Startup ─────────────────────────────────────────────────────────────
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.database import async_session
    from app.models.settings import SerialPortConfig
    from sqlalchemy import select, text as _text

    # ── Ensure runtime tables exist ──────────────────────────────────────────
    runtime_ddl = [
        # USB keys (registered USB key UUIDs + HMAC secrets)
        """
        CREATE TABLE IF NOT EXISTS usb_keys (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            key_uuid VARCHAR(200) NOT NULL UNIQUE,
            hmac_secret VARCHAR(200),
            label VARCHAR(200) NOT NULL DEFAULT 'Primary Key',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # USB recovery sessions (admin-created time-limited PINs)
        """
        CREATE TABLE IF NOT EXISTS usb_recovery_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            pin_hash VARCHAR(500) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            created_by UUID REFERENCES users(id),
            reason TEXT DEFAULT '',
            used BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # USB client sessions (per-user, IP-bound)
        """
        CREATE TABLE IF NOT EXISTS usb_client_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            key_uuid VARCHAR(200) NOT NULL,
            created_by UUID REFERENCES users(id),
            expires_at TIMESTAMPTZ NOT NULL,
            ip_address VARCHAR(45),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Add ip_address column if table already existed without it
        "ALTER TABLE usb_client_sessions ADD COLUMN IF NOT EXISTS ip_address VARCHAR(45)",
        # USB nonces (single-use challenge tokens for HMAC auth)
        """
        CREATE TABLE IF NOT EXISTS usb_nonces (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            nonce VARCHAR(200) NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # USB lockouts (rate limiting per scope)
        """
        CREATE TABLE IF NOT EXISTS usb_lockouts (
            scope VARCHAR(200) PRIMARY KEY,
            fail_count INTEGER NOT NULL DEFAULT 0,
            locked_until TIMESTAMPTZ,
            last_attempt TIMESTAMPTZ
        )
        """,
        # USB auth log (audit trail for all USB auth events)
        """
        CREATE TABLE IF NOT EXISTS usb_auth_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id),
            event_type VARCHAR(50) NOT NULL,
            method VARCHAR(30),
            success BOOLEAN NOT NULL DEFAULT FALSE,
            ip_address VARCHAR(45),
            detail TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Add used column to recovery sessions if it already existed without it
        "ALTER TABLE usb_recovery_sessions ADD COLUMN IF NOT EXISTS used BOOLEAN NOT NULL DEFAULT FALSE",
        # Notification config
        """
        CREATE TABLE IF NOT EXISTS notification_config (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            channel VARCHAR(20) NOT NULL,
            is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            smtp_host VARCHAR(200),
            smtp_port INTEGER,
            smtp_user VARCHAR(200),
            smtp_password VARCHAR(500),
            from_email VARCHAR(200),
            from_name VARCHAR(200),
            use_tls BOOLEAN NOT NULL DEFAULT TRUE,
            sms_api_key VARCHAR(500),
            sms_sender_id VARCHAR(20),
            sms_route VARCHAR(10) DEFAULT '4',
            wa_api_url VARCHAR(500),
            wa_api_key VARCHAR(500),
            wa_phone_number_id VARCHAR(50),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Notification templates
        """
        CREATE TABLE IF NOT EXISTS notification_templates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            event_type VARCHAR(50) NOT NULL,
            channel VARCHAR(20) NOT NULL,
            name VARCHAR(200) NOT NULL,
            subject VARCHAR(500),
            body TEXT NOT NULL,
            is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Notification log
        """
        CREATE TABLE IF NOT EXISTS notification_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            channel VARCHAR(20) NOT NULL,
            event_type VARCHAR(50) NOT NULL,
            entity_type VARCHAR(50),
            entity_id VARCHAR(50),
            recipient VARCHAR(300) NOT NULL,
            subject VARCHAR(500),
            body_preview VARCHAR(500),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            error_message TEXT,
            sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Audit log (ensure exists; model uses audit_log table name)
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            user_id UUID REFERENCES users(id),
            action VARCHAR(20) NOT NULL,
            entity_type VARCHAR(50) NOT NULL,
            entity_id VARCHAR(50),
            details TEXT,
            ip_address VARCHAR(45),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Supplementary entries (private non-GST invoices, AES-256-GCM encrypted)
        """
        CREATE TABLE IF NOT EXISTS supplementary_entries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            invoice_no VARCHAR(50) NOT NULL,
            invoice_date DATE NOT NULL,
            customer_name VARCHAR(200),
            vehicle_no VARCHAR(50),
            net_weight NUMERIC(12,2),
            rate NUMERIC(12,2),
            amount NUMERIC(12,2) NOT NULL DEFAULT 0,
            notes TEXT,
            customer_name_enc TEXT,
            vehicle_no_enc TEXT,
            net_weight_enc TEXT,
            rate_enc TEXT,
            amount_enc TEXT,
            notes_enc TEXT,
            payment_mode TEXT,
            integrity_hash VARCHAR(200),
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Gap-free supplement sequence (replaces COUNT(*)+1 approach)
        "CREATE SEQUENCE IF NOT EXISTS supplement_seq START 1",
        # New columns on tokens table (nullable token_no + is_supplement flag)
        "ALTER TABLE tokens ALTER COLUMN token_no DROP NOT NULL",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS is_supplement BOOLEAN NOT NULL DEFAULT FALSE",
        # invoice_no now assigned at finalise — make nullable
        "ALTER TABLE invoices ALTER COLUMN invoice_no DROP NOT NULL",
        # New token-context columns on supplementary_entries for cross-reference
        "ALTER TABLE supplementary_entries ADD COLUMN IF NOT EXISTS token_id UUID REFERENCES tokens(id)",
        "ALTER TABLE supplementary_entries ADD COLUMN IF NOT EXISTS token_no_enc TEXT",
        "ALTER TABLE supplementary_entries ADD COLUMN IF NOT EXISTS token_date_enc TEXT",
        "ALTER TABLE supplementary_entries ADD COLUMN IF NOT EXISTS gross_weight_enc TEXT",
        "ALTER TABLE supplementary_entries ADD COLUMN IF NOT EXISTS tare_weight_enc TEXT",
        # Generic key-value app settings (e.g. urgency thresholds)
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Compliance items: insurance, certifications, licenses, permits
        """
        CREATE TABLE IF NOT EXISTS compliance_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            item_type VARCHAR(50) NOT NULL,
            name VARCHAR(200) NOT NULL,
            policy_holder VARCHAR(200),
            issuer VARCHAR(200),
            reference_no VARCHAR(100),
            issue_date DATE,
            expiry_date DATE,
            file_path TEXT,
            notes TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Camera snapshots: one row per camera per token
        """
        CREATE TABLE IF NOT EXISTS token_snapshots (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            token_id UUID NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
            camera_id VARCHAR(10) NOT NULL,
            camera_label VARCHAR(100),
            file_path TEXT,
            capture_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            captured_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (token_id, camera_id)
        )
        """,
        # ── Inventory Management ──────────────────────────────────────────────
        # Master list of raw material items
        """
        CREATE TABLE IF NOT EXISTS inventory_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            name VARCHAR(200) NOT NULL,
            category VARCHAR(50) NOT NULL,
            unit VARCHAR(30) NOT NULL,
            current_stock NUMERIC(14,3) NOT NULL DEFAULT 0,
            min_stock_level NUMERIC(14,3) NOT NULL DEFAULT 0,
            description TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Immutable audit log of every stock movement
        """
        CREATE TABLE IF NOT EXISTS inventory_transactions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            item_id UUID NOT NULL REFERENCES inventory_items(id),
            transaction_type VARCHAR(20) NOT NULL,
            quantity NUMERIC(14,3) NOT NULL,
            stock_before NUMERIC(14,3) NOT NULL,
            stock_after NUMERIC(14,3) NOT NULL,
            reference_id UUID,
            reference_no VARCHAR(50),
            notes TEXT,
            created_by UUID REFERENCES users(id),
            created_by_name VARCHAR(200),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Purchase Order header
        """
        CREATE TABLE IF NOT EXISTS inventory_purchase_orders (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            po_no VARCHAR(30) NOT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'pending_approval',
            supplier_name VARCHAR(200),
            expected_date DATE,
            notes TEXT,
            requested_by UUID REFERENCES users(id),
            requested_by_name VARCHAR(200) NOT NULL,
            approved_by UUID REFERENCES users(id),
            approved_by_name VARCHAR(200),
            approved_at TIMESTAMPTZ,
            rejection_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Purchase Order line items
        """
        CREATE TABLE IF NOT EXISTS inventory_po_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            po_id UUID NOT NULL REFERENCES inventory_purchase_orders(id) ON DELETE CASCADE,
            item_id UUID NOT NULL REFERENCES inventory_items(id),
            item_name VARCHAR(200) NOT NULL,
            unit VARCHAR(30) NOT NULL,
            quantity_ordered NUMERIC(14,3) NOT NULL,
            quantity_received NUMERIC(14,3) NOT NULL DEFAULT 0,
            unit_price NUMERIC(14,2)
        )
        """,
        # Login lockouts — brute force protection per IP
        """
        CREATE TABLE IF NOT EXISTS login_lockouts (
            scope          VARCHAR(100) PRIMARY KEY,
            fail_count     INTEGER NOT NULL DEFAULT 0,
            locked_until   TIMESTAMPTZ,
            last_attempt   TIMESTAMPTZ
        )
        """,
        # Login audit log — all login events (success + failure)
        """
        CREATE TABLE IF NOT EXISTS login_audit (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            username       VARCHAR(200) NOT NULL,
            user_id        UUID REFERENCES users(id),
            ip_address     VARCHAR(45),
            success        BOOLEAN NOT NULL DEFAULT FALSE,
            detail         TEXT,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ]

    try:
        async with async_session() as db:
            for ddl in runtime_ddl:
                await db.execute(_text(ddl))
            await db.commit()
    except Exception as e:
        logger.warning("Could not create runtime tables: %s", e)

    # ── Column migrations (safe ALTER TABLE … IF NOT EXISTS) ──────────────────
    column_migrations = [
        "ALTER TABLE compliance_items ADD COLUMN IF NOT EXISTS policy_holder VARCHAR(200)",
        "ALTER TABLE compliance_items ALTER COLUMN item_type TYPE VARCHAR(50)",
        # Tally ledger name mappings (Phase 1)
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS ledger_sales VARCHAR(100) NOT NULL DEFAULT 'Sales'",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS ledger_purchase VARCHAR(100) NOT NULL DEFAULT 'Purchase'",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS ledger_cgst VARCHAR(100) NOT NULL DEFAULT 'CGST'",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS ledger_sgst VARCHAR(100) NOT NULL DEFAULT 'SGST'",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS ledger_igst VARCHAR(100) NOT NULL DEFAULT 'IGST'",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS ledger_freight VARCHAR(100) NOT NULL DEFAULT 'Freight Outward'",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS ledger_discount VARCHAR(100) NOT NULL DEFAULT 'Trade Discount'",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS ledger_tcs VARCHAR(100) NOT NULL DEFAULT 'TCS Payable'",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS ledger_roundoff VARCHAR(100) NOT NULL DEFAULT 'Round Off'",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS narration_vehicle BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS narration_token BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS narration_weight BOOLEAN NOT NULL DEFAULT TRUE",
        # Tally Phase 2 — per-party ledger name
        "ALTER TABLE parties ADD COLUMN IF NOT EXISTS tally_ledger_name VARCHAR(200)",
        # Inventory — auto-reorder columns (added after initial release)
        "ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS reorder_quantity NUMERIC(14,3) NOT NULL DEFAULT 0",
        "ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS auto_po_enabled BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE inventory_purchase_orders ADD COLUMN IF NOT EXISTS is_auto_generated BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE inventory_transactions ADD COLUMN IF NOT EXISTS used_by_name VARCHAR(200)",
        "ALTER TABLE inventory_transactions ADD COLUMN IF NOT EXISTS used_on DATE",
        # Tally sync tracking for parties, quotations, and inventory purchase orders
        "ALTER TABLE parties ADD COLUMN IF NOT EXISTS tally_synced BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE parties ADD COLUMN IF NOT EXISTS tally_sync_at TIMESTAMPTZ",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS tally_synced BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS tally_sync_at TIMESTAMPTZ",
        "ALTER TABLE inventory_purchase_orders ADD COLUMN IF NOT EXISTS tally_synced BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE inventory_purchase_orders ADD COLUMN IF NOT EXISTS tally_sync_at TIMESTAMPTZ",
        # Notification engine — Telegram support + named recipients
        "ALTER TABLE notification_config ADD COLUMN IF NOT EXISTS tg_bot_token VARCHAR(500)",
        """
        CREATE TABLE IF NOT EXISTS notification_recipients (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            name VARCHAR(200) NOT NULL,
            channel VARCHAR(20) NOT NULL,
            contact VARCHAR(300) NOT NULL,
            event_types TEXT NOT NULL DEFAULT '["*"]',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ]

    # ── Inventory item suppliers table (added after initial release) ─────────
    supplier_ddl = """
        CREATE TABLE IF NOT EXISTS inventory_item_suppliers (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            item_id            UUID NOT NULL REFERENCES inventory_items(id) ON DELETE CASCADE,
            supplier_name      VARCHAR(200) NOT NULL,
            is_preferred       BOOLEAN NOT NULL DEFAULT FALSE,
            lead_time_days     INTEGER,
            agreed_unit_price  NUMERIC(14,2),
            moq                NUMERIC(14,3),
            notes              TEXT,
            is_active          BOOLEAN NOT NULL DEFAULT TRUE,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """
    try:
        async with async_session() as db:
            await db.execute(_text(supplier_ddl))
            await db.commit()
    except Exception as e:
        logger.warning("Could not create inventory_item_suppliers table: %s", e)

    try:
        async with async_session() as db:
            await db.execute(_text("""
                CREATE TABLE IF NOT EXISTS inventory_suppliers (
                    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    company_id    UUID REFERENCES companies(id),
                    name          VARCHAR(200) NOT NULL,
                    contact_person VARCHAR(200),
                    phone         VARCHAR(30),
                    email         VARCHAR(200),
                    notes         TEXT,
                    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """))
            await db.commit()
    except Exception as e:
        logger.warning("Could not create inventory_suppliers table: %s", e)

    try:
        async with async_session() as db:
            await db.execute(_text(
                "ALTER TABLE inventory_item_suppliers ADD COLUMN IF NOT EXISTS master_supplier_id UUID REFERENCES inventory_suppliers(id)"
            ))
            await db.commit()
    except Exception as e:
        logger.warning("Could not add master_supplier_id column: %s", e)

    try:
        async with async_session() as db:
            for migration in column_migrations:
                await db.execute(_text(migration))
            await db.commit()
    except Exception as e:
        logger.warning("Could not run column migrations: %s", e)

    # ── Weight scale ─────────────────────────────────────────────────────────
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

    # ── Seed notification templates + ensure default recipients ──────────────
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


app = FastAPI(
    title="Weighbridge Invoice Software",
    description="Stone Crusher Weighbridge Management System with GST & Tally Integration",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Middleware (order matters: outermost first) ──────────────────────────────

# Security headers on all responses
app.add_middleware(SecurityHeadersMiddleware)

# License enforcement (blocks API when license invalid)
app.add_middleware(LicenseGuardMiddleware)

# CORS — locked down to known origins
_cors_origins = [
    "http://localhost:9000",
    "http://127.0.0.1:9000",
]
try:
    _local_ip = socket.gethostbyname(socket.gethostname())
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
    allow_headers=["Authorization", "Content-Type"],
)

# ── API Routers ───────────────────────────────────────────────────────────────
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
