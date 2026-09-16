"""Add technicians.gender.

Mirrors the former migrate_add_technician_gender.py.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('technicians', sa.Column('gender', sa.String(length=20), nullable=True))


def downgrade():
    op.drop_column('technicians', 'gender')
