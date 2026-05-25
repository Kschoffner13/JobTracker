# JobTracker

A full-stack application that monitors your Gmail inbox for job application emails, automatically classifies them by company and status, and displays them on a dashboard. Built with React, FastAPI, Databricks Delta Lake, and Postgres (Supabase).

## What It Does

- Authenticates users via Google OAuth 2.0
- On first sign-in, scans the last 6 months of Gmail for job-related emails
- Classifies each email by company and application status (applied, interview, offer, rejected)
- Stores raw and classified data in a Databricks medallion architecture (Bronze → Silver)
- Syncs normalized, user-editable data to Postgres (Supabase)
- Rebuilds an analytical Gold star schema in Databricks from Postgres after each sync
- Runs a scheduled Databricks Workflow to automatically process new emails hourly
- Exposes a REST API for manual scans, application edits, notes, history, and analytics

## Architecture

```
frontend/               React 19 + TypeScript + Vite
backend/
  main.py               App entry point, CORS, router registration
  auth.py               Google OAuth code exchange, JWT session management
  email_monitor.py      Gmail scanning, Bronze/Silver writes, Postgres sync, Gold rebuild
  applications.py       CRUD + analytics endpoints (reads/writes Postgres)
  db.py                 Databricks SQL connection helper
  postgres.py           Supabase connection pool
  deps.py               JWT auth dependency for protected routes
  setup_db.py           One-time Databricks Delta table creation
  setup_postgres.py     One-time Postgres table creation
  jobs/
    email_sync.py       Notebook 1 — Bronze ingestion (all users, scheduled)
    bronze_to_silver.py Notebook 2 — Classify Bronze emails → Silver
    silver_to_postgres.py Notebook 3 — Sync Silver → Postgres
    rebuild_gold.py     Notebook 4 — Rebuild Gold star schema from Postgres
```

## Data Architecture

### Databricks — Medallion (Delta Lake)

```
Gmail API
    │
    ▼
00_bronze.emails          Raw email payloads (append-only, deduped by message_id)
    │
    ▼
01_silver.applications    Classified records — company, status, subject, sender, job_id
    │
    ▼
02_gold
  ├── dim_status          Lookup: applied / interview / offer / rejected + rank
  ├── dim_companies       One row per company (name, domain)
  └── fact_applications   One row per application — FKs to dim tables
```

### Postgres (Supabase) — Normalized / Transactional

```
users               Google profile + created_at
companies           Deduplicated company names and domains
applications        One row per job (user-editable: position, status, company)
status_events       Audit log of every status change, with source email reference
notes               Free-text notes attached to an application
```

**Data flow**: Bronze/Silver are pipeline-owned (append-only). Postgres is user-owned — users edit applications here. Gold is rebuilt from Postgres after every scan or edit, so analytics always reflect the latest user corrections.

**Status detection** runs regex patterns against subject + body in priority order:
`offer → interview → rejected → applied (default)`

**Company extraction** parses the sender's email domain, ignoring personal providers (Gmail, Yahoo, etc.)

**job_id** is a SHA-256 hash of `provider:thread_id`, giving each application a stable ID that traces through every tier and supports future non-Gmail providers.

### API Routes

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/google` | Exchange Google auth code → JWT |
| GET | `/api/auth/me` | Get current user from JWT |
| POST | `/api/auth/logout` | Invalidate session |
| POST | `/api/emails/scan` | Trigger incremental Gmail scan |
| GET | `/api/applications` | List all applications (from Postgres) |
| PATCH | `/api/applications/{id}` | Update company, position, or status |
| GET | `/api/applications/{id}/history` | Status change history |
| POST | `/api/applications/{id}/notes` | Add a note |
| GET | `/api/applications/{id}/notes` | List notes |
| GET | `/api/applications/analytics/summary` | Status counts, weekly activity, avg days to interview |

## Prerequisites

- Python 3.11+
- Node.js 18+
- A [Google Cloud project](https://console.cloud.google.com) with the Gmail API enabled
- A Databricks workspace with a SQL Warehouse
- A [Supabase](https://supabase.com) project (free tier works)

## Setup

### 1. Google Cloud

1. Go to **APIs & Services → Enabled APIs** and enable the **Gmail API**
2. Go to **APIs & Services → OAuth consent screen**
   - User type: External
   - Add scope: `https://www.googleapis.com/auth/gmail.readonly`
   - Add your Gmail as a test user
3. Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**
   - Application type: Web application
   - Authorized JavaScript origins: `http://localhost:5173`
   - Authorized redirect URIs: `http://localhost:5173`
4. Copy the **Client ID** and **Client Secret**

### 2. Supabase

1. Create a new project at [supabase.com](https://supabase.com)
2. Go to **Settings → Database → Connection string → URI** and copy the URL
3. If your password contains special characters (`@`, `#`, etc.), URL-encode them (e.g. `@` → `%40`, `#` → `%23`)

### 3. Backend

```bash
cd backend
pip install -r requirements.txt
```

Copy the example env file and fill in your values:
```bash
cp .env.example .env
```

```env
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
JWT_SECRET_KEY=        # python -c "import secrets; print(secrets.token_hex(32))"

DATABRICKS_HOST=your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=your-personal-access-token
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/your-warehouse-id
DATABRICKS_CATALOG=job_tracker
DATABRICKS_SCHEMA_SYSTEM=system
DATABRICKS_SCHEMA_BRONZE=00_bronze
DATABRICKS_SCHEMA_SILVER=01_silver
DATABRICKS_SCHEMA_GOLD=02_gold

POSTGRES_URL=postgresql://postgres:yourpassword@db.yourref.supabase.co:5432/postgres
```

Create all tables (run once each):
```bash
python setup_db.py        # Databricks Delta tables
python setup_postgres.py  # Supabase Postgres tables
```

Start the API:
```bash
uvicorn main:app --reload --port 8000
```

Interactive API docs: `http://localhost:8000/docs`

### 4. Frontend

```bash
cd frontend
npm install
```

```env
VITE_GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
VITE_API_BASE_URL=http://localhost:8000
```

```bash
npm run dev
```

App runs at `http://localhost:5173`

### 5. Databricks Workflow (Automated Pipeline)

The pipeline runs as 4 chained notebook tasks in a Databricks Workflow:

| Task | Notebook | What it does |
|------|----------|--------------|
| 1 | `email_sync.py` | Scans Gmail for all users, writes to Bronze |
| 2 | `bronze_to_silver.py` | Classifies new Bronze rows → Silver |
| 3 | `silver_to_postgres.py` | Syncs new Silver rows → Postgres |
| 4 | `rebuild_gold.py` | Rebuilds Gold star schema from Postgres |

**Setup:**

1. Create a Databricks Secret Scope named `job-tracker`:
   ```
   https://<your-workspace>.azuredatabricks.net/#secrets/createScope
   ```

2. Add secrets:
   ```bash
   databricks secrets put-secret job-tracker google-client-id
   databricks secrets put-secret job-tracker google-client-secret
   databricks secrets put-secret job-tracker postgres-url
   ```

3. Import all four notebooks from `backend/jobs/` into your Databricks Workspace

4. Go to **Workflows → Create Job**, add 4 tasks in order (each depending on the previous), set schedule to hourly (`0 * * * *`)

5. Click **Run now** to verify

> Note: Databricks Community Edition limits job schedules to hourly minimum. User-triggered scans from the frontend run the full pipeline immediately via FastAPI.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 19, TypeScript, Vite |
| Backend | Python, FastAPI, Uvicorn |
| Auth | Google OAuth 2.0, JWT (30-day expiry) |
| Email | Gmail API (`gmail.readonly`) |
| Data Lake | Databricks Delta Lake (medallion architecture) |
| Transactional DB | Postgres via Supabase |
| Pipeline | Databricks Workflows (4-task chained job) |
