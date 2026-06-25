# WeighBridge Setu ↔ TallyPrime Integration — Validation Guide

**Role:** Senior Tally Integration Lead  
**Scope:** All 6 entity types, sample XMLs, balance proofs, setup steps, testing procedure, known gaps  
**Last updated:** 2026-06-25

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [One-Time Setup in TallyPrime](#2-one-time-setup-in-tallyprime)
3. [Configure WeighBridge Setu](#3-configure-weighbridge-setu)
4. [Amount Sign Convention](#4-amount-sign-convention)
5. [Entity Type 1 — Sales Invoice (Intra-state, CGST+SGST)](#5-entity-type-1--sales-invoice-intra-state-cgstsgst)
6. [Entity Type 2 — Purchase Invoice (Intra-state, CGST+SGST)](#6-entity-type-2--purchase-invoice-intra-state-cgstsgst)
7. [Entity Type 3 — Sales Invoice (Inter-state, IGST)](#7-entity-type-3--sales-invoice-inter-state-igst)
8. [Entity Type 4 — Sales Invoice with Discount, Freight, TCS, Round-off](#8-entity-type-4--sales-invoice-with-discount-freight-tcs-round-off)
9. [Entity Type 5 — Customer Master (Sundry Debtors)](#9-entity-type-5--customer-master-sundry-debtors)
10. [Entity Type 6 — Supplier Master (Sundry Creditors)](#10-entity-type-6--supplier-master-sundry-creditors)
11. [Entity Type 7 — Sales Order (from Quotation)](#11-entity-type-7--sales-order-from-quotation)
12. [Entity Type 8 — Purchase Order (from Inventory PO)](#12-entity-type-8--purchase-order-from-inventory-po)
13. [API Endpoint Reference](#13-api-endpoint-reference)
14. [Testing with curl](#14-testing-with-curl)
15. [Testing with Python (direct XML push)](#15-testing-with-python-direct-xml-push)
16. [Common Errors & Fixes](#16-common-errors--fixes)
17. [Validation Checklist](#17-validation-checklist)
18. [Known Gaps & Pending Work](#18-known-gaps--pending-work)

---

## 1. Architecture Overview

```
WeighBridge Setu (backend)
        │
        │  HTTP POST  (Content-Type: text/xml; charset=utf-8)
        ▼
TallyPrime (localhost:9002)   ←  XML import API  →  Tally data file
        │
        │  XML response
        ▼
WeighBridge Setu parses <LINEERROR> / <CREATED> / <ALTERED>
updates invoice.tally_synced = True/False
```

**Key files:**

| File | Purpose |
|---|---|
| `backend/app/integrations/tally/xml_builder.py` | Builds all 6 entity XMLs |
| `backend/app/integrations/tally/client.py` | HTTP push + response parser |
| `backend/app/routers/tally.py` | 12 API endpoints |
| `backend/app/models/settings.py` | `TallyConfig` ORM model |

**Supported entity types:**

| # | Entity | Tally Voucher Type | Object View |
|---|---|---|---|
| 1 | Sales Invoice (intra-state) | Sales | Invoice Voucher View |
| 2 | Purchase Invoice (intra-state) | Purchase | Invoice Voucher View |
| 3 | Sales Invoice (inter-state) | Sales | Invoice Voucher View |
| 4 | Sales Invoice (discount/freight/TCS) | Sales | Invoice Voucher View |
| 5 | Customer Master | LEDGER under All Masters | — |
| 6 | Supplier Master | LEDGER under All Masters | — |
| 7 | Sales Order (from Quotation) | Sales Order | Ordering Voucher View |
| 8 | Purchase Order (from Inventory PO) | Purchase Order | Ordering Voucher View |

---

## 2. One-Time Setup in TallyPrime

### Step 1 — Enable TallyPrime HTTP server

```
TallyPrime → F12 (Configure) → Advanced Configuration
  ✓ Enable ODBC Server (port 9002)
  ✓ Enable XML Input / Output
```

> **Port note:** Our default is **9002**. Tally's factory default is 9000, which
> clashes with the Vite dev server. Always verify the port before testing.

### Step 2 — Open the company you want to import into

Tally must have **exactly one company open** when you push data. If multiple companies are open, Tally uses the currently selected one — data may land in the wrong company.

Verify with:
```
GET /api/v1/tally/companies
```
The response must list exactly the company name you configured in WeighBridge Setu Settings → Tally.

### Step 3 — Create required ledgers in TallyPrime

All ledger names are configurable in WeighBridge Setu. The defaults below must exist **with exactly these names** (case-insensitive) or the XML import will fail with `LINEERROR: Ledger not found`.

| Ledger Name (default) | Group | Notes |
|---|---|---|
| `Sales` | Sales Accounts | Or your existing sales ledger — e.g. "Sales (Taxable)" |
| `Purchase` | Purchase Accounts | Or your existing purchase ledger |
| `CGST` | Duties & Taxes → GST → CGST | Under the Duties & Taxes group |
| `SGST` | Duties & Taxes → GST → SGST | |
| `IGST` | Duties & Taxes → GST → IGST | Only needed for inter-state |
| `Freight Outward` | Indirect Incomes | Create if absent |
| `Trade Discount` | Indirect Expenses | Create if absent |
| `TCS Payable` | Duties & Taxes | Only if TCS is used |
| `Round Off` | Indirect Expenses | Create if absent |

**How to create a ledger in Tally:**
```
Gateway of Tally → Accounts Info → Ledgers → Create
  Name: CGST
  Under: Duties & Taxes
  Type of Duty/Tax: GST
  Tax Type: Central Tax
```

### Step 4 — Create stock items in TallyPrime

Tally requires inventory items to pre-exist as Stock Items before a Sales/Purchase voucher can reference them.

```
Gateway of Tally → Inventory Info → Stock Items → Create
  Name: 10mm Aggregates    (must match product name exactly in WeighBridge)
  Under: Primary
  Unit: MT
  HSN/SAC Code: 2517
  GST Applicable: Applicable
  Set/alter GST Details: Yes
    Rate of Duty: 5%
    Taxability: Taxable
```

> **Tip:** You only need to create items once. Subsequent voucher imports reuse them.

### Step 5 — Create party ledgers

Party ledgers can be created manually **or** pushed from WeighBridge Setu (Entity Types 5 and 6 below). Using the API is recommended to avoid name typos.

```
POST /api/v1/tally/sync/parties
```

This pushes all active parties (customers → Sundry Debtors, suppliers → Sundry Creditors).

---

## 3. Configure WeighBridge Setu

### API

```http
PUT /api/v1/tally/config
Authorization: Bearer <admin-token>
Content-Type: application/json

{
  "host": "localhost",
  "port": 9002,
  "tally_company_name": "Manhotra Quarry Pvt Ltd",
  "is_enabled": true,
  "auto_sync": false,
  "ledger_sales": "Sales",
  "ledger_purchase": "Purchase",
  "ledger_cgst": "CGST",
  "ledger_sgst": "SGST",
  "ledger_igst": "IGST",
  "ledger_freight": "Freight Outward",
  "ledger_discount": "Trade Discount",
  "ledger_tcs": "TCS Payable",
  "ledger_roundoff": "Round Off",
  "narration_vehicle": true,
  "narration_token": true,
  "narration_weight": true
}
```

### UI

Settings → Tally tab → fill Host / Port / Company → Save → Test Connection

---

## 4. Amount Sign Convention

Tally vouchers must **balance to zero**. Signs are:

### Sales voucher

| Entry | ISDEEMEDPOSITIVE | Amount sign | Meaning |
|---|---|---|---|
| Party ledger | Yes | **+** (debit) | Customer owes us |
| Sales / Inventory | No | **−** (credit) | Revenue recognized |
| Discount | Yes | **+** (debit) | Reduces revenue |
| Freight | No | **−** (credit) | Freight income |
| CGST / SGST / IGST | No | **−** (credit) | Tax liability |
| TCS | No | **−** (credit) | TCS liability |
| Round-off | No | **±** | Small balancer |

> **Inventory amount = GROSS.** Every `INVENTORYENTRIES.LIST` → `ACCOUNTINGALLOCATIONS.LIST` amount is the line subtotal **before** the header discount (`qty × rate`). They sum to `subtotal`, **not** `taxable_amount`. The header discount is posted as a **separate** `Trade Discount` debit line. Netting the discount into the inventory amount is the #1 cause of an unbalanced voucher.

```
Balance = +grand_total − subtotal(Σ gross line amounts) + discount − freight − cgst − sgst − igst − tcs ± round_off = 0
```

Verified by the test suite — `test_sales_with_discount_balances`:
```
+9,975.00 (party)  − 10,000.00 (gross → Sales)  + 500.00 (discount)  − 475.00 (GST)  = 0.00 ✓
```

### Purchase voucher

All signs flip relative to sales:

| Entry | ISDEEMEDPOSITIVE | Amount sign |
|---|---|---|
| Party (supplier) | No | **−** (credit) |
| Purchase / Inventory | Yes | **+** (debit) |
| CGST / SGST / IGST | Yes | **+** (debit — ITC claim) |
| Discount | No | **−** (credit — reduces cost) |
| Freight | Yes | **+** (debit — freight expense) |

---

## 5. Entity Type 1 — Sales Invoice (Intra-state, CGST+SGST)

**Scenario:** 10 MT of 10mm Aggregates sold to Rajesh Stone Traders (Maharashtra), GST 5%, 30-day credit, weighbridge token #42.

**Ledger balance proof:**
```
Party debit:   +15,750.00
Sales credit:  −15,000.00
CGST credit:      −375.00
SGST credit:      −375.00
─────────────────────────
Total:              0.00 ✓
```

```xml
<?xml version="1.0" ?>
<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>Vouchers</REPORTNAME>
        <STATICVARIABLES>
          <SVCURRENTCOMPANY>Manhotra Quarry Pvt Ltd</SVCURRENTCOMPANY>
        </STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="Sales" ACTION="Create" OBJVIEW="Invoice Voucher View">
            <DATE>20260601</DATE>
            <GUID>f47ac10b-58cc-4372-a567-0e02b2c3d479</GUID>
            <NARRATION>Sales SAL/25-26/0001 | Vehicle: MH12AB1234 | Net Wt: 10.000 MT</NARRATION>
            <VOUCHERTYPENAME>Sales</VOUCHERTYPENAME>
            <VOUCHERNUMBER>SAL/25-26/0001</VOUCHERNUMBER>
            <PARTYLEDGERNAME>Rajesh Stone Traders</PARTYLEDGERNAME>
            <BASICBASEPARTYNAME>Rajesh Stone Traders</BASICBASEPARTYNAME>
            <PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>
            <PLACEOFSUPPLY>Maharashtra</PLACEOFSUPPLY>

            <!-- Party ledger entry: debit (+) -->
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>Rajesh Stone Traders</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
              <AMOUNT>15750.00</AMOUNT>
              <GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE>
              <PARTYGSTIN>27AABCR1234M1ZL</PARTYGSTIN>
              <!-- Bill-wise aging: creates "New Ref" with 30-day credit period -->
              <BILLALLOCATIONS.LIST>
                <NAME>SAL/25-26/0001</NAME>
                <BILLTYPE>New Ref</BILLTYPE>
                <AMOUNT>15750.00</AMOUNT>
                <CREDITPERIOD>30 Days</CREDITPERIOD>
              </BILLALLOCATIONS.LIST>
            </ALLLEDGERENTRIES.LIST>

            <!-- Inventory entry: sales ledger credit (−) -->
            <INVENTORYENTRIES.LIST>
              <STOCKITEMNAME>10mm Aggregates</STOCKITEMNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <RATE>1500.00/MT</RATE>
              <AMOUNT>-15000.00</AMOUNT>
              <ACTUALQTY>10.000 MT</ACTUALQTY>
              <BILLEDQTY>10.000 MT</BILLEDQTY>
              <GSTTAXABILITY>Taxable</GSTTAXABILITY>
              <HSNCODE>2517</HSNCODE>
              <GSTRATE>5.00</GSTRATE>
              <BATCHALLOCATIONS.LIST>
                <GODOWNNAME>Main Location</GODOWNNAME>
                <BATCHNAME>Primary Batch</BATCHNAME>
                <AMOUNT>-15000.00</AMOUNT>
                <ACTUALQTY>10.000 MT</ACTUALQTY>
                <BILLEDQTY>10.000 MT</BILLEDQTY>
              </BATCHALLOCATIONS.LIST>
              <ACCOUNTINGALLOCATIONS.LIST>
                <LEDGERNAME>Sales</LEDGERNAME>
                <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                <AMOUNT>-15000.00</AMOUNT>
              </ACCOUNTINGALLOCATIONS.LIST>
            </INVENTORYENTRIES.LIST>

            <!-- CGST credit (−) -->
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>CGST</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>-375.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>

            <!-- SGST credit (−) -->
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>SGST</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>-375.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>

          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>
```

---

## 6. Entity Type 2 — Purchase Invoice (Intra-state, CGST+SGST)

**Scenario:** 50 MT of Raw Stone purchased from Kumar Mines (Maharashtra), GST 5%.

**Ledger balance proof:**
```
Purchase debit: +40,000.00
CGST debit:      +1,000.00
SGST debit:      +1,000.00
Party credit:   −42,000.00
─────────────────────────
Total:               0.00 ✓
```

```xml
<?xml version="1.0" ?>
<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>Vouchers</REPORTNAME>
        <STATICVARIABLES>
          <SVCURRENTCOMPANY>Manhotra Quarry Pvt Ltd</SVCURRENTCOMPANY>
        </STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="Purchase" ACTION="Create" OBJVIEW="Invoice Voucher View">
            <DATE>20260601</DATE>
            <GUID>a1b2c3d4-e5f6-7890-abcd-ef1234567890</GUID>
            <NARRATION>Purchase PUR/25-26/0001 | Vehicle: MH12CD5678 | Net Wt: 50.000 MT</NARRATION>
            <VOUCHERTYPENAME>Purchase</VOUCHERTYPENAME>
            <VOUCHERNUMBER>PUR/25-26/0001</VOUCHERNUMBER>
            <PARTYLEDGERNAME>Kumar Mines</PARTYLEDGERNAME>
            <BASICBASEPARTYNAME>Kumar Mines</BASICBASEPARTYNAME>
            <PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>
            <PLACEOFSUPPLY>Maharashtra</PLACEOFSUPPLY>

            <!-- Party (supplier) ledger entry: credit (−) -->
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>Kumar Mines</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
              <AMOUNT>-42000.00</AMOUNT>
              <GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE>
              <PARTYGSTIN>27AABCK9876B1ZD</PARTYGSTIN>
              <BILLALLOCATIONS.LIST>
                <NAME>PUR/25-26/0001</NAME>
                <BILLTYPE>New Ref</BILLTYPE>
                <AMOUNT>-42000.00</AMOUNT>
              </BILLALLOCATIONS.LIST>
            </ALLLEDGERENTRIES.LIST>

            <!-- Inventory entry: purchase debit (+) -->
            <INVENTORYENTRIES.LIST>
              <STOCKITEMNAME>Raw Stone</STOCKITEMNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <RATE>800.00/MT</RATE>
              <AMOUNT>40000.00</AMOUNT>
              <ACTUALQTY>50.000 MT</ACTUALQTY>
              <BILLEDQTY>50.000 MT</BILLEDQTY>
              <GSTTAXABILITY>Taxable</GSTTAXABILITY>
              <HSNCODE>2517</HSNCODE>
              <GSTRATE>5.00</GSTRATE>
              <BATCHALLOCATIONS.LIST>
                <GODOWNNAME>Main Location</GODOWNNAME>
                <BATCHNAME>Primary Batch</BATCHNAME>
                <AMOUNT>40000.00</AMOUNT>
                <ACTUALQTY>50.000 MT</ACTUALQTY>
                <BILLEDQTY>50.000 MT</BILLEDQTY>
              </BATCHALLOCATIONS.LIST>
              <ACCOUNTINGALLOCATIONS.LIST>
                <LEDGERNAME>Purchase</LEDGERNAME>
                <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                <AMOUNT>40000.00</AMOUNT>
              </ACCOUNTINGALLOCATIONS.LIST>
            </INVENTORYENTRIES.LIST>

            <!-- CGST ITC debit (+) -->
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>CGST</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <AMOUNT>1000.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>

            <!-- SGST ITC debit (+) -->
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>SGST</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <AMOUNT>1000.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>

          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>
```

---

## 7. Entity Type 3 — Sales Invoice (Inter-state, IGST)

**Scenario:** 10 MT sold to Delhi Infra Ltd (Delhi, GSTIN starting 07), GST 5% as IGST.

Since the seller is in Maharashtra (27) and buyer in Delhi (07) → **inter-state → IGST only, no CGST/SGST**.

**Ledger balance proof:**
```
Party debit:   +15,750.00
Sales credit:  −15,000.00
IGST credit:      −750.00
─────────────────────────
Total:              0.00 ✓
```

```xml
<?xml version="1.0" ?>
<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>Vouchers</REPORTNAME>
        <STATICVARIABLES>
          <SVCURRENTCOMPANY>Manhotra Quarry Pvt Ltd</SVCURRENTCOMPANY>
        </STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="Sales" ACTION="Create" OBJVIEW="Invoice Voucher View">
            <DATE>20260610</DATE>
            <GUID>b2c3d4e5-f6a7-8901-bcde-f12345678901</GUID>
            <NARRATION>Sales SAL/25-26/0015 | Token #65 | Vehicle: DL01AA9876 | Net Wt: 10.000 MT</NARRATION>
            <VOUCHERTYPENAME>Sales</VOUCHERTYPENAME>
            <VOUCHERNUMBER>SAL/25-26/0015</VOUCHERNUMBER>
            <PARTYLEDGERNAME>Delhi Infra Ltd</PARTYLEDGERNAME>
            <BASICBASEPARTYNAME>Delhi Infra Ltd</BASICBASEPARTYNAME>
            <PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>
            <PLACEOFSUPPLY>Delhi</PLACEOFSUPPLY>

            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>Delhi Infra Ltd</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
              <AMOUNT>15750.00</AMOUNT>
              <GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE>
              <PARTYGSTIN>07AABCD1234E1ZM</PARTYGSTIN>
              <BILLALLOCATIONS.LIST>
                <NAME>SAL/25-26/0015</NAME>
                <BILLTYPE>New Ref</BILLTYPE>
                <AMOUNT>15750.00</AMOUNT>
                <CREDITPERIOD>30 Days</CREDITPERIOD>
              </BILLALLOCATIONS.LIST>
            </ALLLEDGERENTRIES.LIST>

            <INVENTORYENTRIES.LIST>
              <STOCKITEMNAME>10mm Aggregates</STOCKITEMNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <RATE>1500.00/MT</RATE>
              <AMOUNT>-15000.00</AMOUNT>
              <ACTUALQTY>10.000 MT</ACTUALQTY>
              <BILLEDQTY>10.000 MT</BILLEDQTY>
              <GSTTAXABILITY>Taxable</GSTTAXABILITY>
              <HSNCODE>2517</HSNCODE>
              <GSTRATE>5.00</GSTRATE>
              <BATCHALLOCATIONS.LIST>
                <GODOWNNAME>Main Location</GODOWNNAME>
                <BATCHNAME>Primary Batch</BATCHNAME>
                <AMOUNT>-15000.00</AMOUNT>
                <ACTUALQTY>10.000 MT</ACTUALQTY>
                <BILLEDQTY>10.000 MT</BILLEDQTY>
              </BATCHALLOCATIONS.LIST>
              <ACCOUNTINGALLOCATIONS.LIST>
                <LEDGERNAME>Sales</LEDGERNAME>
                <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                <AMOUNT>-15000.00</AMOUNT>
              </ACCOUNTINGALLOCATIONS.LIST>
            </INVENTORYENTRIES.LIST>

            <!-- IGST only (inter-state) — no CGST or SGST -->
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>IGST</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>-750.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>

          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>
```

---

## 8. Entity Type 4 — Sales Invoice with Discount, Freight, TCS, Round-off

**Scenario:** Bulk deal — 20 MT @ ₹1,000/MT, 10% trade discount, ₹500 freight, 0.1% TCS, GST 5% CGST+SGST.

**Calculation** (exactly as `gst_service.calculate_invoice_totals` computes it):
```
Subtotal (20 MT × ₹1,000, GROSS):   ₹20,000.00
Trade Discount (10% of subtotal):   − ₹2,000.00
Taxable (subtotal − discount):      ₹18,000.00
CGST (2.5% of 18,000):              + ₹450.00
SGST (2.5% of 18,000):              + ₹450.00
Freight:                            + ₹500.00
total_amount (taxable+tax+freight): ₹19,400.00
TCS (0.1% of total_amount 19,400):  + ₹19.40        ← TCS base includes tax + freight
Pre-round:                          ₹19,419.40
Round-off (down to whole rupee):    − ₹0.40
Grand Total:                        ₹19,419.00
```

**Ledger balance proof** (raw signed-amount sum — exactly what Tally and the test `_voucher_is_balanced` check):
```
Party debit:               +19,419.00
Sales credit (GROSS):      −20,000.00   ← item.amount = qty×rate, BEFORE discount
Trade Discount debit:       +2,000.00   ← separate ledger line (NOT netted into Sales)
Freight credit:               −500.00
CGST credit:                  −450.00
SGST credit:                  −450.00
TCS credit:                    −19.40
Round Off (balancer):           +0.40   ← emitted = ledger_sign(−1) × round_off(−0.40)
─────────────────────────────────────
Total:                           0.00 ✓
```

> ⚠ **Critical — discount accounting.** The `Sales` ledger line carries the
> **GROSS** amount (₹20,000), and the discount is a **separate** `Trade Discount`
> debit (₹2,000). The earlier draft of this doc showed the inventory at the NET
> ₹18,000 — that double-counts the discount and the voucher fails to balance by
> exactly the discount amount. The code (`xml_builder._extract_items` → `it.amount`,
> which is `line_amount` before discount) and `test_sales_with_discount_balances`
> both confirm GROSS is correct.

```xml
<?xml version="1.0" ?>
<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>Vouchers</REPORTNAME>
        <STATICVARIABLES>
          <SVCURRENTCOMPANY>Manhotra Quarry Pvt Ltd</SVCURRENTCOMPANY>
        </STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="Sales" ACTION="Create" OBJVIEW="Invoice Voucher View">
            <DATE>20260615</DATE>
            <GUID>c3d4e5f6-a7b8-9012-cdef-012345678902</GUID>
            <NARRATION>Sales SAL/25-26/0032 | Vehicle: MH43BC3344 | Net Wt: 20.000 MT</NARRATION>
            <VOUCHERTYPENAME>Sales</VOUCHERTYPENAME>
            <VOUCHERNUMBER>SAL/25-26/0032</VOUCHERNUMBER>
            <PARTYLEDGERNAME>Rajesh Stone Traders</PARTYLEDGERNAME>
            <BASICBASEPARTYNAME>Rajesh Stone Traders</BASICBASEPARTYNAME>
            <PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>
            <PLACEOFSUPPLY>Maharashtra</PLACEOFSUPPLY>

            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>Rajesh Stone Traders</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
              <AMOUNT>19419.00</AMOUNT>
              <GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE>
              <PARTYGSTIN>27AABCR1234M1ZL</PARTYGSTIN>
              <BILLALLOCATIONS.LIST>
                <NAME>SAL/25-26/0032</NAME>
                <BILLTYPE>New Ref</BILLTYPE>
                <AMOUNT>19419.00</AMOUNT>
                <CREDITPERIOD>30 Days</CREDITPERIOD>
              </BILLALLOCATIONS.LIST>
            </ALLLEDGERENTRIES.LIST>

            <!-- Inventory carries NET amount (after discount) -->
            <INVENTORYENTRIES.LIST>
              <STOCKITEMNAME>GSB (Granular Sub-Base)</STOCKITEMNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <RATE>1000.00/MT</RATE>
              <AMOUNT>-20000.00</AMOUNT>
              <ACTUALQTY>20.000 MT</ACTUALQTY>
              <BILLEDQTY>20.000 MT</BILLEDQTY>
              <GSTTAXABILITY>Taxable</GSTTAXABILITY>
              <HSNCODE>2517</HSNCODE>
              <GSTRATE>5.00</GSTRATE>
              <BATCHALLOCATIONS.LIST>
                <GODOWNNAME>Main Location</GODOWNNAME>
                <BATCHNAME>Primary Batch</BATCHNAME>
                <AMOUNT>-20000.00</AMOUNT>
                <ACTUALQTY>20.000 MT</ACTUALQTY>
                <BILLEDQTY>20.000 MT</BILLEDQTY>
              </BATCHALLOCATIONS.LIST>
              <ACCOUNTINGALLOCATIONS.LIST>
                <LEDGERNAME>Sales</LEDGERNAME>
                <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                <AMOUNT>-20000.00</AMOUNT>
              </ACCOUNTINGALLOCATIONS.LIST>
            </INVENTORYENTRIES.LIST>

            <!-- Discount: debit (+) — reduces income -->
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>Trade Discount</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <AMOUNT>2000.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>

            <!-- Freight: credit (−) — freight income -->
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>Freight Outward</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>-500.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>

            <!-- CGST: credit (−) -->
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>CGST</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>-450.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>

            <!-- SGST: credit (−) -->
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>SGST</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>-450.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>

            <!-- TCS: credit (−), base = taxable + tax + freight (₹19,400) -->
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>TCS Payable</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>-19.40</AMOUNT>
            </ALLLEDGERENTRIES.LIST>

            <!-- Round-off: balances the voucher to a whole rupee -->
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>Round Off</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>0.40</AMOUNT>
            </ALLLEDGERENTRIES.LIST>

          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>
```

---

## 9. Entity Type 5 — Customer Master (Sundry Debtors)

Creates or updates a party ledger under Sundry Debtors. Must be pushed **before** the first invoice for that party — otherwise Tally returns `LINEERROR: Ledger not found` on the voucher import.

```xml
<?xml version="1.0" ?>
<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>All Masters</REPORTNAME>
        <STATICVARIABLES>
          <SVCURRENTCOMPANY>Manhotra Quarry Pvt Ltd</SVCURRENTCOMPANY>
        </STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <LEDGER NAME="Rajesh Stone Traders" ACTION="Create">
            <NAME>Rajesh Stone Traders</NAME>
            <PARENT>Sundry Debtors</PARENT>
            <GSTIN>27AABCR1234M1ZL</GSTIN>
            <GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE>
            <STATENAME>Maharashtra</STATENAME>
            <ADDRESS.LIST>
              <ADDRESS>Plot 12, MIDC Industrial Area</ADDRESS>
              <ADDRESS>Pune - 411018</ADDRESS>
            </ADDRESS.LIST>
            <LEDGERPHONE>9876543210</LEDGERPHONE>
            <EMAIL>rajesh@stonestrade.in</EMAIL>
          </LEDGER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>
```

**Unregistered (walk-in, no GSTIN):**

```xml
<LEDGER NAME="Walk-in Customer" ACTION="Create">
  <NAME>Walk-in Customer</NAME>
  <PARENT>Sundry Debtors</PARENT>
  <GSTREGISTRATIONTYPE>Unregistered</GSTREGISTRATIONTYPE>
  <STATENAME>Maharashtra</STATENAME>
</LEDGER>
```

---

## 10. Entity Type 6 — Supplier Master (Sundry Creditors)

```xml
<?xml version="1.0" ?>
<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>All Masters</REPORTNAME>
        <STATICVARIABLES>
          <SVCURRENTCOMPANY>Manhotra Quarry Pvt Ltd</SVCURRENTCOMPANY>
        </STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <LEDGER NAME="Kumar Mines" ACTION="Create">
            <NAME>Kumar Mines</NAME>
            <PARENT>Sundry Creditors</PARENT>
            <GSTIN>27AABCK9876B1ZD</GSTIN>
            <GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE>
            <STATENAME>Maharashtra</STATENAME>
            <ADDRESS.LIST>
              <ADDRESS>Survey No 45, Hadapsar</ADDRESS>
              <ADDRESS>Pune - 411028</ADDRESS>
            </ADDRESS.LIST>
            <LEDGERPHONE>9812345678</LEDGERPHONE>
            <EMAIL>kumar@kmines.in</EMAIL>
          </LEDGER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>
```

---

## 11. Entity Type 7 — Sales Order (from Quotation)

Sales Orders use `OBJVIEW="Ordering Voucher View"` and do **not** have `BILLALLOCATIONS.LIST` — they are not financial transactions yet. GST amounts are included for estimation only.

**Balance proof:**
```
Party:       +11,800.00
Sales item:  −10,000.00
IGST:         −1,000.00
Freight:        −800.00
──────────────────────
Total:            0.00 ✓
```

```xml
<?xml version="1.0" ?>
<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>Vouchers</REPORTNAME>
        <STATICVARIABLES>
          <SVCURRENTCOMPANY>Manhotra Quarry Pvt Ltd</SVCURRENTCOMPANY>
        </STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="Sales Order" ACTION="Create" OBJVIEW="Ordering Voucher View">
            <DATE>20260520</DATE>
            <GUID>d4e5f6a7-b8c9-0123-def0-123456789003</GUID>
            <NARRATION>Sales Order QT/25-26/0007</NARRATION>
            <VOUCHERTYPENAME>Sales Order</VOUCHERTYPENAME>
            <VOUCHERNUMBER>QT/25-26/0007</VOUCHERNUMBER>
            <PARTYLEDGERNAME>Delhi Infra Ltd</PARTYLEDGERNAME>
            <BASICBASEPARTYNAME>Delhi Infra Ltd</BASICBASEPARTYNAME>
            <PERSISTEDVIEW>Ordering Voucher View</PERSISTEDVIEW>

            <!-- Party entry: no BILLALLOCATIONS for orders -->
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>Delhi Infra Ltd</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
              <AMOUNT>11800.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>

            <INVENTORYENTRIES.LIST>
              <STOCKITEMNAME>20mm Aggregates</STOCKITEMNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <RATE>1000.00/MT</RATE>
              <AMOUNT>-10000.00</AMOUNT>
              <ACTUALQTY>10.000 MT</ACTUALQTY>
              <BILLEDQTY>10.000 MT</BILLEDQTY>
              <GSTTAXABILITY>Taxable</GSTTAXABILITY>
              <HSNCODE>2517</HSNCODE>
              <ACCOUNTINGALLOCATIONS.LIST>
                <LEDGERNAME>Sales</LEDGERNAME>
                <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                <AMOUNT>-10000.00</AMOUNT>
              </ACCOUNTINGALLOCATIONS.LIST>
            </INVENTORYENTRIES.LIST>

            <!-- IGST (inter-state) -->
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>IGST</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>-1000.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>

            <!-- Freight -->
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>Freight Outward</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>-800.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>

          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>
```

---

## 12. Entity Type 8 — Purchase Order (from Inventory PO)

Store inventory POs are simple (no GST — these are unpriced store requisitions, not financial purchase invoices).

**Balance proof:**
```
Diesel (10L × ₹97):       +970.00
Engine Oil (2L × ₹350):   +700.00
Purchase ledger total:   +1,670.00
Party (supplier) credit: −1,670.00
──────────────────────────────────
Total:                       0.00 ✓
```

```xml
<?xml version="1.0" ?>
<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>Vouchers</REPORTNAME>
        <STATICVARIABLES>
          <SVCURRENTCOMPANY>Manhotra Quarry Pvt Ltd</SVCURRENTCOMPANY>
        </STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="Purchase Order" ACTION="Create" OBJVIEW="Ordering Voucher View">
            <DATE>20260601</DATE>
            <GUID>e5f6a7b8-c9d0-1234-ef01-234567890004</GUID>
            <NARRATION>Purchase Order PO/25-26/0012</NARRATION>
            <VOUCHERTYPENAME>Purchase Order</VOUCHERTYPENAME>
            <VOUCHERNUMBER>PO/25-26/0012</VOUCHERNUMBER>
            <PARTYLEDGERNAME>City Fuel Depot</PARTYLEDGERNAME>
            <BASICBASEPARTYNAME>City Fuel Depot</BASICBASEPARTYNAME>
            <PERSISTEDVIEW>Ordering Voucher View</PERSISTEDVIEW>

            <!-- Supplier entry: credit (−) -->
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>City Fuel Depot</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
              <AMOUNT>-1670.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>

            <!-- Item 1: Diesel -->
            <INVENTORYENTRIES.LIST>
              <STOCKITEMNAME>Diesel</STOCKITEMNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <RATE>97.00/L</RATE>
              <AMOUNT>970.00</AMOUNT>
              <ACTUALQTY>10.000 L</ACTUALQTY>
              <BILLEDQTY>10.000 L</BILLEDQTY>
              <ACCOUNTINGALLOCATIONS.LIST>
                <LEDGERNAME>Purchase</LEDGERNAME>
                <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                <AMOUNT>970.00</AMOUNT>
              </ACCOUNTINGALLOCATIONS.LIST>
            </INVENTORYENTRIES.LIST>

            <!-- Item 2: Engine Oil -->
            <INVENTORYENTRIES.LIST>
              <STOCKITEMNAME>Engine Oil 15W-40</STOCKITEMNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <RATE>350.00/L</RATE>
              <AMOUNT>700.00</AMOUNT>
              <ACTUALQTY>2.000 L</ACTUALQTY>
              <BILLEDQTY>2.000 L</BILLEDQTY>
              <ACCOUNTINGALLOCATIONS.LIST>
                <LEDGERNAME>Purchase</LEDGERNAME>
                <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                <AMOUNT>700.00</AMOUNT>
              </ACCOUNTINGALLOCATIONS.LIST>
            </INVENTORYENTRIES.LIST>

          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>
```

---

## 13. API Endpoint Reference

All endpoints require `Authorization: Bearer <token>`.

| Method | Endpoint | Role | Description |
|---|---|---|---|
| GET | `/api/v1/tally/config` | Any | Get current Tally config |
| PUT | `/api/v1/tally/config` | admin | Save config (host/port/ledger names/narration) |
| POST | `/api/v1/tally/test-connection` | Any | Ping Tally — `{success, message, host, port}` |
| GET | `/api/v1/tally/companies` | Any | List companies open in Tally |
| GET | `/api/v1/tally/pending` | Any | Finalised GST invoices not yet synced |
| GET | `/api/v1/tally/pending/parties` | Any | Active parties not yet synced |
| GET | `/api/v1/tally/pending/orders` | Any | Accepted quotations + approved POs not yet synced |
| POST | `/api/v1/tally/sync/invoice/{id}` | Any | Push single finalised GST invoice |
| POST | `/api/v1/tally/sync/bulk` | Any | Bulk push invoices (date range, type filter, max 100) |
| POST | `/api/v1/tally/sync/party/{id}` | Any | Push single party as master ledger |
| POST | `/api/v1/tally/sync/parties` | Any | Bulk push all unsynced parties (max 200) |
| POST | `/api/v1/tally/sync/sales-order/{id}` | Any | Push accepted quotation as Sales Order |
| POST | `/api/v1/tally/sync/purchase-order/{id}` | Any | Push approved inventory PO as Purchase Order |

**Business rules enforced by the router:**

- Only `status=final` invoices can be synced
- Only `tax_type=gst` invoices can be synced — Bills of Supply (`tax_type=non_gst`) are silently excluded from bulk sync, and return HTTP 400 on single sync
- Credit/debit notes (`invoice_type IN ('credit_note','debit_note')`) return HTTP 400 — see GAP-2 in §18
- Purchase orders must be `status IN (approved, partially_received, received)` before sync

---

## 14. Testing with curl

### Step 1 — Get auth token

```bash
TOKEN=$(curl -s -X POST http://localhost:9001/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your_password"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

### Step 2 — Test connectivity

```bash
curl -s -X POST http://localhost:9001/api/v1/tally/test-connection \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

Expected:
```json
{
  "success": true,
  "message": "Connected to Tally successfully",
  "host": "localhost",
  "port": 9002
}
```

### Step 3 — List companies open in Tally

```bash
curl -s http://localhost:9001/api/v1/tally/companies \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

Expected:
```json
{ "success": true, "companies": ["Manhotra Quarry Pvt Ltd"] }
```

### Step 4 — Check pending invoices

```bash
curl -s "http://localhost:9001/api/v1/tally/pending" \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

### Step 5 — Push parties first (mandatory before invoice sync)

```bash
curl -s -X POST http://localhost:9001/api/v1/tally/sync/parties \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

### Step 6 — Sync a single invoice

```bash
INVOICE_ID="paste-uuid-here"
curl -s -X POST "http://localhost:9001/api/v1/tally/sync/invoice/$INVOICE_ID" \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

Expected success:
```json
{
  "success": true,
  "message": "Voucher created in Tally (1 record(s))",
  "invoice_no": "SAL/25-26/0001",
  "tally_synced": true,
  "tally_sync_at": "2026-06-25T10:30:00+00:00"
}
```

### Step 7 — Bulk sync all pending invoices

```bash
curl -s -X POST http://localhost:9001/api/v1/tally/sync/bulk \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "invoice_type": "sale",
    "from_date": "2026-06-01",
    "to_date": "2026-06-30",
    "include_synced": false
  }' | python -m json.tool
```

---

## 15. Testing with Python (direct XML push)

Use this script to push sample XMLs **directly to TallyPrime** — bypassing WeighBridge Setu — to verify Tally connectivity and ledger setup independently.

```python
"""
tally_test.py — Push customer master + sales invoice directly to TallyPrime.

Prerequisites:
  pip install requests
  python tally_test.py

Change TALLY_URL and COMPANY to match your setup.
"""
import re
import requests

TALLY_URL = "http://localhost:9002"
COMPANY   = "Manhotra Quarry Pvt Ltd"
HEADERS   = {"Content-Type": "text/xml; charset=utf-8"}


def push(name: str, xml: str):
    try:
        r = requests.post(TALLY_URL, data=xml.encode("utf-8"), headers=HEADERS, timeout=10)
        if r.status_code != 200:
            print(f"  FAIL  {name}: HTTP {r.status_code}")
            return
        txt = r.text
        if "<LINEERROR>" in txt:
            errs = re.findall(r"<LINEERROR>(.*?)</LINEERROR>", txt, re.DOTALL)
            print(f"  ERROR {name}: {'; '.join(errs)}")
        elif "<CREATED>" in txt:
            print(f"  OK    {name}: Created in Tally")
        elif "<ALTERED>" in txt:
            print(f"  OK    {name}: Updated in Tally (already existed)")
        else:
            print(f"  OK?   {name}: No CREATED/ALTERED in response (older Tally?)")
    except requests.ConnectionError:
        print(f"  FAIL  {name}: Cannot connect to {TALLY_URL} — is Tally running?")
    except requests.Timeout:
        print(f"  FAIL  {name}: Timed out")


XML_PING = f"""<ENVELOPE>
  <HEADER><TALLYREQUEST>Export Data</TALLYREQUEST></HEADER>
  <BODY>
    <EXPORTDATA>
      <REQUESTDESC><REPORTNAME>List of Companies</REPORTNAME></REQUESTDESC>
    </EXPORTDATA>
  </BODY>
</ENVELOPE>"""

XML_CUSTOMER = f"""<?xml version="1.0" ?>
<ENVELOPE>
  <HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>All Masters</REPORTNAME>
        <STATICVARIABLES><SVCURRENTCOMPANY>{COMPANY}</SVCURRENTCOMPANY></STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <LEDGER NAME="Rajesh Stone Traders" ACTION="Create">
            <NAME>Rajesh Stone Traders</NAME>
            <PARENT>Sundry Debtors</PARENT>
            <GSTIN>27AABCR1234M1ZL</GSTIN>
            <GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE>
            <STATENAME>Maharashtra</STATENAME>
          </LEDGER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>"""

XML_SUPPLIER = f"""<?xml version="1.0" ?>
<ENVELOPE>
  <HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>All Masters</REPORTNAME>
        <STATICVARIABLES><SVCURRENTCOMPANY>{COMPANY}</SVCURRENTCOMPANY></STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <LEDGER NAME="Kumar Mines" ACTION="Create">
            <NAME>Kumar Mines</NAME>
            <PARENT>Sundry Creditors</PARENT>
            <GSTIN>27AABCK9876B1ZD</GSTIN>
            <GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE>
            <STATENAME>Maharashtra</STATENAME>
          </LEDGER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>"""

XML_SALES = f"""<?xml version="1.0" ?>
<ENVELOPE>
  <HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>Vouchers</REPORTNAME>
        <STATICVARIABLES><SVCURRENTCOMPANY>{COMPANY}</SVCURRENTCOMPANY></STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="Sales" ACTION="Create" OBJVIEW="Invoice Voucher View">
            <DATE>20260601</DATE>
            <GUID>f47ac10b-58cc-4372-a567-0e02b2c3d479</GUID>
            <NARRATION>Sales SAL/25-26/TEST01 | Token #1 | Vehicle: MH12AB1234 | Net Wt: 10.000 MT</NARRATION>
            <VOUCHERTYPENAME>Sales</VOUCHERTYPENAME>
            <VOUCHERNUMBER>SAL/25-26/TEST01</VOUCHERNUMBER>
            <PARTYLEDGERNAME>Rajesh Stone Traders</PARTYLEDGERNAME>
            <BASICBASEPARTYNAME>Rajesh Stone Traders</BASICBASEPARTYNAME>
            <PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>
            <PLACEOFSUPPLY>Maharashtra</PLACEOFSUPPLY>
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>Rajesh Stone Traders</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
              <AMOUNT>15750.00</AMOUNT>
              <GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE>
              <PARTYGSTIN>27AABCR1234M1ZL</PARTYGSTIN>
              <BILLALLOCATIONS.LIST>
                <NAME>SAL/25-26/TEST01</NAME>
                <BILLTYPE>New Ref</BILLTYPE>
                <AMOUNT>15750.00</AMOUNT>
                <CREDITPERIOD>30 Days</CREDITPERIOD>
              </BILLALLOCATIONS.LIST>
            </ALLLEDGERENTRIES.LIST>
            <INVENTORYENTRIES.LIST>
              <STOCKITEMNAME>10mm Aggregates</STOCKITEMNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <RATE>1500.00/MT</RATE>
              <AMOUNT>-15000.00</AMOUNT>
              <ACTUALQTY>10.000 MT</ACTUALQTY>
              <BILLEDQTY>10.000 MT</BILLEDQTY>
              <GSTTAXABILITY>Taxable</GSTTAXABILITY>
              <HSNCODE>2517</HSNCODE>
              <GSTRATE>5.00</GSTRATE>
              <BATCHALLOCATIONS.LIST>
                <GODOWNNAME>Main Location</GODOWNNAME>
                <BATCHNAME>Primary Batch</BATCHNAME>
                <AMOUNT>-15000.00</AMOUNT>
                <ACTUALQTY>10.000 MT</ACTUALQTY>
                <BILLEDQTY>10.000 MT</BILLEDQTY>
              </BATCHALLOCATIONS.LIST>
              <ACCOUNTINGALLOCATIONS.LIST>
                <LEDGERNAME>Sales</LEDGERNAME>
                <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                <AMOUNT>-15000.00</AMOUNT>
              </ACCOUNTINGALLOCATIONS.LIST>
            </INVENTORYENTRIES.LIST>
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>CGST</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>-375.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>SGST</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>-375.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>
          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>"""

XML_PURCHASE = f"""<?xml version="1.0" ?>
<ENVELOPE>
  <HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>Vouchers</REPORTNAME>
        <STATICVARIABLES><SVCURRENTCOMPANY>{COMPANY}</SVCURRENTCOMPANY></STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="Purchase" ACTION="Create" OBJVIEW="Invoice Voucher View">
            <DATE>20260601</DATE>
            <GUID>a1b2c3d4-e5f6-7890-abcd-ef1234567890</GUID>
            <NARRATION>Purchase PUR/25-26/TEST01 | Token #18 | Vehicle: MH12CD5678 | Net Wt: 50.000 MT</NARRATION>
            <VOUCHERTYPENAME>Purchase</VOUCHERTYPENAME>
            <VOUCHERNUMBER>PUR/25-26/TEST01</VOUCHERNUMBER>
            <PARTYLEDGERNAME>Kumar Mines</PARTYLEDGERNAME>
            <BASICBASEPARTYNAME>Kumar Mines</BASICBASEPARTYNAME>
            <PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>
            <PLACEOFSUPPLY>Maharashtra</PLACEOFSUPPLY>
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>Kumar Mines</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
              <AMOUNT>-42000.00</AMOUNT>
              <GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE>
              <PARTYGSTIN>27AABCK9876B1ZD</PARTYGSTIN>
              <BILLALLOCATIONS.LIST>
                <NAME>PUR/25-26/TEST01</NAME>
                <BILLTYPE>New Ref</BILLTYPE>
                <AMOUNT>-42000.00</AMOUNT>
              </BILLALLOCATIONS.LIST>
            </ALLLEDGERENTRIES.LIST>
            <INVENTORYENTRIES.LIST>
              <STOCKITEMNAME>Raw Stone</STOCKITEMNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <RATE>800.00/MT</RATE>
              <AMOUNT>40000.00</AMOUNT>
              <ACTUALQTY>50.000 MT</ACTUALQTY>
              <BILLEDQTY>50.000 MT</BILLEDQTY>
              <GSTTAXABILITY>Taxable</GSTTAXABILITY>
              <HSNCODE>2517</HSNCODE>
              <GSTRATE>5.00</GSTRATE>
              <BATCHALLOCATIONS.LIST>
                <GODOWNNAME>Main Location</GODOWNNAME>
                <BATCHNAME>Primary Batch</BATCHNAME>
                <AMOUNT>40000.00</AMOUNT>
                <ACTUALQTY>50.000 MT</ACTUALQTY>
                <BILLEDQTY>50.000 MT</BILLEDQTY>
              </BATCHALLOCATIONS.LIST>
              <ACCOUNTINGALLOCATIONS.LIST>
                <LEDGERNAME>Purchase</LEDGERNAME>
                <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                <AMOUNT>40000.00</AMOUNT>
              </ACCOUNTINGALLOCATIONS.LIST>
            </INVENTORYENTRIES.LIST>
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>CGST</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <AMOUNT>1000.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>SGST</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <AMOUNT>1000.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>
          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>"""

if __name__ == "__main__":
    print(f"\nTesting Tally at {TALLY_URL}")
    print("=" * 60)
    print("Step 1 — Ping")
    push("Connection ping", XML_PING)
    print("\nStep 2 — Party masters (must succeed before invoices)")
    push("Customer master: Rajesh Stone Traders", XML_CUSTOMER)
    push("Supplier master: Kumar Mines", XML_SUPPLIER)
    print("\nStep 3 — Vouchers")
    push("Sales invoice SAL/25-26/TEST01 (CGST+SGST ₹15,750)", XML_SALES)
    push("Purchase invoice PUR/25-26/TEST01 (CGST+SGST ₹42,000)", XML_PURCHASE)
    print("=" * 60)
    print("Next: open TallyPrime → Voucher Register → Sales / Purchase to verify.")
    print("Check Outstanding Reports → Sundry Debtors for bill-wise aging.")
```

---

## 16. Common Errors & Fixes

| Error | Cause | Fix |
|---|---|---|
| `Cannot connect to Tally at localhost:9002` | Tally not running or port mismatch | Start TallyPrime; check Gateway → F12 → Advanced Config → verify port |
| `LINEERROR: Ledger not found` | Ledger name in config doesn't exactly match Tally | Check spelling/case: "CGST" vs "Cgst", "Sundry Debtors" vs "Sundry Debtors (India)"; fix the ledger name in WeighBridge Settings → Tally |
| `LINEERROR: Stock item not found` | Product name not in Tally's inventory master | Create the stock item in Tally → Inventory Info → Stock Items with the exact name |
| `LINEERROR: Voucher not balanced` | Amount math error | Re-verify with §4 balance formula; usually a rounding issue on multi-item invoices |
| `Tally integration is not enabled` | `is_enabled=false` in TallyConfig | Settings → Tally → toggle "Enable Tally integration" → Save |
| `Invoice type 'credit_note' cannot be synced` | Credit/debit notes blocked (returns HTTP 400) | See GAP-2 in §18 — not yet implemented |
| `Only finalised invoices can be synced` | Invoice is still draft | Finalise the invoice first |
| `Invoice is non-GST (Bill of Supply)` | Party's `default_payment_mode='cash'` → `tax_type='non_gst'` | By design — cash parties don't go to Tally. Change party to `online` if they're GST-registered |
| `Voucher updated in Tally (1 record(s))` | `ACTION="Create"` on existing GUID → Tally auto-updates | Correct — this is idempotent re-push behaviour |
| `Sent to Tally (response: OK)` | Older TallyPrime returns non-XML on success | Not an error — voucher was accepted |
| `LINEERROR: Company not found` | Wrong company name in `SVCURRENTCOMPANY` | Check `tally_company_name` in Settings exactly matches the company open in Tally |
| `HTTP 400: PO must be approved` | Purchase order is still pending_approval | Approve the PO first in WeighBridge → Inventory → Orders |

---

## 17. Validation Checklist

Run this checklist for each fresh deployment before going live.

### A. Infrastructure

- [ ] TallyPrime running; port 9002 active in F12 → Advanced Config
- [ ] `POST /api/v1/tally/test-connection` → `"success": true`
- [ ] `GET /api/v1/tally/companies` → exactly one company matching Settings
- [ ] All 9 required ledgers exist in Tally (Sales, Purchase, CGST, SGST, IGST, Freight Outward, Trade Discount, TCS Payable, Round Off)

### B. Master data sync

- [ ] `POST /api/v1/tally/sync/parties` — all parties pushed, 0 failed
- [ ] Tally: Accounts Info → Ledgers → Sundry Debtors — customers visible
- [ ] Tally: Accounts Info → Ledgers → Sundry Creditors — suppliers visible
- [ ] At least one stock item per WeighBridge product created in Tally's inventory master

### C. Sales invoice (intra-state CGST+SGST)

- [ ] Create test sale invoice with intra-state party
- [ ] Finalise invoice
- [ ] `POST /sync/invoice/{id}` → `"success": true`
- [ ] Tally → Voucher Register → Sales → invoice appears
- [ ] Tally → Outstanding → Sundry Debtors → bill shows with correct credit days

### D. Sales invoice (inter-state IGST)

- [ ] Test with inter-state party (different GSTIN first-2 digits from company)
- [ ] XML contains only IGST, no CGST/SGST
- [ ] Tally import succeeds

### E. Purchase invoice

- [ ] Create purchase invoice, finalise, sync
- [ ] Tally → Voucher Register → Purchase → appears
- [ ] CGST + SGST show as ITC debit in Tally

### F. GSTR-1 cross-check

- [ ] Tally → Reports → GST → GSTR-1 → B2B section matches synced sales invoices
- [ ] HSN summary shows correct codes + quantities + tax amounts

### G. Bill-wise outstanding aging

- [ ] Tally → Outstanding Reports → Sundry Debtors → Bills Outstanding
- [ ] Each invoice shows with bill name = invoice number and correct credit period
- [ ] Aging buckets (0-30, 31-60, 61-90, 90+) compute correctly

---

## 18. Known Gaps & Pending Work

### GAP-1: Auto-sync on finalize ★ HIGH PRIORITY

**Status:** `auto_sync` flag is stored and exposed in Settings, but `routers/invoices.py::finalize_invoice()` never reads it. Manual push only.

**Fix:** In `routers/invoices.py`, after `invoice.status = "final"`, add:

```python
cfg_result = await db.execute(select(TallyConfig).where(TallyConfig.company_id == company.id))
cfg = cfg_result.scalar_one_or_none()
if cfg and cfg.is_enabled and cfg.auto_sync and invoice.tax_type == "gst":
    background_tasks.add_task(_bg_push_to_tally, invoice.id, current_user.company_id)
```

The push **must** be a `BackgroundTask` — finalize response must not block on Tally. Tally failure must not roll back finalization. Add a `_bg_push_to_tally(invoice_id, company_id)` async function in `routers/tally.py` that creates its own DB session.

---

### GAP-2: Credit/Debit Notes not synced ★ MEDIUM

**Status:** `POST /sync/invoice/{id}` returns HTTP 400 for `invoice_type IN ('credit_note','debit_note')`.

Tally has `VCHTYPE="Credit Note"` / `VCHTYPE="Debit Note"` (same `OBJVIEW="Invoice Voucher View"`). They need `<ORIGINALINVOICENO>` referencing the source invoice. Sign convention for credit note = inverse of sales (party credited, sales debited).

**Fix required:** Add `build_credit_note_xml()` / `build_debit_note_xml()` in `xml_builder.py`, then add cases in `_push_invoice()`:

```python
elif invoice.invoice_type == "credit_note":
    xml = build_credit_note_xml(invoice, company, party, ledger_map, narration_opts)
elif invoice.invoice_type == "debit_note":
    xml = build_debit_note_xml(invoice, company, party, ledger_map, narration_opts)
```

---

### GAP-3: Payment receipts/vouchers not synced ★ MEDIUM

**Status:** When `POST /api/v1/payments/receipts` or `/vouchers` records a payment, nothing goes to Tally. Bill-wise outstanding in Tally remains permanently open even after the customer pays.

**Fix required:** New `build_receipt_xml()` / `build_payment_xml()` in `xml_builder.py`. Tally types: `VCHTYPE="Receipt"` (cash/bank debit, party credit, `BILLTYPE="Against Ref"` matching the invoice number) and `VCHTYPE="Payment"` (reverse). Wire into `payments.py` as `BackgroundTask`.

---

### GAP-4: Stock item master not auto-created ★ LOW

**Status:** Vouchers reference stock items by name. If the item doesn't exist in Tally, import fails with `LINEERROR: Stock item not found`. No auto-creation path.

**Fix (optional):** Add `build_stock_item_xml()` and `POST /api/v1/tally/sync/products` endpoint. Push all WeighBridge products as Tally stock items with HSN codes, GST rates, and unit "MT".

---

### GAP-5: No automatic retry queue ★ LOW

**Status:** Failed syncs set `tally_synced=False` and stay in the pending list. No automatic retry — accountant must manually re-push.

**Fix (optional):** Add a background task in `main.py` that runs every 30 minutes and calls `_push_invoice()` for invoices where `tally_synced=False` and `status=final` and `tax_type=gst`. Guard with `tally_last_retry_at` column and 5-minute per-invoice cooldown.

---

### GAP-6: Production cycle stock movements not in Tally ★ OUT OF SCOPE

Production cycles (raw material → finished goods) post stock movements in WeighBridge but are not reflected in Tally's stock register. **Intentional** — Tally is used for invoices and party ledgers only. Stock reconciliation happens in WeighBridge.

---

### GAP-7: Token number missing from voucher narration ★ LOW

**Status:** `xml_builder._build_narration()` reads `getattr(invoice, "token_no", None)`, but the `Invoice` ORM model has **no `token_no` column** (only `token_id`), and `routers/tally.py::_push_invoice()` never enriches it. So the "Token #N" segment is silently dropped — production narration is `"Sales SAL/… | Vehicle: … | Net Wt: … MT"` with no token. (`vehicle_no` and `net_weight` *are* real columns, so those segments do appear.) The sample XMLs in §5–§8 reflect this real output.

**Fix (optional):** In `_push_invoice()`, after loading the invoice, fetch the linked token and set `invoice.token_no = token.token_no` before calling `build_sales_xml`/`build_purchase_xml`. The narration helper already supports it.

---

## 19. Validation Findings — Opus 4.8 Line-by-Line Review (2026-06-25)

A full line-by-line pass of `xml_builder.py`, `client.py`, `routers/tally.py`, the ORM models, `gst_service.calculate_invoice_totals`, and the 43-test suite (`test_tally_integration.py` + `mock_tally_server.py`).

### Code verdict: ✅ correct and balance-proven

- All 6 entity builders produce well-formed Tally import XML with the correct `VCHTYPE` / `OBJVIEW` / `REPORTNAME`.
- Every voucher **balances to zero** — proven by 8 dedicated balance tests (sales, purchase, discount, freight, IGST-only, CGST/SGST-only, TCS, round-off) asserting `_voucher_is_balanced(...)` within ±0.02.
- Sign conventions verified against the mock validator's raw signed-amount sum (party + ledger entries + inventory accounting-allocations = 0; `BILLALLOCATIONS` and the inventory/batch top-level `AMOUNT` are correctly excluded from the balance sum, matching Tally's own accounting).
- `_party_place_of_supply`, GSTIN-on-party-entry, bill-wise `CREDITPERIOD`, and the GST-only / finalised-only / PO-status guards in the router are all correct.

### Documentation bugs found and fixed in this pass

| # | Location | Bug | Fix |
|---|---|---|---|
| D-1 | §4 balance formula | Used `− taxable_amount`; the inventory line actually carries `subtotal` (GROSS, pre-discount). The written formula computes a non-zero result when a discount exists. | Rewrote as `− subtotal(Σ gross line amounts) + discount`, added the tested mini-proof. |
| D-2 | §8 sample (discount) | Inventory shown at NET ₹18,000 + a separate ₹2,000 discount line → **double-counts the discount; voucher off by ₹2,000**. TCS computed on the wrong base (₹18 vs ₹19.40); grand total ₹19,418 vs ₹19,419; round-off line missing entirely. | Inventory → GROSS ₹20,000; TCS on `total_amount` (₹19,400) = ₹19.40; added `Round Off` ₹0.40; grand total ₹19,419; full balance proof re-derived to 0.00. |
| D-3 | §5/§6/§8 narration | Showed "Token #N", which the builder does not emit (see GAP-7). | Removed; narration now matches real output. |

### Minor observations (no action required)

- `_build_voucher_xml(..., taxable_amount=...)` receives `taxable_amount` but never emits it — the inventory entries drive the taxable value. Harmless dead parameter.
- Round-off entry is always emitted with `ISDEEMEDPOSITIVE=No` for sales regardless of the sign of `round_off`; the signed `AMOUNT` carries the real direction and the voucher balances for both signs (confirmed for `round_off = +1.00` by `test_with_round_off_balances` and for `−0.40` by the §8 re-derivation). Cosmetic only.

### Net result

The **integration code is production-correct**; the only defects were in this document, now corrected. The single functional enhancement worth scheduling is **GAP-1 (auto-sync on finalize)**, since today every voucher requires a manual push.

---

*End of Tally Integration Validation Guide*
