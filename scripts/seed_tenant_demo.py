"""
Production-grade demo seeder for a Weighbridge SaaS tenant.

Seeds: company profile, financial year, compliance items, master data
(parties, products, categories, vehicles, drivers, transporters), store
inventory (items + POs + transactions), quotations, sales/purchase
invoices, weighbridge tokens (today + last 30 days), and payment receipts.

The token + payment data is sized so the Dashboard widgets populate:
  • Today's tokens / tonnage / revenue cards
  • Recent tokens table
  • Top customers
  • 30-day daily revenue + tonnage trend
  • Product tonnage chart (top 8)
  • Token status distribution (current month)
  • Payment pipeline (last 6 months, paid vs unpaid)

NOT seeded by this script: notifications, camera snapshots.

Usage:
    # Dry-run (default): prints planned calls, makes no writes
    python scripts/seed_tenant_demo.py \\
        --base-url https://manhotra-consulting.weighbridgesetu.com \\
        --username admin \\
        --password YOUR_PASS

    # Actually write:
    python scripts/seed_tenant_demo.py \\
        --base-url https://manhotra-consulting.weighbridgesetu.com \\
        --username admin --password YOUR_PASS --apply

Idempotency: each entity is checked by a natural key (name, registration_no,
GSTIN, etc.) before create. Re-running the script does not duplicate data.
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

# Windows console defaults to cp1252 — force UTF-8 so section-header box-drawing
# chars don't print as ─── escapes.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

# Quiet httpx access logs — they add noise (every dry-run GET prints an INFO line)
logging.getLogger("httpx").setLevel(logging.WARNING)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
log = logging.getLogger("seed")


def _norm(path: str) -> str:
    """Strip trailing slash from API paths so we don't fall through Nginx to the SPA.

    `/api/v1/company/` → `/api/v1/company` (canonical FastAPI route)
    `/api/v1/invoices/{id}/finalise` → unchanged (no trailing slash anyway)
    """
    if path.endswith("/") and path != "/":
        return path.rstrip("/")
    return path


def _items(resp: Any) -> list:
    """Unwrap a list response. Some endpoints return a plain list, others
    return a paginated `{items: [...], total: N}` envelope."""
    if isinstance(resp, dict) and "items" in resp:
        return resp["items"]
    if isinstance(resp, list):
        return resp
    return []

random.seed(20260413)  # deterministic output across runs

DEMO_TAG = "Seeded by demo-seeder 2026-05-26"


# ─── HTTP client ────────────────────────────────────────────────────────────

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
        """Tenant login: OAuth2PasswordRequestForm + tenant_slug (form-encoded).

        The tenant_slug is auto-derived from base_url when not provided
        (e.g. https://manhotra-consulting.weighbridgesetu.com → "manhotra-consulting").
        """
        url = f"{self.base_url}/api/v1/auth/login"
        if not tenant_slug:
            host = self.base_url.split("//", 1)[-1].split("/", 1)[0]
            parts = host.split(".")
            if len(parts) >= 3 and parts[0] not in ("www", "platform"):
                tenant_slug = parts[0]
            else:
                tenant_slug = ""
        log.info("Authenticating as %s (tenant=%s)", username, tenant_slug or "(single-tenant)")
        r = httpx.post(
            url,
            data={"username": username, "password": password, "tenant_slug": tenant_slug},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        if r.status_code != 200:
            raise SystemExit(f"login failed: HTTP {r.status_code}  {r.text[:200]}")
        body = r.json()
        self.token = body["access_token"]
        log.info("Authenticated. Tenant: %s  Status: %s",
                 body.get("tenant_slug", "?"), body.get("tenant_status", "?"))

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        path = _norm(path)
        r = httpx.get(f"{self.base_url}{path}", headers=self._headers(), params=params, timeout=60)
        if r.status_code >= 400:
            raise RuntimeError(f"GET {path} → {r.status_code}  {r.text[:200]}")
        try:
            return r.json()
        except ValueError:
            raise RuntimeError(
                f"GET {path} → {r.status_code} but body was not JSON (likely Nginx fell through to SPA). "
                f"First 120 chars: {r.text[:120]!r}"
            )

    def post(self, path: str, payload: dict[str, Any], label: str = "") -> dict[str, Any]:
        path = _norm(path)
        if not self.apply:
            log.info("[DRY] POST %-50s %s", path, label or _short(payload))
            self.counts["created"] += 1
            return {"id": f"dry-{self.counts['created']}", **payload}
        r = httpx.post(f"{self.base_url}{path}", headers=self._headers(), json=payload, timeout=60)
        if r.status_code >= 400:
            self.counts["errors"] += 1
            log.error("POST %s → %s  %s", path, r.status_code, r.text[:300])
            raise RuntimeError(f"POST {path} failed")
        self.counts["created"] += 1
        log.info("POST %-50s OK  %s", path, label or "")
        return r.json()

    def put(self, path: str, payload: dict[str, Any], label: str = "") -> dict[str, Any]:
        path = _norm(path)
        if not self.apply:
            log.info("[DRY] PUT  %-50s %s", path, label or _short(payload))
            return {"id": "dry", **payload}
        r = httpx.put(f"{self.base_url}{path}", headers=self._headers(), json=payload, timeout=60)
        if r.status_code >= 400:
            self.counts["errors"] += 1
            log.error("PUT %s → %s  %s", path, r.status_code, r.text[:300])
            raise RuntimeError(f"PUT {path} failed")
        log.info("PUT  %-50s OK  %s", path, label or "")
        return r.json()

    def skip(self, label: str) -> None:
        log.info("skip  %s", label)
        self.counts["skipped"] += 1


def _short(d: dict) -> str:
    s = json.dumps({k: v for k, v in d.items() if k != "items"}, default=str)
    return s if len(s) < 100 else s[:97] + "..."


# ─── Reference data ─────────────────────────────────────────────────────────

# Company state: Haryana (state_code 06). Intra-state sales = CGST+SGST,
# Delhi (07) / UP (09) / Rajasthan (08) / Punjab (03) = IGST.

CATEGORIES = [
    {"name": "Aggregate",   "description": "Crushed stone aggregates", "sort_order": 1},
    {"name": "Sand",        "description": "M-sand and natural sand",  "sort_order": 2},
    {"name": "Stone Dust",  "description": "Fine crushed stone fines", "sort_order": 3},
    {"name": "GSB & Base",  "description": "Granular sub-base, base course materials", "sort_order": 4},
]

PRODUCTS = [
    # bulk_density values are industry rule-of-thumb (t/m³); operator can fine-tune later.
    # Aggregate (HSN 2517, GST 5%)
    {"category": "Aggregate",  "name": "20mm Stone Aggregate",  "code": "AGG-20",  "hsn_code": "2517", "unit": "MT", "default_rate": "560.00", "gst_rate": "5.00", "bulk_density": "1.500"},
    {"category": "Aggregate",  "name": "10mm Stone Aggregate",  "code": "AGG-10",  "hsn_code": "2517", "unit": "MT", "default_rate": "580.00", "gst_rate": "5.00", "bulk_density": "1.520"},
    {"category": "Aggregate",  "name": "6mm Stone Aggregate",   "code": "AGG-06",  "hsn_code": "2517", "unit": "MT", "default_rate": "620.00", "gst_rate": "5.00", "bulk_density": "1.480"},
    {"category": "Aggregate",  "name": "40mm Stone Boulder",    "code": "AGG-40",  "hsn_code": "2517", "unit": "MT", "default_rate": "490.00", "gst_rate": "5.00", "bulk_density": "1.450"},
    # Sand (HSN 2505, GST 5%)
    {"category": "Sand",       "name": "M-Sand (Fine)",          "code": "SND-MF",  "hsn_code": "2505", "unit": "MT", "default_rate": "650.00", "gst_rate": "5.00", "bulk_density": "1.700"},
    {"category": "Sand",       "name": "M-Sand (Plaster)",       "code": "SND-MP",  "hsn_code": "2505", "unit": "MT", "default_rate": "680.00", "gst_rate": "5.00", "bulk_density": "1.720"},
    {"category": "Sand",       "name": "Crushed Sand",           "code": "SND-CR",  "hsn_code": "2505", "unit": "MT", "default_rate": "540.00", "gst_rate": "5.00", "bulk_density": "1.550"},
    # Stone Dust (HSN 2517, GST 5%)
    {"category": "Stone Dust", "name": "Stone Dust",             "code": "DUS-01",  "hsn_code": "2517", "unit": "MT", "default_rate": "320.00", "gst_rate": "5.00", "bulk_density": "1.550"},
    {"category": "Stone Dust", "name": "Fine Stone Powder",      "code": "DUS-FP",  "hsn_code": "2517", "unit": "MT", "default_rate": "380.00", "gst_rate": "5.00", "bulk_density": "1.600"},
    # GSB (HSN 2517, GST 5%)
    {"category": "GSB & Base", "name": "GSB Grade-I",            "code": "GSB-I",   "hsn_code": "2517", "unit": "MT", "default_rate": "440.00", "gst_rate": "5.00", "bulk_density": "1.900"},
    {"category": "GSB & Base", "name": "GSB Grade-II",           "code": "GSB-II",  "hsn_code": "2517", "unit": "MT", "default_rate": "410.00", "gst_rate": "5.00", "bulk_density": "1.880"},
    {"category": "GSB & Base", "name": "Wet Mix Macadam (WMM)",  "code": "WMM",     "hsn_code": "2517", "unit": "MT", "default_rate": "520.00", "gst_rate": "5.00", "bulk_density": "1.850"},
    {"category": "GSB & Base", "name": "Recycled Building Material", "code": "RBM", "hsn_code": "2517", "unit": "MT", "default_rate": "290.00", "gst_rate": "5.00", "bulk_density": "1.500"},
]


def _gstin(state_code: str, pan_prefix: str, seq: int) -> str:
    """Synthesise a realistic-looking GSTIN. NOT a real GSTIN — for demo only."""
    pan = f"{pan_prefix}{seq:04d}F"   # 10-char PAN-style (5 alpha + 4 digit + 1 alpha)
    entity = "1"
    return f"{state_code}{pan}{entity}Z{(seq * 7) % 10}"


PARTIES = [
    # ── Local B2B customers (Haryana 06) — Intrastate CGST+SGST ──
    {"party_type": "customer", "name": "Aggarwal Constructions Pvt Ltd",     "gstin": _gstin("06", "AAGCA", 101), "phone": "9988774410", "billing_city": "Faridabad",  "billing_state": "Haryana", "billing_state_code": "06", "billing_pincode": "121002", "credit_limit": "500000", "payment_terms_days": 30},
    {"party_type": "customer", "name": "Singla Builders & Developers",       "gstin": _gstin("06", "ABDPS", 102), "phone": "9810234561", "billing_city": "Gurugram",   "billing_state": "Haryana", "billing_state_code": "06", "billing_pincode": "122001", "credit_limit": "750000", "payment_terms_days": 45},
    {"party_type": "customer", "name": "Verma Infra Projects",               "gstin": _gstin("06", "AAFCV", 103), "phone": "9999013421", "billing_city": "Sonipat",    "billing_state": "Haryana", "billing_state_code": "06", "billing_pincode": "131001", "credit_limit": "300000", "payment_terms_days": 30},
    {"party_type": "customer", "name": "Modi Cement Works Pvt Ltd",          "gstin": _gstin("06", "AAFCM", 104), "phone": "9871230987", "billing_city": "Panipat",    "billing_state": "Haryana", "billing_state_code": "06", "billing_pincode": "132103", "credit_limit": "1200000", "payment_terms_days": 60},
    {"party_type": "customer", "name": "Hindustan Highway Contractors",      "gstin": _gstin("06", "AAACH", 105), "phone": "9818765432", "billing_city": "Karnal",     "billing_state": "Haryana", "billing_state_code": "06", "billing_pincode": "132001", "credit_limit": "2000000", "payment_terms_days": 60},
    {"party_type": "customer", "name": "Rohtak RMC Plant",                   "gstin": _gstin("06", "AABCR", 106), "phone": "9999874511", "billing_city": "Rohtak",     "billing_state": "Haryana", "billing_state_code": "06", "billing_pincode": "124001", "credit_limit": "400000", "payment_terms_days": 30},
    {"party_type": "customer", "name": "NHAI Hisar Project Office",          "gstin": _gstin("06", "AABFN", 107), "phone": "9711200120", "billing_city": "Hisar",      "billing_state": "Haryana", "billing_state_code": "06", "billing_pincode": "125001", "credit_limit": "5000000", "payment_terms_days": 90},
    {"party_type": "customer", "name": "Surya Cement Concrete Works",        "gstin": _gstin("06", "AAGCS", 108), "phone": "9050987612", "billing_city": "Faridabad",  "billing_state": "Haryana", "billing_state_code": "06", "billing_pincode": "121004", "credit_limit": "350000", "payment_terms_days": 30},
    {"party_type": "customer", "name": "Saini Real Estate Developers",       "gstin": _gstin("06", "AAGCS", 109), "phone": "9211231234", "billing_city": "Gurugram",   "billing_state": "Haryana", "billing_state_code": "06", "billing_pincode": "122018", "credit_limit": "600000", "payment_terms_days": 45},
    {"party_type": "customer", "name": "Kapoor Brick & Block Co",            "gstin": _gstin("06", "AAGCK", 110), "phone": "9818000110", "billing_city": "Bahadurgarh","billing_state": "Haryana", "billing_state_code": "06", "billing_pincode": "124507", "credit_limit": "200000", "payment_terms_days": 30},
    # ── Interstate customers ──
    {"party_type": "customer", "name": "Delhi Metro Rail Corp",              "gstin": _gstin("07", "AABCD", 201), "phone": "9999100100", "billing_city": "New Delhi",  "billing_state": "Delhi",     "billing_state_code": "07", "billing_pincode": "110001", "credit_limit": "10000000", "payment_terms_days": 90},
    {"party_type": "customer", "name": "DLF Universal Limited",              "gstin": _gstin("07", "AAACD", 202), "phone": "9818100200", "billing_city": "New Delhi",  "billing_state": "Delhi",     "billing_state_code": "07", "billing_pincode": "110037", "credit_limit": "3500000", "payment_terms_days": 60},
    {"party_type": "customer", "name": "Larsen & Toubro Noida Site",         "gstin": _gstin("09", "AAACL", 203), "phone": "9971220011", "billing_city": "Noida",      "billing_state": "Uttar Pradesh", "billing_state_code": "09", "billing_pincode": "201301", "credit_limit": "8000000", "payment_terms_days": 75},
    {"party_type": "customer", "name": "Shapoorji Pallonji Ghaziabad",       "gstin": _gstin("09", "AAACS", 204), "phone": "9820123412", "billing_city": "Ghaziabad",  "billing_state": "Uttar Pradesh", "billing_state_code": "09", "billing_pincode": "201001", "credit_limit": "4500000", "payment_terms_days": 75},
    {"party_type": "customer", "name": "Raj Construction Co (Jaipur)",       "gstin": _gstin("08", "AAGCR", 205), "phone": "9414012345", "billing_city": "Jaipur",     "billing_state": "Rajasthan",   "billing_state_code": "08", "billing_pincode": "302001", "credit_limit": "700000", "payment_terms_days": 45},
    {"party_type": "customer", "name": "Patiala Civil Works",                "gstin": _gstin("03", "AAGCP", 206), "phone": "9417890123", "billing_city": "Patiala",    "billing_state": "Punjab",      "billing_state_code": "03", "billing_pincode": "147001", "credit_limit": "400000", "payment_terms_days": 30},
    # ── B2C walk-in customers (no GSTIN) ──
    {"party_type": "customer", "name": "Walk-in Customer (Faridabad)",       "gstin": None, "phone": "9999000001", "billing_city": "Faridabad",  "billing_state": "Haryana", "billing_state_code": "06"},
    {"party_type": "customer", "name": "Walk-in Customer (Gurugram)",        "gstin": None, "phone": "9999000002", "billing_city": "Gurugram",   "billing_state": "Haryana", "billing_state_code": "06"},
    {"party_type": "customer", "name": "Mr. Rakesh Kumar (Retail)",          "gstin": None, "phone": "9555123121", "billing_city": "Faridabad",  "billing_state": "Haryana", "billing_state_code": "06"},
    {"party_type": "customer", "name": "Mr. Suresh Chand (Retail)",          "gstin": None, "phone": "9555234567", "billing_city": "Palwal",     "billing_state": "Haryana", "billing_state_code": "06"},
    # ── Suppliers ──
    {"party_type": "supplier", "name": "Rajasthan Stone Quarry Co",          "gstin": _gstin("08", "AAFCQ", 301), "phone": "9414556677", "billing_city": "Alwar",      "billing_state": "Rajasthan", "billing_state_code": "08", "credit_limit": "0",      "payment_terms_days": 30},
    {"party_type": "supplier", "name": "Aravalli Aggregates Pvt Ltd",        "gstin": _gstin("08", "AAACA", 302), "phone": "9414778899", "billing_city": "Bhiwadi",    "billing_state": "Rajasthan", "billing_state_code": "08", "credit_limit": "0",      "payment_terms_days": 45},
    {"party_type": "supplier", "name": "HP Diesel & Fuel Station",           "gstin": _gstin("06", "AAACH", 303), "phone": "9050000123", "billing_city": "Faridabad",  "billing_state": "Haryana",   "billing_state_code": "06", "credit_limit": "0",      "payment_terms_days": 15},
    {"party_type": "supplier", "name": "Sandhu Crusher Spares",              "gstin": _gstin("03", "AAACS", 304), "phone": "9417223344", "billing_city": "Ludhiana",   "billing_state": "Punjab",    "billing_state_code": "03", "credit_limit": "0",      "payment_terms_days": 30},
    {"party_type": "supplier", "name": "Mahalaxmi Hydraulics",               "gstin": _gstin("06", "AAACM", 305), "phone": "9810112233", "billing_city": "Gurugram",   "billing_state": "Haryana",   "billing_state_code": "06", "credit_limit": "0",      "payment_terms_days": 30},
    {"party_type": "supplier", "name": "Indian Oil Corp (Bulk)",             "gstin": _gstin("06", "AAACI", 306), "phone": "9999444555", "billing_city": "Faridabad",  "billing_state": "Haryana",   "billing_state_code": "06", "credit_limit": "0",      "payment_terms_days": 15},
    # ── Both (acts as customer and supplier) ──
    {"party_type": "both",     "name": "Yadav Trading Company",              "gstin": _gstin("06", "AAGCY", 401), "phone": "9818345678", "billing_city": "Faridabad",  "billing_state": "Haryana",   "billing_state_code": "06", "credit_limit": "150000", "payment_terms_days": 30},
    {"party_type": "both",     "name": "Sharma Brothers Materials",          "gstin": _gstin("06", "AAGCS", 402), "phone": "9050778899", "billing_city": "Ballabhgarh","billing_state": "Haryana",   "billing_state_code": "06", "credit_limit": "100000", "payment_terms_days": 30},
]

VEHICLES = [
    {"registration_no": "HR55AB1234", "vehicle_type": "truck",     "owner_name": "Vikram Singh",       "owner_phone": "9050111222", "default_tare_weight": "11800"},
    {"registration_no": "HR55CD5678", "vehicle_type": "truck",     "owner_name": "Rajesh Tomar",       "owner_phone": "9050333444", "default_tare_weight": "12200"},
    {"registration_no": "HR55EF9012", "vehicle_type": "tipper",    "owner_name": "Naresh Yadav",       "owner_phone": "9050555666", "default_tare_weight": "9400"},
    {"registration_no": "HR55GH3456", "vehicle_type": "tipper",    "owner_name": "Sunil Kumar",        "owner_phone": "9050777888", "default_tare_weight": "9650"},
    {"registration_no": "HR99AB1212", "vehicle_type": "trailer",   "owner_name": "Davinder Singh",     "owner_phone": "9871222333", "default_tare_weight": "16200"},
    {"registration_no": "HR99CD3434", "vehicle_type": "trailer",   "owner_name": "Mohan Lal",          "owner_phone": "9871444555", "default_tare_weight": "16400"},
    {"registration_no": "HR55IJ7890", "vehicle_type": "truck",     "owner_name": "Aman Verma",         "owner_phone": "9050666777", "default_tare_weight": "11500"},
    {"registration_no": "HR55KL2233", "vehicle_type": "tipper",    "owner_name": "Pradeep Yadav",      "owner_phone": "9050888999", "default_tare_weight": "9550"},
    {"registration_no": "HR26MN4455", "vehicle_type": "tipper",    "owner_name": "Ramesh Kumar",       "owner_phone": "9555121212", "default_tare_weight": "9700"},
    {"registration_no": "PB02OP6677", "vehicle_type": "truck",     "owner_name": "Hardip Singh",       "owner_phone": "9417888777", "default_tare_weight": "11900"},
    {"registration_no": "PB02QR8899", "vehicle_type": "trailer",   "owner_name": "Jaspreet Singh",     "owner_phone": "9417666555", "default_tare_weight": "16100"},
    {"registration_no": "RJ14ST1010", "vehicle_type": "truck",     "owner_name": "Mukesh Sharma",      "owner_phone": "9414111000", "default_tare_weight": "11700"},
    {"registration_no": "DL01UV2020", "vehicle_type": "mini_truck","owner_name": "Subhash Chand",      "owner_phone": "9818020202", "default_tare_weight": "4800"},
    {"registration_no": "HR55WX3030", "vehicle_type": "tanker",    "owner_name": "Karan Singh",        "owner_phone": "9050303030", "default_tare_weight": "13500"},
    {"registration_no": "UP14YZ4040", "vehicle_type": "tipper",    "owner_name": "Ajay Kumar",         "owner_phone": "9971404040", "default_tare_weight": "9600"},
]

DRIVERS = [
    {"name": "Ramesh Pal",       "license_no": "HR-2018-0011223",  "phone": "9050100001"},
    {"name": "Surinder Kumar",   "license_no": "HR-2017-0044556",  "phone": "9050100002"},
    {"name": "Jagdish Singh",    "license_no": "PB-2019-0078891",  "phone": "9417100003"},
    {"name": "Bhuvan Tomar",     "license_no": "HR-2020-0099112",  "phone": "9050100004"},
    {"name": "Manoj Yadav",      "license_no": "HR-2016-0033445",  "phone": "9050100005"},
    {"name": "Karim Khan",       "license_no": "RJ-2018-0055678",  "phone": "9414100006"},
]

TRANSPORTERS = [
    {"name": "Yadav Transport Co",        "gstin": _gstin("06", "AAGCY", 901), "phone": "9050900100", "address": "Plot 14, Sec-37, Faridabad, Haryana"},
    {"name": "Shree Balaji Logistics",    "gstin": _gstin("06", "AAGCS", 902), "phone": "9818900200", "address": "Industrial Area, Gurugram, Haryana"},
    {"name": "Northern Carriers Ltd",     "gstin": _gstin("03", "AAFCN", 903), "phone": "9417900300", "address": "GT Road, Ludhiana, Punjab"},
]

# ── Compliance items: realistic stone-crusher operating licenses ────────────
TODAY = date(2026, 5, 26)
COMPLIANCE = [
    {"item_type": "license",       "name": "Stone Crusher Operating Licence",
     "policy_holder": "Manhotra Consulting", "issuer": "Mining Dept, Govt of Haryana",
     "reference_no": "MIN/SC/2024/1142", "issue_date": (TODAY - timedelta(days=400)).isoformat(),
     "expiry_date": (TODAY + timedelta(days=330)).isoformat(),
     "notes": "Annual renewal required. Pay royalty Q1."},
    {"item_type": "permit",        "name": "Pollution Control NOC (HSPCB)",
     "policy_holder": "Manhotra Consulting", "issuer": "Haryana State Pollution Control Board",
     "reference_no": "HSPCB/CTO/2024/8821", "issue_date": (TODAY - timedelta(days=200)).isoformat(),
     "expiry_date": (TODAY + timedelta(days=45)).isoformat(),
     "notes": "Renewal application to be filed 30 days before expiry."},
    {"item_type": "certification", "name": "Weighbridge Stamping Certificate",
     "policy_holder": "Manhotra Consulting", "issuer": "Legal Metrology Dept, Haryana",
     "reference_no": "LM/WB/FBD/2025/0451", "issue_date": (TODAY - timedelta(days=120)).isoformat(),
     "expiry_date": (TODAY + timedelta(days=245)).isoformat(),
     "notes": "Annual recalibration mandatory."},
    {"item_type": "insurance",     "name": "Fire & Burglary Insurance — Plant",
     "policy_holder": "Manhotra Consulting", "issuer": "Oriental Insurance Co Ltd",
     "reference_no": "OIC/HR/2025/FB/22341", "issue_date": (TODAY - timedelta(days=330)).isoformat(),
     "expiry_date": (TODAY + timedelta(days=20)).isoformat(),
     "notes": "Auto-renewal. Premium ₹48,500/yr."},
    {"item_type": "insurance",     "name": "Vehicle Insurance — HR55AB1234",
     "policy_holder": "Vikram Singh", "issuer": "ICICI Lombard",
     "reference_no": "IL/COMM/2024/HR/9981", "issue_date": (TODAY - timedelta(days=380)).isoformat(),
     "expiry_date": (TODAY - timedelta(days=14)).isoformat(),
     "notes": "EXPIRED — renew before next use."},
]


# ── Inventory: realistic crusher consumables ──────────────────────────────
INVENTORY_ITEMS = [
    {"name": "HSD Diesel",          "category": "fuel",        "unit": "litre", "min_stock_level": "500",  "reorder_quantity": "2000", "description": "High Speed Diesel for plant + DG set"},
    {"name": "Hydraulic Oil 68",    "category": "fuel",        "unit": "litre", "min_stock_level": "100",  "reorder_quantity": "200",  "description": "HLP 68 hydraulic oil for crusher hydraulics"},
    {"name": "Engine Oil 15W40",    "category": "fuel",        "unit": "litre", "min_stock_level": "60",   "reorder_quantity": "120",  "description": "Diesel engine lubricant for trucks/DG"},
    {"name": "Jaw Plate (Fixed)",   "category": "parts",       "unit": "piece", "min_stock_level": "2",    "reorder_quantity": "4",    "description": "Mn-steel fixed jaw plate, primary jaw crusher"},
    {"name": "Jaw Plate (Swing)",   "category": "parts",       "unit": "piece", "min_stock_level": "2",    "reorder_quantity": "4",    "description": "Mn-steel swing jaw plate, primary jaw crusher"},
    {"name": "Cone Mantle",         "category": "parts",       "unit": "piece", "min_stock_level": "1",    "reorder_quantity": "2",    "description": "Cone crusher mantle"},
    {"name": "Bowl Liner",          "category": "parts",       "unit": "piece", "min_stock_level": "1",    "reorder_quantity": "2",    "description": "Cone crusher bowl liner"},
    {"name": "Conveyor Belt 800mm", "category": "parts",       "unit": "metre", "min_stock_level": "20",   "reorder_quantity": "40",   "description": "EP 500/4 ply rubber belt"},
    {"name": "Bearing 22228 CC/W33","category": "parts",       "unit": "piece", "min_stock_level": "4",    "reorder_quantity": "8",    "description": "SKF spherical roller bearing"},
    {"name": "Welding Rod E7018",   "category": "tools",       "unit": "kg",    "min_stock_level": "20",   "reorder_quantity": "50",   "description": "Low-hydrogen welding electrodes"},
    {"name": "Safety Helmet",       "category": "other",       "unit": "piece", "min_stock_level": "10",   "reorder_quantity": "20",   "description": "ISI marked safety helmets for operators"},
]


# ─── Seeders ─────────────────────────────────────────────────────────────────

def seed_company(c: Client) -> dict:
    """Update the singleton company profile."""
    log.info("─── Company profile ───")
    existing = c.get("/api/v1/company/")
    if (existing.get("gstin") or "").strip():
        log.info("Company already populated (GSTIN=%s) — skipping", existing["gstin"])
        c.counts["skipped"] += 1
        return existing
    payload = {
        "name": "Manhotra Consulting — Stone Crusher Division",
        "legal_name": "Manhotra Consulting Services Pvt Ltd",
        "gstin": _gstin("06", "AAGCM", 1),
        "pan": "AAGCM0001F",
        "address_line1": "Plot 7, Industrial Area Sector-58",
        "city": "Faridabad",
        "state": "Haryana",
        "state_code": "06",
        "pincode": "121004",
        "phone": "0129-4123456",
        "email": "accounts@manhotra-consulting.com",
        "website": "https://weighbridgesetu.com",
        "bank_name": "HDFC Bank",
        "bank_account_no": "501020010012345",
        "bank_ifsc": "HDFC0001234",
        "bank_branch": "Sector-15, Faridabad",
        "invoice_prefix": "MCS",
        "quotation_prefix": "QTN",
        "purchase_prefix": "PUR",
    }
    return c.put("/api/v1/company/", payload, "Manhotra Consulting")


def seed_financial_year(c: Client) -> dict:
    """Ensure FY 25-26 exists and is active."""
    log.info("─── Financial year ───")
    fys = c.get("/api/v1/company/financial-years")
    target = next((f for f in fys if f.get("label") == "FY 2025-26"), None)
    if target:
        log.info("FY 2025-26 already exists")
        c.counts["skipped"] += 1
        if not target.get("is_active"):
            c.put(f"/api/v1/company/financial-years/{target['id']}/activate", {}, "Activate FY 2025-26")
        return target
    return c.post("/api/v1/company/financial-years", {
        "label": "FY 2025-26",
        "start_date": "2025-04-01",
        "end_date": "2026-03-31",
    }, "FY 2025-26")


def seed_categories(c: Client) -> dict[str, str]:
    log.info("─── Product categories ───")
    existing = {cat["name"]: cat["id"] for cat in c.get("/api/v1/product-categories")}
    result = dict(existing)
    for cat in CATEGORIES:
        if cat["name"] in existing:
            c.skip(f"category: {cat['name']}")
            result[cat["name"]] = existing[cat["name"]]
        else:
            r = c.post("/api/v1/product-categories", cat, cat["name"])
            result[cat["name"]] = r["id"]
    return result


def seed_products(c: Client, categories: dict[str, str]) -> dict[str, dict]:
    log.info("─── Products ───")
    existing = {p["name"]: p for p in _items(c.get("/api/v1/products", params={"page_size": 200}))}
    result: dict[str, dict] = dict(existing)
    for p in PRODUCTS:
        if p["name"] in existing:
            c.skip(f"product: {p['name']}")
            continue
        payload = {
            "category_id": categories.get(p["category"]),
            "name": p["name"], "code": p["code"], "hsn_code": p["hsn_code"],
            "unit": p["unit"], "default_rate": p["default_rate"], "gst_rate": p["gst_rate"],
            "bulk_density": p.get("bulk_density"),
        }
        r = c.post("/api/v1/products", payload, p["name"])
        result[p["name"]] = r
    return result


def seed_parties(c: Client) -> dict[str, dict]:
    log.info("─── Parties ───")
    existing = {p["name"]: p for p in _items(c.get("/api/v1/parties", params={"page_size": 200}))}
    result = dict(existing)
    for p in PARTIES:
        if p["name"] in existing:
            c.skip(f"party: {p['name']}")
            continue
        r = c.post("/api/v1/parties", p, p["name"])
        result[p["name"]] = r
    return result


def seed_vehicles(c: Client) -> dict[str, dict]:
    log.info("─── Vehicles ───")
    existing = {v["registration_no"]: v for v in _items(c.get("/api/v1/vehicles", params={"page_size": 200}))}
    result = dict(existing)
    for v in VEHICLES:
        if v["registration_no"] in existing:
            c.skip(f"vehicle: {v['registration_no']}")
            continue
        r = c.post("/api/v1/vehicles", v, v["registration_no"])
        result[v["registration_no"]] = r
    return result


def seed_drivers(c: Client) -> None:
    log.info("─── Drivers ───")
    existing = {d["name"] for d in _items(c.get("/api/v1/drivers", params={"page_size": 200}))}
    for d in DRIVERS:
        if d["name"] in existing:
            c.skip(f"driver: {d['name']}")
            continue
        c.post("/api/v1/drivers", d, d["name"])


def seed_transporters(c: Client) -> None:
    log.info("─── Transporters ───")
    existing = {t["name"] for t in _items(c.get("/api/v1/transporters", params={"page_size": 200}))}
    for t in TRANSPORTERS:
        if t["name"] in existing:
            c.skip(f"transporter: {t['name']}")
            continue
        c.post("/api/v1/transporters", t, t["name"])


def seed_compliance(c: Client) -> None:
    log.info("─── Compliance ───")
    existing = {it["name"] for it in _items(c.get("/api/v1/compliance"))}
    for item in COMPLIANCE:
        if item["name"] in existing:
            c.skip(f"compliance: {item['name']}")
            continue
        c.post("/api/v1/compliance", item, item["name"])


def seed_inventory(c: Client) -> dict[str, dict]:
    log.info("─── Inventory items ───")
    existing = {i["name"]: i for i in _items(c.get("/api/v1/inventory/items"))}
    result = dict(existing)
    for it in INVENTORY_ITEMS:
        if it["name"] in existing:
            c.skip(f"inventory: {it['name']}")
            continue
        r = c.post("/api/v1/inventory/items", it, it["name"])
        result[it["name"]] = r
    return result


def seed_inventory_movements(c: Client, items: dict[str, dict]) -> None:
    """Adjust + issue some stock so dashboard analytics have real history."""
    log.info("─── Inventory movements (adjust + issue) ───")

    # Opening adjustments to fill stock
    opening = {
        "HSD Diesel": "3500",
        "Hydraulic Oil 68": "180",
        "Engine Oil 15W40": "100",
        "Jaw Plate (Fixed)": "3",
        "Jaw Plate (Swing)": "3",
        "Cone Mantle": "2",
        "Bowl Liner": "2",
        "Conveyor Belt 800mm": "35",
        "Bearing 22228 CC/W33": "6",
        "Welding Rod E7018": "40",
        "Safety Helmet": "18",
    }
    for name, qty in opening.items():
        item = items.get(name)
        if not item:
            continue
        c.post("/api/v1/inventory/adjust", {
            "item_id": item["id"],
            "quantity": qty,
            "reason": f"Opening stock — {DEMO_TAG}",
        }, f"adjust +{qty} {item['unit']} → {name}")

    # Subsequent issues (consumption pattern)
    issues = [
        ("HSD Diesel",         "320", "Plant operations — week 1"),
        ("HSD Diesel",         "280", "Plant operations — week 2"),
        ("HSD Diesel",         "295", "Plant operations — week 3"),
        ("Hydraulic Oil 68",   "25",  "Cone crusher top-up"),
        ("Engine Oil 15W40",   "15",  "DG set service"),
        ("Welding Rod E7018",  "8",   "Chassis repair — HR55AB1234"),
        ("Safety Helmet",      "3",   "New operator joining"),
    ]
    for name, qty, note in issues:
        item = items.get(name)
        if not item:
            continue
        c.post("/api/v1/inventory/issue", {
            "item_id": item["id"],
            "quantity": qty,
            "notes": f"{note} — {DEMO_TAG}",
            "used_by_name": random.choice(["Plant Operator", "Foreman", "Workshop Team"]),
            "used_on": (TODAY - timedelta(days=random.randint(1, 45))).isoformat(),
        }, f"issue -{qty} {item['unit']} → {name}")


def seed_purchase_orders(c: Client, items: dict[str, dict]) -> None:
    log.info("─── Purchase Orders ───")
    if not items:
        return

    # PO 1: pending approval
    diesel = items.get("HSD Diesel")
    if diesel:
        c.post("/api/v1/inventory/purchase-orders", {
            "supplier_name": "Indian Oil Corp (Bulk)",
            "expected_date": (TODAY + timedelta(days=7)).isoformat(),
            "notes": f"Monthly diesel order — {DEMO_TAG}",
            "items": [{"item_id": diesel["id"], "quantity_ordered": "2000", "unit_price": "92.50"}],
        }, "PO: Indian Oil (pending)")

    # PO 2: approved + fully received
    spares = [items.get("Jaw Plate (Fixed)"), items.get("Jaw Plate (Swing)"), items.get("Bearing 22228 CC/W33")]
    spares = [s for s in spares if s]
    if spares:
        po = c.post("/api/v1/inventory/purchase-orders", {
            "supplier_name": "Sandhu Crusher Spares",
            "expected_date": (TODAY - timedelta(days=10)).isoformat(),
            "notes": f"Quarterly spares — {DEMO_TAG}",
            "items": [
                {"item_id": spares[0]["id"], "quantity_ordered": "2", "unit_price": "18500.00"},
                {"item_id": spares[1]["id"], "quantity_ordered": "2", "unit_price": "19200.00"},
                *([{"item_id": spares[2]["id"], "quantity_ordered": "4", "unit_price": "4500.00"}] if len(spares) > 2 else []),
            ],
        }, "PO: Sandhu Crusher Spares")
        po_id = po["id"]
        if c.apply:
            c.post(f"/api/v1/inventory/purchase-orders/{po_id}/approve", {}, "approve")
            # Receive everything
            full = c.get(f"/api/v1/inventory/purchase-orders/{po_id}")
            c.post(f"/api/v1/inventory/purchase-orders/{po_id}/receive", {
                "items": [{"po_item_id": ln["id"], "quantity_received": ln["quantity_ordered"]} for ln in full["items"]],
            }, "receive (full)")
        else:
            log.info("[DRY] would approve + receive PO (Sandhu)")

    # PO 3: approved + partially received
    hyd = items.get("Hydraulic Oil 68")
    if hyd:
        po3 = c.post("/api/v1/inventory/purchase-orders", {
            "supplier_name": "Mahalaxmi Hydraulics",
            "expected_date": (TODAY + timedelta(days=3)).isoformat(),
            "notes": f"Hydraulic oil top-up — {DEMO_TAG}",
            "items": [{"item_id": hyd["id"], "quantity_ordered": "200", "unit_price": "210.00"}],
        }, "PO: Mahalaxmi (partial)")
        if c.apply:
            c.post(f"/api/v1/inventory/purchase-orders/{po3['id']}/approve", {}, "approve")
            full3 = c.get(f"/api/v1/inventory/purchase-orders/{po3['id']}")
            c.post(f"/api/v1/inventory/purchase-orders/{po3['id']}/receive", {
                "items": [{"po_item_id": full3["items"][0]["id"], "quantity_received": "120"}],
            }, "receive (partial 120/200)")
        else:
            log.info("[DRY] would approve + partial-receive PO (Mahalaxmi)")


# ── Invoice helpers ─────────────────────────────────────────────────────────

def _is_intrastate(party: dict) -> bool:
    """Company is in Haryana (state_code 06). Intrastate = party in 06 too."""
    return (party.get("billing_state_code") == "06")


def _gst_rate(p_def: dict) -> Decimal:
    return Decimal(str(p_def.get("gst_rate", "5.00")))


def _build_invoice_items(products: dict[str, dict], n: int = None) -> tuple[list[dict], Decimal]:
    """Choose n random products, return invoice items + estimated taxable amount."""
    n = n or random.randint(1, 3)
    chosen_names = random.sample(list(products.keys()), k=min(n, len(products)))
    items, total = [], Decimal("0")
    for i, name in enumerate(chosen_names):
        p = products[name]
        qty = Decimal(str(round(random.uniform(8, 35), 2)))     # 8-35 MT load
        rate = Decimal(str(p.get("default_rate", "500")))
        items.append({
            "product_id": p["id"],
            "description": p["name"],
            "hsn_code": p.get("hsn_code", "2517"),
            "quantity": str(qty),
            "unit": p.get("unit", "MT"),
            "rate": str(rate),
            "gst_rate": str(p.get("gst_rate", "5.00")),
            "sort_order": i,
        })
        total += qty * rate
    return items, total


def seed_quotations(c: Client, parties: dict[str, dict], products: dict[str, dict]) -> list[dict]:
    log.info("─── Quotations ───")
    customers = [p for p in parties.values() if p.get("party_type") in ("customer", "both") and p.get("gstin")]
    if not customers or not products:
        return []

    quotations: list[dict] = []
    samples = random.sample(customers, k=min(5, len(customers)))
    for i, party in enumerate(samples):
        qd = TODAY - timedelta(days=random.randint(5, 80))
        items, _ = _build_invoice_items(products, n=random.randint(2, 4))
        payload = {
            "quotation_date": qd.isoformat(),
            "valid_to": (qd + timedelta(days=30)).isoformat(),
            "party_id": party["id"],
            "tax_type": "gst",
            "discount_type": "percentage" if i == 0 else None,
            "discount_value": "2.50" if i == 0 else "0",
            "notes": f"As discussed; ex-plant pricing — {DEMO_TAG}",
            "terms_and_conditions": "1. Rates valid 30 days. 2. Payment 30 days. 3. Loading at our plant. 4. GST extra as applicable.",
            "items": items,
        }
        q = c.post("/api/v1/quotations/", payload, f"Q→{party['name'][:30]}")
        quotations.append(q)

    if not c.apply:
        return quotations

    # Workflow: 3 sent, 2 converted to invoice, 1 left as draft
    for q in quotations[:3]:
        try:
            c.post(f"/api/v1/quotations/{q['id']}/send", {}, f"send {q.get('quotation_no', q['id'])}")
        except Exception as e:
            log.warning("send quotation failed: %s", e)
    for q in quotations[:2]:
        try:
            c.post(f"/api/v1/quotations/{q['id']}/convert", {}, f"convert {q.get('quotation_no', q['id'])}")
        except Exception as e:
            log.warning("convert quotation failed: %s", e)
    return quotations


def seed_invoices(c: Client, parties: dict[str, dict], products: dict[str, dict], vehicles: dict[str, dict]) -> None:
    log.info("─── Invoices (sales + purchase) ───")
    if not parties or not products:
        log.warning("no parties or products — skipping invoices")
        return

    customers = [p for p in parties.values() if p.get("party_type") in ("customer", "both")]
    suppliers = [p for p in parties.values() if p.get("party_type") in ("supplier", "both")]
    veh_list = list(vehicles.values())

    # Sales invoices: ~60% spread across Oct 2025 - Apr 2026, ~40% in last 30 days
    # so the dashboard's 30-day daily trend has visible activity.
    sales_target = 30
    fy_start = date(2025, 10, 1)
    fy_to_30days_ago = (TODAY - timedelta(days=31) - fy_start).days
    for i in range(sales_target):
        party = random.choice(customers)
        if random.random() < 0.4:
            # Within last 30 days
            d = TODAY - timedelta(days=random.randint(1, 29))
        else:
            # Earlier in FY (Oct 2025 → 31 days ago)
            d = fy_start + timedelta(days=random.randint(0, max(fy_to_30days_ago, 1)))
        items, _ = _build_invoice_items(products, n=random.randint(1, 3))
        veh = random.choice(veh_list) if veh_list else None
        gross = Decimal(str(round(random.uniform(20000, 32000), 0)))
        tare = Decimal(str(veh["default_tare_weight"])) if veh else Decimal("10000")
        net = gross - tare

        payload = {
            "invoice_type": "sale",
            "tax_type": "non_gst" if not party.get("gstin") else "gst",
            "invoice_date": d.isoformat(),
            "party_id": party["id"],
            "customer_name": None if party.get("gstin") else party["name"],
            "vehicle_no": veh["registration_no"] if veh else None,
            "transporter_name": random.choice([None, "Yadav Transport Co", "Shree Balaji Logistics"]),
            "driver_name": random.choice([d["name"] for d in DRIVERS]),
            "gross_weight": str(gross), "tare_weight": str(tare), "net_weight": str(net),
            "discount_type": "percentage" if i % 8 == 0 else None,
            "discount_value": "1.00" if i % 8 == 0 else "0",
            "freight": str(random.choice([0, 0, 0, 500, 1200])),
            "payment_mode": random.choice(["cash", "upi", "bank", "credit"]),
            "destination": party.get("billing_city"),
            "notes": f"{DEMO_TAG}",
            "items": items,
        }
        try:
            inv = c.post("/api/v1/invoices/", payload, f"S-{i+1:02d} → {party['name'][:25]}")
        except Exception as e:
            log.warning("invoice create failed: %s", e)
            continue
        # Finalise ~80% of them
        if c.apply and random.random() < 0.8:
            try:
                c.post(f"/api/v1/invoices/{inv['id']}/finalise", {}, "finalise")
            except Exception as e:
                log.warning("finalise failed: %s", e)

    # Purchase invoices: 6
    if suppliers:
        for i in range(6):
            sup = random.choice(suppliers)
            d = fy_start + timedelta(days=random.randint(10, max(fy_to_30days_ago, 11)))
            items, _ = _build_invoice_items(products, n=1)
            payload = {
                "invoice_type": "purchase",
                "tax_type": "gst",
                "invoice_date": d.isoformat(),
                "party_id": sup["id"],
                "vehicle_no": random.choice(veh_list)["registration_no"] if veh_list else None,
                "supplier_ref": f"BILL/{sup['name'][:3].upper()}/{1000+i}",
                "payment_mode": random.choice(["bank", "credit"]),
                "notes": f"Purchase from {sup['name']} — {DEMO_TAG}",
                "items": items,
            }
            try:
                inv = c.post("/api/v1/invoices/", payload, f"P-{i+1:02d} ← {sup['name'][:25]}")
                if c.apply and random.random() < 0.7:
                    c.post(f"/api/v1/invoices/{inv['id']}/finalise", {}, "finalise")
            except Exception as e:
                log.warning("purchase invoice failed: %s", e)


# ─── Tokens (for dashboard: today's count/tonnage + 30-day trend + product chart) ──

def _choose_vehicle(vehicles: dict[str, dict]) -> dict | None:
    """Pick a vehicle dict with id, registration_no, default_tare_weight."""
    if not vehicles:
        return None
    return random.choice(list(vehicles.values()))


def _completed_token(c: Client, party: dict, product: dict, vehicle: dict | None,
                     token_date: date, label: str) -> dict | None:
    """Create + first-weight + second-weight a token. Returns the completed token (with linked_invoice)."""
    create_payload = {
        "token_date": token_date.isoformat(),
        "direction": "outbound",
        "token_type": "sale",
        "party_id": party["id"],
        "product_id": product["id"],
        "vehicle_no": vehicle["registration_no"] if vehicle else "HR55AB1234",
        "vehicle_id": vehicle["id"] if vehicle else None,
        "vehicle_type": vehicle.get("vehicle_type") if vehicle else "truck",
        "remarks": f"{DEMO_TAG}",
    }
    try:
        tok = c.post("/api/v1/tokens", create_payload, label)
    except Exception as e:
        log.warning("token create failed: %s", e)
        return None
    if not c.apply:
        return tok
    tare = Decimal(str(vehicle.get("default_tare_weight", 12000))) if vehicle else Decimal("12000")
    gross = tare + Decimal(str(random.randint(15000, 26000)))  # 15-26 tonnes net
    # Outbound (sale): truck enters empty (first=tare) → loads → exits heavy (second=gross)
    try:
        c.post(f"/api/v1/tokens/{tok['id']}/first-weight",
               {"weight_kg": str(tare), "is_manual": True}, "first-weight")
        c.post(f"/api/v1/tokens/{tok['id']}/second-weight",
               {"weight_kg": str(gross), "is_manual": True}, "second-weight")
        # Re-fetch to get linked_invoice
        full = c.get(f"/api/v1/tokens/{tok['id']}")
        return full
    except Exception as e:
        log.warning("token weighment failed: %s", e)
        return tok


def seed_tokens(c: Client,
                parties: dict[str, dict],
                products: dict[str, dict],
                vehicles: dict[str, dict]) -> list[dict]:
    """Seed tokens such that the dashboard populates richly.

    - 12 tokens dated TODAY: 8 completed, 3 in-progress (first weight only), 1 cancelled
    - 24 tokens spread across last 30 days, all COMPLETED — drives daily trend + product chart
    """
    log.info("─── Tokens (today + recent 30 days) ───")
    customers = [p for p in parties.values() if p.get("party_type") in ("customer", "both")]
    if not customers or not products:
        log.warning("no parties/products — skipping tokens")
        return []

    veh_list = list(vehicles.values())
    completed_tokens: list[dict] = []

    # ── (A) Today's tokens — completed ──
    for i in range(8):
        party = random.choice(customers)
        product = random.choice(list(products.values()))
        vehicle = _choose_vehicle(vehicles)
        tok = _completed_token(c, party, product, vehicle, TODAY,
                               f"T-today-{i+1}/8 → {party['name'][:20]} / {product['name'][:18]}")
        if tok:
            completed_tokens.append(tok)

    # ── (B) Today's tokens — in-progress (first weight only) ──
    for i in range(3):
        party = random.choice(customers)
        product = random.choice(list(products.values()))
        vehicle = _choose_vehicle(vehicles)
        payload = {
            "token_date": TODAY.isoformat(),
            "direction": "outbound",
            "token_type": "sale",
            "party_id": party["id"],
            "product_id": product["id"],
            "vehicle_no": vehicle["registration_no"] if vehicle else "HR55AB1234",
            "vehicle_id": vehicle["id"] if vehicle else None,
            "vehicle_type": vehicle.get("vehicle_type") if vehicle else "truck",
            "remarks": f"In progress — awaiting load — {DEMO_TAG}",
        }
        try:
            tok = c.post("/api/v1/tokens", payload, f"T-inprog-{i+1}/3")
            if c.apply:
                tare = Decimal(str(vehicle.get("default_tare_weight", 12000))) if vehicle else Decimal("12000")
                c.post(f"/api/v1/tokens/{tok['id']}/first-weight",
                       {"weight_kg": str(tare), "is_manual": True}, "first-weight only")
        except Exception as e:
            log.warning("in-progress token failed: %s", e)

    # ── (C) Today — 1 cancelled ──
    try:
        party = random.choice(customers)
        product = random.choice(list(products.values()))
        vehicle = _choose_vehicle(vehicles)
        payload = {
            "token_date": TODAY.isoformat(),
            "direction": "outbound",
            "token_type": "sale",
            "party_id": party["id"],
            "product_id": product["id"],
            "vehicle_no": vehicle["registration_no"] if vehicle else "HR55AB1234",
            "vehicle_id": vehicle["id"] if vehicle else None,
            "vehicle_type": vehicle.get("vehicle_type") if vehicle else "truck",
            "remarks": f"Cancelled by operator — {DEMO_TAG}",
        }
        tok = c.post("/api/v1/tokens", payload, "T-cancel")
        if c.apply:
            c.post(f"/api/v1/tokens/{tok['id']}/cancel", {}, "cancel")
    except Exception as e:
        log.warning("cancelled token failed: %s", e)

    # ── (D) Last 30 days — completed tokens (drives daily trend + product chart) ──
    for i in range(24):
        days_back = random.randint(1, 29)  # 1..29 days ago — exclude today (handled above)
        tdate = TODAY - timedelta(days=days_back)
        party = random.choice(customers)
        product = random.choice(list(products.values()))
        vehicle = _choose_vehicle(vehicles)
        tok = _completed_token(c, party, product, vehicle, tdate,
                               f"T-D-{days_back:02d}days → {party['name'][:18]}")
        if tok:
            completed_tokens.append(tok)

    # ── (E) Volume tokens (skip-bridge) — verifies operator's volume flow ──
    # Pick products that have a bulk_density set so the math is meaningful.
    volume_products = [p for p in products.values() if p.get("bulk_density")]
    if not volume_products:
        # Fall back: any product (server will reject if no bulk_density — that's OK for demo logs)
        volume_products = list(products.values())
    tyre_options = [(4, 3.0), (6, 7.0), (8, 10.0), (10, 13.0), (12, 17.0)]
    for i in range(5):
        days_back = random.randint(0, 14)
        tdate = TODAY - timedelta(days=days_back)
        party = random.choice(customers)
        product = random.choice(volume_products)
        vehicle = _choose_vehicle(vehicles)
        tyre_count, default_m3 = random.choice(tyre_options)
        # Slight randomness around the standard volume
        volume = round(default_m3 * (0.9 + random.random() * 0.2), 2)
        payload = {
            "token_date": tdate.isoformat(),
            "direction": "outbound",
            "token_type": "sale",
            "party_id": party["id"],
            "product_id": product["id"],
            "vehicle_no": vehicle["registration_no"] if vehicle else "HR99VL9999",
            "vehicle_id": vehicle["id"] if vehicle else None,
            "vehicle_type": vehicle.get("vehicle_type") if vehicle else "truck",
            "tyre_count": tyre_count,
            "volume_m3": str(volume),
            "remarks": f"Volume token ({tyre_count}-tyre, {volume} m³) — {DEMO_TAG}",
        }
        try:
            tok = c.post("/api/v1/tokens/volume", payload,
                         f"T-vol-{i+1}/5 → {party['name'][:18]} / {product['name'][:14]} / {volume} m³")
            if tok:
                completed_tokens.append(tok)
        except Exception as e:
            log.warning("volume token failed: %s", e)

    return completed_tokens


# ─── Payments (drives outstanding, payment_pipeline chart) ────────────────────

def seed_payments(c: Client, parties: dict[str, dict]) -> None:
    """Create receipts allocated against finalised sales invoices.

    Targets ~60% of finalised invoices: ~50% fully paid, ~10% partial.
    """
    log.info("─── Payments (receipts against finalised invoices) ───")
    # Pull finalised sales invoices (paged)
    inv_resp = c.get("/api/v1/invoices/",
                     params={"invoice_type": "sale", "status": "final", "page_size": 100})
    invoices = inv_resp.get("items", []) if isinstance(inv_resp, dict) else []
    if not invoices:
        log.warning("no finalised sales invoices found — skipping payments")
        return

    party_index = {p["id"]: p for p in parties.values()}
    paid_count = 0
    partial_count = 0

    for inv in invoices:
        party_obj = inv.get("party") or {}
        party_id = party_obj.get("id") or inv.get("party_id")
        if not party_id:
            continue
        grand = Decimal(str(inv.get("grand_total") or "0"))
        already_paid = Decimal(str(inv.get("amount_paid") or "0"))
        balance = grand - already_paid
        if balance <= 0:
            continue
        # 60% chance of getting a receipt
        roll = random.random()
        if roll > 0.60:
            continue
        full_pay = roll < 0.50  # 50% full, 10% partial
        amount = balance if full_pay else (balance * Decimal("0.4")).quantize(Decimal("0.01"))
        if amount <= 0:
            continue

        inv_date = inv.get("invoice_date")
        # Receipt some days after the invoice (1..30), bounded by today
        try:
            base = date.fromisoformat(inv_date) if isinstance(inv_date, str) else TODAY
        except Exception:
            base = TODAY
        rdate = min(TODAY, base + timedelta(days=random.randint(1, 30)))

        payload = {
            "receipt_date": rdate.isoformat(),
            "party_id": party_id,
            "amount": str(amount),
            "payment_mode": random.choice(["upi", "bank_transfer", "cash", "cheque"]),
            "reference_no": f"REF-{random.randint(100000, 999999)}",
            "bank_name": random.choice(["HDFC", "SBI", "ICICI", "Axis"]),
            "notes": f"Payment against {inv.get('invoice_no')} — {DEMO_TAG}",
            "allocations": [{"invoice_id": inv["id"], "amount": str(amount)}],
        }
        try:
            c.post("/api/v1/payments/receipts", payload,
                   f"recv {amount} ← {party_obj.get('name', '?')[:20]} ({'full' if full_pay else 'partial'})")
            if full_pay:
                paid_count += 1
            else:
                partial_count += 1
        except Exception as e:
            log.warning("receipt failed: %s", e)

    log.info("payments: %d full, %d partial", paid_count, partial_count)


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--base-url", required=True,
                    help="e.g. https://manhotra-consulting.weighbridgesetu.com")
    ap.add_argument("--username", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--apply", action="store_true",
                    help="Actually write to the API. Without this flag, only prints planned calls.")
    args = ap.parse_args()

    base = args.base_url.rstrip("/")
    c = Client(base_url=base, apply=args.apply)
    c.login(args.username, args.password)

    log.info("Mode: %s", "APPLY (writes)" if args.apply else "DRY-RUN (no writes)")
    log.info("Target: %s", base)

    seed_company(c)
    seed_financial_year(c)
    cats = seed_categories(c)
    prods = seed_products(c, cats)
    parties = seed_parties(c)
    vehicles = seed_vehicles(c)
    seed_drivers(c)
    seed_transporters(c)
    seed_compliance(c)
    items = seed_inventory(c)
    seed_inventory_movements(c, items)
    seed_purchase_orders(c, items)
    seed_quotations(c, parties, prods)
    seed_invoices(c, parties, prods, vehicles)
    # Tokens AFTER invoices so master data is fully in place. Some tokens
    # auto-create draft invoices via the second-weight workflow — those
    # additional invoices are intentional and feed today's revenue card.
    seed_tokens(c, parties, prods, vehicles)
    # Finalise any draft invoices the tokens just created (so they count
    # toward revenue_today / payment_pipeline / outstanding).
    if c.apply:
        try:
            drafts = c.get("/api/v1/invoices/",
                           params={"invoice_type": "sale", "status": "draft", "page_size": 100})
            for inv in drafts.get("items", []):
                try:
                    c.post(f"/api/v1/invoices/{inv['id']}/finalise", {}, f"finalise draft {inv['id'][:8]}")
                except Exception as e:
                    log.warning("post-token finalise failed: %s", e)
        except Exception as e:
            log.warning("fetch drafts failed: %s", e)
    # Payments must run LAST so all finalised invoices exist.
    seed_payments(c, parties)

    log.info("─" * 60)
    log.info("Done. Created=%d  Skipped=%d  Errors=%d",
             c.counts["created"], c.counts["skipped"], c.counts["errors"])
    if not args.apply:
        log.info("DRY-RUN only. Re-run with --apply to actually write.")


if __name__ == "__main__":
    main()
