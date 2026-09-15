"""One-off migration: add tickets.photo_data and tickets.photo_content_type.

Same idempotent approach as the other migrate_add_*.py scripts: no
Flask-Migrate/Alembic is set up in this project, so this is a standalone
script for adding columns to an EXISTING Postgres database without touching
any other tables or rows. Safe to run more than once (ADD COLUMN IF NOT
EXISTS).

Render's free-tier filesystem is ephemeral (no Persistent Disk add-on), so
uploaded photos are stored inline in Postgres as base64 text rather than on
disk or in external object storage - simplest option that needs no new
accounts/credentials, adequate for the small photos this feature expects
(server-side capped at 5 MB decoded, see models.MAX_PHOTO_BYTES).

Adds to the "tickets" table:
    - photo_data           TEXT          base64-encoded photo bytes (no
                                          "data:" URI prefix), NULL when no
                                          photo was attached
    - photo_content_type   VARCHAR(50)   MIME type of the photo, e.g.
                                          "image/jpeg"

Both columns are nullable with no default, so existing ticket rows are
left untouched (NULL = "no photo").

Usage:
    # Point at the target Postgres database (Render's "External Database
    # URL" if running from your own machine; "Internal Database URL" if
    # running from inside Render, e.g. via the service's Shell tab).
    export DATABASE_URL="postgresql://user:password@host:5432/dbname"
    python migrate_add_ticket_photo.py
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
                    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS photo_data TEXT;"
                )
                cur.execute(
                    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS photo_content_type VARCHAR(50);"
                )
        print("Done: tickets.photo_data and tickets.photo_content_type are present.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
