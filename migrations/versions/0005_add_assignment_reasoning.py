"""Add tickets.assignment_reasoning.

Mirrors the former migrate_add_assignment_reasoning.py.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tickets', sa.Column('assignment_reasoning', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('tickets', 'assignment_reasoning')
