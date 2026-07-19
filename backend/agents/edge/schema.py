"""Edge SQLite schema.

`app/ddl.py` is Postgres-only (43 × gen_random_uuid(), 91 × TIMESTAMPTZ, JSONB,
partial indexes) so it cannot build the local database. Instead the edge schema
is emitted from the SAME SQLAlchemy models the server uses, which keeps the two
in lockstep automatically — a column added to a model reaches the edge on the
next agent build with no parallel DDL to maintain.

Proven on 2026-07-19: all 39 ORM models materialise on SQLite with a single type
override (JSONB → JSON). UUID primary keys round-trip as real `uuid.UUID`
because SQLAlchemy 2.0 resolves `Mapped[uuid.UUID]` per dialect, and JSONB
columns round-trip as dicts.

Two gaps have to be closed by hand, both because the server keeps some tables in
raw DDL with no ORM model:

  1. FK targets with no model — `branches` (referenced by invoices, tokens,
     users and number_sequences) and `royalty_passes` (tokens.transit_pass_id).
     Without these, create_all() fails outright: SQLAlchemy cannot emit a
     foreign key to a table that is absent from the metadata.
  2. Tables the offline flow needs — `gate_passes`, `gate_pass_daily_seq`,
     `app_settings`, `product_stock`. Gate passes in particular have no model at
     all (routers/gate.py uses raw SQL) yet are squarely in the offline scope.

Both groups are declared below, mirroring app/ddl.py, using portable types only.

NOTE: this module imports `app.models`, so the agent ships with the backend
package. That is deliberate — reusing the real models, the real gst_service and
the real Jinja2 templates is what removes any risk of the offline path
calculating or printing something different from the server.
"""
from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Integer, MetaData, Numeric,
    String, Table, Text, Uuid, event, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles


# ── Type overrides ───────────────────────────────────────────────────────────
# The only Postgres-specific column type the models use. Everything else
# (Uuid, Numeric, DateTime, Date, Boolean) is already dialect-portable.
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, D401
    return "JSON"


import app.models  # noqa: E402,F401  — registers every model on Base.metadata
from app.database import Base  # noqa: E402


def _tbl(name: str, *columns: Column) -> Table:
    """Declare a raw-DDL table once, tolerating repeat imports."""
    existing = Base.metadata.tables.get(name)
    if existing is not None:
        return existing
    return Table(name, Base.metadata, *columns)


