"""Fleet fuel & mileage — brim-to-brim mileage, deviation, auto-learned baseline.

All values are computed at READ time from ``vehicle_fuel_entries`` rows; nothing
derived is ever stored (so a corrected fill instantly re-derives correct mileage).

Method (industry-standard "tank / brim-to-brim"):
  - Sort a vehicle's fills by odometer ascending.
  - The distance between fill[i-1] and fill[i] was powered by the litres added at
    fill[i] (you refill what you burned). So over a window of fills f0<f1<…<fn:
        distance = odo(fn) - odo(f0)
        litres   = litres(f1) + … + litres(fn)     # exclude f0 — it powered pre-window km
        mileage  = distance / litres  (km per litre)
  - Rollback intervals (odometer went backwards = meter reset/tamper) are excluded
    from the aggregate and flagged.
"""
from __future__ import annotations

from statistics import median
from typing import Any


def _f(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def compute_intervals(
    entries: list[dict],
    tank_capacity: float | None = None,
    min_distance_km: float = 0.0,
) -> list[dict]:
    """Per-interval breakdown for one vehicle's fills.

    ``entries``: dicts with at least ``odometer_km``, ``litres`` (and any id/date
    fields you want echoed back). Returned list is one row per fill in odometer
    order; each carries the interval that the fill *closed* (distance since the
    previous fill, its km/l, and any tamper flags).
    """
    # Sort TEMPORALLY (by date, odometer as tiebreak) — NOT by odometer — so a
    # backwards odometer reading (meter reset / tamper) stays out of order and is
    # detectable below, instead of being silently re-sorted into ascending order.
    rows = sorted(entries, key=lambda e: (str(e.get("entry_date") or ""), _f(e.get("odometer_km"))))
    out: list[dict] = []
    prev: dict | None = None
    for e in rows:
        odo = _f(e.get("odometer_km"))
        litres = _f(e.get("litres"))
        flags: list[str] = []
        if tank_capacity and tank_capacity > 0 and litres > tank_capacity * 1.05:
            flags.append("litres_over_tank")

        distance: float | None = None
        kmpl: float | None = None
        if prev is not None:
            distance = odo - _f(prev.get("odometer_km"))
            if distance < 0:
                flags.append("odometer_rollback")  # meter reset / tamper — can't measure across it
                distance = None
            elif litres > 0 and distance >= (min_distance_km or 0):
                kmpl = round(distance / litres, 2)

        out.append({
            **e,
            "distance_km": None if distance is None else round(distance, 1),
            "interval_kmpl": kmpl,
            "flags": flags,
        })
        prev = e
    return out


def aggregate(
    entries: list[dict],
    benchmark_kmpl: float | None,
    tank_capacity: float | None = None,
    min_distance_km: float = 0.0,
) -> dict:
    """Period aggregate for ONE vehicle.

    Returns distance / litres / actual km/l / deviation% / expected & excess litres
    (+ excess cost if rates known) / flags. Needs >= 2 fills to yield a mileage.
    """
    rows = sorted(entries, key=lambda e: (str(e.get("entry_date") or ""), _f(e.get("odometer_km"))))
    n = len(rows)
    result: dict[str, Any] = {
        "fills": n,
        "distance_km": 0.0,
        "litres": round(sum(_f(e.get("litres")) for e in rows), 2),
        "actual_kmpl": None,
        "benchmark_kmpl": round(benchmark_kmpl, 2) if benchmark_kmpl else None,
        "deviation_pct": None,
        "expected_km": None,
        "km_shortfall": None,
        "expected_litres": None,
        "excess_litres": None,
        "excess_cost": None,
        "flags": [],
    }
    if n < 2:
        return result

    intervals = compute_intervals(rows, tank_capacity, min_distance_km)
    flags: set[str] = set()
    total_dist = 0.0
    total_litres = 0.0
    total_cost = 0.0
    for iv in intervals:
        flags.update(iv.get("flags") or [])
        if iv["distance_km"] is not None and iv["distance_km"] >= 0:
            total_dist += iv["distance_km"]
            total_litres += _f(iv.get("litres"))       # litres at the LATER fill powered this interval
            rate = iv.get("rate_per_litre")
            if rate is not None:
                total_cost += _f(iv.get("litres")) * _f(rate)

    result["distance_km"] = round(total_dist, 1)
    result["litres"] = round(total_litres, 2)
    result["flags"] = sorted(flags)

    if total_litres > 0 and total_dist > 0:
        actual = total_dist / total_litres
        result["actual_kmpl"] = round(actual, 2)
        if benchmark_kmpl and benchmark_kmpl > 0:
            result["deviation_pct"] = round((benchmark_kmpl - actual) / benchmark_kmpl * 100, 1)
            # Distance the vehicle SHOULD have covered on the diesel it consumed,
            # at its benchmark efficiency (litres × benchmark km/l). Shortfall vs
            # the actual odometer distance = km "lost" to leakage / idling / theft.
            result["expected_km"] = round(total_litres * benchmark_kmpl, 1)
            result["km_shortfall"] = round(result["expected_km"] - total_dist, 1)
            expected = total_dist / benchmark_kmpl
            result["expected_litres"] = round(expected, 2)
            excess = total_litres - expected
            result["excess_litres"] = round(excess, 2)
            # ₹ excess vs benchmark — the number the owner acts on
            avg_rate = (total_cost / total_litres) if total_cost > 0 and total_litres > 0 else None
            if avg_rate:
                result["excess_cost"] = round(excess * avg_rate, 2)
    return result


def estimate_range(
    tank_capacity: float | None,
    last_fill_odometer: float | None,
    last_fill_was_full: bool,
    current_odometer: float | None,
    kmpl: float | None,
) -> dict:
    """How much diesel is likely left, and how far that goes.

    The only moment the level in a tank is known is a brim-full fill, so the
    estimate is anchored there: subtract what the vehicle has burned since, at the
    mileage it actually achieves. Anything missing returns a reason rather than a
    confident-looking number, because a wrong range estimate strands a truck.
    """
    out = {"fuel_left_litres": None, "range_km": None, "km_since_fill": None,
           "reason": None}
    if not tank_capacity or tank_capacity <= 0:
        out["reason"] = "Set the vehicle's tank capacity to estimate range"
        return out
    if not kmpl or kmpl <= 0:
        out["reason"] = "Need a mileage figure — set a benchmark or record two fills"
        return out
    if last_fill_odometer is None or current_odometer is None:
        out["reason"] = "No odometer reading since the last fill"
        return out
    if not last_fill_was_full:
        out["reason"] = "Last fill was not a full tank, so the level is unknown"
        return out

    km_since = max(0.0, current_odometer - last_fill_odometer)
    out["km_since_fill"] = round(km_since, 1)
    used = km_since / kmpl
    left = max(0.0, tank_capacity - used)
    out["fuel_left_litres"] = round(left, 1)
    out["range_km"] = round(left * kmpl, 0)
    return out


def learn_baseline(interval_kmpls: list[float | None]) -> float | None:
    """Auto-learned benchmark = median of a vehicle's own per-interval mileages.
    Needs >= 3 clean intervals, else None (not enough history)."""
    vals = [k for k in interval_kmpls if k and k > 0]
    if len(vals) < 3:
        return None
    return round(median(vals), 2)


def effective_benchmark(manual_kmpl: float | None, learned_kmpl: float | None) -> tuple[float | None, str]:
    """Manual benchmark wins when set; else fall back to the learned baseline.
    Returns (benchmark, source) where source ∈ {'manual','auto','none'}."""
    if manual_kmpl and manual_kmpl > 0:
        return round(manual_kmpl, 2), "manual"
    if learned_kmpl and learned_kmpl > 0:
        return learned_kmpl, "auto"
    return None, "none"


def status_for(deviation_pct: float | None, threshold_pct: float) -> str:
    """ok / watch / leak from the deviation vs the configured threshold.
    Positive deviation = actual mileage BELOW benchmark (more fuel than expected)."""
    if deviation_pct is None:
        return "unknown"
    if deviation_pct >= threshold_pct:
        return "leak"
    if deviation_pct >= threshold_pct * 0.5:
        return "watch"
    return "ok"
