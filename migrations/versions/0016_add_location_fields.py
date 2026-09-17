"""Add customer address/coordinates to tickets, and base location/service
radius/coordinates to technicians.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-18

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tickets', sa.Column('customer_address', sa.String(length=500), nullable=True))
    op.add_column('tickets', sa.Column('customer_lat', sa.Float(), nullable=True))
    op.add_column('tickets', sa.Column('customer_lng', sa.Float(), nullable=True))

    op.add_column('technicians', sa.Column('location_label', sa.String(length=200), nullable=True))
    op.add_column('technicians', sa.Column('lat', sa.Float(), nullable=True))
    op.add_column('technicians', sa.Column('lng', sa.Float(), nullable=True))
    op.add_column('technicians', sa.Column('service_radius_km', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('technicians', 'service_radius_km')
    op.drop_column('technicians', 'lng')
    op.drop_column('technicians', 'lat')
    op.drop_column('technicians', 'location_label')

    op.drop_column('tickets', 'customer_lng')
    op.drop_column('tickets', 'customer_lat')
    op.drop_column('tickets', 'customer_address')
