import { expect, request as apiRequest, test } from '@playwright/test'

test('instructor generates a real catalog instance and attaches it to a session', async ({ page }) => {
  const api = await apiRequest.newContext({
    baseURL: process.env.E2E_API_URL,
    extraHTTPHeaders: { 'X-Demo-User': 'instructor' },
  })
  try {
    const templatesResponse = await api.get('/api/scenario-templates?status=READY')
    expect(templatesResponse.ok(), await templatesResponse.text()).toBeTruthy()
    const templates = (await templatesResponse.json()).items
    const template = templates.find((item) => item.object_rule?.selection_mode === 'GENERIC')
    expect(template).toBeTruthy()
    const sessionResponse = await api.post('/api/training/sessions', {
      data: { title: `UT112-26 E2E ${Date.now()}`, mode: 'MANUAL', workstation_count: 1 },
    })
    expect(sessionResponse.ok(), await sessionResponse.text()).toBeTruthy()
    const session = await sessionResponse.json()

    await page.addInitScript(() => sessionStorage.setItem('ut112-demo-username', 'instructor'))
    await page.goto('/')
    await page.getByRole('button', { name: 'Библиотека сценариев' }).click()
    await page.getByRole('button', { name: new RegExp(template.name) }).click()
    await page.getByRole('button', { name: 'Сгенерировать экземпляр' }).click()
    await expect(page.getByLabel('Подходящий объект')).toBeVisible()
    const options = page.getByLabel('Подходящий объект').locator('option')
    expect(await options.count()).toBeGreaterThan(1)
    const objectId = await options.nth(1).getAttribute('value')
    await page.getByLabel('Подходящий объект').selectOption(objectId)
    await page.getByRole('button', { name: 'Показать предпросмотр' }).click()
    await expect(page.getByText('Подходящих объектов:', { exact: false })).toBeVisible()
    await page.getByRole('button', { name: 'Сгенерировать экземпляр' }).click()
    await expect(page.getByRole('heading', { name: /Экземпляр #/ })).toBeVisible()
    await page.getByLabel('Использовать в занятии').selectOption(String(session.id))
    await page.getByRole('button', { name: 'Привязать к занятию' }).click()
    await expect(page.getByText(`Занятие: #${session.id}`)).toBeVisible()

    const attachedResponse = await api.get(`/api/training/sessions/${session.id}/scenario-instances`)
    expect(attachedResponse.ok(), await attachedResponse.text()).toBeTruthy()
    const attached = await attachedResponse.json()
    expect(attached).toHaveLength(1)
    expect(attached[0].object_snapshot.id).toBe(Number(objectId))
    expect(attached[0].classifier_snapshot.final_incident_type).toBeTruthy()
    expect(attached[0].events.length).toBeGreaterThan(0)
  } finally {
    await api.dispose()
  }
})
