import { expect, request as apiRequest, test } from '@playwright/test'

async function json(response) {
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

test('instructor confirms result before trainee can see it', async ({ browser }) => {
  const apiBase = process.env.E2E_API_URL
  const instructorApi = await apiRequest.newContext({ baseURL: apiBase, extraHTTPHeaders: { 'X-Demo-User': 'instructor' } })
  const traineeApi = await apiRequest.newContext({ baseURL: apiBase, extraHTTPHeaders: { 'X-Demo-User': 'trainee' } })
  const instructor = await browser.newPage()
  const trainee = await browser.newPage()
  try {
    const title = `UT112-22-${Date.now()}`
    const session = await json(await instructorApi.post('/api/training/sessions', { data: { title, mode: 'MANUAL', workstation_count: 1 } }))
    await json(await traineeApi.post(`/api/training/sessions/${session.id}/join`, { data: { workstation_number: 1 } }))
    const joined = await json(await instructorApi.get(`/api/training/sessions/${session.id}`))
    await json(await instructorApi.post(`/api/training/sessions/${session.id}/assign`, { data: { run_ids: [joined.runs[0].id], dds_profile: 'ДДС района' } }))
    const queue = await json(await instructorApi.post(`/api/training/sessions/${session.id}/queue`, { data: {
      training_run_id: joined.runs[0].id, title: 'Проверочная карточка',
      snapshot: { incident_number: `КП-${Date.now()}`, reported_at: new Date().toISOString(), source: 'Система-112', address: 'Учебная улица, 1', description: 'Учебное происшествие', incident_type: 'Проверка', notified_services: ['ДДС района'] },
    } }))
    await json(await instructorApi.post(`/api/training/sessions/${session.id}/queue/approve`))
    await json(await instructorApi.post(`/api/training/sessions/${session.id}/prepare`))
    await json(await instructorApi.post(`/api/training/sessions/${session.id}/start`))
    await json(await instructorApi.post(`/api/training/sessions/${session.id}/manual-cards`, { data: { scenario_id: queue[0].scenario_id, target: 'RUN', target_id: joined.runs[0].id } }))
    await json(await instructorApi.post(`/api/training/sessions/${session.id}/finish`, { data: { mode: 'IMMEDIATE' } }))

    expect((await json(await traineeApi.get('/api/training/my/results'))).some((row) => row.session_id === session.id)).toBeFalsy()
    await instructor.addInitScript(() => sessionStorage.setItem('ut112-demo-username', 'instructor'))
    await instructor.goto('/')
    await instructor.getByRole('button', { name: new RegExp(title) }).click()
    await expect(instructor.getByRole('heading', { name: `Разбор · ${title}` })).toBeVisible()
    await expect(instructor.getByText('Предварительная оценка системы')).toBeVisible()
    await expect(instructor.getByText('Карточка не завершена', { exact: false })).toBeVisible()
    await instructor.getByLabel('Причина решения или изменения').fill('Проверена история карточки')
    const deviations = instructor.locator('article[class*="deviation"]')
    const count = await deviations.count()
    for (let index = 0; index < count; index += 1) {
      await deviations.nth(index).getByRole('button', { name: 'Подтвердить' }).click()
    }
    await instructor.getByLabel('Комментарий преподавателя').fill('Хорошая работа')
    await instructor.getByLabel('Причина решения или изменения').fill('Проверен итог занятия')
    await instructor.getByRole('button', { name: 'Подтвердить итог' }).click()
    await expect(instructor.getByText(`История корректировок (${count + 1})`)).toBeVisible()

    await trainee.addInitScript(() => sessionStorage.setItem('ut112-demo-username', 'trainee'))
    await trainee.goto('/')
    const history = trainee.getByText(/Результаты завершённых занятий/)
    await expect(history).toBeVisible()
    await history.click()
    await expect(trainee.getByRole('heading', { name: new RegExp(title) })).toBeVisible()
    await expect(trainee.locator('article').filter({ hasText: title }).getByText('Хорошая работа')).toBeVisible()
  } finally {
    await instructor.close()
    await trainee.close()
    await instructorApi.dispose()
    await traineeApi.dispose()
  }
})
