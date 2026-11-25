"""add default_market_price_type to strategies

Revision ID: 75818ed95f0e
Revises: 7704d36f098a
Create Date: 2026-07-31 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '75818ed95f0e'
down_revision: Union[str, Sequence[str], None] = '7704d36f098a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 策略默认市价下单方式：5=最新价，44=对手方最优，45=本方最优；存量策略默认最新价
    op.add_column('strategies', sa.Column('default_market_price_type', sa.Integer(), nullable=False, server_default=sa.text('5')))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('strategies', 'default_market_price_type')
