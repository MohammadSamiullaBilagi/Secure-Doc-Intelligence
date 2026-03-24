"""add_gstr9_reconciliations_table

Revision ID: 3e5834727c0b
Revises: 72907553eafb
Create Date: 2026-03-15 06:26:23.737923

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3e5834727c0b'
down_revision: Union[str, Sequence[str], None] = '72907553eafb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'gstr9_reconciliations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('client_id', sa.Uuid(), nullable=True),
        sa.Column('gstin', sa.String(length=15), nullable=False),
        sa.Column('fy', sa.String(length=7), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='processing'),
        sa.Column('gstr1_turnover', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('gstr3b_turnover', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('books_turnover', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('gstr1_tax_paid', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('gstr3b_tax_paid', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('discrepancy_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('result_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('gstr9_reconciliations')
