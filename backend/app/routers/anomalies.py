"""H3-C: Fraud / Anomaly Analytics.

Seven detectors for stone-crusher operational fraud patterns.
All queries are read-only, company-scoped, and accept a date range.
Config thresholds stored in app_settings under 'anomaly_config' key.
"""
import json
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/v1/reports", tags=["Anomaly Analytics"])

DEFAULT_CONFIG: dict[str, Any] = {
    "high_frequency_trips_per_day": 8,    # > N trips same vehicle same day
    "weight_variance_pct": 25,             # > N% deviation from 30-day mean
    "tare_deviation_kg": 200,              # tare differs from master by > N kg
    "invoice_leakage_hours": 6,            # completed token with no invoice after N hours
    "after_hours_start": 21,              # hour (24h) after which = suspicious
    "after_hours_end": 5,                 # hour (24h) before which = suspicious
    "round_weight_divisor": 1000,         # net_weight divisible by N kg = suspicious
}

_TABLE = "app_settings"
_KEY = "anomaly_config"


async def _get_config(db: AsyncSession) -> dict[str, Any]:
    row = (await db.execute(
        text(f"SELECT value FROM {_TABLE} WHERE key = :k"),
        {"k": _KEY},
    )).fetchone()
    if row:
        try:
            cfg = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            return {**DEFAULT_CONFIG, **cfg}
        except Exception:
            pass
    return DEFAULT_CONFIG


@router.get("/anomaly-config")
async def get_anomaly_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return current anomaly detector thresholds."""
    return await _get_config(db)


@router.put("/anomaly-config")
async def put_anomaly_config(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save anomaly detector thresholds (admin-configurable)."""
    val = json.dumps(payload)
    await db.execute(
        text(f"""
            INSERT INTO {_TABLE} (key, value, updated_at)
            VALUES (:k, :v, NOW())
            ON CONFLICT (key) DO UPDATE
              SET value = EXCLUDED.value,
                  updated_at = NOW()
        """),
        {"k": _KEY, "v": val},
    )
    await db.commit()
    return {"ok": True}


