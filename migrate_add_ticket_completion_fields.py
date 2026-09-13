"""One-off migration: add ticket completion/review columns.

Same idempotent approach as migrate_add_tech_contact.py and
migrate_add_resume_fields.py: no Flask-Migrate/Alembic is set up in this
project, so this is a standalone script for adding columns to an EXISTING
Postgres database without touching any other tables or rows. Safe to run
more than once (ADD COLUMN IF NOT EXISTS).

Adds to the "tickets" table:
    - lang             VARCHAR(5)   the customer's language at creation,
                                     used to localize the completion email
                                     and review form (defaults to 'uk' for
                                     rows created before this column existed)
    - completed_at     TIMESTAMPTZ  when the technician marked it completed
    - client_rating    INTEGER      1-5 star rating left by the customer
    - client_review    TEXT         free-text review left by the customer

Usage:
    # Point at the target Postgres database (Render's "External Database
    # URL" if running from your own machine; "Internal Database URL" if
    # running from inside Render, e.g. via the service's Shell tab).
    export DATABASE_URL="postgresql://user:password@host:5432/dbname"
    python migrate_add_ticket_completion_fields.py
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
                    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS lang VARCHAR(5) DEFAULT 'uk';"
                )
                cur.execute(
                    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;"
                )
                cur.execute(
                    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS client_rating INTEGER;"
                )
                cur.execute(
                    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS client_review TEXT;"
                )
        print(
            "Done: tickets.lang, completed_at, client_rating, and "
            "client_review are present."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