# ── 1. FK targets that have no ORM model ─────────────────────────────────────
# Mirrors app/ddl.py. `branches` is a real edge dependency (per-branch numbering
# and the branch stamped on tokens/invoices), so it is defined in full rather
# than stubbed.
_tbl(
    "branches",
    Column("id", Uuid, primary_key=True, default=uuid.uuid4),
    Column("company_id", Uuid, ForeignKey("companies.id")),
    Column("name", String(150), nullable=False),
    Column("code", String(12), nullable=False),
    Column("gstin", String(15)),
    Column("address_line1", String(255)),
    Column("city", String(100)),
    Column("state", String(100)),
    Column("state_code", String(2)),
    Column("pincode", String(10)),
    Column("phone", String(20)),
    Column("is_default", Boolean, nullable=False, default=False),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# Royalty is NOT in the offline scope; this exists so tokens.transit_pass_id has
# a resolvable target and so a mirrored token that already carries a pass id
# still satisfies the constraint.
_tbl(
    "royalty_passes",
    Column("id", Uuid, primary_key=True, default=uuid.uuid4),
    Column("company_id", Uuid, ForeignKey("companies.id")),
    Column("fy_id", Uuid, ForeignKey("financial_years.id")),
    Column("pass_no", String(60), nullable=False),
    Column("pass_type", String(20), nullable=False, default="royalty"),
    Column("source_name", String(200)),
    Column("party_id", Uuid, ForeignKey("parties.id")),
    Column("mineral", String(120)),
    Column("product_id", Uuid, ForeignKey("products.id")),
    Column("issue_date", Date),
    Column("valid_till", Date),
    Column("quantity_mt", Numeric(14, 3), nullable=False, default=0),
    Column("rate", Numeric(12, 2), nullable=False, default=0),
    Column("amount", Numeric(14, 2), nullable=False, default=0),
    Column("vehicle_no", String(20)),
    Column("status", String(15), nullable=False, default="active"),
    Column("notes", Text),
    Column("created_by", Uuid, ForeignKey("users.id")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# ── 2. Raw-DDL tables the offline flow needs ─────────────────────────────────
_tbl(
    "gate_passes",
    Column("id", Uuid, primary_key=True, default=uuid.uuid4),
    Column("company_id", Uuid, ForeignKey("companies.id")),
    Column("gate_pass_no", String(40), nullable=False),
    Column("pass_date", Date, nullable=False),
    Column("seq_no", Integer, nullable=False, default=0),
    Column("vehicle_no", String(20), nullable=False),
    Column("vehicle_name", String(120)),
    Column("vehicle_type", String(50)),
    Column("vehicle_id", Uuid, ForeignKey("vehicles.id")),
    Column("driver_name", String(120)),
    Column("driver_phone", String(20)),
    Column("material", String(150)),
    Column("product_id", Uuid, ForeignKey("products.id")),
    Column("purpose", String(30), nullable=False, default="weighbridge"),
    Column("token_id", Uuid, ForeignKey("tokens.id")),
    Column("net_weight", Numeric(12, 3)),
    Column("entry_time", DateTime(timezone=True)),
    Column("exit_time", DateTime(timezone=True)),
    Column("entry_photo_path", Text),
    Column("exit_photo_path", Text),
    Column("status", String(15), nullable=False, default="inside"),
    Column("notes", Text),
    Column("created_by", Uuid, ForeignKey("users.id")),
    Column("created_by_name", String(120)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# Atomic daily counter. On Postgres this is INSERT … ON CONFLICT DO UPDATE; on
# SQLite the edge is single-writer so a plain read-modify-write inside the
# transaction is already serialised.
_tbl(
    "gate_pass_daily_seq",
    Column("company_id", Uuid, primary_key=True),
    Column("pass_date", Date, primary_key=True),
    Column("last_no", Integer, nullable=False, default=0),
)

_tbl(
    "app_settings",
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

_tbl(
    "product_stock",
    Column("id", Uuid, primary_key=True, default=uuid.uuid4),
    Column("company_id", Uuid, ForeignKey("companies.id")),
    Column("product_id", Uuid, ForeignKey("products.id"), nullable=False, unique=True),
    Column("current_stock", Numeric(14, 3), nullable=False, default=0),
    Column("min_stock_level", Numeric(14, 3), nullable=False, default=0),
    Column("last_alerted_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


# Tables the offline flow (gate pass + token + invoicing) cannot work without.
# bootstrap() asserts every one of these exists, so a future model refactor that
# silently drops one fails loudly at agent start instead of at 2am on a bridge.
EDGE_REQUIRED_TABLES: tuple[str, ...] = (
    "companies", "financial_years", "users", "branches",
    "parties", "party_rates",
    "products", "product_categories", "product_unit_rates", "product_stock",
    "vehicles", "drivers", "transporters",
    "tokens", "invoices", "invoice_items",
    "number_sequences", "custom_field_definitions", "agents",
    "gate_passes", "gate_pass_daily_seq", "app_settings",
)


def configure_sqlite(engine: Engine) -> None:
    """Apply the pragmas the edge relies on.

    WAL matters here beyond performance: it is what makes the database file
    crash-safe and copyable while the agent is running, which is the whole point
    of keeping a local durable store. foreign_keys is OFF by default in SQLite,
    so integrity would silently not be enforced without this.
    """

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA synchronous=FULL")   # never trade durability for speed here
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()


def bootstrap(engine: Engine) -> list[str]:
    """Create the full edge schema. Idempotent.

    Returns the sorted table list. Raises if a required table is missing.
    """
    configure_sqlite(engine)
    Base.metadata.create_all(engine)

    from sqlalchemy import inspect

    present = set(inspect(engine).get_table_names())
    missing = [t for t in EDGE_REQUIRED_TABLES if t not in present]
    if missing:
        raise RuntimeError(
            "edge schema incomplete — missing required table(s): " + ", ".join(missing)
        )
    return sorted(present)
