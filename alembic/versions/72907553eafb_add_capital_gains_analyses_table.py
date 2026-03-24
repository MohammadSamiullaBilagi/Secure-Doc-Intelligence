"""add_capital_gains_analyses_table

Revision ID: 72907553eafb
Revises: 9715884db14a
Create Date: 2026-03-14 23:43:01.365354

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '72907553eafb'
down_revision: Union[str, Sequence[str], None] = '9715884db14a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Table is created by Base.metadata.create_all on startup.
    # This migration exists to keep Alembic history in sync.
    op.create_table(
        'capital_gains_analyses',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('client_id', sa.Uuid(), nullable=True),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('fy', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('result_json', sa.JSON(), nullable=True),
        sa.Column('total_transactions', sa.Integer(), nullable=True),
        sa.Column('total_gain_loss', sa.Float(), nullable=True),
        sa.Column('total_estimated_tax', sa.Float(), nullable=True),
        sa.Column('ltcg_equity_taxable', sa.Float(), nullable=True),
        sa.Column('stcg_equity_net', sa.Float(), nullable=True),
        sa.Column('exemption_112a', sa.Float(), nullable=True),
        sa.Column('reconciliation_warnings', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('capital_gains_analyses')
