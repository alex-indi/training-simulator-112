import { expect, request as apiRequest, test } from '@playwright/test'

const apiBase = process.env.E2E_API_URL

async function json(response) {
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

test('MVP: общий пул, claim, принятие и сообщение бригады 101', async ({ page }) => {
  test.setTimeout(70000)
  const instructor = await apiRequest.newContext({
    baseURL: apiBase,
    extraHTTPHeaders: { 'X-Demo-User': 'instructor' },
  })
  const trainee = await apiRequest.newContext({
    baseURL: apiBase,
    extraHTTPHeaders: { 'X-Demo-User': 'trainee' },
  })

  try {
    const title = `MVP smoke ${Date.now()}`
    const session = await json(await instructor.post('/api/training/sessions', {
      data: { title, mode: 'FIXED_SET', workstation_count: 1 },
    }))

    await json(await trainee.post(`/api/training/sessions/${session.id}/join`, {
      data: { workstation_number: 1 },
    }))
    await page.addInitScript((id) => {
      sessionStorage.setItem('ut112-demo-username', 'trainee')
      sessionStorage.setItem('ut112-trainee-session-id', String(id))
      sessionStorage.setItem('ut112-workstation-number', '1')
    }, session.id)
    await page.goto('/')
    await expect(page.getByRole('combobox', { name: 'Текущий пользователь' })).toHaveValue('trainee')
    await expect.poll(async () => {
      const sessions = await json(await trainee.get('/api/training/sessions'))
      return sessions.find((item) => item.id === session.id)?.own_run?.id
    }).toBeTruthy()

    const grouped = await json(await instructor.post(`/api/training/sessions/${session.id}/groups`, {
      data: {
        name: `Группа ${session.id}`,
        dds_profile: 'ДДС района',
        difficulty: 'Средняя',
        queue_mode: 'SHARED_QUEUE',
      },
    }))
    const group = grouped.groups[0]
    const assigned = await json(await instructor.post(`/api/training/sessions/${session.id}/assign`, {
      data: { run_ids: grouped.runs.map((run) => run.id), group_id: group.id },
    }))
    expect(assigned.runs[0].group_id).toBe(group.id)

    const templates = await json(await instructor.get('/api/scenario-templates/simple'))
    const template = templates.find((item) => item.name === 'Пожар в образовательном учреждении')
    expect(template).toBeTruthy()

    const cards = await json(await instructor.post(`/api/scenario-templates/${template.id}/batch`, {
      data: {
        count: 1,
        seed: 1122026,
        training_session_id: session.id,
        training_group_id: group.id,
      },
    }))
    expect(cards).toHaveLength(1)

    await json(await instructor.post(`/api/training/sessions/${session.id}/scenario-instances/confirm-batch`, {
      data: { instance_ids: [cards[0].id], training_group_id: group.id },
    }))
    await json(await instructor.post(`/api/training/sessions/${session.id}/prepare`))
    await json(await instructor.post(`/api/training/sessions/${session.id}/start`))

    let incidentId
    await expect.poll(async () => {
      const queue = await json(await instructor.get(`/api/training/sessions/${session.id}/queue`))
      incidentId = queue.find((item) => item.scenario_instance_id === cards[0].id)?.incident_id
      return incidentId
    }).toBeTruthy()
    const number = `СЦ-${cards[0].id}`

    await expect(page.getByText(number).first()).toBeVisible()
    await page.getByText(number).first().click()

    await expect.poll(async () => {
      const claimed = await json(await trainee.get(`/api/incidents/${incidentId}`))
      return claimed.claimed_by_training_run_id
    }).toBeTruthy()

    const ownServiceEdit = page.getByRole('button', { name: 'Изменить статус службы Служба 101' })
    await ownServiceEdit.click()
    await page.getByLabel('Статус', { exact: true }).selectOption('ACCEPT')
    await page.getByRole('button', { name: 'Сохранить статус' }).click()

    await expect.poll(async () => {
      const incident = await json(await instructor.get(`/api/incidents/${incidentId}`))
      return incident.activities.some((item) => item.kind === 'OTHER_SERVICE' && item.stage === 'ACCEPTED')
    }).toBe(true)

    await expect.poll(async () => {
      const incident = await json(await instructor.get(`/api/incidents/${incidentId}`))
      return incident.activities.some((item) => item.kind === 'TRAINING_BRIGADE' && item.stage === 'EN_ROUTE')
    }, { timeout: 30000 }).toBe(true)

    await ownServiceEdit.click()
    await page.getByLabel('Статус', { exact: true }).selectOption('START_RESPONSE')
    await page.getByRole('button', { name: 'Сохранить статус' }).click()

    const progressed = await json(await trainee.get(`/api/incidents/${incidentId}`))
    expect(progressed.dds_status).toBe('RESPONSE_STARTED')
    expect(progressed.activities.some((item) => item.stage === 'EN_ROUTE')).toBe(true)
  } finally {
    await instructor.dispose()
    await trainee.dispose()
  }
})
