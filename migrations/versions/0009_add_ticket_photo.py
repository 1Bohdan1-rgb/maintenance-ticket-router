"""Add tickets.photo_data and tickets.photo_content_type.

Mirrors the former migrate_add_ticket_photo.py.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tickets', sa.Column('photo_data', sa.Text(), nullable=True))
    op.add_column('tickets', sa.Column('photo_content_type', sa.String(length=50), nullable=True))


def downgrade():
    op.drop_column('tickets', 'photo_content_type')
    op.drop_column('tickets', 'photo_data')
