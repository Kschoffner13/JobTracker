"""
Run once to create the Delta tables in Databricks.
Usage: python setup_db.py
"""
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
        subject     STRING,
        sender      STRING,
        received_at STRING,
        body_raw    STRING,
        ingested_at TIMESTAMP
    """,
    ("silver", "applications"): """
        user_id       STRING NOT NULL,
        message_id    STRING NOT NULL,
        company       STRING,
        status        STRING,
        email_subject STRING,
        sender        STRING,
        parsed_at     TIMESTAMP
    """,
}


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


if __name__ == "__main__":
    main()
