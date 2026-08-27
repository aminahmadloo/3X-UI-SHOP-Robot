"""add gift promocode expiry

Revision ID: 20260827_gift_code_expiry
Revises: 20260827_gift_service_metadata
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260827_gift_code_expiry"
down_revision: str | None = "20260827_gift_service_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "promocodes",
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("promocodes", "expires_at")
