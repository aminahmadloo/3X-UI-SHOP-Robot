"""allow one test account across multiple selected inbounds

Revision ID: 20260829_multi_inbound_test_accounts
Revises: 20260829_custom_volume_purchase
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260829_multi_inbound_test_accounts"
down_revision: str | None = "20260829_custom_volume_purchase"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite requires rebuilding the table to remove UNIQUE constraints.
    op.execute(
        """
        CREATE TABLE test_accounts_new (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER NOT NULL,
            username VARCHAR(64),
            first_name VARCHAR(64),
            server_id INTEGER NOT NULL,
            inbound_id INTEGER NOT NULL,
            client_id VARCHAR(64) NOT NULL,
            client_email VARCHAR(128) NOT NULL UNIQUE,
            subscription_token VARCHAR(64) NOT NULL,
            quota_bytes INTEGER NOT NULL,
            expires_at DATETIME NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'active',
            usage_up_bytes INTEGER NOT NULL DEFAULT 0,
            usage_down_bytes INTEGER NOT NULL DEFAULT 0,
            deleted_at DATETIME,
            failure_reason TEXT,
            created_at DATETIME NOT NULL
        )
        """
    )

    op.execute(
        """
        INSERT INTO test_accounts_new (
            id,
            telegram_user_id,
            username,
            first_name,
            server_id,
            inbound_id,
            client_id,
            client_email,
            subscription_token,
            quota_bytes,
            expires_at,
            status,
            usage_up_bytes,
            usage_down_bytes,
            deleted_at,
            failure_reason,
            created_at
        )
        SELECT
            id,
            telegram_user_id,
            username,
            first_name,
            server_id,
            inbound_id,
            client_id,
            client_email,
            subscription_token,
            quota_bytes,
            expires_at,
            status,
            usage_up_bytes,
            usage_down_bytes,
            deleted_at,
            failure_reason,
            created_at
        FROM test_accounts
        """
    )

    op.drop_table("test_accounts")
    op.rename_table("test_accounts_new", "test_accounts")

    op.create_index(
        "ix_test_accounts_telegram_user_id",
        "test_accounts",
        ["telegram_user_id"],
    )
    op.create_index(
        "ix_test_accounts_server_id",
        "test_accounts",
        ["server_id"],
    )
    op.create_index(
        "ix_test_accounts_expires_at",
        "test_accounts",
        ["expires_at"],
    )
    op.create_index(
        "ix_test_accounts_status",
        "test_accounts",
        ["status"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade is intentionally unsupported for multi-inbound test accounts."
    )
