# Weighbridge — Client Agent Installation Guide

**For:** the weighbridge PC on the client's LAN · **Platform:** Windows 10 / 11 (64-bit)
**Install location:** `C:\weighbridge-agent` · **Python required on the client PC:** **No** (frozen EXEs)

---

## 1. What these agents are

The Weighbridge application itself is **cloud SaaS** — the operator just opens
`https://<your-tenant>.weighbridgesetu.com` in Chrome. Nothing about the app is
installed on the client PC.

What *is* installed on the weighbridge PC are small **bridge agents** that connect
the local hardware (which the cloud cannot reach across the internet) to your cloud
tenant:

| Agent | What it does | Needed when |
|---|---|---|
| **Scale Agent** | Reads the weight indicator on a COM/serial port and streams the live weight to the cloud (and directly to the operator's browser on the same PC). | Always (there is a weighbridge). |
| **Camera Agent** | Captures snapshots from the IP cameras at each weighment, and pushes the gate entry/exit live frames. | If cameras are installed. |
| **Tally Connector** | Pulls finalised vouchers from the cloud and pushes them into the **local** Tally on the LAN. | Only if the client uses Tally. |

> These agents were always part of a weighbridge install — they are **not** an
> "offline module." Offline resilience lives in the web app itself (see §9).

---

## 2. What's in this bundle (`C:\weighbridge-agent`)

```
C:\weighbridge-agent\
├── scale_agent.exe          ← weight indicator → cloud
├── camera_agent.exe         ← IP cameras → cloud (weighment snapshots + gate live)
├── tally_connector.exe      ← cloud vouchers → local Tally   (optional)
├── deploy-agents.ps1        ← one-step installer for Scale + Camera
├── INSTALL.md               ← this guide
└── examples\                ← sample config files (reference only — no real keys)
```

The EXEs are self-contained — **no Python, no pip, nothing else to install.**

---

## 3. Before you start — gather these per-client values

Get these from the **Platform admin console** (Platform → the tenant → its agent key)
and from the site:

| Value | Example | Where it comes from |
|---|---|---|
| **Tenant slug** | `manhotra-consulting` | The tenant's subdomain / Platform console |
| **Agent key** | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` (one key per tenant) | Platform console → tenant → agent key |
| **Cloud URL** | `https://weighbridgesetu.com` | Always this (the agent auto-routes to the tenant subdomain) |
| **Scale COM port + baud** | `COM3`, `9600` | The weight-indicator cable / its manual |
| **Camera snapshot URLs** | `http://192.168.0.101/cgi-bin/snapshot.cgi` | The IP cameras on the LAN |
| **Camera user / password** | `admin` / `admin123` | The camera login |
| **Tally host / port** | `localhost` / `9000` | The PC running TallyPrime (if used) |

> The **same agent key** is used by all three agents for one client.

---

## 4. Install Scale + Camera (one step)

1. Copy this whole folder to **`C:\weighbridge-agent`** on the weighbridge PC.
2. Open **PowerShell as Administrator** (Start → type `PowerShell` → right-click →
   *Run as administrator*).
3. If PowerShell blocks the script, allow it for this user once:
   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   ```
4. Run the installer:
   ```powershell
   cd C:\weighbridge-agent
   .\deploy-agents.ps1
   ```
5. It will prompt for the values from §3 (tenant slug, agent key, camera URLs, COM
   port…), write the config files, register the agents as **auto-start Windows
   Scheduled Tasks**, open the firewall ports, and test the cameras.

That's it — the agents start immediately and again on every reboot.

**Non-interactive** (all values on the command line — handy for repeat installs):
```powershell
.\deploy-agents.ps1 -TenantSlug "manhotra-consulting" -AgentKey "PASTE-KEY" `
    -FrontCameraUrl "http://192.168.0.101/cgi-bin/snapshot.cgi" `
    -TopCameraUrl   "http://192.168.0.103/cgi-bin/snapshot.cgi" `
    -EntryCameraUrl "http://192.168.0.223/cgi-bin/snapshot.cgi" `
    -ExitCameraUrl  "http://192.168.0.224/cgi-bin/snapshot.cgi" `
    -CameraUser "admin" -CameraPass "admin123" `
    -ComPort "COM3" -BaudRate 9600
```

**Scale only** (no cameras): add `-AgentType scale`.
**Camera only:** add `-AgentType camera`.

---

## 5. Install the Tally Connector (optional — only if the client uses Tally)

The Tally connector installs itself. It needs **NSSM** on the PC
(free, from <https://nssm.cc> — put `nssm.exe` on the PATH or in `C:\scripts\`).

```powershell
cd C:\weighbridge-agent
.\tally_connector.exe --setup      # asks for cloud URL, tenant, agent key, Tally host/port
.\tally_connector.exe --test       # verifies cloud auth + that local Tally is reachable
.\tally_connector.exe --install    # registers the auto-start service WeighbridgeTallyConnector
```

> In TallyPrime, enable the HTTP gateway (Gateway of Tally → F1 → Settings →
> Connectivity), and in **Import Configuration** set **"Overwrite same-GUID
> voucher = Yes"** so re-syncs update instead of silently skipping.

To also stage the Tally EXE during the Scale/Camera install (so it's in the folder
ready for `--setup`), add `-IncludeTally` to the `deploy-agents.ps1` command.

---

## 6. ⚠ Smart App Control / SmartScreen (unsigned EXEs)

These EXEs are **not code-signed**. On a PC with **Smart App Control ON**, Windows
may block them until they build reputation, or refuse to run them. If an agent will
not start:

- Right-click the `.exe` → **Properties** → tick **Unblock** → Apply, then restart
  the task; **or**
- Turn Smart App Control **OFF** (Settings → Privacy & security → Windows Security →
  App & browser control → Smart App Control). *Note: once OFF it stays off until a
  Windows reinstall.*

A code-signing certificate removes this entirely — recommended before a wide rollout.

---

## 7. Verify

| Agent | Local check (on the weighbridge PC) |
|---|---|
| Scale | Browse to `http://localhost:9002` → shows connected + live weight. |
| Camera | Browse to `http://localhost:9003` → shows the agent running. |
| Tally | Browse to `http://localhost:9010` → shows CLOUD ONLINE / TALLY OK. |

Then, in the **web app** (`https://<tenant>.weighbridgesetu.com`):
- The **live weight** moves in the weighment screen.
- Cameras capture a snapshot when a weighment completes (Operations → Gate Cameras
  → Live for the gate feed).

---

## 8. Update / uninstall

**Update to a new build:** replace the three `.exe` files in `C:\weighbridge-agent`
with the new ones and re-run `.\deploy-agents.ps1` (it re-registers the tasks). For
Tally: `.\tally_connector.exe --uninstall` then `--install` with the new EXE.

**Uninstall everything** (tasks, NSSM services, firewall rules, running processes):
```powershell
cd C:\weighbridge-agent
.\deploy-agents.ps1 -Uninstall
```
(Config files and `logs\` are left in place; delete the folder to remove them too.)

---

## 9. A note on offline / unstable internet

If the internet drops, the weighbridge keeps working — **no extra install is
needed for this**:

- The **web app is a PWA** (use Chrome → *Install app* for a standing window). The
  page still loads, dropdowns still work from cache.
- The **Scale Agent** runs on this same PC, so the operator's browser reads the live
  weight **directly** from it (`127.0.0.1:9002`) even while the cloud is unreachable.
- Weighments captured during an outage are **queued and auto-sync** when the link
  returns; the server assigns gap-free numbers at sync, and **nothing is dropped**.

Only new-truck capture is queued in the browser; reports, payments and invoice
finalisation resume when back online. (A richer fully-offline tier — a local
database "edge agent" — exists but is not part of this bundle.)

---

## 10. Reference — services, ports, config, logs

| Agent | Service / Task name | Local port(s) | Config file | Logs |
|---|---|---|---|---|
| Scale | `WeighbridgeScaleAgent` (Scheduled Task) | 9002 | `C:\weighbridge-agent\scale_config.json` | `C:\weighbridge-agent\logs\scale_agent.log` |
| Camera | `WeighbridgeCameraAgent` (Scheduled Task) | 9003 (status), 9004 (live WS) | `C:\weighbridge-agent\camera_config.json` | `C:\weighbridge-agent\logs\camera_agent.log` |
| Tally | `WeighbridgeTallyConnector` (NSSM service) | 9010 | `C:\weighbridge-agent\tally_connector.json` | `C:\weighbridge-agent\logs\tally_connector.log` |

Handy commands:
```powershell
Get-ScheduledTask 'Weighbridge*Agent'                 # scale + camera status
Get-Service  WeighbridgeTallyConnector                # tally status
Get-Content C:\weighbridge-agent\logs\scale_agent.log -Tail 20
Stop-ScheduledTask WeighbridgeScaleAgent; Start-ScheduledTask WeighbridgeScaleAgent
```

---

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| **Live weight not moving** | `http://localhost:9002` — is the scale connected? Check the COM port/baud (Device Manager → Ports). Re-run the installer if the port changed. |
| **"AGENT KEY REJECTED (403)"** in logs | Wrong `tenant_slug` or `agent_key`. Re-run the installer (or `tally_connector.exe --setup`) with the correct values from the Platform console. |
| **Camera "offline"** | Open the snapshot URL in a browser to confirm it works + the user/password. CP Plus/Dahua: `http://IP/cgi-bin/snapshot.cgi`; Hikvision: `http://IP/Streaming/channels/1/picture`. |
| **Agent won't start at all** | Almost always Smart App Control — see §6. |
| **Tally: "NSSM not found"** | Install NSSM from <https://nssm.cc> and add `nssm.exe` to PATH, then re-run `--install`. |
| **Tally: imported 0 / EXCEPTIONS** | In TallyPrime, set Import Configuration → *Overwrite same-GUID voucher = Yes*; for GST/inventory rejections use the app's **Accounting-vouchers (no inventory)** mode in Settings → Tally. |

---

*Bundle: Scale + Camera + Tally agents (frozen EXEs). Installer: `deploy-agents.ps1`.*
