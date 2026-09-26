import { expect, test } from '@playwright/test'

test('instructor reviews five variants and confirms the shared batch', async ({ page }) => {
  const user = { id: 1, username: 'instructor', full_name: 'Преподаватель', role: 'INSTRUCTOR' }
  const template = {
    id: 7, name: 'Пожар в образовательном учреждении', description: 'Пожар в школе',
    status: 'READY', difficulty: 3, object_rule: { object_type_id: 5 },
    services: [{ service_id: 3 }],
  }
  const training = {
    id: 4, title: 'Учебная смена', state: 'DRAFT', mode: 'FIXED_SET',
    duration_minutes: 30, delivery_interval_seconds: 120, delivery_order: 'SEQUENTIAL',
    workstation_count: 2, runs: [
      { id: 8, trainee_id: 2, trainee_name: 'Первый', workstation_number: 1,
        queue_mode: 'SHARED_QUEUE', group_id: 6, dds_profile: 'Пожарная охрана' },
      { id: 9, trainee_id: 3, trainee_name: 'Второй', workstation_number: 2,
        queue_mode: 'SHARED_QUEUE', group_id: 6, dds_profile: 'Пожарная охрана' },
    ],
    groups: [{ id: 6, name: 'Дежурная группа', queue_mode: 'SHARED_QUEUE', run_ids: [8, 9] }],
    readiness: { participant_count: 2, workstation_count: 2, group_count: 1,
      profiles_assigned: 2, online_count: 0, offline_count: 2, warnings: [],
      can_start: false, prepared_count: 0, approved_count: 0 },
  }
  const makeCard = (index) => ({
    id: 40 + index, scenario_template_id: 7, training_session_id: 4,
    status: 'DRAFT', name: `Школа №${index}`, difficulty: 3,
    template_snapshot: { batch_seed: 123, batch_position: index,
      variant_options: { floor: [1, 2, 3, 4] } },
    object_snapshot: { id: index, name: `Школа №${index}`, address: `Улица ${index}` },
    initial_state_snapshot: { variant_facts: { floor: index },
      render: { rendered_text: `дым на ${index} этаже`, render_origin: 'GENERATED' } },
    events: [{ id: 100 + index, event_type: 'RESPONSE_MESSAGE',
      payload_snapshot: { target_service_name: 'Пожарная охрана' },
      render: { rendered_text: `на месте у школы №${index}`, render_origin: 'GENERATED' } }],
  })
  let cards = []
  let confirmed = null
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const method = route.request().method()
    let body = null
    if (path === '/api/users/demo') body = [user]
    else if (path === '/api/users/me') body = user
    else if (path === '/api/training/sessions') body = [training]
    else if (path === '/api/training/templates') body = []
    else if (path === '/api/training/sessions/4/queue') body = []
    else if (path === '/api/training/sessions/4/scenario-instances') body = cards
    else if (path === '/api/scenario-templates/catalog') body = {
      services: [{ id: 3, name: 'Пожарная охрана' }],
      object_types: [{ id: 5, name: 'Школы' }],
    }
    else if (path === '/api/scenario-templates') body = {
      items: [template], total: 1, offset: 0, limit: 100,
    }
    else if (path === '/api/scenario-templates/7/batch' && method === 'POST') {
      expect(route.request().postDataJSON().count).toBe(5)
      cards = Array.from({ length: 5 }, (_, index) => makeCard(index + 1))
      body = cards
    } else if (path === '/api/scenario-instances/41/rerender-initial-message') {
      cards[0] = { ...cards[0], initial_state_snapshot: {
        ...cards[0].initial_state_snapshot,
        render: { rendered_text: 'снова дым на 1 этаже', render_origin: 'GENERATED' },
      } }
      body = cards[0]
    } else if (path === '/api/scenario-instances/41/regenerate-card') {
      cards[0] = { ...cards[0], initial_state_snapshot: {
        ...cards[0].initial_state_snapshot, variant_facts: { floor: 4 },
        render: { rendered_text: 'дым на 4 этаже', render_origin: 'GENERATED' },
      } }
      body = cards[0]
    } else if (path === '/api/scenario-instances/41/variant-facts') {
      const facts = route.request().postDataJSON()
      cards[0] = { ...cards[0], initial_state_snapshot: {
        ...cards[0].initial_state_snapshot, variant_facts: facts,
        render: { rendered_text: `дым на ${facts.floor} этаже`, render_origin: 'GENERATED' },
      } }
      body = cards[0]
    } else if (path === '/api/scenario-instances/41/events/101/message') {
      cards[0] = { ...cards[0], events: [{ ...cards[0].events[0],
        render: { rendered_text: route.request().postDataJSON().text, render_origin: 'MANUAL' },
      }] }
      body = cards[0]
    } else if (path === '/api/training/sessions/4/scenario-instances/confirm-batch') {
      confirmed = route.request().postDataJSON()
      body = { count: 5, queue_item_ids: [1, 2, 3, 4, 5] }
    }
    await route.fulfill({ status: body === null ? 404 : 200,
      contentType: 'application/json', body: JSON.stringify(body ?? { detail: 'Unknown route' }) })
  })
  await page.addInitScript(() => sessionStorage.setItem('ut112-demo-username', 'instructor'))
  await page.goto('/')
  await page.getByRole('button', { name: /Учебная смена/ }).click()
  await page.getByRole('button', { name: /Задания/ }).click()
  await page.getByRole('button', { name: '+ Добавить карточки по сценарию' }).click()
  const picker = page.getByRole('dialog', { name: 'Выберите сценарий' })
  await picker.getByRole('button', { name: /Пожар в образовательном учреждении/ }).click()
  await expect(picker.getByLabel('Занятие')).toHaveCount(0)
  await picker.getByRole('button', { name: 'Сформировать', exact: true }).click()
  await expect(page.getByRole('navigation', { name: 'Карточки набора' }).getByRole('button')).toHaveCount(5)
  await page.getByRole('button', { name: 'Перегенерировать текст', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Карточка ДДС' })).toHaveValue('снова дым на 1 этаже')
  expect(cards[0].initial_state_snapshot.variant_facts.floor).toBe(1)
  await page.getByRole('button', { name: 'Перегенерировать карточку' }).click()
  await expect(page.getByRole('textbox', { name: 'Карточка ДДС' })).toHaveValue('дым на 4 этаже')
  expect(cards[0].initial_state_snapshot.variant_facts.floor).toBe(4)
  await page.getByText('Изменить условия карточки').click()
  await page.getByLabel('Этаж', { exact: true }).selectOption('2')
  await page.getByRole('button', { name: 'Сохранить условия' }).click()
  await expect(page.getByRole('textbox', { name: 'Карточка ДДС' })).toHaveValue('дым на 2 этаже')
  expect(cards[0].initial_state_snapshot.variant_facts.floor).toBe(2)
  await page.getByRole('textbox', { name: 'Пожарная охрана' }).fill('на месте, виден дым')
  await page.getByRole('button', { name: 'Сохранить сообщение' }).click()
  await expect(page.getByRole('textbox', { name: 'Пожарная охрана' })).toHaveValue('на месте, виден дым')
  expect(cards[0].events[0].render.render_origin).toBe('MANUAL')
  await page.getByRole('button', { name: 'Утвердить набор и добавить в занятие' }).click()
  await expect(picker).not.toBeVisible()
  expect(confirmed).toEqual({ instance_ids: [41, 42, 43, 44, 45], training_group_id: 6 })
})
