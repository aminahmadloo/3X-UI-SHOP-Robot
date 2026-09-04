"""add channel content management

Revision ID: 20260904_channel_content
Revises: 20260902_special_offer_campaigns
Create Date: 2026-09-04
"""

from alembic import op
import sqlalchemy as sa

revision = "20260904_channel_content"
down_revision = "20260902_special_offer_campaigns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_contents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False, server_default="پست کانال"),
        sa.Column("content_type", sa.String(length=16), nullable=False, server_default="text"),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("media_file_id", sa.Text(), nullable=True),
        sa.Column("show_caption_above_media", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("buttons_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("poll_question", sa.Text(), nullable=True),
        sa.Column("poll_options_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("poll_is_anonymous", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("poll_allows_multiple", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["channel_id"], ["advertising_channels.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_channel_contents_channel_id", "channel_contents", ["channel_id"])
    op.create_index("ix_channel_contents_status", "channel_contents", ["status"])
    op.create_index("ix_channel_contents_scheduled_at", "channel_contents", ["scheduled_at"])
    op.create_index("ix_channel_contents_telegram_message_id", "channel_contents", ["telegram_message_id"])


def downgrade() -> None:
    op.drop_index("ix_channel_contents_telegram_message_id", table_name="channel_contents")
    op.drop_index("ix_channel_contents_scheduled_at", table_name="channel_contents")
    op.drop_index("ix_channel_contents_status", table_name="channel_contents")
    op.drop_index("ix_channel_contents_channel_id", table_name="channel_contents")
    op.drop_table("channel_contents")
