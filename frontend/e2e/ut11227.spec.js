import { expect, test } from '@playwright/test'

test('instructor puts a confirmed instance into the existing queue', async ({ page }) => {
  const user = { id: 1, username: 'instructor', full_name: 'Преподаватель', role: 'INSTRUCTOR' }
  const training = {
    id: 4, title: 'Учебная смена', topic: 'Пожар', state: 'DRAFT', mode: 'FIXED_SET',
    duration_minutes: 30, delivery_interval_seconds: 120, delivery_order: 'SEQUENTIAL',
    workstation_count: 1, runs: [{ id: 8, trainee_id: 2, trainee_name: 'Курсант',
      workstation_number: 1, dds_profile: 'Пожарная охрана', queue_mode: 'INDIVIDUAL_QUEUE',
      online: true, group_id: null }], groups: [],
    readiness: { participant_count: 1, workstation_count: 1, group_count: 0,
      profiles_assigned: 1, online_count: 1, offline_count: 0, warnings: [],
      can_start: false, prepared_count: 0, approved_count: 0 },
  }
  const instance = { id: 42, name: 'Пожар в школе №1', status: 'CONFIRMED', difficulty: 3,
    object_snapshot: { name: 'Школа №1', address: 'Пехотная, 1' },
    events: [{ id: 70, offset_seconds: 0, title: 'Звонок' },
      { id: 71, offset_seconds: 60, title: 'Уточнение' }] }
  let queue = []
  let submitted = null
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body = null
    if (path === '/api/users/demo') body = [user]
    else if (path === '/api/users/me') body = user
    else if (path === '/api/training/sessions') body = [training]
    else if (path === '/api/training/templates') body = []
    else if (path === '/api/training/sessions/4/queue') body = queue
    else if (path === '/api/training/sessions/4/scenario-instances') body = [instance]
    else if (path === '/api/scenario-instances/42/materialize') {
      submitted = route.request().postDataJSON()
      queue = [{ id: 51, scenario_instance_id: 42, title: instance.name,
        training_run_id: 8, training_group_id: null, position: 1, approved: false,
        delivery_state: 'PENDING', snapshot: { incident_type: 'Пожар',
          address: 'Пехотная, 1', description: 'Первый звонок' } }]
      body = { queue_item_id: 51, incident_id: null }
    }
    await route.fulfill({ status: body === null ? 404 : 200,
      contentType: 'application/json', body: JSON.stringify(body ?? { detail: 'Unknown route' }) })
  })
  await page.addInitScript(() => sessionStorage.setItem('ut112-demo-username', 'instructor'))
  await page.goto('/')
  await page.getByRole('button', { name: /Учебная смена/ }).click()
  await page.getByRole('button', { name: /Задания/ }).click()
  await expect(page.getByText('Пожар в школе №1')).toBeVisible()
  await page.getByLabel('Очередь для экземпляра 42').selectOption('run:8')
  await page.getByRole('button', { name: 'Добавить в очередь' }).click()
  await expect(page.getByText('В очереди')).toBeVisible()
  expect(submitted).toEqual({ training_run_id: 8 })
})
