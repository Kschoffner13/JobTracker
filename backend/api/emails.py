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
