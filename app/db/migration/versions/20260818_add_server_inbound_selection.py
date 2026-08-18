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
    op.add_column(
        "servers",
        sa.Column("selected_inbound_ids", sa.Text(), nullable=False, server_default="[]"),
    )
    op.alter_column("servers", "selected_inbound_ids", server_default=None)


def downgrade() -> None:
    op.drop_column("servers", "selected_inbound_ids")
