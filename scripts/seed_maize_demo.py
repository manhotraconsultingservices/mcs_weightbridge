"""
Production-grade demo seeder for a MAIZE-TRADING Weighbridge SaaS tenant.

Built for the Megna Trading requirement (farmer purchase → weighment → purchase
bill → godown stock → Tally). Uses ONLY existing data models — no schema change.

Mapping (requirement → existing model):
  Farmer            → parties (party_type='supplier', payment_mode='online' so
                      purchase bills are GST/Tally-syncable; village → billing_city)
  Commodity         → products (maize grades, HSN 1005, GST 0%)
  Purchase weighment→ tokens (token_type='purchase', direction='inbound';
                      truck LOADED first = gross, EMPTY second = tare; net = gross−tare)
  Purchase bill     → invoices (auto-created on token completion; type='purchase')
  Godown stock      → product_stock (+ on purchase finalise, − on sale finalise)
  Godowns (master)  → branches  (NOTE: stock balance is company-wide, not per-godown)
  Rate fixed        → party_rates (per farmer per commodity)
  Quality/Moisture/ → token.remarks  (no dedicated fields — see fit-gap report)
   Rate/Godown
  Payments to farmer→ payment_vouchers ; Receipts from buyer → payment_receipts

Usage:
    # Dry-run (default — prints planned calls, writes nothing):
    python scripts/seed_maize_demo.py \\
        --base-url https://megna-trading.weighbridgesetu.com \\
        --username admin --password YOUR_PASS

    # Actually write:
    python scripts/seed_maize_demo.py \\
        --base-url https://megna-trading.weighbridgesetu.com \\
        --username admin --password YOUR_PASS --apply

Idempotent: every entity is checked by natural key before create.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

try:
    import httpx
except ImportError:
    sys.exit("missing dependency: pip install httpx")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
log = logging.getLogger("seed-maize")

random.seed(20260625)
DEMO_TAG = "Seeded by maize-demo-seeder 2026-06-25"
TODAY = date(2026, 6, 25)


def _norm(path: str) -> str:
    return path.rstrip("/") if path.endswith("/") and path != "/" else path


def _items(resp: Any) -> list:
    if isinstance(resp, dict) and "items" in resp:
        return resp["items"]
    return resp if isinstance(resp, list) else []


def _short(d: dict) -> str:
    s = json.dumps({k: v for k, v in d.items() if k != "items"}, default=str)
    return s if len(s) < 100 else s[:97] + "..."


@dataclass
class Client:
    base_url: str
    apply: bool
    token: str | None = None
    counts: dict[str, int] = field(default_factory=lambda: {"created": 0, "skipped": 0, "errors": 0})

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def login(self, username: str, password: str, tenant_slug: str | None = None) -> None:
        url = f"{self.base_url}/api/v1/auth/login"
        if not tenant_slug:
            host = self.base_url.split("//", 1)[-1].split("/", 1)[0]
            parts = host.split(".")
            tenant_slug = parts[0] if len(parts) >= 3 and parts[0] not in ("www", "platform") else ""
        log.info("Authenticating as %s (tenant=%s)", username, tenant_slug or "(single-tenant)")
        r = httpx.post(url, data={"username": username, "password": password, "tenant_slug": tenant_slug},
                       headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
        if r.status_code != 200:
            raise SystemExit(f"login failed: HTTP {r.status_code}  {r.text[:200]}")
        body = r.json()
        self.token = body["access_token"]
        log.info("Authenticated. Tenant: %s  Status: %s", body.get("tenant_slug", "?"), body.get("tenant_status", "?"))

    def get(self, path: str, params: dict | None = None) -> Any:
        r = httpx.get(f"{self.base_url}{_norm(path)}", headers=self._headers(), params=params, timeout=60)
        if r.status_code >= 400:
            raise RuntimeError(f"GET {path} → {r.status_code}  {r.text[:200]}")
        try:
            return r.json()
        except ValueError:
            raise RuntimeError(f"GET {path} not JSON (Nginx→SPA?). First 120: {r.text[:120]!r}")

    def post(self, path: str, payload: dict, label: str = "") -> dict:
        path = _norm(path)
        if not self.apply:
            log.info("[DRY] POST %-46s %s", path, label or _short(payload))
            self.counts["created"] += 1
            return {"id": f"dry-{self.counts['created']}", **payload}
        r = httpx.post(f"{self.base_url}{path}", headers=self._headers(), json=payload, timeout=60)
        if r.status_code >= 400:
            self.counts["errors"] += 1
            log.error("POST %s → %s  %s", path, r.status_code, r.text[:300])
            raise RuntimeError(f"POST {path} failed")
        self.counts["created"] += 1
        log.info("POST %-46s OK  %s", path, label or "")
        return r.json()

    def put(self, path: str, payload: dict, label: str = "") -> dict:
        path = _norm(path)
        if not self.apply:
            log.info("[DRY] PUT  %-46s %s", path, label or _short(payload))
            return {"id": "dry", **payload}
        r = httpx.put(f"{self.base_url}{path}", headers=self._headers(), json=payload, timeout=60)
        if r.status_code >= 400:
            self.counts["errors"] += 1
            log.error("PUT %s → %s  %s", path, r.status_code, r.text[:300])
            raise RuntimeError(f"PUT {path} failed")
        log.info("PUT  %-46s OK  %s", path, label or "")
        return r.json()

    def skip(self, label: str) -> None:
        log.info("skip  %s", label)
        self.counts["skipped"] += 1


# ─── Reference data (company in Karnataka, state_code 29) ───────────────────

def _gstin(state_code: str, pan_prefix: str, seq: int) -> str:
    pan = f"{pan_prefix}{seq:04d}F"
    return f"{state_code}{pan}1Z{(seq * 7) % 10}"


CATEGORIES = [
    {"name": "Maize",        "description": "Maize / corn grades", "sort_order": 1},
    {"name": "Other Grains", "description": "Jowar, bajra, wheat, soybean", "sort_order": 2},
    {"name": "By-Products",  "description": "Bran, husk, broken", "sort_order": 3},
]

# Loose food grain (HSN 1005 maize) is GST-exempt → gst_rate 0. Bran (2302) = 5%.
PRODUCTS = [
    {"category": "Maize",        "name": "Yellow Maize (Feed Grade)",   "code": "MZ-YF",  "hsn_code": "1005", "unit": "MT", "default_rate": "21000.00", "gst_rate": "0.00", "bulk_density": "21.20"},
    {"category": "Maize",        "name": "Yellow Maize (Starch Grade)", "code": "MZ-YS",  "hsn_code": "1005", "unit": "MT", "default_rate": "22500.00", "gst_rate": "0.00", "bulk_density": "21.20"},
    {"category": "Maize",        "name": "White Maize",                 "code": "MZ-WH",  "hsn_code": "1005", "unit": "MT", "default_rate": "23000.00", "gst_rate": "0.00", "bulk_density": "21.00"},
    {"category": "Maize",        "name": "Hybrid Maize",                "code": "MZ-HY",  "hsn_code": "1005", "unit": "MT", "default_rate": "20500.00", "gst_rate": "0.00", "bulk_density": "21.30"},
    {"category": "Maize",        "name": "Maize (Cattle Feed)",         "code": "MZ-CF",  "hsn_code": "1005", "unit": "MT", "default_rate": "19500.00", "gst_rate": "0.00", "bulk_density": "21.40"},
    {"category": "Other Grains", "name": "Jowar (Sorghum)",             "code": "GR-JW",  "hsn_code": "1007", "unit": "MT", "default_rate": "28000.00", "gst_rate": "0.00", "bulk_density": "22.60"},
    {"category": "Other Grains", "name": "Bajra (Pearl Millet)",        "code": "GR-BJ",  "hsn_code": "1008", "unit": "MT", "default_rate": "24000.00", "gst_rate": "0.00", "bulk_density": "22.10"},
    {"category": "Other Grains", "name": "Wheat",                       "code": "GR-WT",  "hsn_code": "1001", "unit": "MT", "default_rate": "25000.00", "gst_rate": "0.00", "bulk_density": "22.40"},
    {"category": "Other Grains", "name": "Soybean",                     "code": "GR-SB",  "hsn_code": "1201", "unit": "MT", "default_rate": "45000.00", "gst_rate": "0.00", "bulk_density": "20.40"},
    {"category": "By-Products",  "name": "Broken Maize",                "code": "BP-BM",  "hsn_code": "1005", "unit": "MT", "default_rate": "17000.00", "gst_rate": "0.00", "bulk_density": "20.80"},
    {"category": "By-Products",  "name": "Maize Bran",                  "code": "BP-BR",  "hsn_code": "2302", "unit": "MT", "default_rate": "14000.00", "gst_rate": "5.00", "bulk_density": "12.00"},
]

# Godowns modelled as branches (master only — stock balance is company-wide).
BRANCHES = [
    {"name": "Main Godown",     "code": "G1",  "city": "Davangere", "state": "Karnataka", "state_code": "29", "is_default": True},
    {"name": "Godown 2",        "code": "G2",  "city": "Harihar",   "state": "Karnataka", "state_code": "29", "is_default": False},
    {"name": "Outside Storage", "code": "OUT", "city": "Ranebennur","state": "Karnataka", "state_code": "29", "is_default": False},
]

_VILLAGES = ["Harihar", "Ranebennur", "Byadgi", "Haveri", "Hirekerur", "Channagiri",
             "Honnali", "Jagalur", "Mayakonda", "Anagodu", "Kukkuwada", "Malebennur",
             "Nyamati", "Santebennur", "Basavapatna"]

_FARMER_NAMES = [
    "Basavaraj Patil", "Mallikarjuna Gowda", "Shivakumar Hiremath", "Ningappa Talwar",
    "Channabasappa Kallapur", "Hanumantappa Doddamani", "Veerabhadrappa Naik",
    "Siddappa Lamani", "Gangadhar Madar", "Yallappa Bhajantri", "Renukaradhya Swamy",
    "Manjunatha Reddy", "Parashuram Goudar", "Fakkirappa Walikar", "Basappa Angadi",
    "Kotresh Kumbar", "Devendrappa Pujar", "Sharanappa Badiger", "Eshwarappa Tubaki",
    "Nagaraj Hadapad", "Rudrappa Chalawadi", "Maheshwarappa Goud",
]

FARMERS = []
for i, nm in enumerate(_FARMER_NAMES):
    FARMERS.append({
        "party_type": "supplier",
        "name": nm,
        "phone": f"9{random.randint(400000000, 879999999)}",
        "billing_city": _VILLAGES[i % len(_VILLAGES)],     # village → city (no village field)
        "billing_state": "Karnataka", "billing_state_code": "29",
        "default_payment_mode": "online",                   # → GST purchase bill → Tally-syncable
        "tally_ledger_name": nm,
        "credit_limit": "0", "payment_terms_days": 7,
        "notes": f"Maize farmer — {DEMO_TAG}",
    })

BUYERS = [
    {"party_type": "customer", "name": "Suguna Poultry Feeds Ltd",      "gstin": _gstin("33", "AABCS", 201), "phone": "9842100200", "billing_city": "Coimbatore", "billing_state": "Tamil Nadu",   "billing_state_code": "33", "default_payment_mode": "online", "credit_limit": "5000000", "payment_terms_days": 30},
    {"party_type": "customer", "name": "Godrej Agrovet Feed Division",  "gstin": _gstin("27", "AAACG", 202), "phone": "9820100300", "billing_city": "Pune",       "billing_state": "Maharashtra",  "billing_state_code": "27", "default_payment_mode": "online", "credit_limit": "8000000", "payment_terms_days": 45},
    {"party_type": "customer", "name": "Venkateshwara Cattle Feeds",    "gstin": _gstin("29", "AAGCV", 203), "phone": "9844100400", "billing_city": "Shivamogga",  "billing_state": "Karnataka",   "billing_state_code": "29", "default_payment_mode": "online", "credit_limit": "2000000", "payment_terms_days": 30},
    {"party_type": "customer", "name": "Sukhjit Starch & Chemicals",    "gstin": _gstin("03", "AAACS", 204), "phone": "9417100500", "billing_city": "Phagwara",   "billing_state": "Punjab",       "billing_state_code": "03", "default_payment_mode": "online", "credit_limit": "6000000", "payment_terms_days": 30},
    {"party_type": "customer", "name": "Davangere Poultry Farm",        "gstin": _gstin("29", "AAGCD", 205), "phone": "9844100600", "billing_city": "Davangere",  "billing_state": "Karnataka",   "billing_state_code": "29", "default_payment_mode": "online", "credit_limit": "1000000", "payment_terms_days": 15},
    {"party_type": "customer", "name": "Mysore Feed & Foods Pvt Ltd",   "gstin": _gstin("29", "AAGCM", 206), "phone": "9844100700", "billing_city": "Mysuru",     "billing_state": "Karnataka",   "billing_state_code": "29", "default_payment_mode": "online", "credit_limit": "1500000", "payment_terms_days": 30},
]

VEHICLES = [
    {"registration_no": "KA17T1234", "vehicle_type": "tractor",  "owner_name": "Basavaraj Patil",   "owner_phone": "9844111111", "default_tare_weight": "3800"},
    {"registration_no": "KA17T5678", "vehicle_type": "tractor",  "owner_name": "Mallikarjuna Gowda","owner_phone": "9844222222", "default_tare_weight": "4100"},
    {"registration_no": "KA27T2233", "vehicle_type": "tractor",  "owner_name": "Shivakumar H",      "owner_phone": "9844333333", "default_tare_weight": "3950"},
    {"registration_no": "KA27T4455", "vehicle_type": "tractor",  "owner_name": "Ningappa Talwar",   "owner_phone": "9844444444", "default_tare_weight": "4300"},
    {"registration_no": "KA17A6677", "vehicle_type": "truck",    "owner_name": "Channabasappa K",   "owner_phone": "9844555555", "default_tare_weight": "11800"},
    {"registration_no": "KA17A8899", "vehicle_type": "truck",    "owner_name": "Hanumantappa D",    "owner_phone": "9844666666", "default_tare_weight": "12400"},
    {"registration_no": "KA27B1010", "vehicle_type": "truck",    "owner_name": "Veerabhadrappa N",  "owner_phone": "9844777777", "default_tare_weight": "12100"},
    {"registration_no": "KA14C2020", "vehicle_type": "truck",    "owner_name": "Manjunatha Reddy",  "owner_phone": "9844888888", "default_tare_weight": "11900"},
    {"registration_no": "KA17T3030", "vehicle_type": "tractor",  "owner_name": "Yallappa B",        "owner_phone": "9844999999", "default_tare_weight": "4000"},
    {"registration_no": "KA27D4040", "vehicle_type": "mini_truck","owner_name": "Kotresh Kumbar",   "owner_phone": "9845000000", "default_tare_weight": "4600"},
    {"registration_no": "KA17A5050", "vehicle_type": "truck",    "owner_name": "Nagaraj Hadapad",   "owner_phone": "9845111111", "default_tare_weight": "12200"},
    {"registration_no": "KA34E6060", "vehicle_type": "truck",    "owner_name": "Rudrappa C",        "owner_phone": "9845222222", "default_tare_weight": "12600"},
]

DRIVERS = [
    {"name": "Imamsab Nadaf",   "license_no": "KA-2018-0011223", "phone": "9845100001"},
    {"name": "Shankarappa M",   "license_no": "KA-2019-0044556", "phone": "9845100002"},
    {"name": "Lokesh Naik",     "license_no": "KA-2020-0078891", "phone": "9845100003"},
    {"name": "Basavaraj Koppa", "license_no": "KA-2017-0099112", "phone": "9845100004"},
]

# Realistic quality grades + moisture for maize procurement (captured in remarks).
_QUALITY = ["FAQ", "FAQ", "Superfine", "Good", "Average", "Discoloured (cut rate)"]


# ─── Seeders ────────────────────────────────────────────────────────────────

def seed_company(c: Client) -> dict:
    log.info("─── Company profile ───")
    existing = c.get("/api/v1/company/")
    if (existing.get("gstin") or "").strip():
        log.info("Company already populated (GSTIN=%s) — skipping", existing["gstin"])
        c.counts["skipped"] += 1
        return existing
    return c.put("/api/v1/company/", {
        "name": "Megna Trading Company",
        "legal_name": "Megna Trading Company",
        "gstin": _gstin("29", "AAGCM", 1), "pan": "AAGCM0001F",
        "address_line1": "APMC Yard, Shop 14-16",
        "city": "Davangere", "state": "Karnataka", "state_code": "29", "pincode": "577001",
        "phone": "08192-234567", "email": "accounts@megnatrading.in",
        "bank_name": "Canara Bank", "bank_account_no": "1234201500678",
        "bank_ifsc": "CNRB0001234", "bank_branch": "APMC Davangere",
        "invoice_prefix": "INV", "quotation_prefix": "QTN", "purchase_prefix": "PUR",
    }, "Megna Trading Company")


def seed_financial_year(c: Client) -> dict:
    log.info("─── Financial year ───")
    fys = c.get("/api/v1/company/financial-years")
    target = next((f for f in fys if f.get("label") == "FY 2025-26"), None)
    if target:
        c.counts["skipped"] += 1
        if not target.get("is_active"):
            c.put(f"/api/v1/company/financial-years/{target['id']}/activate", {}, "Activate FY 2025-26")
        return target
    return c.post("/api/v1/company/financial-years",
                  {"label": "FY 2025-26", "start_date": "2025-04-01", "end_date": "2026-03-31"}, "FY 2025-26")


def seed_branches(c: Client) -> None:
    log.info("─── Branches (godowns) ───")
    try:
        existing = {b["name"] for b in _items(c.get("/api/v1/branches"))}
    except Exception:
        existing = set()
    for b in BRANCHES:
        if b["name"] in existing:
            c.skip(f"branch: {b['name']}")
            continue
        try:
            c.post("/api/v1/branches", b, b["name"])
        except Exception as e:
            log.warning("branch create failed (%s): %s", b["name"], e)


def seed_categories(c: Client) -> dict[str, str]:
    log.info("─── Product categories ───")
    existing = {cat["name"]: cat["id"] for cat in c.get("/api/v1/product-categories")}
    result = dict(existing)
    for cat in CATEGORIES:
        if cat["name"] in existing:
            c.skip(f"category: {cat['name']}")
        else:
            result[cat["name"]] = c.post("/api/v1/product-categories", cat, cat["name"])["id"]
    return result


def seed_products(c: Client, categories: dict[str, str]) -> dict[str, dict]:
    log.info("─── Products (maize grades) ───")
    existing = {p["name"]: p for p in _items(c.get("/api/v1/products", params={"page_size": 200}))}
    result = dict(existing)
    for p in PRODUCTS:
        if p["name"] in existing:
            c.skip(f"product: {p['name']}")
            continue
        result[p["name"]] = c.post("/api/v1/products", {
            "category_id": categories.get(p["category"]), "name": p["name"], "code": p["code"],
            "hsn_code": p["hsn_code"], "unit": p["unit"], "default_rate": p["default_rate"],
            "gst_rate": p["gst_rate"], "bulk_density": p.get("bulk_density"),
        }, p["name"])
    return result


def seed_parties(c: Client) -> dict[str, dict]:
    log.info("─── Parties (farmers + buyers) ───")
    existing = {p["name"]: p for p in _items(c.get("/api/v1/parties", params={"page_size": 300}))}
    result = dict(existing)
    for p in (FARMERS + BUYERS):
        if p["name"] in existing:
            c.skip(f"party: {p['name']}")
            continue
        result[p["name"]] = c.post("/api/v1/parties", p, p["name"])
    return result


def seed_vehicles(c: Client) -> dict[str, dict]:
    log.info("─── Vehicles ───")
    existing = {v["registration_no"]: v for v in _items(c.get("/api/v1/vehicles", params={"page_size": 200}))}
    result = dict(existing)
    for v in VEHICLES:
        if v["registration_no"] in existing:
            c.skip(f"vehicle: {v['registration_no']}")
            continue
        result[v["registration_no"]] = c.post("/api/v1/vehicles", v, v["registration_no"])
    return result


def seed_drivers(c: Client) -> None:
    log.info("─── Drivers ───")
    existing = {d["name"] for d in _items(c.get("/api/v1/drivers", params={"page_size": 200}))}
    for d in DRIVERS:
        if d["name"] in existing:
            c.skip(f"driver: {d['name']}")
        else:
            c.post("/api/v1/drivers", d, d["name"])


def seed_party_rates(c: Client, parties: dict[str, dict], products: dict[str, dict]) -> None:
    """Demonstrate 'rate fixed per farmer per commodity' via party_rates."""
    log.info("─── Party rates (farmer fixed rates) ───")
    farmers = [p for p in parties.values() if p.get("party_type") == "supplier"]
    feed = products.get("Yellow Maize (Feed Grade)")
    if not feed:
        return
    for farmer in random.sample(farmers, k=min(6, len(farmers))):
        rate = random.choice([20800, 21000, 21200, 21500])
        try:
            c.post(f"/api/v1/parties/{farmer['id']}/rates", {
                "product_id": feed["id"], "rate": str(rate),
                "effective_from": (TODAY - timedelta(days=20)).isoformat(),
            }, f"rate {rate} {farmer['name'][:18]} / Feed Maize")
        except Exception as e:
            log.warning("party-rate failed: %s", e)


def seed_opening_stock(c: Client, products: dict[str, dict]) -> None:
    """Opening godown stock (only applies when product stock is currently 0)."""
    log.info("─── Opening godown stock ───")
    opening = {
        "Yellow Maize (Feed Grade)": "250.000",
        "White Maize": "120.000",
        "Hybrid Maize": "80.000",
        "Jowar (Sorghum)": "45.000",
    }
    for name, qty in opening.items():
        p = products.get(name)
        if not p:
            continue
        try:
            c.post("/api/v1/product-stock/opening", {
                "product_id": p["id"], "opening_quantity": qty,
                "notes": f"Opening godown stock — {DEMO_TAG}",
            }, f"opening {qty} MT → {name}")
        except Exception as e:
            log.warning("opening stock skipped (%s): %s", name, e)


# ── Purchase weighment tokens (the core maize flow) ─────────────────────────

def _completed_purchase_token(c: Client, farmer: dict, product: dict, vehicle: dict | None,
                              tdate: date, label: str) -> dict | None:
    """Farmer arrives LOADED → first weight = gross; leaves EMPTY → second = tare."""
    moisture = round(random.uniform(11.5, 16.5), 1)
    quality = random.choice(_QUALITY)
    rate = product.get("default_rate", "21000")
    godown = random.choice([b["name"] for b in BRANCHES])
    remarks = f"Moisture {moisture}% | Quality: {quality} | Rate ₹{rate}/MT | Godown: {godown} | {DEMO_TAG}"
    create = {
        "token_date": tdate.isoformat(), "direction": "inbound", "token_type": "purchase",
        "party_id": farmer["id"], "product_id": product["id"],
        "vehicle_no": vehicle["registration_no"] if vehicle else "KA17T0000",
        "vehicle_id": vehicle["id"] if vehicle else None,
        "vehicle_type": vehicle.get("vehicle_type") if vehicle else "tractor",
        "remarks": remarks,
    }
    try:
        tok = c.post("/api/v1/tokens", create, label)
    except Exception as e:
        log.warning("purchase token create failed: %s", e)
        return None
    if not c.apply:
        return tok
    tare = Decimal(str(vehicle.get("default_tare_weight", 4000))) if vehicle else Decimal("4000")
    # tractor-trolley ~6-13 MT maize; truck ~13-19 MT
    load = Decimal(str(random.randint(6000, 13000))) if (vehicle and vehicle.get("vehicle_type") == "tractor") \
        else Decimal(str(random.randint(13000, 19000)))
    gross = tare + load
    try:
        c.post(f"/api/v1/tokens/{tok['id']}/first-weight", {"weight_kg": str(gross), "is_manual": True}, "first-weight (gross/loaded)")
        c.post(f"/api/v1/tokens/{tok['id']}/second-weight", {"weight_kg": str(tare), "is_manual": True}, "second-weight (tare/empty)")
        return c.get(f"/api/v1/tokens/{tok['id']}")
    except Exception as e:
        log.warning("purchase weighment failed: %s", e)
        return tok


def seed_purchase_tokens(c: Client, parties: dict[str, dict], products: dict[str, dict],
                         vehicles: dict[str, dict]) -> None:
    log.info("─── Purchase weighment tokens (today + 30 days) ───")
    farmers = [p for p in parties.values() if p.get("party_type") == "supplier"]
    maize = [p for p in products.values() if p.get("name", "").startswith(("Yellow", "White", "Hybrid", "Maize"))] or list(products.values())
    veh = list(vehicles.values())
    if not farmers or not maize:
        log.warning("no farmers/products — skip purchase tokens")
        return

    # Today: 6 completed + 2 in-progress (first weight only)
    for i in range(6):
        _completed_purchase_token(c, random.choice(farmers), random.choice(maize),
                                  random.choice(veh) if veh else None, TODAY,
                                  f"P-today-{i+1}/6 ← {random.choice(farmers)['name'][:16]}")
    for i in range(2):
        farmer = random.choice(farmers); product = random.choice(maize)
        vehicle = random.choice(veh) if veh else None
        try:
            tok = c.post("/api/v1/tokens", {
                "token_date": TODAY.isoformat(), "direction": "inbound", "token_type": "purchase",
                "party_id": farmer["id"], "product_id": product["id"],
                "vehicle_no": vehicle["registration_no"] if vehicle else "KA17T0000",
                "vehicle_id": vehicle["id"] if vehicle else None,
                "vehicle_type": vehicle.get("vehicle_type") if vehicle else "tractor",
                "remarks": f"Awaiting empty weight — {DEMO_TAG}",
            }, f"P-inprog-{i+1}/2")
            if c.apply:
                gross = Decimal(str(vehicle.get("default_tare_weight", 4000))) + Decimal("9000")
                c.post(f"/api/v1/tokens/{tok['id']}/first-weight", {"weight_kg": str(gross), "is_manual": True}, "first-weight only")
        except Exception as e:
            log.warning("in-progress purchase token failed: %s", e)

    # Last 30 days: 26 completed (drives stock, daily inward, farmer/vehicle reports)
    for i in range(26):
        tdate = TODAY - timedelta(days=random.randint(1, 29))
        _completed_purchase_token(c, random.choice(farmers), random.choice(maize),
                                  random.choice(veh) if veh else None, tdate,
                                  f"P-D{(TODAY - tdate).days:02d} ← {random.choice(farmers)['name'][:14]}")


def finalise_purchase_invoices(c: Client) -> None:
    """Finalise the draft purchase invoices the weighments auto-created
    (→ godown stock increases, Tally purchase voucher if configured)."""
    log.info("─── Finalise auto-created purchase bills ───")
    if not c.apply:
        log.info("[DRY] would finalise draft purchase invoices")
        return
    try:
        drafts = c.get("/api/v1/invoices/", params={"invoice_type": "purchase", "status": "draft", "page_size": 200})
        for inv in drafts.get("items", []):
            try:
                c.post(f"/api/v1/invoices/{inv['id']}/finalise", {}, f"finalise PUR {inv.get('invoice_no') or inv['id'][:8]}")
            except Exception as e:
                log.warning("finalise purchase failed: %s", e)
    except Exception as e:
        log.warning("fetch purchase drafts failed: %s", e)


# ── Sales (maize → feed mills) to exercise outward stock + receivables ──────

def _invoice_items(products: dict[str, dict], names: list[str]) -> list[dict]:
    items = []
    for i, name in enumerate(names):
        p = products.get(name)
        if not p:
            continue
        qty = Decimal(str(round(random.uniform(18, 40), 2)))
        items.append({
            "product_id": p["id"], "description": p["name"], "hsn_code": p.get("hsn_code", "1005"),
            "quantity": str(qty), "unit": p.get("unit", "MT"), "rate": str(p.get("default_rate", "21000")),
            "gst_rate": str(p.get("gst_rate", "0.00")), "sort_order": i,
        })
    return items


def seed_sales(c: Client, parties: dict[str, dict], products: dict[str, dict], vehicles: dict[str, dict]) -> None:
    log.info("─── Sales invoices (maize → buyers) ───")
    buyers = [p for p in parties.values() if p.get("party_type") == "customer"]
    sale_products = ["Yellow Maize (Feed Grade)", "Yellow Maize (Starch Grade)", "White Maize", "Hybrid Maize", "Maize Bran"]
    veh = list(vehicles.values())
    if not buyers:
        return
    for i in range(12):
        buyer = random.choice(buyers)
        d = TODAY - timedelta(days=random.randint(0, 40))
        names = random.sample(sale_products, k=random.randint(1, 2))
        v = random.choice(veh) if veh else None
        payload = {
            "invoice_type": "sale", "tax_type": "gst", "invoice_date": d.isoformat(),
            "party_id": buyer["id"], "vehicle_no": v["registration_no"] if v else None,
            "transporter_name": None, "payment_mode": "bank",
            "destination": buyer.get("billing_city"), "notes": f"Maize despatch — {DEMO_TAG}",
            "items": _invoice_items(products, names),
        }
        try:
            inv = c.post("/api/v1/invoices/", payload, f"S-{i+1:02d} → {buyer['name'][:22]}")
            if c.apply and random.random() < 0.85:
                c.post(f"/api/v1/invoices/{inv['id']}/finalise", {}, "finalise")
        except Exception as e:
            log.warning("sale invoice failed: %s", e)


# ── Payments: vouchers to farmers, receipts from buyers ─────────────────────

def seed_payments(c: Client) -> None:
    log.info("─── Payments (vouchers to farmers + receipts from buyers) ───")
    if not c.apply:
        log.info("[DRY] would pay farmers + collect from buyers")
        return
    # Pay farmers against finalised PURCHASE invoices (~70%, mostly full)
    purch = c.get("/api/v1/invoices/", params={"invoice_type": "purchase", "status": "final", "page_size": 200})
    for inv in purch.get("items", []):
        pid = (inv.get("party") or {}).get("id") or inv.get("party_id")
        grand = Decimal(str(inv.get("grand_total") or "0"))
        bal = grand - Decimal(str(inv.get("amount_paid") or "0"))
        if not pid or bal <= 0 or random.random() > 0.70:
            continue
        full = random.random() < 0.55
        amt = bal if full else (bal * Decimal("0.5")).quantize(Decimal("0.01"))
        try:
            base = date.fromisoformat(inv["invoice_date"]) if inv.get("invoice_date") else TODAY
        except Exception:
            base = TODAY
        vd = min(TODAY, base + timedelta(days=random.randint(0, 7)))
        try:
            c.post("/api/v1/payments/vouchers", {
                "voucher_date": vd.isoformat(), "party_id": pid, "amount": str(amt),
                "payment_mode": random.choice(["bank_transfer", "upi", "cash"]),
                "reference_no": f"PAY-{random.randint(100000, 999999)}", "bank_name": "Canara Bank",
                "notes": f"Paid against {inv.get('invoice_no')} — {DEMO_TAG}",
                "allocations": [{"invoice_id": inv["id"], "amount": str(amt)}],
            }, f"pay {amt} → farmer ({'full' if full else 'part'})")
        except Exception as e:
            log.warning("voucher failed: %s", e)
    # Collect from buyers against finalised SALE invoices (~60%)
    sales = c.get("/api/v1/invoices/", params={"invoice_type": "sale", "status": "final", "page_size": 200})
    for inv in sales.get("items", []):
        pid = (inv.get("party") or {}).get("id") or inv.get("party_id")
        grand = Decimal(str(inv.get("grand_total") or "0"))
        bal = grand - Decimal(str(inv.get("amount_paid") or "0"))
        if not pid or bal <= 0 or random.random() > 0.60:
            continue
        full = random.random() < 0.5
        amt = bal if full else (bal * Decimal("0.4")).quantize(Decimal("0.01"))
        try:
            base = date.fromisoformat(inv["invoice_date"]) if inv.get("invoice_date") else TODAY
        except Exception:
            base = TODAY
        rd = min(TODAY, base + timedelta(days=random.randint(2, 25)))
        try:
            c.post("/api/v1/payments/receipts", {
                "receipt_date": rd.isoformat(), "party_id": pid, "amount": str(amt),
                "payment_mode": random.choice(["bank_transfer", "upi", "cheque"]),
                "reference_no": f"RCV-{random.randint(100000, 999999)}", "bank_name": "Canara Bank",
                "notes": f"Received against {inv.get('invoice_no')} — {DEMO_TAG}",
                "allocations": [{"invoice_id": inv["id"], "amount": str(amt)}],
            }, f"recv {amt} ← buyer ({'full' if full else 'part'})")
        except Exception as e:
            log.warning("receipt failed: %s", e)


# ─── Main ─────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--base-url", required=True, help="e.g. https://megna-trading.weighbridgesetu.com")
    ap.add_argument("--username", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--apply", action="store_true", help="Actually write. Without it, dry-run only.")
    args = ap.parse_args()

    c = Client(base_url=args.base_url.rstrip("/"), apply=args.apply)
    c.login(args.username, args.password)
    log.info("Mode: %s   Target: %s", "APPLY (writes)" if args.apply else "DRY-RUN (no writes)", c.base_url)

    seed_company(c)
    seed_financial_year(c)
    seed_branches(c)
    cats = seed_categories(c)
    prods = seed_products(c, cats)
    parties = seed_parties(c)
    vehicles = seed_vehicles(c)
    seed_drivers(c)
    seed_party_rates(c, parties, prods)
    seed_opening_stock(c, prods)               # before purchases (opening needs stock=0)
    seed_purchase_tokens(c, parties, prods, vehicles)
    finalise_purchase_invoices(c)              # → godown stock up + Tally purchase vouchers
    seed_sales(c, parties, prods, vehicles)    # → godown stock down + receivables
    seed_payments(c)                           # farmer payouts + buyer collections

    log.info("─" * 60)
    log.info("Done. Created=%d  Skipped=%d  Errors=%d",
             c.counts["created"], c.counts["skipped"], c.counts["errors"])
    if not args.apply:
        log.info("DRY-RUN only. Re-run with --apply to actually write.")


if __name__ == "__main__":
    main()
