"""add channel management settings templates campaigns

Revision ID: 20260904_channel_extras
Revises: 08cd9dfd396b
"""

from alembic import op
import sqlalchemy as sa

revision = "20260904_channel_extras"
down_revision = "08cd9dfd396b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("template_type", sa.String(length=32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_channel_templates_template_type", "channel_templates", ["template_type"])
    op.create_index("ix_channel_templates_is_active", "channel_templates", ["is_active"])

    op.create_table(
        "channel_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("channel_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("backup_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("auto_signature", sa.String(length=255), nullable=True),
        sa.Column("default_buttons_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("auto_publish", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("admin_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["channel_id"], ["advertising_channels.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_channel_settings_channel_id", "channel_settings", ["channel_id"])

    op.create_table(
        "channel_referral_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("invite_id", sa.Integer(), nullable=False),
        sa.Column("reward_enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["invite_id"], ["invites.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("invite_id", name="uq_channel_referral_campaign_invite"),
    )
    op.create_index("ix_channel_referral_campaigns_invite_id", "channel_referral_campaigns", ["invite_id"])

    templates = sa.table(
        "channel_templates",
        sa.column("name", sa.String()),
        sa.column("template_type", sa.String()),
        sa.column("body", sa.Text()),
    )
    op.bulk_insert(
        templates,
        [
            {"name": "فروش ویژه", "template_type": "special_offer", "body": "🔥 فروش ویژه ToonelVPN\n\n📦 سرویس: {service_name}\n💾 حجم: {volume}\n⏳ مدت: {duration}\n💰 قیمت: {price}\n\n👇 خرید: {buy_link}"},
            {"name": "سرور جدید", "template_type": "server_new", "body": "🆕 سرور جدید ToonelVPN\n\n🌍 سرور: {service_name}\n🔗 اتصال: {buy_link}\n\n💬 پشتیبانی: {support_link}"},
            {"name": "قطعی و تعمیرات", "template_type": "maintenance", "body": "⚡ اطلاعیه تعمیرات\n\n🔧 سرویس: {service_name}\n⏳ مدت: {duration}\n\n💬 پشتیبانی: {support_link}"},
            {"name": "معرفی دوستان", "template_type": "referral", "body": "🎁 معرفی به دوستان\n\nبا لینک اختصاصی خود دوستانت را دعوت کن:\n{buy_link}\n\n💬 پشتیبانی: {support_link}"},
            {"name": "تمدید سرویس", "template_type": "renewal", "body": "🔄 تمدید سرویس\n\n📦 سرویس: {service_name}\n💾 حجم: {volume}\n⏳ مدت: {duration}\n💰 قیمت: {price}\n\n👇 تمدید: {buy_link}"},
            {"name": "قالب سفارشی", "template_type": "custom", "body": "{service_name}\n{volume}\n{duration}\n{price}\n{buy_link}\n{support_link}"},
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_channel_referral_campaigns_invite_id", table_name="channel_referral_campaigns")
    op.drop_table("channel_referral_campaigns")
    op.drop_index("ix_channel_settings_channel_id", table_name="channel_settings")
    op.drop_table("channel_settings")
    op.drop_index("ix_channel_templates_is_active", table_name="channel_templates")
    op.drop_index("ix_channel_templates_template_type", table_name="channel_templates")
    op.drop_table("channel_templates")
