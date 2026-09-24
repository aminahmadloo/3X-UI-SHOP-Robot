"""add reusable test account eligibility controls

Revision ID: 20260924_test_account_reuse_controls
Revises: 20260920_ai_content_production
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = "20260924_test_account_reuse_controls"
down_revision = "20260920_ai_content_production"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "test_account_settings",
        sa.Column(
            "reuse_after_days",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "test_account_settings",
        sa.Column(
            "reset_at",
            sa.DateTime(),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "trial_reset_at",
            sa.DateTime(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "trial_reset_at")
    op.drop_column("test_account_settings", "reset_at")
    op.drop_column("test_account_settings", "reuse_after_days")
