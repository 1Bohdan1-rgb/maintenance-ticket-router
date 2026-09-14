"""One-off migration: add technicians.price_tier and technicians.speed_rating.

Same idempotent approach as the other migrate_add_*.py scripts: no
Flask-Migrate/Alembic is set up in this project, so this is a standalone
script for adding columns to an EXISTING Postgres database without touching
any other tables or rows. Safe to run more than once (ADD COLUMN IF NOT
EXISTS).

Adds to the "technicians" table:
    - price_tier     VARCHAR(20)   optional price bracket the technician
                                    charges at: "budget" | "mid" | "premium"
                                    (NULL for existing rows and whenever a
                                    technician skips it at registration)
    - speed_rating    VARCHAR(20)   optional typical turnaround speed:
                                    "fast" | "medium" | "slow" (same NULL
                                    behavior as price_tier)

Both columns are nullable with no default, so existing technician rows are
left untouched (NULL = "not specified") rather than given a value that
might misrepresent them.

Usage:
    # Point at the target Postgres database (Render's "External Database
    # URL" if running from your own machine; "Internal Database URL" if
    # running from inside Render, e.g. via the service's Shell tab).
    export DATABASE_URL="postgresql://user:password@host:5432/dbname"
    python migrate_add_technician_price_speed.py
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
                    "ALTER TABLE technicians ADD COLUMN IF NOT EXISTS price_tier VARCHAR(20);"
                )
                cur.execute(
                    "ALTER TABLE technicians ADD COLUMN IF NOT EXISTS speed_rating VARCHAR(20);"
                )
        print("Done: technicians.price_tier and technicians.speed_rating are present.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
