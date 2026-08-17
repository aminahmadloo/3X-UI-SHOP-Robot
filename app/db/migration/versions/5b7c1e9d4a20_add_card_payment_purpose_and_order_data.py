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
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_columns = {
        column["name"]
        for column in inspector.get_columns("card_payments")
    }

    if "payment_type" not in existing_columns:
        op.add_column(
            "card_payments",
            sa.Column(
                "payment_type",
                sa.String(length=32),
                nullable=False,
                server_default="wallet_topup",
            ),
        )

    if "order_data" not in existing_columns:
        op.add_column(
            "card_payments",
            sa.Column(
                "order_data",
                sa.String(length=255),
                nullable=True,
            ),
        )

    # SQLite does not support:
    # ALTER TABLE ... ALTER COLUMN ... DROP DEFAULT
    #
    # The temporary server default is therefore intentionally retained.
    # It is harmless for existing rows and provides a safe default for
    # future inserts.


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_columns = {
        column["name"]
        for column in inspector.get_columns("card_payments")
    }

    if "order_data" in existing_columns:
        op.drop_column("card_payments", "order_data")

    if "payment_type" in existing_columns:
        op.drop_column("card_payments", "payment_type")
