"""add_bank_statement_analysis

Revision ID: 9715884db14a
Revises: a8d8552719f7
Create Date: 2026-03-14 23:11:56.876763

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9715884db14a'
down_revision: Union[str, Sequence[str], None] = 'a8d8552719f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'bank_statement_analyses',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('client_id', sa.Uuid(), nullable=True),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('period_from', sa.Date(), nullable=True),
        sa.Column('period_to', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='processing'),
        sa.Column('result_json', sa.JSON(), nullable=True),
        sa.Column('total_transactions', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_debit', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('total_credit', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('flags_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('high_flags', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('bank_statement_analyses')
