# ANUMATI v2 — Complete Deployment & Implementation Guide
**AICTE Approval Workflow Automation, Compliance Monitoring and Alert Management System**
*Problem Statement ID: SIH 26262 | AICTE Approval Process Handbook (APH 2024–27)*

---

This document provides a comprehensive, step-by-step deployment guide for running and developing **ANUMATI v2** locally on both **macOS** and **Windows (10/11)** systems.

---

## 📑 Table of Contents
1. [System Requirements](#1-system-requirements)
2. [Demo Credentials Matrix](#2-demo-credentials-matrix)
3. [Method 1: Docker 1-Click Deployment (Recommended for macOS & Windows)](#3-method-1-docker-1-click-deployment-recommended)
4. [Method 2: Native Manual Setup on macOS](#4-method-2-native-manual-setup-on-macos)
5. [Method 3: Native Manual Setup on Windows (PowerShell & CMD)](#5-method-3-native-manual-setup-on-windows)
6. [Running the Test Suites (macOS & Windows)](#6-running-the-test-suites)
7. [Troubleshooting & Common Edge Cases](#7-troubleshooting--common-edge-cases)

---

## 1. System Requirements

| Requirement | Minimum | Recommended |
| :--- | :--- | :--- |
| **Operating System** | macOS 12+ (Monterey/Ventura/Sonoma/Sequoia) or Windows 10/11 (64-bit) | macOS (Apple Silicon or Intel) / Windows 11 with WSL2 |
| **RAM** | 8 GB | 16 GB |
| **Disk Space** | 5 GB free disk space | 10 GB SSD |
| **Python** | Python 3.11, 3.12, or 3.13 | Python 3.12+ |
| **Node.js** | Node.js v18 LTS | Node.js v20+ or v22 LTS |
| **Docker (Optional)** | Docker Desktop 4.20+ with Docker Compose v2 | Docker Desktop with WSL2 (Windows) or Colima/OrbStack (macOS) |

---

## 2. Demo Credentials Matrix

When seeded with demonstration data, all accounts share the default password:
**`DemoOnly-2026-Local!`**

| Username | Role | Assigned Workspace | Capabilities / Workflow |
| :--- | :--- | :--- | :--- |
| `demo_institution` | `INSTITUTION_USER` | `/institution` | Application intake, deficiency response upload, evidence tracking, document validity & renewals. |
| `demo_officer` | `REGIONAL_OFFICER`, `SCRUTINY_MEMBER` | `/officer` | Scrutiny examination, recording deficiencies, review findings, EVC slot reservation, compliance verification. |
| `demo_evc` | `EVC_MEMBER` | `/officer` | Expert Visit Committee evaluation, observations recording, video upload ref, EVC report submission. |
| `demo_authority` | `COMPETENT_AUTHORITY` | `/officer` & `/policy` | Executive Committee disposition: Grant LoA/EoA, Issue LoD/LoR, Refer-Back, approve policy activations. |
| `demo_auditor` | `OVERSIGHT_AUDITOR` | `/oversight` | Regional/bureau pendency, officer/committee workload, ageing bottles, escalation register, sealed audit drill-down. |
| `demo_policy` | `POLICY_ADMIN` | `/policy` | Draft declarative policy versions, validate route integrity, dry-run regression suites, sync exceptions reconciliation. |
| `demo_admin` | `TECHNICAL_ADMIN` | `/admin` | System directory management (institutions, regions, bureaus, committees), user provisioning, failed outbox replay. |

> [!NOTE]
> Sign out from the portal before switching roles so that the server-issued session cookie and role-based workspace permissions re-initialize properly.

---

## 3. Method 1: Docker 1-Click Deployment (Recommended)

Docker provides an isolated, multi-container environment including **React (Nginx)**, **Django API**, **PostgreSQL 16**, **Redis 7**, **Celery Worker**, and **Celery Beat**.

### On macOS:
Open Terminal (`zsh` or `bash`):
```bash
# 1. Clone repository
git clone https://github.com/Shazeen899/Anumati.git
cd Anumati/anumati

# 2. Prepare environment file
cp .env.example .env

# 3. Launch the full isolated stack
docker compose -p anumati-demo -f docker-compose.demo.yml up --build -d

# 4. Check running containers
docker compose -p anumati-demo -f docker-compose.demo.yml ps
```

### On Windows:
Open **PowerShell** (Run as Administrator or standard user):
```powershell
# 1. Clone repository
git clone https://github.com/Shazeen899/Anumati.git
cd Anumati\anumati

# 2. Prepare environment file
Copy-Item .env.example .env

# 3. Launch Docker Compose stack
docker compose -p anumati-demo -f docker-compose.demo.yml up --build -d

# 4. Check running containers
docker compose -p anumati-demo -f docker-compose.demo.yml ps
```

### Accessing the Portal:
- **Web Interface:** [http://localhost:15173](http://localhost:15173) (or `http://127.0.0.1:15173`)
- **Backend API:** Proxied through `http://localhost:15173/api/`
- **Sign In:** Use `demo_officer` or `demo_institution` with password `DemoOnly-2026-Local!`

### Stopping Docker Stack:
```bash
# Retains database volume & uploaded test files
docker compose -p anumati-demo -f docker-compose.demo.yml down

# Or delete volumes to start completely fresh
docker compose -p anumati-demo -f docker-compose.demo.yml down -v
```

---

## 4. Method 2: Native Manual Setup on macOS

If you do not want to use Docker, you can run the backend and frontend directly using Python and Node.js.

### Step 1: Install Dependencies via Homebrew
```bash
brew install python@3.12 node
```

### Step 2: Clone & Set Up Backend Virtual Environment
```bash
cd Anumati/anumati

# Create Python virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Upgrade pip and install Python packages
pip install --upgrade pip
pip install -r backend/requirements.txt
```

### Step 3: Configure Environment Variables
```bash
cp .env.example .env
```

### Step 4: Database Migration & Seeding (SQLite Fallback)
The project supports an instant `USE_SQLITE_FALLBACK=true` flag so you don't even need to configure PostgreSQL locally:
```bash
# Run database migrations
USE_SQLITE_FALLBACK=true python backend/manage.py migrate

# Bootstrap default administrative accounts
USE_SQLITE_FALLBACK=true python backend/manage.py bootstrap_anumati

# Seed full synthetic demo data (Institutions, cases, stages, documents, demo users)
USE_SQLITE_FALLBACK=true python backend/manage.py seed_demo
```

### Step 5: Start the Django Backend Server
In Terminal 1 (with `.venv` active):
```bash
USE_SQLITE_FALLBACK=true python backend/manage.py runserver 127.0.0.1:8000
```
Backend will be live at `http://127.0.0.1:8000/api/v1/`.

### Step 6: Install Frontend & Start Vite Dev Server
Open a **new Terminal window** (Terminal 2):
```bash
cd Anumati/anumati/frontend

# Install npm packages
npm install

# Start Vite React server
npm run dev
```
Frontend will be live at `http://localhost:5173`. Open in your browser, log in, and explore all 4 workspaces!

---

## 5. Method 3: Native Manual Setup on Windows

Follow these exact steps in **Windows PowerShell** or **Command Prompt (CMD)**.

### Step 1: Prerequisites Installation on Windows
1. **Python 3.11 or 3.12:** Download from [python.org](https://www.python.org/downloads/).
   > [!IMPORTANT]
   > During Python installation, make sure to check **"Add python.exe to PATH"** on the first setup screen!
2. **Node.js LTS:** Download and install from [nodejs.org](https://nodejs.org/).
3. **Git for Windows:** Download and install from [git-scm.com](https://git-scm.com/).

### Step 2: Open PowerShell and Clone Repository
```powershell
cd "$HOME\Documents"
git clone https://github.com/Shazeen899/Anumati.git
cd Anumati\anumati
```

### Step 3: Create & Activate Virtual Environment
In PowerShell, if script execution is disabled by default, permit local scripts:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Create and activate the environment:
```powershell
# Create virtual environment
python -m venv .venv

# Activate in PowerShell
.\.venv\Scripts\Activate.ps1

# (Alternative: If you are using Command Prompt / CMD):
# .venv\Scripts\activate.bat
```

### Step 4: Install Backend Requirements
```powershell
python -m pip install --upgrade pip
pip install -r backend\requirements.txt
```

### Step 5: Configure Environment
```powershell
Copy-Item .env.example .env
```

### Step 6: Database Setup & Seeding (SQLite Fallback)
Set the SQLite fallback environment variable in PowerShell:
```powershell
$env:USE_SQLITE_FALLBACK="true"

# Run migrations
python backend\manage.py migrate

# Bootstrap default administrative accounts
python backend\manage.py bootstrap_anumati

# Seed demonstration workflow records & users
python backend\manage.py seed_demo
```

*(Note for CMD users):*
```cmd
set USE_SQLITE_FALLBACK=true
python backend\manage.py migrate
python backend\manage.py bootstrap_anumati
python backend\manage.py seed_demo
```

### Step 7: Run Backend Development Server
Keep Terminal 1 running:
```powershell
$env:USE_SQLITE_FALLBACK="true"
python backend\manage.py runserver 127.0.0.1:8000
```

### Step 8: Install Frontend Dependencies & Start Vite Server
Open a **new PowerShell window** (Terminal 2):
```powershell
cd "$HOME\Documents\Anumati\anumati\frontend"

# Install npm packages
npm install

# Start frontend development server
npm run dev
```

Open your browser to:
**[http://localhost:5173](http://localhost:5173)**

Sign in with:
- **Username:** `demo_officer`
- **Password:** `DemoOnly-2026-Local!`

---

## 6. Running the Test Suites

### Running All Verification Tests on macOS / Linux:
```bash
# Unified check (Static check, Ruff lint, Vitest, Pytest)
USE_SQLITE_FALLBACK=true ./scripts/checks.sh all
```

Or run backend and frontend tests individually:
```bash
# Backend test suite (59 tests across all domains + edge cases)
USE_SQLITE_FALLBACK=true .venv/bin/pytest backend

# Frontend test suite (19 tests across all workspace suites + edge cases)
cd frontend && npm test -- --run
```

### Running Tests on Windows (PowerShell):
```powershell
# Activate venv
.\.venv\Scripts\Activate.ps1

# Set fallback flag
$env:USE_SQLITE_FALLBACK="true"

# Run all 59 backend tests
pytest backend

# Run all 19 frontend Vitest tests
cd frontend
npm test -- --run
```

---

## 7. Troubleshooting & Common Edge Cases

### A. Port Conflict (8000, 5173, or 15173 already in use)
- **Error:** `Error: listen EADDRINUSE: address already in use 127.0.0.1:8000`
- **Solution (macOS):**
  ```bash
  lsof -ti:8000 | xargs kill -9
  lsof -ti:5173 | xargs kill -9
  ```
- **Solution (Windows PowerShell):**
  ```powershell
  Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess | Stop-Process -Force
  Get-Process -Id (Get-NetTCPConnection -LocalPort 5173).OwningProcess | Stop-Process -Force
  ```

### B. Windows PowerShell Script Execution Policy
- **Error:** `.\.venv\Scripts\Activate.ps1 cannot be loaded because running scripts is disabled on this system.`
- **Solution:** Run this command once in PowerShell:
  ```powershell
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
  ```

### C. Missing `USE_SQLITE_FALLBACK`
- **Error:** `psycopg.OperationalError: connection to server at "localhost", port 5432 failed: Connection refused`
- **Solution:** You forgot to set the SQLite fallback flag.
  - On macOS/Linux: `export USE_SQLITE_FALLBACK=true`
  - On Windows PowerShell: `$env:USE_SQLITE_FALLBACK="true"`
  - On Windows CMD: `set USE_SQLITE_FALLBACK=true`

### D. CSRF Token Error in Browser
- **Error:** `403 Forbidden: CSRF verification failed`
- **Solution:** Make sure you access the frontend via `http://localhost:5173` or `http://127.0.0.1:5173`, matching the CORS/CSRF trusted origins in `backend/config/settings/base.py`. Click "Sign out" and log in again to refresh the session token.

---

*Authored for SIH 26262 — ANUMATI v2 Architectural Standard.*
