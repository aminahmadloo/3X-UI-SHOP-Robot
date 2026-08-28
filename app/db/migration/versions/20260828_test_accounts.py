"""add persistent test account storage

Revision ID: 20260828_test_accounts
Revises: 20260828_persistent_maintenance_mode
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260828_test_accounts"
down_revision: str | None = "20260828_persistent_maintenance_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "test_account_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("volume_mb", sa.Integer(), nullable=False, server_default="200"),
        sa.Column("duration_days", sa.Integer(), nullable=False, server_default="2"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO test_account_settings (id, enabled, volume_mb, duration_days) VALUES (1, 1, 200, 2)"
        )
    )

    op.create_table(
        "test_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_user_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=64), nullable=True),
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("inbound_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("client_email", sa.String(length=128), nullable=False),
        sa.Column("subscription_token", sa.String(length=64), nullable=False),
        sa.Column("quota_bytes", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("usage_up_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_down_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_user_id"),
        sa.UniqueConstraint("client_id"),
        sa.UniqueConstraint("client_email"),
        sa.UniqueConstraint("subscription_token"),
    )
    op.create_index("ix_test_accounts_telegram_user_id", "test_accounts", ["telegram_user_id"])
    op.create_index("ix_test_accounts_server_id", "test_accounts", ["server_id"])
    op.create_index("ix_test_accounts_expires_at", "test_accounts", ["expires_at"])
    op.create_index("ix_test_accounts_status", "test_accounts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_test_accounts_status", table_name="test_accounts")
    op.drop_index("ix_test_accounts_expires_at", table_name="test_accounts")
    op.drop_index("ix_test_accounts_server_id", table_name="test_accounts")
    op.drop_index("ix_test_accounts_telegram_user_id", table_name="test_accounts")
    op.drop_table("test_accounts")
    op.drop_table("test_account_settings")
