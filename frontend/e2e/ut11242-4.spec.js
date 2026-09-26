import { expect, test } from '@playwright/test'

test('connection step shows groups and launches the live monitor', async ({ page }) => {
  const teacher = { id: 1, username: 'instructor', full_name: 'Преподаватель', role: 'INSTRUCTOR' }
  const groups = [
    { id: 6, name: 'Группа A', difficulty: 'Средняя', queue_mode: 'SHARED_QUEUE', run_ids: [1, 2] },
    { id: 7, name: 'Группа B', difficulty: 'Высокая', queue_mode: 'INDIVIDUAL_QUEUE', run_ids: [3, 4] },
  ]
  const runs = Array.from({ length: 4 }, (_, index) => ({
    id: index + 1, trainee_id: index + 2, workstation_number: index + 1,
    trainee_name: `Обучаемый ${index + 1}`, group_id: index < 2 ? 6 : 7,
    dds_profile: 'ДДС', difficulty: index < 2 ? 'Средняя' : 'Высокая',
    queue_mode: index < 2 ? 'SHARED_QUEUE' : 'INDIVIDUAL_QUEUE', online: true,
  }))
  const session = {
    id: 4, title: 'Практическое занятие', state: 'DRAFT', mode: 'FIXED_SET',
    duration_minutes: null, delivery_interval_seconds: null, delivery_order: 'SEQUENTIAL',
    workstation_count: 30, groups, runs,
    readiness: { participant_count: 4, group_count: 2, approved_count: 14,
      prepared_count: 14, profiles_assigned: 4, online_count: 4, offline_count: 0,
      warnings: [], can_start: true },
  }
  const cards = [
    ...Array.from({ length: 8 }, (_, index) => ({ id: index + 1, training_group_id: 6, status: 'CONFIRMED' })),
    ...Array.from({ length: 6 }, (_, index) => ({ id: index + 9, training_group_id: 7, status: 'CONFIRMED' })),
  ]
  let prepares = 0
  let starts = 0
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    let body = null
    if (path === '/api/users/demo') body = [teacher]
    else if (path === '/api/users/me') body = teacher
    else if (path === '/api/training/sessions') body = [session]
    else if (path === '/api/training/templates') body = []
    else if (path === '/api/training/user-groups') body = []
    else if (path === '/api/training/sessions/4/queue') body = []
    else if (path === '/api/training/sessions/4/scenario-instances') body = cards
    else if (path === '/api/training/sessions/4') body = session
    else if (path === '/api/training/sessions/4/assign' && method === 'POST') {
      const assignment = route.request().postDataJSON()
      const run = runs.find((item) => item.id === assignment.run_ids[0])
      run.group_id = assignment.group_id
      groups.forEach((group) => { group.run_ids = runs.filter((item) => item.group_id === group.id).map((item) => item.id) })
      body = session
    } else if (path === '/api/training/sessions/4/prepare') {
      prepares += 1
      session.state = 'READY'
      body = session
    } else if (path === '/api/training/sessions/4/start') {
      starts += 1
      session.state = 'ACTIVE'
      body = session
    } else if (path === '/api/training/sessions/4/monitor') {
      body = {
        session: { id: 4, title: session.title, topic: '', state: session.state,
          duration_minutes: null, delivery_elapsed_seconds: 0 },
        counts: { online: 4, offline: 0, new: 0, working: 0, completed: 0, deviations: 0 },
        runs: runs.map((run) => ({ ...run, group_name: groups.find((group) => group.id === run.group_id)?.name,
          counts: { new: 0, working: 0, completed: 0, refusals: 0, deviations: 0 },
          active_incidents: [], signals: [], timeline: [], current: null })),
        attention: [],
      }
    }
    await route.fulfill({ status: body === null ? 404 : 200,
      contentType: 'application/json', body: JSON.stringify(body ?? { detail: 'Unknown route' }) })
  })
  await page.addInitScript(() => sessionStorage.setItem('ut112-demo-username', 'instructor'))
  await page.goto('/')
  await page.getByRole('button', { name: /Практическое занятие/ }).click()
  await page.getByRole('button', { name: 'Подключение и запуск' }).click()
  await expect(page.getByText('8 карточек · ✓ Набор готов')).toBeVisible()
  await expect(page.getByText('6 карточек каждому · ✓ Набор готов')).toBeVisible()
  await page.getByLabel('Группа для АРМ 1').selectOption('7')
  await expect(page.getByText('3 подключено · Личный пул')).toBeVisible()
  await page.getByLabel('Группа для АРМ 1').selectOption('6')
  await expect(page.getByText('2 подключено · Общий пул')).toBeVisible()
  await page.getByRole('button', { name: 'Начать занятие' }).click()
  await expect(page.getByRole('heading', { name: 'Live-монитор' })).toBeVisible()
  await expect(page.getByRole('button', { name: /АРМ 01.*Группа A/ })).toBeVisible()
  expect(prepares).toBe(1)
  expect(starts).toBe(1)
})
