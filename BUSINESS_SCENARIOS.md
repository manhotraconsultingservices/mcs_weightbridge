# Business Scenarios — Weighbridge Invoice Software

> Stone crusher weighbridge management system for Indian SMEs.
> Handles the complete workflow from vehicle weighment through GST-compliant invoicing, payments, accounting integration, compliance, and administration.

---

## Quick Reference

| # | Business Area | Scenarios |
|---|---|---|
| 1 | [Weighbridge Operations](#1-weighbridge-operations) | Sale token, Purchase token, Cancel, Real-time scale |
| 2 | [Sales Invoicing](#2-sales-invoicing) | GST B2B, GST B2C, Non-GST, Edit, Cancel, Print |
| 3 | [Purchase Invoicing](#3-purchase-invoicing) | From token, Manual entry, Print |
| 4 | [Quotations](#4-quotations) | Create, Send, Convert to invoice, Cancel |
| 5 | [Payment Management](#5-payment-management) | Receipts, Vouchers, Partial pay, Outstanding aging |
| 6 | [Tally Prime Integration](#6-tally-prime-integration) | Single sync, Bulk multi-select, Ledger config, Bill aging |
| 7 | [GST Reports](#7-gst-reports) | GSTR-1 (CSV + JSON), GSTR-3B |
| 8 | [Business Reports](#8-business-reports) | Sales/Purchase register, Weight register, P&L, Stock |
| 9 | [Party & Product Master](#9-party--product-master) | Party CRUD, Rates, Vehicle, Driver, Transporter |
| 10 | [IP Camera Integration](#10-ip-camera-integration) | Auto-capture, Retry, Lightbox, Configure & test |
| 11 | [Private / Supplement System](#11-private--supplement-system) | USB-gated non-GST invoices, Move to supplement, Backup |
| 12 | [Compliance Management](#12-compliance-management) | Insurance, Certs, Licenses, Permits, Expiry alerts |
| 13 | [Notifications](#13-notifications) | Email, SMS, WhatsApp, Templates, Delivery log |
| 14 | [User Management & Access](#14-user-management--access-control) | Roles, Permissions, User CRUD |
| 15 | [Audit Trail](#15-audit-trail) | Action log, Filters, Stats |
| 16 | [Backup & Restore](#16-backup--restore) | pg_dump, Download, Restore |
| 17 | [Data Import](#17-data-import) | Parties, Products, Vehicles from Excel/CSV |
| 18 | [Dashboard](#18-dashboard) | Metrics, Top customers, Recent tokens, Compliance alerts |
| 19 | [Company Setup](#19-company--financial-year-setup) | Profile, Bank, FY, Numbering |

---

## 1. Weighbridge Operations

### 1.1 Sale Token — Two-Stage Weighment
**Who:** Weighbridge Operator
**Trigger:** Customer's loaded truck arrives at the weighbridge

| Step | Action | Detail |
|---|---|---|
| 1 | Operator creates Sale Token | Selects vehicle, customer party, product |
| 2 | Records **Gross Weight** (1st weighment) | Loaded truck weight captured from serial scale |
| 3 | Records **Tare Weight** (2nd weighment) | Empty truck after unloading |
| 4 | System calculates Net Weight | Net = Gross − Tare |
| 5 | Token → **COMPLETED** | Gap-free Token Number assigned |
| 6 | Draft Sales Invoice auto-created | Rate lookup: Party Rate → Product Default → 0 |
| 7 | Camera snapshots fired | Front View + Top View JPEG captured automatically (fire-and-forget) |

**Key rule:** Camera failure never blocks weight recording. Token completes regardless.

---

### 1.2 Purchase Token — Two-Stage Weighment
**Who:** Weighbridge Operator
**Trigger:** Supplier's empty truck arrives to load material

| Step | Action | Detail |
|---|---|---|
| 1 | Operator creates Purchase Token | Selects vehicle, supplier party, product |
| 2 | Records **Tare Weight** (1st weighment) | Empty truck before loading |
| 3 | Camera snapshots fired | Captured at 1st weighment (purchase-specific) |
| 4 | Material loaded onto truck | |
| 5 | Records **Gross Weight** (2nd weighment) | Loaded truck |
| 6 | Token → **COMPLETED** | Token Number assigned |
| 7 | Draft Purchase Invoice auto-created | Rate from party/product defaults |

---

### 1.3 Token Management
- **Cancel token** at any stage (before completion)
- **Search tokens** by vehicle number or party name (ILIKE)
- **Date range filter** on token list
- **Real-time weight** display via WebSocket from serial port scale (stability detection)
- **Supplement flag** marks tokens moved to the private encrypted system

---

## 2. Sales Invoicing

### 2.1 GST Sales Invoice — B2B (Registered Business)
**Who:** Admin / Accountant
**Trigger:** Draft invoice auto-created after sale token completion

| Step | Action | Detail |
|---|---|---|
| 1 | Admin reviews draft | Pre-populated from token: vehicle, party, net weight, rate |
| 2 | Edit invoice | Rate, discount (% or flat), freight, TCS rate, payment mode |
| 3 | **Finalise** | Gap-free invoice number assigned: `SAL/25-26/0001` |
| 4 | GST auto-determined | Same state code → CGST + SGST · Different state → IGST |
| 5 | Print or download PDF | A4 (PDF) or Thermal 80mm print via popup |
| 6 | Sync to Tally | Sends Sales Voucher with GST ledger entries |

---

### 2.2 GST Sales Invoice — B2C (Walk-in Customer)
- No GSTIN — customer name entered manually
- Treated as B2C in GSTR-1 (consolidated)
- Same finalise / PDF / Tally sync flow as B2B

---

### 2.3 Non-GST / Bill of Supply
- **USB key required** to create or view
- Excluded from all GST reports
- Can be moved to the Supplement (private) table

---

### 2.4 Edit Draft Invoice (Admin Only)
- Party, invoice date, tax type
- Line items (add/remove/edit), rates, discounts, freight, TCS
- Only draft invoices are editable; finalised invoices are locked

---

### 2.5 Invoice Cancellation
- Marks invoice as CANCELLED
- Cancellation allowed for both draft and final invoices

---

### 2.6 Print / PDF
- **A4 PDF:** Company header, GSTIN, line items, GST breakup, signature lines
- **Thermal 80mm:** Compact monospace format for receipt printer

---

## 3. Purchase Invoicing

### 3.1 Purchase Invoice from Token
- Auto-created after purchase token completion
- Supplier party, product, rate from defaults
- Finalise assigns: `PUR/25-26/0001`
- Payment via **Voucher** (outgoing payment to supplier)
- Sync to Tally: Purchase Voucher

### 3.2 Manual Purchase Invoice
- Created without a linked token (for direct material purchases)
- Same edit → finalise → pay → Tally flow

---

## 4. Quotations

### 4.1 End-to-End Quotation Flow

| Step | Action |
|---|---|
| 1 | Create Quotation with party + line items + rates |
| 2 | Download Quotation PDF to send to customer |
| 3 | Mark as **Sent** |
| 4 | Customer accepts → **Convert to Invoice** (preserves all items and rates) |
| 5 | Invoice created as draft → edit → finalise normally |
| 6 | OR: **Cancel** if not required |

---

## 5. Payment Management

### 5.1 Sales Payment Receipt
- Record payment received from a customer
- Modes: Cash · Cheque · UPI · Bank Transfer
- **Partial payment:** Multiple receipts against a single invoice
- Invoice status auto-updates: Unpaid → Partial → Paid
- Banknote button on invoice row for quick access

### 5.2 Purchase Payment Voucher
- Record payment made to a supplier
- Links to purchase invoice
- Tracks outstanding payables

### 5.3 Party Ledger
- Running balance with debit/credit per transaction
- Full history: invoices + receipts/vouchers

### 5.4 Outstanding Aging Analysis
- Party-wise outstanding balances
- Ageing buckets: Current · 1–30 days · 31–60 · 61–90 · 90+ days
- Due date from invoice feeds into Tally for bill-wise aging

---

## 6. Tally Prime Integration

### 6.1 Single Invoice Sync
- Click the sync icon on any **final** invoice row
- Pushes Sales or Purchase Voucher to TallyPrime via HTTP XML
- Icon shows current state:
  - 🟠 Orange arrow = never synced (needs sync)
  - 🟡 Amber refresh = modified after last sync (re-sync needed)
  - ✅ Green check = synced and up to date (button disabled)
- Spinner shown on the row while sync is in progress

### 6.2 Bulk Multi-Select Sync
- Checkboxes on all **final** invoice rows
- Select-all checkbox in header (indeterminate state when partial selection)
- **"Send to Tally (N)"** button appears in toolbar showing count
- Shows `(N pending)` when some selected are already up to date
- Sends invoices **sequentially** (Tally HTTP server is single-threaded)
- Per-failure error toast with invoice number
- Selection cleared on complete success

### 6.3 `tally_needs_sync` Logic
```
tally_needs_sync = TRUE  when:
  - Invoice never synced  (tally_synced = false)
  - Invoice updated after last sync (updated_at > tally_sync_at)

tally_needs_sync = FALSE when:
  - Synced and unchanged since last sync
```

### 6.4 Configurable Ledger Names
All 9 ledger names are configurable in Settings → Tally:

| Field | Default |
|---|---|
| Sales Ledger | Sales |
| Purchase Ledger | Purchase |
| CGST Ledger | CGST |
| SGST Ledger | SGST |
| IGST Ledger | IGST |
| Freight Ledger | Freight Outward |
| Discount Ledger | Trade Discount |
| TCS Ledger | TCS Payable |
| Round-off Ledger | Round Off |

### 6.5 Rich Voucher Narration
Narration example: `Sales INV/25-26/0047 | Token #4872 | Vehicle: MH12AB1234 | Net Wt: 15.760 MT`
Each component (Vehicle / Token / Weight) independently toggleable in Settings.

### 6.6 Bill-wise Aging in Tally
- `BILLALLOCATIONS.LIST` added to party ledger entry
- Credit period = `due_date − invoice_date` OR party `payment_terms_days`
- Enables Tally's **Outstanding Reports** and **Ageing Analysis**

### 6.7 GST Compliance Tags
- Buyer GSTIN + GST Registration Type on party entry
- Place of Supply (state name) on voucher
- GST Rate % on each inventory entry → feeds GSTR-1 HSN summary in Tally

### 6.8 Per-Party Tally Ledger Name Override
- Each party can have a custom `Tally Ledger Name`
- Example: party name "Raj Enterprises" → Tally ledger "RAJ ENTERPRISES LTD"
- Falls back to party name if not set

### Tally Setup Requirements (one-time)
1. TallyPrime → F12 → Connectivity → Enable **TallyPrime Server** → Port **9002**
2. Company must be open in Tally; name must match Settings exactly
3. All 9 ledgers must pre-exist in Tally under the correct groups
4. Party ledgers must pre-exist (Sundry Debtors / Sundry Creditors)
5. Stock items auto-created by Tally on first import

### Expected Sync Timing
| Scenario | Approx. Time |
|---|---|
| Single invoice (local) | 200–500 ms |
| Single invoice (LAN) | 300 ms – 1.5 sec |
| Bulk 10 invoices | 2–8 sec |
| Bulk 50 invoices | 10–40 sec |

---

## 7. GST Reports

### 7.1 GSTR-1
- **B2B invoices:** Invoice-wise detail with party GSTIN, place of supply, tax breakup
- **B2C aggregate:** Consolidated by state, rate
- **HSN summary:** Quantity, taxable value, IGST/CGST/SGST per HSN code
- Export: **CSV** or **GSTN portal JSON** (ready to upload on GST portal)
- Filters: Month, Financial Year

### 7.2 GSTR-3B
- **Section 3.1a:** Total outward taxable supplies (excluding zero-rated)
- **Section 3.1e:** Zero-rated supplies
- **Section 4A5:** Eligible ITC from purchase invoices
- **Net tax payable:** IGST · CGST · SGST

---

## 8. Business Reports

### 8.1 Sales / Purchase Register
- Date range + party filter
- Columns: Invoice No, Date, Party, Vehicle, Net Wt, Taxable, CGST, SGST, IGST, Total
- **CSV export**

### 8.2 Weight Register
- Token-wise: vehicle, party, product, gross/tare/net weights, in/out times
- Filters: Date range, type (sale/purchase)
- **CSV export**

### 8.3 Profit & Loss (Monthly)
- Revenue (sales) vs COGS (purchases) month by month
- Gross profit and gross margin %
- Default: current financial year

### 8.4 Stock Summary
- Product-wise: Qty Purchased · Qty Sold · Closing Stock · Closing Value
- **CSV export**

---

## 9. Party & Product Master

### 9.1 Party Management
- Types: Customer · Supplier · Both
- GSTIN (auto-detects state code), PAN, billing address
- Credit limit, payment terms (days), opening balance
- **Custom product rates** per party (rate sheet)
- **Tally Ledger Name** override for Tally integration
- Outstanding balance tracked in real time

### 9.2 Product Management
- Product categories (grouping)
- HSN code, GST rate, default rate, unit of measure
- Active/inactive flag

### 9.3 Vehicle Management
- Registration number, tare weight, owner
- **Tare weight history** recorded on every weighment
- Default tare weight for quick token creation

### 9.4 Driver & Transporter
- Driver master: name, license, phone
- Transporter master: name, GSTIN

---

## 10. IP Camera Integration

### 10.1 Automatic Snapshot on Weighment
- **2 cameras:** Front View + Top View
- **Sale tokens:** Captured at **2nd weighment** (tare)
- **Purchase tokens:** Captured at **1st weighment** (tare)
- Protocol: HTTP GET to snapshot URL (STQC/Hikvision/Dahua compatible)
- HTTP Basic Auth supported

### 10.2 Reliability Design
- `BackgroundTasks` — weight recording never waits for camera
- **3 retries × 5s timeout** per camera
- PIL image validation before saving (rejects corrupt responses)
- Per-camera status tracked: `pending → captured / failed`
- Admin can **retry failed captures** via API

### 10.3 Frontend UX
- Capturing spinner in WeightCaptureDialog after weighment
- Per-camera status rows: Waiting… → ✓ Captured / ✗ Failed
- Thumbnail grid shown once images are ready
- **Camera icon** (🎥) on completed token rows → opens lightbox
- Full-size image in new tab on click

### 10.4 Admin Configure & Test
- Settings → Cameras tab
- Configure URL, username, password for Front and Top cameras
- **Live test button** captures a snapshot and shows preview inline
- Passwords stored masked (send `"***"` to preserve existing)

---

## 11. Private / Supplement System (USB-Gated)

### 11.1 Non-GST Private Invoice
- Accessible only with a **registered USB key**
- Stored in a **separate encrypted table** (`supplementary_entries`)
- Encryption: AES-256-GCM (all sensitive fields)
- Gap-free invoice numbering: `SE/00001` via PostgreSQL sequence
- Never appears in any GST report

### 11.2 Move Normal Invoice to Supplement
- Admin moves a **draft** invoice to the Supplement system (USB required)
- Original invoice + token data migrated to encrypted table
- Record deleted from normal invoice table
- Token's invoice link updated automatically

### 11.3 USB Guard System
| Method | How it works |
|---|---|
| Server USB | `.weighbridge_key` UUID file on USB drive inserted in server |
| Client USB | User selects `.weighbridge_key` file via browser file picker (any LAN machine) |
| Recovery PIN | Admin pre-creates time-limited PIN; user enters it on lock screen |

### 11.4 Hourly Auto-Backup to USB
- After Client USB auth, user selects a USB directory via File System Access API
- System writes AES-256-GCM encrypted backup of all supplement data hourly

### 11.5 Private Admin Console (`/priv-admin`)
- Role: `private_admin` only (no USB needed)
- Full audit view of all supplement entries
- CSV export of all private invoice data

---

## 12. Compliance Management

### 12.1 Document Tracking
- **Types:** Insurance · Certification · License · Permit
- Fields: Issuer, Reference No, Issue Date, Expiry Date, File Upload, Notes

### 12.2 Expiry Alerts
- Alert levels auto-computed from expiry date:
  - ✅ **OK** — not expiring soon
  - 🟡 **Warning** — expiring within configurable days (default 60)
  - 🔴 **Critical** — expiring within configurable days (default 30)
  - ⛔ **Expired** — past expiry date
- **Dashboard alert banner** shows count of critical/expired items
- Clickable alert cards filter the compliance table

### 12.3 File Access
- Upload: PDF, images stored on server
- Open: streamed via `FileResponse` → blob URL → `window.open()` (Windows Service safe)

---

## 13. Notifications

### 13.1 Channels
| Channel | Provider |
|---|---|
| Email | SMTP (any provider) |
| SMS | MSG91 |
| WhatsApp | WATI |

### 13.2 Template Engine
- **Jinja2 templates** per event type per channel
- Per-event variable hints shown in editor (e.g. `{{ invoice_no }}`, `{{ party_name }}`)
- Templates seeded with defaults on first load

### 13.3 Test & Delivery Log
- **Test send** button per channel in Settings
- Delivery log: channel, status, event type, timestamp, error message
- Filters: channel, status, date range

---

## 14. User Management & Access Control

### 14.1 Roles

| Role | Default Access |
|---|---|
| `admin` | Everything + Administration section |
| `operator` | Dashboard, Tokens |
| `sales_executive` | Dashboard, Sales Invoices, Quotations, Parties, Vehicles |
| `purchase_executive` | Dashboard, Purchase Invoices, Parties, Products |
| `accountant` | Dashboard, Payments, Ledger, GST Reports, Reports, Parties |
| `viewer` | Dashboard, Reports, GST Reports, Ledger (read-only) |
| `private_admin` | Private Admin Console only |

### 14.2 Configurable Permissions
- Admin overrides role → page mapping via `/admin/permissions`
- Per-role page checklist
- Saved to `app_settings`; **sidebar updates live** without page reload

### 14.3 User CRUD (Admin Only)
- Create users with username + role + active status
- Edit user profile (full name, email, phone, role, active)
- Reset another user's password
- Active/inactive toggle

### 14.4 Wallpaper Customisation
- Admin uploads a background image for the main content area
- Semi-transparent overlay preserves readability

---

## 15. Audit Trail

- All **create / update / delete** actions logged with user + IP + timestamp
- Entity types: invoice, token, party, payment, user, etc.
- **Filters:** action type, entity type, user, date range, text search
- **Stats cards:** totals by action and entity

---

## 16. Backup & Restore

- **Create backup:** Runs `pg_dump`, saves timestamped `.sql` file on server
- **Download:** Admin downloads backup file to local machine
- **Restore:** Restores from selected backup file (`psql`), requires confirmation dialog
- **Delete:** Remove old backup files from server disk

---

## 17. Data Import

### Supported Entities
| Entity | Fields Imported |
|---|---|
| Parties | Name, type, GSTIN, phone, state, credit limit, opening balance |
| Products | Name, category, HSN code, GST rate, default rate, unit |
| Vehicles | Registration no, owner, default tare weight |

### Flow
1. Upload Excel (`.xlsx`) or CSV file
2. **Preview first 10 rows** with column mapping
3. Toggle **Update Existing** (by name/registration)
4. Confirm import → results shown (created / updated / failed)
5. Download blank **template** per entity type

---

## 18. Dashboard

| Widget | Content |
|---|---|
| Today Tokens | Count of tokens created today |
| Today Revenue | Sum of grand total from finalised sale invoices today |
| Today Tonnage | Sum of net weight (MT) from completed tokens today |
| Outstanding | Total amount due across all parties |
| Top Customers | Top 5 customers by revenue today |
| Recent Tokens | Last 10 tokens with status and weight |
| Compliance Alert | Banner showing critical/expired compliance items |

---

## 19. Company & Financial Year Setup

### Company Profile
- Legal name, trade name, GSTIN, PAN, state code
- Address, city, state, pincode, phone, email
- Bank: account name, account no, IFSC, branch

### Invoice Numbering
- Separate prefix per invoice type: `SAL`, `PUR`, `REC`, `VOU`, `QUO`, `TKN`
- Format: `PREFIX/YY-YY/NNNN` (e.g. `SAL/25-26/0047`)
- Sequence resets on new financial year activation

### Financial Years
- Create multiple financial years
- Activate a year → all new invoices use its sequence
- Historical invoices remain accessible under their original FY

---

## Technical Stack Reference

| Layer | Technology | Notes |
|---|---|---|
| Backend | Python 3.11 + FastAPI | Fully async, `asyncpg` |
| Database | PostgreSQL 16 | UUID PKs, `gen_random_uuid()` |
| Frontend | React 19 + TypeScript + Vite | shadcn/ui, Tailwind CSS |
| PDF | xhtml2pdf (WeasyPrint fallback) | Jinja2 HTML templates |
| Weight Scale | pyserial | Serial port, WebSocket streaming |
| IP Camera | httpx + Pillow | HTTP snapshot, no RTSP |
| Encryption | AES-256-GCM | Supplement data, USB backups |
| Tally Sync | XML over HTTP | TallyPrime Server on port 9002 |
| Auth | JWT (8h expiry) | Stored in `sessionStorage` |
| Deployment | NSSM Windows Service | `install.ps1` auto-installer |

---

*Last updated: 2026-04-08*
