"""covermate ai chat conversations and messages

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('chat_conversations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('public_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=80), nullable=False),
    sa.Column('focus_policy_id', sa.Integer(), nullable=True),
    sa.Column('focus_claim_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['focus_claim_id'], ['claims.id'], ),
    sa.ForeignKeyConstraint(['focus_policy_id'], ['policies.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('chat_conversations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_chat_conversations_public_id'), ['public_id'], unique=True)
        batch_op.create_index(batch_op.f('ix_chat_conversations_updated_at'), ['updated_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_conversations_user_id'), ['user_id'], unique=False)

    op.create_table('chat_messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('conversation_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=10), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('provider', sa.String(length=30), nullable=False),
    sa.Column('model', sa.String(length=80), nullable=False),
    sa.Column('meta', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['chat_conversations.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('chat_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_chat_messages_conversation_id'), ['conversation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_messages_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_messages_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('chat_messages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_chat_messages_user_id'))
        batch_op.drop_index(batch_op.f('ix_chat_messages_created_at'))
        batch_op.drop_index(batch_op.f('ix_chat_messages_conversation_id'))
    op.drop_table('chat_messages')
    with op.batch_alter_table('chat_conversations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_chat_conversations_user_id'))
        batch_op.drop_index(batch_op.f('ix_chat_conversations_updated_at'))
        batch_op.drop_index(batch_op.f('ix_chat_conversations_public_id'))
    op.drop_table('chat_conversations')
