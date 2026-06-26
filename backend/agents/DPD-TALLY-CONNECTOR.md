# Tally Connector — install runbook (SaaS / cloud tenants)

The **Tally Connector** bridges a cloud (SaaS) tenant to the client's **local
Tally Prime**. The cloud builds the GST vouchers and queues them; this connector
(a tiny Windows service on the client's LAN) pulls the queue, pushes each voucher
to the **local** Tally gateway, and reports the result back. The cloud **never
connects into the client's network** — the connector makes only outbound HTTPS.

> Only for **cloud tenants** (`MULTI_TENANT=true`, `tally_config.mode='relay'`,
> which is the default in the cloud). On-prem installs push to Tally directly and
> do **not** need this connector.

Same shape as the scale agent (single self-contained file, `--setup` / `--test`
/ `--install`, NSSM service, a local status page). Run it on the **same PC as
Tally** when possible.

---

## 0. Prerequisites (once per machine)

- [ ] **Tally Prime** open, with its HTTP gateway enabled:
      Gateway of Tally → **F12** → Advanced → **Enable XML/ODBC Server = Yes**, note the **port** (commonly 9000).
- [ ] **Python 3.11+** (`python --version`) + `pip install requests`.
- [ ] **NSSM** on PATH (`nssm version`) — not downloaded by the connector.
- [ ] `tally_connector.py` in **`C:\weighbridge-tally`** (any folder is fine).
- [ ] **Tenant slug** + **Agent key** from the Platform console (same key the
      scale agent uses — Tenants → the client → Agent key).
- [ ] In the app: **Settings → Tally** is **enabled**, the company name + ledger
      names match Tally exactly, and the invoice-prefix filter is set as desired.
      (These live in the cloud and apply to the queued vouchers.)

---

## P — PREPARE

```powershell
cd C:\weighbridge-tally
python tally_connector.py --setup
```
Answer: **Cloud URL** (`https://weighbridgesetu.com`, press Enter) · **Tenant
slug** · **Agent key** · **Local Tally host** (`localhost`) · **Local Tally
port** (e.g. `9000`). Writes `tally_connector.json`.

### GATE P — `--test` passes
```powershell
python tally_connector.py --test
```
Both lines must be **[OK]**:
- `Cloud auth accepted — pending=N dead=M` (the agent key is valid for the tenant)
- `Local Tally <host>:<port> — HTTP 200` (Tally is reachable with its gateway on)

| Symptom | Fix |
|---|---|
| `AGENT KEY REJECTED` | Wrong tenant slug / agent key — re-copy from the Platform console, re-run `--setup`. |
| `Local Tally … ERR` | Tally not open, gateway disabled, or wrong port — F12 → Advanced → enable XML/ODBC server; confirm the port. |
| `Cloud unreachable` | Outbound 443 blocked, or wrong cloud URL. |

---

## D — DEPLOY (Windows service)

Run PowerShell **as Administrator**:
```powershell
python tally_connector.py --install      # registers WeighbridgeTallyConnector (auto-start, restart-on-crash)
nssm start WeighbridgeTallyConnector
```

### GATE D — pass when ALL are true
1. `Get-Service WeighbridgeTallyConnector` → **Running**.
2. **Status page** `http://localhost:9010` shows **CLOUD ONLINE** + **TALLY OK** and a rising *Pushed* count.
3. **End-to-end:** in the cloud app, finalise a GST invoice for this tenant →
   within a few seconds it disappears from **Settings → Tally → pending** and the
   voucher appears in Tally. (The connector drains the queue every ~5 s.)

| Symptom | Fix |
|---|---|
| Pushed stays 0, *pending* > 0 | Check the status page badges. CLOUD OFFLINE → 443/auth; TALLY ERROR → Tally gateway/port. |
| `Tally: FAIL — Ledger 'X' does not exist` | A party/ledger isn't in Tally yet. The connector processes **masters before vouchers**, but if a ledger name was changed in Tally, fix the name (Settings → Tally ledger map, or push the party master) and the job auto-retries with backoff. |
| Jobs go to **dead** | They failed `max_attempts` times — fix the root cause (ledger name, Tally company not open) and re-queue from Settings → Tally (Phase 3 UI), or re-finalise. |

---

## Day-to-day

```powershell
Get-Service WeighbridgeTallyConnector
Restart-Service WeighbridgeTallyConnector
Get-Content C:\weighbridge-tally\logs\tally_connector.log -Tail 30 -Wait
Invoke-RestMethod http://localhost:9010/status | ConvertTo-Json
```
Uninstall: `python tally_connector.py --uninstall`.

**Rules of thumb**
- **One connector per Tally company.** Two connectors on the same queue still
  work (idempotent — each voucher carries a GUID so Tally *alters*, never
  duplicates), but masters-first ordering is only guaranteed with one.
- Keep Tally **open** with the right company loaded; the connector pushes into
  whatever company the job names (`tally_company_name` from Settings).
- The connector and the **scale agent** are independent services — installing one
  doesn't require the other. They use different status ports (9010 vs 9002).
