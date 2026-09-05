"""add dynamic first and repeat referral reward rates

Revision ID: 20260905_referral_dual_rates
Revises: 20260905_channel_campaigns
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

revision = "20260905_referral_dual_rates"
down_revision = "20260905_channel_campaigns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "referral_settings",
        sa.Column("repeat_reward_percent", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE referral_settings SET repeat_reward_percent = 5 "
        "WHERE repeat_reward_percent IS NULL"
    )
    with op.batch_alter_table("referral_settings") as batch_op:
        batch_op.alter_column(
            "repeat_reward_percent",
            existing_type=sa.Integer(),
            nullable=False,
            server_default="5",
        )


def downgrade() -> None:
    with op.batch_alter_table("referral_settings") as batch_op:
        batch_op.drop_column("repeat_reward_percent")
