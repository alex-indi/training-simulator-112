import assert from 'node:assert/strict'
import { test } from 'node:test'

import { previewActionStatuses, previewAvailableActions, previewCurrentStatus, previewServiceTiles, statusEditorActions } from './serviceStatusPreview.js'

test('demo tile names and order match the provided ARM-112 reference', () => {
  assert.deepEqual(previewServiceTiles, [
    'Служба 101', 'Служба 104', 'Служба 102', 'Деп. ЖКХ',
    'ЦЭМП', 'ЦОДД', 'Мос.Без.', 'Мослифт',
  ])
})

test('each demo service starts with a manual accept-or-reject decision', () => {
  assert.deepEqual(previewAvailableActions([]), ['ACCEPT', 'REJECT'])
  assert.equal(previewCurrentStatus([]), 'AWAITING_DECISION')
})

test('accepting one service enables later statuses without changing another service', () => {
  const service102 = [{ action: 'ACCEPT', status: 'ACCEPTED' }]
  assert.equal(previewCurrentStatus(service102), 'ACCEPTED')
  assert.deepEqual(previewAvailableActions(service102), ['START_RESPONSE', 'REFUSE_WORK', 'COMPLETE_WORK'])
  assert.deepEqual(previewAvailableActions([]), ['ACCEPT', 'REJECT'])
})

test('pencil dropdown contains only the three later statuses specified by the user', () => {
  assert.deepEqual(statusEditorActions(), ['START_RESPONSE', 'REFUSE_WORK', 'COMPLETE_WORK'])
})

test('completed service has no further status actions', () => {
  const history = [
    { action: 'ACCEPT', status: 'ACCEPTED' },
    { action: 'COMPLETE_WORK', status: 'COMPLETED' },
  ]
  assert.equal(previewCurrentStatus(history), 'COMPLETED')
  assert.deepEqual(previewAvailableActions(history), [])
})

test('later service status replaces the previous status on its upper tile', () => {
  const history = [
    { action: 'ACCEPT', status: previewActionStatuses.ACCEPT },
    { action: 'START_RESPONSE', status: previewActionStatuses.START_RESPONSE },
  ]
  assert.equal(previewCurrentStatus(history), 'RESPONSE_STARTED')
})
