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
