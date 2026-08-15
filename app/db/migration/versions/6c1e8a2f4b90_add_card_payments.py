"""Add card-to-card wallet payment requests.

Revision ID: 6c1e8a2f4b90
Revises: 4f8d2e6b7a11
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "6c1e8a2f4b90"
down_revision: Union[str, None] = "4f8d2e6b7a11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "card_payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_tg_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("receipt_file_id", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("admin_tg_id", sa.Integer(), nullable=True),
        sa.Column("admin_note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_tg_id"], ["users.tg_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_card_payments_status", "card_payments", ["status"])


def downgrade() -> None:
    op.drop_index("ix_card_payments_status", table_name="card_payments")
    op.drop_table("card_payments")
