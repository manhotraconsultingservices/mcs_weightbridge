# Weighbridge Software — User Manual for the **Accountant**

> A plain-language, task-by-task guide for the person who handles the money:
> receipts, payments, expenses, the ledger, GST returns and the daily/period
> reports. No accounting jargon assumed. Keep this handy for the first few weeks.

**Who this is for:** staff logged in with the **Accountant** role.
**What you can do:** record money in and out, manage party balances, close bad
debts, run the Day Book, P&L and GST reports, and reconcile cash.
**What you cannot do:** system settings, user management, backups (those are the
Admin's job). If the maker-checker control is switched on, some money actions
you start will need an **Admin to approve** before they take effect (explained in
§12).

---

## 1. Getting started

1. Open the app in your browser (your Admin will give you the address, e.g.
   `https://<yourcompany>.weighbridgesetu.com`).
2. Enter your **username** and **password**. If your company uses a **Company
   Code**, type it in that field too.
3. You land on the **Dashboard**. On a phone, tap the **☰** menu (top-left) to
   open the sidebar; there's also a bottom tab bar.

**Trouble logging in?** After 5 wrong passwords the system locks that computer
for 15 minutes (a security feature). Wait, or ask your Admin to reset your
password.

### Your menu (sidebar)
As an Accountant you'll mainly use:

| Menu item | What it's for |
|---|---|
| **Dashboard** | Today's snapshot: collections, outstanding, top customers |
| **Payments** | Record money **received** (receipts) and money **paid** (vouchers/expenses) |
| **Customers / Parties** | Customer & supplier list, balances, Customer 360 |
| **Account Statement / Ledger** | Party-wise running balance + outstanding with ageing |
| **Reports** | Day Book, P&L, GST returns, Sales register, Write-offs, and more (tabs) |
| **Day Book** | Quick link to the end-of-day cash summary |

> **Rule of thumb:** *money movement* → **Payments**. *"How much does X owe / did
> we earn / must we file"* → **Reports** or **Ledger**.

---

## 2. Understanding the two money directions

Everything in accounts is one of two things:

- **Money IN (Receipts)** — a customer pays you for a sale.
- **Money OUT (Vouchers)** — you pay a supplier, **or** you pay a running
  expense (electricity, rent, EMI, diesel, wages…). Expenses are a special kind
  of voucher (see §4).

Both live under **Payments**, on two tabs: **Receipts** and **Vouchers**.

---

## 3. Record money received (a customer payment) — **Receipts**

Use this when a customer hands over cash, pays by UPI, or transfers to the bank.

1. Go to **Payments → Receipts → Record Receipt**.
2. Pick the **Customer**. As soon as you pick them, the screen shows their
   **current outstanding** (e.g. *"₹45,000 to collect — customer owes"*), so you
   know the context.
3. Enter the **amount** received and the **payment mode** (Cash / UPI / Bank /
   Cheque / Card).
4. **Allocate to invoices (auto):** the app automatically applies the money to
   the customer's **oldest unpaid bills first** (FIFO) — you'll see it fill each
   bill until the amount runs out. This is the "**Auto-offset (oldest first)**"
   checkbox, on by default.
   - To split the payment your own way, **untick** auto-offset and type the
     amount against each bill manually.
5. **More than the bills?** If the amount is larger than what's owed, the app
   shows *"₹X will be recorded as an advance (on account)"* — the extra becomes a
   **customer advance** you can use against future bills (see §5).
6. **Save.**

> **Cash vs Bank matters** for the Day Book: a *Cash* receipt lands in the Cash
> column, UPI/Bank/Cheque/Card land in the Bank column. Pick the correct mode.

### Recording who collected the cash (operator handover)
If a **weighbridge operator** collected the cash at the gate and you're just
entering it, set **"Collected by (operator)"** on the receipt to that operator.
This makes the end-of-day **Operator Cash** report attribute the cash to the
right person (see §11).

---

## 4. Record money paid out — **Vouchers** (supplier payments **and** expenses)

Open **Payments → Vouchers → Record Voucher**. There are two kinds:

### (a) Paying a supplier (against purchases)
1. Leave **"Direct expense"** unticked.
2. Pick the **Supplier**; the screen shows what you owe them.
3. Enter amount + mode; the app **auto-offsets the oldest purchase bills first**
   (same as receipts). Overpayment becomes a **supplier advance**.
4. Save.

### (b) Paying a running expense / overhead (Electricity, Rent, EMI, Repairs…)
This is money that is **not** tied to a supplier bill — it's an overhead that
reduces your profit.

1. **Tick "Direct expense (overhead)".** The supplier picker disappears.
2. **Category:** pick a saved category **or type a new one** (e.g. `EMI`,
   `Loan interest`, `Diesel`, `Office`). A new one you type is remembered for
   next time.
3. Enter amount + mode + a note, and **Save**.

Direct expenses automatically appear as **Overhead** on the **Profit & Loss**
report and as money-out on the **Day Book** — so your profit is correct.

> **EMI caution (ask your CA):** only the **interest** part of a loan EMI is a
> P&L expense; the **principal** repayment is a balance-sheet item, not an
> expense. If you want the P&L accurate, book them as two categories, e.g.
> `Loan interest` (expense) and a separate line for principal.

---

## 5. Advances (prepaid money)

An **advance** is money received (or paid) *before* the bill exists.

- **Customer advance:** a customer pays ₹50,000 up front. Record it as a
  **Receipt** with **no invoice allocation** (or leave a remainder). It shows as
  a credit. When you later finalise their invoices, the advance is **used up
  automatically, oldest bill first**.
- **Supplier advance:** you pay a supplier ahead of their bill — record a
  **Voucher** with no allocation.

There's also a dedicated **Advances** screen (Accounts area) to record and see
every party holding an advance, with a running total. Fully-used advances drop
off the list automatically.

---

## 6. Party Ledger, Outstanding & Balances

### Account Statement / Ledger
Go to **Ledger** (Account Statement). Pick a party to see their **running
balance** — every sale, purchase, receipt, payment and write-off in date order,
with the balance carried forward. If you set a start date, everything before it
is folded into an **"Opening balance b/f"** line, so the statement always closes
at the party's true current balance.

### Outstanding (with ageing)
The **Outstanding** view groups unpaid amounts into buckets:
**Current · 1–30 · 31–60 · 61–90 · 90+ days**. Use this to chase old money —
the 90+ column is where bad debt hides.

### Balances by party
**Reports → Balances** lists every customer/supplier with **Bills · Advance ·
Net** and a Customer/Supplier filter, exportable to CSV. This is your quick
"who owes what / whom do we owe" sheet.

### Customer 360
Click any **customer name** (in Parties, Ledger, or Dashboard) to open their
**360 page**: lifetime sales, outstanding, ageing chart, last 20 invoices, last
20 payments, custom rates, and write-off history — everything about one party on
one screen.

---

## 7. Working with invoices

You don't usually *create* weighbridge invoices (they're auto-created when a
truck completes weighing), but as Accountant you **finalise, settle, correct and
close** them. Open **Sales** (Bills) or **Purchases**.

