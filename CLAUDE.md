# Weighbridge Invoice Software — Project Reference

> **IMPORTANT:** Update this file every time a new feature, page, endpoint, model, or behaviour change is added. Keep it the single source of truth.

---

## Project Overview

Stone crusher weighbridge management system built for Indian SMEs. Handles two-stage weighment (gross + tare), GST-compliant invoicing, party/vehicle master, payments, ledger, reports, and a hardware-gated private invoice system.

**Stack:** Python 3.11 + FastAPI (backend) · React 19 + TypeScript + Vite (frontend) · PostgreSQL 16 · xhtml2pdf (PDF)

**Ports:** Backend → `9001` · Frontend dev → `9000` (strictPort)

**Database:** `postgresql+asyncpg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge`

---

## Running the Project

```bash
# Backend
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 9001

# Frontend
cd frontend
npm run dev
```

**Important:** After backend code changes, always do a full stop + start (not just WatchFiles reload) to ensure new code is loaded.

---

## Architecture

```
workspace_Weighbridge/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app + lifespan startup
│   │   ├── config.py                # Pydantic settings (env vars)
│   │   ├── database.py              # Async SQLAlchemy engine
│   │   ├── dependencies.py          # get_current_user, require_role
│   │   ├── models/                  # SQLAlchemy ORM models
│   │   ├── routers/                 # FastAPI route handlers
│   │   ├── schemas/                 # Pydantic request/response schemas
│   │   ├── services/                # Business logic (usb_guard, etc.)
│   │   ├── templates/pdf/           # Jinja2 HTML templates → PDF
│   │   ├── templates/xml/           # Tally XML templates
│   │   ├── utils/pdf_generator.py   # WeasyPrint → xhtml2pdf fallback
│   │   ├── utils/hardware_fingerprint.py  # CPU/MB/Disk/Registry fingerprint for license binding
│   │   ├── utils/secrets_manager.py       # Windows DPAPI encrypt/decrypt wrapper
│   │   └── integrations/
│   │       ├── serial_port/         # Weight scale WebSocket
│   │       ├── tally/               # Tally Prime sync
│   │       └── notifications/
│   │           └── telegram.py      # Telegram Bot API sender (httpx) + daily report builder
│   ├── alembic/                     # DB migrations
│   ├── requirements.txt
│   ├── setup_usb_key.py             # Admin utility: register USB key
│   ├── setup_dpapi.py               # One-time deployment: encrypt .env → secrets.dpapi
│   ├── show_fingerprint.py          # Vendor utility: print hardware fingerprint for license gen
│   └── build_dist.ps1               # Nuitka production binary builder (PowerShell)
├── frontend/
│   ├── src/
│   │   ├── App.tsx                  # Router + auth + USB guard layout
│   │   ├── pages/                   # Page components
│   │   ├── components/              # Shared UI components
│   │   ├── hooks/                   # Custom React hooks
│   │   ├── services/api.ts          # Axios instance (base URL + auth header)
│   │   └── types/                   # TypeScript interfaces
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml
└── scripts/
    ├── Deploy-Full.ps1              # Master 6-phase deployment orchestrator
    ├── Setup-CloudflareTunnel.ps1   # Cloudflare Tunnel install + service
    ├── Setup-CloudBackup.ps1        # R2 backup setup (rclone + scheduled task)
    ├── Backup-ToCloud.ps1           # Daily backup (dump→encrypt→upload→prune→notify)
    ├── Verify-Deployment.ps1        # Post-deployment health check
    ├── Generate-DeploymentConfig.ps1 # Vendor-side config generator
    ├── Install-Client.ps1           # Automated client installer
    └── install-services.ps1         # NSSM service registration
```

---

## Authentication & Roles

- JWT tokens, 8-hour expiry, stored in `sessionStorage`
- `Authorization: Bearer <token>` header on all API calls
- Roles: `admin` · `store_manager` · `operator` · `sales_executive` · `purchase_executive` · `accountant` · `viewer` · `private_admin`

| Role | Default Sidebar Pages |
|---|---|
| `admin` | All pages + Administration section |
| `store_manager` | Dashboard, Store Inventory |
| `operator` | Dashboard, Tokens |
| `sales_executive` | Dashboard, Sales Invoices, Quotations, Parties, Vehicles |
| `purchase_executive` | Dashboard, Purchase Invoices, Parties, Products |
| `accountant` | Dashboard, Payments, Ledger, GST Reports, Reports, Parties |
| `viewer` | Dashboard, Reports, GST Reports, Ledger |
| `private_admin` | Access to `/priv-admin` console only (no sidebar login needed) |

**Admin-configurable permissions:** Admins can override the default role→page mapping via `/admin/permissions`. Stored in `app_settings` table under key `role_permissions`.

**Dependency helpers in `dependencies.py`:**
```python
get_current_user   # Any authenticated user
require_role("admin")  # Role guard — returns 403 if not matching
```

---

## Database Tables

> Tables are created via Alembic migrations plus runtime `CREATE TABLE IF NOT EXISTS` for USB tables.