@router.get("/anomalies")
async def get_anomalies(
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run all 7 anomaly detectors and return findings grouped by type."""
    cid = str(current_user.company_id)
    cfg = await _get_config(db)
    results: dict[str, Any] = {}

    # ── 1. HIGH-FREQUENCY TRIPS ──────────────────────────────────────────────
    # Same vehicle made > N trips in a single day (could be fake loads)
    try:
        rows = (await db.execute(text("""
            SELECT vehicle_no, token_date, COUNT(*) AS trip_count
            FROM tokens
            WHERE company_id = :cid
              AND token_date BETWEEN :d1 AND :d2
              AND status = 'COMPLETED'
              AND is_supplement = FALSE
            GROUP BY vehicle_no, token_date
            HAVING COUNT(*) > :threshold
            ORDER BY trip_count DESC, token_date DESC
            LIMIT 50
        """), {
            "cid": cid, "d1": date_from, "d2": date_to,
            "threshold": cfg["high_frequency_trips_per_day"],
        })).fetchall()
        results["high_frequency"] = {
            "title": "High-Frequency Trips",
            "description": f"Same vehicle made > {cfg['high_frequency_trips_per_day']} trips in a single day",
            "severity": "high" if rows else "ok",
            "count": len(rows),
            "items": [
                {"vehicle_no": r[0], "date": str(r[1]), "trip_count": int(r[2])}
                for r in rows
            ],
        }
    except Exception as e:
        results["high_frequency"] = {
            "title": "High-Frequency Trips", "error": str(e), "severity": "ok", "count": 0, "items": [],
        }

    # ── 2. WEIGHT VARIANCE ───────────────────────────────────────────────────
    # Net weight > N% from 30-day historical mean for same vehicle+product
    try:
        rows = (await db.execute(text("""
            WITH stats AS (
                SELECT vehicle_no, product_id,
                       AVG(net_weight)    AS mean_wt,
                       COUNT(*)           AS sample_count
                FROM tokens
                WHERE company_id = :cid
                  AND token_date BETWEEN :hist_start AND :d2
                  AND status = 'COMPLETED'
                  AND net_weight > 0
                  AND is_supplement = FALSE
                GROUP BY vehicle_no, product_id
                HAVING COUNT(*) >= 3
            )
            SELECT t.token_no, t.vehicle_no, t.token_date,
                   t.net_weight,
                   s.mean_wt,
                   ROUND(ABS(t.net_weight - s.mean_wt) / NULLIF(s.mean_wt, 0) * 100, 1) AS variance_pct,
                   p.name AS product_name
            FROM tokens t
            JOIN stats s ON s.vehicle_no = t.vehicle_no AND s.product_id = t.product_id
            LEFT JOIN products p ON p.id = t.product_id
            WHERE t.company_id = :cid
              AND t.token_date BETWEEN :d1 AND :d2
              AND t.status = 'COMPLETED'
              AND t.net_weight > 0
              AND t.is_supplement = FALSE
              AND ABS(t.net_weight - s.mean_wt) / NULLIF(s.mean_wt, 0) * 100 > :threshold
            ORDER BY variance_pct DESC
            LIMIT 50
        """), {
            "cid": cid, "d1": date_from, "d2": date_to,
            "hist_start": date_from - timedelta(days=30),
            "threshold": cfg["weight_variance_pct"],
        })).fetchall()
        results["weight_variance"] = {
            "title": "Weight Variance",
            "description": f"Net weight > {cfg['weight_variance_pct']}% from 30-day average for same vehicle+material",
            "severity": "high" if len(rows) > 5 else "medium" if rows else "ok",
            "count": len(rows),
            "items": [{
                "token_no": r[0], "vehicle_no": r[1], "date": str(r[2]),
                "net_weight_mt": round(float(r[3] or 0) / 1000, 3),
                "mean_mt": round(float(r[4] or 0) / 1000, 3),
                "variance_pct": float(r[5] or 0),
                "product": r[6] or "—",
            } for r in rows],
        }
    except Exception as e:
        results["weight_variance"] = {
            "title": "Weight Variance", "error": str(e), "severity": "ok", "count": 0, "items": [],
        }

    # ── 3. TARE DEVIATION ────────────────────────────────────────────────────
    # Token tare differs from vehicle master tare by > N kg (tare manipulation)
    try:
        rows = (await db.execute(text("""
            SELECT t.token_no, t.vehicle_no, t.token_date,
                   t.tare_weight        AS token_tare,
                   v.default_tare_weight AS master_tare,
                   ABS(t.tare_weight - v.default_tare_weight) AS diff_kg
            FROM tokens t
            JOIN vehicles v ON v.id = t.vehicle_id
            WHERE t.company_id = :cid
              AND t.token_date BETWEEN :d1 AND :d2
              AND t.status = 'COMPLETED'
              AND t.tare_weight IS NOT NULL
              AND v.default_tare_weight IS NOT NULL
              AND ABS(t.tare_weight - v.default_tare_weight) > :threshold
            ORDER BY diff_kg DESC
            LIMIT 50
        """), {
            "cid": cid, "d1": date_from, "d2": date_to,
            "threshold": cfg["tare_deviation_kg"],
        })).fetchall()
        results["tare_deviation"] = {
            "title": "Tare Weight Deviation",
            "description": f"Recorded tare differs from vehicle master tare by > {cfg['tare_deviation_kg']} kg",
            "severity": "high" if rows else "ok",
            "count": len(rows),
            "items": [{
                "token_no": r[0], "vehicle_no": r[1], "date": str(r[2]),
                "token_tare_kg": float(r[3] or 0),
                "master_tare_kg": float(r[4] or 0),
                "diff_kg": float(r[5] or 0),
            } for r in rows],
        }
    except Exception as e:
        results["tare_deviation"] = {
            "title": "Tare Weight Deviation", "error": str(e), "severity": "ok", "count": 0, "items": [],
        }

    # ── 4. INVOICE LEAKAGE ───────────────────────────────────────────────────
    # Completed tokens with no finalized invoice after N hours (revenue slippage)
    try:
        cutoff = datetime.utcnow() - timedelta(hours=cfg["invoice_leakage_hours"])
        rows = (await db.execute(text("""
            SELECT t.token_no, t.vehicle_no, t.token_date, t.net_weight,
                   t.created_at,
                   EXTRACT(EPOCH FROM (NOW() - t.created_at)) / 3600 AS hours_since
            FROM tokens t
            WHERE t.company_id = :cid
              AND t.token_date BETWEEN :d1 AND :d2
              AND t.status = 'COMPLETED'
              AND t.is_supplement = FALSE
              AND NOT EXISTS (
                  SELECT 1 FROM invoices i
                  WHERE i.token_id = t.id
                    AND i.status = 'final'
              )
              AND t.created_at < :cutoff
            ORDER BY t.created_at DESC
            LIMIT 50
        """), {
            "cid": cid, "d1": date_from, "d2": date_to,
            "cutoff": cutoff,
        })).fetchall()
        results["invoice_leakage"] = {
            "title": "Invoice Leakage",
            "description": f"Completed tokens with no finalized invoice after {cfg['invoice_leakage_hours']} hours",
            "severity": "high" if rows else "ok",
            "count": len(rows),
            "items": [{
                "token_no": r[0], "vehicle_no": r[1], "date": str(r[2]),
                "net_mt": round(float(r[3] or 0) / 1000, 3),
                "hours_since": round(float(r[5] or 0), 1),
            } for r in rows],
        }
    except Exception as e:
        results["invoice_leakage"] = {
            "title": "Invoice Leakage", "error": str(e), "severity": "ok", "count": 0, "items": [],
        }

    # ── 5. AFTER-HOURS TOKENS ────────────────────────────────────────────────
    # Tokens created outside normal business hours (gate open when it shouldn't be)
    try:
        rows = (await db.execute(text("""
            SELECT token_no, vehicle_no, token_date,
                   EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata') AS hour_ist,
                   net_weight
            FROM tokens
            WHERE company_id = :cid
              AND token_date BETWEEN :d1 AND :d2
              AND status = 'COMPLETED'
              AND is_supplement = FALSE
              AND (
                  EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata') >= :ah_start
                  OR EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata') < :ah_end
              )
            ORDER BY created_at DESC
            LIMIT 50
        """), {
            "cid": cid, "d1": date_from, "d2": date_to,
            "ah_start": cfg["after_hours_start"],
            "ah_end": cfg["after_hours_end"],
        })).fetchall()
        results["after_hours"] = {
            "title": "After-Hours Activity",
            "description": (
                f"Tokens recorded after {cfg['after_hours_start']}:00 "
                f"or before {cfg['after_hours_end']}:00 IST"
            ),
            "severity": "medium" if rows else "ok",
            "count": len(rows),
            "items": [{
                "token_no": r[0], "vehicle_no": r[1], "date": str(r[2]),
                "hour_ist": int(r[3] or 0),
                "net_mt": round(float(r[4] or 0) / 1000, 3),
            } for r in rows],
        }
    except Exception as e:
        results["after_hours"] = {
            "title": "After-Hours Activity", "error": str(e), "severity": "ok", "count": 0, "items": [],
        }

    # ── 6. ROUND WEIGHT ──────────────────────────────────────────────────────
    # Weighbridge tokens where net weight is exactly divisible by 1000 kg
    # (suggests manual override rather than live scale reading)
    try:
        divisor = int(cfg["round_weight_divisor"])
        rows = (await db.execute(text("""
            SELECT token_no, vehicle_no, token_date, net_weight, weight_method
            FROM tokens
            WHERE company_id = :cid
              AND token_date BETWEEN :d1 AND :d2
              AND status = 'COMPLETED'
              AND net_weight > 0
              AND is_supplement = FALSE
              AND weight_method = 'weighbridge'
              AND MOD(CAST(net_weight AS BIGINT), :divisor) = 0
            ORDER BY token_date DESC
            LIMIT 50
        """), {
            "cid": cid, "d1": date_from, "d2": date_to,
            "divisor": divisor,
        })).fetchall()
        results["round_weight"] = {
            "title": "Suspiciously Round Weights",
            "description": f"Weighbridge tokens where net weight is exactly divisible by {divisor} kg",
            "severity": "medium" if len(rows) > 3 else "low" if rows else "ok",
            "count": len(rows),
            "items": [{
                "token_no": r[0], "vehicle_no": r[1], "date": str(r[2]),
                "net_mt": round(float(r[3] or 0) / 1000, 3),
            } for r in rows],
        }
    except Exception as e:
        results["round_weight"] = {
            "title": "Suspiciously Round Weights", "error": str(e), "severity": "ok", "count": 0, "items": [],
        }

    # ── 7. UNLINKED PURCHASE LOADS ───────────────────────────────────────────
    # Purchase tokens completed without a royalty/transit pass (compliance risk)
    try:
        rows = (await db.execute(text("""
            SELECT t.token_no, t.vehicle_no, t.token_date, t.net_weight,
                   p.name AS party_name
            FROM tokens t
            LEFT JOIN parties p ON p.id = t.party_id
            WHERE t.company_id = :cid
              AND t.token_date BETWEEN :d1 AND :d2
              AND t.token_type = 'purchase'
              AND t.status = 'COMPLETED'
              AND t.is_supplement = FALSE
              AND t.transit_pass_id IS NULL
            ORDER BY t.token_date DESC
            LIMIT 100
        """), {
            "cid": cid, "d1": date_from, "d2": date_to,
        })).fetchall()
        results["unlinked_passes"] = {
            "title": "Unlinked Purchase Loads",
            "description": "Purchase tokens completed without a royalty/transit pass linked (compliance risk)",
            "severity": "high" if rows else "ok",
            "count": len(rows),
            "items": [{
                "token_no": r[0], "vehicle_no": r[1], "date": str(r[2]),
                "net_mt": round(float(r[3] or 0) / 1000, 3),
                "supplier": r[4] or "—",
            } for r in rows],
        }
    except Exception as e:
        results["unlinked_passes"] = {
            "title": "Unlinked Purchase Loads", "error": str(e), "severity": "ok", "count": 0, "items": [],
        }

    # ── Overall severity ─────────────────────────────────────────────────────
    severities = [v.get("severity", "ok") for v in results.values()]
    overall = "ok"
    if "high" in severities:
        overall = "high"
    elif "medium" in severities:
        overall = "medium"
    elif "low" in severities:
        overall = "low"

    return {
        "overall": overall,
        "date_from": str(date_from),
        "date_to": str(date_to),
        "detectors": results,
    }
