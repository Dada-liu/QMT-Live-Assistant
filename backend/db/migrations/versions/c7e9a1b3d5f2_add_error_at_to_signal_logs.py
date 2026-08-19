"""add error_at to signal_logs

Revision ID: c7e9a1b3d5f2
Revises: b5c1d8f2a3e4
Create Date: 2026-08-19 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e9a1b3d5f2'
down_revision: Union[str, Sequence[str], None] = 'b5c1d8f2a3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 报错发生时间：update_error 时记录；存量数据为 NULL，前端回退用 received_at 展示
    op.add_column('signal_logs', sa.Column('error_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('signal_logs', 'error_at')