| Table | Key Columns | Notes |
|---|---|---|
| `users` | id, company_id, username, password_hash, role, is_active | Roles as plain string |
| `companies` | id, name, gstin, pan, address, bank details, invoice_prefix | Single row per deployment |
| `financial_years` | id, company_id, label, start_date, end_date, is_active | |
| `parties` | id, company_id, party_type, name, gstin, phone, current_balance | party_type: customer/supplier/both |
| `party_rates` | id, party_id, product_id, rate, effective_from | Custom rate per party+product |
| `products` | id, company_id, category_id, name, hsn_code, unit, default_rate, gst_rate | |
| `product_categories` | id, company_id, name | |
| `vehicles` | id, company_id, registration_no, default_tare_weight | |
| `tare_weight_history` | id, vehicle_id, tare_weight, recorded_at | |
| `drivers` | id, company_id, name, license_no, phone | |
| `transporters` | id, company_id, name, gstin | |
| `tokens` | id, company_id, token_no (nullable), token_type, vehicle_id, party_id, product_id, gross_weight, tare_weight, net_weight, status, is_supplement | token_no assigned at COMPLETED; is_supplement=TRUE when moved to supplement |
| `invoices` | id, company_id, fy_id, invoice_type, tax_type, invoice_no (nullable), party_id, token_id, total_amount, grand_total, payment_status, status | invoice_no assigned at FINALISE; draft may be auto-created from token |
| `invoice_items` | id, invoice_id, product_id, quantity, rate, gst_rate, amounts | Line items |
| `quotations` | id, company_id, fy_id, quotation_no, party_id, status, grand_total | |
| `quotation_items` | id, quotation_id, product_id, quantity, rate | |
| `payment_receipts` | id, company_id, receipt_no, party_id, amount, payment_mode | Incoming payments (sales) |
| `payment_vouchers` | id, company_id, voucher_no, party_id, amount, payment_mode | Outgoing payments (purchase) |
| `invoice_payments` | id, invoice_id, receipt_id/voucher_id, amount | Links payment to invoice |
| `accounts` | id, company_id, name, group_id, current_balance, party_id | GL accounts |
| `account_groups` | id, company_id, name, group_type, parent_id | Chart of accounts |
| `ledger_entries` | id, company_id, account_id, voucher_type, debit, credit, narration | Double-entry GL |
| `number_sequences` | id, company_id, fy_id, sequence_type, prefix, last_number | Auto-numbering |
| `serial_port_config` | id, company_id, port_name, baud_rate, protocol, is_enabled | Weight scale config |
| `tally_config` | id, company_id, host, port, tally_company_name, auto_sync | Tally integration |
| `audit_logs` | id, user_id, action, entity_type, entity_id, details | |
| `usb_keys` | id, key_uuid, label, is_active | Registered USB key UUIDs |
| `usb_recovery_sessions` | id, pin_hash, expires_at, created_by, reason | Time-limited admin recovery |
| `usb_client_sessions` | id, key_uuid, created_by, expires_at | Per-user client-side USB auth |
| `supplementary_entries` | id, company_id, invoice_no (SE/NNNNN), invoice_date_enc, customer_name_enc, vehicle_no_enc, net_weight_enc, rate_enc, amount_enc, payment_mode_enc, notes_enc, token_id, token_no_enc, token_date_enc, gross_weight_enc, tare_weight_enc, created_by | Non-GST hidden invoices; all sensitive fields AES-256-GCM encrypted; SE/NNNNN from supplement_seq PostgreSQL sequence |
| `compliance_items` | id, company_id, item_type, name, issuer, reference_no, issue_date, expiry_date, file_path, notes, is_active, created_by, created_at, updated_at | Insurance/cert/license/permit tracker; alert level computed from expiry_date |
| `inventory_items` | id, company_id, name, category, unit, current_stock, min_stock_level, description, is_active, created_at, updated_at | Store items; category: fuel/electricity/parts/tools/other; stock_status computed (ok/low/out) |
| `inventory_transactions` | id, company_id, item_id, transaction_type, quantity, stock_before, stock_after, reference_id, reference_no, notes, created_by, created_by_name, created_at | Every stock movement; type: receipt/issue/adjustment; positive=in, negative=out |
| `inventory_purchase_orders` | id, company_id, po_no, status, supplier_name, expected_date, notes, requested_by, requested_by_name, approved_by, approved_by_name, approved_at, rejection_reason, created_at, updated_at | PO workflow; status: pending_approval→approved/rejected→partially_received→received |
| `inventory_po_items` | id, po_id, item_id, item_name, unit, quantity_ordered, quantity_received, unit_price | Line items per PO; item_name+unit denormalized at creation |
| `login_lockouts` | scope (PK), fail_count, locked_until, last_attempt | IP-scoped brute-force lockout; 5 failures = 15-minute lockout |
| `login_audit` | id, username, user_id, ip_address, success, detail, created_at | Full audit trail of all login attempts (success + failure) |

---

## Backend API Endpoints

All endpoints prefixed `/api/v1` unless noted.

