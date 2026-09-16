"""Add tickets.lang, completed_at, client_rating, client_review.

Mirrors the former migrate_add_ticket_completion_fields.py. `lang` keeps
the DB-level default('uk') the original raw-SQL migration used
(`... DEFAULT 'uk'`), even though models.py itself only declares a
Python-side default - matching what actually ran against prod.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'tickets',
        sa.Column('lang', sa.String(length=5), nullable=True, server_default='uk'),
    )
    op.add_column('tickets', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('tickets', sa.Column('client_rating', sa.Integer(), nullable=True))
    op.add_column('tickets', sa.Column('client_review', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('tickets', 'client_review')
    op.drop_column('tickets', 'client_rating')
    op.drop_column('tickets', 'completed_at')
    op.drop_column('tickets', 'lang')
