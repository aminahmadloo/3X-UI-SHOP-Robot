"""add AI content production controls

Revision ID: 20260920_ai_content_production
Revises: 20260911_advertising_publication_targets
Create Date: 2026-09-20
"""
from alembic import op
import sqlalchemy as sa

revision = "20260920_ai_content_production"
down_revision = "20260911_advertising_publication_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_content_settings",
        sa.Column("production_controls", sa.Text(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("ai_content_settings", "production_controls")
