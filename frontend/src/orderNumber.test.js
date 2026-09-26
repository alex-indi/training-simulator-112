import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { initialOrderNumber } from './serviceStatusPreview.js'

const appSource = readFileSync(new URL('./App.jsx', import.meta.url), 'utf8')

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

test('status editor prefills the remembered order number and keeps it editable', () => {
  assert.match(appSource, /setActionOrderNumber\(initialOrderNumber\(/)
  assert.match(appSource, /value=\{actionOrderNumber\} onChange=\{\(event\) => setActionOrderNumber\(event\.target\.value\)\}/)
  assert.doesNotMatch(appSource, /const openStatusEditor = \(\) => \{[\s\S]*?setActionOrderNumber\(''\)/)
})
