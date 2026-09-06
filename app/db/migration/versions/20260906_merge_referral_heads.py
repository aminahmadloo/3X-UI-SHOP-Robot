"""merge referral share text and customer level heads

Revision ID: 20260906_merge_referral_heads
Revises: 20260905_customer_level_ranges, 20260906_referral_share_text
Create Date: 2026-09-06
"""

revision = "20260906_merge_referral_heads"
down_revision = (
    "20260905_customer_level_ranges",
    "20260906_referral_share_text",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
