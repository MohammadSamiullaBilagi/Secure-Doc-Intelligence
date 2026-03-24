"""add_ca_contact_fields_and_reminder_sent_at

Revision ID: de789fa6a929
Revises: aeffd31b294e
Create Date: 2026-03-10 10:06:29.568042

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'de789fa6a929'
down_revision: Union[str, Sequence[str], None] = 'aeffd31b294e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add CA contact fields to user_preferences and sent_at to user_reminders."""
    op.add_column('user_preferences', sa.Column('firm_address', sa.String(length=500), nullable=True))
    op.add_column('user_preferences', sa.Column('firm_phone', sa.String(length=50), nullable=True))
    op.add_column('user_preferences', sa.Column('firm_email', sa.String(length=255), nullable=True))
    op.add_column('user_reminders', sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Remove CA contact fields and sent_at."""
    op.drop_column('user_reminders', 'sent_at')
    op.drop_column('user_preferences', 'firm_email')
    op.drop_column('user_preferences', 'firm_phone')
    op.drop_column('user_preferences', 'firm_address')
