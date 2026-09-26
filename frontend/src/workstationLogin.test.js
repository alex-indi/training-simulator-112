import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('./App.jsx', import.meta.url), 'utf8')

test('dispatcher selects a workstation during authorization', () => {
  assert.match(source, /className=\{styles\.loginIdentityRow\}/)
  assert.match(source, /aria-label="Рабочее место"/)
  assert.match(source, /Выберите АРМ/)
  assert.match(source, /workstation_number: Number\(loginWorkstation\)/)
  assert.match(source, /\/api\/training\/sessions\/\$\{loginSession\.id\}\/join/)
})

test('opening a new shared card claims it automatically without a banner', () => {
  assert.match(source, /incident\.can_claim[\s\S]*?\/api\/incidents\/\$\{incident\.id\}\/claim/)
  assert.doesNotMatch(source, /Новая карточка общей очереди/)
  assert.doesNotMatch(source, />Взять в работу</)
})

test('workstation enrollment panel is not rendered inside dispatcher workspace', () => {
  assert.doesNotMatch(source, /import TrainingEnrollment/)
  assert.doesNotMatch(source, /<TrainingEnrollment/)
})
