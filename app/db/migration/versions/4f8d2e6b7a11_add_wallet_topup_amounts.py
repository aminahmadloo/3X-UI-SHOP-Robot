"""Add preset wallet top-up amounts.

Revision ID: 4f8d2e6b7a11
Revises: dbf2ed0f9dad
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "4f8d2e6b7a11"
down_revision: Union[str, None] = "dbf2ed0f9dad"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wallet_topup_amounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("amount"),
    )

    wallet_amounts = [
        {"amount": 100_000, "is_active": True, "sort_order": 1},
        {"amount": 200_000, "is_active": True, "sort_order": 2},
        {"amount": 500_000, "is_active": True, "sort_order": 3},
        {"amount": 1_000_000, "is_active": True, "sort_order": 4},
        {"amount": 2_000_000, "is_active": True, "sort_order": 5},
    ]
    op.bulk_insert(
        sa.table(
            "wallet_topup_amounts",
            sa.column("amount", sa.Integer()),
            sa.column("is_active", sa.Boolean()),
            sa.column("sort_order", sa.Integer()),
        ),
        wallet_amounts,
    )


def downgrade() -> None:
    op.drop_table("wallet_topup_amounts")
