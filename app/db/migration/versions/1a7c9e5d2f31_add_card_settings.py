"""add persistent card payment settings

Revision ID: 1a7c9e5d2f31
Revises: 0bdfe56a6e56
Create Date: 2026-08-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1a7c9e5d2f31"
down_revision: Union[str, Sequence[str], None] = "0bdfe56a6e56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "card_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("card_number", sa.String(length=32), nullable=False),
        sa.Column("card_holder_name", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("card_settings")
