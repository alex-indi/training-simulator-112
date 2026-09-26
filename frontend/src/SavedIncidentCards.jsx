/* eslint-disable react/prop-types */
import { useCallback, useEffect, useState } from 'react'
import styles from './ScenarioLibrary.module.css'

const json = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
const factNames = { floor: 'Этаж', room: 'Место', observation: 'Задымление', casualties: 'Пострадавшие' }

export default function SavedIncidentCards({ user, requestJson, sessionId, groupId, onCompleted, picker = false }) {
  const api = useCallback((path, options) => requestJson(path, user.username, options), [requestJson, user.username])
  const [cards, setCards] = useState([])
  const [selected, setSelected] = useState([])
  const [openedId, setOpenedId] = useState(null)
  const [editingId, setEditingId] = useState(null)
  const [editingFactsId, setEditingFactsId] = useState(null)
  const [facts, setFacts] = useState({})
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const reload = useCallback(async () => setCards(await api('/api/incident-cards')), [api])
  useEffect(() => { reload().catch((cause) => setError(cause.message)) }, [reload])
  const perform = async (action) => {
    setBusy(true); setError(''); setNotice('')
    try { await action() } catch (cause) { setError(cause.message) } finally { setBusy(false) }
  }
  const saveText = (card) => perform(async () => {
    await api(`/api/incident-cards/${card.id}/text`, json('PATCH', { text }))
    await reload(); setEditingId(null); setNotice('Текст сохранён')
  })
  const saveFacts = (card) => perform(async () => {
    await api(`/api/incident-cards/${card.id}/facts`, json('PATCH', { facts }))
    await reload(); setEditingFactsId(null); setNotice('Условия и текст карточки обновлены')
  })
  const remove = (card) => {
    if (!window.confirm(`Удалить карточку «${card.name}»?`)) return
    perform(async () => { await api(`/api/incident-cards/${card.id}`, { method: 'DELETE' }); await reload() })
  }
  const add = () => perform(async () => {
    for (const id of selected) await api(`/api/incident-cards/${id}/add-to-group`, json('POST', { session_id: sessionId, group_id: groupId }))
    setNotice(`Добавлено ${selected.length} карточек`); setSelected([]); onCompleted?.()
  })
  return <main className={styles.shell}><div className={styles.content}>
    <div className={styles.topline}><div><h2>Карточки происшествий</h2><p>Сохранённые карточки можно использовать в разных занятиях.</p></div></div>
    {error && <p className={styles.error} role="alert">{error}</p>}
    {notice && <p className={styles.notice} role="status">{notice}</p>}
    <div className={styles.cards}>{cards.map((card) => <article className={styles.card} key={card.id}>
      {picker && <label><input type="checkbox" checked={selected.includes(card.id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, card.id] : current.filter((id) => id !== card.id))} /> Выбрать</label>}
      <h3>{card.name}</h3><p>{card.classifier_snapshot.final_incident_type}</p><p><b>Объект:</b> {card.object_snapshot.name}</p><p><b>Адрес:</b> {card.object_snapshot.address}</p>
      <button type="button" onClick={() => setOpenedId(openedId === card.id ? null : card.id)}>{openedId === card.id ? 'Свернуть' : 'Открыть'}</button>
      {openedId === card.id && <><p><b>Условия:</b> {Object.entries(card.initial_state_snapshot.variant_facts || {}).map(([key, value]) => `${factNames[key] || key}: ${value}`).join(' · ') || 'Без дополнительных условий'}</p><p>{card.initial_state_snapshot.render?.rendered_text}</p><h4>Службы по классификатору</h4><ul>{card.service_snapshot.map((service) => <li key={service.service_id}>{service.official_name}</li>)}</ul></>}
      {editingId === card.id && <div><label>Текст карточки<textarea value={text} onChange={(event) => setText(event.target.value)} /></label><button type="button" disabled={busy || !text.trim()} onClick={() => saveText(card)}>Сохранить текст</button><button type="button" onClick={() => setEditingId(null)}>Отмена</button></div>}
      {editingFactsId === card.id && <div>{Object.entries(card.template_snapshot.variant_options || {}).map(([key, values]) => <label key={key}>{factNames[key] || key}<select value={facts[key] ?? ''} onChange={(event) => setFacts((current) => ({ ...current, [key]: key === 'floor' ? Number(event.target.value) : event.target.value }))}>{values.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>)}<button type="button" disabled={busy} onClick={() => saveFacts(card)}>Сохранить условия</button><button type="button" onClick={() => setEditingFactsId(null)}>Отмена</button></div>}
      {!picker && (user.role === 'ADMIN' || card.created_by_user_id === user.id) && <div className={styles.actions}><button type="button" onClick={() => { setEditingId(card.id); setText(card.initial_state_snapshot.render?.rendered_text || '') }}>Редактировать текст</button>{!!Object.keys(card.template_snapshot.variant_options || {}).length && <button type="button" onClick={() => { setEditingFactsId(card.id); setFacts(card.initial_state_snapshot.variant_facts || {}) }}>Изменить условия</button>}<button type="button" disabled={busy} onClick={() => remove(card)}>Удалить</button></div>}
    </article>)}</div>
    {!cards.length && <p>Сохранённых карточек пока нет.</p>}
    {picker && <button type="button" disabled={busy || !selected.length} onClick={add}>Добавить выбранные в занятие</button>}
  </div></main>
}
