# Databricks notebook source
# MAGIC %pip install google-auth>=2.38.0 google-auth-oauthlib>=1.2.0 google-api-python-client>=2.166.0

# COMMAND ----------

import base64
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from pyspark.sql import SparkSession
from pyspark.sql.types import StructType, StructField, StringType, TimestampType
from pyspark.sql.functions import current_timestamp

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

CLIENT_ID     = dbutils.secrets.get(scope="job-tracker", key="google-client-id")
CLIENT_SECRET = dbutils.secrets.get(scope="job-tracker", key="google-client-secret")

CATALOG      = "job_tracker"
USERS_TABLE  = f"`{CATALOG}`.`system`.`users`"
BRONZE_TABLE = f"`{CATALOG}`.`00_bronze`.`emails`"

JOB_QUERY = (
    'subject:("your application" OR "thank you for applying" OR "application received" '
    'OR interview OR "job offer" OR offer OR rejected OR "we regret" OR '
    '"not moving forward" OR "next steps" OR "hiring process")'
)

# COMMAND ----------

def parse_date(date_str: str) -> datetime | None:
    try:
        return parsedate_to_datetime(date_str).astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


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


def get_watermark(user_id: str) -> str:
    row = spark.sql(f"""
        SELECT MAX(ingested_at) AS max_date
        FROM {BRONZE_TABLE}
        WHERE user_id = '{user_id}'
    """).collect()[0]
    if row.max_date:
        return row.max_date.strftime("%Y/%m/%d")
    return (datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y/%m/%d")


def get_existing_ids(user_id: str) -> set:
    rows = spark.sql(f"""
        SELECT message_id FROM {BRONZE_TABLE} WHERE user_id = '{user_id}'
    """).collect()
    return {r.message_id for r in rows}

# COMMAND ----------

def scan_user(user_id: str, refresh_token: str):
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )
    service = build("gmail", "v1", credentials=creds)

    after_date = get_watermark(user_id)
    query = f"after:{after_date} {JOB_QUERY}"
    existing_ids = get_existing_ids(user_id)

    bronze_rows = []
    page_token = None

    while True:
        kwargs = {"userId": "me", "q": query, "maxResults": 500}
        if page_token:
            kwargs["pageToken"] = page_token

        result = service.users().messages().list(**kwargs).execute()
        messages = result.get("messages", [])

        for msg_ref in messages:
            msg_id = msg_ref["id"]
            if msg_id in existing_ids:
                continue

            msg = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()

            headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
            bronze_rows.append((
                user_id,
                msg_id,
                msg.get("threadId", ""),
                headers.get("Subject", ""),
                headers.get("From", ""),
                parse_date(headers.get("Date", "")),
                decode_body(msg["payload"]),
            ))
            print(f"  + {headers.get('From', '')} | {headers.get('Subject', '')}")

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    if not bronze_rows:
        print(f"  No new emails for {user_id}")
        return

    bronze_schema = StructType([
        StructField("user_id",     StringType()),
        StructField("message_id",  StringType()),
        StructField("thread_id",   StringType()),
        StructField("subject",     StringType()),
        StructField("sender",      StringType()),
        StructField("received_at", TimestampType()),
        StructField("body_raw",    StringType()),
    ])

    bronze_df = spark.createDataFrame(bronze_rows, bronze_schema).withColumn("ingested_at", current_timestamp())
    bronze_df.createOrReplaceTempView("_bronze_batch")

    spark.sql(f"""
        INSERT INTO {BRONZE_TABLE}
        SELECT user_id, message_id, thread_id, subject, sender, received_at, body_raw, ingested_at
        FROM _bronze_batch
    """)

    print(f"  Ingested {len(bronze_rows)} new emails for {user_id}")

# COMMAND ----------

print(f"[email_sync] Starting at {datetime.now(timezone.utc).isoformat()}")

users = spark.sql(f"""
    SELECT user_id, refresh_token
    FROM {USERS_TABLE}
    WHERE refresh_token IS NOT NULL
""").collect()

print(f"[email_sync] {len(users)} user(s) to process")

for user in users:
    print(f"[email_sync] Scanning {user.user_id}")
    try:
        scan_user(user.user_id, user.refresh_token)
    except Exception as e:
        print(f"[email_sync] ERROR for {user.user_id}: {e}")

print(f"[email_sync] Done at {datetime.now(timezone.utc).isoformat()}")
