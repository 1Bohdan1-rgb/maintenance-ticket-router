"""Initial schema: technicians and tickets tables.

Reconstructs the schema as it existed before any migrate_add_*.py script
ever ran - originally created via db.create_all() on the first deploy,
with no migration history at all. Matches models.py as of the project's
first commit (96435d1), plus tickets.urgency_reason - added to models.py
one commit later (5f44499, alongside technicians.email/phone) but, unlike
those two, never got its own migrate_add_*.py script. Prod's tickets table
already has it (confirmed live), so it's folded in here rather than
invented a gap that was never actually patched.

Revision ID: 0001
Revises:
Create Date: 2026-09-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'technicians',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('specialty', sa.String(length=50), nullable=False),
        sa.Column('available', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'tickets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('priority', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('customer_email', sa.String(length=255), nullable=True),
        sa.Column('urgency_reason', sa.Text(), nullable=True),
        sa.Column('assigned_to', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['assigned_to'], ['technicians.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('tickets')
    op.drop_table('technicians')
