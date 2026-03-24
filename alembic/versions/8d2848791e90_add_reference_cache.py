"""add_reference_cache

Revision ID: 8d2848791e90
Revises: de789fa6a929
Create Date: 2026-03-10 14:41:36.933777

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8d2848791e90'
down_revision: Union[str, Sequence[str], None] = 'de789fa6a929'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('reference_cache',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('check_id', sa.String(length=50), nullable=False),
    sa.Column('source_name', sa.String(length=200), nullable=False),
    sa.Column('source_url', sa.String(length=500), nullable=True),
    sa.Column('extracted_rules', sa.Text(), nullable=True),
    sa.Column('ttl_days', sa.Integer(), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reference_cache_check_id'), 'reference_cache', ['check_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_reference_cache_check_id'), table_name='reference_cache')
    op.drop_table('reference_cache')
