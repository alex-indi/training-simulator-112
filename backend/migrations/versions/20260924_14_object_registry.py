"""Extensible city object registry.

Revision ID: 20260924_14
Revises: 20260924_13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_14"
down_revision: str | None = "20260924_13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "object_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(120), nullable=False, unique=True),
        sa.Column("name", sa.String(250), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("object_types.id", ondelete="RESTRICT")),
        sa.Column("description", sa.Text()),
        sa.Column("source", sa.String(250), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_object_types_parent_id", "object_types", ["parent_id"])
    op.create_table(
        "city_objects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(250), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column(
            "object_type_id",
            sa.Integer(),
            sa.ForeignKey("object_types.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("address", sa.Text()),
        sa.Column("district", sa.String(250)),
        sa.Column("administrative_area", sa.String(250)),
        sa.Column("latitude", sa.Numeric(9, 6)),
        sa.Column("longitude", sa.Numeric(9, 6)),
        sa.Column("source", sa.String(250), nullable=False),
        sa.Column("source_dataset_id", sa.String(250)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("source", "external_id", name="uq_city_objects_source_external_id"),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_city_objects_latitude"),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_city_objects_longitude"),
    )
    op.create_index("ix_city_objects_object_type_id", "city_objects", ["object_type_id"])
    op.create_index("ix_city_objects_district", "city_objects", ["district"])
    op.create_index("ix_city_objects_external_id", "city_objects", ["external_id"])
    op.create_table(
        "object_attributes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "object_id",
            sa.Integer(),
            sa.ForeignKey("city_objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attribute_code", sa.String(120), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("value_type", sa.String(40), nullable=False),
        sa.UniqueConstraint("object_id", "attribute_code", name="uq_object_attributes_code"),
    )
    op.create_table(
        "object_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "object_id",
            sa.Integer(),
            sa.ForeignKey("city_objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tag", sa.String(120), nullable=False),
        sa.UniqueConstraint("object_id", "tag", name="uq_object_tags_object_tag"),
    )
    op.create_index("ix_object_tags_tag", "object_tags", ["tag"])


def downgrade() -> None:
    op.drop_index("ix_object_tags_tag", table_name="object_tags")
    op.drop_table("object_tags")
    op.drop_table("object_attributes")
    op.drop_index("ix_city_objects_external_id", table_name="city_objects")
    op.drop_index("ix_city_objects_district", table_name="city_objects")
    op.drop_index("ix_city_objects_object_type_id", table_name="city_objects")
    op.drop_table("city_objects")
    op.drop_index("ix_object_types_parent_id", table_name="object_types")
    op.drop_table("object_types")
