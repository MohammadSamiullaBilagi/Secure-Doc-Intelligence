"""add_notice_jobs_table

Revision ID: aeffd31b294e
Revises: c7c4b3a32dec
Create Date: 2026-03-09 11:07:25.569353

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aeffd31b294e'
down_revision: Union[str, Sequence[str], None] = 'c7c4b3a32dec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create notice_jobs table only if it doesn't exist
    # (startup create_all may have already created it)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'notice_jobs' not in inspector.get_table_names():
        op.create_table(
            'notice_jobs',
            sa.Column('id', sa.Uuid(), nullable=False),
            sa.Column('user_id', sa.Uuid(), nullable=False),
            sa.Column('client_id', sa.Uuid(), nullable=True),
            sa.Column('notice_type', sa.String(length=50), nullable=False),
            sa.Column('notice_document_name', sa.String(length=255), nullable=False),
            sa.Column('supporting_documents', sa.JSON(), nullable=True),
            sa.Column('status', sa.String(length=50), nullable=False),
            sa.Column('langgraph_thread_id', sa.String(length=255), nullable=True),
            sa.Column('extracted_data', sa.JSON(), nullable=True),
            sa.Column('draft_reply', sa.Text(), nullable=True),
            sa.Column('final_reply', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_notice_jobs_langgraph_thread_id', 'notice_jobs', ['langgraph_thread_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_notice_jobs_langgraph_thread_id', table_name='notice_jobs')
    op.drop_table('notice_jobs')
