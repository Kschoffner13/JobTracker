# Databricks notebook source

# Databricks pipeline notebook: Silver → Postgres
# Finds Silver rows that have not yet been synced to Postgres by checking against
# source_email_id in status_events, then upserts companies, applications, and status events.

# MAGIC %pip install psycopg2-binary>=2.9.0

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import psycopg2
from contextlib import contextmanager
from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

CATALOG      = "job_tracker"
SILVER_TABLE = f"`{CATALOG}`.`01_silver`.applications"

POSTGRES_URL = dbutils.secrets.get(scope="job-tracker", key="postgres-url")

STATUS_RANK = {"applied": 1, "interview": 2, "offer": 3, "rejected": 4}


@contextmanager
def pg_conn():
    conn = psycopg2.connect(POSTGRES_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# COMMAND ----------

# Load all Silver rows
silver_rows = spark.sql(f"""
    SELECT user_id, message_id, job_id, provider, company, status
    FROM {SILVER_TABLE}
""").collect()

print(f"[silver_to_postgres] {len(silver_rows)} Silver row(s) found")

# Get already-synced message IDs from Postgres in one query
with pg_conn() as conn:
    with conn.cursor() as pg:
        pg.execute("SELECT source_email_id FROM status_events WHERE source_email_id IS NOT NULL")
        synced_ids = {row[0] for row in pg.fetchall()}

new_rows = [r for r in silver_rows if r.message_id not in synced_ids]
print(f"[silver_to_postgres] {len(new_rows)} new row(s) to sync")

if not new_rows:
    print("[silver_to_postgres] Nothing to do")
else:
    with pg_conn() as conn:
        with conn.cursor() as pg:
            for row in new_rows:
                user_id  = row.user_id
                msg_id   = row.message_id
                job_id   = row.job_id
                provider = row.provider
                company  = row.company
                status   = row.status

                # Upsert company
                pg.execute("""
                    INSERT INTO companies (name) VALUES (%s)
                    ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                    RETURNING company_id
                """, [company])
                company_id = pg.fetchone()[0]

                # Check for existing application
                pg.execute(
                    "SELECT application_id, current_status FROM applications WHERE job_id = %s AND user_id = %s",
                    [job_id, user_id],
                )
                existing = pg.fetchone()

                if not existing:
                    pg.execute("""
                        INSERT INTO applications
                            (user_id, company_id, job_id, provider, current_status, applied_at)
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

    print(f"[silver_to_postgres] Synced {len(new_rows)} row(s) to Postgres")
