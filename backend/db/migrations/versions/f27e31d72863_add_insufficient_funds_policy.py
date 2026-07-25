"""add insufficient_funds_policy to strategies

Revision ID: f27e31d72863
Revises: ead02e07b868
Create Date: 2026-07-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f27e31d72863'
down_revision: Union[str, Sequence[str], None] = 'ead02e07b868'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('strategies', sa.Column('insufficient_funds_policy', sa.String(length=32), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('strategies', 'insufficient_funds_policy')