### Auth — `/api/v1/auth`
| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/login` | Public | Login → JWT token; IP-scoped brute-force protection (5 fails = 15-min lockout) |
| GET | `/me` | Any | Current user info |
| PUT | `/change-password` | Any | Change own password |
| GET | `/users` | admin | List all users |
| POST | `/users` | admin | Create user |
| PUT | `/users/{id}` | admin | Update user (full_name, email, phone, role, is_active) |
| PUT | `/users/{id}/reset-password` | admin | Reset another user's password |
| GET | `/login-audit` | admin | Paginated login audit log (all success + failure attempts) |

### Company — `/api/v1/company`
| Method | Path | Description |
|---|---|---|
| GET | `/` | Company details |
| PUT | `/` | Update company (admin) |
| GET | `/financial-years` | List financial years |
| POST | `/financial-years` | Create FY (admin) |
| PUT | `/financial-years/{id}/activate` | Activate FY (admin) |

### Products — `/api/v1`
| Method | Path | Description |
|---|---|---|
| GET/POST | `/product-categories` | List/create categories |
| PUT | `/product-categories/{id}` | Update category |
| GET/POST | `/products` | List/create products |
| GET/PUT/DELETE | `/products/{id}` | Get/update/delete product |

### Parties — `/api/v1/parties`
| Method | Path | Description |
|---|---|---|
| GET/POST | `/` | List/create parties |
| GET/PUT/DELETE | `/{id}` | Get/update/delete party |
| GET/POST | `/{id}/rates` | Party-specific product rates |

### Vehicles — `/api/v1`
| Method | Path | Description |
|---|---|---|
| GET/POST | `/vehicles` | List/create vehicles |
| GET | `/vehicles/search` | Search by registration |
| GET/PUT | `/vehicles/{id}` | Get/update vehicle |
| GET | `/vehicles/{id}/tare-history` | Tare weight history |
| GET/POST/PUT | `/drivers` | Driver management |
| GET/POST/PUT | `/transporters` | Transporter management |

### Tokens — `/api/v1/tokens`
| Method | Path | Description |
|---|---|---|
| POST | `/` | Create token |
| GET | `/` | List tokens (paginated) |
| GET | `/today` | Today's tokens |
| GET/PUT | `/{id}` | Get/update token |
| POST | `/{id}/first-weight` | Record first weight |
| POST | `/{id}/second-weight` | Record second weight + complete |
| POST | `/{id}/cancel` | Cancel token |
| POST | `/{id}/set-loading` | Mark loading/unloading |

### Invoices — `/api/v1/invoices`
| Method | Path | Description |
|---|---|---|
| POST | `/` | Create invoice (draft, invoice_no=NULL) |
| GET | `/` | List invoices (paginated, filters). Enriched with token_no + token_date |
| GET/PUT | `/{id}` | Get/update invoice |
| POST | `/{id}/finalise` | Finalize → assigns invoice_no from sequence, locks invoice |
| POST | `/{id}/move-to-supplement` | USB-gated. Migrates draft+token to supplementary_entries, deletes from normal tables |
| GET | `/{id}/pdf` | Download PDF |
| POST | `/{id}/cancel` | Cancel invoice |

### Quotations — `/api/v1/quotations`
| Method | Path | Description |
|---|---|---|
| POST | `/` | Create quotation |
| GET | `/` | List (paginated) |
| GET/PUT | `/{id}` | Get/update |
| POST | `/{id}/send` | Mark as sent |
| POST | `/{id}/convert` | Convert to invoice |
| POST | `/{id}/cancel` | Cancel |
| GET | `/{id}/pdf` | Download PDF |

### Payments — `/api/v1/payments`
| Method | Path | Description |
|---|---|---|
| POST | `/receipts` | Record payment received (sale) |
| GET | `/receipts` | List receipts |
| POST | `/vouchers` | Record payment made (purchase) |
| GET | `/vouchers` | List vouchers |
| GET | `/party-ledger/{party_id}` | Full party ledger |
| GET | `/outstanding` | Outstanding with ageing |

### Dashboard — `/api/v1/dashboard`
| Method | Path | Description |
|---|---|---|
| GET | `/summary` | Today metrics + top customers + recent tokens |

### Reports — `/api/v1/reports`
| Method | Path | Description |
|---|---|---|
| GET | `/sales-register` | Sales/purchase register (date range, CSV) |
| GET | `/weight-register` | Token/weight register (date range, CSV) |
| GET | `/gstr1` | GSTR-1 B2B + B2C + HSN summary (CSV) |
| GET | `/gstr1-json` | GSTR-1 download in GSTN portal JSON format |
| GET | `/gstr3b` | GSTR-3B: outward tax (3.1), ITC (4), net payable |
| GET | `/profit-loss` | Monthly P&L — revenue vs COGS, margin % |
| GET | `/stock-summary` | Product-wise qty purchased/sold, closing stock |

### Weight Scale — WebSocket
| Method | Path | Description |
|---|---|---|
| WS | `/ws/weight` | Real-time weight streaming |
| GET | `/api/v1/weight/status` | Scale connection status |
| POST | `/api/v1/weight/capture` | Manual weight capture |
| GET/PUT | `/api/v1/weight/config` | Scale serial port config |

### USB Guard — `/api/v1/usb-guard`
| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/status` | Any | USB auth status for current user |
| POST | `/register-key` | admin | Register a USB key UUID |
| GET | `/keys` | admin | List registered keys |
| POST | `/recovery/create` | admin | Create recovery PIN (N hours) |
| POST | `/recovery/verify` | Any | Verify recovery PIN → grants session |
| POST | `/client-auth` | Any | Authenticate via key file from client USB |

### Private Invoices — `/api/v1/private-invoices`
| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/` | Any + USB | Create non-GST private invoice |
| GET | `/` | Any + USB | List own invoices (includes decrypted token_no, token_date, weights) |
| GET | `/admin/all` | private_admin | All invoices, no USB needed |
| GET | `/admin/export-csv` | private_admin | Download all as CSV |
| GET | `/export-encrypted` | Any + USB | AES-256-GCM encrypted blob of all supplement data for USB backup |

### Notifications — `/api/v1/notifications`
| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/config` | admin | List all 4 channel configs (email/sms/whatsapp/telegram) |
| PUT | `/config/{channel}` | admin | Save channel config (passwords/tokens masked in response) |
| POST | `/config/{channel}/test` | admin | Send test message via channel |
| GET | `/templates` | admin | List templates (seeds defaults on first call) |
| POST | `/templates` | admin | Create template |
| PUT | `/templates/{id}` | admin | Update template |
| DELETE | `/templates/{id}` | admin | Delete template |
| GET | `/recipients` | admin | List named recipients (staff/owner contacts) |
| POST | `/recipients` | admin | Add recipient (name, channel, contact, event_types) |
| PUT | `/recipients/{id}` | admin | Update recipient |
| DELETE | `/recipients/{id}` | admin | Remove recipient |
| GET | `/log` | admin | Delivery log (filters: channel, status, event_type, page) |

### Audit — `/api/v1/audit`
| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/` | admin | Paginated audit log (filters: action, entity_type, user_id, date_from, date_to, search) |
| GET | `/stats` | admin | Totals by action and entity_type |

### Backup — `/api/v1/backup`
| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/list` | admin | List all backup .sql files |
| POST | `/create` | admin | Run pg_dump → timestamped .sql file |
| GET | `/download/{filename}` | admin | Download backup file |
| POST | `/restore/{filename}` | admin | Restore from backup (destructive) |
| DELETE | `/{filename}` | admin | Delete backup file |

### Tally Integration — `/api/v1/tally`
| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/config` | Any | Get Tally connection config |
| PUT | `/config` | admin | Update Tally config (host, port, company name, auto_sync) |
| POST | `/test-connection` | Any | Test connectivity to Tally HTTP server |
| GET | `/companies` | Any | List companies open in Tally |
| GET | `/pending` | Any | List finalised invoices not yet synced |
| GET | `/pending/parties` | Any | List active parties not yet synced as master ledgers |
| GET | `/pending/orders` | Any | List accepted quotations + approved POs not yet synced |
| POST | `/sync/invoice/{id}` | Any | Push single invoice to Tally as voucher |
| POST | `/sync/bulk` | Any | Bulk push invoices (date range, type filter, include_synced flag) |
| POST | `/sync/party/{id}` | Any | Push party as Customer (Sundry Debtors) or Supplier (Sundry Creditors) master |
| POST | `/sync/parties` | Any | Bulk push all unsynced parties as master ledgers (max 200) |
| POST | `/sync/sales-order/{id}` | Any | Push accepted quotation as Sales Order voucher |
| POST | `/sync/purchase-order/{id}` | Any | Push approved PO as Purchase Order voucher |

**Tally setup:** Gateway of Tally → F12 Config → Advanced → Enable ODBC Server → set port (default 9002 in this app)
**XML format:** Sales/Purchase vouchers with party ledger + inventory entries + GST ledger entries (CGST+SGST or IGST). Masters use REPORTNAME="All Masters" with LEDGER elements.
**Entity types:** 6 — Sales Invoice, Purchase Invoice, Customer Master, Supplier Master, Sales Order (from Quotation), Purchase Order (from InventoryPurchaseOrder)
**Sync state:** `tally_synced` + `tally_sync_at` columns on `invoices`, `parties`, `quotations`, `inventory_purchase_orders`
**Sign convention:** Sales voucher: party debit (+), sales/tax ledgers credit (-). Purchase: opposite. Discount debit (+) on both. Vouchers must balance to zero.
**Testing:** `backend/tests/test_tally_integration.py` — 43 tests using `types.SimpleNamespace` + `MockTallyServer` (no database required)

### Compliance — `/api/v1/compliance`
| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/` | Any | List compliance items (filters: item_type, include_inactive) |
| POST | `/` | Any | Create compliance item |
| GET | `/alerts` | Any | Items expiring within threshold days or expired — used by dashboard |
| GET | `/settings/thresholds` | Any | Get warning_days + critical_days thresholds |
| PUT | `/settings/thresholds` | admin | Update warning_days + critical_days thresholds |
| GET | `/{id}` | Any | Get single item |
| PUT | `/{id}` | Any | Update item |
| DELETE | `/{id}` | admin | Soft-delete (is_active=False) |
| GET | `/{id}/download` | Any | Stream file as HTTP response (blob URL in browser) |

