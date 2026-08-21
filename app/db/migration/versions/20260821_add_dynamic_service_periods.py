"""add dynamic service periods

Revision ID: 20260821_dynamic_service_periods
Revises: c91e7f4a2b61
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260821_dynamic_service_periods"
down_revision: str | None = "c91e7f4a2b61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_periods",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("months", sa.Integer(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("service_type", sa.String(length=20), nullable=False),
        sa.Column("traffic_addon_service_type", sa.String(length=30), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("months", name="uq_service_periods_months"),
        sa.UniqueConstraint("service_type", name="uq_service_periods_service_type"),
        sa.UniqueConstraint("traffic_addon_service_type", name="uq_service_periods_traffic_addon_type"),
    )
    op.create_index("ix_service_periods_months", "service_periods", ["months"], unique=True)
    op.create_index("ix_service_periods_service_type", "service_periods", ["service_type"], unique=True)
    op.create_index("ix_service_periods_traffic_addon_service_type", "service_periods", ["traffic_addon_service_type"], unique=True)

    periods = sa.table(
        "service_periods",
        sa.column("name", sa.String()),
        sa.column("months", sa.Integer()),
        sa.column("duration_days", sa.Integer()),
        sa.column("service_type", sa.String()),
        sa.column("traffic_addon_service_type", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("is_archived", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(periods, [
        {"name": "سرویس‌های یکماهه", "months": 1, "duration_days": 30, "service_type": "one_month", "traffic_addon_service_type": "traffic_addon_30", "is_active": True, "is_archived": False, "sort_order": 1},
        {"name": "سرویس‌های سه‌ماهه", "months": 3, "duration_days": 90, "service_type": "three_month", "traffic_addon_service_type": "traffic_addon_90", "is_active": True, "is_archived": False, "sort_order": 3},
    ])


def downgrade() -> None:
    op.drop_index("ix_service_periods_traffic_addon_service_type", table_name="service_periods")
    op.drop_index("ix_service_periods_service_type", table_name="service_periods")
    op.drop_index("ix_service_periods_months", table_name="service_periods")
    op.drop_table("service_periods")
