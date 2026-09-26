/* eslint-disable react/prop-types */
import { useCallback, useEffect, useState } from 'react'
import styles from './ScenarioLibrary.module.css'
import { difficultyLabels, renderOriginLabels } from './uiLabels.js'
import AdvancedScenarioLibrary from './AdvancedScenarioLibrary.jsx'

const options = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
const variantFactLabels = { floor: 'Этаж', room: 'Помещение', observation: 'Обстановка', casualties: 'Пострадавшие' }

function ResponseMessageEditor({ event, instanceId, busy, onChange }) {
  const [text, setText] = useState(event.render?.rendered_text || '')
  useEffect(() => setText(event.render?.rendered_text || ''), [event.render?.rendered_text])
  const path = `/api/scenario-instances/${instanceId}/events/${event.id}`
  return <div>
    <label>{event.payload_snapshot.target_service_name || 'Служба'}
      <textarea value={text} onChange={(change) => setText(change.target.value)} />
    </label>
    <small>{renderOriginLabels[event.render?.render_origin] || 'Текст подготовлен'}</small>
    <div className={styles.actions}>
      <button type="button" disabled={busy || !text.trim() || text === event.render?.rendered_text} onClick={() => onChange(`${path}/message`, options('PATCH', { text }))}>Сохранить сообщение</button>
      <button type="button" disabled={busy} onClick={() => onChange(`${path}/rerender`, { method: 'POST' })}>Перегенерировать сообщение</button>
    </div>
  </div>
}

