"""Address planned response messages by dispatch service.

Revision ID: 20260925_074331_b9d594
Revises: 20260925_071858_c7748e
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_074331_b9d594"
down_revision: str | None = "20260925_071858_c7748e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("scenario_event_templates", sa.Column("target_service_id", sa.Integer()))
    op.create_foreign_key(
        "fk_scenario_event_target_service",
        "scenario_event_templates",
        "dispatch_services",
        ["target_service_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_scenario_event_templates_target_service_id",
        "scenario_event_templates",
        ["target_service_id"],
    )
    op.add_column("response_assignments", sa.Column("dispatch_service_id", sa.Integer()))
    op.create_foreign_key(
        "fk_response_assignment_dispatch_service",
        "response_assignments",
        "dispatch_services",
        ["dispatch_service_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_response_assignments_dispatch_service_id",
        "response_assignments",
        ["dispatch_service_id"],
    )
    op.create_unique_constraint(
        "uq_response_assignment_incident_service",
        "response_assignments",
        ["incident_id", "dispatch_service_id"],
    )

    bind = op.get_bind()
    # A single configured service makes the historical template target unambiguous.
    bind.execute(sa.text("""
        UPDATE scenario_event_templates AS event
        SET target_service_id = service.service_id
        FROM scenario_template_services AS service
        WHERE event.scenario_template_id = service.scenario_template_id
          AND event.event_type = 'RESPONSE_MESSAGE'
          AND (SELECT count(*) FROM scenario_template_services AS all_services
               WHERE all_services.scenario_template_id = event.scenario_template_id) = 1
    """))
    # Existing multi-service templates require an explicit editor decision.
    bind.execute(sa.text("""
        UPDATE scenario_templates AS template
        SET status = 'DRAFT'
        WHERE template.status = 'READY'
          AND EXISTS (
            SELECT 1 FROM scenario_event_templates AS event
            WHERE event.scenario_template_id = template.id
              AND event.event_type = 'RESPONSE_MESSAGE'
              AND event.target_service_id IS NULL
          )
    """))
    # A prepared instance keeps its own service facts; update only unambiguous plans.
    rows = bind.execute(sa.text("""
        SELECT event.id, event.payload_snapshot, instance.service_snapshot
        FROM scenario_instance_events AS event
        JOIN scenario_instances AS instance ON instance.id = event.scenario_instance_id
        WHERE event.event_type = 'RESPONSE_MESSAGE'
    """)).mappings()
    for row in rows:
        services = row["service_snapshot"] or []
        if len(services) != 1 or not services[0].get("service_id"):
            continue
        service = services[0]
        payload = dict(row["payload_snapshot"] or {})
        payload.update(
            target_service_id=service["service_id"],
            target_service_name=service["official_name"],
            target_service_source=service.get("source_reference"),
        )
        bind.execute(
            sa.text("""
                UPDATE scenario_instance_events SET payload_snapshot = :payload
                WHERE id = :event_id
            """).bindparams(sa.bindparam("payload", type_=sa.JSON())),
            {"payload": payload, "event_id": row["id"]},
        )
        bind.execute(
            sa.text("""
                UPDATE scenario_runtime_events SET payload_snapshot = :payload
                WHERE scenario_instance_event_id = :event_id AND status = 'PENDING'
            """).bindparams(sa.bindparam("payload", type_=sa.JSON())),
            {"payload": payload, "event_id": row["id"]},
        )
        bind.execute(sa.text("""
            UPDATE response_assignments AS assignment
            SET dispatch_service_id = :service_id
            FROM incidents AS incident
            WHERE assignment.incident_id = incident.id
              AND incident.scenario_instance_id = (
                SELECT scenario_instance_id FROM scenario_instance_events WHERE id = :event_id
              )
              AND (SELECT count(*) FROM response_assignments AS all_assignments
                   WHERE all_assignments.incident_id = incident.id) = 1
              AND assignment.dispatch_service_id IS NULL
        """), {"service_id": service["service_id"], "event_id": row["id"]})

    # Already delivered incidents need the same service choice in their UI snapshot.
    incidents = bind.execute(sa.text("""
        SELECT incident.id, incident.source_snapshot, instance.service_snapshot
        FROM incidents AS incident
        JOIN scenario_instances AS instance ON instance.id = incident.scenario_instance_id
    """)).mappings()
    for row in incidents:
        snapshot = dict(row["source_snapshot"] or {})
        if "scenario_services" in snapshot:
            continue
        snapshot["scenario_services"] = [
            {"service_id": service["service_id"], "name": service["official_name"]}
            for service in row["service_snapshot"] or []
            if service.get("service_id")
        ]
        bind.execute(
            sa.text("""
                UPDATE incidents SET source_snapshot = :snapshot WHERE id = :incident_id
            """).bindparams(sa.bindparam("snapshot", type_=sa.JSON())),
            {"snapshot": snapshot, "incident_id": row["id"]},
        )


def downgrade() -> None:
    op.drop_constraint(
        "uq_response_assignment_incident_service", "response_assignments", type_="unique"
    )
    op.drop_index(
        "ix_response_assignments_dispatch_service_id", table_name="response_assignments"
    )
    op.drop_constraint(
        "fk_response_assignment_dispatch_service", "response_assignments", type_="foreignkey"
    )
    op.drop_column("response_assignments", "dispatch_service_id")
    op.drop_index(
        "ix_scenario_event_templates_target_service_id", table_name="scenario_event_templates"
    )
    op.drop_constraint(
        "fk_scenario_event_target_service", "scenario_event_templates", type_="foreignkey"
    )
    op.drop_column("scenario_event_templates", "target_service_id")
