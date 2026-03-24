"""add_advance_tax_computations_table

Revision ID: 6b6b549fd676
Revises: 95140f9df38d
Create Date: 2026-03-15 11:13:53.602166

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6b6b549fd676'
down_revision: Union[str, Sequence[str], None] = '95140f9df38d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'advance_tax_computations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('client_id', sa.Uuid(), nullable=True),
        sa.Column('fy', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('estimated_tax', sa.Float(), nullable=True),
        sa.Column('total_interest', sa.Float(), nullable=True),
        sa.Column('interest_234a', sa.Float(), nullable=True),
        sa.Column('interest_234b', sa.Float(), nullable=True),
        sa.Column('interest_234c', sa.Float(), nullable=True),
        sa.Column('result_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('advance_tax_computations')
