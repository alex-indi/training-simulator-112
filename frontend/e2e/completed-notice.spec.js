import { expect, test } from '@playwright/test'

test('completion notice appears only when an active lesson ends in this visit', async ({ page }) => {
  const trainee = { id: 4, username: 'sid', full_name: 'Сидоров', role: 'TRAINEE' }
  let sessionState = 'COMPLETED'
  let heartbeatCount = 0
  let sessionReadCount = 0

  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body = {}
    if (path === '/api/users/demo') body = [trainee]
    else if (path === '/api/users/me') body = trainee
    else if (path === '/api/training/sessions') {
      sessionReadCount += 1
      body = [{ id: 77, state: sessionState, own_run: { id: 88 } }]
    } else if (path === '/api/incidents' || path === '/api/training/my/results') body = []
    else if (path === '/api/training/sessions/77/heartbeat') heartbeatCount += 1
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.addInitScript(() => {
    sessionStorage.setItem('ut112-demo-username', 'sid')
    sessionStorage.setItem('ut112-workstation-number', '1')
    sessionStorage.setItem('ut112-trainee-session-id', '77')
  })

  await page.goto('/')
  await expect.poll(() => heartbeatCount).toBeGreaterThan(0)
  await page.waitForTimeout(500)
  const completionNotice = page.getByRole('status').filter({ hasText: 'Занятие завершено' })
  expect(await completionNotice.count()).toBe(0)

  sessionState = 'ACTIVE'
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Поиск происшествий' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Подключение к занятию' })).toHaveCount(0)

  const previousSessionReadCount = sessionReadCount
  sessionState = 'COMPLETED'
  await expect.poll(() => sessionReadCount).toBeGreaterThan(previousSessionReadCount)
  await expect(completionNotice).toBeVisible()

  const previousHeartbeatCount = heartbeatCount
  await page.reload()
  await expect.poll(() => heartbeatCount).toBeGreaterThan(previousHeartbeatCount)
  await page.waitForTimeout(500)
  expect(await completionNotice.count()).toBe(0)
})
