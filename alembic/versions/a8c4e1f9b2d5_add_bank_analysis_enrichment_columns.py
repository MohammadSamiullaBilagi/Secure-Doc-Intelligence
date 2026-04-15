"""add_bank_analysis_enrichment_columns

Adds 4 nullable columns to bank_statement_analyses for enriched output:
- categorized_totals   JSON  — per-category debit/credit/count/pct
- monthly_summary      JSON  — per-month totals + top category
- counterparty_summary JSON  — top counterparties with volume
- compliance_score     INT   — 0-100 weighted score

All nullable; safe to apply on Postgres without a table rewrite.

Revision ID: a8c4e1f9b2d5
Revises: 4bce6d82905a
Create Date: 2026-04-14 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a8c4e1f9b2d5'
down_revision: Union[str, Sequence[str], None] = '4bce6d82905a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'bank_statement_analyses',
        sa.Column('categorized_totals', sa.JSON(), nullable=True),
    )
    op.add_column(
        'bank_statement_analyses',
        sa.Column('monthly_summary', sa.JSON(), nullable=True),
    )
    op.add_column(
        'bank_statement_analyses',
        sa.Column('counterparty_summary', sa.JSON(), nullable=True),
    )
    op.add_column(
        'bank_statement_analyses',
        sa.Column('compliance_score', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('bank_statement_analyses', 'compliance_score')
    op.drop_column('bank_statement_analyses', 'counterparty_summary')
    op.drop_column('bank_statement_analyses', 'monthly_summary')
    op.drop_column('bank_statement_analyses', 'categorized_totals')
