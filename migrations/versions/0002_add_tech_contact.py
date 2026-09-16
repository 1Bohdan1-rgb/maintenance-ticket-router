"""Add technicians.email and technicians.phone.

Mirrors the former migrate_add_tech_contact.py.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('technicians', sa.Column('email', sa.String(length=255), nullable=True))
    op.add_column('technicians', sa.Column('phone', sa.String(length=30), nullable=True))


def downgrade():
    op.drop_column('technicians', 'phone')
    op.drop_column('technicians', 'email')
