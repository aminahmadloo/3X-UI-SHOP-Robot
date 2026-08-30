"""add persistent customer payment method visibility settings

Revision ID: 20260830_payment_method_visibility
Revises: 20260829_multi_inbound_test_accounts
"""

from alembic import op
import sqlalchemy as sa


revision: str = "20260830_payment_method_visibility"
down_revision: str | None = "20260829_multi_inbound_test_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "payment_method_settings" in inspector.get_table_names():
        return

    op.create_table(
        "payment_method_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("method_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.UniqueConstraint("method_key", name="uq_payment_method_settings_method_key"),
    )

    op.create_index(
        "ix_payment_method_settings_method_key",
        "payment_method_settings",
        ["method_key"],
        unique=False,
    )
    op.create_index(
        "ix_payment_method_settings_sort_order",
        "payment_method_settings",
        ["sort_order"],
        unique=False,
    )

    payment_method_settings = sa.table(
        "payment_method_settings",
        sa.column("method_key", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
    )

    op.bulk_insert(
        payment_method_settings,
        [
            {
                "method_key": "pay_zarinpal",
                "display_name": "🏦 زرین‌پال",
                "enabled": True,
                "sort_order": 10,
            },
            {
                "method_key": "mp_card",
                "display_name": "💳 کارت به کارت",
                "enabled": True,
                "sort_order": 20,
            },
            {
                "method_key": "mp_wallet",
                "display_name": "💰 کیف پول",
                "enabled": True,
                "sort_order": 30,
            },
        ],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "payment_method_settings" not in inspector.get_table_names():
        return

    op.drop_index(
        "ix_payment_method_settings_sort_order",
        table_name="payment_method_settings",
    )
    op.drop_index(
        "ix_payment_method_settings_method_key",
        table_name="payment_method_settings",
    )
    op.drop_table("payment_method_settings")
