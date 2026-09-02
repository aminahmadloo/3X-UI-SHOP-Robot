"""remove an invalid command-shaped special-offer campaign title

Revision ID: 20260902_cleanup_invalid_special_offer_command
Revises: 20260902_special_offer_campaigns
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260902_cleanup_invalid_special_offer_command"
down_revision = "20260902_special_offer_campaigns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM special_offer_campaign_plans "
            "WHERE campaign_id IN ("
            "SELECT id FROM special_offer_campaigns WHERE title = :title"
            ")"
        ),
        {"title": "/start"},
    )
    bind.execute(
        sa.text("DELETE FROM special_offer_campaigns WHERE title = :title"),
        {"title": "/start"},
    )


def downgrade() -> None:
    # The invalid campaign was test data, so it is intentionally not restored.
    pass
