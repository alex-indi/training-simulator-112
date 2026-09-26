"""Create runtime queues from the instructor-approved group master packs."""

from copy import deepcopy

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.scenario_library.instance_models import ScenarioInstance, ScenarioInstanceEvent
from app.modules.scenario_library.runtime import incident_snapshot
from app.modules.training.delivery import _new_item
from app.modules.training.models import QueueMode, TrainingSession


async def materialize_group_pools(database: AsyncSession, session: TrainingSession) -> None:
    """Copy approved facts and text once at launch; never run generation or AI here."""
    if not any(group.source_user_group_id is not None for group in session.groups):
        return
    if session.queue_items:
        raise ValueError("Очередь занятия уже содержит карточки")

    for group in session.groups:
        masters = sorted(
            (row for row in session.master_instances if row.training_group_id == group.id),
            key=lambda row: row.id,
        )
        runs = [run for run in session.runs if run.group_id == group.id]
        if group.queue_mode == QueueMode.SHARED_QUEUE:
            if runs:
                for master in masters:
                    item = _new_item(
                        session, None, master.name[:200], incident_snapshot(master),
                        group_id=group.id,
                    )
                    item.scenario_instance_id = master.id
                    item.approved = True
            continue

        for run in runs:
            for master in masters:
                clone = ScenarioInstance(
                    scenario_template_id=master.scenario_template_id,
                    training_session_id=session.id,
                    training_group_id=None,
                    created_by_user_id=master.created_by_user_id,
                    name=master.name,
                    difficulty=master.difficulty,
                    generation_seed=master.generation_seed,
                    status="CONFIRMED",
                    classifier_snapshot=deepcopy(master.classifier_snapshot),
                    object_snapshot=deepcopy(master.object_snapshot),
                    service_snapshot=deepcopy(master.service_snapshot),
                    initial_state_snapshot=deepcopy(master.initial_state_snapshot),
                    expected_actions_snapshot=deepcopy(master.expected_actions_snapshot),
                    assessment_criteria_snapshot=deepcopy(master.assessment_criteria_snapshot),
                    template_snapshot=deepcopy(master.template_snapshot),
                    events=[
                        ScenarioInstanceEvent(
                            sequence_number=event.sequence_number,
                            offset_seconds=event.offset_seconds,
                            event_type=event.event_type,
                            title=event.title,
                            description=event.description,
                            source_type=event.source_type,
                            payload_snapshot=deepcopy(event.payload_snapshot),
                        )
                        for event in master.events
                    ],
                )
                database.add(clone)
                await database.flush()
                item = _new_item(session, run.id, clone.name[:200], incident_snapshot(clone))
                item.scenario_instance_id = clone.id
                item.approved = True
