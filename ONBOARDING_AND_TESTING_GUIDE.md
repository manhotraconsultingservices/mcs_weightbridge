# Weighbridge ERP — Client Onboarding & Business Testing Guide

**Version:** 1.0
**Product:** MC Weighbridge ERP
**Stack:** FastAPI + React + PostgreSQL
**Audience:** Vendor (you) — for deploying at new client sites and verifying all features work correctly

---

## Table of Contents

1. [Pre-Onboarding Checklist](#1-pre-onboarding-checklist)
2. [Hardware & Software Requirements](#2-hardware--software-requirements)
3. [Installation at Client Site](#3-installation-at-client-site)
4. [First-Time Application Setup](#4-first-time-application-setup)
5. [Master Data Configuration](#5-master-data-configuration)
6. [USB Guard Setup (Private Invoices)](#6-usb-guard-setup-private-invoices)
7. [Weighing Scale Setup](#7-weighing-scale-setup)
8. [LAN Access for Other Computers](#8-lan-access-for-other-computers)
9. [Handover to Client](#9-handover-to-client)
10. [Business Use Case Testing Checklist](#10-business-use-case-testing-checklist)
11. [After Every System Restart](#11-after-every-system-restart)
12. [Troubleshooting Reference](#12-troubleshooting-reference)

---

## 1. Pre-Onboarding Checklist

Complete these steps **before visiting the client site.**

### Information to Collect from Client

| Item | Example | Where Used |
|------|---------|-----------|
| Company legal name | Shree Ram Stone Crusher Pvt Ltd | Settings > Company |
| GSTIN | 23AABCS1429B1ZB | All GST invoices |
| PAN | AABCS1429B | Company profile |
| State & state code | Uttarakhand / 05 | IGST vs CGST+SGST determination |
| Registered address | Industrial Area, Haridwar | Invoice footer |
| Phone / email | 9425756123 | Invoice footer |
| Bank name | State Bank of India | Invoice bank details |
| Bank account number | 30211234567 | Invoice bank details |
| IFSC code | SBIN0002341 | Invoice bank details |
| Invoice prefix (sales) | INV | Numbering: INV/25-26/0001 |
| Invoice prefix (purchase) | PUR | Numbering: PUR/25-26/0001 |
| Financial year start | April 2025 | FY: 2025-26 |
| Products sold | Gitti 10mm, GSB, Boulders | Product master |
| HSN codes for products | 2517 | GST invoices |
| GST rate per product | 5%, 18% | Invoice tax calculation |
| Default rate per product (Rs/MT) | 800, 1200 | Auto-fill on invoices |
| Scale COM port | COM7 | Settings > Scale |
| Scale baud rate | 9600 | Settings > Scale |

### Prepare USB Pendrive 1 — Installer

Copy these files to a USB pendrive:

```
USB Pendrive 1 (Installer)/
    weighbridge/
        weighbridge.exe           (or full folder if running from source)
        frontend/dist/            (built React app)
        .env                      (pre-filled with client's DB + secret keys)
        tools/nssm.exe
        scripts/fix-services.ps1
        start-weighbridge.bat
    python-3.11.9-amd64.exe       (Python installer — in case not online)
    postgresql-15-x64.exe         (PostgreSQL installer — in case not installed)
```

### Prepare USB Pendrive 2 — USB Guard Key

This is the client's security key for private (non-GST) invoices.

On your laptop, run:
```bash
cd backend
python setup_usb_key.py
```

This writes a `.weighbridge_key` file to the pendrive and registers the UUID. Keep a note of the UUID.

> **Critical:** Label this pendrive clearly. If it is lost, the client cannot access private invoices without the recovery PIN.

---

## 2. Hardware & Software Requirements

### Minimum Hardware (Server PC)

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| OS | Windows 10 Pro 64-bit | Windows 11 Pro |
| RAM | 4 GB | 8 GB |
| Storage | 50 GB free | 100 GB SSD |
| Network | LAN (wired or Wi-Fi) | Wired LAN |
| USB ports | 1 free | 2 free |
| COM port | 1 (RS232 or USB-to-Serial) | USB-to-Serial (CH340) |

### Software Prerequisites

| Software | Version | Purpose |
|---------|---------|---------|
| Python | 3.11.x (system-wide) | Backend runtime |
| PostgreSQL | 15 or 16 | Database |
| Windows services (NSSM) | 2.24 | Auto-start on boot |

> PostgreSQL must be installed as a **Windows service** (not Docker) so it auto-starts on reboot.

---

## 3. Installation at Client Site

### Step 3.1 — Install PostgreSQL (if not already installed)

1. Run `postgresql-15-x64.exe`
2. Installation options:
   - Port: **5432** (default)
   - Superuser password: choose a strong password and note it
   - Install as Windows service: **Yes** (auto-start)
3. After install, open pgAdmin or command prompt:

```sql
-- Create the application database and user
psql -U postgres
CREATE USER weighbridge WITH PASSWORD 'weighbridge_dev_2024';
CREATE DATABASE weighbridge OWNER weighbridge;
GRANT ALL PRIVILEGES ON DATABASE weighbridge TO weighbridge;
\q
```

### Step 3.2 — Copy Application Files

1. Insert USB Pendrive 1
2. Copy the `weighbridge/` folder to:
   ```
   C:\Users\Admin\Documents\workspace_Weighbridge\
   ```
3. Verify the `.env` file has the correct DB credentials and secret keys

### Step 3.3 — Run the Service Fix Script

Open **PowerShell as Administrator** and run:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Users\Admin\Documents\workspace_Weighbridge\scripts\fix-services.ps1"
```

This script:
- Installs Python 3.11 system-wide (downloads if needed, or use offline installer)
- Creates a Python virtualenv with all packages
- Registers and starts two Windows services:
  - `WeighbridgeBackend` — FastAPI on port 9001
  - `WeighbridgeFrontend` — React app on port 9000
- Both services are set to **Automatic** (start on every reboot)

Expected output: `Fix complete! Both services AUTO-START on every reboot.`

### Step 3.4 — Run Database Migrations

```powershell
cd C:\Users\Admin\Documents\workspace_Weighbridge\backend
venv\Scripts\python.exe -m alembic upgrade head
```

### Step 3.5 — Verify Installation

Open browser on server PC:
- Frontend: `http://localhost:9000`
- Login: `admin` / `admin123`

Both should work. If not, see Section 12 (Troubleshooting).

---

## 4. First-Time Application Setup

### Step 4.1 — Change Admin Password

1. Login as `admin` / `admin123`
2. Click top-right user icon → **Change Password**
3. Set a strong password. **Give this to the client owner only.**

### Step 4.2 — Company Profile

Navigate to **Settings > Company**

Fill in:
- Company Name
- GSTIN
- PAN
- State Code (2-digit, e.g. `05` for Uttarakhand, `09` for UP)
- Address, phone, email
- Bank Name, Account Number, IFSC

Click **Save**.

> The state code is critical — it determines whether invoices use CGST+SGST (same state) or IGST (inter-state).

### Step 4.3 — Create Financial Year

Navigate to **Settings > Financial Years**

1. Click **Add Financial Year**
2. Label: `2025-26`
3. Start Date: `01-04-2025`
4. End Date: `31-03-2026`
5. Click **Create**, then **Activate**

### Step 4.4 — Set Invoice Prefixes

Navigate to **Settings > Company** (or invoice prefix section)

- Sales Invoice Prefix: `INV`
- Purchase Invoice Prefix: `PUR`
- Token Prefix: `TKN` (optional)

### Step 4.5 — Create Users

Navigate to **Settings > Users** (admin only)

Create accounts based on who will use the system:

| Role | Who Gets This | What They Can Do |
|------|--------------|-----------------|
| `admin` | Owner / Manager | Everything including user management |
| `operator` | Weighbridge operator | Create tokens, complete weighments |
| `accountant` | Accountant | Invoices, payments, reports, ledger |
| `viewer` | Supervisor | Read-only access to all pages |
| `private_admin` | Owner only | Access private invoice audit console |

---

## 5. Master Data Configuration

### Step 5.1 — Product Categories

Navigate to **Products**

1. Click **Add Category**
2. Create categories matching the client's material types:
   - Crushed Stone
   - Sand
   - Aggregates

### Step 5.2 — Products

Navigate to **Products**, click **Add Product** for each material:

| Field | Example | Notes |
|-------|---------|-------|
| Name | Gitti 10mm | Display name |
| Category | Crushed Stone | Select from created categories |
| HSN Code | 2517 | From GST rate schedule |
| Unit | MT | Metric Tonnes (standard for stone crusher) |
| Default Rate | 800 | Rs per MT — used if no party-specific rate |
| GST Rate | 5% | Check with client's CA |

### Step 5.3 — Parties (Customers & Suppliers)

Navigate to **Parties**, click **Add Party** for each customer and supplier:

| Field | Notes |
|-------|-------|
| Party Type | `customer`, `supplier`, or `both` |
| Name | Legal name as per GST registration |
| GSTIN | 15-character GST number (leave blank for B2C / unregistered) |
| State | Client's state |
| Phone | For notifications |
| Opening Balance | Ask client for any existing balance (debit = they owe us; credit = we owe them) |

**Party-specific rates:** After creating a party, open them and go to **Rates** tab. Add product-specific rates if this customer gets a different price than the default.

### Step 5.4 — Vehicles

Navigate to **Vehicles**, click **Add Vehicle** for each truck:

| Field | Example | Notes |
|-------|---------|-------|
| Registration No | HP38G 1671 | Exact as on RC book |
| Default Tare Weight (kg) | 9500 | Weighed empty truck weight |

> Tip: If the client has a list of vehicles in Excel, use **Import > Vehicles** to bulk-upload.

### Step 5.5 — Drivers & Transporters (Optional)

Navigate to **Vehicles > Drivers** and **Vehicles > Transporters** tabs.

Add drivers with license numbers and transporters with GSTIN if the client tracks these for transport documentation.

---

## 6. USB Guard Setup (Private Invoices)

Private invoices are non-GST off-the-record transactions. They are USB-gated and encrypted.

### Step 6.1 — Register the USB Key

**Method A — Using pre-prepared pendrive (recommended):**

1. Insert USB Pendrive 2 (the one prepared before site visit)
2. The backend auto-scans all drives for `.weighbridge_key` file on startup
3. Navigate to **Settings > USB Guard**
4. You should see the key as registered. If not, click **Register Key** and paste the UUID from the pendrive

**Method B — Register manually on-site:**

1. Insert a blank pendrive
2. Open PowerShell in the backend folder:
   ```powershell
   cd C:\Users\Admin\Documents\workspace_Weighbridge\backend
   venv\Scripts\python.exe setup_usb_key.py
   ```
3. This writes `.weighbridge_key` to the pendrive and registers in the database

### Step 6.2 — Set Up Recovery PIN

In case the USB pendrive is lost or forgotten:

1. Navigate to **Settings > USB Guard > Recovery**
2. Set a PIN (minimum 6 digits) — give this ONLY to the owner
3. Set validity: 24 hours (standard)
4. Click **Create Recovery PIN**

> The recovery PIN allows time-limited access without the USB pendrive. The owner enters it on the Private Invoices lock screen.

### Step 6.3 — Test Private Invoice Access

1. Remove the USB pendrive
2. Navigate to **Private Invoices** — you should see a lock screen
3. Re-insert the pendrive and click **Authenticate with USB** — it should unlock
4. Try the recovery PIN — it should also unlock

### Step 6.4 — Create a Private Admin User

1. Navigate to **Settings > Users**
2. Create a new user:
   - Username: `priv_admin` (or client's choice)
   - Role: `private_admin`
   - Password: Strong password, give to owner only
3. This user accesses `/priv-admin` URL (not in sidebar) to see the full private invoice audit trail

---

## 7. Weighing Scale Setup

### Step 7.1 — Identify the COM Port

1. Connect the weighbridge indicator to the PC via RS232 cable or USB-to-serial adapter
2. Open Device Manager (Win+X > Device Manager)
3. Expand **Ports (COM & LPT)**
4. Note the COM port number (e.g., COM7 for CH340 USB-serial adapter)

### Step 7.2 — Configure in Application

1. Navigate to **Settings > Scale** (or via API at `http://localhost:9001/api/v1/weight/config`)
2. Set:
   - Port: COM7 (whatever was found in Device Manager)
   - Baud Rate: 9600 (most common; check indicator manual)
   - Data Bits: 8
   - Stop Bits: 1
   - Parity: None
3. Click **Save**

### Step 7.3 — Verify Live Weight

1. Navigate to **Tokens** (create new token)
2. The weight display at the top should show a live reading
3. If it shows "Not connected", see Troubleshooting section

### Step 7.4 — Scale Troubleshooting Quick Reference

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Not connected" | Wrong COM port | Check Device Manager, update config |
| "Not connected" after restart | CH340 driver error | See restart guide below |
| Weight reading is negative | Indicator sending minus sign | Check indicator settings |
| Weight fluctuating | Electrical noise | Check cable, use shielded RS232 cable |

**If scale stops working after force-killing the application:**

The CH340 USB-serial driver can get stuck. Fix:

1. Open PowerShell as Administrator
2. Run:
   ```powershell
   pnputil /disable-device "USB\VID_1A86&PID_7523\5&2AB78670&0&5"
   Start-Sleep 3
   pnputil /enable-device "USB\VID_1A86&PID_7523\5&2AB78670&0&5"
   ```
3. If it says "pending reboot" — reboot the machine. Scale will reconnect automatically after reboot.

---

## 8. LAN Access for Other Computers

Other computers on the same network can access the application.

### Step 8.1 — Find Server IP Address

On the server PC, open Command Prompt:
```
ipconfig
```
Note the IPv4 address, e.g., `192.168.1.10`

### Step 8.2 — Open Firewall Ports

On the server PC, run PowerShell as Administrator:
```powershell
netsh advfirewall firewall add rule name="Weighbridge Backend" dir=in action=allow protocol=TCP localport=9001
netsh advfirewall firewall add rule name="Weighbridge Frontend" dir=in action=allow protocol=TCP localport=9000
```

### Step 8.3 — Access from Other PCs

On any other PC on the same LAN, open a browser and go to:
```
http://192.168.1.10:9000
```
Replace `192.168.1.10` with the server's actual IP address.

> Note: The weighing scale and USB Guard only work on the server PC. Other PCs are for invoice management, reports, and payments only.

---

## 9. Handover to Client

### Handover Checklist

Go through this with the client before leaving.

**Application Access:**
- [ ] Frontend URL written down: `http://localhost:9000` (server) or `http://192.168.1.x:9000` (LAN)
- [ ] Admin credentials given to owner in writing (sealed envelope)
- [ ] Operator credentials given to weighbridge operator
- [ ] Accountant credentials given to accountant

**Physical Items:**
- [ ] USB Pendrive 2 (USB Guard key) given to owner — **label it clearly**
- [ ] Recovery PIN written down and given to owner (sealed envelope, separate from password)

**Demonstrated and Confirmed Working:**
- [ ] Create a test token (Sales) — complete weighment — verify net weight is correct
- [ ] Finalize a test invoice — download PDF — verify it looks correct
- [ ] Record a test payment against the invoice
- [ ] Verify party ledger shows the transaction
- [ ] Private invoice created and visible (USB inserted)
- [ ] Scale shows live weight on Token page
- [ ] Reboot the machine and confirm everything auto-starts

**Training Done:**
- [ ] Operator trained on token creation and two-stage weighment
- [ ] Accountant trained on invoices, payments, and reports
- [ ] Owner shown how to use private invoices
- [ ] Owner shown how to do manual backup (Settings > Backup > Create)
- [ ] Owner knows to call you if USB pendrive is lost (recovery PIN procedure)

**Leave Behind:**
- [ ] Printed 1-page quick-start guide (URL, login, basic workflow)
- [ ] Your WhatsApp / phone number for support

---

## 10. Business Use Case Testing Checklist

Run through every test below after installation to confirm all features work.

Use these credentials for testing:
- URL: `http://localhost:9000`
- Admin: `admin` / `admin123` (change before handover)

---

### UC-01: Sales Token — Full Weighment (Outbound)

**Scenario:** Loaded truck leaves the crusher with material. First weigh = empty truck (tare), second weigh = loaded truck (gross).

**Steps:**
1. Navigate to **Tokens**
2. Click **New Token**
3. Fill:
   - Direction: **Sales (Outbound)**
   - Party: Select any customer
   - Vehicle: Select any vehicle
   - Product: Select any product
   - Driver (optional)
4. Click **Save** — token is created with status `pending`
5. Click **Record 1st Weight**
   - Enter weight (e.g., 9500 kg — empty truck)
   - Click Save
6. Load the truck (in real scenario). In testing, proceed immediately.
7. Click **Record 2nd Weight**
   - Enter weight (e.g., 12800 kg — loaded truck)
   - Click Save
8. Token status changes to **Completed**

**Verify:**
- [ ] Tare = 9500 kg (1st weight)
- [ ] Gross = 12800 kg (2nd weight)
- [ ] Net = 3300 kg = 3.300 MT
- [ ] Token number assigned (e.g., TKN/25-26/0001)
- [ ] A draft sales invoice was auto-created

---

### UC-02: Purchase Token — Full Weighment (Inbound)

**Scenario:** Supplier delivers raw material. First weigh = loaded truck (gross), second weigh = empty truck (tare).

**Steps:**
1. Click **New Token**
2. Fill:
   - Direction: **Purchase (Inbound)**
   - Party: Select any supplier
   - Vehicle, Product
3. Click **Record 1st Weight** — enter 22000 kg (loaded truck)
4. Click **Record 2nd Weight** — enter 9800 kg (empty truck)

**Verify:**
- [ ] Gross = 22000 kg (1st weight)
- [ ] Tare = 9800 kg (2nd weight)
- [ ] Net = 12200 kg = 12.200 MT
- [ ] Draft purchase invoice auto-created

---

### UC-03: Live Scale Weight

**Steps:**
1. Navigate to Tokens
2. Observe the weight display at the top of the page

**Verify:**
- [ ] Live weight shown (e.g., 0.49 kg or actual scale reading)
- [ ] Weight updates in real time as something is placed on the scale
- [ ] Stable indicator shows when weight is steady
- [ ] Scale status: **Connected**

---

### UC-04: Invoice Finalization and PDF

**Steps:**
1. Navigate to **Invoices**
2. Find the draft invoice created from UC-01
3. Open it — review the line items, rate, quantity, GST
4. Click **Finalize**
5. Invoice number is assigned (e.g., INV/25-26/0001)
6. Click **Download PDF**

**Verify:**
- [ ] Invoice number assigned after finalization
- [ ] PDF opens correctly (not blank HTML)
- [ ] PDF contains: company header, party details, vehicle number, gross/tare/net weights, line items, GST breakdown, grand total, bank details
- [ ] Status changes to `final` (cannot be edited)

---

### UC-05: GST Calculation — Same State (CGST + SGST)

**Setup:** Party's state = same as company's state code.

**Steps:**
1. Create invoice for a same-state customer (GSTIN starts with same 2 digits as company)
2. Add a line item with 18% GST product

**Verify:**
- [ ] Invoice shows CGST 9% + SGST 9% (not IGST)
- [ ] Tax amounts are correct

---

### UC-06: GST Calculation — Inter-State (IGST)

**Setup:** Party's GSTIN starts with a different state code than the company.

**Steps:**
1. Create invoice for an out-of-state customer
2. Add a line item

**Verify:**
- [ ] Invoice shows IGST 18% (not CGST + SGST)
- [ ] Tax amounts are correct

---

### UC-07: B2C Invoice (Unregistered Customer)

**Steps:**
1. Create a party with no GSTIN (leave GSTIN blank)
2. Create and finalize an invoice for this party

**Verify:**
- [ ] Invoice generates without GSTIN field
- [ ] PDF shows "B2C" or no GSTIN row
- [ ] Shows up in GSTR-1 under B2C section

---

### UC-08: Record Payment Against Invoice

**Steps:**
1. Navigate to **Payments > Receipts**
2. Click **New Receipt**
3. Select the party from UC-04
4. Amount: enter the invoice amount (or partial amount)
5. Payment Mode: Cash / Bank Transfer / Cheque
6. Link to Invoice: select the finalized invoice
7. Click **Save**

**Verify:**
- [ ] Receipt number assigned
- [ ] Invoice payment status shows `paid` (or `partial` for partial payment)
- [ ] Party balance reduces by the payment amount

---

### UC-09: Party Ledger

**Steps:**
1. Navigate to **Ledger**
2. Select the party from previous tests
3. View the running balance

**Verify:**
- [ ] Invoice debit entry appears
- [ ] Payment credit entry appears
- [ ] Running balance is correct
- [ ] Can print the ledger

---

### UC-10: Outstanding / Ageing Report

**Steps:**
1. Navigate to **Ledger > Outstanding**

**Verify:**
- [ ] Unpaid invoices appear with correct amounts
- [ ] Ageing buckets show correctly: Current / 1-30 days / 31-60 / 61-90 / 90+ days

---

### UC-11: Quotation Workflow

**Steps:**
1. Navigate to **Quotations**
2. Click **New Quotation**
3. Add party, product, quantity, rate
4. Click **Save** → **Send** (marks as sent)
5. Click **Convert to Invoice**

**Verify:**
- [ ] Quotation number assigned
- [ ] Converting creates a draft invoice with the same line items
- [ ] Quotation status changes to `converted`
- [ ] PDF download works for quotation

---

### UC-12: Purchase Invoice (Supplier)

**Steps:**
1. Navigate to **Purchase Invoices**
2. Find the draft purchase invoice from UC-02
3. Edit: add rate, verify quantities
4. Finalize

**Verify:**
- [ ] Purchase invoice number assigned (PUR/25-26/0001)
- [ ] Separate numbering sequence from sales invoices
- [ ] PDF shows "PURCHASE INVOICE"

---

### UC-13: Sales Register Report

**Steps:**
1. Navigate to **Reports > Sales Register**
2. Set date range to include your test invoices
3. View and export CSV

**Verify:**
- [ ] All finalized invoices appear
- [ ] Invoice-wise GST breakdown (taxable value, CGST, SGST, IGST, total)
- [ ] CSV downloads correctly and opens in Excel

---

### UC-14: Weight Register Report

**Steps:**
1. Navigate to **Reports > Weight Register**
2. Set date range

**Verify:**
- [ ] All completed tokens appear
- [ ] Columns: Token No, Date, Vehicle, Party, Product, Gross, Tare, Net (MT)
- [ ] CSV export works

---

### UC-15: GSTR-1 Report

**Steps:**
1. Navigate to **GST Reports > GSTR-1**
2. Select the test month and year

**Verify:**
- [ ] B2B section: invoices for registered parties (with GSTIN)
- [ ] B2C section: invoices for unregistered parties
- [ ] HSN Summary: quantity and tax by HSN code
- [ ] CSV export works
- [ ] JSON export (for GSTN portal upload) downloads and is valid JSON

---

### UC-16: GSTR-3B Report

**Steps:**
1. Navigate to **GST Reports > GSTR-3B**
2. Select month

**Verify:**
- [ ] Section 3.1: Outward taxable supplies (from sales invoices)
- [ ] Section 4A5: ITC from purchases (from purchase invoices)
- [ ] Net tax payable = Output tax - ITC

---

### UC-17: Profit & Loss Report

**Steps:**
1. Navigate to **Reports > Profit & Loss**
2. Select current financial year

**Verify:**
- [ ] Monthly rows with Revenue, COGS (purchases), Gross Profit, Margin %
- [ ] Totals at the bottom

---

### UC-18: Stock Summary Report

**Steps:**
1. Navigate to **Reports > Stock Summary**

**Verify:**
- [ ] Product-wise: Qty Purchased, Qty Sold, Closing Stock (MT)
- [ ] Closing value per product
- [ ] CSV export works

---

### UC-19: Private Invoice (Non-GST)

**Pre-condition:** USB Guard pendrive must be inserted.

**Steps:**
1. Navigate to **Private Invoices**
2. If locked: insert USB pendrive → click **Authenticate with USB** → select `.weighbridge_key` file
3. Click **New Private Invoice**
4. Fill: customer name, vehicle, product, net weight, rate, amount, payment mode
5. Link to an existing token if available
6. Click **Save**

**Verify:**
- [ ] Invoice created with SE/NNNNN number (e.g., SE/00001)
- [ ] All sensitive fields are encrypted (you cannot see them directly in the database)
- [ ] Invoice appears in the list with decrypted values

---

### UC-20: Move to Supplement (Invoice → Private)

**Scenario:** A draft sales invoice needs to be moved to the private (off-record) system.

**Pre-condition:** USB must be authenticated. Invoice must be in `draft` status.

**Steps:**
1. Navigate to **Invoices**
2. Find a draft invoice
3. Click **Move to Supplement** (USB required)
4. Confirm the action

**Verify:**
- [ ] Invoice disappears from the main invoices list
- [ ] Token also removed from tokens list
- [ ] Entry appears in Private Invoices list
- [ ] Original invoice number sequence has no gap (next invoice still gets the correct next number)

---

### UC-21: Private Admin Console

**Steps:**
1. Login as the `private_admin` user (not admin)
2. Navigate directly to: `http://localhost:9000/priv-admin`
3. View the full private invoice audit trail

**Verify:**
- [ ] This page is NOT in the sidebar — only accessible by direct URL
- [ ] Shows who created each private invoice and when
- [ ] CSV export downloads all private invoice data in plain text

---

### UC-22: USB Recovery PIN

**Steps:**
1. Remove the USB pendrive
2. Navigate to **Private Invoices** — should show lock screen
3. Click **Use Recovery PIN**
4. Enter the PIN set in Settings > USB Guard
5. Access should be granted for the configured number of hours

**Verify:**
- [ ] PIN works without the USB pendrive
- [ ] Access expires after the configured duration
- [ ] After expiry, lock screen appears again

---

### UC-23: Notifications (if configured)

**Steps:**
1. Navigate to **Settings > Notifications**
2. Configure at least one channel (Email / SMS / WhatsApp)
3. Click **Test** on the configured channel

**Verify:**
- [ ] Test message received on the configured channel
- [ ] Delivery log shows the test message with status `delivered`

---

### UC-24: Audit Trail

**Steps:**
1. Navigate to **Audit**
2. Filter by action type (e.g., `create`, `finalise`, `cancel`)

**Verify:**
- [ ] All actions from testing are logged with user, timestamp, and entity details
- [ ] Search by entity type (invoice, token, payment) works

---

### UC-25: Backup and Restore

**Steps:**
1. Navigate to **Settings > Backup**
2. Click **Create Backup**
3. Wait ~30 seconds for the backup to complete
4. Click **Download** to save the `.sql.enc` file

**Verify:**
- [ ] Backup file appears in the list with timestamp and file size (should be > 100 KB)
- [ ] Download works

**Restore test (do on a test machine, not production):**
1. Click **Restore** on a backup file
2. Confirm the destructive action
3. Verify the application still works after restore

---

### UC-26: Tally Integration (if client uses Tally Prime)

**Steps:**
1. Open Tally Prime on the same PC
2. Go to Gateway of Tally > F12 > Advanced > Enable ODBC Server > port 9002
3. Navigate to **Settings > Tally**
4. Set Host: `localhost`, Port: `9002`, Company Name (as in Tally)
5. Click **Test Connection** — should show success
6. Find a finalized invoice in the Invoices list
7. Click the **Tally Sync** button on that invoice row

**Verify:**
- [ ] Test connection returns success
- [ ] Invoice synced — Tally shows the voucher (Sales/Purchase)
- [ ] `tally_synced` flag shows on the invoice row

---

### UC-27: Data Import

**Steps:**
1. Navigate to **Import**
2. Download the blank **Parties template** (Excel)
3. Fill in 3-4 test parties in the template
4. Upload the file and click **Preview**
5. Confirm the import

**Verify:**
- [ ] Preview shows the correct rows and columns
- [ ] After import, new parties appear in the Parties page
- [ ] Duplicate check: import same file again with `update_existing = false` — should skip duplicates

---

### UC-28: Token Search

**Steps:**
1. Navigate to **Tokens**
2. Use the search box to search by:
   - Vehicle registration (partial, e.g., "HP38")
   - Party name (partial, e.g., "JP")
3. Use date filters

**Verify:**
- [ ] Search returns matching tokens
- [ ] Date filter narrows results correctly

---

### UC-29: Invoice Token Hyperlink

**Steps:**
1. Navigate to **Invoices**
2. Find an invoice that has an associated token
3. Click the token badge/number shown on the invoice row

**Verify:**
- [ ] Token detail modal opens showing: gross weight, tare weight, net weight, vehicle, timestamps

---

### UC-30: System Auto-Start After Reboot

**This is the final and most important test.**

**Steps:**
1. Reboot the PC completely
2. Wait 60 seconds after login (do NOT do anything manually)
3. Open browser → `http://localhost:9000`

**Verify:**
- [ ] Frontend loads without any manual steps
- [ ] Login works (backend is up)
- [ ] Scale reconnects automatically (Token page shows live weight within 10-15 seconds)
- [ ] Check Windows Services: both `WeighbridgeBackend` and `WeighbridgeFrontend` show **Running**

---

## 11. After Every System Restart

**Everything is automatic.** No manual action is needed.

| Service | Auto-Starts? | Port |
|---------|-------------|------|
| PostgreSQL | Yes (native Windows service) | 5432 |
| WeighbridgeBackend | Yes (NSSM, Automatic) | 9001 |
| WeighbridgeFrontend | Yes (NSSM, Automatic) | 9000 |
| Weighing Scale (COM7) | Yes (backend retries every 5s) | COM7 |

**If something does not start automatically:**

Double-click `start-weighbridge.bat` on the Desktop (or in `workspace_Weighbridge\`).

This runs:
```
net start WeighbridgeBackend
net start WeighbridgeFrontend
```

If it still fails, open PowerShell as Administrator and check:
```powershell
Get-Service WeighbridgeBackend,WeighbridgeFrontend | Select-Object Name,Status
Get-Content C:\Users\Admin\Documents\workspace_Weighbridge\logs\backend_stderr.log -Tail 30
```

---

## 12. Troubleshooting Reference

### Application Won't Open

| Symptom | Check | Fix |
|---------|-------|-----|
| Browser shows "This site can't be reached" | Services running? | Run `start-weighbridge.bat` as Administrator |
| Login gives "Internal Server Error" | Backend just started | Wait 30 seconds, retry |
| Login gives "Invalid credentials" | Wrong password | Use `admin` / `admin123` (or the changed password) |
| Blank white page | JavaScript error | Press F12 > Console — report the error |

### Scale Not Connecting

| Symptom | Check | Fix |
|---------|-------|-----|
| "Not connected" on Token page | COM port configured correctly? | Settings > Scale — verify port number |
| COM port in config but not connecting | Wrong port number | Device Manager > Ports — find CH340 port |
| Was working, suddenly stopped | Driver stuck in Error 31 | Reboot the PC (clears driver state) |
| "Access is denied" on port | Another process holds the port | Check Device Manager for conflicts |

### PDF Download Issues

| Symptom | Fix |
|---------|-----|
| PDF downloads as HTML file | Restart backend service; check backend_stderr.log for xhtml2pdf errors |
| PDF is blank | Check that invoice has line items and a finalized status |

### Private Invoices

| Symptom | Fix |
|---------|-----|
| Lock screen won't unlock | Verify `.weighbridge_key` file is on the pendrive root |
| "USB key not registered" error | Register the key UUID in Settings > USB Guard |
| Forgot USB pendrive | Use recovery PIN (Settings > USB Guard > Recovery) |
| Lost USB pendrive + forgot PIN | Call vendor — full recovery requires database access |

### Services Won't Start

| Symptom | Fix |
|---------|-----|
| Service fails to start | Re-run `fix-services.ps1` as Administrator |
| "Cannot open service" error | NSSM service not registered — re-run `fix-services.ps1` |
| Service starts then stops immediately | Check `logs\backend_stderr.log` for the error |
| Port 9001 already in use | Kill the occupying process: `netstat -ano | findstr :9001` then `taskkill /PID <pid> /F` |

### Database Issues

| Symptom | Fix |
|---------|-----|
| "could not connect to server" | PostgreSQL not running — check Windows Services |
| "database does not exist" | Run: `psql -U postgres -c "CREATE DATABASE weighbridge OWNER weighbridge;"` |
| Migration errors on startup | Run: `cd backend && venv\Scripts\python.exe -m alembic upgrade head` |

---

*Document prepared for MC Weighbridge ERP — Internal Use*
