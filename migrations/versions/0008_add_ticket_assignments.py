"""Add the ticket_assignments table for multi-discipline tickets, and
backfill it from existing tickets.

Mirrors the former migrate_add_ticket_assignments.py, including its
backfill: every existing ticket with a category but no ticket_assignments
row yet gets exactly one row built from its own
category/assigned_to/assignment_reasoning, so old and new tickets look the
same in the app's "assignments" view. A no-op on a fresh database (no
tickets exist yet at this point in the chain).

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ticket_assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ticket_id', sa.Integer(), nullable=False),
        sa.Column('technician_id', sa.Integer(), nullable=True),
        sa.Column('specialty', sa.String(length=50), nullable=False),
        sa.Column('reasoning', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id']),
        sa.ForeignKeyConstraint(['technician_id'], ['technicians.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO ticket_assignments (ticket_id, technician_id, specialty, reasoning)
            SELECT t.id, t.assigned_to, t.category, t.assignment_reasoning
            FROM tickets t
            WHERE t.category IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM ticket_assignments ta WHERE ta.ticket_id = t.id
              )
            """
        )
    )


def downgrade():
    op.drop_table('ticket_assignments')
