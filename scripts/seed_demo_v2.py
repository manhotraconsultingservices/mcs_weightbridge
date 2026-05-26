"""
Seed demo data for the four new modules launched today:

  • Customer-specific pricing (party_rates) — negotiated rates for 5 key customers
  • Product (finished-goods) stock — min levels + opening stock for the 13 seeded products
  • Production cycles — 6 daily cycles across the past week, finalised so they post to stock

Reads existing parties + products from the tenant; does not create new master data.
Idempotent-ish: skips entries that would conflict (one-cycle-per-day, opening-stock-must-be-zero).

Usage:
    py -3 scripts\\seed_demo_v2.py \\
        --base-url https://manhotra-consulting.weighbridgesetu.com \\
        --username admin --password YOUR_PASS [--apply]
"""
from __future__ import annotations

import argparse
import logging
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

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
log = logging.getLogger("seed-v2")

random.seed(20260526)
TODAY = date(2026, 5, 25)  # server UTC date — matches actual server clock


# ─── Pricing matrix: negotiated rates for 5 key customers ────────────────────
# Each entry overrides the product default rate for that customer.
PRICING_OVERRIDES = {
    "Larsen & Toubro Noida Site": {
        # Bulk highway contractor — discounted across the board
        "20mm Stone Aggregate":  540.00,
        "10mm Stone Aggregate":  555.00,
        "GSB Grade-I":           420.00,
        "Wet Mix Macadam (WMM)": 495.00,
    },
    "NHAI Hisar Project Office": {
        # Government project — even bigger volumes, deeper discount
        "20mm Stone Aggregate":  525.00,
        "10mm Stone Aggregate":  540.00,
        "GSB Grade-I":           410.00,
        "GSB Grade-II":          380.00,
        "Wet Mix Macadam (WMM)": 485.00,
    },
    "Delhi Metro Rail Corp": {
        # Premium contract — special grade requirements (slight premium)
        "20mm Stone Aggregate":  580.00,
        "10mm Stone Aggregate":  600.00,
        "M-Sand (Fine)":         670.00,
    },
    "Modi Cement Works Pvt Ltd": {
        # Long-term customer — modest discount
        "20mm Stone Aggregate":  545.00,
        "Stone Dust":            305.00,
        "M-Sand (Plaster)":      660.00,
    },
    "Hindustan Highway Contractors": {
        # Heavy GSB consumer
        "GSB Grade-I":           425.00,
        "GSB Grade-II":          395.00,
        "Wet Mix Macadam (WMM)": 500.00,
    },
}


# ─── Product stock: min_level + opening_stock per product ────────────────────
# Heavy aggregates kept in larger stockpiles; fines in smaller piles.
STOCK_PLAN = {
    "20mm Stone Aggregate":  {"min": 100, "opening": 425},   # healthy
    "10mm Stone Aggregate":  {"min": 80,  "opening": 320},   # healthy
    "6mm Stone Aggregate":   {"min": 50,  "opening": 180},   # healthy
    "40mm Stone Boulder":    {"min": 60,  "opening":  72},   # near min — slight buffer
    "M-Sand (Fine)":         {"min": 60,  "opening": 240},   # healthy
    "M-Sand (Plaster)":      {"min": 40,  "opening": 150},   # healthy
    "Crushed Sand":          {"min": 40,  "opening": 110},   # healthy
    "Stone Dust":            {"min": 30,  "opening":  28},   # LOW — will trigger alert
    "Fine Stone Powder":     {"min": 20,  "opening":  85},   # healthy
    "GSB Grade-I":           {"min": 80,  "opening": 360},   # healthy
    "GSB Grade-II":          {"min": 50,  "opening": 195},   # healthy
    "Wet Mix Macadam (WMM)": {"min": 60,  "opening": 250},   # healthy
    "Recycled Building Material": {"min": 25, "opening": 0}, # OUT — zero stock by design
}


