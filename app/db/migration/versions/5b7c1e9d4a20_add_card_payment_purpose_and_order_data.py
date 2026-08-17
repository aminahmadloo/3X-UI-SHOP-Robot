"""add card payment purpose and order data

Revision ID: 5b7c1e9d4a20
Revises: 4483c2dabc36
Create Date: 2026-08-17 20:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5b7c1e9d4a20"
down_revision: Union[str, None] = "4483c2dabc36"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "card_payments",
        sa.Column(
            "payment_type",
            sa.String(length=32),
            nullable=False,
            server_default="wallet_topup",
        ),
    )
    op.add_column(
        "card_payments",
        sa.Column("order_data", sa.String(length=255), nullable=True),
    )
    op.alter_column("card_payments", "payment_type", server_default=None)


def downgrade() -> None:
    op.drop_column("card_payments", "order_data")
    op.drop_column("card_payments", "payment_type")
