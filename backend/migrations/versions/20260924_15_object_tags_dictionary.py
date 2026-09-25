"""Add a dictionary for semantic object tags.

Revision ID: 20260924_15
Revises: 20260924_14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_15"
down_revision: str | None = "20260924_14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if inspector.has_table("object_tags_dictionary"):
        columns = {column["name"] for column in inspector.get_columns("object_tags_dictionary")}
        foreign_keys = inspector.get_foreign_keys("object_tags")
        has_tag_reference = any(
            key["referred_table"] == "object_tags_dictionary"
            and key["constrained_columns"] == ["tag"]
            for key in foreign_keys
        )
        unmapped_tags = connection.scalar(
            sa.text(
                "SELECT count(*) FROM object_tags t LEFT JOIN object_tags_dictionary d "
                "ON d.code = t.tag WHERE d.code IS NULL"
            )
        )
        if columns != {"code", "name", "description"} or not has_tag_reference or unmapped_tags:
            raise RuntimeError("Существующий словарь тегов неполон; требуется ручная сверка")
        return  # Схема уже создана в локальной истории параллельной задачи.
    op.create_table(
        "object_tags_dictionary",
        sa.Column("code", sa.String(120), primary_key=True),
        sa.Column("name", sa.String(250), nullable=False),
        sa.Column("description", sa.Text()),
    )
    connection.execute(
        sa.text(
            "INSERT INTO object_tags_dictionary (code, name) "
            "SELECT DISTINCT tag, tag FROM object_tags"
        )
    )
    op.create_foreign_key(
        "fk_object_tags_dictionary_code",
        "object_tags",
        "object_tags_dictionary",
        ["tag"],
        ["code"],
        ondelete="RESTRICT",
    )
    connection.execute(
        sa.text(
            "UPDATE object_types SET parent_id = "
            "(SELECT id FROM object_types WHERE code = 'BUILDING') "
            "WHERE code = 'TRANSPORT' AND parent_id IS NULL"
        )
    )


def downgrade() -> None:
    op.execute(
        "UPDATE object_types SET parent_id = NULL WHERE code = 'TRANSPORT' "
        "AND parent_id = (SELECT id FROM object_types WHERE code = 'BUILDING')"
    )
    op.drop_constraint("fk_object_tags_dictionary_code", "object_tags", type_="foreignkey")
    op.drop_table("object_tags_dictionary")