# ─── Production cycles: 6 days of operation ──────────────────────────────────
# Realistic Indian stone-crusher pattern: ~50 MT input/day, ~83-88% overall yield.
def cycle_for(d: date, input_mt: float) -> dict:
    """Build one cycle's data with realistic stage losses."""
    inp_kg = input_mt * 1000
    stage1 = inp_kg * random.uniform(0.97, 0.99)         # 1-3% lost at primary crusher
    stage2 = stage1  * random.uniform(0.96, 0.99)         # 1-4% lost at secondary
    stage3 = stage2  * random.uniform(0.94, 0.97)         # 3-6% lost at screening (oversize rejected)
    # Stage 4 (wash) — split across products: aggregate dominates, then sand, dust, GSB
    total_out = stage3 * random.uniform(0.88, 0.94)       # 6-12% lost at conveyor wash
    return {
        "cycle_date": d.isoformat(),
        "input_kg":   round(inp_kg, 2),
        "stage1_output_kg": round(stage1, 2),
        "stage2_output_kg": round(stage2, 2),
        "stage3_output_kg": round(stage3, 2),
        "_total_out": total_out,   # used by output splitter below
        "notes": "Normal day shift — single crusher line",
    }


# Cycles for the past 7 days excluding the demo-seeder tokens day
CYCLE_DATES = [TODAY - timedelta(days=i) for i in (1, 2, 3, 4, 5, 7)]
CYCLE_INPUTS = [52.0, 48.0, 51.5, 49.0, 53.0, 50.5]


# ─── HTTP plumbing ────────────────────────────────────────────────────────────

class Client:
    def __init__(self, base_url: str, apply: bool):
        self.base = base_url.rstrip("/")
        self.apply = apply
        self.token: str | None = None
        self.counts = {"created": 0, "skipped": 0, "errors": 0}

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def login(self, username: str, password: str, tenant_slug: str):
        r = httpx.post(f"{self.base}/api/v1/auth/login",
                       data={"username": username, "password": password, "tenant_slug": tenant_slug},
                       timeout=30)
        if r.status_code != 200:
            raise SystemExit(f"login failed: {r.status_code} {r.text[:200]}")
        self.token = r.json()["access_token"]
        log.info("Authenticated as %s (tenant=%s)", username, tenant_slug)

    def get(self, path, **kw):
        r = httpx.get(f"{self.base}{path}", headers=self._h(), timeout=60, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"GET {path} -> {r.status_code} {r.text[:200]}")
        return r.json()

    def post(self, path, payload, label=""):
        if not self.apply:
            log.info("[DRY] POST %-45s %s", path, label)
            self.counts["created"] += 1
            return {"_dry": True}
        r = httpx.post(f"{self.base}{path}", headers=self._h(), json=payload, timeout=60)
        if r.status_code >= 400:
            self.counts["errors"] += 1
            log.warning("POST %s -> %s %s", path, r.status_code, r.text[:180])
            return None
        self.counts["created"] += 1
        log.info("POST %-45s OK  %s", path, label)
        return r.json()

    def put(self, path, payload, label=""):
        if not self.apply:
            log.info("[DRY] PUT  %-45s %s", path, label)
            return {"_dry": True}
        r = httpx.put(f"{self.base}{path}", headers=self._h(), json=payload, timeout=60)
        if r.status_code >= 400:
            self.counts["errors"] += 1
            log.warning("PUT %s -> %s %s", path, r.status_code, r.text[:180])
            return None
        log.info("PUT  %-45s OK  %s", path, label)
        return r.json()


# ─── Seeders ──────────────────────────────────────────────────────────────────

def seed_pricing(c: Client, parties_by_name: dict, products_by_name: dict):
    log.info("─── Pricing matrix overrides ───")
    for party_name, rates in PRICING_OVERRIDES.items():
        party = parties_by_name.get(party_name)
        if not party:
            log.warning("skip pricing for unknown party: %s", party_name)
            c.counts["skipped"] += 1
            continue
        payload_rates = []
        for prod_name, rate in rates.items():
            prod = products_by_name.get(prod_name)
            if not prod:
                log.warning("  unknown product: %s", prod_name)
                continue
            payload_rates.append({"product_id": prod["id"], "rate": rate})
        if not payload_rates:
            continue
        c.post(f"/api/v1/parties/{party['id']}/rates/bulk",
               {"rates": payload_rates},
               f"{party_name}: {len(payload_rates)} rates")