**Item types:** `insurance` · `certification` · `license` · `permit`
**Alert levels (computed):** `expired` (past expiry) · `critical` (≤critical_days, default 30) · `warning` (≤warning_days, default 60) · `ok`
**Thresholds stored:** `app_settings` table keys `compliance_warning_days` + `compliance_critical_days`
**File open pattern:** `GET /{id}/download` → `FileResponse` → frontend creates blob URL → `window.open(blobUrl, '_blank')`. Required because backend runs in Windows Session 0 (service isolation) — `os.startfile()` is invisible.
**Table:** `compliance_items` — created via runtime DDL in `main.py`

### App Settings — `/api/v1/app-settings`
| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/role-permissions` | Any | Get role→pages map (falls back to defaults if not stored) |
| PUT | `/role-permissions` | admin | Save role→pages map (`{"admin": ["*"], "operator": ["/", "/tokens"], ...}`) |
| GET | `/wallpaper/info` | Any | Get wallpaper URL (`{"url": "/uploads/wallpaper/filename.jpg"}` or `{"url": null}`) |
| POST | `/wallpaper` | admin | Upload wallpaper (multipart `file` field, image/*, max 5 MB) |
| DELETE | `/wallpaper` | admin | Remove wallpaper (deletes file from disk + app_settings row) |

**Stored keys:** `role_permissions` (JSON), `app_wallpaper_path` (relative path string)
**Uploaded files:** saved to `<project_root>/uploads/wallpaper/` served via `/uploads` static mount
**Live update:** admin pages dispatch `new CustomEvent('appsettings:updated')` after save; `useAppSettings` hook listens and re-fetches without page reload

### Cameras — `/api/v1/cameras` + `/api/v1/tokens`
| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/v1/cameras/config` | Any | Get camera config (passwords masked) |
| PUT | `/api/v1/cameras/config` | admin | Save camera config; password `"***"` preserves existing |
| POST | `/api/v1/cameras/test/{camera_id}` | admin | Capture test snapshot → return preview URL |
| GET | `/api/v1/tokens/{token_id}/snapshots` | Any | Poll snapshot status for a token |
| POST | `/api/v1/tokens/{token_id}/snapshots/retry` | admin | Re-trigger failed camera captures |

**Config key:** `camera_config` in `app_settings` table (JSON: `{"front": {...}, "top": {...}}`)
**Trigger:** Automatically fires after second weight commit via `BackgroundTasks` — non-blocking
**Retry logic:** 3 attempts × 5s timeout per camera; failures tracked in `token_snapshots` table
**File storage:** `uploads/camera/<token_id>/<camera_id>_<timestamp>.jpg` served via `/uploads`
**Frontend:** Capturing spinner + per-camera status in WeightCaptureDialog; lightbox via Camera icon on completed token rows; Camera tab in Settings for URL config + test snapshot
**Table:** `token_snapshots` — columns: id, token_id, camera_id, camera_label, file_path, capture_status (pending|captured|failed), attempts, error_message, captured_at

### Inventory — `/api/v1/inventory`
| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/items` | any | List active items with stock_status; filters: `?category=&status=` |
| POST | `/items` | admin | Create item; current_stock starts at 0 |
| PUT | `/items/{id}` | admin | Partial update; cannot change current_stock directly |
| DELETE | `/items/{id}` | admin | Soft delete; blocked if open POs reference item |
| POST | `/issue` | any | Atomic stock issue (FOR UPDATE lock); validates qty≤stock; creates issue transaction |
| POST | `/adjust` | admin | Atomic stock adjustment; positive or negative; validates result≥0 |
| GET | `/transactions` | any | Paginated transaction history; filters: item_id, type, date_from, date_to |
| GET | `/purchase-orders` | any | List POs; filter `?status=`; includes line items |
| POST | `/purchase-orders` | any | Create PO; auto-generates PO/YY-YY/NNNN number via NumberSequence |
| GET | `/purchase-orders/{id}` | any | Full PO with line items |
| POST | `/purchase-orders/{id}/approve` | admin | pending_approval → approved |
| POST | `/purchase-orders/{id}/reject` | admin | pending_approval → rejected (terminal); stores reason |
| POST | `/purchase-orders/{id}/receive` | admin | Receive goods (partial allowed); creates receipt transactions; auto-sets status |
| GET | `/dashboard` | any | Items + pending_po_count + last 10 transactions |
| GET | `/settings` | admin | Telegram config (token masked with ****+last4) |
| PUT | `/settings` | admin | Save Telegram config; masked token sentinel skips DB update |
| POST | `/settings/test` | admin | Send test Telegram message |
| POST | `/daily-report/send` | admin | Manual trigger of the daily inventory Telegram report |
| GET | `/settings/categories` | admin | List current item categories |
| PUT | `/settings/categories` | admin | Save custom categories list |
| GET | `/analytics` | any | Consumption trend + top consumed + category breakdown + summary; filters: date_from, date_to, granularity (day/week/month), item_id |

**PO State Machine:** `pending_approval` → `approved` / `rejected` → `partially_received` → `received`
**Concurrency:** `FOR UPDATE` lock on inventory_items row during issue/adjust; on NumberSequence during PO creation
**Settings stored in `app_settings`:** `inventory.telegram_bot_token`, `inventory.telegram_chat_id`, `inventory.telegram_report_time` (default `"20:00"`), `inventory.telegram_enabled`, `inventory.categories` (JSON array)
**Background task:** `_inventory_daily_report_loop` checks every 60s; module-level `_last_inv_report_date` prevents double-send
**stock_status computed:** `ok` (current_stock > min_stock_level), `low` (0 < current_stock ≤ min_stock_level), `out` (current_stock = 0)

### Data Import — `/api/v1/import`
| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/preview/{entity}` | admin | Preview first 10 rows + columns |
| POST | `/parties` | admin | Import parties from Excel/CSV |
| POST | `/products` | admin | Import products (auto-creates categories) |
| POST | `/vehicles` | admin | Import vehicles |
| GET | `/template/{entity}` | any | Download blank Excel template |

