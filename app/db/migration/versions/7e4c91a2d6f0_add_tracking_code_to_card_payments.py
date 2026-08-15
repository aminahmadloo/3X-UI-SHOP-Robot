"""add tracking code to card payments

Revision ID: 7e4c91a2d6f0
Revises: 0bdfe56a6e56
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "7e4c91a2d6f0"
down_revision: Union[str, Sequence[str], None] = "0bdfe56a6e56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("card_payments") as batch_op:
        batch_op.add_column(
            sa.Column("tracking_code", sa.String(length=64), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uq_card_payments_tracking_code",
            ["tracking_code"],
        )


def downgrade() -> None:
    with op.batch_alter_table("card_payments") as batch_op:
        batch_op.drop_constraint(
            "uq_card_payments_tracking_code",
            type_="unique",
        )
        batch_op.drop_column("tracking_code")
