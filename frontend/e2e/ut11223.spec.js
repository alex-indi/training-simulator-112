import { expect, request as apiRequest, test } from '@playwright/test'

const apiBase = process.env.E2E_API_URL
const unique = (prefix) => `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`

async function instructorApi() {
  return apiRequest.newContext({
    baseURL: apiBase,
    extraHTTPHeaders: { 'X-Demo-User': 'instructor' },
  })
}

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
  await expect(page.getByRole('button', { name: 'Занять АРМ' })).toHaveCount(0)
}

function snapshot(number, profile) {
  return {
    incident_number: number,
    reported_at: new Date().toISOString(),
    source: 'Система-112',
    address: 'Учебная улица, 1',
    description: 'Учебное происшествие',
    incident_type: 'Проверка',
    notified_services: [profile],
  }
}

test('trainee: login, join, open, accept and restore', async ({ page }) => {
  const api = await instructorApi()
  try {
    const title = unique('E2E trainee')
    const number = unique('КП')
    const session = await json(await api.post('/api/training/sessions', {
      data: { title, mode: 'MANUAL', workstation_count: 3 },
    }))
    await login(page, 'trainee')
    await join(page, title, 1)
    const joined = await json(await api.get(`/api/training/sessions/${session.id}`))
    await json(await api.post(`/api/training/sessions/${session.id}/assign`, {
      data: { run_ids: [joined.runs[0].id], dds_profile: 'ДДС района' },
    }))
    await json(await api.post(`/api/training/sessions/${session.id}/prepare`))
    await json(await api.post(`/api/training/sessions/${session.id}/start`))
    const incident = await json(await api.post('/api/incidents', {
      data: { training_session_id: session.id, source_snapshot: snapshot(number, 'ДДС пожарной охраны') },
    }))
    await page.getByText(number).click()
    await expect(page.getByText('Координаты не указаны')).toBeVisible()
    await page.getByRole('button', { name: /района .*Получена службой/ }).click()
    await page.getByRole('button', { name: 'Сохранить статус' }).click()
    await expect.poll(async () => (await json(await api.get(`/api/incidents/${incident.id}`))).dds_status)
      .toBe('ACCEPTED')
    await page.reload()
    await login(page, 'trainee')
    await page.getByText(number).click()
    await expect(page.getByRole('button', { name: /района .*Принята/ })).toBeVisible()
  } finally {
    await api.dispose()
  }
})

test('shared: one claim, second trainee read only', async ({ browser }) => {
  const api = await instructorApi()
  const first = await browser.newPage()
  const second = await browser.newPage()
  try {
    const users = await json(await api.get('/api/users/demo'))
    expect(users.some((user) => user.username === 'trainee2')).toBeTruthy()
    const title = unique('E2E shared')
    const number = unique('КП')
    const session = await json(await api.post('/api/training/sessions', {
      data: { title, mode: 'MANUAL', workstation_count: 3 },
    }))
    await login(first, 'trainee')
    await join(first, title, 1)
    await login(second, 'trainee2')
    await join(second, title, 2)
    const groupSession = await json(await api.post(`/api/training/sessions/${session.id}/groups`, {
      data: { name: unique('Группа'), dds_profile: 'ДДС района', queue_mode: 'SHARED_QUEUE' },
    }))
    const group = groupSession.groups[0]
    const runs = groupSession.runs.map((run) => run.id)
    await json(await api.post(`/api/training/sessions/${session.id}/assign`, {
      data: { run_ids: runs, group_id: group.id },
    }))
    await json(await api.post(`/api/training/sessions/${session.id}/prepare`))
    await json(await api.post(`/api/training/sessions/${session.id}/start`))
    await json(await api.post('/api/incidents', {
      data: {
        training_session_id: session.id,
        training_group_id: group.id,
        source_snapshot: snapshot(number, 'ДДС района'),
      },
    }))
    await first.getByText(number).click()
    await first.getByRole('button', { name: 'Взять в работу' }).click()
    await second.getByText(number).click()
    await expect(second.getByText(/просмотр без права изменения/)).toBeVisible()
    await expect(second.getByRole('button', { name: 'Сохранить статус' })).toHaveCount(0)
  } finally {
    await first.close()
    await second.close()
    await api.dispose()
  }
})

test('instructor: create, assign profile, prepare queue, start', async ({ page, browser }) => {
  const api = await instructorApi()
  const trainee = await browser.newPage()
  try {
    const title = unique('E2E instructor')
    await login(page, 'instructor')
    await page.getByRole('button', { name: '+ Новое занятие' }).click()
    await page.getByLabel('Название занятия').fill(title)
    await page.getByLabel('Режим').selectOption('FIXED_SET')
    await page.getByRole('button', { name: 'Создать и продолжить' }).click()
    await expect(page.getByRole('heading', { name: title })).toBeVisible()
    await login(trainee, 'trainee')
    await join(trainee, title, 3)
    await page.getByRole('button', { name: 'Распределение' }).click()
    await expect(page.getByText('АРМ 03').first()).toBeVisible()
    await page.getByRole('button', { name: 'Выбрать всех' }).click()
    await page.getByPlaceholder('Например, ДДС района').fill('ДДС района')
    await page.getByRole('button', { name: 'Применить к выбранным' }).click()
    await page.getByRole('button', { name: 'К заданиям →' }).click()
    await page.getByRole('button', { name: 'Сформировать набор' }).click()
    await page.getByRole('button', { name: 'Утвердить набор' }).click()
    await page.getByRole('button', { name: 'К готовности →' }).click()
    await page.getByRole('button', { name: 'Проверить готовность' }).click()
    await page.getByRole('button', { name: 'Запустить занятие' }).click()
    await expect.poll(async () => {
      const sessions = await json(await api.get('/api/training/sessions'))
      return sessions.find((item) => item.title === title)?.state
    }).toBe('ACTIVE')
  } finally {
    await trainee.close()
    await api.dispose()
  }
})
