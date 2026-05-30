# Databricks SQL connection helper. Provides get_cursor() (context manager that opens/closes
# a connection per call) and table() (builds a fully-qualified Delta table name from schema + table).

from databricks import sql
from contextlib import contextmanager
import os

CATALOG = os.getenv("DATABRICKS_CATALOG", "job_tracker")

SCHEMAS = {
    "system": os.getenv("DATABRICKS_SCHEMA_SYSTEM", "system"),
    "bronze": os.getenv("DATABRICKS_SCHEMA_BRONZE", "00_bronze"),
    "silver": os.getenv("DATABRICKS_SCHEMA_SILVER", "01_silver"),
    "gold":   os.getenv("DATABRICKS_SCHEMA_GOLD",   "02_gold"),
}


def table(schema: str, name: str) -> str:
    return f"`{CATALOG}`.`{SCHEMAS[schema]}`.`{name}`"


@contextmanager
def get_cursor():
    conn = sql.connect(
        server_hostname=os.getenv("DATABRICKS_HOST"),
        http_path=os.getenv("DATABRICKS_HTTP_PATH"),
        access_token=os.getenv("DATABRICKS_TOKEN"),
        _socket_timeout=30,
    )
    cursor = conn.cursor()
    try:
        yield cursor
    finally:
        cursor.close()
        conn.close()
