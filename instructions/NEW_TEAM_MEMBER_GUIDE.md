# New Team Member Guide — Weighbridge ERP

> Everything you need to start developing, building, and deploying the Weighbridge application.
> Read this document top-to-bottom on your first day.

**Repository:** https://github.com/manhotraconsultingservices/mcs_weightbridge
**Last updated:** 10-Apr-2026

---

## Table of Contents

1. [What Is This Project?](#1-what-is-this-project)
2. [Tech Stack](#2-tech-stack)
3. [Setting Up Your Development Machine](#3-setting-up-your-development-machine)
4. [Running the Application Locally](#4-running-the-application-locally)
5. [Project Structure](#5-project-structure)
6. [Understanding the Backend](#6-understanding-the-backend)
7. [Understanding the Frontend](#7-understanding-the-frontend)
8. [Database](#8-database)
9. [Key Code Patterns](#9-key-code-patterns)
10. [Testing](#10-testing)
11. [Building for Production](#11-building-for-production)
12. [Deploying to a Client](#12-deploying-to-a-client)
13. [Git Workflow](#13-git-workflow)
14. [Key Documents to Read Next](#14-key-documents-to-read-next)
15. [FAQ & Troubleshooting](#15-faq--troubleshooting)

---

## 1. What Is This Project?

Weighbridge ERP is a **stone crusher weighbridge management system** built for Indian SMEs. It handles:

- **Two-stage weighment** — Gross weight (loaded truck) and Tare weight (empty truck)
- **GST-compliant invoicing** — Sales, purchase, quotations with CGST/SGST/IGST
- **Party/Vehicle master** — Customer, supplier, vehicle, driver management
- **Payments & Ledger** — Receipt/voucher recording, party-wise running balance
- **Reports** — GSTR-1, GSTR-3B, P&L, stock summary, sales/purchase register
- **Tally Prime integration** — Push vouchers to Tally accounting software
- **Store inventory** — Fuel, parts, tools tracking with PO workflow
- **Notifications** — Telegram, email, SMS alerts on events
- **Hardware integration** — Weight scale (serial port), IP cameras, USB security key

**Who uses it?** Stone crusher plant operators, accountants, and owners in India.

---

## 2. Tech Stack

### Backend

| Technology | Version | Purpose |
|-----------|---------|---------|
| Python | 3.11 | Language |
| FastAPI | 0.115+ | REST API framework |
| Uvicorn | 0.34+ | ASGI server |
| PostgreSQL | 16 | Database (runs in Docker) |
| SQLAlchemy | 2.0+ | ORM (async mode with asyncpg) |
| Alembic | 1.13+ | Database migrations |
| python-jose | 3.3 | JWT token generation |
| Pydantic | 2.x | Request/response validation |
| xhtml2pdf | — | PDF generation (invoices) |
| Jinja2 | — | HTML templates for PDFs and notifications |

### Frontend

| Technology | Version | Purpose |
|-----------|---------|---------|
| React | 19 | UI framework |
| TypeScript | 5.9 | Type-safe JavaScript |
| Vite | 8.0 | Build tool (fast dev server + production bundler) |
| Tailwind CSS | 4.x | Utility-first CSS |
| shadcn/ui | — | Pre-built UI components (buttons, dialogs, tables) |
| Axios | 1.13 | HTTP client for API calls |
| Recharts | 2.15 | Charts (dashboard, analytics) |
| Lucide React | — | Icons |
| Sonner | — | Toast notifications |
| React Router | 7.x | Client-side routing |

### Infrastructure

| Technology | Purpose |
|-----------|---------|
| Docker Compose | Runs PostgreSQL locally |
| Nuitka | Compiles Python to native `.exe` for production |
| NSSM | Registers `.exe` as Windows service |
| Cloudflare Tunnel | Secure remote access (no port forwarding) |
| Cloudflare R2 | Encrypted cloud backup storage |

---

## 3. Setting Up Your Development Machine

### What You Need

- **Windows 10/11** (64-bit) — the app targets Windows for production
- **8 GB+ RAM**
- **10 GB free disk space**

### Step-by-Step Setup

Open **PowerShell as Administrator** and run each step:

**1. Install Git**
```powershell
winget install -e --id Git.Git
```
Close and reopen PowerShell after install.

**2. Clone the repository**
```powershell
cd C:\Projects
git clone https://github.com/manhotraconsultingservices/mcs_weightbridge.git
cd mcs_weightbridge
```

**3. Install Python 3.11**
- Download from https://www.python.org/downloads/release/python-3119/
- **CHECK** the box "Add Python 3.11 to PATH" during install
- Verify: `python --version` should show `Python 3.11.x`

**4. Install Node.js 20 LTS**
- Download from https://nodejs.org/
- Verify: `node --version` should show `v20.x.x`

**5. Install Docker Desktop**
- Download from https://www.docker.com/products/docker-desktop/
- After install, open Docker Desktop and wait for it to show "Running"
- Verify: `docker --version`

**6. Set up the backend**
```powershell
cd C:\Projects\mcs_weightbridge\backend

# Create virtual environment
python -m venv venv

# Activate it (you'll see (venv) in your prompt)
.\venv\Scripts\Activate.ps1

# Install Python packages
pip install -r requirements.txt

# Create your local .env file from the template
Copy-Item .env.example .env
```

Now edit `backend\.env` and set real values:
```
DATABASE_URL=postgresql+asyncpg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge
DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge
SECRET_KEY=dev-secret-key-change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
PRIVATE_DATA_KEY=0000000000000000000000000000000000000000000000000000000000000000
```

**7. Set up the frontend**
```powershell
cd C:\Projects\mcs_weightbridge\frontend
npm install
```

**8. Start the database**
```powershell
cd C:\Projects\mcs_weightbridge
docker-compose up -d
```
This starts PostgreSQL 16 on `localhost:5432`.

**9. Enable PowerShell scripts** (one-time)
```powershell
Set-ExecutionPolicy RemoteSigned -Force
```

---

## 4. Running the Application Locally

You need **3 terminals** running simultaneously:

### Terminal 1 — Database (already running from setup)
```powershell
# If not running:
cd C:\Projects\mcs_weightbridge
docker-compose up -d
```

### Terminal 2 — Backend
```powershell
cd C:\Projects\mcs_weightbridge\backend
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 9001
```
The `--reload` flag auto-restarts when you change Python files.

### Terminal 3 — Frontend
```powershell
cd C:\Projects\mcs_weightbridge\frontend
npm run dev
```
Vite dev server starts on `http://localhost:9000` with hot reload.

### Open the App
- Open browser: **http://localhost:9000**
- Login: **admin** / **admin123**

### API Docs (Interactive)
- Swagger UI: **http://localhost:9001/docs**
- ReDoc: **http://localhost:9001/redoc**

> **How it connects:** The Vite dev server on port 9000 proxies all `/api/*` requests
> to the FastAPI backend on port 9001. This is configured in `frontend/vite.config.ts`.

---

## 5. Project Structure

```
mcs_weightbridge/
├── backend/
│   ├── app/
│   │   ├── main.py              # App startup, background tasks, middleware
│   │   ├── config.py            # Settings from .env (Pydantic BaseSettings)
│   │   ├── database.py          # Async SQLAlchemy engine + session factory
│   │   ├── dependencies.py      # Auth guards: get_current_user, require_role
│   │   ├── models/              # SQLAlchemy ORM models (1 file per table)
│   │   ├── routers/             # API endpoints (1 file per domain)
│   │   ├── schemas/             # Pydantic request/response models
│   │   ├── services/            # Business logic (license, USB guard, GST)
│   │   ├── middleware/          # License guard, security headers
│   │   ├── integrations/        # External: serial port, cameras, Tally, notifications
│   │   ├── templates/pdf/       # Jinja2 HTML templates for PDF invoices
│   │   └── utils/               # Helpers: auth, crypto, PDF generator
│   ├── alembic/                 # Database migration scripts
│   ├── tests/                   # Pytest test suite
│   ├── requirements.txt         # Python dependencies
│   ├── .env.example             # Template for environment variables
│   ├── build_dist.ps1           # Nuitka build script (Python → .exe)
│   ├── setup_dpapi.py           # Encrypt .env with Windows DPAPI
│   └── show_fingerprint.py      # Collect hardware fingerprint for licensing
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx              # Root component: routing, auth, layout
│   │   ├── main.tsx             # React entry point
│   │   ├── pages/               # Page components (1 file per page)
│   │   ├── components/          # Reusable UI components
│   │   │   └── ui/              # shadcn/ui primitives (button, dialog, etc.)
│   │   ├── hooks/               # Custom React hooks
│   │   ├── services/api.ts      # Axios client with JWT interceptor
│   │   ├── types/index.ts       # TypeScript interfaces
│   │   └── lib/utils.ts         # Utility functions
│   ├── package.json             # NPM config + scripts
│   ├── vite.config.ts           # Vite build + dev proxy config
│   └── tsconfig.json            # TypeScript config
│
├── scripts/                     # Deployment automation (PowerShell)
├── tools/                       # License generator utility
├── docker-compose.yml           # PostgreSQL database container
├── CLAUDE.md                    # Complete project reference (read this!)
├── SECURE_DEPLOYMENT_PIPELINE.md # How to build + deploy at client sites
└── .gitignore                   # Excludes secrets, binaries, node_modules
```

---

## 6. Understanding the Backend

### API Endpoint Pattern

Every API endpoint follows this pattern:
```python
# File: backend/app/routers/products.py

@router.get("/api/v1/products")
async def list_products(
    db: AsyncSession = Depends(get_db),           # Database session injected
    current_user: User = Depends(get_current_user), # Auth required
):
    result = await db.execute(select(Product).where(...))
    return result.scalars().all()
```

### Key Backend Files

| File | What to learn from it |
|------|----------------------|
| `app/main.py` | App startup, background tasks, DDL migrations |
| `app/dependencies.py` | How `get_current_user` and `require_role()` work |
| `app/routers/invoices.py` | Complex CRUD: drafts, finalization, PDF, GST calc |
| `app/routers/tokens.py` | Two-stage weighment: first weight + second weight |
| `app/routers/payments.py` | Payment receipts + linking to invoices |
| `app/integrations/serial_port/manager.py` | Weight scale hardware integration |
| `app/integrations/tally/xml_builder.py` | Tally XML voucher construction |
| `app/services/license.py` | Ed25519 license validation + hardware fingerprint |

### All API Routers (25)

| Router | Prefix | Description |
|--------|--------|-------------|
| auth | `/api/v1/auth` | Login, JWT, user CRUD |
| company | `/api/v1/company` | Company profile, financial years |
| products | `/api/v1` | Products + categories |
| parties | `/api/v1/parties` | Customers/suppliers |
| vehicles | `/api/v1` | Vehicles, drivers, transporters |
| tokens | `/api/v1/tokens` | Weighment tokens (two-stage) |
| invoices | `/api/v1/invoices` | Sales/purchase invoices |
| quotations | `/api/v1/quotations` | Price quotations |
| payments | `/api/v1/payments` | Receipts + vouchers |
| dashboard | `/api/v1/dashboard` | Today's metrics |
| reports | `/api/v1/reports` | Sales/purchase register, P&L, stock |
| weight | `/ws/weight` | WebSocket for live scale readings |
| tally | `/api/v1/tally` | Tally Prime sync |
| inventory | `/api/v1/inventory` | Store inventory + PO workflow |
| notifications | `/api/v1/notifications` | Templates, recipients, delivery log |
| backup | `/api/v1/backup` | Database backup/restore |
| audit | `/api/v1/audit` | Action audit trail |
| compliance | `/api/v1/compliance` | Insurance/license/permit tracking |
| cameras | `/api/v1/cameras` | IP camera snapshot config |
| usb_guard | `/api/v1/usb-guard` | USB key authentication |
| private_invoices | `/api/v1/private-invoices` | Encrypted non-GST invoices |
| import_data | `/api/v1/import` | Excel/CSV bulk import |
| app_settings | `/api/v1/app-settings` | Role permissions, wallpaper |
| license | `/api/v1/license` | License status check |

### User Roles

| Role | Access |
|------|--------|
| `admin` | Everything + user management |
| `operator` | Dashboard, tokens (weighment) |
| `sales_executive` | Dashboard, sales invoices, quotations, parties |
| `purchase_executive` | Dashboard, purchase invoices, parties, products |
| `accountant` | Dashboard, payments, ledger, GST reports |
| `store_manager` | Dashboard, store inventory |
| `viewer` | Dashboard, reports (read-only) |
| `private_admin` | Private invoice admin console only |

---

## 7. Understanding the Frontend

### Page Components (26 pages)

Each page is a self-contained React component in `frontend/src/pages/`:

| Page | Route | What it does |
|------|-------|-------------|
| `LoginPage` | `/login` | JWT login form |
| `DashboardPage` | `/` | Today's tokens, revenue, top customers |
| `TokenPage` | `/tokens` | Create/complete weighment tokens |
| `InvoicesPage` | `/invoices` | Sales invoice CRUD + PDF download |
| `InvoicesPage` | `/purchase-invoices` | Purchase invoices (same component) |
| `QuotationsPage` | `/quotations` | Quotation CRUD + convert to invoice |
| `PaymentsPage` | `/payments` | Record receipts/vouchers |
| `PartiesPage` | `/parties` | Customer/supplier CRUD |
| `ProductsPage` | `/products` | Product + category management |
| `VehiclesPage` | `/vehicles` | Vehicle, driver, transporter tabs |
| `ReportsPage` | `/reports` | Sales/purchase register, P&L, stock summary |
| `GstReportsPage` | `/gst-reports` | GSTR-1 (B2B/B2C/HSN), GSTR-3B |
| `LedgerPage` | `/ledger` | Party ledger + outstanding ageing |
| `InventoryPage` | `/inventory` | Stock, POs, history, analytics, settings |
| `NotificationsPage` | `/notifications` | Templates, recipients, delivery log |
| `SettingsPage` | `/settings` | Company, bank, weight scale, Tally, cameras |
| `BackupPage` | `/backup` | Create/restore backups + cloud status |
| `CompliancePage` | `/compliance` | Insurance/license/permit tracker |
| `AuditPage` | `/audit` | Action audit trail viewer |
| `ImportPage` | `/import` | Bulk Excel/CSV import |
| `UserManagementPage` | `/admin/users` | Create/edit users (admin only) |
| `PermissionsPage` | `/admin/permissions` | Role-page mapping (admin only) |

### Custom Hooks

| Hook | File | What it does |
|------|------|-------------|
| `useAuth` | `hooks/useAuth.ts` | Login/logout, JWT in sessionStorage, 401 listener |
| `useWeight` | `hooks/useWeight.ts` | WebSocket to `/ws/weight` for live scale readings |
| `useUsbGuard` | `hooks/useUsbGuard.ts` | Polls USB key status every 10s |
| `useAppSettings` | `hooks/useAppSettings.ts` | Loads role permissions + wallpaper URL |

### API Client

All API calls go through `frontend/src/services/api.ts`:
```typescript
import axios from 'axios';

const api = axios.create({ baseURL: '/' });

// Auto-inject JWT token on every request
api.interceptors.request.use(config => {
    const token = sessionStorage.getItem('token');
    if (token) config.headers.Authorization = `Bearer ${token}`;
    return config;
});

// Auto-logout on 401
api.interceptors.response.use(
    response => response,
    error => {
        if (error.response?.status === 401) {
            sessionStorage.removeItem('token');
            window.dispatchEvent(new Event('auth:logout'));
        }
        return Promise.reject(error);
    }
);
```

### UI Component Pattern

Every page follows this pattern:
```typescript
export default function InvoicesPage() {
    const [items, setItems] = useState<Invoice[]>([]);
    const [loading, setLoading] = useState(false);
    const [dialog, setDialog] = useState(false);

    const load = useCallback(async () => {
        setLoading(true);
        const { data } = await api.get('/api/v1/invoices');
        setItems(data.items);
        setLoading(false);
    }, []);

    useEffect(() => { load(); }, [load]);

    return (
        <div>
            <h1>Invoices</h1>
            <Button onClick={() => setDialog(true)}>New Invoice</Button>
            <Table data={items} />
            <Dialog open={dialog} onOpenChange={setDialog}>...</Dialog>
        </div>
    );
}
```

---

## 8. Database

### Connection

- **Engine:** PostgreSQL 16 (Docker container `weighbridge_db`)
- **Port:** 5432 (localhost only — firewalled from external access)
- **Credentials:** `weighbridge` / `weighbridge_dev_2024` (dev default)
- **Async driver:** `asyncpg` (for FastAPI async endpoints)
- **Connection pool:** 5 base + 10 overflow = max 15 connections

### Key Tables

| Table | Purpose |
|-------|---------|
| `users` | Application users (admin, operator, etc.) |
| `companies` | Company profile (GSTIN, PAN, bank details) |
| `financial_years` | Active fiscal year (April-March for India) |
| `parties` | Customers and suppliers |
| `products` | Product catalog with HSN codes and GST rates |
| `vehicles` | Truck registration numbers |
| `tokens` | Weighment records (gross, tare, net weight) |
| `invoices` | Sales and purchase invoices |
| `invoice_items` | Line items per invoice |
| `payment_receipts` | Incoming payments (from customers) |
| `payment_vouchers` | Outgoing payments (to suppliers) |
| `ledger_entries` | Double-entry accounting journal |
| `number_sequences` | Auto-incrementing invoice/token numbers |
| `notification_config` | Telegram/email/SMS channel settings |
| `notification_recipients` | Named contacts for alerts |
| `inventory_items` | Store stock levels |
| `inventory_purchase_orders` | PO workflow (raise, approve, receive) |

### Database Migrations

Tables are created two ways:
1. **Alembic migrations** (`backend/alembic/versions/`) — for initial schema
2. **Runtime DDL** in `main.py` — `ALTER TABLE ADD COLUMN IF NOT EXISTS` for new columns added after initial deployment

To run migrations:
```powershell
cd backend
.\venv\Scripts\Activate.ps1
alembic upgrade head
```

---

## 9. Key Code Patterns

### Authentication Guard
```python
# Require any logged-in user
@router.get("/api/v1/something")
async def handler(user: User = Depends(get_current_user)):
    pass

# Require admin role
@router.post("/api/v1/admin-only")
async def handler(user: User = Depends(require_role("admin"))):
    pass
```

### Database Session Injection
```python
@router.get("/api/v1/items")
async def list_items(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Item).where(Item.is_active == True))
    return result.scalars().all()
```

### Pagination
```python
# Backend returns: {"items": [...], "total": 150}
@router.get("/api/v1/invoices")
async def list_invoices(page: int = 1, page_size: int = 20, db = Depends(get_db)):
    offset = (page - 1) * page_size
    items = await db.execute(select(Invoice).offset(offset).limit(page_size))
    total = await db.execute(select(func.count(Invoice.id)))
    return {"items": items.scalars().all(), "total": total.scalar()}
```

### Background Task (fire-and-forget)
```python
from fastapi import BackgroundTasks

@router.post("/api/v1/invoices/{id}/finalise")
async def finalise(id: UUID, background_tasks: BackgroundTasks, db = Depends(get_db)):
    # ... finalize invoice ...
    background_tasks.add_task(send_telegram_notification, invoice_id=id)
    return {"message": "Invoice finalised"}
```

### INR Currency Formatting (Frontend)
```typescript
const INR = (v: number) => '₹' + v.toLocaleString('en-IN', { minimumFractionDigits: 2 });
// INR(150000) → "₹1,50,000.00"
```

### GST Calculation
```
If buyer's state == seller's state:
    CGST = rate / 2, SGST = rate / 2  (intra-state)
Else:
    IGST = rate  (inter-state)

State detected from first 2 digits of GSTIN.
```

---

## 10. Testing

### Running Tests
```powershell
cd backend
.\venv\Scripts\Activate.ps1
python -m pytest tests/ -v
```

### Test Structure
```
backend/tests/
    __init__.py
    conftest.py                    # Fixtures (MockTallyServer, sample data)
    mock_tally_server.py           # Fake Tally HTTP server for testing
    test_tally_integration.py      # 43 test cases
```

### Test Categories

| Category | Tests | What's Tested |
|----------|-------|--------------|
| XML Structure | 12 | Voucher XML is well-formed, correct types |
| Ledger Balance | 10 | Debit/credit amounts sum to zero |
| Mock Server | 8 | Push invoices/masters to mock Tally |
| Edge Cases | 5 | Special characters, zero amounts, multiple items |

> Tests use `types.SimpleNamespace` for mock data — **no database required** to run tests.

---

## 11. Building for Production

See **SECURE_DEPLOYMENT_PIPELINE.md** Section 0 for complete build instructions. Quick summary:

```powershell
# 1. Build frontend
cd frontend
npm run build      # → frontend/dist/

# 2. Build backend binary
cd backend
powershell -File build_dist.ps1    # → backend/dist/weighbridge_server.exe

# 3. Package release
# Follow Section 0.4 in SECURE_DEPLOYMENT_PIPELINE.md
```

---

## 12. Deploying to a Client

Read **SECURE_DEPLOYMENT_PIPELINE.md** — it covers the complete workflow:

1. Build release package (office)
2. Create Cloudflare Tunnel + Zero Trust policy
3. Generate hardware-locked license
4. Create deployment package with `Generate-DeploymentConfig.ps1`
5. Copy to USB drive
6. At client site: run `Deploy-Full.ps1` (automated 6-phase install)
7. Verify with `Verify-Deployment.ps1`

---

## 13. Git Workflow

### Branching
```powershell
# Create feature branch
git checkout -b feature/add-vehicle-report

# Work on your feature...

# Commit
git add -A
git commit -m "Add vehicle tonnage report"

# Push
git push -u origin feature/add-vehicle-report

# Create Pull Request on GitHub
```

### What NOT to Commit
The `.gitignore` protects against this, but be aware:
- **Never commit** `.env` files (contain passwords)
- **Never commit** `*.key` files (license keys, vendor keys)
- **Never commit** `CREDENTIALS_AND_URLS.md` (plaintext secrets)
- **Never commit** `node_modules/`, `venv/`, `dist/`, `*.exe`

### Before Each Commit
```powershell
# Check what's staged — make sure no secrets
git status
git diff --cached --name-only
```

---

## 14. Key Documents to Read Next

| Document | What You'll Learn |
|----------|------------------|
| **CLAUDE.md** | Complete API reference, database tables, all features |
| **SECURE_DEPLOYMENT_PIPELINE.md** | How to build + deploy at client sites |
| **BUILD_GUIDE.md** | Detailed build instructions (Nuitka, packaging) |
| **SETUP_GUIDE.md** | Windows server setup (services, LAN access) |

---

## 15. FAQ & Troubleshooting

### "uvicorn is not recognized"
You forgot to activate the virtual environment:
```powershell
cd backend
.\venv\Scripts\Activate.ps1
# You should see (venv) in your prompt
uvicorn app.main:app --reload --port 9001
```

### "Cannot connect to database"
Docker Desktop might not be running. Open Docker Desktop, wait for it to start, then:
```powershell
docker-compose up -d
```

### "Port 9001 already in use"
Another instance is running. Find and kill it:
```powershell
netstat -ano | findstr :9001
# Note the PID (last column)
taskkill /PID <PID> /F
```

### "npm run dev" shows errors
Missing node_modules. Run:
```powershell
cd frontend
npm install
npm run dev
```

### "Login returns 401"
The database might not have the admin user. Run the seed script:
```powershell
cd backend
.\venv\Scripts\Activate.ps1
python ..\scripts\seed_data.py
```
Default login: **admin** / **admin123**

### "Serial error: could not open port COM13"
This is normal if no weight scale is connected. The error appears at startup but the app continues running. The weight scale is optional for development.

### "Checking license..." screen won't go away
In development mode, the license check may fail. Add this to your `.env`:
```
LICENSE_CHECK_DISABLED=true
```
Or copy a valid `license.key` to the project root.

### How do I add a new API endpoint?

1. Create or edit a file in `backend/app/routers/`
2. Add the router to `backend/app/main.py` (import + `app.include_router()`)
3. Add Pydantic schemas in `backend/app/schemas/` if needed
4. Add ORM models in `backend/app/models/` if new tables needed
5. Add any new table DDL to the `column_migrations` list in `main.py`
6. Test with Swagger UI at http://localhost:9001/docs

### How do I add a new frontend page?

1. Create `frontend/src/pages/MyNewPage.tsx`
2. Add route in `frontend/src/App.tsx`
3. Add sidebar link in `frontend/src/components/Sidebar.tsx`
4. Add role permission in `backend/app/dependencies.py` → `DEFAULT_PERMISSIONS`
5. Update `frontend/src/hooks/useAppSettings.ts` if new permission

---

## Welcome to the Team!

Start by running the app locally (Section 4), then explore the code. The best way to learn the codebase is to:

1. Open Swagger UI (http://localhost:9001/docs) and try the API endpoints
2. Create a test token (weighment) in the UI and follow the code path
3. Read `CLAUDE.md` for the complete feature reference
4. Pick a small bug or feature and submit your first PR

If you get stuck, check the troubleshooting section above or ask the team.
