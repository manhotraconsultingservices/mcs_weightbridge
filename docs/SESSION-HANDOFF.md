# Session Handoff & Pending Tracker

> Living doc — the state of in-flight work + what's pending, so a new session can
> pick up without re-deriving context. **Canonical history is the CLAUDE.md
> changelog**; this file only tracks what's *not done yet*. Update it as items
> close. Last updated: **2026-06-26** · branch `main` · last commit `d54fede`.

---

## 🔭 Active workstream — Tally dual-mode (on-prem + SaaS)

Design/plan: `~/.claude/plans/linear-splashing-map.md`. Architecture summary in
the CLAUDE.md changelog (2026-06-26 Phase 1 + Phase 2 entries).

| Phase | What | Status |
|---|---|---|
| **1** | Transport seam (`integrations/tally/transport.py`) + `tally_sync_jobs` queue + `relay_queue.py` + connector endpoints (`routers/tally_connector.py`) + `tally_config.mode`. On-prem `direct` push unchanged; SaaS auto-`relay`. | ✅ done (`9779986`) — 44 tests green |
| **2** | LAN-side `backend/agents/tally_connector.py` (Windows service: claim → push to local Tally → report) + `POST /connector/ping` + `DPD-TALLY-CONNECTOR.md`. | ✅ done (`d54fede`) — compile + MockTally round-trip verified |
| **3** | Settings connector-status card + relay-aware UI (hide host/port + Test, mode badge) + dead-letter/Retry + 30-day `done`-job retention. | ✅ done (`<pending push>`) — 44 tests + tsc green |
| **4** | Tier-0 "Download Tally XML" — `_build_invoice_xml` extraction + `_merge_voucher_xmls`; `GET /invoices/{id}/xml` + `GET /export-xml`; Settings "Manual export" button. | ✅ done — 44 tests + tsc green |

**Tally dual-mode roadmap is COMPLETE (Phases 1-4).** Remaining are all *optional*:
- [ ] Per-invoice **Download XML** button on `InvoicesPage` (backend `GET /tally/invoices/{id}/xml` already exists — just wire a row action).
- [ ] **Credit/Debit Note auto-sync.** Builders + Tier-0 export + manual sync-by-id now handle CN/DN (2026-06-26). Still to do: include them in `/tally/pending` + fire auto-sync-on-finalise (today sale/purchase only). Also: the CN/DN builders assume **seller-issued vs a sale** — extend if notes against *purchase* invoices are ever added.
- [ ] Scoped `tally_agent_key` (separate from the scale agent's `agent_api_key`) so a leaked key can't drain financial XML — currently both reuse `Tenant.agent_api_key`.
- [ ] Combined single-process "edge agent" (scale + Tally) for single-PC sites.

### Live end-to-end smoke still owed (couldn't run from dev box)
The connector's **live HTTP against a seeded cloud tenant** wasn't exercised here
(needs a multi-tenant backend + seeded tenant+agent_key + the connector running).
Do the DPD GATE-D smoke on a real SaaS tenant: `tally_connector.py --setup` →
`--test` (both [OK]) → finalise a GST invoice → watch it drain from
`/tally/pending` into Tally and `tally_synced` flip.

**Before the smoke, set the client's Tally Import Configuration** (DPD-TALLY-CONNECTOR.md §0a):
**Overwrite voucher when same GUID exists = Yes** + **Record Exceptions and Import**.
With `Overwrite = No`, a re-sent/corrected voucher is skipped as a duplicate and the
connector now reports it as a **failure** (parser hardened 2026-06-26) → it lands in
the dead-letter list instead of silently flipping `tally_synced`.

---

## 🛠 Operational follow-ups (tenant DATA/config — not code)

These came out of the live debugging earlier this session; they need someone with
tenant access to action (not a code change):

- [ ] **manhotra-consulting — clear stuck tokens.** 7 tokens stuck `FIRST_WEIGHT`/`OPEN` (since ~May 26) block their vehicles (409 on re-create). Operator must Complete or Cancel each. Plates: `MP 13 CC 5551`, `HP38G 1671`, `MB 12345`, `HR55AB1234`, `HR55WX3030`, `HR55KL2233`, `UP14YZ4040`.
- [ ] **manhotra-consulting — activate FY 2026-27.** Active FY is still the expired **2025-26**, so new gate passes mint as `GP/25-26/…`. Settings → Financial Years → activate 2026-27.
- [ ] **megna-trading scale — load/unit check.** Live weight reads ~0.3; confirm the app value matches the indicator under a known load. If off by ~1000× the indicator sends **tonnes** → set a unit/calibration in `C:\weighbridge-agent\scale_config.json` (`calibration_offset_kg` is additive only; a ×1000 unit mismatch needs the indicator set to kg or a multiplier).
- [ ] **WS auth deploy** — already live; if any weighbridge tab still shows OFFLINE, **hard-refresh once** (`Ctrl+Shift+R`) to load the token-sending frontend.
- [ ] **maize tenants using QUINTAL** — set ALL products' unit = `QUINTAL`; converting an existing MT product needs stock ×10 and rates ÷10 (`product_stock.current_stock` is in the product unit).

---

## 🧩 Known deferrals (lower priority, documented in CLAUDE.md)
- Custom fields v1 = weighments only (products/parties + kiosk/token-detail display deferred).
- Per-branch **stock** deferred (H3-A) — `product_stock.product_id` is globally UNIQUE; needs a constraint rework before per-branch stock. Reports/dashboards not yet branch-scoped beyond token/invoice lists.
- Production-cycle stock posting (`product_stock.py`) is MT-only — make QUINTAL-aware before enabling production for a quintal tenant.

---

## Where to look
- **What changed & why:** CLAUDE.md → Changelog (newest at the bottom).
- **Tally design:** `~/.claude/plans/linear-splashing-map.md`.
- **Agent install runbooks:** `backend/agents/DPD-GUIDE.md` (scale) · `backend/agents/DPD-TALLY-CONNECTOR.md` (Tally).
- **Debugging principle:** CLAUDE.md top — prove root cause from code/logs/live (per-tenant subdomain login bypasses the www WAF), don't assume.