---

## Frontend Pages

| Page | Route | Description |
|---|---|---|
| `LoginPage` | `/login` | JWT login form |
| `DashboardPage` | `/` | Widgets: today tokens/revenue/tonnage/outstanding, top customers, recent tokens |
| `TokenPage` | `/tokens` | Create tokens, two-stage weighment, real-time weight display |
| `InvoicesPage` | `/invoices` | Sales invoices. Tax type dropdown hides Non-GST without USB |
| `InvoicesPage` | `/purchase-invoices` | Purchase invoices (same component, `defaultType="purchase"`) |
| `QuotationsPage` | `/quotations` | Quotations with date range filter, convert to invoice |
| `PaymentsPage` | `/payments` | Receipts + vouchers tabs, link to invoices |
| `PartiesPage` | `/parties` | Party master CRUD |
| `ProductsPage` | `/products` | Product + category CRUD |
| `VehiclesPage` | `/vehicles` | Vehicles, drivers, transporters tabs |
| `ReportsPage` | `/reports` | Sales/Purchase register · Weight register · P&L · Stock Summary tabs, CSV export |
| `GstReportsPage` | `/gst-reports` | GSTR-1 (B2B/B2C/HSN + JSON export) · GSTR-3B (sections 3.1 + 4 + net tax) |
| `LedgerPage` | `/ledger` | Party ledger (running balance) + outstanding with ageing |
| `SettingsPage` | `/settings` | Company, bank, invoice prefixes, financial years, USB Guard, Notifications config tabs |
| `PrivateInvoicesPage` | `/private-invoices` | USB-gated. Lock screen with file picker + recovery PIN |
| `PrivateAdminPage` | `/priv-admin` | Role: private_admin only. Audit view + CSV export. No sidebar. |
| `NotificationsPage` | `/notifications` | Template editor (Jinja2 body + per-event variable hints) · Delivery log with channel/status filters |
| `AuditPage` | `/audit` | Audit trail viewer: filter by action/entity/date/search, stats cards, pagination |
| `BackupPage` | `/backup` | Create pg_dump backup, download, restore (with confirm), delete |
| `ImportPage` | `/import` | Bulk import parties/products/vehicles from Excel/CSV; file drop, preview, confirm, template download |
| `CompliancePage` | `/compliance` | Insurance, Certifications, Licenses, Permits — due-date alerts (clickable cards filter table), configurable thresholds, blob-URL file open, CRUD |
| `UserManagementPage` | `/admin/users` | Admin-only. Create/edit users, reset passwords, role badges, active/inactive toggle |
| `PermissionsPage` | `/admin/permissions` | Admin-only. Tabs per role; checklist of pages per role; save → live sidebar update |
| `WallpaperSettingsPage` | `/admin/wallpaper` | Admin-only. Upload/preview/remove wallpaper image for main content area background |
| `InventoryPage` | `/inventory` | Store Inventory — 5 tabs: Stock (cards with colour-coded levels + Use Stock dialog), Orders (PO workflow with approve/reject/receive), History (paginated transaction log), Analytics (trend/pie/top-consumed charts with date presets), Settings (Telegram config + custom categories) |

---

## Frontend Hooks

| Hook | File | Purpose |
|---|---|---|
| `useAuth` | `hooks/useAuth.ts` | Login, logout, JWT in `sessionStorage`, 401 event listener |
| `useWeight` | `hooks/useWeight.ts` | WebSocket connection to `/ws/weight`, real-time weight state |
| `useUsbGuard` | `hooks/useUsbGuard.ts` | Polls `/usb-guard/status` every 10s. Exposes `authorized`, `method`, `expires_at`, `refresh()`, `clientAuth(fileHandle)`, `revokeSession()`, `backupNow()`, `hasBackupDir`. After clientAuth, prompts for USB directory and starts hourly supplement auto-backup. |
| `useAppSettings` | `hooks/useAppSettings.ts` | Fetches role-permissions + wallpaper/info in parallel. Returns `{ permissions, wallpaperUrl, loading }`. Listens for `appsettings:updated` DOM event to re-fetch without page reload. Exports `DEFAULT_PERMISSIONS` constant (used by PermissionsPage for reset-to-defaults). |

---

## USB Guard System

### How it works
1. **Server USB** — On server machine, scans all drive letters for `.weighbridge_key` UUID file. If found and registered in `usb_keys` table → authorized.
2. **Client USB** — From any machine on LAN: user clicks "Authenticate with USB" on lock screen, selects `.weighbridge_key` file via browser file picker, UUID sent to `/usb-guard/client-auth`, server verifies and creates `usb_client_sessions` record (8-hour expiry).
3. **Recovery** — Admin pre-creates a PIN via Settings → USB Guard tab. User enters PIN on lock screen → `usb_recovery_sessions` record grants time-limited access.

### What USB controls
- `PrivateInvoicesPage` — completely hidden from sidebar; shows lock screen if accessed directly
- `Non-GST / Bill of Supply` option in New Invoice dialog — hidden without USB
- All `/api/v1/private-invoices` endpoints — return HTTP 403 without USB/recovery/client session

### Setup steps
1. Insert USB → run `python setup_usb_key.py` (writes `.weighbridge_key`, registers UUID in DB)
2. Or: Settings → USB Guard → paste UUID manually → Register Key
3. To set up recovery: Settings → USB Guard → Recovery → enter PIN + hours

