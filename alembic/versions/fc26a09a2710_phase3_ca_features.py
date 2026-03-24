"""phase3_ca_features

Revision ID: fc26a09a2710
Revises: 2aabb68b9074
Create Date: 2026-03-08 08:32:36.776032

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fc26a09a2710'
down_revision: Union[str, Sequence[str], None] = '2aabb68b9074'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    """Check if a table already exists (dialect-aware: SQLite + PostgreSQL)."""
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect == "sqlite":
        result = conn.execute(
            sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
            {"name": table_name},
        )
    else:
        result = conn.execute(
            sa.text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name=:name AND table_schema='public'"
            ),
            {"name": table_name},
        )
    return result.fetchone() is not None


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table (dialect-aware: SQLite + PostgreSQL)."""
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect == "sqlite":
        result = conn.execute(sa.text(f"PRAGMA table_info({table_name})"))
        columns = [row[1] for row in result.fetchall()]
    else:
        result = conn.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name=:table AND column_name=:col"
            ),
            {"table": table_name, "col": column_name},
        )
        columns = [row[0] for row in result.fetchall()]
    return column_name in columns


def upgrade() -> None:
    """Upgrade schema — Phase 3 CA features."""

    if not _table_exists('clients'):
        op.create_table(
            'clients',
            sa.Column('id', sa.Uuid(), nullable=False),
            sa.Column('ca_user_id', sa.Uuid(), nullable=False),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('gstin', sa.String(length=15), nullable=True),
            sa.Column('email', sa.String(length=255), nullable=True),
            sa.Column('phone', sa.String(length=50), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['ca_user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )

    if not _table_exists('client_documents'):
        op.create_table(
            'client_documents',
            sa.Column('id', sa.Uuid(), nullable=False),
            sa.Column('client_id', sa.Uuid(), nullable=False),
            sa.Column('audit_job_id', sa.Uuid(), nullable=False),
            sa.Column('document_name', sa.String(length=255), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['audit_job_id'], ['audit_jobs.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )

    if not _table_exists('tax_deadlines'):
        op.create_table(
            'tax_deadlines',
            sa.Column('id', sa.Uuid(), nullable=False),
            sa.Column('title', sa.String(length=255), nullable=False),
            sa.Column('due_date', sa.Date(), nullable=False),
            sa.Column('category', sa.String(length=50), nullable=False),
            sa.Column('description', sa.String(length=500), nullable=True),
            sa.Column('is_system', sa.Boolean(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_tax_deadlines_due_date', 'tax_deadlines', ['due_date'])

    if not _table_exists('user_reminders'):
        op.create_table(
            'user_reminders',
            sa.Column('id', sa.Uuid(), nullable=False),
            sa.Column('user_id', sa.Uuid(), nullable=False),
            sa.Column('deadline_id', sa.Uuid(), nullable=False),
            sa.Column('remind_days_before', sa.Integer(), nullable=False),
            sa.Column('channel', sa.String(length=50), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['deadline_id'], ['tax_deadlines.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )

    # Add client_id FK to audit_jobs
    if not _column_exists('audit_jobs', 'client_id'):
        op.add_column('audit_jobs', sa.Column('client_id', sa.Uuid(), nullable=True))
        with op.batch_alter_table('audit_jobs') as batch_op:
            batch_op.create_foreign_key(
                'fk_audit_jobs_client_id', 'clients', ['client_id'], ['id'], ondelete='SET NULL'
            )


def downgrade() -> None:
    """Downgrade schema — remove Phase 3 CA features."""
    if _column_exists('audit_jobs', 'client_id'):
        with op.batch_alter_table('audit_jobs') as batch_op:
            batch_op.drop_constraint('fk_audit_jobs_client_id', type_='foreignkey')
        op.drop_column('audit_jobs', 'client_id')

    if _table_exists('user_reminders'):
        op.drop_table('user_reminders')
    if _table_exists('tax_deadlines'):
        op.drop_index('ix_tax_deadlines_due_date', table_name='tax_deadlines')
        op.drop_table('tax_deadlines')
    if _table_exists('client_documents'):
        op.drop_table('client_documents')
    if _table_exists('clients'):
        op.drop_table('clients')
