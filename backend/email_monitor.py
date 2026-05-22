from fastapi import APIRouter, HTTPException
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import base64
import re
import os
from datetime import datetime, timedelta, timezone
from deps import CurrentUser
from db import get_cursor, table

router = APIRouter(prefix="/api", tags=["emails"])

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

JOB_QUERY = (
    'subject:("your application" OR "thank you for applying" OR "application received" '
    'OR interview OR "job offer" OR offer OR rejected OR "we regret" OR '
    '"not moving forward" OR "next steps" OR "hiring process")'
)

STATUS_PATTERNS = [
    (r"offer|pleased to offer|congratulations.*position|accept.*offer", "offer"),
    (r"interview|schedule.*call|speak with you|next steps|hiring manager", "interview"),
    (r"unfortunately|regret|not.*moving forward|decided.*not|no longer|other candidate", "rejected"),
    (r"received your application|thank you for apply|application.*received|we have received", "applied"),
]


def detect_status(subject: str, body: str) -> str:
    text = f"{subject} {body}".lower()
    for pattern, status in STATUS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return status
    return "applied"


def extract_company(sender: str) -> str:
    match = re.search(r"@([\w.-]+)", sender)
    if not match:
        return "Unknown"
    domain = match.group(1)
    personal_domains = {"gmail", "yahoo", "hotmail", "outlook", "icloud", "me", "googlemail"}
    parts = domain.split(".")
    company_part = parts[-2] if len(parts) >= 2 else parts[0]
    if company_part in personal_domains:
        return "Unknown"
    return company_part.capitalize()


def build_gmail_service(refresh_token: str):
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )
    return build("gmail", "v1", credentials=creds)


def decode_body(payload: dict) -> str:
    if "parts" in payload:
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")[:2000]
    data = payload.get("body", {}).get("data", "")
    if data:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")[:2000]
    return ""


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

            # Bronze — raw email
            with get_cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {table('bronze', 'emails')} "
                    f"(user_id, message_id, thread_id, subject, sender, received_at, body_raw, ingested_at) "
                    f"VALUES (?, ?, ?, ?, ?, ?, ?, current_timestamp())",
                    [user_id, msg_id, thread_id, subject, sender, received_at, body],
                )

            # Silver — classified
            status = detect_status(subject, body)
            company = extract_company(sender)

            with get_cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {table('silver', 'applications')} "
                    f"(user_id, message_id, company, status, email_subject, sender, parsed_at) "
                    f"VALUES (?, ?, ?, ?, ?, ?, current_timestamp())",
                    [user_id, msg_id, company, status, subject, sender],
                )

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
