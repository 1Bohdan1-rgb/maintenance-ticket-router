"""Add ticket_assignments.response_status.

Supports the technician accept/decline flow: tracks whether the assigned
technician has responded once the customer confirms the ticket (see
Ticket.status == "pending_technician_response").

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'ticket_assignments', sa.Column('response_status', sa.String(length=20), nullable=True)
    )


def downgrade():
    op.drop_column('ticket_assignments', 'response_status')
