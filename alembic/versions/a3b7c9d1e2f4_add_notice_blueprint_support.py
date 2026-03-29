"""add_notice_blueprint_support

Revision ID: a3b7c9d1e2f4
Revises: f7f1d8075e6a
Create Date: 2026-03-29 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3b7c9d1e2f4'
down_revision: Union[str, Sequence[str], None] = 'f7f1d8075e6a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add category to blueprints and notice_blueprint fields to notice_jobs."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Add category column to blueprints table
    if 'blueprints' in inspector.get_table_names():
        existing_cols = [c['name'] for c in inspector.get_columns('blueprints')]
        if 'category' not in existing_cols:
            op.add_column('blueprints', sa.Column(
                'category', sa.String(length=20), nullable=False, server_default='audit'
            ))

    # Add notice_blueprint_id and notice_blueprint_name to notice_jobs
    if 'notice_jobs' in inspector.get_table_names():
        existing_cols = [c['name'] for c in inspector.get_columns('notice_jobs')]
        if 'notice_blueprint_id' not in existing_cols:
            op.add_column('notice_jobs', sa.Column(
                'notice_blueprint_id', sa.Uuid(), nullable=True
            ))
            # SQLite doesn't support adding FK constraints after table creation
            # For PostgreSQL, add the foreign key
            dialect = conn.dialect.name
            if dialect != 'sqlite':
                op.create_foreign_key(
                    'fk_notice_jobs_blueprint_id',
                    'notice_jobs', 'blueprints',
                    ['notice_blueprint_id'], ['id'],
                    ondelete='SET NULL'
                )
        if 'notice_blueprint_name' not in existing_cols:
            op.add_column('notice_jobs', sa.Column(
                'notice_blueprint_name', sa.String(length=255), nullable=True
            ))


def downgrade() -> None:
    """Remove notice blueprint support columns."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'notice_jobs' in inspector.get_table_names():
        existing_cols = [c['name'] for c in inspector.get_columns('notice_jobs')]
        dialect = conn.dialect.name
        if 'notice_blueprint_id' in existing_cols:
            if dialect != 'sqlite':
                op.drop_constraint('fk_notice_jobs_blueprint_id', 'notice_jobs', type_='foreignkey')
            op.drop_column('notice_jobs', 'notice_blueprint_id')
        if 'notice_blueprint_name' in existing_cols:
            op.drop_column('notice_jobs', 'notice_blueprint_name')

    if 'blueprints' in inspector.get_table_names():
        existing_cols = [c['name'] for c in inspector.get_columns('blueprints')]
        if 'category' in existing_cols:
            op.drop_column('blueprints', 'category')
