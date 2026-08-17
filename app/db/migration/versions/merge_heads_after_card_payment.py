"""merge connected device and card payment migration heads

Revision ID: merge_heads_after_card_payment
Revises: add_connected_device_settings, 5b7c1e9d4a20
Create Date: 2026-08-17
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "merge_heads_after_card_payment"
down_revision: Union[str, Sequence[str], None] = (
    "add_connected_device_settings",
    "5b7c1e9d4a20",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
