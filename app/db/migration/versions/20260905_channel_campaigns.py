"""add channel campaign manager and analytics

Revision ID: 20260905_channel_campaigns
Revises: 20260904_template_vars
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

revision = "20260905_channel_campaigns"
down_revision = "20260904_template_vars"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(96), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_type", sa.String(20), nullable=False, server_default="referral"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("start_date", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("end_date", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("slug", name="uq_channel_campaign_slug"),
    )
    op.create_index("ix_channel_campaigns_slug", "channel_campaigns", ["slug"])
    op.create_index("ix_channel_campaigns_channel_id", "channel_campaigns", ["channel_id"])
    op.create_index("ix_channel_campaigns_campaign_type", "channel_campaigns", ["campaign_type"])
    op.create_index("ix_channel_campaigns_status", "channel_campaigns", ["status"])
    op.create_index("ix_channel_campaigns_created_by", "channel_campaigns", ["created_by"])

    op.create_table(
        "channel_campaign_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False, server_default="campaign"),
        sa.Column("joined_channel", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("started_bot", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("converted_to_customer", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["campaign_id"], ["channel_campaigns.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("campaign_id", "telegram_user_id", name="uq_campaign_member_user"),
    )
    op.create_index("ix_campaign_members_campaign_id", "channel_campaign_members", ["campaign_id"])
    op.create_index("ix_campaign_members_telegram_user_id", "channel_campaign_members", ["telegram_user_id"])
    op.create_index("ix_campaign_members_converted", "channel_campaign_members", ["converted_to_customer"])
    op.create_index("ix_campaign_members_created_at", "channel_campaign_members", ["created_at"])

    op.create_table(
        "channel_member_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("snapshot_date", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("channel_id", "snapshot_date", name="uq_channel_member_snapshot_date"),
    )
    op.create_index("ix_channel_member_snapshots_channel_id", "channel_member_snapshots", ["channel_id"])
    op.create_index("ix_channel_member_snapshots_snapshot_date", "channel_member_snapshots", ["snapshot_date"])

    op.create_table(
        "campaign_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("source", sa.String(64), nullable=True),
        sa.Column("referrer_id", sa.BigInteger(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["campaign_id"], ["channel_campaigns.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("campaign_id", "telegram_user_id", "event_type", name="uq_campaign_event_user_type"),
    )
    op.create_index("ix_campaign_events_campaign_id", "campaign_events", ["campaign_id"])
    op.create_index("ix_campaign_events_telegram_user_id", "campaign_events", ["telegram_user_id"])
    op.create_index("ix_campaign_events_event_type", "campaign_events", ["event_type"])
    op.create_index("ix_campaign_events_source", "campaign_events", ["source"])
    op.create_index("ix_campaign_events_referrer_id", "campaign_events", ["referrer_id"])
    op.create_index("ix_campaign_events_created_at", "campaign_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("campaign_events")
    op.drop_table("channel_member_snapshots")
    op.drop_table("channel_campaign_members")
    op.drop_table("channel_campaigns")
