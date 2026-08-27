"""add gift recipient tracking

Revision ID: 20260827_gift_recipient
Revises: 20260827_gift_code_expiry
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260827_gift_recipient"
down_revision: str | None = "20260827_gift_code_expiry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "promocodes",
        sa.Column("recipient_tg_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_promocodes_recipient_tg_id",
        "promocodes",
        ["recipient_tg_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_promocodes_recipient_tg_id", table_name="promocodes")
    op.drop_column("promocodes", "recipient_tg_id")
