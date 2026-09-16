"""Add tickets.customer_phone.

Mirrors the former migrate_add_customer_phone.py.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tickets', sa.Column('customer_phone', sa.String(length=30), nullable=True))


def downgrade():
    op.drop_column('tickets', 'customer_phone')
