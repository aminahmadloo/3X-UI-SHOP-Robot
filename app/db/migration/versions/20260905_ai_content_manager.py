"""add AI content manager settings

Revision ID: 20260905_ai_content_manager
Revises: 20260905_channel_campaigns
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

revision = "20260905_ai_content_manager"
down_revision = "20260905_channel_campaigns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_content_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("mode", sa.String(16), nullable=False, server_default="approval"),
        sa.Column("model", sa.String(64), nullable=False, server_default="gpt-5.6-luna"),
        sa.Column("topics", sa.Text(), nullable=False, server_default="آموزشی,خبری,تعامل,معرفی قابلیت,فروش ویژه"),
        sa.Column("smart_rules", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("smart_risk_level", sa.String(16), nullable=False, server_default="balanced"),
        sa.Column("posts_per_day", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("auto_schedule", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("ai_content_settings")
