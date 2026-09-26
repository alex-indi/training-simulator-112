/* eslint-disable react/prop-types */
import { useCallback, useEffect, useState } from 'react'
import styles from './ScenarioLibrary.module.css'
import { difficultyLabels, renderOriginLabels } from './uiLabels.js'
import { compactInstanceName, compactObjectName } from './scenarioDisplay.js'

const steps = ['Основное', 'Тип происшествия', 'Тип объекта', 'Службы', 'Карточка и варианты', 'Работа служб', 'Оценивание', 'Предпросмотр']
const eventTypes = { INITIAL_REPORT: 'Исходное сообщение', ADDITIONAL_INFO: 'Дополнительная информация', RESPONSE_MESSAGE: 'Сообщение группы', SITUATION_CHANGE: 'Изменение обстановки', SYSTEM_EVENT: 'Системное событие' }
const responseStates = { ACKNOWLEDGED: 'Задание подтверждено', EN_ROUTE: 'Следует к месту', ARRIVED: 'Прибыла', WORKING: 'Выполняет работы', COMPLETED: 'Завершила работы' }
const blank = () => ({ name: '', description: '', difficulty: 3, classifier_rule_id: null, object_rule: null, initial_title: '', initial_description: '', initial_caller_text: '', variant_options: {}, events: [], services: [], expected_actions: [], criteria: [] })
const variantLabels = { floor: 'Этаж', room: 'Помещение', observation: 'Обстановка', casualties: 'Пострадавшие' }
const toInput = (item) => Object.fromEntries(Object.keys(blank()).map((key) => [key, item[key]]))
const formatOffset = (seconds) => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
const asOptions = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

function RenderEditor({ title, facts, render, editable, busy, onSave, onRerender }) {
  const [text, setText] = useState(render?.rendered_text || '')
  useEffect(() => { setText(render?.rendered_text || '') }, [render?.rendered_text])
  return <div className={styles.fact}>
    <h4>{title}</h4>
    <p><b>Исходные факты:</b> {facts.filter(Boolean).join(' · ')}</p>
    <label>Текст для обучаемого<textarea value={text} disabled={!editable} onChange={(event) => setText(event.target.value)} /></label>
    <small>Источник: {renderOriginLabels[render?.render_origin] || 'Текст подготовлен'}{render?.fallback_used ? ' · резервный текст' : ''}</small>
    {editable && <div className={styles.actions}>
      <button type="button" disabled={busy || !text.trim() || text === render?.rendered_text} onClick={() => onSave(text)}>Сохранить правку</button>
      <button type="button" disabled={busy} onClick={onRerender}>Перегенерировать</button>
    </div>}
  </div>
}

