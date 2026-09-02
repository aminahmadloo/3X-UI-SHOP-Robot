"""add special offer fields to service purchase plans

Revision ID: 20260902_special_offers
Revises: 20260902_advertising_media_tracking
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260902_special_offers"
down_revision: str | None = "20260902_advertising_media_tracking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "service_purchase_plans",
        sa.Column("is_special_offer", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "service_purchase_plans",
        sa.Column("special_offer_price_toman", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_service_purchase_plans_is_special_offer",
        "service_purchase_plans",
        ["is_special_offer"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_service_purchase_plans_is_special_offer",
        table_name="service_purchase_plans",
    )
    op.drop_column("service_purchase_plans", "special_offer_price_toman")
    op.drop_column("service_purchase_plans", "is_special_offer")
