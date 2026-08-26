"""Per-tenant data reset — give a client a clean slate without touching anyone else.

Every tenant is its own database (``wb_<slug>``), which is what makes this safe:
a reset physically cannot reach another tenant's rows. Two modes:

* ``transactions`` — keep who they are and what they sell (company, users, parties,
  products, vehicles, rates, settings), wipe what they did (weighments, invoices,
  payments, stock, fuel, attendance, gate). This is what a client wants after a
  trial, before going live.
* ``full`` — drop the schema and rebuild it exactly as a brand-new tenant is
  provisioned. They re-enter everything, including their own login.

Classification is by an explicit KEEP list, and everything else is wiped. That
direction is deliberate: a table added by a future feature is transactional far
more often than not, and a leftover transaction quietly polluting reports is a
worse surprise than a wiped setting that can be re-entered. The truncate runs
WITHOUT cascade so that a keep-table pointing at a wipe-table fails loudly instead
of silently taking the keep-table with it.
"""
from __future__ import annotations

import logging
import os
import shutil

from sqlalchemy import text

log = logging.getLogger(__name__)

# ── What survives a "transactions" reset ─────────────────────────────────────
# Who the tenant is, what they sell, who works there, and how the system is
# configured. Everything not listed here is treated as activity and wiped.
KEEP_TABLES: set[str] = {
    # identity & structure
    "companies", "financial_years", "branches",
    # logins and access
    "users", "usb_keys", "customer_users",
    # trading partners
    "parties", "party_rates",
    # catalogue & pricing
    "products", "product_categories", "product_unit_rates",
    # fleet & people
    "vehicles", "drivers", "transporters", "workers", "agents",
    # store masters (stock LEVELS are reset separately, the items stay)
    "inventory_items", "inventory_suppliers", "inventory_item_suppliers",
    # chart of accounts (structure, not entries)
    "accounts", "account_groups",
    # statutory documents that remain valid after a reset
    "compliance_items", "royalty_passes",
    # configuration
    "app_settings", "custom_field_definitions",
    "notification_templates", "notification_recipients", "notification_config",
    "tally_config", "serial_port_config",
}

# Derived running totals that live on a KEPT row and must go back to zero, or the
# tenant starts "fresh" still owing money and holding stock.
RESET_COLUMNS: list[tuple[str, str, str]] = [
    ("parties", "current_balance", "0"),
    ("inventory_items", "current_stock", "0"),
]

# File columns to collect BEFORE wiping. Once the rows are gone there is no way to
# tell which uploads belonged to this tenant — several upload folders are shared
# across tenants and keyed only by row id — so orphans would be permanent.
SNAPSHOT_COLUMNS: list[tuple[str, str]] = [
    ("token_snapshots", "file_path"),
    ("anpr_events", "snapshot_path"),
    ("gate_passes", "entry_photo_path"),
    ("gate_passes", "exit_photo_path"),
    ("gate_camera_events", "snapshot_path"),
    ("gate_vehicle_events", "snapshot_path"),
]


