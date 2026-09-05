"""add dynamic customer level point ranges

Revision ID: 20260905_customer_level_ranges
Revises: 20260905_referral_dual_rates
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

revision = "20260905_customer_level_ranges"
down_revision = "20260905_referral_dual_rates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = (
        ("base_min_points", 0),
        ("base_max_points", 4),
        ("bronze_min_points", 5),
        ("bronze_max_points", 10),
        ("silver_min_points", 11),
        ("silver_max_points", 20),
        ("gold_min_points", 21),
    )
    for name, default in columns:
        op.add_column(
            "customer_level_settings",
            sa.Column(name, sa.Integer(), nullable=True, server_default=str(default)),
        )

    op.add_column(
        "customer_level_settings",
        sa.Column("gold_max_points", sa.Integer(), nullable=True),
    )

    with op.batch_alter_table("customer_level_settings") as batch_op:
        for name, _ in columns:
            batch_op.alter_column(
                name,
                existing_type=sa.Integer(),
                nullable=False,
            )


def downgrade() -> None:
    with op.batch_alter_table("customer_level_settings") as batch_op:
        batch_op.drop_column("gold_max_points")
        batch_op.drop_column("gold_min_points")
        batch_op.drop_column("silver_max_points")
        batch_op.drop_column("silver_min_points")
        batch_op.drop_column("bronze_max_points")
        batch_op.drop_column("bronze_min_points")
        batch_op.drop_column("base_max_points")
        batch_op.drop_column("base_min_points")
