# Maintenance Ticket Router

AI-powered triage and dispatch for building maintenance requests. A client describes a problem (with an optional photo); Claude classifies it, scores its severity, and the system automatically routes it to the right technician — or team, for jobs spanning multiple trades — based on their resume, rating history, and the client's stated priorities.

**Live demo:** [maintenance-ticket-router.onrender.com](https://maintenance-ticket-router.onrender.com)

![Demo: submitting a ticket through AI classification to technician assignment](docs/demo.gif)

> **Screenshot/GIF placeholder** — `docs/demo.gif` doesn't exist yet. Record the flow below and drop it at that path (or swap the line above for a static PNG):
> 1. Open the client form, fill in a description (ideally one that triggers multi-discipline routing, e.g. *"the ceiling collapsed, exposing wiring and a burst pipe"*), optionally attach a photo.
> 2. Submit — capture the result panel showing the AI-assigned category, priority, severity, and technician(s).
> 3. Open `/dashboard/view` and capture the same ticket in the table, showing the severity badge and assignment reasoning tooltip.

## Key Features

- **AI ticket classification** (Claude) — category, priority, and urgency reasoning from the description and an optional photo
- **Severity scoring, independent of priority** — a 1–5 scale of physical damage/disrepair, assessed from the same text + photo evidence; a severe issue automatically escalates priority even when the wording undersells it
- **Resume- and rating-based technician matching** — candidates are weighed by Claude against their resume summary and rating history, biased by the client's stated priority (quality / speed / price)
- **Multi-discipline team assignment** — a single ticket that genuinely needs more than one trade (e.g. a collapsed ceiling exposing wiring and a burst pipe) is split into per-trade assignments, each independently matched, instead of forced into one category
- **Technician accept/decline** — a technician can decline an assignment; the system immediately retries matching for that slot (excluding them) rather than leaving the ticket stuck
- **Gender preference matching** — optional and non-blocking; an unmet preference falls back to normal matching instead of leaving the ticket unassigned
- **Mobile-responsive** throughout — client form, technician dashboard, business dashboard, and admin views

## Tech Stack

| | |
|---|---|
| Backend | Flask, Flask-SQLAlchemy |
| Database | PostgreSQL (Render) in production, SQLite for local dev |
| AI | Claude API (Anthropic) — classification, severity scoring, resume-based technician selection |
| Migrations | Alembic via Flask-Migrate |
| Testing | pytest — 45 tests, Claude API mocked, in-memory SQLite |
| Email | Gmail SMTP, HTML notification template with inline photo embedding |
| Hosting | Render |

## Architecture Notes

**Severity is deliberately separate from client-facing priority.** `priority` answers "how urgently must someone respond" — a gas smell is high-priority even with zero visible damage. `severity` answers "how much physical damage already exists," scored independently from the same text+photo evidence. A severity of 4 or 5 forces a priority floor (`high` / `emergency` respectively) even when the text description alone undersells it, so a serious leak that's only obvious in the photo can't slip through as "medium priority" because the client's wording was neutral.

**Declining an assignment triggers live reassignment, not a dead end.** When a technician declines, the system re-runs matching for that specific specialty immediately — excluding the technician who just declined — and notifies whoever's next. If nobody else is available, the slot falls back to `pending_assignment` instead of silently staying assigned to someone who said no.

**Alembic instead of hand-rolled migration scripts.** The project originally shipped one `migrate_add_*.py` script per schema change, each run manually against the production database. That doesn't scale, has no rollback story, and gives no way to verify that replaying the full history reconstructs the current schema. Alembic (via Flask-Migrate) replaced it with a versioned chain of migrations (`migrations/versions/`) — verified to reproduce the exact current schema on a clean database with zero drift from `models.py`, and to round-trip cleanly (`downgrade base` → `upgrade head`).

## Running Locally

```bash
git clone https://github.com/1Bohdan1-rgb/maintenance-ticket-router.git
cd maintenance-ticket-router
pip install -r requirements.txt

cp .env.example .env
# At minimum, set ANTHROPIC_API_KEY to get real AI classification - the
# app still runs without it (falls back to a default category/priority).
# DATABASE_URL defaults to a local SQLite file; everything else (SMTP,
# ADMIN_TOKEN) degrades gracefully or just gates the admin endpoints.

flask db upgrade   # apply migrations
python app.py      # http://localhost:5000
```

Run the test suite (Claude API is mocked, database is in-memory SQLite — no external services needed):

```bash
pip install -r requirements-dev.txt
pytest
```
