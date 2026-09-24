"""Добавляет сообщения оперативной связи для назначений групп.

Revision ID: 20260923_09
Revises: 20260923_08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260923_09"
down_revision: str | None = "20260923_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

sender_type = postgresql.ENUM(
    "DISPATCHER", "RESPONSE_UNIT", "SYSTEM", name="response_message_sender", create_type=False
)


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    sender_type.create(connection, checkfirst=True)
    if inspector.has_table("response_messages"):
        columns = {column["name"] for column in inspector.get_columns("response_messages")}
        expected = {
            "id",
            "response_assignment_id",
            "sender_type",
            "body",
            "actor_user_id",
            "event_key",
            "created_at",
            "read_at",
        }
        if columns != expected:
            raise RuntimeError("Существующая таблица response_messages имеет несовместимую схему")
    else:
        op.create_table(
            "response_messages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "response_assignment_id",
                sa.Integer(),
                sa.ForeignKey("response_assignments.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("sender_type", sender_type, nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column(
                "actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
            ),
            sa.Column("event_key", sa.String(120)),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("read_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("response_assignment_id", "event_key"),
        )
    indexes = {index["name"] for index in sa.inspect(connection).get_indexes("response_messages")}
    if "ix_response_messages_response_assignment_id" not in indexes:
        op.create_index(
            "ix_response_messages_response_assignment_id",
            "response_messages",
            ["response_assignment_id"],
        )


def downgrade() -> None:
    op.drop_table("response_messages")
    sender_type.drop(op.get_bind(), checkfirst=False)
