"""add customizable referral share text

Revision ID: 20260906_referral_share_text
Revises: 20260905_referral_dual_rates
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa

revision = "20260906_referral_share_text"
down_revision = "20260905_referral_dual_rates"
branch_labels = None
depends_on = None


DEFAULT_SHARE_TEXT = (
    "من به‌تازگی مشتری تونلVPN شدم و از کیفیت سرویس‌هاش واقعاً راضی‌ام. "
    "پینگ عالی، سرعت مناسب و قیمت‌های مقرون‌به‌صرفه از مزیت‌های این سرویسه.\n\n"
    "اگر دوست داشتی تو هم امتحانش کنی، از طریق لینک زیر وارد شو و خریدت رو انجام بده:\n\n"
    "🔗 {referral_link}"
)


def upgrade() -> None:
    op.add_column(
        "referral_settings",
        sa.Column("share_text", sa.Text(), nullable=True),
    )
    op.execute(
        sa.text("UPDATE referral_settings SET share_text = :share_text WHERE share_text IS NULL")
        .bindparams(share_text=DEFAULT_SHARE_TEXT)
    )
    with op.batch_alter_table("referral_settings") as batch_op:
        batch_op.alter_column(
            "share_text",
            existing_type=sa.Text(),
            nullable=False,
            server_default=DEFAULT_SHARE_TEXT,
        )


def downgrade() -> None:
    with op.batch_alter_table("referral_settings") as batch_op:
        batch_op.drop_column("share_text")
