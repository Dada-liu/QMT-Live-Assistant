"""add defer_buy_on_insufficient_funds and pending_buy_orders

Revision ID: a3f8c21d9e04
Revises: 75818ed95f0e
Create Date: 2026-08-07 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f8c21d9e04'
down_revision: Union[str, Sequence[str], None] = '75818ed95f0e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'strategies',
        sa.Column('defer_buy_on_insufficient_funds', sa.Boolean(), nullable=False, server_default='0'),
    )
    op.create_table(
        'pending_buy_orders',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('strategy_id', sa.String(length=36), sa.ForeignKey('strategies.id')),
        sa.Column('method_name', sa.String(length=64), nullable=False),
        sa.Column('stock_code', sa.String(length=16), nullable=False),
        sa.Column('request_payload', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('signal_log_id', sa.String(length=36), sa.ForeignKey('signal_logs.id'), nullable=True),
        sa.Column('submitted_order_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expire_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f('ix_pending_buy_orders_strategy_id'), 'pending_buy_orders', ['strategy_id'], unique=False)
    op.create_index(op.f('ix_pending_buy_orders_status'), 'pending_buy_orders', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_pending_buy_orders_status'), table_name='pending_buy_orders')
    op.drop_index(op.f('ix_pending_buy_orders_strategy_id'), table_name='pending_buy_orders')
    op.drop_table('pending_buy_orders')
    op.drop_column('strategies', 'defer_buy_on_insufficient_funds')
