# Megna Trading — Maize Weighbridge + Inventory + Tally
## Fit–Gap Report (against the existing WeighBridge Setu data model)

**Scope:** Map the 9-module maize-trading requirement onto the **existing** data model (no new models), seed production-grade demo data into `megna-trading.weighbridgesetu.com`, and flag what's missing.

**Legend:** ✅ Supported as-is · 🟡 Partial / workaround (no schema change) · ❌ Gap (needs a small enhancement)

**Headline:** **~80% supported today.** The whole operational spine — farmer → weighment → auto purchase bill → godown stock → Tally purchase voucher → reports — already works. The gaps are mostly **two-way Tally sync** (pull payments + voucher no. + stock compare), **per-godown stock split**, and a few **structured fields** (moisture/quality/bank).

---

## 1 · Farmer Master  →  `parties` (party_type = `supplier`)

| Requirement | Status | Maps to / Note |
|---|---|---|
| Farmer name, mobile, vehicle | ✅ | `parties.name`, `phone`; vehicles via `vehicles` master + linked on each weighment |
| Tally ledger mapping | ✅ | `parties.tally_ledger_name` |
| Connect farmer ↔ Tally ledger | ✅ | Used by the Tally purchase voucher (farmer = Sundry Creditor) |
| Search by name / mobile | ✅ | Parties search |
| Show previous history; pending weighments on select | ✅ / 🟡 | Customer/Supplier **360** page shows full history (purchases, payments, balance). Pending (OPEN) weighments are listed on the Trips/Token page filtered by farmer — 🟡 not yet auto-popped inside the 360 view |
| Avoid duplicate farmer | ✅ | Seeder is idempotent; UI warns on duplicate name |
| **Farmer ID (auto, human-readable)** | 🟡 | Each farmer has a unique system ID (UUID), but there is **no short "FARM-001" code** field |
| **Village** (as its own field) + search by village | 🟡 | Stored in `billing_city`; works for display/filter but it's not a dedicated "village" field and village isn't a search key |
| **Bank details** (A/c, IFSC) | ❌ | `parties` has **no bank fields** (only the company record does). Needs 3 columns if farmer bank payout details must live in the software |

---

## 2 · Purchase Weighment  →  `tokens` (token_type = `purchase`, direction = `inbound`)

