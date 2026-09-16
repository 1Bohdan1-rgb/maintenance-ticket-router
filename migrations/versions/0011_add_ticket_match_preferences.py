"""Add tickets.match_priority and tickets.preferred_gender.

Mirrors the former migrate_add_ticket_match_preferences.py.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tickets', sa.Column('match_priority', sa.String(length=20), nullable=True))
    op.add_column('tickets', sa.Column('preferred_gender', sa.String(length=20), nullable=True))


def downgrade():
    op.drop_column('tickets', 'preferred_gender')
    op.drop_column('tickets', 'match_priority')
