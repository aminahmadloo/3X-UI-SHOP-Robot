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
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    columns = {
        column["name"]
        for column in inspector.get_columns("card_settings")
    }

    if "bank_name" not in columns:
        op.add_column(
            "card_settings",
            sa.Column(
                "bank_name",
                sa.String(length=100),
                nullable=False,
                server_default="",
            ),
        )

    if "display_order" not in columns:
        op.add_column(
            "card_settings",
            sa.Column(
                "display_order",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )

    op.execute(
        sa.text(
            """
            UPDATE card_settings
            SET display_order = 1
            WHERE display_order IS NULL OR display_order = 0
            """
        )
    )

    # Remove temporary migration defaults when the columns were newly created.
    # SQLite may not support ALTER COLUMN directly, so only attempt this where
    # the dialect supports it.
    if bind.dialect.name != "sqlite":
        if "bank_name" not in columns:
            op.alter_column(
                "card_settings",
                "bank_name",
                server_default=None,
            )
        if "display_order" not in columns:
            op.alter_column(
                "card_settings",
                "display_order",
                server_default=None,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    columns = {
        column["name"]
        for column in inspector.get_columns("card_settings")
    }

    if "display_order" in columns:
        op.drop_column("card_settings", "display_order")

    if "bank_name" in columns:
        op.drop_column("card_settings", "bank_name")
