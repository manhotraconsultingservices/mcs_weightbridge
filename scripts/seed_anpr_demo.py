"""
ANPR demo seeder — Daily Movement Report + Plate Review queue.

Layers realistic gate-camera data on top of the data already created by
`seed_tenant_demo.py` (which seeds vehicles, parties, products, store inventory,
tokens/trips and invoices). This script does NOT create tokens — it:

  1. Picks recent COMPLETED tokens (that have a vehicle + linked invoice) and
     stamps them as gate movements: source='anpr', a realistic anpr_entry_at,
     and an anpr_exit_at (entry + dwell). A few are left "still inside" (no
     exit) so the "currently inside" gauge is non-zero.
  2. Inserts matching anpr_events (entry + exit) for each — so the event log and
     stats line up with the trips.
  3. Inserts unmatched / low-confidence anpr_events (needs_review=TRUE, unknown
     plates, OCR alternates) — these populate the Plate Review queue.

Direct-DB (raw SQL) on purpose: the /anpr/detect API stamps entry/exit with
NOW(), which would cluster every movement at "now" with ~0 dwell. Writing the
timestamps directly gives a believable spread of entry times + dwell.

Idempotent: all demo rows are tagged camera_id='gate-demo'. Re-running without
--force skips if demo events already exist; --force wipes the demo rows first.

Usage (run on the VPS, against the tenant DB):
    # find the tenant DB name first, e.g.  wb_manhotra_consulting
    python scripts/seed_anpr_demo.py \
        --db-url "postgresql://USER:PASS@localhost:5432/wb_manhotra_consulting"        # dry-run
    python scripts/seed_anpr_demo.py --db-url "..." --apply                            # write
    python scripts/seed_anpr_demo.py --db-url "..." --apply --force                    # re-seed
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import uuid
from datetime import datetime, timedelta, time

try:
    import psycopg
except ImportError:
    sys.exit("missing dependency: pip install 'psycopg[binary]'  (the backend venv already has it)")

DEMO_CAM = "gate-demo"     # marker so re-runs are idempotent

# Plates that intentionally do NOT match the vehicle master → land in review queue
UNKNOWN_PLATES = [
    ("MH14GH7788", ["MH14GH7783", "MH14CH7788", "MH140H7788"]),
    ("KA05MN2231", ["KA05MN2231", "KA05NN2231", "KA05MN223I"]),
    ("RJ19TC9007", ["RJ19TC9007", "RJ19IC9007", "RJ19TC900T"]),
    ("GJ01AB4456", ["GJ01AB4456", "GJ0IAB4456", "GJ01A84456"]),
    ("MH12XY0099", ["MH12XY0099", "MH12XY00B9", "MH12KY0099"]),
    ("UP80DD1234", ["UP80DD1234", "UP80OD1234", "UP80DD1Z34"]),
]


def norm(plate: str) -> str:
    return "".join(ch for ch in (plate or "").upper() if ch.isalnum())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-url", required=True, help="postgresql://… URL of the tenant DB")
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry-run)")
    ap.add_argument("--force", action="store_true", help="wipe existing gate-demo rows and re-seed")
    ap.add_argument("--movements", type=int, default=26, help="how many tokens to mark as gate movements")
    ap.add_argument("--unmatched", type=int, default=6, help="how many review-queue events")
    args = ap.parse_args()
    rnd = random.Random(20260616)

    conn = psycopg.connect(args.db_url, autocommit=False)
    cur = conn.cursor()

    # ── Resolve company ──────────────────────────────────────────────────────
    cur.execute("SELECT id FROM companies LIMIT 1")
    row = cur.fetchone()
    if not row:
        sys.exit("No company found — run seed_tenant_demo.py first.")
    company_id = row[0]

    # ── Idempotency ──────────────────────────────────────────────────────────
    cur.execute("SELECT COUNT(*) FROM anpr_events WHERE camera_id = %s", (DEMO_CAM,))
    existing = cur.fetchone()[0]
    if existing and not args.force:
        print(f"✔ Demo ANPR data already present ({existing} events). Use --force to re-seed.")
        return 0
    if existing and args.force:
        print(f"… --force: removing {existing} existing gate-demo events + clearing their token stamps")
        if args.apply:
            cur.execute("""
                UPDATE tokens SET anpr_entry_at = NULL, anpr_exit_at = NULL
                WHERE id IN (SELECT token_id FROM anpr_events WHERE camera_id = %s AND token_id IS NOT NULL)
            """, (DEMO_CAM,))
            cur.execute("DELETE FROM anpr_events WHERE camera_id = %s", (DEMO_CAM,))

    # ── Candidate tokens: recent COMPLETED, with a vehicle + (ideally) invoice ─
    cur.execute("""
        SELECT t.id, t.vehicle_id, t.vehicle_no, t.token_date, t.gate_pass_no
        FROM tokens t
        WHERE t.company_id = %s
          AND t.status = 'COMPLETED'
          AND t.is_supplement = FALSE
          AND COALESCE(t.vehicle_no, '') <> ''
          AND t.anpr_entry_at IS NULL
        ORDER BY t.token_date DESC, t.created_at DESC
        LIMIT %s
    """, (company_id, args.movements))
    tokens = cur.fetchall()
    if not tokens:
        sys.exit("No eligible COMPLETED tokens found — run seed_tenant_demo.py --apply first.")

    moves = 0
    events = 0
    inside = 0
    fy_short = "25-26"
    gp_counter = rnd.randint(900, 1200)

    for i, (tid, vid, vno, tdate, gpno) in enumerate(tokens):
        # entry between 06:30 and 14:30 on the token's date
        entry_dt = datetime.combine(tdate, time(0, 0)) + timedelta(
            minutes=rnd.randint(6 * 60 + 30, 14 * 60 + 30))
        dwell_min = rnd.choice([22, 35, 48, 61, 77, 95, 110, 132, 156])
        # ~1 in 6 still inside (no exit) → feeds the "currently inside" gauge
        still_inside = (i % 6 == 5)
        exit_dt = None if still_inside else entry_dt + timedelta(minutes=dwell_min)
        if still_inside:
            inside += 1
        if not gpno:
            gp_counter += 1
            gpno = f"GP/{fy_short}/{gp_counter:04d}"

        if args.apply:
            cur.execute(
                "UPDATE tokens SET source='anpr', anpr_entry_at=%s, anpr_exit_at=%s, "
                "gate_pass_no=COALESCE(gate_pass_no, %s) WHERE id=%s",
                (entry_dt, exit_dt, gpno, tid))
            # entry event
            cur.execute(
                "INSERT INTO anpr_events (id, company_id, plate_raw, plate_normalized, vehicle_id, "
                "token_id, direction, confidence, source, camera_id, detected_at, needs_review) "
                "VALUES (%s,%s,%s,%s,%s,%s,'entry',%s,'manual',%s,%s,FALSE)",
                (uuid.uuid4(), company_id, vno, norm(vno), vid, tid,
                 round(rnd.uniform(0.86, 0.98), 3), DEMO_CAM, entry_dt))
            events += 1
            if exit_dt:
                cur.execute(
                    "INSERT INTO anpr_events (id, company_id, plate_raw, plate_normalized, vehicle_id, "
                    "token_id, direction, confidence, source, camera_id, detected_at, needs_review) "
                    "VALUES (%s,%s,%s,%s,%s,%s,'exit',%s,'manual',%s,%s,FALSE)",
                    (uuid.uuid4(), company_id, vno, norm(vno), vid, tid,
                     round(rnd.uniform(0.86, 0.98), 3), DEMO_CAM, exit_dt))
                events += 1
        moves += 1

    # ── Review queue: unmatched / low-confidence plates today ────────────────
    today = datetime.now()
    rq = 0
    for j in range(args.unmatched):
        plate, alts = UNKNOWN_PLATES[j % len(UNKNOWN_PLATES)]
        det = datetime.combine(today.date(), time(0, 0)) + timedelta(minutes=rnd.randint(7 * 60, 17 * 60))
        conf = round(rnd.uniform(0.41, 0.57), 3)
        ocr = json.dumps([{"plate": a, "confidence": round(rnd.uniform(0.3, conf), 3)} for a in alts])
        if args.apply:
            cur.execute(
                "INSERT INTO anpr_events (id, company_id, plate_raw, plate_normalized, vehicle_id, "
                "token_id, direction, confidence, source, camera_id, detected_at, ocr_alternates, "
                "needs_review, notes) "
                "VALUES (%s,%s,%s,%s,NULL,NULL,'unmatched',%s,'local_fastalpr',%s,%s,%s::jsonb,TRUE,%s)",
                (uuid.uuid4(), company_id, plate, norm(plate), conf, DEMO_CAM, det, ocr,
                 "Unknown plate — no vehicle-master match (demo)"))
            events += 1
        rq += 1

    if args.apply:
        conn.commit()
        print(f"✅ Wrote demo ANPR data: {moves} gate movements ({inside} still inside), "
              f"{rq} review-queue events, {events} anpr_events total.")
    else:
        conn.rollback()
        print(f"DRY-RUN (no writes): would mark {moves} tokens as gate movements "
              f"({inside} still inside) + {rq} review-queue events. Re-run with --apply.")
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
