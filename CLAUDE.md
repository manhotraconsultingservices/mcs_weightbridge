# Weighbridge Invoice Software — Project Reference

> **IMPORTANT:** Update this file every time a new feature, page, endpoint, model, or behaviour change is added. Keep it the single source of truth.

> **DEBUGGING PRINCIPLE — don't assume, find the root cause, then fix.** When
> something breaks, never guess or ship a speculative fix. Prove the cause first
> by (a) reading the relevant **code path** end-to-end, and/or (b) analysing
> **logs / live data** — backend logs, the scale agent's Discovery UI, or by
> **reproducing against the real API**. Useful technique: the **per-tenant
> subdomain** login (`https://<slug>.weighbridgesetu.com/api/v1/auth/login`)
> bypasses the `www` Cloudflare WAF that 405-blocks scripted login on the apex,
> so you can probe a specific tenant's prod state directly. Heuristic: **"works
> for tenant A but not tenant B" with shared code ⇒ the difference is per-tenant
> data / schema / config, not code.** State the proven cause before writing the
> fix, and prefer surfacing the real error over a generic message.

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

## Deployment to production (weighbridgesetu.com)

**Auto-deploy via GitHub Actions** — every push to `main` runs `.github/workflows/deploy.yml`, which SSHes into the Hostinger VPS and executes `scripts/ci-deploy.sh`. That script: pulls latest, detects whether `frontend/` or `backend/` changed, rebuilds only what's affected, restarts the `weighbridge` systemd unit if needed, reloads nginx, hits `/api/v1/health`, and appends a one-line summary to `/var/log/weighbridge-deploy.log`. Cloudflare cache is purged at the end. Typical deploy: 45–90 s.

Paths-ignored: `**/*.md`, `docs/**`, `instructions/**`, `plans/**`, `CLAUDE.md` — pure-doc changes don't trigger a deploy or a cache purge.

Setup guide: `docs/CI_CD_SETUP.md` (one-time SSH-key + GitHub-secrets setup).

Rollback: SSH in, `cd /opt/weighbridge && git reset --hard <good-sha> && bash scripts/ci-deploy.sh`.

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
│   │   ├── services/                # Business logic (usb_guard, barrier, etc.)
│   │   └── barrier.py           # H3-D: fire-and-forget HTTP relay trigger (asyncio.create_task)
│   │   ├── templates/pdf/           # Jinja2 HTML templates → PDF
│   │   ├── templates/xml/           # Tally XML templates
│   │   ├── utils/pdf_generator.py   # WeasyPrint → xhtml2pdf fallback
│   │   ├── utils/hardware_fingerprint.py  # CPU/MB/Disk/Registry fingerprint for license binding
│   │   ├── utils/secrets_manager.py       # Windows DPAPI encrypt/decrypt wrapper
│   │   ├── utils/invoice_diff.py          # compute_invoice_diff() + invoice_to_snapshot() for revision system
│   │   └── integrations/
│   │       ├── serial_port/         # Weight scale WebSocket
│   │       ├── tally/               # Tally Prime sync
│   │       ├── einvoice/            # NIC GST eInvoice API (builder.py + client.py)
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
| `gate_guard` | Gate Register (`/gate`) only — auto-redirected on login |

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
| `parties` | id, company_id, party_type, name, gstin, phone, current_balance, default_payment_mode | party_type: customer/supplier/both; **default_payment_mode** (default `'cash'`): `'cash'` → non-GST invoice (Bill of Supply), blocked from Tally · `'online'` → GST invoice, syncable to Tally |
| `party_rates` | id, party_id, product_id, rate, effective_from | Custom rate per party+product |
| `products` | id, company_id, category_id, name, hsn_code, unit, default_rate, gst_rate, bulk_density, is_raw_material | bulk_density (**kg/CFT** — cubic feet is the canonical volume unit) enables volume→weight conversion for volume-based tokens; is_raw_material flag marks production inputs |
| `product_categories` | id, company_id, name | |
| `vehicles` | id, company_id, registration_no, default_tare_weight | |
| `tare_weight_history` | id, vehicle_id, tare_weight, recorded_at | |
| `drivers` | id, company_id, name, license_no, phone | |
| `transporters` | id, company_id, name, gstin | |
| `tokens` | id, company_id, token_no (nullable), token_type, vehicle_id, party_id, product_id, vehicle_no, vehicle_type, tyre_count, gross_weight, tare_weight, net_weight, weight_method, volume_cft, status, is_supplement | token_no assigned at COMPLETED; vehicle_type from admin-configurable list; tyre_count (4/6/8/10/12) shown on slips + drives volume defaults; is_supplement=TRUE when moved to supplement; weight_method='weighbridge' (default, gross-tare) or 'volume' (volume_cft × product.bulk_density(kg/CFT)); volume_cft populated only when weight_method='volume' — **cubic feet is the canonical volume unit** (legacy m³ DBs auto-migrated via the units_migrated_to_cft_v1 DDL marker × 35.3147) |
| `invoices` | id, company_id, fy_id, invoice_type, tax_type, invoice_no (nullable), party_id, token_id, due_date, total_amount, grand_total, payment_status, status, revision_no, original_invoice_id, write_off_amount, write_off_reason, write_off_at, write_off_by, irn, irn_ack_no, irn_ack_date, irn_qr_code, irn_signed_invoice, einvoice_status, einvoice_error, irn_cancelled_at | invoice_no assigned at FINALISE; due_date auto-computed = invoice_date + party.payment_terms_days; tax_type derived from party.default_payment_mode (cash→non_gst, online→gst); revision_no starts at 1; original_invoice_id NULL for v1, points to root for all revisions; write_off_* tracks bad-debt closure; eInvoice columns for NIC IRN integration |
| `invoice_items` | id, invoice_id, product_id, quantity, rate, gst_rate, amounts | Line items |
| `invoice_revisions` | id, original_invoice_id, from_revision_no, to_revision_no, from_invoice_id, to_invoice_id, snapshot (JSONB), diff (JSONB), change_summary, revised_by, created_at, finalized_at | Revision chain records; snapshot = full from-invoice at creation time; diff computed at finalization |
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
| `tally_config` | id, company_id, host, port, tally_company_name, auto_sync, sync_invoice_prefix | Tally integration; `sync_invoice_prefix` (comma-separated, blank=all) limits which invoice-number series sync to Tally |
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
| `product_stock` | id, company_id, product_id (UNIQUE), current_stock, min_stock_level, last_alerted_at, updated_at | Finished-goods inventory — one row per product per company; current_stock in kg; status pill computed (ok/low/out); 24h throttle for low-stock Telegram alerts |
| `product_stock_movements` | id, company_id, product_id, movement_type, quantity (signed kg), stock_before, stock_after, reference_type, reference_id, reference_no, notes, created_by, created_at | Append-only audit; movement_type: `opening` · `sale` · `sale_cancelled` · `purchase` · `purchase_cancelled` · `cycle_input` (negative, raw-material consumption) · `cycle_output` (positive) · `adjustment` |
| `production_cycles` | id, company_id, cycle_date, raw_material_id (→products.id, must have is_raw_material=true), input_kg, stage1_output_kg, stage2_output_kg, stage3_output_kg, status (draft/finalised), notes, created_by, created_at, finalised_at | One cycle per company per day; finalise posts `cycle_input` (negative on raw material) + `cycle_output` (positive on each finished product) movements |
| `production_cycle_outputs` | id, cycle_id, product_id, output_kg | Per-product Stage 4 finished weights; sum drives yield_pct = total_output / input × 100 |
| `login_lockouts` | scope (PK), fail_count, locked_until, last_attempt | IP-scoped brute-force lockout; 5 failures = 15-minute lockout |
| `login_audit` | id, username, user_id, ip_address, success, detail, created_at | Full audit trail of all login attempts (success + failure) |
| `anpr_events` | id, company_id, plate_raw, plate_normalized, vehicle_id, token_id, direction (entry/exit/unmatched/duplicate/heartbeat), confidence, source (local_fastalpr/hikvision_webhook/dahua_webhook/manual), camera_id, snapshot_path, detected_at, ocr_alternates JSONB, needs_review, reviewed_by, reviewed_at, notes | Append-only ANPR event log. One row per gate-camera plate detection. `needs_review=TRUE` surfaces in /anpr/review queue. Indexes on (company_id, detected_at desc), (plate_normalized, detected_at desc), (token_id), partial on needs_review. |
| `delivery_challans` | id, company_id, fy_id, challan_no (DC/FY/NNNN), challan_date, purpose, party_id, customer_name, token_id, vehicle_no, transporter_name, driver_name, distance_km, destination, tax_type, sub_total, total_amount, status (open/invoiced/cancelled), invoice_id, notes, ewb_no, ewb_date, ewb_valid_till, ewb_status, ewb_error, created_by | GST Rule 55 dispatch document (Horizon 1). Own tables so a challan never touches GSTR-1/P&L/receivables until converted to an invoice. challan_no gap-free at create via `next_doc_no`. |
| `delivery_challan_items` | id, challan_id, product_id, description, hsn_code, quantity, unit, rate, amount, gst_rate, sort_order | Challan line items. |
| `invoices` (+H1 cols) | …, `reference_invoice_id` (→invoices.id; for credit/debit notes), `note_reason`, `ewb_date`, `ewb_valid_till`, `ewb_status` (none/generated/cancelled/failed), `ewb_error`, `ewb_distance_km` | Credit/Debit notes reuse this table with `invoice_type IN ('credit_note','debit_note')` — safe because every financial query filters `invoice_type=='sale'/'purchase'`. EWB cols populated by IRN-integrated capture + standalone NIC EWB. |
| `royalty_passes` | id, company_id, fy_id, pass_no, pass_type (royalty/e_transit/mineral_permit), source_name, party_id, mineral, product_id, issue_date, valid_till, quantity_mt, rate, amount, vehicle_no, status (active/exhausted/expired/cancelled), notes, created_by | Horizon 2. Govt mineral royalty / e-transit pass; authorised qty consumed against inbound purchase loads. |
| `royalty_pass_consumptions` | id, pass_id, company_id, token_id, invoice_id, quantity_mt, consumed_date, notes, created_by | Append-only draw-downs against a pass. balance = pass.quantity_mt − Σ consumptions. |
| `customer_users` | id, company_id, party_id, email, password_hash, is_active, last_login_at, created_by | Horizon 2. Customer-portal login — a SEPARATE identity from staff `users`. Unique on (company_id, lower(email)). JWT scope='customer' + party_id; a customer only ever sees that party's data. |
| `branches` | id, company_id, name, code, gstin, address_line1, city, state, state_code, pincode, phone, is_default, is_active, created_at | Horizon 3. A plant/weighbridge. `branch_id` (NULLABLE = default branch) added to tokens, invoices, payments, product_stock, production_cycles, users, number_sequences. Per-branch gap-free invoice/gate-pass numbering. |
| `gate_passes` | id, company_id, gate_pass_no (GP/YYYY-MM-DD/NNN), pass_date, seq_no, vehicle_no, vehicle_name, vehicle_id (nullable), driver_name, driver_phone, material, product_id, purpose (weighbridge/delivery/pickup/own_use/other), token_id (nullable), net_weight, entry_time, exit_time, entry_photo_path, exit_photo_path, status (inside/exited/cancelled), notes, created_by, created_by_name, created_at, updated_at | Guard-managed gate pass register. One row per vehicle visit. Gate pass number resets to 001 each day. For `purpose='weighbridge'`, `token_id` is mandatory before exit. |
| `gate_pass_daily_seq` | company_id + pass_date (composite PK), last_no INTEGER | Atomic daily counter for gate pass numbers. Uses `INSERT … ON CONFLICT DO UPDATE SET last_no = last_no + 1 RETURNING last_no`. |
| `gate_camera_events` | id, company_id, camera_position (entry/exit), camera_id, gate_pass_id, snapshot_path, source (manual/webhook), webhook_payload JSONB, detected_at, linked_at | Raw camera detection events (from CP Plus vehicle-detection webhook or manual capture). Unlinked events surface in a review queue for the guard to action. |
| `custom_field_definitions` | id, company_id, entity_type (token/product/party), field_key, label, field_type (text/number/select/date/boolean), unit, options (JSONB), required, show_on_slip, sort_order, is_active | Owner-managed custom attributes ("the matrix"). Per-tenant (lives in the tenant DB → only that tenant sees its fields). v1 attaches to `token` (weighment). UNIQUE (company_id, entity_type, field_key). Values stored in `tokens.custom_fields` JSONB keyed by field_key (e.g. `{"moisture_pct":13.5,"quality_grade":"A"}`). Maize tenants auto-seed Moisture % + Quality grade. |

---

## Backend API Endpoints

All endpoints prefixed `/api/v1` unless noted.

