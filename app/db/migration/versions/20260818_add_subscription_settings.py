"""add subscription settings table

Revision ID: 20260818_add_subscription_settings
Revises: 3a79f6c8490e
Create Date: 2026-08-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260818_add_subscription_settings"
down_revision: Union[str, None] = "3a79f6c8490e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscription_settings",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "domain",
            sa.String(length=255),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "port",
            sa.Integer(),
            nullable=False,
            server_default="2096",
        ),
        sa.Column(
            "path",
            sa.String(length=100),
            nullable=False,
            server_default="sub",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.execute(
        """
        INSERT INTO subscription_settings
        (id, domain, port, path)
        VALUES
        (1, '', 2096, 'sub')
        """
    )


def downgrade() -> None:
    op.drop_table("subscription_settings")
