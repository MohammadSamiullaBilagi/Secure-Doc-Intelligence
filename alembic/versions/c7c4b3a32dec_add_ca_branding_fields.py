"""add_ca_branding_fields

Revision ID: c7c4b3a32dec
Revises: fc26a09a2710
Create Date: 2026-03-09 11:06:28.825800

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7c4b3a32dec'
down_revision: Union[str, Sequence[str], None] = 'fc26a09a2710'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('user_preferences', sa.Column('firm_name', sa.String(length=255), nullable=True))
    op.add_column('user_preferences', sa.Column('ca_name', sa.String(length=255), nullable=True))
    op.add_column('user_preferences', sa.Column('icai_membership_number', sa.String(length=50), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_preferences', 'icai_membership_number')
    op.drop_column('user_preferences', 'ca_name')
    op.drop_column('user_preferences', 'firm_name')
