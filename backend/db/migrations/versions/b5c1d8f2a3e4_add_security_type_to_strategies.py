"""add security_type to strategies

Revision ID: b5c1d8f2a3e4
Revises: a3f8c21d9e04
Create Date: 2026-08-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5c1d8f2a3e4'
down_revision: Union[str, Sequence[str], None] = 'a3f8c21d9e04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 策略种类（券种）：stock=股票，convertible_bond=可转债；存量数据为 NULL，读取时归一为 stock
    op.add_column('strategies', sa.Column('security_type', sa.String(length=32), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('strategies', 'security_type')