### Private Admin Console (`/priv-admin`)
- Not in sidebar — accessed by direct URL only
- Requires user with `role = 'private_admin'`
- No USB needed — role-based only
- Full audit table (who created, when) + CSV export

---

## PDF Generation

**Chain:** Jinja2 template → HTML → WeasyPrint (try first) → xhtml2pdf (fallback)

- Templates: `backend/app/templates/pdf/invoice.html`, `quotation.html`
- Entry point: `backend/app/utils/pdf_generator.py` → `generate_pdf(template_name, context)`
- WeasyPrint fails silently on Windows (no GTK) → xhtml2pdf used automatically
- Response: `Content-Type: application/pdf`, `Content-Disposition: attachment`

---

## Key Patterns & Conventions

### Backend
- All endpoints are `async def`
- DB session injected via `Depends(get_db)` → `AsyncSession`
- Auth via `Depends(get_current_user)` or `Depends(require_role("admin"))`
- Direct SQL via `text()` for complex queries; ORM for CRUD
- Pagination: `page` + `page_size` query params → `{"items": [...], "total": N}`
- Financial year (`fy_id`) stored on invoices/tokens/payments for multi-year support
- Invoice numbering: `NumberSequence` table, format `{prefix}/{YY-YY}/{NNNN}`

### Frontend
- API calls via `src/services/api.ts` (Axios with baseURL + Bearer token interceptor)
- All pages fetch on mount via `useCallback` + `useEffect`
- Dialog pattern: `open` boolean state + `Dialog` from shadcn
- Form state: `useState({field: ''})` + `setForm(f => ({...f, field: value}))`
- Select `onValueChange` always uses `v ?? 'default'` to handle null
- Dates: `new Date().toISOString().split('T')[0]` for `YYYY-MM-DD`
- INR formatter: `const INR = (v) => '₹' + v.toLocaleString('en-IN', {minimumFractionDigits: 2})`
- GST state detection: GSTIN first 2 digits vs company state code → CGST+SGST or IGST

---

## Features Status

### ✅ Completed

| Feature | Details |
|---|---|
| Authentication | JWT login, role-based access, 8-hour tokens |
| Company setup | Profile, bank details, GSTIN, logo |
| Financial year | Multi-year support, activate/switch |
| Token/Weighment | Two-stage weighing, real-time scale, manual entry |
| Sales invoices | GST/Non-GST, B2B/B2C, line items, PDF download |
| Purchase invoices | Same as sales, separate numbering |
| Quotations | Full CRUD, date range filter, convert to invoice, PDF |
| Payments | Receipts + vouchers, partial payments, link to invoices |
| Party ledger | Running balance, debit/credit, print |
| Outstanding | Ageing analysis (Current / 1-30 / 31-60 / 61-90 / 90+ days) |
| Party master | CRUD, GSTIN, custom product rates |
| Product master | Categories, HSN codes, GST rates |
| Vehicle master | Vehicle, driver, transporter CRUD, tare history |
| Dashboard | Today tokens/revenue/tonnage/outstanding, top customers, recent tokens |
| Sales register | Date/party filter, GST breakdown, CSV export |
| Weight register | Token-wise, date range, type filter, CSV export |
| GSTR-1 | B2B + B2C + HSN summary, month/year filter, CSV export, GSTN JSON export |
| GSTR-3B | Outward tax (3.1a, 3.1e), ITC from purchases (4A5), net tax payable |
| Profit & Loss | Monthly revenue vs COGS (purchases), gross profit, margin %, financial year default |
| Stock summary | Product-wise qty purchased/sold/closing, closing value per product, CSV export |
| Settings | Company profile, bank details, invoice prefixes, FY, USB Guard, Notifications config tabs |
| PDF invoices | xhtml2pdf fallback chain, B2C party handling |
| Tally Prime Integration | XML voucher push (Sales + Purchase) · config + test connection in Settings · per-invoice sync button · bulk sync · pending list |
| Weight scale | WebSocket serial port integration, stability detection |
| USB Guard | Server USB + client file picker + recovery PIN + HMAC challenge-response |
| USB auto-backup | Hourly AES-256-GCM encrypted supplement backup to pendrive via File System Access API |
| Private invoices | Separate table, USB-gated UI, SE/NNNNN gap-free PostgreSQL sequence numbering |
| Private admin | `/priv-admin` — `private_admin` role, audit view, CSV export |
| Record payment | Banknote button on invoice rows, partial payment support |
| Gap-free sequencing | token_no assigned at COMPLETED (not creation); invoice_no assigned at FINALISE (not draft) |
| Auto-invoice on completion | Second weight → COMPLETED auto-creates draft invoice (rate from party_rates → product default → 0) |
| Move to Supplement | POST /invoices/{id}/move-to-supplement — USB-gated; migrates draft+token to encrypted supplementary_entries; deletes from normal tables |
| Token hyperlink in invoices | Invoice list enriched with token_no + token_date; click badge opens TokenDetailModal |
| Token search | GET /tokens?search= searches vehicle_no OR party name; date_from/to filters |
| Notifications (Phase 7) | SMTP email + MSG91 SMS + WATI WhatsApp + Telegram Bot · Jinja2 templates per event+channel · named recipients table (staff/owner contacts) · delivery log · test send · event triggers on token_completed/invoice_finalized/payment_received |
| Audit trail (Phase 7) | `audit_log` table · log_action() helper in invoices/payments/tokens · AuditPage with filters + stats |
| Backup & Restore (Phase 7) | pg_dump/psql wrapper · BackupPage: create, download, restore (confirm), delete |
| Data Import (Phase 8) | Excel/CSV import for parties/products/vehicles · preview 10 rows · update_existing flag · blank template download |
| Windows deployment (Phase 8) | install.ps1 auto-installer · nssm-register.ps1 Windows service · SETUP_GUIDE.md deployment reference |
| Compliance management | Insurance/Certification/License/Permit tracking · expiry date alerts (clickable cards) · configurable thresholds · blob-URL file download (Windows Session 0 safe) · dashboard alert banner |
| Role-based UI | Sidebar filters nav items per role · admin sees all + Administration section |
| User Management | Admin page: create/edit/reset-password for all users; role badge color-coding |
| Configurable permissions | Admin page: per-role page checklist stored in `app_settings`; live sidebar update via DOM event |
| Wallpaper | Admin uploads custom background image; shown with semi-transparent overlay in main content area |
| IP Camera integration | Auto-captures JPEG snapshots from 2 cameras (front + top) on second weight via HTTP snapshot URL; fire-and-forget BackgroundTasks; retry 3×; lightbox on token row |
| Store Inventory module | 4 tables (items/transactions/POs/PO-items) · full PO workflow (raise→approve→receive) · atomic FOR UPDATE stock issue/adjust · Telegram daily report + background loop · InventoryPage with 5 tabs · store_manager role |
| Inventory Analytics | 📈 Analytics tab with preset date ranges, daily/weekly/monthly granularity, item drill-down, 4 summary cards, 3 recharts charts (consumption trend, category pie, top consumed) |
| Security hardening | Hardware fingerprint license binding (CPU/MB/Disk/Registry, 2-of-4 tolerance) · login brute-force lockout (5 fails=15 min, login_audit table) · CSP + HSTS security headers · DPAPI machine-locked secrets (secrets_manager.py + setup_dpapi.py) · license_guard default-False fix · Nuitka binary build (build_dist.ps1) · OS hardening script (hardening/secure_setup.ps1) · Vite sourcemap:false + hash filenames |
| Build documentation | BUILD_GUIDE.md — 12-section guide: prerequisites, frontend build, Nuitka binary, packaging, client install, DPAPI setup, license generation, updates, troubleshooting |

