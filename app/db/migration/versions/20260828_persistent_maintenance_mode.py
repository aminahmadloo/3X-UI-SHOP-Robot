"""persist maintenance mode across bot restarts

Revision ID: 20260828_persistent_maintenance_mode
Revises: 20260828_multi_card_settings
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260828_persistent_maintenance_mode"
down_revision: str | None = "20260828_multi_card_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "maintenance_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.execute(
        sa.text(
            "INSERT INTO maintenance_settings (id, enabled) VALUES (1, 0)"
        )
    )


def downgrade() -> None:
    op.drop_table("maintenance_settings")
