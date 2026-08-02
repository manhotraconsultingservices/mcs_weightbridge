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
from app.schemas.vehicle import FuelEntryCreate, FuelEntryUpdate, FuelEntryResponse
from app.services import fuel as fuel_svc

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
    await db.commit()
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
    await db.delete(entry)
    await db.commit()
    return {"ok": True}


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

    out: dict[str, float] = {}
    for vid, entries in by_v.items():
        v = veh.get(vid)
        if not v or not v.tank_capacity_litres or not v.benchmark_mileage_kmpl:
            continue
        tank = float(v.tank_capacity_litres); bench = float(v.benchmark_mileage_kmpl)
        if bench <= 0:
            continue
        full_idx = None
        for i, e in enumerate(entries):
            if e["tank_full"]:
                full_idx = i
        if full_idx is None:
            continue
        full_odo = float(entries[full_idx]["odometer_km"] or 0)
        full_date = entries[full_idx]["entry_date"]
        litres_after = sum(float(e["litres"] or 0) for e in entries[full_idx + 1:])
        # Distance since the last full fill: rent-trip km dated strictly after the fill
        # day (so a just-filled tank reads full), OR the manual current odometer if it
        # implies more — whichever is larger.
        trip_dist = sum(km for (d, km) in trips_by_v.get(vid, [])
                        if full_date is None or d > full_date)
        odo_dist = (max(0.0, float(v.current_odometer_km) - full_odo)
                    if v.current_odometer_km else 0.0)
        burnt = max(trip_dist, odo_dist) / bench
        out[vid] = round(max(0.0, min(tank, tank + litres_after - burnt)), 1)
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
        rows.append({
            "vehicle_id": vid, "registration_no": v.registration_no if v else "—",
            "trips": trips, "rent_km": rk, "rent_earned": re_,
            "fuel_litres": fl, "fuel_cost": fc, "net": net,
            "fuel_left_est": left.get(vid),
            "tank_capacity_litres": (float(v.tank_capacity_litres) if v and v.tank_capacity_litres else None),
            "benchmark_mileage_kmpl": (float(v.benchmark_mileage_kmpl) if v and v.benchmark_mileage_kmpl else None),
        })
        tot["trips"] += trips; tot["rent_km"] += rk; tot["rent_earned"] += re_
        tot["fuel_litres"] += fl; tot["fuel_cost"] += fc; tot["net"] += net
    rows.sort(key=lambda x: x["net"], reverse=True)
    for k in ("rent_km", "rent_earned", "fuel_litres", "fuel_cost", "net"):
        tot[k] = r2(tot[k])
    return {"date_from": str(date_from), "date_to": str(date_to), "rows": rows, "totals": tot}


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
