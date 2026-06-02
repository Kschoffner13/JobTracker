# Email scanning endpoints — manual (user-triggered) and scheduled (cron-triggered).

from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
import os
from core.deps import CurrentUser
from core.db import get_cursor, table
from services.email_scanner import run_scan, write_to_databricks, rebuild_gold_for_user, get_watermark

router = APIRouter(prefix="/api", tags=["emails"])


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
        raise HTTPException(
            status_code=400,
            detail="No Gmail credentials on file — please sign out and sign in again",
        )

    after_date = get_watermark(user_id)

    # Postgres written synchronously — user sees results immediately
    emails, bronze_batch, silver_batch = run_scan(user_id, row[0], after_date)

    # Databricks and Gold written in background — cold start doesn't block the user
    background_tasks.add_task(write_to_databricks, user_id, bronze_batch, silver_batch)
    background_tasks.add_task(rebuild_gold_for_user, user_id)

    return {"new": len(emails), "emails": emails}


@router.post("/emails/scan/all")
def scan_all_users(request: Request, background_tasks: BackgroundTasks):
    """Cron endpoint — scans all users. Secured by X-Cron-Secret header, not a user JWT.
    Returns immediately; scanning happens in the background.
    Set CRON_SECRET in .env and match it in the GitHub Actions secret.
    """
    cron_secret = os.getenv("CRON_SECRET", "")
    if not cron_secret or request.headers.get("X-Cron-Secret") != cron_secret:
        raise HTTPException(status_code=401, detail="Unauthorized")

    with get_cursor() as cursor:
        cursor.execute(
            f"SELECT user_id, refresh_token FROM {table('system', 'users')} WHERE refresh_token IS NOT NULL"
        )
        users = cursor.fetchall()

    def scan_all():
        for user_id, refresh_token in users:
            try:
                after_date = get_watermark(user_id)
                emails, bronze_batch, silver_batch = run_scan(user_id, refresh_token, after_date)
                write_to_databricks(user_id, bronze_batch, silver_batch)
                rebuild_gold_for_user(user_id)
                print(f"[cron] {user_id}: {len(emails)} new emails")
            except Exception as e:
                print(f"[cron] Error for {user_id}: {e}")

    background_tasks.add_task(scan_all)
    return {"status": "scan started", "users": len(users)}
