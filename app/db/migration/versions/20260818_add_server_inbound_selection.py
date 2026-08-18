"""add per-server inbound selection

Revision ID: 20260818_add_server_inbound_selection
Revises: merge_heads_after_card_payment
Create Date: 2026-08-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260818_add_server_inbound_selection"
down_revision: Union[str, Sequence[str], None] = "merge_heads_after_card_payment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {
        column["name"]
        for column in inspector.get_columns("servers")
    }

    if "selected_inbound_ids" not in columns:
        op.add_column(
            "servers",
            sa.Column(
                "selected_inbound_ids",
                sa.Text(),
                nullable=False,
                server_default="[]",
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {
        column["name"]
        for column in inspector.get_columns("servers")
    }

    if "selected_inbound_ids" in columns:
        op.drop_column("servers", "selected_inbound_ids")
