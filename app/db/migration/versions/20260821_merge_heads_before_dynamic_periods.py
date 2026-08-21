"""merge existing migration heads before dynamic service periods

Revision ID: 20260821_merge_dynamic_heads
Revises: c91e7f4a2b61, merge_heads_after_card_payment, 20260819_add_user_client_toggle
"""

from collections.abc import Sequence
from alembic import op

revision: str = "20260821_merge_dynamic_heads"
down_revision: str | Sequence[str] | None = (
    "c91e7f4a2b61",
    "merge_heads_after_card_payment",
    "20260819_add_user_client_toggle",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
