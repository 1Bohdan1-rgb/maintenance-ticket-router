"""Add ticket_assignments.decline_count.

Persists a per-slot decline counter across reassignment, so analytics can
compute an accurate decline rate - response_status alone gets overwritten
back to "pending" on a successful reassignment and loses the fact that a
decline ever happened.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-18

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'ticket_assignments',
        sa.Column('decline_count', sa.Integer(), nullable=False, server_default='0'),
    )
    # Drop the server_default after backfilling existing rows - models.py
    # only declares a Python-side default, matching the rest of the app's
    # convention (see 0004's `lang` column for the one deliberate exception).
    with op.batch_alter_table('ticket_assignments') as batch_op:
        batch_op.alter_column('decline_count', server_default=None)


def downgrade():
    op.drop_column('ticket_assignments', 'decline_count')
