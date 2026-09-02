"""Extend advertising campaigns for rich media and publication tracking.

Revision ID: 20260902_advertising_media_tracking
Revises: 20260902_advertising_builder
"""
from alembic import op
import sqlalchemy as sa

revision = "20260902_advertising_media_tracking"
down_revision = "20260902_advertising_builder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("advertising_campaigns", sa.Column("content_type", sa.String(16), nullable=True, server_default="text"))
    op.add_column("advertising_campaigns", sa.Column("media_file_id", sa.Text(), nullable=True))
    op.add_column("advertising_campaigns", sa.Column("show_caption_above_media", sa.Boolean(), nullable=True, server_default="1"))
    op.execute("UPDATE advertising_campaigns SET content_type='text' WHERE content_type IS NULL")
    op.execute("UPDATE advertising_campaigns SET show_caption_above_media=1 WHERE show_caption_above_media IS NULL")
    with op.batch_alter_table("advertising_campaigns") as batch_op:
        batch_op.alter_column("content_type", nullable=False)
        batch_op.alter_column("show_caption_above_media", nullable=False)
    op.create_table(
        "advertising_publications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("advertising_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("advertising_channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("campaign_id", "channel_id", "message_id", name="uq_ad_publication_campaign_channel_message"),
    )
    op.create_index("ix_advertising_publications_campaign_id", "advertising_publications", ["campaign_id"])
    op.create_index("ix_advertising_publications_channel_id", "advertising_publications", ["channel_id"])
    op.create_index("ix_advertising_publications_is_active", "advertising_publications", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_advertising_publications_is_active", table_name="advertising_publications")
    op.drop_index("ix_advertising_publications_channel_id", table_name="advertising_publications")
    op.drop_index("ix_advertising_publications_campaign_id", table_name="advertising_publications")
    op.drop_table("advertising_publications")
    with op.batch_alter_table("advertising_campaigns") as batch_op:
        batch_op.drop_column("show_caption_above_media")
        batch_op.drop_column("media_file_id")
        batch_op.drop_column("content_type")
