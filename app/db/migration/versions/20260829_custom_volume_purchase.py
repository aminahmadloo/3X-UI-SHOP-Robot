"""add per-period custom volume pricing settings

Revision ID: 20260829_custom_volume_purchase
Revises: 20260829_custom_service_button_visibility
"""

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_custom_volume_purchase"
down_revision: str | None = "20260829_custom_service_button_visibility"
branch_labels = None
depends_on = None


def _columns(table: str):
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table)
    }


def upgrade() -> None:
    period_columns = _columns("service_periods")

    if "custom_price_per_gb_toman" not in period_columns:
        op.add_column(
            "service_periods",
            sa.Column(
                "custom_price_per_gb_toman",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    if "custom_min_volume_gb" not in period_columns:
        op.add_column(
            "service_periods",
            sa.Column(
                "custom_min_volume_gb",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    if "custom_max_volume_gb" not in period_columns:
        op.add_column(
            "service_periods",
            sa.Column(
                "custom_max_volume_gb",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    plan_columns = _columns("service_purchase_plans")

    if "is_custom" not in plan_columns:
        op.add_column(
            "service_purchase_plans",
            sa.Column(
                "is_custom",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    plan_columns = _columns("service_purchase_plans")

    if "is_custom" in plan_columns:
        op.drop_column("service_purchase_plans", "is_custom")

    period_columns = _columns("service_periods")

    for name in (
        "custom_max_volume_gb",
        "custom_min_volume_gb",
        "custom_price_per_gb_toman",
    ):
        if name in period_columns:
            op.drop_column("service_periods", name)
