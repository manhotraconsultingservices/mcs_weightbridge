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
| **3** | **PENDING** — see below | ⏳ |
| **4** | **PENDING (optional)** — Tier-0 "Download Tally XML" route + button; optional combined edge agent | ⏳ |

### Phase 3 — to build next (Settings UI + observability)
- [ ] **Settings → Tally connector-status card** — calls the **already-built** `GET /api/v1/tally/connector/status` (pending/in_progress/done/failed/dead counts + `last_done_at`). Show in `frontend/src/pages/SettingsPage.tsx` `TallyTab`.
- [ ] **Expose `mode` + relay-aware UI**: add `mode` to the frontend `TallyConfig` interface; when `mode==='relay'` **hide Host/Port + Test-Connection** (cloud can't reach the LAN) and show a "Sync mode: Cloud Connector" badge. (Backend already returns `mode` in `TallyConfigOut`; the PUT preserves it when omitted.)
- [ ] **Dead-letter / re-queue UI** — list `dead` jobs; a button to re-arm them (set `status='pending', attempts=0, next_attempt_at=now`).
- [ ] **Retention task** — purge `done` jobs older than ~30d (configurable); keep `dead` for audit. Wire into the existing background-loop scheduler (`main.py` owner-digest/low-stock loop pattern).
- [ ] Optional: a per-tenant scoped `tally_agent_key` (separate from the scale agent's `agent_api_key`) so a leaked key can't drain financial XML — currently both reuse `Tenant.agent_api_key`.

### Live end-to-end smoke still owed (couldn't run from dev box)
The connector's **live HTTP against a seeded cloud tenant** wasn't exercised here
(needs a multi-tenant backend + seeded tenant+agent_key + the connector running).
Do the DPD GATE-D smoke on a real SaaS tenant: `tally_connector.py --setup` →
`--test` (both [OK]) → finalise a GST invoice → watch it drain from
`/tally/pending` into Tally and `tally_synced` flip.

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
