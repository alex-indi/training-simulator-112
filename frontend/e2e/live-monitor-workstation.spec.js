import { expect, test } from '@playwright/test'

test('instructor follows the trainee open card and can inspect its history', async ({ page }) => {
  const teacher = { id: 1, username: 'instructor', full_name: 'Преподаватель', role: 'INSTRUCTOR' }
  const session = { id: 1, title: 'Занятие', topic: '', state: 'ACTIVE', mode: 'MANUAL',
    groups: [], runs: [], duration_minutes: null }
  let openId = 11
  const cards = [11, 12].map((id) => ({
    id, incident_number: `КП-${id}`, incident_type: 'Пожар', address: 'Учебная, 7',
    description: `Описание ${id}`, dds_status: 'ACCEPTED', source: '112',
    reported_at: '2026-09-27T09:00:00Z', delivered_at: '2026-09-27T09:00:01Z',
    opened_at: '2026-09-27T09:00:02Z', applicant_name: 'Иванов', applicant_phone: '123',
    source_snapshot: { features: ['Дым'] }, scenario_events: [], activities: [],
    actions: [{ id, status: 'ACCEPTED', created_at: '2026-09-27T09:00:03Z', comment: 'Принято' }],
    response_assignments: [],
  }))
  const run = () => ({ id: 2, workstation_number: 1, trainee_name: 'Обучаемый',
    dds_profile: 'ДДС', group_name: 'Группа', online: true, open_incident_id: openId,
    counts: { new: 0, working: 2, completed: 0, refusals: 0, deviations: 0 },
    active_incidents: cards, timeline: [], signals: [], current: cards[0], incidents: cards })

  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body
    if (path === '/api/users/demo') body = [teacher]
    else if (path === '/api/users/me') body = teacher
    else if (path === '/api/training/sessions') body = [session]
    else if (path === '/api/training/templates' || path === '/api/training/user-groups'
      || path === '/api/training/sessions/1/queue' || path === '/api/training/sessions/1/scenario-instances'
      || path === '/api/training/sessions/1/runs/2/notes') body = []
    else if (path === '/api/training/sessions/1') body = session
    else if (path === '/api/training/sessions/1/monitor') body = {
      session: { ...session, delivery_elapsed_seconds: 0 },
      counts: { online: 1, offline: 0, new: 0, working: 2, completed: 0, deviations: 0 },
      runs: [run()], attention: [],
    }
    else if (path === '/api/training/sessions/1/runs/2/workstation') body = run()
    await route.fulfill({ status: body === undefined ? 404 : 200, contentType: 'application/json',
      body: JSON.stringify(body ?? { detail: 'Unknown route' }) })
  })
  await page.addInitScript(() => {
    sessionStorage.setItem('ut112-demo-username', 'instructor')
    sessionStorage.setItem('ut112-instructor-session-id', '1')
  })
  await page.goto('/')
  await page.getByRole('button', { name: /АРМ 01.*Обучаемый/ }).click()
  await page.getByRole('button', { name: 'Открыть рабочее место' }).click()
  await expect(page.getByText('У обучаемого открыта карточка КП-11')).toBeVisible()
  await expect(page.getByText('Описание 11')).toBeVisible()
  await page.getByRole('button', { name: /КП-12/ }).click()
  await expect(page.getByText('Описание 12')).toBeVisible()
  await page.getByRole('button', { name: 'Вернуться к открытой карточке' }).click()
  await expect(page.getByText('Описание 11')).toBeVisible()

  openId = 12
  await expect.poll(async () => {
    await page.waitForTimeout(500)
    return page.getByText('У обучаемого открыта карточка КП-12').isVisible()
  }, { timeout: 12000 }).toBe(true)
  await expect(page.getByText('Описание 12')).toBeVisible()
})
