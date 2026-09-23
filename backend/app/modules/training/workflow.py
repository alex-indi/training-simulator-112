"""Доменные переходы учебной сессии."""

from datetime import UTC, datetime

from app.modules.training.models import TrainingRun, TrainingSession, TrainingSessionState


class InvalidTrainingSessionTransitionError(ValueError):
    """Запрошенный переход не разрешён текущим состоянием сессии."""


def prepare_training_session(training_session: TrainingSession) -> None:
    """Переводит полностью настроенный черновик в готовность к запуску."""
    if training_session.state != TrainingSessionState.DRAFT:
        raise InvalidTrainingSessionTransitionError(
            "Подготовить можно только сессию в состоянии DRAFT"
        )
    if not training_session.trainees:
        raise InvalidTrainingSessionTransitionError(
            "Для подготовки сессии нужен хотя бы один обучаемый"
        )

    training_session.state = TrainingSessionState.READY


def start_training_session(
    training_session: TrainingSession,
    *,
    server_time: datetime | None = None,
) -> None:
    """Запускает подготовленную сессию и фиксирует серверное время."""
    if training_session.state != TrainingSessionState.READY:
        raise InvalidTrainingSessionTransitionError(
            "Запустить можно только сессию в состоянии READY"
        )

    training_session.state = TrainingSessionState.ACTIVE
    training_session.started_at = server_time or datetime.now(UTC)
    existing_ids = {run.trainee_id for run in training_session.runs}
    for run in training_session.runs:
        run.started_at = training_session.started_at
    for trainee in training_session.trainees:
        if trainee.id in existing_ids:
            continue
        training_session.runs.append(
            TrainingRun(
                trainee_id=trainee.id,
                dds_profile="ДДС",
                started_at=training_session.started_at,
            )
        )
