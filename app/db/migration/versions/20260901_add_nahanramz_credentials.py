"""add NahanRamz gateway credentials

Revision ID: 20260901_nahanramz_credentials
Revises: 20260830_payment_method_visibility
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260901_nahanramz_credentials"
down_revision: str | None = "20260830_payment_method_visibility"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("payment_gateway_settings")}

    if "nahanramz_api_key" not in columns:
        op.add_column(
            "payment_gateway_settings",
            sa.Column("nahanramz_api_key", sa.String(length=500), nullable=False, server_default=""),
        )
    if "nahanramz_webhook_secret" not in columns:
        op.add_column(
            "payment_gateway_settings",
            sa.Column("nahanramz_webhook_secret", sa.String(length=500), nullable=False, server_default=""),
        )

    payment_methods = sa.table(
        "payment_method_settings",
        sa.column("method_key", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
    )
    existing = bind.execute(
        sa.text("SELECT 1 FROM payment_method_settings WHERE method_key = 'pay_nahanramz' LIMIT 1")
    ).first()
    if existing is None:
        op.bulk_insert(
            payment_methods,
            [
                {
                    "method_key": "pay_nahanramz",
                    "display_name": "🪙 نهان رمز",
                    "enabled": False,
                    "sort_order": 15,
                }
            ],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("payment_gateway_settings")}

    if "nahanramz_webhook_secret" in columns:
        op.drop_column("payment_gateway_settings", "nahanramz_webhook_secret")
    if "nahanramz_api_key" in columns:
        op.drop_column("payment_gateway_settings", "nahanramz_api_key")

    bind.execute(
        sa.text("DELETE FROM payment_method_settings WHERE method_key = 'pay_nahanramz'")
    )
