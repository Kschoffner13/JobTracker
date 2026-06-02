# Postgres (Supabase) connection pool.
# get_pg_cursor() checks out a connection, yields a cursor,
# commits on success, and rolls back on error.

from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager
import os

_pool: ThreadedConnectionPool | None = None


def get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=os.getenv("POSTGRES_URL", "postgresql://jobtracker:jobtracker@localhost:5432/jobtracker"),
        )
    return _pool


@contextmanager
def get_pg_cursor():
    pool = get_pool()
    conn = pool.getconn()
    try:
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
    finally:
        pool.putconn(conn)
