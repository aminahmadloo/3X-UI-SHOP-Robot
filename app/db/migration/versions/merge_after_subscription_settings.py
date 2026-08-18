"""merge subscription settings and inbound selection heads

Revision ID: merge_after_subscription_settings
Revises: 20260818_add_server_inbound_selection, 20260818_add_subscription_settings
Create Date: 2026-08-18
"""

from typing import Sequence, Union

from alembic import op


revision: str = "merge_after_subscription_settings"

down_revision: Union[
    str,
    Sequence[str],
    None
] = (
    "20260818_add_subscription_settings",
    "21ce58fd554c",
)

branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
