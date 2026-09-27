import { expect, test } from '@playwright/test'

test('trainee can choose a workstation and sign in before a session exists', async ({ page }) => {
  const trainee = { id: 4, username: 'sid', full_name: 'Сидоров', role: 'TRAINEE' }
  const quickUsers = [
    { id: 1, username: 'admin', full_name: 'Администратор', role: 'ADMIN' },
    { id: 2, username: 'instructor', full_name: 'Преподаватель', role: 'INSTRUCTOR' },
    { id: 3, username: 'trainee', full_name: 'Обучаемый', role: 'TRAINEE' },
  ]
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const body = path === '/api/users/demo' ? [...quickUsers, trainee]
      : path === '/api/users/login' ? trainee
        : path === '/api/users/workstation' ? { user_id: 4, trainee_name: 'Сидоров', workstation_number: 1, last_seen_at: new Date().toISOString() }
        : path === '/api/training/sessions' || path === '/api/incidents'
          || path === '/api/training/my/results' ? []
          : { detail: 'Unknown route' }
    await route.fulfill({ status: path === '/api/users/login' || path === '/api/users/workstation' || Array.isArray(body) ? 200 : 404,
      contentType: 'application/json', body: JSON.stringify(body) })
  })

  await page.goto('/')
  await expect(page.getByLabel('Пользователь').locator('option')).toHaveCount(3)
  await page.getByRole('button', { name: 'Ввести логин другого пользователя' }).click()
  await page.getByLabel('Пользователь').fill('SID')
  const workstation = page.getByRole('combobox', { name: 'Рабочее место' })
  await expect(workstation).toBeEnabled()
  await workstation.selectOption('1')
  await page.locator('input[type="password"]').fill('учебный')
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page.getByRole('heading', { name: 'АРМ 01 подключён' })).toBeVisible()
})
