import { expect, request as apiRequest, test } from '@playwright/test'

const apiBase = process.env.E2E_API_URL

async function json(response) {
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

async function login(page, username) {
  await page.goto('/')
  const password = page.locator('input[type="password"]')
  const currentUser = page.getByRole('combobox', { name: 'Текущий пользователь' })
  await expect(password.or(currentUser).first()).toBeVisible()
  if (await password.isVisible()) {
    await page.getByLabel('Пользователь').selectOption(username)
    await password.fill('учебный')
    await page.getByRole('button', { name: 'Войти' }).click()
  } else {
    await currentUser.selectOption(username)
  }
}

async function join(page, title, workstation) {
  await page.getByLabel('Занятие', { exact: true }).selectOption({ label: title })
  await page.getByLabel('Рабочее место').fill(String(workstation))
  const [response] = await Promise.all([
    page.waitForResponse((item) => item.url().endsWith('/join') && item.request().method() === 'POST'),
    page.getByRole('button', { name: 'Занять АРМ' }).click(),
  ])
  expect(response.ok(), await response.text()).toBeTruthy()
}

test('shared scenario is claimed once and crew chat stays on its incident', async ({ browser }) => {
  test.setTimeout(90000)
  const api = await apiRequest.newContext({
    baseURL: apiBase,
    extraHTTPHeaders: { 'X-Demo-User': 'instructor' },
  })
  const first = await browser.newPage()
  const second = await browser.newPage()
  try {
    const title = `UT112-40 real ${Date.now()}`
    const session = await json(await api.post('/api/training/sessions', {
      data: { title, mode: 'FIXED_SET', workstation_count: 2 },
    }))
    await login(first, 'trainee')
    await join(first, title, 1)
    await login(second, 'trainee2')
    await join(second, title, 2)

    const grouped = await json(await api.post(`/api/training/sessions/${session.id}/groups`, {
      data: { name: `Группа ${session.id}`, dds_profile: 'ДДС района', queue_mode: 'SHARED_QUEUE' },
    }))
    const group = grouped.groups[0]
    await json(await api.post(`/api/training/sessions/${session.id}/assign`, {
      data: { run_ids: grouped.runs.map((run) => run.id), group_id: group.id },
    }))
    const template = (await json(await api.get('/api/scenario-templates?status=READY')))
      .items.find((item) => item.name === 'Пожар в образовательном учреждении')
    expect(template).toBeTruthy()
    const cards = await json(await api.post(`/api/scenario-templates/${template.id}/batch`, {
      data: { count: 2, seed: session.id, training_session_id: session.id, different_objects: true },
    }))
    expect(cards).toHaveLength(2)
    expect(cards[0].object_snapshot.id).not.toBe(cards[1].object_snapshot.id)
    await json(await api.post(`/api/training/sessions/${session.id}/scenario-instances/confirm-batch`, {
      data: { instance_ids: cards.map((card) => card.id), training_group_id: group.id },
    }))
    await json(await api.post(`/api/training/sessions/${session.id}/prepare`))
    await json(await api.post(`/api/training/sessions/${session.id}/start`))

    const units = []
    for (const code of ['101', '103']) {
      units.push(await json(await api.post('/api/response/units', {
        data: { name: `Учебная группа ${code} ${session.id}`, dds_profile: 'ДДС района' },
      })))
    }
    const number = `СЦ-${cards[0].id}`
    await expect(first.getByText(number).first()).toBeVisible()
    await expect(second.getByText(number).first()).toBeVisible()
    await first.getByText(number).first().click()
    await first.getByRole('button', { name: 'Взять в работу' }).click()
    await second.getByText(number).first().click()
    await expect(second.getByText(/просмотр без права изменения/)).toBeVisible()
    await expect(second.getByRole('button', { name: 'Сохранить статус' })).toHaveCount(0)

    await first.getByRole('button', { name: /района .*Добавлена/ }).click()
    await first.getByLabel('Статус', { exact: true }).selectOption('ACCEPT')
    await first.getByRole('button', { name: 'Сохранить статус' }).click()
    const incident = await json(await api.get(`/api/incidents/${(await json(await api.get(`/api/training/sessions/${session.id}/queue`)))[0].incident_id}`))
    expect(incident.dds_status).toBe('ACCEPTED')
    await first.getByText('Виртуальная группа реагирования', { exact: true }).first().click()
    const services = cards[0].service_snapshot
    for (const [index, code] of ['101', '103'].entries()) {
      const service = services.find((item) => item.official_name.includes(code))
      expect(service).toBeTruthy()
      await first.getByLabel('Служба сценария').selectOption(String(service.service_id))
      await first.getByLabel('Доступная группа реагирования').selectOption(String(units[index].id))
      const [response] = await Promise.all([
        first.waitForResponse((item) => item.url().endsWith('/assignments') && item.request().method() === 'POST'),
        first.getByRole('button', { name: 'Назначить группу' }).click(),
      ])
      expect(response.ok(), await response.text()).toBeTruthy()
      await expect.poll(async () =>
        (await json(await api.get(`/api/response/incidents/${incident.id}/assignments`))).length,
      ).toBe(index + 1)
    }
    const assignments = await json(await api.get(`/api/response/incidents/${incident.id}/assignments`))
    expect(assignments).toHaveLength(2)
    for (const code of ['101', '103']) {
      const assignment = assignments.find((item) => item.response_unit.name.includes(code))
      await expect.poll(async () => {
        const messages = await json(await api.get(`/api/response/assignments/${assignment.id}/messages`))
        return messages.filter((message) => message.sender_type === 'RESPONSE_UNIT').length
      }, { timeout: 40000 }).toBeGreaterThan(0)
      const messages = await json(await api.get(`/api/response/assignments/${assignment.id}/messages`))
      await first.getByRole('button', { name: new RegExp(`Оперативная связь .* Учебная группа ${code} ${session.id}`) }).click()
      await expect(first.getByText(messages.find((message) => message.sender_type === 'RESPONSE_UNIT').body)).toBeVisible()
    }
    expect((await json(await api.get(`/api/incidents/${incident.id}`))).dds_status).toBe('ACCEPTED')
    const traineeApi = await apiRequest.newContext({
      baseURL: apiBase,
      extraHTTPHeaders: { 'X-Demo-User': 'trainee' },
    })
    try {
      for (const action of ['START_RESPONSE', 'MARK_ARRIVAL', 'START_WORK', 'COMPLETE_WORK']) {
        await json(await traineeApi.post(`/api/incidents/${incident.id}/actions`, { data: { action } }))
      }
    } finally {
      await traineeApi.dispose()
    }
    const finished = await json(await api.get(`/api/incidents/${incident.id}`))
    expect(finished.dds_status).toBe('COMPLETED')
    expect(finished.lifecycle_state).toBe('FINISHED')
  } finally {
    await first.close()
    await second.close()
    await api.dispose()
  }
})
