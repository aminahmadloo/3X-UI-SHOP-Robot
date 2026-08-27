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

    # Before this migration every code managed by the existing admin
    # "کد هدیه" flow was stored without an explicit gift flag. Preserve all
    # still-unused legacy codes as real 30 GB gift codes so already-issued
    # codes remain usable after the new redemption flow is deployed.
    op.execute(
        sa.text(
            "UPDATE promocodes "
            "SET is_gift = :is_gift, volume_gb = :volume_gb "
            "WHERE is_activated = :is_activated"
        ).bindparams(is_gift=True, volume_gb=30, is_activated=False)
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "is_gift")
    op.drop_column("promocodes", "is_gift")
    op.drop_column("promocodes", "volume_gb")
