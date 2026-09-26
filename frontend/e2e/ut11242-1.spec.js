import { expect, test } from '@playwright/test'

test('instructor selects reusable groups before anyone connects', async ({ page }) => {
  const teacher = { id: 2, username: 'instructor', full_name: 'Преподаватель', role: 'INSTRUCTOR' }
  const trainee = { id: 3, full_name: 'Иванов И.И.', group_id: null }
  let groups = []
  let session = null

  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/\/$/, '')
    const method = route.request().method()
    const data = method === 'GET' ? null : route.request().postDataJSON()
    let body = null
    if (path === '/api/users/demo') body = [teacher]
    else if (path === '/api/users/me') body = teacher
    else if (path === '/api/training/user-groups/trainees') body = [trainee]
    else if (path === '/api/training/user-groups' && method === 'GET') body = groups
    else if (path === '/api/training/user-groups' && method === 'POST') {
      const group = { id: groups.length + 1, name: data.name, code: data.code,
        is_archived: false, members: data.member_ids.includes(3) ? [trainee] : [],
        member_count: data.member_ids.length }
      groups = [...groups, group]
      if (data.member_ids.includes(3)) trainee.group_id = group.id
      body = group
    } else if (path === '/api/training/sessions' && method === 'GET') body = session ? [session] : []
    else if (path === '/api/training/sessions' && method === 'POST') {
      session = { id: 10, ...data, state: 'DRAFT', runs: [], groups: [],
        readiness: { participant_count: 0, workstation_count: 30, group_count: 0,
          profiles_assigned: 0, online_count: 0, offline_count: 0, warnings: [],
          can_start: false, prepared_count: 0, approved_count: 0 } }
      body = session
    } else if (path === '/api/training/templates') body = []
    else if (path === '/api/training/sessions/10/queue') body = []
    else if (path === '/api/training/sessions/10/scenario-instances') body = []
    else if (path === '/api/training/sessions/10/groups' && method === 'POST') {
      session.groups.push({ id: session.groups.length + 1, ...data, run_ids: [] })
      body = session
    } else if (/^\/api\/training\/sessions\/10\/groups\/\d+$/.test(path) && method === 'PUT') {
      session.groups = session.groups.map((group) => group.id === Number(path.split('/').at(-1))
        ? { ...group, ...data } : group)
      body = session
    }
    await route.fulfill({ status: body === null ? 404 : 200, contentType: 'application/json',
      body: JSON.stringify(body ?? { detail: 'Unknown route' }) })
  })

  await page.addInitScript(() => sessionStorage.setItem('ut112-demo-username', 'instructor'))
  await page.goto('/')
  await page.getByRole('button', { name: 'Группы обучающихся' }).click()
  for (const [name, code] of [['Первая группа', 'DDS-101'], ['Вторая группа', 'DDS-103']]) {
    await page.getByRole('button', { name: '+ Создать группу' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Название').fill(name)
    await dialog.getByLabel('Короткий код').fill(code)
    if (code === 'DDS-101') await dialog.getByRole('checkbox', { name: /Иванов/ }).check()
    await dialog.getByRole('button', { name: 'Создать', exact: true }).click()
    await expect(dialog).not.toBeVisible()
  }

  await page.getByRole('button', { name: 'Занятия', exact: true }).click()
  await page.getByRole('button', { name: '+ Новое занятие' }).click()
  await expect(page.getByLabel('Название занятия')).toHaveValue(/Практическое занятие/)
  await page.getByRole('button', { name: 'Создать занятие' }).click()
  await expect(page.getByRole('heading', { name: 'Выберите группы для занятия' })).toBeVisible()
  await page.getByRole('button', { name: 'Добавить в занятие' }).first().click()
  await expect(page.getByRole('button', { name: '✓ В занятии · убрать' })).toHaveCount(1)
  await page.getByRole('button', { name: 'Добавить в занятие' }).first().click()
  await expect(page.getByRole('button', { name: '✓ В занятии · убрать' })).toHaveCount(2)
  await page.getByRole('button', { name: '+ Создать новую группу' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Название').fill('Третья группа')
  await dialog.getByLabel('Короткий код').fill('DDS-105')
  await dialog.getByRole('button', { name: 'Создать и добавить в занятие' }).click()
  await expect(page.getByRole('heading', { name: 'Группы этого занятия' })).toBeVisible()
  await expect.poll(() => session.groups.length).toBe(3)
  await expect(page.getByText('Третья группа', { exact: true }).first()).toBeVisible()
  expect(session.runs).toHaveLength(0)
})
