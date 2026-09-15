"""One-off migration: add the ticket_assignments table for multi-discipline
tickets, and backfill it from existing tickets.

Same idempotent approach as the other migrate_add_*.py scripts: no
Flask-Migrate/Alembic is set up in this project, so this is a standalone
script for evolving an EXISTING Postgres database without touching any
other tables or rows unnecessarily. Safe to run more than once.

Adds a new table:
    ticket_assignments
        id              SERIAL PRIMARY KEY
        ticket_id       INTEGER NOT NULL REFERENCES tickets(id)
        technician_id   INTEGER REFERENCES technicians(id)  (nullable - no
                         available technician for that specialty yet)
        specialty       VARCHAR(50) NOT NULL
        reasoning       TEXT

One row per (ticket, required specialty). A single-discipline ticket gets
exactly one row, mirroring the existing tickets.assigned_to /
assignment_reasoning columns (which are left in place unchanged, still
used as the "primary" specialty's assignment for backward compatibility).
A multi-discipline ticket ("the ceiling collapsed" -> carpentry +
electrical + plumbing) gets one row per specialty.

Backfill: every existing ticket that has a category but no
ticket_assignments row yet gets exactly one row created from its current
tickets.category / assigned_to / assignment_reasoning, so old and new
tickets look the same in the app's "assignments" view. The backfill
INSERT is itself idempotent - it only targets tickets with zero existing
rows, so re-running this script after new tickets/assignments have been
created is a safe no-op for them.

Usage:
    # Point at the target Postgres database (Render's "External Database
    # URL" if running from your own machine; "Internal Database URL" if
    # running from inside Render, e.g. via the service's Shell tab).
    export DATABASE_URL="postgresql://user:password@host:5432/dbname"
    python migrate_add_ticket_assignments.py
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
                    """
                    CREATE TABLE IF NOT EXISTS ticket_assignments (
                        id SERIAL PRIMARY KEY,
                        ticket_id INTEGER NOT NULL REFERENCES tickets(id),
                        technician_id INTEGER REFERENCES technicians(id),
                        specialty VARCHAR(50) NOT NULL,
                        reasoning TEXT
                    );
                    """
                )
                cur.execute(
                    """
                    INSERT INTO ticket_assignments (ticket_id, technician_id, specialty, reasoning)
                    SELECT t.id, t.assigned_to, t.category, t.assignment_reasoning
                    FROM tickets t
                    WHERE t.category IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM ticket_assignments ta WHERE ta.ticket_id = t.id
                      );
                    """
                )
                backfilled = cur.rowcount
        print(f"Done: ticket_assignments table is present, backfilled {backfilled} row(s).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
