# Gmail scanning and ingestion pipeline. Fetches job-related emails via the Gmail API,
# writes raw messages to Databricks Bronze, classifies them into Silver, syncs normalized
# records to Postgres, and rebuilds the Gold star schema after each scan.

from fastapi import APIRouter, HTTPException
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import os
from datetime import datetime, timedelta, timezone
from deps import CurrentUser
from db import get_cursor, table
from postgres import get_pg_cursor
from email_config import JOB_QUERY, make_job_id, decode_body, detect_status, extract_company, extract_position

router = APIRouter(prefix="/api", tags=["emails"])

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")


def build_gmail_service(refresh_token: str):
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )
    return build("gmail", "v1", credentials=creds)


def get_watermark(user_id: str) -> str | None:
    """Return the date of the last ingested email as a Gmail date string YYYY/MM/DD."""
    with get_cursor() as cursor:
        cursor.execute(
            f"SELECT MAX(ingested_at) FROM {table('bronze', 'emails')} WHERE user_id = ?",
            [user_id],
        )
        row = cursor.fetchone()
    if row and row[0]:
        return row[0].strftime("%Y/%m/%d")
    return None


def run_scan(user_id: str, refresh_token: str, after_date: str | None = None) -> list[dict]:
    """
    Fetch job-related emails from Gmail and write to Bronze + Silver.
    after_date: Gmail date string "YYYY/MM/DD". Defaults to 6 months ago.
    Returns a list of newly ingested email dicts.
    """
    if not after_date:
        after_date = (datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y/%m/%d")

    service = build_gmail_service(refresh_token)
    query = f"after:{after_date} {JOB_QUERY}"

    print(f"[scan] Starting scan for {user_id} after {after_date}")

    ingested: list[dict] = []
    page_token = None

    while True:
        kwargs: dict = {"userId": "me", "q": query, "maxResults": 500}
        if page_token:
            kwargs["pageToken"] = page_token

        result = service.users().messages().list(**kwargs).execute()
        messages = result.get("messages", [])

        for msg_ref in messages:
            msg_id = msg_ref["id"]

            with get_cursor() as cursor:
                cursor.execute(
                    f"SELECT 1 FROM {table('bronze', 'emails')} WHERE user_id = ? AND message_id = ?",
                    [user_id, msg_id],
                )
                if cursor.fetchone():
                    continue

            msg = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()

            headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
            subject = headers.get("Subject", "")
            sender = headers.get("From", "")
            received_at = headers.get("Date", "")
            body = decode_body(msg["payload"])
            thread_id = msg.get("threadId", "")
            provider = "gmail"
            job_id = make_job_id(provider, thread_id)

            # Bronze — raw email
            with get_cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {table('bronze', 'emails')} "
                    f"(user_id, message_id, thread_id, job_id, provider, subject, sender, received_at, body_raw, ingested_at) "
                    f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp())",
                    [user_id, msg_id, thread_id, job_id, provider, subject, sender, received_at, body],
                )

            # Silver — classified
            status = detect_status(subject, body)
            company = extract_company(sender)
            position = extract_position(subject, body)

            with get_cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {table('silver', 'applications')} "
                    f"(user_id, message_id, job_id, provider, company, position, status, email_subject, sender, received_at, parsed_at) "
                    f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp())",
                    [user_id, msg_id, job_id, provider, company, position, status, subject, sender, received_at],
                )

            sync_to_postgres(user_id, msg_id, job_id, provider, company, status)

            ingested.append({
                "id": msg_id,
                "subject": subject,
                "from": sender,
                "date": received_at,
                "snippet": msg.get("snippet", ""),
                "body": body,
            })
            print(f"[scan] {sender} | {subject}")

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    print(f"[scan] Done for {user_id}: {len(ingested)} new emails ingested")
    return ingested


STATUS_RANK = {"applied": 1, "interview": 2, "offer": 3, "rejected": 4}


