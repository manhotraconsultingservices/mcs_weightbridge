# Weighbridge — Offline (No‑Internet) Operation

**Audience:** vendor engineers + technically‑minded owners.
**Scope:** how the weighbridge keeps working when the internet link drops, what is
guaranteed, what is not, and the exact mechanisms behind it.

---

## 0. The short answer — "is there a separate installation?"

**No.** The offline capability that is **live today** needs nothing installed beyond
what a weighbridge already has:

| Piece | Already there? | Role in offline |
|---|---|---|
| The **web app** (SaaS, opened in Chrome) | yes | Is a PWA — shell + logic keep working offline |
| The **Scale Agent** (`scale_agent.exe`) | yes — installed for the weight indicator | Serves live weight to the browser **locally** during an outage |
| **PWA "Install app"** in Chrome | optional, one click | Standing window + Windows‑protected storage |

There is **no "offline module" to install and no separate offline server.** Offline
behaviour is built into the web app and reuses the scale agent that is already on
the weighbridge PC.

> A richer, fully‑offline tier (a local **edge agent** with its own database) exists
> in the codebase but is **not deployed and not part of the shipped bundle** — it
> *would* need a separate install. See [§8](#8-the-optional-edge-agent-tier-not-shipped).

---

## 1. What keeps working during an outage — and what doesn't

Assume the operator's browser is on the **same PC** as the scale agent (the standard
weighbridge setup).

