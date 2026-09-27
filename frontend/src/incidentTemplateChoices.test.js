import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const component = readFileSync(new URL('./IncidentTemplates.jsx', import.meta.url), 'utf8')
const styles = readFileSync(new URL('./ScenarioLibrary.module.css', import.meta.url), 'utf8')

test('incident template choices keep each checkbox beside its text', () => {
  assert.match(component, /className=\{styles\.variantChoice\}/)
  assert.match(styles, /\.variantChoice\s*\{[^}]*display:\s*flex[^}]*align-items:\s*center/s)
  assert.match(styles, /\.variantChoice input\s*\{[^}]*margin:\s*0/s)
})
