# Databricks notebook source
# Databricks pipeline notebook: Postgres → Gold
# Reads the current normalized state from Postgres and does a full rebuild of the Gold
# star schema (dim_companies and fact_applications) in Databricks Delta.

# MAGIC %pip install psycopg2-binary>=2.9.0

# COMMAND ----------

import psycopg2
from contextlib import contextmanager
from pyspark.sql import Row, SparkSession
from pyspark.sql.types import (
    StructType, StructField,
    IntegerType, StringType, TimestampType,
)

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

CATALOG           = "job_tracker"
DIM_COMPANIES     = f"`{CATALOG}`.`02_gold`.dim_companies"
FACT_APPLICATIONS = f"`{CATALOG}`.`02_gold`.fact_applications"

POSTGRES_URL = dbutils.secrets.get(scope="job-tracker", key="postgres-url")

STATUS_ID = {"applied": 1, "interview": 2, "offer": 3, "rejected": 4}


@contextmanager
def pg_conn():
    conn = psycopg2.connect(POSTGRES_URL)
    try:
        yield conn
    finally:
        conn.close()

# COMMAND ----------

with pg_conn() as conn:
    with conn.cursor() as pg:
        pg.execute("""
            SELECT a.application_id, a.user_id, a.company_id, c.name,
                   COALESCE(c.domain, ''), a.job_id, a.provider,
                   COALESCE(a.source, ''), COALESCE(a.position, ''),
                   a.current_status, a.applied_at, a.last_updated
            FROM applications a
            JOIN companies c ON a.company_id = c.company_id
        """)
        rows = pg.fetchall()

print(f"[rebuild_gold] {len(rows)} application(s) from Postgres")

if not rows:
    print("[rebuild_gold] Nothing to rebuild")
    dbutils.notebook.exit("no data")

# COMMAND ----------

# Build dim_companies rows (deduplicated by company_id)
company_map = {}
for row in rows:
    _, _, company_id, company_name, domain, *_ = row
    if company_id not in company_map:
        company_map[company_id] = Row(company_id=int(company_id), name=company_name, domain=domain)

companies_schema = StructType([
    StructField("company_id", IntegerType()),
    StructField("name",       StringType()),
    StructField("domain",     StringType()),
])
companies_df = spark.createDataFrame(list(company_map.values()), companies_schema)

# Build fact_applications rows
fact_schema = StructType([
    StructField("application_id", IntegerType()),
    StructField("user_id",        StringType()),
    StructField("company_id",     IntegerType()),
    StructField("status_id",      IntegerType()),
    StructField("job_id",         StringType()),
    StructField("provider",       StringType()),
    StructField("source",         StringType()),
    StructField("position",       StringType()),
    StructField("applied_at",     TimestampType()),
    StructField("last_updated",   TimestampType()),
])

fact_rows = [
    Row(
        application_id=int(r[0]),
        user_id=r[1],
        company_id=int(r[2]),
        status_id=STATUS_ID.get(r[9], 1),
        job_id=r[5],
        provider=r[6],
        source=r[7],
        position=r[8],
        applied_at=r[10],
        last_updated=r[11],
    )
    for r in rows
]
fact_df = spark.createDataFrame(fact_rows, fact_schema)

# COMMAND ----------

# Full rebuild: delete existing rows then insert fresh data
companies_df.createOrReplaceTempView("_gold_companies")
fact_df.createOrReplaceTempView("_gold_fact")

spark.sql(f"DELETE FROM {DIM_COMPANIES}")
spark.sql(f"""
    INSERT INTO {DIM_COMPANIES}
    SELECT company_id, name, domain FROM _gold_companies
""")

spark.sql(f"DELETE FROM {FACT_APPLICATIONS}")
spark.sql(f"""
    INSERT INTO {FACT_APPLICATIONS}
    SELECT application_id, user_id, company_id, status_id,
           job_id, provider, source, position, applied_at, last_updated
    FROM _gold_fact
""")

print(f"[rebuild_gold] Gold rebuilt — {len(company_map)} company(s), {len(fact_rows)} application(s)")
