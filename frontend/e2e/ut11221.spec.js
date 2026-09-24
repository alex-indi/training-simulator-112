import { expect, request as apiRequest, test } from '@playwright/test'

const apiBase = process.env.E2E_API_URL
const unique = (prefix) => `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`

async function json(response) {
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

test('instructor controls active session and trainee sees pause', async ({ browser }) => {
  const instructorApi = await apiRequest.newContext({ baseURL: apiBase, extraHTTPHeaders: { 'X-Demo-User': 'instructor' } })
  const traineeApi = await apiRequest.newContext({ baseURL: apiBase, extraHTTPHeaders: { 'X-Demo-User': 'trainee' } })
  const instructor = await browser.newPage()
  const trainee = await browser.newPage()
  const dialog = instructor.locator('form[class*="dialog"]')
  try {
    const title = unique('E2E control')
    const scenarioTitle = unique('Сценарий')
    const session = await json(await instructorApi.post('/api/training/sessions', {
      data: { title, mode: 'MANUAL', workstation_count: 2 },
    }))
    await json(await traineeApi.post(`/api/training/sessions/${session.id}/join`, {
      data: { workstation_number: 1 },
    }))
    const joined = await json(await instructorApi.get(`/api/training/sessions/${session.id}`))
    const runId = joined.runs[0].id
    await json(await instructorApi.post(`/api/training/sessions/${session.id}/assign`, {
      data: { run_ids: [runId], dds_profile: 'ДДС района' },
    }))
    const queue = await json(await instructorApi.post(`/api/training/sessions/${session.id}/queue`, {
      data: {
        training_run_id: runId, title: scenarioTitle,
        snapshot: {
          incident_number: unique('КП'), reported_at: new Date().toISOString(),
          source: 'Система-112', address: 'Учебная улица, 1',
          description: 'Учебное происшествие', incident_type: 'Проверка',
          notified_services: ['ДДС района'],
        },
      },
    }))
    expect(queue).toHaveLength(1)
    await json(await instructorApi.post(`/api/training/sessions/${session.id}/queue/approve`))
    await json(await instructorApi.post(`/api/training/sessions/${session.id}/prepare`))
    await json(await instructorApi.post(`/api/training/sessions/${session.id}/start`))

    await instructor.addInitScript((id) => {
      sessionStorage.setItem('ut112-demo-username', 'instructor')
      sessionStorage.setItem('ut112-instructor-session-id', String(id))
    }, session.id)
    await instructor.goto('/')
    await expect(instructor.getByRole('heading', { name: title })).toBeVisible()
    await trainee.goto('/')
    await trainee.getByLabel('Занятие', { exact: true }).selectOption({ label: title })

    await instructor.getByRole('button', { name: 'Пауза', exact: true }).click()
    await expect(instructor.getByText('ЗАНЯТИЕ ПРИОСТАНОВЛЕНО ПРЕПОДАВАТЕЛЕМ')).toBeVisible()
    await expect(trainee.getByText('ЗАНЯТИЕ ПРИОСТАНОВЛЕНО ПРЕПОДАВАТЕЛЕМ')).toBeVisible()
    await instructor.getByRole('button', { name: 'Продолжить', exact: true }).click()
    await expect(instructor.getByText('ЗАНЯТИЕ ПРИОСТАНОВЛЕНО ПРЕПОДАВАТЕЛЕМ')).toHaveCount(0)

    await instructor.getByRole('button', { name: 'АРМ 01' }).click()
    await instructor.getByRole('button', { name: 'Приостановить АРМ' }).click()
    await dialog.getByLabel('Причина').fill('Разбор ситуации')
    await dialog.getByRole('button', { name: 'Сохранить' }).click()
    await expect(trainee.getByText('ВАШЕ РАБОЧЕЕ МЕСТО ПРИОСТАНОВЛЕНО ПРЕПОДАВАТЕЛЕМ')).toBeVisible()
    await instructor.getByRole('button', { name: 'Продолжить АРМ' }).click()
    await instructor.getByRole('button', { name: '+ Заметка' }).click()
    await dialog.getByLabel('Заметка').fill('Уверенно уточнил адрес')
    await dialog.getByRole('button', { name: 'Сохранить' }).click()
    await expect(instructor.getByText('Уверенно уточнил адрес')).toBeVisible()
    await instructor.getByRole('button', { name: 'Закрыть' }).click()

    await instructor.getByRole('button', { name: '+ Карточка' }).click()
    await dialog.getByLabel('Подготовленный сценарий').selectOption({ label: scenarioTitle })
    await dialog.getByRole('button', { name: 'Сохранить' }).click()
    await expect.poll(async () => (await json(await instructorApi.get(`/api/training/sessions/${session.id}/monitor`))).counts.new).toBe(1)
    await instructor.getByRole('button', { name: '+ Событие' }).click()
    await dialog.getByLabel('Карточка').selectOption({ index: 1 })
    await dialog.getByLabel('Текст').fill('Появился второй заявитель')
    await dialog.getByRole('button', { name: 'Сохранить' }).click()
    const monitor = await json(await instructorApi.get(`/api/training/sessions/${session.id}/monitor`))
    const incident = monitor.runs[0].active_incidents[0]
    await expect.poll(async () => {
      const card = await json(await traineeApi.get(`/api/incidents/${incident.id}`))
      return card.scenario_events.some((item) => item.body === 'Появился второй заявитель')
    }).toBeTruthy()
    await trainee.getByText(incident.incident_number).click()
    await expect(trainee.getByText('Появился второй заявитель')).toBeVisible()

    await instructor.getByRole('button', { name: 'Завершить', exact: true }).click()
    await dialog.getByRole('button', { name: 'Сохранить' }).click()
    await expect(instructor.getByText('Выдача остановлена. Обучаемые завершают текущие карточки.')).toBeVisible()
    await instructor.getByRole('button', { name: 'Завершить немедленно' }).click()
    await dialog.getByRole('button', { name: 'Сохранить' }).click()
    await expect.poll(async () => (await json(await instructorApi.get(`/api/training/sessions/${session.id}`))).state).toBe('COMPLETED')
  } finally {
    await instructor.close()
    await trainee.close()
    await instructorApi.dispose()
    await traineeApi.dispose()
  }
})
