# JobTracker

A full-stack application that monitors your Gmail inbox for job application emails, automatically classifies them by company and status, and displays them on a dashboard. Built with React, FastAPI, and Databricks Delta Lake.

## What It Does

- Authenticates users via Google OAuth 2.0
- On first sign-in, scans the last 6 months of Gmail for job-related emails
- Classifies each email by company and application status (applied, interview, offer, rejected)
- Stores data in a Databricks medallion architecture (Bronze → Silver → Gold)
- Runs a scheduled Databricks Workflow to automatically sync new emails hourly
- Exposes a REST API for the frontend to trigger manual scans and retrieve results

## Architecture

```
frontend/          React 19 + TypeScript + Vite
backend/           FastAPI + Python
  auth.py          Google OAuth code exchange, JWT session management
  email_monitor.py Gmail scanning, email classification, Databricks writes
  db.py            Databricks SQL connection helper
  deps.py          JWT auth dependency for protected routes
  setup_db.py      One-time Delta table creation
  jobs/
    email_sync.py  Databricks Workflow notebook for scheduled sync
```

### ELT Pipeline — Medallion Architecture

```
Gmail API
    │
    ▼
00_bronze.emails          Raw email payloads (append-only, never modified)
    │
    ▼
01_silver.applications    Parsed records — company, status, subject, sender
    │
    ▼
GET /api/applications     Gold view — one row per company, most recent status
```

**Status detection** runs regex patterns against subject + body in priority order:
`offer → interview → rejected → applied (default)`

**Company extraction** parses the sender's email domain, ignoring personal providers (Gmail, Yahoo, etc.)

### API Routes

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/google` | Exchange Google auth code → JWT |
| GET | `/api/auth/me` | Get current user from JWT |
| POST | `/api/auth/logout` | Invalidate session |
| POST | `/api/emails/scan` | Trigger incremental Gmail scan |
| GET | `/api/applications` | Return applications grouped by company |

## Prerequisites

- Python 3.11+
- Node.js 18+
- A [Google Cloud project](https://console.cloud.google.com) with the Gmail API enabled
- A Databricks workspace with a SQL Warehouse

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

### 2. Backend

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
JWT_SECRET_KEY=run: python -c "import secrets; print(secrets.token_hex(32))"
DATABRICKS_HOST=your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=your-personal-access-token
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/your-warehouse-id
DATABRICKS_CATALOG=job_tracker
DATABRICKS_SCHEMA_SYSTEM=system
DATABRICKS_SCHEMA_BRONZE=00_bronze
DATABRICKS_SCHEMA_SILVER=01_silver
DATABRICKS_SCHEMA_GOLD=02_gold
```

Create the Delta tables (run once):
```bash
python setup_db.py
```

Start the API:
```bash
uvicorn main:app --reload --port 8000
```

Interactive API docs available at `http://localhost:8000/docs`

### 3. Frontend

```bash
cd frontend
npm install
```

Copy the example env file:
```bash
cp .env.example .env
```

```env
VITE_GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
VITE_API_BASE_URL=http://localhost:8000
```

Start the dev server:
```bash
npm run dev
```

App runs at `http://localhost:5173`

### 4. Databricks Workflow (Automated Sync)

1. Create a Databricks Secret Scope named `job-tracker`:
   ```
   https://<your-workspace>.azuredatabricks.net/#secrets/createScope
   ```
2. Add your Google credentials as secrets:
   ```bash
   databricks secrets put --scope job-tracker --key google-client-id
   databricks secrets put --scope job-tracker --key google-client-secret
   ```
3. Import `backend/jobs/email_sync.py` into your Databricks Workspace
4. Go to **Workflows → Create Job**
   - Task type: Notebook
   - Path: the imported notebook
   - Schedule: hourly (`0 * * * *`)
5. Click **Run now** to verify it works

## Databricks Table Structure

```
job_tracker (catalog)
├── system
│   └── users              user profile + encrypted Google refresh token
├── 00_bronze
│   └── emails             raw Gmail message payloads
├── 01_silver
│   └── applications       parsed company, status, subject per email
└── 02_gold
    └── (served via API)   aggregated view built at query time
```

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 19, TypeScript, Vite |
| Backend | Python, FastAPI, Uvicorn |
| Auth | Google OAuth 2.0, JWT |
| Email | Gmail API (`gmail.readonly`) |
| Database | Databricks Delta Lake |
| Pipeline | Databricks Workflows |
