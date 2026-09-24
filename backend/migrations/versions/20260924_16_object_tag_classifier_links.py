"""Link semantic object tags to verified SRC-006 features.

Revision ID: 20260924_16
Revises: 20260924_15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_16"
down_revision: str | None = "20260924_15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "object_tag_classifier_features",
        sa.Column(
            "tag_code",
            sa.String(120),
            sa.ForeignKey("object_tags_dictionary.code", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "feature_id",
            sa.Integer(),
            sa.ForeignKey("incident_features.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_object_tag_classifier_features_feature_id",
        "object_tag_classifier_features",
        ["feature_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_object_tag_classifier_features_feature_id",
        table_name="object_tag_classifier_features",
    )
    op.drop_table("object_tag_classifier_features")
