"""add_depreciation_analyses_table

Revision ID: 95140f9df38d
Revises: 3e5834727c0b
Create Date: 2026-03-15 06:51:40.198288

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '95140f9df38d'
down_revision: Union[str, Sequence[str], None] = '3e5834727c0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'depreciation_analyses',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('client_id', sa.Uuid(), nullable=True),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('fy', sa.String(length=10), nullable=False),
        sa.Column('tax_rate', sa.Float(), nullable=True, default=0.25),
        sa.Column('status', sa.String(length=20), nullable=True, default='processing'),
        sa.Column('result_json', sa.JSON(), nullable=True),
        sa.Column('total_assets', sa.Integer(), nullable=True, default=0),
        sa.Column('total_cost', sa.Float(), nullable=True, default=0.0),
        sa.Column('it_act_depreciation', sa.Float(), nullable=True, default=0.0),
        sa.Column('ca_depreciation', sa.Float(), nullable=True, default=0.0),
        sa.Column('timing_difference', sa.Float(), nullable=True, default=0.0),
        sa.Column('deferred_tax_amount', sa.Float(), nullable=True, default=0.0),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('depreciation_analyses')
