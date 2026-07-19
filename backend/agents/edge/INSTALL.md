# Weighbridge Offline Edge Agent — install runbook

The edge agent is a small FastAPI app that runs on the **weighbridge PC** and lets
the operator keep creating gate passes + tokens (and approving invoices) while the
internet is down. It keeps a local SQLite mirror of the masters, buffers every
weighment as an ordered **intent**, and replays those intents to the cloud when the
link returns. The cloud stays the single source of truth — the legal invoice number
is always assigned by the server at sync.

> **Runs from `.py` source on purpose.** Windows **Smart App Control** blocks unsigned
> PyInstaller EXEs by per-file reputation (re-rolled on every rebuild), so a frozen
> `.exe` is unreliable for a hand-installed agent. Running `python -m agents.edge.app`
> from a venv sidesteps that entirely. One binary/codebase for every client — the JSON
> config holds the client-specific values.

---

## 0. Prerequisites

- Python 3.11 + the repo checked out on the weighbridge PC (the agent imports the
  backend package, so it ships with `backend/`).
- A venv with the backend deps: `pip install -r backend/requirements.txt`
  (the edge agent adds only `aiosqlite` + `httpx`, both already present).
- **NSSM** on PATH (https://nssm.cc) — for the Windows service.
- The tenant's **agent key** (same key as `camera_config.json` / the scale agent — a
  tenant secret; treat it like a password).

## 1. Config — `edge_agent.json`

Placed next to where the service runs (the backend dir), or point `EDGE_CONFIG` at it.

```json
{
  "cloud_url":    "https://weighbridgesetu.com",
  "tenant_slug":  "<tenant-slug>",
  "agent_key":    "<tenant agent key>",
  "terminal_tag": "B1",
  "api_port":     9007,
  "db_path":      "C:/weighbridge-agent/edge.db",
  "sync_interval_sec": 30,
  "retain_days":  7,
  "telegram_bot_token": "",
  "telegram_chat_id":   ""
}
```

- `cloud_url` may be the apex — the agent auto-routes to `https://<tenant_slug>.weighbridgesetu.com`
  (the apex 301-redirect drops POST bodies).
- `terminal_tag` **must be unique per terminal** (`B1`, `B2`, …) — it namespaces the
  offline gate-pass series `GP/<date>/<tag>-NNN`.
- `telegram_*` are optional — if set, a **skipped** 04:00 prune (unsynced work still
  pending) fires an alert.

## 2. Test before installing

```bat
python -m agents.edge.app --test
```

Prints the SQLite path, opens/creates the schema, and does one **masters pull** to prove
cloud reachability + a valid agent key. Expect `cloud masters : OK — N master rows`.

## 3. Install the service + scheduled tasks

```bat
python -m agents.edge.app --install
nssm start WeighbridgeEdgeAgent
```

`--install` registers:
- **NSSM service `WeighbridgeEdgeAgent`** — auto-start, log rotation, runs
  `python -m agents.edge.app` from the backend dir.
- **`WeighbridgeEdgeRestart`** — daily **04:00** `nssm restart WeighbridgeEdgeAgent`
  (clears leaks / wedged sockets → a known-good daily baseline).
- **`WeighbridgeEdgePrune`** — daily **04:05** `python -m agents.edge.prune`.

## 4. The 04:05 conditional prune — what it does

Runs **after** the restart so the spool is settled. It is a **conditional prune, never a
wipe**:

- If **any** intent is still unsynced (`pending` / `needs_review` / `needs_auth`), it
  **skips entirely**, logs loudly, and (if Telegram is configured) alerts — a truck that
  physically crossed the bridge is never deleted to save disk.
- Otherwise it deletes synced intents older than `retain_days` **measured from sync time**
  (an intent created at 23:00 and synced at 09:00 survives), plus local tokens/invoices/
  gate-passes older than `retain_days`, then `VACUUM`s. The permanent audit trail lives
  server-side in `sync_operations`, so short local retention is free.

Run it by hand anytime: `python -m agents.edge.prune` → prints `PRUNED …` or `SKIPPED …`.

## 5. Point the browser at the edge when offline

The operator's browser is the **installed Chrome PWA** on this same PC. The frontend
already switches its API base URL to `http://127.0.0.1:9007` when the cloud is
unreachable (see the reachability probe / `LOCAL BRIDGE` banner) and switches back on
reconnect. Nothing to configure per-terminal beyond the PWA install.

## 6. Verify

```bat
curl http://127.0.0.1:9007/api/v1/health
curl http://127.0.0.1:9007/api/v1/sync/status
```

- `health` → `{"status":"running","sync_enabled":true,…}`
- `sync/status` → `{"spool":{…},"pending":N,"needs_review":…}` — the operator's
  "N pending to sync" figure.

## 7. Upgrade / uninstall

- **Upgrade:** `git pull`, `pip install -r backend/requirements.txt` (if changed),
  `nssm restart WeighbridgeEdgeAgent`. The SQLite file + spool are preserved
  (`init_db` is idempotent and migrates in place — never wiped).
- **Uninstall:** `python -m agents.edge.app --uninstall` (removes the service + both
  tasks). The `edge.db` file is left on disk — delete it manually only after confirming
  `sync/status` shows `pending: 0`.

## 8. Operational notes

- **One writer per bridge.** The offline number bands (`token_no` 9000–9999,
  `GP/<date>/<tag>-NNN`) assume a single terminal per weighbridge. Multiple terminals →
  give each its own `terminal_tag`.
- **Numbers on the driver's slip are the final numbers.** The server keeps the 9xxx
  token number and the gate-pass number verbatim at sync (#172).
- **Never `del edge.db`** while `sync/status` shows pending > 0 — that destroys real
  weighments. The prune's skip-guard exists precisely to stop that.
