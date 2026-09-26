/* eslint-disable react/prop-types */
import { useCallback, useEffect, useState } from 'react'
import styles from './ScenarioLibrary.module.css'
import { difficultyLabels } from './uiLabels.js'

const choices = {
  floor: { label: 'Этаж', values: [1, 2, 3, 4] },
  room: { label: 'Место', values: ['кабинет', 'коридор', 'подсобное помещение'] },
  observation: { label: 'Задымление', values: ['нет', 'слабое', 'сильное'] },
  casualties: { label: 'Пострадавшие', values: ['нет', 'неизвестно', 'есть'] },
}
const empty = () => ({ name: '', classifier_rule_id: '', object_type_id: '', difficulty: 3, variant_options: {} })
const json = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export default function IncidentTemplates({ user, requestJson, onUse, onSaved, onViewChange, startCreate = false }) {
  const api = useCallback((path, options) => requestJson(path, user.username, options), [requestJson, user.username])
  const [items, setItems] = useState([])
  const [catalog, setCatalog] = useState({ rules: [], object_types: [] })
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState(startCreate ? {} : null)
  const [draft, setDraft] = useState(empty())
  const [services, setServices] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const reload = useCallback(async () => setItems(await api('/api/scenario-templates/simple')), [api])
  useEffect(() => { reload().catch((cause) => setError(cause.message)) }, [reload])
  useEffect(() => { onViewChange?.(Boolean(editing)) }, [editing, onViewChange])
  useEffect(() => () => onViewChange?.(false), [onViewChange])
  useEffect(() => { api(`/api/scenario-templates/catalog?q=${encodeURIComponent(query)}`).then(setCatalog).catch((cause) => setError(cause.message)) }, [api, query])
  useEffect(() => {
    if (!draft.classifier_rule_id) { setServices([]); return }
    api(`/incident-classifier/rules/${draft.classifier_rule_id}`).then((rule) => setServices(rule.services)).catch((cause) => setError(cause.message))
  }, [api, draft.classifier_rule_id])

  const open = (item) => {
    setEditing(item)
    setDraft({ name: item.name, classifier_rule_id: item.classifier_rule_id, object_type_id: item.object_rule?.object_type_id || '', difficulty: item.difficulty, variant_options: item.variant_options || {} })
    setError(''); setNotice('')
  }
  const create = () => { setEditing({}); setDraft(empty()); setError(''); setNotice('') }
  const toggle = (key, value) => {
    setDraft((current) => {
      const selected = current.variant_options[key] || []
      const values = selected.includes(value) ? selected.filter((item) => item !== value) : [...selected, value]
      const variant_options = { ...current.variant_options }
      if (values.length) variant_options[key] = values
      else delete variant_options[key]
      return { ...current, variant_options }
    })
  }
  const save = async () => {
    setBusy(true); setError('')
    try {
      const payload = { ...draft, classifier_rule_id: Number(draft.classifier_rule_id), object_type_id: Number(draft.object_type_id) }
      const saved = await api(editing.id ? `/api/scenario-templates/simple/${editing.id}` : '/api/scenario-templates/simple', json(editing.id ? 'PATCH' : 'POST', payload))
      await reload()
      setEditing(null)
      setNotice('Шаблон сохранён и доступен для формирования карточек')
      onSaved?.(saved)
    } catch (cause) { setError(cause.message) } finally { setBusy(false) }
  }
  const remove = async (item) => {
    if (!window.confirm(`Удалить шаблон «${item.name}»?`)) return
    setBusy(true); setError('')
    try { await api(`/api/scenario-templates/${item.id}`, { method: 'DELETE' }); await reload() } catch (cause) { setError(cause.message) } finally { setBusy(false) }
  }
  const typeName = (id) => catalog.object_types.find((item) => item.id === id)?.name || 'Тип объекта'
  const canEdit = !editing?.id || user.role === 'ADMIN' || editing.created_by_user_id === user.id

  return <main className={styles.shell}>
    {error && <p className={styles.error} role="alert">{error}</p>}
    {notice && <p className={styles.notice} role="status">{notice}</p>}
    <div className={styles.content}>
      {editing ? <section className={styles.panel}>
        <div className={styles.topline}><h2>{editing.id ? 'Редактировать шаблон' : 'Создать шаблон'}</h2></div>
        <label>Название<input value={draft.name} disabled={!canEdit} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} /></label>
        <label>Поиск типа происшествия<input value={query} disabled={!canEdit} onChange={(event) => setQuery(event.target.value)} placeholder="Например, пожар" /></label>
        <label>Тип происшествия<select value={draft.classifier_rule_id} disabled={!canEdit} onChange={(event) => setDraft((current) => ({ ...current, classifier_rule_id: event.target.value }))}><option value="">Выберите тип</option>{catalog.rules.map((rule) => <option key={rule.id} value={rule.id}>{rule.group} · {rule.type}</option>)}{draft.classifier_rule_id && !catalog.rules.some((rule) => rule.id === Number(draft.classifier_rule_id)) && <option value={draft.classifier_rule_id}>Выбранный тип #{draft.classifier_rule_id}</option>}</select></label>
        <label>Тип объекта<select value={draft.object_type_id} disabled={!canEdit} onChange={(event) => setDraft((current) => ({ ...current, object_type_id: event.target.value }))}><option value="">Выберите тип</option>{catalog.object_types.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}</select></label>
        <label>Сложность<select value={draft.difficulty} disabled={!canEdit} onChange={(event) => setDraft((current) => ({ ...current, difficulty: Number(event.target.value) }))}>{[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>{difficultyLabels[value]}</option>)}</select></label>
        <h3>Варианты условий</h3><p>Отметьте значения, которые могут встретиться в карточках.</p>
        {Object.entries(choices).map(([key, item]) => <fieldset key={key} disabled={!canEdit}><legend>{item.label}</legend>{item.values.map((value) => <label key={value}><input type="checkbox" checked={(draft.variant_options[key] || []).includes(value)} onChange={() => toggle(key, value)} /> {value}</label>)}</fieldset>)}
        <h3>Службы по классификатору</h3>{services.length ? <ul>{services.map((service) => <li key={service.id}>{service.official_name}</li>)}</ul> : <p>{draft.classifier_rule_id ? 'Для этого типа службы не указаны.' : 'Выберите тип происшествия.'}</p>}
        {canEdit && <div className={styles.actions}><button type="button" disabled={busy || !draft.name.trim() || !draft.classifier_rule_id || !draft.object_type_id} onClick={save}>Сохранить</button></div>}
      </section> : <>
        <div className={styles.topline}><div><h2>Шаблоны инцидентов</h2><p>Создавайте правила и сразу формируйте карточки происшествий.</p></div><button type="button" onClick={create}>+ Создать шаблон</button></div>
        <div className={styles.templateList}>{items.map((item) => <article className={styles.templateListRow} key={item.id}><div><h3>{item.name}</h3><small>{item.incident_type || 'Укажите тип происшествия'}</small></div><span>{typeName(item.object_rule?.object_type_id)}</span><span>{difficultyLabels[item.difficulty]}</span><div className={styles.catalogActions}><button type="button" onClick={() => open(item)}>Открыть</button>{(user.role === 'ADMIN' || item.created_by_user_id === user.id) && <button type="button" onClick={() => open(item)}>Редактировать</button>}{onUse && <button type="button" disabled={!item.usable} onClick={() => onUse(item)}>Создать карточки</button>}{(user.role === 'ADMIN' || item.created_by_user_id === user.id) && <button type="button" disabled={busy} onClick={() => remove(item)}>Удалить</button>}</div></article>)}</div>
        {!items.length && <p>Шаблонов пока нет.</p>}
      </>}
    </div>
  </main>
}
