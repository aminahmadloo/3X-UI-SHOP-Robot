"""add ordered multi-card card-to-card settings

Revision ID: 20260828_multi_card_settings
Revises: 20260827_support_tickets
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260828_multi_card_settings"
down_revision: str | None = "20260827_support_tickets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "card_settings",
        sa.Column("bank_name", sa.String(length=100), nullable=False, server_default=""),
    )
    op.add_column(
        "card_settings",
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="1"),
    )
    op.alter_column("card_settings", "id", existing_type=sa.Integer(), autoincrement=True)

    op.execute(
        sa.text(
            "UPDATE card_settings SET display_order = 1 WHERE display_order IS NULL OR display_order = 0"
        )
    )

    op.alter_column("card_settings", "bank_name", server_default=None)
    op.alter_column("card_settings", "display_order", server_default=None)


def downgrade() -> None:
    op.drop_column("card_settings", "display_order")
    op.drop_column("card_settings", "bank_name")
