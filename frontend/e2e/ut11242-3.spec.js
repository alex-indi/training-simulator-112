import { expect, test } from '@playwright/test'

test('two groups prepare and approve mixed cards with no connected workstations', async ({ page }) => {
  const user = { id: 1, username: 'instructor', full_name: 'Преподаватель', role: 'INSTRUCTOR' }
  const session = {
    id: 4, title: 'Учебная смена', state: 'DRAFT', mode: 'FIXED_SET',
    duration_minutes: 30, delivery_interval_seconds: 120, delivery_order: 'SEQUENTIAL',
    workstation_count: 0, runs: [],
    groups: [
      { id: 6, name: 'Группа A', difficulty: 'Средняя', queue_mode: 'SHARED_QUEUE', run_ids: [] },
      { id: 7, name: 'Группа B', difficulty: 'Высокая', queue_mode: 'INDIVIDUAL_QUEUE', run_ids: [] },
    ],
    readiness: { participant_count: 0, group_count: 2, approved_count: 0, prepared_count: 0,
      profiles_assigned: 0, online_count: 0, offline_count: 0, warnings: [], can_start: false },
  }
  const templates = [
    { id: 10, name: 'Пожар в школе', description: 'Школа', difficulty: 3, object_rule: null, services: [] },
    { id: 11, name: 'ДТП', description: 'Дорога', difficulty: 3, object_rule: null, services: [] },
  ]
  const card = (id, template, groupId) => ({
    id, scenario_template_id: template.id, training_session_id: 4, training_group_id: groupId,
    status: 'DRAFT', template_snapshot: { name: template.name, variant_options: { floor: [1, 2] } },
    object_snapshot: { name: `Объект ${id}`, address: `Адрес ${id}` },
    initial_state_snapshot: { variant_facts: { floor: 1 }, render: { rendered_text: `Текст ${id}` } },
    events: [],
  })
  let instances = [
    ...Array.from({ length: 5 }, (_, index) => card(index + 1, templates[0], 6)),
    ...Array.from({ length: 3 }, (_, index) => card(index + 6, templates[1], 6)),
    ...Array.from({ length: 2 }, (_, index) => card(index + 9, templates[1], 7)),
  ]
  let generatedFor = null
  let generatedPayload = null
  let approved = []
  const rerenderedIds = []
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    let body = null
    if (path === '/api/users/demo') body = [user]
    else if (path === '/api/users/me') body = user
    else if (path === '/api/training/sessions') body = [session]
    else if (path === '/api/training/templates') body = []
    else if (path === '/api/training/user-groups') body = []
    else if (path === '/api/training/sessions/4/queue') body = []
    else if (path === '/api/training/sessions/4/scenario-instances') body = instances
    else if (path === '/api/scenario-templates/catalog') body = { services: [], object_types: [] }
    else if (path === '/api/scenario-templates' && method === 'GET') body = { items: templates, total: 2 }
    else if (path === '/api/scenario-templates/11/batch') {
      generatedPayload = route.request().postDataJSON()
      generatedFor = generatedPayload.training_group_id
      const created = card(11, templates[1], generatedFor)
      instances = [...instances, created]
      body = [created]
    } else if (path === '/api/training/sessions/4/groups/6/cards/approve' || path === '/api/training/sessions/4/groups/7/cards/approve') {
      const groupId = Number(path.split('/')[6])
      approved.push(groupId)
      instances = instances.map((item) => item.training_group_id === groupId ? { ...item, status: 'CONFIRMED' } : item)
      body = { count: instances.filter((item) => item.training_group_id === groupId).length, approved: true }
    } else if (path.match(/^\/api\/scenario-instances\/\d+\/rerender-initial-message$/)) {
      const id = Number(path.split('/')[3])
      rerenderedIds.push(id)
      instances = instances.map((item) => item.id === id ? { ...item, initial_state_snapshot: { ...item.initial_state_snapshot, render: { rendered_text: 'Новый текст' } } } : item)
      body = instances.find((item) => item.id === id)
    } else if (path.match(/^\/api\/scenario-instances\/\d+\/variant-facts$/)) {
      const id = Number(path.split('/')[3])
      const facts = route.request().postDataJSON()
      instances = instances.map((item) => item.id === id ? { ...item,
        initial_state_snapshot: { ...item.initial_state_snapshot, variant_facts: facts } } : item)
      body = instances.find((item) => item.id === id)
    } else if (path.match(/^\/api\/scenario-instances\/\d+$/) && method === 'DELETE') {
      instances = instances.filter((item) => item.id !== Number(path.split('/')[3]))
      body = {}
    }
    await route.fulfill({ status: body === null ? 404 : 200,
      contentType: 'application/json', body: JSON.stringify(body ?? { detail: 'Unknown route' }) })
  })
  await page.addInitScript(() => sessionStorage.setItem('ut112-demo-username', 'instructor'))
  await page.goto('/')
  await page.getByRole('button', { name: /Учебная смена/ }).click()
  await page.getByRole('button', { name: /Карточки происшествий/ }).click()
  const groupA = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Группа A' }) })
  const groupB = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Группа B' }) })
  await expect(groupA).toContainText('Подготовлено 8 карточек')
  await expect(groupA).toContainText('Пожар в школе · 5')
  await expect(groupA).toContainText('ДТП · 3')
  await expect(groupB).toContainText('Подготовлено 2 карточек')
  await groupA.getByRole('button', { name: 'Перегенерировать текст', exact: true }).click()
  await expect(groupA.getByLabel('Текст карточки')).toHaveValue('Новый текст')
  await groupA.getByLabel('Выбрать карточку 1 для перегенерации').check()
  await groupA.getByLabel('Выбрать карточку 2 для перегенерации').check()
  await groupA.getByRole('button', { name: 'Перегенерировать тексты выбранных' }).click()
  await expect(groupA).toContainText('Тексты обновлены: 2 карточек')
  expect(rerenderedIds).toEqual([1, 1, 2])
  await groupA.getByLabel('Этаж').selectOption('2')
  await groupA.getByRole('button', { name: 'Сохранить условия' }).click()
  await expect(groupA).toContainText('Этаж: 2')
  await groupA.getByRole('button', { name: 'Исключить' }).click()
  await expect(groupA).toContainText('Подготовлено 7 карточек')
  await groupA.getByRole('button', { name: '+ Добавить карточки по сценарию' }).click()
  const picker = page.getByRole('dialog', { name: 'Выберите сценарий' })
  await picker.getByRole('button', { name: /ДТП/ }).click()
  await expect(picker.getByLabel('Использовать разные объекты')).toHaveCount(0)
  await picker.getByLabel('Количество карточек').fill('1')
  await picker.getByRole('button', { name: 'Сформировать', exact: true }).click()
  await picker.getByRole('button', { name: 'Добавить в набор группы' }).click()
  expect(generatedFor).toBe(6)
  expect(generatedPayload).not.toHaveProperty('different_objects')
  await expect(groupA).toContainText('Подготовлено 8 карточек')
  await groupA.getByRole('button', { name: 'Утвердить набор' }).click()
  await groupB.getByRole('button', { name: 'Утвердить набор' }).click()
  expect(approved).toEqual([6, 7])
  await expect(groupA).toContainText('набор утверждён')
  await expect(groupB).toContainText('набор утверждён')
  expect(session.runs).toEqual([])
})