### Finalise a draft
A draft invoice has **no number** yet. **Finalise** assigns the legal GST number
(`INV/25-26/0001`) and locks it. Only finalised invoices count in GST returns and
the ledger.

### Record a payment on a specific invoice
Click the **₹ / banknote** icon on an invoice row to record a payment straight
against that bill (a shortcut to the receipt flow).

### Write off a bad debt (uncollectable balance)
When a customer will never pay, you **write off** the balance so it stops showing
as receivable and is booked as a bad-debt expense.

1. On the finalised sale invoice, click the **amber write-off** icon.
2. Confirm the amount (defaults to the full balance) and **enter a reason**
   (required — it's saved in the audit log).
3. Confirm. The invoice closes, the customer's balance drops, and the amount
   shows on the **Write-offs** report and reduces **P&L** net profit.

**Mass write-off:** on a customer's **360 page**, tick several invoices and use
**"Write off N invoices"** to close a whole defaulting customer at once.

> If **maker-checker is ON**, a write-off doesn't take effect immediately — it's
> sent for an Admin to approve first (see §12).

### Correct a finalised invoice — **Revision**
You can't edit a finalised invoice directly (it's a legal document). Instead
create a **Revision**: it makes a new draft copy; when you finalise it you get a
`…/Rv2` number and a full record of what changed.

