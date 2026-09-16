"""Add technicians.resume_summary and technicians.resume_uploaded_at.

Mirrors the former migrate_add_resume_fields.py.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('technicians', sa.Column('resume_summary', sa.Text(), nullable=True))
    op.add_column(
        'technicians', sa.Column('resume_uploaded_at', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade():
    op.drop_column('technicians', 'resume_uploaded_at')
    op.drop_column('technicians', 'resume_summary')
