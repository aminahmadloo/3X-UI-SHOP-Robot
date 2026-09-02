"""remove legacy KPay and NahanRamz payment gateway data

Revision ID: 20260902_remove_legacy_payment_gateways
Revises: 20260830_payment_method_visibility
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260902_remove_legacy_payment_gateways"
down_revision: str | None = "20260830_payment_method_visibility"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Remove legacy payment-method visibility entries.
    bind = op.get_bind()

    if "payment_method_settings" in sa.inspect(bind).get_table_names():
        op.execute(
            sa.text(
                """
                DELETE FROM payment_method_settings
                WHERE method_key IN ('pay_nahanramz', 'pay_kpay')
                """
            )
        )

    # Remove legacy gateway credentials/configuration columns.
    if "payment_gateway_settings" in sa.inspect(bind).get_table_names():
        with op.batch_alter_table("payment_gateway_settings") as batch_op:
            batch_op.drop_column("nahanramz_api_key")
            batch_op.drop_column("nahanramz_webhook_secret")
            batch_op.drop_column("kpay_api_key")
            batch_op.drop_column("kpay_shop_id")
            batch_op.drop_column("kpay_card_id")


def downgrade() -> None:
    # Recreate legacy columns as empty values only.
    # Deleted credentials are intentionally not restored.
    bind = op.get_bind()

    if "payment_gateway_settings" in sa.inspect(bind).get_table_names():
        columns = {
            column["name"]
            for column in sa.inspect(bind).get_columns("payment_gateway_settings")
        }

        with op.batch_alter_table("payment_gateway_settings") as batch_op:
            if "nahanramz_api_key" not in columns:
                batch_op.add_column(
                    sa.Column(
                        "nahanramz_api_key",
                        sa.String(length=500),
                        nullable=False,
                        server_default="",
                    )
                )
            if "nahanramz_webhook_secret" not in columns:
                batch_op.add_column(
                    sa.Column(
                        "nahanramz_webhook_secret",
                        sa.String(length=500),
                        nullable=False,
                        server_default="",
                    )
                )
            if "kpay_api_key" not in columns:
                batch_op.add_column(
                    sa.Column(
                        "kpay_api_key",
                        sa.String(length=500),
                        nullable=False,
                        server_default="",
                    )
                )
            if "kpay_shop_id" not in columns:
                batch_op.add_column(
                    sa.Column(
                        "kpay_shop_id",
                        sa.String(length=128),
                        nullable=False,
                        server_default="",
                    )
                )
            if "kpay_card_id" not in columns:
                batch_op.add_column(
                    sa.Column(
                        "kpay_card_id",
                        sa.String(length=128),
                        nullable=False,
                        server_default="",
                    )
                )

    if "payment_method_settings" in sa.inspect(bind).get_table_names():
        payment_method_settings = sa.table(
            "payment_method_settings",
            sa.column("method_key", sa.String()),
            sa.column("display_name", sa.String()),
            sa.column("enabled", sa.Boolean()),
            sa.column("sort_order", sa.Integer()),
        )

        existing = {
            row[0]
            for row in bind.execute(
                sa.text("SELECT method_key FROM payment_method_settings")
            )
        }

        rows = []

        if "pay_nahanramz" not in existing:
            rows.append(
                {
                    "method_key": "pay_nahanramz",
                    "display_name": "🪙 نهان رمز",
                    "enabled": False,
                    "sort_order": 15,
                }
            )

        if "pay_kpay" not in existing:
            rows.append(
                {
                    "method_key": "pay_kpay",
                    "display_name": "💳 کارت‌به‌کارت هوشمند",
                    "enabled": False,
                    "sort_order": 16,
                }
            )

        if rows:
            op.bulk_insert(payment_method_settings, rows)
