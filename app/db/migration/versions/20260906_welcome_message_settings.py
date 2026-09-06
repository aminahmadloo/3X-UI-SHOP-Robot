"""add persistent welcome message settings

Revision ID: 20260906_welcome_message_settings
Revises: 20260906_merge_referral_heads
Create Date: 2026-09-06
"""

from alembic import op
import sqlalchemy as sa

revision = "20260906_welcome_message_settings"
down_revision = "20260906_merge_referral_heads"
branch_labels = None
depends_on = None


DEFAULT_WELCOME_MESSAGE = (
    "🌀 <b>{first_name} عزیز، به ToonelVPN خوش آمدی</b> 🌐\n\n"
    "⚡️ اتصال سریع، پایدار و مطمئن به اینترنت آزاد، با سرویس‌هایی متناسب با نیازت.\n\n"
    "🚀 سرویس‌های متنوع برای استفاده روزمره\n"
    "🌍 سرورهای مختلف برای انتخاب بهتر\n"
    "🛡️ اتصال پایدار و مطمئن\n"
    "💻 سازگار با دستگاه‌های مختلف\n"
    "🔄 خرید، تمدید و مدیریت آسان سرویس\n"
    "──────────────────\n\n"
    "🎁 <b>برای شروع، می‌تونی اکانت تست رو امتحان کنی.</b>\n\n"
    "✨ <b>یکی از گزینه‌های زیر رو انتخاب کن:</b> 👇"
)


def upgrade() -> None:
    op.create_table(
        "welcome_message_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO welcome_message_settings (id, message) VALUES (:id, :message)"
        ).bindparams(id=1, message=DEFAULT_WELCOME_MESSAGE)
    )


def downgrade() -> None:
    op.drop_table("welcome_message_settings")
