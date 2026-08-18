"""add subscriptions table

Revision ID: 21ce58fd554c
Revises: 20260818_add_server_inbound_selection
Create Date: 2026-08-18 10:34:59.988287

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "21ce58fd554c"
down_revision: Union[str, None] = "20260818_add_server_inbound_selection"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("server_id", sa.Integer(), nullable=True),
        sa.Column("plan_id", sa.Integer(), nullable=True),
        sa.Column("config_name", sa.String(length=255), nullable=False),
        sa.Column("client_id", sa.String(length=100), nullable=True),
        sa.Column("volume_gb", sa.Integer(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("devices", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("start_date", sa.DateTime(), nullable=True),
        sa.Column("expire_date", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["servers.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("subscriptions")
