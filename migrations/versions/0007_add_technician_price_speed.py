"""Add technicians.price_tier and technicians.speed_rating.

Mirrors the former migrate_add_technician_price_speed.py.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('technicians', sa.Column('price_tier', sa.String(length=20), nullable=True))
    op.add_column('technicians', sa.Column('speed_rating', sa.String(length=20), nullable=True))


def downgrade():
    op.drop_column('technicians', 'speed_rating')
    op.drop_column('technicians', 'price_tier')
