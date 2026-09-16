"""One-off migration: add tickets.match_priority and tickets.preferred_gender.

Same idempotent approach as the other migrate_add_*.py scripts: no
Flask-Migrate/Alembic is set up in this project, so this is a standalone
script for adding columns to an EXISTING Postgres database without touching
any other tables or rows. Safe to run more than once (ADD COLUMN IF NOT
EXISTS).

Adds to the "tickets" table:
    - match_priority     VARCHAR(20)   "quality" | "speed" | "price" - the
                          client's stated priority at ticket creation time
                          (NULL for tickets created before this column
                          existed).
    - preferred_gender   VARCHAR(20)   "male" | "female" - the client's
                          preferred technician gender, if any (NULL = no
                          preference / created before this column existed).

Previously these were only used transiently during assignment and then
discarded, so /admin/reassign-pending could never honor a client's original
choice when retrying a gap - it silently fell back to "quality"/no
preference. Backfilling old rows isn't possible (the original values were
never stored anywhere), so existing tickets are simply left NULL, which the
app already treats as "quality"/no preference - unchanged behavior for them.

Usage:
    # Point at the target Postgres database (Render's "External Database
    # URL" if running from your own machine; "Internal Database URL" if
    # running from inside Render, e.g. via the service's Shell tab).
    export DATABASE_URL="postgresql://user:password@host:5432/dbname"
    python migrate_add_ticket_match_preferences.py
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
                    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS match_priority VARCHAR(20);"
                )
                cur.execute(
                    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS preferred_gender VARCHAR(20);"
                )
        print("Done: tickets.match_priority and tickets.preferred_gender are present.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
