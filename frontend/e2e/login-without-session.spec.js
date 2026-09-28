import { expect, test } from '@playwright/test'

test('trainee can choose a workstation and sign in before a session exists', async ({ page }) => {
  const trainee = { id: 4, username: 'sid', full_name: 'Сидоров', role: 'TRAINEE' }
  const results = [
    { session_id: 1, title: 'Занятие без оценки', date: '2026-09-27T10:00:00Z', dds_profile: 'ДДС', cards: 0,
      result: { final_score: null, confirmed_at: null, metrics: { cards: 0 }, deviations: [] } },
    { session_id: 2, title: 'Занятие с нулевой оценкой', date: '2026-09-26T10:00:00Z', dds_profile: 'ДДС', cards: 0,
      result: { final_score: 0, confirmed_at: '2026-09-27T10:00:00Z', metrics: { cards: 0 }, deviations: [] } },
  ]
  const quickUsers = [
    { id: 1, username: 'admin', full_name: 'Администратор', role: 'ADMIN' },
    { id: 2, username: 'instructor', full_name: 'Наталья Андреева', role: 'INSTRUCTOR' },
    { id: 3, username: 'trainee', full_name: 'Александр Иванов', role: 'TRAINEE' },
  ]
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const body = path === '/api/users/demo' ? [...quickUsers, trainee]
      : path === '/api/users/login' ? trainee
        : path === '/api/users/workstation' ? { user_id: 4, trainee_name: 'Сидоров', workstation_number: 1, last_seen_at: new Date().toISOString() }
        : path === '/api/training/my/results' ? results
          : path === '/api/training/sessions' || path === '/api/incidents' ? []
          : { detail: 'Unknown route' }
    await route.fulfill({ status: path === '/api/users/login' || path === '/api/users/workstation' || Array.isArray(body) ? 200 : 404,
      contentType: 'application/json', body: JSON.stringify(body) })
  })

  await page.goto('/')
  await expect(page.getByLabel('Пользователь').locator('option')).toHaveCount(3)
  await expect(page.getByLabel('Пользователь').locator('option')).toHaveText([
    'Администратор', 'Преподаватель', 'Обучающийся',
  ])
  await page.getByRole('button', { name: 'Ввести логин другого пользователя' }).click()
  await page.getByLabel('Пользователь').fill('SID')
  const workstation = page.getByRole('combobox', { name: 'Рабочее место' })
  await expect(workstation).toBeEnabled()
  await workstation.selectOption('1')
  await page.locator('input[type="password"]').fill('учебный')
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page.getByRole('heading', { name: 'АРМ 01 подключён' })).toBeVisible()
  const notice = page.getByRole('region', { name: 'Подключение к занятию' })
  await expect.poll(async () => notice.evaluate((element) => {
    const bounds = element.getBoundingClientRect()
    return Math.abs(bounds.top + bounds.height / 2 - window.innerHeight / 2) < 2
      && Math.abs(bounds.left + bounds.width / 2 - window.innerWidth / 2) < 2
      && document.elementFromPoint(10, 10) === element.parentElement
  })).toBe(true)
  await page.getByRole('button', { name: 'Результаты занятий' }).click()
  const resultsDialog = page.getByRole('dialog', { name: 'Результаты занятий' })
  await expect(resultsDialog).toBeVisible()
  await expect(resultsDialog.getByRole('button', { name: /Занятие без оценки/ })).toContainText('Нет оценки')
  await expect(resultsDialog.getByRole('button', { name: /Занятие с нулевой оценкой/ })).toContainText('Итог: 0 / 100')
  await resultsDialog.getByRole('button', { name: 'Закрыть' }).click()
  await page.getByRole('button', { name: 'Выйти' }).click()
  await expect(page.getByRole('button', { name: 'Войти' })).toBeVisible()
})
