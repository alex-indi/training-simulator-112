export const difficultyLabels = { 1: 'Начальная', 2: 'Ниже средней', 3: 'Средняя', 4: 'Высокая', 5: 'Экспертная' }
export const renderOriginLabels = { MANUAL: 'Изменён преподавателем', GENERATED: 'Текст сформирован автоматически' }
export const incidentSourceLabels = { SCENARIO_INSTANCE: 'Учебный сценарий' }
export const sessionStateLabels = { DRAFT: 'Черновик', READY: 'Готово к запуску', ACTIVE: 'Активное', COMPLETED: 'Завершённое', CANCELLED: 'Отменённое' }
export const trainingModeLabels = { FLOW: 'Потоковая тренировка', FIXED_SET: 'Набор заданий', MANUAL: 'Управляемая тренировка' }
export const ddsStatusLabels = {
  AWAITING_DECISION: 'Ожидает решения', ACCEPTED: 'Принята', REJECTED: 'Не принята',
  RESPONSE_STARTED: 'Начало реагирования', ARRIVED: 'Прибытие',
  WORKING: 'Проведение работ', COMPLETED: 'Работы завершены',
  WORK_REFUSED: 'Отказ от выполнения работ',
}
export const responseStateLabels = {
  ASSIGNED: 'Назначена', ACKNOWLEDGED: 'Задание подтверждено', EN_ROUTE: 'Выехала',
  ARRIVED: 'Прибыла', WORKING: 'Выполняет работы', COMPLETED: 'Работы завершила',
  CANCELLED: 'Назначение отменено',
}
export const responseSenderLabels = {
  DISPATCHER: 'Диспетчер ДДС', RESPONSE_UNIT: 'Старший группы', SYSTEM: 'Система',
}
export const incidentHistoryLabels = {
  SERVICE_ADDED: 'Добавлена', SERVICE_RECEIVED: 'Получена службой', ...ddsStatusLabels,
}
