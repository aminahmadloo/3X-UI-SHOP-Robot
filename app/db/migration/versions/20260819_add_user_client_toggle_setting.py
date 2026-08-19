"""add admin-controlled user client toggle setting

Revision ID: 20260819_add_user_client_toggle
Revises: merge_after_subscription_settings
Create Date: 2026-08-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260819_add_user_client_toggle"
down_revision: Union[str, None] = "merge_after_subscription_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscription_settings",
        sa.Column(
            "allow_user_client_toggle",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("subscription_settings", "allow_user_client_toggle")