| Capability | Offline? | How |
|---|---|---|
| App opens / pages load | ✅ | Service worker serves the cached app shell |
| Party / product / vehicle dropdowns | ✅ | Last‑known‑good masters cached in `localStorage` |
| **Live weight on screen** | ✅ | Browser reads the scale agent directly at `http://127.0.0.1:9002` |
| **Capture a truck (create token)** | ✅ | Saved to an offline queue, auto‑synced on reconnect |
| Volume (single‑shot) tokens | ✅ | The whole create+complete payload is queued and replayed |
| Stays logged in through the drop | ✅ | Token kept in `sessionStorage`; refresh is network‑tolerant |
| Nothing silently lost | ✅ | "Never‑drop" queue invariant (see [§5.3](#53-offline-token-queue-offlinequeuets)) |
| Two‑stage weigh‑in **and** weigh‑out while offline | ⚠️ partial | The *create* is queued; the per‑stage weight POSTs need the server. See [§7](#7-limitations-read-this) |
| Invoicing / finalise / numbering | ❌ online | Server assigns the GST number at sync |
| Payments, reports, GST, Tally | ❌ online | Cloud‑only features |

**Design principle:** numbers (token no., invoice no.) are always assigned by the
**server** — never minted in the browser — so there is **zero numbering/compliance
risk** from working offline. The queued capture replays and the server numbers it
exactly as if it had been created online.

---

## 2. Components involved

```
        Weighbridge PC (one machine)
 ┌───────────────────────────────────────────────┐        INTERNET
 │  Chrome (installed PWA)                        │           │
 │   ├─ Service Worker  sw.js  (app‑shell cache)  │           │
 │   ├─ localStorage:                             │           │
 │   │    wb.offlineQueue.v1   (queued tokens)    │        ┌──▼─────────────────────┐
 │   │    wb.masters.*         (cached dropdowns) │  HTTPS │  Cloud SaaS             │
 │   │    wb.agentPort         (last good port)   │◄──────►│  <tenant>.weighbridge   │
 │   ├─ sessionStorage: token  (JWT + refresh)    │        │  setu.com               │
 │   └─ useWeight hook                            │        │  = SOURCE OF TRUTH,     │
 │        ├─ WS  wss://…/ws/weight  (cloud)       │        │    numbering, billing   │
 │        └─ GET http://127.0.0.1:9002/status ◄───┼──┐     └─────────────────────────┘
 │                                                │  │
 │  Scale Agent  (scale_agent.exe)  ──────────────┼──┘  (loopback — no internet needed)
 │        reads COM port, serves /status locally  │
 └───────────────────────────────────────────────┘
```

- **Cloud** stays the single source of truth. The browser never becomes a second book
  of record.
- **Scale agent** is a local process that always serves the current weight on
  `127.0.0.1:9002` regardless of internet — that is why live weight survives an outage.

---

## 3. Timeline of a single outage

1. **Link drops.** The cloud WebSocket for weight goes silent; API calls start failing.
2. **Indicator flips.** The header pill probes `GET /api/v1/health`; on failure it shows
   **"Offline"** (and a count if items are queued). It uses a real request, **not**
   `navigator.onLine` (which lies — it reports "online" on a dead uplink).
3. **Live weight continues.** `useWeight` notices the cloud feed is stale and begins
   polling the local scale agent (`127.0.0.1:9002/status`); the on‑screen weight keeps
   moving, now tagged `source: 'local'`.
4. **Operator captures the truck.** Dropdowns are filled from the masters cache. On
   submit, the token POST fails (no internet) → it is **queued** in `localStorage` and
   the operator sees *"Saved offline — <vehicle> will sync when the connection returns."*
5. **Session holds.** The 8‑hour JWT stays valid; the refresh loop's offline attempts
   fail as *network errors* (not 401), so the still‑valid token is kept.
6. **Link returns.** The `online` event (and a 60 s safety timer) fire `flushQueue()`.
   Queued tokens replay **in order** to the cloud; the server validates, numbers, and
   books each one. Confirmed `2xx` is the only thing that removes an item.
7. **Anything the server refuses** (e.g. a duplicate) is **parked, not deleted** — it
   shows as "N need attention" for a human to resolve.

---

## 4. Storage map (what lives where, and why)

| Store | Key | Contents | Survives browser restart? |
|---|---|---|---|
| `localStorage` | `wb.offlineQueue.v1` | Queued token‑create requests + per‑item state | ✅ |
| `localStorage` | `wb.masters.parties` / `.products` / `.vehicles` | Last successful dropdown fetch | ✅ |
| `localStorage` | `wb.agentPort` | Last scale‑agent port that answered (9002–9006) | ✅ |
| `sessionStorage` | `token` | JWT for API auth | ❌ (cleared on full browser close) |
| Cache Storage | (service worker) | App shell (HTML/JS/CSS) | ✅ |

> **Consequence:** the queued weighments survive a browser restart, but the **JWT does
> not** (it is in `sessionStorage` by design, for security). After a full restart the
> queue waits — it does **not** discard — and resumes syncing once the operator logs
> back in. See the `needs_auth` state in [§5.3](#53-offline-token-queue-offlinequeuets).

---

## 5. Technical deep‑dives

### 5.1 Live‑weight failover — `hooks/useWeight.ts`

Two sources, cloud always wins:

- **Cloud (preferred):** a WebSocket to `…/ws/weight`. Each frame sets
  `source: 'cloud'`. A **silence watchdog** (`SILENCE_LIMIT_MS = 8000`) force‑reconnects
  if no frame arrives for 8 s — this catches "half‑dead" sockets that Cloudflare/nginx
  drop without a close event, so recovery is ~1–2 s instead of ~30 s. Reconnect backoff
  is fast (`BASE_DELAY_MS = 1000`, capped at 4 s); only a "no scale manager" close
  (code `1013`) backs off long (15 s).
- **Local fallback:** a poll loop that runs **only when the cloud feed is not fresh**.
  It `fetch`es `http://127.0.0.1:<port>/status` over `AGENT_PORTS = [9002,9003,9004,9005,9006]`,
  caches the port that answers (`wb.agentPort`), and tags the reading `source: 'local'`.
- **Neither live →** `source: 'none'` renders a **blank**, never a frozen last value —
  a stale number next to a truck on the bridge is worse than an obvious "no reading".

`127.0.0.1` is used (not `localhost`) because the agent binds IPv4 only. The scale
agent must send a permissive **CORS allowlist** for the tenant origin so an HTTPS page
may read `http://127.0.0.1` — this is already implemented in the agent.

### 5.2 Masters cache — `lib/mastersCache.ts`

A plain read‑through cache. On every successful dropdown fetch the page calls
`cacheMasters('parties'|'products'|'vehicles', data)`; when a fetch fails it falls back
to `readCachedMasters(...)`. No writes, no sync — it can never corrupt anything and is
never more stale than the operator's last online moment.

### 5.3 Offline token queue — `lib/offlineQueue.ts`

The heart of offline capture. Storage key `wb.offlineQueue.v1`.

**Never‑drop safety invariant (do not weaken):** *a queued item is NEVER deleted because
the server rejected it.* Every item is a truck that physically crossed the bridge. The
**only** automatic removal is a confirmed `2xx`; the only manual removal is a deliberate
`discardItem()`.

Per‑item state machine on replay:

| Replay outcome | New state | Meaning |
|---|---|---|
| `2xx` | (removed) | Synced — the only auto‑removal |
| `401` / `403` | `needs_auth` | Session expired → **pause**, resume after re‑login |
| `409` / `422` / other 4xx (≠408/429) | `needs_review` | Server refused → **park + HALT the drain** for a human |
| network / timeout / `408` / `429` / `5xx` | `pending` (retry) | Transient → retry later (`attempts`/`last_error` recorded) |

**Ordering is strict.** The backend rejects a second OPEN token for the same vehicle
(`409`), so replaying out of order would fail spuriously — therefore any unresolved
outcome **breaks** the drain instead of skipping ahead.

**Replay triggers** (`initOfflineQueue()` at startup): the browser `online` event, a
60 s safety interval (covers flaky links + picks up `needs_auth` items after login),
and once at boot. Flushing is skipped entirely when there is no session (avoids a
boot‑time 401 storm) and when `navigator.onLine` is false.

**Timeout:** replay uses a 10 s timeout (`REPLAY_TIMEOUT_MS`) so a black‑holed link
fails fast instead of hanging ~2 minutes.

**Legacy rescue:** the old queue stored bare endpoints like `/tokens` (which 404 on
replay because the router is `/api/v1/tokens`). `normalizeEndpoint()` rewrites those on
read, so tokens stranded by the historical bug are **recovered**, not lost.

### 5.4 Reachability indicator — `components/OfflineIndicator.tsx`

Probes `GET /api/v1/health` (not `navigator.onLine`). States shown:
- **"Offline"** (+ `· N queued`) when the health probe fails.
- **"N pending sync"** when online with a non‑empty queue.
- **"N need attention"** (amber) when items are parked as `needs_review` — so a refused
  weighment can never go unnoticed.

### 5.5 Auth across the outage — `hooks/useAuth.ts` + `POST /api/v1/auth/refresh`

The JWT (8 h) lives in `sessionStorage`. A single app‑wide refresh loop re‑mints the
token every ~20 min and on window focus via `POST /api/v1/auth/refresh` (which preserves
the tenant claim). Crucially, an **offline** refresh fails as a *network error*, **not**
a `401`, so the still‑valid token is kept and topped up on the next online tick — an
operator on a link that flaps for 30–40 minutes is never logged out mid‑shift.

### 5.6 Numbering & idempotency (why sync is safe)

- **Numbers come from the server.** A replayed token is created by the normal
  `create_token` path and gets its `token_no` at COMPLETED (volume tokens auto‑complete);
  invoices are numbered by the server's row‑locked sequence. Gap‑free, no browser‑minted
  numbers.
- **Duplicate protection.** Strict in‑order replay + the server's "one active token per
  vehicle" `409` guard. A genuine duplicate is **parked** (`needs_review`), never double‑booked.
- **Idempotency ledger (infrastructure).** The server carries a `sync_operations` ledger
  keyed by `client_op_id`, and a reserved **9000–9999 token band** for offline terminals
  (the server itself draws 1000–8999). These exist to make *replays* provably safe and
  are the foundation for the edge‑agent tier ([§8](#8-the-optional-edge-agent-tier-not-shipped)).

### 5.7 PWA / service worker — `public/sw.js`, registered in `main.tsx`

- Registered **production‑only** (`import.meta.env.PROD`).
- **Navigation:** network‑first, falling back to the cached app shell → pages open offline.
- **API:** `/api/*` is **never** cached — stale business data must never be served; API
  offline‑ness is handled by the queue + caches above, not by caching responses.
- Installing the app ("Install app" in Chrome) gives a standing window and Windows‑protected
  persistent storage for the caches/queue.

---

## 6. Operator SOP during an outage

1. Keep working — the page and dropdowns still respond; the weight display still moves.
2. Weigh and **capture the truck** as normal. On save you'll see *"Saved offline…"*.
3. Watch the header pill: **Offline → N pending sync → 0** as the link returns.
4. If it ever shows **"N need attention"**, open the queue and resolve those items
   (usually a duplicate that was already recorded) — they are held, not lost.
5. Use the **same browser on the same PC**, and **do not clear browsing data** until the
   pending count is back to 0.

---

## 7. Limitations (read this)

- **Only token *capture* (create) is queued offline.** For a **two‑stage** weighbridge
  token, the create is queued, but the per‑stage weigh‑in/weigh‑out POSTs
  (`/tokens/{id}/first-weight`, `/second-weight`) target a server token that doesn't
  exist yet offline. **Single‑call volume tokens** carry everything in one payload and
  replay as complete. Full offline two‑stage weighment is the edge‑agent tier ([§8](#8-the-optional-edge-agent-tier-not-shipped)).
- **Downstream is online‑only:** invoicing/finalise, payments, reports, GST, Tally.
- **Per‑browser / per‑device.** The queue and caches live in that browser's storage.
  Different browser or a data wipe = those items aren't visible there.
- **Live weight offline needs the scale agent on the same PC** (loopback) and its CORS
  allowlist (already shipped). A browser on a *different* PC than the agent won't get the
  local fallback.
- **Auth needs a login at least once online**, and survives restarts only for the life of
  `sessionStorage` (a full browser close clears the JWT; the queue still waits safely).

---

## 8. The optional "edge agent" tier (NOT shipped)

For clients who need the driver to leave with a **numbered slip produced entirely
offline** and full **two‑stage weighment + invoice approval** during long outages, the
codebase contains a design + working pieces for a local **edge agent**: a small
FastAPI + **SQLite** service on the weighbridge PC that mirrors master data, serves the
offline subset of routes, and replays *intents* to the cloud on reconnect (the cloud
still assigns the legal invoice number at sync).

- It **would be a separate installation** on the weighbridge PC, plus a browser base‑URL
  switch to the local edge API.
- It is **built and tested but deliberately not wired or deployed** — the browser‑queue
  path above covers the core "don't lose a truck / keep the bridge usable" need without
  it.
- Turning it on is a future upgrade decision, not part of the current agent bundle.

Design reference: `~/.claude/plans/linear-splashing-map.md` (internal).

---

## 9. Verifying / troubleshooting offline

| Check | How |
|---|---|
| Live weight offline | Pull the internet; the weight display should keep moving with a "local" indication. If it freezes: open `http://localhost:9002` — is the scale agent up? |
| Capture offline | With the internet down, create a token → expect *"Saved offline…"* and the header **Offline · 1 queued**. |
| Auto‑sync | Restore the internet → the pill should go **pending → 0** within ~60 s (or immediately on the `online` event). |
| Parked items | Header shows **"N need attention"** → open the queue; resolve/`discard` confirmed duplicates. |
| Reachability lies? | The app uses `GET /api/v1/health`, so a dead uplink that still shows a Wi‑Fi icon is detected correctly. |

---

## 10. File reference (for engineers)

| Concern | File |
|---|---|
| Offline token queue + never‑drop invariant | `frontend/src/lib/offlineQueue.ts` |
| Masters read cache | `frontend/src/lib/mastersCache.ts` |
| Live‑weight cloud/local failover | `frontend/src/hooks/useWeight.ts` |
| Offline / pending / needs‑attention pill | `frontend/src/components/OfflineIndicator.tsx` |
| Auth refresh across outage | `frontend/src/hooks/useAuth.ts`, `POST /api/v1/auth/refresh` |
| Queue init + SW register | `frontend/src/main.tsx` |
| Service worker (app‑shell cache) | `frontend/public/sw.js`, `frontend/public/manifest.webmanifest` |
| Local live weight source | `backend/agents/scale_agent.py` (`/status` on 9002) |
| Server idempotency ledger + offline routes | `backend/app/routers/offline.py`, `sync_operations`, `client_op_id` |

---

*This document describes the offline behaviour shipped in the live web app + the existing
scale agent. No separate offline installation is required for it.*
