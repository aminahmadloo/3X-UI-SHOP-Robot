"""add Telegram advertising channels, campaigns and tracking events

Revision ID: 20260902_add_telegram_advertising
Revises: 20260902_remove_legacy_payment_gateways
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260902_add_telegram_advertising"
down_revision: str | None = "20260902_remove_legacy_payment_gateways"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "advertising_channels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_advertising_channels_chat_id", "advertising_channels", ["chat_id"], unique=True)
    op.create_index("ix_advertising_channels_is_active", "advertising_channels", ["is_active"])

    op.create_table(
        "advertising_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("bot_username", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_advertising_campaigns_is_active", "advertising_campaigns", ["is_active"])

    op.create_table(
        "advertising_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("advertising_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tg_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=True),
        sa.Column("plan_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("campaign_id", "tg_id", "event_type", name="uq_ad_event_campaign_user_type"),
    )
    op.create_index("ix_advertising_events_campaign_id", "advertising_events", ["campaign_id"])
    op.create_index("ix_advertising_events_tg_id", "advertising_events", ["tg_id"])
    op.create_index("ix_advertising_events_event_type", "advertising_events", ["event_type"])
    op.create_index("ix_advertising_events_channel_id", "advertising_events", ["channel_id"])
    op.create_index("ix_advertising_events_plan_id", "advertising_events", ["plan_id"])
    op.create_index("ix_advertising_events_created_at", "advertising_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("advertising_events")
    op.drop_table("advertising_campaigns")
    op.drop_table("advertising_channels")
