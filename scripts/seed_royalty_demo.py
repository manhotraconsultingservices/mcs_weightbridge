"""
Royalty / Transit-Pass demo seeder.

Populates the Materials → Royalty Passes page (and its reconciliation) with a
believable mix for a stone-crusher: passes that are healthy, near-exhausted,
fully drawn, expiring-soon, and already expired — plus draw-downs against them
so the utilisation bars and the authorised-vs-consumed reconciliation look real.

API-based + idempotent: demo passes are prefixed RYL/DEMO/ so a re-run skips
ones that already exist. Run AFTER seed_tenant_demo.py (it reuses the suppliers
and products that script creates).

Usage (run on the VPS, or anywhere that can reach the tenant URL):
    python scripts/seed_royalty_demo.py \
        --base-url https://manhotra-consulting.weighbridgesetu.com \
        --username admin --password 'YOUR_PASS'            # dry-run
    python scripts/seed_royalty_demo.py \
        --base-url https://manhotra-consulting.weighbridgesetu.com \
        --username admin --password 'YOUR_PASS' --apply
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta

try:
    import httpx
except ImportError:
    sys.exit("missing dependency: pip install httpx")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

SOURCES = [
    ("Bhilwara Stone Quarry", "Boulder"),
    ("Sikar Mining Lease #44", "Black Trap"),
    ("Nimbahera Aggregate Mine", "GSB Material"),
    ("Chittor Quarry Block-7", "Boulder"),
    ("Banas River Sand Ghat", "River Sand"),
    ("Rajsamand Hill Lease", "Stone Aggregate"),
]
PASS_TYPES = ["royalty", "e_transit", "mineral_permit"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--username", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--tenant-slug", default=None)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    rnd = random.Random(20260616)
    base = args.base_url.rstrip("/")

    # ── Login (tenant form-encoded, slug derived from subdomain) ──────────────
    slug = args.tenant_slug
    if slug is None:
        host = base.split("//", 1)[-1].split("/", 1)[0]
        parts = host.split(".")
        slug = parts[0] if len(parts) >= 3 and parts[0] not in ("www", "platform") else ""
    r = httpx.post(f"{base}/api/v1/auth/login",
                   data={"username": args.username, "password": args.password, "tenant_slug": slug},
                   headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    if r.status_code != 200:
        sys.exit(f"login failed: HTTP {r.status_code} {r.text[:200]}")
    token = r.json()["access_token"]
    H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def get(p, **params):
        rr = httpx.get(f"{base}{p}", headers=H, params=params or None, timeout=60)
        rr.raise_for_status()
        return rr.json()

    def post(p, body, label=""):
        if not args.apply:
            print(f"[DRY] POST {p:38} {label}")
            return {"id": f"dry-{rnd.random()}"}
        rr = httpx.post(f"{base}{p}", headers=H, json=body, timeout=60)
        if rr.status_code >= 400:
            print(f"  ERROR POST {p} → {rr.status_code} {rr.text[:200]}")
            return None
        print(f"  POST {p:38} OK  {label}")
        return rr.json()

    # ── Reference data ───────────────────────────────────────────────────────
    parties = get("/api/v1/parties")
    parties = parties.get("items", parties) if isinstance(parties, dict) else parties
    suppliers = [p for p in parties if p.get("party_type") in ("supplier", "both")] or parties
    products = get("/api/v1/products")
    products = products.get("items", products) if isinstance(products, dict) else products

    existing = get("/api/v1/royalty/passes", page_size=300)
    have = {p["pass_no"] for p in existing.get("items", [])}
    if any(n.startswith("RYL/DEMO/") for n in have):
        print("✔ Royalty demo passes already present — skipping (delete them to re-seed).")
        return 0

    today = date.today()
    # (label, qty_mt, rate, issue_offset_days, valid_offset_days, consume_fraction)
    plan = [
        ("healthy-1",       1200, 65,  -40, 60,  0.55),
        ("healthy-2",        800, 90,  -25, 75,  0.40),
        ("near-exhausted",   500, 110, -50, 20,  0.96),
        ("fully-drawn",      300, 120, -55, 15,  1.00),
        ("expiring-soon",   1500, 48,  -28, 4,   0.22),   # lots left but expires in 4 days → waste risk
        ("expired-partial",  600, 80,  -70, -3,  0.65),   # already expired
        ("fresh-1",          900, 70,  -3,  85,  0.0),
        ("fresh-2",         2200, 55,  -1,  90,  0.0),
    ]

    n = 1000
    made = drawn = 0
    for i, (label, qty, rate, issd, vald, frac) in enumerate(plan):
        src, mineral = SOURCES[i % len(SOURCES)]
        sup = suppliers[i % len(suppliers)] if suppliers else None
        prod = next((p for p in products if mineral.split()[0].lower() in (p.get("name", "").lower())), None)
        n += 1
        body = {
            "pass_no": f"RYL/DEMO/{today.year % 100}-{(today.year + 1) % 100}/{n:04d}",
            "pass_type": PASS_TYPES[i % len(PASS_TYPES)],
            "source_name": src,
            "party_id": sup["id"] if sup else None,
            "mineral": mineral,
            "product_id": prod["id"] if prod else None,
            "issue_date": (today + timedelta(days=issd)).isoformat(),
            "valid_till": (today + timedelta(days=vald)).isoformat(),
            "quantity_mt": qty,
            "rate": rate,
            "amount": qty * rate,
            "vehicle_no": f"RJ{rnd.randint(1,45):02d}GA{rnd.randint(1000,9999)}",
            "notes": f"{label} demo pass",
        }
        res = post("/api/v1/royalty/passes", body, label=f"{label} {qty}MT")
        made += 1
        pid = res.get("id") if res else None

        # Draw down in 1-3 chunks against the pass
        target = round(qty * frac, 1)
        if pid and target > 0:
            remaining = target
            chunks = rnd.randint(1, 3)
            for c in range(chunks):
                amt = round(remaining if c == chunks - 1 else remaining / (chunks - c) * rnd.uniform(0.8, 1.2), 1)
                amt = min(amt, remaining)
                if amt <= 0:
                    break
                cdate = (today + timedelta(days=issd + rnd.randint(1, max(2, -issd - 2)))).isoformat()
                post(f"/api/v1/royalty/passes/{pid}/consume",
                     {"quantity_mt": amt, "consumed_date": cdate,
                      "notes": f"Inbound load against pass ({label})"},
                     label=f"consume {amt}MT")
                drawn += 1
                remaining = round(remaining - amt, 1)

    print(f"\n{'WROTE' if args.apply else 'DRY-RUN — would create'}: "
          f"{made} royalty passes, {drawn} consumptions.")
    if not args.apply:
        print("Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
