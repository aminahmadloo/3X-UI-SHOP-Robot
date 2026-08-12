"""Add wallet balance and transaction ledger tables.

Revision ID: 7b9c4d1e2f30
Revises: 4f8d2e6b7a11
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7b9c4d1e2f30"
down_revision: Union[str, None] = "4f8d2e6b7a11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wallets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_tg_id", sa.Integer(), nullable=False),
        sa.Column("balance", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["user_tg_id"], ["users.tg_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_tg_id"),
    )

    op.create_table(
        "wallet_transactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_tg_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("transaction_type", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("reference_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_tg_id"], ["users.tg_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference_id"),
    )

    op.create_index(
        "ix_wallet_transactions_user_tg_id",
        "wallet_transactions",
        ["user_tg_id"],
        unique=False,
    )

    op.execute(
        sa.text(
            "INSERT INTO wallets (user_tg_id, balance) "
            "SELECT tg_id, 0 FROM users"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_wallet_transactions_user_tg_id", table_name="wallet_transactions")
    op.drop_table("wallet_transactions")
    op.drop_table("wallets")
