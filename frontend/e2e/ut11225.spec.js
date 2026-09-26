import { expect, request as apiRequest, test } from '@playwright/test'

const apiBase = process.env.E2E_API_URL

async function json(response) {
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

test('instructor prepares a real catalog scenario, then duplicates it', async ({ page }) => {
  test.setTimeout(45000)
  const api = await apiRequest.newContext({ baseURL: apiBase, extraHTTPHeaders: { 'X-Demo-User': 'instructor' } })
  try {
    const catalog = await json(await api.get('/api/scenario-templates/catalog?q=пожар'))
    const school = catalog.object_types.find((type) => type.code === 'SCHOOL')
    const rule = catalog.rules[0]
    expect(school).toBeTruthy()
    expect(rule).toBeTruthy()
    const title = `E2E сценарий ${Date.now()}`
    await page.addInitScript(() => sessionStorage.setItem('ut112-demo-username', 'instructor'))
    await page.goto('/')
    await expect(page.getByRole('button', { name: 'Библиотека сценариев' })).toBeVisible()
    await page.getByRole('button', { name: 'Библиотека сценариев' }).click()
    await expect(page.getByRole('heading', { name: 'Библиотека сценариев' })).toBeVisible()
    await page.getByRole('button', { name: '+ Создать сценарий' }).click()
    await page.getByLabel('Название', { exact: true }).fill(title)
    await page.getByLabel('Описание', { exact: true }).fill('Проверка библиотеки')
    await page.getByRole('navigation', { name: 'Разделы сценария' }).getByRole('button', { name: 'Тип происшествия' }).click()
    await page.getByLabel('Поиск в классификаторе').fill('пожар')
    await page.getByLabel('Правило').selectOption(String(rule.id))
    await page.getByRole('navigation', { name: 'Разделы сценария' }).getByRole('button', { name: 'Тип объекта' }).click()
    await page.getByLabel('Режим').selectOption('GENERIC')
    await page.getByLabel('Тип объекта').selectOption(String(school.id))
    await page.getByRole('navigation', { name: 'Разделы сценария' }).getByRole('button', { name: 'Карточка и варианты' }).click()
    await page.getByLabel('Заголовок карточки').fill('Запах дыма в школе')
    await page.getByLabel('Описание происшествия').fill('Из школы поступило сообщение о задымлении')
    await page.getByRole('navigation', { name: 'Разделы сценария' }).getByRole('button', { name: 'Работа служб' }).click()
    await page.getByRole('button', { name: '+ Добавить событие' }).click()
    await page.getByLabel('Название', { exact: true }).fill('Первичное сообщение')
    await page.getByRole('button', { name: 'Сохранить черновик' }).click()
    await expect(page.getByText('Черновик сохранён')).toBeVisible()
    await page.getByLabel('Название', { exact: true }).fill('Уточнённое сообщение')
    await page.getByRole('navigation', { name: 'Разделы сценария' }).getByRole('button', { name: 'Предпросмотр' }).click()
    await page.getByRole('button', { name: 'Проверить сценарий' }).click()
    await expect(page.getByText('Сначала сохраните черновик')).toBeVisible()
    await page.getByRole('button', { name: 'Сохранить черновик' }).click()
    await page.getByRole('button', { name: 'Проверить сценарий' }).click()
    await expect(page.getByText('Ошибок не найдено.')).toBeVisible()
    await page.getByRole('button', { name: 'Перевести в READY' }).click()
    await expect(page.getByText('Сценарий готов к использованию')).toBeVisible()
    const original = (await json(await api.get(`/api/scenario-templates?q=${encodeURIComponent(title)}`))).items[0]
    expect(original.status).toBe('READY')
    await page.getByRole('button', { name: 'Изменить', exact: true }).click()
    await expect(page.getByText('Создана копия черновика')).toBeVisible()
    await page.getByRole('navigation', { name: 'Разделы сценария' }).getByRole('button', { name: 'Основное' }).click()
    await page.getByRole('textbox', { name: 'Описание' }).fill('Изменена только копия')
    await page.getByRole('button', { name: 'Сохранить черновик' }).click()
    expect((await json(await api.get(`/api/scenario-templates/${original.id}`))).description).toBe('Проверка библиотеки')
    await json(await api.post(`/api/scenario-templates/${original.id}/archive`))
  } finally {
    await api.dispose()
  }
})
