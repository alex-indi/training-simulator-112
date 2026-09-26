import { expect, test } from '@playwright/test'

test('new scenario from the picker keeps the selected session and group', async ({ page }) => {
  const user = { id: 1, username: 'instructor', full_name: 'Преподаватель', role: 'INSTRUCTOR' }
  const session = {
    id: 4, title: 'Учебная смена', state: 'DRAFT', mode: 'FIXED_SET',
    duration_minutes: 30, delivery_interval_seconds: 120, delivery_order: 'SEQUENTIAL',
    workstation_count: 1, runs: [],
    groups: [{ id: 6, name: 'Дежурная группа', difficulty: 'Средняя', queue_mode: 'SHARED_QUEUE', run_ids: [] }],
    readiness: { participant_count: 0, group_count: 1, approved_count: 0, prepared_count: 0,
      profiles_assigned: 0, online_count: 0, offline_count: 0, warnings: [], can_start: false },
  }
  let saved = null
  let batchInput = null
  let confirmed = null
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    let body = null
    if (path === '/api/users/demo') body = [user]
    else if (path === '/api/users/me') body = user
    else if (path === '/api/training/sessions') body = [session]
    else if (path === '/api/training/templates') body = []
    else if (path === '/api/training/sessions/4/queue') body = []
    else if (path === '/api/training/sessions/4/scenario-instances') body = []
    else if (path === '/api/scenario-instances') body = []
    else if (path === '/api/scenario-templates/catalog') body = { rules: [], object_types: [], services: [], objects: [], tags: [], authors: [] }
    else if (path === '/api/scenario-templates' && method === 'GET') body = { items: saved?.status === 'READY' ? [saved] : [], total: saved ? 1 : 0, offset: 0, limit: 200 }
    else if (path === '/api/scenario-templates' && method === 'POST') {
      saved = { id: 12, ...route.request().postDataJSON(), status: 'DRAFT', created_by_user_id: 1 }
      body = saved
    } else if (path === '/api/scenario-templates/12/validate') body = { errors: [], matching_object_count: 1 }
    else if (path === '/api/scenario-templates/12/ready') {
      saved = { ...saved, status: 'READY' }
      body = saved
    } else if (path === '/api/scenario-templates/12/batch') {
      batchInput = route.request().postDataJSON()
      body = [{ id: 30, scenario_template_id: 12, training_session_id: 4, status: 'DRAFT',
        template_snapshot: { variant_options: {} }, object_snapshot: { name: 'Школа №1', address: 'Школьная, 1' },
        initial_state_snapshot: { variant_facts: {}, render: { rendered_text: 'дым в школе', render_origin: 'GENERATED' } },
        events: [] }]
    } else if (path === '/api/training/sessions/4/scenario-instances/confirm-batch') {
      confirmed = route.request().postDataJSON()
      body = { count: 1, queue_item_ids: [90] }
    }
    await route.fulfill({ status: body === null ? 404 : 200,
      contentType: 'application/json', body: JSON.stringify(body ?? { detail: 'Unknown route' }) })
  })
  await page.addInitScript(() => sessionStorage.setItem('ut112-demo-username', 'instructor'))
  await page.goto('/')
  await page.getByRole('button', { name: /Учебная смена/ }).click()
  await page.getByRole('button', { name: /Задания/ }).click()
  await page.getByRole('button', { name: '+ Добавить карточки по сценарию' }).click()
  const picker = page.getByRole('dialog', { name: 'Выберите сценарий' })
  await picker.getByRole('button', { name: '+ Создать новый сценарий' }).click()
  await picker.getByRole('navigation', { name: 'Разделы сценария' }).getByRole('button', { name: 'Основное' }).click()
  await picker.getByLabel('Название', { exact: true }).fill('Пожар в школе')
  await picker.getByRole('button', { name: 'Сохранить и использовать' }).click()
  await expect(picker.getByRole('heading', { name: 'Пожар в школе' })).toBeVisible()
  await expect(picker.getByLabel('Занятие')).toHaveCount(0)
  await expect(picker.getByLabel('Группа')).toHaveCount(0)
  await picker.getByRole('button', { name: 'Сформировать', exact: true }).click()
  expect(batchInput.training_session_id).toBe(4)
  expect(saved.status).toBe('READY')
  await picker.getByRole('button', { name: 'Утвердить набор и добавить в занятие' }).click()
  expect(confirmed).toEqual({ instance_ids: [30], training_group_id: 6 })
})

test('ready scenarios open an editable copy and archive stays author-only', async ({ page }) => {
  const user = { id: 1, username: 'instructor', full_name: 'Преподаватель', role: 'INSTRUCTOR' }
  const own = { id: 7, name: 'Мой сценарий', description: '', status: 'READY', difficulty: 3,
    created_by_user_id: 1, classifier_rule_id: null, object_rule: null, variant_options: {},
    initial_title: '', initial_description: '', initial_caller_text: '', events: [], services: [],
    expected_actions: [], criteria: [] }
  const other = { ...own, id: 8, name: 'Сценарий коллеги', created_by_user_id: 2 }
  let copy = null
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body = null
    if (path === '/api/users/demo') body = [user]
    else if (path === '/api/users/me') body = user
    else if (path === '/api/training/sessions') body = []
    else if (path === '/api/training/templates') body = []
    else if (path === '/api/scenario-instances') body = []
    else if (path === '/api/scenario-templates/catalog') body = { rules: [], object_types: [], services: [], objects: [], tags: [], authors: [] }
    else if (path === '/api/scenario-templates') body = { items: [own, other], total: 2, offset: 0, limit: 24 }
    else if (path === '/api/scenario-templates/7/duplicate') {
      copy = { ...own, id: 13, name: 'Мой сценарий — копия', status: 'DRAFT' }
      body = copy
    }
    await route.fulfill({ status: body === null ? 404 : 200,
      contentType: 'application/json', body: JSON.stringify(body ?? { detail: 'Unknown route' }) })
  })
  await page.addInitScript(() => sessionStorage.setItem('ut112-demo-username', 'instructor'))
  await page.goto('/')
  await page.getByRole('button', { name: 'Библиотека сценариев' }).click()
  const ownCard = page.getByRole('article').filter({ hasText: 'Мой сценарий' })
  const otherCard = page.getByRole('article').filter({ hasText: 'Сценарий коллеги' })
  await expect(ownCard.getByRole('button', { name: 'Архивировать' })).toBeVisible()
  await expect(otherCard.getByRole('button', { name: 'Архивировать' })).toHaveCount(0)
  await ownCard.getByRole('button', { name: 'Изменить' }).click()
  expect(copy.status).toBe('DRAFT')
  await expect(page.getByRole('heading', { name: 'Мой сценарий — копия' })).toBeVisible()
  await page.getByRole('navigation', { name: 'Разделы сценария' }).getByRole('button', { name: 'Основное' }).click()
  await expect(page.getByLabel('Название', { exact: true })).toBeEnabled()
})
