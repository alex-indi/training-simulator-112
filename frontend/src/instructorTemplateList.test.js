import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('./InstructorWorkspace.jsx', import.meta.url), 'utf8')

test('lesson templates use the shared compact list style', () => {
  assert.match(
    source,
    /<h3>Шаблоны занятий<\/h3><div className=\{styles\.itemList\}>/,
  )
  assert.doesNotMatch(
    source,
    /<h3>Шаблоны занятий<\/h3><div className=\{styles\.cards\}>/,
  )
})
