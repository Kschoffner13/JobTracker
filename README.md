# JobTracker

A full-stack application that monitors your Gmail inbox for job application emails, automatically classifies them by company, status, and position, and displays them on an interactive dashboard. Built with React, FastAPI, Databricks Delta Lake, and Postgres (Supabase).

## What It Does

- Authenticates users via Google OAuth 2.0
- On first sign-in, automatically scans the last 6 months of Gmail history
- Filters out promotional emails — only real job application emails are stored
- Classifies each email: company, position, status (applied/interview/offer/rejected), source platform, and job URL
- Stores raw data in Databricks (Bronze/Silver/Gold medallion architecture)
- Syncs normalized, user-editable records to Postgres (Supabase) — the primary data source for the UI
- Runs automated scans every 15 minutes via GitHub Actions
- Exposes a REST API for manual scans, application edits, analytics, and status history

## Architecture

```
frontend/                     React 19 + TypeScript + Vite
backend/
  main.py                     App entry point, CORS, router registration
  email_config.py             Email classification logic (shared with Databricks)
  email_patterns.py           Platform-specific patterns and regexes
  core/
    deps.py                   JWT auth dependency
    db.py                     Databricks SQL connection
    postgres.py               Supabase connection pool
  models/
    schemas.py                Pydantic request/response models
  api/
    auth.py                   Google OAuth, JWT issuance
    emails.py                 Manual scan + cron scan endpoints
    applications.py           CRUD, analytics, status history
  services/
    email_scanner.py          Gmail scanning, Postgres sync, Gold rebuild
  jobs/                       Databricks notebooks (background pipeline)
    email_sync.py             Bronze ingestion (all users)
    bronze_to_silver.py       Classify Bronze → Silver
    silver_to_postgres.py     Sync Silver → Postgres
    rebuild_gold.py           Rebuild Gold star schema
  setup_files/
    setup_db.py               One-time Databricks table creation
    setup_postgres.py         One-time Postgres table creation
.github/
  workflows/
    scan.yml                  GitHub Actions cron job (every 15 min)
```

## Data Architecture

### Scan pipeline (per request)

```
Gmail API
    │  (classified in memory — no Databricks in the hot path)
    ▼
Postgres (Supabase)           ← written synchronously, UI reads from here
    │
    ▼  (background task)
Databricks Bronze/Silver      ← written after response is returned
    │
    ▼  (background task)
Databricks Gold               ← star schema rebuilt from Postgres
```

### Databricks — Medallion (Delta Lake)

```
00_bronze.emails          Raw email payloads (append-only)
01_silver.applications    Classified: company, status, position, source, job_url
02_gold
  ├── dim_status          Lookup table
  ├── dim_companies       One row per company
  └── fact_applications   One row per application
```

### Postgres (Supabase) — Primary application database

```
users               Google profile + OAuth refresh token reference
companies           Deduplicated company names
applications        One row per job — editable: company, position, status, job_type, job_url
status_events       Audit log of every status change
```

### Email classification

- **Status detection** uses regex patterns: `offer → interview → rejected → applied`
- **Company extraction** handles LinkedIn notifications, ATS platforms (Greenhouse, Lever, Ashby, BambooHR, Workday, etc.), and company-owned domains
- **Position extraction** has platform-specific parsers for ZipRecruiter, LinkedIn, and generic ATS subject formats
- **Source detection** maps sender domain to the platform (LinkedIn, Greenhouse, Company Website, etc.)
- **Promotional filtering** blocks non-application emails from known platforms before they reach the database

