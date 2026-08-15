"""merge wallet and card payment migrations

Revision ID: 0bdfe56a6e56
Revises: 6c1e8a2f4b90, 7b9c4d1e2f30
Create Date: 2026-08-12
"""

from typing import Sequence, Union


revision: str = "0bdfe56a6e56"
down_revision: Union[str, Sequence[str], None] = (
    "6c1e8a2f4b90",
    "7b9c4d1e2f30",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
