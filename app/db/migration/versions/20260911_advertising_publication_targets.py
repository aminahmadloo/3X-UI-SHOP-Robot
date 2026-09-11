"""add publication targets to advertising campaigns

Revision ID: 20260911_advertising_publication_targets
Revises: 20260907_transaction_gateway
Create Date: 2026-09-11
"""

from alembic import op
import sqlalchemy as sa


revision = "20260911_advertising_publication_targets"
down_revision = "20260907_transaction_gateway"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "advertising_campaigns",
        sa.Column("publication_targets_json", sa.Text(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("advertising_campaigns", "publication_targets_json")
