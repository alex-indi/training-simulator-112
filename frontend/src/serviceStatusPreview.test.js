import assert from 'node:assert/strict'
import { test } from 'node:test'

import { incidentServiceName, statusEditorActions } from './serviceStatusPreview.js'

test('generic DDS profile uses the service assigned by the scenario', () => {
  assert.equal(incidentServiceName({
    viewer_dds_profile: 'ДДС',
    source_snapshot: { scenario_services: [{ service_id: 1, name: 'Служба 101' }] },
  }), 'Служба 101')
})

test('explicit DDS profile stays the assigned service', () => {
  assert.equal(incidentServiceName({
    viewer_dds_profile: 'Служба 102',
    source_snapshot: { scenario_services: [{ service_id: 1, name: 'Служба 101' }] },
  }), 'Служба 102')
})

test('status editor exposes all response statuses supported by backend', () => {
  assert.deepEqual(statusEditorActions(), [
    'START_RESPONSE',
    'MARK_ARRIVAL',
    'START_WORK',
    'REFUSE_WORK',
    'COMPLETE_WORK',
  ])
})
