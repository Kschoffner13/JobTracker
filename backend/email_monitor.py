# Gmail scanning and ingestion pipeline. Fetches job-related emails via the Gmail API,
# writes raw messages to Databricks Bronze, classifies them into Silver, syncs normalized
# records to Postgres, and rebuilds the Gold star schema after each scan.

from fastapi import APIRouter, HTTPException, BackgroundTasks
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from email.utils import parsedate_to_datetime
import os
from datetime import datetime, timedelta, timezone
from deps import CurrentUser
from db import get_cursor, table
from postgres import get_pg_cursor
from email_config import JOB_QUERY, make_job_id, decode_body, detect_status, extract_company, extract_position, detect_source, is_application_email

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
    """Return the Gmail after: date string for the next scan.
    Uses MAX(received_at) from Bronze (the actual email date) minus 1 day,
    because Gmail's after: filter is exclusive so subtracting 1 day ensures
    we include emails from the same day as the last ingested email.
    """
    with get_cursor() as cursor:
        cursor.execute(
            f"SELECT MAX(received_at) FROM {table('bronze', 'emails')} WHERE user_id = ?",
            [user_id],
        )
        row = cursor.fetchone()
    if row and row[0]:
        watermark = (row[0] - timedelta(days=1)).strftime("%Y/%m/%d")
        return watermark
    return None


def run_scan(user_id: str, refresh_token: str, after_date: str | None = None):
    """
    Fetch emails from Gmail, classify in memory, write to Postgres immediately.
    Returns (ingested, bronze_batch, silver_batch) — the batches are written to
    Databricks in the background so the user gets results without waiting for a
    cold warehouse start.
    """
    if not after_date:
        after_date = (datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y/%m/%d")

    service = build_gmail_service(refresh_token)
    query = f"after:{after_date} {JOB_QUERY}"
    print(f"[scan] Starting scan for {user_id} after {after_date}")

    # Only query Postgres for deduplication — no Databricks in the hot path
    with get_pg_cursor() as pg:
        pg.execute("SELECT source_email_id FROM status_events WHERE source_email_id IS NOT NULL")
        synced_postgres = {row[0] for row in pg.fetchall()}

    bronze_batch: list[list] = []
    silver_batch: list[list] = []
    ingested: list[dict]     = []
    page_token = None

    while True:
        kwargs: dict = {"userId": "me", "q": query, "maxResults": 500}
        if page_token:
            kwargs["pageToken"] = page_token
        result = service.users().messages().list(**kwargs).execute()

        for msg_ref in result.get("messages", []):
            msg_id = msg_ref["id"]
            if msg_id in synced_postgres:
                continue

            msg     = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
            headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
            subject    = headers.get("Subject", "")
            sender     = headers.get("From", "")
            body       = decode_body(msg["payload"])
            thread_id  = msg.get("threadId", "")
            provider   = "gmail"
            job_id     = make_job_id(provider, thread_id)
            try:
                received_at = parsedate_to_datetime(headers.get("Date", "")).astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                received_at = datetime.now(timezone.utc).replace(tzinfo=None)

            if not is_application_email(sender, subject, body):
                print(f"[scan] Skipping promo: {subject}")
                continue

            print(f"[scan] {sender} | {subject}")

            status   = detect_status(subject, body)
            company  = extract_company(sender, subject, body)
            position = extract_position(subject, body)
            source   = detect_source(sender)

            bronze_batch.append([user_id, msg_id, thread_id, job_id, provider, subject, sender, received_at, body])
            silver_batch.append([user_id, msg_id, job_id, provider, company, position, status, subject, sender, received_at, source])

            sync_to_postgres(user_id, msg_id, job_id, provider, company, status, source, received_at, position)
            synced_postgres.add(msg_id)

            ingested.append({"id": msg_id, "subject": subject, "from": sender,
                              "date": str(received_at), "snippet": msg.get("snippet", ""), "body": body})

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    print(f"[scan] Done for {user_id}: {len(ingested)} new emails ingested")
    return ingested, bronze_batch, silver_batch


def write_to_databricks(user_id: str, bronze_batch: list, silver_batch: list):
    """Write Bronze and Silver batches in the background after the scan has returned.
    Checks for existing IDs first to avoid duplicates from the Databricks scheduled job.
    """
    if not bronze_batch and not silver_batch:
        return
    try:
        with get_cursor() as cursor:
            cursor.execute(
                f"SELECT message_id FROM {table('bronze', 'emails')} WHERE user_id = ?", [user_id]
            )
            existing_bronze = {row[0] for row in cursor.fetchall()}
            cursor.execute(
                f"SELECT message_id FROM {table('silver', 'applications')} WHERE user_id = ?", [user_id]
            )
            existing_silver = {row[0] for row in cursor.fetchall()}

            for row in bronze_batch:
                if row[1] not in existing_bronze:
                    cursor.execute(
                        f"INSERT INTO {table('bronze', 'emails')} "
                        f"(user_id, message_id, thread_id, job_id, provider, subject, sender, received_at, body_raw, ingested_at) "
                        f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp())", row,
                    )

            for row in silver_batch:
                if row[1] not in existing_silver:
                    cursor.execute(
                        f"INSERT INTO {table('silver', 'applications')} "
                        f"(user_id, message_id, job_id, provider, company, position, status, email_subject, sender, received_at, parsed_at, source) "
                        f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp(), ?)", row,
                    )

        print(f"[databricks] Wrote {len(bronze_batch)} Bronze + {len(silver_batch)} Silver rows for {user_id}")
    except Exception as e:
        print(f"[databricks] Background write failed (non-fatal): {e}")


STATUS_RANK = {"applied": 1, "interview": 2, "offer": 3, "rejected": 4}


def sync_to_postgres(user_id: str, msg_id: str, job_id: str, provider: str,
                     company: str, status: str, source: str = "Unknown",
                     received_at=None, position: str | None = None):
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
                INSERT INTO applications (user_id, company_id, job_id, provider, source, position, current_status, applied_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING application_id
            """, [user_id, company_id, job_id, provider, source, position, status, received_at])
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
                   COALESCE(a.source, ''), COALESCE(a.position, ''),
                   a.current_status, a.applied_at, a.last_updated
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
            app_id, uid, company_id, _, _, job_id, provider, source, position, status, applied_at, last_updated = row
            applied_str = applied_at.strftime("%Y-%m-%d %H:%M:%S") if applied_at else None
            updated_str = last_updated.strftime("%Y-%m-%d %H:%M:%S") if last_updated else None
            cursor.execute(
                f"INSERT INTO {table('gold', 'fact_applications')} "
                f"(application_id, user_id, company_id, status_id, job_id, provider, source, position, applied_at, last_updated) "
                f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [app_id, uid, company_id, STATUS_ID.get(status, 1),
                 job_id, provider, source, position, applied_str, updated_str],
            )

    print(f"[gold] Rebuilt for {user_id}: {len(rows)} applications")


@router.post("/emails/scan")
def scan_emails(user: CurrentUser, background_tasks: BackgroundTasks):
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

    # Postgres is written synchronously — user sees results immediately
    emails, bronze_batch, silver_batch = run_scan(user_id, row[0], after_date)

    # Databricks and Gold are written in the background — cold start doesn't block the user
    background_tasks.add_task(write_to_databricks, user_id, bronze_batch, silver_batch)
    background_tasks.add_task(rebuild_gold_for_user, user_id)

    return {"new": len(emails), "emails": emails}