### Tenant Management — `/api/v1/admin` (multi-tenant only)
| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/tenants` | X-Super-Admin | Create tenant (DB + DDL + seed) |
| GET | `/tenants` | X-Super-Admin | List all tenants |
| GET | `/tenants/{slug}` | X-Super-Admin | Get tenant detail |
| PUT | `/tenants/{slug}` | X-Super-Admin | Update tenant (name, active, config) |
| POST | `/tenants/{slug}/backup` | X-Super-Admin | Backup tenant database |
| POST | `/tenants/backup-all` | X-Super-Admin | Backup all active tenants |
| POST | `/tenants/{slug}/rotate-key` | X-Super-Admin | Regenerate agent API key |

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
| GET | `/{id}/effective-rate/{product_id}` | Effective rate (party_rate → product default → 0) |
| GET | `/rates/matrix` | Sparse matrix of all (party, product, rate) cells |
| POST | `/{id}/rates/bulk` | Bulk-set rates for one party (per-product entries) |
| DELETE | `/{id}/rates/{product_id}` | Clear a custom rate (revert to default) |
| GET | `/{id}/360` | Customer 360 — KPIs, aging, last 20 invoices+payments, custom rates, lifetime tonnage |

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
| GET | `/last-by-vehicle/{vehicle_no}` | Smart-suggest: returns last COMPLETED token's party + product + tare for this plate (used by Operator Kiosk's "Same as last time?" card) |
| GET/PUT | `/{id}` | Get/update token |
| POST | `/{id}/first-weight` | Record first weight |
| POST | `/{id}/second-weight` | Record second weight + complete |
| POST | `/volume` | Volume-based token (skips bridge): one call creates + completes + auto-invoices. Requires `product.bulk_density` (kg/CFT). Body: `volume_cft`. Computes net_weight = volume_cft × bulk_density. |
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
| POST | `/{id}/generate-irn` | Manual IRN generation/retry (finalized B2B invoices with GSTIN) |
| POST | `/{id}/cancel-irn` | Cancel IRN within 24 hours (reason + remark) |
| POST | `/{id}/create-revision` | admin/accountant — creates a draft copy (revision_no+1, original_invoice_id set) |
| GET | `/{id}/revisions` | List all versions in the revision chain (original + all amendments) |
| GET | `/{id}/compare/{other_id}` | Side-by-side diff between any two invoice versions |
| POST | `/{id}/write-off` | admin/accountant — write off uncollectable balance; closes invoice as bad debt; reduces party.current_balance |
| POST | `/write-off-bulk` | admin/accountant — mass write-off across N invoices for one customer (Customer 360 action). Body: `{invoice_ids:[…], reason:"…"}`. Returns `{written, skipped, total_amount, parties_affected}`. |

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
| GET | `/exceptions` | One-shot aggregate for the exception-first OwnerDashboardPage: traffic-light status + overdue customers + low-stock products + compliance expiring + yield variance + today vs 30-day-median revenue |
| POST | `/whatsapp-overdue` | Batch-send `payment_overdue_reminder` notifications to a list of `party_ids` (uses existing notifications pipeline — WhatsApp/SMS/Email/Telegram per templates configured) |

### Reports — `/api/v1/reports`
| Method | Path | Description |
|---|---|---|
| GET | `/sales-register` | Sales/purchase register (date range, CSV) |
| GET | `/weight-register` | Token/weight register (date range, CSV) |
| GET | `/gstr1` | GSTR-1 B2B + B2C + HSN summary (CSV) |
| GET | `/gstr1-json` | GSTR-1 download in GSTN portal JSON format |
| GET | `/gstr3b` | GSTR-3B: outward tax (3.1), ITC (4), net payable |
| GET | `/profit-loss` | Monthly P&L — revenue vs COGS minus bad-debt → net profit, margin % |
| GET | `/stock-summary` | Product-wise qty purchased/sold, closing stock |
| GET | `/write-offs` | All invoice write-offs in date range with per-customer aggregate + per-row detail (powers Reports → Write-offs tab) |
| GET | `/gst-split` | GST vs non-GST (Bill of Supply) breakdown — counts + amounts + monthly + top cash customers |
| GET | `/sales-by-status` | Sale-invoice amount split by status (Draft vs Final/"Complete") over a date range. Params: `from_date`, `to_date`, `granularity` (day/week/month). Returns `summary` (per-status count+amount; cancelled counted but excluded from series) + time-bucketed `series` for charting. Powers Reports → Sales by Status tab |
| GET | `/anomalies` | Run all 7 fraud/anomaly detectors. Params: `date_from`, `date_to`. Returns `{overall, detectors}` — per-detector `{title, description, severity, count, items[]}`. Detectors: high_frequency · weight_variance · tare_deviation · invoice_leakage · after_hours · round_weight · unlinked_passes. Each isolated in try/except so one failure never blocks others. |
| GET | `/anomaly-config` | Get anomaly detection thresholds (stored in `app_settings` key `anomaly_config`) |
| PUT | `/anomaly-config` | Update anomaly thresholds: `high_frequency_trips_per_day` (default 8), `weight_variance_pct` (25), `tare_deviation_kg` (200), `invoice_leakage_hours` (6), `after_hours_start` (21), `after_hours_end` (5), `round_weight_divisor` (1000) |

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
**Auto-sync on finalise:** when `tally_config.auto_sync` + `is_enabled`, finalising a GST `sale`/`purchase` invoice fires a fire-and-forget `BackgroundTask` (`invoices.py::_auto_sync_tally_bg`) that opens its own tenant-routed session, reuses `tally.py::_push_invoice`, and commits `tally_synced`. Non-blocking, never rolls back finalisation, leaves `tally_synced=False` on failure so the invoice stays in `/tally/pending` for manual retry. Toggle in Settings → Tally. When `auto_sync` is OFF, nothing syncs automatically (manual push only).
**Invoice prefix filter:** `tally_config.sync_invoice_prefix` (comma-separated, e.g. `INV,PUR`; blank = all GST invoices) gates which invoice-number series flow to Tally. Enforced at the single `tally.py::_push_invoice` chokepoint (so manual + bulk + auto-sync all respect it via `_invoice_matches_prefix`, case-insensitive `startswith`) plus SQL-side `ILIKE` filtering on `/tally/pending` and bulk-sync worklists. Series prefixes: `INV`=GST sale, `PUR`=purchase, `CN`/`DN`=credit/debit notes, `CINV`=non-GST cash sale (already excluded by the GST guard).
**Sign convention:** Sales voucher: party debit (+), sales/tax ledgers credit (-). Purchase: opposite. Discount debit (+) on both. **Inventory line carries the GROSS amount (pre-discount); discount is a separate ledger line.** Vouchers must balance to zero.
**Testing:** `backend/tests/test_tally_integration.py` — 43 tests using `types.SimpleNamespace` + `MockTallyServer` (no database required). Full payload reference + balance proofs + setup steps in `docs/tally-integration-validation.md`.

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
| GET | `/manager-contacts` | Any | Returns active admin users with a phone — powers the Operator Kiosk SOS button (zero-config) |
| GET | `/vehicle-types` | Any | List vehicle types (default: truck, tractor, trailer, tipper, mini_truck, tanker, dumper) |
| PUT | `/vehicle-types` | admin | Save custom vehicle types list (deduplicated, lowercased, underscore-spaced) |
| GET | `/einvoice-config` | admin | Get eInvoice config (passwords masked) |
| PUT | `/einvoice-config` | admin | Save eInvoice config (masked fields preserve existing) |
| POST | `/einvoice-config/test` | admin | Test NIC eInvoice authentication |
| GET | `/barrier-config` | admin | Get barrier relay config (`http_auth_pass` masked with `***`) |
| PUT | `/barrier-config` | admin | Save barrier config; sentinel `***` preserves stored password |
| POST | `/barrier-config/test` | admin | Fire one synthetic `trigger_barrier("entry","TEST-PLATE")` → returns `{ok, message}` |

**Stored keys:** `role_permissions` (JSON), `app_wallpaper_path` (relative path string), `vehicle_types` (JSON array), `einvoice_config` (JSON object with NIC credentials), `barrier_config` (JSON — relay type/URL/auth/duration/direction toggles), `anomaly_config` (JSON — detector thresholds)
**Uploaded files:** saved to `<project_root>/uploads/wallpaper/` served via `/uploads` static mount
**Live update:** admin pages dispatch `new CustomEvent('appsettings:updated')` after save; `useAppSettings` hook listens and re-fetches without page reload

### Cameras — `/api/v1/cameras` + `/api/v1/tokens`
| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/v1/cameras/config` | Any | Get camera config (passwords masked) |
| PUT | `/api/v1/cameras/config` | admin | Save camera config; password `"***"` preserves existing |
| POST | `/api/v1/cameras/test/{camera_id}` | admin | Capture test snapshot → return preview URL |
| GET | `/api/v1/cameras/search` | Any | Search snapshots by token number, vehicle number, date range |
| GET | `/api/v1/cameras/stream/{camera_id}` | Any | Live MJPEG stream (auth via `?token=` query param) |
| POST | `/api/v1/cameras/mock-snapshots/{token_id}` | admin | Seed fake camera images for testing (dev only) |
| GET | `/api/v1/tokens/{token_id}/snapshots` | Any | Poll snapshot status for a token |
| POST | `/api/v1/tokens/{token_id}/snapshots/retry` | admin | Re-trigger failed camera captures |

**Config key:** `camera_config` in `app_settings` table (JSON: `{"front": {...}, "top": {...}}`)
**Trigger:** Automatically fires after both first and second weight commits via `BackgroundTasks` — non-blocking
**Dual-stage capture:** `weight_stage` column (`first_weight` | `second_weight`) tracks which weighment triggered the snapshot
**Retry logic:** 3 attempts × 5s timeout per camera; failures tracked in `token_snapshots` table
**File storage:** `uploads/camera/<token_id>/<camera_id>_<stage>_<timestamp>.jpg` served via `/uploads`
**Frontend:** Capturing spinner + per-camera status in WeightCaptureDialog; lightbox via Camera icon on completed token rows; Camera tab in Settings for URL config + test snapshot; SnapshotSearchPage for image search
**Table:** `token_snapshots` — columns: id, token_id, camera_id, camera_label, file_path, capture_status (pending|captured|failed), attempts, error_message, captured_at, weight_stage
**Unique constraint:** `(token_id, camera_id, weight_stage)` — allows separate snapshots per weight stage

### ANPR — `/api/v1/anpr` (Gate-camera plate recognition)
| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/detect` | Any (agent JWT) | Source A — local FastALPR worker posts a single detection. Body: `{plate_raw, confidence, camera_id, source, snapshot_b64?, ocr_alternates?}`. Returns `{event_id, direction, token_id?, gate_pass_no?, action_taken}`. |
| POST | `/webhook/hikvision` | X-ANPR-Secret | Source B — Hikvision Generic Event Push (HTTP Listening Server). Normalises vendor JSON → `_handle_detection()`. |
| POST | `/webhook/dahua` | X-ANPR-Secret | Source B — Dahua Smart Event HTTP Notify. Same normalisation. |
| GET | `/events` | Any | Paginated event log; filters: `date_from`, `date_to`, `direction`, `plate`, `needs_review` |
| GET | `/events/{id}` | Any | Single event with hydrated vehicle + token (party + product names) |
| GET | `/unmatched` | Any | Review queue — events flagged `needs_review=TRUE` |
| POST | `/events/{id}/reassign` | admin/operator/accountant | Operator fixes a misread: link to existing vehicle (`vehicle_id`), correct plate (`plate_corrected`), or auto-register new vehicle (`register_new_vehicle=true`) |
| GET | `/stats` | Any | Counts (entries / exits / unmatched / unique_vehicles), `currently_inside` gauge, `avg_dwell_minutes`, per-day buckets |
| GET | `/config` | admin | ANPR feature config (webhook_secret masked with `***`) |
| PUT | `/config` | admin | Save ANPR config; submitting `***` for webhook_secret preserves the stored value |
| POST | `/config/test` | admin | Fire one synthetic detection (Source='manual') through the full pipeline — Settings → ANPR → "Run Test" button |
| GET | `/trips` | Any | **Daily Vehicle Movement Report.** One row per visit — pairs `anpr_entry_at` + `anpr_exit_at` and LEFT JOINs the linked invoice. Filters: `date_from`, `date_to` (default today), `page`, `page_size`. Response includes per-row trip data + roll-ups (`entries`, `exits`, `currently_inside`, `total_tonnage_mt`, `total_revenue`, `avg_dwell_minutes`). |
| POST | `/daily-summary/send` | admin | Fire the daily ANPR Telegram report on demand. Same context the scheduled 8 PM loop builds. Query param `target_date` (default today). Returns `{ok, date, trip_count, entries, exits}`. |

**Decision logic (single-camera setup, 3-layer dedup):**
1. 15-second SQL window suppresses retry races (`anpr_events.detected_at > NOW() - 15s` for same plate → `direction='duplicate'`).
2. Open token today same plate → **EXIT** (stamps `anpr_exit_at` on the linked token).
3. Recently-completed token (within 24h) without exit → late **EXIT** fallback.
4. Else → **ENTRY**: 5-min application guard against double-creating, allocate `GP/<FY>/NNNN` via `NumberSequence(sequence_type='gate_pass')` (same gap-free row-lock pattern as `_next_invoice_no`), create OPEN Token with `source='anpr'`, smart-suggest party/product/tare from last COMPLETED token for that plate.

**Unknown plates (no vehicle master match):** token still created with `vehicle_no` only, `vehicle_id` NULL, event flagged `needs_review=TRUE`. Fuzzy match is 1-char Levenshtein vs `vehicles.registration_no`. Auto-invoice silently skips when party/product NULL (existing `tokens.py:217` behaviour — no regression).

**Telegram delivery:** Five templates seeded by `seed_default_templates()` — `anpr_entry`, `anpr_exit`, `anpr_unknown_plate`, `anpr_camera_down`, and `anpr_daily_summary`. Owner picks which events they receive via existing Recipients tab on `/notifications`. The daily summary fires from the existing `_owner_digest_loop` in `main.py` at the configured `owner_digest.time` (default 20:00) — gated by `anpr_config.daily_summary` (default TRUE) AND `anpr_config.enabled`. Body lists top-20 trips with plate, entry/exit times, dwell, token, gate pass, invoice no + amount.

**Snapshots:** Persisted to `uploads/anpr/<YYYYMMDD>/<event_id>.jpg` from inline base64 (Source A) or fetched separately (Source B).

**Token columns added:** `gate_pass_no` (auto-numbered, `GP/25-26/0001` format), `anpr_entry_at`, `anpr_exit_at`, `source` (manual|anpr|kiosk). The existing `tokens.gate_pass` free-text column is untouched.

**Tables:** `anpr_events` (see Database Tables section). Indexes: (company_id, detected_at desc), (plate_normalized, detected_at desc), (token_id), partial on `needs_review=TRUE`.

**Webhook security:** Hikvision + Dahua endpoints require `X-ANPR-Secret` header matching `anpr_config.webhook_secret`. Secret masked with `***` sentinel on GET (same pattern as einvoice_config, camera passwords).

**Disabled by default:** `anpr_config.enabled=false` initially. Existing kiosk + manual token flows unchanged when ANPR is off.

### Gate Management — `/api/v1/gate`
| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/passes` | gate_guard, operator, admin | Create gate pass (entry); background entry photo capture via `BackgroundTasks` |
| GET | `/passes` | gate_guard, operator, admin | List passes; filters: `date`, `status`, `vehicle_no`, `page`, `page_size` |
| GET | `/passes/summary` | gate_guard, operator, admin | Daily counts + mismatch flag + inside_list for the given `date` (default today) |
| GET | `/passes/{id}` | gate_guard, operator, admin | Single pass with joined vehicle, token, creator |
| PUT | `/passes/{id}` | gate_guard, operator, admin | Update guard details (vehicle_no, driver, material, purpose, token_id, notes) via COALESCE |
| POST | `/passes/{id}/exit` | gate_guard, operator, admin | Record exit time + background exit photo; returns HTTP 400 if `purpose='weighbridge'` and `token_id` is NULL |
| POST | `/passes/{id}/cancel` | gate_guard, operator, admin | Cancel an inside pass (marks status=cancelled) |
| POST | `/capture/{position}` | gate_guard, operator, admin | On-demand HTTP snapshot from entry/exit camera (`position`: `entry` or `exit`); returns `snapshot_path` |
| POST | `/webhook/cpplus` | X-Gate-Secret | CP Plus vehicle-detection alarm push; infers camera position from cam_id; creates `gate_camera_events` row; fires `asyncio.create_task()` background snapshot |
| GET | `/camera-events` | gate_guard, operator, admin | Recent unlinked camera events for guard to review |
| GET | `/config` | admin | Gate camera config (passwords and webhook_secret masked with `***`) |
| PUT | `/config` | admin | Save gate camera config; `***` sentinel preserves stored passwords |
| POST | `/config/test/{position}` | admin | Test HTTP snapshot from entry/exit camera; validates image content-type |