export default function ScenarioLibrary({ user, requestJson, sessionId, groupId, groupDifficulty, initialTemplate = null, onCompleted, embedded = false, picker = false, listView = false }) {
  const api = useCallback((path, init) => requestJson(path, user.username, init), [requestJson, user.username])
  const [templates, setTemplates] = useState([])
  const [sessions, setSessions] = useState([])
  const [catalog, setCatalog] = useState({ services: [], object_types: [] })
  const [chosen, setChosen] = useState(initialTemplate)
  const [search, setSearch] = useState('')
  const [editorOpen, setEditorOpen] = useState(false)
  const [selectedSessionId, setSelectedSessionId] = useState(sessionId || '')
  const [count, setCount] = useState(5)
  const [target, setTarget] = useState(picker ? `group:${groupId}` : '')
  const [cards, setCards] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [editedText, setEditedText] = useState('')
  const [variantDraft, setVariantDraft] = useState({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    Promise.all([
      api('/api/scenario-templates?status=READY&limit=200'),
      picker ? Promise.resolve([]) : api('/api/training/sessions'),
      api('/api/scenario-templates/catalog'),
    ]).then(([library, available, names]) => {
      setTemplates(library.items)
      setSessions(available.filter((item) => ['DRAFT', 'READY'].includes(item.state)))
      setCatalog(names)
    }).catch((cause) => setError(cause.message))
  }, [api, picker])

  useEffect(() => {
    if (!chosen?.id || !selectedSessionId || picker) return undefined
    let active = true
    api(`/api/training/sessions/${selectedSessionId}/scenario-instances`)
      .then((instances) => {
        if (!active) return
        const drafts = instances.filter((item) => item.scenario_template_id === chosen.id && item.status === 'DRAFT')
        const latestBatch = drafts.at(-1)?.template_snapshot?.batch_seed
        const currentBatch = drafts.filter((item) => item.template_snapshot?.batch_seed === latestBatch)
        setCards(currentBatch)
        setSelectedId(currentBatch[0]?.id || null)
      }).catch((cause) => { if (active) setError(cause.message) })
    return () => { active = false }
  }, [api, chosen?.id, picker, selectedSessionId])

  const session = sessions.find((item) => item.id === Number(selectedSessionId))
  const selected = cards.find((item) => item.id === selectedId) || cards[0]
  const targets = session && !picker ? [
    ...session.groups.filter((group) => group.queue_mode === 'SHARED_QUEUE' && group.run_ids.length)
      .map((group) => ({ value: `group:${group.id}`, label: `Общий пул · ${group.name}` })),
    ...session.runs.filter((run) => run.queue_mode === 'INDIVIDUAL_QUEUE')
      .map((run) => ({ value: `run:${run.id}`, label: `Персонально · АРМ ${run.workstation_number}` })),
  ] : []

  useEffect(() => {
    setEditedText(selected?.initial_state_snapshot?.render?.rendered_text || '')
  }, [selectedId, selected?.initial_state_snapshot?.render?.rendered_text])

  useEffect(() => {
    setVariantDraft(selected?.initial_state_snapshot?.variant_facts || {})
  }, [selectedId, selected?.initial_state_snapshot?.variant_facts])

  const perform = async (action) => {
    setBusy(true)
    setError('')
    setNotice('')
    try { await action() } catch (cause) { setError(cause.message) } finally { setBusy(false) }
  }
  const updateCard = (updated) => setCards((current) => current.map((item) => item.id === updated.id ? updated : item))
  const hasManualEdits = cards.some((card) => card.initial_state_snapshot.render?.render_origin === 'MANUAL'
    || card.events.some((event) => event.render?.render_origin === 'MANUAL'))
  const confirmOverwrite = () => !hasManualEdits || window.confirm('В наборе есть правки преподавателя. Заменить эти тексты?')

  const createBatch = () => perform(async () => {
    const generated = await api(`/api/scenario-templates/${chosen.id}/batch`, options('POST', {
      count: Number(count), seed: Math.floor(Math.random() * 2147483647),
      training_session_id: Number(selectedSessionId), training_group_id: groupId || null,
    }))
    setCards(generated)
    setSelectedId(generated[0]?.id)
    setNotice(`Сформировано ${generated.length} карточек. Просмотрите и утвердите набор.`)
  })
  const replaceBatch = () => {
    if (!confirmOverwrite() || !window.confirm('Пересоздать весь набор карточек?')) return
    perform(async () => {
      const generated = await api(`/api/scenario-templates/${chosen.id}/batch`, options('POST', {
        count: Number(count), seed: Math.floor(Math.random() * 2147483647),
        training_session_id: Number(selectedSessionId), training_group_id: groupId || null,
      }))
      for (const card of cards) await api(`/api/scenario-instances/${card.id}`, { method: 'DELETE' })
      setCards(generated)
      setSelectedId(generated[0]?.id)
    })
  }
  const changeCard = (path, init) => perform(async () => updateCard(await api(path, init)))
  const saveVariantFacts = () => {
    if ((selected.initial_state_snapshot.render?.render_origin === 'MANUAL'
      || selected.events.some((event) => event.render?.render_origin === 'MANUAL'))
      && !window.confirm('Изменение условий заменит вручную исправленные тексты этой карточки. Продолжить?')) return
    changeCard(`/api/scenario-instances/${selected.id}/variant-facts`, options('PATCH', {
      ...variantDraft, floor: Number(variantDraft.floor),
    }))
  }
  const rerenderAll = () => {
    if (!confirmOverwrite()) return
    perform(async () => {
      for (const card of cards) {
        let updated = await api(`/api/scenario-instances/${card.id}/rerender-initial-message`, { method: 'POST' })
        for (const event of card.events.filter((item) => item.event_type === 'RESPONSE_MESSAGE')) {
          updated = await api(`/api/scenario-instances/${card.id}/events/${event.id}/rerender`, { method: 'POST' })
        }
        updateCard(updated)
      }
      setNotice('Тексты карточек и сообщений служб обновлены; факты сохранены.')
    })
  }
  const exclude = () => perform(async () => {
    await api(`/api/scenario-instances/${selected.id}`, { method: 'DELETE' })
    setCards((current) => current.filter((item) => item.id !== selected.id))
    setSelectedId(null)
  })
  const approve = () => perform(async () => {
    if (picker) {
      onCompleted?.()
      return
    }
    const [kind, id] = target.split(':')
    await api(`/api/training/sessions/${selectedSessionId}/scenario-instances/confirm-batch`, options('POST', {
      instance_ids: cards.map((card) => card.id),
      [kind === 'group' ? 'training_group_id' : 'training_run_id']: Number(id),
    }))
    setCards([])
    setChosen(null)
    setNotice('Набор утверждён и добавлен в занятие.')
    onCompleted?.()
  })

  const serviceName = (id) => catalog.services.find((service) => service.id === id)?.name || 'Служба'
  const objectTypeName = (id) => catalog.object_types.find((item) => item.id === id)?.name || 'Подходящий объект'
  const visibleTemplates = templates.filter((item) => `${item.name} ${item.incident_type || ''}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()))

  if (editorOpen) return <AdvancedScenarioLibrary embedded startCreate user={user} requestJson={requestJson} onSaved={(saved) => { setEditorOpen(false); setTemplates((current) => [saved, ...current]); setChosen(saved); setCards([]) }} />

  return <main className={`${styles.shell} ${embedded ? styles.embedded : ''}`}>
    {!embedded && <header className={styles.header}><div><small>Кабинет преподавателя</small><h1>Библиотека сценариев</h1></div></header>}
    {error && <p className={styles.error} role="alert">{error}</p>}
    {notice && <p className={styles.notice} role="status">{notice}</p>}
    <div className={styles.content}>
      {!chosen && <><div className={styles.topline}><div><h2>Выберите сценарий</h2><p>Карточки для занятия формируются из готового сценария.</p></div></div>
        <label className={styles.search}>Поиск<input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Название или тип происшествия" /></label>
        {listView ? <div className={styles.scenarioList}>
          <div className={styles.scenarioListHead}><span>Сценарий</span><span>Тип происшествия</span><span>Сложность</span><span>Объекты</span><span>Службы</span><span>Действия</span></div>
          {visibleTemplates.map((item) => <div className={styles.scenarioListRow} key={item.id}>
            <div><strong>{item.name}</strong><small>{item.description || 'Описание не заполнено'}</small></div>
            <span>{item.incident_type || '—'}</span>
            <span>{difficultyLabels[item.difficulty] || item.difficulty || '—'}</span>
            <span>{objectTypeName(item.object_rule?.object_type_id)}</span>
            <span>{item.services.map((service) => serviceName(service.service_id)).join(', ') || 'По условиям сценария'}</span>
            <button type="button" onClick={() => { setCards([]); setChosen(item) }}>Открыть</button>
          </div>)}
        </div> : <div className={styles.cards}>{visibleTemplates.map((item) => <button key={item.id} type="button" className={styles.card} onClick={() => { setCards([]); setChosen(item) }}>
          <span className={styles.status}>Готов к использованию</span><h3>{item.name}</h3><p>{item.description}</p>
          <dl><div><dt>Сложность</dt><dd>{difficultyLabels[item.difficulty]}</dd></div><div><dt>Объекты</dt><dd>{objectTypeName(item.object_rule?.object_type_id)}</dd></div></dl>
          <small>Службы: {item.services.map((service) => serviceName(service.service_id)).join(', ') || 'По условиям сценария'}</small><strong>Сформировать карточки →</strong>
        </button>)}</div>}{!visibleTemplates.length && <p>Готовых сценариев не найдено.</p>}<div className={styles.actions}><button type="button" onClick={() => setEditorOpen(true)}>+ Создать новый сценарий</button></div></>}
      {chosen && <>
        <h2>{chosen.name}</h2>
        {!cards.length && <section className={styles.panel}><p>{chosen.description}</p><div className={styles.batchForm}>
          {!picker && <label>Занятие<select value={selectedSessionId} onChange={(event) => { setSelectedSessionId(event.target.value); setTarget('') }}><option value="">Выберите занятие</option>{sessions.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>}
          <label>Количество карточек<input type="number" min="1" max="50" value={count} onChange={(event) => setCount(event.target.value)} /></label>
          {picker && groupDifficulty && <p>Сложность группы: {groupDifficulty}</p>}
          <p>Для каждой карточки будет выбран отдельный подходящий объект.</p>
        </div>{!picker && session && !targets.length && <p>Сначала создайте общую группу или назначьте АРМ в занятии.</p>}
          <button type="button" disabled={busy || (!picker && (!session || !targets.length)) || Number(count) < 1 || Number(count) > 50} onClick={createBatch}>Сформировать</button>
        </section>}
        {!!cards.length && <><div className={styles.topline}><div><h3>Сформировано {cards.length} карточек</h3><p>Просмотрите набор перед запуском занятия.</p></div></div>
          <div className={styles.reviewLayout}><nav className={styles.cardList} aria-label="Карточки набора">{cards.map((card, index) => <button type="button" key={card.id} className={card.id === selected?.id ? styles.selectedCard : ''} onClick={() => setSelectedId(card.id)}><b>{String(index + 1).padStart(2, '0')}</b><span>{card.object_snapshot.name}</span><small>{card.initial_state_snapshot.render?.render_origin === 'MANUAL' ? 'Изменена' : 'Готова'}</small></button>)}</nav>
            {selected && <section className={styles.panel}><h3>Карточка {cards.findIndex((item) => item.id === selected.id) + 1} из {cards.length}</h3>
              <p><b>Объект:</b> {selected.object_snapshot.name}</p><p><b>Адрес:</b> {selected.object_snapshot.address}</p><p><b>Район:</b> {selected.object_snapshot.district || '—'}</p>
              {!!Object.keys(selected.initial_state_snapshot.variant_facts || {}).length && <p><b>Условия:</b> {Object.values(selected.initial_state_snapshot.variant_facts).join(' · ')}</p>}
              {!!Object.keys(selected.template_snapshot.variant_options || {}).length && <details>
                <summary>Изменить условия карточки</summary>
                <div className={styles.batchForm}>{Object.entries(selected.template_snapshot.variant_options).map(([key, values]) => <label key={key}>{variantFactLabels[key] || key}<select aria-label={variantFactLabels[key] || key} value={variantDraft[key] ?? ''} onChange={(event) => setVariantDraft((current) => ({ ...current, [key]: key === 'floor' ? Number(event.target.value) : event.target.value }))}>{values.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>)}</div>
                <button type="button" disabled={busy || Object.keys(selected.template_snapshot.variant_options).every((key) => variantDraft[key] === selected.initial_state_snapshot.variant_facts[key])} onClick={saveVariantFacts}>Сохранить условия</button>
              </details>}
              <label>Карточка ДДС<textarea value={editedText} onChange={(event) => setEditedText(event.target.value)} /></label>
              <small>{renderOriginLabels[selected.initial_state_snapshot.render?.render_origin] || 'Текст подготовлен'}</small>
              <div className={styles.actions}><button type="button" disabled={busy || !editedText.trim() || editedText === selected.initial_state_snapshot.render?.rendered_text} onClick={() => changeCard(`/api/scenario-instances/${selected.id}/initial-message`, options('PATCH', { text: editedText }))}>Сохранить текст</button>
                <button type="button" disabled={busy} onClick={() => changeCard(`/api/scenario-instances/${selected.id}/rerender-initial-message`, { method: 'POST' })}>Перегенерировать текст</button>
                <button type="button" disabled={busy} onClick={() => changeCard(`/api/scenario-instances/${selected.id}/regenerate-card`, { method: 'POST' })}>Перегенерировать карточку</button>
                <button type="button" disabled={busy} onClick={exclude}>Исключить из набора</button></div>
              <h4>Работа служб</h4>{selected.events.filter((event) => event.event_type === 'RESPONSE_MESSAGE').map((event) => <ResponseMessageEditor key={event.id} event={event} instanceId={selected.id} busy={busy} onChange={changeCard} />)}
            </section>}</div>
          <section className={styles.panel}><h3>{picker ? 'Добавление в набор группы' : 'Утверждение набора'}</h3>{!picker && <label>Распределение<select value={target} onChange={(event) => setTarget(event.target.value)}><option value="">Выберите общий пул или АРМ</option>{targets.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>}
            <div className={styles.actions}><button type="button" disabled={busy} onClick={rerenderAll}>Перегенерировать тексты всех карточек</button><button type="button" disabled={busy} onClick={replaceBatch}>Пересоздать весь набор</button><button type="button" disabled={busy || !target} onClick={approve}>{picker ? 'Добавить в набор группы' : 'Утвердить набор и добавить в занятие'}</button></div>
          </section></>}
      </>}
    </div>
  </main>
}
