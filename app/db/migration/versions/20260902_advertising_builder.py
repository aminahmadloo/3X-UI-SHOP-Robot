"""Add flexible advertising builder configuration.

Revision ID: 20260902_advertising_builder
Revises: 20260902_add_telegram_advertising
"""

from alembic import op
import sqlalchemy as sa

revision = "20260902_advertising_builder"
down_revision = "20260902_add_telegram_advertising"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("advertising_campaigns", sa.Column("custom_buttons_json", sa.Text(), nullable=True, server_default="[]"))
    op.add_column("advertising_campaigns", sa.Column("selected_offers_json", sa.Text(), nullable=True, server_default="[]"))
    op.add_column("advertising_campaigns", sa.Column("show_services", sa.Boolean(), nullable=True, server_default="1"))
    op.execute("UPDATE advertising_campaigns SET custom_buttons_json='[]' WHERE custom_buttons_json IS NULL")
    op.execute("UPDATE advertising_campaigns SET selected_offers_json='[]' WHERE selected_offers_json IS NULL")
    op.execute("UPDATE advertising_campaigns SET show_services=1 WHERE show_services IS NULL")
    with op.batch_alter_table("advertising_campaigns") as batch_op:
        batch_op.alter_column("custom_buttons_json", nullable=False)
        batch_op.alter_column("selected_offers_json", nullable=False)
        batch_op.alter_column("show_services", nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("advertising_campaigns") as batch_op:
        batch_op.drop_column("show_services")
        batch_op.drop_column("selected_offers_json")
        batch_op.drop_column("custom_buttons_json")
