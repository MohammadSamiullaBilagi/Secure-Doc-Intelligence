"""add_compliance_metrics_to_audit_jobs

Revision ID: d9e435cd8173
Revises: 6b6b549fd676
Create Date: 2026-03-20 20:39:54.851547

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9e435cd8173'
down_revision: Union[str, Sequence[str], None] = '6b6b549fd676'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add denormalized compliance metrics to audit_jobs for dashboard queries."""
    op.add_column('audit_jobs', sa.Column('blueprint_name', sa.String(length=255), nullable=True))
    op.add_column('audit_jobs', sa.Column('compliance_score', sa.Float(), nullable=True))
    op.add_column('audit_jobs', sa.Column('open_violations', sa.Integer(), server_default='0', nullable=False))
    op.add_column('audit_jobs', sa.Column('total_financial_exposure', sa.Float(), server_default='0', nullable=False))


def downgrade() -> None:
    """Remove compliance metric columns from audit_jobs."""
    op.drop_column('audit_jobs', 'total_financial_exposure')
    op.drop_column('audit_jobs', 'open_violations')
    op.drop_column('audit_jobs', 'compliance_score')
    op.drop_column('audit_jobs', 'blueprint_name')
