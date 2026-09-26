/* eslint-disable react/prop-types */
import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import styles from './ScenarioLibrary.module.css'

const json = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
const factNames = { floor: 'Этаж', room: 'Место', observation: 'Задымление', casualties: 'Пострадавшие' }
const searchable = (value) => String(value || '').toLocaleLowerCase('ru').replaceAll('ё', 'е')

export default function SavedIncidentCards({ user, requestJson, sessionId, groupId, onCompleted, picker = false }) {
  const api = useCallback((path, options) => requestJson(path, user.username, options), [requestJson, user.username])
  const [cards, setCards] = useState([])
  const [search, setSearch] = useState('')
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

  const openedCard = cards.find((card) => card.id === openedId)
  const canEditOpened = openedCard && (user.role === 'ADMIN' || openedCard.created_by_user_id === user.id)
  const terms = searchable(search).trim().split(/\s+/).filter(Boolean)
  const visibleCards = cards.filter((card) => {
    const content = searchable([
      card.name,
      card.classifier_snapshot?.final_incident_type,
      card.object_snapshot?.name,
      card.object_snapshot?.address,
      card.initial_state_snapshot?.render?.rendered_text,
    ].join(' '))
    return terms.every((term) => content.includes(term))
  })

  useEffect(() => {
    if (!openedId) return undefined
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setOpenedId(null)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [openedId])

  const perform = async (action) => {
    setBusy(true); setError(''); setNotice('')
    try { await action() } catch (cause) { setError(cause.message) } finally { setBusy(false) }
  }
  const toggleSelected = (id) => setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])
  const openCard = (card) => {
    setOpenedId(card.id)
    setEditingId(null)
    setEditingFactsId(null)
    setError('')
    setNotice('')
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
    perform(async () => {
      await api(`/api/incident-cards/${card.id}`, { method: 'DELETE' })
      await reload()
      setOpenedId(null)
      setSelected((current) => current.filter((id) => id !== card.id))
      setNotice('Карточка удалена')
    })
  }
  const add = () => perform(async () => {
    for (const id of selected) await api(`/api/incident-cards/${id}/add-to-group`, json('POST', { session_id: sessionId, group_id: groupId }))
    setNotice(`Добавлено ${selected.length} карточек`); setSelected([]); onCompleted?.()
  })

  return <main className={styles.shell}><div className={styles.content}>
    <div className={styles.savedLibraryToolbar}>
      <div><h2>Карточки происшествий</h2><p>Сохранённые карточки можно использовать в разных занятиях.</p></div>
      <div className={styles.savedLibraryControls}>
        <label className={styles.savedSearch}>Поиск карточки
          <span><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Название, объект, тип или адрес" />{search && <button type="button" onClick={() => setSearch('')} aria-label="Очистить поиск">×</button>}</span>
        </label>
        {picker && <button type="button" className={styles.savedAddButton} disabled={busy || !selected.length} onClick={add}>Добавить выбранные ({selected.length})</button>}
      </div>
      <small>Показано {visibleCards.length} из {cards.length}</small>
    </div>
    {!openedCard && error && <p className={styles.error} role="alert">{error}</p>}
    {!openedCard && notice && <p className={styles.notice} role="status">{notice}</p>}
    <div className={styles.savedCardGrid}>{visibleCards.map((card) => {
      const isSelected = selected.includes(card.id)
      const summary = <><strong>{card.name}</strong><small>{card.classifier_snapshot.final_incident_type}</small></>
      return <article className={`${styles.savedCard} ${isSelected ? styles.savedCardSelected : ''}`} key={card.id}>
        {picker ? <label className={styles.savedCardMain}>
          <input type="checkbox" checked={isSelected} onChange={() => toggleSelected(card.id)} aria-label={`Выбрать карточку: ${card.name}`} />
          <span className={styles.savedCardSummary}>{summary}</span>
        </label> : <div className={styles.savedCardMain}><span className={styles.savedCardSummary}>{summary}</span></div>}
        <button type="button" className={styles.savedPreviewButton} onClick={() => openCard(card)}>{user.role === 'ADMIN' || card.created_by_user_id === user.id ? 'Предпросмотр и редактирование' : 'Предпросмотр карточки'}</button>
      </article>
    })}</div>
    {!cards.length && <p>Сохранённых карточек пока нет.</p>}
    {!!cards.length && !visibleCards.length && <p>По запросу ничего не найдено.</p>}
  </div>
  {openedCard && createPortal(<div className={styles.savedPreviewOverlay} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpenedId(null) }}>
    <section className={styles.savedPreviewDialog} role="dialog" aria-modal="true" aria-labelledby={`saved-card-${openedCard.id}`}>
      <header className={styles.savedPreviewHeader}><h2 id={`saved-card-${openedCard.id}`}>{openedCard.name}</h2><button type="button" autoFocus onClick={() => setOpenedId(null)}>Закрыть</button></header>
      {error && <p className={styles.error} role="alert">{error}</p>}
      {notice && <p className={styles.notice} role="status">{notice}</p>}
      <div className={styles.savedPreviewBody}>
        <p><b>Тип:</b> {openedCard.classifier_snapshot.final_incident_type}</p>
        <p><b>Объект:</b> {openedCard.object_snapshot.name}</p>
        <p><b>Адрес:</b> {openedCard.object_snapshot.address}</p>
        <p><b>Условия:</b> {Object.entries(openedCard.initial_state_snapshot.variant_facts || {}).map(([key, value]) => `${factNames[key] || key}: ${value}`).join(' · ') || 'Без дополнительных условий'}</p>
        {editingFactsId === openedCard.id && <div className={styles.savedEditFacts}>{Object.entries(openedCard.template_snapshot.variant_options || {}).map(([key, values]) => <label key={key}>{factNames[key] || key}<select value={facts[key] ?? ''} onChange={(event) => setFacts((current) => ({ ...current, [key]: key === 'floor' ? Number(event.target.value) : event.target.value }))}>{values.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>)}<div className={styles.savedEditActions}><button type="button" disabled={busy} onClick={() => saveFacts(openedCard)}>Сохранить условия</button><button type="button" onClick={() => setEditingFactsId(null)}>Отмена</button></div></div>}
        <div className={styles.savedCardText}><b>Текст карточки</b>{editingId === openedCard.id ? <><textarea value={text} onChange={(event) => setText(event.target.value)} /><div className={styles.savedEditActions}><button type="button" disabled={busy || !text.trim()} onClick={() => saveText(openedCard)}>Сохранить текст</button><button type="button" onClick={() => setEditingId(null)}>Отмена</button></div></> : <p>{openedCard.initial_state_snapshot.render?.rendered_text}</p>}</div>
        <div><b>Службы по классификатору</b><ul>{openedCard.service_snapshot.map((service) => <li key={service.service_id}>{service.official_name}</li>)}</ul></div>
        {canEditOpened && <div className={styles.savedEditActions}>
          <button type="button" onClick={() => { setEditingId(openedCard.id); setEditingFactsId(null); setText(openedCard.initial_state_snapshot.render?.rendered_text || '') }}>Редактировать текст</button>
          {!!Object.keys(openedCard.template_snapshot.variant_options || {}).length && <button type="button" onClick={() => { setEditingFactsId(openedCard.id); setEditingId(null); setFacts(openedCard.initial_state_snapshot.variant_facts || {}) }}>Изменить условия</button>}
          {!picker && <button type="button" disabled={busy} onClick={() => remove(openedCard)}>Удалить</button>}
        </div>}
      </div>
    </section>
  </div>, document.body)}
  </main>
}