**Gate pass number format:** `GP/YYYY-MM-DD/NNN` — resets to 001 each day per company. Allocated at entry (token create); EXIT reuses the same number.
**Daily sequence:** `gate_pass_daily_seq` table; atomic via `INSERT … ON CONFLICT DO UPDATE SET last_no = last_no + 1 RETURNING last_no` — no separate `FOR UPDATE` lock.
**Mandatory token link:** `POST /passes/{id}/exit` returns HTTP 400 if `purpose='weighbridge'` and `token_id IS NULL`. All other purposes exit freely.
**CP Plus webhook position inference:** `_infer_position()` checks `cam_id` for "exit"/"out" keywords, falls back to "entry". Guard can correct via camera-events queue.
**Background photo capture:** both `_bg_capture_entry_photo` and `_bg_capture_exit_photo` use `async_session_factory` context manager (independent of request session).
**Settings stored in `app_settings`:** key `gate_camera_config` (JSON — entry/exit camera URL/credentials, webhook_secret, eod_alert_time, eod_alert_enabled).

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
| `SnapshotSearchPage` | `/snapshot-search` | Search camera snapshots by token number, vehicle number, or date range. Results grouped by token with 1st/2nd weight sections. Lightbox image viewer. Date presets (Today/7 Days/30 Days). Pagination. |
| `AnprEventsPage` | `/anpr/events` (also Operations Hub tab "Gate Cameras") | Full ANPR event log via shared `<DataTable>`. Date range, direction, plate, review-status filters. KPI strip (entries/exits/unique/inside/dwell). CSV export. Snapshot lightbox per row. |
| `AnprLivePage` | `/anpr/live` | Full-bleed wall-board for the gate office: 4 big KPIs (in/out/inside/unmatched) + last 20 detections with snapshot thumbnails. Auto-polls `/anpr/events` and `/anpr/stats` every 5 s. Designed for a wall-mounted TV. |
| `AnprReviewPage` | `/anpr/review` (also Operations Hub tab "Plate Review") | Operator review queue for unmatched / low-confidence plates. Per-row snapshot + OCR text + top-3 alternates. Three resolution paths: link to existing vehicle, correct plate, or auto-register from plate. Calls `POST /anpr/events/{id}/reassign`. |
| `AnprTripsPage` | `/anpr/trips` (also Operations Hub tab "Movement Report") | **Daily vehicle-movement report.** One row per visit pairing entry + exit + dwell + token + invoice. 6 KPI cards (entries, exits, inside, tonnage MT, revenue ₹, avg dwell). Date range with Today / Last 7 / Last 30 presets. CSV export. Admin "Send Daily Report" button fires `POST /api/v1/anpr/daily-summary/send` → Telegram. |
| `CustomerProfilePage` | `/customers/:id` | Customer/Supplier 360 — KPIs (outstanding/LTV/AOV/last-order/write-off count), aging chart, last 20 invoices (with mass-write-off checkboxes for admin/accountant), last 20 payments, custom rate cards. Linked from Parties names, Ledger outstanding, Dashboard Top Customers, and Dashboard Outstanding KPI. |
| `CustomerPickerPage` | `/customers` | Card grid of every customer with name, type, phone, city, current balance. Search + customer/supplier filter chips. Click a card → opens `/customers/:id`. Discoverability landing page for Customer 360 — sidebar "Customers" points here. |
| `WriteOffsReportPage` | `/reports?tab=write-offs` (tab inside Reports hub) | Date range + 3 KPI cards (total ₹, invoice count, customer count) + per-customer aggregate DataTable + all-rows DataTable + CSV export. Powered by `/api/v1/reports/write-offs`. |
| `DeliveryChallansPage` | `/delivery-challans` (also Sales hub "Challans" tab) | Horizon 1. Create challan (party + items + transport), per-row Print / Convert-to-invoice / Cancel / Generate-EWB. `<CreditStatusBanner>` in the create dialog. |
| `CreditDebitNotesPage` | `/credit-debit-notes` (also Sales hub "Notes" tab) | Horizon 1. Issue a credit/debit note against a finalised invoice (pick source + type + reason), list, finalise (assigns CN/DN no.), print. |
| `RoyaltyPassesPage` | `/royalty` (also Materials hub "Royalty Passes" tab) | Horizon 2. Royalty/transit-pass register: reconciliation KPIs (authorised/consumed/inbound/balance/unaccounted), expiring banner, utilisation bars, create + per-pass consume dialogs. |
| `CustomerPortalPage` | `/portal` (standalone — own customer auth, NOT the staff AppLayout) | Horizon 2. Customer self-service: email+password login → outstanding, invoices (PDF download), payments statement, UPI pay (VPA + `upi://` deep link), change password. Tenant derived from subdomain. Admin creates logins via `PortalAccessDialog` on the Customer-360 page. |
| `BranchAdminPage` | `/admin/branches` (admin gear dropdown) | Horizon 3. Branch/plant CRUD; each branch gets its own number series. Header `BranchPicker` (admin) switches the active branch (sends `X-Branch-Id`). |
| `Gstr2bReconcilePage` | `/reports?tab=gstr2b` (Reports hub "GSTR-2B (ITC)" tab) | Horizon 3. Upload GSTR-2B JSON → match vs purchase invoices → matched / value-mismatch / in-2B-not-books / in-books-not-2B + ITC summary. |
| `GstSplitReportPage` | `/reports?tab=gst-split` (tab inside Reports hub) | GST vs Cash (Bill of Supply) split by date range — 4 KPI cards, monthly stacked bar chart, per-month detail table, top cash customers, CSV export. Powered by `/api/v1/reports/gst-split`. |
| `GatePassPage` | `/gate` | Guard-facing gate register. Summary strip (N entered/exited/inside + mismatch banner). Two tabs: "Inside Now" + "All Today". New Gate Pass dialog (vehicle no/name, driver, material, purpose, entry photo capture). Exit dialog (token ID mandatory for weighbridge, exit photo). Auto-refresh every 60 s. `gate_guard` role lands here on login. |
| `OperatorKioskPage` | `/operator` | Full-bleed kiosk-mode UI for low-literacy bridge operators. 3-screen flow (Arrival → Weighing → Done) with photo-tile pickers, "Same as last time?" smart-suggest, voice confirm, floating SOS-call-manager button. Users with `role='operator'` land here by default on login. |
| `OwnerDashboardPage` | `/` | **Default home for non-operators.** Exception-first owner dashboard. Traffic-light status header (green/amber/red) + revenue strip + 4 action cards (overdue customers / low stock / compliance expiring / yield variance) with one-tap WhatsApp batch reminder, jump-to-PO, jump-to-renew, and jump-to-production. Auto-refresh every 60 s. Mobile-first 360 px responsive. Legacy chart-heavy dashboard moved to `/dashboard-legacy`. |
| `SalesHubPage` | `/sales` | Tabbed hub for Bills (invoices) + Estimates (quotations). URL syncs via `?tab=`. |
| `MaterialsHubPage` | `/materials` | Tabbed hub for Catalog · Customer Rates · Stock on Hand · Production · Production Dashboard · Production Settings. Consolidates 6 old sidebar items. |
| `OperationsHubPage` | `/operations` | Tabbed hub for Vehicles · Store Inventory · Camera & Scale · Snapshot Search. |
| `ReportsHubPage` | `/reports` | Tabbed hub for Payments · Account Statement · GST · GSTR-2B · GST vs Cash Split · Sales by Status · P&L + Sales · Write-offs · Documents (compliance) · Activity Log (audit). Default tab `reports` so `/reports` URL behaves like the old page. Legacy reports at `/reports-classic`. |
| `SalesStatusReportPage` | `/reports?tab=sales-status` (tab inside Reports hub) | **Sales by Invoice Status chart report.** Date range + day/week/month granularity toggle. 4 KPI cards (Draft ₹+count, Final/Complete ₹+count, Total, Draft share %), a stacked bar chart of Draft vs Final sale-invoice amounts per period, and a Draft-vs-Complete donut. CSV export. Powered by `GET /api/v1/reports/sales-by-status`. |
| `AnomalyReportPage` | `/reports?tab=anomaly` (tab inside Reports hub) | **H3-C Fraud/Anomaly Analytics.** Date range with presets. Overall severity banner (green/amber/red). 7 collapsible `DetectorCard` components — auto-expand when findings exist. Per-detector item table with type-specific columns. CSV export of summary. Configurable thresholds via `GET/PUT /api/v1/reports/anomaly-config`. |
| `SettingsPage` (Barrier tab) | `/settings?tab=barrier` | **H3-D Barrier relay config.** Enable/disable, direction toggles (entry/exit/unknown), relay URL, HTTP method, open param string, open duration, timeout, optional Basic Auth. Save + Test buttons. `POST /barrier-config/test` fires one synthetic trigger; result shown inline. Hidden in SaaS mode. |

---

## Frontend Hooks

| Hook | File | Purpose |
|---|---|---|
| `useAuth` | `hooks/useAuth.ts` | Login, logout, JWT in `sessionStorage`, 401 event listener |
| `useWeight` | `hooks/useWeight.ts` | WebSocket connection to `/ws/weight`, real-time weight state |
| `useUsbGuard` | `hooks/useUsbGuard.ts` | Polls `/usb-guard/status` every 10s. Exposes `authorized`, `method`, `expires_at`, `refresh()`, `clientAuth(fileHandle)`, `revokeSession()`, `backupNow()`, `hasBackupDir`. After clientAuth, prompts for USB directory and starts hourly supplement auto-backup. |
| `useAppSettings` | `hooks/useAppSettings.ts` | Fetches role-permissions + wallpaper/info in parallel. Returns `{ permissions, wallpaperUrl, loading }`. Listens for `appsettings:updated` DOM event to re-fetch without page reload. Exports `DEFAULT_PERMISSIONS` constant (used by PermissionsPage for reset-to-defaults). |

---

## Shared UI Components

### `DataTable<T>` — reusable sortable / filterable / exportable table

Located at `frontend/src/components/DataTable.tsx`.

> **MANDATORY STANDARD:** Every multi-row data table in the app MUST use `DataTable<T>`. Raw `<table>` / `<tbody>` HTML is forbidden for data grids. This applies to new tables and any future page additions.

**Features:**
- Click column header to toggle sort: asc → desc → none (3-state).
- Per-column filter inputs in a toggleable row. Number columns accept `>10`, `<5`, `10-20`, or plain substring. Enum columns get a dropdown of `enumOptions`.
- Column show/hide via gear-icon menu with Reset.
- CSV export of the *currently filtered + sorted* view (uses `exportValue` if provided, else the accessor).
- Per-table state (sort + filters + visible columns) persisted to `localStorage` under `dt.<id>.<setting>` keys.