### API Routes

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/auth/google` | — | Exchange Google auth code → JWT |
| GET | `/api/auth/me` | JWT | Get current user from token |
| POST | `/api/auth/logout` | JWT | Invalidate session |
| POST | `/api/emails/scan` | JWT | Trigger incremental Gmail scan |
| POST | `/api/emails/scan/all` | Cron secret | Scan all users (GitHub Actions) |
| GET | `/api/applications` | JWT | List all applications |
| PATCH | `/api/applications/{id}` | JWT | Update company, position, status, job_type, job_url |
| DELETE | `/api/applications/{id}` | JWT | Delete an application |
| GET | `/api/applications/{id}/history` | JWT | Status change history |
| GET | `/api/applications/analytics/summary` | JWT | Status counts, weekly activity, avg days to interview |

## Prerequisites

- Python 3.11+
- Node.js 18+
- A [Google Cloud project](https://console.cloud.google.com) with the Gmail API enabled
- A [Databricks](https://databricks.com) workspace (Community Edition works for development)
- A [Supabase](https://supabase.com) project (free tier works)
- A GitHub repository (for GitHub Actions cron)

## Local Development Setup

### 1. Start both servers with one command

```bash
npm install       # install concurrently at the root
npm run dev       # starts FastAPI (port 8000) + Vite (port 5173)
```

### 2. Google Cloud

1. Enable the **Gmail API** under APIs & Services
2. Configure the **OAuth consent screen** — External, add `gmail.readonly` scope, add your Gmail as test user
3. Create an **OAuth client ID** — Web application
   - Authorized JavaScript origins: `http://localhost:5173`
   - Authorized redirect URIs: `http://localhost:5173`
4. Copy the **Client ID** and **Client Secret**

### 3. Supabase

1. Create a project at [supabase.com](https://supabase.com)
2. Go to **Settings → Database → Connection string → URI** and copy it
3. URL-encode any special characters in your password (`@` → `%40`, `#` → `%23`)

### 4. Backend environment

```bash
cd backend
pip install -r requirements.txt
```

Create `backend/.env`:

```env
# Google OAuth
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
JWT_SECRET_KEY=        # python -c "import secrets; print(secrets.token_hex(32))"

# Databricks
DATABRICKS_HOST=your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=your-personal-access-token
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/your-warehouse-id
DATABRICKS_CATALOG=job_tracker
DATABRICKS_SCHEMA_SYSTEM=system
DATABRICKS_SCHEMA_BRONZE=00_bronze
DATABRICKS_SCHEMA_SILVER=01_silver
DATABRICKS_SCHEMA_GOLD=02_gold

# Postgres (Supabase)
POSTGRES_URL=postgresql://postgres:yourpassword@db.yourref.supabase.co:5432/postgres

# GitHub Actions cron secret
CRON_SECRET=        # python -c "import secrets; print(secrets.token_hex(32))"
```

Create all database tables (run once):

```bash
cd backend
python setup_files/setup_db.py        # Databricks Delta tables
python setup_files/setup_postgres.py  # Supabase Postgres tables
```

### 5. Frontend environment

Create `frontend/.env`:

```env
VITE_GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
VITE_API_BASE_URL=http://localhost:8000
```

## Automated Scanning (GitHub Actions)

A workflow in `.github/workflows/scan.yml` calls `POST /api/emails/scan/all` every 15 minutes, scanning new emails for all registered users automatically.

**Setup:**

1. Generate a cron secret:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. Add the same value to `CRON_SECRET` in `.env` and as a GitHub secret

3. Add your deployed backend URL as a GitHub secret:

   | Secret | Value |
   |--------|-------|
   | `CRON_SECRET` | The random string from step 1 |
   | `API_URL` | Your deployed backend URL (e.g. `https://your-app.onrender.com`) |

4. To test manually: GitHub repo → **Actions → Hourly Email Scan → Run workflow**

> The GitHub Action only works once the backend is deployed to a public URL. For local development, use the **Scan Emails** button in the frontend.

## Deployment

| Layer | Recommended service |
|-------|-------------------|
| Frontend | [Vercel](https://vercel.com) — free, auto-deploys from GitHub |
| Backend | [Render](https://render.com) — free tier, or Railway ($5/month) for always-on |
| Database | Supabase (already hosted) |
| Data lake | Databricks (already hosted) |
| Scheduling | GitHub Actions (free) |

**Before deploying**, update `main.py` CORS to allow your Vercel domain:
```python
allow_origins=["https://your-app.vercel.app"]
```

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 19, TypeScript, Vite |
| Backend | Python 3.11, FastAPI, Uvicorn |
| Auth | Google OAuth 2.0, JWT (30-day expiry) |
| Email | Gmail API (`gmail.readonly`) |
| Data Lake | Databricks Delta Lake (Bronze / Silver / Gold) |
| Transactional DB | Postgres via Supabase |
| Scheduling | GitHub Actions (every 15 min) |
