import { expect, test } from '@playwright/test'

test('instructor creates a lesson and opens the current template library', async ({ page }) => {
  const title = `E2E занятие ${Date.now()}`
  await page.addInitScript(() => {
    sessionStorage.setItem('ut112-demo-username', 'instructor')
    sessionStorage.removeItem('ut112-instructor-session-id')
  })
  await page.goto('/')

  await page.getByRole('button', { name: '+ Новое занятие' }).click()
  await page.getByLabel('Название занятия').fill(title)
  await page.getByRole('button', { name: 'Создать занятие' }).click()
  await expect(page.getByRole('heading', { name: 'Группы', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: title })).toBeVisible()

  const navigation = page.getByRole('navigation', { name: 'Разделы кабинета преподавателя' })
  await navigation.getByRole('button', { name: 'Шаблоны инцидентов' }).click()
  await expect(page.getByRole('heading', { name: 'Шаблоны инцидентов', level: 1 })).toBeVisible()
  await navigation.getByRole('button', { name: 'Занятия', exact: true }).click()
  await expect(page.getByText(title)).toBeVisible()
})
