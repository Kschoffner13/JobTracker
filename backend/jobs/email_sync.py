# Databricks notebook source
# MAGIC %pip install google-auth>=2.38.0 google-auth-oauthlib>=1.2.0 google-api-python-client>=2.166.0

# COMMAND ----------

import base64
import re
from datetime import datetime, timedelta, timezone
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from pyspark.sql import SparkSession
from pyspark.sql.types import StructType, StructField, StringType
from pyspark.sql.functions import current_timestamp

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

# Credentials stored in Databricks Secret Scope (never hardcoded)
CLIENT_ID     = dbutils.secrets.get(scope="job-tracker", key="google-client-id")
CLIENT_SECRET = dbutils.secrets.get(scope="job-tracker", key="google-client-secret")

CATALOG       = "job_tracker"
USERS_TABLE   = f"`{CATALOG}`.`system`.`users`"
BRONZE_TABLE  = f"`{CATALOG}`.`00_bronze`.`emails`"
SILVER_TABLE  = f"`{CATALOG}`.`01_silver`.`applications`"

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

# COMMAND ----------

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
    # No prior scan — fall back to 6 months ago
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
    silver_rows = []
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
            subject    = headers.get("Subject", "")
            sender     = headers.get("From", "")
            received_at = headers.get("Date", "")
            body       = decode_body(msg["payload"])
            thread_id  = msg.get("threadId", "")

            bronze_rows.append((user_id, msg_id, thread_id, subject, sender, received_at, body))
            silver_rows.append((user_id, msg_id, extract_company(sender), detect_status(subject, body), subject, sender))
            print(f"  + {sender} | {subject}")

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
        StructField("received_at", StringType()),
        StructField("body_raw",    StringType()),
    ])
    silver_schema = StructType([
        StructField("user_id",       StringType()),
        StructField("message_id",    StringType()),
        StructField("company",       StringType()),
        StructField("status",        StringType()),
        StructField("email_subject", StringType()),
        StructField("sender",        StringType()),
    ])

    bronze_df = spark.createDataFrame(bronze_rows, bronze_schema).withColumn("ingested_at", current_timestamp())
    silver_df = spark.createDataFrame(silver_rows, silver_schema).withColumn("parsed_at", current_timestamp())

    bronze_df.createOrReplaceTempView("_bronze_batch")
    silver_df.createOrReplaceTempView("_silver_batch")

    spark.sql(f"""
        INSERT INTO {BRONZE_TABLE}
        SELECT user_id, message_id, thread_id, subject, sender, received_at, body_raw, ingested_at
        FROM _bronze_batch
    """)
    spark.sql(f"""
        INSERT INTO {SILVER_TABLE}
        SELECT user_id, message_id, company, status, email_subject, sender, parsed_at
        FROM _silver_batch
    """)

    print(f"  Ingested {len(bronze_rows)} new emails for {user_id}")

# COMMAND ----------

# Main — runs for every registered user
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
