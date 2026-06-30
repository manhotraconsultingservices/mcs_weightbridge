# DPD — Camera Agent (Local-First / Cloudflare Tunnel Mode)

Deployment guide for the Weighbridge Camera Agent using **Option 1: Local-First storage**.

Images are saved on the **client PC** and served via Cloudflare Tunnel.
The VPS only stores the URL — no image data ever touches the VPS disk.

---

## Architecture

```
IP Camera (LAN)
      │ HTTP snapshot
      ▼
Camera Agent (client PC)
  ├── saves JPEG to D:\weighbridge\snapshots\{date}\{token_id}\{cam}_{stage}.jpg
  ├── HTTP file server on :9005 (LocalSnapshotServer)
  └── POSTs URL to cloud (/api/v1/cameras/agent-notify)
              │
              ▼
        VPS (weighbridgesetu.com)
          stores URL in token_snapshots.file_path
              │
              ▼
  Owner's browser (any location)
    loads image from https://cam-{slug}.weighbridgesetu.com/{path}
              │
              ▼
    Cloudflare Edge ──tunnel──► client PC :9005 ──► local JPEG file
```

---

## Prerequisites

- Camera agent PC already has `cloudflared` running as a Windows service  
  (installed via `Setup-CloudflareTunnel.ps1` — check with `nssm status cloudflared`)
- Python 3.11+ installed on the camera agent PC
- Camera snapshot URLs known and tested

---

## Step 1 — Add a hostname to the Cloudflare Tunnel

Edit `C:\cloudflared\config.yml` on the **camera agent PC**.

Add one new `ingress` entry **before** the catch-all `service: http_status:404`:

```yaml
tunnel: <your-tunnel-id>
credentials-file: C:\cloudflared\<your-tunnel-id>.json

ingress:
  # Weighbridge app (existing entry — do not change)
  - hostname: acme.weighbridgesetu.com
    service: http://localhost:9001

  # Camera snapshot file server (ADD THIS)
  - hostname: cam-acme.weighbridgesetu.com
    service: http://localhost:9005

  # Catch-all (must be last)
  - service: http_status:404
```

> Replace `acme` with the actual tenant slug (e.g. `megna-trading`).

Then in the **Cloudflare Zero Trust dashboard** (dash.cloudflare.com → Zero Trust → Networks → Tunnels → your tunnel):
- Add a Public Hostname: `cam-acme.weighbridgesetu.com` → `http://localhost:9005`

Restart the tunnel service:
```powershell
nssm restart cloudflared
```

Verify the tunnel is healthy:
```powershell
curl https://cam-acme.weighbridgesetu.com/
# Expected: "snapshot server ok"
```

---

## Step 2 — Install / configure the camera agent

```powershell
cd C:\weighbridge\agents\
python camera_agent.py --setup
```

When prompted:

| Question | Example answer |
|---|---|
| Cloud URL | `https://weighbridgesetu.com` |
| Tenant slug | `acme-minerals` |
| Agent API key | *(from Platform Admin → edit tenant → Agent API Key)* |
| Front camera URL | `http://192.168.0.101/cgi-bin/snapshot.cgi` |
| Top camera URL | `http://192.168.0.103/cgi-bin/snapshot.cgi` |
| Camera username | `admin` |
| Camera password | `camera123` |
| **Snapshot serve URL** | `https://cam-acme.weighbridgesetu.com` |
| Local snapshot save directory | `D:\weighbridge\snapshots` |
| Local file server port | `9005` *(default)* |

---

## Step 3 — Test cameras

```powershell
python camera_agent.py --test
```

Expected output:
```
  front: OK (87432 bytes) → ...\test_snapshots\test_front.jpg
  top:   OK (91208 bytes) → ...\test_snapshots\test_top.jpg
```

---

## Step 4 — Install as Windows service

```powershell
python camera_agent.py --install
```

Check it started:
```powershell
nssm status WeighbridgeCameraAgent
# Expected: SERVICE_RUNNING
```

---

## Step 5 — Verify end-to-end

1. Record a weight in the app (second weight on any token)
2. Open the token detail — the snapshot should appear within ~10 seconds
3. Open the snapshot in a new tab — the URL should be  
   `https://cam-acme.weighbridgesetu.com/20260630/{token_id}/front_second_weight_143022.jpg`
4. Check the logs:
   ```powershell
   Get-Content C:\weighbridge\agents\logs\camera_agent.log -Tail 20
   ```
   Expected log lines:
   ```
   [INFO] Capturing front: http://192.168.0.101/cgi-bin/snapshot.cgi
   [INFO] Saved front: 87432 bytes → D:\weighbridge\snapshots\20260630\{id}\front_second_weight_143022.jpg
   [INFO] Notified cloud: front → https://cam-acme.weighbridgesetu.com/20260630/{id}/front_second_weight_143022.jpg
   ```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| `snapshot server ok` not returned | `nssm status cloudflared` — must be running; check `C:\cloudflared\config.yml` has the cam hostname |
| Snapshots show "pending" forever | Agent not running: `nssm status WeighbridgeCameraAgent`; check `camera_config.json` has `snapshot_serve_url` set |
| Image loads on-site but 404 remotely | Cloudflare dashboard → Tunnels → verify `cam-acme.weighbridgesetu.com` hostname points to `localhost:9005` |
| "Notify failed: HTTP 403" in logs | `agent_key` in `camera_config.json` doesn't match the Platform Admin agent key — re-run `--setup` |
| Camera capture fails | Run `python camera_agent.py --test`; check camera IP/auth; `nssm status WeighbridgeCameraAgent` |

---

## Storage & retention

Images accumulate in `D:\weighbridge\snapshots\`. Estimated size:

- 500 trucks/day × 4 snapshots × 500 KB = ~1 GB/day
- At 30-day retention: ~30 GB

Add a scheduled task to prune old images (run daily at 2 AM):

```powershell
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument '-Command "Get-ChildItem D:\weighbridge\snapshots -Directory | Where-Object { $_.CreationTime -lt (Get-Date).AddDays(-30) } | Remove-Item -Recurse -Force"'
$trigger = New-ScheduledTaskTrigger -Daily -At "02:00"
Register-ScheduledTask -TaskName "PruneWeighbridgeSnapshots" -Action $action -Trigger $trigger -RunLevel Highest -Force
```

---

## Legacy mode (upload to VPS)

To revert to the original binary-upload mode, set `snapshot_serve_url` to `""` in `camera_config.json` and restart the service:

```powershell
# In camera_config.json:
#   "snapshot_serve_url": "",

nssm restart WeighbridgeCameraAgent
```

The agent automatically falls back to `POST /api/v1/cameras/agent-upload` when the field is empty — no other config change needed.
