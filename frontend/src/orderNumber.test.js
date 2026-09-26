import assert from 'node:assert/strict'
import test from 'node:test'

import { initialOrderNumber } from './serviceStatusPreview.js'

test('later status changes reuse the order number from the initial decision', () => {
  assert.equal(initialOrderNumber([
    { is_system: true, action: null, order_number: null },
    { is_system: false, action: 'ACCEPT', order_number: ' 24154 ' },
    { is_system: false, action: 'START_RESPONSE', order_number: '99999' },
  ]), '24154')
})

test('rejected initial decision can also provide the order number', () => {
  assert.equal(initialOrderNumber([
    { is_system: false, action: 'REJECT', order_number: '317' },
  ]), '317')
})

test('missing initial decision leaves the field empty', () => {
  assert.equal(initialOrderNumber([
    { is_system: false, action: 'START_RESPONSE', order_number: '99999' },
  ]), '')
})
