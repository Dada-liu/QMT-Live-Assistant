"""add app_settings table and bark_notify_enabled to strategies

Revision ID: 7704d36f098a
Revises: f27e31d72863
Create Date: 2026-07-31 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7704d36f098a'
down_revision: Union[str, Sequence[str], None] = 'f27e31d72863'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'app_settings',
        sa.Column('key', sa.String(length=64), primary_key=True),
        sa.Column('value', sa.Text(), nullable=True),
    )
    # 存量策略默认开启 Bark 推送
    op.add_column('strategies', sa.Column('bark_notify_enabled', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('strategies', 'bark_notify_enabled')
    op.drop_table('app_settings')