### Credit / Debit Notes
To adjust a finalised invoice (returns, rate correction, extra charge), issue a
**Credit Note** (reduces what the customer owes) or **Debit Note** (increases it)
against the original — **Sales → Notes**. These flow into GSTR-1 (CDNR)
automatically.

### Cancel an invoice
Cancelling a finalised invoice reverses its stock and returns any allocated
payments to the party as an advance. (Under maker-checker, a cancel also needs
Admin approval — §12.)

---

## 8. The Day Book (your daily cash register)

There are **two** Day Books — they answer different questions.

### A. Day Book (Cash Book) — the traditional hand-written sheet
**Reports → Day Book (Cash Book)**. Reproduces the classic daily cash book:

```
Opening Balance B/F   →   Receipts (money in)   −   Payments (money out)   →   Closing Balance C/F
```

…with **Cash · Bank · CC/OD** columns. Each day's **Closing** automatically
becomes the next day's **Opening** — you never re-enter it. **Print** or **CSV**
at the bottom.

**Setting the Opening Balance (one-time, then it rolls forward):**
1. Click **"Opening balance"** (admin/accountant only).
2. Enter a **start date** and the cash-in-hand, bank and CC/OD balances **as of
   that date**.
3. Save. From then on the Day Book rolls forward automatically day by day.

> **Fraud control:** every change to the Opening Balance is recorded in the
> **Audit Trail** (who, when, from which computer, old → new value). And if
> maker-checker is ON, changing it needs Admin approval. Set it once, correctly.

### B. Day Book (EOD) — end-of-day business summary
**Reports → Day Book (EOD)** (also the **Day Book** sidebar item). A summary of:
**Cash sales vs Bank/UPI collections**, and money-out itemised (Purchases · Store
· Diesel · Salary · Advances · Commission · Overheads) with a **Net** for each
day. Date presets (Today / Yesterday / Last-7 / Month), CSV export.

> Both are cash-book views and are **different from the P&L** (§9), which is an
> accrual profit statement.

---

## 9. Profit & Loss (P&L)

**Reports → P&L**. A real profit statement by month:

```
Revenue (net of credit/debit notes)  −  COGS  =  Gross Profit
    −  Labour  −  Store inventory  −  Fuel/Diesel  −  Commission  −  Overheads  −  Write-offs
    =  Net Profit
```

- **Overheads** = your direct-expense vouchers from §4(b).
- **Optional stock adjustment:** enter **Opening** and **Closing** stock values
  (₹, from your CA) and the P&L uses *goods actually sold*:
  `COGS = Opening + Purchases − Closing`. Save the figures with **"Save stock
  values"** and they pre-fill next time.
