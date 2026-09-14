"""One-off migration: add tickets.customer_phone.

Same idempotent approach as the other migrate_add_*.py scripts: no
Flask-Migrate/Alembic is set up in this project, so this is a standalone
script for adding a column to an EXISTING Postgres database without touching
any other tables or rows. Safe to run more than once (ADD COLUMN IF NOT
EXISTS).

Adds to the "tickets" table:
    - customer_phone   VARCHAR(30)   the customer's phone number, collected
                                      as an alternative to customer_email
                                      (the customer must provide at least
                                      one of the two - enforced in routes.py,
                                      not at the database level, since older
                                      rows may have neither)

Usage:
    # Point at the target Postgres database (Render's "External Database
    # URL" if running from your own machine; "Internal Database URL" if
    # running from inside Render, e.g. via the service's Shell tab).
    export DATABASE_URL="postgresql://user:password@host:5432/dbname"
    python migrate_add_customer_phone.py
"""
import os
import sys

import psycopg2


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        sys.exit(1)

    # Render (and some other providers) hand out "postgres://", but modern
    # SQLAlchemy rejects it - psycopg2 itself accepts either, but normalize
    # for consistency with app.py and to fail loudly on non-Postgres URLs.
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    if not database_url.startswith("postgresql://"):
        print(
            f"ERROR: this script only supports Postgres, got scheme: "
            f"{database_url.split('://', 1)[0]}://",
            file=sys.stderr,
        )
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS customer_phone VARCHAR(30);"
                )
        print("Done: tickets.customer_phone is present.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
