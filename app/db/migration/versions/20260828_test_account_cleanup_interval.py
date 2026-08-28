"""add test account cleanup interval

Revision ID: 20260828_test_account_cleanup_interval
Revises: 20260828_test_accounts
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260828_test_account_cleanup_interval"
down_revision: str | None = "20260828_test_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "test_account_settings",
        sa.Column(
            "cleanup_interval_hours",
            sa.Integer(),
            nullable=False,
            server_default="12",
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "test_account_settings",
        "cleanup_interval_hours",
    )