### ❌ Pending

| Feature | Priority | Notes |
|---|---|---|
| Vehicle report | Low | Vehicle-wise tonnage + revenue analytics |
| Weight scale Settings tab | Low | UI for serial port config (currently via API only) |

### 🔮 Future Phases

| Feature | Phase |
|---|---|
| Tally auto-sync on finalise (auto_sync flag) | 6 |
| Customer portal (read-only party view) | 6 |
| Multi-company support | 7 |
| Scheduled email reports | 7 |

---

## Environment & Config

```env
# backend/.env
DATABASE_URL=postgresql+asyncpg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge
DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge
SECRET_KEY=dev-secret-key-change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
```

---

## Changelog

| Date | Feature |
|---|---|
| 2026-03-28 | PDF generation fixed (xhtml2pdf fallback for Windows/no-GTK) |
| 2026-03-28 | Quotations page date range filter added |
| 2026-03-28 | Record Payment against Invoice (partial payment support) |
| 2026-03-28 | USB Guard system — server + client USB + recovery PIN |
| 2026-03-28 | Private invoices (non-GST, USB-gated, separate table) |
| 2026-03-28 | Non-GST option hidden in invoice form without USB |
| 2026-03-28 | Client USB file picker authentication |
| 2026-03-28 | Private Admin Console at `/priv-admin` (private_admin role) |
| 2026-03-28 | GSTR-1 JSON export (GSTN portal format) |
| 2026-03-28 | GSTR-3B report (sections 3.1 + 4, net tax payable) |
| 2026-03-28 | Profit & Loss report (monthly, financial year default) |
| 2026-03-28 | Stock Summary report (product-wise in/out/closing) |
| 2026-03-28 | Fixed P&L date_trunc grouping (extract year/month instead) |
| 2026-03-28 | Phase 7: Notification system — SMTP/MSG91/WATI + templates + delivery log + audit trail |
| 2026-03-28 | Phase 7: Backup/Restore — pg_dump/psql via backend API + BackupPage UI |
| 2026-03-28 | Phase 7: NotificationsPage (template editor + delivery log) + Notifications config tab in SettingsPage |
| 2026-03-28 | Phase 7: AuditPage — audit trail viewer with action/entity/date filters + stats cards |
| 2026-03-28 | Phase 8: ImportPage — bulk Excel/CSV import for parties/products/vehicles with preview |
| 2026-03-28 | Phase 8: install.ps1 + nssm-register.ps1 Windows service scripts + SETUP_GUIDE.md |
| 2026-03-29 | Tally Prime integration — XML voucher builder (Sales+Purchase), HTTP client, 7 API endpoints, Settings tab, per-invoice sync button |
| 2026-03-29 | Bug fix: TokenPage party dropdown — added textValue prop to SelectItem, removed div wrapper |
| 2026-03-29 | UI fix: Invoice line items Qty+Rate columns wider (minmax 80px/100px) |
| 2026-03-29 | Tally default port changed to 9002 (avoids clash with Vite dev server on 9000) |
| 2026-04-01 | Gap-free sequencing: token_no assigned at COMPLETED, invoice_no assigned at FINALISE |
| 2026-04-01 | Auto-invoice creation: second-weight COMPLETED → draft sales invoice auto-created with rate from party_rates/product default |
| 2026-04-01 | Move-to-Supplement: POST /invoices/{id}/move-to-supplement (USB-gated) migrates draft invoice+token data to encrypted supplement, deletes from normal tables |
| 2026-04-01 | Gap-free supplement sequence: supplement_seq PostgreSQL sequence (replaces COUNT(*)+1) |
| 2026-04-01 | Token hyperlink: invoice list enriched with token_no+token_date; TokenDetailModal component for inline detail view |
| 2026-04-01 | Token search: GET /tokens?search= matches vehicle_no OR party name (ILIKE) |
| 2026-04-01 | USB auto-backup: useUsbGuard prompts for FileSystemDirectoryHandle after clientAuth; hourly writeBackup() to USB |
| 2026-04-01 | Export-encrypted endpoint: GET /private-invoices/export-encrypted returns AES-256-GCM blob of all supplement data |
| 2026-04-01 | Schema: tokens.token_no nullable, tokens.is_supplement bool, invoices.invoice_no nullable, supplementary_entries token columns |
| 2026-04-04 | Compliance management: insurance/cert/license/permit tracking, expiry alerts, file-open, dashboard banner |
| 2026-04-04 | Fix: finalise/cancel invoice now show error/success toasts (previously silent failures) |
| 2026-04-04 | Fix: InvoiceResponse schema now includes tally_sync_at field |
| 2026-04-04 | Compliance: clickable alert cards filter table; configurable warning/critical day thresholds stored in app_settings |
| 2026-04-04 | Compliance: replaced OS file-open (broken in Windows service) with FileResponse blob-URL pattern |
| 2026-04-04 | Role-based UI: sidebar filters nav per role; admin sees Administration section |
| 2026-04-04 | New roles: sales_executive, purchase_executive (string values only, no schema change) |
| 2026-04-04 | User Management page (/admin/users): create/edit users, reset passwords, role badges |
| 2026-04-04 | Role Permissions page (/admin/permissions): per-role page checklist, save to app_settings, live update via appsettings:updated event |
| 2026-04-04 | Wallpaper settings (/admin/wallpaper): upload/preview/remove; applied as background on main content area |
| 2026-04-04 | Auth: PUT /users/{id}/reset-password endpoint (admin only) |
| 2026-04-04 | App Settings: GET/PUT /role-permissions + GET/POST/DELETE /wallpaper endpoints |
| 2026-04-04 | Static /uploads mount for wallpaper serving; uploads/wallpaper/ dir created on startup |
| 2026-04-04 | JWT token storage changed from localStorage to sessionStorage |
| 2026-04-04 | IP Camera integration: auto-snapshot on second weight via HTTP snapshot URL (STQC/Hikvision/Dahua compatible) |
| 2026-04-04 | Camera: BackgroundTasks fire-and-forget, 3-retry with 5s timeout, PIL validation, saved to uploads/camera/ |
| 2026-04-04 | Camera: token_snapshots table tracks per-camera status (pending/captured/failed) |
| 2026-04-04 | Camera: WeightCaptureDialog shows spinner + per-camera status + thumbnails after second weight |
| 2026-04-04 | Camera: SnapshotLightboxModal on completed token rows (Camera icon → 2-column image grid) |
| 2026-04-04 | Camera: Settings → Cameras tab for URL config + live test snapshot preview |
| 2026-04-09 | Store Inventory module: 4 new tables, full PO workflow, atomic stock issue/adjust, Telegram daily report, InventoryPage (5 tabs), store_manager role |
| 2026-04-09 | Inventory Analytics tab: preset date ranges, granularity toggle, item filter, 4 summary cards, bar/pie/bar recharts |
| 2026-04-09 | Security: hardware fingerprint license binding (wmic CPU/MB/Disk + registry, 2-of-4 tolerance) |
| 2026-04-09 | Security: login brute-force lockout (5 fails = 15-min IP lockout, login_audit + login_lockouts tables) |
| 2026-04-09 | Security: full CSP + HSTS + X-Request-ID in security_headers.py |
| 2026-04-09 | Security: Windows DPAPI machine-locked secrets (secrets_manager.py + setup_dpapi.py) |
| 2026-04-09 | Security: license_guard default True→False bug fix (was silently allowing all requests on startup failure) |
| 2026-04-09 | Security: Vite build hardening — sourcemap:false, hash-only filenames, manualChunks vendor splitting |
| 2026-04-09 | Build: Nuitka production binary builder (build_dist.ps1) — standalone .exe, no Python source |
| 2026-04-09 | Build: OS hardening script (hardening/secure_setup.ps1) — service account, ACLs, pg_hba, firewall, BitLocker |
| 2026-04-09 | Build: BUILD_GUIDE.md — 12-section team build guide (prerequisites → license generation → troubleshooting) |
| 2026-04-09 | PermissionsPage: added store_manager role tab; DEFAULT_PERMISSIONS includes store_manager→['/inventory'] |
| 2026-04-09 | Tally: 4 new XML builders — build_customer_master_xml, build_supplier_master_xml, build_sales_order_xml, build_purchase_order_xml |
| 2026-04-09 | Tally: 6 new API endpoints — /pending/parties, /pending/orders, /sync/party/{id}, /sync/parties, /sync/sales-order/{id}, /sync/purchase-order/{id} |
| 2026-04-09 | Tally: tally_synced + tally_sync_at columns added to parties, quotations, inventory_purchase_orders (runtime DDL + SQLAlchemy model columns) |
| 2026-04-09 | Tally: 43-test integration suite — MockTallyServer (balancing validator), conftest fixtures, 4 test categories (XML structure, ledger balance, mock server, edge cases) |
| 2026-04-09 | Notification engine: Telegram Bot channel added (tg_bot_token in notification_config, telegram_notify.py sender) |
| 2026-04-09 | Notification engine: notification_recipients table + full CRUD (GET/POST/PUT/DELETE /recipients) — named staff/owner contacts with per-event subscriptions |
| 2026-04-09 | Notification engine: send_notification() updated — dispatches to both party (from context) and all named recipients; supports email/sms/whatsapp/telegram |
| 2026-04-09 | Notification engine: event triggers wired — token_completed in tokens.py, invoice_finalized in invoices.py, payment_received in payments.py (all as BackgroundTasks) |
| 2026-04-09 | Notification engine: default Telegram templates added for invoice_finalized, payment_received, token_completed (HTML bold/italic via Bot API) |
| 2026-04-09 | NotificationsPage: Recipients tab added — table with add/edit/delete dialog, event-type multi-select, Telegram chat ID helper hint |
| 2026-04-10 | Notification fix: seed_default_templates() now uses upsert by (event_type, channel) — adds missing Telegram templates to existing DBs |
| 2026-04-10 | Notification fix: startup seeds default recipients (Ankush/RM telegram + email contacts) idempotently |
| 2026-04-10 | Deployment pipeline: 6 new PowerShell scripts for secure client deployment |
| 2026-04-10 | Cloudflare Tunnel: Setup-CloudflareTunnel.ps1 — installs cloudflared, configures tunnel as Windows service |
| 2026-04-10 | Cloud Backup: Backup-ToCloud.ps1 — daily pg_dump → AES-256 encrypt → upload to Cloudflare R2 → prune → Telegram notify |
| 2026-04-10 | Cloud Backup: Setup-CloudBackup.ps1 — installs rclone, configures R2 credentials, creates scheduled task (daily 2 AM) |
| 2026-04-10 | Deployment: Deploy-Full.ps1 — 6-phase master orchestrator (system check → install → harden → tunnel → backup → verify) |
| 2026-04-10 | Deployment: Verify-Deployment.ps1 — post-deployment health check (services, security, connectivity, backup) |
| 2026-04-10 | Deployment: Generate-DeploymentConfig.ps1 — vendor-side config generator with CHECKLIST.txt + DEPLOY.bat |
| 2026-04-10 | Backup API: GET /api/v1/backup/cloud-status — reads backup-status.json written by scheduled task |
| 2026-04-10 | BackupPage: cloud backup status card (healthy/error badge, last backup time/size, next scheduled, R2 location) |
