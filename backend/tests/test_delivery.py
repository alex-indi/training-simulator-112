"""Проверки серверного порядка и учебного времени выдачи."""

from datetime import UTC, datetime, timedelta

from app.modules.identity.models import User, UserRole
from app.modules.training.delivery import due_items, finalize_order
from app.modules.training.models import (
    DeliveryOrder,
    DeliveryState,
    QueueMode,
    ScenarioQueueItem,
    TrainingMode,
    TrainingRun,
    TrainingSession,
    TrainingSessionState,
)
from app.modules.training.router import _readiness


def make_session(mode=TrainingMode.FLOW):
    started = datetime(2026, 9, 23, 12, tzinfo=UTC)
    runs = [TrainingRun(id=1), TrainingRun(id=2)]
    session = TrainingSession(
        id=10,
        mode=mode,
        state=TrainingSessionState.ACTIVE,
        delivery_order=DeliveryOrder.SEQUENTIAL,
        duration_minutes=4,
        delivery_interval_seconds=120,
        workstation_count=2,
        delivery_elapsed_seconds=0,
        delivery_checked_at=started,
        runs=runs,
        queue_items=[
            ScenarioQueueItem(
                id=index,
                training_run_id=run_id,
                position=index,
                delivery_state=DeliveryState.PENDING,
                approved=True,
            )
            for index, run_id in enumerate([1, 2, 1, 2, 1, 2], 1)
        ],
    )
    return session, started


def test_flow_delivers_each_run_on_server_schedule_and_stops_at_duration():
    session, started = make_session()
    finalize_order(session)
    assert [item.id for item in due_items(session, started)] == [1, 2]
    session.queue_items[0].delivery_state = DeliveryState.DELIVERED
    session.queue_items[1].delivery_state = DeliveryState.DELIVERED
    assert [item.id for item in due_items(session, started + timedelta(seconds=119))] == []
    assert [item.id for item in due_items(session, started + timedelta(seconds=120))] == [3, 4]
    assert [item.id for item in due_items(session, started + timedelta(minutes=5))] == [3, 4]


def test_fixed_set_delivers_approved_pool_at_start():
    session, started = make_session(TrainingMode.FIXED_SET)
    finalize_order(session)
    assert len(due_items(session, started)) == 6


def test_manual_mode_has_no_automatic_delivery():
    session, started = make_session(TrainingMode.MANUAL)
    finalize_order(session)
    assert due_items(session, started + timedelta(hours=1)) == []


def test_random_order_is_persisted_per_run(monkeypatch):
    session, _ = make_session()
    session.delivery_order = DeliveryOrder.RANDOM
    monkeypatch.setattr("app.modules.training.delivery.random.shuffle", list.reverse)
    finalize_order(session)
    assert [(item.id, item.delivery_position) for item in session.queue_items] == [
        (1, 3),
        (2, 3),
        (3, 2),
        (4, 2),
        (5, 1),
        (6, 1),
    ]


def test_flow_readiness_requires_approved_pool_for_each_run():
    session, _ = make_session()
    session.state = TrainingSessionState.DRAFT
    session.trainees = [
        User(id=index, username=f"trainee{index}", role=UserRole.TRAINEE) for index in (1, 2)
    ]
    session.groups = []
    for index, run in enumerate(session.runs, 1):
        run.trainee_id = index
        run.workstation_number = index
        run.dds_profile = "ДДС района"
    readiness = _readiness(session)
    assert readiness.prepared_count == 6
    assert readiness.approved_count == 6
    assert readiness.can_start is True
    session.queue_items[0].approved = False
    assert _readiness(session).can_start is False
    session.queue_items[0].approved = True
    session.queue_items = [item for item in session.queue_items if item.training_run_id != 2]
    assert _readiness(session).can_start is False


def test_shared_queue_requires_group():
    session, _ = make_session()
    session.trainees = [
        User(id=index, username=f"trainee{index}", role=UserRole.TRAINEE) for index in (1, 2)
    ]
    session.groups = []
    for index, run in enumerate(session.runs, 1):
        run.trainee_id = index
        run.workstation_number = index
        run.dds_profile = "ДДС района"
    session.runs[0].queue_mode = QueueMode.SHARED_QUEUE
    readiness = _readiness(session)
    assert readiness.can_start is False
    assert "Назначьте общей очереди учебную группу" in readiness.warnings
