"""add support tickets and messages

Revision ID: 20260827_support_tickets
Revises: 20260827_gift_recipient
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260827_support_tickets"
down_revision: str | None = "20260827_gift_recipient"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "support_tickets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default="waiting_support",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_support_tickets_user_id",
        "support_tickets",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "support_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("sender_type", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["support_tickets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_support_messages_ticket_id",
        "support_messages",
        ["ticket_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_support_messages_ticket_id",
        table_name="support_messages",
    )
    op.drop_table("support_messages")

    op.drop_index(
        "ix_support_tickets_user_id",
        table_name="support_tickets",
    )
    op.drop_table("support_tickets")
