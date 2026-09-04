"""merge channel content management

Revision ID: 08cd9dfd396b
Revises: 20260902_cleanup_invalid_zero_day_periods, 20260904_channel_content
Create Date: 2026-09-04 12:05:41.755540

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '08cd9dfd396b'
down_revision: Union[str, None] = ('20260902_cleanup_invalid_zero_day_periods', '20260904_channel_content')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
