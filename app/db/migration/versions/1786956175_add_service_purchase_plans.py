"""add service purchase plans

Revision ID: c91e7f4a2b61
Revises: 4483c2dabc36
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c91e7f4a2b61"
down_revision: str | None = "4483c2dabc36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_purchase_plans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("service_type", sa.String(length=20), nullable=False),
        sa.Column("volume_gb", sa.Integer(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("price_toman", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_service_purchase_plans_service_type",
        "service_purchase_plans",
        ["service_type"],
        unique=False,
    )

    plans = sa.table(
        "service_purchase_plans",
        sa.column("service_type", sa.String()),
        sa.column("volume_gb", sa.Integer()),
        sa.column("duration_days", sa.Integer()),
        sa.column("price_toman", sa.Integer()),
    )

    op.bulk_insert(
        plans,
        [
            # سرویس‌های یک ماهه
            {
                "service_type": "one_month",
                "volume_gb": 20,
                "duration_days": 31,
                "price_toman": 100000,
            },
            {
                "service_type": "one_month",
                "volume_gb": 30,
                "duration_days": 30,
                "price_toman": 140000,
            },
            {
                "service_type": "one_month",
                "volume_gb": 50,
                "duration_days": 30,
                "price_toman": 200000,
            },
            {
                "service_type": "one_month",
                "volume_gb": 100,
                "duration_days": 31,
                "price_toman": 350000,
            },

            # سرویس‌های سه ماهه
            # طبق درخواست: فعلاً همان مقادیر پیش‌فرض
            # ویرایش این مقادیر بعداً از داخل ربات امکان‌پذیر است.
            {
                "service_type": "three_month",
                "volume_gb": 20,
                "duration_days": 31,
                "price_toman": 100000,
            },
            {
                "service_type": "three_month",
                "volume_gb": 30,
                "duration_days": 30,
                "price_toman": 140000,
            },
            {
                "service_type": "three_month",
                "volume_gb": 50,
                "duration_days": 30,
                "price_toman": 200000,
            },
            {
                "service_type": "three_month",
                "volume_gb": 100,
                "duration_days": 31,
                "price_toman": 350000,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_service_purchase_plans_service_type",
        table_name="service_purchase_plans",
    )
    op.drop_table("service_purchase_plans")
