import { expect, request as apiRequest, test } from '@playwright/test'

async function json(response) {
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

test('trainee sees a completed lesson without a score until instructor confirms it', async ({ browser }) => {
  const apiBase = process.env.E2E_API_URL
  const instructorApi = await apiRequest.newContext({ baseURL: apiBase, extraHTTPHeaders: { 'X-Demo-User': 'instructor' } })
  const traineeApi = await apiRequest.newContext({ baseURL: apiBase, extraHTTPHeaders: { 'X-Demo-User': 'trainee' } })
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

    const provisional = (await json(await traineeApi.get('/api/training/my/results')))
      .find((row) => row.session_id === session.id)
    expect(provisional).toBeTruthy()
    expect(provisional.result.final_score).toBeNull()
    expect(provisional.result.confirmed_at).toBeNull()
    expect(provisional.result).not.toHaveProperty('automatic_score')
    await trainee.addInitScript(() => {
      sessionStorage.setItem('ut112-demo-username', 'trainee')
      sessionStorage.setItem('ut112-workstation-number', '1')
    })
    await trainee.goto('/')
    await trainee.getByRole('button', { name: /Результаты занятий/ }).click()
    const result = trainee.getByRole('dialog', { name: 'Результаты занятий' })
      .getByRole('button', { name: new RegExp(title) })
    await expect(result).toContainText('Нет оценки')

    await json(await instructorApi.post(`/api/training/sessions/${session.id}/runs/${joined.runs[0].id}/finalize`, {
      data: { final_score: 80, final_comment: 'Хорошая работа', reason: 'Проверен итог занятия' },
    }))
    const confirmed = (await json(await traineeApi.get('/api/training/my/results')))
      .find((row) => row.session_id === session.id)
    expect(confirmed.result.final_score).toBe(80)
    expect(confirmed.result.confirmed_at).toBeTruthy()
    await trainee.reload()
    await trainee.getByRole('button', { name: /Результаты занятий/ }).click()
    await expect(trainee.getByRole('dialog', { name: 'Результаты занятий' })
      .getByRole('button', { name: new RegExp(title) })).toContainText('Итог: 80 / 100')
  } finally {
    await trainee.close()
    await instructorApi.dispose()
    await traineeApi.dispose()
  }
})