- Advances are correctly **excluded** (they're not income/expense yet).

---

## 10. GST returns

**GST Reports** (and Reports → GST tabs).

- **GSTR-1** (outward sales): B2B + B2C + HSN summary + credit/debit notes.
  Filter by month/year, export **CSV** or the **GSTN portal JSON**.
- **GSTR-3B**: outward tax (3.1), input tax credit (4), and net tax payable —
  net of credit/debit notes.
- **GSTR-2B (ITC) reconciliation** (**Reports → GSTR-2B**): upload the GSTR-2B
  JSON you download from the GST portal; the app matches it against your purchase
  invoices and shows **Matched · Value-mismatch · In-2B-not-in-books (claim this
  ITC) · In-books-not-in-2B (chase the supplier)**.
- **GST vs Cash split** (**Reports → GST vs Cash Split**): how much of your sales
  are GST tax invoices vs non-GST Bills of Supply (cash).

> **Reminder:** cash sales are usually a **Bill of Supply** (non-GST) and are
> correctly excluded from GSTR-1. GST invoices are the ones that go on the
> return. The app handles this automatically from each party's payment mode.

---

## 11. End-of-day cash reconciliation (Operator Cash)

If operators collect cash at the gate, reconcile it daily:

1. **Reports → Operator Cash (EOD)**. It lists each operator with **Opening float
   · Cash collected · Handed over · Expected · Counted · Variance**.
2. Use **"Count"** to enter the operator's **opening float** and the **physically
   counted cash**; the app shows the **variance** (turns amber if it doesn't
   match expected).
3. Use **"Receive cash"** to record the handover into accounts.

> **Daily nudge:** if an operator collected cash today but nobody recorded a
> count, the owner gets an automatic reminder in the evening. Recording the count
> each day closes the skimming gap — make it a habit.

---

## 12. Maker-checker approvals (4-eyes) — **read this if it's switched on**

Your company may turn on a **maker-checker** control so that sensitive money
actions need **two people**. When it's ON, if **you** (the "maker") do any of
these:

- Write off an invoice (single or bulk)
- Cancel a finalised invoice
- Change the Day Book **Opening Balance**

…the action **does not happen immediately**. Instead you'll see:
**"Submitted for approval — a second admin must approve before it takes effect."**

- Nothing changes until a **different Admin** (the "checker") approves it on the
  **Approvals** page. You **cannot approve your own** request (that's the whole
  point — 4-eyes).
- If it's approved, the action runs exactly as you intended, recorded under your
  name.
- If it's rejected, nothing happens and you'll be told.

When maker-checker is **OFF** (the default), these actions work instantly as
before. You don't need to do anything differently — just be aware of the
"submitted for approval" message if you see it.

---

## 13. Tally sync (if your company uses Tally)

If Tally is enabled, finalised GST invoices can be pushed to Tally — either
automatically (auto-sync) or via the **🔄 Sync to Tally** buttons on the
Parties/Products pages and invoice list. This is usually set up by the Admin; as
Accountant you mainly confirm invoices are finalised so they're eligible to sync.

---

## 14. Month-end / period-end checklist

Run through this at the close of each month:

- [ ] All completed weighbridge tokens have a **finalised** invoice (check **Reports → Sales by Status** — Draft vs Complete).
- [ ] All customer payments **received** are recorded (Payments → Receipts).
- [ ] All supplier payments and **expenses** are recorded (Payments → Vouchers), including EMIs/rent/electricity.
- [ ] **Outstanding** reviewed; genuinely bad debts **written off** with reasons.
- [ ] **Day Book (Cash Book)** closing balances match your physical cash + bank statement.
- [ ] **Operator cash** counts recorded and variances explained.
- [ ] **GSTR-1** and **GSTR-3B** generated and reconciled with **GSTR-2B** for ITC.
- [ ] **P&L** reviewed (with opening/closing stock values from the CA) — the Net Profit looks right.
- [ ] Any **advances** correctly reflected.

---

## 15. Quick tips & cautions

- **Always pick the correct payment mode** (Cash vs UPI/Bank) — it drives the Day Book columns and GST behaviour.
- **A write-off is permanent** and needs a reason — use it only for money you'll truly never collect.
- **Don't try to edit a finalised invoice** — use a **Revision** or a **Credit/Debit Note**.
- **Set the Day Book opening balance once, carefully** — it rolls forward and every change is audited.
- **`.toFixed`/rounding:** amounts on screen are rounded to paise; the system keeps exact figures internally.
- **Numbers look wrong?** Most "wrong balance" issues are a missing receipt/voucher or a payment recorded against the wrong party — check the party's **Ledger** first.
- **Locked out or a page says "No access"?** That page isn't granted to the Accountant role — ask your Admin.

---

## 16. Who to contact

- **Password reset / new page access / settings** → your **Admin**.
- **Approving a write-off / cancel / opening-balance change** (when maker-checker is on) → any **Admin** (not you — 4-eyes).
- **GST filing questions / stock valuation / EMI treatment** → your **CA / tax advisor**.
- **Software not working (errors, blank screens)** → note what you clicked and the message, and report it to your Admin / support.

---

*This manual reflects the Accountant role as configured in the Weighbridge
software. Screens and available tabs may vary slightly if your Admin has
customised role permissions or turned specific feature modules on or off.*