**Usage pattern:**
```tsx
import { DataTable, type ColumnDef } from '@/components/DataTable';

const COLUMNS: ColumnDef<MyRow>[] = [
  { key: 'date',    label: 'Date',    type: 'date',   accessor: r => r.date,
    format: v => new Date(String(v)).toLocaleDateString('en-IN') },
  { key: 'amount',  label: 'Amount',  type: 'number', align: 'right',
    accessor: r => r.amount,
    format: v => `₹${Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` },
  { key: 'status',  label: 'Status',  type: 'enum',   enumOptions: ['draft', 'final'],
    accessor: r => r.status },
  { key: 'notes',   label: 'Notes',   defaultVisible: false,   // hidden by default
    accessor: r => r.notes },
];

<DataTable<MyRow>
  id="invoices.main"                              // stable; used as localStorage key — must be globally unique
  data={rows}
  columns={COLUMNS}
  rowKey={r => r.id}
  exportFilename="invoices"
  defaultSort={{ key: 'date', direction: 'desc' }}
  emptyMessage="No invoices yet"
  rowActions={r => <Button onClick={() => edit(r)}>Edit</Button>}
/>
```

**Column types:** `string` (default), `number`, `date`, `enum`. Behaviour of sort + filter is type-aware.

**`id` naming convention:** `<pagename>.<tablename>` — e.g. `invoices.main`, `gstr1.b2b`, `anomaly.high_frequency`, `customer360.invoices`. Must be globally unique (drives localStorage key isolation).

**`exportValue` field:** provide when the `format` renders UI elements (badges, icons, links) that would pollute the CSV. Return a raw string or number:
```tsx
{ key: 'amount', ..., format: v => `₹${...}`, exportValue: r => r.amount }
```

**`defaultVisible: false`:** use for noisy/rarely-needed columns (e.g. internal IDs, long notes, timestamps). They appear in the column picker but are hidden by default.

**Per-table localStorage keys** (all JSON):
- `dt.{id}.sort` — `{ key, direction } | null`
- `dt.{id}.filters` — `{ [colKey]: filterValue }`
- `dt.{id}.visible` — `string[]` of column keys

**Acceptable exceptions** (raw `<table>` is OK):
- Diff/comparison displays (e.g. `InvoiceRevisionDialog` old→new change rows) — structured layout, not a data grid
- Expandable sub-panels nested inside a DataTable row (e.g. RoyaltyPassesPage consumption sub-table)
- GSTR-3B summary sections (single aggregated row per tax type, not sortable/filterable data)

**Pages migrated (complete — all data grids use DataTable):**
ProductsPage · PartiesPage · InvoicesPage · QuotationsPage · PaymentsPage · LedgerPage · ProductInventoryPage · InventoryPage · TokenPageV1 · AuditPage · UserManagementPage · CompliancePage · NotificationsPage · AnprEventsPage · AnprTripsPage · WriteOffsReportPage · GstSplitReportPage · PricingMatrixPage · ProductionPage · BranchAdminPage · CreditDebitNotesPage · DeliveryChallansPage · PrivateAdminPage · PrivateInvoicesPage · GstReportsPage · RoyaltyPassesPage · CustomerProfilePage · AnomalyReportPage · Gstr2bReconcilePage

### `ResizableSplit` — draggable two-pane split

`frontend/src/components/ResizableSplit.tsx`. Horizontal (left/right) or vertical (top/bottom) split with a visible grip-pill divider. Drag to resize, double-click to reset, pointer-events + body cursor lock during drag, sizes persist in `localStorage` under the `storageKey` prop. Min/max bounds configurable. No external deps. Used on `/tokens-v1` to split Form vs Cameras+List and Cameras vs List.

### `ErrorBoundary` — global runtime-error catcher

`frontend/src/components/ErrorBoundary.tsx`. Wraps the entire `<Routes>` tree inside `AppLayout`. Any uncaught render-time exception in any page renders a friendly fallback showing the actual error name + message + first 8 lines of component stack, with "Try again" / "Go to Dashboard" / "Reload" buttons. Logs full error to `console.error`. Without this, runtime errors used to white-screen the whole app — critical safety net.

### Pydantic Decimal → JSON string gotcha (`.toFixed()` rule)

Pydantic V2 serialises `Decimal` fields as **JSON strings** (to avoid float precision loss). Frontend TS interfaces type them as `number`, but at runtime they arrive as `"500.00"`, not `500.00`. **Calling `.toFixed()` directly on a Decimal field throws `TypeError: t.toFixed is not a function`.**

Rule: any `.toFixed()` call on a value originating from an API response must coerce via `Number(value ?? 0)` first:

```ts
// ❌ partyStats.lifetime_tonnage.toFixed(3)     // may crash
// ✅ Number(partyStats.lifetime_tonnage ?? 0).toFixed(3)
```

Arithmetic operators (`/`, `-`, `*`, `Math.abs`) coerce implicitly, so `("500"/1000).toFixed(2)` works fine. Only **direct** method calls on the string break.

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
| Vehicle Type dropdown | Admin-configurable vehicle types via Settings; GET/PUT `/api/v1/app-settings/vehicle-types`; VehiclesPage dynamic dropdown + Badge per vehicle; admin gear icon → manage dialog |
| GST eInvoice (IRN) | NIC eInvoice API integration: auto-generate IRN on finalize (B2B+GSTIN); manual retry/cancel; IRN+QR in PDF; `integrations/einvoice/` module (builder+client); Settings → eInvoice tab; InvoicesPage IRN status badges + action buttons; non-blocking (failure doesn't block finalization) |
| Invoice Revision/Versioning | Admin/accountant can create revision of finalized invoice → new draft with revision_no+1; finalization assigns `INV/24-25/0001/Rv2` number; `invoice_revisions` table stores JSONB snapshot + structured diff; InvoiceRevisionDialog: revision timeline + side-by-side diff (header/amounts/items/eInvoice sections); `invoice_revised` notification event; compare any two versions via GET compare endpoint |
| Multi-Tenant SaaS | Separate database per client within single PG container; `MULTI_TENANT=true` activates; `weighbridge_master` DB for tenant registry; `wb_<slug>` databases per client; TenantMiddleware extracts tenant from JWT ContextVar; tenant-aware background tasks; per-tenant WeightScaleManager; Super-admin API for tenant CRUD; Docker + init scripts; parallel Windows (PowerShell) + Linux (bash) management scripts; frontend Company Code login field; zero data interchange risk |
| Dual-stage camera capture | Snapshots captured at both 1st and 2nd weight events; `weight_stage` column on `token_snapshots`; unique constraint `(token_id, camera_id, weight_stage)`; mock snapshot seeding endpoint for dev/test |
| Snapshot Search | SnapshotSearchPage: search camera images by token number, vehicle number, or date range; results grouped by token with 1st/2nd weight sections; lightbox viewer; date presets; pagination; `GET /api/v1/cameras/search` endpoint |
| Volume-based tokens | `POST /api/v1/tokens/volume` — single-call create + complete + auto-invoice for trucks not weighed on the bridge. Computes `net_weight = volume_cft × product.bulk_density(kg/CFT)`. `products.bulk_density` set on Products page (kg/CFT). TokenPage adds Measurement Method toggle (Weighbridge / Volume) with CFT input and live weight preview. **Canonical volume unit is CFT** (cubic feet — Indian stone-crusher industry standard); m³ has been removed from the UI |
| Royalty P1+P3 | `tokens.transit_pass_id` FK — operator links purchase token to its royalty/transit pass at creation. Auto-draw on completion: `_auto_consume_royalty_pass()` deducts `net_weight_mt` from the pass (non-blocking, swallows errors). Variance tracking per consumption row (`authorized_mt`, `actual_mt`, `variance_mt`). `RoyaltyPassesPage` P3: expandable per-pass consumption history with variance colour-coding, ₹ Royalty Paid card in reconciliation strip, CSV export |
| Fraud / Anomaly Analytics (H3-C) | `GET /api/v1/reports/anomalies` runs 7 detectors: high-frequency trips, weight variance >25% from 30-day mean, tare deviation >200 kg from master, invoice leakage (completed token, no final invoice after 6 h), after-hours activity (outside 05–21 IST), suspiciously round weighbridge weights (divisible by 1000 kg), unlinked purchase loads (no transit_pass_id). Per-detector try/except — one failure never blocks others. Thresholds configurable via `anomaly_config` in `app_settings`. `AnomalyReportPage` at Reports → Anomaly tab; auto-expands flagged detectors; overall severity banner |
| Unmanned Barrier Relay (H3-D) | `backend/app/services/barrier.py` fires a GET/POST to a configured HTTP relay URL (ESP8266/smart relay board) when ANPR detects a registered vehicle. Unknown plates never trigger the barrier. `asyncio.create_task()` in `_handle_detection()` — fire-and-forget, no latency on ANPR response. `GET/PUT/POST /api/v1/app-settings/barrier-config` + test endpoint. Settings → Barrier tab with direction toggles, URL, method, open param, duration, Basic Auth, Test button |

### ❌ Pending

| Feature | Priority | Notes |
|---|---|---|
| Vehicle report | Low | Vehicle-wise tonnage + revenue analytics |
| Weight scale Settings tab | Low | UI for serial port config (currently via API only) |

### 🔮 Future Phases

| Feature | Phase |
|---|---|
| Customer portal (read-only party view) | 6 |
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

# Multi-tenant (set to true for cloud SaaS deployment)
MULTI_TENANT=false
MASTER_DATABASE_URL=postgresql+asyncpg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge_master
MASTER_DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge_master
SUPER_ADMIN_SECRET=change-this-to-a-strong-secret
```

---

## Code Review

| Codex will review your output once you are done.

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
| 2026-04-13 | Vehicle Type dropdown: admin-configurable vehicle types via app_settings; GET/PUT endpoints; VehiclesPage dynamic dropdown with Badge; admin manage dialog (add/remove types) |
| 2026-04-13 | GST eInvoice: NIC API integration module (builder.py + client.py) in integrations/einvoice/; 8 new DB columns on invoices (irn, ack_no, ack_date, qr_code, signed_invoice, einvoice_status, einvoice_error, irn_cancelled_at) |
| 2026-04-13 | eInvoice: auto-IRN on finalize (non-blocking), manual generate-irn + cancel-irn endpoints; config endpoints in app_settings; IRN/QR section in invoice PDF template |
| 2026-04-13 | eInvoice: InvoicesPage IRN status badges (green/red/grey) + retry/cancel action buttons; SettingsPage eInvoice config tab (environment, credentials, test connection, auto-generate toggle) |
| 2026-04-13 | PDF template: IRN section (IRN hash + Ack No/Date + QR code image) at top of each copy; "Computer Generated Invoice" footer |
| 2026-04-13 | Dependencies: qrcode[pil]>=7.4 added to requirements.txt for eInvoice QR code generation |
| 2026-04-13 | Invoice Revision system: invoice_revisions table (JSONB snapshot + structured diff); revision_no + original_invoice_id columns on invoices |
| 2026-04-13 | Invoice Revision: POST /{id}/create-revision (admin/accountant); GET /{id}/revisions (chain); GET /{id}/compare/{other_id} (diff); revision invoice_no format: INV/24-25/0001/Rv2 |
| 2026-04-13 | Invoice Revision: compute_invoice_diff() utility in utils/invoice_diff.py — structured diff covering header, amounts, items (added/removed/modified by product_id), eInvoice fields |
| 2026-04-13 | Invoice Revision: InvoiceRevisionDialog component — collapsible timeline + version compare selectors + DiffView with ChangeRow/ItemBadge sub-components |
| 2026-04-13 | Invoice Revision: InvoicesPage — purple Rv{n} badge on revision invoices; Create Revision (GitFork) button for final invoices; View History (History) button for multi-version invoices |
| 2026-04-13 | Invoice Revision: invoice_revised notification event (email/SMS/Telegram templates); dual-fires invoice_finalized+invoice_revised on revision finalization |
| 2026-04-13 | Token vehicle_type field: operator can select vehicle type (truck/tractor/etc.) at token creation; auto-fills from vehicle master when registered vehicle selected; shown in token list, weight dialog, and TokenDetailModal; uses admin-configurable vehicle types list |
| 2026-04-13 | Multi-Tenant SaaS: separate database per client (wb_<slug>) within single PG Docker container; backward-compatible (MULTI_TENANT=false keeps single-DB); TenantMiddleware + ContextVar routing; tenant-aware background tasks (notifications, cameras); per-tenant WeightScaleManager; Super-admin API (/api/v1/admin/tenants); docker-compose.yml with PG tuning (shared_buffers=2GB, max_connections=300); init-multi-db.sh Docker entrypoint; 4 management scripts (setup-docker.sh/ps1, manage-tenant.sh/ps1); frontend: Company Code field on login + tenant_slug in sessionStorage + WebSocket tenant param |
| 2026-04-13 | Multi-Tenant: 11 new files (multitenancy package: context/models/master_db/registry/middleware/router, schemas/tenant, ddl.py, docker/init-multi-db.sh, scripts/*); 14 modified files (config, database, dependencies, auth, main, weight, tokens, invoices, payments, cameras, docker-compose, LoginPage, useAuth, useWeight) |
| 2026-04-14 | Dual-stage camera capture: `weight_stage` column on token_snapshots; snapshots captured at both 1st and 2nd weight; unique constraint `(token_id, camera_id, weight_stage)`; DDL migration; tokens.py triggers capture for all token types at both weight events |
| 2026-04-14 | Snapshot Search page: `GET /api/v1/cameras/search` endpoint (search by token_no/vehicle_no + date range); SnapshotSearchPage.tsx with grouped results, 1st/2nd weight sections, lightbox viewer, date presets, pagination; sidebar entry under Daily Work |
| 2026-04-14 | Mock snapshot seeding: `POST /api/v1/cameras/mock-snapshots/{token_id}` generates PIL test images for both weight stages and cameras (4 images per token) |
| 2026-05-26 | Bulk density + volume-based tokens: `products.bulk_density` (NUMERIC t/m³); `tokens.weight_method` + `tokens.volume_m3`; new `POST /api/v1/tokens/volume` endpoint computes weight as `volume_m3 × bulk_density × 1000` and creates+completes+auto-invoices in one call; ProductsPage shows + edits bulk_density; TokenPage adds Measurement Method toggle (Weighbridge / Volume) with m³/ft³ unit conversion and live computed weight preview; seed_tenant_demo.py seeds industry-standard density values for all 13 crusher products |
| 2026-05-26 | Customer Pricing Matrix (Enh #1): backend already had party_rates; added `GET /api/v1/parties/{id}/effective-rate/{product_id}`, `GET /api/v1/parties/rates/matrix`, `POST /api/v1/parties/{id}/rates/bulk`, `DELETE /api/v1/parties/{id}/rates/{product_id}`; manual invoice POST now applies party_rates server-side as a safety net when client sends rate=0; PricingMatrixPage with party picker + per-product rate editor + copy-from-party + reset-all |
| 2026-05-26 | Finished-goods Product Inventory (Enh #2): new `product_stock` (current_stock, min_stock_level, last_alerted_at) + `product_stock_movements` (append-only audit, signed quantity, types: opening/sale/purchase/adjustment/cycle_output/sale_cancelled/purchase_cancelled) tables; auto-postings on invoice finalise (sale=down, purchase=up), invoice cancel (reverse), production cycle finalise (up); endpoints: list with status pills, low-only filter, set min level, manual adjustment, set opening stock, paginated movement log; ProductInventoryPage with summary cards, filter tabs, Adjust/History dialogs |
| 2026-05-26 | Low-product-stock notifications (Enh #3): new `low_product_stock` event with default Telegram template; hourly background loop `_low_stock_alert_loop` scans `product_stock WHERE current_stock <= min_stock_level`; 24h per-row throttle via `product_stock.last_alerted_at`; multi-tenant aware (iterates all active tenants per CLAUDE.md pattern) |
| 2026-05-26 | Production cycles + yield tracking (Enh #5): new `production_cycles` (one per company per day, input_kg, stage1/2/3 outputs) + `production_cycle_outputs` (per-product Stage 4 finished weights) tables; endpoints: CRUD + `POST /cycles/{id}/finalise` (posts each output to product_stock as `cycle_output` movement); computed metrics — yield_pct = total_output/input × 100, belt_loss_pct = (stage3 − total_output) / stage3 × 100, wastage_kg = input − total_output; ProductionPage entry UI with live metrics preview; ProductionDashboardPage with yield trend (line), wastage by stage (stacked bar — orange=belt loss), top product outputs (horizontal bar), 4 KPI cards including conveyor-belt avg loss; 1-day cycle, manual input weight (per locked-in design decisions) |
| 2026-05-26 | Production stage defaults: configurable per-stage names, loss-type labels (industry terminology), expected yield %, and warning thresholds. Stored in `app_settings` under key `production.stage_defaults` as JSON. Industry defaults: S1 Primary Crushing (Dust & Spillage Loss, 97.5%), S2 Secondary Crushing (Dust & Spillage Loss, 97%), S3 Screening (Oversize Reject, 94%), S4 Washing/Conveyor Belt (Silt / Wash Loss, 91%) → compound plant yield 80.8%. New endpoints `GET/PUT /api/v1/production/stage-defaults`. Production cycle entry rebuilt with per-stage cards showing live yield % vs target with green/amber/red variance badges. ProductionSettingsPage at `/production/settings` for tuning. Dashboard adds target reference line on yield chart, "vs Target" variance KPI card, and stacked-bar labels from configured stage names |
| 2026-05-26 | Reusable `<DataTable<T>>` component (`frontend/src/components/DataTable.tsx`): generic sortable / per-column filterable / column-visibility toggleable / CSV-exportable table. Type-aware sort + filter (`string`/`number`/`date`/`enum`). Per-table state persisted to localStorage under `dt.{id}.{sort\|filters\|visible}` keys. Self-contained popover (no extra deps). First migration: ProductionPage cycles table — added a "Products" column showing badges of finished products + tonnage per cycle, CSV export, gear-icon column picker, and filter row. Pattern documented in CLAUDE.md → "Shared UI Components" section for incremental migration of remaining tables (Invoices, Products, Parties, etc.). |
| 2026-05-31 | Tokens: dual-unit display (MT + CFT) everywhere. PDF macro `format_wt_dual` renders gross/tare/net in both MT and CFT (computed from `volume_m3 × bulk_density`). TokenPage CSV export adds "Net (CFT)" column. Volume Tokens and weighbridge tokens render identically. |
| 2026-05-31 | TokenPage: inline party-add. `+` button next to the Party Select opens a quick-create dialog (name, party_type, GSTIN, phone, billing city/state). Newly created party is selected automatically. |
| 2026-05-31 | Invoice write-off: `POST /api/v1/invoices/{id}/write-off` (admin + accountant). Records `write_off_amount`/`reason`/`at`/`by`; closes balance (sets `payment_status='paid'` when zero, else `'partial'`); writes a `write_off` audit-log entry. DB columns `write_off_amount NUMERIC(14,2)`, `write_off_reason VARCHAR(500)`, `write_off_at TIMESTAMPTZ`, `write_off_by UUID -> users`. InvoicesPage adds amber XCircle button next to Record Payment + a `W/O` badge with hover-detail on written-off rows. |
| 2026-05-31 | Customer 360 view: `GET /api/v1/parties/{id}/360` returns one-shot aggregate (header + KPIs + aging buckets + last 20 invoices + last 20 payments + custom rates + lifetime tonnage). New `CustomerProfilePage` at `/customers/:id` with 8 KPI cards, stacked aging chart, 3 tabs (Invoices / Payments / Pricing), and quick-action footer. Dashboard Top Customers rows now link to `/customers/:id`; Outstanding KPI card links to `/ledger?tab=outstanding`. Parties names + Ledger outstanding party names are now clickable hyperlinks. Top-customers backend response includes `party_id` for linkability. |
| 2026-05-31 | **Operator Kiosk Mode** (BCG strategic review · Sprint 1): new `/operator` route — full-bleed, no sidebar, no chrome. Three-screen state machine (Arrival → Weighing → Done) built for low-literacy operators. Every primary control ≥64px, vocabulary action-oriented ("Truck OUT" not "Sale Token"), photo-tile pickers (colored-circle avatars + initials, since `products.image` doesn't exist yet), tyre-count quick-select that auto-routes to `/tokens/volume` for skip-the-bridge tokens. Backend: new `GET /api/v1/tokens/last-by-vehicle/{plate}` powers "Same as last time?" smart-suggest. Web Speech API voice confirmation post-capture ("X tonne captured. Truck can move."). Floating red "Need Help" SOS button on every screen → modal with admin phone numbers (zero-config via new `GET /api/v1/app-settings/manager-contacts`, falls back to active admins with phone). Users with `role='operator'` land here automatically on login via `HomeRedirect`; power-users keep `/tokens-v1` (link in top bar). |
| 2026-05-31 | Weight slip rewrite for volume tokens: new `tokens.tyre_count SMALLINT` column (4/6/8/10/12). Kiosk now persists tyre_count via both `/tokens` and `/tokens/volume` endpoints (added `tyre_count` to `TokenCreate` + `TokenVolumeCreate` schemas). `token_a4.html` and `token_thermal.html` rewritten with `weight_method`-based branching: weighbridge slips keep the gross/tare/net table (now MT-primary on thermal too); volume slips show a "VOLUME · NO BRIDGE" badge plus a 3-cell calculation block (Volume m³+CFT · Density t/m³ · Truck class N-tyre) and the equation `vol × density = MT` rendered as text. Both modes now show tyre count + truck class in the header, driver name+phone if present, GSTIN in address line, remarks, and bulk density next to the material name. Net weight rendered identically prominent in both modes. |
| 2026-05-31 | **Owner Dashboard Sprint 2 — exception-first home** (BCG review). New `OwnerDashboardPage` at `/` (default for non-operators); old chart-heavy dashboard moved to `/dashboard-legacy`. Traffic-light header (healthy/warning/critical) drives 4 action cards: Overdue Customers (with one-tap WhatsApp batch reminder), Low Stock (jumps to Product Inventory), Compliance Expiring (jumps to item detail), Yield Variance (jumps to Production Dashboard). Revenue strip shows today vs 30-day median with trend arrow. Auto-refresh every 60 s. Mobile-first responsive at 360 px. Backend: new `GET /api/v1/dashboard/exceptions` one-shot aggregator (overdue customers + low stock + compliance + yield + today_revenue), `POST /api/v1/dashboard/whatsapp-overdue` for batch reminders. Two new default templates seeded: `payment_overdue_reminder` (whatsapp + sms + email) and `owner_digest` (telegram). New background loop `_owner_digest_loop` runs hourly, fires at configured time (default 20:00) per-tenant, sends daily brief via Telegram to all `notification_recipients` subscribed to `owner_digest` event. Configurable send time via `app_settings.owner_digest.time`. |
| 2026-05-31 | **Sidebar consolidation Sprint 3** (BCG review). Reduced sidebar from 28 items / 5 groups → 8 top-level items + a single admin gear dropdown. Hubs: Sales (Bills + Estimates), Materials (Catalog + Rates + Stock + Production×3), Operations (Vehicles + Store + Camera + Snapshots), Reports (Payments + Statement + GST + P&L + Compliance + Activity). Top-level items: Dashboard · Trips (was Token) · Sales · Purchases · Customers (was Parties) · Materials · Operations · Reports. Admin items (Settings + Users + Permissions + Branding + Notifications + Backup + Import) move to gear-icon dropup in the user/logout row. All existing routes preserved — `/invoices`, `/parties`, `/audit` etc. still work as standalone pages, so bookmarks and email deep-links are unaffected. Sidebar permission check expanded: a role with any child-path permission unlocks the hub link (`HUB_CHILDREN` map in Sidebar.tsx). `/reports` now serves `ReportsHubPage` (default tab = old reports page); legacy ReportsPage kept reachable at `/reports-classic`. |
| 2026-06-01 | Dashboard partial-failure tolerance: `/api/v1/dashboard/exceptions` SQL rewritten. `func.max(today - Invoice.due_date)` (PG/SA quirk) replaced with `func.min(Invoice.due_date)` + Python date math. Each section (overdue/low-stock/compliance/yield/revenue) wrapped in its own try/except so one slow query never 500s the whole dashboard. Eliminates 502s on the new OwnerDashboardPage. |
| 2026-06-01 | Bug pack: (1) Invoice `due_date` was never persisted on create — added `due_date = invoice_date + party.payment_terms_days` in both `routers/invoices.py:create_invoice` and `routers/tokens.py:_auto_create_invoice` (auto-invoice on token completion). Backfill SQL provided. (2) Trip page hid volume tokens — `DEFAULT_VISIBLE_STATUSES` now includes `COMPLETED` (volume tokens are auto-completed on creation). (3) Manual weight entry now accepts MT (was kg); WeightCaptureDialog converts `parseFloat(mt) × 1000` at API boundary, label "(MT)", step `0.001`, kg shown as subtitle. (4) Parties name hyperlinks made obvious — added inline `ExternalLink` icon next to the link + dedicated 🔗 button in row actions. |
| 2026-06-01 | Security: `npm audit fix` resolved all 12 vulnerabilities (transitive bumps only — axios + vite + esbuild). One TS regression in PrintButton.tsx (axios 1.12 stricter header types) fixed by coercing response header: `const contentType = typeof rawType === 'string' ? rawType : String(rawType ?? '')`. |
| 2026-06-01 | **Write-off feature pack** (P&L + mass + ledger + 360). (a) Single-invoice write-off now updates `party.current_balance` (silent bug — was only writing audit row before). (b) New `POST /api/v1/invoices/write-off-bulk` accepts `{invoice_ids:[], reason}`, applies per-party balance deltas once, returns `{written, skipped, total_amount, parties_affected}`. (c) New `GET /api/v1/reports/write-offs` — date range, per-customer count + total, all rows; powers new `WriteOffsReportPage` (KPI cards + 2 DataTables + CSV) at `/reports?tab=write-offs`. (d) `/api/v1/reports/profit-loss` now computes `net_profit = gross_profit − total_write_offs` so write-offs flow through to P&L. (e) Ledger fix: party-wise drill-down accepts `?party=<id>` URL param + now includes write-off rows. (f) Customer 360 stats include `lifetime_written_off` + `write_off_count`. (g) InvoicesPage adds row checkbox + sticky bulk-action bar with "Write-off N invoices" button. |
| 2026-06-01 | **MT-first audit** — every user-facing weight display now shows MT (was a mix of kg and MT). DashboardPage `Number(t.first_weight) / 1000`; PrivateAdminPage column header "Net Wt (MT)"; TokenPage CSV columns relabelled; TokenPageV1 + TokenDetailModal `wFmt` returns `(kg/1000).toFixed(3) + ' MT'`; CameraScalePage shows MT large + kg small; production cycle form rebuilt in MT — `fmtKg` → `fmtMt`, state in MT, `mtToKg()` only at save boundary, `kgToMtStr` on edit-load, labels "Input (MT)" / "Output (MT)"; `utils/invoice_diff.py` labels + values converted to MT (3dp). API/DB still stores kg as the canonical unit — conversion happens at API boundary only. |
| 2026-06-01 | **Raw material tracking** on production cycles. New columns `products.is_raw_material BOOLEAN` + `production_cycles.raw_material_id UUID → products.id`. ProductCreate/Update payloads accept the flag; ProductsPage adds "Raw material?" toggle. Production cycle entry shows raw-material picker (filtered to `is_raw_material=true`). On finalise, `post_cycle_input()` posts a NEGATIVE `cycle_input` movement against the raw material (consumption) and `post_cycle_outputs()` posts POSITIVE `cycle_output` movements for each finished product — closes the loop: purchase invoice → raw stock up · cycle finalise → raw stock down + finished stock up · sale invoice → finished stock down. |
| 2026-06-01 | Customer 360 discoverability: new `CustomerPickerPage` at `/customers` — card grid of all parties with initials avatar, type badge, phone, city, current_balance. Filter chips (All / Customers / Suppliers) + search. Replaces the previous "no way to find a customer's 360 page" gap. |
| 2026-06-02 | **Global ErrorBoundary** (`frontend/src/components/ErrorBoundary.tsx`) wraps `<Routes>` in App.tsx — catches runtime React errors, surfaces `error.name + error.message + first 8 lines of component stack` with Try-again / Dashboard / Reload buttons. Replaces silent white-screens. |
| 2026-06-02 | **Pydantic Decimal → JSON string** gotcha fix. Pydantic V2 serialises `Decimal` as a JSON string, but TypeScript types declared `number`, causing `TypeError: t.toFixed is not a function` (white screen on CustomerProfilePage). Convention now documented in CLAUDE.md → Shared UI Components: **ALWAYS** `Number(value ?? 0).toFixed(...)`. CustomerProfilePage rewritten with defensive `Number()` coercion + `?? []` on every list. |
| 2026-06-02 | **Payment-mode drives invoice tax_type + Tally gating**. New `parties.default_payment_mode VARCHAR(20)` (`'cash'` | `'online'`). On invoice create, `effective_tax_type` is derived: `cash` → `non_gst` (Bill of Supply); `online` → respects payload `tax_type` (defaults GST). Tally sync now returns 400 if `invoice.tax_type != 'gst'`; bulk-sync filter adds `Invoice.tax_type == 'gst'`; `/tally/pending` excludes non-GST. New `GET /api/v1/reports/gst-split` returns summary + monthly + top-cash-customers; new `GstSplitReportPage` at `/reports?tab=gst-split` (KPI cards + stacked monthly bar + per-month table + top cash customers). Parties form adds "Mode of Payment" select. |
| 2026-06-02 | `parties.default_payment_mode` default flipped from `'online'` → `'cash'`. Rationale: typical stone-crusher SME walk-in customers are cash-based and only need a Bill of Supply; GST customers are the exception and flagged explicitly. Schema default, model default, and DDL `ALTER COLUMN ... SET DEFAULT 'cash'` all updated. |
| 2026-06-06 | **CFT-only volume system** (BREAKING storage-unit change). m³ removed from the entire app; CFT is now the canonical volume unit and kg/CFT the canonical density unit — matches Indian stone-crusher industry practice. (a) Schema: `tokens.volume_m3` renamed → `volume_cft NUMERIC(10,3)`; `products.bulk_density` semantics changed from t/m³ to kg/CFT (column name preserved). (b) One-shot data migration via guarded DO block in `ddl.py` — marker `app_settings.units_migrated_to_cft_v1` prevents re-running; on existing tenants: `UPDATE tokens SET volume_cft = volume_m3 × 35.3147` + `DROP COLUMN volume_m3` + `UPDATE products SET bulk_density = bulk_density × 28.3168`. Idempotent — new tenants no-op past the marker insert. (c) Calculation: `weight_kg = volume_cft × bulk_density(kg/CFT)` (was `m3 × t/m3 × 1000`). Round-trip drift < 0.001 % on real data. (d) Backend: Token model + schemas + `POST /tokens/volume` payload field renamed; PDF templates (`token_a4.html` + `token_thermal.html`) rewritten to show CFT and kg/CFT only — no m³ display anywhere. (e) Frontend: ProductsPage label "Bulk Density (kg/CFT)" + typical values (aggregate 42.5, sand 48.1, GSB 53.8, stone dust 43.9) + tip showing t/m³ × 28.32 conversion; TokenPageV1 m³/ft³ unit selector removed, `TYRE_VOLUME_M3` → `TYRE_VOLUME_CFT` (106/247/353/459/600), `volumeM3` → `volumeCft`, dualFmt CFT formula simplified to `kg ÷ kg_per_cft`; OperatorKioskPage tyre tiles show CFT, voice prompt says "cubic feet"; types/index.ts `Token.volume_m3` → `volume_cft`. (f) Seed script (`seed_tenant_demo.py`) bulk densities + volume tokens updated to kg/CFT + CFT. (g) eInvoice NIC unit map already mapped `cft` → `CFT`, no change. |
| 2026-06-16 | **Production → inventory now auto-posts on save** (was finalise-only). Creating a production cycle immediately credits finished-goods **Stock on Hand** (`product_stock`) and debits the raw material — no separate "Finalise" click. `create_cycle` sets `is_finalised=True` + calls new `_post_cycle_stock()`. Cycles are now **editable + deletable** with stock kept correct: `update_cycle` reverses the OLD postings (new `product_stock.reverse_cycle_stock()` — `cycle_output_cancelled` / `cycle_input_cancelled` movements) then re-posts the NEW values (net delta = new−old); `delete_cycle` reverses postings before deleting (no orphaned stock). Frontend ProductionPage: Edit/Delete always available (re-sync/reverse stock), messaging updated ("finished goods added to Stock on Hand"). Legacy draft cycles keep the Finalise button. |
| 2026-06-16 | **Horizon 3 (partial) — scaling + ITC** (multi-branch foundation + GSTR-2B; fraud + barrier deferred to a follow-up). **(A) Full multi-branch foundation (backward-compatible):** new `branches` table + Branch CRUD (`/api/v1/branches`, admin) + `GET /branches/current`. `branch_id` (NULLABLE → existing rows = implicit default branch, so current numbering/queries untouched) added to tokens, invoices, payment_receipts/vouchers, product_stock, production_cycles, users, number_sequences. Branch context = `get_current_branch_id` dependency (admins switch via `X-Branch-Id` header sent by the UI picker; others pinned to `user.branch_id`; None = all/default). **Per-branch numbering** — `next_gate_pass_no`/`next_doc_no`/`_next_invoice_no` take a `branch_id` and filter NULL-safely (`branch_id == None` → `IS NULL`), so each branch gets its own gap-free invoice/GP series and the default branch keeps its existing sequences (token_no is random per company-day → unchanged). `create_token`/`create_volume_token`/`create_invoice` stamp branch; token + invoice lists filter by active branch. Frontend: `BranchPicker` header dropdown + `BranchAdminPage` (`/admin/branches`) + sidebar entry + `api.ts` forwards `X-Branch-Id`. **DEFERRED:** per-branch *stock* (product_stock.product_id is globally UNIQUE — needs a constraint rework + `_get_or_create_stock_row` rewrite, not shipped untested); reports/dashboards not yet branch-scoped beyond token/invoice lists. ⚠️ per-branch numbering touches the gap-free invariant — verify on deploy. **(B) GSTR-2B ITC reconciliation:** new `POST /api/v1/reports/gstr2b-reconcile` (multipart 2B JSON upload, stateless — no writes). Parses `data.docdata.b2b` (tolerant of layout/field-name variants), matches against finalised purchase invoices by GSTIN + normalised invoice no (±₹1 tol) → matched / value-mismatch / in-2B-not-books (ITC available, enter these) / in-books-not-2B (ITC at risk, chase supplier) + ITC summary. `Gstr2bReconcilePage` (upload + 4 KPI cards + 4 buckets) as a Reports-hub "GSTR-2B (ITC)" tab. |
| 2026-06-16 | **Horizon 2 — differentiation pack** (3 features, BCG gap review). **(A) Royalty / mining transit-pass:** new `royalty_passes` + `royalty_pass_consumptions` tables. Router `/api/v1/royalty` — CRUD passes; `POST /passes/{id}/consume` (records a draw-down, auto-exhausts at zero balance, overrun flagged); `GET /reconciliation` (authorised vs consumed vs completed-purchase-token inbound MT + "unaccounted" delta); `GET /alerts` (expiring within N days). `RoyaltyPassesPage` (reconciliation KPIs + utilisation bars + create/consume dialogs) → Materials hub "Royalty Passes" tab + `/royalty`. The killer stone-crusher differentiator. **(B) Customer portal + static UPI:** new `customer_users` table — a SEPARATE auth realm; JWTs carry `scope='customer'` + party_id so a portal token can't hit staff endpoints and a customer only sees their own party. `routers/portal.py` — dual-mode login (tenant from subdomain), `/me` (balance net of notes), `/invoices`, `/invoices/{id}/pdf` (ownership-enforced), `/statement`, `/payment-info`, `/change-password`; standalone bearer dep (not staff OAuth2). Admin mgmt on parties: `POST/GET/DELETE /parties/{id}/portal-account` + reset-password. Static UPI: `app-settings /upi-config` (vpa+payee+enabled) shown on the portal Pay tab as VPA + `upi://` deep link (no live gateway — manual reconciliation, per locked decision). Frontend: standalone `CustomerPortalPage` at `/portal` (own login + dashboard), `PortalAccessDialog` on Customer-360, Settings "UPI / Portal" tab. **(C) Offline resilience:** `lib/offlineQueue.ts` — token POSTs that fail on a network error (or while offline) are stored in localStorage and replayed on reconnect (+60s safety retry); server numbering stays gap-free (assigned at sync). TokenPageV1 weighbridge create queues offline ("Saved offline — will sync…"); `OfflineIndicator` header pill (Offline / N pending). PWA: `manifest.webmanifest` + `sw.js` app-shell SW (network-first nav → cached shell offline; `/api/*` never cached), registered in `main.tsx` (prod only). Agent: scale streams live (non-transactional) weight so it's NOT buffered (replaying stale weights would be wrong) — it already degrades gracefully + serves weight on local `:9002`; added a `cloud_online` status flag for observability. |
| 2026-06-16 | **Horizon 1 — compliance/commercial parity pack** (4 features, BCG gap review). **(1) Credit-limit enforcement (warn-only):** new `GET /api/v1/parties/{id}/credit-status` (outstanding vs limit, overdue, net of finalised credit/debit notes; status `ok\|near_limit\|overdue\|over_limit`). Reusable `<CreditStatusBanner partyId>` advisory banner wired into the token create form + invoice create/edit dialogs + delivery-challan dialog. NEVER blocks (per locked design decision) — surfaces, operator decides. **(2) Delivery Challan (GST Rule 55):** new `delivery_challans` + `delivery_challan_items` tables (own tables → never leak into GSTR-1/P&L/receivables). `DC/<FY>/NNNN` numbering via new shared `services/numbering.next_doc_no()` (generic gap-free row-locked allocator). Router `/api/v1/delivery-challans` (create/list/get/cancel/convert-to-invoice/PDF + generate-ewb/cancel-ewb). convert-to-invoice reuses the canonical `create_invoice` path. `delivery_challan.html` A4 print template. `DeliveryChallansPage` + Sales-hub "Challans" tab + `/delivery-challans` route. **(3) GST Credit/Debit Notes (CDNR):** reuse the invoices table with `invoice_type IN ('credit_note','debit_note')` (safe — every financial query already filters `invoice_type=='sale'/'purchase'`). New cols `invoices.reference_invoice_id` + `note_reason`. `POST /invoices/{id}/issue-note` (admin/accountant) clones a finalised invoice → DRAFT note; finalise assigns CN/DN number (`_invoice_prefix`); finalise skips product-stock + IRN for notes. Receivables net credit (−)/debit (+) notes in credit-status; Customer-360 outstanding loop excludes note types. GSTR-1 report gains a CDNR section. invoice PDF prints "Credit/Debit Note". `CreditDebitNotesPage` + Sales-hub "Notes" tab + `/credit-debit-notes` route. **(4) E-Way Bill (IRN-integrated + standalone):** invoice cols `ewb_date/ewb_valid_till/ewb_status/ewb_error/ewb_distance_km`. IRN-integrated: einvoice builder sends `EwbDtls` (vehicle+distance) so NIC mints the EWB with the IRN; `EInvoiceResult` carries `ewb_no/date/valid_till`, stamped in `_try_generate_irn`. Standalone `integrations/eway/{client,builder}.py` (mirrors einvoice — NIC auth+6h cache, retry, generate/cancel/Part-B, `demo_mode`) + `services/eway_service.py`. Endpoints: invoices + delivery-challans `/{id}/generate-ewb` + `/cancel-ewb`; `app-settings /eway-config` GET/PUT/test. Frontend: Generate-EWB action on InvoicesPage + DeliveryChallansPage; Settings → "E-Way Bill" tab. Needs separate NIC EWB credentials for live calls — Demo mode exercises the workflow until then. |
| 2026-06-12 | **Gate pass fully wired across the app** (previously only the ANPR happy-path issued one). (a) New shared helper `app/services/numbering.py::next_gate_pass_no()` — single gap-free, row-locked (`WITH FOR UPDATE`) allocator for `GP/25-26/NNNN`; `anpr.py::_next_gate_pass_no` now delegates to it so ANPR and manual paths can't diverge. (b) **Manual token creation now auto-issues a gate pass at entry** — both `create_token` (weighbridge, status OPEN) and `create_volume_token` allocate `gate_pass_no` via the shared helper, mirroring the ANPR auto-entry behaviour. So every truck gets a gate pass whether ANPR is on or off. (c) `TokenResponse` schema now exposes `gate_pass_no`, `source`, `anpr_entry_at`, `anpr_exit_at` (previously dropped — the auto gate pass was invisible to `GET /tokens`). (d) PDF slips (`token_a4.html` + `token_thermal.html`) print `gate_pass_no` (falling back to legacy free-text `gate_pass`) — the printed slip is now the physical gate pass. (e) Frontend: `Token` type gains the 4 fields; TokenPageV1 shows the GP number under the token # on each row + a Gate Pass CSV column; TokenDetailModal adds a Gate Pass card + gate-movement (in/out) panel. The legacy free-text `tokens.gate_pass` field is retained as an optional note. (f) **Accepted design tradeoff (code-reviewed):** the GP number is gap-FREE at allocation (no two trucks share one) but NOT gap-less over time — issued at gate ENTRY (token create), so a cancelled/abandoned token leaves a hole that maps to a real arrival event and is never reclaimed. This is intentional and differs from `token_no` (assigned at COMPLETED) / `invoice_no` (assigned at FINALISE). |
| 2026-06-11 | **CI/CD auto-deploy pipeline** (`.github/workflows/deploy.yml` + `scripts/ci-deploy.sh`). Every push to `main` SSHes into the Hostinger VPS and runs the deploy script: `git pull`, detect what changed, rebuild only the affected side (frontend `npm ci && npm run build` → nginx docroot, backend `pip install` if requirements changed + `systemctl restart weighbridge`), `nginx -t && systemctl reload nginx`, `curl /api/v1/health` rollback signal, append to `/var/log/weighbridge-deploy.log`. Workflow then purges Cloudflare cache (zone + token from repo secrets) and pings the live URL for sanity. `concurrency: deploy-vps` prevents overlapping runs. `paths-ignore` on `**/*.md`, `docs/**`, `plans/**` so doc-only commits don't deploy. `workflow_dispatch` for manual runs. Setup guide at `docs/CI_CD_SETUP.md` covers SSH-key generation on VPS, the 4 required GitHub secrets (`VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `VPS_PORT`) + 2 optional CF secrets, troubleshooting, and rollback procedure. Replaces the manual `ssh + git pull + npm run build + cp + reload` runbook that left 4+ commits un-deployed for a week. |
| 2026-06-08 | **ANPR daily movement report + Telegram digest.** Adds the user-friendly "one row per vehicle visit" view that the existing event log lacked. New endpoint `GET /api/v1/anpr/trips` joins tokens with anpr_entry_at OR anpr_exit_at populated → LEFT JOIN invoices (LATERAL — most recent) → LEFT JOIN parties + products. Returns paginated rows plus 6 roll-ups (entries, exits, currently_inside, total_tonnage_mt, total_revenue, avg_dwell_minutes). New `POST /anpr/daily-summary/send` fires the same context as Telegram on demand (admin button on the trips page). New `anpr_daily_summary` template seeded — lists top-20 trips with plate, entry/exit times, dwell, token #, gate pass, invoice no, amount. Scheduled daily fire wired into the existing `_owner_digest_loop` at the configured `owner_digest.time` (default 20:00) — gated by `anpr_config.daily_summary` (default TRUE) AND `anpr_config.enabled`, so tenants without ANPR see no behaviour change. New frontend page `AnprTripsPage` at `/anpr/trips` (also Operations Hub "Movement Report" tab) with DataTable + CSV export + date-range presets + "Send Daily Report" admin button. Settings → ANPR adds a "Send daily Telegram report" toggle bound to `anpr_config.daily_summary`. |
| 2026-06-08 | **ANPR (Automatic Number Plate Recognition) — backend + frontend v1.** Self-operated gate cameras detect plates, auto-issue gate passes, stamp entry/exit times, and notify the owner via Telegram. (a) Dual ingest sources: `POST /api/v1/anpr/detect` (Source A — local FastALPR worker via camera agent) + `POST /webhook/hikvision` and `/webhook/dahua` (Source B — on-camera ANPR webhooks, X-ANPR-Secret auth). Both funnel into one `_handle_detection()`. (b) Single-camera entry/exit decision with 3-layer dedup: 15 s SQL window → open-token-today → recently-completed-24h fallback. Plus a 5-min application guard on entry to stop double-token-creation. Unknown plates: token still created with `vehicle_no` only, `vehicle_id` NULL, event flagged `needs_review=TRUE` (1-char Levenshtein fuzzy match vs vehicle master). (c) Gate-pass auto-numbering reuses `NumberSequence(sequence_type='gate_pass')` with the same gap-free `WITH FOR UPDATE` row-lock pattern as invoice numbering — `GP/25-26/0001` format. Allocated only on ENTRY; EXIT reuses the entry's number. (d) DDL adds `anpr_events` table (plate_raw/normalized, vehicle_id, token_id, direction, confidence, source, snapshot_path, ocr_alternates JSONB, needs_review, indexes) + token columns `gate_pass_no`/`anpr_entry_at`/`anpr_exit_at`/`source` (manual\|anpr\|kiosk). Existing `tokens.gate_pass` free-text untouched. (e) Browsing: `GET /anpr/events` (filters), `/unmatched` queue, `POST /events/{id}/reassign`, `GET /stats` (entries/exits/inside/avg_dwell/by-day). (f) Config: `GET/PUT /anpr/config` with `webhook_secret` masked (`***`); `POST /config/test` for the Settings → ANPR "Run Test" button. (g) Notifications: 4 new Telegram templates seeded by `seed_default_templates()` — `anpr_entry`, `anpr_exit`, `anpr_unknown_plate`, `anpr_camera_down`. Recipients select via existing /notifications page. (h) Snapshots: `uploads/anpr/<YYYYMMDD>/<event_id>.jpg`. (i) Frontend: 3 new pages (`AnprEventsPage` with DataTable+CSV, `AnprLivePage` full-bleed wallboard auto-refresh 5s, `AnprReviewPage` for unmatched queue), 1 new component (`AnprStatsCard` on OwnerDashboardPage — hidden when ANPR off or no traffic), 1 new SettingsPage tab (engine choice, camera, confidence, fuzzy, auto-create-token, notify toggles, webhook secret, Test Detection button). Hooked into OperationsHub as "Gate Cameras" + "Plate Review" tabs. (j) Sidebar permission map (`HUB_CHILDREN['/operations']`) extended to include `/anpr/*`. (k) **ANPR is disabled by default** (`anpr_config.enabled=false`) — existing kiosk + manual flows are completely unaffected when ANPR is off. The agent ANPR worker (Source A FastALPR) + Hikvision/Dahua camera-side configuration land in a follow-up commit. |
| 2026-06-16 | **Sales-by-Status chart report.** New `GET /api/v1/reports/sales-by-status?from_date=&to_date=&granularity=` (day/week/month) — filters sale invoices in range, buckets by period, returns `summary` (Draft + Final/"Complete" + Cancelled counts & amounts; cancelled excluded from the chart series) + a time-bucketed `series` of Draft vs Final amounts. New `SalesStatusReportPage` at `/reports?tab=sales-status` (Reports hub "Sales by Status" tab): date range + day/week/month toggle, 4 KPI cards (Draft, Final/Complete, Total, Draft share %), a stacked recharts bar (Draft amber + Final emerald per period), a Draft-vs-Complete donut, and CSV export. Company-scoped via `current_user.company_id`. ("Complete" maps to the invoice `final` status; "Draft" = unfinalised.) |
| 2026-06-16 | **Royalty P1+P3.** P1: `tokens.transit_pass_id` FK column — operator links a purchase token to its royalty/transit pass at creation time. Auto-draw on token completion: `_auto_consume_royalty_pass()` (non-blocking, in both `record_second_weight` and `create_volume_token`, swallows all errors) deducts `net_weight_mt` from the pass balance and records `authorized_mt`, `actual_mt`, `variance_mt` per consumption row. Pass auto-marks `exhausted` when balance reaches zero. Overruns (actual > authorized) are recorded but never blocked. New `GET /api/v1/royalty/passes/{id}/consumptions` returns full consumption history with `token_no` batch-joined. P3 frontend: expandable per-pass consumption sub-table with green/amber/red variance column; 6th "Royalty paid ₹" KPI card in reconciliation strip; CSV export of pass register. Transit pass picker on TokenPageV1 (purchase tokens only, shows live balance, warns if < 5 MT remaining). |
| 2026-06-16 | **H3-C: Fraud / Anomaly Analytics.** New `GET /api/v1/reports/anomalies?date_from=&date_to=` runs 7 detectors: (1) high-frequency trips (same vehicle >8/day), (2) weight variance (>25% from 30-day rolling mean, min 3 samples), (3) tare deviation (token tare differs from vehicle master by >200 kg), (4) invoice leakage (COMPLETED tokens >6 h with no `final` invoice), (5) after-hours activity (before 05:00 or after 21:00 IST), (6) round weights (weighbridge net divisible by 1000 kg — possible manual override), (7) unlinked purchase loads (`transit_pass_id IS NULL`). Each detector runs in an isolated try/except — one failure never blocks others. Returns `{overall: high/medium/low/ok, detectors: {...}}`. Thresholds configurable via `GET/PUT /api/v1/reports/anomaly-config` (stored in `app_settings.anomaly_config`). New `AnomalyReportPage` at Reports hub → Anomaly tab: overall severity banner, 7 collapsible `DetectorCard` components that auto-expand on findings, CSV export. |
| 2026-06-16 | **H3-D: Unmanned Barrier Relay Trigger.** New `backend/app/services/barrier.py` — `trigger_barrier(db, direction, vehicle_no, gate_pass_no)` fires a GET or POST to a configured HTTP relay URL (supports ESP8266/ESP32 boards, smart relays, webhook endpoints). Loaded non-blocking via `asyncio.create_task()` inside `_handle_detection()` in `anpr.py` — only for registered vehicles (not `needs_review`). Unknown plates never open the gate. Config key `barrier_config` in `app_settings`: `enabled`, `trigger_entry/exit/unknown`, `http_url`, `http_method`, `http_open_param` (appended to URL, e.g. `?state=on&duration=5`), Basic Auth, timeout. New endpoints: `GET/PUT /api/v1/app-settings/barrier-config` + `POST /barrier-config/test` (fires one synthetic trigger). Settings → Barrier tab with all config fields + inline test result. Disabled by default. |
| 2026-06-20 | **DataTable universal migration.** All multi-row data tables across the app now use the shared `DataTable<T>` component — sortable, per-column filterable, column-show/hide, CSV export, localStorage-persisted preferences. 10 remaining pages migrated: BranchAdminPage · CreditDebitNotesPage · DeliveryChallansPage · PrivateAdminPage · PrivateInvoicesPage · GstReportsPage (B2B/B2C/HSN tabs) · RoyaltyPassesPage · CustomerProfilePage (invoices/payments/rates tabs) · AnomalyReportPage (7 per-detector DataTables) · Gstr2bReconcilePage (4 bucket tabs). Raw `<table>` HTML is now banned for data grids — documented as mandatory standard in CLAUDE.md → Shared UI Components. Zero TypeScript errors after migration. |
| 2026-06-20 | **BCG-style 4-section grouped navigation.** Sidebar restructured from 9 flat items into 4 labelled sections: **OPERATIONS** (Weighbridge hub — gate register + weigh tickets + movement report + cameras + ANPR), **COMMERCIAL** (Sales & CRM hub · Procurement hub), **RESOURCES** (Inventory & Production hub), **FINANCE & INTELLIGENCE** (Accounts hub · Analytics hub). 5 new hub pages created: `WeighbridgeHubPage` (`/weighbridge`), `ProcurementHubPage` (`/procurement`), `InventoryProductionHubPage` (`/inventory-hub`), `AccountsHubPage` (`/accounts`), `AnalyticsHubPage` (`/analytics`). `SalesHubPage` updated to include Customers as the first tab. `HUB_CHILDREN` permission expansion maps old stored role paths (e.g. `/gate`, `/purchase-invoices`) to new hub URLs automatically — no permission-store migration needed. Hindi i18n keys added for all new entries. All existing direct-URL routes preserved. |
| 2026-06-20 | **Accounting hardening pack (5 audit follow-ups; 51/51 tests + DB recompute check).** **(1) GSTR-3B + GSTR-1-JSON net credit/debit notes:** `/gstr3b` 3.1(a) outward taxable+tax now computed net of finalised GST credit (−) / debit (+) notes (adjustment exposed); `/gstr1-json` gained the **CDNR** block (notes to registered persons, GSTN portal format) — was absent, so credit notes never reached the filing and overstated liability. **(2) `party.current_balance` drift fixed:** new `app/services/balances.py::recompute_party_balance()` recomputes from source (opening + Σsale − Σpurchase + Σdebit − Σcredit, each net of payments & write-offs), idempotent. Wired into finalise / cancel / write-off (single+bulk — manual ± mutations removed) / payment receipt+voucher. **(3) Payment allocation guards:** `payments.py::_validate_allocations` rejects Σallocations > payment amount, allocation > invoice outstanding, and cross-party / cross-company allocation. **(4) Place of supply from GSTIN[0:2]:** `gst_service.party_place_of_supply()` keys CGST/SGST-vs-IGST off the GSTIN's registered-state digits (authoritative), falling back to billing_state_code; wired into all 8 callers (invoices ×4, quotations ×3, tokens ×1). **(5) Stock-summary totals no longer sum mixed units:** qty totals are now per-unit maps (MT/CFT/bag separate) + unit-agnostic `value_purchased`/`value_sold`; `ReportsPage` shows value totals + per-unit qty. |
| 2026-06-20 | **CRITICAL fix: per-statement DDL bootstrap.** `get_column_migrations()` listed `ALTER TABLE production_cycles ADD COLUMN raw_material_id` **before** the `CREATE TABLE production_cycles` in the same list. On any DB lacking that table, the ALTER raised "relation does not exist"; because `main.py::_apply_all_ddl` ran the WHOLE list in ONE transaction, that error aborted the transaction and the commit rolled back — so **every** statement after it silently never applied: `production_cycles`, `product_stock`, `branches`, `royalty_passes`, `delivery_challans`, `gate_passes`, `gate_pass_daily_seq`, `gate_camera_events`, `anpr_events`, `customer_users`. Result: Gate Register, Production, Product Inventory, Branches, Royalty, Challans, Credit/Debit Notes, ANPR, Customer Portal & GSTR-2B all 500'd on a missing relation (surfaced as the generic "Something went wrong. Try again."). Fix: `_apply_all_ddl` (and the multi-tenant `router.py` provisioner) now run **each** DDL statement in its **own** transaction — one failure is logged & skipped, all others apply; idempotent stmts self-heal next start. Also moved the `raw_material_id` ALTER after its CREATE so it applies on a fresh DB in one pass. Verified: all 10 missing tables create, 0 residual failures, gate-pass INSERT succeeds, no other ALTER-before-CREATE traps. Tables auto-create on the next backend restart (CI deploy). |
| 2026-06-20 | **Accounting-calculation audit + fixes** (senior-partner review; `backend/tests/test_accounting_audit.py`, 41/41 pass ×3). **(1) Volume-billing density-unit trap (CRITICAL):** Products density labels/hints (en+hi) said "kg/m³ (~1500)" while the backend stores & bills in **kg/CFT (~42.5)** — an operator following the old hint would over-bill every volume token ~35×. Relabelled to kg/CFT with correct typical values (aggregate 42.5, sand 48.1, GSB 53.8, stone dust 43.9) + "per cubic FOOT" warning. **(2) Grand-total round-off (HIGH):** `gst_service.calculate_invoice_totals` now rounds grand_total to the **nearest whole rupee** (standard Indian tax invoice); the previously-dead `round_off` column now carries the ± adjustment so the invoice still foots (`taxable+cgst+sgst+igst+freight+tcs+round_off==grand_total`). **(3) GSTR-1 excludes non-GST (HIGH/compliance):** added `tax_type='gst'` to GSTR-1 summary + JSON B2B/B2C/HSN selects so Bill-of-Supply sales no longer inflate GSTR-1 turnover (GSTR-3B already filtered). **(4) P&L on taxable basis (HIGH):** `/reports/profit-loss` revenue & COGS now use `taxable_amount` (ex-GST) not `grand_total`, and revenue is net of credit/debit notes. **(5) `dualFmt` display:** treated kg/CFT as kg/m³ — rewritten CFT-correct. **Verified-correct (no change):** Decimal-everywhere money, per-line GST on post-discount base, CGST/SGST never loses a paisa, non-GST→0 tax on all create paths, `amount_due=grand_total` at draft create on both manual+token paths, volume formula `volume_cft × bulk_density(kg/CFT)`, CFT migration constants. **Flagged for follow-up (not auto-fixed):** GSTR-3B 3.1(a) + GSTR-1-JSON CDNR note-netting; payment over-allocation guard; `party.current_balance` only half-maintained; reports not company-scoped (latent under per-tenant-DB). |
| 2026-06-20 | **Gate Management System** — guard-managed gate pass register for standard CP Plus 4MP IP cameras (not ANPR). New `gate_passes` + `gate_pass_daily_seq` + `gate_camera_events` tables (DDL in `ddl.py`). New role `gate_guard` (lands on `/gate` on login). Gate pass number: `GP/YYYY-MM-DD/NNN` — atomic daily reset using `INSERT … ON CONFLICT DO UPDATE`. Backend router `/api/v1/gate` (10 endpoints): create pass, list, summary (mismatch flag), update guard details, record exit (mandatory token link for weighbridge purpose), cancel, on-demand CP Plus snapshot, CP Plus vehicle-detection webhook, camera-events queue. Exit enforcement: `POST /passes/{id}/exit` returns HTTP 400 if `purpose='weighbridge'` and `token_id IS NULL`. CP Plus webhook uses `X-Gate-Secret` header auth. Background photo capture on entry/exit via `async_session_factory`. Gate camera config stored in `app_settings.gate_camera_config`. Frontend: `GatePassPage` at `/gate` with summary strip + Inside/All Today tabs + New Gate Pass + Exit dialogs with per-position `CaptureButton`. Sidebar "Gate Register" item (DoorOpen icon) visible when user has `/gate` permission. Settings → "Gate Cameras" tab for entry/exit camera URL/credentials, webhook secret, EOD alert time. |
| 2026-06-21 | **Full mobile PWA responsiveness.** App now installable via "Add to Home Screen" on Android (Chrome) and iOS (Safari) with a fully responsive UI. Changes: (a) `viewport-fit=cover` + safe-area inset CSS utilities (`pt-safe/pb-safe/pl-safe/pr-safe`) for iOS notch/home indicator. (b) `DialogContent` now `max-h-[calc(100dvh-4rem)] overflow-y-auto` — fixes all modal dialogs on iOS Safari (using `dvh` not `vh`). (c) `DataTable` gets `min-w-max` on the `<table>` and `whitespace-nowrap` + sticky-first-column (`sticky left-0 z-10`) on cells — enables proper horizontal scroll with pinned identifier column. (d) `App.tsx`: mobile main padding `pt-14 px-3 py-3` (clears 40px hamburger), hamburger enlarged to `h-10 w-10` (44px Apple HIG minimum), `pb-16 md:pb-0` bottom padding for nav bar. PWA install prompt (`beforeinstallprompt`) stored in `useRef`, shows as dismissable chip in top-right header. (e) New `MobileBottomNav` — `fixed bottom-0 md:hidden` 5-tab bar (Home/Weighbridge/Sales/Reports/More→sidebar) with `pb-[env(safe-area-inset-bottom)]` for iPhone home indicator. (f) New `useIsMobile` hook (matchMedia listener). (g) `TokenPageV1` mobile early-return: stacked layout (ScaleStatus → CreateTokenForm → 2-col cameras → compact card-list with weigh + detail buttons); desktop ResizableSplit unchanged. (h) `GstReportsPage` TabsList + nested GSTR-1 TabsList: `flex-wrap h-auto`. (i) `Sidebar` admin dropup: `max-w-[calc(100vw-1.5rem)]` to prevent right-edge overflow. (j) Gate Pass + Token hyperlinks in register pages: click gate-pass-no → `GatePassDetailDialog` (with entry/exit photos); click token-no → existing `TokenDetailModal`. |
| 2026-06-21 | **Gate Pass + Token Register report pages.** Two new admin report pages added to `AnalyticsHubPage` ("Gate Pass Register" + "Token Register" tabs). `GET /api/v1/reports/gate-pass-register` — raw SQL joins gate_passes → tokens → products → users; filters: date range, status, purpose, vehicle_no; summary cards (total/unique vehicles/inside/exited); 14-column DataTable with CSV export. `GET /api/v1/reports/token-register` — ORM query with LEFT JOIN invoices; filters: date range, token_type, status; summary cards (total/completed/cancelled/net weight MT); 16-column DataTable with CSV export. **IST datetime display:** both reports show entry/exit times and created-at timestamp in IST timezone using `toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', … })` — Gate Pass shows "Entry (IST)" + "Exit (IST)" columns with full date+time; Token Register shows "Time (IST)" column from `tokens.created_at`. Backend fix: date query params passed as Python `date` objects (not `.isoformat()` strings) to avoid asyncpg type mismatch that caused zero rows. Error banners surface API failures instead of silently showing empty tables. |
| 2026-06-25 | **Tally GAP-1: auto-sync invoices on finalise.** `routers/invoices.py::finalise_invoice()` now reads `TallyConfig.auto_sync`. After the finalisation commits, if `is_enabled && auto_sync` and the invoice is a GST `sale`/`purchase`, it enqueues a fire-and-forget `BackgroundTask` → new `_auto_sync_tally_bg(company_id, invoice_id, tenant_slug)`. The helper opens its own tenant-routed session (`get_tenant_session` — same idiom as `_send_notification_bg`), re-checks the guards (final + GST + sale/purchase), reuses the canonical `routers.tally._push_invoice` builder + HTTP push, and commits `tally_synced`. Non-blocking (finalise response returns immediately), never rolls back the finalisation (swallows all exceptions), self-healing (`tally_synced` stays False on failure → invoice remains in `GET /tally/pending` for manual retry), race-safe (`_push_invoice` re-reads config and no-ops if disabled mid-flight), multi-tenant safe (tenant slug captured in-request, replayed in the bg session). The Settings → Tally "Auto-sync when invoice is finalised" toggle (already in the UI) is now wired to real behaviour. Non-GST Bills of Supply and credit/debit notes are excluded (never enter the GST books). Verified: full app import (no circular import from the lazy `routers.tally` import), 43/43 Tally tests pass. Doc `docs/tally-integration-validation.md` GAP-1 marked IMPLEMENTED with manual-verification steps. |
| 2026-06-25 | **Tally: auto-sync master toggle + invoice-prefix filter.** (1) Clarified `auto_sync` is the master switch — when OFF, no invoice auto-syncs on finalise (manual push only); the Settings → Tally toggle now has explanatory help text. (2) New `tally_config.sync_invoice_prefix` (VARCHAR(200), nullable; DDL `ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS …`): comma-separated invoice-number prefixes (e.g. `INV,PUR`; blank = all GST invoices) that gate which series flow to Tally. Enforced at the single `tally.py::_push_invoice` chokepoint via new `_invoice_matches_prefix()` (case-insensitive `startswith`, blank = match-all) so manual, bulk, AND auto-sync all respect it uniformly; plus SQL-side `ILIKE 'prefix%'` (`_prefix_sql_clause`) filtering on the `/tally/pending` and `/tally/sync/bulk` worklists, and a pre-check in the finalise auto-sync enqueue (`invoices.py`) so non-matching invoices never spawn a background task. Schema fields added to `TallyConfigIn`/`Out` + saved in `update_tally_config` (blank→NULL). Frontend: SettingsPage Tally tab gains the prefix input + auto-sync help text; `TallyConfig` TS interface + default state updated. Backward compatible (existing rows have NULL prefix = sync all). Verified: 43/43 Tally tests pass, prefix-matcher unit assertions pass, full app import OK, frontend tsc 0 errors. |
| 2026-06-25 | **Fix: PWA icon not showing correctly (root cause + fix).** The installed/home-screen icon rendered clipped, washed-out, or with dark corner halos. Root cause: the icon PNGs had **transparent rounded corners** but were declared `"purpose": "any maskable"` in the manifest — a maskable icon must be full-bleed (reach every edge), and the green accent bar (bottom edge) + green dot (top-right corner) sat **outside the maskable 80% safe zone**, so Android's circle/squircle mask clipped them and the transparent corners showed through; `apple-touch-icon` transparency also produced black corner halos on iOS. Fix: regenerated all icons **full-bleed solid navy (opaque to every edge, no transparent corners)** via `scripts/gen_pwa_icons.py`; split into **separate `any` and `maskable`** manifest entries (maskable variants keep the WB wordmark + underline inside the inner safe zone with ~24% margin); `apple-touch-icon` now fully opaque. Shipped under **new `-v3` filenames** (`icon-192-v3.png`, `icon-512-v3.png`, `icon-maskable-192-v3.png`, `icon-maskable-512-v3.png`, `apple-touch-icon-v3.png`, `favicon-32-v3.png`) to bust every HTTP / Cloudflare / service-worker cache; old broken PNGs deleted; `manifest.webmanifest` + `index.html` repointed. Note: already-installed PWAs capture the icon at install time — users must remove + re-add to home screen to pick up the new icon. |
| 2026-06-25 | **Industry Accelerator — per-tenant vertical profile (one shared instance).** A tenant can be tagged with an `industry` that (a) hides irrelevant feature modules and (b) overlays vertical terminology — so the same codebase serves stone-crusher AND maize/grain-trader tenants without separate instances or any change to existing tenants. **Mechanism reuses the existing tenant-modules system** (`tenant.config.modules` → `tenant_modules` at login → `Sidebar.HUB_MODULES` gating). New `backend/app/multitenancy/industry.py` holds `INDUSTRY_PRESETS` (`generic`/`stone_crusher`/`maize_trader`): each maps to module overrides + a terminology overlay key. Login (`routers/auth.py`) resolves modules as `{**DEFAULT_MODULES, **industry_preset, **saved_config_modules}` (preset applied dynamically, never baked into config, so switching industry is immediate and explicit per-tenant module overrides still win) and returns new `tenant_industry` on `TokenResponse`. `DEFAULT_MODULES` gained 5 vertical flags (`production`, `cameras`, `anpr`, `royalty`, `gate`) all defaulting **True** → existing tenants unaffected. `maize_trader` preset turns those 5 off. Super-admin sets it via `PUT /api/v1/admin/tenants/{slug}` with `{"industry":"maize_trader"}` (new `industry` field stamps `config.industry`); `GET /api/v1/admin/industries` lists choices. Single-tenant installs read `app_settings.industry_profile`. Frontend: `useAuth` stores `tenant_industry` + exposes `getTenantIndustry()`/`moduleEnabled()`; `i18n.ts` `applyIndustryTerminology()` deep-merges a per-industry label overlay (`locales/industry/maize.{en,hi}.json` — Customer→Buyer, Supplier→Farmer, Token→Weighment, Catalog→Commodities) onto the base bundle, reset-then-apply so switching tenants in one tab can't leak labels; `Sidebar.HUB_MODULES` gates `/cameras-anpr` (cameras+anpr) and `/production-hub` (production); `MaterialsHubPage` + `OperationsHubPage` filter Royalty/Production/Camera/ANPR tabs by module (OperationsHub also switched from hardcoded labels to `t('hubs.operations.*')`). Scope = visibility + terminology; per-industry seed/dashboards/PDF wording deferred. Verified: full app import, 43/43 Tally tests, industry-preset unit assertions, frontend tsc 0 errors. No DB schema or data-model change (reuses `tenants.config` JSON). |
| 2026-06-25 | **Industry picker in Platform Admin console.** The platform tenant-edit dialog (`PlatformDashboard.tsx` → Edit tenant) gains an **Industry** dropdown (Generic / Stone Crusher / Maize Trader) above the Feature Modules panel — picking one flips the vertical module flags (production/cameras/anpr/royalty/gate) live and, on Save, stores `config.industry` (terminology overlay) + the module overrides. Platform `update_tenant` special-cases `industry` (lives in config JSON, not a column) + invalidates the modules cache; modules GET now folds in the industry preset and returns the current `industry`. The 5 vertical modules added to the dialog's `MODULE_META`. So a platform admin sets a tenant's vertical entirely from the UI — no curl/super-admin-secret needed. |
| 2026-06-25 | **Supplier / Farmer Pricing Matrix.** `PricingMatrixPage` (Materials → Customer Rates) gains a **Customer ⇄ Supplier toggle** so per-supplier/farmer purchase rates are set exactly like per-customer sale rates. No backend change — `party_rates` + the matrix/bulk/effective-rate endpoints were always party-type-agnostic; the page just hard-filtered to customers. Toggle scopes the party picker (customers/both vs suppliers/both), and all labels (title, search, copy-from, CSV header, help) use the localized party word `t('party.customer'\|'party.supplier')` → reads "Farmer Pricing Matrix" under the maize overlay. **Backend:** the manual-invoice rate auto-fill safety net (`invoices.py`, was sale-only) now also applies to **purchases** — a manual purchase invoice with rate=0 picks up the supplier/farmer rate (weighment auto-invoices already did, via the token rate resolver). |
| 2026-06-25 | **Quintal (Qtl) unit of measure** (Indian grain trade; 1 Qtl = 100 kg). Added `QUINTAL` to the product unit picklists (`ProductsPage` dropdown + DataTable filter, `QuotationsPage` line items; `unit` is a free String column so no schema change). Weighbridge→invoice conversion is now **unit-aware**: `tokens.py::_auto_create_invoice` divides scale-kg by the product unit (MT ÷1000 · QUINTAL ÷100 · KG/other ÷1) instead of a hardcoded MT branch — covers weighbridge + volume tokens; `print_token` slip-amount fallback too. A QUINTAL product auto-bills `kg/100` quintals at the ₹/quintal rate. (Production-cycle stock posting in `product_stock.py` is still MT-only — make QUINTAL-aware before enabling production for a quintal tenant.) |
| 2026-06-25 | **Nav: split "Sales & CRM" → Sales + CRM; add Vehicle Master to Resources.** The COMMERCIAL section's combined hub was disintegrated. **Sales** (`/sales`, `SalesHubPage`) now holds documents only — Bills · Estimates · Challans · Credit/Debit Notes (the Customers tab removed; default tab → Bills). New **CRM** hub (`/crm`, `CrmHubPage`) with two tabs: Customers + Suppliers, each a `CustomerPickerPage` reused via a new `lockType?: 'customer'|'supplier'` prop (locks the type, hides the all/customer/supplier chips, type-aware title; cards → `/customers/:id` 360). **Vehicle Master** (`/vehicles`, existing `VehiclesPage`) added as a direct item in the RESOURCES section (was previously only reachable by URL). Sidebar: `/sales` label `salesCrm`→`sales`; new `/crm` (Users icon) in COMMERCIAL + `/vehicles` (Truck icon) in RESOURCES; `HUB_CHILDREN['/sales']` drops `/customers`+`/parties`, new `HUB_CHILDREN['/crm']=['/customers','/parties']` (so a role with party perms unlocks CRM); `/vehicles` gated by direct `/vehicles` permission. New i18n `sidebar.crm` · `sidebar.vehicleMaster` · `hubs.crm.{customers,suppliers}` (en+hi). All standalone routes (`/customers`, `/parties`, `/invoices`, …) still work for deep-links. tsc 0 errors, locales valid. |
| 2026-06-25 | **Custom fields: auto-seed industry defaults from the weighbridge form.** Previously the maize starter fields (Moisture % + Quality grade) only seeded when an admin opened `/admin/custom-fields`. Now `TokenPageV1`'s custom-field fetch also POSTs `/custom-fields/seed-defaults?industry=<tenant industry>` when the token-field list comes back empty (idempotent; non-admins get 403 and skip). So an admin's first visit to the weigh-ticket page makes Moisture % + Quality grade appear on the form **and** the printed slip (both maize defaults are `show_on_slip=true`) with no separate setup step. |
| 2026-06-25 | **Custom Attributes (owner-managed custom fields) — v1 on weighments.** A tenant admin can define vertical-specific attributes (e.g. Moisture %, Quality grade) that show only for that tenant and are captured per weighment + optionally printed on the slip — no per-industry hardcoding. **Design:** new `custom_field_definitions` table (per-tenant "matrix": entity_type · field_key · label · field_type text/number/select/date/boolean · unit · options JSONB · required · show_on_slip · sort_order · is_active; UNIQUE company+entity+key) + a JSONB `tokens.custom_fields` value column (keyed by field_key — value travels with the weighment, no joins). **Backend:** `models/custom_field.py`, `schemas/custom_field.py` (auto-slugs field_key from label), `routers/custom_fields.py` — `GET /api/v1/custom-fields` (any user, for form rendering) · `POST`/`PUT`/`DELETE` (admin) · `POST /seed-defaults?industry=` (admin, idempotent). `tokens.py` create_token + create_volume_token persist `custom_fields`; `update_token` accepts it; `TokenCreate/TokenVolumeCreate/TokenUpdate/TokenResponse` carry it. `print_token` loads `show_on_slip` defs and renders label:value on `token_a4.html` + `token_thermal.html` (after the ITEM/PRODUCT row). DDL: table in `get_runtime_ddl()` + `ALTER tokens ADD custom_fields JSONB` in `get_column_migrations()`. **Industry seed:** `industry.py::INDUSTRY_DEFAULT_FIELDS` — `maize_trader` → Moisture % (number, %) + Quality grade (select A/B/FAQ), both show_on_slip. **Frontend:** `CustomFieldDefinition` type + `tokens.custom_fields`; `components/CustomFieldsInput.tsx` (dynamic renderer by field_type); `pages/CustomFieldsPage.tsx` admin matrix (`/admin/custom-fields`, DataTable + add/edit dialog + auto-seeds industry defaults when empty + "Add recommended" button) wired into the admin gear dropdown; `TokenPageV1` weighment form fetches token defs, renders the inputs after Remarks, and posts `custom_fields` (weighbridge + volume paths). **Scope:** v1 = weighments only (products/parties plug into the same `entity_type` later); kiosk + token-detail display deferred. Verified: backend import + slip render (Moisture/Quality print), tsc 0 errors, locales valid. |
| 2026-06-25 | **Quintal slip PDF + weighbridge UI for maize tenants.** **(PDF)** `token_a4.html` + `token_thermal.html` now render gross/tare/net **and the rate label** in the **line product's billing unit** (`token.product.unit`): MT → `kg/1000 MT` (+ CFT hint when `bulk_density` set — crusher unchanged), QUINTAL → `kg/100 Qtl` (no CFT anywhere), KG → as-is. So a maize product set to QUINTAL prints a quintal slip with no cubic-feet; verified MT slips are byte-identical (MT+CFT, /MT) and QUINTAL slips show Qtl only + /Qtl. **(Weighbridge UI)** New `frontend/src/lib/weightUnit.ts` resolves the on-screen weight unit from the **tenant industry** (`maize_trader` → Qtl/100 kg, else MT/1000 kg) — DB still stores kg, only display + manual-entry conversion change. Routed through it: `useWeight.formattedMT` (live scale readout → `WeightDisplay` + weighbridge pages), `TokenPageV1` (`wFmt`/`mtFmt`/`dualFmt`, manual entry via `displayToKg`, tare buttons, column headers, CSV export), `OperatorKiosk` (giant readout, manual entry, done-screen weights, WhatsApp share, voice "quintal"/"tonne"), i18n manual-entry label/hint made unit-agnostic. **⚠ For a maize tenant, set ALL products' unit = QUINTAL** so the industry-driven UI (Qtl) stays consistent with the product-unit-driven slip + billing; `product_stock.current_stock` is stored in the product unit, so converting an existing MT product to QUINTAL requires rescaling stock ×10 and rates ÷10. Crusher tenants (no industry) unchanged — still MT. |
| 2026-06-26 | **"Failed to create token" — root-caused (per-tenant data) + UX fix.** Reported as broken on `manhotra-consulting` but working on `megna-trading`. **Proven, not assumed** (probed prod via the per-tenant subdomain login, which bypasses the `www` Cloudflare WAF): backend + schema are identical and correct on both tenants — a fresh-plate `POST /api/v1/tokens` returns **201**. The real cause was a **UX defect masking a 409**: `TokenPageV1.handleSubmit`'s **weighbridge** path swallowed the server response and always showed a generic *"Failed to create token. Please try again."*, while the **volume** path already surfaced the detail. The hidden error was the duplicate-active-token guard (`tokens.py::create_token`, line ~404): *"Vehicle <no> already has an active token (status: FIRST_WEIGHT). Complete or cancel it before creating a new one."* — and manhotra had **7 tokens stuck in `FIRST_WEIGHT`/`OPEN`** (operators did first-weight, never completed/cancelled), so each blocked its vehicle. megna had clean/fresh plates → looked fine. **Fix:** the weighbridge catch now shows `HTTP <status>: <detail>` (handles string detail, FastAPI 422 arrays, axios message fallback) — parity with the volume path — so the operator sees the actionable "complete or cancel" message. `tsc -p tsconfig.app.json` 0 errors. **Operational follow-ups (data, not code):** (1) complete or cancel the stuck in-progress tokens to unblock those vehicles; (2) manhotra's **active financial year is still 2025-26 (expired 2026-03-31)** while 2026-27 is inactive — so new gate passes mint as `GP/25-26/…`; activate FY 2026-27 in Settings → Financial Years. |
| 2026-06-26 | **Two log-surfaced backend bugs fixed (found via prod `journalctl -u weighbridge`, not assumed).** While confirming the token-create 409 above, the journal exposed two unrelated real defects. **(1) `gate.py` 500 — `ImportError: cannot import name 'async_session_factory' from 'app.database'`:** the 3 gate background tasks (`_bg_capture_entry_photo`, `_bg_capture_exit_photo`, `_async_webhook_event`) imported a name that never existed (the module exports `async_session`), so gate-pass entry/exit **photo capture** + the **CP Plus webhook** handler crashed every time — post-response, so the gate pass still saved but the photo never did and the journal filled with tracebacks. Fixed to use the canonical `get_tenant_session(tenant_slug)` (same tenant-routed bg-session helper as `anpr.py`/`cameras.py`/`invoices.py`), threading the request's tenant slug via a new `_ctx_tenant_slug()` helper (reads the `current_tenant_slug` ContextVar; `None` → default engine, single-tenant-safe) so the photo writes to the **correct tenant DB**. **(2) `dashboard.exceptions` low-stock query — `'ProductStock' object has no attribute 'ProductStock'`:** the comprehension unpacks `for s, name, unit in stock_rows` (so `s` *is* the `ProductStock` entity) but then read `s.ProductStock.<col>`; corrected to `s.<col>`. The OwnerDashboard "low stock" card was silently empty (the per-section try/except swallowed it as a warning + returned 200). Verified: py_compile + module import OK, no remaining `async_session_factory` references. |
| 2026-06-26 | **Live weight not reaching the browser (weighment dialog stuck "OFFLINE") — root-caused: multi-worker WebSocket split.** The scale agent's Discovery UI showed SCALE CONNECTED + CLOUD ONLINE + rising push count, yet the dialog's SCALE READING stayed **OFFLINE**. Proven cause (from `scripts/deploy-vps.sh`, not assumed): prod ran `uvicorn … --workers 2`, but the live-weight pub/sub (`weight.py::_tenant_weight_managers`) is an **in-memory module-level dict — one copy per worker process**. The agent's `POST /api/v1/weight/external-reading` and the browser's `/ws/weight` WebSocket get load-balanced to **different workers**, so `_broadcast()` on worker A never reaches the WS client on worker B — the push succeeds but the browser sees nothing (intermittent ~50%, depending which worker the WS lands on). **Fix: pin `--workers 1`** in all provisioning (`deploy-vps.sh` systemd unit + `install-services.ps1` + `fix-services.ps1`, each with a guard comment) — one process co-locates the push and the WebSocket; async FastAPI on 1 worker is ample for weighbridge concurrency. **To scale past 1 worker you MUST first add a cross-process bus (Redis pub/sub or Postgres LISTEN/NOTIFY) for the weight channel.** Live prod is fixed by editing the running unit (CI does not re-run deploy-vps.sh): `sudo sed -i 's/--workers 2/--workers 1/' /etc/systemd/system/weighbridge.service && sudo systemctl daemon-reload && sudo systemctl restart weighbridge`. |
| 2026-06-26 | **Weight STILL offline after `--workers 1` — 2nd root cause: agent posting to the apex (301 drops the POST) + closed the WebSocket auth gap.** The server's own `GET /api/v1/weight/ping?tenant=<slug>` proved it: `manager:active` but `scale_connected:false` (no readings landed). The agent's `cloud_url` was the apex `https://weighbridgesetu.com`, which **301-redirects to www**; Python `requests` follows a 301 by converting POST→GET and **dropping the body**, so the reading never reached the backend (the agent still saw a 2xx and counted it "pushed"). A POST to the tenant **subdomain** returns 200 and ping immediately flips to `scale_connected:true, weight_kg:…`. **Fixes:** (1) repointed the live agent's `cloud_url` to `https://megna-trading.weighbridgesetu.com` + restarted (verified pushing). (2) Robust agent code — new `scale_agent.py::_effective_push_base(cloud_url, tenant_slug)` auto-routes the apex/`www` host to `https://<tenant_slug>.weighbridgesetu.com` (custom domains / localhost / already-subdomained hosts untouched), so no future install hits the redirect trap even with the default apex `cloud_url`. (3) **Closed the WebSocket auth gap:** in multi-tenant mode `/ws/weight` now REQUIRES `?token=<JWT>` whose `tenant` claim equals `?tenant=` (closes with 4003 on missing/invalid/mismatched), so one tenant can't even READ another's live feed; `useWeight.ts` now sends the JWT (new `getAuthToken()` in `useAuth.ts`). Single-tenant/LAN installs stay open (no token). **⚠ After this deploy, already-open weighbridge tabs must be hard-refreshed once** to load the token-sending frontend (else their WS gets 4003). Verified: agent+backend py_compile + import, `_effective_push_base` unit check (apex→subdomain, localhost untouched), tsc 0 errors. |
| 2026-06-26 | **CRITICAL: `/ws/weight` 500'd on EVERY connect — wrong JWT lib in the auth I just added.** After the worker + agent fixes the browser STILL showed OFFLINE. Proven by a raw WS-handshake probe against prod (`curl -H "Upgrade: websocket" …`) → **HTTP 500**, not `101 Switching Protocols`, so no browser could ever open the socket (this masked the agent + worker fixes — the relay was fine, the handshake itself crashed). Reproduced on the local backend and read the traceback: `weight.py:63 ModuleNotFoundError: No module named 'jwt'`. The WS-auth I added did `import jwt` (PyJWT), but **this app uses python-jose (`from jose import jwt`)** — PyJWT isn't installed — and the import was OUTSIDE the try/except, so it 500'd the whole handshake. Fix: `from jose import jwt as _jwt` (matches `dependencies.py`); dropped the `reason=` kwarg from the reject `close()` calls (use bare `close(code=4403)`/`4001`) to avoid any cross-version `WebSocket.close()` signature issue. **Verified locally with raw handshakes:** no-token → 403, valid token + matching `tenant` claim → 101 (accept), valid token + mismatched tenant → 403. nginx WS proxy (`location /ws/` + Upgrade headers) confirmed correct. **Lesson:** when adding a lib import, match the one the codebase already uses (`grep` it first) — and always test the actual handshake (`101` vs `403` vs `500`), not just the server-side push state. |
