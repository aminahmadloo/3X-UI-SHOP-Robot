"""add payment gateway settings

Revision ID: 20260826_payment_gateway_settings
Revises: 20260821_seed_default_service_periods
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260826_payment_gateway_settings"
down_revision: str | None = "20260821_seed_default_service_periods"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_gateway_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("zarinpal_payment_base_url", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("zarinpal_payment_base_url_configured", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("payment_gateway_settings")
