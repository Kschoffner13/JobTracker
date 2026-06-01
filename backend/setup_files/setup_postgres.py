# One-time setup script that creates the normalized Postgres (Supabase) schema: users,
# companies, applications, status_events, and notes. Run before starting the server.
# Usage: python setup_postgres.py
from dotenv import load_dotenv
load_dotenv()

from postgres import get_pg_cursor

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    VARCHAR PRIMARY KEY,
    email      VARCHAR UNIQUE NOT NULL,
    name       VARCHAR,
    picture    VARCHAR,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS companies (
    company_id SERIAL PRIMARY KEY,
    name       VARCHAR NOT NULL UNIQUE,
    domain     VARCHAR
);

CREATE TABLE IF NOT EXISTS applications (
    application_id SERIAL PRIMARY KEY,
    user_id        VARCHAR REFERENCES users(user_id),
    company_id     INT REFERENCES companies(company_id),
    job_id         VARCHAR UNIQUE,
    provider       VARCHAR DEFAULT 'gmail',
    source         VARCHAR,
    position       VARCHAR,
    job_type       VARCHAR,
    job_url        VARCHAR,
    current_status VARCHAR DEFAULT 'applied',
    applied_at     TIMESTAMP,
    last_updated   TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS status_events (
    event_id        SERIAL PRIMARY KEY,
    application_id  INT REFERENCES applications(application_id),
    status          VARCHAR NOT NULL,
    changed_at      TIMESTAMP DEFAULT NOW(),
    source_email_id VARCHAR
);

CREATE TABLE IF NOT EXISTS notes (
    note_id        SERIAL PRIMARY KEY,
    application_id INT REFERENCES applications(application_id),
    content        TEXT NOT NULL,
    created_at     TIMESTAMP DEFAULT NOW()
);
"""


def main():
    with get_pg_cursor() as cursor:
        cursor.execute(SCHEMA)
    print("Postgres tables ready.")


if __name__ == "__main__":
    main()