def sync_to_postgres(user_id: str, msg_id: str, job_id: str, provider: str,
                     company: str, status: str):
    with get_pg_cursor() as pg:
        # Upsert company
        pg.execute("""
            INSERT INTO companies (name) VALUES (%s)
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
            RETURNING company_id
        """, [company])
        company_id = pg.fetchone()[0]

        # Check if application exists for this job_id
        pg.execute(
            "SELECT application_id, current_status FROM applications WHERE job_id = %s AND user_id = %s",
            [job_id, user_id],
        )
        existing = pg.fetchone()

        if not existing:
            pg.execute("""
                INSERT INTO applications (user_id, company_id, job_id, provider, current_status, applied_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                RETURNING application_id
            """, [user_id, company_id, job_id, provider, status])
            application_id = pg.fetchone()[0]
            pg.execute(
                "INSERT INTO status_events (application_id, status, source_email_id) VALUES (%s, %s, %s)",
                [application_id, status, msg_id],
            )
        else:
            application_id, current_status = existing
            if STATUS_RANK.get(status, 0) > STATUS_RANK.get(current_status, 0):
                pg.execute(
                    "UPDATE applications SET current_status = %s, last_updated = NOW() WHERE application_id = %s",
                    [status, application_id],
                )
                pg.execute(
                    "INSERT INTO status_events (application_id, status, source_email_id) VALUES (%s, %s, %s)",
                    [application_id, status, msg_id],
                )


def rebuild_gold_for_user(user_id: str):
    with get_pg_cursor() as pg:
        pg.execute("""
            SELECT a.application_id, a.user_id, a.company_id, c.name,
                   COALESCE(c.domain, ''), a.job_id, a.provider,
                   COALESCE(a.position, ''), a.current_status,
                   a.applied_at, a.last_updated
            FROM applications a
            JOIN companies c ON a.company_id = c.company_id
            WHERE a.user_id = %s
        """, [user_id])
        rows = pg.fetchall()

    if not rows:
        return

    STATUS_ID = {"applied": 1, "interview": 2, "offer": 3, "rejected": 4}

    with get_cursor() as cursor:
        cursor.execute(
            f"DELETE FROM {table('gold', 'fact_applications')} WHERE user_id = ?",
            [user_id],
        )

        seen_companies = set()
        for row in rows:
            _, _, company_id, company_name, domain, *_ = row
            if company_id not in seen_companies:
                cursor.execute(
                    f"DELETE FROM {table('gold', 'dim_companies')} WHERE company_id = ?",
                    [company_id],
                )
                cursor.execute(
                    f"INSERT INTO {table('gold', 'dim_companies')} (company_id, name, domain) VALUES (?, ?, ?)",
                    [company_id, company_name, domain],
                )
                seen_companies.add(company_id)

        for row in rows:
            app_id, uid, company_id, _, _, job_id, provider, position, status, applied_at, last_updated = row
            applied_str = applied_at.strftime("%Y-%m-%d %H:%M:%S") if applied_at else None
            updated_str = last_updated.strftime("%Y-%m-%d %H:%M:%S") if last_updated else None
            cursor.execute(
                f"INSERT INTO {table('gold', 'fact_applications')} "
                f"(application_id, user_id, company_id, status_id, job_id, provider, position, applied_at, last_updated) "
                f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [app_id, uid, company_id, STATUS_ID.get(status, 1),
                 job_id, provider, position, applied_str, updated_str],
            )

    print(f"[gold] Rebuilt for {user_id}: {len(rows)} applications")


@router.post("/emails/scan")
def scan_emails(user: CurrentUser):
    user_id = user["sub"]

    with get_cursor() as cursor:
        cursor.execute(
            f"SELECT refresh_token FROM {table('system', 'users')} WHERE user_id = ?",
            [user_id],
        )
        row = cursor.fetchone()

    if not row or not row[0]:
        raise HTTPException(status_code=400, detail="No Gmail credentials on file — please sign out and sign in again")

    after_date = get_watermark(user_id)
    emails = run_scan(user_id, row[0], after_date)
    rebuild_gold_for_user(user_id)

    return {"new": len(emails), "emails": emails}


@router.get("/applications")
def get_applications(user: CurrentUser):
    user_id = user["sub"]

    with get_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT company, status, email_count, first_contact, last_update
            FROM (
                SELECT
                    company,
                    status,
                    COUNT(*) OVER (PARTITION BY company)       AS email_count,
                    MIN(parsed_at) OVER (PARTITION BY company) AS first_contact,
                    MAX(parsed_at) OVER (PARTITION BY company) AS last_update,
                    ROW_NUMBER() OVER (PARTITION BY company ORDER BY parsed_at DESC) AS rn
                FROM {table('silver', 'applications')}
                WHERE user_id = ?
            )
            WHERE rn = 1
            ORDER BY last_update DESC
            """,
            [user_id],
        )
        rows = cursor.fetchall()

    return [
        {
            "company": r[0],
            "status": r[1],
            "email_count": r[2],
            "first_contact": str(r[3]),
            "last_update": str(r[4]),
        }
        for r in rows
    ]
