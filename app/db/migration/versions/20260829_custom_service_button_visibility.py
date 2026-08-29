"""add custom service button visibility setting

Revision ID: 20260829_custom_service_button_visibility
Revises: 20260828_test_account_cleanup_interval
"""

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_custom_service_button_visibility"
down_revision: str | None = "20260828_test_account_cleanup_interval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    inspector = sa.inspect(bind)
    columns = {
        column["name"]
        for column in inspector.get_columns("custom_service_pricing")
    }

    if "show_custom_service_button" not in columns:
        op.add_column(
            "custom_service_pricing",
            sa.Column(
                "show_custom_service_button",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()

    inspector = sa.inspect(bind)
    columns = {
        column["name"]
        for column in inspector.get_columns("custom_service_pricing")
    }

    if "show_custom_service_button" in columns:
        op.drop_column(
            "custom_service_pricing",
            "show_custom_service_button",
        )