| Requirement | Status | Maps to / Note |
|---|---|---|
| Farmer, vehicle no., commodity | ✅ | `party_id`, `vehicle_no`/`vehicle_id`, `product_id` |
| Gross / tare / net (auto) | ✅ | Truck **LOADED first = gross**, **empty second = tare**, `net = gross − tare` (built-in purchase logic) |
| Date/time, slip number | ✅ | `token_date`, weigh timestamps, `token_no` + auto `gate_pass_no` (the printed slip) |
| **Purchase ready automatically after 2nd weight** | ✅ | On completion the system **auto-creates a draft purchase bill** — office only verifies + approves. No re-entry of weight/details |
| Office: search farmer → check → approve → print/bill | ✅ | Finalise the auto-draft → assigns bill no. → print |
| **Rate fixed** (per farmer/commodity) | 🟡 | Captured via `party_rates` (farmer×commodity rate) **and** echoed in the weighment remarks. There is no dedicated "rate" field **on the weighment row** itself |
| **Quality details** | 🟡 | Captured in `token.remarks` (free text). No structured "grade" field |
| **Moisture %** | 🟡 | Captured in `token.remarks`. No numeric moisture field (so it can't be reported/averaged) |
| **Godown location** | 🟡 | Captured in remarks + (optionally) the branch the token is created under. No first-class "godown" picker on the weighment |

---

## 3 · Godown Inventory  →  `product_stock` + `product_stock_movements`

| Requirement | Status | Maps to / Note |
|---|---|---|
| Opening + Purchase − Sales = Current | ✅ | `product_stock.current_stock`; opening via API; **purchase finalise auto-+, sale finalise auto-−** |
| Every purchase ↑ stock, every sale ↓ stock | ✅ | Automatic on invoice finalise (append-only movement log) |
| Total available stock, daily inward/outward, closing | ✅ | Product Inventory page + movements log (by day/type) |
| **Multiple godowns (Godown 1 / 2 / Outside) — stock split per godown** | ❌ | **Biggest gap.** `product_stock` keys on `product_id` **UNIQUE = one balance per commodity, company-wide**. Godowns exist as **branches** (we seed Main Godown / Godown 2 / Outside Storage as masters, and can tag movements), but the **live stock balance cannot currently be split per godown.** Per-branch stock was explicitly deferred in the platform |

> **Practical position for the demo:** total maize stock, daily in/out, and closing are all live and correct. "Godown-wise stock balance" is the one inventory sub-feature that needs the per-branch-stock enhancement.

---

## 4 · Tally Prime Integration  →  Tally module (auto-sync, just shipped)

| Requirement | Status | Maps to / Note |
|---|---|---|
| Auto-create **purchase voucher** on approval | ✅ | Finalising a GST purchase bill auto-pushes to Tally (background, non-blocking). Toggle: Settings → Tally → Auto-sync |
| Transfer farmer ledger, commodity, qty, rate, amount, vehicle, weighment no., date | ✅ | All carried in the purchase voucher: farmer = party ledger, commodity = stock item, qty/rate/amount on the inventory line, vehicle + weighment no. + date in the narration |
| Restrict which series sync | ✅ | Invoice-prefix filter (e.g. `PUR`) |
| **Quality details into Tally** | 🟡 | Only flows if put in remarks (→ narration). No structured field |
| **Tally voucher number comes back & is saved** | ❌ | We store **sync status + timestamp** (`tally_synced`, `tally_sync_at`), **not the Tally voucher number.** Tally's XML import reply doesn't reliably return it — needs a follow-up "read-back" call to fetch and store the voucher no. |

---

## 5 · Farmer Ledger Sync **from** Tally  (payments/balance shown in software)

| Requirement | Status | Note |
|---|---|---|
| Show total purchase qty + amount | ✅ | Supplier-360 (computed from weighbridge data) |
| Show **payments made + outstanding balance — sourced from Tally** | ❌ / 🟡 | The software shows **payments recorded in the weighbridge** (farmer payout vouchers) and computes the balance from them. It does **not pull payment/balance data back from Tally.** If all farmer payments are entered in the weighbridge too, the balance is correct there; true **"read payments from Tally"** is a **one-way → two-way sync** enhancement (Tally is currently write-only from our side) |

---

## 6 · Stock Reconciliation (Compare software vs Tally)

| Requirement | Status | Note |
|---|---|---|
| "Compare Stock" button, software vs Tally, show match/mismatch | ❌ | **Not implemented.** We have a GSTR-2B (ITC) reconciliation, but **not** a stock-quantity reconciliation that reads Tally's closing stock and diffs it against `product_stock`. Needs a Tally stock-summary read + a compare screen |

---

## 7 · Reports Dashboard

| Report | Status | Note |
|---|---|---|
| Daily Purchase (vehicles, qty, **avg buy rate**, value) | ✅ | Purchase register (date range, CSV). Avg rate = value ÷ qty |
| Sales (vehicles, qty, buyer) | ✅ | Sales register |
| Farmer report (history, total supplied, avg rate, payment status) | ✅ | Supplier-360 |
| **Vehicle report** (trips, total qty) | 🟡 | ANPR/Trips gives vehicle **movements**; a vehicle-wise **tonnage + value** analytics report is still pending |
| Stock report (godown-wise, balance) | ✅ / ❌ | Company-wide stock ✅; **godown-wise** ❌ (see §3) |

---

## 8 · Owner Mobile Dashboard

| Requirement | Status | Note |
|---|---|---|
| Phone access anytime | ✅ | Installable PWA, fully mobile-responsive |
| Today: purchase qty, sales qty, available stock, total vehicles, avg purchase rate, farmer payable | ✅ | Owner dashboard (exception-first) + KPIs |
| **Godown-wise stock** on the dashboard | ❌ | Same per-godown gap (§3) |

---

## 9 · Users & Permissions

| Role (requirement) | Maps to | Status |
|---|---|---|
| Weighbridge Operator (entry, weigh, print; no edit/delete) | role `operator` (kiosk) | ✅ page-level; 🟡 a hard **field-lock on "change weight"** is role/page-gated, not an individual-field lock |
| Office Staff (check, approve, send to Tally, print) | role `accountant` | ✅ |
| Owner (full + user control) | role `admin` | ✅ |

---

## Final flow — end-to-end check

```
Farmer entry ✅ → Auto weighment ✅ → Stock update ✅ → Office searches farmer ✅
→ Purchase verification ✅ → Send to Tally ✅ → Bill print ✅ → Reports & inventory updated ✅
```
**The entire operational flow is supported today.** Weighbridge is the system of record; Tally receives the accounting.

---

## Consolidated gap list (priority order)

| # | Gap | Severity | Needs schema change? | Recommendation |
|---|---|---|---|---|
| G1 | **Per-godown stock balance** (Godown 1/2/Outside) | **High** | Yes (per-branch `product_stock`) | Make stock key `(product_id, branch_id)`; rewrite stock get/create. Godown masters already exist as branches |
| G2 | **Tally voucher no. read-back** into software | Med | Small (1 column) | After push, do a Tally read to fetch + store the voucher number |
| G3 | **Pull farmer payments/balance from Tally** | Med-High | No (integration work) | Add a Tally "fetch ledger" call; or keep payments in weighbridge (already works) |
| G4 | **"Compare Stock" vs Tally** | Med | No (new report) | Read Tally stock summary, diff vs `product_stock`, show match/mismatch |
| G5 | **Structured moisture % + quality grade** on weighment | Med | Yes (2 columns on `tokens`) | Add `moisture_pct`, `quality_grade`; enables averages/reports (today: remarks) |
| G6 | **Farmer bank details** | Low-Med | Yes (3 columns on `parties`) | Add bank a/c, IFSC, holder if payouts run from software |
| G7 | **Vehicle-wise tonnage/value report** | Low | No (new report) | Aggregate tokens by vehicle |
| G8 | **Farmer code + Village field + village search** | Low | Small | Add `code` + `village`; or keep village in city |
| G9 | **Operator field-lock on weight edit** | Low | No (permission rule) | Tighten operator permission to block weight edits |

> Per your instruction, **no new models were created.** Items marked "needs schema change" are listed so you can decide which to add later; everything else works on the current model.

---

## What the seeder loads into `megna-trading`

`scripts/seed_maize_demo.py` (idempotent; dry-run by default) creates:

- **Company:** Megna Trading Company (Davangere, Karnataka, GST 29)
- **FY 2025-26** (active)
- **Godowns (branches):** Main Godown, Godown 2, Outside Storage
- **Commodities:** 11 products — 5 maize grades + jowar/bajra/wheat/soybean + broken maize + bran (HSN 1005/1007/1008/1001/1201/2302)
- **22 farmers** (suppliers, village in city, online-mode → Tally-syncable, Tally ledger name set)
- **6 buyers** (feed mills / starch / poultry — KA + interstate)
- **12 vehicles** (KA tractors + trucks) + 4 drivers
- **Party rates** for 6 farmers (rate-fixed demo)
- **Opening godown stock** for 4 maize products
- **~34 purchase weighments** (today + last 30 days; loaded-first/empty-second) → **auto purchase bills → finalised → godown stock up**
- **12 sales** to buyers → **godown stock down + receivables**
- **Payments:** farmer payout vouchers (~70%) + buyer receipts (~60%)

This populates: today's purchase/sales/stock cards, 30-day trends, farmer & buyer 360s, purchase/sales/stock registers, outstanding/payables, and (if Tally is configured) purchase vouchers.

### How to run

```bash
# 1) Dry-run first (writes nothing — review the planned calls):
python scripts/seed_maize_demo.py \
  --base-url https://megna-trading.weighbridgesetu.com \
  --username <admin-user> --password <admin-pass>

# 2) Apply for real:
python scripts/seed_maize_demo.py \
  --base-url https://megna-trading.weighbridgesetu.com \
  --username <admin-user> --password <admin-pass> --apply
```
