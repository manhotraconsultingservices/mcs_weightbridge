"""Fleet Fuel & Mileage — diesel-leakage detection.

Records diesel fills (a plant-tank fill atomically issues litres from the store
diesel inventory item) and computes per-vehicle mileage vs a benchmark (manual,
or auto-learned from the vehicle's own history) to surface leakage as excess
litres / ₹. All-new tables + endpoints — nothing existing changes.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.vehicle import Vehicle, VehicleFuelEntry, Driver
from app.models.company import FinancialYear
from app.models.fuel_po import FuelPurchaseOrder, FuelPoPayment
from app.schemas.vehicle import (
    FuelEntryCreate, FuelEntryUpdate, FuelEntryResponse, FuelPoPaymentCreate,
)
from app.services import fuel as fuel_svc
from app.services.numbering import next_doc_no

log = logging.getLogger(__name__)


def _ctx_tenant_slug():
    try:
        from app.multitenancy.context import current_tenant_slug
        return current_tenant_slug.get()
    except Exception:
        return None


async def _notify_bg(company_id, event_type: str, context: dict,
                     entity_type=None, entity_id=None, tenant_slug=None) -> None:
    """Background wrapper: own tenant-routed session → send_notification."""
    try:
        from app.database import get_tenant_session
        from app.integrations.notifications.service import send_notification
        async with await get_tenant_session(tenant_slug) as _db:
            await send_notification(_db, company_id, event_type, context, entity_type, entity_id)
    except Exception as exc:
        log.warning("fuel notification failed [%s]: %s", event_type, exc)
router = APIRouter(prefix="/api/v1/fuel", tags=["Fleet Fuel & Mileage"])

DEFAULT_FUEL_CONFIG: dict[str, Any] = {
    "diesel_item_id": None,          # store inventory item to deduct plant_tank fills from
    "deviation_threshold_pct": 15,   # flag when actual mileage is >= N% below benchmark
    "min_distance_km": 50,           # ignore intervals shorter than this in mileage calc
    "auto_learn_days": 90,           # window for the rolling-median baseline
    "alert_enabled": True,           # fire a leakage notification on a leaking fill
    "pump_alert_threshold": 0,       # ₹ — Telegram alert when a pump's outstanding crosses this (0 = off)
}


# ── Config ────────────────────────────────────────────────────────────────────

async def _get_fuel_config(db: AsyncSession) -> dict[str, Any]:
    try:
        row = (await db.execute(
            text("SELECT value FROM app_settings WHERE key = 'fuel_config'")
        )).fetchone()
        if row:
            cfg = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            return {**DEFAULT_FUEL_CONFIG, **(cfg or {})}
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
    return dict(DEFAULT_FUEL_CONFIG)


@router.get("/config")
async def get_config(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await _get_fuel_config(db)


@router.put("/config")
async def put_config(payload: dict, db: AsyncSession = Depends(get_db),
                     user: User = Depends(get_current_user)):
    await db.execute(
        text("""
            INSERT INTO app_settings (key, value, updated_at)
            VALUES ('fuel_config', :v, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """),
        {"v": json.dumps(payload)},
    )
    await db.commit()
    return {"ok": True}


async def _resolve_diesel_item_id(db: AsyncSession, cfg: dict[str, Any], company_id) -> Any:
    """The store item to deduct plant-tank diesel from — self-configuring for new tenants.

    Prefer the explicitly-configured `diesel_item_id`. If none is set (a fresh tenant
    that never opened Fuel → Settings), auto-resolve an UNAMBIGUOUS diesel item —
    exactly one active inventory item whose name mentions 'diesel' — and persist it
    into `fuel_config`, so plant-tank fills deduct from day one and the Settings tab
    then shows the choice. Ambiguous (0 or >1 name matches) → return None: never
    auto-guess which item to draw down; the fill still records, just without a
    deduction (and the Settings warning nudges the admin to pick one).
    """
    if cfg.get("diesel_item_id"):
        return cfg["diesel_item_id"]
    from app.models.inventory import InventoryItem
    ids = (await db.execute(
        select(InventoryItem.id).where(
            InventoryItem.company_id == company_id,
            InventoryItem.is_active == True,  # noqa: E712
            func.lower(InventoryItem.name).like("%diesel%"),
        )
    )).scalars().all()
    if len(ids) != 1:
        return None
    item_id = str(ids[0])
    try:  # best-effort persist — a config-write failure must never block the fill
        await db.execute(
            text("""
                INSERT INTO app_settings (key, value, updated_at)
                VALUES ('fuel_config', :v, NOW())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """),
            {"v": json.dumps({**cfg, "diesel_item_id": item_id})},
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("could not persist auto-resolved diesel_item_id: %s", exc)
    return item_id


# ── Inventory deduction (plant-tank fills) ────────────────────────────────────

async def _issue_diesel(db: AsyncSession, user: User, item_id, litres: Decimal,
                        reg_no: str, on_date: date) -> tuple[Any, Any]:
    """Atomically issue `litres` of diesel from the configured store item."""
    from app.models.inventory import InventoryItem, InventoryTransaction
    res = await db.execute(
        select(InventoryItem)
        .where(InventoryItem.id == item_id,
               InventoryItem.company_id == user.company_id,
               InventoryItem.is_active == True)
        .with_for_update()
    )
    item = res.scalar_one_or_none()
    if not item:
        raise HTTPException(400, "Configured diesel inventory item not found — set it in Fuel → Settings.")
    if item.current_stock < litres:
        raise HTTPException(
            400,
            f"Not enough diesel in the plant tank: {item.current_stock} {item.unit} available, "
            f"{litres} requested.",
        )
    stock_before = item.current_stock
    item.current_stock = item.current_stock - litres
    txn = InventoryTransaction(
        company_id=user.company_id, item_id=item.id, transaction_type="issue",
        quantity=-litres, stock_before=stock_before, stock_after=item.current_stock,
        notes=f"Diesel issued to {reg_no}", created_by=user.id,
        created_by_name=getattr(user, "full_name", None) or user.username,
        used_by_name=reg_no, used_on=on_date,
    )
    db.add(txn)
    await db.flush()
    return item.id, txn.id


async def _reverse_diesel(db: AsyncSession, user: User, entry: VehicleFuelEntry) -> None:
    """Return diesel to the plant tank when a plant-tank fill is deleted."""
    if not (entry.inventory_item_id and entry.fuel_source == "plant_tank"):
        return
    from app.models.inventory import InventoryItem, InventoryTransaction
    res = await db.execute(
        select(InventoryItem).where(InventoryItem.id == entry.inventory_item_id).with_for_update()
    )
    item = res.scalar_one_or_none()
    if not item:
        return
    stock_before = item.current_stock
    item.current_stock = item.current_stock + entry.litres
    db.add(InventoryTransaction(
        company_id=user.company_id, item_id=item.id, transaction_type="adjustment",
        quantity=entry.litres, stock_before=stock_before, stock_after=item.current_stock,
        notes="Reversal of deleted fuel entry", created_by=user.id,
        created_by_name=getattr(user, "full_name", None) or user.username,
    ))


# ── Petrol-pump credit PO ─────────────────────────────────────────────────────

async def _active_fy_id(db: AsyncSession):
    fy = (await db.execute(
        select(FinancialYear).where(FinancialYear.is_active == True).limit(1)  # noqa: E712
    )).scalar_one_or_none()
    return fy.id if fy else None


async def _pump_supplier_map(db: AsyncSession) -> dict[str, str]:
    """station_name → supplier party_id, from app_settings `fuel_pump_suppliers`.
    Lets a petrol pump be linked to a supplier party for a unified vendor view."""
    try:
        row = (await db.execute(
            text("SELECT value FROM app_settings WHERE key='fuel_pump_suppliers'")
        )).fetchone()
        if row and row[0]:
            m = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            return {k: str(v) for k, v in (m or {}).items() if v}
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
    return {}


async def _party_names(db: AsyncSession, party_ids) -> dict[str, str]:
    ids = [str(p) for p in party_ids if p]
    if not ids:
        return {}
    try:
        rows = (await db.execute(text(
            "SELECT id, name FROM parties WHERE id = ANY(:ids)"), {"ids": ids})).all()
        return {str(r[0]): r[1] for r in rows}
    except Exception:
        return {}


async def _create_pump_po(db: AsyncSession, user: User, entry: VehicleFuelEntry,
                          station_name: str) -> FuelPurchaseOrder | None:
    """Auto-create a credit PO against the petrol pump for an outside-pump fill.
    Pure accounts-payable — NO inventory movement, NO P&L re-booking (the fuel
    expense is already recognised via the fuel entry). Best-effort: a PO failure
    must never lose the physical fuel record. Runs inside the caller's txn."""
    station = (station_name or "").strip()
    if not station:
        return None
    try:
        fy_id = await _active_fy_id(db)
        po_no = (await next_doc_no(db, user.company_id, fy_id, "fuel_po", "FPO")
                 if fy_id else f"FPO-{str(entry.id)[:8]}")
        supplier_party_id = (await _pump_supplier_map(db)).get(station)   # linked supplier, if any
        po = FuelPurchaseOrder(
            company_id=user.company_id, po_no=po_no, station_name=station,
            supplier_party_id=(uuid.UUID(supplier_party_id) if supplier_party_id else None),
            fuel_entry_id=entry.id, vehicle_id=entry.vehicle_id, po_date=entry.entry_date,
            litres=entry.litres, rate_per_litre=entry.rate_per_litre,
            amount=entry.amount or Decimal("0"), amount_paid=Decimal("0"), status="unpaid",
            created_by=user.id,
        )
        db.add(po)
        await db.flush()
        return po
    except Exception as e:  # noqa: BLE001 — never block the fill
        log.warning("pump PO auto-create failed: %s", e)
        return None


async def _po_no_for_entry(db: AsyncSession, entry_id) -> str | None:
    return (await db.execute(
        select(FuelPurchaseOrder.po_no).where(FuelPurchaseOrder.fuel_entry_id == entry_id).limit(1)
    )).scalar_one_or_none()


# ── Response helper ───────────────────────────────────────────────────────────

async def _entry_to_response(db: AsyncSession, entry: VehicleFuelEntry, veh: Vehicle,
                             driver_name: str | None = None) -> FuelEntryResponse:
    prev = (await db.execute(
        select(VehicleFuelEntry).where(
            VehicleFuelEntry.vehicle_id == entry.vehicle_id,
            VehicleFuelEntry.company_id == entry.company_id,
            VehicleFuelEntry.odometer_km < entry.odometer_km,
        ).order_by(VehicleFuelEntry.odometer_km.desc()).limit(1)
    )).scalar_one_or_none()
    distance = None
    kmpl = None
    flags: list[str] = []
    tank = float(veh.tank_capacity_litres) if veh.tank_capacity_litres else None
    if tank and float(entry.litres) > tank * 1.05:
        flags.append("litres_over_tank")
    if prev is not None:
        d = float(entry.odometer_km) - float(prev.odometer_km)
        if d < 0:
            flags.append("odometer_rollback")
        elif float(entry.litres) > 0:
            distance = round(d, 1)
            kmpl = round(d / float(entry.litres), 2)
    return FuelEntryResponse(
        id=entry.id, vehicle_id=entry.vehicle_id, registration_no=veh.registration_no,
        entry_date=entry.entry_date, odometer_km=entry.odometer_km, litres=entry.litres,
        rate_per_litre=entry.rate_per_litre, amount=entry.amount, fuel_source=entry.fuel_source,
        station_name=entry.station_name, po_no=await _po_no_for_entry(db, entry.id),
        tank_full=entry.tank_full, driver_id=entry.driver_id, driver_name=driver_name,
        notes=entry.notes, created_at=entry.created_at,
        distance_km=distance, interval_kmpl=kmpl, flags=flags,
    )


# ── Fuel-entry CRUD ───────────────────────────────────────────────────────────

@router.post("/entries", response_model=FuelEntryResponse, status_code=201)
async def create_entry(payload: FuelEntryCreate, background: BackgroundTasks,
                       db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    veh = (await db.execute(select(Vehicle).where(
        Vehicle.id == payload.vehicle_id, Vehicle.company_id == user.company_id
    ))).scalar_one_or_none()
    if not veh:
        raise HTTPException(404, "Vehicle not found")

    litres = Decimal(str(payload.litres))
    if litres < 0:
        raise HTTPException(400, "Litres cannot be negative")
    # litres == 0 is allowed: an odometer-only reading (update the meter without a fill).
    if veh.tank_capacity_litres and litres > veh.tank_capacity_litres * Decimal("1.05"):
        raise HTTPException(
            400,
            f"Litres ({litres}) exceed the tank capacity ({veh.tank_capacity_litres} L). "
            "Check the reading before saving.",
        )

    odo = Decimal(str(payload.odometer_km))
    last = (await db.execute(select(VehicleFuelEntry).where(
        VehicleFuelEntry.vehicle_id == veh.id, VehicleFuelEntry.company_id == user.company_id
    ).order_by(VehicleFuelEntry.odometer_km.desc()).limit(1))).scalar_one_or_none()
    if last is not None and odo < last.odometer_km:
        raise HTTPException(
            400,
            f"Odometer {odo} km is below the last recorded reading ({last.odometer_km} km). "
            "A meter can't run backwards — correct the reading.",
        )

    cfg = await _get_fuel_config(db)
    rate = Decimal(str(payload.rate_per_litre)) if payload.rate_per_litre is not None else None
    amount = (Decimal(str(payload.amount)) if payload.amount is not None
              else (litres * rate if rate is not None else None))

    inv_item_id = None
    inv_txn_id = None
    diesel_item_id = await _resolve_diesel_item_id(db, cfg, user.company_id)
    # litres > 0 guard: a 0-litre entry is an odometer-only reading (no fill), so it
    # must NOT issue diesel from the store (no phantom 0-qty stock movement).
    if litres > 0 and (payload.fuel_source or "plant_tank") == "plant_tank" and diesel_item_id:
        inv_item_id, inv_txn_id = await _issue_diesel(
            db, user, diesel_item_id, litres, veh.registration_no, payload.entry_date)

    entry = VehicleFuelEntry(
        company_id=user.company_id,
        branch_id=getattr(user, "branch_id", None),
        vehicle_id=veh.id,
        entry_date=payload.entry_date,
        odometer_km=odo,
        litres=litres,
        rate_per_litre=rate,
        amount=amount,
        fuel_source=payload.fuel_source or "plant_tank",
        station_name=(payload.station_name or "").strip() or None,
        tank_full=bool(payload.tank_full),
        inventory_item_id=inv_item_id,
        inventory_txn_id=inv_txn_id,
        driver_id=payload.driver_id,
        notes=payload.notes,
        created_by=user.id,
    )
    db.add(entry)
    # Keep the vehicle master's current odometer in sync — bump to the highest reading
    # seen (a 0-litre entry is exactly the "update odometer without a fill" path).
    if veh.current_odometer_km is None or odo > veh.current_odometer_km:
        veh.current_odometer_km = odo
    await db.flush()
    from app.routers.audit import log_action
    await log_action(db, user.company_id, user.id, "create", "fuel_entry", entity_id=str(entry.id),
                     details={"vehicle": veh.registration_no, "litres": str(litres),
                              "rate": str(rate), "amount": str(amount),
                              "source": entry.fuel_source, "odometer_km": str(odo)})
    # Petrol-pump fill on credit → auto-create a credit PO against the pump (no
    # inventory, no P&L re-booking). Only for outside_pump/other fills with a
    # station name and on_credit set; plant-tank fills never create a PO.
    _pump_alert_ctx = None
    if (entry.fuel_source in ("outside_pump", "other") and getattr(payload, "on_credit", True)
            and (payload.station_name or "").strip() and (amount or 0) > 0):
        _po = await _create_pump_po(db, user, entry, payload.station_name)
        # Threshold-crossing alert: fire once, only when this fill pushes the pump's
        # outstanding from below the threshold to at/above it (not on every fill after).
        try:
            thr = float(cfg.get("pump_alert_threshold", 0) or 0)
            if _po is not None and thr > 0:
                after = float((await db.execute(text(
                    "SELECT COALESCE(SUM(amount - amount_paid), 0) FROM fuel_purchase_orders "
                    "WHERE company_id=:c AND station_name=:s"),
                    {"c": str(user.company_id), "s": _po.station_name})).scalar() or 0)
                before = after - float(_po.amount or 0)
                if before < thr <= after:
                    _pump_alert_ctx = {
                        "station": _po.station_name,
                        "outstanding": f"{after:,.2f}",
                        "threshold": f"{thr:,.2f}",
                        "vehicle_no": veh.registration_no,
                        "po_no": _po.po_no,
                    }
        except Exception as _e:  # noqa: BLE001
            log.warning("pump threshold alert check failed: %s", _e)
    await db.commit()
    if _pump_alert_ctx is not None:
        from app.models.company import Company as _Co
        _co = (await db.execute(select(_Co).limit(1))).scalar_one_or_none()
        _pump_alert_ctx["company_name"] = _co.name if _co else ""
        background.add_task(_notify_bg, user.company_id, "fuel_pump_outstanding_alert",
                            _pump_alert_ctx, "fuel_po", None, _ctx_tenant_slug())
    await db.refresh(entry)

    resp = await _entry_to_response(db, entry, veh)

    # Fire a "diesel transaction" notification on every fill (non-blocking)
    try:
        from app.models.company import Company as _Company
        _co = (await db.execute(select(_Company).limit(1))).scalar_one_or_none()
        background.add_task(
            _notify_bg, user.company_id, "diesel_transaction",
            {
                "vehicle_no": veh.registration_no,
                "litres": f"{float(litres):g}",
                "rate": f"{float(rate):.2f}" if rate is not None else "",
                "amount": f"{float(amount):.2f}" if amount is not None else "",
                "odometer_km": f"{float(odo):g}",
                "fuel_source": (payload.fuel_source or "plant_tank").replace("_", " "),
                "company_name": _co.name if _co else "",
            },
            "fuel_entry", str(entry.id), _ctx_tenant_slug(),
        )
    except Exception as _e:
        log.warning("diesel_transaction notify wiring failed: %s", _e)

    # Fire a leakage alert (non-blocking) when this fill's interval mileage is
    # well below the effective benchmark.
    try:
        if cfg.get("alert_enabled", True) and resp.interval_kmpl and veh.benchmark_mileage_kmpl:
            bench = float(veh.benchmark_mileage_kmpl)
            if bench > 0:
                dev = (bench - resp.interval_kmpl) / bench * 100
                if dev >= float(cfg.get("deviation_threshold_pct", 15)):
                    slug = _current_tenant_slug()
                    ctx = {
                        "vehicle_no": veh.registration_no,
                        "actual_kmpl": f"{resp.interval_kmpl:.2f}",
                        "benchmark_kmpl": f"{bench:.2f}",
                        "deviation_pct": f"{dev:.1f}",
                        "distance_km": f"{resp.distance_km or 0:.1f}",
                        "litres": f"{float(litres):.2f}",
                    }
                    background.add_task(_alert_leakage_bg, str(user.company_id), slug, ctx)
    except Exception:
        pass
    return resp


@router.get("/entries")
async def list_entries(
    vehicle_id: Optional[uuid.UUID] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    q = select(VehicleFuelEntry).where(VehicleFuelEntry.company_id == user.company_id)
    if vehicle_id:
        q = q.where(VehicleFuelEntry.vehicle_id == vehicle_id)
    if date_from:
        q = q.where(VehicleFuelEntry.entry_date >= date_from)
    if date_to:
        q = q.where(VehicleFuelEntry.entry_date <= date_to)
    rows = (await db.execute(q.order_by(VehicleFuelEntry.entry_date.desc(),
                                        VehicleFuelEntry.odometer_km.desc()))).scalars().all()
    total = len(rows)
    page_rows = rows[(page - 1) * page_size: page * page_size]

    # name maps
    veh_map = {v.id: v for v in (await db.execute(select(Vehicle).where(
        Vehicle.company_id == user.company_id))).scalars().all()}
    drv_map = {d.id: d.name for d in (await db.execute(select(Driver).where(
        Driver.company_id == user.company_id))).scalars().all()}

    # per-vehicle interval computation (for distance + interval km/l columns)
    by_veh: dict[Any, list[dict]] = {}
    for r in rows:
        by_veh.setdefault(r.vehicle_id, []).append({
            "id": str(r.id), "odometer_km": float(r.odometer_km), "litres": float(r.litres),
            "entry_date": r.entry_date, "rate_per_litre": float(r.rate_per_litre) if r.rate_per_litre else None,
        })
    interval_by_id: dict[str, dict] = {}
    for vid, ents in by_veh.items():
        veh = veh_map.get(vid)
        tank = float(veh.tank_capacity_litres) if (veh and veh.tank_capacity_litres) else None
        for iv in fuel_svc.compute_intervals(ents, tank):
            interval_by_id[iv["id"]] = iv

    items = []
    for r in page_rows:
        veh = veh_map.get(r.vehicle_id)
        iv = interval_by_id.get(str(r.id), {})
        items.append({
            "id": str(r.id), "vehicle_id": str(r.vehicle_id),
            "registration_no": veh.registration_no if veh else None,
            "entry_date": str(r.entry_date), "odometer_km": float(r.odometer_km),
            "litres": float(r.litres),
            "rate_per_litre": float(r.rate_per_litre) if r.rate_per_litre else None,
            "amount": float(r.amount) if r.amount else None,
            "fuel_source": r.fuel_source, "tank_full": r.tank_full,
            "driver_name": drv_map.get(r.driver_id),
            "notes": r.notes,
            "distance_km": iv.get("distance_km"),
            "interval_kmpl": iv.get("interval_kmpl"),
            "flags": iv.get("flags", []),
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.put("/entries/{entry_id}", response_model=FuelEntryResponse)
async def update_entry(entry_id: uuid.UUID, payload: FuelEntryUpdate,
                       db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    entry = (await db.execute(select(VehicleFuelEntry).where(
        VehicleFuelEntry.id == entry_id, VehicleFuelEntry.company_id == user.company_id
    ))).scalar_one_or_none()
    if not entry:
        raise HTTPException(404, "Fuel entry not found")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(entry, k, v)
    # keep amount consistent if rate/litres changed and amount not explicitly set
    if "amount" not in data and entry.rate_per_litre is not None and entry.litres is not None:
        entry.amount = Decimal(str(entry.litres)) * Decimal(str(entry.rate_per_litre))
    # Keep a linked, still-UNPAID pump PO in step with the corrected fill.
    po = (await db.execute(select(FuelPurchaseOrder).where(
        FuelPurchaseOrder.fuel_entry_id == entry.id, FuelPurchaseOrder.company_id == user.company_id
    ))).scalar_one_or_none()
    if po is not None and float(po.amount_paid or 0) == 0:
        po.amount = entry.amount or Decimal("0")
        po.litres = entry.litres
        po.rate_per_litre = entry.rate_per_litre
        po.po_date = entry.entry_date
        if entry.station_name:
            po.station_name = entry.station_name
    await db.commit()
    await db.refresh(entry)
    veh = (await db.execute(select(Vehicle).where(Vehicle.id == entry.vehicle_id))).scalar_one_or_none()
    return await _entry_to_response(db, entry, veh)


@router.delete("/entries/{entry_id}")
async def delete_entry(entry_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                       user: User = Depends(get_current_user)):
    entry = (await db.execute(select(VehicleFuelEntry).where(
        VehicleFuelEntry.id == entry_id, VehicleFuelEntry.company_id == user.company_id
    ))).scalar_one_or_none()
    if not entry:
        raise HTTPException(404, "Fuel entry not found")
    await _reverse_diesel(db, user, entry)
    # Remove a linked pump PO only if nothing has been paid against it; a PO with
    # payments is left in place (unlinked from the deleted fill) for the audit trail.
    po = (await db.execute(select(FuelPurchaseOrder).where(
        FuelPurchaseOrder.fuel_entry_id == entry.id, FuelPurchaseOrder.company_id == user.company_id
    ))).scalar_one_or_none()
    if po is not None:
        if float(po.amount_paid or 0) == 0:
            await db.delete(po)
        else:
            po.fuel_entry_id = None
            po.notes = ((po.notes or "") + " [source fuel entry deleted]").strip()
    await db.delete(entry)
    await db.commit()
    return {"ok": True}


# ── Petrol-pump credit — POs · payments · outstanding report ──────────────────

def _pf(v) -> float:
    return float(v or 0)


@router.get("/pump-pos")
async def list_pump_pos(
    station: Optional[str] = Query(None),
    status: Optional[str] = Query(None),      # unpaid | partial | paid
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    """List the auto-created petrol-pump credit POs (one per outside-pump fill)."""
    q = select(FuelPurchaseOrder).where(FuelPurchaseOrder.company_id == user.company_id)
    if station:
        q = q.where(FuelPurchaseOrder.station_name.ilike(f"%{station}%"))
    if status:
        q = q.where(FuelPurchaseOrder.status == status)
    if date_from:
        q = q.where(FuelPurchaseOrder.po_date >= date_from)
    if date_to:
        q = q.where(FuelPurchaseOrder.po_date <= date_to)
    rows = (await db.execute(
        q.order_by(FuelPurchaseOrder.po_date.desc(), FuelPurchaseOrder.created_at.desc())
    )).scalars().all()
    vids = {r.vehicle_id for r in rows if r.vehicle_id}
    regos: dict = {}
    if vids:
        for vid, rego in (await db.execute(
            select(Vehicle.id, Vehicle.registration_no).where(Vehicle.id.in_(vids))
        )).all():
            regos[vid] = rego
    return {"items": [{
        "id": str(r.id), "po_no": r.po_no, "station_name": r.station_name,
        "po_date": r.po_date.isoformat() if r.po_date else None,
        "vehicle_no": regos.get(r.vehicle_id), "litres": _pf(r.litres),
        "rate_per_litre": _pf(r.rate_per_litre), "amount": _pf(r.amount),
        "amount_paid": _pf(r.amount_paid), "outstanding": _pf(r.amount) - _pf(r.amount_paid),
        "status": r.status, "notes": r.notes,
    } for r in rows]}


@router.get("/pump-outstanding")
async def pump_outstanding(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    """Per-pump accounts-payable — how much is owed to each petrol pump on credit
    (total billed − paid). This is the "outstanding to petrol pump" report."""
    q = select(FuelPurchaseOrder).where(FuelPurchaseOrder.company_id == user.company_id)
    if date_from:
        q = q.where(FuelPurchaseOrder.po_date >= date_from)
    if date_to:
        q = q.where(FuelPurchaseOrder.po_date <= date_to)
    rows = (await db.execute(q)).scalars().all()
    stations: dict = {}
    for r in rows:
        s = stations.setdefault(r.station_name, {
            "station_name": r.station_name, "po_count": 0, "unpaid_count": 0,
            "total_billed": 0.0, "total_paid": 0.0, "outstanding": 0.0,
            "oldest_unpaid_date": None,
        })
        s["po_count"] += 1
        s["total_billed"] += _pf(r.amount)
        s["total_paid"] += _pf(r.amount_paid)
        out = _pf(r.amount) - _pf(r.amount_paid)
        s["outstanding"] += out
        if out > 0.01:
            s["unpaid_count"] += 1
            d = r.po_date.isoformat() if r.po_date else None
            if d and (s["oldest_unpaid_date"] is None or d < s["oldest_unpaid_date"]):
                s["oldest_unpaid_date"] = d
    station_list = sorted(stations.values(), key=lambda x: x["outstanding"], reverse=True)
    for s in station_list:
        for k in ("total_billed", "total_paid", "outstanding"):
            s[k] = round(s[k], 2)
    # Attach the linked supplier party (unified vendor view), if any.
    smap = await _pump_supplier_map(db)
    pnames = await _party_names(db, [smap[s["station_name"]] for s in station_list if s["station_name"] in smap])
    for s in station_list:
        pid = smap.get(s["station_name"])
        s["supplier_party_id"] = pid
        s["supplier_name"] = pnames.get(pid) if pid else None
    totals = {
        "total_billed": round(sum(s["total_billed"] for s in station_list), 2),
        "total_paid": round(sum(s["total_paid"] for s in station_list), 2),
        "outstanding": round(sum(s["outstanding"] for s in station_list), 2),
        "pumps_with_dues": sum(1 for s in station_list if s["outstanding"] > 0.01),
        "po_count": sum(s["po_count"] for s in station_list),
    }
    return {"stations": station_list, "totals": totals}


@router.get("/pump-payments")
async def list_pump_payments(
    station: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    q = select(FuelPoPayment).where(FuelPoPayment.company_id == user.company_id)
    if station:
        q = q.where(FuelPoPayment.station_name.ilike(f"%{station}%"))
    rows = (await db.execute(
        q.order_by(FuelPoPayment.payment_date.desc(), FuelPoPayment.created_at.desc())
    )).scalars().all()
    return {"items": [{
        "id": str(r.id), "station_name": r.station_name, "amount": _pf(r.amount),
        "payment_date": r.payment_date.isoformat() if r.payment_date else None,
        "mode": r.mode, "reference": r.reference, "notes": r.notes,
    } for r in rows]}


@router.post("/pump-payments", status_code=201)
async def record_pump_payment(
    payload: FuelPoPaymentCreate,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    """Record a payment to a petrol pump and allocate it FIFO across that pump's
    open POs (oldest first), updating each PO's amount_paid + status. Any surplus
    beyond the pump's dues is recorded but left unallocated."""
    station = (payload.station_name or "").strip()
    if not station:
        raise HTTPException(400, "Station name is required")
    amt = Decimal(str(payload.amount))
    if amt <= 0:
        raise HTTPException(400, "Amount must be positive")
    pay = FuelPoPayment(
        company_id=user.company_id, station_name=station, amount=amt,
        payment_date=payload.payment_date, mode=payload.mode or "cash",
        reference=payload.reference, notes=payload.notes, created_by=user.id,
    )
    db.add(pay)
    remaining = amt
    pos = (await db.execute(select(FuelPurchaseOrder).where(
        FuelPurchaseOrder.company_id == user.company_id,
        FuelPurchaseOrder.station_name == station,
        FuelPurchaseOrder.status != "paid",
    ).order_by(FuelPurchaseOrder.po_date.asc(), FuelPurchaseOrder.created_at.asc())
        .with_for_update())).scalars().all()
    for po in pos:
        if remaining <= 0:
            break
        due = (po.amount or Decimal("0")) - (po.amount_paid or Decimal("0"))
        if due <= 0:
            continue
        applied = min(due, remaining)
        po.amount_paid = (po.amount_paid or Decimal("0")) + applied
        remaining -= applied
        po.status = "paid" if (po.amount - po.amount_paid) <= Decimal("0.01") else "partial"
    await db.flush()
    from app.routers.audit import log_action
    await log_action(db, user.company_id, user.id, "create", "fuel_po_payment", entity_id=str(pay.id),
                     details={"station": station, "amount": str(amt), "mode": payload.mode,
                              "unallocated": str(remaining)})
    await db.commit()
    return {"ok": True, "id": str(pay.id), "allocated": float(amt - remaining),
            "unallocated": float(remaining)}


@router.get("/pump-suppliers")
async def list_pump_suppliers(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Station → linked supplier party map (for the unified vendor view)."""
    smap = await _pump_supplier_map(db)
    names = await _party_names(db, list(smap.values()))
    return {"items": [{"station_name": st, "party_id": pid, "party_name": names.get(pid)}
                      for st, pid in smap.items()]}


@router.post("/pump-suppliers")
async def link_pump_supplier(
    payload: dict, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    """Link (or unlink) a petrol pump to a supplier party. Updates the station→party
    map AND stamps `supplier_party_id` on all of that pump's POs, so the pump shows as
    a supplier in the unified vendor view. `party_id: null` unlinks."""
    station = str(payload.get("station_name") or "").strip()
    if not station:
        raise HTTPException(400, "station_name is required")
    party_id = payload.get("party_id")
    smap = await _pump_supplier_map(db)
    if party_id:
        smap[station] = str(party_id)
    else:
        smap.pop(station, None)
    await db.execute(text(
        "INSERT INTO app_settings (key, value, updated_at) VALUES ('fuel_pump_suppliers', :v, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"),
        {"v": json.dumps(smap)})
    await db.execute(text(
        "UPDATE fuel_purchase_orders SET supplier_party_id = :pid "
        "WHERE company_id = :c AND station_name = :s"),
        {"pid": str(party_id) if party_id else None, "c": str(user.company_id), "s": station})
    await db.commit()
    return {"ok": True, "station_name": station, "party_id": str(party_id) if party_id else None}


@router.get("/party/{party_id}/credit")
async def party_fuel_credit(
    party_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    """Fuel-pump credit summary for one supplier party (unified vendor view) — the
    petrol-pump POs linked to this party, so a pump shows its fuel dues on the
    Customer/Supplier-360 page alongside its normal ledger."""
    rows = (await db.execute(
        select(FuelPurchaseOrder).where(
            FuelPurchaseOrder.company_id == user.company_id,
            FuelPurchaseOrder.supplier_party_id == party_id,
        ).order_by(FuelPurchaseOrder.po_date.desc())
    )).scalars().all()
    billed = sum(_pf(r.amount) for r in rows)
    paid = sum(_pf(r.amount_paid) for r in rows)
    stations = sorted({r.station_name for r in rows})
    return {
        "po_count": len(rows), "stations": stations,
        "total_billed": round(billed, 2), "total_paid": round(paid, 2),
        "outstanding": round(billed - paid, 2),
        "recent": [{
            "po_no": r.po_no, "po_date": r.po_date.isoformat() if r.po_date else None,
            "station_name": r.station_name, "amount": _pf(r.amount),
            "amount_paid": _pf(r.amount_paid), "status": r.status,
        } for r in rows[:20]],
    }


# ── Mileage / leakage analytics ───────────────────────────────────────────────

def _period_key(d: date, gran: str) -> str:
    if gran == "month":
        return d.strftime("%Y-%m")
    if gran == "week":
        iso = d.isocalendar()
        return f"{iso[0]}-W{int(iso[1]):02d}"
    return d.isoformat()


async def _vehicle_summaries(db: AsyncSession, user: User, date_from: date, date_to: date,
                             cfg: dict, vehicle_id: uuid.UUID | None = None,
                             gran: str = "day") -> tuple[list[dict], dict]:
    """Per-vehicle mileage summary over [date_from, date_to] + a period series.

    Intervals are computed from ALL of a vehicle's fills up to date_to (so the
    first in-range interval uses the fill just before the window), then filtered
    to the window. The auto-learned baseline is the median of the vehicle's own
    interval mileages within `auto_learn_days` of date_to.
    """
    min_dist = float(cfg.get("min_distance_km", 0) or 0)
    threshold = float(cfg.get("deviation_threshold_pct", 15))
    learn_cutoff = date_to - timedelta(days=int(cfg.get("auto_learn_days", 90)))

    vq = select(Vehicle).where(Vehicle.company_id == user.company_id, Vehicle.is_active == True)
    if vehicle_id:
        vq = vq.where(Vehicle.id == vehicle_id)
    vehicles = {v.id: v for v in (await db.execute(vq)).scalars().all()}

    fq = select(VehicleFuelEntry).where(
        VehicleFuelEntry.company_id == user.company_id,
        VehicleFuelEntry.entry_date <= date_to,
    )
    if vehicle_id:
        fq = fq.where(VehicleFuelEntry.vehicle_id == vehicle_id)
    fills = (await db.execute(fq)).scalars().all()

    by_veh: dict[Any, list[dict]] = {}
    for f in fills:
        by_veh.setdefault(f.vehicle_id, []).append({
            "odometer_km": float(f.odometer_km), "litres": float(f.litres),
            "entry_date": f.entry_date,
            "rate_per_litre": float(f.rate_per_litre) if f.rate_per_litre else None,
        })

    summaries: list[dict] = []
    series_acc: dict[str, dict[str, float]] = {}   # period -> {distance, litres, cost}
    for vid, veh in vehicles.items():
        ents = by_veh.get(vid, [])
        if not ents:
            continue
        tank = float(veh.tank_capacity_litres) if veh.tank_capacity_litres else None
        intervals = fuel_svc.compute_intervals(ents, tank, min_dist)
        learned = fuel_svc.learn_baseline([
            iv["interval_kmpl"] for iv in intervals
            if iv.get("entry_date") and iv["entry_date"] >= learn_cutoff
        ])
        manual = float(veh.benchmark_mileage_kmpl) if veh.benchmark_mileage_kmpl else None
        bench, bench_src = fuel_svc.effective_benchmark(manual, learned)

        dist = 0.0
        litres = 0.0
        cost = 0.0
        flags: set[str] = set()
        for iv in intervals:
            flags.update(iv.get("flags") or [])
            ed = iv.get("entry_date")
            if ed and date_from <= ed <= date_to and iv.get("distance_km") is not None:
                dist += iv["distance_km"]
                litres += float(iv.get("litres") or 0)
                if iv.get("rate_per_litre"):
                    cost += float(iv["litres"]) * float(iv["rate_per_litre"])
                key = _period_key(ed, gran)
                b = series_acc.setdefault(key, {"distance": 0.0, "litres": 0.0, "cost": 0.0})
                b["distance"] += iv["distance_km"]
                b["litres"] += float(iv.get("litres") or 0)
                b["cost"] += (float(iv["litres"]) * float(iv["rate_per_litre"])) if iv.get("rate_per_litre") else 0.0

        actual = round(dist / litres, 2) if litres > 0 and dist > 0 else None
        deviation = expected = excess = excess_cost = None
        expected_km = km_shortfall = None
        if actual is not None and bench:
            deviation = round((bench - actual) / bench * 100, 1)
            expected = round(dist / bench, 2)
            excess = round(litres - expected, 2)
            # Distance the vehicle SHOULD have covered on the diesel it burned, at
            # its benchmark efficiency; shortfall vs the actual odometer distance =
            # km "lost" to leakage / idling / theft.
            expected_km = round(litres * bench, 1)
            km_shortfall = round(expected_km - dist, 1)
            if cost > 0:
                excess_cost = round(excess * (cost / litres), 2)
        summaries.append({
            "vehicle_id": str(vid), "registration_no": veh.registration_no,
            "distance_km": round(dist, 1), "litres": round(litres, 2),
            "actual_kmpl": actual, "benchmark_kmpl": bench, "benchmark_source": bench_src,
            "deviation_pct": deviation, "expected_km": expected_km, "km_shortfall": km_shortfall,
            "expected_litres": expected,
            "excess_litres": excess, "excess_cost": excess_cost,
            "status": fuel_svc.status_for(deviation, threshold),
            "flags": sorted(flags),
        })

    # build the sorted period series (fleet or single-vehicle) with mileage
    series = []
    for key in sorted(series_acc.keys()):
        b = series_acc[key]
        km = round(b["distance"] / b["litres"], 2) if b["litres"] > 0 else None
        series.append({
            "period": key, "distance_km": round(b["distance"], 1),
            "litres": round(b["litres"], 2), "actual_kmpl": km,
            "cost": round(b["cost"], 2),
        })

    tot_dist = sum(s["distance_km"] for s in summaries)
    tot_litres = sum(s["litres"] for s in summaries)
    tot_excess_cost = sum(s["excess_cost"] or 0 for s in summaries)
    totals = {
        "vehicles": len(summaries),
        "distance_km": round(tot_dist, 1),
        "litres": round(tot_litres, 2),
        "avg_kmpl": round(tot_dist / tot_litres, 2) if tot_litres > 0 else None,
        "total_excess_cost": round(tot_excess_cost, 2),
        "leaking_vehicles": sum(1 for s in summaries if s["status"] == "leak"),
    }
    return summaries, {"series": series, "totals": totals}


@router.get("/mileage-report")
async def mileage_report(
    date_from: date = Query(...),
    date_to: date = Query(...),
    granularity: str = Query("day"),
    vehicle_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    if granularity not in ("day", "week", "month"):
        granularity = "day"
    cfg = await _get_fuel_config(db)
    summaries, extra = await _vehicle_summaries(db, user, date_from, date_to, cfg,
                                                vehicle_id, gran=granularity)
    summaries.sort(key=lambda s: (s["deviation_pct"] is None, -(s["deviation_pct"] or 0)))
    return {
        "date_from": str(date_from), "date_to": str(date_to), "granularity": granularity,
        "summary": summaries, "series": extra["series"], "totals": extra["totals"],
    }


async def _fuel_left_by_vehicle(db: AsyncSession, cid: str, veh: dict) -> dict:
    """Approx litres left in each tank (point-in-time, all-time).

    From the most recent brim-full fill: tank_capacity + any partial top-ups after it
    − (distance driven since / benchmark), clamped to [0, tank]. **Distance driven since
    the last fill is taken from the vehicle's weighbridge rent trips** (`tokens.rent_km`
    for COMPLETED sale tokens dated after the fill) so the gauge drops automatically as
    the vehicle works — no manual odometer needed; if the manually-kept current odometer
    implies a *longer* distance, that wins (never a shorter one). Needs tank capacity +
    benchmark + ≥1 tank_full fill; otherwise omitted (None). Approximate — there is no
    live fuel gauge."""
    from collections import defaultdict
    rows = (await db.execute(text(
        "SELECT vehicle_id::text AS vid, odometer_km, litres, tank_full, entry_date "
        "FROM vehicle_fuel_entries WHERE company_id=:cid ORDER BY vehicle_id, odometer_km"
    ), {"cid": cid})).mappings().all()
    by_v: dict[str, list] = defaultdict(list)
    for r in rows:
        by_v[r["vid"]].append(r)

    # Weighbridge rent-trip km per vehicle, with IST completion date — the automatic
    # "distance driven since the last fill" signal (summed per-vehicle after each fill
    # date below). Same trip population as the rent side of the utilisation report.
    trips_by_v: dict[str, list] = defaultdict(list)
    for r in (await db.execute(text(
        "SELECT vehicle_id::text AS vid, "
        "CAST(COALESCE(completed_at, created_at) AT TIME ZONE 'Asia/Kolkata' AS date) AS d, "
        "COALESCE(rent_km, 0) AS km FROM tokens "
        "WHERE company_id=:cid AND token_type='sale' AND status='COMPLETED' "
        "AND vehicle_id IS NOT NULL AND COALESCE(rent_km, 0) > 0"), {"cid": cid})).mappings():
        trips_by_v[r["vid"]].append((r["d"], float(r["km"] or 0)))

    out: dict[str, dict] = {}
    for vid, entries in by_v.items():
        v = veh.get(vid)
        last_fill_odo = float(entries[-1]["odometer_km"] or 0)      # highest fill odo
        last_fill_date = entries[-1]["entry_date"]
        cur_manual = float(v.current_odometer_km) if (v and v.current_odometer_km) else None
        # Odometer to SHOW: the highest HARD reading — manual current or the last fill.
        rec = {"left": None, "odo": round(max(last_fill_odo, cur_manual or 0.0), 1)}
        out[vid] = rec
        if not v or not v.tank_capacity_litres or not v.benchmark_mileage_kmpl:
            continue
        tank = float(v.tank_capacity_litres); bench = float(v.benchmark_mileage_kmpl)
        if bench <= 0:
            continue
        # Reference = the most recent brim-FULL fill (tank is known = capacity there).
        full_idx = None
        for i, e in enumerate(entries):
            if e["tank_full"]:
                full_idx = i
        if full_idx is None:
            continue
        full_odo = float(entries[full_idx]["odometer_km"] or 0)
        litres_after = sum(float(e["litres"] or 0) for e in entries[full_idx + 1:])
        # Current odometer: distance is KNOWN from the fill odometers up to the last fill
        # (operators record the odo at every fill — this captures driving even between a
        # full fill and later partial top-ups); after the last fill, add the rent-km
        # driven (trips dated after it). A manual current reading wins if it is higher.
        trip_after = sum(km for (d, km) in trips_by_v.get(vid, [])
                         if last_fill_date is None or d > last_fill_date)
        current_odo = max(last_fill_odo + trip_after, cur_manual or 0.0)
        burnt = max(0.0, current_odo - full_odo) / bench
        # tank was full at full_odo → − fuel burnt since + partial top-ups since.
        rec["left"] = round(max(0.0, min(tank, tank + litres_after - burnt)), 1)
    return out


@router.get("/vehicle-utilization")
async def vehicle_utilization(
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    """Per-vehicle rent-vs-fuel utilisation over a period (additive report).

    Rent side  — COMPLETED *sale* tokens for own vehicles: km run (tokens.rent_km) +
                 rent earned (tokens.vehicle_rent), IST-bucketed on completion.
    Fuel side  — the fuel log (litres + ₹) in the period.
    Fuel left  — a point-in-time tank estimate (see _fuel_left_by_vehicle).
    net = rent earned − fuel cost (the rent-out profitability of each vehicle)."""
    cid = str(user.company_id)
    p = {"cid": cid, "fd": date_from, "td": date_to}
    r2 = lambda x: round(float(x or 0), 2)  # noqa: E731

    vrows = (await db.execute(select(
        Vehicle.id, Vehicle.registration_no, Vehicle.benchmark_mileage_kmpl,
        Vehicle.tank_capacity_litres, Vehicle.current_odometer_km,
    ).where(Vehicle.company_id == user.company_id))).all()
    veh = {str(r.id): r for r in vrows}

    rent: dict[str, dict] = {}
    for r in (await db.execute(text(
        "SELECT vehicle_id::text AS vid, COUNT(*) AS trips, "
        "COALESCE(SUM(rent_km),0) AS rent_km, COALESCE(SUM(vehicle_rent),0) AS rent_earned "
        "FROM tokens WHERE company_id=:cid AND token_type='sale' AND status='COMPLETED' "
        "AND vehicle_id IS NOT NULL AND (COALESCE(vehicle_rent,0) > 0 OR COALESCE(rent_km,0) > 0) "
        "AND CAST(COALESCE(completed_at, created_at) AT TIME ZONE 'Asia/Kolkata' AS date) "
        "BETWEEN :fd AND :td GROUP BY vehicle_id"), p)).mappings():
        rent[r["vid"]] = dict(r)

    fuel: dict[str, dict] = {}
    for r in (await db.execute(text(
        "SELECT vehicle_id::text AS vid, COALESCE(SUM(litres),0) AS litres, "
        "COALESCE(SUM(amount),0) AS cost FROM vehicle_fuel_entries "
        "WHERE company_id=:cid AND entry_date BETWEEN :fd AND :td GROUP BY vehicle_id"), p)).mappings():
        fuel[r["vid"]] = dict(r)

    left = await _fuel_left_by_vehicle(db, cid, veh)

    rows = []
    tot = {"trips": 0, "rent_km": 0.0, "rent_earned": 0.0, "fuel_litres": 0.0, "fuel_cost": 0.0, "net": 0.0}
    for vid in set(rent) | set(fuel):
        v = veh.get(vid)
        rk = r2(rent.get(vid, {}).get("rent_km")); re_ = r2(rent.get(vid, {}).get("rent_earned"))
        fl = r2(fuel.get(vid, {}).get("litres")); fc = r2(fuel.get(vid, {}).get("cost"))
        trips = int(rent.get(vid, {}).get("trips") or 0)
        net = r2(re_ - fc)
        finfo = left.get(vid) or {}
        odo = finfo.get("odo")
        if odo is None and v and v.current_odometer_km:      # vehicles with rent but no fuel fills
            odo = float(v.current_odometer_km)
        rows.append({
            "vehicle_id": vid, "registration_no": v.registration_no if v else "—",
            "trips": trips, "rent_km": rk, "rent_earned": re_,
            "fuel_litres": fl, "fuel_cost": fc, "net": net,
            "fuel_left_est": finfo.get("left"), "odometer_km": odo,
            "tank_capacity_litres": (float(v.tank_capacity_litres) if v and v.tank_capacity_litres else None),
            "benchmark_mileage_kmpl": (float(v.benchmark_mileage_kmpl) if v and v.benchmark_mileage_kmpl else None),
        })
        tot["trips"] += trips; tot["rent_km"] += rk; tot["rent_earned"] += re_
        tot["fuel_litres"] += fl; tot["fuel_cost"] += fc; tot["net"] += net
    rows.sort(key=lambda x: x["net"], reverse=True)
    for k in ("rent_km", "rent_earned", "fuel_litres", "fuel_cost", "net"):
        tot[k] = r2(tot[k])
    return {"date_from": str(date_from), "date_to": str(date_to), "rows": rows, "totals": tot}


@router.get("/vehicle/{vehicle_id}/history")
async def vehicle_history(
    vehicle_id: str,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    """Full per-vehicle history for the business owner: every diesel fill (when + how
    much + odometer + ₹) and every rent trip (when + km + rent + party/product), plus
    the current fuel-left / odometer estimate. Powers the drill-down from the Fuel-vs-Rent
    report's vehicle link."""
    cid = str(user.company_id)
    fl = lambda x: (float(x) if x is not None else None)  # noqa: E731
    v = (await db.execute(select(Vehicle).where(
        Vehicle.id == vehicle_id, Vehicle.company_id == user.company_id))).scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    left = await _fuel_left_by_vehicle(db, cid, {str(v.id): v})
    finfo = left.get(str(v.id)) or {}

    fills = []
    for r in (await db.execute(text(
        "SELECT entry_date, odometer_km, litres, rate_per_litre, amount, fuel_source, "
        "tank_full, notes FROM vehicle_fuel_entries WHERE company_id=:cid AND vehicle_id=:vid "
        "ORDER BY odometer_km DESC, entry_date DESC"), {"cid": cid, "vid": vehicle_id})).mappings():
        fills.append({
            "entry_date": str(r["entry_date"]) if r["entry_date"] else None,
            "odometer_km": fl(r["odometer_km"]), "litres": fl(r["litres"]),
            "rate_per_litre": fl(r["rate_per_litre"]), "amount": fl(r["amount"]),
            "fuel_source": r["fuel_source"], "tank_full": bool(r["tank_full"]), "notes": r["notes"],
        })

    trips = []
    for r in (await db.execute(text(
        "SELECT t.token_no, t.id::text AS token_id, "
        "CAST(COALESCE(t.completed_at, t.created_at) AT TIME ZONE 'Asia/Kolkata' AS date) AS trip_date, "
        "t.rent_km, t.vehicle_rent, t.net_weight, p.name AS party, pr.name AS product "
        "FROM tokens t LEFT JOIN parties p ON p.id=t.party_id LEFT JOIN products pr ON pr.id=t.product_id "
        "WHERE t.company_id=:cid AND t.vehicle_id=:vid AND t.token_type='sale' AND t.status='COMPLETED' "
        "AND (COALESCE(t.rent_km,0) > 0 OR COALESCE(t.vehicle_rent,0) > 0) "
        "ORDER BY COALESCE(t.completed_at, t.created_at) DESC"), {"cid": cid, "vid": vehicle_id})).mappings():
        trips.append({
            "token_no": r["token_no"], "token_id": r["token_id"],
            "trip_date": str(r["trip_date"]) if r["trip_date"] else None,
            "rent_km": fl(r["rent_km"]), "vehicle_rent": fl(r["vehicle_rent"]),
            "net_weight": fl(r["net_weight"]), "party": r["party"], "product": r["product"],
        })

    summary = {
        "total_litres": round(sum(f["litres"] or 0 for f in fills), 2),
        "total_fuel_cost": round(sum(f["amount"] or 0 for f in fills), 2),
        "fills_count": len(fills),
        "total_rent_km": round(sum(t["rent_km"] or 0 for t in trips), 2),
        "total_rent_earned": round(sum(t["vehicle_rent"] or 0 for t in trips), 2),
        "trips_count": len(trips),
    }
    return {
        "vehicle": {
            "id": str(v.id), "registration_no": v.registration_no,
            "tank_capacity_litres": fl(v.tank_capacity_litres),
            "benchmark_mileage_kmpl": fl(v.benchmark_mileage_kmpl),
            "current_odometer_km": fl(v.current_odometer_km),
            "fuel_left_est": finfo.get("left"), "odometer_est": finfo.get("odo"),
        },
        "fuel_fills": fills, "trips": trips, "summary": summary,
    }


@router.get("/leakage-alerts")
async def leakage_alerts(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    """Vehicles whose mileage deviates beyond the threshold over the last N days,
    ranked by ₹ excess. Powers the Leakage tab + owner glance."""
    to = _today()
    frm = to - timedelta(days=days)
    cfg = await _get_fuel_config(db)
    summaries, extra = await _vehicle_summaries(db, user, frm, to, cfg, gran="day")
    leaks = [s for s in summaries if s["status"] in ("leak", "watch")]
    leaks.sort(key=lambda s: -(s.get("excess_cost") or s.get("excess_litres") or 0))
    return {
        "days": days, "from": str(frm), "to": str(to),
        "threshold_pct": cfg.get("deviation_threshold_pct", 15),
        "alerts": leaks, "totals": extra["totals"],
    }


# ── helpers ───────────────────────────────────────────────────────────────────

def _today() -> date:
    return datetime.utcnow().date()


def _current_tenant_slug() -> str | None:
    try:
        from app.config import get_settings
        if not get_settings().MULTI_TENANT:
            return None
        from app.multitenancy.context import current_tenant_slug
        return current_tenant_slug.get()
    except Exception:
        return None


async def _alert_leakage_bg(company_id: str, tenant_slug: str | None, ctx: dict) -> None:
    """Fire-and-forget diesel-leakage notification (own tenant-routed session)."""
    try:
        from app.database import get_tenant_session
        from app.integrations.notifications.service import send_notification
        async with await get_tenant_session(tenant_slug) as db:
            await send_notification(db, uuid.UUID(company_id), "fuel_leakage_alert", ctx)
            await db.commit()
    except Exception as exc:  # never let an alert break anything
        log.warning("fuel_leakage_alert send failed: %s", exc)
