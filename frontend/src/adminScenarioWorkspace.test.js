import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('./AdminWorkspace.jsx', import.meta.url), 'utf8')

test('admin scenarios use the current incident template list', () => {
  assert.match(source, /\['scenarios', 'Шаблоны инцидентов'\]/)
  assert.match(source, /import IncidentTemplates from '.\/IncidentTemplates\.jsx'/)
  assert.match(source, /renderScenarios = \(\) => <IncidentTemplates/)
  assert.doesNotMatch(source, /renderScenarios = \(\) => <ScenarioLibrary/)
})
