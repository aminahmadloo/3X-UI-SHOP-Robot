"""add KPay gateway credentials

Revision ID: 20260901_kpay_credentials
Revises: 20260901_nahanramz_credentials
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260901_kpay_credentials"
down_revision: str | None = "20260901_nahanramz_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("payment_gateway_settings")}

    for name in ("kpay_api_key", "kpay_shop_id", "kpay_card_id"):
        if name not in columns:
            length = 500 if name == "kpay_api_key" else 128
            op.add_column(
                "payment_gateway_settings",
                sa.Column(name, sa.String(length=length), nullable=False, server_default=""),
            )

    payment_methods = sa.table(
        "payment_method_settings",
        sa.column("method_key", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
    )
    existing = bind.execute(
        sa.text("SELECT 1 FROM payment_method_settings WHERE method_key = 'pay_kpay' LIMIT 1")
    ).first()
    if existing is None:
        op.bulk_insert(
            payment_methods,
            [
                {
                    "method_key": "pay_kpay",
                    "display_name": "💳 کارت‌به‌کارت هوشمند",
                    "enabled": False,
                    "sort_order": 16,
                }
            ],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("payment_gateway_settings")}

    bind.execute(sa.text("DELETE FROM payment_method_settings WHERE method_key = 'pay_kpay'"))

    for name in ("kpay_card_id", "kpay_shop_id", "kpay_api_key"):
        if name in columns:
            op.drop_column("payment_gateway_settings", name)
