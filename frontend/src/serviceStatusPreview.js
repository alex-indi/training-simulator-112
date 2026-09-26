const referenceStatusActions = [
  'START_RESPONSE',
  'MARK_ARRIVAL',
  'START_WORK',
  'REFUSE_WORK',
  'COMPLETE_WORK',
]

export function statusEditorActions() {
  return [...referenceStatusActions]
}

export function initialOrderNumber(actions = []) {
  const initialDecision = actions.find(
    (entry) => !entry.is_system
      && (entry.action === 'ACCEPT' || entry.action === 'REJECT')
      && entry.order_number?.trim(),
  )

  return initialDecision?.order_number.trim() || ''
}

export function incidentServiceName(incident) {
  const profile = incident?.viewer_dds_profile?.trim()
  if (profile && profile.toUpperCase() !== 'ДДС') return profile
  return incident?.source_snapshot?.scenario_services?.[0]?.name
    || incident?.source_snapshot?.notified_services?.[0]
    || profile
    || ''
}

// Локальный набор служб для подгонки фронтенда по присланному референсу.
// Адрес верхней плитки всегда берётся из открытой карточки, а не из макета.
export const previewServiceTiles = [
  'Служба 101',
  'Служба 104',
  'Служба 102',
  'Деп. ЖКХ',
  'ЦЭМП',
  'ЦОДД',
  'Мос.Без.',
  'Мослифт',
]

export const previewActionStatuses = {
  ACCEPT: 'ACCEPTED',
  REJECT: 'REJECTED',
  START_RESPONSE: 'RESPONSE_STARTED',
  MARK_ARRIVAL: 'ARRIVED',
  START_WORK: 'WORKING',
  COMPLETE_WORK: 'COMPLETED',
  REFUSE_WORK: 'WORK_REFUSED',
}

export function previewAvailableActions(entries) {
  const performed = new Set(entries.map((entry) => entry.action))
  if (performed.has('COMPLETE_WORK') || performed.has('REFUSE_WORK')) return []
  if (!performed.has('ACCEPT')) return performed.has('REJECT') ? ['ACCEPT'] : ['ACCEPT', 'REJECT']
  return referenceStatusActions.filter((action) => !performed.has(action))
}

export function previewCurrentStatus(entries) {
  return entries.at(-1)?.status || 'AWAITING_DECISION'
}
