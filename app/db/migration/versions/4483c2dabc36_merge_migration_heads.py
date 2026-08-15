"""merge migration heads

Revision ID: 4483c2dabc36
Revises: 032f2bef8d8d, 1a7c9e5d2f31, 7e4c91a2d6f0
Create Date: 2026-08-15 15:41:12.257115

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4483c2dabc36'
down_revision: Union[str, None] = ('032f2bef8d8d', '1a7c9e5d2f31', '7e4c91a2d6f0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
