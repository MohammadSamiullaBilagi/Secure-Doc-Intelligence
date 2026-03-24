"""add_gst_reconciliation

Revision ID: a8d8552719f7
Revises: 8d2848791e90
Create Date: 2026-03-14 16:19:14.600862

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8d8552719f7'
down_revision: Union[str, Sequence[str], None] = '8d2848791e90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'gst_reconciliations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('client_id', sa.Uuid(), nullable=True),
        sa.Column('period', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='processing'),
        sa.Column('gstr2b_filename', sa.String(length=255), nullable=True),
        sa.Column('purchase_register_filename', sa.String(length=255), nullable=True),
        sa.Column('result_json', sa.JSON(), nullable=True),
        sa.Column('matched_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('mismatched_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('missing_in_books_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('missing_in_gstr2b_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_itc_available', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('total_itc_at_risk', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('gst_reconciliations')
