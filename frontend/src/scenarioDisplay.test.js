import assert from 'node:assert/strict'
import test from 'node:test'

import { compactInstanceName, compactObjectName } from './scenarioDisplay.js'

test('shortens the legal organization prefix of an educational object', () => {
  assert.equal(
    compactObjectName('Государственное бюджетное образовательное учреждение города Москвы гимназия № 1597'),
    'ГБОУ г. Москвы Гимназия № 1597',
  )
})

test('shortens a scientific institution legal form', () => {
  assert.equal(
    compactObjectName('Государственное автономное научное учреждение города Москвы "Институт гуманитарного развития мегаполиса"'),
    'ГАНУ г. Москвы "Институт гуманитарного развития мегаполиса"',
  )
})

test('shortens an autonomous educational institution legal form', () => {
  assert.equal(
    compactObjectName('Государственное автономное образовательное учреждение города Москвы центр образования № 548 "Царицыно"'),
    'ГАОУ г. Москвы Центр образования № 548 "Царицыно"',
  )
})

test('shows only the incident title in the review card heading', () => {
  assert.equal(compactInstanceName({
    name: 'Длинное сохранённое название',
    template_snapshot: { name: 'Задымление в учебном заведении' },
    object_snapshot: { name: 'Государственное бюджетное образовательное учреждение города Москвы детский сад № 1517' },
  }), 'Задымление в учебном заведении')
})
