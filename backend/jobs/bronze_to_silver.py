# Databricks notebook source
# Databricks pipeline notebook: Bronze → Silver
# Reads emails from Bronze that have not yet been classified, applies regex-based status
# detection and company extraction, then inserts the results into the Silver table.

# COMMAND ----------
# MAGIC %run ../email_config

# COMMAND ----------

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StringType

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

CATALOG      = "job_tracker"
BRONZE_TABLE = f"`{CATALOG}`.`00_bronze`.emails"
SILVER_TABLE = f"`{CATALOG}`.`01_silver`.applications"

# Wrap shared functions as Spark UDFs for DataFrame operations
detect_status_udf   = F.udf(detect_status, StringType())
extract_company_udf = F.udf(extract_company, StringType())
extract_position_udf = F.udf(extract_position, StringType())

# COMMAND ----------

# Find Bronze rows that have no matching Silver row yet
new_bronze = spark.sql(f"""
    SELECT b.*
    FROM {BRONZE_TABLE} b
    LEFT JOIN {SILVER_TABLE} s ON b.message_id = s.message_id
    WHERE s.message_id IS NULL
""")

count = new_bronze.count()
print(f"[bronze_to_silver] {count} new row(s) to classify")

if count == 0:
    print("[bronze_to_silver] Nothing to do")
else:
    silver_df = (
        new_bronze
        .withColumn("status",        detect_status_udf(F.col("subject"), F.col("body_raw")))
        .withColumn("company",       extract_company_udf(F.col("sender")))
        .withColumn("position",      extract_position_udf(F.col("subject"), F.col("body_raw")))
        .withColumn("email_subject", F.col("subject"))
        .withColumn("parsed_at",     F.current_timestamp())
        .select(
            "user_id", "message_id", "job_id", "provider",
            "company", "position", "status", "email_subject",
            "sender", "received_at", "parsed_at",
        )
    )

    silver_df.createOrReplaceTempView("_silver_batch")

    spark.sql(f"""
        INSERT INTO {SILVER_TABLE}
        SELECT user_id, message_id, job_id, provider, company, position,
               status, email_subject, sender, received_at, parsed_at
        FROM _silver_batch
    """)

    print(f"[bronze_to_silver] Inserted {count} row(s) into Silver")
