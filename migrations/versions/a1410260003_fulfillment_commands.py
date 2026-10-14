"""Idempotent recovery for fulfillment state transitions."""
from alembic import op
import sqlalchemy as sa
revision = 'a1410260003'
down_revision = 'a1410260002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('fulfillment_commands',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id'), nullable=False),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('request_key', sa.String(100), nullable=False),
        sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.Column('result_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(40), nullable=False),
        sa.UniqueConstraint('order_id', 'actor_id', 'request_key'))


def downgrade():
    raise RuntimeError('履約成功識別不得刪除，請使用備份還原')
