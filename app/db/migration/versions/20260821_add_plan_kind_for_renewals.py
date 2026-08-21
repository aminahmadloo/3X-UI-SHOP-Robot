"""separate renewal plans from purchase plans

Revision ID: 20260821_plan_kind
Revises: 20260821_dynamic_service_periods
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260821_plan_kind"
down_revision: str | None = "20260821_dynamic_service_periods"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "service_purchase_plans",
        sa.Column(
            "plan_kind",
            sa.String(length=20),
            nullable=False,
            server_default="purchase",
        ),
    )
    op.create_index(
        "ix_service_purchase_plans_plan_kind",
        "service_purchase_plans",
        ["plan_kind"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_service_purchase_plans_plan_kind",
        table_name="service_purchase_plans",
    )
    op.drop_column("service_purchase_plans", "plan_kind")
