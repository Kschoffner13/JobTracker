# REST endpoints for managing job applications stored in Postgres. Supports listing,
# updating (company/position/status), status history, notes, and analytics summary.

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from deps import CurrentUser
from backend.archive.postgres import get_pg_cursor

router = APIRouter(prefix="/api/applications", tags=["applications"])

VALID_STATUSES = {"applied", "interview", "offer", "rejected"}


VALID_JOB_TYPES = {"Remote", "Hybrid", "On-site"}


class ApplicationUpdate(BaseModel):
    company_name: str | None = None
    position: str | None = None
    current_status: str | None = None
    job_type: str | None = None
    job_url: str | None = None



def _owns_application(cursor, application_id: int, user_id: str):
    cursor.execute(
        "SELECT application_id FROM applications WHERE application_id = %s AND user_id = %s",
        [application_id, user_id],
    )
    if not cursor.fetchone():  
        raise HTTPException(status_code=404, detail="Application not found")


@router.delete("/{application_id}")
def delete_application(application_id: int, user: CurrentUser):
    user_id = user["sub"]
    with get_pg_cursor() as cursor:
        _owns_application(cursor, application_id, user_id)
        cursor.execute("DELETE FROM notes WHERE application_id = %s", [application_id])
        cursor.execute("DELETE FROM status_events WHERE application_id = %s", [application_id])
        cursor.execute("DELETE FROM applications WHERE application_id = %s", [application_id])
    return {"ok": True}


@router.get("")
def list_applications(user: CurrentUser):
    user_id = user["sub"]
    with get_pg_cursor() as cursor:
        cursor.execute("""
            SELECT
                a.application_id, c.name AS company, a.position,
                a.current_status, a.source, a.job_type, a.job_url,
                a.applied_at, a.last_updated, a.job_id, a.provider
            FROM applications a
            JOIN companies c ON a.company_id = c.company_id
            WHERE a.user_id = %s
            ORDER BY a.applied_at DESC NULLS LAST
        """, [user_id])
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, r)) for r in cursor.fetchall()]


@router.patch("/{application_id}")
def update_application(application_id: int, body: ApplicationUpdate, user: CurrentUser):
    user_id = user["sub"]

    if body.current_status and body.current_status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {VALID_STATUSES}")

    with get_pg_cursor() as cursor:
        _owns_application(cursor, application_id, user_id)

        if body.company_name:
            cursor.execute("""
                INSERT INTO companies (name) VALUES (%s)
                ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                RETURNING company_id
            """, [body.company_name])
            company_id = cursor.fetchone()[0]
            cursor.execute(
                "UPDATE applications SET company_id = %s, last_updated = NOW() WHERE application_id = %s",
                [company_id, application_id],
            )

        if body.position is not None:
            cursor.execute(
                "UPDATE applications SET position = %s, last_updated = NOW() WHERE application_id = %s",
                [body.position, application_id],
            )

        if body.current_status:
            cursor.execute(
                "UPDATE applications SET current_status = %s, last_updated = NOW() WHERE application_id = %s",
                [body.current_status, application_id],
            )
            cursor.execute(
                "INSERT INTO status_events (application_id, status) VALUES (%s, %s)",
                [application_id, body.current_status],
            )

        if body.job_type is not None:
            if body.job_type and body.job_type not in VALID_JOB_TYPES:
                raise HTTPException(status_code=400, detail=f"Invalid job type. Must be one of: {VALID_JOB_TYPES}")
            cursor.execute(
                "UPDATE applications SET job_type = %s, last_updated = NOW() WHERE application_id = %s",
                [body.job_type or None, application_id],
            )

        if body.job_url is not None:
            cursor.execute(
                "UPDATE applications SET job_url = %s, last_updated = NOW() WHERE application_id = %s",
                [body.job_url or None, application_id],
            )

    return {"ok": True}


@router.get("/{application_id}/history")
def get_history(application_id: int, user: CurrentUser):
    user_id = user["sub"]
    with get_pg_cursor() as cursor:
        _owns_application(cursor, application_id, user_id)
        cursor.execute("""
            SELECT status, changed_at, source_email_id
            FROM status_events
            WHERE application_id = %s
            ORDER BY changed_at ASC
        """, [application_id])
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, r)) for r in cursor.fetchall()]




@router.get("/analytics/summary")
def get_analytics(user: CurrentUser):
    user_id = user["sub"]
    with get_pg_cursor() as cursor:
        # Status breakdown
        cursor.execute("""
            SELECT current_status, COUNT(*) AS total
            FROM applications
            WHERE user_id = %s
            GROUP BY current_status
        """, [user_id])
        status_counts = {r[0]: r[1] for r in cursor.fetchall()}

        # Applications per week (last 12 weeks)
        cursor.execute("""
            SELECT
                DATE_TRUNC('week', applied_at) AS week,
                COUNT(*) AS total
            FROM applications
            WHERE user_id = %s AND applied_at >= NOW() - INTERVAL '12 weeks'
            GROUP BY week
            ORDER BY week ASC
        """, [user_id])
        weekly = [{"week": str(r[0]), "total": r[1]} for r in cursor.fetchall()]

        # Average days applied → interview
        cursor.execute("""
            SELECT AVG(EXTRACT(EPOCH FROM (i.changed_at - a.applied_at)) / 86400)
            FROM applications a
            JOIN status_events i ON i.application_id = a.application_id AND i.status = 'interview'
            WHERE a.user_id = %s
        """, [user_id])
        avg_days_to_interview = cursor.fetchone()[0]

    return {
        "status_counts": status_counts,
        "weekly_applications": weekly,
        "avg_days_to_interview": round(avg_days_to_interview, 1) if avg_days_to_interview else None,
        "total": sum(status_counts.values()),
    }