def seed_product_stock(c: Client, products_by_name: dict):
    log.info("─── Product stock: min levels + opening stock ───")
    # Pull current stock levels so we know which products already have non-zero stock
    current_stock = {}
    if c.apply:
        try:
            stock_list = c.get("/api/v1/product-stock")["items"]
            current_stock = {s["product_id"]: float(s["current_stock"]) for s in stock_list}
        except Exception as e:
            log.warning("could not read current stock: %s", e)

    for prod_name, plan in STOCK_PLAN.items():
        prod = products_by_name.get(prod_name)
        if not prod:
            log.warning("skip stock for unknown product: %s", prod_name)
            c.counts["skipped"] += 1
            continue
        # 1. Set min level (idempotent — last write wins)
        c.put(f"/api/v1/product-stock/{prod['id']}/min-level",
              {"min_stock_level": plan["min"]},
              f"{prod_name}: min={plan['min']} MT")
        # 2. Set opening stock if current_stock = 0, otherwise adjust to target
        if plan["opening"] <= 0:
            continue
        cur = current_stock.get(prod["id"], 0)
        if cur == 0:
            c.post("/api/v1/product-stock/opening",
                   {
                       "product_id": prod["id"],
                       "opening_quantity": plan["opening"],
                       "notes": "Opening stock — initial inventory bootstrap",
                   },
                   f"{prod_name}: opening={plan['opening']} MT")
        else:
            # Stock has been pre-decremented (or set) by prior activity — adjust toward target
            delta = plan["opening"] - cur
            if abs(delta) < 0.01:
                log.info("  skip %s: already at target (%.3f MT)", prod_name, cur)
                c.counts["skipped"] += 1
                continue
            c.post("/api/v1/product-stock/adjust",
                   {
                       "product_id": prod["id"],
                       "quantity": delta,
                       "reason": f"Reconcile to opening target {plan['opening']} MT (was {cur:.3f})",
                   },
                   f"{prod_name}: adjust {delta:+.3f} → {plan['opening']} MT")


def seed_production_cycles(c: Client, products_by_name: dict):
    log.info("─── Production cycles ───")
    # Pick 5 products to split Stage 4 outputs across (the bulk of our finished goods)
    output_products = [
        ("20mm Stone Aggregate", 0.35),
        ("10mm Stone Aggregate", 0.25),
        ("M-Sand (Fine)",        0.15),
        ("Stone Dust",           0.15),
        ("GSB Grade-I",          0.10),
    ]
    valid = [(products_by_name[n], frac) for n, frac in output_products if n in products_by_name]
    if not valid:
        log.error("no matching products found — cannot create cycles")
        return

    for d, inp_mt in zip(CYCLE_DATES, CYCLE_INPUTS):
        cycle = cycle_for(d, inp_mt)
        total_out_kg = cycle.pop("_total_out")
        # Distribute output across products by fractions, with a little random jitter
        outputs = []
        for prod, frac in valid:
            jitter = random.uniform(0.92, 1.08)
            outputs.append({
                "product_id": prod["id"],
                "output_kg": round(total_out_kg * frac * jitter, 2),
            })
        cycle["outputs"] = outputs
        created = c.post("/api/v1/production/cycles", cycle, f"cycle {d}: {inp_mt} MT in")
        if created and not created.get("_dry") and c.apply:
            cycle_id = created.get("id")
            if cycle_id:
                c.post(f"/api/v1/production/cycles/{cycle_id}/finalise", {},
                       f"finalise cycle {d}")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--username", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--tenant-slug", default=None,
                    help="Defaults to first subdomain component of base-url")
    ap.add_argument("--apply", action="store_true", help="Write to API (default: dry-run)")
    args = ap.parse_args()

    # Derive tenant_slug from URL if not given
    slug = args.tenant_slug
    if not slug:
        host = args.base_url.split("//", 1)[-1].split("/", 1)[0]
        parts = host.split(".")
        slug = parts[0] if len(parts) >= 3 and parts[0] not in ("www", "platform") else ""

    c = Client(args.base_url, args.apply)
    c.login(args.username, args.password, slug)
    log.info("Mode: %s", "APPLY" if args.apply else "DRY-RUN")

    parties = c.get("/api/v1/parties", params={"page_size": 200}).get("items", [])
    products = c.get("/api/v1/products", params={"page_size": 100}).get("items", [])
    parties_by_name = {p["name"]: p for p in parties}
    products_by_name = {p["name"]: p for p in products}
    log.info("Loaded %d parties, %d products", len(parties_by_name), len(products_by_name))

    seed_pricing(c, parties_by_name, products_by_name)
    seed_product_stock(c, products_by_name)
    seed_production_cycles(c, products_by_name)

    log.info("─" * 60)
    log.info("Done. Created=%d Skipped=%d Errors=%d",
             c.counts["created"], c.counts["skipped"], c.counts["errors"])
    if not args.apply:
        log.info("DRY-RUN — re-run with --apply to actually write.")


if __name__ == "__main__":
    main()