function InstanceReview({ instance, busy, api, perform, onChange, sessions, trainingSessionId, onSelectSession }) {
  const editable = instance.status === 'DRAFT'
  const action = (path, options, status = '') => perform(async () => {
    const updated = await api(path, options)
    onChange(updated)
  }, status)
  const base = `/api/scenario-instances/${instance.id}`
  const initial = instance.initial_state_snapshot
  return <section className={styles.panel}>
    <h3>Карточка на проверке · {instance.status === 'CONFIRMED' ? 'Подтверждена' : 'Черновик'}</h3>
    <p>{instance.name} · сложность {instance.difficulty}/5</p>
    <p>Объект: {instance.object_snapshot.name} · {instance.object_snapshot.address}</p>
    <p>Классификация: {instance.classifier_snapshot.final_incident_type}</p>
    <p>Занятие: {instance.training_session_id ? 'Выбрано' : 'не выбрано'}</p>
    <h4>Службы</h4><ul>{instance.service_snapshot.map((service) => <li key={service.service_id}>{service.official_name}</li>)}</ul>
    <RenderEditor title="Исходная карточка" facts={[initial.title, initial.description, initial.caller_text]} render={initial.render} editable={editable} busy={busy}
      onSave={(text) => action(`${base}/initial-message`, asOptions('PATCH', { text }))}
      onRerender={() => action(`${base}/rerender-initial-message`, { method: 'POST' }, 'ИИ перегенерирует текст карточки…')} />
    <h4>События</h4><ol>{instance.events.map((event) => <li key={event.id}>T+{formatOffset(event.offset_seconds)} · {event.title}
      {event.event_type === 'RESPONSE_MESSAGE' ? <RenderEditor title="Сообщение группы" facts={[event.title, event.description]} render={event.render} editable={editable} busy={busy}
        onSave={(text) => action(`${base}/events/${event.id}/message`, asOptions('PATCH', { text }))}
        onRerender={() => action(`${base}/events/${event.id}/rerender`, { method: 'POST' }, 'ИИ перегенерирует текст сообщения…')} /> : <p>{event.description}</p>}
    </li>)}</ol>
    {editable && <button type="button" disabled={busy} onClick={() => action(`${base}/confirm`, { method: 'POST' })}>Подтвердить тексты и экземпляр</button>}
    {!instance.training_session_id && <label>Использовать в занятии<select value={trainingSessionId || ''} onChange={(event) => onSelectSession(Number(event.target.value) || null)}><option value="">Выберите занятие</option>{sessions.map((session) => <option key={session.id} value={session.id}>{session.title} · #{session.id}</option>)}</select></label>}
    {!instance.training_session_id && <button type="button" disabled={busy || !trainingSessionId} onClick={() => action(`${base}/attach`, asOptions('POST', { training_session_id: trainingSessionId }))}>Привязать к занятию</button>}
  </section>
}

export default function AdvancedScenarioLibrary({ user, requestJson, embedded = false, startCreate = false, onSaved, onUse, onViewChange }) {
  const api = useCallback((path, options) => requestJson(path, user.username, options), [requestJson, user.username])
  const [filters, setFilters] = useState({ q: '', status: 'READY', difficulty: '', incident_group: '', incident_type: '', object_type_id: '', district: '', administrative_area: '', service_id: '', created_by: '' })
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [catalog, setCatalog] = useState({ rules: [], object_types: [], services: [], objects: [], tags: [], authors: [] })
  const [ruleSearch, setRuleSearch] = useState('')
  const [objectSearch, setObjectSearch] = useState('')
  const [ruleDetail, setRuleDetail] = useState(null)
  const [selected, setSelected] = useState(startCreate ? { status: 'DRAFT' } : null)
  const [draft, setDraft] = useState(blank())
  const [step, setStep] = useState(null)
  const [validation, setValidation] = useState(null)
  const [dirty, setDirty] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [generationStatus, setGenerationStatus] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [generation, setGeneration] = useState(null)
  const [generationInput, setGenerationInput] = useState({ object_id: null, object_query: '', difficulty: 3, seed: 0, variant_mode: 'MANUAL', training_session_id: null })
  const [generationPreview, setGenerationPreview] = useState(null)
  const [generationCandidates, setGenerationCandidates] = useState([])
  const [generatedInstance, setGeneratedInstance] = useState(null)
  const [availableInstances, setAvailableInstances] = useState([])
  const [sessions, setSessions] = useState([])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ limit: '24', offset: String(offset) })
      Object.entries(filters).forEach(([key, value]) => { if (value !== '') params.set(key, value) })
      const [result, instances] = await Promise.all([
        api(`/api/scenario-templates?${params}`), api('/api/scenario-instances'),
      ])
      setItems(result.items)
      setTotal(result.total)
      setAvailableInstances(instances)
    } catch (cause) { setError(cause.message) } finally { setLoading(false) }
  }, [api, filters, offset])

  useEffect(() => { load() }, [load])
  useEffect(() => { api('/api/scenario-templates/catalog').then(setCatalog).catch((cause) => setError(cause.message)) }, [api])
  useEffect(() => { onViewChange?.(Boolean(selected || generation)) }, [generation, onViewChange, selected])
  useEffect(() => () => onViewChange?.(false), [onViewChange])
  useEffect(() => {
    if (!ruleSearch.trim()) return
    const timer = setTimeout(() => api(`/api/scenario-templates/catalog?q=${encodeURIComponent(ruleSearch)}`).then((result) => setCatalog((old) => ({ ...old, rules: result.rules }))).catch((cause) => setError(cause.message)), 250)
    return () => clearTimeout(timer)
  }, [api, ruleSearch])
  useEffect(() => {
    if (!objectSearch.trim()) return
    const timer = setTimeout(() => api(`/api/scenario-templates/catalog?q=${encodeURIComponent(objectSearch)}`).then((result) => setCatalog((old) => ({ ...old, objects: result.objects }))).catch((cause) => setError(cause.message)), 250)
    return () => clearTimeout(timer)
  }, [api, objectSearch])
  useEffect(() => {
    if (!draft.classifier_rule_id) { setRuleDetail(null); return }
    api(`/incident-classifier/rules/${draft.classifier_rule_id}`).then(setRuleDetail).catch((cause) => setError(cause.message))
  }, [api, draft.classifier_rule_id])

  const change = (field, value) => { setDraft((old) => ({ ...old, [field]: value })); setValidation(null); setDirty(true) }
  const changeVariant = (key, raw) => {
    const values = raw.split(',').map((value) => value.trim()).filter(Boolean)
      .map((value) => key === 'floor' && /^\d+$/.test(value) ? Number(value) : value)
    if (JSON.stringify(values) === JSON.stringify(draft.variant_options?.[key] || [])) return
    const next = { ...draft.variant_options }
    if (values.length) next[key] = values
    else delete next[key]
    change('variant_options', next)
  }
  const changeFilter = (field, value) => { setFilters((old) => ({ ...old, [field]: value })); setOffset(0) }
  const perform = async (action, status = '') => {
    setBusy(true); setGenerationStatus(status); setError(''); setNotice('')
    try { await action() } catch (cause) { setError(cause.message) } finally { setBusy(false); setGenerationStatus('') }
  }
  const open = (item) => { setSelected(item); setDraft(toInput(item)); setStep(null); setValidation(null); setDirty(false) }
  const save = () => perform(async () => {
    const path = selected?.id ? `/api/scenario-templates/${selected.id}` : '/api/scenario-templates'
    const saved = await api(path, asOptions(selected?.id ? 'PATCH' : 'POST', draft))
    setSelected(saved); setDraft(toInput(saved)); setValidation(null); setDirty(false); setNotice('Черновик сохранён'); await load()
  })
  const check = () => perform(async () => {
    if (!selected?.id || dirty) { setError('Сначала сохраните черновик'); return }
    const result = await api(`/api/scenario-templates/${selected.id}/validate`)
    setValidation(result); setStep(7)
  })
  const ready = () => perform(async () => {
    const saved = await api(`/api/scenario-templates/${selected.id}/ready`, { method: 'POST' })
    setSelected(saved); setDraft(toInput(saved)); setValidation(null); setDirty(false); setNotice('Сценарий готов к использованию'); await load()
  })
  const duplicate = (item = selected) => perform(async () => {
    const saved = await api(`/api/scenario-templates/${item.id}/duplicate`, { method: 'POST' })
    open(saved); setNotice('Создана копия черновика'); await load()
  })
  const archive = (item = selected) => perform(async () => {
    const saved = await api(`/api/scenario-templates/${item.id}/archive`, { method: 'POST' })
    setSelected(saved); setNotice('Сценарий архивирован'); await load()
  })
  const saveAndUse = () => perform(async () => {
    const path = selected?.id ? `/api/scenario-templates/${selected.id}` : '/api/scenario-templates'
    const saved = await api(path, asOptions(selected?.id ? 'PATCH' : 'POST', draft))
    setSelected(saved); setDraft(toInput(saved)); setDirty(false)
    const result = await api(`/api/scenario-templates/${saved.id}/validate`)
    setValidation(result)
    if (result.errors.length) {
      setStep(7)
      setError('Сценарий сохранён как черновик. Исправьте замечания перед использованием.')
      return
    }
    const ready = await api(`/api/scenario-templates/${saved.id}/ready`, { method: 'POST' })
    setSelected(ready)
    await load()
    onSaved?.(ready)
  })
  const startGeneration = (item) => perform(async () => {
    const seed = Math.floor(Math.random() * 2147483647)
    const input = { object_id: item.object_rule?.specific_object_id || null, object_query: '', difficulty: item.difficulty, seed, variant_mode: 'MANUAL', training_session_id: null }
    const [preview, availableSessions] = await Promise.all([
      api(`/api/scenario-templates/${item.id}/generate-preview`, asOptions('POST', input)),
      api('/api/training/sessions'),
    ])
    setGeneration(item); setGenerationInput(input); setGenerationPreview(preview); setGenerationCandidates(preview.matching_objects)
    setSessions(availableSessions.filter((session) => ['DRAFT', 'READY'].includes(session.state)))
    setGeneratedInstance(null)
  })
  const refreshGenerationPreview = () => perform(async () => {
    const preview = await api(`/api/scenario-templates/${generation.id}/generate-preview`, asOptions('POST', generationInput))
    setGenerationPreview(preview); setGenerationCandidates(preview.matching_objects)
  })
  const createInstance = () => perform(async () => {
    const created = await api(`/api/scenario-templates/${generation.id}/instances`, asOptions('POST', generationInput))
    setGeneratedInstance(created); setGenerationPreview(null); setNotice('Карточка создана'); await load()
  }, 'ИИ формирует карточку…')
  const openInstance = (instance) => perform(async () => {
    const availableSessions = await api('/api/training/sessions')
    setSessions(availableSessions.filter((session) => ['DRAFT', 'READY'].includes(session.state)))
    setGeneration({ id: instance.scenario_template_id, name: instance.template_snapshot.name })
    setGeneratedInstance(instance)
    setGenerationPreview(null)
    setGenerationInput((old) => ({ ...old, training_session_id: instance.training_session_id }))
  })
  const updateList = (field, index, patch) => change(field, draft[field].map((item, position) => position === index ? { ...item, ...patch } : item))
  const removeList = (field, index) => change(field, draft[field].filter((_, position) => position !== index))
  const addList = (field, item) => change(field, [...draft[field], item])
  const editable = !selected || selected.status === 'DRAFT'
  const chosenRule = catalog.rules.find((rule) => rule.id === draft.classifier_rule_id)
  const chosenObject = catalog.objects.find((object) => object.id === draft.object_rule?.specific_object_id)
  const serviceName = (id) => catalog.services.find((service) => service.id === id)?.name || `Служба ${id}`
  const typeName = (id) => catalog.object_types.find((type) => type.id === id)?.name || 'Не выбран'

  return <main className={`${styles.shell} ${embedded ? styles.embedded : ''}`}>
    {!embedded && <header className={styles.header}><div><small>Кабинет преподавателя / методические материалы</small><h1>Библиотека сценариев</h1></div></header>}
    {error && <p className={styles.error} role="alert">{error}</p>}
    {notice && <p className={styles.notice} role="status">{notice}</p>}
    {generationStatus && <p className={`${styles.generationStatus} ${styles.floatingGenerationStatus}`} role="status">{generationStatus}</p>}
    {generation && <div className={styles.content}>
      <div className={styles.topline}><div><h2>Карточка: {generation.name}</h2></div></div>
      {!generatedInstance && <section className={styles.panel}>
        <h3>Параметры генерации</h3>
        <div className={styles.fields}>
          <label>Сложность<select value={generationInput.difficulty} onChange={(event) => { setGenerationInput((old) => ({ ...old, difficulty: Number(event.target.value) })); setGenerationPreview(null) }}>{[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>{value}/5</option>)}</select></label>
          {generation.object_rule?.selection_mode === 'GENERIC' && <><label>Выбор объекта<select value={generationInput.variant_mode} onChange={(event) => { setGenerationInput((old) => ({ ...old, variant_mode: event.target.value, object_id: null })); setGenerationPreview(null) }}><option value="MANUAL">Вручную</option><option value="RANDOM">Случайный</option></select></label>{generationInput.variant_mode === 'MANUAL' && <><label>Поиск объекта<input value={generationInput.object_query} onChange={(event) => { setGenerationInput((old) => ({ ...old, object_query: event.target.value, object_id: null })); setGenerationPreview(null) }} placeholder="Название, адрес или район" /></label><label>Подходящий объект<select value={generationInput.object_id || ''} onChange={(event) => { setGenerationInput((old) => ({ ...old, object_id: Number(event.target.value) || null })); setGenerationPreview(null) }}><option value="">Выберите объект</option>{generationCandidates.map((object) => <option key={object.id} value={object.id}>{object.name} · {object.address}</option>)}</select></label></>}</>}
          <label>Случайный вариант<input type="number" min="0" max="2147483647" value={generationInput.seed} onChange={(event) => { setGenerationInput((old) => ({ ...old, seed: Number(event.target.value) })); setGenerationPreview(null) }} /></label>
          <label>Занятие<select value={generationInput.training_session_id || ''} onChange={(event) => { setGenerationInput((old) => ({ ...old, training_session_id: Number(event.target.value) || null })); setGenerationPreview(null) }}><option value="">Привязать позже</option>{sessions.map((session) => <option key={session.id} value={session.id}>{session.title} · #{session.id}</option>)}</select></label>
        </div>
        {!generationPreview && <button type="button" disabled={busy} onClick={refreshGenerationPreview}>Показать предпросмотр</button>}
        {generationPreview && <div className={styles.preview}><div><h4>Объект</h4><p>{generationPreview.object_snapshot?.name || 'Выберите объект'}</p><p>{generationPreview.object_snapshot?.address}</p><p>Подходящих объектов: {generationPreview.matching_object_count}</p></div><div><h4>Классификация и службы</h4><p>{generationPreview.classifier_snapshot.final_incident_type}</p><ul>{generationPreview.service_snapshot.map((service) => <li key={service.service_id}>{service.official_name}</li>)}</ul><h4>События</h4><ol>{generationPreview.events.map((event, index) => <li key={index}>T+{formatOffset(event.offset_seconds)} · {event.title} — {event.description}</li>)}</ol></div></div>}
        {generationPreview?.object_snapshot && <button type="button" disabled={busy} onClick={createInstance}>Создать карточку</button>}
      </section>}
      {generatedInstance && <InstanceReview instance={generatedInstance} busy={busy} api={api} perform={perform} onChange={(updated) => { setGeneratedInstance(updated); if (updated.status !== generatedInstance.status) load() }} sessions={sessions} trainingSessionId={generationInput.training_session_id} onSelectSession={(id) => setGenerationInput((old) => ({ ...old, training_session_id: id }))} />}
    </div>}
    {!selected && !generation && <div className={styles.content}>
      {availableInstances.some((instance) => instance.status === 'DRAFT') && <section className={styles.panel}><h3>Карточки на проверке</h3><div className={styles.reviewQueue}>{availableInstances.filter((instance) => instance.status === 'DRAFT').map((instance) => <button className={styles.reviewQueueRow} type="button" key={instance.id} onClick={() => openInstance(instance)}><b>{compactInstanceName(instance)}</b><small>{compactObjectName(instance.object_snapshot.name)}</small><span>Тексты ждут подтверждения</span></button>)}</div></section>}
      <div className={styles.topline}><div><h2>Сценарии</h2><p>Создавайте сценарии и подготавливайте их для занятий.</p></div><button type="button" onClick={() => { setSelected({ status: 'DRAFT' }); setDraft(blank()); setStep(null); setValidation(null); setDirty(false) }}>+ Создать сценарий</button></div>
      <div className={styles.filters}>
        <label>Поиск<input value={filters.q} onChange={(event) => changeFilter('q', event.target.value)} placeholder="Название" /></label>
        <label>Статус<select value={filters.status} onChange={(event) => changeFilter('status', event.target.value)}><option value="READY">Готовые</option><option value="DRAFT">Черновики</option><option value="ARCHIVED">Архив</option><option value="ALL">Все</option></select></label>
        <label>Сложность<select value={filters.difficulty} onChange={(event) => changeFilter('difficulty', event.target.value)}><option value="">Любая</option>{[1, 2, 3, 4, 5].map((value) => <option key={value}>{value}</option>)}</select></label>
        <label>Тип объекта<select value={filters.object_type_id} onChange={(event) => changeFilter('object_type_id', event.target.value)}><option value="">Любой</option>{catalog.object_types.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}</select></label>
        <label>Служба<select value={filters.service_id} onChange={(event) => changeFilter('service_id', event.target.value)}><option value="">Любая</option>{catalog.services.map((service) => <option key={service.id} value={service.id}>{service.name}</option>)}</select></label>
        <label>Район<input value={filters.district} onChange={(event) => changeFilter('district', event.target.value)} placeholder="Для конкретного объекта" /></label>
        <label>Округ<input value={filters.administrative_area} onChange={(event) => changeFilter('administrative_area', event.target.value)} placeholder="Для конкретного объекта" /></label>
        <label>Автор<select value={filters.created_by} onChange={(event) => changeFilter('created_by', event.target.value)}><option value="">Любой</option>{catalog.authors.map((author) => <option key={author.id} value={author.id}>{author.name}</option>)}</select></label>
        <label>Группа происшествий<input value={filters.incident_group} onChange={(event) => changeFilter('incident_group', event.target.value)} placeholder="Например, пожар" /></label>
        <label>Тип происшествия<input value={filters.incident_type} onChange={(event) => changeFilter('incident_type', event.target.value)} placeholder="Например, пожар в здании" /></label>
      </div>
      <p className={styles.count}>Найдено: {total}</p>
      {loading ? <p>Загрузка библиотеки…</p> : items.length ? <div className={styles.scenarioCatalog}>
        <div className={styles.scenarioCatalogHead}><span>Сценарий</span><span>Статус</span><span>Тип происшествия</span><span>Сложность</span><span>Объект</span><span>Действия</span></div>
        {items.map((item) => <article className={styles.scenarioCatalogRow} key={item.id}>
          <div><strong>{item.name || 'Без названия'}</strong><small>{item.description || 'Описание не задано'}</small></div>
          <span>{({ DRAFT: 'Черновик', READY: 'Готов', ARCHIVED: 'В архиве' })[item.status]}</span>
          <span>{item.incident_type || 'Не выбран'}</span>
          <span>{difficultyLabels[item.difficulty] || item.difficulty}</span>
          <div><strong>{typeName(item.object_rule?.object_type_id)}</strong><small>{item.object_rule?.selection_mode === 'OBJECT_BOUND' ? item.object_rule.specific_object_name || 'Конкретный объект' : 'Любой подходящий объект'} · {item.services.length} служб · {catalog.authors.find((author) => author.id === item.created_by_user_id)?.name || 'Преподаватель'}</small></div>
          <div className={styles.catalogActions}>{item.status === 'DRAFT' && <button type="button" onClick={() => open(item)}>Редактировать</button>}{item.status === 'READY' && <><button type="button" onClick={() => open(item)}>Просмотреть</button><button type="button" onClick={() => onUse?.(item)} disabled={!onUse}>Использовать</button><button type="button" disabled={busy} onClick={() => duplicate(item)}>Изменить</button>{(user.role === 'ADMIN' || item.created_by_user_id === user.id) && <button type="button" disabled={busy} onClick={() => archive(item)}>Архивировать</button>}</>}{item.status === 'ARCHIVED' && <button type="button" onClick={() => open(item)}>Посмотреть</button>}</div>
        </article>)}
      </div> : <p>По выбранным фильтрам сценариев нет.</p>}
      <div className={styles.actions}><button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 24))}>Назад</button><span>{total ? offset + 1 : 0}–{Math.min(total, offset + 24)} из {total}</span><button type="button" disabled={offset + 24 >= total} onClick={() => setOffset(offset + 24)}>Далее</button></div>
    </div>}
    {selected && !generation && <div className={styles.content}>
      <div className={styles.topline}><div><h2>{selected.id ? draft.name || 'Без названия' : 'Новый сценарий'}</h2><p>{({ DRAFT: 'Черновик', READY: 'Готов к использованию', ARCHIVED: 'В архиве' })[selected.status]}</p></div><div className={styles.actions}>{editable && <button type="button" disabled={busy} onClick={save}>Сохранить черновик</button>}{editable && onSaved && <button type="button" disabled={busy} onClick={saveAndUse}>Сохранить и использовать</button>}{selected.status === 'READY' && <button type="button" disabled={busy} onClick={() => duplicate()}>Изменить</button>}{selected.status === 'READY' && onUse && <button type="button" onClick={() => onUse(selected)}>Использовать</button>}{selected.status === 'READY' && <button type="button" disabled={busy} onClick={() => startGeneration(selected)}>Создать отдельную карточку</button>}{selected.status === 'READY' && (user.role === 'ADMIN' || selected.created_by_user_id === user.id) && <button type="button" disabled={busy} onClick={() => archive()}>Архивировать</button>}</div></div>
      <nav className={styles.steps} aria-label="Разделы сценария"><button type="button" onClick={() => setStep(null)} className={step === null ? styles.current : ''}>Все разделы</button>{steps.map((label, index) => <button type="button" key={label} onClick={() => setStep(index)} className={step === index ? styles.current : ''}>{label}</button>)}</nav>
      <section className={styles.panel}>
        <h3>{step === null ? 'Параметры сценария' : steps[step]}</h3>
        {(step === null || step === 0) && <div className={styles.fields}>{step === null && <h4>Основное</h4>}<label>Название<input disabled={!editable} value={draft.name} onChange={(event) => change('name', event.target.value)} /></label><label>Описание<textarea disabled={!editable} value={draft.description} onChange={(event) => change('description', event.target.value)} /></label><label>Сложность<select disabled={!editable} value={draft.difficulty} onChange={(event) => change('difficulty', Number(event.target.value))}>{[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>{value}/5</option>)}</select></label></div>}
        {(step === null || step === 1) && <div className={styles.fields}>{step === null && <h4>Тип происшествия</h4>}<p>Выберите тип происшествия для карточек.</p><label>Поиск в классификаторе<input value={ruleSearch} onChange={(event) => setRuleSearch(event.target.value)} placeholder="Например, пожар" /></label><label>Правило<select disabled={!editable} value={draft.classifier_rule_id || ''} onChange={(event) => { change('classifier_rule_id', Number(event.target.value) || null); change('services', []) }}><option value="">Выберите правило</option>{catalog.rules.map((rule) => <option key={rule.id} value={rule.id}>{rule.group} / {rule.type}</option>)}</select></label>{ruleDetail && <div className={styles.fact}><b>{ruleDetail.final_incident_type}</b><p>{ruleDetail.incident_group}</p><ul>{ruleDetail.features.map((feature) => <li key={feature.id}>{feature.level}: {feature.name}</li>)}</ul></div>}{chosenRule && <small>Выбрано: {chosenRule.type}</small>}</div>}
        {(step === null || step === 2) && <div className={styles.fields}>{step === null && <h4>Тип объекта</h4>}<p>Для общего правила подходят выбранный тип и его потомки. Перед использованием проверяется наличие подходящих объектов.</p><label>Режим<select disabled={!editable} value={draft.object_rule?.selection_mode || ''} onChange={(event) => change('object_rule', event.target.value ? { selection_mode: event.target.value, object_type_id: draft.object_rule?.object_type_id || catalog.object_types[0]?.id || 0, specific_object_id: null, required_tags: [] } : null)}><option value="">Не выбран</option><option value="GENERIC">Любой подходящий</option><option value="OBJECT_BOUND">Конкретный объект</option></select></label>{draft.object_rule && <><label>Тип объекта<select disabled={!editable} value={draft.object_rule.object_type_id} onChange={(event) => change('object_rule', { ...draft.object_rule, object_type_id: Number(event.target.value), specific_object_id: null })}>{catalog.object_types.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}</select></label><fieldset><legend>Обязательные теги</legend>{catalog.tags.map((tag) => <label key={tag.code} className={styles.check}><input type="checkbox" disabled={!editable} checked={draft.object_rule.required_tags.includes(tag.code)} onChange={(event) => change('object_rule', { ...draft.object_rule, required_tags: event.target.checked ? [...draft.object_rule.required_tags, tag.code] : draft.object_rule.required_tags.filter((value) => value !== tag.code) })} />{tag.name}</label>)}</fieldset>{draft.object_rule.selection_mode === 'OBJECT_BOUND' && <><label>Поиск объекта<input value={objectSearch} onChange={(event) => setObjectSearch(event.target.value)} placeholder="Название школы, адрес…" /></label><label>Объект<select disabled={!editable} value={draft.object_rule.specific_object_id || ''} onChange={(event) => change('object_rule', { ...draft.object_rule, specific_object_id: Number(event.target.value) || null })}><option value="">Выберите объект</option>{catalog.objects.map((object) => <option key={object.id} value={object.id}>{object.name} · {object.address}</option>)}</select></label></>}{chosenObject && <p>{chosenObject.address} · {chosenObject.district}</p>}</>}</div>}
        {(step === null || step === 3) && <div className={styles.fields}>{step === null && <h4>Службы</h4>}<p>Автоматические рекомендации берутся из выбранного правила. Дополнительные службы выбираются из каталога.</p>{ruleDetail?.services.length ? <fieldset><legend>По классификатору</legend>{ruleDetail.services.map((service) => <label className={styles.check} key={service.id}><input type="checkbox" disabled={!editable} checked={draft.services.some((item) => item.service_id === service.id)} onChange={(event) => change('services', event.target.checked ? [...draft.services, { service_id: service.id, source: 'CLASSIFIER' }] : draft.services.filter((item) => item.service_id !== service.id))} />{service.official_name}</label>)}</fieldset> : <p>Для правила нет подтверждённых служб.</p>}<label>Дополнительная служба<select disabled={!editable} value="" onChange={(event) => { const id = Number(event.target.value); if (id && !draft.services.some((item) => item.service_id === id)) addList('services', { service_id: id, source: 'MANUAL' }) }}><option value="">Добавить из каталога…</option>{catalog.services.filter((service) => !draft.services.some((item) => item.service_id === service.id)).map((service) => <option key={service.id} value={service.id}>{service.name}</option>)}</select></label><ul>{draft.services.map((service, index) => <li key={service.service_id}>{serviceName(service.service_id)}{editable && <button type="button" onClick={() => removeList('services', index)}>Удалить</button>}</li>)}</ul></div>}
        {(step === null || step === 4) && <div className={styles.fields}><h4>Вариативные параметры</h4><p>Укажите допустимые значения через запятую. В тексте можно использовать {'{floor}'}, {'{room}'}, {'{observation}'} и {'{casualties}'}.</p>{Object.entries(variantLabels).map(([key, label]) => <label key={key}>{label}<input key={`${selected.id || 'new'}:${key}`} disabled={!editable} defaultValue={(draft.variant_options?.[key] || []).join(', ')} onBlur={(event) => changeVariant(key, event.target.value)} placeholder="Значения через запятую" /></label>)}<h4>Исходная карточка</h4><label>Заголовок карточки<input disabled={!editable} value={draft.initial_title} onChange={(event) => change('initial_title', event.target.value)} /></label><label>Описание происшествия<textarea disabled={!editable} value={draft.initial_description} onChange={(event) => change('initial_description', event.target.value)} /></label><label>Слова заявителя<textarea disabled={!editable} value={draft.initial_caller_text} onChange={(event) => change('initial_caller_text', event.target.value)} /></label><div className={styles.fact}><b>Видит обучаемый</b><h4>{draft.initial_title || 'Заголовок'}</h4><p>{draft.initial_description || 'Описание'}</p><blockquote>{draft.initial_caller_text}</blockquote></div></div>}
        {(step === null || step === 5) && <div className={styles.fields}>{step === null && <h4>Работа служб</h4>}<p>События выполняются в указанном порядке по учебному времени. Начальное сообщение должно быть одно, в T+0.</p>{draft.events.map((event, index) => <div className={styles.entry} key={index}><label>Время от начала, секунд<input type="number" min="0" disabled={!editable} value={event.offset_seconds} onChange={(e) => updateList('events', index, { offset_seconds: Number(e.target.value) })} /></label><label>Тип<select disabled={!editable} value={event.event_type} onChange={(e) => updateList('events', index, { event_type: e.target.value, target_service_id: e.target.value === 'RESPONSE_MESSAGE' ? event.target_service_id ?? null : null })}>{Object.entries(eventTypes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>Название<input disabled={!editable} value={event.title} onChange={(e) => updateList('events', index, { title: e.target.value })} /></label><label>Описание<textarea disabled={!editable} value={event.description} onChange={(e) => updateList('events', index, { description: e.target.value })} /></label>{event.event_type === 'RESPONSE_MESSAGE' && <label>От кого поступает сообщение<select disabled={!editable} value={event.target_service_id || ''} required onChange={(e) => updateList('events', index, { target_service_id: Number(e.target.value) || null })}><option value="">Выберите службу</option>{draft.services.map((service) => <option key={service.service_id} value={service.service_id}>{serviceName(service.service_id)}</option>)}</select>{!event.target_service_id && <small>Для сообщения группы необходимо выбрать службу.</small>}</label>}{event.event_type === 'RESPONSE_MESSAGE' && <label>Состояние группы<select disabled={!editable} value={event.target_response_state || ''} onChange={(e) => updateList('events', index, { target_response_state: e.target.value || null })}><option value="">Без смены состояния</option>{Object.entries(responseStates).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>}{editable && <div className={styles.actions}><button type="button" disabled={index === 0} onClick={() => { const next = [...draft.events]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; change('events', next) }}>↑</button><button type="button" disabled={index === draft.events.length - 1} onClick={() => { const next = [...draft.events]; [next[index + 1], next[index]] = [next[index], next[index + 1]]; change('events', next) }}>↓</button><button type="button" onClick={() => removeList('events', index)}>Удалить</button></div>}</div>)}{editable && <button type="button" onClick={() => addList('events', { offset_seconds: draft.events.length ? draft.events.at(-1).offset_seconds + 60 : 0, event_type: draft.events.length ? 'ADDITIONAL_INFO' : 'INITIAL_REPORT', title: '', description: '', source_type: 'SYSTEM', target_service_id: null })}>+ Добавить событие</button>}</div>}
        {(step === null || step === 6) && <div className={styles.fields}>{step === null && <h4>Оценивание</h4>}<h4>Ожидаемые действия</h4>{draft.expected_actions.map((action, index) => <div className={styles.entry} key={index}><label>Тип действия<input disabled={!editable} value={action.expected_action_type} onChange={(e) => updateList('expected_actions', index, { expected_action_type: e.target.value })} /></label><label>Целевой статус<input disabled={!editable} value={action.target_status || ''} onChange={(e) => updateList('expected_actions', index, { target_status: e.target.value || null })} /></label><label>Служба<select disabled={!editable} value={action.expected_service_id || ''} onChange={(e) => updateList('expected_actions', index, { expected_service_id: Number(e.target.value) || null })}><option value="">Не требуется</option>{catalog.services.map((service) => <option key={service.id} value={service.id}>{service.name}</option>)}</select></label><label>Срок, секунд<input type="number" min="0" disabled={!editable} value={action.deadline_seconds ?? ''} onChange={(e) => updateList('expected_actions', index, { deadline_seconds: e.target.value === '' ? null : Number(e.target.value) })} /></label><label>Описание<textarea disabled={!editable} value={action.description} onChange={(e) => updateList('expected_actions', index, { description: e.target.value })} /></label><label className={styles.check}><input type="checkbox" disabled={!editable} checked={action.is_critical} onChange={(e) => updateList('expected_actions', index, { is_critical: e.target.checked })} />Критично</label>{editable && <button type="button" onClick={() => removeList('expected_actions', index)}>Удалить действие</button>}</div>)}{editable && <button type="button" onClick={() => addList('expected_actions', { expected_action_type: '', target_status: null, expected_service_id: null, deadline_seconds: null, is_critical: false, description: '' })}>+ Добавить действие</button>}<h4>Критерии оценки</h4>{draft.criteria.map((criterion, index) => <div className={styles.entry} key={index}><label>Название<input disabled={!editable} value={criterion.name} onChange={(e) => updateList('criteria', index, { name: e.target.value })} /></label><label>Описание<textarea disabled={!editable} value={criterion.description} onChange={(e) => updateList('criteria', index, { description: e.target.value })} /></label><label>Вес<input type="number" min="0" disabled={!editable} value={criterion.weight ?? ''} onChange={(e) => updateList('criteria', index, { weight: e.target.value === '' ? null : Number(e.target.value) })} /></label><label className={styles.check}><input type="checkbox" disabled={!editable} checked={criterion.is_critical} onChange={(e) => updateList('criteria', index, { is_critical: e.target.checked })} />Критично</label>{editable && <button type="button" onClick={() => removeList('criteria', index)}>Удалить критерий</button>}</div>)}{editable && <button type="button" onClick={() => addList('criteria', { name: '', description: '', weight: null, is_critical: false })}>+ Добавить критерий</button>}</div>}
        {(step === null || step === 7) && <div className={styles.preview}><div><h4>Видит обучаемый</h4><b>{draft.initial_title}</b><p>{draft.initial_description}</p><blockquote>{draft.initial_caller_text}</blockquote></div><div><h4>Видит преподаватель</h4><p><b>{draft.name}</b> · сложность {draft.difficulty}/5</p><p>Тип происшествия: {ruleDetail?.final_incident_type || 'Не выбран'}</p><p>Объект: {typeName(draft.object_rule?.object_type_id)} · {draft.object_rule?.selection_mode === 'OBJECT_BOUND' ? 'Конкретный объект' : 'Любой подходящий объект'}</p><p>Теги: {draft.object_rule?.required_tags.join(', ') || '—'}</p><p>Службы: {draft.services.map((service) => serviceName(service.service_id)).join(', ') || '—'}</p><h5>События</h5><ol>{draft.events.map((event, index) => <li key={index}>T+{formatOffset(event.offset_seconds)} · {eventTypes[event.event_type]}{event.event_type === 'RESPONSE_MESSAGE' ? ` · ${serviceName(event.target_service_id) || 'служба не выбрана'}` : ''} · {event.title} — {event.description}</li>)}</ol><h5>Ожидаемые действия</h5><ul>{draft.expected_actions.map((action, index) => <li key={index}>{action.expected_action_type}: {action.description}</li>)}</ul><h5>Критерии</h5><ul>{draft.criteria.map((criterion, index) => <li key={index}>{criterion.name}: {criterion.description}</li>)}</ul></div>{selected.id && <div className={styles.validation}><button type="button" disabled={busy} onClick={check}>Проверить сценарий</button>{dirty && <p>Сохраните изменения перед проверкой.</p>}{validation && <><p>Подходящих объектов: {validation.matching_object_count}</p>{validation.errors.length ? <ul>{validation.errors.map((issue) => <li key={issue}>{issue}</li>)}</ul> : <p>Ошибок не найдено.</p>}</>}{selected.status === 'DRAFT' && !dirty && validation?.errors.length === 0 && <button type="button" disabled={busy} onClick={ready}>Перевести в READY</button>}</div>}</div>}
        {step !== null && <div className={styles.actions}><button type="button" disabled={step === 0} onClick={() => setStep(step - 1)}>← Назад</button><button type="button" onClick={() => setStep(null)}>Показать все разделы</button><button type="button" disabled={step === steps.length - 1} onClick={() => setStep(step + 1)}>Далее →</button></div>}
      </section>
    </div>}
  </main>
}
