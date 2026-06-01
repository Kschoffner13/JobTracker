# Databricks notebook source
# Databricks pipeline notebook: Bronze → Silver
# Reads emails from Bronze that have not yet been classified, applies regex-based status
# detection and company extraction, then inserts the results into the Silver table.

# COMMAND ----------
# MAGIC %run ../email_config

# COMMAND ----------

from datetime import datetime, timezone
from pyspark.sql import SparkSession
from pyspark.sql.types import StructType, StructField, StringType, TimestampType

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

CATALOG      = "job_tracker"
BRONZE_TABLE = f"`{CATALOG}`.`00_bronze`.emails"
SILVER_TABLE = f"`{CATALOG}`.`01_silver`.applications"

# COMMAND ----------

# Find Bronze rows that have no matching Silver row yet
new_bronze = spark.sql(f"""
    SELECT b.user_id, b.message_id, b.job_id, b.provider,
           b.sender, b.subject, b.body_raw, b.received_at
    FROM {BRONZE_TABLE} b
    LEFT JOIN {SILVER_TABLE} s ON b.message_id = s.message_id
    WHERE s.message_id IS NULL
""")

count = new_bronze.count()
print(f"[bronze_to_silver] {count} new row(s) to classify")

if count == 0:
    print("[bronze_to_silver] Nothing to do")
else:
    # Collect to driver so AI API calls run here (workers don't have the API key)
    rows = new_bronze.collect()
    parsed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    classified = []

    for row in rows:
        status   = detect_status(row.subject, row.body_raw)
        company  = extract_company(row.sender, row.subject, row.body_raw or "")
        position = extract_position(row.subject, row.body_raw)
        source   = detect_source(row.sender)
        classified.append((
            row.user_id, row.message_id, row.job_id, row.provider,
            company, position, status, row.subject,
            row.sender, row.received_at, parsed_at, source,
        ))
        print(f"  {row.sender} | {row.subject} → {status} | {source} | {position}")

    silver_schema = StructType([
        StructField("user_id",       StringType()),
        StructField("message_id",    StringType()),
        StructField("job_id",        StringType()),
        StructField("provider",      StringType()),
        StructField("company",       StringType()),
        StructField("position",      StringType()),
        StructField("status",        StringType()),
        StructField("email_subject", StringType()),
        StructField("sender",        StringType()),
        StructField("received_at",   TimestampType()),
        StructField("parsed_at",     TimestampType()),
        StructField("source",        StringType()),
    ])

    silver_df = spark.createDataFrame(classified, silver_schema)
    silver_df.createOrReplaceTempView("_silver_batch")

    spark.sql(f"""
        INSERT INTO {SILVER_TABLE}
        SELECT user_id, message_id, job_id, provider, company, position,
               status, email_subject, sender, received_at, parsed_at, source
        FROM _silver_batch
    """)

    print(f"[bronze_to_silver] Inserted {count} row(s) into Silver")
