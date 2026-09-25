import { expect, test } from '@playwright/test'

const user = { id: 1, username: 'instructor', full_name: 'Преподаватель', role: 'INSTRUCTOR' }
const template = {
  id: 7, name: 'Пожар в школе', description: 'Учебная ситуация', status: 'READY', difficulty: 3,
  classifier_rule_id: 9, incident_type: 'Пожар', created_by_user_id: 1,
  initial_title: 'Дым', initial_description: 'Сообщение о дыме', initial_caller_text: '',
  object_rule: { selection_mode: 'GENERIC', object_type_id: 5, specific_object_id: null, required_tags: [] },
  events: [{ id: 1, offset_seconds: 0, event_type: 'INITIAL_REPORT', title: 'Заявитель', description: 'Дым', source_type: 'CALLER' }],
  services: [{ service_id: 3, source: 'CLASSIFIER' }], expected_actions: [], criteria: [],
}
const object = { id: 11, name: 'Школа №1', address: 'Пехотная, 1', district: 'Щукино' }
const session = { id: 4, title: 'Учебная смена', state: 'DRAFT', mode: 'MANUAL', runs: [], groups: [], workstation_count: 1 }

test('instructor previews, generates and attaches a scenario instance', async ({ page }) => {
  let instance = null
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    let body = null
    if (path === '/api/users/demo') body = [user]
    else if (path === '/api/users/me') body = user
    else if (path === '/api/training/sessions') body = [session]
    else if (path === '/api/training/templates') body = []
    else if (path === '/api/scenario-templates/catalog') body = { rules: [], object_types: [{ id: 5, name: 'Школа', code: 'SCHOOL' }], services: [{ id: 3, name: 'Пожарная охрана' }], objects: [], tags: [], authors: [{ id: 1, name: 'Преподаватель' }] }
    else if (path === '/api/scenario-templates') body = { items: [template], total: 1, offset: 0, limit: 24 }
    else if (path === '/incident-classifier/rules/9') body = { id: 9, final_incident_type: 'Пожар', incident_group: 'Пожар', source_reference: 'SRC:1', features: [], services: [] }
    else if (path.endsWith('/generate-preview')) {
      const input = route.request().postDataJSON()
      body = { matching_objects: [object], matching_object_count: 1, object_snapshot: input.object_id ? object : null, classifier_snapshot: { final_incident_type: 'Пожар' }, service_snapshot: [{ service_id: 3, official_name: 'Пожарная охрана' }], events: [{ offset_seconds: 0, title: 'Заявитель', description: 'Дым' }] }
    } else if (path.endsWith('/instances') && route.request().method() === 'POST') {
      instance = { id: 42, name: 'Пожар в школе — Школа №1', difficulty: 3, training_session_id: null, object_snapshot: object, classifier_snapshot: { final_incident_type: 'Пожар' }, service_snapshot: [{ service_id: 3, official_name: 'Пожарная охрана' }], events: [{ offset_seconds: 0, title: 'Заявитель', description: 'Дым' }] }
      body = instance
    } else if (path.endsWith('/attach')) {
      instance = { ...instance, training_session_id: 4 }
      body = instance
    }
    await route.fulfill({ status: body === null ? 404 : 200, contentType: 'application/json', body: JSON.stringify(body ?? { detail: 'Unknown route' }) })
  })
  await page.addInitScript(() => sessionStorage.setItem('ut112-demo-username', 'instructor'))
  await page.goto('/')
  await page.getByRole('button', { name: 'Библиотека сценариев' }).click()
  await page.getByRole('button', { name: /Пожар в школе/ }).click()
  await page.getByRole('button', { name: 'Сгенерировать экземпляр' }).click()
  await page.getByLabel('Подходящий объект').selectOption('11')
  await page.getByRole('button', { name: 'Показать предпросмотр' }).click()
  await expect(page.getByText('Пехотная, 1', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Сгенерировать экземпляр' }).click()
  await expect(page.getByRole('heading', { name: 'Экземпляр #42' })).toBeVisible()
  await page.getByLabel('Использовать в занятии').selectOption('4')
  await page.getByRole('button', { name: 'Привязать к занятию' }).click()
  await expect(page.getByText('Занятие: #4')).toBeVisible()
})
