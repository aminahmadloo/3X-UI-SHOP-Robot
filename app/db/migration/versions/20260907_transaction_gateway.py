"""add gateway to transactions

Revision ID: 20260907_transaction_gateway
Revises: 20260906_welcome_message_settings
Create Date: 2026-09-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260907_transaction_gateway"
down_revision = "20260906_welcome_message_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("gateway", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transactions", "gateway")
