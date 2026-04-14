# Weighbridge Client Agents

Two independent agents for client-site deployment. Install one or both based on client needs.

## Quick Deploy (Recommended)

Run **PowerShell as Administrator** on the client PC:

```powershell
# One-command interactive setup (prompts for tenant, cameras, COM port)
.\deploy-agents.ps1

# Or fully automated
.\deploy-agents.ps1 -TenantSlug "ziya-ore" -AgentKey "your-key-here" `
    -FrontCameraUrl "http://192.168.0.101/cgi-bin/snapshot.cgi" `
    -TopCameraUrl "http://192.168.0.103/cgi-bin/snapshot.cgi" `
    -CameraUser "admin" -CameraPass "admin123" `
    -ComPort "COM3"

# Camera only (no scale)
.\deploy-agents.ps1 -AgentType camera -TenantSlug "demo" -AgentKey "key"

# Scale only (no camera)
.\deploy-agents.ps1 -AgentType scale -TenantSlug "demo" -AgentKey "key" -ComPort "COM3"
```

The deploy script handles everything:
1. Checks Python is installed
2. Creates `C:\weighbridge-agent\` folder
3. Copies agent files
4. Installs dependencies (requests, pyserial, websockets)
5. Generates config files
6. Tests camera connectivity
7. Registers Windows Scheduled Tasks (auto-start on boot)
8. Opens firewall ports
9. Verifies everything is running

## Day-to-Day Management

```powershell
.\manage-agents.ps1 status              # Show agent status + ports + logs
.\manage-agents.ps1 restart             # Restart all agents
.\manage-agents.ps1 restart camera      # Restart camera agent only
.\manage-agents.ps1 logs                # View last 20 log lines
.\manage-agents.ps1 logs camera         # Camera logs only
.\manage-agents.ps1 update              # Update agent files + restart
.\manage-agents.ps1 test camera         # Test camera snapshot capture
.\manage-agents.ps1 test scale          # Check scale COM port
```

## Uninstall

```powershell
.\deploy-agents.ps1 -Uninstall
```

## Architecture

```
Client PC (Windows)
├── C:\weighbridge-agent\
│   ├── camera_agent.py        # Camera agent
│   ├── camera_config.json     # Camera URLs, tenant, API key
│   ├── scale_agent.py         # Scale agent
│   ├── scale_config.json      # COM port, baud rate, tenant
│   ├── requirements.txt       # Python dependencies
│   └── logs\                  # Agent logs
│
├── Port 9002 ← Scale Agent    # Weight status API
├── Port 9003 ← Camera Agent   # HTTP status + snapshot proxy
└── Port 9004 ← Camera Agent   # WebSocket live video feed
```

## How It Works

### Camera Agent
- **Event capture**: Polls cloud for pending weight events, captures JPEG from IP cameras, uploads to Cloudflare R2
- **Live feed**: Streams live camera frames via WebSocket (`ws://localhost:9004/live/front|top`)
- **Mixed content fix**: HTTPS pages cannot load `http://` images, but CAN connect to `ws://localhost` (Chrome treats localhost as secure context)
- **Auth**: Supports Digest + Basic auth (CP Plus, Dahua, Hikvision compatible)
- **Retry**: 3 attempts per capture, frame caching for live view

### Scale Agent
- Reads weight from RS232/USB serial port continuously
- Pushes readings to cloud API (`POST /api/v1/weight/external-reading`)
- Auto-reconnects on disconnect with exponential backoff

## Ports & Firewall

| Port | Protocol | Agent | Purpose |
|------|----------|-------|---------|
| 9002 | HTTP | Scale | Status API + weight reading |
| 9003 | HTTP | Camera | Status API + snapshot proxy |
| 9004 | WebSocket | Camera | Live video feed for browser |

## Camera URL Formats

| Brand | Snapshot URL |
|-------|-------------|
| CP Plus / Dahua | `http://IP/cgi-bin/snapshot.cgi` |
| Hikvision | `http://IP/Streaming/channels/1/picture` |
| Generic ONVIF | `http://IP/snap.jpg` |

## Scheduled Task vs NSSM

The deploy script uses **Windows Scheduled Tasks** (not NSSM) because:
- No extra software needed (built into Windows)
- Auto-restarts on failure (3 retries, 1-minute interval)
- Runs as SYSTEM (survives user logoff)
- Starts at boot
- Visible in Task Scheduler GUI

## Manual Setup (Alternative)

If you prefer manual setup over the deploy script:

```powershell
# 1. Create folder + copy files
mkdir C:\weighbridge-agent
copy camera_agent.py C:\weighbridge-agent\
copy scale_agent.py C:\weighbridge-agent\
copy requirements.txt C:\weighbridge-agent\

# 2. Install dependencies (system-wide for SYSTEM user)
python -m pip install -r requirements.txt --target "C:\Program Files\Python311\Lib\site-packages"

# 3. Interactive config wizard
cd C:\weighbridge-agent
python camera_agent.py --setup
python scale_agent.py --setup

# 4. Test
python camera_agent.py --test

# 5. Run
python camera_agent.py
python scale_agent.py
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `websockets not installed` | `python -m pip install websockets --target "C:\Program Files\Python311\Lib\site-packages"` |
| Camera shows "Offline" in browser | Check agent logs: `Get-Content C:\weighbridge-agent\logs\camera_agent.log -Tail 20` |
| Live feed not connecting | Ensure port 9004 is open: `Test-NetConnection localhost -Port 9004` |
| Scale not reading | Check COM port: `[System.IO.Ports.SerialPort]::GetPortNames()` |
| Agent not starting at boot | Verify task: `Get-ScheduledTask 'Weighbridge*Agent'` |
| Camera 401 error | Check username/password in camera_config.json |

## Config Files

### camera_config.json
```json
{
  "cloud_url": "https://weighbridgesetu.com",
  "tenant_slug": "your-tenant",
  "agent_key": "your-api-key",
  "poll_interval_sec": 5,
  "status_port": 9003,
  "ws_port": 9004,
  "cameras": {
    "front": {
      "label": "Front View",
      "url": "http://192.168.0.101/cgi-bin/snapshot.cgi",
      "username": "admin",
      "password": "admin123"
    },
    "top": {
      "label": "Top View",
      "url": "http://192.168.0.103/cgi-bin/snapshot.cgi",
      "username": "admin",
      "password": "admin123"
    }
  }
}
```

### scale_config.json
```json
{
  "cloud_url": "https://weighbridgesetu.com",
  "tenant_slug": "your-tenant",
  "agent_key": "your-api-key",
  "port": "COM3",
  "baud_rate": 9600,
  "data_bits": 8,
  "stop_bits": 1,
  "parity": "N",
  "push_interval_ms": 500,
  "status_port": 9002
}
```
