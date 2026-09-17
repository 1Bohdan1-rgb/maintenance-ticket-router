"""Add tickets.severity and tickets.severity_reason.

AI-assessed scale of physical damage/disrepair (1-5), independent of
priority - see ai_classifier.py's severity rules and
_SEVERITY_PRIORITY_FLOOR.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-18

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tickets', sa.Column('severity', sa.Integer(), nullable=True))
    op.add_column('tickets', sa.Column('severity_reason', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('tickets', 'severity_reason')
    op.drop_column('tickets', 'severity')
