/* eslint-disable react/prop-types */
import { useCallback, useEffect, useState } from 'react'
import styles from './ScenarioLibrary.module.css'
import { difficultyLabels, renderOriginLabels } from './uiLabels.js'

const options = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
const variantFactLabels = { floor: 'Этаж', room: 'Помещение', observation: 'Обстановка', casualties: 'Пострадавшие' }
const steps = ['Основное', 'Классификация', 'Объект', 'Службы', 'Исходная карточка', 'События', 'Оценивание', 'Предпросмотр']
const eventTypes = { INITIAL_REPORT: 'Исходное сообщение', ADDITIONAL_INFO: 'Дополнительная информация', RESPONSE_MESSAGE: 'Сообщение группы', SITUATION_CHANGE: 'Изменение обстановки', SYSTEM_EVENT: 'Системное событие' }
const blank = () => ({ name: '', description: '', difficulty: 3, classifier_rule_id: null, object_rule: null, initial_title: '', initial_description: '', initial_caller_text: '', events: [], services: [], expected_actions: [], criteria: [], created_by_user_id: null })
const toInput = (item) => Object.fromEntries(Object.keys(blank()).map((key) => [key, item[key]]))
const formatOffset = (seconds) => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
const asOptions = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

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

export default function ScenarioLibrary({ user, requestJson, onBack, sessionId }) {
  const api = useCallback((path, init) => requestJson(path, user.username, init), [requestJson, user.username])
  const [templates, setTemplates] = useState([])
  const [sessions, setSessions] = useState([])
  const [catalog, setCatalog] = useState({ services: [], object_types: [] })
  const [chosen, setChosen] = useState(null)
  const [selectedSessionId, setSelectedSessionId] = useState(sessionId || '')
  const [count, setCount] = useState(5)
  const [differentObjects, setDifferentObjects] = useState(true)
  const [target, setTarget] = useState('')
  const [cards, setCards] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [editedText, setEditedText] = useState('')
  const [variantDraft, setVariantDraft] = useState({})
function InstanceReview({ instance, busy, api, perform, onChange, sessions, trainingSessionId, onSelectSession }) {
  const editable = instance.status === 'DRAFT'
  const action = (path, options) => perform(async () => {
    const updated = await api(path, options)
    onChange(updated)
  })
  const base = `/api/scenario-instances/${instance.id}`
  const initial = instance.initial_state_snapshot
  return <section className={styles.panel}>
    <h3>Экземпляр #{instance.id} · {instance.status}</h3>
    <p>{instance.name} · сложность {instance.difficulty}/5</p>
    <p>Объект: {instance.object_snapshot.name} · {instance.object_snapshot.address}</p>
    <p>Классификация: {instance.classifier_snapshot.final_incident_type}</p>
    <p>Занятие: {instance.training_session_id ? `#${instance.training_session_id}` : 'не привязано'}</p>
    <h4>Службы</h4><ul>{instance.service_snapshot.map((service) => <li key={service.service_id}>{service.official_name}</li>)}</ul>
    <RenderEditor title="Исходная карточка" facts={[initial.title, initial.description, initial.caller_text]} render={initial.render} editable={editable} busy={busy}
      onSave={(text) => action(`${base}/initial-message`, asOptions('PATCH', { text }))}
      onRerender={() => action(`${base}/rerender-initial-message`, { method: 'POST' })} />
    <h4>Timeline</h4><ol>{instance.events.map((event) => <li key={event.id}>T+{formatOffset(event.offset_seconds)} · {event.title}
      {event.event_type === 'RESPONSE_MESSAGE' ? <RenderEditor title="Сообщение группы" facts={[event.title, event.description, event.source_type]} render={event.render} editable={editable} busy={busy}
        onSave={(text) => action(`${base}/events/${event.id}/message`, asOptions('PATCH', { text }))}
        onRerender={() => action(`${base}/events/${event.id}/rerender`, { method: 'POST' })} /> : <p>{event.description}</p>}
    </li>)}</ol>
    {editable && <button type="button" disabled={busy} onClick={() => action(`${base}/confirm`, { method: 'POST' })}>Подтвердить тексты и экземпляр</button>}
    {!instance.training_session_id && <label>Использовать в занятии<select value={trainingSessionId || ''} onChange={(event) => onSelectSession(Number(event.target.value) || null)}><option value="">Выберите занятие</option>{sessions.map((session) => <option key={session.id} value={session.id}>{session.title} · #{session.id}</option>)}</select></label>}
    {!instance.training_session_id && <button type="button" disabled={busy || !trainingSessionId} onClick={() => action(`${base}/attach`, asOptions('POST', { training_session_id: trainingSessionId }))}>Привязать к занятию</button>}
  </section>
}

export default function ScenarioLibrary({ user, requestJson, onBack, embedded = false }) {
  const api = useCallback((path, options) => requestJson(path, user.username, options), [requestJson, user.username])
  const [filters, setFilters] = useState({ q: '', status: 'READY', difficulty: '', incident_group: '', incident_type: '', object_type_id: '', district: '', administrative_area: '', service_id: '', created_by: '' })
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [catalog, setCatalog] = useState({ rules: [], object_types: [], services: [], objects: [], tags: [], authors: [] })
  const [ruleSearch, setRuleSearch] = useState('')
  const [objectSearch, setObjectSearch] = useState('')
  const [ruleDetail, setRuleDetail] = useState(null)
  const [selected, setSelected] = useState(null)
  const [draft, setDraft] = useState(blank())
  const [step, setStep] = useState(0)
  const [validation, setValidation] = useState(null)
  const [dirty, setDirty] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    Promise.all([
      api('/api/scenario-templates?status=READY&limit=100'),
      api('/api/training/sessions'),
      api('/api/scenario-templates/catalog'),
    ]).then(([library, available, names]) => {
      setTemplates(library.items)
      setSessions(available.filter((item) => ['DRAFT', 'READY'].includes(item.state)))
      setCatalog(names)
    }).catch((cause) => setError(cause.message))
  }, [api])

  useEffect(() => {
    if (!chosen?.id || !selectedSessionId) return undefined
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
  }, [api, chosen?.id, selectedSessionId])

  const session = sessions.find((item) => item.id === Number(selectedSessionId))
  const selected = cards.find((item) => item.id === selectedId) || cards[0]
  const targets = session ? [
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
      training_session_id: Number(selectedSessionId), different_objects: differentObjects,
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
        training_session_id: Number(selectedSessionId), different_objects: differentObjects,
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
    const [kind, id] = target.split(':')
    await api(`/api/training/sessions/${selectedSessionId}/scenario-instances/confirm-batch`, options('POST', {
      instance_ids: cards.map((card) => card.id),
      [kind === 'group' ? 'training_group_id' : 'training_run_id']: Number(id),
    }))
    setCards([])
    setChosen(null)
    setNotice('Набор утверждён и добавлен в занятие.')
  })

  const serviceName = (id) => catalog.services.find((service) => service.id === id)?.name || 'Служба'
  const objectTypeName = (id) => catalog.object_types.find((item) => item.id === id)?.name || 'Подходящий объект'

  return <main className={styles.shell}>
    <header className={styles.header}><div><small>Кабинет преподавателя</small><h1>Библиотека сценариев</h1></div><button type="button" onClick={onBack}>← К занятиям</button></header>
    {error && <p className={styles.error} role="alert">{error}</p>}
    {notice && <p className={styles.notice} role="status">{notice}</p>}
    <div className={styles.content}>
      {!chosen && <><div className={styles.topline}><div><h2>Выберите готовый сценарий</h2><p>Карточки для занятия формируются автоматически из проверенных данных.</p></div></div>
        <div className={styles.cards}>{templates.map((item) => <button key={item.id} type="button" className={styles.card} onClick={() => { setCards([]); setChosen(item) }}>
          <span className={styles.status}>Готов к использованию</span><h3>{item.name}</h3><p>{item.description}</p>
          <dl><div><dt>Сложность</dt><dd>{difficultyLabels[item.difficulty]}</dd></div><div><dt>Объекты</dt><dd>{objectTypeName(item.object_rule?.object_type_id)}</dd></div></dl>
          <small>Службы: {item.services.map((service) => serviceName(service.service_id)).join(', ') || 'По условиям сценария'}</small><strong>Сформировать карточки →</strong>
        </button>)}</div>{!templates.length && <p>Готовых сценариев пока нет.</p>}</>}
      {chosen && <><button type="button" className={styles.link} onClick={() => { setChosen(null); setCards([]) }}>← Библиотека</button>
        <h2>{chosen.name}</h2>
        {!cards.length && <section className={styles.panel}><p>{chosen.description}</p><div className={styles.batchForm}>
          <label>Занятие<select value={selectedSessionId} onChange={(event) => { setSelectedSessionId(event.target.value); setTarget('') }}><option value="">Выберите занятие</option>{sessions.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
          <label>Количество карточек<input type="number" min="1" max="50" value={count} onChange={(event) => setCount(event.target.value)} /></label>
          <label className={styles.inlineCheck}><input type="checkbox" checked={differentObjects} onChange={(event) => setDifferentObjects(event.target.checked)} /> Использовать разные объекты</label>
        </div>{session && !targets.length && <p>Сначала создайте общую группу или назначьте АРМ в занятии.</p>}
          <button type="button" disabled={busy || !session || !targets.length || Number(count) < 1 || Number(count) > 50} onClick={createBatch}>Сформировать {count} карточек</button>
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
          <section className={styles.panel}><h3>Утверждение набора</h3><label>Распределение<select value={target} onChange={(event) => setTarget(event.target.value)}><option value="">Выберите общий пул или АРМ</option>{targets.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
            <div className={styles.actions}><button type="button" disabled={busy} onClick={rerenderAll}>Перегенерировать тексты всех карточек</button><button type="button" disabled={busy} onClick={replaceBatch}>Пересоздать весь набор</button><button type="button" disabled={busy || !target} onClick={approve}>Утвердить набор и добавить в занятие</button></div>
          </section></>}
      </>}
    </div>
  return <main className={`${styles.shell} ${embedded ? styles.embedded : ''}`}>
    {!embedded && <header className={styles.header}><div><small>Кабинет преподавателя / методические материалы</small><h1>Библиотека сценариев</h1></div><button type="button" onClick={onBack}>← К занятиям</button></header>}
    {error && <p className={styles.error} role="alert">{error}</p>}
    {notice && <p className={styles.notice} role="status">{notice}</p>}
    {generation && <div className={styles.content}>
      <div className={styles.topline}><div><button type="button" className={styles.link} onClick={() => { setGeneration(null); setGenerationPreview(null); setGeneratedInstance(null) }}>← Библиотека</button><h2>Экземпляр: {generation.name}</h2></div></div>
      {!generatedInstance && <section className={styles.panel}>
        <h3>Параметры генерации</h3>
        <div className={styles.fields}>
          <label>Сложность<select value={generationInput.difficulty} onChange={(event) => { setGenerationInput((old) => ({ ...old, difficulty: Number(event.target.value) })); setGenerationPreview(null) }}>{[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>{value}/5</option>)}</select></label>
          {generation.object_rule?.selection_mode === 'GENERIC' && <><label>Выбор объекта<select value={generationInput.variant_mode} onChange={(event) => { setGenerationInput((old) => ({ ...old, variant_mode: event.target.value, object_id: null })); setGenerationPreview(null) }}><option value="MANUAL">Вручную</option><option value="RANDOM">Случайный по seed</option></select></label>{generationInput.variant_mode === 'MANUAL' && <><label>Поиск объекта<input value={generationInput.object_query} onChange={(event) => { setGenerationInput((old) => ({ ...old, object_query: event.target.value, object_id: null })); setGenerationPreview(null) }} placeholder="Название, адрес или район" /></label><label>Подходящий объект<select value={generationInput.object_id || ''} onChange={(event) => { setGenerationInput((old) => ({ ...old, object_id: Number(event.target.value) || null })); setGenerationPreview(null) }}><option value="">Выберите объект</option>{generationCandidates.map((object) => <option key={object.id} value={object.id}>{object.name} · {object.address}</option>)}</select></label></>}</>}
          <label>Seed<input type="number" min="0" max="2147483647" value={generationInput.seed} onChange={(event) => { setGenerationInput((old) => ({ ...old, seed: Number(event.target.value) })); setGenerationPreview(null) }} /></label>
          <label>Занятие<select value={generationInput.training_session_id || ''} onChange={(event) => { setGenerationInput((old) => ({ ...old, training_session_id: Number(event.target.value) || null })); setGenerationPreview(null) }}><option value="">Привязать позже</option>{sessions.map((session) => <option key={session.id} value={session.id}>{session.title} · #{session.id}</option>)}</select></label>
        </div>
        {!generationPreview && <button type="button" disabled={busy} onClick={refreshGenerationPreview}>Показать предпросмотр</button>}
        {generationPreview && <div className={styles.preview}><div><h4>Объект</h4><p>{generationPreview.object_snapshot?.name || 'Выберите объект'}</p><p>{generationPreview.object_snapshot?.address}</p><p>Подходящих объектов: {generationPreview.matching_object_count}</p></div><div><h4>Классификация и службы</h4><p>{generationPreview.classifier_snapshot.final_incident_type}</p><ul>{generationPreview.service_snapshot.map((service) => <li key={service.service_id}>{service.official_name}</li>)}</ul><h4>Timeline</h4><ol>{generationPreview.events.map((event, index) => <li key={index}>T+{formatOffset(event.offset_seconds)} · {event.title} — {event.description}</li>)}</ol></div></div>}
        {generationPreview?.object_snapshot && <button type="button" disabled={busy} onClick={createInstance}>Сгенерировать экземпляр</button>}
      </section>}
      {generatedInstance && <InstanceReview instance={generatedInstance} busy={busy} api={api} perform={perform} onChange={(updated) => { setGeneratedInstance(updated); if (updated.status !== generatedInstance.status) load() }} sessions={sessions} trainingSessionId={generationInput.training_session_id} onSelectSession={(id) => setGenerationInput((old) => ({ ...old, training_session_id: id }))} />}
    </div>}
    {!selected && !generation && <div className={styles.content}>
      {availableInstances.some((instance) => instance.status === 'DRAFT') && <section className={styles.panel}><h3>Экземпляры на проверке</h3><div className={styles.cards}>{availableInstances.filter((instance) => instance.status === 'DRAFT').map((instance) => <button className={styles.card} type="button" key={instance.id} onClick={() => openInstance(instance)}><b>#{instance.id} · {instance.name}</b><small>{instance.object_snapshot.name} · тексты ждут подтверждения</small></button>)}</div></section>}
      <div className={styles.topline}><div><h2>Сценарии преподавателей</h2><p>Общая библиотека методических шаблонов. По умолчанию показаны проверенные READY-сценарии.</p></div><button type="button" onClick={() => { setSelected({ status: 'DRAFT' }); setDraft({ ...blank(), created_by_user_id: user.id }); setStep(0); setValidation(null); setDirty(false) }}>+ Создать сценарий</button></div>
      <div className={styles.filters}>
        <label>Поиск<input value={filters.q} onChange={(event) => changeFilter('q', event.target.value)} placeholder="Название" /></label>
        <label>Статус<select value={filters.status} onChange={(event) => changeFilter('status', event.target.value)}><option value="READY">Готовые</option><option value="DRAFT">Черновики</option><option value="ARCHIVED">Архив</option><option value="ALL">Все</option></select></label>
        <label>Сложность<select value={filters.difficulty} onChange={(event) => changeFilter('difficulty', event.target.value)}><option value="">Любая</option>{[1, 2, 3, 4, 5].map((value) => <option key={value}>{value}</option>)}</select></label>
        <label>Тип объекта<select value={filters.object_type_id} onChange={(event) => changeFilter('object_type_id', event.target.value)}><option value="">Любой</option>{catalog.object_types.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}</select></label>
        <label>Служба<select value={filters.service_id} onChange={(event) => changeFilter('service_id', event.target.value)}><option value="">Любая</option>{catalog.services.map((service) => <option key={service.id} value={service.id}>{service.name}</option>)}</select></label>
        <label>Район<input value={filters.district} onChange={(event) => changeFilter('district', event.target.value)} placeholder="Для конкретного объекта" /></label>
        <label>Округ<input value={filters.administrative_area} onChange={(event) => changeFilter('administrative_area', event.target.value)} placeholder="Для конкретного объекта" /></label>
        <label>Автор<select value={filters.created_by} onChange={(event) => changeFilter('created_by', event.target.value)}><option value="">Любой</option>{catalog.authors.map((author) => <option key={author.id} value={author.id}>{author.name}</option>)}</select></label>
        <label>Группа SRC-006<input value={filters.incident_group} onChange={(event) => changeFilter('incident_group', event.target.value)} placeholder="Например, пожар" /></label>
        <label>Тип происшествия<input value={filters.incident_type} onChange={(event) => changeFilter('incident_type', event.target.value)} placeholder="Из SRC-006" /></label>
      </div>
      <p className={styles.count}>Найдено: {total}</p>
      {loading ? <p>Загрузка библиотеки…</p> : items.length ? <div className={styles.cards}>{items.map((item) => <button className={styles.card} type="button" key={item.id} onClick={() => open(item)}>
        <span className={styles.status}>{item.status}</span><h3>{item.name || 'Без названия'}</h3><p>{item.incident_type || 'Классификация не выбрана'}</p><p>{item.description || 'Описание не задано'}</p>
        <dl><div><dt>Сложность</dt><dd>{item.difficulty}/5</dd></div><div><dt>Объект</dt><dd>{typeName(item.object_rule?.object_type_id)}</dd></div><div><dt>Событий</dt><dd>{item.events.length}</dd></div><div><dt>Служб</dt><dd>{item.services.length}</dd></div></dl>
        <small>{item.object_rule?.selection_mode === 'OBJECT_BOUND' ? `${item.object_rule.specific_object_name || 'Конкретный объект'} · ${item.object_rule.district || 'район не указан'}` : 'Любой подходящий объект'} · {catalog.authors.find((author) => author.id === item.created_by_user_id)?.name || `Автор #${item.created_by_user_id}`}</small>
      </button>)}</div> : <p>По выбранным фильтрам сценариев нет.</p>}
      <div className={styles.actions}><button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 24))}>Назад</button><span>{total ? offset + 1 : 0}–{Math.min(total, offset + 24)} из {total}</span><button type="button" disabled={offset + 24 >= total} onClick={() => setOffset(offset + 24)}>Далее</button></div>
    </div>}
    {selected && !generation && <div className={styles.content}>
      <div className={styles.topline}><div><button type="button" className={styles.link} onClick={() => { setSelected(null); setValidation(null) }}>← Библиотека</button><h2>{selected.id ? draft.name || 'Без названия' : 'Новый сценарий'}</h2><p>{selected.status} · {selected.id ? `№ ${selected.id}` : 'Не сохранён'}</p></div><div className={styles.actions}>{editable && <button type="button" disabled={busy} onClick={save}>Сохранить черновик</button>}{selected.id && <button type="button" disabled={busy} onClick={duplicate}>Создать копию</button>}{selected.status === 'READY' && <button type="button" disabled={busy} onClick={() => startGeneration(selected)}>Сгенерировать экземпляр</button>}{selected.status === 'READY' && <button type="button" disabled={busy} onClick={archive}>Архивировать</button>}</div></div>
      <nav className={styles.steps} aria-label="Редактор сценария">{steps.map((label, index) => <button type="button" key={label} onClick={() => setStep(index)} className={step === index ? styles.current : ''}><b>{index + 1}</b>{label}</button>)}</nav>
      <section className={styles.panel}>
        <h3>{steps[step]}</h3>
        {step === 0 && <div className={styles.fields}><label>Название<input disabled={!editable} value={draft.name} onChange={(event) => change('name', event.target.value)} /></label><label>Описание<textarea disabled={!editable} value={draft.description} onChange={(event) => change('description', event.target.value)} /></label><label>Сложность<select disabled={!editable} value={draft.difficulty} onChange={(event) => change('difficulty', Number(event.target.value))}>{[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>{value}/5</option>)}</select></label>{user.role === 'ADMIN' && <label>Автор<select disabled={!editable} value={draft.created_by_user_id || ''} onChange={(event) => change('created_by_user_id', Number(event.target.value) || null)}><option value="">Выберите преподавателя</option>{catalog.authors.map((author) => <option key={author.id} value={author.id}>{author.name}</option>)}</select></label>}</div>}
        {step === 1 && <div className={styles.fields}><p>Тип происшествия выбирается только из SRC-006.</p><label>Поиск в классификаторе<input value={ruleSearch} onChange={(event) => setRuleSearch(event.target.value)} placeholder="Например, пожар" /></label><label>Правило<select disabled={!editable} value={draft.classifier_rule_id || ''} onChange={(event) => { change('classifier_rule_id', Number(event.target.value) || null); change('services', []) }}><option value="">Выберите правило</option>{catalog.rules.map((rule) => <option key={rule.id} value={rule.id}>{rule.group} / {rule.type} · #{rule.id}</option>)}</select></label>{ruleDetail && <div className={styles.fact}><b>{ruleDetail.final_incident_type}</b><p>{ruleDetail.incident_group} · {ruleDetail.source_reference}</p><ul>{ruleDetail.features.map((feature) => <li key={feature.id}>{feature.level}: {feature.name}</li>)}</ul></div>}{chosenRule && <small>Выбрано: {chosenRule.type}</small>}</div>}
        {step === 2 && <div className={styles.fields}><p>Для общего правила подходят выбранный тип и его потомки. При READY backend проверяет наличие объектов.</p><label>Режим<select disabled={!editable} value={draft.object_rule?.selection_mode || ''} onChange={(event) => change('object_rule', event.target.value ? { selection_mode: event.target.value, object_type_id: draft.object_rule?.object_type_id || catalog.object_types[0]?.id || 0, specific_object_id: null, required_tags: [] } : null)}><option value="">Не выбран</option><option value="GENERIC">Любой подходящий</option><option value="OBJECT_BOUND">Конкретный объект</option></select></label>{draft.object_rule && <><label>Тип объекта<select disabled={!editable} value={draft.object_rule.object_type_id} onChange={(event) => change('object_rule', { ...draft.object_rule, object_type_id: Number(event.target.value), specific_object_id: null })}>{catalog.object_types.map((type) => <option key={type.id} value={type.id}>{type.name} ({type.code})</option>)}</select></label><fieldset><legend>Обязательные теги</legend>{catalog.tags.map((tag) => <label key={tag.code} className={styles.check}><input type="checkbox" disabled={!editable} checked={draft.object_rule.required_tags.includes(tag.code)} onChange={(event) => change('object_rule', { ...draft.object_rule, required_tags: event.target.checked ? [...draft.object_rule.required_tags, tag.code] : draft.object_rule.required_tags.filter((value) => value !== tag.code) })} />{tag.name}</label>)}</fieldset>{draft.object_rule.selection_mode === 'OBJECT_BOUND' && <><label>Поиск объекта<input value={objectSearch} onChange={(event) => setObjectSearch(event.target.value)} placeholder="Название школы, адрес…" /></label><label>Объект<select disabled={!editable} value={draft.object_rule.specific_object_id || ''} onChange={(event) => change('object_rule', { ...draft.object_rule, specific_object_id: Number(event.target.value) || null })}><option value="">Выберите объект</option>{catalog.objects.map((object) => <option key={object.id} value={object.id}>{object.name} · {object.address}</option>)}</select></label></>}{chosenObject && <p>{chosenObject.address} · {chosenObject.district}</p>}</>}</div>}
        {step === 3 && <div className={styles.fields}><p>Автоматические рекомендации берутся из выбранного правила. Дополнительные службы выбираются из каталога.</p>{ruleDetail?.services.length ? <fieldset><legend>По классификатору</legend>{ruleDetail.services.map((service) => <label className={styles.check} key={service.id}><input type="checkbox" disabled={!editable} checked={draft.services.some((item) => item.service_id === service.id)} onChange={(event) => change('services', event.target.checked ? [...draft.services, { service_id: service.id, source: 'CLASSIFIER' }] : draft.services.filter((item) => item.service_id !== service.id))} />{service.official_name}</label>)}</fieldset> : <p>Для правила нет подтверждённых служб.</p>}<label>Дополнительная служба<select disabled={!editable} value="" onChange={(event) => { const id = Number(event.target.value); if (id && !draft.services.some((item) => item.service_id === id)) addList('services', { service_id: id, source: 'MANUAL' }) }}><option value="">Добавить из каталога…</option>{catalog.services.filter((service) => !draft.services.some((item) => item.service_id === service.id)).map((service) => <option key={service.id} value={service.id}>{service.name}</option>)}</select></label><ul>{draft.services.map((service, index) => <li key={service.service_id}>{serviceName(service.service_id)} · {service.source}{editable && <button type="button" onClick={() => removeList('services', index)}>Удалить</button>}</li>)}</ul></div>}
        {step === 4 && <div className={styles.fields}><label>Заголовок карточки<input disabled={!editable} value={draft.initial_title} onChange={(event) => change('initial_title', event.target.value)} /></label><label>Описание происшествия<textarea disabled={!editable} value={draft.initial_description} onChange={(event) => change('initial_description', event.target.value)} /></label><label>Слова заявителя<textarea disabled={!editable} value={draft.initial_caller_text} onChange={(event) => change('initial_caller_text', event.target.value)} /></label><div className={styles.fact}><b>Видит обучаемый</b><h4>{draft.initial_title || 'Заголовок'}</h4><p>{draft.initial_description || 'Описание'}</p><blockquote>{draft.initial_caller_text}</blockquote></div></div>}
        {step === 5 && <div className={styles.fields}><p>События выполняются в указанном порядке по учебному времени. Начальное сообщение должно быть одно, в T+0.</p>{draft.events.map((event, index) => <div className={styles.entry} key={index}><label>Время T+ секунд<input type="number" min="0" disabled={!editable} value={event.offset_seconds} onChange={(e) => updateList('events', index, { offset_seconds: Number(e.target.value) })} /></label><label>Тип<select disabled={!editable} value={event.event_type} onChange={(e) => updateList('events', index, { event_type: e.target.value, target_service_id: e.target.value === 'RESPONSE_MESSAGE' ? event.target_service_id ?? null : null })}>{Object.entries(eventTypes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>Название<input disabled={!editable} value={event.title} onChange={(e) => updateList('events', index, { title: e.target.value })} /></label><label>Описание<textarea disabled={!editable} value={event.description} onChange={(e) => updateList('events', index, { description: e.target.value })} /></label><label>Источник<input disabled={!editable} value={event.source_type} onChange={(e) => updateList('events', index, { source_type: e.target.value })} /></label>{event.event_type === 'RESPONSE_MESSAGE' && <label>От кого поступает сообщение<select disabled={!editable} value={event.target_service_id || ''} required onChange={(e) => updateList('events', index, { target_service_id: Number(e.target.value) || null })}><option value="">Выберите службу</option>{draft.services.map((service) => <option key={service.service_id} value={service.service_id}>{serviceName(service.service_id)}</option>)}</select>{!event.target_service_id && <small>Для сообщения группы необходимо выбрать службу.</small>}</label>}{editable && <div className={styles.actions}><button type="button" disabled={index === 0} onClick={() => { const next = [...draft.events]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; change('events', next) }}>↑</button><button type="button" disabled={index === draft.events.length - 1} onClick={() => { const next = [...draft.events]; [next[index + 1], next[index]] = [next[index], next[index + 1]]; change('events', next) }}>↓</button><button type="button" onClick={() => removeList('events', index)}>Удалить</button></div>}</div>)}{editable && <button type="button" onClick={() => addList('events', { offset_seconds: draft.events.length ? draft.events.at(-1).offset_seconds + 60 : 0, event_type: draft.events.length ? 'ADDITIONAL_INFO' : 'INITIAL_REPORT', title: '', description: '', source_type: 'SYSTEM', target_service_id: null })}>+ Добавить событие</button>}</div>}
        {step === 6 && <div className={styles.fields}><h4>Ожидаемые действия</h4>{draft.expected_actions.map((action, index) => <div className={styles.entry} key={index}><label>Тип действия<input disabled={!editable} value={action.expected_action_type} onChange={(e) => updateList('expected_actions', index, { expected_action_type: e.target.value })} /></label><label>Целевой статус<input disabled={!editable} value={action.target_status || ''} onChange={(e) => updateList('expected_actions', index, { target_status: e.target.value || null })} /></label><label>Служба<select disabled={!editable} value={action.expected_service_id || ''} onChange={(e) => updateList('expected_actions', index, { expected_service_id: Number(e.target.value) || null })}><option value="">Не требуется</option>{catalog.services.map((service) => <option key={service.id} value={service.id}>{service.name}</option>)}</select></label><label>Срок, секунд<input type="number" min="0" disabled={!editable} value={action.deadline_seconds ?? ''} onChange={(e) => updateList('expected_actions', index, { deadline_seconds: e.target.value === '' ? null : Number(e.target.value) })} /></label><label>Описание<textarea disabled={!editable} value={action.description} onChange={(e) => updateList('expected_actions', index, { description: e.target.value })} /></label><label className={styles.check}><input type="checkbox" disabled={!editable} checked={action.is_critical} onChange={(e) => updateList('expected_actions', index, { is_critical: e.target.checked })} />Критично</label>{editable && <button type="button" onClick={() => removeList('expected_actions', index)}>Удалить действие</button>}</div>)}{editable && <button type="button" onClick={() => addList('expected_actions', { expected_action_type: '', target_status: null, expected_service_id: null, deadline_seconds: null, is_critical: false, description: '' })}>+ Добавить действие</button>}<h4>Критерии оценки</h4>{draft.criteria.map((criterion, index) => <div className={styles.entry} key={index}><label>Название<input disabled={!editable} value={criterion.name} onChange={(e) => updateList('criteria', index, { name: e.target.value })} /></label><label>Описание<textarea disabled={!editable} value={criterion.description} onChange={(e) => updateList('criteria', index, { description: e.target.value })} /></label><label>Вес<input type="number" min="0" disabled={!editable} value={criterion.weight ?? ''} onChange={(e) => updateList('criteria', index, { weight: e.target.value === '' ? null : Number(e.target.value) })} /></label><label className={styles.check}><input type="checkbox" disabled={!editable} checked={criterion.is_critical} onChange={(e) => updateList('criteria', index, { is_critical: e.target.checked })} />Критично</label>{editable && <button type="button" onClick={() => removeList('criteria', index)}>Удалить критерий</button>}</div>)}{editable && <button type="button" onClick={() => addList('criteria', { name: '', description: '', weight: null, is_critical: false })}>+ Добавить критерий</button>}</div>}
        {step === 7 && <div className={styles.preview}><div><h4>Видит обучаемый</h4><b>{draft.initial_title}</b><p>{draft.initial_description}</p><blockquote>{draft.initial_caller_text}</blockquote></div><div><h4>Видит преподаватель</h4><p><b>{draft.name}</b> · сложность {draft.difficulty}/5</p><p>Правило SRC-006: #{draft.classifier_rule_id || '—'} · {ruleDetail?.final_incident_type || ''}</p><p>Объект: {typeName(draft.object_rule?.object_type_id)} · {draft.object_rule?.selection_mode || '—'}</p><p>Теги: {draft.object_rule?.required_tags.join(', ') || '—'}</p><p>Службы: {draft.services.map((service) => serviceName(service.service_id)).join(', ') || '—'}</p><h5>Timeline</h5><ol>{draft.events.map((event, index) => <li key={index}>T+{formatOffset(event.offset_seconds)} · {eventTypes[event.event_type]}{event.event_type === 'RESPONSE_MESSAGE' ? ` · ${serviceName(event.target_service_id) || 'служба не выбрана'}` : ''} · {event.title} — {event.description}</li>)}</ol><h5>Ожидаемые действия</h5><ul>{draft.expected_actions.map((action, index) => <li key={index}>{action.expected_action_type}: {action.description}</li>)}</ul><h5>Критерии</h5><ul>{draft.criteria.map((criterion, index) => <li key={index}>{criterion.name}: {criterion.description}</li>)}</ul></div>{selected.id && <div className={styles.validation}><button type="button" disabled={busy} onClick={check}>Проверить сценарий</button>{dirty && <p>Сохраните изменения перед проверкой.</p>}{validation && <><p>Подходящих объектов: {validation.matching_object_count}</p>{validation.errors.length ? <ul>{validation.errors.map((issue) => <li key={issue}>{issue}</li>)}</ul> : <p>Ошибок не найдено.</p>}</>}{selected.status === 'DRAFT' && !dirty && validation?.errors.length === 0 && <button type="button" disabled={busy} onClick={ready}>Перевести в READY</button>}</div>}</div>}
        <div className={styles.actions}><button type="button" disabled={step === 0} onClick={() => setStep(step - 1)}>← Назад</button><span>Шаг {step + 1} из {steps.length}</span><button type="button" disabled={step === steps.length - 1} onClick={() => setStep(step + 1)}>Далее →</button></div>
      </section>
    </div>}
  </main>
}
