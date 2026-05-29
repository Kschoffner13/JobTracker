# One-time setup script that creates all Databricks Delta schemas and tables (system, Bronze,
# Silver, Gold) and seeds the dim_status lookup table. Run before starting the server.
# Usage: python setup_db.py
from dotenv import load_dotenv
load_dotenv()

from db import get_cursor, table, CATALOG, SCHEMAS

TABLES = {
    ("system", "users"): """
        user_id       STRING NOT NULL,
        email         STRING NOT NULL,
        name          STRING,
        picture       STRING,
        refresh_token STRING,
        created_at    TIMESTAMP,
        last_login    TIMESTAMP
    """,
    ("bronze", "emails"): """
        user_id     STRING NOT NULL,
        message_id  STRING NOT NULL,
        thread_id   STRING,
        job_id      STRING,
        provider    STRING,
        subject     STRING,
        sender      STRING,
        received_at TIMESTAMP,
        body_ raw    STRING,
        ingested_at TIMESTAMP
    """,
    ("silver", "applications"): """
        user_id       STRING NOT NULL,
        message_id    STRING NOT NULL,
        job_id        STRING,
        provider      STRING,
        company       STRING,
        position      STRING,
        status        STRING,
        email_subject STRING,
        sender        STRING,
        received_at   TIMESTAMP,
        parsed_at     TIMESTAMP,
        source        STRING
    """,
    ("gold", "dim_status"): """
        status_id   INT NOT NULL,
        status_name STRING NOT NULL,
        rank        INT NOT NULL
    """,
    ("gold", "dim_companies"): """
        company_id INT NOT NULL,
        name       STRING NOT NULL,
        domain     STRING
    """,
    ("gold", "fact_applications"): """
        application_id INT NOT NULL,
        user_id        STRING NOT NULL,
        company_id     INT NOT NULL,
        status_id      INT NOT NULL,
        job_id         STRING,
        provider       STRING,
        source         STRING,
        position       STRING,
        applied_at     TIMESTAMP,
        last_updated   TIMESTAMP
    """,
}

DIM_STATUS_SEED = [
    (1, "applied",   1),
    (2, "interview", 2),
    (3, "offer",     3),
    (4, "rejected",  4),
]


def main():
    with get_cursor() as cursor:
        for tier, schema_name in SCHEMAS.items():
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS `{CATALOG}`.`{schema_name}`")
            print(f"Schema ready: {CATALOG}.{schema_name}")

        for (schema, name), columns in TABLES.items():
            cursor.execute(
                f"CREATE TABLE IF NOT EXISTS {table(schema, name)} ({columns}) USING DELTA"
            )
            print(f"  Table ready: {table(schema, name)}")

        # Seed dim_status (idempotent)
        for status_id, status_name, rank in DIM_STATUS_SEED:
            cursor.execute(f"""
                MERGE INTO {table('gold', 'dim_status')} AS t
                USING (SELECT {status_id} AS status_id) AS s ON t.status_id = s.status_id
                WHEN NOT MATCHED THEN
                    INSERT (status_id, status_name, rank) VALUES ({status_id}, '{status_name}', {rank})
            """)
        print("  dim_status seeded.")


if __name__ == "__main__":
    main()