def uploads_base() -> str:
    """Same resolution the routers use, so paths line up with what was written."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "uploads",
    )


async def list_tenant_tables(db) -> list[str]:
    return [r[0] for r in (await db.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
    ))).all()]


async def collect_upload_paths(db, slug: str) -> list[str]:
    """Absolute paths of this tenant's uploaded files, resolved while the rows
    still exist. Returns files and directories; missing ones are ignored later."""
    base = uploads_base()
    paths: list[str] = []

    tables = set(await list_tenant_tables(db))
    for table, col in SNAPSHOT_COLUMNS:
        if table not in tables:
            continue
        try:
            rows = (await db.execute(text(
                f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL AND {col} <> ''"
            ))).all()
        except Exception as e:            # a tenant may predate the column
            log.warning("reset: could not read %s.%s: %s", table, col, e)
            continue
        for (rel,) in rows:
            rel = str(rel).lstrip("/")
            if rel.startswith("uploads/"):
                rel = rel[len("uploads/"):]
            paths.append(os.path.join(base, rel.replace("/", os.sep)))

    # Camera snapshots sit in uploads/camera/<token_id>/ — a flat folder shared by
    # every tenant, so the only way to claim them is through this tenant's tokens.
    if "tokens" in tables:
        try:
            for (tid,) in (await db.execute(text("SELECT id::text FROM tokens"))).all():
                d = os.path.join(base, "camera", str(tid))
                if os.path.isdir(d):
                    paths.append(d)
        except Exception as e:
            log.warning("reset: could not list token snapshot dirs: %s", e)

    # Vehicle-counter frames ARE stored per tenant, so the whole folder goes.
    veh_dir = os.path.join(base, "gate", "vehicle", slug)
    if os.path.isdir(veh_dir):
        paths.append(veh_dir)

    return sorted(set(paths))


def purge_paths(paths: list[str]) -> dict:
    """Delete collected files/dirs. Best-effort: a file we cannot remove must not
    abort a reset that has already changed the database."""
    files = dirs = failed = 0
    freed = 0
    for p in paths:
        try:
            if os.path.isdir(p):
                for root, _, names in os.walk(p):
                    for n in names:
                        try:
                            freed += os.path.getsize(os.path.join(root, n))
                        except OSError:
                            pass
                shutil.rmtree(p, ignore_errors=True)
                dirs += 1
            elif os.path.isfile(p):
                try:
                    freed += os.path.getsize(p)
                except OSError:
                    pass
                os.remove(p)
                files += 1
        except Exception as e:  # noqa: BLE001
            failed += 1
            log.warning("reset: could not remove %s: %s", p, e)
    return {"files_deleted": files, "dirs_deleted": dirs,
            "failed": failed, "bytes_freed": freed}


async def reset_transactions(db, slug: str) -> dict:
    """Wipe activity, keep masters and configuration."""
    tables = await list_tenant_tables(db)
    wipe = [t for t in tables if t not in KEEP_TABLES]
    kept = [t for t in tables if t in KEEP_TABLES]
    if not wipe:
        return {"truncated": [], "kept": kept}

    # One statement so mutual foreign keys between wiped tables are satisfied, and
    # deliberately no CASCADE: if a KEPT table references a wiped one, this raises
    # instead of quietly emptying the kept table too.
    stmt = "TRUNCATE TABLE " + ", ".join(f'"{t}"' for t in wipe) + " RESTART IDENTITY"
    await db.execute(text(stmt))

    for table, col, value in RESET_COLUMNS:
        if table in tables:
            await db.execute(text(f'UPDATE "{table}" SET {col} = {value}'))
    await db.commit()
    return {"truncated": sorted(wipe), "kept": sorted(kept)}


async def reset_full(slug: str, tenant_name: str, admin_username: str,
                     admin_password: str) -> dict:
    """Rebuild the tenant database as if it had just been provisioned.

    Drops the schema rather than the database: the tenant's connection pool stays
    valid, so there is no engine to evict and no other session to terminate.
    """
    from app.multitenancy.registry import tenant_registry
    from app.multitenancy.router import _run_tenant_ddl, _seed_tenant_data
    from app.schemas.tenant import TenantCreate

    factory = await tenant_registry.get_session_factory(slug)
    async with factory() as db:
        user = (await db.execute(text("SELECT current_user"))).scalar()
        await db.execute(text("DROP SCHEMA public CASCADE"))
        await db.execute(text("CREATE SCHEMA public"))
        await db.execute(text(f'GRANT ALL ON SCHEMA public TO "{user}"'))
        await db.commit()

    await _run_tenant_ddl(slug)
    await _seed_tenant_data(slug, TenantCreate(
        slug=slug, display_name=tenant_name, company_name=tenant_name,
        admin_username=admin_username, admin_password=admin_password,
    ))
    return {"rebuilt": True, "admin_username": admin_username}
