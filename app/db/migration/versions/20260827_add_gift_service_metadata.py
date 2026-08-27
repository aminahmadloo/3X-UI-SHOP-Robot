"""add real VPN gift metadata

Revision ID: 20260827_gift_service_metadata
Revises: 20260826_payment_gateway_settings
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260827_gift_service_metadata"
down_revision: str | None = "20260826_payment_gateway_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "promocodes",
        sa.Column("volume_gb", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "promocodes",
        sa.Column("is_gift", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "subscriptions",
        sa.Column("is_gift", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "is_gift")
    op.drop_column("promocodes", "is_gift")
    op.drop_column("promocodes", "volume_gb")
