"""Remove postal prefixes from object and prepared-card addresses.

Revision ID: 20260926_194017_800c20
Revises: 20260926_183318_d91f6a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.modules.object_registry.address import normalize_address, normalize_generated_text

revision: str = "20260926_194017_800c20"
down_revision: str | Sequence[str] | None = "20260926_183318_d91f6a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _city_address(address: str | None, source: str | None) -> str | None:
    default_city = "г. Москва" if (source or "").startswith("data.mos.ru:") else None
    return normalize_address(address, default_city=default_city)


def _snapshot_address(snapshot: dict | None) -> tuple[dict | None, str | None, str | None]:
    if not isinstance(snapshot, dict):
        return snapshot, None, None
    old = snapshot.get("address")
    new = _city_address(old, snapshot.get("source"))
    if not old or old == new:
        return snapshot, None, None
    result = dict(snapshot)
    result["address"] = new
    return result, old, new


def _rendered_state(state: dict | None, old: str | None, new: str | None) -> dict | None:
    if not isinstance(state, dict) or not old or not new:
        return state
    render = state.get("render")
    if not isinstance(render, dict) or render.get("render_origin") == "MANUAL":
        return state
    text = render.get("rendered_text")
    if not isinstance(text, str):
        return state
    updated = normalize_generated_text(text, old, new)
    if updated == text:
        return state
    result = dict(state)
    result["render"] = {**render, "rendered_text": updated}
    return result


def upgrade() -> None:
    connection = op.get_bind()
    objects = sa.table(
        "city_objects",
        sa.column("id", sa.Integer),
        sa.column("source", sa.String),
        sa.column("address", sa.Text),
    )
    for row in connection.execute(sa.select(objects.c.id, objects.c.source, objects.c.address)):
        address = _city_address(row.address, row.source)
        if address != row.address:
            connection.execute(
                objects.update().where(objects.c.id == row.id).values(address=address)
            )

    instances = sa.table(
        "scenario_instances",
        sa.column("id", sa.Integer),
        sa.column("object_snapshot", sa.JSON),
        sa.column("initial_state_snapshot", sa.JSON),
    )
    for row in connection.execute(sa.select(instances)):
        obj, old, new = _snapshot_address(row.object_snapshot)
        state = _rendered_state(row.initial_state_snapshot, old, new)
        if obj != row.object_snapshot or state != row.initial_state_snapshot:
            connection.execute(
                instances.update()
                .where(instances.c.id == row.id)
                .values(object_snapshot=obj, initial_state_snapshot=state)
            )

    saved_cards = sa.table(
        "saved_incident_cards", sa.column("id", sa.Integer), sa.column("snapshot", sa.JSON)
    )
    for row in connection.execute(sa.select(saved_cards)):
        if not isinstance(row.snapshot, dict):
            continue
        obj, old, new = _snapshot_address(row.snapshot.get("object_snapshot"))
        state = _rendered_state(row.snapshot.get("initial_state_snapshot"), old, new)
        if obj != row.snapshot.get("object_snapshot") or state != row.snapshot.get(
            "initial_state_snapshot"
        ):
            snapshot = {**row.snapshot, "object_snapshot": obj, "initial_state_snapshot": state}
            connection.execute(
                saved_cards.update().where(saved_cards.c.id == row.id).values(snapshot=snapshot)
            )

    incidents = sa.table(
        "incidents",
        sa.column("id", sa.Integer),
        sa.column("address", sa.Text),
        sa.column("description", sa.Text),
        sa.column("source_snapshot", sa.JSON),
    )
    for row in connection.execute(sa.select(incidents)):
        address = normalize_address(row.address) or row.address
        source_snapshot, _, _ = _snapshot_address(row.source_snapshot)
        description = (
            normalize_generated_text(row.description, row.address, address)
            if row.description and row.address != address
            else row.description
        )
        if (
            address != row.address
            or source_snapshot != row.source_snapshot
            or description != row.description
        ):
            connection.execute(
                incidents.update()
                .where(incidents.c.id == row.id)
                .values(
                    address=address,
                    description=description,
                    source_snapshot=source_snapshot,
                )
            )


def downgrade() -> None:
    # Удалённые из адресов индексы невозможно надёжно восстановить.
    pass
