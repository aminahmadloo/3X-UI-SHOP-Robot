"""add channel management v2 tables and analytics

Revision ID: 20260904_channel_v2
Revises: 08cd9dfd396b
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa

revision = "20260904_channel_v2"
down_revision = "08cd9dfd396b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("channel_settings", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("primary_channel_id", sa.Integer(), nullable=True), sa.Column("backup_channel_id", sa.Integer(), nullable=True), sa.Column("signature", sa.Text(), nullable=True), sa.Column("default_buttons_json", sa.Text(), nullable=False, server_default="[]"), sa.Column("auto_publish_enabled", sa.Boolean(), nullable=False, server_default="0"), sa.Column("admin_ids_json", sa.Text(), nullable=False, server_default="[]"), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()), sa.ForeignKeyConstraint(["primary_channel_id"], ["advertising_channels.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["backup_channel_id"], ["advertising_channels.id"], ondelete="SET NULL"))
    op.create_table("channel_content_templates", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("slug", sa.String(length=64), nullable=False), sa.Column("title", sa.String(length=255), nullable=False), sa.Column("body", sa.Text(), nullable=False), sa.Column("is_system", sa.Boolean(), nullable=False, server_default="0"), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("slug"))
    op.create_index("ix_channel_content_templates_slug", "channel_content_templates", ["slug"])
    op.create_table("channel_content_events", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("content_id", sa.Integer(), nullable=False), sa.Column("event_type", sa.String(length=32), nullable=False), sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()), sa.ForeignKeyConstraint(["content_id"], ["channel_contents.id"], ondelete="CASCADE"))
    op.create_index("ix_channel_content_events_content_id", "channel_content_events", ["content_id"])
    op.create_index("ix_channel_content_events_event_type", "channel_content_events", ["event_type"])
    op.create_index("ix_channel_content_events_created_at", "channel_content_events", ["created_at"])
    templates = [
        ("special_offer", "فروش ویژه", "🔥 <b>{service_name}</b>\n\n📦 حجم: {volume}\n⏳ مدت: {duration}\n💰 قیمت ویژه: <b>{price}</b>\n🎁 تخفیف: {discount}\n\n{buy_link}"),
        ("server_notice", "اطلاعیه سرور", "⚡ <b>اطلاعیه سرور</b>\n\n{service_name}\n\nپشتیبانی: {support_link}"),
        ("maintenance", "قطعی و تعمیرات", "🛠 <b>تعمیرات برنامه‌ریزی‌شده</b>\n\n{service_name}\n⏳ مدت تقریبی: {duration}\n\nپشتیبانی: {support_link}"),
        ("referral", "معرفی دوستان", "🎯 <b>دوستانت را دعوت کن</b>\n\n{discount}\n\n{buy_link}"),
        ("renewal", "تمدید سرویس", "🔄 <b>وقت تمدید سرویس است</b>\n\n{service_name}\n📦 {volume} / {duration}\n💰 {price}\n\n{buy_link}"),
        ("custom", "سفارشی", "{service_name}"),
    ]
    op.bulk_insert(sa.table("channel_content_templates", sa.column("slug", sa.String()), sa.column("title", sa.String()), sa.column("body", sa.Text()), sa.column("is_system", sa.Boolean())), [{"slug": slug, "title": title, "body": body, "is_system": True} for slug, title, body in templates])


def downgrade() -> None:
    op.drop_table("channel_content_events")
    op.drop_table("channel_content_templates")
    op.drop_table("channel_settings")
