"""Widen tickets.status from VARCHAR(20) to VARCHAR(40).

The new "pending_technician_response" status (28 chars) doesn't fit in the
original VARCHAR(20) - caught this live: confirm_ticket() started 500ing
on Postgres (StringDataRightTruncation) the moment a real ticket hit that
code path, even though every existing status value happened to fit under
20 chars so nothing caught it locally on SQLite (which doesn't enforce
VARCHAR length at all).

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    # SQLite has no ALTER COLUMN ... TYPE - batch mode recreates the table
    # there and is a no-op wrapper around a plain ALTER on Postgres.
    with op.batch_alter_table('tickets') as batch_op:
        batch_op.alter_column(
            'status',
            existing_type=sa.String(length=20),
            type_=sa.String(length=40),
            existing_nullable=False,
        )


def downgrade():
    with op.batch_alter_table('tickets') as batch_op:
        batch_op.alter_column(
            'status',
            existing_type=sa.String(length=40),
            type_=sa.String(length=20),
            existing_nullable=False,
        )
