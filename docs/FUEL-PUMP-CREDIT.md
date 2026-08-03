# Fuel at Petrol Pumps — Credit POs & Outstanding (End-to-End Workflow)

## The business scenario

Most vehicles are fuelled at an **outside petrol pump / gas station**, almost always
**on credit** (the pump bills the company periodically). The owner needs to know, at
any moment, **how much is owed to each petrol pump**, and settle those dues.

This feature makes that automatic: **every credit fill at a pump auto-creates a
Purchase Order (PO) against that pump**, and a dedicated report shows the outstanding
per pump. It deliberately does **not** touch inventory (the diesel goes straight into
the truck, not into a store tank).

---

## The end-to-end flow

```
 Operator records a fuel fill              Owner / accountant
 (Fuel & Mileage → Fuel Log)               (Fuel & Mileage → Pump Credit)
 ─────────────────────────────             ─────────────────────────────────────
  Source = "Outside pump"                   ┌────────────────────────────────┐
  Station = "HP Petrol Pump - NH48"         │  Outstanding by petrol pump     │
  On credit ✔  Litres 40  Rate ₹95          │  HP Petrol Pump   ₹3,800  [Pay] │
        │                                    │  Bharat Ring Rd   ₹2,850  [Pay] │
        ▼                                    └────────────────────────────────┘
  Fuel entry saved (₹3,800)                            │  click "Pay"
        │  (auto)                                       ▼
        ▼                                    Record payment ₹5,000 (bank)
  PO  FPO/26-27/0001  created                          │  (auto, FIFO)
  against "HP Petrol Pump - NH48"                       ▼
  status = UNPAID   (no stock movement)      Oldest POs settled first:
                                              FPO/0001 → PAID, FPO/0002 → PARTIAL
```

### 1. Record the fill (operator)
`Fuel & Mileage → Fuel Log → Record Fill`
- **Source** = `Outside pump` (or `Other`). A pump panel appears.
- **Petrol pump / station** — type the pump name (autocompletes from pumps used before).
- **On credit** ✔ (default) — "auto-create a PO to pay the pump later".
  Untick if it was **paid in cash at the pump** → no PO, nothing outstanding.
- Enter litres, rate, odometer as usual.

On save, if `Source = outside pump/other` **and** `On credit` **and** a station name is
given **and** amount > 0 → a **credit PO** is created automatically. The success banner
shows the PO number (e.g. *"Credit PO FPO/26-27/0001 created against HP Petrol Pump"*).

> **Plant-tank fills are unaffected** — they still issue diesel from store inventory and
> create **no** PO. Only outside-pump/other credit fills create a PO.

### 2. Track what's owed (owner / accountant)
`Fuel & Mileage → Pump Credit`
- **KPI cards:** Total outstanding · Pumps with dues · Billed on credit · Paid to pumps.
- **Outstanding by petrol pump** — one row per pump: Fills/POs · Billed · Paid ·
  **Outstanding** · Oldest due. A red **Pay** button appears while a pump has dues.
- **Purchase orders (per fill)** — every PO: no., date, pump, vehicle, litres, amount,
  paid, due, status (UNPAID / PARTIAL / PAID). CSV export on both tables.

### 3. Pay the pump
Click **Pay** on a pump row → enter amount, date, mode (cash/bank/UPI/cheque), reference.
The payment is **allocated oldest-PO-first (FIFO)** across that pump's open POs, updating
each PO's paid amount and status. Any surplus beyond the dues is recorded but left
unallocated (the pump then effectively holds a credit with you).

---

## What it does NOT do (by design)

| Concern | Behaviour |
|---|---|
| **Inventory** | A pump PO moves **no** store stock. Diesel bought at a pump goes straight into the truck. (Only `plant_tank` fills deduct from the store diesel item.) |
| **P&L double-count** | The fuel **expense** is already recognised in the P&L via the fuel entry (`vehicle_fuel_entries` → the *Fuel* line). The PO is a **balance-sheet payable to the pump**, not a second expense — so it is **not** re-booked into the P&L. |
| **Party master / main AP** | Pumps are tracked by **station name** in a dedicated fuel-credit ledger, kept separate from the customer/supplier party ledger. This isolation is what prevents the double-count above. |

---

## Data model

| Table | Purpose |
|---|---|
| `vehicle_fuel_entries.station_name` (new column) | The pump for an outside-pump fill. |
| `fuel_purchase_orders` | One credit PO per pump fill: `po_no` (FPO/YY-YY/NNNN), `station_name`, `fuel_entry_id`, `vehicle_id`, `po_date`, `litres`, `rate_per_litre`, `amount`, `amount_paid`, `status` (unpaid/partial/paid). |
| `fuel_po_payments` | Payments to a pump: `station_name`, `amount`, `payment_date`, `mode`, `reference`. Allocated FIFO across that pump's POs. |

PO numbers are gap-free per financial year via the shared `next_doc_no` allocator
(prefix `FPO`), the same mechanism as delivery challans / credit notes.

**Edits & deletes stay consistent:** editing a fill re-syncs its still-**unpaid** PO
(amount/litres/station); deleting a fill removes its PO **only if nothing was paid**
against it (a PO with payments is kept and unlinked, for the audit trail).

---

## API — all under `/api/v1/fuel`

| Method | Path | Description |
|---|---|---|
| POST | `/entries` | Record a fill. New body fields `station_name`, `on_credit`. Auto-creates the PO for a credit pump fill. Response carries `station_name` + `po_no`. |
| GET | `/pump-outstanding` | **The outstanding report** — per-pump billed/paid/outstanding + totals. Filters: `date_from`, `date_to`. |
| GET | `/pump-pos` | List every pump PO. Filters: `station`, `status`, `date_from`, `date_to`. |
| GET | `/pump-payments` | List payments made to pumps. Filter: `station`. |
| POST | `/pump-payments` | Record a payment to a pump (`station_name`, `amount`, `payment_date`, `mode`, `reference`) → FIFO-allocated. Returns `allocated` / `unallocated`. |

Everything lives inside the existing **`fuel` feature module** (RBAC + module gating
already wired) — no new module or permission to configure.

---

## Verified

Real-DB end-to-end (via the actual router code): two credit fills at one pump →
`FPO/26-27/0001` + `0002` (₹3,800 + ₹2,850); a plant-tank fill created **no** PO;
outstanding = ₹6,650; a ₹5,000 payment allocated FIFO → oldest PO **PAID**, next
**PARTIAL**, remaining due ₹1,650.

## Possible follow-ups (not in v1)

- Surface pump payments in the **Day Book / cash-book** money-out (today they live only
  in the dedicated fuel-credit ledger to avoid P&L entanglement).
- Optionally link a pump to a **supplier party** for a unified vendor view.
- A **Telegram alert** when a pump's outstanding crosses a threshold.
