"""Add is_admin to users and feedbacks table

Revision ID: ff009a3b6dec
Revises: d9e435cd8173
Create Date: 2026-03-23 06:50:56.013482

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff009a3b6dec'
down_revision: Union[str, Sequence[str], None] = 'd9e435cd8173'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # feedbacks table may already exist from SQLite auto-create
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)
    existing = inspector.get_table_names()

    if 'feedbacks' not in existing:
        op.create_table('feedbacks',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('page', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )

    # is_admin column may already exist from SQLite auto-create
    user_cols = [c['name'] for c in inspector.get_columns('users')]
    if 'is_admin' not in user_cols:
        op.add_column('users', sa.Column('is_admin', sa.Boolean(), server_default='0', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'is_admin')
    op.drop_table('feedbacks')
