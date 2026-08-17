"""add connected device settings

Revision ID: add_connected_device_settings
Revises: c91e7f4a2b61
"""

from alembic import op
import sqlalchemy as sa


revision = "add_connected_device_settings"
down_revision = "c91e7f4a2b61"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connected_device_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "max_connected_devices",
            sa.Integer(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("connected_device_settings")
