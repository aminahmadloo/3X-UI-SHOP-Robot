"""document variables for channel content templates

Revision ID: 20260904_template_vars
Revises: 20260904_channel_v2
Create Date: 2026-09-04
"""
import json

from alembic import op
import sqlalchemy as sa

revision = "20260904_template_vars"
down_revision = "20260904_channel_v2"
branch_labels = None
depends_on = None


def _variable(key, label, description, example, required=True):
    return {"key": key, "label": label, "description": description, "example": example, "required": required}


def upgrade() -> None:
    op.add_column("channel_content_templates", sa.Column("purpose", sa.Text(), nullable=True))
    op.add_column("channel_content_templates", sa.Column("variable_definitions_json", sa.Text(), nullable=False, server_default="[]"))
    templates = {
        "special_offer": ("🔥 فروش ویژه", "برای معرفی تخفیف و پیشنهاد فروش", [_variable("service_name", "نام سرویس", "نام سرویس VPN که ارائه می‌شود.", "سرویس طلایی"), _variable("volume", "حجم", "حجم ترافیک سرویس.", "100 گیگ"), _variable("duration", "مدت", "مدت اعتبار سرویس.", "30 روز"), _variable("price", "قیمت", "قیمت نهایی پیشنهاد.", "100 هزار تومان"), _variable("old_price", "قیمت قبل", "قیمت پیش از تخفیف.", "150 هزار تومان", False), _variable("discount", "درصد تخفیف", "میزان تخفیف یا متن تخفیف.", "30٪"), _variable("buy_link", "لینک خرید", "لینک مستقیم خرید سرویس.", "https://example.com/buy"), _variable("support_link", "لینک پشتیبانی", "لینک تماس با پشتیبانی.", "https://t.me/support", False)]),
        "server_notice": ("⚡ اطلاعیه سرور", "برای اطلاع‌رسانی وضعیت یا تغییرات سرور", [_variable("service_name", "عنوان اطلاعیه", "خلاصه وضعیت یا موضوع اطلاعیه.", "به‌روزرسانی سرور آلمان"), _variable("support_link", "لینک پشتیبانی", "لینک تماس با پشتیبانی.", "https://t.me/support")]),
        "maintenance": ("🛠 قطعی و تعمیرات", "برای اعلام تعمیرات برنامه‌ریزی‌شده", [_variable("service_name", "سرویس یا سرور", "سرویسی که تعمیرات آن انجام می‌شود.", "سرور آلمان"), _variable("duration", "مدت تقریبی", "زمان تقریبی تعمیرات.", "30 دقیقه"), _variable("support_link", "لینک پشتیبانی", "لینک تماس با پشتیبانی.", "https://t.me/support")]),
        "referral": ("🎯 معرفی دوستان", "برای دعوت کاربران به معرفی دوستان", [_variable("discount", "متن جایزه", "توضیح جایزه یا تخفیف معرفی دوستان.", "20٪ تخفیف برای هر دعوت"), _variable("buy_link", "لینک دعوت", "لینک معرفی یا خرید.", "https://example.com/invite")]),
        "renewal": ("🔄 تمدید سرویس", "برای یادآوری تمدید سرویس کاربران", [_variable("service_name", "نام سرویس", "نام سرویس قابل تمدید.", "VIP 100GB"), _variable("volume", "حجم", "حجم سرویس.", "100 گیگ"), _variable("duration", "مدت", "مدت اعتبار پس از تمدید.", "30 روز"), _variable("price", "قیمت", "هزینه تمدید.", "100 هزار تومان"), _variable("buy_link", "لینک تمدید", "لینک مستقیم تمدید سرویس.", "https://example.com/renew")]),
        "custom": ("✏️ سفارشی", "برای نوشتن یک پیام کوتاه و آزاد", [_variable("service_name", "متن پست", "متن دلخواه پست.", "پیام جدید ما")]),
    }
    template_table = sa.table("channel_content_templates", sa.column("slug", sa.String()), sa.column("title", sa.String()), sa.column("purpose", sa.Text()), sa.column("variable_definitions_json", sa.Text()))
    for slug, (title, purpose, definitions) in templates.items():
        op.execute(template_table.update().where(template_table.c.slug == slug).values(title=title, purpose=purpose, variable_definitions_json=json.dumps(definitions, ensure_ascii=False)))


def downgrade() -> None:
    with op.batch_alter_table("channel_content_templates") as batch_op:
        batch_op.drop_column("variable_definitions_json")
        batch_op.drop_column("purpose")
